# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline native secondary-position planning; no transmitter or grants.

Original feature 18 (decimal, 0x12) produces held code 0x6D and followup 0x32.
The source fixtures establish fixed bodies and channel continuity for flags 1,
native context C9A=6 and an idle phase-2 start. Packet counts, timing and the
initial channel remain explicit synthesis assumptions, not physical evidence.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .rf_native_position import (
    MODEL_NOTE, _NativePositionPlanCore, _iter_native_position_iq_chunks,
    _write_native_position_waveform,
)
from .rf_positions import build_position_payloads


def build_native_secondary_position_payloads(room_rf_id: bytes, shade_mask: int,
                                              position: int) -> tuple[bytes, bytes]:
    """Build fixed feature-18 bodies using a two-byte ID and one-hot mask.

    Raw values 0..255 are retained verbatim. Their physical rail direction,
    endpoint meaning and travel calibration require separate observation.
    """
    command, followup = build_position_payloads(room_rf_id, shade_mask, position)
    return command[:2] + b"\x6d" + command[3:], followup


@dataclass(frozen=True)
class NativeSecondaryPositionPlan(_NativePositionPlanCore):
    """Secondary feature-18 plan, separate from the primary plan type."""

    _build_payloads = staticmethod(build_native_secondary_position_payloads)
    _operation = "native_secondary_position"
    _model_note = MODEL_NOTE + (
        " Secondary feature 18 (0x12) source fixtures use flags 1 and C9A=6; "
        "they do not establish physical secondary-rail acceptance or interlocks."
    )

    def as_dict(self, *, include_private: bool = False) -> dict:
        return dict(super().as_dict(include_private=include_private),
                    feature_decimal=18, feature_hex="12", native_context_c9a=6)


def build_native_secondary_position_plan(room_rf_id, mask, position, *, prior_channel,
                                         command_frame_count, followup_frame_count,
                                         slot_us) -> NativeSecondaryPositionPlan:
    """Plan an offline secondary train; infer no scheduling inputs."""
    return NativeSecondaryPositionPlan(room_rf_id, mask, position, prior_channel,
                                       command_frame_count, followup_frame_count, slot_us)


def iter_native_secondary_position_iq_chunks(plan: NativeSecondaryPositionPlan, *,
                                             chunk_samples: int = 262_144) -> Iterator:
    """Yield bounded SC16Q11 chunks for a secondary plan only."""
    if not isinstance(plan, NativeSecondaryPositionPlan):
        raise ValueError("plan must be a NativeSecondaryPositionPlan")
    yield from _iter_native_position_iq_chunks(plan, chunk_samples=chunk_samples)


def write_native_secondary_position_waveform(path: str | Path,
                                             plan: NativeSecondaryPositionPlan, *,
                                             chunk_samples: int = 262_144,
                                             include_private: bool = False) -> dict:
    """Write new private offline IQ, rejecting other plan types and existing files.

    The waveform contains the identity even when metadata is redacted. Writing
    a file neither authorizes nor performs a secondary-rail transmission.
    """
    if not isinstance(plan, NativeSecondaryPositionPlan):
        raise ValueError("plan must be a NativeSecondaryPositionPlan")
    return _write_native_position_waveform(path, plan, chunk_samples=chunk_samples,
                                           include_private=include_private)
