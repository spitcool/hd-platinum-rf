# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline native primary-position synthesis with per-packet channel rotation.

The 0x50 command and 0x32 followup bodies retain the requested position byte.
An idle start in phase 2, initial channel, and phase packet counts are explicit
synthesis assumptions;
isolated original-code checks do not establish exact interrupt epochs or shade
acceptance. This module adds no transmitter, backend, or operation grant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .rf import REMOTE_CHANNELS, REMOTE_FREQUENCIES_HZ
from .rf_positions import build_position_payloads
from .rf_waveform import WaveformConfig, _integer, _numpy, _write_iq_chunks, synthesize_frame


NOMINAL_SLOT_US = 200.5
SAMPLE_RATE_HZ = 48_000_000
CENTER_HZ = 2_452_000_000
MAX_DURATION_SECONDS = 2.0
MODEL_NOTE = (
    "Offline diagnostic synthesis, not hardware qualified. An idle start in "
    "phase 2 without a prelude, initial channel, and phase packet counts are "
    "explicit assumptions. The 200.5 us grid is nominal "
    "firmware timing; independent timer epochs and main-loop service do not "
    "establish exact original packet counts. Gaussian BT, deviation and pulse "
    "envelope remain provisional. Command/followup labels do not assert motor "
    "direction, rail meaning, actual position feedback, or stop behavior."
)


@dataclass(frozen=True)
class NativePositionEvent:
    """One native packet; its payload contains a private installation identity."""

    ordinal: int
    start_sample: int
    channel_hz: int
    phase: str
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class NativePositionPlan:
    """One command/followup train with explicit initial state and phase counts.

    ``prior_channel`` is the RF_CH number (33, 52 or 71) before the first
    rotation. Counts include each phase-entry pulse, not timer ticks or full
    channel cycles. This models an assumed idle start in phase 2 with no
    phase-1 prelude. The position body has no alternating Jog-style variant.
    """

    room_rf_id: bytes = field(repr=False)
    mask: int
    position: int
    prior_channel: int
    command_frame_count: int
    followup_frame_count: int
    slot_us: float
    config: WaveformConfig = field(init=False)
    _payloads: tuple[bytes, bytes] = field(init=False, repr=False)

    def __post_init__(self):
        payloads = build_position_payloads(self.room_rf_id, self.mask, self.position)
        object.__setattr__(self, "room_rf_id", payloads[0][:2])
        object.__setattr__(self, "mask", payloads[0][3])
        object.__setattr__(self, "position", payloads[0][4])
        object.__setattr__(self, "_payloads", payloads)
        channel = _integer(self.prior_channel, "prior channel", 0, 125)
        if channel not in REMOTE_CHANNELS:
            raise ValueError("prior channel must be 33, 52 or 71")
        object.__setattr__(self, "prior_channel", channel)
        for name in ("command_frame_count", "followup_frame_count"):
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
            raise ValueError("native position plan exceeds the two-second duration limit")

    @property
    def command_payload(self) -> bytes:
        return self._payloads[0]

    @property
    def followup_payload(self) -> bytes:
        return self._payloads[1]

    @property
    def frame_count(self) -> int:
        return self.command_frame_count + self.followup_frame_count

    @property
    def sample_count(self) -> int:
        return self.frame_count * self.config.slot_samples

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / SAMPLE_RATE_HZ

    def iter_events(self) -> Iterator[NativePositionEvent]:
        """Rotate before every packet, retaining channel phase at the boundary."""
        channel_index = REMOTE_CHANNELS.index(self.prior_channel)
        for ordinal in range(self.frame_count):
            if ordinal < self.command_frame_count:
                phase, payload = "command", self.command_payload
            else:
                phase, payload = "followup", self.followup_payload
            channel_index = (channel_index + 1) % len(REMOTE_CHANNELS)
            yield NativePositionEvent(ordinal, ordinal * self.config.slot_samples,
                REMOTE_FREQUENCIES_HZ[channel_index], phase, payload)

    def as_dict(self, *, include_private: bool = False) -> dict:
        if type(include_private) is not bool:
            raise ValueError("include_private must be a boolean")

        def body(value):
            return value.hex() if include_private else "xxxx" + value[2:].hex()

        return {
            "candidate_only": True, "hardware_qualified": False,
            "operation": "native_primary_position",
            "format": "SC16Q11 little-endian interleaved I,Q",
            "sample_rate_hz": SAMPLE_RATE_HZ, "center_hz": CENTER_HZ,
            "channels_hz": list(REMOTE_FREQUENCIES_HZ), "bit_rate_hz": 2_000_000,
            "framing": "shockburst", "frame_bits": 88,
            "prior_channel": self.prior_channel,
            "initial_phase": 2, "idle_start_assumed": True, "prelude_included": False,
            "command_frame_count": self.command_frame_count,
            "followup_frame_count": self.followup_frame_count,
            "phase_counts_are_assumed": True, "slot_us": self.slot_us,
            "slot_samples": self.config.slot_samples, "frame_count": self.frame_count,
            "sample_count": self.sample_count, "duration_seconds": self.duration_seconds,
            "command_seconds": self.command_frame_count * self.config.slot_samples / SAMPLE_RATE_HZ,
            "followup_seconds": self.followup_frame_count * self.config.slot_samples / SAMPLE_RATE_HZ,
            "max_duration_seconds": MAX_DURATION_SECONDS,
            "command_payload": body(self.command_payload),
            "followup_payload": body(self.followup_payload),
            "shade_mask": self.mask, "position": self.position,
            "deviation_hz": self.config.deviation_hz, "gaussian_bt": self.config.gaussian_bt,
            "amplitude": self.config.amplitude, "lead_in_us": self.config.lead_in_us,
            "ramp_us": self.config.ramp_us, "pulse_samples": self.config.pulse_samples,
            "model_note": MODEL_NOTE,
        }


def build_native_position_plan(room_rf_id, mask, position, *, prior_channel,
                               command_frame_count, followup_frame_count,
                               slot_us) -> NativePositionPlan:
    """Plan offline only; no initial channel, phase count, or grid is inferred."""
    return NativePositionPlan(room_rf_id, mask, position, prior_channel,
                              command_frame_count, followup_frame_count, slot_us)


def iter_native_position_iq_chunks(plan: NativePositionPlan, *,
                                   chunk_samples: int = 262_144) -> Iterator:
    """Render bounded SC16Q11 chunks from six body/channel pulse templates."""
    if not isinstance(plan, NativePositionPlan):
        raise ValueError("plan must be a NativePositionPlan")
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    np = _numpy()
    config = plan.config
    templates = {}
    for payload in (plan.command_payload, plan.followup_payload):
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


def write_native_position_waveform(path: str | Path, plan: NativePositionPlan, *,
                                   chunk_samples: int = 262_144,
                                   include_private: bool = False) -> dict:
    """Write new mode-0600 offline IQ; refuse existing paths and redact metadata.

    The waveform itself contains the room identity regardless of redaction.
    No operation grant or hardware action is implied by creating this file.
    """
    if not isinstance(plan, NativePositionPlan):
        raise ValueError("plan must be a NativePositionPlan")
    metadata = plan.as_dict(include_private=include_private)
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    _numpy()
    artifact = _write_iq_chunks(path,
        iter_native_position_iq_chunks(plan, chunk_samples=chunk_samples),
        sample_count=plan.sample_count, overwrite=False)
    return dict(metadata, **artifact)
