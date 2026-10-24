# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Probe contract tests with fictional firmware; these are not CPU evidence."""

import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from hd_platinum.firmware import FirmwareImage
from hd_platinum import firmware_native as native


def _record(address=0, data=b"", kind=0):
    raw = bytes((len(data),)) + address.to_bytes(2, "big") + bytes((kind,)) + data
    return b":" + (raw + bytes((-sum(raw) & 255,))).hex().encode() + b"\n"


FICTIONAL_HEX = _record(data=b"\x02\x01\x00") + _record(0x100, b"\x22") + _record(kind=1)


class FakeConsole:
    """Independent fixed console contract, without executing the supplied HEX."""

    instances = []
    wrong_payload = False
    unexpected_peripheral = False
    interrupt = False
    wrong_channel = False
    wrong_duration = False

    def __init__(self, simulator, directory, *, deadline, output_limit):
        self.__class__.instances.append(self)
        self.pc = self.instructions = self.output_bytes = 0
        self.memory = {"simif_on": 0}
        self.transcript, self.step_requests = [], []
        self.closed = False
        self.proc = self

    def poll(self):
        return 0 if self.closed else None

    def close(self):
        self.closed = True

    def value(self, expression):
        if "[" in expression:
            space, address = expression[:-1].split("[")
            expression = f"{space}[{int(address, 0)}]"
        return self.memory.get(expression, 0)

    def state(self):
        return {"pc": self.pc, "instructions": self.instructions}

    def put(self, space, address, *values):
        for i, value in enumerate(values):
            self.memory[f"{space}[{address + i}]"] = value

    def command(self, command):
        self.transcript.append({"command": command, "output": ""})
        if command.startswith("set memory "):
            parts = command.split()
            self.put(parts[2], int(parts[3], 0), *(int(v, 0) for v in parts[4:]))
        elif command.startswith("pc "):
            self.pc = int(command.split()[1], 0)
        elif command.startswith("step "):
            budget = int(command.split()[1])
            self.step_requests.append(budget)
            cost = 1153 if self.pc == 0 else 150
            if self.interrupt:
                raise KeyboardInterrupt()
            self.instructions += min(budget, cost)
            if budget < cost or self.unexpected_peripheral:
                self.pc = 0xB15E
                return ""
            if self.pc == 0:
                self.pc = 0x11A9
                self.put("sfr", 0x81, 0x3E)
            elif self.pc == 0x7D38:
                phase, feature, value = (self.value(f"xram[{a}]") for a in (0x805, 0x806, 0x836))
                alternate = self.value("xram[0x740]")
                if self.value("xram[0x835]"):
                    alternate = 1 - alternate
                self.put("xram", 0x740, alternate)
                self.put("xram", 0x839, 20 if self.value("xram[0x835]") and alternate else 100)
                if feature in (1, 2):
                    code, value = 0x20, (0xA0 if phase == 2 else 0x20) + feature
                elif feature == 4:
                    code = 0x50 if phase == 2 else 0x32
                elif feature == 12:
                    code = 0x32 if phase == 3 else (0x20 if alternate else 0x6A)
                    value = 0x6A if phase == 2 and alternate else value
                else:
                    raise AssertionError("unexpected fictional feature")
                payload = [self.value("xram[0x741]"), self.value("xram[0x742]"), code,
                           self.value("xram[0x837]"), value]
                if self.wrong_payload:
                    payload[-1] ^= 1
                self.put("xram", 0x807, *payload)
                self.put("iram", 7, 0xE1)
                self.put("sfr", 0x81, 0x42)
                self.pc = 0xB7CE
            elif self.pc == 0xA9F4:
                channel = {33: 52, 52: 71}.get(self.value("xram[0x73f]"), 33)
                if self.wrong_channel:
                    channel = 40
                self.put("xram", 0x73F, channel)
                self.put("iram", 5, channel)
                self.put("iram", 7, 5)
                self.pc = 0xA801
            elif self.pc == 0x81DD:
                count = ({1: 150, 2: 275, 3: 1500}[self.value("xram[0x829]")]
                         if self.value("xram[0x805]") == 2 else 30)
                if self.wrong_duration:
                    count += 1
                self.put("xram", 0x82E, count >> 8, count & 255)
                self.put("xram", 0x831, 1)
                self.pc = 0xAACC
            elif self.pc == 0xA589:
                count = self.value("xram[0x82e]") * 256 + self.value("xram[0x82f]") - 1
                self.put("xram", 0x82E, count >> 8, count & 255)
                self.put("xram", 0x831, int(count != 0))
                self.put("sfr", 0x81, 0x3E)
                self.pc = 0xFFF0
            else:
                raise AssertionError(f"unexpected fictional entry {self.pc:#x}")
        return ""


class NativeFirmwareProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.image = FirmwareImage.parse(FICTIONAL_HEX)
        self.executable = Path(sys.executable).resolve()
        FakeConsole.instances = []
        for name in ("wrong_payload", "unexpected_peripheral", "interrupt", "wrong_channel", "wrong_duration"):
            setattr(FakeConsole, name, False)

    def run_fake(self, name="probe", **kwargs):
        with patch.object(native, "GATEWAY_CODE_SHA256", hashlib.sha256(self.image.code).hexdigest()), \
                patch.object(native, "_Console", FakeConsole):
            return native.run_native_probe(self.image, simulator=self.executable,
                                           output_dir=self.directory / name, **kwargs)

    def test_unknown_image_and_limits_refused_without_files_or_child(self):
        with patch.object(native, "_Console") as console:
            with self.assertRaisesRegex(ValueError, "verified gateway"):
                native.run_native_probe(self.image, simulator=self.executable,
                                        output_dir=self.directory / "unknown")
            console.assert_not_called()
        for key, values in {"instruction_limit": (True, 0, 1_000_001),
                            "timeout_seconds": (True, 0, float("inf"), float("nan"), 301),
                            "output_limit_bytes": (True, 0, 32_000_001)}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.run_fake(**{key: value})
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_matrix_has_private_artifacts_boundaries_and_honest_scope(self):
        report = self.run_fake()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["payloads"]), 84)
        positions = [r for r in report["payloads"] if r["operation"] == "position"]
        self.assertEqual({r["value"] for r in positions}, {0, 1, 127, 128, 254, 255})
        self.assertEqual({r["mask"] for r in positions}, {1, 128})
        self.assertEqual({r["identity_hex"] for r in positions}, {"1234", "5678"})
        self.assertEqual(len(report["channel_rotation"]), 5)
        self.assertEqual([r["actual_ticks"] for r in report["durations"]], [150, 275, 1500, 30, 30, 30])
        self.assertEqual(report["duration_decrement"], [[1, 0, 1], [0, 0, 0]])
        self.assertFalse(report["full_board_boot"] or report["cycle_exact"] or any(report["host_io"].values()))
        self.assertTrue(report["child_reaped"])
        self.assertNotIn("execution_performed", report["firmware"])
        console = FakeConsole.instances[-1]
        self.assertTrue(console.closed)
        self.assertTrue(all(a > b for a, b in zip(console.step_requests, console.step_requests[1:])))
        commands = [item["command"] for item in console.transcript]
        for boundary in ("break sfr w 0xa3", "break sfr w 0x99", "break 0xb7ce", "break 0xa801", "break 0xaacc"):
            self.assertIn(boundary, commands)
        self.assertLess(commands.index("simif_on=0"), commands.index("step 100000"))
        output = self.directory / "probe"
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.iterdir()))
        self.assertEqual(json.loads((output / "report.private.json").read_text()), report)
        with self.assertRaises(FileExistsError):
            self.run_fake()

    def test_public_encoder_regression_fails_independent_contract(self):
        with patch.object(native, "build_position_payloads", return_value=(b"wrong", b"wrong")):
            with self.assertRaises(native.FirmwareRuntimeError) as caught:
                self.run_fake()
        report = json.loads(caught.exception.report_path.read_text())
        self.assertFalse(report["payloads"][0]["checks"]["payload_exact"])
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["child_reaped"])

    def test_payload_channel_and_duration_mismatches_stop_and_reap(self):
        for flag in ("wrong_payload", "wrong_channel", "wrong_duration"):
            setattr(FakeConsole, flag, True)
            with self.subTest(flag=flag), self.assertRaises(native.FirmwareRuntimeError) as caught:
                self.run_fake(flag)
            report = json.loads(caught.exception.report_path.read_text())
            self.assertEqual(report["status"], "failed")
            self.assertTrue(report["child_reaped"])
            setattr(FakeConsole, flag, False)

    def test_total_budget_unexpected_stop_constructor_failure_and_interrupt(self):
        with self.assertRaises(native.FirmwareRuntimeError):
            self.run_fake("budget", instruction_limit=1300)
        self.assertLessEqual(FakeConsole.instances[-1].instructions, 1300)
        self.assertTrue(FakeConsole.instances[-1].closed)
        FakeConsole.unexpected_peripheral = True
        with self.assertRaisesRegex(native.FirmwareRuntimeError, "verified boundary"):
            self.run_fake("peripheral")
        self.assertTrue(FakeConsole.instances[-1].closed)
        FakeConsole.unexpected_peripheral = False
        FakeConsole.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_fake("interrupt")
        report = json.loads((self.directory / "interrupt/report.private.json").read_text())
        self.assertEqual(report["status"], "interrupted")
        self.assertTrue(report["child_reaped"])
        with patch.object(native, "GATEWAY_CODE_SHA256", hashlib.sha256(self.image.code).hexdigest()), \
                patch.object(native, "_Console", side_effect=OSError("start failed")):
            with self.assertRaises(native.FirmwareRuntimeError) as caught:
                native.run_native_probe(self.image, simulator=self.executable,
                                        output_dir=self.directory / "constructor")
        report = json.loads(caught.exception.report_path.read_text())
        self.assertFalse(report["execution_attempted"] or report["execution_performed"])
        self.assertTrue(report["child_reaped"])


if __name__ == "__main__":
    unittest.main()
