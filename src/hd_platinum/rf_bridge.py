# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Firmware-verified 250 kbps bridge payloads and the exercised finite PHY.

The local sequence ordinal is distinct from the eight-bit on-air transaction
counter. This module only creates samples; it never opens RF hardware. The flat
lead deliberately preserves the profile exercised with a real repeater and
shade. Position requests do not establish resulting position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path

from .rf import REMOTE_ADDRESS, bytes_to_bits, crc16_ccitt_bits


SAMPLE_RATE_HZ = 8_000_000
WIDE_SAMPLE_RATE_HZ = 32_000_000
CENTER_HZ = 2_440_000_000
BANDWIDTH_HZ = 1_500_000
SYMBOL_RATE_HZ = 250_000
DEVIATION_HZ = 160_000
GAUSSIAN_BT = .5
AMPLITUDE = .5
LEAD_SAMPLES = 432
RAMP_SAMPLES = 16
TAIL_SAMPLES = 104
SAMPLES_PER_SYMBOL = 32
SAMPLE_COUNT = 897_072
DURATION_SECONDS = SAMPLE_COUNT / SAMPLE_RATE_HZ
# Ten captured preamble-relative starts, with 10 ms quiet at each end.
BURST_START_SAMPLES = (80_000, 172_340, 252_600, 332_366, 412_538,
                       492_392, 572_640, 652_396, 732_648, 812_408)


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer within {minimum}..{maximum}")
    return value


def _sample_rate_factor(sample_rate_hz):
    if type(sample_rate_hz) is not int or sample_rate_hz not in (SAMPLE_RATE_HZ, WIDE_SAMPLE_RATE_HZ):
        raise ValueError("sample_rate_hz must be 8000000 or 32000000")
    return sample_rate_hz // SAMPLE_RATE_HZ


def _checksum(prefix: bytes) -> bytes:
    value = 0xff
    for byte in prefix[1:]:
        value ^= byte
    return prefix + bytes((value,))


def build_position_payload(room_rf_id: bytes, mask: int, position: int,
                           *, feature: int = 4) -> bytes:
    """Encode an observed primary-position command for one configured shade."""
    if not isinstance(room_rf_id, (bytes, bytearray)) or len(room_rf_id) != 2:
        raise ValueError("room_rf_id must contain exactly two bytes")
    _integer(mask, "mask", 1, 128)
    if mask & (mask - 1):
        raise ValueError("mask must select exactly one shade")
    _integer(position, "position", 0, 255)
    _integer(feature, "feature", 4, 4)
    return _checksum(b"\x01\x0a\x02\x34" + bytes(room_rf_id)
                     + bytes((feature, mask, position, 0, 1)))


def build_sequence_payload(sequence: int, countdown: int) -> bytes:
    """Encode one command's short packet from a durable local sequence ordinal.

    Original firmware stores command count and transaction counter as separate
    bytes. A single-command plan always advertises count 1; its transaction byte
    wraps at 255. The 16-bit argument remains a local allocation identifier for
    compatibility with existing durable state, not a 16-bit on-air field.
    """
    _integer(sequence, "sequence", 0, 65535)
    _integer(countdown, "countdown", 0, 4)
    return _checksum(b"\x01\x07\x02\x38"
                     + bytes((1, sequence & 0xff, countdown, 6)))


def build_sync_payload(room_rf_id: bytes, mask: int) -> bytes:
    """Encode the captured enrollment request, distinct from position control.

    Two observed Sync exchanges retain feature 01, value 00 and flags 03.
    Merely changing the position command's feature would retain the wrong flag.
    This requests a sync signal; it never proves a shade accepted enrollment.
    """
    prefix = bytearray(build_position_payload(room_rf_id, mask, 0)[:-1])
    prefix[6], prefix[10] = 1, 3
    return _checksum(bytes(prefix))


def build_jog_payload(room_rf_id: bytes, mask: int) -> bytes:
    """Encode captured Jog feature 0x0c, RF value 1, and flags 1.

    The original LAN request carries value 000, but its response and observed
    RF command use value 001. This requests Jog; it does not confirm movement.
    """
    prefix = bytearray(build_position_payload(room_rf_id, mask, 1)[:-1])
    prefix[6] = 12
    return _checksum(bytes(prefix))


def build_esb_bits(payload: bytes, pid: int, *, no_ack: int = 0) -> tuple[int, ...]:
    """AA + three-byte address + nine-bit PCF + payload + CRC16, MSB first."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) not in (9, 12):
        raise ValueError("bridge payload must contain 9 or 12 bytes")
    _integer(pid, "pid", 0, 3)
    _integer(no_ack, "no_ack", 0, 1)
    pcf = tuple(map(int, f"{len(payload):06b}{pid:02b}{no_ack}"))
    protected = bytes_to_bits(REMOTE_ADDRESS) + pcf + bytes_to_bits(bytes(payload))
    crc = crc16_ccitt_bits(protected)
    return bytes_to_bits(b"\xaa") + protected + bytes_to_bits(crc.to_bytes(2, "big"))


@dataclass(frozen=True)
class BridgeFrame:
    start_sample: int
    payload: bytes = field(repr=False)
    pid: int
    no_ack: int = 0

    def __post_init__(self):
        _integer(self.start_sample, "start_sample", 0, SAMPLE_COUNT - 1)
        build_esb_bits(self.payload, self.pid, no_ack=self.no_ack)
        object.__setattr__(self, "payload", bytes(self.payload))

    @property
    def bits(self):
        return build_esb_bits(self.payload, self.pid, no_ack=self.no_ack)

    @property
    def preamble_sample(self):
        return self.start_sample + LEAD_SAMPLES


@dataclass(frozen=True)
class BridgeWaveformPlan:
    sequence: int
    frames: tuple[BridgeFrame, ...] = field(repr=False)

    def __post_init__(self):
        _integer(self.sequence, "sequence", 0, 65535)
        object.__setattr__(self, "frames", tuple(self.frames))
        if any(not isinstance(frame, BridgeFrame) for frame in self.frames):
            raise ValueError("frames must contain BridgeFrame values")
        if len(self.frames) != 10:
            raise ValueError("bridge plan requires exactly ten frames")
        long_payload = self.frames[0].payload
        if len(long_payload) != 12 or long_payload[0:4] != b"\x01\x0a\x02\x34":
            raise ValueError("invalid position payload")
        if long_payload[6] == 1:
            expected_long = build_sync_payload(long_payload[4:6], long_payload[7])
        elif long_payload[6] == 12:
            expected_long = build_jog_payload(long_payload[4:6], long_payload[7])
        else:
            expected_long = build_position_payload(long_payload[4:6], long_payload[7],
                                                   long_payload[8], feature=long_payload[6])
        if long_payload != expected_long:
            raise ValueError("position payload is inconsistent")
        for i, frame in enumerate(self.frames):
            wanted = long_payload if i % 2 == 0 else build_sequence_payload(self.sequence, 4 - i // 2)
            if (frame.start_sample != BURST_START_SAMPLES[i] or frame.payload != wanted
                    or frame.pid != i % 4 or frame.no_ack != 0):
                raise ValueError("frame does not match the exercised bridge schedule")

    def as_dict(self, *, include_private=False, sample_rate_hz=SAMPLE_RATE_HZ):
        """Describe emitted samples; this plan's own indices remain at 8 MS/s."""
        if type(include_private) is not bool:
            raise ValueError("include_private must be a boolean")
        factor = _sample_rate_factor(sample_rate_hz)
        operation = {1: "sync", 4: "position", 12: "jog"}[self.frames[0].payload[6]]
        result = {"operation": operation,
                  "sample_rate_hz": sample_rate_hz, "center_hz": CENTER_HZ,
                  "source_sample_rate_hz": SAMPLE_RATE_HZ, "source_sample_count": SAMPLE_COUNT,
                  "bandwidth_hz": BANDWIDTH_HZ, "symbol_rate_hz": SYMBOL_RATE_HZ,
                  "deviation_hz": DEVIATION_HZ, "gaussian_bt": GAUSSIAN_BT,
                  "amplitude": AMPLITUDE, "lead_us": 54, "ramp_us": 2, "tail_us": 13,
                  "lead_policy": "Unmodulated center carrier; exercised flat-lead profile",
                  "sample_count": SAMPLE_COUNT * factor, "duration_seconds": DURATION_SECONDS,
                  "frame_count": 10, "sequence": self.sequence,
                  "command_count": 1, "transaction_counter": self.sequence & 0xff,
                  "burst_start_samples": [value * factor for value in BURST_START_SAMPLES]}
        if factor == 4:
            result["interpolation"] = {
                "up": 4, "down": 1, "filter_taps": 257, "cutoff_hz": 3_000_000,
                "filter_design_rate_hz": WIDE_SAMPLE_RATE_HZ, "window": "Kaiser beta8.6",
                "delay_compensated": True, "gain_scale": 1.0,
                "quiet_policy": "Zero outside canonical burst supports scaled by four",
            }
        if include_private:
            result["frames"] = [{"start_sample": f.start_sample * factor,
                "preamble_sample": f.preamble_sample * factor, "payload_hex": f.payload.hex(),
                "pid": f.pid, "no_ack": f.no_ack,
                "bits": "".join(map(str, f.bits))} for f in self.frames]
        return result


def build_bridge_plan(command, sequence: int) -> BridgeWaveformPlan:
    from .bridge import JogCommand, PositionCommand, ShadeConfig, SyncCommand
    if not isinstance(command, (PositionCommand, SyncCommand, JogCommand)) or not isinstance(command.target, ShadeConfig):
        raise ValueError("a position, sync, or jog command with a configured shade is required")
    if isinstance(command, SyncCommand):
        if not command.target.sync_enabled:
            raise ValueError("enrollment is disabled for this target")
        long_payload = build_sync_payload(command.target.room_rf_id, command.target.mask)
    elif isinstance(command, JogCommand):
        if not command.target.jog_enabled:
            raise ValueError("Jog is disabled for this target")
        long_payload = build_jog_payload(command.target.room_rf_id, command.target.mask)
    else:
        if not command.target.position_enabled:
            raise ValueError("position control is disabled for this target")
        long_payload = build_position_payload(command.target.room_rf_id, command.target.mask,
                                              command.position, feature=command.target.feature)
    _integer(sequence, "sequence", 0, 65535)
    frames = tuple(BridgeFrame(start,
        long_payload if i % 2 == 0 else build_sequence_payload(sequence, 4 - i // 2), i % 4)
        for i, start in enumerate(BURST_START_SAMPLES))
    return BridgeWaveformPlan(sequence, frames)


def render_bridge_iq(plan: BridgeWaveformPlan, *, sample_rate_hz=SAMPLE_RATE_HZ):
    """Return SC16Q11 at 8 MS/s, or the reviewed 4x interpolation at 32 MS/s.

    The 32 MS/s option preserves physical timing and the canonical 8 MS/s
    samples. Filtering and requantization produce the intervening samples;
    it is not a change to the packet format or a claim of receiver acceptance.
    """
    if not isinstance(plan, BridgeWaveformPlan):
        raise ValueError("a validated BridgeWaveformPlan is required")
    factor = _sample_rate_factor(sample_rate_hz)
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("bridge synthesis requires the analysis extra") from exc
    sigma = math.sqrt(math.log(2)) / (2 * math.pi * GAUSSIAN_BT) * SAMPLES_PER_SYMBOL
    half = max(2 * SAMPLES_PER_SYMBOL, math.ceil(4 * sigma))
    x = np.arange(-half, half + 1, dtype=np.float64)
    gaussian = np.exp(-.5 * (x / sigma) ** 2)
    gaussian /= gaussian.sum()
    edge = .5 - .5 * np.cos(np.linspace(0, math.pi, RAMP_SAMPLES))
    output = np.zeros((SAMPLE_COUNT, 2), dtype="<i2")
    for frame in plan.frames:
        symbols = np.repeat(np.array(frame.bits, dtype=np.float64) * 2 - 1, SAMPLES_PER_SYMBOL)
        values = np.concatenate((np.zeros(LEAD_SAMPLES), symbols, np.full(TAIL_SAMPLES, symbols[-1])))
        shaped = np.convolve(np.pad(values, (half, half), mode="edge"), gaussian, mode="valid")
        phase = np.cumsum(DEVIATION_HZ * shaped) * (2 * math.pi / SAMPLE_RATE_HZ)
        envelope = np.full(len(values), AMPLITUDE, dtype=np.float64)
        envelope[:RAMP_SAMPLES] *= edge
        envelope[-RAMP_SAMPLES:] *= edge[::-1]
        pulse = envelope * np.exp(1j * phase)
        start, stop = frame.start_sample, frame.start_sample + len(pulse)
        output[start:stop, 0] = np.rint(pulse.real * 2048).astype("<i2")
        output[start:stop, 1] = np.rint(pulse.imag * 2048).astype("<i2")
    if factor == 1:
        return output
    try:
        from scipy import signal
    except ImportError as exc:
        raise ValueError("32 MS/s bridge synthesis requires the analysis extra") from exc
    # Interpolate the quantized canonical waveform, as in the reviewed 32 MS/s
    # diagnostic. resample_poly compensates the symmetric filter's delay.
    iq = output[:, 0].astype(float) + 1j * output[:, 1].astype(float)
    taps = signal.firwin(257, 3_000_000, fs=WIDE_SAMPLE_RATE_HZ, window=("kaiser", 8.6))
    interpolated = signal.resample_poly(iq, factor, 1, window=taps)
    active = np.zeros(len(interpolated), dtype=bool)
    for frame in plan.frames:
        length = LEAD_SAMPLES + len(frame.bits) * SAMPLES_PER_SYMBOL + TAIL_SAMPLES
        active[frame.start_sample * factor:(frame.start_sample + length) * factor] = True
    # FIR tails must not turn the prescribed quiet gaps into additional RF.
    interpolated[~active] = 0
    return np.column_stack((np.rint(interpolated.real), np.rint(interpolated.imag))).astype("<i2")


def write_bridge_waveform(path: str | Path, plan: BridgeWaveformPlan, *, sample_rate_hz=SAMPLE_RATE_HZ) -> dict:
    """Write one private waveform exclusively; an existing file is never replaced."""
    output = render_bridge_iq(plan, sample_rate_hz=sample_rate_hz)
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        output.tofile(stream)
        stream.flush()
        os.fsync(stream.fileno())
    return {**plan.as_dict(sample_rate_hz=sample_rate_hz), "sha256": hashlib.sha256(output.tobytes()).hexdigest(),
            "byte_count": output.nbytes}
