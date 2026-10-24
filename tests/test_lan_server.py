# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fictional inventory and loopback-only original bridge compatibility checks."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hd_platinum.bridge import BridgeConfig, BridgeError, BridgeService, DryRunBackend, JogCommand, ShadeConfig, SyncCommand
from hd_platinum.lan import BridgeRecord, RecordFramer, parse_records, query_inventory
from hd_platinum.lan_control import PositionTransaction
from hd_platinum.lan_server import (
    BANNER, CHECK_YEAR_REPLY, ERROR_BACKEND, ERROR_BUSY, ERROR_CLOCK, ERROR_LIMIT, ERROR_STAGE, ERROR_TARGET,
    ERROR_UNSUPPORTED, _Commands, load_inventory, make_lan_server,
)


PAYLOADS = [
    BANNER, b"$firm03-2018-HD gateway test", b"$MAC0x001122334455-", b"$LEDl064-",
    b"$upd00-", b"$reset", b"$set006-", b"$ct\x00\xffopaque-$",
    b"$cr02-01-0x1A2B-Fictional room", b"$cs03-02-01-Fictional shade",
    b"$cp03-04-000-", b"$cs04-02-02-Disabled shade", b"$cp04-04-128-",
    b"$cs05-02-03-Unconfigured shade", b"$cp05-04-255-", b"$upd01-",
]


def inventory():
    return parse_records(BridgeRecord.from_raw(b"12 " + payload) for payload in PAYLOADS)


def service(backend=None):
    config = BridgeConfig(b"\xaa\xbb", {}, "fictional-lan-test-token-123456789", {
        3: ShadeConfig("Fictional shade", 2, b"\x1a\x2b", 1, position_enabled=True),
        4: ShadeConfig("Disabled shade", 2, b"\x1a\x2b", 2, position_enabled=False),
    })
    return BridgeService(config, DryRunBackend(), position_backend=backend or DryRunBackend())


def setup_inventory():
    return parse_records(BridgeRecord.from_raw(payload) for payload in (
        BANNER, b"$upd00-", b"$reset", b"$ct\x00\xffopaque-$",
        b"$cr00-01-0x1A2B-Existing room", b"$cs00-00-01-Existing shade",
        b"$cp00-04-000-", b"$upd01-"))


def setup_service(backend=None):
    config = BridgeConfig(b"\xaa\xbb", {}, "fictional-lan-test-token-123456789", {
        0: ShadeConfig("Existing shade", 0, b"\x1a\x2b", 1, position_enabled=True),
    })
    return BridgeService(config, DryRunBackend(), position_backend=backend or DryRunBackend())


class Peer:
    def __init__(self, address):
        self.socket = socket.create_connection(address, timeout=2)
        self.socket.settimeout(2)
        self.framer = RecordFramer()
        self.pending = []
        self.connection_id = self.read_until(BANNER)[-1].connection_id

    def send(self, data):
        self.socket.sendall(data)

    def read_until(self, marker):
        records = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self.pending:
                data = self.socket.recv(65536)
                if not data:
                    raise EOFError("server closed before marker")
                self.pending.extend(self.framer.feed(data))
            while self.pending:
                record = self.pending.pop(0)
                records.append(record)
                if record.payload == marker:
                    return records
        raise TimeoutError("marker not received")

    def close(self):
        self.socket.close()


class LANServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.servers = []
        self.addCleanup(self.stop_servers)

    def stop_servers(self):
        for server, thread in reversed(self.servers):
            server.shutdown()
            server.server_close()
            thread.join(2)

    def start(self, bridge=None, inventory_source=None, **kwargs):
        server = make_lan_server(bridge or service(), inventory_source or inventory(), port=0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
        thread.start()
        self.servers.append((server, thread))
        return server

    def peer(self, server):
        peer = Peer(server.server_address)
        self.addCleanup(peer.close)
        return peer

    def test_wire_journal_records_unknown_requests_and_failure_does_not_retry(self):
        journal, calls = [], []

        def record(direction, peer, connection, data):
            journal.append((direction, data))

        server = self.start(wire_journal=record)
        peer = self.peer(server)
        peer.send(b"$unknown")
        peer.read_until(ERROR_UNSUPPORTED)
        self.assertIn(("receive", b"$unknown"), journal)

        def broken(*args):
            raise OSError("fictional diagnostic write failure")

        def backend(command):
            calls.append(command)
            return {"status": "submitted"}

        with self.assertLogs("hd_platinum.lan_server", level="ERROR"):
            server = self.start(service(backend), wire_journal=broken)
            peer = self.peer(server)
            peer.send(b"$pss03-04-128-$rls")
            peer.read_until(b"$act00-00-")
        self.assertEqual(len(calls), 1)
        self.assertEqual(server.positions.values[3], 128)

    def test_raw_snapshot_and_saved_json_preserve_opaque_records(self):
        raw = b"".join(b"12 " + value + b"\n\r" for value in PAYLOADS)
        loaded = load_inventory(raw)
        self.assertEqual([r.payload for r in loaded.records], PAYLOADS)
        path = self.root / "snapshot.json"
        path.write_text(json.dumps({"records": [{"raw_hex": r.raw.hex()} for r in loaded.records]}))
        self.assertEqual(load_inventory(path).title_raw, b"\x00\xffopaque-$")
        with self.assertRaises(ValueError):
            load_inventory(raw[:-1])
        with self.assertRaises(ValueError):
            load_inventory(raw.replace(b"$upd01-", b"$done"))

    def test_summary_loader_preserves_ids_without_inventing_opaque_title(self):
        summary = inventory().public_summary(include_names=True, include_mac=True)
        loaded = load_inventory({"inventory": summary})
        self.assertEqual(set(loaded.shades), {3, 4, 5})
        self.assertEqual(loaded.rooms[2].rf_identifier, "0x1A2B")
        self.assertIsNone(loaded.title_raw)
        summary["mac"] = "<redacted>"
        with self.assertRaises(ValueError):
            load_inventory({"inventory": summary})

    def test_fragmented_coalesced_requests_and_optional_endings(self):
        parser = _Commands()
        commands = []
        wire = b"$dat-$pss03-04-128-\r\n$rls$dmy"
        for byte in wire:
            commands.extend(parser.feed(bytes((byte,))))
        self.assertEqual(commands, [b"$dat", b"$pss03-04-128-", b"$rls", b"$dmy"])
        self.assertFalse(parser.pending)
        self.assertEqual(_Commands().feed(b"$pss03-04-255$rls"), [b"$pss03-04-255-", b"$rls"])
        for wire, room in ((b"$psr02-04-128-$rls", b"$psr02-04-128-"),
                           (b"$psr02-04-128-00-$rls", b"$psr02-04-128-00-")):
            parser, commands = _Commands(), []
            for byte in wire:
                commands.extend(parser.feed(bytes((byte,))))
            self.assertEqual(commands, [room, b"$rls"])
        wire = b"$sdt10-24-07-2026-$chksy2026-$stm12-31-37-$dat"
        expected = [b"$sdt10-24-07-2026-", b"$chksy2026-", b"$stm12-31-37-", b"$dat"]
        for split in range(len(wire) + 1):
            parser = _Commands()
            self.assertEqual(parser.feed(wire[:split]) + parser.feed(wire[split:]), expected)
        parser, commands = _Commands(), []
        for byte in b"$sdt10-24-7-2026-$stm00-00-00-":
            commands.extend(parser.feed(bytes((byte,))))
        self.assertEqual(commands, [b"$sdt10-24-7-2026-", b"$stm00-00-00-"])
        for wire in (b"$pss0x", b"$pss03/04-128-", b"$BdgBtl", b"\x00$rls", b"$datgarbage",
                     b"$psr02-04-128-01-", b"$psr02-04-128-0x-",
                     b"$sdt10/24-07-2026-", b"$chksz2026-", b"$stm12-3x-37-",
                     b"\r\n", b"$dmy\r\n\r\n", b"x" * 4097):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                _Commands().feed(wire)

    def test_real_readonly_client_receives_original_snapshot(self):
        server = self.start()
        snapshot = query_inventory(server.server_address[0], port=server.server_address[1], timeout=2)
        self.assertTrue(snapshot.update_complete)
        self.assertEqual(snapshot.title_raw, b"\x00\xffopaque-$")
        self.assertEqual(snapshot.shades[3].positions[4], 0)
        self.assertEqual(set(snapshot.shades), {3, 4, 5})

    def test_android_widths_and_room_tail_never_execute_a_partial_command(self):
        self.assertEqual(_Commands().feed(b"$pss3-4-7-$rsc3-"),
                         [b"$pss03-04-007-", b"$rsc03-"])
        for tail in (b"0-", b"00-"):
            wire = b"$psr2-4-128-" + tail
            for split in range(len(wire)):
                parser = _Commands()
                self.assertEqual(parser.feed(wire[:split]), [])
                self.assertEqual(parser.feed(wire[split:]), [b"$psr02-04-128-00-"])
        parser = _Commands()
        self.assertEqual(parser.feed(b"$psr02-04-128-"), [])
        self.assertEqual(parser.feed(b"0"), [])
        self.assertEqual(parser.feed(b"0"), [])
        self.assertEqual(parser.feed(b"-$dat"), [b"$psr02-04-128-00-", b"$dat"])

    def test_default_idle_timeout_covers_android_keepalive_interval(self):
        self.assertGreaterEqual(self.start().idle_timeout, 240)

    def test_metadata_and_clock_uncertain_commit_reports_backend_error(self):
        server = self.start()
        peer = self.peer(server)
        with patch.object(server.service, "mutate_inventory", side_effect=RuntimeError("uncertain commit")):
            for command in (b"$ar01-4-Room", b"$stm12-00-00-"):
                peer.send(command)
                self.assertEqual([r.payload for r in peer.read_until(ERROR_BACKEND)], [ERROR_BACKEND])
        peer.send(b"$dat")
        peer.read_until(b"$upd01-")

    def test_sync_parser_requires_exact_target_and_terminal_hyphen(self):
        wire = b"$rsc03-$dat$dmy"
        for split in range(len(wire) + 1):
            parser = _Commands()
            self.assertEqual(parser.feed(wire[:split]) + parser.feed(wire[split:]),
                             [b"$rsc03-", b"$dat", b"$dmy"])
        parser = _Commands()
        self.assertEqual(parser.feed(b"$rsc03"), [])
        self.assertEqual(parser.feed(b"-"), [b"$rsc03-"])
        self.assertEqual(_Commands().feed(b"$rsc3-"), [b"$rsc03-"])
        for malformed in (b"$rsc003-", b"$rscxx-", b"$rsc03$dat", b"$rsc03--"):
            with self.subTest(wire=malformed), self.assertRaises(ValueError):
                _Commands().feed(malformed)

    def test_sync_is_immediate_opt_in_and_does_not_persist_position(self):
        calls, position_calls = [], []
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def backend(command):
            calls.append(command)
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test backend timed out")
            return {"status": "submitted"}
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=key == 3)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=backend,
            position_backend=lambda command: position_calls.append(command) or {"status": "submitted"})
        server = self.start(bridge, state_path=self.root / "sync-state.json")
        original_positions = dict(server.positions.values)
        peer = self.peer(server)
        peer.send(b"$pss03-04-128")
        peer.read_until(b"$done")
        peer.send(b"$rsc")
        peer.send(b"03-")
        started = peer.read_until(b"$cp03-01-000-")
        self.assertEqual([record.payload for record in started], [b"$act01-00-", b"$cp03-01-000-"])
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], SyncCommand)
        self.assertEqual(calls[0].shade, 3)
        self.assertEqual(server.positions.values, original_positions)
        self.assertFalse((self.root / "sync-state.json").exists())
        # Keepalives are handled before RF finishes. All other input received
        # during Sync is rejected immediately, with no delayed retry/staging.
        peer.socket.settimeout(.5)
        peer.send(b"$dmy$stm01-02-03-$rls$rsc03-$pss03-04-255-")
        self.assertEqual([record.payload for record in peer.read_until(b"$ack")], [b"$ack"])
        for _ in range(4):
            self.assertEqual([record.payload for record in peer.read_until(ERROR_BUSY)], [ERROR_BUSY])
        self.assertFalse(release.is_set())
        self.assertEqual(len(calls), 1)
        self.assertEqual(server.positions.virtual_clock, {})
        release.set()
        ended = peer.read_until(b"$act00-00-")
        self.assertEqual([record.payload for record in ended], [b"$act02-02-", b"$act00-00-"])
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)  # Sync consumed the earlier staged position.
        self.assertEqual(position_calls, [])
        self.assertEqual(server.positions.values, original_positions)
        self.assertIn(b"$cp03-04-000-", server.positions.snapshot())

    def test_idle_keepalive_acknowledges_fragmented_and_coalesced_requests(self):
        server = self.start()
        peer = self.peer(server)
        peer.send(b"$dm")
        peer.send(b"y$dmy$dat")
        records = peer.read_until(b"$upd01-")
        self.assertEqual([record.payload for record in records[:2]], [b"$ack", b"$ack"])
        self.assertEqual([record.payload for record in records[2:]], PAYLOADS[1:])
        self.assertTrue(all(record.connection_id == peer.connection_id for record in records))

    def jog_service(self, backend, *, positions=False):
        original = service().config
        config = replace(original, shades={key: replace(target,
            position_enabled=positions and key == 3, sync_enabled=False, jog_enabled=key == 3)
            for key, target in original.shades.items()})
        return BridgeService(config, DryRunBackend(), jog_backend=backend,
                             position_backend=backend if positions else None)

    def test_jog_stages_without_rf_then_releases_once_without_position_state(self):
        calls = []
        server = self.start(self.jog_service(lambda command: calls.append(command) or {"status": "submitted"}),
                            state_path=self.root / "jog-state.json")
        before = server.positions.snapshot()
        peer = self.peer(server)
        peer.send(b"$pss03-12-")
        peer.send(b"000")  # Original app may omit the final hyphen.
        self.assertEqual([r.payload for r in peer.read_until(b"$done")],
                         [b"$act01-00-", b"$cp03-12-001-", b"$done"])
        self.assertEqual(calls, [])
        self.assertEqual(server.positions.snapshot(), before)
        peer.send(b"$rls")
        self.assertEqual([r.payload for r in peer.read_until(b"$act00-00-")],
                         [b"$act02-02-", b"$act00-00-"])
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], JogCommand)
        self.assertFalse(calls[0].target.position_enabled or calls[0].target.sync_enabled)
        self.assertEqual(server.positions.snapshot(), before)
        self.assertFalse((self.root / "jog-state.json").exists())
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 1)

    def test_jog_rejects_mixed_duplicate_room_and_nonzero_value_stages(self):
        calls = []
        server = self.start(self.jog_service(lambda command: calls.append(command) or {"status": "submitted"},
                                             positions=True))
        peer = self.peer(server)
        for first, second in ((b"$pss03-04-128-", b"$pss03-12-000-"),
                              (b"$pss03-12-000-", b"$pss03-04-128-"),
                              (b"$pss03-12-000-", b"$pss03-12-000-"),
                              (b"$pss03-12-000-", b"$psr02-04-128-00-")):
            with self.subTest(first=first, second=second):
                peer.send(first)
                peer.read_until(b"$done")
                peer.send(second + b"$rls")
                peer.read_until(ERROR_STAGE)
                peer.read_until(ERROR_STAGE)
        for invalid in (b"$pss03-12-001-", b"$pss03-12-255-", b"$psr02-12-000-00-",
                        b"$pss04-12-000-", b"$pss99-12-000-"):
            peer.send(invalid + b"$rls")
            peer.read_until(ERROR_TARGET)
            peer.read_until(ERROR_STAGE)
        self.assertEqual(calls, [])

    def test_jog_failure_consumes_stage_without_action_end_position_write_or_retry(self):
        calls = []
        def failed(command):
            calls.append(command)
            raise RuntimeError("fictional uncertain RF result")
        server = self.start(self.jog_service(failed))
        before = server.positions.snapshot()
        peer = self.peer(server)
        peer.send(b"$pss03-12-000-")
        peer.read_until(b"$done")
        peer.send(b"$rls")
        self.assertEqual([r.payload for r in peer.read_until(ERROR_BACKEND)], [ERROR_BACKEND])
        peer.send(b"$rls$dat")
        records = peer.read_until(b"$upd01-")
        self.assertEqual(records[0].payload, ERROR_STAGE)
        self.assertNotIn(b"$act00-00-", [r.payload for r in records])
        self.assertEqual(server.positions.snapshot(), before)
        self.assertEqual(len(calls), 1)

    def test_jog_stage_is_discarded_on_disconnect_or_binding_change(self):
        calls = []
        bridge = self.jog_service(lambda command: calls.append(command) or {"status": "submitted"})
        server = self.start(bridge)
        peer = self.peer(server)
        peer.send(b"$pss03-12-000-")
        peer.read_until(b"$done")
        peer.close()
        other = self.peer(server)
        other.send(b"$rls")
        other.read_until(ERROR_STAGE)
        other.send(b"$pss03-12-000-")
        other.read_until(b"$done")
        bridge.mutate_inventory(lambda store: store.update_shade(3, group=4))
        other.send(b"$rls")
        other.read_until(ERROR_TARGET)
        self.assertEqual(calls, [])

    def test_partial_command_retains_busy_provenance_after_sync_ends(self):
        for first, tail, expected, coalesced in ((b"$rsc", b"03-", ERROR_BUSY, False),
                                                 (b"$dm", b"y", b"$ack", False),
                                                 (b"$rsc", b"03-", ERROR_BUSY, True)):
            with self.subTest(fragment=first, coalesced=coalesced):
                calls = []
                entered, release = threading.Event(), threading.Event()
                self.addCleanup(release.set)
                def backend(command):
                    calls.append(command)
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("fake finite backend timeout")
                    return {"status": "submitted"}
                original = service().config
                config = replace(original, shades={key: replace(target, sync_enabled=True)
                                                   for key, target in original.shades.items()})
                server = self.start(BridgeService(config, DryRunBackend(), sync_backend=backend))
                peer = self.peer(server)
                peer.send(b"$rsc03-" + (first if coalesced else b""))
                peer.read_until(b"$cp03-01-000-")
                self.assertTrue(entered.wait(1))
                # The first acknowledgement proves the server parsed this
                # chunk, including the unfinished next command, while busy.
                if not coalesced:
                    peer.send(b"$dmy" + first)
                    peer.read_until(b"$ack")
                release.set()
                peer.read_until(b"$act00-00-")
                peer.send(tail + b"$dat")
                records = peer.read_until(b"$upd01-")
                self.assertEqual(records[0].payload, expected)
                self.assertEqual([record.payload for record in records[1:]], PAYLOADS[1:])
                self.assertEqual(len(calls), 1)

    def test_sync_disconnect_keeps_one_action_owned_until_cleanup(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []
        def backend(command):
            calls.append(command)
            entered.set()
            if not release.wait(3):
                raise RuntimeError("fake finite backend timeout")
            finished.set()
            return {"status": "submitted"}
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=key == 3)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=backend)
        server = self.start(bridge)
        peer = self.peer(server)
        peer.send(b"$rsc03-")
        peer.read_until(b"$cp03-01-000-")
        self.assertTrue(entered.wait(1))
        with server.clients_lock:
            handler = next(client for client in server.clients if client.connection_id == peer.connection_id)
        worker = handler.sync_worker
        self.assertFalse(worker.daemon)
        peer.close()
        self.assertTrue(handler.disconnected.wait(1))
        self.assertTrue(worker.is_alive())
        other = self.peer(server)
        other.send(b"$rsc03-")
        self.assertEqual([record.payload for record in other.read_until(ERROR_BUSY)], [ERROR_BUSY])
        other.send(b"$dmy")
        self.assertEqual([record.payload for record in other.read_until(b"$ack")], [b"$ack"])
        self.assertEqual(len(calls), 1)
        release.set()
        other.read_until(b"$act00-00-")
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(finished.is_set())
        self.assertFalse(server.release_lock.locked())
        self.assertFalse(bridge._send_lock.locked())

    def test_sync_shutdown_waits_for_worker_and_does_not_launch_queued_action(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []
        def backend(command):
            calls.append(command)
            entered.set()
            if not release.wait(3):
                raise RuntimeError("fake finite backend timeout")
            return {"status": "submitted"}
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=True)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=backend)
        server = self.start(bridge)
        peer = self.peer(server)
        peer.send(b"$rsc03-$rsc03-$dmy")
        peer.read_until(b"$ack")
        self.assertTrue(entered.wait(1))
        self.assertEqual(len(calls), 1)
        def stop():
            server.shutdown()
            server.server_close()
            closed.set()
        stopper = threading.Thread(target=stop)
        stopper.start()
        self.assertFalse(closed.wait(.05))
        self.assertTrue(bridge._send_lock.locked())
        release.set()
        self.assertTrue(closed.wait(2))
        stopper.join(2)
        self.assertEqual(len(calls), 1)
        self.assertFalse(bridge._send_lock.locked())
        self.assertFalse(server.release_lock.locked())

    def test_sync_worker_start_failure_releases_ownership_without_rf(self):
        calls = []
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=True)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=lambda command:
                               calls.append(command) or {"status": "submitted"})
        server = self.start(bridge)
        peer = self.peer(server)
        original_start = threading.Thread.start
        def start(thread):
            if thread.name == "platinum-lan-sync":
                raise RuntimeError("fake thread creation failure")
            return original_start(thread)
        with patch("hd_platinum.lan_server.threading.Thread.start", start):
            peer.send(b"$rsc03-")
            self.assertEqual([record.payload for record in peer.read_until(ERROR_BACKEND)], [ERROR_BACKEND])
        self.assertEqual(calls, [])
        self.assertFalse(server.release_lock.locked())
        self.assertFalse(bridge._send_lock.locked())
        peer.send(b"$dmy")
        self.assertEqual([record.payload for record in peer.read_until(b"$ack")], [b"$ack"])

    def test_sync_scope_missing_backend_and_jog_remain_rejected(self):
        calls = []
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=key == 3)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), position_backend=DryRunBackend(),
            sync_backend=lambda command: calls.append(command) or {"status": "submitted"})
        server = self.start(bridge)
        peer = self.peer(server)
        for command in (b"$rsc04-", b"$rsc05-", b"$rsc99-", b"$pss03-12-000"):
            peer.send(command)
            records = peer.read_until(ERROR_TARGET)
            self.assertEqual([record.payload for record in records], [ERROR_TARGET])
        self.assertEqual(calls, [])
        missing = BridgeService(config, DryRunBackend())
        peer = self.peer(self.start(missing))
        peer.send(b"$rsc03-")
        self.assertEqual([record.payload for record in peer.read_until(ERROR_TARGET)], [ERROR_TARGET])

    def test_sync_failure_reports_backend_error_without_done_or_action_end(self):
        calls = []
        def failed(command):
            calls.append(command)
            raise RuntimeError("fictional private failure")
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=True)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=failed)
        server = self.start(bridge)
        before = dict(server.positions.values)
        peer = self.peer(server)
        peer.send(b"$rsc03-")
        records = peer.read_until(ERROR_BACKEND)
        self.assertEqual([record.payload for record in records],
                         [b"$act01-00-", b"$cp03-01-000-", ERROR_BACKEND])
        self.assertEqual(len(calls), 1)
        self.assertEqual(server.positions.values, before)

    def test_stage_order_release_once_and_persist_only_after_submission(self):
        calls = []
        bridge = service(lambda command: calls.append(command) or {"status": "submitted"})
        path = self.root / "positions.json"
        server = self.start(bridge, state_path=path)
        peer = self.peer(server)
        peer.send(b"$ps")
        peer.send(b"s03-04-128-")
        records = peer.read_until(b"$done")
        self.assertEqual([r.payload for r in records], [b"$act01-00-", b"$cp03-04-128-", b"$done"])
        self.assertFalse(calls)
        self.assertFalse(path.exists())
        peer.send(b"$dat")
        self.assertIn(b"$cp03-04-000-", [r.payload for r in peer.read_until(b"$upd01-")])
        peer.send(b"$rls")
        self.assertEqual([r.payload for r in peer.read_until(b"$act00-00-")],
                         [b"$cp03-04-128-", b"$act02-02-", b"$act00-00-"])
        self.assertEqual(len(calls), 1)
        state = json.loads(path.read_text())
        self.assertFalse(state["position_confirmed"])
        self.assertEqual(state["requested_positions"], {"3": 128})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 1)
        server.shutdown()
        server.server_close()
        restarted = make_lan_server(bridge, inventory(), port=0, state_path=path)
        try:
            self.assertIn(b"$cp03-04-128-", restarted.positions.snapshot())
        finally:
            restarted.server_close()

    def test_existing_position_transaction_client_completes(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}))
        with PositionTransaction(server.server_address[0], port=server.server_address[1],
                                 inventory=inventory(), shade_id=3, position=255, timeout=2) as transaction:
            transaction.stage()
            self.assertFalse(calls)
            receipt = transaction.trigger()
        self.assertTrue(receipt["action_end_observed"])
        self.assertEqual(len(calls), 1)

    def test_disabled_unconfigured_and_unsupported_requests_never_reach_rf(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}))
        for command in (b"$pss04-04-128-", b"$pss05-04-128-", b"$pss99-04-128-",
                        b"$pss03-18-128-", b"$pss03-04-999-", b"$psr02-04-128-",
                        b"$psr99-04-128-", b"$psr02-18-128-", b"$psr02-04-999-"):
            peer = self.peer(server)
            peer.send(command + b"$rls")
            peer.read_until(ERROR_TARGET)
            peer.read_until(ERROR_STAGE)
            peer.close()
        for command in (b"$BdgBtl", b"$reset", b"$ar02-Example-"):
            peer = self.peer(server)
            peer.send(command)
            peer.read_until(ERROR_UNSUPPORTED)
        self.assertFalse(calls)

    def test_app_startup_clock_commands_acknowledge_persist_and_do_not_dispatch_rf(self):
        calls = []
        state = self.root / "positions.json"
        bridge = service(lambda command: calls.append(command) or {"status": "submitted"})
        server = self.start(bridge, state_path=state)
        peer = self.peer(server)
        peer.send(b"$sdt10-24-07-2026-$chksy2026-$stm12-31-37-$dat")
        for expected in (b"$done", b"$chksy01-", b"$done"):
            self.assertEqual([record.payload for record in peer.read_until(expected)], [expected])
        snapshot = peer.read_until(b"$upd01-")
        self.assertIn(b"$cp03-04-000-", [record.payload for record in snapshot])
        self.assertFalse(calls)
        saved = json.loads(state.read_text())
        self.assertEqual(saved["requested_positions"], {})
        self.assertEqual(saved["virtual_clock"], {"date": "2026-10-24", "weekday": 7,
                                                  "time": "12:31:37", "checked_year": 2026})
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        server.shutdown()
        server.server_close()
        restarted = make_lan_server(bridge, inventory(), port=0, state_path=state)
        try:
            self.assertEqual(restarted.positions.virtual_clock, saved["virtual_clock"])
        finally:
            restarted.server_close()

    def test_captured_same_year_reply_does_not_set_the_virtual_date(self):
        server = self.start(state_path=self.root / "positions.json")
        peer = self.peer(server)
        peer.send(b"$chksy2026-")
        # Exact observed same-year reply; no other year/solar mapping is asserted.
        self.assertEqual(CHECK_YEAR_REPLY, b"$chksy01-")
        peer.read_until(CHECK_YEAR_REPLY)
        self.assertEqual(server.positions.virtual_clock, {"checked_year": 2026})
        self.assertFalse(server.positions.values)

    def test_invalid_clock_values_are_rejected_without_state_or_rf(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}),
                            state_path=self.root / "positions.json")
        peer = self.peer(server)
        for command in (b"$sdt02-29-07-2026-", b"$sdt13-01-01-2026-", b"$sdt10-24-08-2026-",
                        b"$sdt10-24-00-2026-", b"$stm24-00-00-", b"$stm12-60-00-",
                        b"$stm12-00-60-", b"$chksy0000-"):
            peer.send(command)
            peer.read_until(ERROR_CLOCK)
        self.assertEqual(server.positions.virtual_clock, {})
        self.assertFalse((self.root / "positions.json").exists())
        self.assertFalse(calls)
        peer.send(b"$sdt02-29-03-2028-$stm23-59-59-")
        peer.read_until(b"$done")
        peer.read_until(b"$done")
        self.assertEqual(server.positions.virtual_clock["date"], "2028-02-29")

    def test_staging_is_per_connection_and_discarded_on_disconnect(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}))
        first, second = self.peer(server), self.peer(server)
        first.send(b"$pss03-04-128-")
        first.read_until(b"$done")
        second.send(b"$rls")
        second.read_until(ERROR_STAGE)
        first.close()
        third = self.peer(server)
        third.send(b"$rls")
        third.read_until(ERROR_STAGE)
        self.assertFalse(calls)

    def test_invalid_stage_discards_prior_batch(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}))
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$pss04-04-128-$rls")
        peer.read_until(b"$done")
        peer.read_until(ERROR_TARGET)
        peer.read_until(ERROR_STAGE)
        self.assertFalse(calls)

    def test_sync_room_action_precedes_backend_cleanup_and_end_waits(self):
        release, submitted = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        class ProgressBackend:
            def __call__(self, command):
                raise AssertionError("Sync must use progress method")

            def submit(self, command, *, on_transmit_submitted):
                on_transmit_submitted()
                submitted.set()
                if not release.wait(2):
                    raise RuntimeError("test backend timed out")
                return {"status": "submitted"}
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=key == 3)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=ProgressBackend())
        server = self.start(bridge)
        peer = self.peer(server)
        peer.send(b"$rsc03-")
        records = peer.read_until(b"$act02-02-")
        self.assertEqual([record.payload for record in records],
                         [b"$act01-00-", b"$cp03-01-000-", b"$act02-02-"])
        self.assertTrue(submitted.wait(1))
        self.assertTrue(bridge._send_lock.locked())
        self.assertTrue(server.release_lock.locked())
        release.set()
        self.assertEqual([record.payload for record in peer.read_until(b"$act00-00-")], [b"$act00-00-"])

    def test_sync_receive_failure_after_room_action_has_no_end_or_retry(self):
        calls = []
        class FailedAfterSubmission:
            def __call__(self, command):
                raise AssertionError("Sync must use progress method")

            def submit(self, command, *, on_transmit_submitted):
                calls.append(command)
                on_transmit_submitted()
                raise RuntimeError("fake receive failure after finite TX")
        original = service().config
        config = replace(original, shades={key: replace(target, sync_enabled=key == 3)
                                           for key, target in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), sync_backend=FailedAfterSubmission())
        peer = self.peer(self.start(bridge))
        peer.send(b"$rsc03-")
        records = peer.read_until(ERROR_BACKEND)
        self.assertEqual([record.payload for record in records],
                         [b"$act01-00-", b"$cp03-01-000-", b"$act02-02-", ERROR_BACKEND])
        peer.send(b"$dat")
        records = peer.read_until(b"$upd01-")
        self.assertNotIn(b"$act00-00-", [record.payload for record in records])
        self.assertEqual(len(calls), 1)
        self.assertFalse(bridge._send_lock.locked())

    def test_multiple_staged_targets_last_value_wins_and_limit_is_enforced(self):
        calls = []
        original = service().config
        config = replace(original, shades={key: replace(value, position_enabled=True)
                                            for key, value in original.shades.items()})
        bridge = BridgeService(config, DryRunBackend(), position_backend=lambda command:
                               calls.append(command) or {"status": "submitted"})
        server = self.start(bridge)
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$pss03-04-064-$pss04-04-255-$rls")
        peer.read_until(b"$act00-00-")
        self.assertEqual([(c.shade, c.position) for c in calls], [(3, 64), (4, 255)])
        server.shutdown()
        server.server_close()
        limited = self.start(bridge, max_staged=1)
        peer = self.peer(limited)
        peer.send(b"$pss03-04-128-$pss04-04-255-$rls")
        peer.read_until(ERROR_LIMIT)
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 2)

    def test_room_fanout_and_batch_serialization_preserve_requested_state(self):
        calls, contention = [], []
        old = service().config
        shades = {key: replace(value, position_enabled=True) for key, value in old.shades.items()}
        shades[5] = ShadeConfig("Third fictional shade", 2, b"\x1a\x2b", 4, position_enabled=True)
        bridge = BridgeService(replace(old, shades=shades), DryRunBackend(), position_backend=lambda command:
                               calls.append(command) or {"status": "submitted", "sequence": len(calls)})
        # A competing HTTP-style call cannot enter even between batch receipts.
        def competing_request(command, receipt):
            try:
                bridge.dispatch_position({"shade": 3, "position": 255})
            except BridgeError as error:
                contention.append(error.code)
        unsubscribe = bridge.add_position_listener(competing_request)
        self.addCleanup(unsubscribe)
        state = self.root / "positions.json"
        server = self.start(bridge, state_path=state)
        peer = self.peer(server)
        peer.send(b"$psr02-04-128-00-")
        self.assertEqual([r.payload for r in peer.read_until(b"$done")],
                         [b"$act01-00-", b"$cp03-04-128-", b"$cp04-04-128-", b"$cp05-04-128-", b"$done"])
        result = [r.payload for r in peer.read_until(b"$act00-00-")]
        self.assertEqual(result, [b"$cp03-04-128-", b"$cp04-04-128-", b"$cp05-04-128-",
                                  b"$act02-02-", b"$act00-00-"])
        self.assertEqual([(c.shade, c.position) for c in calls], [(3, 128), (4, 128), (5, 128)])
        self.assertEqual(contention, ["busy"] * 3)
        self.assertEqual(json.loads(state.read_text())["requested_positions"], {"3": 128, "4": 128, "5": 128})
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 3)

    def test_mixed_scope_room_clears_entire_staged_batch_without_rf(self):
        calls = []
        server = self.start(service(lambda command: calls.append(command) or {"status": "submitted"}))
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$psr02-04-255-00-$rls")
        peer.read_until(b"$done")
        peer.read_until(ERROR_TARGET)
        peer.read_until(ERROR_STAGE)
        self.assertFalse(calls)

    def test_android_room_immediate_clears_prior_stage_and_later_release_is_empty(self):
        calls = []
        server = self.start(setup_service(lambda command: calls.append(command) or {"status": "submitted"}),
                            inventory_source=setup_inventory())
        peer = self.peer(server)
        peer.send(b"$pss0-4-255-$psr0-4-128-")
        peer.read_until(b"$done")
        self.assertEqual(calls, [])
        peer.send(b"0")
        self.assertEqual(calls, [])
        peer.send(b"-")
        peer.read_until(b"$act00-00-")
        self.assertEqual([(c.shade, c.position) for c in calls], [(0, 128)])
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 1)

    def test_release_retains_room_for_completion_after_concurrent_target_removal(self):
        bridge = setup_service(lambda command: {"status": "submitted"})
        server = self.start(bridge, inventory_source=setup_inventory())
        dispatch = bridge.dispatch_positions
        def deleting_dispatch(values):
            result = dispatch(values)
            bridge.mutate_inventory(lambda store: store.delete_shade(0))
            return result
        peer = self.peer(server)
        with patch.object(bridge, "dispatch_positions", side_effect=deleting_dispatch):
            peer.send(b"$pss0-4-128-$rls")
            records = peer.read_until(b"$act00-00-")
        self.assertIn(b"$act02-00-", [r.payload for r in records])
        self.assertNotIn(0, bridge.config.shades)

    def test_later_batch_failure_retains_prior_success_without_retry(self):
        calls = []
        old = service().config
        config = replace(old, shades={key: replace(value, position_enabled=True)
                                      for key, value in old.shades.items()})
        def backend(command):
            calls.append(command)
            if command.shade == 4:
                raise RuntimeError("fictional second-target failure")
            return {"status": "submitted"}
        server = self.start(BridgeService(config, DryRunBackend(), position_backend=backend),
                            state_path=self.root / "positions.json")
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$pss04-04-255-$rls")
        peer.read_until(ERROR_BACKEND)
        self.assertEqual([(c.shade, c.position) for c in calls], [(3, 128), (4, 255)])
        self.assertEqual(json.loads((self.root / "positions.json").read_text())["requested_positions"], {"3": 128})
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 2)

    def test_backend_failure_does_not_persist_and_release_is_consumed(self):
        calls = []
        def backend(command):
            calls.append(command)
            raise RuntimeError("synthetic hardware failure")
        path = self.root / "positions.json"
        server = self.start(service(backend), state_path=path)
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$rls")
        peer.read_until(b"$done")
        peer.read_until(ERROR_BACKEND)
        self.assertFalse(path.exists())
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 1)

    def test_simulation_does_not_persist_position(self):
        path = self.root / "positions.json"
        server = self.start(state_path=path)
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$rls")
        peer.read_until(b"$act00-00-")
        self.assertFalse(path.exists())
        self.assertIn(b"$cp03-04-000-", server.positions.snapshot())

    def test_http_service_dispatch_updates_lan_and_replayed_request_does_not_duplicate(self):
        calls = []
        bridge = service(lambda command: calls.append(command) or {"status": "submitted"})
        server = self.start(bridge, state_path=self.root / "positions.json")
        peer = self.peer(server)
        request = {"shade": 3, "position": 128, "request_id": "shared-http-request"}
        result = bridge.dispatch_position(request)
        self.assertFalse(result["position_confirmed"])
        peer.read_until(b"$cp03-04-128-")
        bridge.dispatch_position(request)
        self.assertEqual(len(calls), 1)
        self.assertIn(b"$cp03-04-128-", server.positions.snapshot())

    def test_busy_shared_service_does_not_queue_or_retry(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def backend(command):
            calls.append(command)
            entered.set()
            release.wait(3)
            return {"status": "submitted"}
        bridge = service(backend)
        server = self.start(bridge)
        worker = threading.Thread(target=lambda: bridge.dispatch_position({"shade": 3, "position": 0}))
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            peer = self.peer(server)
            peer.send(b"$pss03-04-128-$rls")
            peer.read_until(ERROR_BUSY)
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            worker.join(2)
        peer.send(b"$rls")
        peer.read_until(ERROR_STAGE)
        self.assertEqual(len(calls), 1)

    def test_rate_and_partial_command_deadline(self):
        server = self.start(commands_per_minute=2)
        peer = self.peer(server)
        peer.send(b"$dmy$dmy$dat")
        peer.read_until(ERROR_LIMIT)
        server = self.start(command_timeout=.05)
        peer = self.peer(server)
        peer.send(b"$pss03-")
        peer.read_until(ERROR_LIMIT)

    def test_client_allowlist_connection_limit_and_bind_validation(self):
        for options in ({"host": "0.0.0.0"}, {"allowed_clients": ["0.0.0.0/0"]},
                        {"allowed_clients": "127.0.0.1"}, {"max_connections": 0},
                        {"max_connections": 10}, {"max_connections": 64}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                make_lan_server(service(), inventory(), port=0, **options)
        blocked = self.start(allowed_clients=["192.168.50.0/24"])
        with socket.create_connection(blocked.server_address, timeout=1) as sock:
            self.assertEqual(sock.recv(1024), b"")
        limited = self.start(max_connections=1)
        self.peer(limited)
        with socket.create_connection(limited.server_address, timeout=1) as sock:
            self.assertEqual(sock.recv(1024), b"")

    def test_single_digit_connection_ids_are_unique_and_reused_after_disconnect(self):
        server = self.start(max_connections=9)
        peers = [self.peer(server) for _ in range(9)]
        self.assertEqual({peer.connection_id for peer in peers}, set(range(1, 10)))
        with socket.create_connection(server.server_address, timeout=1) as sock:
            self.assertEqual(sock.recv(1024), b"")

        # Keep eight clients active while repeatedly replacing the ninth. This
        # crosses the old monotonic counter's first two-digit ID boundary.
        replaced = peers.pop(3)
        released_id = replaced.connection_id
        for _ in range(12):
            replaced.close()
            self.assertTrue(server.slots.acquire(timeout=1))
            server.slots.release()
            replaced = self.peer(server)
            self.assertEqual(replaced.connection_id, released_id)
        for peer in peers + [replaced]:
            peer.send(b"$dat")
            records = peer.read_until(b"$upd01-")
            prefix = f"{peer.connection_id} ".encode()
            self.assertTrue(all(record.raw.startswith(prefix) for record in records))

    def test_target_mask_or_invalid_inventory_group_cannot_select_another_shade(self):
        original = service().config
        altered = replace(original, shades={3: replace(original.shades[3], mask=4)})
        bridge = BridgeService(altered, DryRunBackend(), position_backend=DryRunBackend())
        with self.assertRaisesRegex(ValueError, "target does not match"):
            make_lan_server(bridge, inventory(), port=0)
        for group in (0, 9):
            source = inventory()
            source.shades[3].group_field = group
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "target does not match"):
                make_lan_server(service(), source, port=0)

    def test_shutdown_waits_for_finite_backend_and_persists_completion(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        def backend(command):
            entered.set()
            release.wait(3)
            return {"status": "submitted"}
        path = self.root / "positions.json"
        server = self.start(service(backend), state_path=path)
        peer = self.peer(server)
        peer.send(b"$pss03-04-128-$rls")
        self.assertTrue(entered.wait(1))
        def stop():
            server.shutdown()
            server.server_close()
            closed.set()
        stopper = threading.Thread(target=stop)
        stopper.start()
        self.assertFalse(closed.wait(.05))
        release.set()
        self.assertTrue(closed.wait(2))
        stopper.join(2)
        self.assertEqual(json.loads(path.read_text())["requested_positions"], {"3": 128})


if __name__ == "__main__":
    unittest.main()
