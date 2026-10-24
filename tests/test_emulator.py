# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

import http.client
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hd_platinum.bridge import BridgeConfig, BridgeError, BridgeService, DryRunBackend, ShadeConfig
from hd_platinum.emulator import EmulatorServer, run_emulator
from hd_platinum.lan import query_inventory


TOKEN = "fictional-emulator-test-token-12345"
SNAPSHOT = b"\n\r".join([
    b"1 HunterDouglas Shade Controller", b"1 $firm03-2018-HD gateway 2.18a",
    b"1 $MAC0x02AABBCCDDEE-", b"1 $upd00-", b"1 $reset",
    b"1 $cr00-01-0xAABB-Test Room", b"1 $cs00-00-01-Test Shade",
    b"1 $cp00-04-000-", b"1 $upd01-", b""])


def config(two=False):
    shades = {0: ShadeConfig("Test Shade", 0, b"\xaa\xbb", 1, position_enabled=True)}
    if two:
        shades[1] = ShadeConfig("Second Shade", 0, b"\xaa\xbb", 2, position_enabled=True)
    return BridgeConfig(b"\xaa\xbb", {}, TOKEN, shades)


class EmulatorProfileTests(unittest.TestCase):
    def test_sync_profile_defaults_narrow_and_wide_keeps_positions_narrow(self):
        from hd_platinum.cli import _parser
        for profile in ("narrow", "wide"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                arguments = ["bridge-emulate", "--config", "unused-config",
                    "--inventory", "unused-inventory", "--state-dir", directory,
                    "--backend", "bladerf-bridge", "--rx-gain", "30"]
                if profile == "wide":
                    arguments += ["--sync-rf-profile", "wide"]
                args = _parser().parse_args(arguments)
                self.assertEqual(args.sync_rf_profile, profile)
                backends, calls, services = [], [], []
                def backend(state_dir, **kwargs):
                    calls.append((state_dir, kwargs))
                    value = DryRunBackend()
                    backends.append(value)
                    return value
                class FakeServer:
                    stop_event = threading.Event()
                    def __init__(self, service, *args, **kwargs):
                        services.append(service)
                    def start(self): pass
                    def status(self): return {}
                    def wait(self): pass
                    def close(self): pass
                with patch("hd_platinum.emulator.load_config", return_value=config()), \
                     patch("hd_platinum.bladerf_bridge.BladeRFBridgeBackend", side_effect=backend), \
                     patch("hd_platinum.emulator.EmulatorServer", FakeServer), \
                     patch("hd_platinum.emulator.signal.signal"), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run_emulator(args), 0)
                self.assertNotIn("profile", calls[0][1])
                self.assertIs(services[0].position_backend, backends[0])
                self.assertIs(services[0].jog_backend, backends[0])
                self.assertEqual(calls[0][1]["rx_gain_db"], 30)
                if profile == "wide":
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[0][0], calls[1][0])
                    self.assertEqual(calls[1][1]["profile"], "wide")
                    self.assertEqual(calls[1][1]["rx_gain_db"], 30)
                    self.assertIs(services[0].sync_backend, backends[1])
                else:
                    self.assertEqual(len(calls), 1)
                    self.assertIs(services[0].sync_backend, backends[0])


class DispatchStateTests(unittest.TestCase):
    def test_listener_failure_does_not_repeat_submitted_command(self):
        calls = []
        service = BridgeService(config(), DryRunBackend(), position_backend=lambda command:
                                calls.append(command) or {"status": "submitted", "sequence": 7})
        def failure(command, receipt):
            raise OSError("synthetic state failure")
        unsubscribe = service.add_position_listener(failure)
        value = {"shade": 0, "position": 128, "request_id": "same-request"}
        with self.assertLogs("hd_platinum.bridge", level="ERROR"):
            result = service.dispatch_position(value)
        self.assertEqual(result["backend"]["sequence"], 7)
        self.assertTrue(service.dispatch_position(value)["replayed"])
        self.assertEqual(len(calls), 1)
        unsubscribe()
        service.dispatch_position(dict(value, request_id="new-request"))
        self.assertEqual(len(calls), 2)

    def test_batch_validates_every_target_before_sending(self):
        calls = []
        service = BridgeService(config(), DryRunBackend(), position_backend=lambda command:
                                calls.append(command) or {"status": "submitted"})
        with self.assertRaises(BridgeError):
            service.dispatch_positions([{"shade": 0, "position": 128},
                                        {"shade": 99, "position": 128}])
        self.assertEqual(calls, [])

    def test_batch_holds_serialization_and_observes_each_request_once(self):
        started, release = threading.Event(), threading.Event()
        calls, observed, errors = [], [], []
        def backend(command):
            calls.append(command.shade)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise TimeoutError("test did not release backend")
            return {"status": "submitted"}
        service = BridgeService(config(True), DryRunBackend(), position_backend=backend)
        service.add_position_listener(lambda command, receipt: observed.append(command.shade))
        values = [{"shade": i, "position": 128, "request_id": f"batch-{i}"} for i in (0, 1)]
        def run():
            try:
                service.dispatch_positions(values)
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(started.wait(3))
            with self.assertRaises(BridgeError) as error:
                service.dispatch_position({"shade": 0, "position": 0})
            self.assertEqual(error.exception.code, "busy")
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(calls, [0, 1])
        self.assertEqual(observed, [0, 1])
        self.assertTrue(all(item["replayed"] for item in service.dispatch_positions(values)))
        self.assertEqual(calls, [0, 1])


class EmulatorIntegrationTests(unittest.TestCase):
    def test_http_and_original_tcp_client_share_inventory_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            service = BridgeService(config(), DryRunBackend(), position_backend=lambda command:
                                    calls.append(command) or {"status": "submitted", "sequence": 19})
            server = EmulatorServer(service, SNAPSHOT, port=0, http_port=0,
                                    state_path=Path(directory) / "positions.json")
            server.start()
            try:
                before = query_inventory("127.0.0.1", port=server.lan.server_address[1])
                self.assertEqual(before.shades[0].positions[4], 0)
                client = http.client.HTTPConnection("127.0.0.1", server.http.server_address[1], timeout=3)
                body = json.dumps({"shade": 0, "position": 128, "request_id": "http-test"})
                client.request("POST", "/api/positions", body,
                               {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
                response = client.getresponse()
                self.assertEqual(response.status, 202)
                receipt = json.loads(response.read())
                self.assertFalse(receipt["position_confirmed"])
                client.close()
                after = query_inventory("127.0.0.1", port=server.lan.server_address[1])
                self.assertEqual(after.shades[0].positions[4], 128)
                self.assertEqual(len(calls), 1)
            finally:
                server.close()
            self.assertTrue(all(not thread.is_alive() for thread in server.threads))

    def test_partial_startup_failure_closes_previously_bound_endpoints(self):
        service = BridgeService(config(), DryRunBackend(), position_backend=DryRunBackend())
        with self.assertRaises(ValueError):
            EmulatorServer(service, SNAPSHOT, port=0, http_port=0, discovery=True)
        self.assertEqual(service._position_listeners, [])

    def test_optional_protocol_log_receives_unknown_app_bytes_before_parsing(self):
        records, paths = [], []
        class RecordingJournal:
            def __init__(self, path):
                paths.append(path)
            def __call__(self, direction, peer, connection_id, data):
                records.append((direction, peer, connection_id, data))
        service = BridgeService(config(), DryRunBackend(), position_backend=DryRunBackend())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.private.jsonl"
            with patch.dict(sys.modules, {"hd_platinum.lan_trace": SimpleNamespace(WireJournal=RecordingJournal)}):
                server = EmulatorServer(service, SNAPSHOT, port=0, http_port=0, protocol_log=path).start()
            try:
                with socket.create_connection(server.lan.server_address, timeout=2) as client:
                    self.assertIn(b"HunterDouglas Shade Controller", client.recv(1024))
                    unknown = b"$futureAppCommand-\x00"
                    client.sendall(unknown)
                    self.assertIn(b"$error01-", client.recv(1024))
            finally:
                server.close()
            self.assertEqual(paths, [path])
            self.assertEqual(b"".join(record[3] for record in records if record[0] == "receive"), unknown)
            self.assertTrue(any(record[0] == "send" and b"$error01-\n\r" in record[3] for record in records))
            self.assertTrue(all(record[1][0] == "127.0.0.1" and isinstance(record[2], int) for record in records))

    def test_thread_start_failure_stops_prior_listener_and_closes_all_sockets(self):
        service = BridgeService(config(), DryRunBackend(), position_backend=DryRunBackend())
        server = EmulatorServer(service, SNAPSHOT, port=0, http_port=0)
        start_thread = threading.Thread.start
        def start_or_fail(thread):
            if thread.name == "platinum-server-1":
                raise RuntimeError("synthetic listener startup failure")
            return start_thread(thread)
        with patch("hd_platinum.emulator.threading.Thread.start", new=start_or_fail):
            with self.assertRaisesRegex(RuntimeError, "synthetic listener startup"):
                server.start()
        self.assertTrue(server.closed)
        self.assertEqual(len(server.threads), 1)
        self.assertTrue(all(not thread.is_alive() for thread in server.threads))
        self.assertTrue(all(endpoint.socket.fileno() == -1 for endpoint in server.servers))
        self.assertEqual(service._position_listeners, [])
        server.close()

    def test_shutdown_waits_for_http_rf_and_keeps_lan_state_listener_until_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            entered, release, closed = threading.Event(), threading.Event(), threading.Event()
            failures, responses = [], []
            def backend(command):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("test did not release backend")
                return {"status": "submitted"}
            service = BridgeService(config(), DryRunBackend(), position_backend=backend)
            state = Path(directory) / "positions.json"
            server = EmulatorServer(service, SNAPSHOT, port=0, http_port=0, state_path=state).start()
            def request():
                client = http.client.HTTPConnection("127.0.0.1", server.http.server_address[1], timeout=3)
                try:
                    client.request("POST", "/api/positions", json.dumps({"shade": 0, "position": 128}),
                                   {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
                    response = client.getresponse()
                    responses.append((response.status, json.loads(response.read())))
                except BaseException as error:
                    failures.append(error)
                finally:
                    client.close()
            def stop():
                try:
                    server.close()
                except BaseException as error:
                    failures.append(error)
                finally:
                    closed.set()
            requester = threading.Thread(target=request)
            requester.start()
            stopper = None
            try:
                self.assertTrue(entered.wait(2))
                stopper = threading.Thread(target=stop)
                stopper.start()
                self.assertFalse(closed.wait(.05))
                self.assertFalse(state.exists())
            finally:
                release.set()
                requester.join(3)
                if stopper is not None:
                    stopper.join(3)
                else:
                    server.close()
            self.assertFalse(failures)
            self.assertTrue(closed.is_set())
            self.assertEqual(responses[0][0], 202)
            self.assertFalse(responses[0][1]["position_confirmed"])
            self.assertEqual(json.loads(state.read_text())["requested_positions"], {"0": 128})
            self.assertEqual(service._position_listeners, [])
            self.assertTrue(all(not thread.is_alive() for thread in server.threads))


if __name__ == "__main__":
    unittest.main()
