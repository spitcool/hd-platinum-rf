# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline transmitter tests; no radio is opened and all identities are fictional."""

from __future__ import annotations

import binascii
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hd_platinum.rf_iq import decode_iq_file
from hd_platinum.rf_waveform import (
    WaveformConfig,
    WaveformPlan,
    build_command_plan,
    build_frame_bits,
    iter_iq_chunks,
    synthesize_frame,
    write_waveform,
)

try:
    import numpy as np
    import scipy  # noqa: F401 -- independent receive validation needs SciPy
except ImportError:
    np = None


class WaveformPlanTests(unittest.TestCase):
    def test_frame_matches_literal_independent_crc_vector(self) -> None:
        bits = build_frame_bits(bytes.fromhex("aabb2001a1"))
        packed = bytes(int("".join(str(bit) for bit in bits[k:k+8]), 2)
                       for k in range(0, len(bits), 8))
        self.assertEqual(len(bits), 88)
        self.assertEqual(packed.hex(), "aae7e7e7aabb2001a157f9")
        self.assertEqual(binascii.crc_hqx(packed[1:-2], 0xFFFF), int.from_bytes(packed[-2:], "big"))

    def test_default_count_duration_and_redacted_plan(self) -> None:
        plan = build_command_plan("aabb", 1, "up")
        self.assertEqual(plan.frame_count, 3000)
        self.assertEqual(plan.sample_count, 28_080_000)
        self.assertEqual(plan.duration_seconds, .585)
        self.assertEqual(plan.config.pulse_samples, 4560)
        self.assertEqual(plan.action_payload.hex(), "aabb2001a1")
        self.assertEqual(plan.release_payload.hex(), "aabb200121")
        self.assertNotIn("aabb", json.dumps(plan.as_dict()))
        self.assertNotIn("aabb", repr(plan))
        self.assertEqual(plan.as_dict(include_private=True)["action_payload"], "aabb2001a1")
        self.assertIn("provisional", plan.as_dict()["model_note"])

    def test_airtime_repetition_and_configuration_limits(self) -> None:
        for kwargs in (
            {"action_repetitions": 0}, {"action_repetitions": True},
            {"action_repetitions": 1.5}, {"release_repetitions": -1},
            {"action_repetitions": 3500, "release_repetitions": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_command_plan("aabb", 1, "up", **kwargs)
        for kwargs in (
            {"sample_rate_hz": 8_000_001}, {"sample_rate_hz": 80_000_000},
            {"gaussian_bt": 0}, {"deviation_hz": float("nan")},
            {"amplitude": 1}, {"max_airtime_seconds": 2.01},
            {"slot_us": 50}, {"lead_in_us": 1, "ramp_us": 2},
            {"channels_hz": ()}, {"channels_hz": (2_452_000_000,) * 2},
            {"channels_hz": (2_440_000_000,)},
            {"sample_rate_hz": 8_000_000},  # cannot span all three channels
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                WaveformConfig(**kwargs)

    def test_plan_cannot_mix_identity_or_action_between_press_and_release(self) -> None:
        for action_payload, release_payload in (
            ("aabb2001a1", "ccdd200121"),
            ("aabb2001a1", "aabb200222"),
            ("aabb2001a2", "aabb200122"),
        ):
            with self.subTest(payload=release_payload), self.assertRaises(ValueError):
                WaveformPlan(WaveformConfig(), "up", bytes.fromhex(action_payload),
                             bytes.fromhex(release_payload), 1, 1)
        for payload in (b"", b"1234", b"123456", "aabb2001a1"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                build_frame_bits(payload)
        with self.assertRaises(ValueError):
            build_command_plan("aabb", 1, "release-up")
        with self.assertRaises(ValueError):
            build_command_plan("aabb", 1, "up").as_dict(include_private="false")


@unittest.skipIf(np is None, "optional NumPy/SciPy analysis dependencies are unavailable")
class WaveformSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fictional.sc16q11"

    def decode(self, path, plan):
        return decode_iq_file(path, sample_rate_hz=plan.config.sample_rate_hz,
                              center_hz=plan.config.center_hz,
                              channels_hz=plan.config.channels_hz,
                              chunk_seconds=.001)

    def test_single_channel_gaussian_pulse_and_complete_crc(self) -> None:
        pulse = synthesize_frame(bytes.fromhex("aabb2001a1"))
        self.assertEqual(pulse.dtype, np.dtype("complex64"))
        self.assertEqual(len(pulse), 760)  # 49 + 44 + 2 microseconds at 8 MS/s
        self.assertEqual(pulse[0], 0)
        self.assertEqual(pulse[-1], 0)
        self.assertLessEqual(float(abs(pulse).max()), .500001)
        config = WaveformConfig(sample_rate_hz=8_000_000, channels_hz=(2_452_000_000,))
        plan = build_command_plan("aabb", 1, "up", config=config,
                                  action_repetitions=1, release_repetitions=0)
        write_waveform(self.path, plan)
        result = self.decode(self.path, plan)
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["frames"][0]["payload_hex"], "aabb2001a1")
        self.assertEqual(result["frames"][0]["crc_hex"], "57f9")
        self.assertEqual(result["frames"][0]["polarity"], 1)

    def test_three_channel_hopping_press_and_release_decode_end_to_end(self) -> None:
        for action in ("up", "down"):
            with self.subTest(action=action):
                plan = build_command_plan("aabb", 1, action,
                    action_repetitions=2, release_repetitions=1)
                write_waveform(self.path, plan, overwrite=True)
                result = self.decode(self.path, plan)
                self.assertEqual(result["frame_count"], 9)
                self.assertEqual(result["framing_counts"], {"shockburst": 9})
                self.assertEqual(result["action_counts"], {action: 6, "release-" + action: 3})
                self.assertEqual([f["channel_hz"] for f in result["frames"]],
                                 list(plan.config.channels_hz) * 3)
                for number, frame in enumerate(result["frames"]):
                    expected_time = (number * 195 + 49 + 4) / 1_000_000
                    self.assertAlmostEqual(frame["address_time_s"], expected_time, delta=1e-6)
                    expected_payload = plan.action_payload if number < 6 else plan.release_payload
                    self.assertEqual(frame["payload_hex"], expected_payload.hex())
                    self.assertEqual(int(frame["crc_hex"], 16),
                        binascii.crc_hqx(bytes.fromhex("e7e7e7") + expected_payload, 0xFFFF))

    def test_wrong_identity_negative_control_changes_decoded_identity(self) -> None:
        results = []
        digests = []
        for identity in ("aabb", "ccdd"):
            plan = build_command_plan(identity, "all", "down",
                action_repetitions=1, release_repetitions=1)
            artifact = write_waveform(self.path, plan, overwrite=True)
            result = self.decode(self.path, plan)
            self.assertEqual(result["frame_count"], 6)
            self.assertEqual({f["remote_id"] for f in result["frames"]}, {identity})
            self.assertTrue(all(f["group_mask"] == 255 for f in result["frames"]))
            public_fields = {key: value for key, value in artifact.items() if key != "sha256"}
            self.assertNotIn(identity, json.dumps(public_fields))
            results.append([f["payload_hex"] for f in result["frames"]])
            digests.append(artifact["sha256"])
        self.assertNotEqual(results[0], results[1])
        self.assertNotEqual(digests[0], digests[1])

    def test_chunk_boundaries_preserve_samples_silence_and_hash(self) -> None:
        plan = build_command_plan("aabb", 1, "up", action_repetitions=1, release_repetitions=1)
        chunks = list(iter_iq_chunks(plan, chunk_samples=997))
        self.assertTrue(all(x.shape[1] == 2 and len(x) <= 997 for x in chunks))
        values = np.concatenate(chunks)
        self.assertEqual(values.shape, (plan.sample_count, 2))
        self.assertLessEqual(int(abs(values).max()), 1024)
        for slot in range(plan.frame_count):
            start = slot * plan.config.slot_samples + plan.config.pulse_samples
            end = (slot + 1) * plan.config.slot_samples
            self.assertFalse(np.any(values[start:end]))
        metadata = write_waveform(self.path, plan, chunk_samples=997)
        self.assertEqual(self.path.stat().st_size, plan.sample_count * 4)
        self.assertEqual(metadata["sha256"], hashlib.sha256(values.tobytes()).hexdigest())
        alternate = Path(self.directory.name) / "different-chunks.sc16q11"
        self.assertEqual(write_waveform(alternate, plan)["sha256"], metadata["sha256"])

    def test_existing_artifacts_and_privacy_flags_are_protected(self) -> None:
        plan = build_command_plan("aabb", 1, "up", action_repetitions=1, release_repetitions=0)
        self.path.write_bytes(b"keep-existing-artifact")
        with self.assertRaises(FileExistsError):
            write_waveform(self.path, plan)
        self.assertEqual(self.path.read_bytes(), b"keep-existing-artifact")
        for flags in ({"overwrite": "false"}, {"include_private": "false"}, {"chunk_samples": 0}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                write_waveform(self.path, plan, **flags)
        self.assertEqual(self.path.read_bytes(), b"keep-existing-artifact")


if __name__ == "__main__":
    unittest.main()
