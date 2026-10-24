# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bounded original-Platinum TCP compatibility service.

Supported requests include $dat, acknowledged $dmy, feature-04 $pss/$psr, and $rls. Staging
emits the observed action-start, requested-position, done sequence; shade and
legacy short room requests require release. APK room requests ending in 0-/00-
dispatch immediately. All positions are requested state,
never physical feedback. Room/shade CRUD updates the private inventory without
granting RF authorization; scene/reset writes remain rejected.
Explicitly enabled $rscII- requests dispatch a separate Sync backend immediately,
without $rls or $done. Feature-01 reports are not persisted as positions and
action completion does not confirm enrollment. Explicitly enabled feature-12
Jog stages one target separately from positions and requires release; requested
LAN value 000 produces the observed feature-12 status value 001.
App date/time startup requests store virtual fields without touching host time;
the same-year check reply is captured, while broader year/solar semantics remain
unestablished.

Use the same BridgeService as HTTP to share its allowlist and RF serialization.
Sync owns one non-daemon worker while its connection continues acknowledging
keepalives. Other requests received during that action are rejected as busy,
never queued. shutdown() stops accepting/reading clients; server_close() waits
for owned finite backend calls. This cleartext protocol has no authentication, so binds
outside loopback require an explicit private/local client-network allowlist.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Mapping
from copy import deepcopy
import ipaddress
import json
import logging
import math
from pathlib import Path
import re
import secrets
import socket
import socketserver
import threading
import time
from uuid import uuid4

from .bridge import BridgeError, BridgeService
from .inventory_store import InventoryStore, MAX_NAME_UTF16_UNITS
from .products import validate_product_code
from .lan import (BridgeInventory, BridgeRecord, MAX_SNAPSHOT_BYTES,
                  RECORD_DELIMITER, RecordFramer, parse_records)


BANNER = b"HunterDouglas Shade Controller"
_POSITION = re.compile(rb"\$cp([0-9]{2})-([0-9]{2})-([0-9]{3})-\Z")
_STAGE = re.compile(rb"\$ps[sr]([0-9]{2})-([0-9]{2})-([0-9]{3})-\Z")
_SYNC = re.compile(rb"\$rsc([0-9]{2})-\Z")
_DATE = re.compile(rb"\$sdt([0-9]{2})-([0-9]{2})-([0-9]{1,2})-([0-9]{4})-\Z")
_TIME = re.compile(rb"\$stm([0-9]{2})-([0-9]{2})-([0-9]{2})-\Z")
_CHECK_YEAR = re.compile(rb"\$chksy([0-9]{4})-\Z")
# A same-year request to the original bridge returned exactly $chksy01-.
# Broader year/solar semantics and other response mappings are unestablished.
CHECK_YEAR_REPLY = b"$chksy01-"
_LOCAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"))

# Legacy emulator error assignments; most do not map to original meanings.
ERROR_UNSUPPORTED, ERROR_TARGET, ERROR_BUSY = b"$error01-", b"$error02-", b"$error03-"
ERROR_STAGE, ERROR_BACKEND, ERROR_LIMIT = b"$error04-", b"$error05-", b"$error06-"
ERROR_CLOCK = b"$error07-"
# The APK specifically handles 03 as eight shade slots occupied in one room.
# The existing emulator busy code also uses 03; broader errors remain unverified.
ERROR_ROOM_FULL = b"$error03-"


class _RoomFullError(ValueError):
    pass


def _number(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer within {low}..{high}")
    return value


def _label(value):
    if not isinstance(value, str) or not value or any(c in value for c in "\r\n\x00"):
        raise ValueError("inventory text must be nonempty and cannot contain record delimiters")
    return value.encode("utf-8")


def _summary_records(document):
    """Fallback for saved summaries; an original raw-record snapshot is preferable."""
    value = document.get("inventory", document)
    if not isinstance(value, Mapping) or value.get("update_complete") is not True:
        raise ValueError("inventory summary must be complete")
    records = [BANNER]
    if value.get("firmware"):
        code = value.get("firmware_record_code")
        code = _number(3 if code is None else code, "firmware code", 0, 99)
        records.append(f"$firm{code:02d}-".encode() + _label(value["firmware"]))
    mac = value.get("mac")
    if mac is not None:
        if not isinstance(mac, str) or not re.fullmatch(r"[0-9a-fA-F]{12}", mac):
            raise ValueError("inventory MAC must be unredacted hexadecimal")
        records.append(f"$MAC0x{mac}-".encode())
    if value.get("led_level") is not None:
        records.append(f'$LEDl{_number(value["led_level"], "LED level", 0, 255):03d}-'.encode())
    records.extend((b"$upd00-", b"$reset"))
    if document.get("title_raw_hex") is not None:
        records.append(b"$ct" + bytes.fromhex(document["title_raw_hex"]))
    for room in value.get("rooms", []):
        ident = _number(room["id"], "room ID", 0, 99)
        product = _number(room["product_type"], "product type", 0, 99)
        rf = room["rf_identifier"]
        if not isinstance(rf, str) or not re.fullmatch(r"0x[0-9a-fA-F]{4}", rf):
            raise ValueError("room identity must be unredacted")
        records.append(f"$cr{ident:02d}-{product:02d}-{rf}-".encode() + _label(room["name"]))
    for shade in value.get("shades", []):
        ident = _number(shade["id"], "shade ID", 0, 99)
        room = _number(shade["room_id"], "room ID", 0, 99)
        group = _number(shade["group_field"], "group field", 0, 99)
        records.append(f"$cs{ident:02d}-{room:02d}-{group:02d}-".encode() + _label(shade["name"]))
        for feature, position in shade.get("positions", {}).items():
            if not re.fullmatch(r"[0-9]{1,2}", str(feature)):
                raise ValueError("invalid inventory feature")
            records.append(f'$cp{ident:02d}-{int(feature):02d}-{_number(position, "position", 0, 255):03d}-'.encode())
    if value.get("scene_count", 0):
        raise ValueError("scene-bearing inventories require original raw records")
    return [BridgeRecord.from_raw(payload) for payload in records + [b"$upd01-"]]


def load_inventory(source):
    """Load BridgeInventory, LF-CR bytes/file, or saved raw/summary JSON.

    Original opaque records, identifiers, scene definitions and ordering survive
    raw-record loading. Summary-only input cannot recover an omitted opaque title.
    """
    if isinstance(source, BridgeInventory):
        inventory = deepcopy(source)
    else:
        if isinstance(source, (str, Path)):
            path = Path(source)
            if path.stat().st_size > MAX_SNAPSHOT_BYTES:
                raise ValueError("inventory exceeds the snapshot size limit")
            source = path.read_bytes()
        if isinstance(source, bytes):
            if len(source) > MAX_SNAPSHOT_BYTES:
                raise ValueError("inventory exceeds the snapshot size limit")
            if source.lstrip().startswith(b"{"):
                source = json.loads(source)
            else:
                framer = RecordFramer()
                records = framer.feed(source)
                if framer.pending:
                    raise ValueError("inventory contains an incomplete LF-CR record")
                source = parse_records(records)
        if isinstance(source, BridgeInventory):
            inventory = source
        elif isinstance(source, Mapping):
            if "records" in source:
                records = []
                for item in source["records"]:
                    if not isinstance(item, Mapping):
                        raise ValueError("saved records must be objects with raw_hex or payload_hex")
                    raw = item.get("raw_hex", item.get("payload_hex"))
                    if not isinstance(raw, str):
                        raise ValueError("saved records require raw_hex or payload_hex")
                    records.append(BridgeRecord.from_raw(bytes.fromhex(raw)))
                inventory = parse_records(records)
            else:
                inventory = parse_records(_summary_records(source))
        else:
            raise ValueError("unsupported inventory source")
    payloads = [record.payload for record in inventory.records]
    if (not inventory.update_complete or not inventory.update_started
            or payloads.count(b"$upd00-") != 1 or payloads.count(b"$upd01-") != 1
            or payloads[-1] != b"$upd01-"
            or sum(len(p) + 2 for p in payloads) > MAX_SNAPSHOT_BYTES
            or any(RECORD_DELIMITER in p or len(p) > 65536 for p in payloads)):
        raise ValueError("inventory must contain one bounded complete snapshot")
    if any(record.kind in ("action", "done", "ack", "error") for record in inventory.records):
        raise ValueError("inventory contains runtime responses instead of a pure snapshot")
    for shade in inventory.shades.values():
        if shade.room_id not in inventory.rooms or not shade.name:
            raise ValueError("inventory has an undefined shade or room")
        if any(not 0 <= value <= 255 for value in shade.positions.values()):
            raise ValueError("inventory position is out of range")
    return inventory


_Positions = InventoryStore  # Compatibility for callers of the former overlay.


class _Commands:
    """Bounded streaming grammar for both observed iOS and APK request forms.

    Names count UTF-16 code units, but arrive as UTF-8 bytes. Position requests
    with three value digits can omit their final hyphen. Room requests wait for
    the complete 0-/00- suffix, or a following command boundary for the old
    short form; a TCP packet boundary must never prematurely finish that suffix.
    """

    _simple = (b"$dat", b"$dmy", b"$rls")
    _named = {b"$ar": (2, 2), b"$as": (2, 2),
              b"$mer": (2, 2, 2), b"$mes": (2, 2, 2)}
    _tokens = _simple + tuple(_named) + (b"$rr", b"$rs", b"$rsc", b"$pss", b"$psr",
                                         b"$sdt", b"$stm", b"$chksy")

    def __init__(self):
        self.pending = bytearray()
        self.optional_hyphen = False
        self.after_command = False
        self.padding = 0

    @staticmethod
    def _numbers(data, at, widths):
        values = []
        for width in widths:
            first = at
            while at < len(data) and 48 <= data[at] <= 57:
                at += 1
                if at - first > width:
                    raise ValueError("numeric field is too long")
            if at == len(data):
                return None
            if at == first or data[at] != 45:
                raise ValueError("numeric field requires a hyphen")
            values.append(int(data[first:at]))
            at += 1
        return values, at

    @staticmethod
    def _name_end(data, at, units):
        if not 1 <= units <= MAX_NAME_UTF16_UNITS:
            raise ValueError("name length must be within 1..25 UTF-16 units")
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        seen = 0
        for index in range(at, len(data)):
            try:
                character = decoder.decode(bytes((data[index],)), final=False)
            except UnicodeDecodeError as exc:
                raise ValueError("name is not valid UTF-8") from exc
            if character:
                seen += 2 if ord(character) > 0xffff else 1
                if seen > units:
                    raise ValueError("name length splits a Unicode character")
                if seen == units:
                    return index + 1
        return None

    def _parse(self, data, token):
        if token in self._simple:
            return len(token), token, True
        if token in self._named:
            header = self._numbers(data, len(token), self._named[token])
            if header is None:
                return None
            fields, at = header
            end = self._name_end(data, at, fields[-1])
            return None if end is None else (end, bytes(data[:end]), False)
        if token in (b"$rr", b"$rs", b"$rsc"):
            header = self._numbers(data, len(token), (2,))
            if header is None:
                return None
            fields, end = header
            return end, token + f"{fields[0]:02d}-".encode(), False
        if token in (b"$sdt", b"$stm", b"$chksy"):
            if token == b"$sdt":
                pattern = (b"$sdt00-00-0-0000-" if len(data) > 11 and data[11] == 45
                           else b"$sdt00-00-00-0000-")
            else:
                pattern = b"$stm00-00-00-" if token == b"$stm" else b"$chksy0000-"
            if any(not 48 <= value <= 57 if pattern[i] == 48 else value != pattern[i]
                   for i, value in enumerate(data[:len(pattern)])):
                raise ValueError("malformed clock command")
            return None if len(data) < len(pattern) else (len(pattern), bytes(data[:len(pattern)]), False)
        header = self._numbers(data, len(token), (2, 2))
        if header is None:
            return None
        fields, at = header
        first = at
        while at < len(data) and 48 <= data[at] <= 57:
            at += 1
            if at - first > 3:
                raise ValueError("position field is too long")
        if at == first:
            if at == len(data):
                return None
            raise ValueError("position must be decimal")
        normalized = token + f"{fields[0]:02d}-{fields[1]:02d}-{int(data[first:at]):03d}-".encode()
        if at == len(data):
            if token == b"$pss" and at - first == 3:
                return at, normalized, True
            return None
        if data[at] in (36, 10, 13):
            return at, normalized, False
        if data[at] != 45:
            raise ValueError("invalid position ending")
        at += 1
        if token == b"$pss":
            return at, normalized, False
        if at == len(data):
            return None
        if data[at] in (36, 10, 13):
            return at, normalized, False
        tail = self._numbers(data, at, (2,))
        if tail is None:
            return None
        values, end = tail
        if values != [0]:
            raise ValueError("unsupported room command suffix")
        return end, normalized + b"00-", False

    def feed(self, data):
        self.pending.extend(data)
        if len(self.pending) > 4096:
            raise ValueError("command buffer exceeded")
        commands = []
        while self.pending:
            if self.pending[0] in (10, 13):
                if not self.after_command or self.padding >= 2:
                    raise ValueError("unexpected request delimiter")
                self.padding += 1
                del self.pending[0]
                continue
            if self.optional_hyphen and self.pending[0] == 45:
                self.optional_hyphen = False
                del self.pending[0]
                continue
            self.optional_hyphen = False
            data = bytes(self.pending)
            tokens = [token for token in self._tokens if data.startswith(token)]
            if not tokens:
                if any(token.startswith(data) for token in self._tokens):
                    break
                raise ValueError("unsupported command")
            token = max(tokens, key=len)
            if data == token and any(other.startswith(token) and other != token for other in self._tokens):
                break
            parsed = self._parse(data, token)
            if parsed is None:
                break
            length, command, optional = parsed
            del self.pending[:length]
            commands.append(command)
            self.optional_hyphen = optional
            self.after_command = True
            self.padding = 0
        return commands


class _Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.send_lock = threading.Lock()
        self.disconnected = threading.Event()
        self.sync_state_lock = threading.Lock()
        self.sync_running = False
        self.sync_worker = None
        self.staged = OrderedDict()
        self.staged_jog = None
        self.request.settimeout(.25)
        self.connection_id = self.server.register(self)

    def clear_staged(self):
        self.staged.clear()
        self.staged_jog = None

    def send(self, *payloads):
        wire = b"".join(str(self.connection_id).encode() + b" " + p + RECORD_DELIMITER for p in payloads)
        with self.send_lock:
            if self.disconnected.is_set() or self.server.closing.is_set():
                raise OSError("LAN connection is closing")
            self.request.sendall(wire)
            self.server.journal("send", self.client_address, self.connection_id, wire)

    def sync_in_progress(self):
        with self.sync_state_lock:
            return self.sync_running

    def handle(self):
        if self.connection_id is None:
            return
        try:
            self.send(BANNER)
            parser, last_input, partial_since = _Commands(), time.monotonic(), None
            partial_was_busy = False
            while not self.server.closing.is_set():
                now = time.monotonic()
                if now - last_input > self.server.idle_timeout or (partial_since is not None and now - partial_since > self.server.command_timeout):
                    self.send(ERROR_LIMIT)
                    return
                try:
                    data = self.request.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    return
                self.server.journal("receive", self.client_address, self.connection_id, data)
                last_input = time.monotonic()
                sync_was_running = self.sync_in_progress()
                inherited_busy = partial_was_busy
                try:
                    commands = parser.feed(data)
                except ValueError:
                    self.clear_staged()
                    self.send(ERROR_UNSUPPORTED)
                    return
                partial_since = (last_input if commands else partial_since or last_input) if parser.pending else None
                # Only the first completed command can contain a prior chunk's
                # partial input. Remember its busy provenance even if Sync ended
                # before this chunk arrived; new following commands are distinct.
                partial_was_busy = bool(parser.pending) and (
                    sync_was_running or (inherited_busy and not commands))
                for index, command in enumerate(commands):
                    if self.server.closing.is_set():
                        return
                    if not self.server.take_rate(self.client_address[0]):
                        self.clear_staged()
                        self.send(ERROR_LIMIT)
                        return
                    if command == b"$dmy":
                        self.send(b"$ack")
                    elif sync_was_running or (index == 0 and inherited_busy) or self.sync_in_progress():
                        self.clear_staged()
                        self.send(ERROR_BUSY)
                    elif command == b"$dat":
                        self.send(*self.server.positions.snapshot())
                    elif command == b"$rls":
                        self.release()
                    elif command.startswith((b"$sdt", b"$stm", b"$chksy")):
                        self.clock_command(command)
                    elif command.startswith(b"$rsc"):
                        sync_was_running = self.sync(command)
                        if sync_was_running and parser.pending:
                            # A trailing fragment coalesced with this accepted
                            # Sync must not become a delayed second action either.
                            partial_was_busy = True
                    elif command.startswith((b"$ar", b"$as", b"$mer", b"$mes", b"$rr", b"$rs")):
                        self.mutate(command)
                    else:
                        self.stage(command)
        except (OSError, TimeoutError):
            pass

    def clock_command(self, command):
        try:
            self.server.service.mutate_inventory(lambda store: store.set_virtual_clock(command))
        except BridgeError as exc:
            self.send(ERROR_BUSY if exc.code == "busy" else ERROR_BACKEND)
            return
        except ValueError:
            self.send(ERROR_CLOCK)
            return
        except (OSError, RuntimeError):
            self.send(ERROR_BACKEND)
            return
        self.send(CHECK_YEAR_REPLY if command.startswith(b"$chksy") else b"$done")

    def mutate(self, command):
        """Commit one metadata edit; no inventory write grants an RF target."""
        self.clear_staged()

        def require_slot(store, room, exclude=None):
            occupied = {shade.group_field for shade in store.inventory.shades.values()
                        if shade.room_id == room and shade.id != exclude}
            if all(group in occupied for group in range(1, 9)):
                raise _RoomFullError("all eight shade slots are occupied")

        def change(store):
            if command.startswith(b"$ar"):
                product, _, raw_name = command[3:].split(b"-", 2)
                product = validate_product_code(int(product))
                used = {bytes.fromhex(room.rf_identifier[2:]) for room in store.inventory.rooms.values()}
                for _ in range(256):
                    identity = secrets.token_bytes(2)
                    if identity not in used and identity not in (b"\x00\x00", b"\xff\xff"):
                        break
                else:
                    raise ValueError("could not allocate a unique room identity")
                room = store.create_room(product, raw_name.decode("utf-8"), identity)
                return [f"$cr{room.id:02d}-{room.product_type:02d}-{room.rf_identifier}-".encode()
                        + room.name.encode("utf-8")]
            if command.startswith(b"$as"):
                room, _, raw_name = command[3:].split(b"-", 2)
                require_slot(store, int(room))
                shade = store.create_shade(int(room), raw_name.decode("utf-8"))
                return [f"$cs{shade.id:02d}-{shade.room_id:02d}-{shade.group_field:02d}-".encode()
                        + shade.name.encode("utf-8")]
            if command.startswith(b"$mer"):
                room, product, _, raw_name = command[4:].split(b"-", 3)
                store.update_room(int(room), product_type=validate_product_code(int(product)),
                                  name=raw_name.decode("utf-8"))
                return []  # APK edit callers do not read an acknowledgement.
            if command.startswith(b"$mes"):
                shade, room, _, raw_name = command[4:].split(b"-", 3)
                current = store.inventory.shades.get(int(shade))
                if current is not None and current.room_id != int(room):
                    require_slot(store, int(room), exclude=current.id)
                store.update_shade(int(shade), room_id=int(room), name=raw_name.decode("utf-8"))
                return []
            identifier = int(command[3:-1])
            inventory = store.inventory
            if command.startswith(b"$rr"):
                children = {shade.id for shade in inventory.shades.values() if shade.room_id == identifier}
                remaining = set(inventory.shades) - children
                if (any(room > identifier for room in inventory.rooms)
                        or children and remaining and min(children) < max(remaining)):
                    raise ValueError("deletion would create IDs incompatible with the app")
                # Local metadata cascade only. RF unpairing and rewriting opaque
                # scene references are not inferred from the client grammar.
                store.delete_room(identifier, cascade=True)
            else:
                if any(shade > identifier for shade in inventory.shades):
                    raise ValueError("deletion would create IDs incompatible with the app")
                store.delete_shade(identifier)
            return store.snapshot()

        try:
            response = self.server.service.mutate_inventory(change)
        except BridgeError as exc:
            self.send(ERROR_BUSY if exc.code == "busy" else ERROR_BACKEND)
            return
        except _RoomFullError:
            self.send(ERROR_ROOM_FULL)
            return
        except (ValueError, UnicodeError):
            self.send(ERROR_TARGET)
            return
        except (OSError, RuntimeError):
            self.send(ERROR_BACKEND)
            return
        if response:
            self.send(*response)

    def stage(self, command):
        if self.staged_jog is not None:
            # Never let an additional stage replace/extend a pending Jog or
            # turn it into a mixed position/Jog batch.
            self.clear_staged()
            self.send(ERROR_STAGE)
            return
        immediate = command.startswith(b"$psr") and command.endswith(b"-00-")
        if immediate:
            command = command[:-3]
            self.clear_staged()
        match = _STAGE.fullmatch(command)
        identifier, feature, position = map(int, match.groups())
        inventory = self.server.positions.inventory
        if feature == 12:
            if self.staged:
                self.clear_staged()
                self.send(ERROR_STAGE)
                return
            target = self.server.service.config.shades.get(identifier)
            if (not command.startswith(b"$pss") or position != 0 or target is None
                    or not target.jog_enabled or identifier not in inventory.shades
                    or self.server.service.jog_backend is None):
                self.clear_staged()
                self.send(ERROR_TARGET)
                return
            self.staged_jog = (identifier, target)
            self.send(b"$act01-00-", f"$cp{identifier:02d}-12-001-".encode(), b"$done")
            return
        shades = (sorted(shade.id for shade in inventory.shades.values() if shade.room_id == identifier)
                  if command.startswith(b"$psr") else [identifier])
        targets = [self.server.service.config.shades.get(shade) for shade in shades]
        if (feature != 4 or position > 255 or not shades
                or any(target is None or not target.position_enabled for target in targets)
                or any(shade not in inventory.shades for shade in shades)
                or self.server.service.position_backend is None):
            self.clear_staged()
            self.send(ERROR_TARGET)
            return
        if len(set(self.staged).union(shades)) > self.server.max_staged:
            self.clear_staged()
            self.send(ERROR_LIMIT)
            return
        self.staged.update((shade, position) for shade in shades)
        self.send(b"$act01-00-", *(f"$cp{shade:02d}-04-{position:03d}-".encode() for shade in shades), b"$done")
        if immediate:
            self.release()

    def sync(self, command):
        # Sync is immediate and independent of staged position/release state.
        # Discard any old stage so a later release cannot send a stale action.
        self.clear_staged()
        shade = int(_SYNC.fullmatch(command)[1])
        target = self.server.service.config.shades.get(shade)
        if (target is None or not target.sync_enabled
                or shade not in self.server.positions.inventory.shades
                or self.server.service.sync_backend is None):
            self.send(ERROR_TARGET)
            return False
        if not self.server.release_lock.acquire(blocking=False):
            self.send(ERROR_BUSY)
            return False
        try:
            if self.server.closing.is_set() or self.disconnected.is_set():
                self.server.release_lock.release()
                return False
            # The preceding worker has completed its action and notifications.
            # Join before replacing ownership; never accumulate detached jobs.
            if self.sync_worker is not None:
                self.sync_worker.join()
            with self.sync_state_lock:
                self.sync_running = True
            self.sync_worker = threading.Thread(target=self.run_sync, args=(shade, target.room_id),
                                                name="platinum-lan-sync", daemon=False)
            self.sync_worker.start()
        except BaseException as exc:
            if self.sync_worker is not None and self.sync_worker.is_alive():
                raise  # A started worker retains the lock and action ownership.
            self.sync_worker = None
            with self.sync_state_lock:
                self.sync_running = False
            self.server.release_lock.release()
            if isinstance(exc, Exception):
                self.send(ERROR_BACKEND)
                return False
            raise
        return True

    def run_sync(self, shade, room):
        # This is the sole owner of release_lock after a successful start.
        # A disconnected client cannot cancel/retry a partially submitted RF
        # action. The finite backend retains ownership through its cleanup.
        terminal, broadcast = None, False
        try:
            if self.server.closing.is_set() or self.disconnected.is_set():
                return
            try:
                self.server.service.dispatch_sync(
                    {"shade": shade, "request_id": "lan-sync-" + uuid4().hex},
                    on_started=lambda: self.send(b"$act01-00-", f"$cp{shade:02d}-01-000-".encode()),
                    on_transmit_submitted=lambda: self.server.broadcast(
                        f"$act02-{room:02d}-".encode()))
            except BridgeError as exc:
                terminal = ERROR_BUSY if exc.code == "busy" else ERROR_BACKEND
            except (OSError, ValueError, RuntimeError):
                terminal = ERROR_BACKEND
            else:
                terminal, broadcast = b"$act00-00-", True
        finally:
            # Complete the terminal notification and state transition together.
            # A client acting on that notification cannot observe stale busy
            # state. send_lock still serializes these records with keepalives.
            with self.sync_state_lock:
                try:
                    if terminal is not None:
                        if broadcast:
                            self.server.broadcast(terminal)
                        else:
                            self.send(terminal)
                except OSError:
                    pass
                finally:
                    self.server.release_lock.release()
                    self.sync_running = False

    def release(self):
        batch = list(self.staged.items())
        jog = self.staged_jog
        self.clear_staged()  # Consume before dispatch, even on failure/disconnect.
        if (not batch and jog is None) or (batch and jog is not None):
            self.send(ERROR_STAGE)
            return
        if not self.server.release_lock.acquire(blocking=False):
            self.send(ERROR_BUSY)
            return
        try:
            if self.server.closing.is_set():
                return
            try:
                # Keep immutable targets before dispatch releases the shared RF
                # lock; another client's metadata edit may then remove them.
                if jog is not None:
                    shade, staged_target = jog
                    target = self.server.service.config.shades.get(shade)
                    if target != staged_target or not target.jog_enabled:
                        self.send(ERROR_TARGET)
                        return
                    rooms = (target.room_id,)
                    self.server.service.dispatch_jog({"shade": shade, "request_id": "lan-jog-" + uuid4().hex})
                else:
                    targets = [self.server.service.config.shades.get(shade) for shade, _ in batch]
                    if any(target is None for target in targets):
                        self.send(ERROR_TARGET)
                        return
                    rooms = dict.fromkeys(target.room_id for target in targets)
                    self.server.service.dispatch_positions([
                        {"shade": shade, "position": position, "request_id": "lan-" + uuid4().hex}
                        for shade, position in batch])
            except BridgeError as exc:
                self.send(ERROR_BUSY if exc.code == "busy" else ERROR_BACKEND)
                return
            except (OSError, ValueError, RuntimeError):
                self.send(ERROR_BACKEND)
                return
            for room in rooms:
                self.server.broadcast(f"$act02-{room:02d}-".encode())
            self.server.broadcast(b"$act00-00-")
        finally:
            self.server.release_lock.release()

    def finish(self):
        with self.send_lock:
            self.disconnected.set()
        self.clear_staged()
        self.server.unregister(self)
        if self.sync_worker is not None:
            # The non-daemon request owner and its connection slot remain held
            # until this one finite action ends; server_close() joins that owner.
            self.sync_worker.join()


class PlatinumLANServer(socketserver.ThreadingTCPServer):
    """TCP service with 1–9 active clients (default 8) and recycled wire IDs."""

    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8

    def __init__(self, service, inventory_source, host="127.0.0.1", port=522, *,
                 allowed_clients=None, state_path=None, max_connections=8, idle_timeout=300,
                 command_timeout=5, commands_per_minute=120, max_staged=16, wire_journal=None):
        if not isinstance(service, BridgeService):
            raise ValueError("service must be a BridgeService")
        address = ipaddress.ip_address(host)
        _number(port, "port", 0, 65535)
        self.address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        if allowed_clients is None:
            if not address.is_loopback:
                raise ValueError("non-loopback binding requires an explicit local client allowlist")
            allowed_clients = ("127.0.0.0/8", "::1/128")
        if isinstance(allowed_clients, (str, bytes)):
            raise ValueError("allowed_clients must be a sequence of local CIDRs")
        self.allowed_clients = tuple(ipaddress.ip_network(value, strict=False) for value in allowed_clients)
        if not self.allowed_clients or any(not any(net.version == local.version and net.subnet_of(local)
                                                  for local in _LOCAL_NETWORKS) for net in self.allowed_clients):
            raise ValueError("client networks must be explicit private/local CIDRs")
        self.max_connections = _number(max_connections, "maximum connections", 1, 9)
        self.commands_per_minute = _number(commands_per_minute, "command rate", 1, 10000)
        self.max_staged = _number(max_staged, "maximum staged targets", 1, 100)
        for name, value in (("idle_timeout", idle_timeout), ("command_timeout", command_timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .05 <= value <= 3600:
                raise ValueError(f"{name} must be finite and within 0.05..3600 seconds")
            setattr(self, name, value)
        if state_path is not None and isinstance(inventory_source, (str, Path)) and Path(state_path).resolve() == Path(inventory_source).resolve():
            raise ValueError("position state must not replace the source inventory")
        self.service = service
        if wire_journal is not None and not callable(wire_journal):
            raise ValueError("wire_journal must be callable")
        self.wire_journal = wire_journal
        inventory = load_inventory(inventory_source)
        for shade, target in service.config.shades.items():
            if shade in inventory.shades:
                defined = inventory.shades[shade]
                room = inventory.rooms[defined.room_id]
                if (defined.room_id != target.room_id
                        or bytes.fromhex(room.rf_identifier[2:]) != target.room_rf_id
                        or not 1 <= defined.group_field <= 8
                        or target.mask != 1 << (defined.group_field - 1)):
                    raise ValueError("configured shade target does not match the source inventory")
        self.positions = _Positions(inventory, state_path)
        self.closing, self.release_lock = threading.Event(), threading.Lock()
        self.clients_lock, self.clients = threading.Lock(), set()
        self.rate_lock, self.rates = threading.Lock(), {}
        # Legacy clients parse a single digit and one space as the wire prefix.
        # Reuse released IDs while keeping concurrent connections distinct.
        self.available_connection_ids = set(range(1, 10))
        self.slots = threading.BoundedSemaphore(self.max_connections)
        self._unsubscribe = None
        self._inventory_attached = False
        super().__init__((host, port), _Handler)
        try:
            service.attach_inventory(self.positions)
            self._inventory_attached = True
            self._unsubscribe = service.add_position_listener(self._position_submitted)
        except BaseException:
            self.server_close()
            raise

    def journal(self, direction, peer, connection_id, data):
        if self.wire_journal is not None:
            try:
                self.wire_journal(direction, peer, connection_id, data)
            except Exception:
                # A full disk or diagnostic failure must never change an
                # already submitted command into a retryable RF operation.
                logging.getLogger(__name__).error("TCP protocol journal write failed")

    def _position_submitted(self, command, receipt):
        if receipt["status"] in ("submitted", "sent"):
            self.positions.submitted(command.shade, command.position)
        self.broadcast(f"$cp{command.shade:02d}-04-{command.position:03d}-".encode())

    def verify_request(self, request, client_address):
        address = ipaddress.ip_address(client_address[0])
        return not self.closing.is_set() and any(address in network for network in self.allowed_clients)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def register(self, handler):
        with self.clients_lock:
            if self.closing.is_set() or not self.available_connection_ids:
                return None
            ident = min(self.available_connection_ids)
            self.available_connection_ids.remove(ident)
            self.clients.add(handler)
            return ident

    def unregister(self, handler):
        with self.clients_lock:
            if handler in self.clients:
                self.clients.remove(handler)
                self.available_connection_ids.add(handler.connection_id)

    def take_rate(self, address):
        now = time.monotonic()
        with self.rate_lock:
            self.rates = {key: stamps for key, stamps in self.rates.items() if stamps and stamps[-1] > now - 60}
            if address not in self.rates and len(self.rates) >= 1024:
                return False
            stamps = self.rates.setdefault(address, deque())
            while stamps and stamps[0] <= now - 60:
                stamps.popleft()
            if len(stamps) >= self.commands_per_minute:
                return False
            stamps.append(now)
            return True

    def broadcast(self, *payloads):
        with self.clients_lock:
            clients = tuple(self.clients)
        for client in clients:
            try:
                client.send(*payloads)
            except OSError:
                try:
                    client.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _stop_clients(self):
        self.closing.set()
        with self.clients_lock:
            clients = tuple(self.clients)
        for client in clients:
            try:
                client.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def shutdown(self):
        self._stop_clients()
        super().shutdown()

    def server_close(self):
        self._stop_clients()
        super().server_close()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._inventory_attached:
            self.service.detach_inventory(self.positions)
            self._inventory_attached = False


def make_lan_server(service, inventory_source, host="127.0.0.1", port=522, **options):
    """Construct the bounded TCP server; serving remains under the caller's control."""
    return PlatinumLANServer(service, inventory_source, host, port, **options)
