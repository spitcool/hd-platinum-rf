# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Typed inventory editing and private persistence, without sockets or radio."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from hd_platinum.bridge import ShadeConfig
from hd_platinum.inventory_store import InventoryStore, MAX_STATE_BYTES
from hd_platinum.lan import BridgeRecord, RECORD_DELIMITER, parse_records


PAYLOADS = [
    b"HunterDouglas Shade Controller", b"$firm02-fictional", b"$upd00-", b"$reset",
    b"$ct\x00\xffopaque-$title", b"$set006-", b"$other\x80opaque",
    b"$cr02-01-0x1A2B-Example room", b"$cr05-02-0x3C4D-Second room",
    b"$cs00-02-01-Example shade", b"$cp00-04-000-",
    b"$cs03-02-03-Another shade", b"$cp03-04-128-", b"$upd01-",
]


def inventory(extra=()):
    return parse_records(BridgeRecord.from_raw(b"12 " + payload)
                         for payload in PAYLOADS[:-1] + list(extra) + PAYLOADS[-1:])


def targets():
    return {0: ShadeConfig("Example shade", 2, b"\x1a\x2b", 1,
                           position_enabled=True, sync_enabled=True)}


class InventoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.initial = inventory()

    def test_opaque_records_prefixes_overlay_and_detached_views_survive_rename_and_restart(self):
        store = InventoryStore(self.initial, self.path)
        original_raw = [record.raw for record in self.initial.records]
        untouched = [record.raw for record in self.initial.records
                     if record.kind not in ("room", "shade")]
        store.submitted(0, 200)
        store.rename_shade(0, " Tést $ shade - ")
        store.rename_room(2, "Changed room")
        self.assertIn(b"$cp00-04-200-", store.snapshot())
        self.assertEqual(store.inventory.shades[0].positions[4], 0)
        self.assertTrue(store.project_targets(targets())[0].sync_enabled)
        self.assertEqual([record.raw for record in store.inventory.records
                          if record.kind not in ("room", "shade")], untouched)
        self.assertTrue(next(record.raw for record in store.inventory.records
                             if record.payload.startswith(b"$cs00-")).startswith(b"12 "))
        self.assertEqual([record.raw for record in self.initial.records], original_raw)
        exposed = store.inventory
        exposed.shades[0].name = "outside mutation"
        values = store.values
        values[0] = 1
        self.assertEqual(store.inventory.shades[0].name, " Tést $ shade - ")
        self.assertEqual(store.values[0], 200)
        restored = InventoryStore(self.initial, self.path)
        self.assertEqual(restored.snapshot(), store.snapshot())
        self.assertEqual(restored.revision, 3)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_schema_one_migrates_only_with_matching_original_inventory(self):
        fingerprint = hashlib.sha256(RECORD_DELIMITER.join(record.payload for record in self.initial.records)).hexdigest()
        document = {"schema_version": 1, "inventory_sha256": fingerprint,
                    "position_confirmed": False, "requested_positions": {"0": 128},
                    "virtual_clock": {"date": "2026-10-24", "weekday": 7, "time": "12:30:00"}}
        self.path.write_text(json.dumps(document))
        store = InventoryStore(self.initial, self.path)
        migrated = json.loads(self.path.read_text())
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(store.values, {0: 128})
        self.assertEqual(store.virtual_clock, document["virtual_clock"])
        self.assertIn(b"$cp00-04-128-", store.snapshot())
        self.assertEqual([record.raw.hex() for record in self.initial.records],
                         [record["raw_hex"] for record in migrated["records"]])
        document["inventory_sha256"] = "0" * 64
        self.path.write_text(json.dumps(document))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "does not match"):
            InventoryStore(self.initial, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_lowest_free_ids_and_room_local_slots_are_allocated_without_position_claims(self):
        store = InventoryStore(self.initial, self.path)
        room = store.create_room(1, "Added room", b"AB")
        self.assertEqual((room.id, room.product_type, room.rf_identifier), (0, 1, "0x4142"))
        shade = store.create_shade(2, "Added shade")
        self.assertEqual((shade.id, shade.room_id, shade.group_field, shade.positions), (1, 2, 2, {}))
        second = store.create_shade(2, "Next shade", group=5)
        self.assertEqual((second.id, second.group_field), (2, 5))
        self.assertNotIn(1, store.values)
        self.assertFalse(any(payload.startswith(b"$cp01-") for payload in store.snapshot()))
        for call in (lambda: store.create_shade(2, "Collision", group=3),
                     lambda: store.create_shade(99, "No room"),
                     lambda: store.create_room(1, "Duplicate RF", b"AB")):
            with self.assertRaises(ValueError):
                call()

    def test_snapshot_orders_stable_ids_and_positions_without_rewriting_opaque_records(self):
        source = inventory()
        # An opaque record between old definitions must retain its bytes and
        # relative position among all other opaque records after normalization.
        source.records.insert(10, BridgeRecord.from_raw(b"12 $opaque-between\x00\xff"))
        store = InventoryStore(source, self.path)
        room = store.create_room(1, "New first room", b"AB")
        shade = store.create_shade(2, "New middle shade")
        store.submitted(shade.id, 170)
        raw_before = [record.raw for record in store.inventory.records]
        snapshot = store.snapshot()
        self.assertEqual([int(payload[3:5]) for payload in snapshot if payload.startswith(b"$cr")], [0, 2, 5])
        self.assertEqual([int(payload[3:5]) for payload in snapshot if payload.startswith(b"$cs")], [0, 1, 3])
        seen_shades = set()
        for payload in snapshot:
            if payload.startswith(b"$cs"):
                seen_shades.add(int(payload[3:5]))
            elif payload.startswith(b"$cp"):
                self.assertIn(int(payload[3:5]), seen_shades)
        new_index = next(index for index, payload in enumerate(snapshot) if payload.startswith(b"$cs01-"))
        self.assertEqual(snapshot[new_index + 1], b"$cp01-04-170-")
        self.assertEqual([record.raw for record in store.inventory.records], raw_before)
        self.assertEqual([payload for payload in snapshot if payload.startswith((b"$ct", b"$set", b"$other", b"$opaque"))],
                         [record.payload for record in store.inventory.records
                          if record.payload.startswith((b"$ct", b"$set", b"$other", b"$opaque"))])
        restored = InventoryStore(source, self.path)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual((room.id, shade.id), (0, 1))
        self.assertEqual(set(restored.inventory.rooms), {0, 2, 5})
        self.assertEqual(set(restored.inventory.shades), {0, 1, 3})

    def test_deletion_does_not_compact_ids_or_change_surviving_rf_targets(self):
        store = InventoryStore(self.initial, self.path)
        survivor = store.inventory.shades[3]
        room = store.inventory.rooms[survivor.room_id]
        store.delete_shade(0)
        self.assertEqual(set(store.inventory.shades), {3})
        self.assertIn(b"$cs03-02-03-Another shade", store.snapshot())
        self.assertIn(b"$cp03-04-128-", store.snapshot())
        self.assertEqual(store.inventory.rooms[2].rf_identifier, room.rf_identifier)
        self.assertEqual(store.inventory.shades[3].group_field, survivor.group_field)
        self.assertEqual(InventoryStore(self.initial, self.path).snapshot(), store.snapshot())

    def test_slot_exhaustion_is_bounded_and_does_not_change_state(self):
        store = InventoryStore(self.initial)
        for group in (2, 4, 5, 6, 7, 8):
            store.create_shade(2, f"Slot {group}", group)
        revision, snapshot = store.revision, store.snapshot()
        with self.assertRaisesRegex(ValueError, "no free shade slots"):
            store.create_shade(2, "One too many")
        self.assertEqual((store.revision, store.snapshot()), (revision, snapshot))

    def test_move_clears_requested_position_and_persistently_revokes_old_binding(self):
        store = InventoryStore(self.initial, self.path)
        store.submitted(0, 128)
        moved = store.move_shade(0, 5)
        self.assertEqual((moved.room_id, moved.group_field, moved.positions), (5, 1, {}))
        self.assertNotIn(0, store.values)
        self.assertFalse(any(payload.startswith(b"$cp00-") for payload in store.snapshot()))
        projected = store.project_targets(targets())[0]
        self.assertEqual((projected.room_id, projected.room_rf_id, projected.mask), (5, b"\x3c\x4d", 1))
        self.assertFalse(projected.position_enabled)
        self.assertFalse(projected.sync_enabled)
        store.move_shade(0, 2, group=1)
        restored = InventoryStore(self.initial, self.path)
        self.assertFalse(restored.project_targets(targets())[0].sync_enabled)
        self.assertIn(0, restored.revoked_shade_ids)

    def test_new_and_recreated_ids_cannot_inherit_configured_grants(self):
        store = InventoryStore(self.initial, self.path)
        store.delete_shade(0)
        self.assertEqual(store.project_targets(targets()), {})
        replacement = store.create_shade(2, "Replacement", group=1)
        self.assertEqual(replacement.id, 0)
        self.assertFalse(store.project_targets(targets())[0].sync_enabled)
        created = store.create_shade(5, "New shade")
        presumed = {created.id: ShadeConfig("New shade", 5, b"\x3c\x4d", 1,
                                           position_enabled=True, sync_enabled=True)}
        self.assertFalse(store.project_targets(presumed)[created.id].sync_enabled)
        restored = InventoryStore(self.initial, self.path)
        self.assertFalse(restored.project_targets(targets())[0].position_enabled)

    def test_explicit_sync_grant_is_identity_bound_operation_scoped_and_persistent(self):
        store = InventoryStore(self.initial, self.path)
        shade = store.create_shade(2, "Added shade")
        configured = {shade.id: ShadeConfig("Added shade", 2, b"\x1a\x2b", 2,
                                            position_enabled=True, sync_enabled=True)}
        self.assertFalse(store.project_targets(configured)[shade.id].sync_enabled)
        grant = store.authorize_target(shade.id, expected_revision=store.revision,
                                       room_id=2, room_rf_id=b"\x1a\x2b", mask=2)
        self.assertEqual(grant, {"binding": {"room_id": 2, "room_rf_id": "1a2b", "mask": 2,
                                             "product_type": 1}, "operations": ["sync"]})
        grant["operations"].append("position")  # Returned values cannot widen the stored grant.
        restored = InventoryStore(self.initial, self.path)
        projected = restored.project_targets(configured)[shade.id]
        self.assertTrue(projected.sync_enabled)
        self.assertFalse(projected.position_enabled)
        self.assertIn(shade.id, restored.revoked_shade_ids)
        self.assertFalse(restored.project_targets({shade.id: replace(configured[shade.id], sync_enabled=False)})[shade.id].sync_enabled)
        self.assertFalse(restored.project_targets({shade.id: replace(configured[shade.id], mask=4)})[shade.id].sync_enabled)
        self.assertEqual(restored.project_targets({}), {})
        restored.authorize_target(shade.id, expected_revision=restored.revision,
                                  room_id=2, room_rf_id=b"\x1a\x2b", mask=2,
                                  operations={"position"})
        projected = restored.project_targets(configured)[shade.id]
        self.assertTrue(projected.position_enabled)
        self.assertFalse(projected.sync_enabled)  # Replacement does not silently union old permissions.

    def test_explicit_grant_requires_reviewed_revision_and_exact_valid_fields(self):
        store = InventoryStore(self.initial, self.path)
        shade = store.create_shade(2, "Added shade")
        valid = dict(expected_revision=store.revision, room_id=2, room_rf_id=b"\x1a\x2b", mask=2)
        disk, revision = self.path.read_bytes(), store.revision
        for changes in ({"expected_revision": 0}, {"expected_revision": None},
                        {"expected_revision": True}, {"room_id": 5}, {"room_id": True},
                        {"room_rf_id": b"AB"}, {"room_rf_id": "1a2b"}, {"mask": 4},
                        {"mask": 3}, {"mask": True}, {"operations": set()},
                        {"operations": {"unknown"}}, {"operations": "sync"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                store.authorize_target(shade.id, **(valid | changes))
        with self.assertRaises(ValueError):
            store.authorize_target(99, **valid)
        self.assertEqual((self.path.read_bytes(), store.revision), (disk, revision))

    def test_binding_changes_remove_grants_but_names_positions_and_clock_preserve_them(self):
        mutations = {
            "move": lambda store, shade: store.move_shade(shade, 5),
            "slot": lambda store, shade: store.update_shade(shade, group=4),
            "room_rf": lambda store, shade: store.update_room(2, rf_identifier=b"QR"),
            "product": lambda store, shade: store.update_room(2, product_type=2),
            "shade_delete": lambda store, shade: store.delete_shade(shade),
            "room_delete": lambda store, shade: store.delete_room(2, cascade=True),
        }
        for name, change in mutations.items():
            with self.subTest(change=name):
                path = self.path.parent / (name + ".json")
                store = InventoryStore(self.initial, path)
                shade = store.create_shade(2, "Added shade")
                configured = {shade.id: ShadeConfig("Added shade", 2, b"\x1a\x2b", 2,
                                                    position_enabled=True, sync_enabled=True)}
                store.authorize_target(shade.id, expected_revision=store.revision,
                                       room_id=2, room_rf_id=b"\x1a\x2b", mask=2,
                                       operations={"position", "sync"})
                store.rename_shade(shade.id, "Renamed shade")
                store.rename_room(2, "Renamed room")
                store.submitted(shade.id, 128)
                store.set_virtual_clock(b"$chksy2026-")
                self.assertTrue(store.project_targets(configured)[shade.id].sync_enabled)
                change(store, shade.id)
                self.assertNotIn(str(shade.id), json.loads(path.read_text())["rf_authorization_grants"])
                self.assertIn(shade.id, store.revoked_shade_ids)
                restored = InventoryStore(self.initial, path)
                projected = restored.project_targets(configured)
                self.assertTrue(shade.id not in projected or not projected[shade.id].sync_enabled)
                if name == "shade_delete":
                    replacement = restored.create_shade(2, "Replacement", group=2)
                    self.assertEqual(replacement.id, shade.id)
                    self.assertFalse(restored.project_targets(configured)[shade.id].sync_enabled)

    def test_optional_grant_state_is_backwards_compatible_and_malformed_grants_fail_closed(self):
        store = InventoryStore(self.initial, self.path)
        shade = store.create_shade(2, "Added shade")
        store.authorize_target(shade.id, expected_revision=store.revision,
                               room_id=2, room_rf_id=b"\x1a\x2b", mask=2)
        document = json.loads(self.path.read_text())
        old_schema_two = deepcopy(document)
        del old_schema_two["rf_authorization_grants"]
        self.path.write_text(json.dumps(old_schema_two))
        old = InventoryStore(self.initial, self.path)
        configured = {shade.id: ShadeConfig("Added shade", 2, b"\x1a\x2b", 2, sync_enabled=True)}
        self.assertFalse(old.project_targets(configured)[shade.id].sync_enabled)
        grant = document["rf_authorization_grants"][str(shade.id)]
        bad_grants = [[], {str(shade.id): {**grant, "extra": True}},
                      {"99": grant}, {str(shade.id): {**grant, "operations": ["unknown"]}},
                      {str(shade.id): {**grant, "operations": ["sync", "sync"]}},
                      {str(shade.id): {**grant, "binding": {**grant["binding"], "product_type": 2}}},
                      {str(shade.id): {**grant, "binding": {**grant["binding"], "room_id": True}}}]
        for malformed in bad_grants:
            with self.subTest(grants=malformed):
                invalid = deepcopy(document)
                invalid["rf_authorization_grants"] = malformed
                self.path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    InventoryStore(self.initial, self.path)

    def test_failed_grant_persistence_does_not_publish_authorization(self):
        store = InventoryStore(self.initial, self.path)
        shade = store.create_shade(2, "Added shade")
        configured = {shade.id: ShadeConfig("Added shade", 2, b"\x1a\x2b", 2, sync_enabled=True)}
        disk, revision = self.path.read_bytes(), store.revision
        with patch("hd_platinum.inventory_store.os.replace", side_effect=OSError("fake disk failure")):
            with self.assertRaises(OSError):
                store.authorize_target(shade.id, expected_revision=revision,
                                       room_id=2, room_rf_id=b"\x1a\x2b", mask=2)
        self.assertEqual((self.path.read_bytes(), store.revision), (disk, revision))
        self.assertFalse(store.project_targets(configured)[shade.id].sync_enabled)
        self.assertFalse(InventoryStore(self.initial, self.path).project_targets(configured)[shade.id].sync_enabled)

    def test_jog_grant_is_separate_persistent_and_revoked_on_identity_change(self):
        store = InventoryStore(self.initial, self.path)
        shade = store.create_shade(2, "Added shade")
        configured = {shade.id: ShadeConfig("Added shade", 2, b"\x1a\x2b", 2,
            position_enabled=True, sync_enabled=True, jog_enabled=True)}
        projected = store.project_targets(configured)[shade.id]
        self.assertFalse(projected.position_enabled or projected.sync_enabled or projected.jog_enabled)
        binding = dict(room_id=2, room_rf_id=b"\x1a\x2b", mask=2)
        # The unchanged default grants Sync only, never newly supported Jog.
        store.authorize_target(shade.id, expected_revision=store.revision, **binding)
        self.assertFalse(store.project_targets(configured)[shade.id].jog_enabled)
        store.authorize_target(shade.id, expected_revision=store.revision,
                               operations={"jog"}, **binding)
        store.rename_shade(shade.id, "Renamed shade")
        restored = InventoryStore(self.initial, self.path)
        projected = restored.project_targets(configured)[shade.id]
        self.assertTrue(projected.jog_enabled)
        self.assertFalse(projected.sync_enabled or projected.position_enabled)
        self.assertIn(shade.id, restored.revoked_shade_ids)
        self.assertFalse(restored.project_targets({shade.id: replace(configured[shade.id], jog_enabled=False)})[shade.id].jog_enabled)
        restored.update_room(2, product_type=2)
        self.assertFalse(restored.project_targets(configured)[shade.id].jog_enabled)
        self.assertNotIn(str(shade.id), json.loads(self.path.read_text())["rf_authorization_grants"])

    def test_room_binding_change_revokes_children_and_cascade_is_explicit_atomic(self):
        store = InventoryStore(self.initial, self.path)
        store.submitted(0, 200)
        before = store.snapshot()
        with self.assertRaisesRegex(ValueError, "still contains"):
            store.delete_room(2)
        self.assertEqual(store.snapshot(), before)
        store.update_room(2, rf_identifier=b"QR")
        self.assertEqual(store.revoked_shade_ids, frozenset({0, 3}))
        self.assertEqual(store.values, {})
        store.delete_room(2, cascade=True)
        self.assertEqual(store.inventory.shades, {})
        self.assertNotIn(2, store.inventory.rooms)
        self.assertFalse(any(payload.startswith((b"$cs", b"$cp")) for payload in store.snapshot()))
        store.delete_room(5)
        restored = InventoryStore(self.initial, self.path)
        self.assertEqual(restored.inventory.rooms, {})
        self.assertEqual(restored.inventory.shades, {})
        self.assertEqual(restored.snapshot()[-1], b"$upd01-")
        self.assertIn(b"$ct\x00\xffopaque-$title", restored.snapshot())

    def test_failed_replace_preserves_disk_memory_and_revision(self):
        store = InventoryStore(self.initial, self.path)
        store.submitted(0, 100)
        disk, revision, snapshot = self.path.read_bytes(), store.revision, store.snapshot()
        with patch("hd_platinum.inventory_store.os.replace", side_effect=OSError("fake disk failure")):
            with self.assertRaises(OSError):
                store.rename_shade(0, "Uncommitted")
        self.assertEqual(self.path.read_bytes(), disk)
        self.assertEqual((store.revision, store.snapshot()), (revision, snapshot))
        self.assertEqual(list(self.path.parent.glob(".inventory-*")), [])

    def test_uncertain_directory_sync_blocks_stale_memory_until_reopen(self):
        store = InventoryStore(self.initial, self.path)
        store.submitted(0, 100)
        real_fsync = os.fsync
        def fail_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("fake directory sync failure")
            return real_fsync(descriptor)
        with patch("hd_platinum.inventory_store.os.fsync", side_effect=fail_directory):
            with self.assertRaises(OSError):
                store.rename_shade(0, "Committed uncertainly")
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            store.snapshot()
        reopened = InventoryStore(self.initial, self.path)
        self.assertEqual(reopened.inventory.shades[0].name, "Committed uncertainly")
        self.assertEqual(reopened.values, {0: 100})

    def test_name_limits_use_utf16_units_and_reject_controls_without_trimming(self):
        store = InventoryStore(self.initial)
        name = "😀" * 12 + "x"
        self.assertEqual(store.rename_shade(0, name).name, name)
        self.assertEqual(store.rename_shade(0, "  Named shade  ").name, "  Named shade  ")
        for bad in ("😀" * 13, "x" * 26, "", "   ", "x\x00y", "x\ty", "x\ry", "x\ny", "x\x7fy", "\ud800", None):
            with self.subTest(name=repr(bad)), self.assertRaises((ValueError, UnicodeError)):
                store.rename_shade(0, bad)
        for bad in (True, -1, 100, "2"):
            with self.subTest(identifier=bad), self.assertRaises(ValueError):
                store.create_shade(bad, "Invalid")

    def test_scene_dependencies_are_not_silently_rewritten(self):
        store = InventoryStore(inventory([b"$cm01-Scene", b"$cq01-00-01-", b"$cx01-05-04-128-"]))
        for operation in (lambda: store.delete_shade(0), lambda: store.delete_room(2, cascade=True),
                          lambda: store.delete_room(5)):
            with self.assertRaisesRegex(ValueError, "scene"):
                operation()
        self.assertIn(b"$cq01-00-01-", store.snapshot())

    def test_clock_compatibility_expected_revision_and_concurrent_methods(self):
        store = InventoryStore(self.initial, self.path)
        store.set_virtual_clock(b"$sdt10-24-07-2026-")
        store.set_virtual_clock(b"$stm12-30-01-")
        store.set_virtual_clock(b"$chksy2026-")
        self.assertEqual(store.virtual_clock, {"date": "2026-10-24", "weekday": 7,
                                               "time": "12:30:01", "checked_year": 2026})
        with self.assertRaisesRegex(ValueError, "revision changed"):
            store.rename_room(2, "Stale", expected_revision=0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            created = list(pool.map(lambda i: store.create_room(1, f"Room {i}", bytes((128, i))), range(6)))
        self.assertEqual(sorted(room.id for room in created), [0, 1, 3, 4, 6, 7])
        self.assertEqual(InventoryStore(self.initial, self.path).revision, 9)
        self.assertEqual(len(store.inventory.rooms), 8)

    def test_unsafe_corrupt_or_oversized_state_and_duplicate_definitions_are_rejected(self):
        target = self.path.parent / "other"
        target.write_text("untouched")
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            InventoryStore(self.initial, self.path)
        self.assertEqual(target.read_text(), "untouched")
        self.path.unlink()
        with self.path.open("wb") as stream:
            stream.truncate(MAX_STATE_BYTES + 1)
        with self.assertRaises(ValueError):
            InventoryStore(self.initial, self.path)
        self.path.write_text('{"schema_version":2,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            InventoryStore(self.initial, self.path)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            InventoryStore(inventory([b"$cs00-02-01-Duplicate"]))


if __name__ == "__main__":
    unittest.main()
