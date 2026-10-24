# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mutable private bridge inventory with atomic, receive-independent persistence.

This module accepts typed database operations, not app write-command grammar.
Unrelated raw records survive edits. Inventory membership never grants RF
authorization; creation, deletion, or rebinding revokes inherited target grants.
One shared store instance owns a state path; its RLock serializes its users.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, time
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import unicodedata

from .lan import BridgeInventory, BridgeRecord, MAX_SNAPSHOT_BYTES, RECORD_DELIMITER, Room, Shade, parse_records


MAX_STATE_BYTES = 4 * MAX_SNAPSHOT_BYTES
MAX_NAME_UTF16_UNITS = 25
_ROOM = re.compile(rb"\$cr([0-9]{2})-([0-9]{2})-(0x[0-9a-fA-F]{4})-(.*)\Z", re.DOTALL)
_SHADE = re.compile(rb"\$cs([0-9]{2})-([0-9]{2})-([0-9]{2})-(.*)\Z", re.DOTALL)
_POSITION = re.compile(rb"\$cp([0-9]{2})-([0-9]{2})-([0-9]{3})-\Z")
_DATE = re.compile(rb"\$sdt([0-9]{2})-([0-9]{2})-([0-9]{1,2})-([0-9]{4})-\Z")
_TIME = re.compile(rb"\$stm([0-9]{2})-([0-9]{2})-([0-9]{2})-\Z")
_CHECK_YEAR = re.compile(rb"\$chksy([0-9]{4})-\Z")


def _integer(value, name, low=0, high=99):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer within {low}..{high}")
    return value


def _name(value):
    if (not isinstance(value, str) or not value.strip()
            or any(unicodedata.category(character) == "Cc" for character in value)):
        raise ValueError("name must be nonempty text without control characters")
    if not 1 <= len(value.encode("utf-16-le")) // 2 <= MAX_NAME_UTF16_UNITS or len(value.encode("utf-8")) > 396:
        raise ValueError("name must contain 1..25 UTF-16 code units and at most 396 UTF-8 bytes")
    return value  # Preserve intentional spaces and Unicode; do not normalize.


def _rf_identifier(value):
    if not isinstance(value, (bytes, bytearray)) or len(value) != 2:
        raise ValueError("room RF identifier must contain exactly two bytes")
    return "0x" + bytes(value).hex().upper()


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("state contains a duplicate JSON key")
        result[key] = value
    return result


def _validate_inventory(records):
    inventory = parse_records(records)
    payloads = [record.payload for record in inventory.records]
    if (not inventory.update_started or not inventory.update_complete or not payloads
            or payloads.count(b"$upd00-") != 1 or payloads.count(b"$upd01-") != 1
            or payloads[-1] != b"$upd01-"
            or sum(len(record.raw) + 2 for record in records) > MAX_SNAPSHOT_BYTES
            or any(RECORD_DELIMITER in payload or len(payload) > 65536 for payload in payloads)
            or any(record.kind in ("action", "done", "ack", "error") for record in records)):
        raise ValueError("inventory must contain one bounded complete snapshot")
    room_ids = [int(match[1]) for record in records if (match := _ROOM.fullmatch(record.payload))]
    shade_ids = [int(match[1]) for record in records if (match := _SHADE.fullmatch(record.payload))]
    if len(room_ids) != len(set(room_ids)) or len(shade_ids) != len(set(shade_ids)):
        raise ValueError("inventory contains duplicate room or shade definitions")
    if set(shade_ids) != set(inventory.shades):
        raise ValueError("inventory contains positions for an undefined shade")
    for shade in inventory.shades.values():
        if shade.room_id not in inventory.rooms or not shade.name:
            raise ValueError("shade requires an existing room and nonempty name")
        if any(not 0 <= value <= 255 for value in shade.positions.values()):
            raise ValueError("inventory position is out of range")
    if any(not room.name for room in inventory.rooms.values()):
        raise ValueError("room requires a nonempty name")
    return inventory


def _validate_clock(value):
    if not isinstance(value, dict) or set(value) - {"date", "weekday", "time", "checked_year"}:
        raise ValueError("invalid virtual clock fields")
    if "date" in value:
        if not isinstance(value["date"], str):
            raise ValueError("virtual date must be a string")
        date.fromisoformat(value["date"])
    if "time" in value:
        if not isinstance(value["time"], str):
            raise ValueError("virtual time must be a string")
        time.fromisoformat(value["time"])
    if "weekday" in value:
        _integer(value["weekday"], "weekday", 1, 7)
    if "checked_year" in value:
        _integer(value["checked_year"], "checked year", 1, 9999)
    return dict(value)


def _target_binding(inventory, shade_id):
    shade = inventory.shades.get(shade_id)
    if shade is None:
        raise ValueError("shade is undefined")
    _integer(shade.group_field, "shade group", 1, 8)
    room = inventory.rooms[shade.room_id]
    return {"room_id": shade.room_id,
            "room_rf_id": bytes.fromhex(room.rf_identifier[2:]).hex(),
            "mask": 1 << (shade.group_field - 1), "product_type": room.product_type}


def _validate_grants(value, inventory):
    if not isinstance(value, dict):
        raise ValueError("RF authorization grants must be an object")
    grants = {}
    for key, grant in value.items():
        if (not isinstance(key, str) or not re.fullmatch(r"0|[1-9][0-9]?", key)
                or not isinstance(grant, dict) or set(grant) != {"binding", "operations"}):
            raise ValueError("invalid RF authorization grant")
        binding = grant["binding"]
        expected = _target_binding(inventory, int(key))
        if (not isinstance(binding, dict) or set(binding) != set(expected)
                or any(type(binding[name]) is not type(item) or binding[name] != item
                       for name, item in expected.items())):
            raise ValueError("RF authorization grant does not match the current identity")
        operations = grant["operations"]
        if (not isinstance(operations, list) or not operations
                or any(type(operation) is not str or operation not in {"sync", "position", "jog"}
                       for operation in operations)
                or len(operations) != len(set(operations))):
            raise ValueError("invalid RF authorization operations")
        grants[int(key)] = {"binding": dict(binding), "operations": sorted(operations)}
    return grants


@dataclass
class _State:
    inventory: BridgeInventory
    values: dict
    virtual_clock: dict
    revoked: set
    revision: int = 0
    grants: dict = field(default_factory=dict)


class InventoryStore:
    """Compatible with the former position overlay, plus typed room/shade CRUD.

    Reads return detached views. Every mutation validates and durably replaces
    the single schema-2 file before publishing memory. A schema-1 position file
    is migrated once only when its seed inventory hash matches. The original
    inventory remains an immutable seed, not an update source on restart.
    """

    def __init__(self, initial: BridgeInventory, state_path=None):
        if not isinstance(initial, BridgeInventory):
            raise ValueError("initial inventory must be a BridgeInventory")
        self.lock = threading.RLock()
        self.path = Path(state_path) if state_path is not None else None
        inventory = _validate_inventory(list(initial.records))
        self.fingerprint = hashlib.sha256(RECORD_DELIMITER.join(record.payload for record in inventory.records)).hexdigest()
        self._unavailable = False
        self._state = _State(inventory, {}, {}, set())
        document = self._read_document() if self.path is not None else None
        if document is not None:
            schema = document.get("schema_version")
            if type(schema) is not int:
                raise ValueError("inventory state schema must be an integer")
            if schema == 1:
                if document.get("inventory_sha256") != self.fingerprint or document.get("position_confirmed") is not False:
                    raise ValueError("legacy position state does not match the original inventory")
                candidate = self._load_state(document, inventory)
                self._persist(candidate)
            elif schema == 2:
                if document.get("seed_inventory_sha256") != self.fingerprint or document.get("position_confirmed") is not False:
                    raise ValueError("saved inventory state does not match the original seed")
                saved_records = document.get("records")
                if not isinstance(saved_records, list):
                    raise ValueError("saved inventory requires raw records")
                records = []
                for item in saved_records:
                    if not isinstance(item, dict) or set(item) != {"raw_hex"} or not isinstance(item["raw_hex"], str):
                        raise ValueError("saved records require raw_hex only")
                    records.append(BridgeRecord.from_raw(bytes.fromhex(item["raw_hex"])))
                candidate = self._load_state(document, _validate_inventory(records))
            else:
                raise ValueError("unsupported inventory state schema")
            self._state = candidate

    def _check_available(self):
        if self._unavailable:
            raise RuntimeError("inventory commit was uncertain; reopen the store before continuing")

    def _read_document(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_STATE_BYTES:
                raise ValueError("inventory state must be a bounded regular file with one link")
            os.fchmod(stream.fileno(), 0o600)
            result = json.loads(stream.read(), object_pairs_hook=_unique_json)
        if not isinstance(result, dict):
            raise ValueError("inventory state must be a JSON object")
        return result

    @staticmethod
    def _load_state(document, inventory):
        values = document.get("requested_positions", {})
        if not isinstance(values, dict):
            raise ValueError("requested positions must be an object")
        positions = {}
        for key, value in values.items():
            if not isinstance(key, str) or not re.fullmatch(r"0|[1-9][0-9]?", key) or int(key) not in inventory.shades:
                raise ValueError("requested position refers to an undefined shade")
            positions[int(key)] = _integer(value, "requested position", 0, 255)
        revoked = document.get("rf_authorization_revoked_shade_ids", [])
        if not isinstance(revoked, list) or any(type(value) is not int or not 0 <= value <= 99 for value in revoked):
            raise ValueError("invalid RF authorization revocations")
        if len(revoked) != len(set(revoked)):
            raise ValueError("duplicate RF authorization revocation")
        revision = _integer(document.get("revision", 0), "revision", 0, (1 << 63) - 1)
        grants = _validate_grants(document.get("rf_authorization_grants", {}), inventory)
        return _State(inventory, positions, _validate_clock(document.get("virtual_clock", {})),
                      set(revoked), revision, grants)

    def _persist(self, state):
        if self.path is None:
            return
        document = {"schema_version": 2, "revision": state.revision,
                    "seed_inventory_sha256": self.fingerprint,
                    "records": [{"raw_hex": record.raw.hex()} for record in state.inventory.records],
                    "requested_positions": {str(key): value for key, value in state.values.items()},
                    "virtual_clock": state.virtual_clock,
                    "rf_authorization_revoked_shade_ids": sorted(state.revoked),
                    "rf_authorization_grants": {str(key): value for key, value in state.grants.items()},
                    "position_confirmed": False,
                    "position_semantics": "requested after submission; physically unconfirmed"}
        encoded = (json.dumps(document, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > MAX_STATE_BYTES:
            raise ValueError("inventory state exceeds the encoded size limit")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A symlink must not be silently replaced, nor a shared hard-linked file.
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("inventory state must be a regular file with one link")
        descriptor, temporary = tempfile.mkstemp(prefix=".inventory-", dir=self.path.parent)
        replaced = False
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            replaced = True
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            if replaced:
                self._unavailable = True
            raise
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _mutate(self, change, expected_revision=None):
        with self.lock:
            self._check_available()
            if expected_revision is not None:
                _integer(expected_revision, "expected revision", 0, (1 << 63) - 1)
                if expected_revision != self._state.revision:
                    raise ValueError("inventory revision changed")
            candidate = deepcopy(self._state)
            result = change(candidate)
            candidate.inventory = _validate_inventory(candidate.inventory.records)
            candidate.grants = _validate_grants({str(key): value for key, value in candidate.grants.items()},
                                                candidate.inventory)
            if any(shade not in candidate.inventory.shades for shade in candidate.values):
                raise ValueError("requested position refers to a removed shade")
            candidate.revision = _integer(candidate.revision + 1, "revision", 0, (1 << 63) - 1)
            self._persist(candidate)
            self._state = candidate
            return deepcopy(result)

    @property
    def inventory(self):
        with self.lock:
            self._check_available()
            return deepcopy(self._state.inventory)

    @property
    def values(self):
        with self.lock:
            self._check_available()
            return dict(self._state.values)

    @property
    def virtual_clock(self):
        with self.lock:
            self._check_available()
            return dict(self._state.virtual_clock)

    @property
    def revision(self):
        with self.lock:
            self._check_available()
            return self._state.revision

    @property
    def revoked_shade_ids(self):
        with self.lock:
            self._check_available()
            return frozenset(self._state.revoked)

    def snapshot(self):
        """Emit rooms/shades by ascending stable ID, positions after their shade.

        The Android client appends definitions to lists and then indexes those
        lists by ID. Ordering is necessary but does not make sparse IDs dense;
        no ID or RF identity is renumbered here. Stored raw records stay intact,
        and opaque records retain their bytes and relative order on the wire.
        """
        with self.lock:
            self._check_available()
            rooms, shades, positions = {}, {}, {}
            for record in self._state.inventory.records:
                if match := _ROOM.fullmatch(record.payload):
                    rooms[int(match[1])] = record.payload
                elif match := _SHADE.fullmatch(record.payload):
                    shades[int(match[1])] = record.payload
                elif match := _POSITION.fullmatch(record.payload):
                    positions.setdefault(int(match[1]), []).append((int(match[2]), record.payload))
            definitions = [payload for _, payload in sorted(rooms.items())]
            for shade, payload in sorted(shades.items()):
                definitions.append(payload)
                seen_primary = False
                for feature, position_payload in positions.get(shade, []):
                    if feature == 4:
                        seen_primary = True
                        if shade in self._state.values:
                            position_payload = f"$cp{shade:02d}-04-{self._state.values[shade]:03d}-".encode()
                    definitions.append(position_payload)
                if shade in self._state.values and not seen_primary:
                    definitions.append(f"$cp{shade:02d}-04-{self._state.values[shade]:03d}-".encode())
            output, emitted = [], False
            for record in self._state.inventory.records:
                if record.kind == "banner":
                    continue
                payload = record.payload
                if _ROOM.fullmatch(payload) or _SHADE.fullmatch(payload) or _POSITION.fullmatch(payload):
                    if not emitted:
                        output.extend(definitions)
                        emitted = True
                    continue
                output.append(payload)
            return output

    def submitted(self, shade, position):
        _integer(shade, "shade ID")
        _integer(position, "requested position", 0, 255)
        def change(state):
            if shade not in state.inventory.shades:
                raise ValueError("requested position refers to an undefined shade")
            state.values[shade] = position
        self._mutate(change)

    def set_virtual_clock(self, command):
        if match := _DATE.fullmatch(command):
            month, day, weekday, year = map(int, match.groups())
            update = {"date": date(year, month, day).isoformat(), "weekday": _integer(weekday, "weekday", 1, 7)}
        elif match := _TIME.fullmatch(command):
            update = {"time": time(*map(int, match.groups())).isoformat()}
        elif match := _CHECK_YEAR.fullmatch(command):
            update = {"checked_year": _integer(int(match[1]), "checked year", 1, 9999)}
        else:
            raise ValueError("unsupported virtual clock command")
        self._mutate(lambda state: state.virtual_clock.update(update))

    @staticmethod
    def _lowest_free(used):
        try:
            return next(value for value in range(100) if value not in used)
        except StopIteration:
            raise ValueError("no free inventory IDs remain") from None

    @staticmethod
    def _replace_record(state, pattern, identifier, payload):
        for index, record in enumerate(state.inventory.records):
            match = pattern.fullmatch(record.payload)
            if match and int(match[1]) == identifier:
                prefix = record.raw[:-len(record.payload)]
                state.inventory.records[index] = BridgeRecord.from_raw(prefix + payload)
                return
        raise ValueError("entity definition is missing")

    @staticmethod
    def _insert_record(state, payload, *, room=False):
        records = state.inventory.records
        index = next((i for i, record in enumerate(records)
                      if (room and _SHADE.fullmatch(record.payload))
                      or record.kind in ("scene", "scene_link", "scene_room_position", "schedule")
                      or record.payload == b"$upd01-"), len(records) - 1)
        records.insert(index, BridgeRecord.from_raw(payload))

    @staticmethod
    def _clear_target_state(state, shade):
        state.revoked.add(shade)
        state.grants.pop(shade, None)
        state.values.pop(shade, None)
        state.inventory.records = [record for record in state.inventory.records
                                   if not ((match := _POSITION.fullmatch(record.payload)) and int(match[1]) == shade)]

    def create_room(self, product_type, name, rf_identifier, *, expected_revision=None):
        product_type, name, rf = _integer(product_type, "product type"), _name(name), _rf_identifier(rf_identifier)
        def change(state):
            if any(room.rf_identifier.lower() == rf.lower() for room in state.inventory.rooms.values()):
                raise ValueError("room RF identifier is already in use")
            identifier = self._lowest_free(state.inventory.rooms)
            room = Room(identifier, product_type, rf, name)
            self._insert_record(state, f"$cr{identifier:02d}-{product_type:02d}-{rf}-".encode() + name.encode("utf-8"), room=True)
            return room
        return self._mutate(change, expected_revision)

    def update_room(self, room_id, *, name=None, product_type=None, rf_identifier=None, expected_revision=None):
        _integer(room_id, "room ID")
        if name is not None:
            _name(name)
        if product_type is not None:
            _integer(product_type, "product type")
        rf = _rf_identifier(rf_identifier) if rf_identifier is not None else None
        def change(state):
            if room_id not in state.inventory.rooms:
                raise ValueError("room is undefined")
            old = state.inventory.rooms[room_id]
            room = Room(room_id, old.product_type if product_type is None else product_type,
                        old.rf_identifier if rf is None else rf, old.name if name is None else name)
            if (room.rf_identifier.lower() != old.rf_identifier.lower()
                    and any(other.id != room_id and other.rf_identifier.lower() == room.rf_identifier.lower()
                            for other in state.inventory.rooms.values())):
                raise ValueError("room RF identifier is already in use")
            if (room.product_type, room.rf_identifier.lower()) != (old.product_type, old.rf_identifier.lower()):
                for shade in state.inventory.shades.values():
                    if shade.room_id == room_id:
                        self._clear_target_state(state, shade.id)
            self._replace_record(state, _ROOM, room_id,
                f"$cr{room_id:02d}-{room.product_type:02d}-{room.rf_identifier}-".encode() + room.name.encode("utf-8"))
            return room
        return self._mutate(change, expected_revision)

    def rename_room(self, room_id, name, *, expected_revision=None):
        return self.update_room(room_id, name=_name(name), expected_revision=expected_revision)

    def delete_room(self, room_id, *, cascade=False, expected_revision=None):
        _integer(room_id, "room ID")
        if type(cascade) is not bool:
            raise ValueError("cascade must be a boolean")
        def change(state):
            if room_id not in state.inventory.rooms:
                raise ValueError("room is undefined")
            children = {shade.id for shade in state.inventory.shades.values() if shade.room_id == room_id}
            if children and not cascade:
                raise ValueError("room still contains shades")
            if any(item["room_id"] == room_id for item in state.inventory.scene_room_positions):
                raise ValueError("room is referenced by a scene")
            if any(item["shade_id"] in children for item in state.inventory.scene_links):
                raise ValueError("room contains a shade referenced by a scene")
            room = state.inventory.rooms[room_id]
            for shade in children:
                self._clear_target_state(state, shade)
            state.inventory.records = [record for record in state.inventory.records
                if not (((match := _ROOM.fullmatch(record.payload)) and int(match[1]) == room_id)
                        or ((match := _SHADE.fullmatch(record.payload)) and int(match[1]) in children))]
            return room
        return self._mutate(change, expected_revision)

    @staticmethod
    def _slot(state, room_id, group, *, exclude=None):
        if room_id not in state.inventory.rooms:
            raise ValueError("room is undefined")
        used = {shade.group_field for shade in state.inventory.shades.values()
                if shade.room_id == room_id and shade.id != exclude}
        if group is None:
            group = next((value for value in range(1, 9) if value not in used), None)
            if group is None:
                raise ValueError("room has no free shade slots")
        _integer(group, "shade group", 1, 8)
        if group in used:
            raise ValueError("shade group is already occupied in this room")
        return group

    def create_shade(self, room_id, name, group=None, *, expected_revision=None):
        _integer(room_id, "room ID")
        name = _name(name)
        def change(state):
            slot = self._slot(state, room_id, group)
            identifier = self._lowest_free(state.inventory.shades)
            shade = Shade(identifier, room_id, slot, name)
            self._insert_record(state, f"$cs{identifier:02d}-{room_id:02d}-{slot:02d}-".encode() + name.encode("utf-8"))
            state.revoked.add(identifier)  # Never inherit an old or preconfigured grant.
            state.grants.pop(identifier, None)
            return shade
        return self._mutate(change, expected_revision)

    def update_shade(self, shade_id, *, name=None, room_id=None, group=None, expected_revision=None):
        _integer(shade_id, "shade ID")
        if name is not None:
            _name(name)
        if room_id is not None:
            _integer(room_id, "room ID")
        def change(state):
            if shade_id not in state.inventory.shades:
                raise ValueError("shade is undefined")
            old = state.inventory.shades[shade_id]
            destination = old.room_id if room_id is None else room_id
            slot = (old.group_field if group is None and destination == old.room_id
                    else self._slot(state, destination, group, exclude=shade_id))
            shade = Shade(shade_id, destination, slot, old.name if name is None else name, dict(old.positions))
            if (destination, slot) != (old.room_id, old.group_field):
                self._clear_target_state(state, shade_id)
                shade.positions.clear()
            self._replace_record(state, _SHADE, shade_id,
                f"$cs{shade_id:02d}-{destination:02d}-{slot:02d}-".encode() + shade.name.encode("utf-8"))
            return shade
        return self._mutate(change, expected_revision)

    def rename_shade(self, shade_id, name, *, expected_revision=None):
        return self.update_shade(shade_id, name=_name(name), expected_revision=expected_revision)

    def move_shade(self, shade_id, room_id, group=None, *, expected_revision=None):
        return self.update_shade(shade_id, room_id=_integer(room_id, "room ID"), group=group, expected_revision=expected_revision)

    def delete_shade(self, shade_id, *, expected_revision=None):
        _integer(shade_id, "shade ID")
        def change(state):
            if shade_id not in state.inventory.shades:
                raise ValueError("shade is undefined")
            if any(item["shade_id"] == shade_id for item in state.inventory.scene_links):
                raise ValueError("shade is referenced by a scene")
            shade = state.inventory.shades[shade_id]
            self._clear_target_state(state, shade_id)
            state.inventory.records = [record for record in state.inventory.records
                                       if not ((match := _SHADE.fullmatch(record.payload)) and int(match[1]) == shade_id)]
            return shade
        return self._mutate(change, expected_revision)

    def authorize_target(self, shade_id, *, expected_revision, room_id, room_rf_id,
                         mask, operations=frozenset({"sync"})):
        """Persist an explicit identity-bound permission, separate from CRUD.

        Callers must supply the exact reviewed revision and current RF binding.
        The current product type is included in the persisted binding. A grant
        replaces prior explicit operations; it never enables a private-config
        flag or clears a revocation tombstone. Later rebinding or deletion
        removes it, while cosmetic names and requested positions do not.
        """
        _integer(shade_id, "shade ID")
        _integer(expected_revision, "expected revision", 0, (1 << 63) - 1)
        _integer(room_id, "room ID")
        identity = _rf_identifier(room_rf_id)[2:].lower()
        _integer(mask, "shade mask", 1, 128)
        if mask & (mask - 1):
            raise ValueError("shade mask must select exactly one shade")
        if (not isinstance(operations, (set, frozenset)) or not operations
                or any(type(operation) is not str or operation not in {"sync", "position", "jog"}
                       for operation in operations)):
            raise ValueError("operations must be a nonempty set of sync, position, and/or jog")
        requested = sorted(operations)

        def change(state):
            binding = _target_binding(state.inventory, shade_id)
            if (binding["room_id"], binding["room_rf_id"], binding["mask"]) != (room_id, identity, mask):
                raise ValueError("requested RF authorization does not match the current identity")
            grant = {"binding": binding, "operations": requested}
            state.grants[shade_id] = grant
            return grant
        return self._mutate(change, expected_revision)

    def project_targets(self, configured_targets: Mapping):
        """Intersect current identity, private config, and explicit permissions.

        A deleted ID is omitted. A rebound or recreated target remains disabled
        even if later edits restore its old numeric ID/address, unless an
        explicit matching grant permits that particular configured operation.
        Ordinary inventory CRUD never creates such a grant.
        """
        if not isinstance(configured_targets, Mapping):
            raise ValueError("configured targets must be a mapping")
        with self.lock:
            self._check_available()
            result = {}
            for identifier, target in configured_targets.items():
                _integer(identifier, "configured shade ID")
                shade = self._state.inventory.shades.get(identifier)
                if shade is None or not 1 <= shade.group_field <= 8:
                    continue
                room = self._state.inventory.rooms[shade.room_id]
                identity, mask = bytes.fromhex(room.rf_identifier[2:]), 1 << (shade.group_field - 1)
                unchanged = (target.room_id, target.room_rf_id, target.mask) == (shade.room_id, identity, mask)
                inherited = identifier not in self._state.revoked
                grant = self._state.grants.get(identifier)
                operations = (grant["operations"] if grant is not None
                              and grant["binding"] == _target_binding(self._state.inventory, identifier) else ())
                result[identifier] = replace(target, name=shade.name, room_id=shade.room_id,
                    room_rf_id=identity, mask=mask,
                    position_enabled=target.position_enabled and unchanged and (inherited or "position" in operations),
                    sync_enabled=target.sync_enabled and unchanged and (inherited or "sync" in operations),
                    jog_enabled=target.jog_enabled and unchanged and (inherited or "jog" in operations))
            return result
