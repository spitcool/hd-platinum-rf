# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline candidate position payloads and waveforms; no radio access.

The five-byte layout is supported by bridge-command-correlated captures of
positions 0, 128, and 255 across two room identities. Other targets and values
still need validation, and the emitting bridge/repeater component and SDR-to-
shade interoperability remain unproven.
The 0x50 and 0x32 phases are called command and followup without asserting
their device-side semantics. Repetition defaults and RF shaping are provisional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .rf_waveform import (
    WaveformConfig,
    _integer,
    _iter_payload_iq_chunks,
    _numpy,
    _write_iq_chunks,
)


POSITION_MODEL_NOTE = (
    "Experimental synthesis: positions 0, 128, and 255 were observed in "
    "bridge-command-correlated RF sequences across two room identities. Modes 0x50/0x32 "
    "are command/followup labels with unproven device-side semantics. "
    "Repetition counts, Gaussian BT, deviation, and timing are provisional, "
    "not universal parameters or verified shade interoperability."
)


def build_position_payloads(room_rf_id: bytes, shade_mask: int,
                            position: int) -> tuple[bytes, bytes]:
    """Return room ID + mode + one-hot shade mask + candidate position.

    The mask is already encoded: values 1, 2, 4, ..., 128 select one bit.
    It is never interpreted as a handheld group number. The position byte is
    accepted over 0..255; captures establish 0, 128, and 255, not every value.
    """
    if not isinstance(room_rf_id, (bytes, bytearray)) or len(room_rf_id) != 2:
        raise ValueError("room RF ID must contain exactly two bytes")
    shade_mask = _integer(shade_mask, "shade mask", 1, 128)
    if shade_mask & (shade_mask - 1):
        raise ValueError("shade mask must contain exactly one set bit")
    position = _integer(position, "position", 0, 255)
    identity = bytes(room_rf_id)
    suffix = bytes((shade_mask, position))
    return identity + b"\x50" + suffix, identity + b"\x32" + suffix


@dataclass(frozen=True)
class PositionWaveformPlan:
    """Validated candidate plan, separate from strict handheld command plans."""

    config: WaveformConfig
    command_payload: bytes = field(repr=False)
    followup_payload: bytes = field(repr=False)
    command_repetitions: int = 2100
    followup_repetitions: int = 425

    def __post_init__(self) -> None:
        if not isinstance(self.config, WaveformConfig):
            raise ValueError("config must be a WaveformConfig")
        for name in ("command_payload", "followup_payload"):
            value = getattr(self, name)
            if not isinstance(value, (bytes, bytearray)) or len(value) != 5:
                raise ValueError(f"{name} must contain exactly five bytes")
            object.__setattr__(self, name, bytes(value))
        command = self.command_payload
        expected = build_position_payloads(command[:2], command[3], command[4])
        if (command, self.followup_payload) != expected:
            raise ValueError("command/followup must share room ID, shade mask, and position with modes 0x50/0x32")
        for name, minimum in (("command_repetitions", 1), ("followup_repetitions", 0)):
            object.__setattr__(self, name, _integer(getattr(self, name), name, minimum, 10_000))
        if self.duration_seconds > self.config.max_airtime_seconds:
            raise ValueError("planned waveform exceeds the configured airtime limit")

    @property
    def frame_count(self) -> int:
        return (self.command_repetitions + self.followup_repetitions) * len(self.config.channels_hz)

    @property
    def sample_count(self) -> int:
        return self.frame_count * self.config.slot_samples

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.config.sample_rate_hz

    def as_dict(self, *, include_private: bool = False) -> dict:
        if not isinstance(include_private, bool):
            raise ValueError("include_private must be a boolean")
        config = self.config
        payload = lambda value: value.hex() if include_private else "xxxx" + value.hex()[4:]
        return {
            "candidate_only": True,
            "format": "SC16Q11 little-endian interleaved I,Q",
            "sample_rate_hz": config.sample_rate_hz,
            "center_hz": config.center_hz,
            "channels_hz": list(config.channels_hz),
            "bit_rate_hz": 2_000_000,
            "frame_bits": 88,
            "framing": "shockburst",
            "command_payload": payload(self.command_payload),
            "followup_payload": payload(self.followup_payload),
            "shade_mask": self.command_payload[3],
            "position": self.command_payload[4],
            "command_repetitions": self.command_repetitions,
            "followup_repetitions": self.followup_repetitions,
            "frame_count": self.frame_count,
            "sample_count": self.sample_count,
            "duration_seconds": self.duration_seconds,
            "deviation_hz": config.deviation_hz,
            "gaussian_bt": config.gaussian_bt,
            "amplitude": config.amplitude,
            "lead_in_us": config.lead_samples / config.sample_rate_hz * 1e6,
            "ramp_us": config.ramp_samples / config.sample_rate_hz * 1e6,
            "pulse_us": config.pulse_samples / config.sample_rate_hz * 1e6,
            "slot_us": config.slot_samples / config.sample_rate_hz * 1e6,
            "max_airtime_seconds": config.max_airtime_seconds,
            "model_note": POSITION_MODEL_NOTE,
        }


def build_position_plan(room_rf_id: bytes, shade_mask: int, position: int, *,
                        config: WaveformConfig | None = None,
                        command_repetitions: int = 2100,
                        followup_repetitions: int = 425) -> PositionWaveformPlan:
    """Plan offline sequential channel cycles followed by the 0x32 phase.

    Defaults produce 2,525 frames per channel over 1.77255 seconds. These
    counts approximate recovered observations and are not known protocol limits.
    """
    command, followup = build_position_payloads(room_rf_id, shade_mask, position)
    if config is None:
        config = WaveformConfig(slot_us=234, deviation_hz=320_000,
                                lead_in_us=49, ramp_us=2)
    return PositionWaveformPlan(config, command, followup,
                                command_repetitions, followup_repetitions)


def iter_position_iq_chunks(plan: PositionWaveformPlan, *,
                            chunk_samples: int = 262_144) -> Iterator:
    """Yield bounded SC16Q11 arrays; input must be a validated position plan."""
    if not isinstance(plan, PositionWaveformPlan):
        raise ValueError("plan must be a PositionWaveformPlan")
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    yield from _iter_payload_iq_chunks(plan.config,
        ((plan.command_payload, plan.command_repetitions),
         (plan.followup_payload, plan.followup_repetitions)), chunk_samples=chunk_samples)


def write_position_waveform(path: str | Path, plan: PositionWaveformPlan, *,
                            overwrite: bool = False, chunk_samples: int = 262_144,
                            include_private: bool = False) -> dict:
    """Write private candidate IQ and return redacted metadata/hash; never TX.

    Existing files are preserved unless overwrite=True. The IQ bytes contain
    the installation identity even when the returned metadata redacts it.
    """
    if not isinstance(plan, PositionWaveformPlan):
        raise ValueError("plan must be a PositionWaveformPlan")
    if not isinstance(overwrite, bool) or not isinstance(include_private, bool):
        raise ValueError("overwrite and include_private must be booleans")
    chunk_samples = _integer(chunk_samples, "chunk samples", 1, 4_194_304)
    _numpy()
    artifact = _write_iq_chunks(path,
        iter_position_iq_chunks(plan, chunk_samples=chunk_samples),
        sample_count=plan.sample_count, overwrite=overwrite)
    return dict(plan.as_dict(include_private=include_private), **artifact)
