# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import unittest
from unittest.mock import patch

from hd_platinum.cli import main
from hd_platinum.rf import REMOTE_FREQUENCIES_HZ


BASE_ARGS = ["rf-iq-decode", "fictional.sc16q11", "--sample-rate", "48000000", "--center", "2452000000"]
FAKE_RESULT = {
    "frame_count": 1,
    "frames": [{
        "address_time_s": 0.012345, "preamble_time_s_estimate": 0.012341,
        "channel_hz": 2_452_000_000, "address_hex": "e7e7e7",
        "payload_hex": "aabb2001a1", "remote_id": "aabb", "crc_hex": "57f9",
        "mode": 0x20, "group_mask": 0x01, "action_code": 0xA1,
        "action": "up", "crc_valid": True, "framing": "shockburst", "frame_bits": 88,
        "preamble_matches": True, "pcf_payload_length": None, "pid": None, "no_ack": None,
        "polarity": 1, "threshold_hz": 0, "phase": 2,
        "decision_margin_hz": 280_000.0, "detection_trials": 7,
    }],
}


class IqCliTests(unittest.TestCase):
    def test_defaults_redact_identity_payload_and_crc(self) -> None:
        result = deepcopy(FAKE_RESULT)
        output = StringIO()
        with patch("hd_platinum.rf_iq.decode_iq_file", return_value=result) as decode:
            with redirect_stdout(output):
                status = main(BASE_ARGS)
        self.assertEqual(status, 0)
        decode.assert_called_once_with(
            "fictional.sc16q11", sample_rate_hz=48_000_000,
            center_hz=2_452_000_000.0, channels_hz=REMOTE_FREQUENCIES_HZ,
            start_seconds=0.0, duration_seconds=None,
        )
        public = json.loads(output.getvalue())
        self.assertEqual(public["frame_count"], 1)
        self.assertEqual(public["frames"][0]["payload_hex"], "xxxx2001a1")
        self.assertEqual(public["frames"][0]["remote_id"], "[redacted]")
        self.assertEqual(public["frames"][0]["crc_hex"], "[redacted]")
        self.assertTrue(public["frames"][0]["crc_valid"])
        self.assertNotIn("aabb", output.getvalue())
        self.assertEqual(result, FAKE_RESULT)

    def test_private_output_and_explicit_interval_channels(self) -> None:
        output = StringIO()
        args = BASE_ARGS + [
            "--include-private", "--channels", "2452000000,2471000000",
            "--start", "9.9", "--duration", "0.1",
        ]
        with patch("hd_platinum.rf_iq.decode_iq_file", return_value=deepcopy(FAKE_RESULT)) as decode:
            with patch("hd_platinum.rf_iq.redact_result") as redact:
                with redirect_stdout(output):
                    status = main(args)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), FAKE_RESULT)
        redact.assert_not_called()
        self.assertEqual(decode.call_args.kwargs["channels_hz"], (2_452_000_000, 2_471_000_000))
        self.assertEqual(decode.call_args.kwargs["start_seconds"], 9.9)
        self.assertEqual(decode.call_args.kwargs["duration_seconds"], 0.1)

    def test_sample_rate_and_center_are_required(self) -> None:
        for args in (
            ["rf-iq-decode", "fictional.sc16q11", "--center", "2452000000"],
            ["rf-iq-decode", "fictional.sc16q11", "--sample-rate", "48000000"],
        ):
            with self.subTest(args=args), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)

    def test_invalid_numbers_rejected_before_decoder(self) -> None:
        invalid = (
            ("--sample-rate", "nan"), ("--sample-rate", "48000000.0"),
            ("--sample-rate", "0"), ("--sample-rate", "10000000"),
            ("--sample-rate", "-8000000"), ("--center", "nan"),
            ("--center", "inf"), ("--center", "-1"), ("--center", "0"),
            ("--start", "-0.1"), ("--start", "nan"),
            ("--duration", "0"), ("--duration", "-1"), ("--duration", "inf"),
            ("--channels", ""), ("--channels", "2452000000,"),
            ("--channels", "2452000000.0"), ("--channels", "2452000000,2452000000"),
            ("--channels", "0"), ("--channels", "-1"),
        )
        with patch("hd_platinum.rf_iq.decode_iq_file") as decode:
            for option, value in invalid:
                with self.subTest(option=option, value=value), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main(BASE_ARGS + [option, value])
                    self.assertEqual(error.exception.code, 2)
            decode.assert_not_called()

    def test_decoder_errors_use_existing_error_status(self) -> None:
        for error in (ValueError("analysis dependencies unavailable"), OSError("recording missing")):
            output, errors = StringIO(), StringIO()
            with self.subTest(error=error):
                with patch("hd_platinum.rf_iq.decode_iq_file", side_effect=error):
                    with redirect_stdout(output), redirect_stderr(errors):
                        status = main(BASE_ARGS)
                self.assertEqual(status, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn(f"error: {error}", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
