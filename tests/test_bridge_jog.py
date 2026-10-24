# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Jog dispatch/API checks with fictional identities and no hardware."""
from dataclasses import replace
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from hd_platinum.bridge import (BridgeConfig, BridgeError, BridgeService, DryRunBackend,
    JogCommand, ShadeConfig, load_config, make_server)

TOKEN = "fictional-jog-token-1234567890"


def config(enabled=True):
    return BridgeConfig(b"AB", {}, TOKEN, {3: ShadeConfig("Example", 2, b"XY", 4,
        position_enabled=True, sync_enabled=True, jog_enabled=enabled)})


class JogServiceTests(unittest.TestCase):
    def test_permission_defaults_false_and_config_requires_boolean(self):
        target = ShadeConfig("Example", 2, b"XY", 4)
        self.assertFalse(target.jog_enabled)
        for value in (None, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(target, jog_enabled=value)
        document = {"remote_id": "4142", "groups": {}, "api_token": TOKEN,
            "shades": {"3": {"name": "Example", "room_id": 2, "room_rf_id": "5859", "mask": 4}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(document))
            self.assertFalse(load_config(path).shades[3].jog_enabled)
            document["shades"]["3"]["jog_enabled"] = True
            path.write_text(json.dumps(document))
            loaded = load_config(path).shades[3]
            self.assertTrue(loaded.jog_enabled)
            self.assertFalse(loaded.sync_enabled or loaded.position_enabled)
        with self.assertRaises(ValueError):
            BridgeService(config(), DryRunBackend(), jog_backend=True)

    def test_disabled_unavailable_and_invalid_inputs_never_dispatch(self):
        backend = Mock()
        service = BridgeService(config(False), DryRunBackend(), jog_backend=backend)
        with self.assertRaises(BridgeError) as error:
            service.dispatch_jog({"shade": 3})
        self.assertEqual(error.exception.code, "jog_disabled")
        service.config = config()
        service.jog_backend = None
        with self.assertRaises(BridgeError) as error:
            service.dispatch_jog({"shade": 3})
        self.assertEqual(error.exception.code, "jog_unavailable")
        service.jog_backend = backend
        for value in ({}, [], {"shade": True}, {"shade": 3.0}, {"shade": 4},
                      {"shade": 3, "position": 0}, {"shade": 3, "value": 1},
                      {"shade": 3, "feature": 12}, {"shade": 3, "request_id": ""}):
            with self.subTest(value=value), self.assertRaises(BridgeError):
                service.dispatch_jog(value)
        backend.assert_not_called()

    def test_jog_receipt_cache_and_listener_are_separate_from_position_and_sync(self):
        backend = Mock(return_value={"status": "submitted", "frames_sent": 10, "sequence": 200,
            "position": 255, "position_confirmed": True, "sync_confirmed": True,
            "jog_confirmed": True, "room_rf_id": "5859"})
        service = BridgeService(config(), DryRunBackend(), jog_backend=backend,
                                position_backend=DryRunBackend(), sync_backend=DryRunBackend())
        listener = Mock()
        service.add_position_listener(listener)
        request = {"shade": 3, "request_id": "one-jog"}
        result = service.dispatch_jog(request)
        self.assertEqual(result["operation"], "jog")
        self.assertFalse(result["jog_confirmed"])
        self.assertEqual(result["backend"], {"frames_sent": 10, "sequence": 200})
        for key in ("position", "requested_position", "position_confirmed", "sync_confirmed", "room_rf_id"):
            self.assertNotIn(key, result)
        self.assertTrue(service.dispatch_jog(request)["replayed"])
        backend.assert_called_once()
        self.assertIsInstance(backend.call_args.args[0], JogCommand)
        listener.assert_not_called()
        for dispatch, other in ((service.dispatch_sync, request),
                                (service.dispatch_position, {**request, "position": 0})):
            with self.assertRaises(BridgeError) as error:
                dispatch(other)
            self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assertTrue(service.shades()["shades"][0]["jog_enabled"])
        self.assertTrue(service.shades()["jog_backend_available"])
        self.assertNotIn("5859", json.dumps(service.shades()))

    def test_jog_shares_nonqueuing_rf_lock_with_sync_and_position(self):
        entered, release = threading.Event(), threading.Event()
        calls, results = [], []
        def backend(command):
            calls.append(command)
            entered.set()
            if not release.wait(2):
                raise RuntimeError("fake backend timeout")
            return {"status": "submitted"}
        service = BridgeService(config(), DryRunBackend(), jog_backend=backend,
                                sync_backend=backend, position_backend=backend)
        worker = threading.Thread(target=lambda: results.append(service.dispatch_jog({"shade": 3})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            for dispatch, value in ((service.dispatch_jog, {"shade": 3}),
                                    (service.dispatch_sync, {"shade": 3}),
                                    (service.dispatch_position, {"shade": 3, "position": 0})):
                with self.assertRaises(BridgeError) as error:
                    dispatch(value)
                self.assertEqual(error.exception.code, "busy")
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            worker.join(2)
        self.assertEqual(len(results), 1)
        self.assertFalse(service._send_lock.locked())

    def test_backend_failure_is_private_and_does_not_notify_or_retry(self):
        backend = Mock(side_effect=RuntimeError("private example identity5859"))
        service = BridgeService(config(), DryRunBackend(), jog_backend=backend)
        listener = Mock()
        service.add_position_listener(listener)
        with self.assertRaises(BridgeError) as error:
            service.dispatch_jog({"shade": 3})
        self.assertEqual(error.exception.code, "backend_error")
        self.assertNotIn("5859", str(error.exception))
        backend.assert_called_once()
        listener.assert_not_called()
        self.assertFalse(service._send_lock.locked())


class JogHTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(return_value={"status": "submitted"})
        self.service = BridgeService(config(False), DryRunBackend(), jog_backend=self.backend)
        self.server = make_server(self.service, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.worker.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, value=None, *, method="POST", headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.request(method, "/api/jog", raw if raw is not None else json.dumps(value), headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def auth(self, **extra):
        return {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json", **extra}

    def test_authenticated_opt_in_jog_replays_without_rf(self):
        request = {"shade": 3, "request_id": "http-jog"}
        self.assertEqual(self.request(method="GET")[0], 405)
        self.assertEqual(self.request(request, headers=self.auth())[0], 409)
        self.backend.assert_not_called()
        self.service.config = config()
        status, result = self.request(request, headers=self.auth())
        self.assertEqual(status, 202)
        self.assertEqual(result["operation"], "jog")
        self.assertFalse(result["jog_confirmed"])
        self.assertTrue(self.request(request, headers=self.auth())[1]["replayed"])
        self.backend.assert_called_once()

    def test_jog_retains_auth_host_origin_and_body_checks(self):
        for headers, expected in (({"Content-Type": "application/json"}, 401),
                                  (self.auth(Origin="http://other.example"), 403),
                                  (self.auth(Host=f"other.example:{self.server.server_port}"), 400)):
            self.assertEqual(self.request({"shade": 3}, headers=headers)[0], expected)
        for body in ('{"shade":3,"shade":4}', '{"shade":true}', '{"shade":3,"position":0}'):
            self.assertEqual(self.request(headers=self.auth(), raw=body)[0], 400)
        self.backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
