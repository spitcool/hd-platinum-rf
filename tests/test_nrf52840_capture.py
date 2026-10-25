# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Independent binary fixtures for the receive-only RAM capture ABI.

The fixtures transcribe the C wire layout rather than using the parser's
constants or serializers. All packet identities are fictional.
"""

import json
from pathlib import Path
import struct
import tempfile
import unittest

from hd_platinum.nrf52840_capture import decode_control, load_capture, parse_capture


OFFSETS = {
    "magic": 0, "abi_version": 4, "control_size": 8, "record_size": 12,
    "capacity": 16, "state": 20, "error": 24, "command": 28,
    "channel": 32, "duration_us": 36, "expected_variant": 40,
    "record_count": 44, "crc_ok_count": 48, "crc_error_count": 52,
    "dropped_count": 56, "radio_irq_count": 60, "rx_attempt_count": 64,
    "stop_reason": 68, "stop_us": 72, "last_end_us": 76,
    "max_rearm_gap_us": 80, "total_rearm_gap_us": 84,
    "partial_at_stop": 88, "late_end_count": 92, "ficr_part": 96,
    "ficr_variant": 100, "ficr_package": 104, "ficr_ram_kib": 108,
    "ficr_flash_kib": 112, "ficr_id0": 116, "ficr_id1": 120,
    "ficr_id2": 124, "resetreas": 128, "hfclkstat": 132,
    "radio_state": 136, "timer_hz": 140, "records_address": 144,
    "build_profile": 148,
}


def control(**changes):
    values = dict(
        magic=0x58524E50, abi_version=1, control_size=256, record_size=32,
        capacity=4096, state=3, error=0, command=0, channel=52,
        duration_us=3_000_000, expected_variant=0x41414630, record_count=3,
        crc_ok_count=2, crc_error_count=1, dropped_count=0, radio_irq_count=4,
        rx_attempt_count=4, stop_reason=1, stop_us=3_000_000, last_end_us=2231,
        max_rearm_gap_us=140, total_rearm_gap_us=280, partial_at_stop=0,
        late_end_count=0, ficr_part=0x52840, ficr_variant=0x41414630,
        ficr_package=0x2004, ficr_ram_kib=256, ficr_flash_kib=1024,
        ficr_id0=8, ficr_id1=5, ficr_id2=0, resetreas=4, hfclkstat=0x10001,
        radio_state=0, timer_hz=1_000_000, records_address=0x20008000,
        build_profile=1,
    )
    values.update(changes)
    output = bytearray(256)
    for name, value in values.items():
        struct.pack_into("<I", output, OFFSETS[name], value)
    return bytes(output)


def record(ordinal=0, *, address_us=1000, end_us=1028, ready_us=140,
           rx_crc=0xA722, payload=bytes.fromhex("12346a0801"),
           crc_status=1, rssi_sample=45, flags=3, rxmatch=0):
    return struct.pack("<5I5s4B3x", ordinal, address_us, end_us, ready_us,
                       rx_crc, payload, crc_status, rssi_sample, flags, rxmatch)


def records(**first_changes):
    # CRC literals were independently calculated with the bitwise 0x1021
    # recurrence over E7 E7 E7 followed by the five payload bytes, init FFFF.
    return b"".join((
        record(**first_changes),
        record(1, address_us=1602, end_us=1630, ready_us=1168,
               rx_crc=0xA083, payload=bytes.fromhex("123420086a")),
        record(2, address_us=2203, end_us=2231, ready_us=1770,
               rx_crc=0, payload=bytes.fromhex("1234320801"), crc_status=0),
    ))


class NrfCaptureTests(unittest.TestCase):
    def test_independent_layout_and_mixed_hardware_crc_results(self):
        raw = records()
        self.assertEqual(len(raw), 96)
        self.assertEqual(raw[20:25], bytes.fromhex("12346a0801"))
        capture = parse_capture(control(), raw)
        self.assertTrue(capture.qualified, capture.checks)
        self.assertEqual([row.computed_crc for row in capture.records],
                         [0xA722, 0xA083, 0x504D])
        self.assertEqual([row.crc_valid for row in capture.records], [True, True, False])
        self.assertTrue(all(row.crc_agrees for row in capture.records))
        self.assertEqual(capture.records[1].address_us, 1602)
        self.assertEqual(capture.control["records_address"], 0x20008000)

    def test_hardware_software_crc_disagreement_retains_evidence(self):
        cases = ((1, 0), (0, 0xA722), (1, 0x1A722))
        for status, crc in cases:
            with self.subTest(status=status, crc=crc):
                data = records(crc_status=status, rx_crc=crc)
                header = control(crc_ok_count=1 + status, crc_error_count=2 - status)
                capture = parse_capture(header, data)
                self.assertFalse(capture.qualified)
                self.assertFalse(capture.records[0].crc_agrees)
                self.assertEqual(capture.records[0].rx_crc, crc)
                self.assertEqual(len(capture.records), 3)

    def test_missing_rssi_is_explicit_and_does_not_invent_a_valid_measurement(self):
        capture = parse_capture(control(), records(flags=1))
        self.assertTrue(capture.qualified, capture.checks)
        self.assertFalse(capture.as_dict(include_private=True)["records"][0]["rssi_valid"])

    def test_readable_record_faults_are_retained_but_never_qualified(self):
        bad_rows = (
            {"ordinal": 7}, {"ready_us": 1001}, {"address_us": 1028},
            {"end_us": 1050}, {"end_us": 3_000_001},
            {"flags": 2}, {"flags": 7}, {"rxmatch": 1}, {"crc_status": 2},
        )
        for changes in bad_rows:
            with self.subTest(changes=changes):
                capture = parse_capture(control(), records(**changes))
                self.assertFalse(capture.qualified)
                self.assertEqual(len(capture.records), 3)

    def test_stopped_faults_configuration_and_counter_mismatches_fail_qualification(self):
        bad_controls = (
            {"state": 4, "error": 5, "stop_reason": 3}, {"error": 5},
            {"stop_reason": 2}, {"dropped_count": 1}, {"partial_at_stop": 1},
            {"late_end_count": 1}, {"channel": 34}, {"duration_us": 0},
            {"duration_us": 3_000_001}, {"timer_hz": 16_000_000},
            {"expected_variant": 0x41414631}, {"ficr_part": 0x52832},
            {"ficr_id0": 7}, {"ficr_id1": 4}, {"build_profile": 2},
            {"hfclkstat": 0x10000}, {"radio_state": 3}, {"stop_us": 2_999_999},
            {"crc_ok_count": 3}, {"crc_error_count": 0}, {"radio_irq_count": 2},
            {"rx_attempt_count": 2}, {"last_end_us": 2230},
            {"max_rearm_gap_us": 139}, {"total_rearm_gap_us": 279},
        )
        for changes in bad_controls:
            with self.subTest(changes=changes):
                capture = parse_capture(control(**changes), records())
                self.assertFalse(capture.qualified)
                self.assertEqual(len(capture.records), 3)

    def test_zero_record_and_error_capture_do_not_prove_receiver_success(self):
        values = dict(record_count=0, crc_ok_count=0, crc_error_count=0,
                      last_end_us=0, max_rearm_gap_us=0, total_rearm_gap_us=0)
        for changes in ({}, {"state": 4, "error": 3, "stop_reason": 3}):
            with self.subTest(changes=changes):
                capture = parse_capture(control(**values, **changes), b"")
                self.assertFalse(capture.qualified)
                self.assertEqual(capture.records, ())

    def test_ready_and_running_blocks_are_inspectable_but_not_completed_captures(self):
        for state in (0, 1, 2):
            with self.subTest(state=state):
                data = control(state=state)
                self.assertEqual(decode_control(data)["state"], state)
                with self.assertRaises(ValueError):
                    parse_capture(data, records())

    def test_structural_failures_reject_before_interpreting_records(self):
        bad_controls = (
            {"magic": 0}, {"abi_version": 2}, {"control_size": 128},
            {"record_size": 31}, {"capacity": 8192}, {"record_count": 4097},
            {"state": 5}, {"error": 7}, {"stop_reason": 4},
            {"records_address": 0x20008001}, {"records_address": 0x20030000},
            {"records_address": 0x10008000},
        )
        for changes in bad_controls:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_capture(control(**changes), records())
        for data in (control()[:-1], control() + b"\0", "not binary", None):
            with self.subTest(data_type=type(data)), self.assertRaises(ValueError):
                decode_control(data)
        reserved = bytearray(control())
        reserved[152] = 1
        with self.assertRaises(ValueError):
            decode_control(reserved)

    def test_record_lengths_unused_storage_and_reserved_bytes_are_strict(self):
        raw = records()
        full = raw + bytes(4096 * 32 - len(raw))
        self.assertTrue(parse_capture(control(), full).qualified)
        for data in (raw[:-1], raw + b"\0", full + b"\0", full[:-1] + b"x", None):
            with self.subTest(size=len(data) if data is not None else None), self.assertRaises(ValueError):
                parse_capture(control(), data)
        reserved = bytearray(raw)
        reserved[29] = 1
        with self.assertRaises(ValueError):
            parse_capture(control(), reserved)

    def test_completed_capacity_stop_is_retained_and_incomplete(self):
        raw = b"".join(record(i, address_us=1000 + i * 602,
                              end_us=1028 + i * 602, ready_us=140 + i * 602)
                       for i in range(4096))
        capture = parse_capture(control(record_count=4096, crc_ok_count=4096,
            crc_error_count=0, stop_reason=2, last_end_us=1028 + 4095 * 602,
            rx_attempt_count=4096, radio_irq_count=4096), raw)
        self.assertEqual(len(capture.records), 4096)
        self.assertFalse(capture.qualified)

    def test_public_summary_and_repr_do_not_disclose_packet_payloads(self):
        capture = parse_capture(control(), records())
        public = json.dumps(capture.as_dict())
        self.assertNotIn("12346a0801", public)
        self.assertNotIn("payload", public)
        self.assertNotIn("records_address", public)
        self.assertNotIn("payload", repr(capture.records[0]))
        private = capture.as_dict(include_private=True)
        self.assertEqual(private["records"][0]["payload_hex"], "12346a0801")
        self.assertEqual(private["accepted_records"], 2)
        with self.assertRaises(ValueError):
            capture.as_dict(include_private=1)

    def test_local_file_loading_stays_within_fixed_abi_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            header_path = Path(directory) / "control.bin"
            records_path = Path(directory) / "records.bin"
            header_path.write_bytes(control())
            records_path.write_bytes(records())
            self.assertTrue(load_capture(header_path, records_path).qualified)
            records_path.write_bytes(bytes(4096 * 32 + 1))
            with self.assertRaises(ValueError):
                load_capture(header_path, records_path)


if __name__ == "__main__":
    unittest.main()
