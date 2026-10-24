# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline candidate-position tests with fictional identities; no radio access."""

from __future__ import annotations

import binascii
from collections import Counter
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.rf_iq import decode_iq_file
from hd_platinum.rf_positions import (
    PositionWaveformPlan,
    build_position_payloads,
    build_position_plan,
    iter_position_iq_chunks,
    write_position_waveform,
)
from hd_platinum.rf_waveform import (
    WaveformConfig,
    WaveformPlan,
    build_command_plan,
    build_frame_bits,
    iter_iq_chunks,
    write_waveform,
)

try:
    import numpy as np
    import scipy  # noqa: F401 -- the independent receive path needs SciPy
except ImportError:
    np = None


class PositionPlanTests(unittest.TestCase):
    def test_payload_modes_and_independent_crc_vectors(self) -> None:
        command, followup = build_position_payloads(bytes.fromhex("aabb"), 8, 128)
        self.assertEqual(command.hex(), "aabb500880")
        self.assertEqual(followup.hex(), "aabb320880")
        for payload, literal in ((command, "aae7e7e7aabb500880012a"),
                                 (followup, "aae7e7e7aabb320880f421")):
            bits = build_frame_bits(payload)
            wire = bytes(int("".join(str(x) for x in bits[n:n+8]), 2)
                         for n in range(0, len(bits), 8))
            self.assertEqual(wire.hex(), literal)
            self.assertEqual(binascii.crc_hqx(wire[1:9], 0xFFFF),
                             int.from_bytes(wire[9:11], "big"))

    def test_mask_is_one_hot_not_a_handheld_group_number(self) -> None:
        for mask in (1, 2, 4, 8, 16, 32, 64, 128):
            self.assertEqual(build_position_payloads(b"\xaa\xbb", mask, 255)[0][3], mask)
        for mask in (0, 3, 5, 127, 129, 255, -1, 256, True, 1.0, "8", b"\x08"):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                build_position_payloads(b"\xaa\xbb", mask, 255)
        for identity in (b"", b"a", b"abc", "aabb", 0xAABB, [0xAA, 0xBB]):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                build_position_payloads(identity, 8, 255)
        for position in (-1, 256, True, 1.0, "128", None):
            with self.subTest(position=position), self.assertRaises(ValueError):
                build_position_payloads(b"\xaa\xbb", 8, position)
        self.assertEqual(build_position_payloads(b"\xaa\xbb", 8, 0)[0][-1], 0)

    def test_default_duration_parameters_and_metadata_privacy(self) -> None:
        identity = bytearray.fromhex("aabb")
        plan = build_position_plan(identity, 8, 255)
        identity[0] = 0
        self.assertEqual(plan.command_payload.hex(), "aabb5008ff")
        self.assertEqual(plan.followup_payload.hex(), "aabb3208ff")
        self.assertEqual(plan.frame_count, 7575)
        self.assertEqual(plan.sample_count, 85_082_400)
        self.assertEqual(plan.duration_seconds, 1.77255)
        self.assertEqual(plan.config.sample_rate_hz, 48_000_000)
        self.assertEqual(plan.config.slot_us, 234)
        self.assertEqual(plan.config.deviation_hz, 320_000)
        self.assertEqual(plan.config.pulse_samples, 4560)
        self.assertNotIn("aabb", repr(plan))
        self.assertNotIn("aabb", json.dumps(plan.as_dict()))
        self.assertEqual(plan.as_dict()["command_payload"], "xxxx5008ff")
        self.assertTrue(plan.as_dict()["candidate_only"])
        self.assertIn("provisional", plan.as_dict()["model_note"])
        self.assertEqual(plan.as_dict(include_private=True)["command_payload"], "aabb5008ff")
        with self.assertRaises(ValueError):
            plan.as_dict(include_private="false")

    def test_plan_cannot_mix_identity_mask_position_or_modes(self) -> None:
        command, followup = build_position_payloads(b"\xaa\xbb", 8, 128)
        for bad_command, bad_followup in (
            (command, bytes.fromhex("ccdd320880")),
            (command, bytes.fromhex("aabb320180")),
            (command, bytes.fromhex("aabb3208ff")),
            (command, bytes.fromhex("aabb500880")),
            (bytes.fromhex("aabb200880"), followup),
            (bytes.fromhex("aabb500380"), bytes.fromhex("aabb320380")),
            ("aabb500880", followup),
            (command, b""),
        ):
            with self.subTest(command=bad_command, followup=bad_followup), self.assertRaises(ValueError):
                PositionWaveformPlan(WaveformConfig(), bad_command, bad_followup, 1, 1)
        with self.assertRaises(ValueError):
            PositionWaveformPlan(None, command, followup, 1, 1)

    def test_repetition_airtime_and_remote_plan_boundaries(self) -> None:
        for kwargs in ({"command_repetitions": 0}, {"command_repetitions": True},
                       {"command_repetitions": 1.5}, {"followup_repetitions": -1},
                       {"followup_repetitions": "425"},
                       {"command_repetitions": 3000, "followup_repetitions": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_position_plan(b"\xaa\xbb", 8, 255, **kwargs)
        position_plan = build_position_plan(b"\xaa\xbb", 8, 255,
                                            command_repetitions=1, followup_repetitions=0)
        remote_plan = build_command_plan("aabb", 1, "up", action_repetitions=1, release_repetitions=0)
        with self.assertRaises(ValueError):
            list(iter_iq_chunks(position_plan))
        with self.assertRaises(ValueError):
            list(iter_position_iq_chunks(remote_plan))
        with self.assertRaises(ValueError):
            WaveformPlan(position_plan.config, "up", position_plan.command_payload,
                         position_plan.followup_payload, 1, 1)


@unittest.skipIf(np is None, "optional NumPy/SciPy analysis dependencies are unavailable")
class PositionSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fictional-position.sc16q11"

    def test_three_channel_offline_roundtrip_counts_payloads_and_timing(self) -> None:
        plan = build_position_plan(b"\xaa\xbb", 8, 128,
                                   command_repetitions=2, followup_repetitions=1)
        metadata = write_position_waveform(self.path, plan, chunk_samples=997)
        result = decode_iq_file(self.path, sample_rate_hz=plan.config.sample_rate_hz,
            center_hz=plan.config.center_hz, channels_hz=plan.config.channels_hz,
            chunk_seconds=.001)
        self.assertEqual(result["frame_count"], 9)
        self.assertEqual(result["framing_counts"], {"shockburst": 9})
        self.assertEqual(Counter(f["payload_hex"] for f in result["frames"]),
                         {"aabb500880": 6, "aabb320880": 3})
        self.assertEqual([f["channel_hz"] for f in result["frames"]],
                         list(plan.config.channels_hz) * 3)
        for number, frame in enumerate(result["frames"]):
            self.assertAlmostEqual(frame["address_time_s"], (number*234 + 49 + 4)/1e6, delta=1e-6)
            expected = plan.command_payload if number < 6 else plan.followup_payload
            self.assertEqual(frame["payload_hex"], expected.hex())
            self.assertEqual(int(frame["crc_hex"], 16), binascii.crc_hqx(bytes.fromhex("e7e7e7")+expected, 0xFFFF))
        self.assertEqual(metadata["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(metadata["byte_count"], plan.sample_count * 4)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(metadata["command_payload"], "xxxx500880")

    def test_chunks_and_silent_intervals_do_not_depend_on_chunk_size(self) -> None:
        config = WaveformConfig(sample_rate_hz=8_000_000, channels_hz=(2_452_000_000,),
                                slot_us=234, deviation_hz=320_000)
        plan = build_position_plan(b"\xaa\xbb", 128, 0, config=config,
                                   command_repetitions=1, followup_repetitions=1)
        chunks = list(iter_position_iq_chunks(plan, chunk_samples=997))
        self.assertTrue(all(chunk.shape[1] == 2 and len(chunk) <= 997 for chunk in chunks))
        data = np.concatenate(chunks)
        self.assertEqual(len(data), plan.sample_count)
        self.assertLessEqual(int(abs(data).max()), 1024)
        for i in range(plan.frame_count):
            self.assertFalse(np.any(data[i*config.slot_samples+config.pulse_samples:(i+1)*config.slot_samples]))
        first = write_position_waveform(self.path, plan, chunk_samples=997)
        second = write_position_waveform(self.path, plan, overwrite=True, include_private=True)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["sha256"], hashlib.sha256(data.tobytes()).hexdigest())
        self.assertEqual(second["command_payload"], "aabb508000")

    def test_existing_artifact_and_flags_validated_before_writing(self) -> None:
        plan = build_position_plan(b"\xaa\xbb", 8, 255, command_repetitions=1, followup_repetitions=0)
        self.path.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            write_position_waveform(self.path, plan)
        for kwargs in ({"overwrite": "false"}, {"include_private": "false"}, {"chunk_samples": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                write_position_waveform(self.path, plan, **kwargs)
        with self.assertRaises(ValueError):
            write_waveform(self.path, plan, overwrite=True)
        with self.assertRaises(ValueError):
            write_position_waveform(self.path, build_command_plan("aabb", 1, "up"), overwrite=True)
        self.assertEqual(self.path.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
