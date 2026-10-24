# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import binascii
import unittest

from hd_platinum.rf import bytes_to_bits, crc16_ccitt_bits
from hd_platinum.rf_frames import parse_frame, scan_frames


# Fictional identity aabb. The byte-aligned CRC is independently checkable with
# binascii.crc_hqx; the ESB CRC was calculated using polynomial long division.
# Keep literal frames so tests do not merely round-trip the production builder.
SHOCKBURST = "".join(f"{byte:08b}" for byte in bytes.fromhex("aae7e7e7aabb2001a157f9"))
ESB = (
    "10101010" "111001111110011111100111" "000101100"
    "1010101010111011001000000000000110100001" "0001110001000011"
)


class FrameParserTests(unittest.TestCase):
    def test_known_crc_vector_and_independent_byte_reference(self) -> None:
        self.assertEqual(crc16_ccitt_bits(bytes_to_bits(b"123456789")), 0x29B1)
        protected = bytes.fromhex("e7e7e7aabb2001a1")
        self.assertEqual(binascii.crc_hqx(protected, 0xFFFF), 0x57F9)
        self.assertEqual(crc16_ccitt_bits(bytes_to_bits(protected)), 0x57F9)

    def test_no_pcf_literal_frame(self) -> None:
        frames = scan_frames(SHOCKBURST, require_preamble=True)
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.framing, "shockburst")
        self.assertEqual(frame.payload.hex(), "aabb2001a1")
        self.assertEqual(frame.address_start_bit, 8)
        self.assertEqual(frame.frame_start_bit, 0)
        self.assertEqual(frame.frame_end_bit, 88)
        self.assertEqual(frame.frame_bit_length, 88)
        self.assertEqual(frame.crc_received, 0x57F9)
        self.assertTrue(frame.crc_valid)
        self.assertIsNone(frame.pcf_payload_length)
        self.assertIsNone(frame.pid)
        self.assertIsNone(frame.no_ack)

    def test_esb_literal_with_unaligned_payload(self) -> None:
        frames = scan_frames(ESB, require_preamble=True)
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.framing, "esb")
        self.assertEqual(frame.frame_bit_length, 97)
        self.assertEqual(frame.payload.hex(), "aabb2001a1")
        self.assertEqual(frame.pcf_payload_length, 5)
        self.assertEqual(frame.pid, 2)
        self.assertEqual(frame.no_ack, 0)
        self.assertEqual(frame.crc_received, 0x1C43)
        self.assertTrue(frame.crc_valid)

    def test_arbitrary_alignment_and_multiple_formats(self) -> None:
        data = "00101" + SHOCKBURST + "000" + ESB + "001"
        frames = scan_frames(int(bit) for bit in data)
        self.assertEqual([frame.framing for frame in frames], ["shockburst", "esb"])
        self.assertEqual([frame.frame_start_bit for frame in frames], [5, 96])
        self.assertEqual([frame.frame_end_bit for frame in frames], [93, 193])

    def test_payload_corruption_does_not_pass_crc(self) -> None:
        damaged = SHOCKBURST[:44] + str(1 - int(SHOCKBURST[44])) + SHOCKBURST[45:]
        self.assertEqual(scan_frames(damaged), ())
        frame = parse_frame(damaged, framing="shockburst")
        self.assertIsNotNone(frame)
        self.assertFalse(frame.crc_valid)
        diagnostic = scan_frames(damaged, include_invalid=True)
        self.assertEqual(len(diagnostic), 1)
        self.assertFalse(diagnostic[0].crc_valid)

    def test_wrong_framing_is_rejected(self) -> None:
        self.assertEqual(scan_frames(ESB, framings=("shockburst",)), ())
        frame = parse_frame(SHOCKBURST + "100100101", framing="esb")
        self.assertIsNotNone(frame)
        self.assertFalse(frame.crc_valid)

    def test_zero_extension_ambiguity_is_not_silently_resolved(self) -> None:
        # A valid CRC codeword followed by zeros remains divisible by the
        # polynomial. Carrier extent and fields must resolve this ambiguity.
        frames = scan_frames(SHOCKBURST + "000000000", require_preamble=True)
        self.assertEqual([frame.framing for frame in frames], ["esb", "shockburst"])
        self.assertEqual([frame.crc_received for frame in frames], [0xF200, 0x57F9])
        self.assertTrue(all(frame.crc_valid for frame in frames))

    def test_truncation_and_address_mismatch(self) -> None:
        for cut in (0, 8, 32, 72, 87):
            with self.subTest(cut=cut):
                self.assertEqual(scan_frames(SHOCKBURST[:cut]), ())
                self.assertIsNone(parse_frame(SHOCKBURST[:cut], framing="shockburst"))
        self.assertEqual(scan_frames(SHOCKBURST, address=b"\x01\x02\x03"), ())

    def test_preamble_missing_or_damaged_is_explicit(self) -> None:
        frame = scan_frames(SHOCKBURST[8:])[0]
        self.assertEqual(frame.address_start_bit, 0)
        self.assertEqual(frame.frame_start_bit, -8)
        self.assertIsNone(frame.preamble_matches)
        self.assertEqual(scan_frames(SHOCKBURST[8:], require_preamble=True), ())
        damaged = "00000000" + SHOCKBURST[8:]
        self.assertFalse(scan_frames(damaged)[0].preamble_matches)
        self.assertEqual(scan_frames(damaged, require_preamble=True), ())

    def test_invalid_inputs_are_rejected(self) -> None:
        for bits in ("010 1", "0102", (0, 1, 2), (0, 1.0), ("0", "1")):
            with self.subTest(bits=bits), self.assertRaises(ValueError):
                scan_frames(bits)
        for kwargs in (
            {"address": b"ab"}, {"address": 3}, {"payload_length": -1},
            {"payload_length": 33}, {"payload_length": 5.0},
            {"payload_length": True}, {"framings": ()}, {"framings": "esb"},
            {"framings": ("invalid",)}, {"framings": ("esb", "esb")},
            {"include_invalid": 1}, {"require_preamble": "yes"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                scan_frames(SHOCKBURST, **kwargs)
        for start in (-1, 0.5, True):
            with self.subTest(start=start), self.assertRaises(ValueError):
                parse_frame(SHOCKBURST, framing="shockburst", address_start_bit=start)
        with self.assertRaises(ValueError):
            parse_frame(SHOCKBURST, framing="other")


if __name__ == "__main__":
    unittest.main()
