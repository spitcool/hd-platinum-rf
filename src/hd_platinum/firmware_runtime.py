# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bounded offline execution of one verified original-firmware handler.

The caller supplies both the firmware and a trusted uCsim executable. This is
an isolated dispatcher experiment, not board boot, TCP emulation, a radio
adapter, or a security sandbox for arbitrary executables. No upstream emulator
code or manufacturer firmware is included here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import subprocess
import time

from .firmware import FirmwareImage


GATEWAY_CODE_SHA256 = "f93843ff65dfb5fe91e9b3e5adf3a191bd09483d5b4ac03389ffb7c53fe5cf01"
_INPUT = b"S1$dmy"
_EXPECTED_OUTPUT = b"\x1bS\x01$ack\n\r\x1bE"
_SENTINEL = 0xFFF0


class FirmwareRuntimeError(RuntimeError):
    """An offline probe failed; any created report is available at report_path."""

    def __init__(self, message, *, report_path=None):
        super().__init__(message)
        self.report_path = report_path


def _write_private(path, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _file_hash(path, *, deadline):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if time.monotonic() >= deadline:
                raise FirmwareRuntimeError("simulator wall-clock limit exceeded during executable hashing")
            digest.update(block)
    return digest.hexdigest()


class _Console:
    """Pipe-only uCsim console with cumulative output and wall-clock bounds."""

    def __init__(self, simulator, directory, *, deadline, output_limit):
        self.deadline = deadline
        self.output_limit = output_limit
        self.output_bytes = 0
        self.counter = 0
        self.transcript = []
        self.proc = subprocess.Popen(
            [str(simulator), "-t", "C52", "-q", "-b", "-R", "1",
             "-C", "console.conf", "-c", "-", "firmware.hex"],
            cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, close_fds=True,
        )
        try:
            os.set_blocking(self.proc.stdin.fileno(), False)
            os.set_blocking(self.proc.stdout.fileno(), False)
        except BaseException:
            self.close()
            raise

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise FirmwareRuntimeError("simulator wall-clock limit exceeded")
        return remaining

    def command(self, command):
        if not isinstance(command, str) or not command or "\n" in command or "\r" in command:
            raise ValueError("one nonempty simulator command is required")
        self.counter += 1
        marker = f"__HD_PROBE_END_{self.counter:06d}__"
        request = memoryview((command + "\necho " + marker + "\n").encode())
        received = bytearray()
        entry = {"command": command, "output": ""}
        self.transcript.append(entry)
        try:
            while request:
                remaining = self._remaining()
                if select.select([], [self.proc.stdin], [], min(remaining, .1))[1]:
                    try:
                        written = os.write(self.proc.stdin.fileno(), request)
                    except BlockingIOError:
                        continue
                    request = request[written:]
            terminal = ("\n" + marker + "\n").encode()
            while terminal not in received:
                remaining = self._remaining()
                if select.select([self.proc.stdout], [], [], min(remaining, .1))[0]:
                    try:
                        block = os.read(self.proc.stdout.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not block:
                        raise FirmwareRuntimeError("simulator exited before command completion")
                    self.output_bytes += len(block)
                    allowed = max(0, self.output_limit - (self.output_bytes - len(block)))
                    received.extend(block[:allowed])
                    if self.output_bytes > self.output_limit:
                        raise FirmwareRuntimeError("simulator cumulative output limit exceeded")
            answer = received.decode("utf-8", "replace")
            if re.search(r"Parser error|Unknown command|syntax error", answer, re.IGNORECASE):
                raise FirmwareRuntimeError(f"simulator rejected command: {command}")
            return answer
        finally:
            entry["output"] = received.decode("utf-8", "replace")

    def value(self, expression):
        answer = self.command("expression " + expression)
        matches = re.findall(r"(?m)^(-?\d+)\r?$", answer)
        if len(matches) != 1:
            raise FirmwareRuntimeError(f"unexpected simulator value response: {expression}")
        return int(matches[0])

    def state(self):
        answer = self.command("state")
        pc = re.search(r"CPU state=.* PC= 0x([0-9a-fA-F]+)", answer)
        instructions = re.search(r"Inst= (\d+)", answer)
        if not pc or not instructions:
            raise FirmwareRuntimeError("simulator did not provide CPU state")
        return {"pc": int(pc[1], 16), "instructions": int(instructions[1])}

    def close(self):
        """Reap the child even after timeout, failed parsing, or interruption."""
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=1)
        finally:
            for stream in (self.proc.stdin, self.proc.stdout):
                if stream is not None:
                    stream.close()


def run_keepalive_probe(image: FirmwareImage, *, simulator, output_dir,
                        instruction_limit=100_000, timeout_seconds=30.0,
                        output_limit_bytes=4_000_000):
    """Run original ``$dmy`` parsing and inspect its internal response queue.

    Accepts only the gateway code hash whose function addresses were verified.
    All CPU execution shares one instruction budget and one wall-clock deadline
    (child cleanup has a separate maximum two-second allowance). The new output
    directory contains private input, transcript, and success/failure report.
    No database, external peripheral response, or outgoing message is supplied.
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
    firmware_metadata = image.summary()
    firmware_metadata.pop("execution_performed", None)
    firmware_metadata.pop("device_access_performed", None)
    result = {
        "schema": 1, "scenario": "isolated_gateway_keepalive_dispatcher_v1",
        "firmware": firmware_metadata, "simulator": str(executable),
        "simulator_sha256": None,
        "cpu": "generic C52 instruction baseline; not a complete C8051F34x model",
        "firmware_modified": False, "full_board_boot": False, "live_tcp": False,
        "cycle_exact": False, "nvm_model": False,
        "host_io": {"network": False, "hardware": False, "uart_mapping": False, "radio": False},
        "limits": {"instructions": instruction_limit, "seconds": timeout_seconds,
                   "output_bytes": output_limit_bytes, "cleanup_seconds": 2},
        "explicit_fixture": {
            "initial_ram": "deterministic zero IRAM/XRAM, followed by actual reset and CODE initialization",
            "connection_slot": 0, "active_connection_mask": 1,
            "connection_established_by_fixture": True,
            "caller": "bank0, interrupts disabled, synthetic ordinary return address at IRAM0x3F/40",
            "return_sentinel": _SENTINEL,
        },
        "output_interpretation": "internal ESC S mask / ESC E routing tokens, not final TCP framing",
        "execution_attempted": False, "execution_performed": False,
        "phases": [], "status": "preparing",
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

        def step_remaining():
            nonlocal previous
            before = cpu.state()
            used = before["instructions"] - initial
            if before["instructions"] < previous or used < 0 or used >= instruction_limit:
                raise FirmwareRuntimeError("total instruction limit reached or counter regressed")
            result["execution_attempted"] = True
            # A timeout/early exit may prevent observing a completed step.
            if not result["execution_performed"]:
                result["execution_performed"] = None
            cpu.command(f"step {instruction_limit - used}")
            after = cpu.state()
            result["execution_performed"] = after["instructions"] > initial
            if (after["instructions"] < before["instructions"]
                    or after["instructions"] - initial > instruction_limit):
                raise FirmwareRuntimeError("simulator exceeded the total instruction budget")
            previous = after["instructions"]
            return before, after

        _, state = step_remaining()
        if state["pc"] != 0x11A9 or cpu.value("sfr[0x81]") != 0x3E:
            raise FirmwareRuntimeError("actual reset/CODE initialization did not reach its verified boundary")
        result["phases"].append({"name": "actual_reset_and_code_initialization", **state})
        cpu.command("clear 0x11a9")
        cpu.command("break 0xfff0")

        def call(address, label, r7=None):
            for command in ("set memory sfr 0xa8 0", "set memory sfr 0xd0 0",
                            "set memory iram 0x3f 0xf0 0xff", "set memory sfr 0x81 0x40"):
                cpu.command(command)
            if r7 is not None:
                cpu.command(f"set memory iram 7 {r7}")
            cpu.command(f"pc {address:#x}")
            before, after = step_remaining()
            sp = cpu.value("sfr[0x81]")
            if after["pc"] != _SENTINEL or sp != 0x3E:
                raise FirmwareRuntimeError(f"{label} did not return; instruction bound or peripheral stop")
            result["phases"].append({"name": label, "entry": address,
                                     "instructions": after["instructions"] - before["instructions"],
                                     "return_pc": after["pc"], "return_sp": sp})

        for address, label in ((0x9C58, "real_network_global_initializer"),
                               (0xB6A8, "real_output_ring_reset"), (0xB9D4, "real_input_ring_reset")):
            call(address, label)
        cpu.command("set memory xram 0x0012 0")
        cpu.command("set memory xram 0x071b 1")
        for index, value in enumerate(_INPUT):
            call(0xA457, f"real_input_ring_append_{index}", value)
        actual_input = bytes(cpu.value(f"xram[{0x5F7 + i}]") for i in range(len(_INPUT)))
        if (actual_input != _INPUT or cpu.value("xram[7]") != 0
                or cpu.value("xram[14]") != 6 or cpu.value("xram[21]") != 6):
            raise FirmwareRuntimeError("real input-ring append did not produce the verified fixture")
        call(0x0400, "real_dispatcher_dmy", 0)
        count = cpu.value("xram[19]") * 256 + cpu.value("xram[20]")
        if not 0 <= count <= 1500:
            raise FirmwareRuntimeError("invalid firmware output-ring count")
        actual_output = bytes(cpu.value(f"xram[{25 + i}]") for i in range(count))
        checks = {
            "output_exact": actual_output == _EXPECTED_OUTPUT,
            "output_count": count == len(_EXPECTED_OUTPUT),
            "input_consumed": cpu.value("xram[21]") == 0,
            "keepalive_side_effect": cpu.value("xram[0xa88]") == 1,
            "caller_mode": cpu.value("xram[0xa8f]") == 0,
            "connection_character": cpu.value("xram[15]") == 0x31,
            "stack_restored": cpu.value("sfr[0x81]") == 0x3E,
        }
        result.update({"input_hex": actual_input.hex(), "actual_output_hex": actual_output.hex(),
                       "checks": checks, "final_state": cpu.state()})
        if not all(checks.values()):
            raise FirmwareRuntimeError("firmware dispatcher result did not match the verified keepalive contract")
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
