#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only acceptance checks against a running gateway firmware instance.

Run the native simulator first, then from the repository root:

    python3 firmware/esp32_gateway/test/python/test_device_network.py --live

Defaults: HTTP 127.0.0.1:18080, legacy TCP 127.0.0.1:1523, Host
127.0.0.1:18080, and the fictional emulator configuration's development token.
Override the token with GATEWAY_TEST_TOKEN or --token-file. For other forwards:

    python3 firmware/esp32_gateway/test/python/test_device_network.py --live \
        --http-port 18087 --tcp-port 1529 --expected-host 127.0.0.1:18080

No inventories, positions, settings, or persistent state are changed. Empty
inventories are valid. Ordinary unittest discovery skips this live suite;
GATEWAY_DEVICE_TESTS=1 explicitly enables discovery using the same defaults.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import re
import socket
import time
import unittest

MAX_HTTP_BODY = 1024 * 1024
MAX_TCP_REPLY = 65536


@dataclass(frozen=True)
class Configuration:
    address: str = "127.0.0.1"
    http_port: int = 18080
    tcp_port: int = 1523
    expected_host: str = "127.0.0.1:18080"
    timeout: float = 8.0
    token: str = ""


def development_token() -> str:
    token = os.environ.get("GATEWAY_TEST_TOKEN")
    if token is None:
        path = Path(__file__).resolve().parents[2] / "include" / "gateway_emulator_config.h"
        match = re.search(r'^#define\s+GATEWAY_API_TOKEN\s+"([^"\r\n]+)"',
                          path.read_text(), re.MULTILINE)
        if not match:
            raise ValueError("Set GATEWAY_TEST_TOKEN or --token-file; emulator token was not found")
        token = match.group(1)
    return validate_token(token)


def validate_token(token: str) -> str:
    if len(token) < 32 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Test token must contain at least 32 printable ASCII characters without whitespace")
    return token


class TcpRecords:
    """Bounded, deadline-limited reader for the gateway's session-prefixed records."""

    def __init__(self, connection: socket.socket, timeout: float):
        self.connection = connection
        self.timeout = timeout
        self.pending = bytearray()
        self.session = None

    def record(self, deadline: float) -> str:
        while b"\n\r" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for a complete port 522 record")
            self.connection.settimeout(remaining)
            data = self.connection.recv(4096)
            if not data:
                raise ConnectionError("Port 522 closed before completing its response")
            self.pending.extend(data)
            if len(self.pending) > MAX_TCP_REPLY:
                raise ValueError("Port 522 response exceeded the acceptance-test limit")
        end = self.pending.index(b"\n\r")
        line = bytes(self.pending[:end]).decode("utf-8")
        del self.pending[:end + 2]
        match = re.fullmatch(r"([0-9]+) (.*)", line)
        if not match:
            raise ValueError("Port 522 returned a malformed session-prefixed record")
        session, payload = match.groups()
        if self.session is not None and session != self.session:
            raise ValueError("Port 522 changed the session ID on an existing connection")
        self.session = session
        return payload

    def until(self, payload: str) -> list[str]:
        deadline = time.monotonic() + self.timeout
        records = []
        size = 0
        while True:
            record = self.record(deadline)
            size += len(record.encode("utf-8")) + 16
            if size > MAX_TCP_REPLY:
                raise ValueError("Port 522 did not terminate its bounded response")
            records.append(record)
            if record == payload:
                return records


class DeviceNetworkTests(unittest.TestCase):
    configuration = None

    @classmethod
    def setUpClass(cls):
        if cls.configuration is None:
            if os.environ.get("GATEWAY_DEVICE_TESTS") != "1":
                raise unittest.SkipTest("Live device acceptance requires --live or GATEWAY_DEVICE_TESTS=1")
            cls.configuration = Configuration(token=development_token())

    def request(self, path: str, *, authorization=True, host=None):
        config = self.configuration
        connection = http.client.HTTPConnection(config.address, config.http_port,
                                                 timeout=config.timeout)
        self.addCleanup(connection.close)
        connection.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", config.expected_host if host is None else host)
        if authorization is not None:
            token = config.token if authorization is True else authorization
            connection.putheader("Authorization", "Bearer " + token)
        connection.putheader("Connection", "close")
        connection.endheaders()
        response = connection.getresponse()
        deadline = time.monotonic() + config.timeout
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.fail(f"HTTP {path} response exceeded the timeout")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(4096)
            if not chunk:
                break
            body.extend(chunk)
            self.assertLessEqual(len(body), MAX_HTTP_BODY, "HTTP response exceeded the test limit")
        self.assertIn("application/json", response.getheader("Content-Type", ""))
        result = json.loads(body)
        self.assertIsInstance(result, dict)
        status = response.status
        response.close()
        connection.close()
        return status, result

    def successful(self, path: str):
        status, result = self.request(path)
        self.assertEqual(status, 200, f"GET {path} failed with HTTP {status}")
        return result

    def services(self, value):
        self.assertIsInstance(value, dict)
        for name in ("tcp522", "http", "web"):
            self.assertIn(name, value)
            self.assertIs(type(value[name]), bool)

    def test_status_reports_healthy_storage_and_operation(self):
        status = self.successful("/api/status")
        self.assertIs(status["storage_ok"], True)
        self.assertIs(type(status["busy"]), bool)
        self.assertIsInstance(status["backend"], str)
        self.assertIsInstance(status["delivery"], str)
        self.services(status["services"])
        self.assertIsInstance(status["operation"]["id"], str)
        self.assertIsInstance(status["operation"]["status"], str)

    def test_read_only_inventory_endpoints_accept_empty_or_populated_state(self):
        for path, field in (("/api/rooms", "rooms"), ("/api/shades", "shades"),
                            ("/api/scenes", "scenes")):
            with self.subTest(endpoint=path):
                items = self.successful(path)[field]
                self.assertIsInstance(items, list)
                ids = set()
                for item in items:
                    self.assertIs(type(item["id"]), int)
                    self.assertGreaterEqual(item["id"], 0)
                    self.assertNotIn(item["id"], ids)
                    ids.add(item["id"])
                    self.assertIsInstance(item["name"], str)
                    if field == "shades":
                        self.assertIsInstance(item["room"], str)
                        self.assertIs(type(item["room_id"]), int)
                        self.assertIs(type(item["enabled"]), bool)
                        self.assertIs(type(item["features"]), int)
                        if item["position"] is not None:
                            self.assertIs(type(item["position"]), int)
                            self.assertTrue(0 <= item["position"] <= 255)
        records = self.successful("/api/inventory")["records"]
        self.assertIsInstance(records, list)
        self.assertTrue(all(isinstance(record, str) for record in records))
        self.assertTrue(any(record.startswith("$firm") for record in records))
        self.assertIn("$upd00-", records)
        self.assertIn("$upd01-", records)
        self.assertLess(records.index("$upd00-"), records.index("$upd01-"))

    def test_service_settings_are_boolean(self):
        self.services(self.successful("/api/settings"))

    def test_missing_and_incorrect_bearer_tokens_are_rejected(self):
        token = self.configuration.token
        incorrect = ("x" if token[0] != "x" else "y") + token[1:]
        for authorization in (None, incorrect):
            with self.subTest(authorization="missing" if authorization is None else "incorrect"):
                status, body = self.request("/api/status", authorization=authorization)
                self.assertEqual(status, 401)
                self.assertIsInstance(body.get("error"), str)

    def test_unexpected_host_is_rejected_with_a_valid_token(self):
        status, body = self.request("/api/status", host="rejected-device-test.invalid")
        self.assertEqual(status, 403)
        self.assertIsInstance(body.get("error"), str)

    def test_repeated_http_connections_release_server_resources(self):
        for connection in range(12):
            with self.subTest(connection=connection):
                self.assertIs(self.successful("/api/status")["storage_ok"], True)

    def test_legacy_banner_fragmented_keepalive_and_inventory_share_one_session(self):
        config = self.configuration
        with socket.create_connection((config.address, config.tcp_port), timeout=config.timeout) as connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            reader = TcpRecords(connection, config.timeout)
            banner = reader.record(time.monotonic() + config.timeout)
            self.assertIn("Shade Controller", banner)
            connection.sendall(b"$d")
            time.sleep(0.05)
            connection.sendall(b"my")
            self.assertIn("$ack", reader.until("$ack"))
            connection.sendall(b"$dat")
            inventory = reader.until("$upd01-")
            self.assertTrue(any(record.startswith("$firm") for record in inventory))
            self.assertIn("$upd00-", inventory)
            self.assertIn("$reset", inventory)
            self.assertLess(inventory.index("$upd00-"), inventory.index("$upd01-"))
            connection.sendall(b"$dmy")
            self.assertIn("$ack", reader.until("$ack"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="enable requests to the running firmware")
    parser.add_argument("--address", default="127.0.0.1", help="IP address to connect to")
    parser.add_argument("--http-port", type=int, default=18080)
    parser.add_argument("--tcp-port", type=int, default=1523)
    parser.add_argument("--expected-host", default="127.0.0.1:18080", help="exact Host header accepted by firmware")
    parser.add_argument("--timeout", type=float, default=8.0, help="per-response timeout in seconds")
    parser.add_argument("--token-file", type=Path, help="file containing the bearer token; otherwise GATEWAY_TEST_TOKEN or emulator fixture")
    args = parser.parse_args()
    if not args.live:
        parser.error("pass --live to explicitly enable the read-only device acceptance suite")
    if not (0 < args.http_port <= 65535 and 0 < args.tcp_port <= 65535 and 0 < args.timeout <= 300):
        parser.error("ports must be 1..65535 and timeout must be greater than zero and at most 300 seconds")
    if not args.expected_host or any(ord(c) <= 32 or ord(c) >= 127 for c in args.expected_host):
        parser.error("expected Host must be nonempty printable ASCII without whitespace")
    try:
        token = validate_token(args.token_file.read_text().strip()) if args.token_file else development_token()
    except (OSError, ValueError) as error:
        parser.error(str(error))
    DeviceNetworkTests.configuration = Configuration(args.address, args.http_port, args.tcp_port,
                                                     args.expected_host, args.timeout, token)
    print(f"Read-only gateway acceptance: HTTP {args.address}:{args.http_port}, TCP {args.address}:{args.tcp_port}", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DeviceNetworkTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
