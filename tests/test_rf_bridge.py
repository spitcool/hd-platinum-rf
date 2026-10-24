# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Synthetic identities only; no installation captures or hardware."""
from dataclasses import replace
from functools import reduce
import hashlib
import json
import operator
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.bridge import JogCommand, PositionCommand, ShadeConfig, SyncCommand
from hd_platinum.rf_bridge import (
    BURST_START_SAMPLES, DURATION_SECONDS, LEAD_SAMPLES, SAMPLE_COUNT,
    build_bridge_plan, build_esb_bits, build_position_payload, build_sequence_payload,
    build_jog_payload, build_sync_payload, render_bridge_iq, write_bridge_waveform,
)
from hd_platinum.rf_frames import parse_frame

try:
    import numpy as np
except ImportError:
    np = None
try:
    import scipy.signal
except ImportError:
    scipy = None


def command(position=128):
    return PositionCommand(3, position, ShadeConfig("Test shade", 2, b"\x12\x34", 8,
                                                   position_enabled=True), "test-request")


class BridgePacketTests(unittest.TestCase):
    @unittest.skipIf(np is None, "analysis extra not installed")
    def test_jog_encodes_rf_value_one_and_written_samples_recover_all_frames(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
        request = JogCommand(3, target, "jog-request")
        payload = build_jog_payload(target.room_rf_id, target.mask)
        self.assertEqual(payload[:11], bytes.fromhex("010a023412340c08010001"))
        self.assertEqual(reduce(operator.xor, payload[1:]), 255)
        plan = build_bridge_plan(request, 256)
        self.assertEqual(plan.as_dict()["operation"], "jog")
        raw = render_bridge_iq(plan)
        iq = raw[:, 0].astype(float) + 1j * raw[:, 1].astype(float)
        hz = np.angle(iq[1:] * iq[:-1].conj()) * 8e6 / (2 * np.pi)
        for index, frame in enumerate(plan.frames):
            centers = frame.preamble_sample + np.arange(len(frame.bits)) * 32 + 16
            bits = "".join("1" if np.mean(hz[c - 8:c + 8]) > 0 else "0" for c in centers)
            parsed = parse_frame(bits, framing="esb", payload_length=len(frame.payload))
            self.assertTrue(parsed.crc_valid)
            self.assertEqual(bits, "".join(map(str, frame.bits)))
            self.assertEqual(parsed.payload, payload if index % 2 == 0 else build_sequence_payload(256, 4 - index // 2))
        with self.assertRaises(ValueError):
            build_bridge_plan(replace(request, target=replace(target, jog_enabled=False)), 256)
        with self.assertRaises(ValueError):
            build_position_payload(target.room_rf_id, target.mask, 0, feature=12)

    def test_sync_has_distinct_observed_flags_and_separate_enablement(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, sync_enabled=True)
        request = SyncCommand(3, target, "sync-request")
        payload = build_sync_payload(target.room_rf_id, target.mask)
        self.assertEqual(payload[:11], bytes.fromhex("010a023412340108000003"))
        self.assertEqual(reduce(operator.xor, payload[1:]), 255)
        plan = build_bridge_plan(request, 256)
        self.assertEqual(plan.as_dict()["operation"], "sync")
        for index, frame in enumerate(plan.frames):
            parsed = parse_frame(frame.bits, framing="esb", payload_length=len(frame.payload))
            self.assertTrue(parsed.crc_valid)
            self.assertEqual(parsed.payload, payload if index % 2 == 0
                             else build_sequence_payload(256, 4 - index // 2))
        with self.assertRaises(ValueError):
            build_bridge_plan(replace(request, target=replace(target, sync_enabled=False)), 256)
        with self.assertRaises(ValueError):
            build_bridge_plan(PositionCommand(3, 0, target, "disabled-position"), 256)
        # The position encoder cannot accidentally synthesize a sync by changing
        # only the feature and retaining position flags 01.
        with self.assertRaises(ValueError):
            build_position_payload(target.room_rf_id, target.mask, 0, feature=1)

    def test_payload_fields_and_integrity_across_boundaries(self):
        for position in (0, 128, 255):
            long = build_position_payload(b"\x12\x34", 8, position)
            self.assertEqual(long[:8], bytes.fromhex("010a023412340408"))
            self.assertEqual(long[8:11], bytes((position, 0, 1)))
            self.assertEqual(reduce(operator.xor, long[1:]), 255)
        for sequence in (0, 255, 256, 511, 512, 65535):
            for count in range(5):
                short = build_sequence_payload(sequence, count)
                self.assertEqual(short[:4], bytes.fromhex("01070238"))
                self.assertEqual(short[4:8], bytes((1, sequence & 255, count, 6)))
                self.assertEqual(reduce(operator.xor, short[1:]), 255)

    def test_command_count_stays_one_when_transaction_counter_wraps(self):
        # Original ROM builder, executed with fictional fixtures and stopped
        # before its radio-send entry, independently produced these packets.
        # Release increments only an eight-bit counter: FF -> 00, count stays1.
        expected = {
            255: "0107023801ff04063e",
            256: "0107023801000406c1",
            511: "0107023801ff04063e",
            512: "0107023801000406c1",
            65535: "0107023801ff04063e",
        }
        for ordinal, payload_hex in expected.items():
            with self.subTest(ordinal=ordinal):
                plan = build_bridge_plan(command(), ordinal)
                self.assertEqual(plan.frames[1].payload.hex(), payload_hex)
                metadata = plan.as_dict()
                self.assertEqual(metadata["sequence"], ordinal)
                self.assertEqual(metadata["command_count"], 1)
                self.assertEqual(metadata["transaction_counter"], ordinal & 255)
                for frame in plan.frames:
                    parsed = parse_frame(frame.bits, framing="esb", payload_length=len(frame.payload))
                    self.assertTrue(parsed.crc_valid)
                self.assertEqual(tuple(frame.start_sample for frame in plan.frames), BURST_START_SAMPLES)
        self.assertEqual(build_sequence_payload(0, 4), build_sequence_payload(256, 4))

    def test_full_esb_frames_parse_with_captured_lengths_and_pid_cycle(self):
        plan = build_bridge_plan(command(), 256)
        self.assertEqual(len(plan.frames), 10)
        for i, frame in enumerate(plan.frames):
            decoded = parse_frame(frame.bits, framing="esb", payload_length=len(frame.payload))
            self.assertTrue(decoded.crc_valid)
            self.assertTrue(decoded.preamble_matches)
            self.assertEqual(decoded.payload, frame.payload)
            self.assertEqual((decoded.pid, decoded.no_ack), (i % 4, 0))
            self.assertEqual(frame.preamble_sample, BURST_START_SAMPLES[i] + LEAD_SAMPLES)
            if i % 2:
                self.assertEqual(frame.payload[6], 4 - i // 2)

    def test_invalid_fields_and_disabled_targets_are_rejected(self):
        for mask in (0, 3, 256, True):
            with self.assertRaises(ValueError):
                build_position_payload(b"\x12\x34", mask, 0)
        for value in (-1, 256, True):
            with self.assertRaises(ValueError):
                build_position_payload(b"\x12\x34", 8, value)
        with self.assertRaises(ValueError):
            build_position_payload(b"\x12", 8, 0)
        with self.assertRaises(ValueError):
            build_position_payload(b"\x12\x34", 8, 0, feature=5)
        for value in (-1, 65536, True):
            with self.assertRaises(ValueError):
                build_sequence_payload(value, 4)
        with self.assertRaises(ValueError):
            build_esb_bits(b"short", 0)
        with self.assertRaises(ValueError):
            build_bridge_plan(replace(command(), target=replace(command().target, position_enabled=False)), 0)

    def test_public_metadata_does_not_expose_identity_or_payload(self):
        value = build_bridge_plan(command(), 42).as_dict()
        self.assertNotIn("frames", value)
        self.assertNotIn("1234", json.dumps(value))
        self.assertNotIn("Test shade", json.dumps(value))

    def test_emitted_metadata_scales_indices_without_mutating_plan_or_revealing_frames(self):
        plan = build_bridge_plan(command(), 256)
        source = plan.as_dict(include_private=True)
        emitted = plan.as_dict(include_private=True, sample_rate_hz=32_000_000)
        self.assertEqual(emitted["sample_count"], SAMPLE_COUNT * 4)
        self.assertEqual(emitted["source_sample_count"], SAMPLE_COUNT)
        self.assertEqual(emitted["source_sample_rate_hz"], 8_000_000)
        self.assertEqual(emitted["duration_seconds"], source["duration_seconds"])
        self.assertEqual(emitted["burst_start_samples"], [value * 4 for value in BURST_START_SAMPLES])
        for original, scaled in zip(source["frames"], emitted["frames"]):
            self.assertEqual(scaled, {**original, "start_sample": original["start_sample"] * 4,
                                     "preamble_sample": original["preamble_sample"] * 4})
        self.assertEqual(plan.as_dict(include_private=True), source)
        public = plan.as_dict(sample_rate_hz=32_000_000)
        self.assertNotIn("frames", public)
        self.assertNotIn("1234", json.dumps(public))
        self.assertNotIn("Test shade", json.dumps(public))

    def test_unsupported_sample_rates_fail_before_creating_a_file(self):
        plan = build_bridge_plan(command(), 256)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.sc16q11"
            for rate in (None, True, 8_000_000.0, 16_000_000, 48_000_000, 0):
                with self.subTest(rate=rate):
                    with self.assertRaises(ValueError):
                        plan.as_dict(sample_rate_hz=rate)
                    with self.assertRaises(ValueError):
                        render_bridge_iq(plan, sample_rate_hz=rate)
                    with self.assertRaises(ValueError):
                        write_bridge_waveform(path, plan, sample_rate_hz=rate)
                    self.assertFalse(path.exists())

    @unittest.skipIf(np is None or scipy is None, "analysis extra not installed")
    def test_32ms_written_iq_retains_packets_timing_flat_lead_and_quiet_support(self):
        plan = build_bridge_plan(command(), 256)
        original = render_bridge_iq(plan)
        # Golden hash of the previously exercised default renderer, using only
        # this fictional fixture. Optional wide synthesis must not change it.
        self.assertEqual(hashlib.sha256(original.tobytes()).hexdigest(),
                         "a6c5f34233699eb7b316f328eb7b56ebe3019f377d30f5fe29bfe77fc05ea51f")
        self.assertTrue(np.array_equal(original, render_bridge_iq(plan, sample_rate_hz=8_000_000)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wide.sc16q11"
            result = write_bridge_waveform(path, plan, sample_rate_hz=32_000_000)
            raw = np.fromfile(path, dtype="<i2").reshape(-1, 2)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_size, SAMPLE_COUNT * 4 * 4)
            self.assertEqual(result["sha256"], hashlib.sha256(raw.tobytes()).hexdigest())
            self.assertEqual(result["sample_count"], len(raw))
            self.assertEqual(result["sample_rate_hz"], 32_000_000)
            self.assertEqual(result["duration_seconds"], DURATION_SECONDS)
            self.assertNotIn("frames", result)
            with self.assertRaises(FileExistsError):
                write_bridge_waveform(path, plan, sample_rate_hz=32_000_000)
        self.assertTrue(np.array_equal(raw[::4], original))
        iq = raw[:, 0].astype(float) + 1j * raw[:, 1].astype(float)
        hz = np.angle(iq[1:] * iq[:-1].conj()) * 32e6 / (2 * np.pi)
        active = np.zeros(len(raw), dtype=bool)
        for frame in plan.frames:
            preamble = frame.preamble_sample * 4
            centers = preamble + np.arange(len(frame.bits)) * 128 + 64
            bits = "".join("1" if np.mean(hz[c - 32:c + 32]) > 0 else "0" for c in centers)
            decoded = parse_frame(bits, framing="esb", payload_length=len(frame.payload))
            self.assertTrue(decoded.crc_valid)
            self.assertEqual(bits, "".join(map(str, frame.bits)))
            self.assertEqual((decoded.pid, decoded.no_ack), (frame.pid, frame.no_ack))
            self.assertLess(abs(float(np.mean(hz[preamble - 120:preamble - 80]))), 2000)
            active[frame.start_sample * 4:(frame.preamble_sample + len(frame.bits) * 32 + 104) * 4] = True
        self.assertFalse(np.any(raw[~active]))
        self.assertLess(int(np.max(raw)), 2047)
        self.assertGreater(int(np.min(raw)), -2048)
        self.assertLess(float(np.max(np.abs(iq))) / 2048, .502)

    @unittest.skipIf(np is None, "analysis extra not installed")
    def test_written_waveform_independently_demodulates_and_preserves_silence(self):
        plan = build_bridge_plan(command(), 256)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "waveform.sc16q11"
            result = write_bridge_waveform(path, plan)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_size, SAMPLE_COUNT * 4)
            self.assertEqual(result["duration_seconds"], DURATION_SECONDS)
            with self.assertRaises(FileExistsError):
                write_bridge_waveform(path, plan)
            raw = np.fromfile(path, dtype="<i2").reshape(-1, 2)
        iq = raw[:, 0].astype(float) + 1j * raw[:, 1].astype(float)
        hz = np.angle(iq[1:] * iq[:-1].conj()) * 8e6 / (2 * np.pi)
        active = np.zeros(len(raw), dtype=bool)
        for frame in plan.frames:
            centers = frame.preamble_sample + np.arange(len(frame.bits)) * 32 + 16
            bits = "".join("1" if np.mean(hz[c - 8:c + 8]) > 0 else "0" for c in centers)
            decoded = parse_frame(bits, framing="esb", payload_length=len(frame.payload))
            self.assertTrue(decoded.crc_valid)
            self.assertEqual(decoded.payload, frame.payload)
            self.assertEqual(decoded.pid, frame.pid)
            # Flat center carrier, including the final full symbol before AA.
            self.assertLess(abs(float(np.mean(hz[frame.preamble_sample - 30:frame.preamble_sample - 20]))), 2000)
            active[frame.start_sample:frame.preamble_sample + len(frame.bits) * 32 + 104] = True
        self.assertFalse(np.any(raw[~active]))
        self.assertLessEqual(int(np.max(np.abs(raw))), 1024)


if __name__ == "__main__":
    unittest.main()
