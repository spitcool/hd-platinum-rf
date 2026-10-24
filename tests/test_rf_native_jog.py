# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline native Jog tests; only fictional identities and software signals."""

import binascii
from collections import Counter
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.rf_native_jog import (
    NativeJogPlan, build_native_jog_payloads, build_native_jog_plan,
    iter_native_jog_iq_chunks, write_native_jog_waveform,
)

try:
    import numpy as np
    import scipy  # noqa: F401 -- needed by the independent receive path
except ImportError:
    np = None


def fixture(**options):
    values = dict(prior_channel=71, prior_alternate=0,
                  held_frame_count=141, tail_frame_count=7, slot_us=200.5)
    values.update(options)
    return build_native_jog_plan(b"\x12\x34", 8, **values)


class NativeJogPlanTests(unittest.TestCase):
    def test_bodies_and_refresh_boundaries_from_original_code_contract(self):
        self.assertEqual(build_native_jog_payloads(b"\x12\x34", 8),
                         (bytes.fromhex("12346a0801"), bytes.fromhex("123420086a"),
                          bytes.fromhex("1234320801")))
        # Original AACC decrements before emission: the first run has one
        # fewer packet than subsequent runs. These boundaries are fixed
        # contract vectors, not derived from the planner's loop.
        for previous, boundaries in (
                (0, ((0, 19, "123420086a"), (19, 119, "12346a0801"),
                     (119, 139, "123420086a"), (139, 239, "12346a0801"),
                     (239, 259, "123420086a"), (259, 359, "12346a0801"))),
                (1, ((0, 99, "12346a0801"), (99, 119, "123420086a"),
                     (119, 219, "12346a0801"), (219, 239, "123420086a"),
                     (239, 339, "12346a0801"), (339, 359, "123420086a")))):
            with self.subTest(previous=previous):
                plan = fixture(prior_alternate=previous, held_frame_count=359, tail_frame_count=25)
                events = list(plan.iter_events())
                for start, end, expected in boundaries:
                    self.assertEqual({e.payload.hex() for e in events[start:end]}, {expected})
                self.assertEqual({e.payload.hex() for e in events[359:]}, {"1234320801"})
                self.assertEqual({e.phase for e in events[:359]}, {"held"})
                self.assertEqual({e.phase for e in events[359:]}, {"tail"})

    def test_channel_phase_carries_across_refresh_and_held_tail_boundaries(self):
        for prior, cycle in ((71, (2_433_000_000, 2_452_000_000, 2_471_000_000)),
                             (33, (2_452_000_000, 2_471_000_000, 2_433_000_000)),
                             (52, (2_471_000_000, 2_433_000_000, 2_452_000_000))):
            with self.subTest(prior=prior):
                events = list(fixture(prior_channel=prior, held_frame_count=140).iter_events())
                self.assertEqual([e.channel_hz for e in events], [cycle[i % 3] for i in range(147)])
                for index in (19, 119, 139, 140):
                    self.assertEqual(events[index].channel_hz, cycle[index % 3])
                self.assertEqual(events[140].phase, "tail")
                self.assertEqual([e.ordinal for e in events], list(range(147)))
                self.assertEqual([e.start_sample for e in events], [i * 9624 for i in range(147)])

    def test_explicit_inputs_strict_validation_and_immutable_target(self):
        with self.assertRaises(TypeError):
            build_native_jog_plan(b"\x12\x34", 8)
        for key in ("prior_channel", "prior_alternate", "held_frame_count", "tail_frame_count", "slot_us"):
            values = dict(prior_channel=71, prior_alternate=0, held_frame_count=1, tail_frame_count=1, slot_us=200.5)
            del values[key]
            with self.subTest(missing=key), self.assertRaises(TypeError):
                build_native_jog_plan(b"\x12\x34", 8, **values)
        invalid = {
            "prior_channel": (0, 34, 2433, 33.0, True, "33", None),
            "prior_alternate": (-1, 2, True, 0.0, "0", None),
            "held_frame_count": (-1, 0, True, 1.0, "1", None, 10001),
            "tail_frame_count": (-1, 0, True, 1.0, "1", None, 10001),
            "slot_us": (200, 234, True, "200.5", float("inf"), float("nan"), None),
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    fixture(**{key: value})
        for identity in (b"", b"a", b"abc", "1234", 0x1234, [0x12, 0x34]):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                build_native_jog_payloads(identity, 8)
        for mask in (0, 3, 127, 129, 255, True, 8.0, "8", None):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                build_native_jog_payloads(b"\x12\x34", mask)
        for mask in (1, 2, 4, 8, 16, 32, 64, 128):
            self.assertEqual(build_native_jog_payloads(b"\x12\x34", mask)[0][3], mask)
        identity = bytearray.fromhex("1234")
        plan = NativeJogPlan(identity, 8, 71, 0, 1, 1, 200.5)
        identity[0] = 0
        self.assertEqual(plan.room_rf_id, b"\x12\x34")

    def test_duration_bound_and_metadata_do_not_claim_physical_qualification(self):
        plan = fixture(held_frame_count=7500, tail_frame_count=1500)
        self.assertEqual((plan.sample_count, plan.duration_seconds), (86_616_000, 1.8045))
        metadata = plan.as_dict()
        self.assertEqual((metadata["held_seconds"], metadata["tail_seconds"]), (1.50375, .30075))
        self.assertTrue(metadata["phase_counts_are_assumed"] and metadata["candidate_only"])
        self.assertFalse(metadata["hardware_qualified"])
        self.assertIn("provisional", metadata["model_note"])
        self.assertEqual(metadata["main_payload"], "xxxx6a0801")
        self.assertNotIn("1234", json.dumps(metadata))
        self.assertNotIn("room_rf_id=", repr(plan))
        self.assertEqual(plan.as_dict(include_private=True)["main_payload"], "12346a0801")
        with self.assertRaises(ValueError):
            plan.as_dict(include_private="false")
        self.assertLessEqual(fixture(held_frame_count=9974, tail_frame_count=1).duration_seconds, 2)
        with self.assertRaisesRegex(ValueError, "two-second"):
            fixture(held_frame_count=9975, tail_frame_count=1)


@unittest.skipIf(np is None, "optional NumPy/SciPy analysis dependencies are unavailable")
class NativeJogSignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "fictional-jog.sc16q11"

    def test_written_three_channel_signal_decodes_with_independent_crc_and_timing(self):
        from hd_platinum.rf_iq import decode_iq_file
        plan = fixture()
        metadata = write_native_jog_waveform(self.path, plan, chunk_samples=10007)
        decoded = decode_iq_file(self.path, sample_rate_hz=48_000_000, center_hz=2_452_000_000,
            channels_hz=(2_433_000_000, 2_452_000_000, 2_471_000_000), chunk_seconds=.005)
        self.assertEqual(decoded["frame_count"], 148)
        self.assertEqual(decoded["framing_counts"], {"shockburst": 148})
        self.assertEqual(Counter(f["payload_hex"] for f in decoded["frames"]),
                         {"12346a0801": 102, "123420086a": 39, "1234320801": 7})
        # This receive path searches the written signal, not plan event bits.
        for index, frame in enumerate(decoded["frames"]):
            self.assertEqual(frame["channel_hz"], (2_433_000_000, 2_452_000_000, 2_471_000_000)[index % 3])
            self.assertAlmostEqual(frame["address_time_s"], (index * 200.5 + 49 + 4) / 1e6, delta=1e-6)
            expected = ("123420086a" if index < 19 or 119 <= index < 139
                        else "12346a0801" if index < 141 else "1234320801")
            self.assertEqual(frame["payload_hex"], expected)
            self.assertEqual(int(frame["crc_hex"], 16),
                             binascii.crc_hqx(bytes.fromhex("e7e7e7" + expected), 0xFFFF))
        self.assertEqual(metadata["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(metadata["byte_count"], plan.sample_count * 4)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_chunk_edges_silence_and_headroom_are_preserved(self):
        plan = fixture(held_frame_count=23, tail_frame_count=7)
        chunks = list(iter_native_jog_iq_chunks(plan, chunk_samples=997))
        self.assertTrue(all(c.dtype == np.dtype("<i2") and c.shape[1] == 2 and len(c) <= 997 for c in chunks))
        data = np.concatenate(chunks)
        self.assertEqual(len(data), plan.sample_count)
        self.assertLessEqual(int(np.abs(data).max()), 1024)
        self.assertGreater(int(np.abs(data).max()), 1000)
        for i in range(plan.frame_count):
            slot = data[i * 9624:(i + 1) * 9624]
            self.assertTrue(np.any(slot[:4560]))
            self.assertFalse(np.any(slot[4560:]))
        first = write_native_jog_waveform(self.path, plan, chunk_samples=997)
        second = write_native_jog_waveform(self.directory / "other.sc16q11", plan, chunk_samples=10007)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["sha256"], hashlib.sha256(data.tobytes()).hexdigest())
        # Large valid plans still produce bounded chunks lazily.
        stream = iter_native_jog_iq_chunks(fixture(held_frame_count=7500, tail_frame_count=1500), chunk_samples=997)
        self.assertEqual(next(stream).shape, (997, 2))
        stream.close()

    def test_invalid_arguments_and_existing_artifact_are_never_overwritten(self):
        plan = fixture(held_frame_count=1, tail_frame_count=1)
        self.path.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            write_native_jog_waveform(self.path, plan)
        for kwargs in ({"chunk_samples": 0}, {"chunk_samples": True},
                       {"chunk_samples": 1.5}, {"include_private": "false"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                write_native_jog_waveform(self.path, plan, **kwargs)
        with self.assertRaises(ValueError):
            write_native_jog_waveform(self.path, None)
        with self.assertRaises(ValueError):
            next(iter_native_jog_iq_chunks(None))
        self.assertEqual(self.path.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
