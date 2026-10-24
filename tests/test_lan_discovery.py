# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import ipaddress
import socket
import struct
import threading
import unittest
from unittest.mock import patch

from hd_platinum.lan_discovery import discovery_response, make_discovery_server


def query(name="PLATLINK-PDBU", *, kind=0x20, flags=0x0110, suffix=0):
    raw = b"*" + bytes(15) if name == "*" else name.encode("ascii").ljust(15, b" ") + bytes((suffix,))
    encoded = bytes(65 + int(nibble, 16) for nibble in raw.hex())
    return struct.pack("!6H", 0xBEEF, flags, 1, 0, 0, 0) + b"\x20" + encoded + b"\0" + struct.pack("!HH", kind, 1)


class DiscoveryPacketTests(unittest.TestCase):
    def test_named_query_returns_only_explicit_advertised_ip(self):
        for name in ("PLATLINK-PDBU", "PLATLINK-FDBU", "PlatLink-PDBU"):
            for suffix in (0, 0x20):
                with self.subTest(name=name, suffix=suffix):
                    request = query(name, suffix=suffix)
                    response = discovery_response(request, "192.168.44.19")
                    self.assertIsNotNone(response)
                    transaction, flags, questions, answers, authority, additional = struct.unpack_from("!6H", response)
                    self.assertEqual(transaction, 0xBEEF)
                    self.assertTrue(flags & 0x8000)
                    self.assertEqual(flags & 0xF, 0)
                    self.assertEqual((questions, answers, authority, additional), (0, 1, 0, 0))
                    self.assertEqual(response[12:46], request[12:46])
                    self.assertEqual(struct.unpack_from("!HHIH", response, 46), (0x20, 1, 30, 6))
                    self.assertEqual(response[56:], b"\x00\x00" + ipaddress.IPv4Address("192.168.44.19").packed)

    def test_status_returns_known_names_without_hardware_identity(self):
        for name in ("*", "PLATLINK-PDBU", "PLATLINK-FDBU"):
            response = discovery_response(query(name, kind=0x21), "192.168.44.19")
            self.assertEqual(struct.unpack_from("!HHIH", response, 46), (0x21, 1, 0, 83))
            data = response[56:]
            self.assertEqual(data[0], 2)
            self.assertEqual(data[1:16], b"PLATLINK-PDBU  ")
            self.assertEqual(data[19:34], b"PLATLINK-FDBU  ")
            self.assertEqual(data[37:], bytes(46))

    def test_bad_or_unrelated_datagrams_receive_no_reply(self):
        valid = query()
        malformed = [
            b"", valid[:11], valid[:-1], valid + b"\0", valid * 20,
            query("OTHER-COMPUTER"), query("*"), query(suffix=0x03),
            query(kind=1), query(flags=0x8500), query(flags=0x2910),
            valid[:12] + b"\xc0\x0c" + valid[14:],
            valid[:13] + b"Q" + valid[14:],
            valid[:45] + b"\x01" + valid[46:],
            valid[:48] + b"\x00\x03",
            valid[:4] + b"\x00\x02" + valid[6:],
            valid[:6] + b"\x00\x01" + valid[8:],
        ]
        for packet in malformed:
            with self.subTest(packet=packet):
                self.assertIsNone(discovery_response(packet, "192.168.44.19"))

    def test_legacy_reserved_flags_do_not_change_name_scope(self):
        self.assertIsNotNone(discovery_response(query(flags=0x010E), "192.168.44.19"))
        self.assertIsNone(discovery_response(query("UNRELATED", flags=0x010E), "192.168.44.19"))

    def test_advertisement_requires_literal_local_ipv4(self):
        for value in ("0.0.0.0", "255.255.255.255", "8.8.8.8", "::1", "localhost"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                discovery_response(query(), value)


class DiscoveryServerTests(unittest.TestCase):
    def test_allowlist_and_rate_limits_are_bounded(self):
        with make_discovery_server("127.0.0.1", host="127.0.0.1", port=0) as server:
            request = (query(), server.socket)
            self.assertFalse(server.verify_request(request, ("192.168.44.20", 1234)))
            with patch("hd_platinum.lan_discovery.time.monotonic", return_value=10):
                self.assertFalse(server.verify_request((b"X" * 1000, server.socket), ("127.0.0.1", 1234)))
                for _ in range(5):
                    self.assertTrue(server.verify_request(request, ("127.0.0.1", 1234)))
                self.assertFalse(server.verify_request(request, ("127.0.0.1", 1234)))
                for peer in range(2, 5):
                    for _ in range(5):
                        self.assertTrue(server.verify_request(request, (f"127.0.0.{peer}", 1234)))
                self.assertFalse(server.verify_request(request, ("127.0.0.5", 1234)))
                self.assertEqual(len(server._recent), 20)
            with patch("hd_platinum.lan_discovery.time.monotonic", return_value=11):
                self.assertTrue(server.verify_request(request, ("127.0.0.1", 1234)))
                self.assertEqual(len(server._recent), 1)

    def test_loopback_datagram_and_explicit_shutdown(self):
        with make_discovery_server("127.0.0.1", host="127.0.0.1", port=0) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(1)
                    client.sendto(query(), server.server_address)
                    response, peer = client.recvfrom(1024)
                    self.assertEqual(peer, server.server_address)
                    self.assertEqual(response, discovery_response(query(), "127.0.0.1"))
            finally:
                server.shutdown()
                thread.join(1)
            self.assertFalse(thread.is_alive())

    def test_invalid_configuration_fails_before_socket_creation(self):
        invalid = [
            {"host": "0.0.0.0"},
            {"allowed_clients": "127.0.0.1"},
            {"allowed_clients": []},
            {"allowed_clients": ["0.0.0.0/0"]},
            {"allowed_clients": ["::1"]},
            {"allowed_clients": ["8.8.8.8"]},
            {"port": True}, {"port": -1}, {"port": 65536},
            {"reuse_port": "yes"},
        ]
        for options in invalid:
            with self.subTest(options=options), patch("hd_platinum.lan_discovery.socket.socket") as create:
                with self.assertRaises(ValueError):
                    make_discovery_server("127.0.0.1", **{"host": "127.0.0.1", "port": 0, **options})
                create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
