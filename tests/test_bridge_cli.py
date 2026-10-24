# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CLI wiring checks; no test opens or transmits through a radio."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from hd_platinum.bladerf import RadioConfig, RadioError, TX1
from hd_platinum.bridge import BridgeError, DryRunBackend
from hd_platinum.cli import main

try:
    import numpy  # noqa: F401
except ImportError:
    numpy = None


TOKEN = "fictional-cli-token-only-1234567890"


class BridgeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / "private.json"
        self.config.write_text(json.dumps({
            "remote_id": "aabb", "api_token": TOKEN, "groups": {"1": "Test group"},
        }))

    def fake_server(self):
        server = Mock()
        server.server_address = ("127.0.0.1", 8077)
        server.serve_forever.side_effect = KeyboardInterrupt
        return server

    def test_config_required_before_server_or_hardware(self) -> None:
        with patch("hd_platinum.bridge.make_server") as server:
            with patch("hd_platinum.bladerf.BladeRF") as radio:
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
                    main(["bridge-serve"])
        self.assertEqual(error.exception.code, 2)
        server.assert_not_called()
        radio.assert_not_called()

    def test_default_backend_is_dry_run_and_shutdown_closes_server(self) -> None:
        server, output = self.fake_server(), StringIO()
        with patch("hd_platinum.bridge.make_server", return_value=server) as factory:
            with patch("hd_platinum.bladerf.BladeRFBackend") as hardware_backend, \
                    patch("hd_platinum.bladerf.BladeRFPositionBackend") as position_hardware:
                with patch("hd_platinum.bladerf.BladeRF") as radio:
                    with patch("hd_platinum.cli.signal.signal", return_value="prior-handler") as signals:
                        with redirect_stdout(output):
                            status = main(["bridge-serve", "--config", str(self.config)])
        self.assertEqual(status, 0)
        service = factory.call_args.args[0]
        self.assertIsInstance(service.backend, DryRunBackend)
        self.assertIsInstance(service.position_backend, DryRunBackend)
        self.assertEqual(factory.call_args.kwargs, {"host": "127.0.0.1", "port": 8077, "allowed_hosts": None})
        self.assertEqual(service.dispatch({"group": 1, "action": "up"})["status"], "simulated")
        hardware_backend.assert_not_called()
        position_hardware.assert_not_called()
        radio.assert_not_called()
        server.serve_forever.assert_called_once_with(poll_interval=.2)
        server.server_close.assert_called_once()
        self.assertEqual(signals.call_count, 2)
        self.assertEqual(signals.call_args.args[1], "prior-handler")
        summary = json.loads(output.getvalue())
        self.assertEqual(summary, {"backend": "dry-run", "groups": [1], "shades": [],
                                   "url": "http://127.0.0.1:8077"})
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertNotIn("aabb", output.getvalue())

    def test_bladerf_backend_requires_explicit_selection_and_receives_options(self) -> None:
        server, output = self.fake_server(), StringIO()
        cache = str(Path(self.directory.name) / "waveforms")
        with patch("hd_platinum.bridge.make_server", return_value=server) as factory:
            with patch("hd_platinum.bladerf.BladeRFBackend") as backend, \
                    patch("hd_platinum.bladerf.BladeRFPositionBackend") as position_backend:
                with patch("hd_platinum.bladerf.BladeRF") as radio:
                    with patch("hd_platinum.cli.signal.signal"):
                        with redirect_stdout(output):
                            status = main([
                                "bridge-serve", "--config", str(self.config), "--backend", "bladerf",
                                "--cache-dir", cache, "--tx-gain", "20", "--device", "libusb:instance=0",
                                "--fpga", "fictional.rbf", "--allowed-host", "localhost",
                            ])
        self.assertEqual(status, 0)
        backend.assert_called_once_with(cache, gain_db=20, device="libusb:instance=0", fpga="fictional.rbf")
        position_backend.assert_called_once_with(cache, gain_db=20, device="libusb:instance=0", fpga="fictional.rbf")
        self.assertIs(factory.call_args.args[0].backend, backend.return_value)
        self.assertIs(factory.call_args.args[0].position_backend, position_backend.return_value)
        self.assertEqual(factory.call_args.kwargs["allowed_hosts"], ["localhost"])
        radio.assert_not_called()
        server.server_close.assert_called_once()

    def test_shades_only_dry_run_exposes_targets_and_retains_validation_gate(self) -> None:
        self.config.write_text(json.dumps({
            "remote_id": "aabb", "api_token": TOKEN, "groups": {},
            "shades": {
                "6": {"name": "Example enabled", "room_id": 1,
                      "room_rf_id": "ccdd", "mask": 4, "position_enabled": True},
                "8": {"name": "Example disabled", "room_id": 1,
                      "room_rf_id": "ccdd", "mask": 64},
            },
        }))
        output = StringIO()
        with patch("hd_platinum.bridge.make_server", return_value=self.fake_server()) as factory, \
                patch("hd_platinum.bladerf.BladeRFBackend") as groups, \
                patch("hd_platinum.bladerf.BladeRFPositionBackend") as positions, \
                patch("hd_platinum.bladerf.BladeRF") as radio, \
                patch("hd_platinum.cli.signal.signal"), redirect_stdout(output):
            status = main(["bridge-serve", "--config", str(self.config)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), {
            "backend": "dry-run", "groups": [], "shades": [6, 8],
            "url": "http://127.0.0.1:8077",
        })
        service = factory.call_args.args[0]
        receipt = service.dispatch_position({"shade": 6, "position": 128})
        self.assertEqual(receipt["status"], "simulated")
        self.assertEqual(receipt["requested_position"], 128)
        self.assertFalse(receipt["position_confirmed"])
        with self.assertRaises(BridgeError) as error:
            service.dispatch_position({"shade": 8, "position": 128})
        self.assertEqual(error.exception.code, "validation_required")
        for backend in (groups, positions, radio):
            backend.assert_not_called()
        for private_value in (TOKEN, "aabb", "ccdd", "Example enabled"):
            self.assertNotIn(private_value, output.getvalue())

    def test_invalid_private_configuration_does_not_start_backend(self) -> None:
        self.config.write_text('{"remote_id":"aabb"}')
        output, errors = StringIO(), StringIO()
        with patch("hd_platinum.bridge.make_server") as server:
            with patch("hd_platinum.bladerf.BladeRFBackend") as backend, \
                    patch("hd_platinum.bladerf.BladeRFPositionBackend") as position_backend:
                with redirect_stdout(output), redirect_stderr(errors):
                    status = main(["bridge-serve", "--config", str(self.config), "--backend", "bladerf"])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("configuration", errors.getvalue())
        backend.assert_not_called()
        position_backend.assert_not_called()
        server.assert_not_called()


class RadioCliTests(unittest.TestCase):
    def test_finite_transmit_uses_context_manager_and_selected_settings(self) -> None:
        output = StringIO()
        with patch("hd_platinum.bladerf.BladeRF") as device:
            radio = device.return_value.__enter__.return_value
            radio.transmit.return_value = {"status": "submitted", "samples_sent": 32}
            with redirect_stdout(output):
                status = main(["rf-transmit", "fictional.sc16q11", "--gain", "0"])
        self.assertEqual(status, 0)
        device.assert_called_once_with(device=None, fpga=None)
        radio.configure.assert_called_once_with(TX1, RadioConfig(gain_db=0))
        radio.transmit.assert_called_once_with("fictional.sc16q11")
        device.return_value.__exit__.assert_called_once()
        self.assertEqual(json.loads(output.getvalue()), {"status": "submitted", "samples_sent": 32})

    def test_invalid_radio_parameters_do_not_open_hardware(self) -> None:
        for option, value in (("--sample-rate", "61440000"), ("--sample-rate", "0"),
                              ("--gain", "61"), ("--gain", "-24"),
                              ("--center", "100000000"), ("--bandwidth", "49000000")):
            with self.subTest(option=option, value=value):
                output, errors = StringIO(), StringIO()
                with patch("hd_platinum.bladerf.BladeRF") as device:
                    with redirect_stdout(output), redirect_stderr(errors):
                        status = main(["rf-transmit", "fictional.sc16q11", option, value])
                self.assertEqual(status, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("error:", errors.getvalue())
                device.assert_not_called()

    def test_transmit_failure_exits_context_and_does_not_report_success(self) -> None:
        output, errors = StringIO(), StringIO()
        with patch("hd_platinum.bladerf.BladeRF") as device:
            device.return_value.__enter__.return_value.transmit.side_effect = RadioError("synthetic TX failure")
            with redirect_stdout(output), redirect_stderr(errors):
                status = main(["rf-transmit", "fictional.sc16q11"])
        self.assertEqual(status, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("synthetic TX failure", errors.getvalue())
        device.return_value.__exit__.assert_called_once()


@unittest.skipIf(numpy is None, "optional NumPy analysis dependency unavailable")
class WaveformCliTests(unittest.TestCase):
    def test_offline_position_artifact_has_three_channels_and_redacted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional-position.sc16q11"
            args = ["rf-position-waveform", str(path), "--room-rf-id", "aabb",
                    "--shade-mask", "0x04", "--position", "128",
                    "--command-repetitions", "2", "--followup-repetitions", "1"]
            output = StringIO()
            with patch("hd_platinum.bladerf._load_library") as hardware:
                with redirect_stdout(output):
                    status = main(args)
                original = path.read_bytes()
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    second = main(args)
                hardware.assert_not_called()
            self.assertEqual(status, 0)
            self.assertEqual(second, 2)
            self.assertEqual(path.read_bytes(), original)
            result = json.loads(output.getvalue())
            self.assertTrue(result["candidate_only"])
            self.assertEqual(result["channels_hz"], [2_433_000_000, 2_452_000_000, 2_471_000_000])
            self.assertEqual(result["frame_count"], 9)
            self.assertEqual(result["sample_count"], 101_088)
            self.assertEqual(result["byte_count"], 4 * result["sample_count"])
            self.assertEqual(result["byte_count"], len(original))
            self.assertAlmostEqual(result["duration_seconds"], .002106)
            self.assertEqual(result["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(result["command_payload"], "xxxx500480")
            self.assertEqual(result["followup_payload"], "xxxx320480")
            self.assertNotIn("aabb", output.getvalue())

    def test_invalid_position_mask_is_rejected_before_artifact_or_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional-position.sc16q11"
            for mask in ("0", "3", "256"):
                with self.subTest(mask=mask), \
                        patch("hd_platinum.bladerf._load_library") as hardware, \
                        patch("hd_platinum.rf_positions.write_position_waveform") as writer, \
                        redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    status = main(["rf-position-waveform", str(path), "--room-rf-id", "aabb",
                                   "--shade-mask", mask, "--position", "128"])
                self.assertEqual(status, 2)
                self.assertFalse(path.exists())
                hardware.assert_not_called()
                writer.assert_not_called()

    def test_offline_waveform_artifact_is_redacted_hashed_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional.sc16q11"
            args = ["rf-waveform", str(path), "--remote-id", "aabb", "--groups", "1",
                    "--action", "up", "--sample-rate", "8000000", "--channels", "2452000000",
                    "--action-repetitions", "2", "--release-repetitions", "1"]
            output = StringIO()
            with patch("hd_platinum.bladerf._load_library") as hardware:
                with redirect_stdout(output):
                    status = main(args)
                original = path.read_bytes()
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    second = main(args)
                hardware.assert_not_called()
            self.assertEqual(status, 0)
            self.assertEqual(second, 2)
            self.assertEqual(path.read_bytes(), original)
            result = json.loads(output.getvalue())
            self.assertEqual(result["frame_count"], 3)
            self.assertEqual(result["byte_count"], len(original))
            self.assertEqual(result["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(result["action_payload"], "xxxx2001a1")
            self.assertNotIn("aabb", output.getvalue())

    def test_invalid_waveform_parameters_leave_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional.sc16q11"
            with patch("hd_platinum.bladerf._load_library") as hardware:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    status = main(["rf-waveform", str(path), "--remote-id", "aabb",
                                   "--groups", "1", "--action", "down", "--sample-rate", "10000000"])
            self.assertEqual(status, 2)
            self.assertFalse(path.exists())
            hardware.assert_not_called()


if __name__ == "__main__":
    unittest.main()
