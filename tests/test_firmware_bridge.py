# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bridge-oracle control-flow tests with fictional images and a fake console."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from hd_platinum import firmware_bridge as oracle
from hd_platinum.cli import main
from hd_platinum.firmware import FirmwareImage
from hd_platinum.firmware_runtime import FirmwareRuntimeError


def _record(address=0, data=b"", kind=0):
    raw = bytes((len(data),)) + address.to_bytes(2, "big") + bytes((kind,)) + data
    return b":" + (raw + bytes((-sum(raw) & 255,))).hex().encode() + b"\n"


FICTIONAL_HEX = _record(data=b"\x02\x01\x00") + _record(0x100, b"\x22") + _record(kind=1)


class FixtureConsole:
    """Test the runner's boundary/fixture handling, not the original CPU code."""

    instances = []
    bad_output = False
    peripheral_stop = False
    interrupt = False

    def __init__(self, simulator, directory, *, deadline, output_limit):
        self.__class__.instances.append(self)
        self.pc, self.instructions = 0, 0
        self.memory = {}
        self.transcript = []
        self.output_bytes = 0
        self.closed = False
        self.proc = self
        self.steps = []

    def poll(self):
        return 0 if self.closed else None

    def close(self):
        self.closed = True

    def get(self, address):
        return self.memory.get(("xram", address), 0)

    def set(self, address, value):
        self.memory["xram", address] = value

    def command(self, command):
        self.transcript.append({"command": command, "output": ""})
        if command.startswith("set memory "):
            parts = command.split()
            space, address = parts[2], int(parts[3], 0)
            for offset, value in enumerate(parts[4:]):
                self.memory[space, address + offset] = int(value, 0)
        elif command.startswith("pc "):
            self.pc = int(command.split()[1], 0)
        elif command.startswith("step "):
            budget = int(command.split()[1])
            self.steps.append(budget)
            cost = 1153 if self.pc == 0 else 100
            if self.interrupt:
                raise KeyboardInterrupt()
            self.instructions += min(cost, budget)
            if budget < cost or self.peripheral_stop:
                self.pc = 0xB15E
                return ""
            if self.pc == 0:
                self.pc = 0x11A9
                self.memory["sfr", 0x81] = 0x3E
                return ""
            if self.pc == 0x87C7:
                self.set(0x08DA, 1)
                self.set(0x08DF, (self.get(0x08DF) + 1) & 255)
                self.set(0x08DC, 0)
                self.set(0x08DD, 0)
                for offset in range(8):
                    self.set(0x083A + offset, self.get(0x0744 + offset))
                self.pc = 0x5FDD
            if self.pc == 0x5FDD:
                index = self.get(0x08DD)
                values = [self.get(0x083A + index * 8 + i) for i in range(8)]
                data = bytes((values[0], values[1], values[5], values[2], values[3], index, values[6]))
                self.set(0x08DD, index + 1)
                payload = bytes((1, 10, 2, 0x34)) + data
            elif self.pc == 0x9AAA:
                payload = bytes((1, 7, 2, 0x38, self.get(0x08DA), self.get(0x08DF),
                                 4 - self.get(0x08DC), 6))
            else:
                raise RuntimeError("runner used an unexpected original entry")
            checksum = 255
            for value in payload[1:]:
                checksum ^= value
            payload += bytes((checksum,))
            if self.bad_output:
                payload = payload[:-1] + bytes((checksum ^ 1,))
            for offset, value in enumerate(payload):
                self.set(0x0A95 + offset, value)
            self.memory["iram", 5] = len(payload)
            self.pc = 0x99AE
        return ""

    def value(self, expression):
        if expression == "simif_on":
            return 0
        space, index = expression[:-1].split("[")
        return self.memory.get((space, int(index, 0)), 0)

    def state(self):
        return {"pc": self.pc, "instructions": self.instructions}


class FirmwareBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.image = FirmwareImage.parse(FICTIONAL_HEX)
        self.executable = Path(sys.executable).resolve()
        FixtureConsole.instances = []
        FixtureConsole.bad_output = FixtureConsole.peripheral_stop = FixtureConsole.interrupt = False

    def run_fake(self, name="probe", **kwargs):
        with patch.object(oracle, "GATEWAY_CODE_SHA256", hashlib.sha256(self.image.code).hexdigest()), \
                patch.object(oracle, "_Console", FixtureConsole):
            return oracle.run_bridge_probe(self.image, simulator=self.executable,
                                           output_dir=self.directory / name, **kwargs)

    def test_fixture_matrix_boundaries_and_honest_report(self):
        report = self.run_fake()
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(len(report["long_cases"]), 5)
        self.assertEqual(len(report["short_cases"]), 16)
        self.assertEqual({case["command_count"] for case in report["short_cases"]}, {1, 2})
        self.assertEqual([case["transaction_after"] for case in report["release_cases"]], [255, 0])
        self.assertEqual([case["local_ordinal"] for case in report["ordinal_cases"]], [0, 255, 256, 511, 512, 65535])
        self.assertFalse(report["full_board_boot"] or report["radio_model"] or report["live_tcp"])
        self.assertTrue(report["execution_performed"] and report["child_reaped"])
        console = FixtureConsole.instances[0]
        self.assertTrue(console.closed)
        self.assertTrue(all(a > b for a, b in zip(console.steps, console.steps[1:])))
        commands = [item["command"] for item in console.transcript]
        self.assertIn("break 0x99ae", commands)
        self.assertIn("break sfr w 0xa3", commands)
        self.assertNotIn("pc 0x99ae", commands)
        output = self.directory / "probe"
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir()))
        self.assertEqual(json.loads((output / "report.private.json").read_text()), report)
        with self.assertRaises(FileExistsError):
            self.run_fake()

    def test_unknown_image_and_invalid_limits_fail_before_console(self):
        with patch.object(oracle, "_Console") as console:
            with self.assertRaisesRegex(ValueError, "verified gateway"):
                oracle.run_bridge_probe(self.image, simulator=self.executable,
                                        output_dir=self.directory / "unknown")
            console.assert_not_called()
        for options in ({"instruction_limit": True}, {"instruction_limit": 0},
                        {"timeout_seconds": float("nan")}, {"output_limit_bytes": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_fake(**options)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_wrong_original_output_and_early_stops_fail_closed(self):
        FixtureConsole.bad_output = True
        with self.assertRaises(FirmwareRuntimeError) as caught:
            self.run_fake("bad-output")
        report = json.loads(caught.exception.report_path.read_text())
        self.assertFalse(report["checks"]["short_checksums"])
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["child_reaped"])
        FixtureConsole.bad_output = False
        with self.assertRaises(FirmwareRuntimeError):
            self.run_fake("budget", instruction_limit=1500)
        self.assertLessEqual(FixtureConsole.instances[-1].instructions, 1500)
        self.assertTrue(FixtureConsole.instances[-1].closed)
        FixtureConsole.peripheral_stop = True
        with self.assertRaises(FirmwareRuntimeError):
            self.run_fake("peripheral")
        self.assertTrue(FixtureConsole.instances[-1].closed)

    def test_interrupt_reaps_child_and_preserves_incomplete_evidence(self):
        FixtureConsole.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_fake()
        self.assertTrue(FixtureConsole.instances[-1].closed)
        report = json.loads((self.directory / "probe/report.private.json").read_text())
        self.assertEqual(report["status"], "interrupted")
        self.assertTrue(report["execution_attempted"])
        self.assertIsNone(report["execution_performed"])

    def test_cli_wiring_keeps_supplied_paths_and_limits(self):
        firmware = self.directory / "fictional.hex"
        firmware.write_bytes(FICTIONAL_HEX)
        with patch.object(oracle, "run_bridge_probe", return_value={"status": "passed"}) as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["firmware-bridge-probe", "--hex", str(firmware),
                         "--simulator", str(self.executable), "--output-dir", str(self.directory / "cli"),
                         "--instruction-limit", "50000", "--timeout", "12"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "passed"})
        self.assertEqual(run.call_args.args[0].code, self.image.code)
        self.assertEqual(run.call_args.kwargs["instruction_limit"], 50000)
        self.assertEqual(run.call_args.kwargs["timeout_seconds"], 12)
        self.assertEqual(run.call_args.kwargs["simulator"], str(self.executable))


if __name__ == "__main__":
    unittest.main()
