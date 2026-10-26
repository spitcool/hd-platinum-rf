#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Mutating acceptance checks for the fictional RF-disabled instruction emulator.

Start tools/device_simulator.py, then run this file with --emulator-loopback.
The address and ports are fixed to loopback. Before any command, the suite
requires the simulated backend and the exact eight-shade sample identities and
control mappings. Ordinary unittest discovery skips it. These assertions cover
requested values and protocol completion; they never claim physical movement.
"""

import argparse
import http.client
import json
import socket
import time
import unittest
import uuid

from test_device_network import MAX_HTTP_BODY, TcpRecords, development_token


class EmulatorControlTests(unittest.TestCase):
    enabled = False
    evidence = []
    token = ""
    prefix = ""

    @classmethod
    def setUpClass(cls):
        if not cls.enabled:
            raise unittest.SkipTest("Mutating emulator acceptance requires --emulator-loopback")
        cls.token = development_token()
        cls.prefix = "emulator-" + uuid.uuid4().hex[:12]

    def request(self, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", 18080, timeout=8)
        try:
            data = None if payload is None else json.dumps(payload)
            connection.request("GET" if data is None else "POST", path, body=data,
                               headers={"Host": "127.0.0.1:18080",
                                        "Authorization": "Bearer " + self.token,
                                        "Content-Type": "application/json",
                                        "Connection": "close"})
            response = connection.getresponse()
            body = response.read(MAX_HTTP_BODY + 1)
            self.assertLessEqual(len(body), MAX_HTTP_BODY)
            result = json.loads(body)
            self.evidence.append({"path": path, "request": payload,
                                  "status": response.status, "response": result})
            return response.status, result
        finally:
            connection.close()

    def get(self, path):
        code, value = self.request(path)
        self.assertEqual(code, 200)
        return value

    def state(self):
        return {shade["id"]: shade for shade in self.get("/api/shades")["shades"]}

    @staticmethod
    def values(shades):
        return {(shade_id, control["feature"]): control["requested_value"]
                for shade_id, shade in shades.items() for control in shade["controls"]}

    def setUp(self):
        status = self.get("/api/status")
        self.assertEqual(status["backend"], "simulated", "Refuse a radio backend")
        self.assertIs(status["storage_ok"], True)
        self.assertIs(status["busy"], False)
        self.assertEqual(status["native_qualified_features"], 0)
        self.assertEqual(status["native_bench_features"], 0)
        self.assertEqual(status["delivery"], "unverified")
        self.assertIs(status["full_compatibility"], False)
        rooms = self.get("/api/rooms")["rooms"]
        self.assertEqual([(r["id"], r["name"]) for r in rooms],
                         [(0, "Bottom-up"), (1, "Dual rail"), (2, "Top-down"), (3, "Sheers")])
        shades = self.state()
        self.assertEqual([(s["id"], s["name"]) for s in shades.values()],
                         list(enumerate(("East window", "West window", "Left shade", "Right shade",
                                         "Desk window", "Door shade", "Front sheer", "Side sheer"))))
        self.assertTrue(all(s["observed_position"] is None for s in shades.values()))
        for shade_id, shade in shades.items():
            self.assertEqual(shade["room_id"], shade_id // 2)
            self.assertEqual(shade["product"], (1, 2, 3, 6)[shade_id // 2])
            controls = {c["feature"]: c for c in shade["controls"]}
            expected = {4, 10} | ({18} if shade_id in (2, 3) else set())
            if shade_id in (6, 7):
                expected |= {7, 19}
            self.assertEqual(set(controls), expected)
            for feature, control in controls.items():
                self.assertTrue(control["granted"] and control["available"] and control["backend_supported"])
                expected_open = (0 if shade_id in (4, 5) else 255) if feature == 4 else 255 if feature == 18 else None
                self.assertEqual(control["open_value"], expected_open)
                self.assertEqual(control["close_value"], None if expected_open is None else 255 - expected_open)

    def complete(self, request_id=None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = self.get("/api/status")
            if not status["busy"]:
                self.assertEqual(status["backend"], "simulated")
                if request_id is not None:
                    self.assertEqual(status["operation"], {"id": request_id, "status": "simulated"})
                return
            time.sleep(.02)
        self.fail("Simulated operation did not complete")

    def change(self, payload, expected):
        before = self.values(self.state())
        request_id = self.prefix + "-" + str(len(self.evidence))
        code, result = self.request("/api/positions", {**payload, "request_id": request_id})
        self.assertEqual(code, 200, result)
        self.assertEqual(result["backend"], "simulated")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["delivery"], "unverified")
        for (shade, feature), value in expected.items():
            self.assertIn(f"$cp{shade:02d}-{feature:02d}-{value:03d}-", result["records"])
        self.complete(request_id)
        before.update(expected)
        after = self.state()
        self.assertEqual(self.values(after), before, "An unrelated historical request changed")
        for shade, feature in expected:
            self.assertEqual(after[shade]["last_requested_feature"], feature)
            for control in after[shade]["controls"]:
                if control["requested_value"] is not None:
                    self.assertEqual(control["request_status"],
                                     "latest" if control["feature"] == feature else "earlier")

    def test_bottom_up_and_top_down_endpoints_are_opposite(self):
        for endpoint, bottom, top in (("open", 255, 0), ("close", 0, 255)):
            self.change({"shade": 0, "endpoint": endpoint}, {(0, 4): bottom})
            self.change({"shade": 4, "endpoint": endpoint}, {(4, 4): top})

    def test_dual_rail_history_and_latest_command(self):
        self.change({"shade": 2, "feature": 4, "position": 127}, {(2, 4): 127})
        self.change({"shade": 2, "feature": 18, "position": 191}, {(2, 18): 191})
        self.change({"shade": 2, "feature": 18, "endpoint": "open"}, {(2, 18): 255})
        self.change({"shade": 2, "feature": 4, "endpoint": "open"}, {(2, 4): 255})
        records = self.get("/api/inventory")["records"]
        self.assertEqual([r for r in records if r.startswith("$cp02-")], ["$cp02-04-255-"])

    def test_group_endpoints_preserve_per_feature_history(self):
        self.change({"room": 1, "feature": 4, "endpoint": "close"}, {(2, 4): 0, (3, 4): 0})
        self.change({"room": 1, "feature": 18, "endpoint": "close"}, {(2, 18): 0, (3, 18): 0})

    def test_tilt_families_and_preset_use_explicit_features(self):
        self.change({"shade": 6, "feature": 7, "position": 63}, {(6, 7): 63})
        self.change({"shade": 6, "feature": 19, "position": 192}, {(6, 19): 192})
        self.change({"shade": 6, "feature": 10, "position": 7}, {(6, 10): 7})

    def test_unavailable_and_unmapped_controls_do_not_change_requested_values(self):
        before = self.values(self.state())
        for payload in ({"shade": 0, "feature": 18, "position": 128},
                        {"shade": 6, "feature": 7, "endpoint": "open"},
                        {"shade": 6, "feature": 10, "position": 8}):
            code, result = self.request("/api/positions", {**payload, "request_id": self.prefix + "-reject"})
            self.assertEqual(code, 409, result)
        self.assertEqual(self.values(self.state()), before)
        self.assertIs(self.get("/api/status")["busy"], False)

    def test_json_types_are_rejected_without_coercion_or_state_change(self):
        before = self.values(self.state())
        cases = (("/api/positions", {"shade": 0, "position": 128, "request_id": 12345678}),
                 ("/api/positions", {"shade": 0, "position": True, "request_id": self.prefix + "-bool"}),
                 ("/api/positions", {"shade": 0, "endpoint": 0, "request_id": self.prefix + "-endpoint"}),
                 ("/api/command", {"command": 12345678, "request_id": self.prefix + "-command"}))
        for path, payload in cases:
            with self.subTest(path=path, payload=payload):
                code, result = self.request(path, payload)
                self.assertEqual(code, 400, result)
        self.assertEqual(self.values(self.state()), before)
        self.assertIs(self.get("/api/status")["busy"], False)

    def test_fragmented_tcp_stages_two_features_until_one_release(self):
        before = self.values(self.state())
        with socket.create_connection(("127.0.0.1", 1523), timeout=8) as connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            reader = TcpRecords(connection, 8)
            self.assertIn("Shade Controller", reader.record(time.monotonic() + 8))
            for fragments in ((b"$p", b"ss03-04-", b"129-"), (b"$pss03-", b"18-", b"064-")):
                for fragment in fragments:
                    connection.sendall(fragment)
                    time.sleep(.01)
                replies = reader.until("$done")
                self.assertFalse(any(x.startswith("$error") for x in replies))
            self.assertEqual(self.values(self.state()), before, "Staging changed committed requests")
            connection.sendall(b"$r")
            time.sleep(.01)
            connection.sendall(b"ls")
            replies = reader.until("$act00-00-")
            self.assertIn("$cp03-04-129-", replies)
            self.assertIn("$cp03-18-064-", replies)
            self.assertFalse(any(x.startswith("$error") for x in replies))
            self.evidence.append({"fragmented_tcp_release_records": replies})
        self.complete()
        before.update({(3, 4): 129, (3, 18): 64})
        self.assertEqual(self.values(self.state()), before)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator-loopback", action="store_true")
    parser.add_argument("--evidence", help="Optional JSON request/response evidence output")
    args = parser.parse_args()
    if not args.emulator_loopback:
        parser.error("pass --emulator-loopback to enable fictional simulated-state changes")
    EmulatorControlTests.enabled = True
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(EmulatorControlTests))
    if args.evidence:
        with open(args.evidence, "x") as output:
            json.dump({"physical_hardware_accessed": False, "rf_backend": "simulated",
                       "passed": result.wasSuccessful(), "tests": result.testsRun,
                       "requests": EmulatorControlTests.evidence}, output, indent=2)
            output.write("\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
