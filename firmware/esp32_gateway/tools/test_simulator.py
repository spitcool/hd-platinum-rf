#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise browser/API adapters against the actual native gateway process."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simulator import Gateway, handler


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = Gateway(cls.binary)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        cls.server.RequestHandlerClass = handler(cls.gateway, cls.server.server_port)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.gateway.close()

    def call(self, path, value=None, method=None, auth=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self.gateway.token
        if origin:
            headers["Origin"] = origin
        request = Request(self.url + path, data=None if value is None else json.dumps(value).encode(),
                          headers=headers, method=method)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.code, json.loads(raw) if "json" in response.headers["Content-Type"] else raw

    def setUp(self):
        self.assertEqual(self.call("/sim/reset", {})[0], 200)

    def tap(self, x, y):
        self.call("/sim/touch", {"down": True, "x": x, "y": y})
        return self.call("/sim/touch", {"down": False, "x": x, "y": y})[1]

    def settled(self):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            state = self.call("/sim/state")[1]
            if not state["busy"]:
                return state
            time.sleep(.05)
        self.fail("gateway job did not finish")

    def test_touch_shade_and_room_use_same_inventory(self):
        self.tap(60, 90)
        state = self.tap(70, 150)
        self.assertTrue(state["busy"])
        self.assertEqual(state["shades"][0]["position"], 255)
        self.settled()
        self.tap(35, 15)
        self.tap(220, 47)
        self.tap(60, 90)
        self.tap(220, 150)
        state = self.settled()
        self.assertEqual([s["position"] for s in state["shades"] if s["room_id"] == 0], [0, 0])
        self.assertEqual(self.call("/api/shades")[1]["shades"], state["shades"])

    def test_api_receipts_and_touch_during_busy(self):
        command = {"shade": 0, "position": 0, "request_id": "local-test-0001"}
        code, receipt = self.call("/api/positions", command)
        self.assertEqual(code, 200)
        self.assertEqual(receipt["status"], "submitted")
        read = {"command": "$dmy", "request_id": "local-read-0001"}
        self.assertEqual(self.call("/api/command", read)[0], 200)
        self.tap(60, 90)  # Navigation must not replace the API operation identity.
        self.assertEqual(self.call("/api/status")[1]["operation"]["id"], command["request_id"])
        self.assertEqual(self.call("/api/positions", command)[0], 200)
        self.assertEqual(self.call("/api/positions", {**command, "position": 255})[0], 409)
        self.settled()
        self.assertEqual(self.call("/api/positions", command)[1]["status"], "completed")
        bad = {"command": "$bad", "request_id": "local-test-0002"}
        self.assertEqual(self.call("/api/command", bad)[0], 409)
        self.assertEqual(self.call("/api/positions", command)[1]["status"], "completed")

    def test_auth_services_and_reset(self):
        self.assertEqual(self.call("/api/shades", auth=False)[0], 401)
        self.assertEqual(self.call("/sim/reset", {}, origin="https://example.com")[0], 403)
        self.assertEqual(self.call("/web")[0], 200)
        self.assertEqual(self.call("/api/settings", {"http": False}, method="PATCH")[0], 200)
        self.assertEqual(self.call("/api/shades")[0], 503)
        self.assertEqual(self.call("/web")[0], 503)
        self.tap(60, 90)
        self.assertTrue(self.tap(70, 150)["busy"])
        self.call("/sim/reset", {})
        self.assertEqual(self.call("/api/shades")[0], 200)

    def test_drag_and_cancel_do_not_dispatch(self):
        self.tap(60, 90)
        for down, x in [(True, 60), (True, 100), (False, 60)]:
            state = self.call("/sim/touch", {"down": down, "x": x, "y": 150})[1]
        self.assertFalse(state["busy"])
        self.call("/sim/touch", {"down": True, "x": 60, "y": 150})
        self.call("/sim/cancel", {})
        state = self.call("/sim/touch", {"down": False, "x": 60, "y": 150})[1]
        self.assertFalse(state["busy"])
        self.assertEqual(state["command"], "")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    SimulatorTests.binary = args.binary.resolve()
    unittest.main(argv=[__file__], verbosity=2)
