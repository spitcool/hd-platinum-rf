# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""End-to-end receiver checks using fictional, locally synthesized IQ only."""

from __future__ import annotations

import binascii
import json
from pathlib import Path
import tempfile
import unittest

from hd_platinum.rf_iq import decode_iq_file, redact_result

try:
    import numpy as np
    import scipy  # noqa: F401 -- the receiver needs both optional packages
except ImportError:
    np = None


# Fixed independent golden bytes; no production frame builder is used.
# binascii.crc_hqx verifies the CRC independently of the project's bitwise CRC.
FRAME = "".join(f"{b:08b}" for b in bytes.fromhex("aae7e7e7aabb2001a157f9"))
ESB_FRAME = (
    "10101010" "111001111110011111100111" "000101100"
    "1010101010111011001000000000000110100001" "0001110001000011"
)
GUARD = "10010010110101100"
CHANNEL = 2_452_000_000


@unittest.skipIf(np is None, "optional NumPy/SciPy analysis dependencies are unavailable")
class IQDecoderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fictional.sc16q11"

    def synthesize(self, packets, *, rate=8_000_000, center=CHANNEL,
                   channel=CHANNEL, cfo=0, polarity=1, seconds=.003,
                   guard=GUARD, noise=.5) -> None:
        """Generate continuous-phase FSK with arbitrary packet sample offsets.

        A known nonzero bit guard avoids silently relying on CRC zero-extension
        ambiguity in tests that are specifically about timing and polarity.
        Separate tests deliberately exercise that ambiguity.
        """
        samples_per_bit = rate // 2_000_000
        rng = np.random.default_rng(8128)
        total = round(seconds * rate)
        values = (rng.normal(0, noise, total) + 1j * rng.normal(0, noise, total))
        for start, bits in packets:
            offset = round(start * rate)
            symbols = np.array([1 if b == "1" else -1 for b in bits + guard])
            deviation = np.repeat(symbols, samples_per_bit) * (320_000 * polarity)
            frequency = deviation + (channel - center) + cfo
            phase = np.cumsum(frequency) * (2 * np.pi / rate)
            waveform = 700 * np.exp(1j * phase)
            count = min(len(waveform), total - offset)
            values[offset:offset + count] += waveform[:count]
        packed = np.column_stack((np.rint(values.real), np.rint(values.imag)))
        packed.astype("<i2").tofile(self.path)

    def decode(self, **kwargs):
        options = dict(sample_rate_hz=8_000_000, center_hz=CHANNEL,
                       channels_hz=(CHANNEL,), chunk_seconds=.001)
        options.update(kwargs)
        return decode_iq_file(self.path, **options)

    def test_literal_frame_with_carrier_offset_and_either_polarity(self) -> None:
        self.assertEqual(binascii.crc_hqx(bytes.fromhex("e7e7e7aabb2001a1"), 0xFFFF), 0x57F9)
        for polarity, cfo in ((1, 112_000), (-1, -108_000)):
            with self.subTest(polarity=polarity, cfo=cfo):
                self.synthesize([(.000247375, FRAME)], polarity=polarity, cfo=cfo)
                result = self.decode()
                self.assertEqual(result["frame_count"], 1)
                frame = result["frames"][0]
                self.assertEqual(frame["payload_hex"], "aabb2001a1")
                self.assertEqual(frame["crc_hex"], "57f9")
                self.assertEqual(frame["framing"], "shockburst")
                self.assertEqual(frame["frame_bits"], 88)
                self.assertEqual(frame["polarity"], polarity)
                self.assertEqual(frame["action"], "up")
                self.assertGreater(frame["detection_trials"], 1)
                self.assertAlmostEqual(frame["address_time_s"], .000251375, delta=1e-6)

    def test_off_center_decimation_and_overlapping_chunks_keep_each_frame_once(self) -> None:
        starts = (.00099625, .001996125)
        self.synthesize([(t, FRAME) for t in starts], rate=48_000_000,
                        center=CHANNEL, channel=2_471_000_000, cfo=-65_000)
        result = self.decode(sample_rate_hz=48_000_000, channels_hz=(2_471_000_000,))
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual([x["payload_hex"] for x in result["frames"]], ["aabb2001a1"] * 2)
        for frame, start in zip(result["frames"], starts):
            self.assertAlmostEqual(frame["address_time_s"], start + 4e-6, delta=1e-6)
            self.assertGreater(frame["detection_trials"], 1)
        # The interval selects by address time while padding supplies the
        # preamble and the remainder of a frame outside the requested interval.
        subset = self.decode(sample_rate_hz=48_000_000, channels_hz=(2_471_000_000,),
                             start_seconds=.00199, duration_seconds=.00002)
        self.assertEqual(subset["frame_count"], 1)
        self.assertAlmostEqual(subset["frames"][0]["address_time_s"], starts[1] + 4e-6, delta=1e-6)

    def test_esb_candidate_is_preserved_as_esb(self) -> None:
        self.synthesize([(.000323125, ESB_FRAME)])
        frames = self.decode()["frames"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["framing"], "esb")
        self.assertEqual(frames[0]["frame_bits"], 97)
        self.assertEqual(frames[0]["payload_hex"], "aabb2001a1")
        self.assertEqual(frames[0]["crc_hex"], "1c43")
        self.assertEqual(frames[0]["pid"], 2)

    def test_corruption_damaged_preamble_and_truncated_waveform_are_rejected(self) -> None:
        corrupted = FRAME[:44] + str(1 - int(FRAME[44])) + FRAME[45:]
        bad_preamble = "00000000" + FRAME[8:]
        for bits in (corrupted, bad_preamble):
            with self.subTest(bits=bits):
                self.synthesize([(.0002, bits)])
                self.assertEqual(self.decode()["frame_count"], 0)
        # A well-formed SC16 file can still end before the packet's CRC.
        self.synthesize([(.0002, FRAME)], seconds=.0002 + 80 / 2_000_000, guard="")
        self.assertEqual(self.decode()["frame_count"], 0)

    def test_no_signal_has_no_decodes(self) -> None:
        self.synthesize([])
        self.assertEqual(self.decode()["frame_count"], 0)

    def test_ambiguous_zero_extended_frame_is_retained_without_identity_leaks(self) -> None:
        self.synthesize([(.0002, FRAME + "000000000")])
        result = self.decode()
        self.assertEqual({f["framing"] for f in result["frames"]}, {"shockburst", "esb"})
        self.assertEqual(result["frame_count"], 2)
        public = redact_result(result)
        # In the alternative ESB parse, the first nine identity bits occupy
        # the presumed PCF. Redacting only two payload bytes leaks them.
        for frame in public["frames"]:
            for field in ("pcf_payload_length", "pid", "no_ack"):
                self.assertIn(frame.get(field), (None, "[redacted]"))
            for field in ("mode", "group_mask", "action_code"):
                self.assertIn("redacted", str(frame.get(field)))
            self.assertIn("redacted", frame["payload_hex"])
            self.assertEqual(frame["action"], "ambiguous-framing")
        self.assertEqual(public["action_counts"], {"ambiguous-framing": 2})
        self.assertNotIn("aabb", json.dumps(public))
        self.assertNotIn("57f9", json.dumps(public))
        self.assertNotEqual(result["frames"][0]["remote_id"], "[redacted]")

    def test_crc_zero_extension_requires_tail_carrier_support(self) -> None:
        # Exact silence must not cause the longer interpretation to be accepted.
        self.synthesize([(.0002, FRAME)], guard="", noise=0)
        result = self.decode()
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["frames"][0]["framing"], "shockburst")
        # Make the CRC ambiguity deterministic using a zero-bit residual tail
        # 26 dB below the packet. Its bits remain recoverable, but its power
        # cannot support the claimed longer packet. One percent amplitude is
        # too weak to survive the receive filter transition consistently.
        self.synthesize([(.0002, FRAME + "000000000")], guard="", noise=0)
        raw = np.fromfile(self.path, dtype="<i2").reshape(-1, 2)
        tail_start = round(.0002 * 8_000_000) + len(FRAME) * 4
        raw[tail_start:tail_start + 9 * 4] = np.rint(raw[tail_start:tail_start + 9 * 4] * .05)
        raw.tofile(self.path)
        result = self.decode()
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["frames"][0]["framing"], "shockburst")
        self.assertGreater(result["crc_candidate_count"], result["frame_count"])
        self.assertGreaterEqual(result["carrier_rejected_framing_counts"].get("esb", 0), 1)

    def test_regular_redaction_keeps_semantics_and_does_not_mutate_private_result(self) -> None:
        self.synthesize([(.0002, FRAME)])
        result = self.decode()
        before = json.dumps(result, sort_keys=True)
        public = redact_result(result)
        self.assertEqual(json.dumps(result, sort_keys=True), before)
        self.assertEqual(public["frames"][0]["payload_hex"], "xxxx2001a1")
        self.assertEqual(public["frames"][0]["remote_id"], "[redacted]")
        self.assertEqual(public["frames"][0]["crc_hex"], "[redacted]")
        self.assertEqual(public["frames"][0]["action"], "up")
        self.assertNotIn("aabb", json.dumps(public))

    def test_invalid_capture_and_frequency_parameters(self) -> None:
        for data in (b"", b"\x00", b"\x00" * 5):
            with self.subTest(data=data):
                self.path.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.decode()
        self.synthesize([])
        for options in (
            {"sample_rate_hz": 7_000_000}, {"sample_rate_hz": 8_000_001},
            {"sample_rate_hz": float("nan")}, {"center_hz": float("inf")},
            {"sample_rate_hz": 10 ** 1000}, {"sample_rate_hz": 264_000_000},
            {"channels_hz": ()}, {"channels_hz": (CHANNEL, CHANNEL)},
            {"channels_hz": (CHANNEL + 3_000_000,)},
            {"start_seconds": -1}, {"start_seconds": .003},
            {"start_seconds": 1e308},
            {"duration_seconds": 0}, {"duration_seconds": 1e-12},
            {"chunk_seconds": .0001}, {"chunk_seconds": 2},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.decode(**options)
        self.assertEqual(self.decode(duration_seconds=1e308)["duration_seconds"], .003)


if __name__ == "__main__":
    unittest.main()
