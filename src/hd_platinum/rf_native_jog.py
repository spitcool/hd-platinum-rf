# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline, finite native Jog synthesis with explicit scheduling assumptions.

The payload/refresh/channel transitions follow isolated original-code checks.
The caller chooses initial state and phase packet counts: interrupt epochs and
physical reset state are not established. No radio, backend, or grant is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .rf import REMOTE_CHANNELS, REMOTE_FREQUENCIES_HZ
from .rf_waveform import WaveformConfig, _integer, _numpy, _write_iq_chunks, synthesize_frame


NOMINAL_SLOT_US = 200.5
SAMPLE_RATE_HZ = 48_000_000
CENTER_HZ = 2_452_000_000
MAX_DURATION_SECONDS = 2.0
MODEL_NOTE = (
    "Offline diagnostic synthesis, not hardware qualified. Initial channel and "
    "alternation state and phase packet counts are explicit assumptions. The "
    "200.5 us grid is nominal firmware timing; independent timer epochs and "
    "main-loop service do not establish exact original packet counts. Gaussian "
    "BT, deviation and pulse envelope remain provisional."
)


def build_native_jog_payloads(room_rf_id, mask) -> tuple[bytes, bytes, bytes]:
    """Return verified main, alternate and tail bodies for one shade mask."""
    if not isinstance(room_rf_id, (bytes, bytearray)) or len(room_rf_id) != 2:
        raise ValueError("room RF ID must contain exactly two bytes")
    mask = _integer(mask, "shade mask", 1, 128)
    if mask & (mask - 1):
        raise ValueError("shade mask must contain exactly one set bit")
    identity = bytes(room_rf_id)
    return (identity + bytes((0x6A, mask, 1)), identity + bytes((0x20, mask, 0x6A)),
            identity + bytes((0x32, mask, 1)))


@dataclass(frozen=True)
class NativeJogEvent:
    """One packet; its payload contains the private installation identity."""

    ordinal: int
    start_sample: int
    channel_hz: int
    phase: str
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class NativeJogPlan:
    """A single assumed held/tail train; every scheduling input is required.

    ``prior_channel`` is the previous RF_CH number (33, 52 or 71), before the
    first rotation. ``prior_alternate`` is the previous alternation bit, before
    the held-phase builder toggles it. Neither has a physical-state default.
    Packet counts include the phase-entry pulse and are not timer tick counts.
    """

    room_rf_id: bytes = field(repr=False)
    mask: int
    prior_channel: int
    prior_alternate: int
    held_frame_count: int
    tail_frame_count: int
    slot_us: float
    config: WaveformConfig = field(init=False)
    _payloads: tuple[bytes, bytes, bytes] = field(init=False, repr=False)

    def __post_init__(self):
        payloads = build_native_jog_payloads(self.room_rf_id, self.mask)
        object.__setattr__(self, "room_rf_id", payloads[0][:2])
        object.__setattr__(self, "mask", payloads[0][3])
        object.__setattr__(self, "_payloads", payloads)
        channel = _integer(self.prior_channel, "prior channel", 0, 125)
        if channel not in REMOTE_CHANNELS:
            raise ValueError("prior channel must be 33, 52 or 71")
        object.__setattr__(self, "prior_channel", channel)
        object.__setattr__(self, "prior_alternate", _integer(self.prior_alternate, "prior alternate", 0, 1))
        for name in ("held_frame_count", "tail_frame_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), name, 1, 10_000))
        if type(self.slot_us) not in (int, float) or self.slot_us != NOMINAL_SLOT_US:
            raise ValueError("slot_us must explicitly select the nominal 200.5 us grid")
        object.__setattr__(self, "slot_us", NOMINAL_SLOT_US)
        object.__setattr__(self, "config", WaveformConfig(
            sample_rate_hz=SAMPLE_RATE_HZ, center_hz=CENTER_HZ,
            channels_hz=REMOTE_FREQUENCIES_HZ, slot_us=NOMINAL_SLOT_US,
            deviation_hz=320_000, gaussian_bt=.5, lead_in_us=49, ramp_us=2,
            amplitude=.5, max_airtime_seconds=MAX_DURATION_SECONDS))
        if self.duration_seconds > MAX_DURATION_SECONDS:
            raise ValueError("native Jog plan exceeds the two-second duration limit")

    @property
    def main_payload(self) -> bytes:
        return self._payloads[0]

    @property
    def alternate_payload(self) -> bytes:
        return self._payloads[1]

    @property
    def tail_payload(self) -> bytes:
        return self._payloads[2]

    @property
    def frame_count(self) -> int:
        return self.held_frame_count + self.tail_frame_count

    @property
    def sample_count(self) -> int:
        return self.frame_count * self.config.slot_samples

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / SAMPLE_RATE_HZ

    def iter_events(self) -> Iterator[NativeJogEvent]:
        """Yield packets without resetting channel phase at any body boundary."""
        channel_index = REMOTE_CHANNELS.index(self.prior_channel)
        alternate = 1 - self.prior_alternate
        remaining = 20 if alternate else 100
        for ordinal in range(self.frame_count):
            if ordinal < self.held_frame_count:
                # AACC decrements before CE. On expiry, 7D38 toggles and loads
                # the new payload before that same pulse. The initial block
                # therefore has 19 or 99 packets, subsequent blocks 20/100.
                remaining -= 1
                if remaining == 0:
                    alternate = 1 - alternate
                    remaining = 20 if alternate else 100
                payload = self.alternate_payload if alternate else self.main_payload
                phase = "held"
            else:
                # Phase 3 retains the refresh machinery, but original code
                # returns this same body in both alternation states.
                payload, phase = self.tail_payload, "tail"
            channel_index = (channel_index + 1) % len(REMOTE_CHANNELS)
            yield NativeJogEvent(ordinal, ordinal * self.config.slot_samples,
                                 REMOTE_FREQUENCIES_HZ[channel_index], phase, payload)

    def as_dict(self, *, include_private: bool = False) -> dict:
        if type(include_private) is not bool:
            raise ValueError("include_private must be a boolean")
        def body(value):
            return value.hex() if include_private else "xxxx" + value[2:].hex()
        return {
            "candidate_only": True, "hardware_qualified": False,
            "operation": "native_jog", "format": "SC16Q11 little-endian interleaved I,Q",
            "sample_rate_hz": SAMPLE_RATE_HZ, "center_hz": CENTER_HZ,
            "channels_hz": list(REMOTE_FREQUENCIES_HZ), "bit_rate_hz": 2_000_000,
            "framing": "shockburst", "frame_bits": 88,
            "prior_channel": self.prior_channel, "prior_alternate": self.prior_alternate,
            "held_frame_count": self.held_frame_count, "tail_frame_count": self.tail_frame_count,
            "phase_counts_are_assumed": True, "slot_us": self.slot_us,
            "slot_samples": self.config.slot_samples, "frame_count": self.frame_count,
            "sample_count": self.sample_count, "duration_seconds": self.duration_seconds,
            "held_seconds": self.held_frame_count * self.config.slot_samples / SAMPLE_RATE_HZ,
            "tail_seconds": self.tail_frame_count * self.config.slot_samples / SAMPLE_RATE_HZ,
            "max_duration_seconds": MAX_DURATION_SECONDS,
            "main_payload": body(self.main_payload), "alternate_payload": body(self.alternate_payload),
            "tail_payload": body(self.tail_payload),
            "deviation_hz": self.config.deviation_hz, "gaussian_bt": self.config.gaussian_bt,
            "amplitude": self.config.amplitude, "lead_in_us": self.config.lead_in_us,
            "ramp_us": self.config.ramp_us, "pulse_samples": self.config.pulse_samples,
            "model_note": MODEL_NOTE,
        }


def build_native_jog_plan(room_rf_id, mask, *, prior_channel, prior_alternate,
                          held_frame_count, tail_frame_count, slot_us) -> NativeJogPlan:
    """Build an offline plan; no initial state, phase count or grid is inferred."""
    return NativeJogPlan(room_rf_id, mask, prior_channel, prior_alternate,
                         held_frame_count, tail_frame_count, slot_us)


def iter_native_jog_iq_chunks(plan: NativeJogPlan, *, chunk_samples: int = 262_144) -> Iterator:
    """Render one pulse at a time with bounded templates and output buffers."""
    if not isinstance(plan, NativeJogPlan):
        raise ValueError("plan must be a NativeJogPlan")
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    np = _numpy()
    config = plan.config
    templates = {}
    for payload in (plan.main_payload, plan.alternate_payload, plan.tail_payload):
        for channel in config.channels_hz:
            pulse = synthesize_frame(payload, sample_rate_hz=SAMPLE_RATE_HZ,
                deviation_hz=config.deviation_hz, gaussian_bt=config.gaussian_bt,
                lead_in_us=config.lead_in_us, ramp_us=config.ramp_us, amplitude=config.amplitude,
                carrier_offset_hz=channel - CENTER_HZ)
            slot = np.zeros((config.slot_samples, 2), dtype="<i2")
            slot[:len(pulse), 0] = np.rint(pulse.real * 2048).astype("<i2")
            slot[:len(pulse), 1] = np.rint(pulse.imag * 2048).astype("<i2")
            templates[(payload, channel)] = slot
    buffer = np.empty((chunk_samples, 2), dtype="<i2")
    filled = 0
    for event in plan.iter_events():
        slot = templates[(event.payload, event.channel_hz)]
        offset = 0
        while offset < len(slot):
            count = min(len(slot) - offset, chunk_samples - filled)
            buffer[filled:filled + count] = slot[offset:offset + count]
            filled += count
            offset += count
            if filled == chunk_samples:
                yield buffer
                buffer = np.empty((chunk_samples, 2), dtype="<i2")
                filled = 0
    if filled:
        yield buffer[:filled]


def write_native_jog_waveform(path: str | Path, plan: NativeJogPlan, *,
                              chunk_samples: int = 262_144, include_private: bool = False) -> dict:
    """Write a new mode-0600 offline IQ artifact; existing paths are refused."""
    if not isinstance(plan, NativeJogPlan):
        raise ValueError("plan must be a NativeJogPlan")
    metadata = plan.as_dict(include_private=include_private)
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    _numpy()
    artifact = _write_iq_chunks(path, iter_native_jog_iq_chunks(plan, chunk_samples=chunk_samples),
                                sample_count=plan.sample_count, overwrite=False)
    return dict(metadata, **artifact)
