# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Independently developed models for legacy Platinum handheld remote RF messages.

This module builds and decodes the five-byte *payload* established by community
captures. It does not key a transmitter or claim the bridge-to-shade protocol
has been decoded. The optional ESB frame builder is an explicitly parameterized
capture-analysis aid because static-payload PCF bits still require IQ proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


REMOTE_CHANNELS = (33, 52, 71)
REMOTE_FREQUENCIES_HZ = tuple((2400 + channel) * 1_000_000 for channel in REMOTE_CHANNELS)
REMOTE_DATA_RATE = 2_000_000
REMOTE_ADDRESS = bytes.fromhex("e7e7e7")
REMOTE_PAYLOAD_LENGTH = 5
REMOTE_MODE_GROUP = 0x20

ACTION_CODES = {
    "release-up": 0x21,
    "release-down": 0x22,
    "up": 0xA1,
    "down": 0xA2,
}
ACTION_NAMES = {value: key for key, value in ACTION_CODES.items()}


def parse_remote_id(value: str | bytes | bytearray) -> bytes:
    if isinstance(value, str):
        cleaned = value.lower().removeprefix("0x").replace(":", "").replace("-", "")
        if len(cleaned) != 4:
            raise ValueError("remote ID must contain exactly two bytes (four hex digits)")
        try:
            result = bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError("remote ID must be hexadecimal") from exc
    else:
        result = bytes(value)
    if len(result) != 2:
        raise ValueError("remote ID must be exactly two bytes")
    return result


def groups_to_mask(groups: str | int | Iterable[int]) -> int:
    """Convert known groups 1..4, ``all``, or an explicit experimental mask."""

    if isinstance(groups, str):
        normalized = groups.strip().lower()
        if normalized == "all":
            return 0xFF
        if "," in normalized:
            return groups_to_mask(int(part.strip()) for part in normalized.split(","))
        if normalized.startswith("0x"):
            try:
                mask = int(normalized, 16)
            except ValueError as exc:
                raise ValueError("hexadecimal group mask is invalid") from exc
            if not 0 <= mask <= 0xFF:
                raise ValueError("group mask must fit in one byte")
            return mask
        try:
            groups = int(normalized, 10)
        except ValueError as exc:
            raise ValueError("group must be 1..4, a comma list, a 0xNN mask, or 'all'") from exc

    if isinstance(groups, int):
        if 1 <= groups <= 4:
            return 1 << (groups - 1)
        raise ValueError("integer group number must be between 1 and 4; use 0xNN for a raw mask")

    mask = 0
    for group in groups:
        if not 1 <= group <= 4:
            raise ValueError("group numbers must be between 1 and 4")
        mask |= 1 << (group - 1)
    if mask == 0:
        raise ValueError("at least one group is required")
    return mask


@dataclass(frozen=True)
class RemoteCommand:
    remote_id: bytes
    mode: int
    group_mask: int
    action_code: int

    @property
    def action(self) -> str:
        return ACTION_NAMES.get(self.action_code, f"unknown-0x{self.action_code:02x}")

    @property
    def groups(self) -> tuple[int, ...]:
        """Return only the four group buttons established by captures."""

        return tuple(group for group in range(1, 5) if self.group_mask & (1 << (group - 1)))

    @property
    def is_all_groups(self) -> bool:
        return self.group_mask == 0xFF

    @property
    def unassigned_mask_bits(self) -> int:
        """High bits are not proven to represent Groups 5-8."""

        return 0 if self.is_all_groups else self.group_mask & 0xF0

    def to_bytes(self) -> bytes:
        return self.remote_id + bytes((self.mode, self.group_mask, self.action_code))

    def as_dict(self) -> dict[str, object]:
        return {
            "remote_id": self.remote_id.hex(),
            "mode": f"0x{self.mode:02x}",
            "group_mask": f"0x{self.group_mask:02x}",
            "groups": list(self.groups),
            "all_groups": self.is_all_groups,
            "unassigned_mask_bits": f"0x{self.unassigned_mask_bits:02x}",
            "action": self.action,
            "action_code": f"0x{self.action_code:02x}",
            "payload_hex": self.to_bytes().hex(),
        }


def build_remote_payload(
    remote_id: str | bytes | bytearray,
    groups: str | int | Iterable[int],
    action: str,
) -> bytes:
    """Build the community-documented five-byte group command payload."""

    normalized_action = action.strip().lower()
    try:
        action_code = ACTION_CODES[normalized_action]
    except KeyError as exc:
        choices = ", ".join(ACTION_CODES)
        raise ValueError(f"unknown action {action!r}; choose one of: {choices}") from exc
    return RemoteCommand(
        remote_id=parse_remote_id(remote_id),
        mode=REMOTE_MODE_GROUP,
        group_mask=groups_to_mask(groups),
        action_code=action_code,
    ).to_bytes()


def decode_remote_payload(payload: bytes | bytearray | str) -> RemoteCommand:
    if isinstance(payload, str):
        cleaned = payload.lower().removeprefix("0x").replace(" ", "").replace(":", "")
        try:
            payload_bytes = bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError("payload must be hexadecimal") from exc
    else:
        payload_bytes = bytes(payload)
    if len(payload_bytes) != REMOTE_PAYLOAD_LENGTH:
        raise ValueError("remote payload must be exactly five bytes")
    return RemoteCommand(
        remote_id=payload_bytes[:2],
        mode=payload_bytes[2],
        group_mask=payload_bytes[3],
        action_code=payload_bytes[4],
    )


def crc16_ccitt_bits(bits: Iterable[int], *, initial: int = 0xFFFF) -> int:
    """Nordic ESB CRC-16 over an arbitrary-length MSB-first bit stream."""

    crc = initial
    for bit in bits:
        if bit not in (0, 1):
            raise ValueError("CRC input must contain only 0/1 bits")
        feedback = ((crc >> 15) & 1) ^ bit
        crc = (crc << 1) & 0xFFFF
        if feedback:
            crc ^= 0x1021
    return crc


def bytes_to_bits(data: bytes) -> tuple[int, ...]:
    return tuple((byte >> shift) & 1 for byte in data for shift in range(7, -1, -1))


def bits_to_bytes(bits: Iterable[int]) -> tuple[bytes, int]:
    materialized = tuple(bits)
    if any(bit not in (0, 1) for bit in materialized):
        raise ValueError("bit stream must contain only 0/1 values")
    padding = (-len(materialized)) % 8
    padded = materialized + (0,) * padding
    output = bytearray()
    for offset in range(0, len(padded), 8):
        byte = 0
        for bit in padded[offset : offset + 8]:
            byte = (byte << 1) | bit
        output.append(byte)
    return bytes(output), len(materialized)


@dataclass(frozen=True)
class EsbCandidateFrame:
    """A candidate on-air ESB frame for comparison with demodulated IQ."""

    bits: tuple[int, ...]
    packed: bytes
    bit_length: int
    crc: int
    pcf_payload_length: int
    pid: int
    no_ack: int

    @property
    def duration_seconds(self) -> float:
        return self.bit_length / REMOTE_DATA_RATE

    @property
    def bit_string(self) -> str:
        return "".join(str(bit) for bit in self.bits)


def build_esb_candidate_frame(
    payload: bytes,
    *,
    address: bytes = REMOTE_ADDRESS,
    pcf_payload_length: int | None = None,
    pid: int = 0,
    no_ack: int = 0,
) -> EsbCandidateFrame:
    """Build a datasheet-shaped ESB frame for offline hypothesis testing.

    The Platinum register dump reports 2 Mbps, so Nordic's documented
    no-PCF ShockBurst compatibility mode does not apply. The six payload-length
    PCF bits are semantically unused when dynamic payloads are disabled,
    however, and their actual on-air value must be established from a capture.
    This function defaults that candidate field to the real payload length but
    allows all six bits to be varied explicitly.
    """

    if not 3 <= len(address) <= 5:
        raise ValueError("ESB address must be 3, 4, or 5 bytes")
    if not 0 <= len(payload) <= 32:
        raise ValueError("ESB payload must be between 0 and 32 bytes")
    length_field = len(payload) if pcf_payload_length is None else pcf_payload_length
    if not 0 <= length_field <= 0x3F:
        raise ValueError("PCF payload-length field must fit in six bits")
    if not 0 <= pid <= 3:
        raise ValueError("PID must fit in two bits")
    if no_ack not in (0, 1):
        raise ValueError("NO_ACK must be 0 or 1")

    address_bits = bytes_to_bits(address)
    pcf_bits = tuple((length_field >> shift) & 1 for shift in range(5, -1, -1))
    pcf_bits += ((pid >> 1) & 1, pid & 1, no_ack)
    payload_bits = bytes_to_bits(payload)
    protected_bits = address_bits + pcf_bits + payload_bits
    crc = crc16_ccitt_bits(protected_bits)
    crc_bits = tuple((crc >> shift) & 1 for shift in range(15, -1, -1))

    first_address_bit = address_bits[0]
    preamble = 0xAA if first_address_bit else 0x55
    frame_bits = bytes_to_bits(bytes((preamble,))) + protected_bits + crc_bits
    packed, bit_length = bits_to_bytes(frame_bits)
    return EsbCandidateFrame(
        bits=frame_bits,
        packed=packed,
        bit_length=bit_length,
        crc=crc,
        pcf_payload_length=length_field,
        pid=pid,
        no_ack=no_ack,
    )
