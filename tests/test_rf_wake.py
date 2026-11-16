# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fictional RF-only wake experiments; never open RF hardware."""

import binascii
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.cli import main
from hd_platinum.rf import build_wake_payload, decode_remote_payload
from hd_platinum.rf_native_position import (
    build_native_position_plan, iter_native_position_iq_chunks,
    write_native_position_waveform,
)
from hd_platinum.rf_waveform import build_frame_bits

try:
    import numpy as np
    import scipy
except ImportError:
    np = None


def fixture(**options):
    settings = dict(prior_channel=71, command_frame_count=4,
        followup_frame_count=5, slot_us=200.5)
    settings.update(options)
    return build_native_position_plan(bytes.fromhex("1234"), 8, 128, **settings)


class WakePlanTests(unittest.TestCase):
    def test_wake_vector_and_scoped_decoder_interpretation(self):
        payload = build_wake_payload("1234")
        self.assertEqual(payload.hex(), "1234010080")
        bits = build_frame_bits(payload)
        packed = bytes(int("".join(map(str, bits[i:i+8])), 2) for i in range(0, 88, 8))
        self.assertEqual(packed.hex(), "aae7e7e71234010080c4b8")
        self.assertEqual(binascii.crc_hqx(packed[1:-2], 0xffff), 0xc4b8)
        self.assertEqual(decode_remote_payload(payload).action, "wake")
        self.assertEqual(decode_remote_payload("1234010000").action, "release-wake")
        for value in ("1234200080", "1234300880", "1234010880", "1234500880"):
            self.assertEqual(decode_remote_payload(value).action, "unknown-0x80")

    def test_prefix_preserves_command_body_counts_channels_and_spacing(self):
        for prior in (33, 52, 71):
            baseline = list(fixture(prior_channel=prior).iter_events())
            for mode, body in (("wake", "1234010080"), ("command-control", "1234500880")):
                plan = fixture(prior_channel=prior, preparation=mode, preparation_frame_count=6)
                events = list(plan.iter_events())
                self.assertEqual([e.phase for e in events], [mode]*6 + ["command"]*4 + ["followup"]*5)
                self.assertEqual({e.payload.hex() for e in events[:6]}, {body})
                self.assertEqual([(e.channel_hz, e.payload) for e in events[6:]],
                                 [(e.channel_hz, e.payload) for e in baseline])
                self.assertEqual([e.start_sample for e in events], [i*9624 for i in range(15)])
                public = plan.as_dict()
                self.assertEqual(public["preparation_payload"], "xxxx" + body[4:])
                self.assertFalse(public["preparation_qualified"] or public["hardware_qualified"])
                self.assertNotIn("1234", json.dumps(public))
                self.assertNotIn("1234", repr(plan))
                self.assertEqual(plan.as_dict(include_private=True)["preparation_payload"], body)

    def test_prefix_is_opt_in_and_combined_duration_cannot_exceed_two_seconds(self):
        self.assertEqual(fixture().as_dict()["preparation"], "none")
        self.assertEqual(fixture().frame_count, 9)
        plan = fixture(command_frame_count=7500, followup_frame_count=1500,
            preparation="wake", preparation_frame_count=975)
        self.assertEqual(plan.frame_count, 9975)
        self.assertEqual(plan.duration_seconds, 1.9999875)
        invalid = (
            dict(preparation="wake"), dict(preparation="command-control"),
            dict(preparation_frame_count=3), dict(preparation="other"),
            *(dict(preparation="wake", preparation_frame_count=n)
              for n in (-3, 1, 2, 4, True, 3.0, 10002)),
            dict(preparation="wake", preparation_frame_count=978,
                 command_frame_count=7500, followup_frame_count=1500),
        )
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                fixture(**settings)


@unittest.skipIf(np is None, "NumPy/SciPy analysis dependencies unavailable")
class WakeSignalTests(unittest.TestCase):
    def test_written_signal_independently_decodes_and_suffix_matches_baseline(self):
        from hd_platinum.rf_iq import decode_iq_file
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = np.concatenate(list(iter_native_position_iq_chunks(fixture(), chunk_samples=997)))
            for mode in ("wake", "command-control"):
                plan = fixture(preparation=mode, preparation_frame_count=6)
                path = root / (mode + ".sc16q11")
                metadata = write_native_position_waveform(path, plan, chunk_samples=997)
                signal = np.fromfile(path, dtype="<i2").reshape(-1, 2)
                np.testing.assert_array_equal(signal[6*9624:], baseline)
                self.assertEqual(metadata["byte_count"], plan.sample_count * 4)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                decoded = decode_iq_file(path, sample_rate_hz=48_000_000,
                    center_hz=2_452_000_000, chunk_seconds=.005)
                self.assertEqual(decoded["frame_count"], 15)
                self.assertEqual(decoded["framing_counts"], {"shockburst": 15})
                for event, frame in zip(plan.iter_events(), decoded["frames"]):
                    self.assertEqual(frame["payload_hex"], event.payload.hex())
                    self.assertEqual(frame["channel_hz"], event.channel_hz)
                    self.assertEqual(int(frame["crc_hex"], 16),
                        binascii.crc_hqx(bytes.fromhex("e7e7e7") + event.payload, 0xffff))
                    self.assertAlmostEqual(frame["address_time_s"],
                        event.start_sample / 48_000_000 + 53e-6, delta=1e-6)

    def test_cli_writes_private_artifact_and_refuses_overwrite_or_invalid_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fictional.sc16q11"
            args = ["rf-native-position-waveform", str(path), "--room-rf-id", "1234",
                "--shade-mask", "8", "--position", "128", "--prior-channel", "71",
                "--command-frames", "4", "--followup-frames", "5", "--slot-us", "200.5",
                "--preparation", "wake", "--preparation-frames", "6"]
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["preparation_payload"], "xxxx010080")
            original = path.read_bytes()
            with redirect_stderr(StringIO()):
                self.assertEqual(main(args), 2)
                self.assertEqual(main(args[:-1] + ["4"]), 2)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
