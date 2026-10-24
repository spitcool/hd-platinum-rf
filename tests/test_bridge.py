# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from hd_platinum.bridge import (
    BridgeConfig, BridgeError, BridgeService, DryRunBackend, load_config, make_server,
)


TOKEN = "fictional-test-token-only-1234567890"


def config():
    return BridgeConfig(bytes.fromhex("aabb"), {1: "Test group", 3: "Third group"}, TOKEN)


class BridgeServiceTests(unittest.TestCase):
    def test_private_config_load_validation_and_readonly_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text(json.dumps({"remote_id": "aabb", "api_token": TOKEN, "groups": {"1": "Test group"}}))
            loaded = load_config(path)
            self.assertEqual(loaded.remote_id, bytes.fromhex("aabb"))
            self.assertEqual(dict(loaded.groups), {1: "Test group"})
            self.assertNotIn(TOKEN, repr(loaded))
            with self.assertRaises(TypeError):
                loaded.groups[2] = "Second"
            for value in (
                {"remote_id": "aabb", "api_token": TOKEN, "groups": {"5": "Invalid"}},
                {"remote_id": "aabb", "api_token": "short", "groups": {"1": "Test"}},
                {"remote_id": "aabb", "api_token": TOKEN, "groups": {}},
                {"remote_id": "aabb", "api_token": TOKEN, "groups": {"1": "Test"}, "extra": 1},
            ):
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load_config(path)
            path.write_text('{"remote_id":"aabb","remote_id":"ccdd"}')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_dry_run_does_not_confirm_position(self) -> None:
        service = BridgeService(config(), DryRunBackend())
        result = service.dispatch({"group": 1, "action": "up"})
        self.assertEqual(result["status"], "simulated")
        self.assertEqual(result["delivery"], "unverified")
        self.assertFalse(result["position_confirmed"])
        self.assertEqual(result["backend"]["frames_sent"], 0)
        self.assertEqual(len(result["request_id"]), 32)
        self.assertEqual(service.health()["transmit_status"], "idle")

    def test_successful_idempotency_does_not_repeat_backend(self) -> None:
        calls = []
        def backend(command):
            calls.append(command)
            return {"status": "sent", "frames_sent": 42, "position_confirmed": True, "position": "open"}
        service = BridgeService(config(), backend)
        request = {"group": 1, "action": "up", "request_id": "operation-1"}
        first = service.dispatch(request)
        first["backend"]["frames_sent"] = 999  # Caller mutation cannot change cached result.
        replay = service.dispatch(request)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].payload.hex(), "aabb2001a1")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["backend"]["frames_sent"], 42)
        self.assertFalse(replay["position_confirmed"])
        self.assertNotIn("position", replay)
        with self.assertRaises(BridgeError) as error:
            service.dispatch(dict(request, action="down"))
        self.assertEqual(error.exception.code, "idempotency_conflict")

    def test_concurrent_transmissions_are_rejected_not_queued(self) -> None:
        entered, release = threading.Event(), threading.Event()
        results = []
        def backend(command):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test timeout")
            return {"status": "sent"}
        service = BridgeService(config(), backend)
        worker = threading.Thread(target=lambda: results.append(service.dispatch({"group": 1, "action": "up"})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(service.health()["transmit_status"], "busy")
            with self.assertRaises(BridgeError) as error:
                service.dispatch({"group": 3, "action": "down"})
            self.assertEqual((error.exception.status, error.exception.code), (409, "busy"))
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)

    def test_failure_is_not_cached_and_lock_is_released(self) -> None:
        attempts = []
        def backend(command):
            attempts.append(command)
            if len(attempts) == 1:
                raise RuntimeError("private backend exception detail")
            return {"status": "submitted"}
        service = BridgeService(config(), backend)
        request = {"group": 1, "action": "down", "request_id": "retryable"}
        with self.assertRaises(BridgeError) as error:
            service.dispatch(request)
        self.assertEqual(error.exception.status, 502)
        self.assertNotIn("private backend", str(error.exception))
        self.assertEqual(service.dispatch(request)["status"], "submitted")
        self.assertEqual(len(attempts), 2)

    def test_bounded_idempotency_cache_and_input_rejections(self) -> None:
        calls = []
        def backend(command):
            calls.append(command)
            return {"status": "sent"}
        service = BridgeService(config(), backend, cache_size=2)
        for request_id in ("a", "b", "c", "a"):
            service.dispatch({"group": 1, "action": "up", "request_id": request_id})
        self.assertEqual(len(calls), 4)
        for request in (
            [], {}, {"group": True, "action": "up"}, {"group": 1.0, "action": "up"},
            {"group": 2, "action": "up"}, {"group": 1, "action": "stop"},
            {"group": 1, "action": "up", "position": "open"},
            {"group": 1, "action": "up", "request_id": ""},
            {"group": 1, "action": "up", "request_id": "invalid key"},
        ):
            with self.subTest(request=request), self.assertRaises(BridgeError) as error:
                service.dispatch(request)
            self.assertEqual(error.exception.status, 400)
        self.assertEqual(len(calls), 4)


class BridgeHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        def backend(command):
            self.calls.append(command)
            return {"status": "sent", "frames_sent": 12, "duration_seconds": .1,
                    "channels_hz": [2_433_000_000, 2_452_000_000, 2_471_000_000]}
        self.service = BridgeService(config(), backend)
        self.server = make_server(self.service, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            value = response.read().decode("utf-8")
            return response.status, value, dict(response.getheaders())
        finally:
            connection.close()

    def auth(self, **extra):
        return {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json", **extra}

    def test_get_resources_never_transmit_or_expose_credentials(self) -> None:
        for path in ("/health", "/api/groups", "/"):
            status, body, headers = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertNotIn(TOKEN, body)
            self.assertNotIn("aabb", body)
            self.assertEqual(headers["Cache-Control"], "no-store")
        status, body, _ = self.request("GET", "/api/commands?group=1&action=up")
        self.assertEqual(status, 405)
        self.assertEqual(self.calls, [])

    def test_authenticated_command_and_replay(self) -> None:
        headers = self.auth(Origin=f"http://127.0.0.1:{self.server.server_port}")
        request = json.dumps({"group": 1, "action": "up", "request_id": "http-operation"})
        first = self.request("POST", "/api/commands", request, headers)
        second = self.request("POST", "/api/commands", request, headers)
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        result = json.loads(second[1])
        self.assertTrue(result["replayed"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["delivery"], "unverified")
        self.assertFalse(result["position_confirmed"])
        self.assertEqual(len(self.calls), 1)

    def test_bad_token_cross_origin_and_rebinding_host_rejected(self) -> None:
        request = json.dumps({"group": 1, "action": "up"})
        for headers, expected in (
            ({"Content-Type": "application/json"}, 401),
            (self.auth(Authorization="Bearer wrong-token-value"), 401),
            (self.auth(Origin="http://other.example"), 403),
            (self.auth(Origin="null"), 403),
            (self.auth(Host=f"other.example:{self.server.server_port}"), 400),
        ):
            with self.subTest(headers=headers):
                status, _, _ = self.request("POST", "/api/commands", request, headers)
                self.assertEqual(status, expected)
        self.assertEqual(self.calls, [])

    def test_invalid_body_and_commands_do_not_transmit(self) -> None:
        for body, headers, expected in (
            ("x" * 4097, self.auth(), 413),
            ("{}", self.auth(**{"Content-Type": "text/plain"}), 415),
            ("not JSON", self.auth(), 400),
            ('{"group":1,"action":"up","extra":true}', self.auth(), 400),
            ('{"group":1,"group":3,"action":"up"}', self.auth(), 400),
            ('{"group":1.0,"action":"up"}', self.auth(), 400),
            ("[]", self.auth(), 400),
            ("[" * 1500 + "]" * 1500, self.auth(), 400),
            ('{"group":1,"action":"up"}', self.auth(**{"Transfer-Encoding": "chunked"}), 400),
        ):
            with self.subTest(body=body[:40], expected=expected):
                status, _, _ = self.request("POST", "/api/commands", body, headers)
                self.assertEqual(status, expected)
        self.assertEqual(self.calls, [])

    def test_default_binding_and_wildcard_requires_explicit_hosts(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            make_server(self.service, host="0.0.0.0", port=0)

    def test_server_close_waits_for_inflight_backend(self) -> None:
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        results = []
        def backend(command):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test timeout")
            return {"status": "sent"}
        self.service.backend = backend
        client = threading.Thread(target=lambda: results.append(self.request(
            "POST", "/api/commands", '{"group":1,"action":"up"}', self.auth())))
        client.start()
        closer = None
        try:
            self.assertTrue(entered.wait(1))
            self.server.shutdown()
            def close():
                self.server.server_close()
                closed.set()
            closer = threading.Thread(target=close)
            closer.start()
            self.assertFalse(closed.wait(.05))
        finally:
            release.set()
            client.join(2)
            if closer is not None:
                closer.join(2)
        self.assertFalse(client.is_alive())
        self.assertTrue(closed.is_set())
        self.assertEqual(results[0][0], 200)


if __name__ == "__main__":
    unittest.main()
