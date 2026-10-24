# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One bounded, deliberate primary-position transaction on an original bridge.

Wire facts are documented in docs/lan-protocol.md. The caller supplies a recent
complete inventory from this same bridge. Stage and trigger are separate so a
receiver can be armed between the command acknowledgement and RF release.
No retry, stop, configuration write, or physical-position confirmation is
implied. Closing a staged session never sends release and does not establish
that the bridge discarded its queued operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from operator import index
import re
import socket
import time

from .lan import BridgeInventory, BridgeRecord, DEFAULT_PORT, ProtocolError, RecordFramer


MAX_CONTROL_BYTES = 65_536
MAX_CONTROL_RECORDS = 2_048
DONE = b"$done"
RELEASE = b"$rls"
ACTION_END = b"$act00-00-"
_DEFINITION = re.compile(rb"^\$cs([0-9]{2})-([0-9]{2})-([0-9]{2})-(.*)$", re.DOTALL)
_POSITION = re.compile(rb"^\$cp([0-9]{2})-([0-9]{2})-([0-9]{3})-$")
_ACTION = re.compile(rb"^\$act([0-9]{2})-([0-9]{2})-(.*)$", re.DOTALL)
_ERROR = re.compile(rb"^\$error([0-9]{2})-$")


class ControlTimeout(TimeoutError):
    """The requested command-layer marker was not observed before the deadline."""


class TransactionStateError(RuntimeError):
    """An operation would repeat or bypass the transaction's allowed order."""


class BridgeCommandError(ProtocolError):
    """The bridge returned an error record; its proprietary code is retained."""

    def __init__(self, code: int | None) -> None:
        self.code = code
        super().__init__("bridge reported a command error" + (f" (code {code:02d})" if code is not None else ""))


def _integer(value, name: str, low: int, high: int) -> int:
    try:
        result = index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or not low <= result <= high:
        raise ValueError(f"{name} must be within {low}..{high}")
    return result


def encode_position(inventory: BridgeInventory, shade_id: int, position: int) -> bytes:
    """Encode feature 04 for one shade explicitly defined in a complete snapshot.

    A position-only placeholder created by the inventory parser is insufficient:
    a real $cs definition must also be present. The endpoint associated with an
    inventory cannot be proven by this data type; the caller must use the same
    bridge from which the supplied inventory was obtained.
    """
    shade_id = _integer(shade_id, "shade ID", 0, 99)
    position = _integer(position, "position", 0, 255)
    if not isinstance(inventory, BridgeInventory) or not inventory.update_complete:
        raise ValueError("a complete bridge inventory is required")
    if inventory.banner is None or inventory.banner.kind != "banner":
        raise ValueError("inventory must include a validated bridge banner")
    shade = inventory.shades.get(shade_id)
    defined = any((match := _DEFINITION.fullmatch(record.payload)) and int(match.group(1)) == shade_id
                  for record in inventory.records)
    if shade is None or shade.id != shade_id or not defined:
        raise ValueError("shade ID must identify a defined shade in the supplied inventory")
    return f"$pss{shade_id:02d}-04-{position:03d}-".encode("ascii")


@dataclass(frozen=True)
class ControlEvent:
    received_monotonic: float
    phase: str
    kind: str
    record: BridgeRecord = field(repr=False)
    preexisting_partial: bool = False
    shade_id: int | None = None
    feature: int | None = None
    position: int | None = None
    action_phase: int | None = None
    room_id: int | None = None
    error_code: int | None = None

    @classmethod
    def from_record(cls, record: BridgeRecord, *, phase: str, received_monotonic: float,
                    preexisting_partial: bool = False) -> "ControlEvent":
        fields = {}
        if match := _POSITION.fullmatch(record.payload):
            fields.update(shade_id=int(match.group(1)), feature=int(match.group(2)),
                          position=int(match.group(3)))
        elif match := _ACTION.fullmatch(record.payload):
            fields.update(action_phase=int(match.group(1)), room_id=int(match.group(2)))
        elif match := _ERROR.fullmatch(record.payload):
            fields["error_code"] = int(match.group(1))
        return cls(received_monotonic, phase, record.kind, record,
                   preexisting_partial=preexisting_partial, **fields)

    def as_dict(self, *, include_raw: bool = False) -> dict:
        """Raw bytes can include private names/IDs; they are excluded by default."""
        if not isinstance(include_raw, bool):
            raise ValueError("include_raw must be a boolean")
        result = {"received_monotonic": self.received_monotonic, "phase": self.phase,
                  "kind": self.kind, "preexisting_partial": self.preexisting_partial}
        for name in ("shade_id", "feature", "position", "action_phase", "room_id", "error_code"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        if include_raw:
            result.update(raw_hex=self.record.raw.hex(), payload_hex=self.record.payload.hex())
        return result


class PositionTransaction:
    """Context-managed, single-use staging and release on one TCP connection.

    Example::

        with PositionTransaction(host, inventory=inventory, shade_id=3,
                                 position=255) as transaction:
            transaction.stage()
            # Arm an independent RF recording here.
            receipt = transaction.trigger()

    timeout (0.01..30 seconds) bounds each connect/banner, stage, and trigger
    operation. No timeout causes an automatic retry. This class is intended for
    a single caller, not concurrent calls from multiple threads.
    """

    def __init__(self, host: str, *, inventory: BridgeInventory, shade_id: int,
                 position: int, port: int = DEFAULT_PORT, timeout: float = 10.0):
        if not isinstance(host, str) or not host or len(host) > 255 or any(c.isspace() or ord(c) < 32 for c in host):
            raise ValueError("host must be a nonempty address without whitespace")
        self._command = encode_position(inventory, shade_id, position)
        self._shade_id, self._position = int(shade_id), int(position)
        self.host, self.port = host, _integer(port, "port", 1, 65535)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout must be a finite number") from exc
        if isinstance(timeout, bool) or not math.isfinite(timeout_value) or not .01 <= timeout_value <= 30:
            raise ValueError("timeout must be within 0.01..30 seconds")
        self.timeout = timeout_value
        self.state = "new"
        self._socket = None
        self._framer = RecordFramer()
        self._events: list[ControlEvent] = []
        self._received_bytes = 0
        self._stage_acknowledged = False
        self._stage_attempted = False
        self._release_attempted = False
        self._release_sent = False
        self._action_end_observed = False

    @property
    def command(self) -> bytes:
        return self._command

    @property
    def shade_id(self) -> int:
        return self._shade_id

    @property
    def position(self) -> int:
        return self._position

    @property
    def events(self) -> tuple[ControlEvent, ...]:
        """Private record journal, including every record coalesced with a marker."""
        return tuple(self._events)

    @property
    def closed(self) -> bool:
        return self._socket is None

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControlTimeout("timed out before the expected command-layer marker")
        return remaining

    def _receive(self, phase: str, deadline: float, wanted: bytes | None) -> None:
        # A record begun before this operation cannot satisfy its completion.
        # Preserve it as evidence when its remaining bytes eventually arrive.
        preexisting = bool(self._framer.pending)
        while True:
            self._socket.settimeout(self._remaining(deadline))
            try:
                chunk = self._socket.recv(4096)
            except socket.timeout as exc:
                raise ControlTimeout(f"timed out waiting for the {phase} response") from exc
            if not chunk:
                raise ProtocolError(f"bridge closed before the {phase} response completed")
            self._received_bytes += len(chunk)
            if self._received_bytes > MAX_CONTROL_BYTES:
                raise ProtocolError("control response exceeded the byte limit")
            records = self._framer.feed(chunk)
            if len(self._events) + len(records) > MAX_CONTROL_RECORDS:
                raise ProtocolError("control response exceeded the record limit")
            matched = False
            errors = []
            received = time.monotonic()
            for record in records:
                event = ControlEvent.from_record(record, phase=phase,
                    received_monotonic=received, preexisting_partial=preexisting)
                self._events.append(event)
                if record.kind == "error":
                    errors.append(event.error_code)
                if not preexisting:
                    matched |= (record.kind == "banner" if wanted is None else record.payload == wanted)
                preexisting = False
            # Preserve every complete record in the batch before deciding.
            if errors:
                raise BridgeCommandError(errors[0])
            if phase == "banner" and records and not matched:
                raise ProtocolError("bridge startup did not contain the expected banner")
            if matched:
                return

    def _send(self, data: bytes, deadline: float) -> None:
        self._socket.settimeout(self._remaining(deadline))
        try:
            self._socket.sendall(data)
        except socket.timeout as exc:
            raise ControlTimeout("timed out writing the command; delivery is unknown") from exc

    def __enter__(self) -> "PositionTransaction":
        if self.state != "new":
            raise TransactionStateError("a transaction can only be opened once")
        deadline = time.monotonic() + self.timeout
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._receive("banner", deadline, None)
            self.state = "connected"
            return self
        except Exception:
            self.state = "failed"
            self.close()
            raise

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self.state not in ("completed", "failed"):
            self.state = "closed"

    def receipt(self) -> dict:
        return {"shade_id": self.shade_id, "feature": 4, "requested_position": self.position,
                "state": self.state, "stage_acknowledged": self._stage_acknowledged,
                "stage_attempted": self._stage_attempted, "release_attempted": self._release_attempted,
                "release_sent": self._release_sent, "action_end_observed": self._action_end_observed,
                "delivery": "unverified", "position_confirmed": False,
                "correlation_note": "Bridge records have no request IDs and can include other clients' activity.",
                "events": [event.as_dict() for event in self._events]}

    def stage(self) -> dict:
        if self.state != "connected" or self.closed:
            raise TransactionStateError("stage requires a connected, unstaged transaction")
        deadline = time.monotonic() + self.timeout
        try:
            self._stage_attempted = True
            self._send(self.command, deadline)
            self._receive("stage", deadline, DONE)
            self._stage_acknowledged = True
            self.state = "staged"
            return self.receipt()
        except Exception:
            self.state = "failed"
            self.close()
            raise

    def trigger(self) -> dict:
        if self.state != "staged" or self.closed:
            raise TransactionStateError("trigger requires one acknowledged staged position")
        deadline = time.monotonic() + self.timeout
        try:
            self._release_attempted = True
            self._send(RELEASE, deadline)
            self._release_sent = True
            self.state = "triggered"
            self._receive("trigger", deadline, ACTION_END)
            self._action_end_observed = True
            self.state = "completed"
            return self.receipt()
        except Exception:
            self.state = "failed"
            self.close()
            raise
