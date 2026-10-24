# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline loading of user-supplied Platinum firmware, without device access.

Firmware is not distributed with this package. Inspecting or extracting an
image never runs it, flashes hardware, opens a socket, or enables a radio.
The Intel HEX address space is bounded to the observed 64 KiB code space.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile


MAX_HEX_BYTES = 2 * 1024 * 1024
CODE_SIZE = 65536
APK_IMAGES = {"gateway": "assets/HiMemGateway.hex", "bridge": "assets/LoMemBridge.hex"}


@dataclass(frozen=True)
class FirmwareImage:
    source: str
    ihex: bytes = field(repr=False)
    code: bytes = field(repr=False)
    mapped_addresses: frozenset[int] = field(repr=False)
    record_types: tuple[tuple[int, int], ...]
    entry_records: tuple[tuple[int, str], ...]

    @classmethod
    def parse(cls, data: bytes, *, source: str = "user-supplied Intel HEX"):
        if not isinstance(data, bytes) or not data or len(data) > MAX_HEX_BYTES:
            raise ValueError("Intel HEX input must be nonempty bytes within the size limit")
        memory, types, entries = {}, {}, []
        base, ended = 0, False
        for number, line in enumerate(data.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if ended:
                raise ValueError(f"Intel HEX data follows EOF at line {number}")
            if not re.fullmatch(rb":[0-9a-fA-F]+", line) or len(line) > 521:
                raise ValueError(f"invalid Intel HEX syntax at line {number}")
            try:
                record = bytes.fromhex(line[1:].decode("ascii"))
            except ValueError as exc:
                raise ValueError(f"invalid Intel HEX bytes at line {number}") from exc
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
                raise ValueError(f"invalid Intel HEX length/checksum at line {number}")
            count, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
            payload = record[4:-1]
            types[kind] = types.get(kind, 0) + 1
            if kind == 0:
                start = base + address
                if address + count > CODE_SIZE or start + count > CODE_SIZE:
                    raise ValueError("firmware data exceeds the 64 KiB code address space")
                for offset, value in enumerate(payload, start):
                    if offset in memory and memory[offset] != value:
                        raise ValueError("conflicting Intel HEX data records")
                    memory[offset] = value
            elif kind == 1:
                if count != 0 or address != 0:
                    raise ValueError("invalid Intel HEX EOF record")
                ended = True
            elif kind in (2, 4):
                if count != 2 or address != 0:
                    raise ValueError("invalid Intel HEX extended-address record")
                base = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
                if base >= CODE_SIZE:
                    raise ValueError("extended address exceeds the 64 KiB code address space")
            elif kind in (3, 5):
                if count != 4 or address != 0:
                    raise ValueError("invalid Intel HEX entry record")
                entries.append((kind, payload.hex()))
            else:
                raise ValueError(f"unsupported Intel HEX record type {kind}")
        if not ended or not memory:
            raise ValueError("firmware requires mapped data and an EOF record")
        code = bytearray(b"\xff" * (max(memory) + 1))
        for address, value in memory.items():
            code[address] = value
        return cls(str(source), data, bytes(code), frozenset(memory),
                   tuple(sorted(types.items())), tuple(entries))

    @classmethod
    def from_hex(cls, path):
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_HEX_BYTES + 1)
        return cls.parse(data, source=str(path))

    @classmethod
    def from_apk(cls, path, image="gateway"):
        if image not in APK_IMAGES:
            raise ValueError("firmware image must be gateway or bridge")
        asset = APK_IMAGES[image]
        try:
            with zipfile.ZipFile(path) as archive:
                matches = [item for item in archive.infolist() if item.filename == asset]
                if len(matches) != 1 or not 0 < matches[0].file_size <= MAX_HEX_BYTES:
                    raise ValueError("APK must contain one bounded selected firmware asset")
                with archive.open(matches[0]) as stream:
                    data = stream.read(MAX_HEX_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError("cannot read firmware from this APK archive") from exc
        return cls.parse(data, source=f"{path}:{asset}")

    def summary(self):
        versions = sorted({match.group().decode("ascii") for match in re.finditer(
            rb"HD (?:gateway|bridge) [0-9][0-9A-Za-z. -]{0,31}(?=\x00)", self.code)})
        reset = (int.from_bytes(self.code[1:3], "big")
                 if {0, 1, 2} <= self.mapped_addresses and self.code[0] == 2 else None)
        return {"source": self.source, "hex_sha256": hashlib.sha256(self.ihex).hexdigest(),
                "binary_sha256": hashlib.sha256(self.code).hexdigest(),
                "mapped_bytes": len(self.mapped_addresses), "binary_bytes": len(self.code),
                "unmapped_fill_byte": 255,
                "record_types": {str(kind): count for kind, count in self.record_types},
                "entry_records": [{"type": kind, "hex": value} for kind, value in self.entry_records],
                "embedded_version_labels": versions, "reset_ljmp_target": reset,
                "execution_performed": False, "device_access_performed": False}

    def extract(self, output_dir):
        """Write a new private directory; refuse to overwrite any prior result."""
        directory = Path(output_dir)
        directory.mkdir(mode=0o700)
        files = {"firmware.hex": self.ihex, "firmware.bin": self.code,
                 "manifest.private.json": (json.dumps(self.summary(), indent=2) + "\n").encode()}
        for name, data in files.items():
            descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        return self.summary()


def inspect_firmware(args):
    image = (FirmwareImage.from_apk(args.apk, args.image) if args.apk
             else FirmwareImage.from_hex(args.hex))
    result = image.extract(args.output_dir) if args.output_dir else image.summary()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
