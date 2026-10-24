# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline runtime bounds/ownership tests; no manufacturer image is bundled."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hd_platinum.cli import main
from hd_platinum.firmware import FirmwareImage
from hd_platinum import firmware_runtime as runtime


def _record(address=0, data=b"", kind=0):
    raw = bytes((len(data),)) + address.to_bytes(2, "big") + bytes((kind,)) + data
    return b":" + (raw + bytes((-sum(raw) & 255,))).hex().encode() + b"\n"


FICTIONAL_HEX = _record(data=b"\x02\x01\x00") + _record(0x100, b"\x22") + _record(kind=1)


class FakeConsole:
    """Model console contract only; never presented as CPU execution evidence."""

    instances = []
    stop_at_peripheral = False
    wrong_output = False
    interrupt = False

    def __init__(self, simulator, directory, *, deadline, output_limit):
        self.__class__.instances.append(self)
        self.pc = 0
        self.instructions = 0
        self.memory = {"simif_on": 0}
        self.input_bytes = bytearray()
        self.transcript = []
        self.output_bytes = 0
        self.closed = False
        self.proc = self
        self.step_requests = []

    def poll(self):
        return 0 if self.closed else None

    def close(self):
        self.closed = True

    def command(self, command):
        self.transcript.append({"command": command, "output": ""})
        if command.startswith("set memory "):
            parts = command.split()
            space, start = parts[2], int(parts[3], 0)
            for index, value in enumerate(parts[4:]):
                self.memory[f"{space}[{start + index}]"] = int(value, 0)
        elif command.startswith("pc "):
            self.pc = int(command.split()[1], 0)
        elif command.startswith("step "):
            budget = int(command.split()[1])
            self.step_requests.append(budget)
            cost = 1153 if self.pc == 0 else 100
            if self.interrupt:
                raise KeyboardInterrupt()
            if budget < cost or self.stop_at_peripheral:
                self.instructions += min(budget, cost)
                self.pc = 0xB15E
                return ""
            self.instructions += cost
            if self.pc == 0:
                self.pc = 0x11A9
            else:
                if self.pc == 0xA457:
                    value = self.memory["iram[7]"]
                    self.memory[f"xram[{0x5F7 + len(self.input_bytes)}]"] = value
                    self.input_bytes.append(value)
                    self.memory["xram[14]"] = self.memory["xram[21]"] = len(self.input_bytes)
                elif self.pc == 0x0400:
                    output = b"bad" if self.wrong_output else b"\x1bS\x01$ack\n\r\x1bE"
                    self.memory["xram[19]"] = 0
                    self.memory["xram[20]"] = len(output)
                    self.memory["xram[21]"] = 0
                    self.memory["xram[0xa88]"] = 1
                    self.memory["xram[15]"] = 0x31
                    for i, value in enumerate(output):
                        self.memory[f"xram[{25 + i}]"] = value
                self.pc = 0xFFF0
            self.memory["sfr[0x81]"] = 0x3E
        return ""

    def state(self):
        return {"pc": self.pc, "instructions": self.instructions}

    def value(self, expression):
        if expression in self.memory:
            return self.memory[expression]
        if "[" in expression:
            space, value = expression[:-1].split("[")
            return self.memory.get(f"{space}[{int(value, 0)}]", 0)
        return 0


class FirmwareRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.image = FirmwareImage.parse(FICTIONAL_HEX)
        self.executable = Path(sys.executable).resolve()
        FakeConsole.instances = []
        FakeConsole.stop_at_peripheral = FakeConsole.wrong_output = FakeConsole.interrupt = False

    def run_fake(self, name="probe", **kwargs):
        # The production hash guard is separately tested. A fictional digest and
        # fake console permit contract tests without redistributing the image.
        with patch.object(runtime, "GATEWAY_CODE_SHA256", hashlib.sha256(self.image.code).hexdigest()), \
                patch.object(runtime, "_Console", FakeConsole):
            return runtime.run_keepalive_probe(self.image, simulator=self.executable,
                                               output_dir=self.directory / name, **kwargs)

    def test_unknown_or_inconsistent_image_refused_before_process_or_files(self):
        with patch.object(runtime, "_Console") as console:
            with self.assertRaisesRegex(ValueError, "verified gateway"):
                runtime.run_keepalive_probe(self.image, simulator=self.executable,
                                           output_dir=self.directory / "unknown")
            console.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])
        inconsistent = FirmwareImage(self.image.source, self.image.ihex, self.image.code + b"x",
                                     self.image.mapped_addresses, self.image.record_types, ())
        with patch.object(runtime, "GATEWAY_CODE_SHA256", hashlib.sha256(inconsistent.code).hexdigest()):
            with self.assertRaisesRegex(ValueError, "verified gateway"):
                runtime.run_keepalive_probe(inconsistent, simulator=self.executable,
                                           output_dir=self.directory / "inconsistent")

    def test_success_has_private_artifacts_honest_scope_and_total_budget(self):
        report = self.run_fake()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["actual_output_hex"], "1b53012461636b0a0d1b45")
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(report["child_reaped"])
        self.assertFalse(report["full_board_boot"] or report["live_tcp"] or report["nvm_model"])
        console = FakeConsole.instances[0]
        self.assertTrue(console.closed)
        self.assertTrue(all(a > b for a, b in zip(console.step_requests, console.step_requests[1:])))
        commands = [entry["command"] for entry in console.transcript]
        self.assertIn("break sfr w 0xa3", commands)
        self.assertIn("break sfr w 0x99", commands)
        self.assertLess(commands.index("simif_on=0"), next(i for i, c in enumerate(commands) if c.startswith("step ")))
        output = self.directory / "probe"
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir()))
        self.assertEqual(json.loads((output / "report.private.json").read_text()), report)
        with self.assertRaises(FileExistsError):
            self.run_fake()

    def test_instruction_bound_unexpected_peripheral_and_result_failure_cleanup(self):
        with self.assertRaises(runtime.FirmwareRuntimeError):
            self.run_fake("bound", instruction_limit=1500)
        self.assertTrue(FakeConsole.instances[-1].closed)
        self.assertLessEqual(FakeConsole.instances[-1].instructions, 1500)
        FakeConsole.stop_at_peripheral = True
        with self.assertRaises(runtime.FirmwareRuntimeError):
            self.run_fake("peripheral")
        self.assertTrue(FakeConsole.instances[-1].closed)
        FakeConsole.stop_at_peripheral = False
        FakeConsole.wrong_output = True
        with self.assertRaises(runtime.FirmwareRuntimeError) as caught:
            self.run_fake("wrong")
        report = json.loads(caught.exception.report_path.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["checks"]["output_exact"])
        self.assertTrue(report["child_reaped"])

    def test_constructor_failure_and_interrupt_save_failure_and_reap(self):
        with patch.object(runtime, "GATEWAY_CODE_SHA256", hashlib.sha256(self.image.code).hexdigest()), \
                patch.object(runtime, "_Console", side_effect=OSError("cannot start")):
            with self.assertRaises(runtime.FirmwareRuntimeError) as caught:
                runtime.run_keepalive_probe(self.image, simulator=self.executable,
                                           output_dir=self.directory / "constructor")
        report = json.loads(caught.exception.report_path.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["child_reaped"])
        FakeConsole.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_fake("interrupted")
        self.assertTrue(FakeConsole.instances[-1].closed)
        report = json.loads((self.directory / "interrupted/report.private.json").read_text())
        self.assertEqual(report["status"], "interrupted")

    def test_invalid_limits_rejected(self):
        for key, values in {"instruction_limit": (True, 0, 1_000_001),
                            "timeout_seconds": (True, 0, float("inf"), float("nan"), 301),
                            "output_limit_bytes": (True, 0, 32_000_001)}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.run_fake(**{key: value})
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cli_passes_explicit_offline_options(self):
        firmware = self.directory / "fictional.hex"
        firmware.write_bytes(FICTIONAL_HEX)
        with patch.object(runtime, "run_keepalive_probe", return_value={"status": "passed"}) as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["firmware-probe", "--hex", str(firmware), "--simulator", str(self.executable),
                         "--output-dir", str(self.directory / "cli"), "--instruction-limit", "12345",
                         "--timeout", "9"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "passed"})
        self.assertEqual(run.call_args.args[0].code, self.image.code)
        self.assertEqual(run.call_args.kwargs["instruction_limit"], 12345)
        self.assertEqual(run.call_args.kwargs["timeout_seconds"], 9)
        self.assertEqual(run.call_args.kwargs["simulator"], str(self.executable))


class ConsoleOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.executable = self.directory / "fake-simulator"
        self.executable.write_text(
            f"#!{sys.executable}\n"
            "import sys,time\n"
            "for line in sys.stdin:\n"
            " line=line.strip()\n"
            " if line=='hang': time.sleep(60)\n"
            " elif line=='flood': print('x'*8192,flush=True)\n"
            " elif line=='exit': sys.exit(0)\n"
            " elif line=='bad': print('Parser error',flush=True)\n"
            " elif line.startswith('echo '): print(line[5:],flush=True)\n"
            " else: print(line,flush=True)\n")
        self.executable.chmod(0o700)

    def console(self, seconds=2, limit=4096):
        result = runtime._Console(self.executable, self.directory,
                                  deadline=time.monotonic() + seconds, output_limit=limit)
        self.addCleanup(result.close)
        return result

    def test_timeout_and_cumulative_output_limits_reap_real_child(self):
        console = self.console(seconds=.15)
        with self.assertRaisesRegex(runtime.FirmwareRuntimeError, "wall-clock"):
            console.command("hang")
        console.close()
        self.assertIsNotNone(console.proc.poll())
        console = self.console(limit=1024)
        console.command("x" * 600)
        with self.assertRaisesRegex(runtime.FirmwareRuntimeError, "cumulative output"):
            console.command("y" * 600)
        console.close()
        self.assertIsNotNone(console.proc.poll())
        self.assertLessEqual(sum(len(x["output"].encode()) for x in console.transcript), 1024)

    def test_early_exit_parser_error_and_constructor_cleanup(self):
        for command, message in (("exit", "exited"), ("bad", "rejected")):
            console = self.console()
            with self.assertRaisesRegex(runtime.FirmwareRuntimeError, message):
                console.command(command)
            console.close()
            self.assertIsNotNone(console.proc.poll())
        children = []
        original = runtime.subprocess.Popen

        def remember(*args, **kwargs):
            proc = original(*args, **kwargs)
            children.append(proc)
            return proc

        with patch.object(runtime.subprocess, "Popen", side_effect=remember), \
                patch.object(runtime.os, "set_blocking", side_effect=OSError("setup failed")):
            with self.assertRaises(OSError):
                self.console()
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())


if __name__ == "__main__":
    unittest.main()
