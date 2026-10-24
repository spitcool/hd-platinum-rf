# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Original-app metadata flows over loopback, with fictional IDs and fake RF."""

from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from hd_platinum.bridge import BridgeConfig, BridgeService, DryRunBackend, ShadeConfig
from hd_platinum.lan import BridgeRecord, RecordFramer, parse_records
from hd_platinum.lan_server import (
    BANNER, CHECK_YEAR_REPLY, ERROR_BUSY, ERROR_ROOM_FULL, ERROR_TARGET, make_lan_server,
)


OPAQUE = b"$ct\x00\xfffictional-$title"


def inventory():
    return parse_records(BridgeRecord.from_raw(payload) for payload in (
        BANNER, b"$upd00-", b"$reset", OPAQUE,
        b"$cr00-01-0x1A2B-First room", b"$cs00-00-01-First shade",
        b"$cp00-04-000-", b"$upd01-"))


class Peer:
    def __init__(self, address):
        self.socket = socket.create_connection(address, timeout=2)
        self.socket.settimeout(2)
        self.framer, self.pending = RecordFramer(), []
        if self.read_until(BANNER) != [BANNER]:
            raise AssertionError("unexpected connection greeting")

    def send(self, data):
        self.socket.sendall(data)

    def read_until(self, marker):
        result = []
        while True:
            if not self.pending:
                data = self.socket.recv(65536)
                if not data:
                    raise EOFError("connection closed before expected response")
                self.pending.extend(self.framer.feed(data))
            while self.pending:
                record = self.pending.pop(0)
                result.append(record.payload)
                if record.payload == marker:
                    return result

    def exchange(self, command):
        # A supported reply-bearing command makes absence of edit acknowledgments
        # observable without relying on sleeps or a short socket timeout.
        self.send(command + b"$chksy2026-")
        return self.read_until(CHECK_YEAR_REPLY)[:-1]

    def snapshot(self, command=b"$dat"):
        self.send(command)
        return self.read_until(b"$upd01-")

    def close(self):
        self.socket.close()


class LANSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "positions.json"
        self.servers, self.calls = [], []
        self.addCleanup(self.stop_all)

    def backend(self, command):
        self.calls.append(command)
        return {"status": "submitted"}

    def start(self, *, backend=None, **options):
        config = BridgeConfig(b"\xaa\xbb", {}, "fictional-setup-token-123456789", {
            0: ShadeConfig("First shade", 0, b"\x1a\x2b", 1,
                           position_enabled=True, sync_enabled=True),
        })
        bridge = BridgeService(config, DryRunBackend(),
                               position_backend=backend or self.backend,
                               sync_backend=self.backend)
        server = make_lan_server(bridge, inventory(), port=0,
                                 state_path=self.state_path, **options)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": .01})
        thread.start()
        self.servers.append((server, thread))
        return server

    def stop(self, server):
        entry = next(entry for entry in self.servers if entry[0] is server)
        server.shutdown()
        server.server_close()
        entry[1].join(2)
        self.assertFalse(entry[1].is_alive())
        self.servers.remove(entry)

    def stop_all(self):
        for server, _ in self.servers[:]:
            self.stop(server)

    def peer(self, server):
        peer = Peer(server.server_address)
        self.addCleanup(peer.close)
        return peer

    def add_room(self, peer):
        with patch("hd_platinum.lan_server.secrets.token_bytes", return_value=b"\x3c\x4d"):
            self.assertEqual(peer.exchange(b"$ar01-11-Second room"),
                             [b"$cr01-01-0x3C4D-Second room"])

    def test_fragmented_utf8_names_use_utf16_length_and_one_create_reply(self):
        first_received = threading.Event()
        chunks = []

        def journal(direction, peer, connection, data):
            if direction == "receive":
                chunks.append(data)
                first_received.set()

        server = self.start(wire_journal=journal)
        peer = self.peer(server)
        name = "A😀$-é"  # Six UTF-16 units, nine UTF-8 bytes, five characters.
        wire = b"$ar01-6-" + name.encode()
        split = len(b"$ar01-6-A") + 2  # In the middle of the four-byte emoji.
        with patch("hd_platinum.lan_server.secrets.token_bytes", return_value=b"\x3c\x4d"):
            peer.send(wire[:split])
            self.assertTrue(first_received.wait(2))
            peer.send(wire[split:] + b"$as1-5-Blind$chksy2026-")
            self.assertEqual(peer.read_until(CHECK_YEAR_REPLY), [
                b"$cr01-01-0x3C4D-" + name.encode(),
                b"$cs01-01-01-Blind", CHECK_YEAR_REPLY])
        self.assertEqual(chunks[0], wire[:split])
        self.assertEqual(server.positions.inventory.rooms[1].name, name)
        self.assertEqual(server.positions.inventory.shades[1].positions, {})
        self.assertNotIn(1, server.service.config.shades)
        self.assertEqual(self.calls, [])

    def test_silent_edits_and_requested_position_survive_restart(self):
        server = self.start()
        peer = self.peer(server)
        peer.send(b"$pss00-04-170-$rls")
        peer.read_until(b"$act00-00-")
        self.add_room(peer)
        self.assertEqual(peer.exchange(b"$as1-5-Blind"), [b"$cs01-01-01-Blind"])
        self.assertEqual(peer.exchange(b"$mer0-1-7-Renamed$mes0-0-8-New name"), [])
        before = peer.snapshot()
        self.assertIn(b"$cr00-01-0x1A2B-Renamed", before)
        self.assertIn(b"$cs00-00-01-New name", before)
        self.assertIn(b"$cp00-04-170-", before)
        self.assertIn(OPAQUE, before)
        self.assertTrue(server.service.config.shades[0].position_enabled)
        self.stop(server)
        restored = self.start()
        self.assertEqual(self.peer(restored).snapshot(), before)
        self.assertEqual(restored.positions.values, {0: 170})
        self.assertEqual(len(self.calls), 1)

    def test_product_validation_and_eight_shade_limit_leave_state_unchanged(self):
        server = self.start()
        peer = self.peer(server)
        before = server.positions.snapshot()
        self.assertEqual(peer.exchange(b"$ar19-3-Bad$mer0-19-3-Bad"), [ERROR_TARGET, ERROR_TARGET])
        self.assertEqual(server.positions.snapshot(), before)
        with patch("hd_platinum.lan_server.secrets.token_bytes", return_value=b"\x3c\x4d"):
            self.assertEqual(peer.exchange(b"$ar30-5-Liner"), [b"$cr01-30-0x3C4D-Liner"])
        for shade in range(1, 8):
            name = f"Blind {shade}".encode()
            self.assertEqual(peer.exchange(b"$as0-7-" + name),
                             [f"$cs{shade:02d}-00-{shade + 1:02d}-".encode() + name])
        before = server.positions.snapshot()
        self.assertEqual(peer.exchange(b"$as0-8-Overflow"), [ERROR_ROOM_FULL])
        self.assertEqual(server.positions.snapshot(), before)
        self.assertEqual(peer.exchange(b"$as1-5-Blind"), [b"$cs08-01-01-Blind"])
        before = server.positions.snapshot()
        self.assertEqual(peer.exchange(b"$mes8-0-5-Moved"), [ERROR_ROOM_FULL])
        self.assertEqual(server.positions.snapshot(), before)
        self.assertEqual(peer.exchange(b"$mes0-0-7-Renamed"), [])
        self.assertEqual(server.positions.inventory.shades[0].name, "Renamed")
        self.assertEqual(self.calls, [])

    def test_tail_deletes_return_snapshots_and_reject_holes(self):
        server = self.start()
        peer = self.peer(server)
        self.add_room(peer)
        self.assertEqual(peer.exchange(b"$as1-5-Blind"), [b"$cs01-01-01-Blind"])
        before = server.positions.snapshot()
        self.assertEqual(peer.exchange(b"$rs00-$rr00-"), [ERROR_TARGET, ERROR_TARGET])
        self.assertEqual(server.positions.snapshot(), before)
        deleted_shade = peer.snapshot(b"$rs01-")
        self.assertEqual(deleted_shade, server.positions.snapshot())
        self.assertFalse(any(value.startswith(b"$cs01-") for value in deleted_shade))
        self.assertEqual(peer.exchange(b"$as1-5-Again"), [b"$cs01-01-01-Again"])
        deleted_room = peer.snapshot(b"$rr01-")
        self.assertEqual(deleted_room, server.positions.snapshot())
        self.assertFalse(any(value.startswith((b"$cr01-", b"$cs01-")) for value in deleted_room))
        self.assertEqual(set(server.positions.inventory.shades), {0})
        self.assertIn(OPAQUE, deleted_room)
        self.assertEqual(self.calls, [])

    def test_recreated_numeric_id_cannot_inherit_position_or_sync_permission(self):
        server = self.start()
        peer = self.peer(server)
        peer.snapshot(b"$rs00-")
        self.assertEqual(peer.exchange(b"$as0-11-Replacement"), [b"$cs00-00-01-Replacement"])
        self.assertEqual(peer.exchange(b"$pss00-04-128-$rsc00-"), [ERROR_TARGET, ERROR_TARGET])
        self.assertFalse(server.service.config.shades[0].position_enabled)
        self.assertFalse(server.service.config.shades[0].sync_enabled)
        self.stop(server)
        restored = self.start()
        self.assertFalse(restored.service.config.shades[0].sync_enabled)
        self.assertEqual(self.calls, [])

    def test_metadata_change_is_busy_while_fake_rf_is_running(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def blocked(command):
            self.calls.append(command)
            entered.set()
            if not release.wait(2):
                raise RuntimeError("fake RF was not released")
            return {"status": "submitted"}

        server = self.start(backend=blocked)
        controller, editor = self.peer(server), self.peer(server)
        controller.send(b"$pss00-04-170-$rls")
        self.assertTrue(entered.wait(2))
        editor.send(b"$mer0-1-7-Changed")
        self.assertEqual(editor.read_until(ERROR_BUSY), [ERROR_BUSY])
        self.assertEqual(server.positions.inventory.rooms[0].name, "First room")
        release.set()
        controller.read_until(b"$act00-00-")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
