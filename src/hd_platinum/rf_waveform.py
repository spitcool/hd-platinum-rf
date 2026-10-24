# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline GFSK waveform synthesis; this module never opens a radio.

The packet bits follow the locally observed 88-bit, no-PCF format. Gaussian
BT, deviation, and envelope are configurable synthesis assumptions, not a
claim of measured equivalence to the original remote. Generated samples must
still pass conducted validation before being used to control equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import os
from operator import index
from pathlib import Path
from typing import Iterator

from .rf import (
    REMOTE_ADDRESS,
    REMOTE_DATA_RATE,
    REMOTE_FREQUENCIES_HZ,
    build_remote_payload,
    bytes_to_bits,
    crc16_ccitt_bits,
)


MAX_AIRTIME_SECONDS = 2.0
FRAME_BITS = 88
MODEL_NOTE = (
    "88-bit no-PCF packet model; Gaussian BT, deviation, and envelope are "
    "provisional synthesis parameters. Software decoding is not RF interoperability validation."
)


def _numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("waveform synthesis requires the analysis extra: pip install '.[analysis]'") from exc
    return np


def _integer(value, name: str, minimum: int, maximum: int) -> int:
    try:
        result = index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be within {minimum}..{maximum}")
    return result


def _finite(value, name: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if isinstance(value, bool) or not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be within {minimum}..{maximum}")
    return result


def build_frame_bits(payload: bytes) -> tuple[int, ...]:
    """Return AA preamble, E7E7E7 address, five payload bytes, and CRC-16.

    Bytes and CRC are MSB first. The CRC covers address and payload only,
    starting at 0xffff, using polynomial 0x1021 and no final XOR.
    """
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != 5:
        raise ValueError("payload must contain exactly five bytes")
    protected = bytes_to_bits(REMOTE_ADDRESS + bytes(payload))
    checksum = crc16_ccitt_bits(protected)
    return bytes_to_bits(b"\xaa") + protected + bytes_to_bits(checksum.to_bytes(2, "big"))


@dataclass(frozen=True)
class WaveformConfig:
    sample_rate_hz: int = 48_000_000
    center_hz: float = 2_452_000_000
    channels_hz: tuple[int, ...] = REMOTE_FREQUENCIES_HZ
    deviation_hz: float = 360_000
    gaussian_bt: float = .5
    lead_in_us: float = 49
    ramp_us: float = 2
    slot_us: float = 195
    amplitude: float = .5
    max_airtime_seconds: float = MAX_AIRTIME_SECONDS

    def __post_init__(self) -> None:
        rate = _integer(self.sample_rate_hz, "sample rate", 8_000_000, 64_000_000)
        if rate % 8_000_000:
            raise ValueError("sample rate must be an integer multiple of 8000000")
        object.__setattr__(self, "sample_rate_hz", rate)
        ranges = {
            "center_hz": (1, 6_000_000_000),
            "deviation_hz": (50_000, 1_000_000),
            "gaussian_bt": (.1, 1),
            "lead_in_us": (0, 500),
            "ramp_us": (0, 20),
            "slot_us": (1, 10_000),
            "amplitude": (1 / 2048, .95),
            "max_airtime_seconds": (.000001, MAX_AIRTIME_SECONDS),
        }
        for name, bounds in ranges.items():
            object.__setattr__(self, name, _finite(getattr(self, name), name, *bounds))
        if self.ramp_us > self.lead_in_us:
            raise ValueError("ramp duration must fit within the carrier lead-in")
        try:
            channels = tuple(_integer(ch, "channel", 1, 6_000_000_000) for ch in self.channels_hz)
        except TypeError as exc:
            raise ValueError("channels must be a sequence of frequencies") from exc
        if not channels or len(channels) > 3 or len(set(channels)) != len(channels):
            raise ValueError("one to three distinct handheld channels are required")
        if any(ch not in REMOTE_FREQUENCIES_HZ for ch in channels):
            raise ValueError("channels must use the locally observed handheld frequencies")
        if any(abs(ch-self.center_hz) + self.deviation_hz + REMOTE_DATA_RATE > rate/2 for ch in channels):
            raise ValueError("channel plus modulation margin exceeds the sampled bandwidth")
        object.__setattr__(self, "channels_hz", channels)
        if self.slot_samples < self.pulse_samples:
            raise ValueError("slot duration must accommodate lead-in, packet, and ramp-down")

    @property
    def lead_samples(self) -> int:
        return round(self.lead_in_us * self.sample_rate_hz / 1_000_000)

    @property
    def ramp_samples(self) -> int:
        return round(self.ramp_us * self.sample_rate_hz / 1_000_000)

    @property
    def pulse_samples(self) -> int:
        return self.lead_samples + FRAME_BITS * (self.sample_rate_hz // REMOTE_DATA_RATE) + self.ramp_samples

    @property
    def slot_samples(self) -> int:
        return round(self.slot_us * self.sample_rate_hz / 1_000_000)


@dataclass(frozen=True)
class WaveformPlan:
    config: WaveformConfig
    action: str
    action_payload: bytes = field(repr=False)
    release_payload: bytes = field(repr=False)
    action_repetitions: int = 500
    release_repetitions: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.config, WaveformConfig):
            raise ValueError("config must be a WaveformConfig")
        if self.action not in ("up", "down"):
            raise ValueError("action must be up or down")
        build_frame_bits(self.action_payload)
        build_frame_bits(self.release_payload)
        object.__setattr__(self, "action_payload", bytes(self.action_payload))
        object.__setattr__(self, "release_payload", bytes(self.release_payload))
        action_code, release_code = (0xA1, 0x21) if self.action == "up" else (0xA2, 0x22)
        if self.action_payload[2] != 0x20 or self.action_payload[4] != action_code:
            raise ValueError("action payload must match the requested group command")
        if self.release_payload != self.action_payload[:4] + bytes((release_code,)):
            raise ValueError("release payload must match the identity, mode, and group of the action")
        for name, minimum in (("action_repetitions", 1), ("release_repetitions", 0)):
            object.__setattr__(self, name, _integer(getattr(self, name), name, minimum, 10_000))
        if self.duration_seconds > self.config.max_airtime_seconds:
            raise ValueError("planned waveform exceeds the configured airtime limit")

    @property
    def frame_count(self) -> int:
        return (self.action_repetitions + self.release_repetitions) * len(self.config.channels_hz)

    @property
    def sample_count(self) -> int:
        return self.frame_count * self.config.slot_samples

    @property
    def duration_seconds(self) -> float:
        """Elapsed waveform duration including silent intervals and final gap."""
        return self.sample_count / self.config.sample_rate_hz

    def as_dict(self, *, include_private: bool = False) -> dict:
        if not isinstance(include_private, bool):
            raise ValueError("include_private must be a boolean")
        config = self.config
        payload = lambda value: value.hex() if include_private else "xxxx" + value.hex()[4:]
        return {
            "format": "SC16Q11 little-endian interleaved I,Q",
            "sample_rate_hz": config.sample_rate_hz,
            "center_hz": config.center_hz,
            "channels_hz": list(config.channels_hz),
            "bit_rate_hz": REMOTE_DATA_RATE,
            "frame_bits": FRAME_BITS,
            "framing": "shockburst",
            "deviation_hz": config.deviation_hz,
            "gaussian_bt": config.gaussian_bt,
            "amplitude": config.amplitude,
            "lead_in_us": config.lead_samples / config.sample_rate_hz * 1e6,
            "ramp_us": config.ramp_samples / config.sample_rate_hz * 1e6,
            "pulse_us": config.pulse_samples / config.sample_rate_hz * 1e6,
            "slot_us": config.slot_samples / config.sample_rate_hz * 1e6,
            "action": self.action,
            "action_payload": payload(self.action_payload),
            "release_payload": payload(self.release_payload),
            "action_repetitions": self.action_repetitions,
            "release_repetitions": self.release_repetitions,
            "frame_count": self.frame_count,
            "sample_count": self.sample_count,
            "duration_seconds": self.duration_seconds,
            "max_airtime_seconds": config.max_airtime_seconds,
            "model_note": MODEL_NOTE,
        }


def build_command_plan(remote_id, groups, action: str, *, action_repetitions: int = 500,
                       release_repetitions: int = 500,
                       config: WaveformConfig | None = None) -> WaveformPlan:
    """Plan bounded sequential channel cycles, followed by release cycles.

    A repetition is one visit to each configured channel, in its given order.
    The defaults produce 1,000 frames per channel over 0.585 seconds: 500 action
    and 500 release frames. Timing/counts are configurable, not universal remote
    constants. A different remote_id produces a separate negative control.
    """
    if not isinstance(action, str) or action.lower() not in ("up", "down"):
        raise ValueError("action must be up or down")
    action = action.lower()
    return WaveformPlan(
        config=WaveformConfig() if config is None else config,
        action=action,
        action_payload=build_remote_payload(remote_id, groups, action),
        release_payload=build_remote_payload(remote_id, groups, "release-" + action),
        action_repetitions=action_repetitions,
        release_repetitions=release_repetitions,
    )


def synthesize_frame(payload: bytes, *, sample_rate_hz: int = 8_000_000,
                     deviation_hz: float = 360_000, gaussian_bt: float = .5,
                     lead_in_us: float = 49, ramp_us: float = 2,
                     amplitude: float = .5, carrier_offset_hz: float = 0):
    """Return one normalized complex64 pulse, including carrier lead-in/ramp.

    A Gaussian filter smooths the NRZ frequency command. The ramp-up occurs
    within the lead-in; ramp-down follows the last CRC bit. Positive deviation
    represents bit one. The phase is continuous within each pulse.
    """
    bits = build_frame_bits(payload)
    offset = _finite(carrier_offset_hz, "carrier offset", -32_000_000, 32_000_000)
    config = WaveformConfig(sample_rate_hz=sample_rate_hz, center_hz=REMOTE_FREQUENCIES_HZ[1]-offset,
                            channels_hz=(REMOTE_FREQUENCIES_HZ[1],), deviation_hz=deviation_hz,
                            gaussian_bt=gaussian_bt, lead_in_us=lead_in_us, ramp_us=ramp_us,
                            slot_us=1000, amplitude=amplitude)
    np = _numpy()
    sps = config.sample_rate_hz // REMOTE_DATA_RATE
    lead, ramp = config.lead_samples, config.ramp_samples
    symbols = np.repeat(np.array(bits, dtype=np.float64) * 2 - 1, sps)
    command = np.concatenate((np.zeros(lead), symbols, np.full(ramp, symbols[-1])))
    # Gaussian amplitude response is -3 dB at B=BT*symbol_rate.
    sigma = math.sqrt(math.log(2)) / (2 * math.pi * config.gaussian_bt) * sps
    half = max(2*sps, math.ceil(4*sigma))
    time = np.arange(-half, half+1, dtype=np.float64)
    gaussian = np.exp(-.5 * (time / sigma) ** 2)
    gaussian /= gaussian.sum()
    # Edge extension avoids introducing a filter transient at the final CRC.
    shaped = np.convolve(np.pad(command, (half, half), mode="edge"), gaussian, mode="valid")
    frequency = config.deviation_hz * shaped + offset
    phase = np.cumsum(frequency) * (2 * math.pi / config.sample_rate_hz)
    envelope = np.full(len(command), config.amplitude, dtype=np.float64)
    if ramp:
        edge = .5 - .5 * np.cos(np.linspace(0, math.pi, ramp))
        envelope[:ramp] *= edge
        envelope[-ramp:] *= edge[::-1]
    return (envelope * np.exp(1j * phase)).astype(np.complex64)


def iter_iq_chunks(plan: WaveformPlan, *, chunk_samples: int = 262_144) -> Iterator:
    """Yield bounded arrays of little-endian int16 I,Q, with zero-filled gaps."""
    if not isinstance(plan, WaveformPlan):
        raise ValueError("plan must be a WaveformPlan")
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    yield from _iter_payload_iq_chunks(plan.config,
        ((plan.action_payload, plan.action_repetitions),
         (plan.release_payload, plan.release_repetitions)), chunk_samples=chunk_samples)


def _iter_payload_iq_chunks(config: WaveformConfig, phases, *, chunk_samples: int) -> Iterator:
    """Render validated payload phases; public plan types validate their own rules."""
    np = _numpy()
    templates = {}
    for payload, _ in phases:
        for channel in config.channels_hz:
            pulse = synthesize_frame(payload, sample_rate_hz=config.sample_rate_hz,
                deviation_hz=config.deviation_hz, gaussian_bt=config.gaussian_bt,
                lead_in_us=config.lead_in_us, ramp_us=config.ramp_us,
                amplitude=config.amplitude, carrier_offset_hz=channel-config.center_hz)
            slot = np.zeros((config.slot_samples, 2), dtype="<i2")
            slot[:len(pulse), 0] = np.rint(pulse.real * 2048).astype("<i2")
            slot[:len(pulse), 1] = np.rint(pulse.imag * 2048).astype("<i2")
            templates[(payload, channel)] = slot
    buffer = np.empty((chunk_samples, 2), dtype="<i2")
    filled = 0
    for payload, repetitions in phases:
        for _ in range(repetitions):
            for channel in config.channels_hz:
                slot = templates[(payload, channel)]
                offset = 0
                while offset < len(slot):
                    count = min(len(slot)-offset, chunk_samples-filled)
                    buffer[filled:filled+count] = slot[offset:offset+count]
                    filled += count
                    offset += count
                    if filled == chunk_samples:
                        yield buffer
                        buffer = np.empty((chunk_samples, 2), dtype="<i2")
                        filled = 0
    if filled:
        yield buffer[:filled]


def write_waveform(path: str | Path, plan: WaveformPlan, *, overwrite: bool = False,
                   chunk_samples: int = 262_144, include_private: bool = False) -> dict:
    """Write a bounded offline artifact and return parameters/hash, never TX.

    Existing files are preserved unless overwrite=True is explicitly supplied.
    Metadata redacts the installation identity by default; the IQ artifact
    itself necessarily contains it and must remain private.
    """
    if not isinstance(plan, WaveformPlan):
        raise ValueError("plan must be a WaveformPlan")
    if not isinstance(overwrite, bool) or not isinstance(include_private, bool):
        raise ValueError("overwrite and include_private must be booleans")
    _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    _numpy()
    artifact = _write_iq_chunks(path, iter_iq_chunks(plan, chunk_samples=chunk_samples),
                               sample_count=plan.sample_count, overwrite=overwrite)
    return dict(plan.as_dict(include_private=include_private), **artifact)


def _write_iq_chunks(path: str | Path, chunks, *, sample_count: int, overwrite: bool) -> dict:
    """Write already-validated offline samples without knowing a command type."""
    path = Path(path)
    checksum = hashlib.sha256()
    written = 0
    with path.open("wb" if overwrite else "xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        for chunk in chunks:
            data = chunk.tobytes()
            stream.write(data)
            checksum.update(data)
            written += len(data)
    if written != sample_count * 4:
        raise RuntimeError("waveform length does not match plan")
    return {"byte_count": written, "sha256": checksum.hexdigest()}
