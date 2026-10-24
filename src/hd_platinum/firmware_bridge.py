# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare bridge payload encoders with isolated original firmware execution.

Only an explicitly supplied, verified image and trusted uCsim binary are used.
Every builder stops before its radio-send function; no radio/peripheral model,
hardware, network adapter, manufacturer image, or upstream CPU code is bundled.
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
    _Console, _file_hash, _write_private, FirmwareRuntimeError, GATEWAY_CODE_SHA256,
)
from .rf_bridge import (
    build_position_payload, build_sync_payload, build_jog_payload, build_sequence_payload,
)


def run_bridge_probe(image: FirmwareImage, *, simulator, output_dir,
                     instruction_limit=100_000, timeout_seconds=30.0,
                     output_limit_bytes=4_000_000):
    """Execute original payload builders and counter wrap with fictional targets.

    This validates payload bytes and their application checksum, not the radio's
    PCF/CRC generation, over-air waveform, timing, or receiver acceptance. A
    count-two fixture verifies field separation; public plans remain restricted
    to one command. All execution shares one instruction/time/output budget.
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
        "schema": 1, "scenario": "isolated_gateway_bridge_builders_v1",
        "firmware": metadata, "simulator": str(executable), "simulator_sha256": None,
        "cpu": "generic C52 instruction baseline; not a complete C8051F34x model",
        "firmware_modified": False, "full_board_boot": False, "live_tcp": False,
        "cycle_exact": False, "radio_model": False, "nvm_model": False,
        "host_io": {"network": False, "hardware": False, "uart_mapping": False, "radio": False},
        "limits": {"instructions": instruction_limit, "seconds": timeout_seconds,
                   "output_bytes": output_limit_bytes, "cleanup_seconds": 2},
        "explicit_fixture": {
            "initial_ram": "zero IRAM/XRAM, then actual reset and CODE initialization",
            "target": "fictional room RF identifier 1234, mask08",
            "state": "explicit staging/execution records and byte counters, not a loaded database",
            "caller": "register bank0, interrupts disabled, synthetic ordinary return address",
            "radio_boundary": "stop before original send entry0x99AE; never execute it",
        },
        "scope": "application payload/checksum and counter wrap; excludes ESB PCF/CRC, PHY, timing and receiver acceptance",
        "execution_attempted": False, "execution_performed": False, "status": "preparing",
        "long_cases": [], "short_cases": [], "release_cases": [], "ordinal_cases": [],
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

        def step():
            nonlocal previous
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
            if (after["instructions"] < before["instructions"]
                    or after["instructions"] - initial > instruction_limit):
                raise FirmwareRuntimeError("simulator exceeded total instruction budget")
            previous = after["instructions"]
            return before, after

        _, state = step()
        if state["pc"] != 0x11A9 or cpu.value("sfr[0x81]") != 0x3E:
            raise FirmwareRuntimeError("actual reset/CODE initialization did not reach its verified boundary")
        result["startup_state"] = state
        cpu.command("clear 0x11a9")
        cpu.command("break 0x99ae")
        cpu.command("break 0xfff0")

        def put(address, values):
            cpu.command(f"set memory xram {address:#x} " + " ".join(str(value) for value in values))

        def build(entry):
            for command in ("set memory sfr 0xa8 0", "set memory sfr 0xd0 0",
                            "set memory iram 0x3f 0xf0 0xff", "set memory sfr 0x81 0x40",
                            f"pc {entry:#x}"):
                cpu.command(command)
            before, after = step()
            if after["pc"] != 0x99AE:
                raise FirmwareRuntimeError("builder did not stop before radio send; bound or peripheral stop")
            count = cpu.value("iram[5]")
            if not 5 <= count <= 32:
                raise FirmwareRuntimeError("invalid original builder output length")
            payload = bytes(cpu.value(f"xram[{0xA95 + index}]") for index in range(count))
            return payload, {"entry": entry, "stopped_before": after["pc"],
                             "instructions": after["instructions"] - before["instructions"],
                             "payload_hex": payload.hex()}

        identity, mask = b"\x12\x34", 8
        for operation, value, feature, flags in (("position", 0, 4, 1), ("position", 128, 4, 1),
                                               ("position", 255, 4, 1), ("sync", 0, 1, 3), ("jog", 1, 12, 1)):
            record = (*identity, mask, value, 0, feature, flags, 0)
            put(0x08DD, (0,))
            put(0x083A, record)
            payload, evidence = build(0x5FDD)
            if operation == "position":
                expected = build_position_payload(identity, mask, value)
            elif operation == "sync":
                expected = build_sync_payload(identity, mask)
            else:
                expected = build_jog_payload(identity, mask)
            evidence.update({"operation": operation, "value": value, "execution_record_hex": bytes(record).hex(),
                             "encoder_equal": payload == expected})
            result["long_cases"].append(evidence)

        for count in (1, 2):
            for transaction in (0, 1, 169, 255):
                for round_index in (0, 4):
                    put(0x08DA, (count,))
                    put(0x08DC, (round_index,))
                    put(0x08DF, (transaction,))
                    payload, evidence = build(0x9AAA)
                    checksum = 0
                    for value in payload[1:]:
                        checksum ^= value
                    evidence.update({"command_count": count, "transaction_counter": transaction,
                                     "round_index": round_index,
                                     "fields_match": payload[:8] == bytes((1, 7, 2, 0x38, count, transaction, 4 - round_index, 6)),
                                     "checksum_valid": len(payload) == 9 and checksum == 255})
                    result["short_cases"].append(evidence)

        for transaction_before in (254, 255):
            put(0x0743, (1,))
            put(0x082A, (0,))
            put(0x0744, (*identity, mask, 0, 0, 1, 3, 0))
            put(0x08DF, (transaction_before,))
            long_payload, evidence = build(0x87C7)
            counter_after = cpu.value("xram[0x8df]")
            count_after = cpu.value("xram[0x8da]")
            short_payload, _ = build(0x9AAA)
            expected_counter = (transaction_before + 1) & 255
            evidence.update({"transaction_before": transaction_before, "transaction_after": counter_after,
                             "command_count_after": count_after, "short_payload_hex": short_payload.hex(),
                             "wrap_correct": counter_after == expected_counter and count_after == 1,
                             "long_encoder_equal": long_payload == build_sync_payload(identity, mask),
                             "short_encoder_equal": short_payload == build_sequence_payload(expected_counter, 4)})
            result["release_cases"].append(evidence)

        for ordinal in (0, 255, 256, 511, 512, 65535):
            put(0x08DA, (1,))
            put(0x08DC, (0,))
            put(0x08DF, (ordinal & 255,))
            payload, evidence = build(0x9AAA)
            expected = build_sequence_payload(ordinal, 4)
            evidence.update({"local_ordinal": ordinal, "transaction_counter": ordinal & 255,
                             "encoder_payload_hex": expected.hex(), "encoder_equal": payload == expected})
            result["ordinal_cases"].append(evidence)

        checks = {
            "long_payloads": all(case["encoder_equal"] for case in result["long_cases"]),
            "separate_count_and_counter": all(case["fields_match"] for case in result["short_cases"]),
            "short_checksums": all(case["checksum_valid"] for case in result["short_cases"]),
            "release_counter_wrap": all(case["wrap_correct"] for case in result["release_cases"]),
            "release_payloads": all(case["long_encoder_equal"] and case["short_encoder_equal"]
                                    for case in result["release_cases"]),
            "ordinal_encoding": all(case["encoder_equal"] for case in result["ordinal_cases"]),
        }
        result.update({"checks": checks, "final_state": cpu.state()})
        if not all(checks.values()):
            raise FirmwareRuntimeError("original bridge payloads do not match the encoder contract")
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
