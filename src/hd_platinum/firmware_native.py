# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare native payloads with bounded execution of user-supplied firmware.

No manufacturer code is bundled. The original five-byte builder executes up
to its first SPI-command boundary; no peripheral response is supplied. Other
fixtures exercise channel selection and the duration-setting suffix in
isolation. This is a code-conformance probe, not board or shade emulation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time

from .firmware import FirmwareImage
from .firmware_runtime import (
    GATEWAY_CODE_SHA256, FirmwareRuntimeError, _Console, _file_hash, _write_private,
)
from .rf import build_remote_payload
from .rf_positions import build_position_payloads


def _payload_cases():
    """Fictional identities and boundary values; never household fixtures."""
    for identity in (b"\x12\x34", b"\x56\x78"):
        for mask in (1, 128):
            for position in (0, 1, 127, 128, 254, 255):
                for phase, expected in zip((2, 3), build_position_payloads(identity, mask, position)):
                    yield {"operation": "position", "identity": identity, "mask": mask,
                           "feature": 4, "value": position, "phase": phase,
                           "alternating": False, "previous_alternate": 0,
                           "expected": expected, "reference": "build_position_payloads"}
            for feature, action in ((1, "up"), (2, "down")):
                for phase in (2, 3):
                    name = action if phase == 2 else "release-" + action
                    yield {"operation": name, "identity": identity, "mask": mask,
                           "feature": feature, "value": 0, "phase": phase,
                           "alternating": False, "previous_alternate": 0,
                           "expected": build_remote_payload(identity, f"0x{mask:02x}", name),
                           "reference": "build_remote_payload"}
            for phase, code in ((2, 0xA1), (3, 0x21)):
                yield {"operation": "sync", "identity": identity, "mask": mask,
                       "feature": 1, "value": 0, "phase": phase,
                       "alternating": False, "previous_alternate": 0,
                       "expected": identity + bytes((0x20, mask, code)),
                       "reference": "verified native Sync body; duration checked separately"}
            for name, phase, previous, code, value in (
                    ("jog_main", 2, 1, 0x6A, 1),
                    ("jog_alternate", 2, 0, 0x20, 0x6A),
                    ("jog_tail", 3, 1, 0x32, 1)):
                yield {"operation": name, "identity": identity, "mask": mask,
                       "feature": 12, "value": 1, "phase": phase,
                       "alternating": True, "previous_alternate": previous,
                       "expected": identity + bytes((code, mask, value)),
                       "reference": "verified native Jog body; no public direct-Jog encoder"}


def run_native_probe(image: FirmwareImage, *, simulator, output_dir,
                     instruction_limit=100_000, timeout_seconds=30.0,
                     output_limit_bytes=4_000_000):
    """Execute original native builders and compare them with explicit fixtures.

    Requires the exact gateway image and a caller-supplied trusted uCsim
    executable. All executions share one instruction, wall-clock and output
    budget. Private artifacts preserve the input and complete console trace.
    No live transport, RF waveform, CRC hardware, ACK or receiver is exercised.
    """
    if not isinstance(image, FirmwareImage):
        raise ValueError("image must be a FirmwareImage")
    reparsed = FirmwareImage.parse(image.ihex, source=image.source)
    if (reparsed.code != image.code or reparsed.mapped_addresses != image.mapped_addresses
            or hashlib.sha256(image.code).hexdigest() != GATEWAY_CODE_SHA256):
        raise ValueError("this address-specific probe requires the verified gateway firmware hash")
    if type(instruction_limit) is not int or not 1 <= instruction_limit <= 1_000_000:
        raise ValueError("instruction_limit must be an integer from 1 to 1000000")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 300):
        raise ValueError("timeout_seconds must be finite, positive, and at most 300")
    if type(output_limit_bytes) is not int or not 1024 <= output_limit_bytes <= 32_000_000:
        raise ValueError("output_limit_bytes must be an integer from 1024 to 32000000")
    executable = Path(simulator).expanduser().resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("simulator must be an explicit executable file")
    directory = Path(output_dir).expanduser().absolute()
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    report_path = directory / "report.private.json"
    started = time.monotonic()
    metadata = image.summary()
    metadata.pop("execution_performed", None)
    metadata.pop("device_access_performed", None)
    result = {
        "schema": 1, "scenario": "isolated_gateway_native_conformance_v1",
        "firmware": metadata, "simulator": str(executable), "simulator_sha256": None,
        "cpu": "generic C52 instruction baseline; not a complete C8051F34x model",
        "firmware_modified": False, "full_board_boot": False, "cycle_exact": False,
        "host_io": {"network": False, "hardware": False, "uart_mapping": False, "radio": False},
        "limits": {"instructions": instruction_limit, "seconds": timeout_seconds,
                   "output_bytes": output_limit_bytes, "cleanup_seconds": 2},
        "explicit_fixture": {
            "identities_are_fictional": True,
            "initial_ram": "zero IRAM/XRAM followed by original reset/CODE initialization",
            "caller": "bank0, interrupts disabled, synthetic return address at IRAM0x3F/40",
            "payload_entry": 0x7D38, "payload_stop_before_spi": 0xB7CE,
            "channel_entry": 0xA9F4, "channel_stop_before_register_write": 0xA801,
            "duration_suffix_entry": 0x81DD, "duration_stop_before_transmit": 0xAACC,
            "duration_suffix_excludes": "earlier payload/SPI setup at0x81D3..0x81DC",
        },
        "scope_limits": [
            "Compares five-byte native bodies, channel state transitions and timer counts only.",
            "Does not exercise radio-generated preamble/address/CRC or on-air timing.",
            "Sync and Jog vectors do not add a direct-radio Sync/Jog backend.",
            "Existing direct backend sends whole trains per channel, unlike original per-pulse rotation.",
            "No receiver enrollment policy or physical shade acceptance is established.",
        ],
        "execution_attempted": False, "execution_performed": False,
        "payloads": [], "channel_rotation": [], "durations": [], "status": "preparing",
    }
    cpu = None
    try:
        result["simulator_sha256"] = _file_hash(executable, deadline=started + timeout_seconds)
        _write_private(directory / "firmware.hex", image.ihex)
        _write_private(directory / "console.conf", "simif_on=0\n")
        cpu = _Console(executable, directory, deadline=started + timeout_seconds,
                       output_limit=output_limit_bytes)
        for command in ("simif_on=0", "set option irq_stop true", "cpu_movxri_addr=0xaa",
                        "fill iram 0 0xff 0", "fill xram 0 0xffff 0", "pc 0",
                        "break sfr w 0xa3", "break sfr w 0x99", "break 0x11a9"):
            cpu.command(command)
        if cpu.value("simif_on") != 0:
            raise FirmwareRuntimeError("simulator host interface was not disabled")
        initial = cpu.state()["instructions"]
        previous = initial

        def execute(entry, stop, expected_sp, *, reset_caller=True):
            nonlocal previous
            if reset_caller:
                for command in ("set memory sfr 0xa8 0", "set memory sfr 0xd0 0",
                                "set memory iram 0x3f 0xf0 0xff", "set memory sfr 0x81 0x40",
                                f"pc {entry:#x}"):
                    cpu.command(command)
            before = cpu.state()
            used = before["instructions"] - initial
            if before["instructions"] < previous or used < 0 or used >= instruction_limit:
                raise FirmwareRuntimeError("total instruction limit reached or counter regressed")
            result["execution_attempted"] = True
            if not result["execution_performed"]:
                result["execution_performed"] = None
            cpu.command(f"step {instruction_limit - used}")
            after = cpu.state()
            result["execution_performed"] = after["instructions"] > initial
            if (after["instructions"] <= before["instructions"]
                    or after["instructions"] - initial > instruction_limit):
                raise FirmwareRuntimeError("simulator exceeded the instruction budget or made no progress")
            previous = after["instructions"]
            if after["pc"] != stop or cpu.value("sfr[0x81]") != expected_sp:
                raise FirmwareRuntimeError("original routine missed its verified boundary or stack state")
            return after["instructions"] - before["instructions"]

        execute(0, 0x11A9, 0x3E, reset_caller=False)
        result["reset_state"] = cpu.state()
        cpu.command("clear 0x11a9")
        for boundary in (0xB7CE, 0xA801, 0xAACC, 0xFFF0):
            cpu.command(f"break {boundary:#x}")

        def fixture(values):
            for address, value in values.items():
                cpu.command(f"set memory xram {address:#x} {value}")

        for case in _payload_cases():
            identity = case["identity"]
            fixture({0x741: identity[0], 0x742: identity[1], 0x837: case["mask"],
                     0x805: case["phase"], 0x806: case["feature"], 0x836: case["value"],
                     0x835: int(case["alternating"]), 0x740: case["previous_alternate"]})
            count = execute(0x7D38, 0xB7CE, 0x42)
            actual = bytes(cpu.value(f"xram[{0x807 + i}]") for i in range(5))
            alternate = 1 - case["previous_alternate"] if case["alternating"] else case["previous_alternate"]
            refresh = 20 if case["alternating"] and alternate else 100
            checks = {"payload_exact": actual == case["expected"],
                      "first_spi_command_not_executed": cpu.value("iram[7]") == 0xE1,
                      "alternation_state": cpu.value("xram[0x740]") == alternate,
                      "refresh_count": cpu.value("xram[0x839]") == refresh}
            result["payloads"].append({**{k: v for k, v in case.items() if k not in ("identity", "expected")},
                                       "identity_hex": identity.hex(), "expected_hex": case["expected"].hex(),
                                       "actual_hex": actual.hex(), "instructions": count, "checks": checks})
            if not all(checks.values()):
                raise FirmwareRuntimeError("original native payload or alternation differs from the expected contract")

        for previous_channel, expected in ((0, 33), (33, 52), (52, 71), (71, 33), (255, 33)):
            fixture({0x73F: previous_channel})
            count = execute(0xA9F4, 0xA801, 0x40)
            actual = cpu.value("xram[0x73f]")
            arguments = [cpu.value("iram[7]"), cpu.value("iram[5]")]
            passed = actual == expected and arguments == [5, expected]
            result["channel_rotation"].append({"previous": previous_channel, "expected": expected,
                                               "actual": actual, "register_write_not_executed": arguments,
                                               "instructions": count, "passed": passed})
            if not passed:
                raise FirmwareRuntimeError("original native channel rotation differs from the expected contract")

        for phase, flags, expected in ((2, 1, 150), (2, 2, 275), (2, 3, 1500),
                                       (1, 3, 30), (3, 1, 30), (3, 3, 30)):
            fixture({0x805: phase, 0x829: flags, 0x82E: 0, 0x82F: 0, 0x831: 0})
            count = execute(0x81DD, 0xAACC, 0x40)
            actual = cpu.value("xram[0x82e]") * 256 + cpu.value("xram[0x82f]")
            passed = actual == expected and cpu.value("xram[0x831]") == 1
            result["durations"].append({"phase": phase, "flags": flags, "expected_ticks": expected,
                                        "actual_ticks": actual, "instructions": count, "passed": passed})
            if not passed:
                raise FirmwareRuntimeError("original native duration differs from the expected contract")
        fixture({0x831: 1, 0x82E: 0, 0x82F: 2, 0x829: 3})
        result["duration_decrement"] = []
        for expected in ([1, 0, 1], [0, 0, 0]):
            execute(0xA589, 0xFFF0, 0x3E)
            actual = [cpu.value(f"xram[{x}]") for x in (0x831, 0x82E, 0x82F)]
            result["duration_decrement"].append(actual)
            if actual != expected:
                raise FirmwareRuntimeError("original duration countdown did not expire as expected")
        result["final_state"] = cpu.state()
        result["instructions_executed"] = result["final_state"]["instructions"] - initial
        result["status"] = "passed"
    except BaseException as exc:
        result["status"] = "interrupted" if not isinstance(exc, Exception) else "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, Exception):
            raise FirmwareRuntimeError(str(exc), report_path=report_path) from exc
        raise
    finally:
        cleanup_error = None
        try:
            if cpu is not None:
                cpu.close()
        except Exception as exc:
            cleanup_error = exc
            result["status"] = "failed"
            result["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result["elapsed_seconds"] = time.monotonic() - started
            result["child_reaped"] = cpu is None or cpu.proc.poll() is not None
            if cpu is not None:
                result["simulator_output_bytes"] = cpu.output_bytes
                _write_private(directory / "transcript.private.json", json.dumps(cpu.transcript, indent=2) + "\n")
            _write_private(report_path, json.dumps(result, indent=2) + "\n")
        if cleanup_error is not None:
            raise FirmwareRuntimeError("simulator child cleanup failed", report_path=report_path) from cleanup_error
    return result
