#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Send gateway console commands through Wokwi's local RFC2217 server."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import time
import zlib

DEFAULT_URL = "rfc2217://127.0.0.1:4000"
MAX_LINE = 131080
STATUS = re.compile(r"storage=(?:ok|FAULT) network=(?:up|down) mode=(?:radio|simulation) "
                    r"busy=[01] rooms=\d+ shades=\d+")


def inventory_hex(executable: Path) -> str:
    result = subprocess.run([str(executable.expanduser().resolve())], check=True,
                            capture_output=True, timeout=10)
    output = result.stdout.decode("ascii").strip()
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){12,65536}", output):
        raise ValueError("Inventory executable must emit exactly one PGW1 hexadecimal line")
    data = bytes.fromhex(output)
    if data[:4] != b"PGW1" or zlib.crc32(data[:-4]) != int.from_bytes(data[-4:], "little"):
        raise ValueError("Inventory executable emitted an invalid PGW1 record or checksum")
    return output


def command_bytes(command: str) -> bytes:
    encoded = command.encode("utf-8")
    if not encoded or any(value in encoded for value in (b"\r", b"\n", b"\0")):
        raise ValueError("Pass exactly one nonempty command without line breaks or NUL bytes")
    if len(encoded) > MAX_LINE:
        raise ValueError("Command exceeds the firmware's serial line limit")
    return encoded + b"\n"


def is_reply(command: str, line: str) -> bool:
    if line.startswith("error:"):
        return True
    if command == "status":
        return STATUS.fullmatch(line) is not None
    if command == "export":
        return re.fullmatch(r"50475731(?:[0-9a-fA-F]{2})+", line) is not None
    return line == "ok" or line.startswith(("ok:", "commands:"))


class Console:
    def __init__(self, port):
        self.port = port
        self.pending = bytearray()

    def exchange(self, command: str, timeout: float, retry_status=False) -> str:
        payload = command_bytes(command)
        deadline = time.monotonic() + timeout
        retry_at = time.monotonic()
        sent = False
        while time.monotonic() < deadline:
            now = time.monotonic()
            if not sent or (retry_status and now >= retry_at):
                self.port.write(payload)
                sent = True
                retry_at = now + 1
            while b"\n" in self.pending:
                raw, _, remaining = self.pending.partition(b"\n")
                self.pending = bytearray(remaining)
                if len(raw) > MAX_LINE:
                    raise ValueError("Serial reply exceeds the firmware's line limit")
                line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
                if is_reply(command, line):
                    return line
            if len(self.pending) > MAX_LINE:
                raise ValueError("Serial reply exceeds the firmware's line limit")
            self.pending.extend(self.port.read(min(max(self.port.in_waiting, 1), 4096)))
        raise TimeoutError("No gateway reply. Keep the running Wokwi tab visible and check "
                           'the board attribute serialInterface="USB_SERIAL_JTAG".')


def positive_seconds(value: str) -> float:
    result = float(value)
    if not 0 < result <= 300:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 300 seconds")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run a gateway USB console command in the running Wokwi simulator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples (from the repository root):
  .venv/bin/python firmware/esp32_gateway/tools/wokwi_serial.py status
  .venv/bin/python firmware/esp32_gateway/tools/wokwi_serial.py 'services 1 1 1'
  .venv/bin/python firmware/esp32_gateway/tools/wokwi_serial.py export
  .venv/bin/python firmware/esp32_gateway/tools/wokwi_serial.py --inventory tmp/esp32-native-tests/sample_inventory

--inventory runs the native sample_inventory executable, validates its PGW1
record, sends 'import HEX' once, waits for 'ok', then prints the new status.
Import replaces the simulator's inventory. Other commands are sent once after
a read-only status handshake; only the handshake may be retried during boot.
Firmware errors and timeouts produce a nonzero exit status.

Wokwi setup:
  In [wokwi] in wokwi.toml: rfc2217ServerPort = 4000
  ESP32-S3 board attrs: "serialInterface": "USB_SERIAL_JTAG"
  Remove $serialMonitor connections and keep the simulator tab visible.
  Start the simulator before running this helper. PySerial is in the repo .venv.

Official configuration and USB routing documentation:
  https://docs.wokwi.com/vscode/project-config#serial-port-forwarding
  https://docs.wokwi.com/guides/esp32#usb-cdc-serial-over-usb-support
""")
    result.add_argument("command", nargs="?", help="one quoted console command (default: status)")
    result.add_argument("--inventory", type=Path, metavar="EXECUTABLE",
                        help="import the PGW1 hex output from sample_inventory")
    result.add_argument("--url", default=DEFAULT_URL, help=f"PySerial port URL (default: {DEFAULT_URL})")
    result.add_argument("--timeout", type=positive_seconds, default=15,
                        help="seconds to wait for each firmware reply (default: 15)")
    return result


def main(argv=None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.inventory and args.command is not None:
        arguments.error("--inventory and a console command cannot be used together")
    try:
        import serial
    except ImportError:
        print("error: PySerial is required; run this helper with the repository's .venv/bin/python", file=sys.stderr)
        return 1
    try:
        command = "import " + inventory_hex(args.inventory) if args.inventory else (args.command or "status")
        command_bytes(command)  # Validate before connecting or sending anything.
        # RFC2217 in PySerial 3.5 does not support write_timeout. The socket has
        # its own network timeout; the short read timeout bounds reply polling.
        with serial.serial_for_url(args.url, baudrate=115200, timeout=0.1) as port:
            console = Console(port)
            ready = console.exchange("status", args.timeout, retry_status=True)
            if ready.startswith("error:"):
                print(ready)
                return 1
            reply = ready if command == "status" else console.exchange(command, args.timeout)
            print(reply)
            if reply.startswith("error:"):
                return 1
            if args.inventory:
                if reply != "ok":
                    raise ValueError("Firmware did not acknowledge the inventory import")
                status = console.exchange("status", args.timeout)
                print(status)
                if status.startswith("error:"):
                    return 1
        return 0
    except (OSError, ValueError, TimeoutError, subprocess.SubprocessError, serial.SerialException) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
