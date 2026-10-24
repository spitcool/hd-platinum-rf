# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Parse two Nordic framing hypotheses from already demodulated bits.

This module has no device or transmit functions. It checks both a nine-bit
packet-control field (``esb``) and its absence (``shockburst``); choosing one
parser is not evidence that a particular radio uses that format. Bits must
already have the desired polarity, with each address/payload/CRC byte MSB first.
CRC-valid candidates can be ambiguous: a complete CRC codeword followed by
zeros can validate a longer framing too. Resolve such cases with measured
packet extent and field consistency, not CRC alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from operator import index
from typing import Iterable

from .rf import REMOTE_ADDRESS, REMOTE_PAYLOAD_LENGTH, crc16_ccitt_bits


FRAMINGS = ("esb", "shockburst")


def _bit_string(bits: Iterable[int] | str) -> str:
    if isinstance(bits, str):
        if any(bit not in "01" for bit in bits):
            raise ValueError("bit string must contain only 0 and 1")
        return bits
    values = []
    for bit in bits:
        try:
            value = index(bit)
        except TypeError as exc:
            raise ValueError("bits must be integers equal to 0 or 1") from exc
        if value not in (0, 1):
            raise ValueError("bits must be integers equal to 0 or 1")
        values.append(str(value))
    return "".join(values)


def _parameters(address: bytes, payload_length: int) -> tuple[bytes, int]:
    if not isinstance(address, (bytes, bytearray)) or not 3 <= len(address) <= 5:
        raise ValueError("address must contain three to five bytes")
    try:
        length = index(payload_length)
    except TypeError as exc:
        raise ValueError("payload length must be an integer between 0 and 32") from exc
    if isinstance(payload_length, bool) or not 0 <= length <= 32:
        raise ValueError("payload length must be an integer between 0 and 32")
    return bytes(address), length


@dataclass(frozen=True)
class DecodedFrame:
    """A complete address-through-CRC candidate, including invalid CRCs.

    Offsets are zero-based bit positions in the supplied bitstream, and
    ``frame_end_bit`` is exclusive. ``frame_start_bit`` includes the eight
    presumed preamble bits and can be negative if the capture begins at the
    address. ``preamble_matches`` is then ``None``. The fixed payload length is
    supplied by the caller; the ESB length field is reported, not trusted.
    """

    address_start_bit: int
    frame_start_bit: int
    frame_end_bit: int
    framing: str
    address: bytes
    payload: bytes
    crc_received: int
    crc_expected: int
    pcf_payload_length: int | None
    pid: int | None
    no_ack: int | None
    preamble_matches: bool | None

    @property
    def crc_valid(self) -> bool:
        return self.crc_received == self.crc_expected

    @property
    def frame_bit_length(self) -> int:
        return self.frame_end_bit - self.frame_start_bit


def _parse_at(
    bits: str, address_start: int, framing: str, address: bytes, payload_length: int
) -> DecodedFrame | None:
    address_bits = "".join(f"{byte:08b}" for byte in address)
    address_end = address_start + len(address_bits)
    pcf_end = address_end + (9 if framing == "esb" else 0)
    payload_end = pcf_end + payload_length * 8
    frame_end = payload_end + 16
    if frame_end > len(bits) or bits[address_start:address_end] != address_bits:
        return None

    payload = bytes(int(bits[offset:offset + 8], 2)
                    for offset in range(pcf_end, payload_end, 8))
    expected_preamble = "10101010" if address[0] & 0x80 else "01010101"
    preamble_matches = (
        bits[address_start - 8:address_start] == expected_preamble
        if address_start >= 8 else None
    )
    pcf_length = pid = no_ack = None
    if framing == "esb":
        pcf_length = int(bits[address_end:address_end + 6], 2)
        pid = int(bits[address_end + 6:address_end + 8], 2)
        no_ack = int(bits[address_end + 8])
    return DecodedFrame(
        address_start_bit=address_start,
        frame_start_bit=address_start - 8,
        frame_end_bit=frame_end,
        framing=framing,
        address=address,
        payload=payload,
        crc_received=int(bits[payload_end:frame_end], 2),
        crc_expected=crc16_ccitt_bits(int(bit) for bit in bits[address_start:payload_end]),
        pcf_payload_length=pcf_length,
        pid=pid,
        no_ack=no_ack,
        preamble_matches=preamble_matches,
    )


def parse_frame(
    bits: Iterable[int] | str,
    *,
    address_start_bit: int = 8,
    framing: str,
    address: bytes = REMOTE_ADDRESS,
    payload_length: int = REMOTE_PAYLOAD_LENGTH,
) -> DecodedFrame | None:
    """Check one framing at a known address position, retaining CRC failures.

    Return ``None`` for a missing address or truncated address-through-CRC
    region. Invalid argument values raise ``ValueError``. A missing or damaged
    preamble is reported separately and does not suppress the candidate.
    """

    data = _bit_string(bits)
    address, payload_length = _parameters(address, payload_length)
    if framing not in FRAMINGS:
        raise ValueError("framing must be 'esb' or 'shockburst'")
    try:
        start = index(address_start_bit)
    except TypeError as exc:
        raise ValueError("address_start_bit must be a nonnegative integer") from exc
    if isinstance(address_start_bit, bool) or start < 0:
        raise ValueError("address_start_bit must be a nonnegative integer")
    return _parse_at(data, start, framing, address, payload_length)


def scan_frames(
    bits: Iterable[int] | str,
    *,
    address: bytes = REMOTE_ADDRESS,
    payload_length: int = REMOTE_PAYLOAD_LENGTH,
    framings: Iterable[str] = FRAMINGS,
    include_invalid: bool = False,
    require_preamble: bool = False,
) -> tuple[DecodedFrame, ...]:
    """Find address matches and check each requested fixed-length framing.

    By default return only CRC-valid candidates, in address-position order and
    then in the requested framing order. Overlapping address matches are
    examined. ``include_invalid`` retains complete CRC-failing candidates for
    diagnosis. ``require_preamble`` requires all eight correct preamble bits;
    otherwise CRC validation alone decides acceptance.

    More than one framing can validate at the same address. Such candidates
    are all returned rather than silently selecting a protocol hypothesis.
    """

    data = _bit_string(bits)
    address, payload_length = _parameters(address, payload_length)
    if isinstance(framings, str):
        raise ValueError("framings must be a nonempty sequence of framing names")
    choices = tuple(framings)
    if not choices or any(choice not in FRAMINGS for choice in choices):
        raise ValueError("framings must contain 'esb' and/or 'shockburst'")
    if len(set(choices)) != len(choices):
        raise ValueError("framing names must not be repeated")
    if not isinstance(include_invalid, bool) or not isinstance(require_preamble, bool):
        raise ValueError("include_invalid and require_preamble must be booleans")

    needle = "".join(f"{byte:08b}" for byte in address)
    matches = []
    start = data.find(needle)
    while start != -1:
        for framing in choices:
            frame = _parse_at(data, start, framing, address, payload_length)
            if frame is None:
                continue
            if require_preamble and frame.preamble_matches is not True:
                continue
            if include_invalid or frame.crc_valid:
                matches.append(frame)
        start = data.find(needle, start + 1)
    return tuple(matches)
