# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline inspection of stopped, receive-only nRF52840 RAM captures.

No programmer, serial port or device is opened here. Structural failures raise
ValueError; readable captures retain their evidence even when quality checks
fail. A passing capture is packet-reception evidence, not shade acceptance.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass, field
from pathlib import Path
import struct


MAGIC = 0x58524E50
ABI_VERSION = 1
CONTROL_SIZE = 256
RECORD_SIZE = 32
CAPACITY = 4096
MAX_DURATION_US = 3_000_000
RAM_START, RAM_END = 0x20000000, 0x20040000
REVIEWED_VARIANT = 0x41414630  # AAF0, as an integer FICR register value.
CONTROL_FIELDS = (
    "magic", "abi_version", "control_size", "record_size", "capacity",
    "state", "error", "command", "channel", "duration_us", "expected_variant",
    "record_count", "crc_ok_count", "crc_error_count", "dropped_count",
    "radio_irq_count", "rx_attempt_count", "stop_reason", "stop_us", "last_end_us",
    "max_rearm_gap_us", "total_rearm_gap_us", "partial_at_stop", "late_end_count",
    "ficr_part", "ficr_variant", "ficr_package", "ficr_ram_kib", "ficr_flash_kib",
    "ficr_id0", "ficr_id1", "ficr_id2", "resetreas", "hfclkstat", "radio_state",
    "timer_hz", "records_address", "build_profile",
)
_RECORD = struct.Struct("<5I5s4B3s")


def _bytes(value, name):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(f"{name} must contain binary bytes")
    return bytes(value)


def decode_control(data: bytes) -> dict[str, int]:
    """Decode a version-1 control block, including idle/running diagnostics."""
    data = _bytes(data, "control")
    if len(data) != CONTROL_SIZE:
        raise ValueError("control block must contain exactly 256 bytes")
    words = struct.unpack("<64I", data)
    control = dict(zip(CONTROL_FIELDS, words))
    expected = {"magic": MAGIC, "abi_version": ABI_VERSION, "control_size": CONTROL_SIZE,
                "record_size": RECORD_SIZE, "capacity": CAPACITY}
    if any(control[key] != value for key, value in expected.items()):
        raise ValueError("unrecognized capture schema or fixed sizes")
    if any(words[len(CONTROL_FIELDS):]):
        raise ValueError("reserved control words must be zero")
    if control["state"] not in range(5) or control["error"] not in range(7):
        raise ValueError("unrecognized capture state or error")
    if control["stop_reason"] not in range(4):
        raise ValueError("unrecognized capture stop reason")
    if control["record_count"] > CAPACITY:
        raise ValueError("record count exceeds the bounded capture capacity")
    address = control["records_address"]
    if address % 4 or not RAM_START <= address <= RAM_END - CAPACITY * RECORD_SIZE:
        raise ValueError("record buffer must fit completely in aligned nRF52840 RAM")
    return control


@dataclass(frozen=True)
class NrfRecord:
    ordinal: int
    address_us: int
    end_us: int
    ready_us: int
    rx_crc: int = field(repr=False)
    payload: bytes = field(repr=False)
    crc_status: int
    rssi_sample: int
    flags: int
    rxmatch: int

    @property
    def computed_crc(self):
        return binascii.crc_hqx(b"\xe7\xe7\xe7" + self.payload, 0xFFFF)

    @property
    def crc_agrees(self):
        return self.crc_status in (0, 1) and bool(self.crc_status) == (self.rx_crc == self.computed_crc)

    @property
    def crc_valid(self):
        return self.crc_status == 1 and self.rx_crc == self.computed_crc


@dataclass(frozen=True)
class NrfCapture:
    control: dict[str, int] = field(repr=False)
    records: tuple[NrfRecord, ...] = field(repr=False)

    @property
    def checks(self) -> dict[str, bool]:
        c, rows = self.control, self.records
        gaps = [following.ready_us - prior.end_us for prior, following in zip(rows, rows[1:])]
        return {
            "terminal_success": c["state"] == 3 and c["error"] == 0 and c["stop_reason"] == 1,
            "configuration_valid": c["channel"] in (33, 52, 71)
                and 1 <= c["duration_us"] <= MAX_DURATION_US and c["timer_hz"] == 1_000_000,
            "profile_match": c["build_profile"] == 1 and c["ficr_part"] == 0x52840
                and c["ficr_variant"] == c["expected_variant"] == REVIEWED_VARIANT
                and c["ficr_id0"] == 8 and c["ficr_id1"] == 5
                and c["ficr_ram_kib"] == 256 and c["ficr_flash_kib"] == 1024,
            "clock_running": (c["hfclkstat"] & 0x10001) == 0x10001,
            "radio_disabled": c["radio_state"] == 0,
            "deadline_completed": c["duration_us"] <= c["stop_us"] <= c["duration_us"] + 1000,
            "no_truncation": c["dropped_count"] == c["partial_at_stop"] == c["late_end_count"] == 0
                and c["record_count"] < CAPACITY,
            "counter_totals": c["crc_ok_count"] == sum(r.crc_status == 1 for r in rows)
                and c["crc_error_count"] == sum(r.crc_status == 0 for r in rows)
                and c["crc_ok_count"] + c["crc_error_count"] == len(rows)
                and c["radio_irq_count"] >= len(rows) and c["rx_attempt_count"] >= len(rows),
            "ordinals_contiguous": all(r.ordinal == i for i, r in enumerate(rows)),
            "record_flags_known": all(r.flags & ~3 == 0 and r.crc_status in (0, 1) for r in rows),
            "address_observed": all(r.flags & 1 and r.rxmatch == 0 for r in rows),
            "timestamps_ordered": all(0 <= r.ready_us <= r.address_us < r.end_us <= c["duration_us"]
                                      for r in rows) and all(gap >= 0 for gap in gaps),
            "native_frame_duration": all(26 <= r.end_us - r.address_us <= 30 for r in rows),
            "last_end_matches": c["last_end_us"] == (rows[-1].end_us if rows else 0),
            "gap_metrics_consistent": c["max_rearm_gap_us"] == max(gaps, default=0)
                and c["total_rearm_gap_us"] == sum(gaps),
            "crc_checks_agree": all(r.rx_crc <= 0xFFFF and r.crc_agrees for r in rows),
        }

    @property
    def qualified(self) -> bool:
        """At least one accepted packet and all local capture checks passed."""
        return any(row.crc_valid for row in self.records) and all(self.checks.values())

    def as_dict(self, *, include_private=False) -> dict:
        if type(include_private) is not bool:
            raise ValueError("include_private must be a boolean")
        names = ("state", "error", "channel", "duration_us", "record_count", "crc_ok_count",
                 "crc_error_count", "dropped_count", "stop_reason", "stop_us", "max_rearm_gap_us",
                 "total_rearm_gap_us", "partial_at_stop", "late_end_count", "build_profile")
        result = {"schema": ABI_VERSION, "operation": "offline_native_packet_capture_review",
                  "qualified": self.qualified, "checks": self.checks,
                  "accepted_records": sum(row.crc_valid for row in self.records),
                  "control": {key: self.control[key] for key in names},
                  "private_data_included": include_private,
                  "scope": "Fixed-channel packet reception; not IQ, simultaneous hopping, or shade acceptance."}
        if include_private:
            result["control"] = dict(self.control)
            result["records"] = [dict(ordinal=r.ordinal, address_us=r.address_us, end_us=r.end_us,
                ready_us=r.ready_us, rx_crc=r.rx_crc, computed_crc=r.computed_crc,
                payload_hex=r.payload.hex(), crc_status=r.crc_status, rssi_sample=r.rssi_sample,
                rssi_valid=bool(r.flags & 2), flags=r.flags, rxmatch=r.rxmatch) for r in self.records]
        return result


def parse_capture(control: bytes, records: bytes) -> NrfCapture:
    """Parse a stopped capture; retain readable failed observations for review."""
    control = decode_control(control)
    if control["state"] not in (3, 4):
        raise ValueError("capture must be stopped in DONE or ERROR state before parsing records")
    records = _bytes(records, "records")
    used = control["record_count"] * RECORD_SIZE
    if len(records) not in (used, CAPACITY * RECORD_SIZE):
        raise ValueError("record dump must contain exactly the used records or full fixed buffer")
    if any(records[used:]):
        raise ValueError("unused record storage must be zero for a single-run capture")
    rows = []
    for offset in range(0, used, RECORD_SIZE):
        values = _RECORD.unpack_from(records, offset)
        if any(values[-1]):
            raise ValueError("reserved record bytes must be zero")
        rows.append(NrfRecord(*values[:-1]))
    return NrfCapture(control, tuple(rows))


def load_capture(control_path: str | Path, records_path: str | Path) -> NrfCapture:
    """Read bounded local dump files; this never opens debugger or serial ports."""
    control_path, records_path = Path(control_path), Path(records_path)
    with control_path.open("rb") as stream:
        control = stream.read(CONTROL_SIZE + 1)
    with records_path.open("rb") as stream:
        records = stream.read(CAPACITY * RECORD_SIZE + 1)
    return parse_capture(control, records)
