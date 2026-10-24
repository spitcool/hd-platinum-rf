# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Explicit Sync scope, shared dispatch, and authenticated HTTP; no hardware."""

from dataclasses import replace
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from hd_platinum.bridge import (
    BridgeConfig, BridgeError, BridgeService, DryRunBackend, ShadeConfig,
    SyncCommand, load_config, make_server,
)


TOKEN = "fictional-sync-token-only-123456789"


def config(enabled=True, position_enabled=False):
    return BridgeConfig(b"AB", {1: "Example group"}, TOKEN, {
        3: ShadeConfig("Example shade", 2, b"XY", 4,
                       position_enabled=position_enabled, sync_enabled=enabled)})


class SyncServiceTests(unittest.TestCase):
    def test_submission_notification_precedes_cleanup_is_once_and_preserves_replay(self):
        events = []
        class ProgressBackend:
            def __call__(self, command):
                raise AssertionError("progress-capable Sync must use submit")

            def submit(self, command, *, on_transmit_submitted):
                events.append("transmitted")
                on_transmit_submitted()
                on_transmit_submitted()  # A duplicate notification is harmless.
                events.append("cleanup")
                return {"status": "submitted"}
        service = BridgeService(config(), DryRunBackend(), sync_backend=ProgressBackend())
        def notified():
            self.assertTrue(service._send_lock.locked())
            events.append("room-action")
            raise ValueError("fake transport notification failure")
        request = {"shade": 3, "request_id": "progress-request"}
        with self.assertLogs("hd_platinum.bridge", level="ERROR"):
            result = service.dispatch_sync(request, on_transmit_submitted=notified)
        self.assertEqual(events, ["transmitted", "room-action", "cleanup"])
        self.assertEqual(result["status"], "submitted")
        self.assertFalse(result["sync_confirmed"])
        replay = service.dispatch_sync(request, on_transmit_submitted=notified)
        self.assertTrue(replay["replayed"])
        self.assertEqual(events, ["transmitted", "room-action", "cleanup"])

    def test_callable_fallback_notifies_only_after_valid_success(self):
        for status, expected in (("submitted", 1), ("simulated", 1), ("invalid", 0)):
            with self.subTest(status=status):
                backend = Mock(return_value={"status": status})
                callback = Mock()
                service = BridgeService(config(), DryRunBackend(), sync_backend=backend)
                if expected:
                    service.dispatch_sync({"shade": 3}, on_transmit_submitted=callback)
                else:
                    with self.assertRaises(BridgeError):
                        service.dispatch_sync({"shade": 3}, on_transmit_submitted=callback)
                self.assertEqual(callback.call_count, expected)
                backend.assert_called_once()
        with self.assertRaises(ValueError):
            service.dispatch_sync({"shade": 3}, on_transmit_submitted=True)

    def test_sync_opt_in_defaults_false_and_loads_only_boolean(self):
        target = ShadeConfig("Example", 2, b"XY", 4)
        self.assertFalse(target.sync_enabled)
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(target, sync_enabled=value)
        document = {"remote_id": "4142", "groups": {}, "api_token": TOKEN,
                    "shades": {"3": {"name": "Example", "room_id": 2, "room_rf_id": "5859", "mask": 4}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(document))
            self.assertFalse(load_config(path).shades[3].sync_enabled)
            document["shades"]["3"]["sync_enabled"] = True
            path.write_text(json.dumps(document))
            loaded = load_config(path)
            self.assertTrue(loaded.shades[3].sync_enabled)
            self.assertFalse(loaded.shades[3].position_enabled)
        with self.assertRaises(ValueError):
            BridgeService(config(), DryRunBackend(), sync_backend=True)

    def test_disabled_missing_and_invalid_requests_never_invoke_backend_or_start(self):
        backend, started = Mock(), Mock()
        service = BridgeService(config(False), DryRunBackend(), sync_backend=backend)
        with self.assertRaises(BridgeError) as error:
            service.dispatch_sync({"shade": 3}, on_started=started)
        self.assertEqual(error.exception.code, "sync_disabled")
        service.config = config(True)
        service.sync_backend = None
        with self.assertRaises(BridgeError) as error:
            service.dispatch_sync({"shade": 3}, on_started=started)
        self.assertEqual(error.exception.code, "sync_unavailable")
        service.sync_backend = backend
        for value in (None, [], {}, {"shade": True}, {"shade": 3.0}, {"shade": 4},
                      {"shade": 3, "position": 0}, {"shade": 3, "duration": 18},
                      {"shade": 3, "request_id": ""}, {"shade": 3, "mask": 4}):
            with self.subTest(value=value), self.assertRaises(BridgeError) as error:
                service.dispatch_sync(value, on_started=started)
            self.assertEqual(error.exception.status, 400)
        backend.assert_not_called()
        started.assert_not_called()

    def test_typed_sync_receipt_is_not_a_position_or_enrollment_confirmation(self):
        calls, order = [], []
        def backend(command):
            order.append("backend")
            calls.append(command)
            return {"status": "submitted", "frames_sent": 10, "sequence": 100,
                    "position": 255, "position_confirmed": True, "sync_confirmed": True,
                    "room_rf_id": "5859", "mask": 4}
        service = BridgeService(config(True, False), DryRunBackend(), sync_backend=backend)
        listener = Mock()
        service.add_position_listener(listener)
        def start():
            self.assertTrue(service._send_lock.locked())
            order.append("start")
        receipt = service.dispatch_sync({"shade": 3, "request_id": "one-sync"}, on_started=start)
        self.assertEqual(order, ["start", "backend"])
        self.assertIsInstance(calls[0], SyncCommand)
        self.assertEqual((calls[0].shade, calls[0].target.room_rf_id, calls[0].target.mask), (3, b"XY", 4))
        self.assertFalse(hasattr(calls[0], "position"))
        self.assertEqual(receipt["operation"], "sync")
        self.assertEqual(receipt["delivery"], "unverified")
        self.assertFalse(receipt["sync_confirmed"])
        for key in ("position", "requested_position", "position_confirmed"):
            self.assertNotIn(key, receipt)
        self.assertEqual(receipt["backend"], {"frames_sent": 10, "sequence": 100})
        listener.assert_not_called()
        self.assertNotIn("XY", repr(calls[0]))
        listing = service.shades()
        self.assertTrue(listing["shades"][0]["sync_enabled"])
        self.assertTrue(listing["sync_backend_available"])
        for secret in ("5859", "room_rf_id", "mask", TOKEN):
            self.assertNotIn(secret, json.dumps(listing))

    def test_sync_replay_and_cross_operation_cache_conflicts(self):
        backend = Mock(return_value={"status": "submitted", "frames_sent": 10})
        started = Mock()
        service = BridgeService(config(True, True), DryRunBackend(),
                                position_backend=DryRunBackend(), sync_backend=backend)
        request = {"shade": 3, "request_id": "shared-key"}
        receipt = service.dispatch_sync(request, on_started=started)
        receipt["backend"]["frames_sent"] = 999
        replay = service.dispatch_sync(request, on_started=started)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["backend"]["frames_sent"], 10)
        backend.assert_called_once()
        started.assert_called_once()
        for invoke in (
                lambda: service.dispatch_position({"shade": 3, "position": 0, "request_id": "shared-key"}),
                lambda: service.dispatch({"group": 1, "action": "up", "request_id": "shared-key"})):
            with self.assertRaises(BridgeError) as error:
                invoke()
            self.assertEqual(error.exception.code, "idempotency_conflict")
        service.dispatch_position({"shade": 3, "position": 0, "request_id": "position-key"})
        with self.assertRaises(BridgeError) as error:
            service.dispatch_sync({"shade": 3, "request_id": "position-key"})
        self.assertEqual(error.exception.code, "idempotency_conflict")

    def test_sync_shares_busy_lock_with_group_and_position_in_both_directions(self):
        for sync_first in (False, True):
            with self.subTest(sync_first=sync_first):
                entered, release = threading.Event(), threading.Event()
                outcomes, callbacks = [], []
                def blocking(command):
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError("test backend timeout")
                    return {"status": "submitted"}
                service = BridgeService(config(True, True), blocking,
                                        position_backend=blocking, sync_backend=blocking)
                invoke_sync = lambda: service.dispatch_sync({"shade": 3}, on_started=lambda: callbacks.append("start"))
                invoke_position = lambda: service.dispatch_position({"shade": 3, "position": 0})
                first = invoke_sync if sync_first else invoke_position
                worker = threading.Thread(target=lambda: outcomes.append(first()))
                worker.start()
                try:
                    self.assertTrue(entered.wait(1))
                    attempts = [invoke_position if sync_first else invoke_sync,
                                lambda: service.dispatch({"group": 1, "action": "up"})]
                    for attempt in attempts:
                        with self.assertRaises(BridgeError) as error:
                            attempt()
                        self.assertEqual(error.exception.code, "busy")
                    self.assertEqual(callbacks, ["start"] if sync_first else [])
                finally:
                    release.set()
                    worker.join(2)
                self.assertEqual(len(outcomes), 1)

    def test_failed_sync_is_private_and_does_not_notify_position_listeners(self):
        backend = Mock(side_effect=RuntimeError("private target 5859"))
        listener = Mock()
        service = BridgeService(config(), DryRunBackend(), sync_backend=backend)
        service.add_position_listener(listener)
        with self.assertRaises(BridgeError) as error:
            service.dispatch_sync({"shade": 3})
        self.assertEqual(error.exception.code, "backend_error")
        self.assertNotIn("5859", str(error.exception))
        self.assertFalse(service._send_lock.locked())
        listener.assert_not_called()


class SyncHTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(return_value={"status": "submitted"})
        self.service = BridgeService(config(False), DryRunBackend(), sync_backend=self.backend)
        self.server = make_server(self.service, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.worker.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, method="POST", value=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.request(method, "/api/sync", body=raw if raw is not None else json.dumps(value),
                               headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def auth(self, **extra):
        return {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json", **extra}

    def test_authenticated_opt_in_sync_and_replay(self):
        request = {"shade": 3, "request_id": "http-sync"}
        self.assertEqual(self.request("GET")[0], 405)
        self.assertEqual(self.request(value=request, headers=self.auth())[0], 409)
        self.backend.assert_not_called()
        self.service.config = config(True)
        status, receipt = self.request(value=request, headers=self.auth())
        self.assertEqual(status, 202)
        self.assertEqual(receipt["operation"], "sync")
        self.assertFalse(receipt["sync_confirmed"])
        self.assertNotIn("position_confirmed", receipt)
        self.assertTrue(self.request(value=request, headers=self.auth())[1]["replayed"])
        self.backend.assert_called_once()

    def test_sync_uses_existing_auth_host_origin_and_body_checks(self):
        for headers, expected in (({"Content-Type": "application/json"}, 401),
                                  (self.auth(Origin="http://other.example"), 403),
                                  (self.auth(Host=f"other.example:{self.server.server_port}"), 400)):
            self.assertEqual(self.request(value={"shade": 3}, headers=headers)[0], expected)
        for raw in ('{"shade":3,"shade":4}', '{"shade":true}',
                    '{"shade":3,"position":0}', '{"shade":3,"duration":18}'):
            self.assertEqual(self.request(headers=self.auth(), raw=raw)[0], 400)
        self.backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
