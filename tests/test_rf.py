# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest

from hd_platinum.rf import (
    REMOTE_FREQUENCIES_HZ,
    build_esb_candidate_frame,
    build_remote_payload,
    decode_remote_payload,
    groups_to_mask,
)


class RemotePayloadTests(unittest.TestCase):
    def test_known_group_one_up_payload(self) -> None:
        payload = build_remote_payload("03c1", 1, "up")
        self.assertEqual(payload.hex(), "03c12001a1")

        decoded = decode_remote_payload(payload)
        self.assertEqual(decoded.remote_id, bytes.fromhex("03c1"))
        self.assertEqual(decoded.mode, 0x20)
        self.assertEqual(decoded.groups, (1,))
        self.assertEqual(decoded.action, "up")

    def test_all_groups_down_and_release(self) -> None:
        self.assertEqual(build_remote_payload("aabb", "all", "down").hex(), "aabb20ffa2")
        release = decode_remote_payload("aabb20ff22")
        self.assertEqual(release.action, "release-down")
        self.assertTrue(release.is_all_groups)
        self.assertEqual(release.groups, (1, 2, 3, 4))

    def test_group_lists_and_explicit_hex_masks(self) -> None:
        self.assertEqual(groups_to_mask("1,3,4"), 0x0D)
        self.assertEqual(groups_to_mask("0x03"), 0x03)

    def test_invalid_payload_inputs(self) -> None:
        with self.assertRaises(ValueError):
            build_remote_payload("abc", 1, "up")
        with self.assertRaises(ValueError):
            build_remote_payload("aabb", 9, "up")
        with self.assertRaises(ValueError):
            decode_remote_payload("aabb")

    def test_channel_numbers_map_to_expected_frequencies(self) -> None:
        self.assertEqual(REMOTE_FREQUENCIES_HZ, (2_433_000_000, 2_452_000_000, 2_471_000_000))


class CandidateFrameTests(unittest.TestCase):
    def test_candidate_has_datasheet_consistent_pcf_length(self) -> None:
        payload = bytes.fromhex("03c12001a1")
        frame = build_esb_candidate_frame(payload, pid=2)

        self.assertEqual(frame.bit_length, 97)
        self.assertEqual(frame.bits[:8], (1, 0, 1, 0, 1, 0, 1, 0))
        self.assertEqual(frame.bits[8:32], tuple(int(bit) for bit in f"{0xE7E7E7:024b}"))
        self.assertEqual(frame.pcf_payload_length, 5)
        self.assertEqual(frame.pid, 2)
        self.assertEqual(frame.no_ack, 0)
        self.assertEqual(frame.crc, 0xB485)
        self.assertAlmostEqual(frame.duration_seconds * 1_000_000, 48.5)
        self.assertEqual(len(frame.packed), 13)

    def test_unresolved_static_pcf_bits_are_parameterized(self) -> None:
        payload = bytes.fromhex("03c12001a1")
        default = build_esb_candidate_frame(payload)
        zero_length = build_esb_candidate_frame(payload, pcf_payload_length=0)
        self.assertNotEqual(default.crc, zero_length.crc)
        self.assertNotEqual(default.bits, zero_length.bits)


if __name__ == "__main__":
    unittest.main()
