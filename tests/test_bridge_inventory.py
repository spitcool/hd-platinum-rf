# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Inventory changes cannot race or inherit physical RF authorizations."""

from pathlib import Path
from dataclasses import replace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from hd_platinum.bridge import BridgeConfig, BridgeError, BridgeService, ShadeConfig
from hd_platinum.inventory_store import InventoryStore
from hd_platinum.lan import BridgeRecord, parse_records


def inventory():
    return parse_records(BridgeRecord.from_raw(payload) for payload in (
        b"$upd00-", b"$reset", b"$cr00-01-0x4142-Example room",
        b"$cs00-00-01-Example shade", b"$cs01-00-02-Second shade", b"$upd01-"))


def config():
    return BridgeConfig(b"CD", {}, "fictional-inventory-token-only", {
        0: ShadeConfig("Example shade", 0, b"AB", 1, position_enabled=True, sync_enabled=True),
        1: ShadeConfig("Second shade", 0, b"AB", 2, position_enabled=True, sync_enabled=True)})


class BridgeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(return_value={"status": "sent"})
        self.service = BridgeService(config(), self.backend,
                                     position_backend=self.backend, sync_backend=self.backend)
        self.store = InventoryStore(inventory())
        self.service.attach_inventory(self.store)

    def test_rename_updates_listing_without_changing_grants_and_new_shades_have_none(self):
        self.service.mutate_inventory(lambda store: store.rename_shade(0, "Renamed"))
        self.assertEqual(self.service.config.shades[0].name, "Renamed")
        self.assertTrue(self.service.config.shades[0].position_enabled)
        self.assertTrue(self.service.config.shades[0].sync_enabled)
        added = self.service.mutate_inventory(lambda store: store.create_shade(0, "New shade"))
        self.assertNotIn(added.id, self.service.config.shades)
        self.backend.assert_not_called()

    def test_delete_recreate_and_restart_do_not_inherit_same_numeric_id_grants(self):
        self.service.detach_inventory(self.store)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = InventoryStore(inventory(), path)
            self.service.attach_inventory(store)
            self.service.mutate_inventory(lambda db: db.delete_shade(0))
            recreated = self.service.mutate_inventory(lambda db: db.create_shade(0, "Replacement"))
            self.assertEqual(recreated.id, 0)
            self.assertFalse(self.service.config.shades[0].position_enabled)
            self.assertFalse(self.service.config.shades[0].sync_enabled)
            restarted = BridgeService(config(), self.backend, sync_backend=self.backend)
            restarted.attach_inventory(InventoryStore(inventory(), path))
            with self.assertRaises(BridgeError) as error:
                restarted.dispatch_sync({"shade": 0})
            self.assertEqual(error.exception.code, "sync_disabled")
        self.backend.assert_not_called()

    def test_empty_inventory_remains_usable_for_setup(self):
        self.service.mutate_inventory(lambda store: store.delete_room(0, cascade=True))
        self.assertEqual(dict(self.service.config.shades), {})
        new_room = self.service.mutate_inventory(lambda store: store.create_room(1, "New room", b"EF"))
        self.assertEqual(new_room.id, 0)
        self.backend.assert_not_called()

    def test_exact_new_target_sync_permission_does_not_enable_position(self):
        added = self.service.mutate_inventory(lambda store: store.create_shade(0, "Pairing target"))
        target = ShadeConfig(added.name, 0, b"AB", 4, position_enabled=True, sync_enabled=True)
        self.service.detach_inventory(self.store)
        service = BridgeService(replace(config(), shades={**config().shades, added.id: target}),
                                self.backend, position_backend=self.backend, sync_backend=self.backend)
        service.attach_inventory(self.store)
        self.assertFalse(service.config.shades[added.id].sync_enabled)
        service.mutate_inventory(lambda store: store.authorize_target(added.id,
            expected_revision=store.revision, room_id=0, room_rf_id=b"AB", mask=4))
        result = service.dispatch_sync({"shade": added.id})
        self.assertEqual(result["status"], "sent")
        with self.assertRaises(BridgeError) as error:
            service.dispatch_position({"shade": added.id, "position": 128})
        self.assertEqual(error.exception.code, "validation_required")
        self.backend.assert_called_once()
        service.mutate_inventory(lambda store: store.update_room(0, product_type=2))
        self.assertFalse(service.config.shades[added.id].sync_enabled)

    def test_position_and_sync_recheck_target_after_preparation(self):
        real_dispatch = self.service._dispatch
        for operation in ("position", "sync"):
            store = self.store
            def intervening_change(*args, **kwargs):
                self.service.mutate_inventory(lambda db: db.rename_shade(0, operation))
                return real_dispatch(*args, **kwargs)
            started = Mock()
            with self.subTest(operation=operation), patch.object(self.service, "_dispatch", intervening_change):
                with self.assertRaises(BridgeError) as error:
                    if operation == "position":
                        self.service.dispatch_position({"shade": 0, "position": 128})
                    else:
                        self.service.dispatch_sync({"shade": 0}, on_started=started)
                self.assertEqual(error.exception.code, "target_changed")
            self.assertIs(self.store, store)
            started.assert_not_called()
        self.backend.assert_not_called()

    def test_entire_batch_rechecked_before_first_transmission(self):
        real_prepare = self.service._prepare_position
        def intervening_change(value):
            result = real_prepare(value)
            if value["shade"] == 1:
                self.service.mutate_inventory(lambda store: store.delete_shade(1))
            return result
        with patch.object(self.service, "_prepare_position", intervening_change):
            with self.assertRaises(BridgeError) as error:
                self.service.dispatch_positions([{"shade": shade, "position": 128} for shade in (0, 1)])
        self.assertEqual(error.exception.code, "target_changed")
        self.backend.assert_not_called()

    def test_inventory_edit_cannot_interleave_with_transmission(self):
        entered, finish = threading.Event(), threading.Event()
        errors = []
        def backend(command):
            entered.set()
            if not finish.wait(3):
                raise RuntimeError("test release timed out")
            return {"status": "sent"}
        self.service.position_backend = backend
        def send():
            try:
                self.service.dispatch_position({"shade": 0, "position": 128})
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=send)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(BridgeError) as error:
                self.service.mutate_inventory(lambda store: store.delete_shade(0))
            self.assertEqual(error.exception.code, "busy")
            self.assertIn(0, self.store.inventory.shades)
        finally:
            finish.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_uncertain_persistence_disables_targets_until_store_reopened(self):
        with patch.object(self.store, "project_targets", side_effect=RuntimeError("uncertain commit")):
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                self.service.mutate_inventory(lambda store: store.rename_shade(0, "Renamed"))
        self.assertEqual(dict(self.service.config.shades), {})
        self.backend.assert_not_called()

    def test_uncertain_position_observer_preserves_receipt_but_blocks_next_rf(self):
        self.service.detach_inventory(self.store)
        with tempfile.TemporaryDirectory() as directory:
            store = InventoryStore(inventory(), Path(directory) / "state.json")
            self.service.attach_inventory(store)
            self.service.add_position_listener(lambda command, receipt: store.submitted(command.shade, command.position))
            request = {"shade": 0, "position": 128, "request_id": "already-sent"}
            with patch("hd_platinum.inventory_store.os.fsync", side_effect=[None, OSError("directory flush failed")]):
                with self.assertLogs("hd_platinum.bridge", level="ERROR"):
                    receipt = self.service.dispatch_position(request)
            self.assertEqual(receipt["status"], "sent")
            self.assertTrue(self.service.dispatch_position(request)["replayed"])
            with self.assertRaises(BridgeError) as error:
                self.service.dispatch_position({"shade": 0, "position": 255})
            self.assertEqual(error.exception.code, "inventory_unavailable")
            self.assertEqual(dict(self.service.config.shades), {})
            self.backend.assert_called_once()

    def test_invalid_edit_preserves_grants_and_store_replacement_requires_detach(self):
        with self.assertRaises(ValueError):
            self.service.mutate_inventory(lambda store: store.rename_shade(0, ""))
        self.assertTrue(self.service.config.shades[0].position_enabled)
        with self.assertRaisesRegex(ValueError, "attached"):
            self.service.attach_inventory(InventoryStore(inventory()))
        self.service.detach_inventory(self.store)
        self.service.attach_inventory(InventoryStore(inventory()))
        self.backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
