# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Binary-safe parser and read-only client for the Platinum bridge LAN API.

The only network operation exposed here is ``$dat``, the read-only inventory
query observed on the lab bridge.  Movement and configuration writes are kept
out of this module until they can be tested deliberately on recoverable
hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import socket
import time
from typing import Any, Iterable


DEFAULT_PORT = 522
RECORD_DELIMITER = b"\n\r"
GET_DATA = b"$dat"
END_OF_UPDATE = b"$upd01-"
MAX_SNAPSHOT_BYTES = 1 << 20

_PREFIX_RE = re.compile(rb"^([0-9]+) (.*)$", re.DOTALL)
_BANNER_RE = re.compile(rb"^HunterDouglas Shade Controller$")
_ROOM_RE = re.compile(rb"^\$cr([0-9]{2})-([0-9]{2})-(0x[0-9A-Fa-f]{4})-(.*)$", re.DOTALL)
_SHADE_RE = re.compile(rb"^\$cs([0-9]{2})-([0-9]{2})-([0-9]{2})-(.*)$", re.DOTALL)
_POSITION_RE = re.compile(rb"^\$cp([0-9]{2})-([0-9]{2})-([0-9]{3})-$")
_SCENE_RE = re.compile(rb"^\$cm([0-9]{2})-(.*)$", re.DOTALL)
_SCENE_LINK_RE = re.compile(rb"^\$cq([0-9]{2})-([0-9]{2})-([0-9]{2})-$")
_SCENE_ROOM_RE = re.compile(
    rb"^\$cx([0-9]{2})-([0-9]{2})-([0-9]{2})-([0-9]{3})(?:-([0-9]{2}))?-$"
)
_MAC_RE = re.compile(rb"^\$MAC(?:0x)?([0-9A-Fa-f]{12})-$")
_LED_RE = re.compile(rb"^\$LEDl([0-9]{1,3})-$")
_UPDATE_RE = re.compile(rb"^\$upd([0-9]{2})-$")
_FIRMWARE_RE = re.compile(rb"^\$firm([0-9]{2})-(.*)$", re.DOTALL)


class ProtocolError(RuntimeError):
    """Raised when a bridge response violates required framing or grammar."""


class SnapshotTimeout(TimeoutError):
    """Raised when a complete ``$dat`` snapshot is not received in time."""


def _text(value: bytes) -> str:
    """Decode a human label without making the whole protocol UTF-8-only."""

    return value.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class BridgeRecord:
    """One LF-CR-delimited server record.

    ``raw`` contains the record before prefix handling. ``payload`` has an
    optional decimal connection prefix removed. Neither includes LF-CR.
    """

    raw: bytes
    payload: bytes
    connection_id: int | None = None

    @classmethod
    def from_raw(cls, raw: bytes) -> "BridgeRecord":
        match = _PREFIX_RE.fullmatch(raw)
        if match is None:
            return cls(raw=raw, payload=raw)
        return cls(
            raw=raw,
            payload=match.group(2),
            connection_id=int(match.group(1)),
        )

    @property
    def kind(self) -> str:
        """Return a stable, best-effort record category."""

        payload = self.payload
        if _BANNER_RE.fullmatch(payload):
            return "banner"
        for prefix, name in (
            (b"$MAC", "mac"),
            (b"$LEDl", "led"),
            (b"$upd", "update"),
            (b"$reset", "reset"),
            (b"$set", "setting"),
            (b"$ctb", "title_aux"),
            (b"$ct", "title"),
            (b"$cr", "room"),
            (b"$cs", "shade"),
            (b"$cp", "position"),
            (b"$cm", "scene"),
            (b"$cq", "scene_link"),
            (b"$cx", "scene_room_position"),
            (b"$ca", "schedule"),
            (b"$firm", "firmware"),
            (b"$done", "done"),
            (b"$ack", "ack"),
            (b"$error", "error"),
            (b"$act", "action"),
        ):
            if payload.startswith(prefix):
                return name
        if re.match(rb"^[0-9]{4}-HD gateway ", payload):
            return "firmware_text"
        return "unknown"


class RecordFramer:
    """Incrementally split arbitrary TCP chunks on the bridge's LF-CR marker."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def pending(self) -> bytes:
        return bytes(self._buffer)

    def feed(self, chunk: bytes) -> list[BridgeRecord]:
        self._buffer.extend(chunk)
        records: list[BridgeRecord] = []
        while True:
            marker = self._buffer.find(RECORD_DELIMITER)
            if marker < 0:
                break
            raw = bytes(self._buffer[:marker])
            del self._buffer[: marker + len(RECORD_DELIMITER)]
            records.append(BridgeRecord.from_raw(raw))
        return records


@dataclass
class Room:
    id: int
    product_type: int
    rf_identifier: str
    name: str


@dataclass
class Shade:
    id: int
    room_id: int
    group_field: int
    name: str
    positions: dict[int, int] = field(default_factory=dict)


@dataclass
class Scene:
    id: int
    name: str


@dataclass
class BridgeInventory:
    """Parsed ``$dat`` snapshot plus every raw record for future research."""

    banner: BridgeRecord | None = None
    firmware: str | None = None
    firmware_record_code: int | None = None
    mac: str | None = None
    led_level: int | None = None
    title_raw: bytes | None = None
    rooms: dict[int, Room] = field(default_factory=dict)
    shades: dict[int, Shade] = field(default_factory=dict)
    scenes: dict[int, Scene] = field(default_factory=dict)
    scene_links: list[dict[str, int]] = field(default_factory=list)
    scene_room_positions: list[dict[str, int | None]] = field(default_factory=list)
    unknown_records: list[BridgeRecord] = field(default_factory=list)
    records: list[BridgeRecord] = field(default_factory=list)
    update_started: bool = False
    update_complete: bool = False

    def ingest(self, record: BridgeRecord) -> None:
        self.records.append(record)
        payload = record.payload
        kind = record.kind

        if kind == "banner":
            self.banner = record
            return
        if kind == "firmware_text":
            self.firmware = _text(payload)
            return
        if kind == "firmware":
            match = _FIRMWARE_RE.fullmatch(payload)
            if match:
                self.firmware_record_code = int(match.group(1))
                self.firmware = _text(match.group(2))
            else:
                self.firmware = _text(payload)
            return

        match = _MAC_RE.fullmatch(payload)
        if match:
            self.mac = _text(match.group(1)).upper()
            return
        match = _LED_RE.fullmatch(payload)
        if match:
            self.led_level = int(match.group(1))
            return
        match = _UPDATE_RE.fullmatch(payload)
        if match:
            phase = int(match.group(1))
            self.update_started = self.update_started or phase == 0
            self.update_complete = phase == 1
            return
        if payload == b"$reset":
            return
        if kind == "setting" or kind == "title_aux":
            self.unknown_records.append(record)
            return
        if kind == "title":
            self.title_raw = payload[3:]
            return

        match = _ROOM_RE.fullmatch(payload)
        if match:
            room = Room(
                id=int(match.group(1)),
                product_type=int(match.group(2)),
                rf_identifier=_text(match.group(3)),
                name=_text(match.group(4)),
            )
            self.rooms[room.id] = room
            return
        match = _SHADE_RE.fullmatch(payload)
        if match:
            shade = Shade(
                id=int(match.group(1)),
                room_id=int(match.group(2)),
                group_field=int(match.group(3)),
                name=_text(match.group(4)),
            )
            prior = self.shades.get(shade.id)
            if prior is not None:
                shade.positions.update(prior.positions)
            self.shades[shade.id] = shade
            return
        match = _POSITION_RE.fullmatch(payload)
        if match:
            shade_id = int(match.group(1))
            feature = int(match.group(2))
            value = int(match.group(3))
            shade = self.shades.get(shade_id)
            if shade is None:
                shade = Shade(shade_id, -1, 0, "")
                self.shades[shade_id] = shade
            shade.positions[feature] = value
            return
        match = _SCENE_RE.fullmatch(payload)
        if match:
            scene = Scene(int(match.group(1)), _text(match.group(2)))
            self.scenes[scene.id] = scene
            return
        match = _SCENE_LINK_RE.fullmatch(payload)
        if match:
            self.scene_links.append(
                {
                    "scene_id": int(match.group(1)),
                    "shade_id": int(match.group(2)),
                    "linked": int(match.group(3)),
                }
            )
            return
        match = _SCENE_ROOM_RE.fullmatch(payload)
        if match:
            self.scene_room_positions.append(
                {
                    "scene_id": int(match.group(1)),
                    "room_id": int(match.group(2)),
                    "feature": int(match.group(3)),
                    "position": int(match.group(4)),
                    "extra": int(match.group(5)) if match.group(5) else None,
                }
            )
            return

        self.unknown_records.append(record)

    def public_summary(
        self,
        *,
        include_names: bool = False,
        include_mac: bool = False,
    ) -> dict[str, Any]:
        """Return JSON-ready data, redacting household identifiers by default."""

        rooms: list[dict[str, Any]] = []
        for room in sorted(self.rooms.values(), key=lambda item: item.id):
            item: dict[str, Any] = {
                "id": room.id,
                "product_type": room.product_type,
                "rf_identifier": "<redacted>",
            }
            if include_names:
                item["name"] = room.name
                item["rf_identifier"] = room.rf_identifier
            rooms.append(item)

        shades: list[dict[str, Any]] = []
        for shade in sorted(self.shades.values(), key=lambda item: item.id):
            item = {
                "id": shade.id,
                "room_id": shade.room_id,
                "group_field": shade.group_field,
                "positions": dict(sorted(shade.positions.items())),
            }
            if include_names:
                item["name"] = shade.name
            shades.append(item)

        return {
            "firmware": self.firmware,
            "firmware_record_code": self.firmware_record_code,
            "mac": self.mac if include_mac else ("<redacted>" if self.mac else None),
            "led_level": self.led_level,
            "title": "<opaque/redacted>" if self.title_raw is not None else None,
            "room_count": len(self.rooms),
            "shade_count": len(self.shades),
            "scene_count": len(self.scenes),
            "rooms": rooms,
            "shades": shades,
            "update_complete": self.update_complete,
            "unknown_record_count": len(self.unknown_records),
        }


def parse_records(records: Iterable[BridgeRecord]) -> BridgeInventory:
    inventory = BridgeInventory()
    for record in records:
        inventory.ingest(record)
    return inventory


def _receive_until_record(
    sock: socket.socket,
    framer: RecordFramer,
    *,
    deadline: float,
    wanted: bytes | None = None,
    maximum: int = MAX_SNAPSHOT_BYTES,
) -> list[BridgeRecord]:
    records: list[BridgeRecord] = []
    received = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SnapshotTimeout("timed out before the expected bridge record arrived")
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(4096)
        except socket.timeout as exc:
            raise SnapshotTimeout("timed out while reading the bridge") from exc
        if not chunk:
            raise ProtocolError("bridge closed the connection before completing the response")
        received += len(chunk)
        if received > maximum:
            raise ProtocolError(f"bridge response exceeded the {maximum}-byte safety limit")
        new_records = framer.feed(chunk)
        records.extend(new_records)

        # ``feed`` drains every complete record in this TCP chunk.  Decide
        # whether to return only after preserving the whole batch so records
        # coalesced after the marker cannot be silently discarded.
        if wanted is None and new_records:
            return records
        if wanted is not None and any(record.payload == wanted for record in new_records):
            return records


def query_inventory(
    host: str,
    *,
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
) -> BridgeInventory:
    """Connect, consume the banner, send bare ``$dat``, and parse the snapshot.

    This function intentionally exposes no arbitrary-command parameter.
    """

    if not host:
        raise ValueError("host must not be empty")
    if not (1 <= port <= 65535):
        raise ValueError("port must be between 1 and 65535")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    deadline = time.monotonic() + timeout
    framer = RecordFramer()
    inventory = BridgeInventory()

    with socket.create_connection((host, port), timeout=timeout) as sock:
        banner_records = _receive_until_record(sock, framer, deadline=deadline)
        for record in banner_records:
            inventory.ingest(record)
        banner = next((record for record in banner_records if record.kind == "banner"), None)
        if banner is None:
            raise ProtocolError(
                f"unexpected bridge startup records: {[record.raw for record in banner_records]!r}"
            )

        sock.sendall(GET_DATA)
        snapshot_records = _receive_until_record(
            sock,
            framer,
            deadline=deadline,
            wanted=END_OF_UPDATE,
        )
        for record in snapshot_records:
            inventory.ingest(record)

    if not inventory.update_complete:
        raise ProtocolError("snapshot did not end with $upd01-")
    return inventory
