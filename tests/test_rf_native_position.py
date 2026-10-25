# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline native position tests with fictional identities and written signals."""

import binascii
from collections import Counter
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.rf_native_position import (
    NativePositionPlan, build_native_position_plan,
    iter_native_position_iq_chunks, write_native_position_waveform,
)
from hd_platinum.rf_positions import build_position_plan, write_position_waveform

try:
    import numpy as np
    import scipy  # noqa: F401 -- independent receive path needs SciPy
except ImportError:
    np = None


def fixture(**options):
    values = dict(prior_channel=71, command_frame_count=101,
                  followup_frame_count=8, slot_us=200.5)
    values.update(options)
    return build_native_position_plan(b"\x12\x34", 8, 128, **values)


class NativePositionPlanTests(unittest.TestCase):
    def test_original_position_vectors_stay_fixed_through_long_phases(self):
        # Original feature-04 phase-2/phase-3 builder vectors. Its loader disables
        # the Jog refresh path, so the body stays fixed throughout each phase.
        for mask, position, command, followup in (
                (1, 0, "1234500100", "1234320100"),
                (8, 128, "1234500880", "1234320880"),
                (128, 255, "12345080ff", "12343280ff")):
            with self.subTest(mask=mask, position=position):
                plan = build_native_position_plan(b"\x12\x34", mask, position,
                    prior_channel=71, command_frame_count=301,
                    followup_frame_count=201, slot_us=200.5)
                self.assertEqual(plan.command_payload.hex(), command)
                self.assertEqual(plan.followup_payload.hex(), followup)
                events = list(plan.iter_events())
                self.assertEqual({e.payload.hex() for e in events[:301]}, {command})
                self.assertEqual({e.payload.hex() for e in events[301:]}, {followup})
                self.assertEqual([e.phase for e in events], ["command"] * 301 + ["followup"] * 201)

    def test_channel_rotation_does_not_restart_at_noncycle_phase_boundary(self):
        for prior, cycle in ((71, (2_433_000_000, 2_452_000_000, 2_471_000_000)),
                             (33, (2_452_000_000, 2_471_000_000, 2_433_000_000)),
                             (52, (2_471_000_000, 2_433_000_000, 2_452_000_000))):
            for command_count in (1, 2, 100, 101):
                with self.subTest(prior=prior, command_count=command_count):
                    events = list(fixture(prior_channel=prior,
                        command_frame_count=command_count).iter_events())
                    count = command_count + 8
                    self.assertEqual([e.channel_hz for e in events], [cycle[i % 3] for i in range(count)])
                    self.assertEqual([e.ordinal for e in events], list(range(count)))
                    self.assertEqual([e.start_sample for e in events], [i * 9624 for i in range(count)])
                    self.assertEqual(events[command_count - 1].phase, "command")
                    self.assertEqual(events[command_count].phase, "followup")

    def test_all_scheduling_inputs_required_and_invalid_values_rejected(self):
        with self.assertRaises(TypeError):
            build_native_position_plan(b"\x12\x34", 8, 128)
        for key in ("prior_channel", "command_frame_count", "followup_frame_count", "slot_us"):
            values = dict(prior_channel=71, command_frame_count=1,
                          followup_frame_count=1, slot_us=200.5)
            del values[key]
            with self.subTest(missing=key), self.assertRaises(TypeError):
                build_native_position_plan(b"\x12\x34", 8, 128, **values)
        invalid = {
            "prior_channel": (0, 34, 2433, 33.0, True, "33", None),
            "command_frame_count": (-1, 0, True, 1.0, "1", None, 10001),
            "followup_frame_count": (-1, 0, True, 1.0, "1", None, 10001),
            "slot_us": (200, 234, True, "200.5", float("inf"), float("nan"), None),
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    fixture(**{key: value})
        for identity in (b"", b"a", b"abc", "1234", 0x1234, [0x12, 0x34]):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                NativePositionPlan(identity, 8, 128, 71, 1, 1, 200.5)
        for mask in (0, 3, 127, 129, 255, True, 8.0, "8", None):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                NativePositionPlan(b"\x12\x34", mask, 128, 71, 1, 1, 200.5)
        for position in (-1, 256, True, 1.0, "128", None):
            with self.subTest(position=position), self.assertRaises(ValueError):
                NativePositionPlan(b"\x12\x34", 8, position, 71, 1, 1, 200.5)

    def test_private_identity_is_immutable_and_redacted_without_qualification_claims(self):
        identity = bytearray.fromhex("1234")
        plan = NativePositionPlan(identity, 8, 128, 71, 1, 1, 200.5)
        identity[0] = 0
        self.assertEqual(plan.room_rf_id, b"\x12\x34")
        self.assertEqual(plan.command_payload.hex(), "1234500880")
        with self.assertRaises(FrozenInstanceError):
            plan.position = 255
        metadata = plan.as_dict()
        self.assertEqual(metadata["command_payload"], "xxxx500880")
        self.assertEqual(metadata["followup_payload"], "xxxx320880")
        self.assertNotIn("1234", json.dumps(metadata))
        self.assertNotIn("room_rf_id=", repr(plan))
        self.assertNotIn("payload=", repr(next(plan.iter_events())))
        self.assertTrue(metadata["candidate_only"] and metadata["phase_counts_are_assumed"])
        self.assertTrue(metadata["idle_start_assumed"])
        self.assertEqual(metadata["initial_phase"], 2)
        self.assertFalse(metadata["hardware_qualified"] or metadata["prelude_included"])
        self.assertIn("provisional", metadata["model_note"])
        self.assertEqual(plan.as_dict(include_private=True)["command_payload"], "1234500880")
        with self.assertRaises(ValueError):
            plan.as_dict(include_private="false")

    def test_duration_cap_counts_packets_once_and_includes_final_gap(self):
        plan = fixture(command_frame_count=7500, followup_frame_count=1500)
        self.assertEqual((plan.frame_count, plan.sample_count, plan.duration_seconds),
                         (9000, 86_616_000, 1.8045))
        metadata = plan.as_dict()
        self.assertEqual((metadata["command_seconds"], metadata["followup_seconds"]), (1.50375, .30075))
        self.assertEqual(metadata["sample_rate_hz"], 48_000_000)
        self.assertEqual(metadata["center_hz"], 2_452_000_000)
        self.assertLessEqual(fixture(command_frame_count=9974, followup_frame_count=1).duration_seconds, 2)
        with self.assertRaisesRegex(ValueError, "two-second"):
            fixture(command_frame_count=9975, followup_frame_count=1)


@unittest.skipIf(np is None, "optional NumPy/SciPy analysis dependencies are unavailable")
class NativePositionSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "fictional-position.sc16q11"

    def test_written_signal_decodes_with_independent_payload_crc_channel_and_timing(self):
        from hd_platinum.rf_iq import decode_iq_file
        plan = fixture(prior_channel=33)
        metadata = write_native_position_waveform(self.path, plan, chunk_samples=10007)
        decoded = decode_iq_file(self.path, sample_rate_hz=48_000_000, center_hz=2_452_000_000,
            channels_hz=(2_433_000_000, 2_452_000_000, 2_471_000_000), chunk_seconds=.005)
        self.assertEqual(decoded["frame_count"], 109)
        self.assertEqual(decoded["framing_counts"], {"shockburst": 109})
        self.assertEqual(Counter(f["payload_hex"] for f in decoded["frames"]),
                         {"1234500880": 101, "1234320880": 8})
        for ordinal, frame in enumerate(decoded["frames"]):
            self.assertEqual(frame["channel_hz"], (2_452_000_000, 2_471_000_000, 2_433_000_000)[ordinal % 3])
            self.assertAlmostEqual(frame["address_time_s"], (ordinal * 200.5 + 49 + 4) / 1e6, delta=1e-6)
            expected = "1234500880" if ordinal < 101 else "1234320880"
            self.assertEqual(frame["payload_hex"], expected)
            self.assertEqual(int(frame["crc_hex"], 16),
                             binascii.crc_hqx(bytes.fromhex("e7e7e7" + expected), 0xFFFF))
        self.assertEqual(metadata["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(metadata["byte_count"], plan.sample_count * 4)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(metadata["command_payload"], "xxxx500880")

    def test_chunk_edges_do_not_change_signal_and_large_plan_remains_lazy(self):
        plan = fixture(command_frame_count=5, followup_frame_count=4)
        chunks = list(iter_native_position_iq_chunks(plan, chunk_samples=997))
        self.assertTrue(all(c.dtype == np.dtype("<i2") and c.shape[1] == 2 and len(c) <= 997 for c in chunks))
        data = np.concatenate(chunks)
        self.assertEqual(len(data), 86_616)
        self.assertLessEqual(int(np.abs(data).max()), 1024)
        self.assertGreater(int(np.abs(data).max()), 1000)
        for ordinal in range(9):
            slot = data[ordinal * 9624:(ordinal + 1) * 9624]
            self.assertTrue(np.any(slot[:4560]))
            self.assertFalse(np.any(slot[4560:]))
        first = write_native_position_waveform(self.path, plan, chunk_samples=997)
        second = write_native_position_waveform(self.directory / "other.sc16q11", plan, chunk_samples=10007)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["sha256"], hashlib.sha256(data.tobytes()).hexdigest())
        stream = iter_native_position_iq_chunks(
            fixture(command_frame_count=7500, followup_frame_count=1500), chunk_samples=997)
        self.assertEqual(next(stream).shape, (997, 2))
        stream.close()

    def test_existing_paths_and_other_plan_types_are_rejected_before_writing(self):
        plan = fixture(command_frame_count=1, followup_frame_count=1)
        self.path.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            write_native_position_waveform(self.path, plan)
        link = self.directory / "link.sc16q11"
        link.symlink_to(self.path)
        with self.assertRaises(FileExistsError):
            write_native_position_waveform(link, plan)
        for kwargs in ({"chunk_samples": 0}, {"chunk_samples": True},
                       {"chunk_samples": 1.5}, {"chunk_samples": 4_194_305},
                       {"include_private": "false"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                write_native_position_waveform(self.path, plan, **kwargs)
        sequential = build_position_plan(b"\x12\x34", 8, 128)
        for invalid in (None, sequential):
            with self.subTest(invalid=type(invalid)), self.assertRaises(ValueError):
                write_native_position_waveform(self.path, invalid)
            with self.subTest(invalid=type(invalid)), self.assertRaises(ValueError):
                next(iter_native_position_iq_chunks(invalid))
        with self.assertRaises(ValueError):
            write_position_waveform(self.path, plan)
        self.assertEqual(self.path.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
