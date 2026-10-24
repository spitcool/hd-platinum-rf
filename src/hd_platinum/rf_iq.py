# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline, bounded-memory GFSK analysis of little-endian SC16Q11 recordings.

This experimental receiver searches the known Platinum address at 2 Mbit/s.
It tests both bit polarities and both framing hypotheses, accepts only correct
preambles and CRCs, and merges repeated detections from timing/threshold trials.
It does not transmit or infer sample continuity from a raw IQ file. NumPy and
SciPy are optional dependencies, imported only when decoding is requested.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

from .rf import REMOTE_ADDRESS, REMOTE_FREQUENCIES_HZ, decode_remote_payload
from .rf_frames import FRAMINGS, parse_frame


DEMOD_RATE = 8_000_000
BIT_RATE = 2_000_000
THRESHOLDS_HZ = (-150_000, -75_000, 0, 75_000, 150_000)


def _dependencies():
    try:
        import numpy as np
        from scipy import signal
    except ImportError as exc:
        raise ValueError("IQ decoding requires the optional analysis dependencies: pip install '.[analysis]'") from exc
    return np, signal


def _finite(value: float, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _merge_detections(hits: list[dict]) -> list[dict]:
    """Keep one observation per frame/hypothesis across threshold and phase trials.

    Distinct CRC-valid payloads or framing hypotheses are deliberately retained.
    Two microseconds is much shorter than a complete supported packet.
    """
    grouped: dict[tuple, list[dict]] = {}
    for hit in hits:
        key = (hit['channel_hz'], hit['framing'], hit['payload_hex'], hit['crc_hex'])
        grouped.setdefault(key, []).append(hit)
    merged = []
    for group in grouped.values():
        group.sort(key=lambda h: h['address_time_s'])
        cluster = []
        for hit in group:
            if cluster and hit['address_time_s'] - cluster[0]['address_time_s'] > 2e-6:
                best = max(cluster, key=lambda h: (h['carrier_supported'], h['decision_margin_hz']))
                merged.append(dict(best, detection_trials=sum(h.get('detection_trials', 1) for h in cluster)))
                cluster = []
            cluster.append(hit)
        if cluster:
            best = max(cluster, key=lambda h: (h['carrier_supported'], h['decision_margin_hz']))
            merged.append(dict(best, detection_trials=sum(h.get('detection_trials', 1) for h in cluster)))
    return sorted(merged, key=lambda h: (h['address_time_s'], h['channel_hz'], h['framing']))


def _decode_channel(iq, *, input_start: int, sample_rate: int, center_hz: float,
                    channel_hz: int, core_start: int, core_end: int) -> list[dict]:
    np, signal = _dependencies()
    offset = channel_hz - center_hz
    if offset:
        oscillator = np.exp(-2j * np.pi * offset / sample_rate * np.arange(len(iq))).astype(np.complex64)
        iq = iq * oscillator
    decimation = sample_rate // DEMOD_RATE
    taps = signal.firwin(20 * decimation + 1, 2_000_000, fs=sample_rate)
    if decimation == 1:
        filtered = signal.convolve(iq, taps, mode='same')
    else:
        filtered = signal.resample_poly(iq, 1, decimation, window=taps)
    frequency = np.angle(filtered[1:] * np.conj(filtered[:-1])) * DEMOD_RATE / (2 * np.pi)
    power = abs(filtered) ** 2
    needle = ''.join(f'{byte:08b}' for byte in REMOTE_ADDRESS).encode('ascii')
    hits = []
    for phase in range(4):
        soft = frequency[phase::4]
        for threshold in THRESHOLDS_HZ:
            for polarity in (1, -1):
                bits = (48 + (((soft - threshold) * polarity) > 0)).astype(np.uint8).tobytes()
                at = bits.find(needle, 8)
                while at >= 0:
                    # Time denotes the discriminator decision for the first
                    # address bit, not an independently calibrated RF edge.
                    decision = input_start + (phase + 4 * at + .5) * decimation
                    if core_start <= decision < core_end:
                        fragment = bits[at-8:at+89].decode('ascii')
                        for framing in FRAMINGS:
                            frame = parse_frame(fragment, framing=framing)
                            if frame is not None and frame.crc_valid and frame.preamble_matches:
                                command = decode_remote_payload(frame.payload)
                                stop = at + frame.frame_bit_length - 8
                                margin = float(np.percentile(abs(soft[at:stop] - threshold), 20))
                                positions = phase + 4 * np.arange(at, stop)
                                interior_power = float(np.median(power[positions[8:-16]]))
                                tail_power = float(np.median(power[positions[-8:]]))
                                tail_ratio = tail_power / max(interior_power, 1e-30)
                                hits.append({
                                    'address_time_s': decision / sample_rate,
                                    'preamble_time_s_estimate': decision / sample_rate - 8 / BIT_RATE,
                                    'channel_hz': channel_hz,
                                    'framing': framing,
                                    'frame_bits': frame.frame_bit_length,
                                    'address_hex': frame.address.hex(),
                                    'payload_hex': frame.payload.hex(),
                                    'remote_id': command.remote_id.hex(),
                                    'mode': command.mode,
                                    'group_mask': command.group_mask,
                                    'action_code': command.action_code,
                                    'action': command.action,
                                    'crc_hex': f'{frame.crc_received:04x}',
                                    'crc_valid': True,
                                    'preamble_matches': True,
                                    'pcf_payload_length': frame.pcf_payload_length,
                                    'pid': frame.pid,
                                    'no_ack': frame.no_ack,
                                    'polarity': polarity,
                                    'threshold_hz': threshold,
                                    'phase': phase,
                                    'decision_margin_hz': margin,
                                    'rf_tail_power_ratio': tail_ratio,
                                    'carrier_supported': tail_ratio >= .1,
                                })
                    at = bits.find(needle, at + 1)
    return hits


def decode_iq_file(
    path: str | Path, *, sample_rate_hz: int, center_hz: float,
    channels_hz: Iterable[int] = REMOTE_FREQUENCIES_HZ,
    start_seconds: float = 0, duration_seconds: float | None = None,
    chunk_seconds: float = .1,
    progress: Callable[[float, float], None] | None = None,
) -> dict:
    """Decode an interval, returning private payloads and a reproducible summary.

    Input rates must be integer multiples of 8 MS/s, at most 256 MS/s. The caller must explicitly
    supply the recording's rate and center; no hardware is opened. Chunks are
    padded so packets crossing chunk boundaries are available in full. Frames
    with an address decision in the requested interval are returned once.
    A CRC-valid frame count is not a packet-error-rate measurement: packets with
    damaged sync/address bits are not counted as attempted frames.
    """
    rate = _finite(sample_rate_hz, 'sample rate')
    center = _finite(center_hz, 'center frequency')
    start = _finite(start_seconds, 'start')
    chunk = _finite(chunk_seconds, 'chunk duration')
    if rate < DEMOD_RATE or rate > 256_000_000 or rate % DEMOD_RATE:
        raise ValueError('sample rate must be an integer multiple of 8000000 within 8..256 MS/s')
    rate = int(rate)
    if center <= 0 or start < 0 or not .001 <= chunk <= 1:
        raise ValueError('center must be positive, start nonnegative, and chunk duration within 0.001..1 s')
    channels = tuple(int(_finite(ch, 'channel frequency')) for ch in channels_hz)
    if not channels or len(channels) != len(set(channels)):
        raise ValueError('at least one distinct channel is required')
    if any(ch <= 0 or abs(ch-center) + 2_000_000 > rate/2 for ch in channels):
        raise ValueError('each channel and its 2 MHz filter margin must fit inside the recording bandwidth')
    path = Path(path)
    size = path.stat().st_size
    if size == 0 or size % 4:
        raise ValueError('input must contain complete SC16Q11 complex samples (four bytes each)')
    total_samples = size // 4
    if start >= total_samples / rate:
        raise ValueError('start lies beyond the recording')
    begin = round(start * rate)
    if begin >= total_samples:
        raise ValueError('start lies beyond the recording')
    if duration_seconds is None:
        end = total_samples
    else:
        duration = _finite(duration_seconds, 'duration')
        if duration <= 0:
            raise ValueError('duration must be positive')
        remaining = (total_samples-begin) / rate
        end = total_samples if duration >= remaining else begin + round(duration * rate)
        if end <= begin:
            raise ValueError('duration must contain at least one sample')
    np, _ = _dependencies()
    raw = np.memmap(path, dtype='<i2', mode='r', shape=(total_samples, 2))
    chunk_samples = round(chunk * rate)
    padding = round(.0001 * rate)
    hits = []
    raw_trials = 0
    for core_start in range(begin, end, chunk_samples):
        core_end = min(end, core_start + chunk_samples)
        left = max(0, core_start-padding)
        right = min(total_samples, core_end+padding)
        values = raw[left:right]
        iq = values[:, 0].astype(np.float32) + 1j * values[:, 1].astype(np.float32)
        for channel in channels:
            trials = _decode_channel(iq, input_start=left, sample_rate=rate,
                        center_hz=center, channel_hz=channel,
                        core_start=core_start, core_end=core_end)
            raw_trials += len(trials)
            hits.extend(_merge_detections(trials))
        if progress is not None:
            progress((core_end-begin)/rate, (end-begin)/rate)
    crc_candidates = _merge_detections(hits)
    # A CRC codeword followed by zeros can also validate a longer framing.
    # Reject candidates whose final eight symbol decisions have lost the RF
    # carrier (>10 dB below the frame interior). This is a measured-envelope
    # check, not proof that every remaining ambiguous candidate is genuine.
    frames = [hit for hit in crc_candidates if hit['carrier_supported']]
    rejected = [hit for hit in crc_candidates if not hit['carrier_supported']]
    return {
        'format': 'SC16Q11 little-endian interleaved I,Q',
        'sample_rate_hz': rate, 'center_hz': center, 'channels_hz': list(channels),
        'start_seconds': begin/rate, 'duration_seconds': (end-begin)/rate,
        'bit_rate_hz': BIT_RATE, 'demod_sample_rate_hz': DEMOD_RATE,
        'thresholds_hz': list(THRESHOLDS_HZ),
        'raw_detection_trials': raw_trials, 'frame_count': len(frames),
        'crc_candidate_count': len(crc_candidates),
        'carrier_rejected_framing_counts': dict(Counter(f['framing'] for f in rejected)),
        'framing_counts': dict(Counter(f['framing'] for f in frames)),
        'channel_counts': dict(Counter(str(f['channel_hz']) for f in frames)),
        'action_counts': dict(Counter(f['action'] for f in frames)),
        'timing_note': 'Sample-index estimates; raw IQ does not establish continuity or calibrated RF-edge times.',
        'crc_note': 'Correct preamble, CRC, and final-symbol RF power >=10% of interior power required. This is not a packet-error-rate measurement. Multiple supported framing hypotheses can be retained.',
        'frames': frames,
    }


def redact_result(result: dict) -> dict:
    """Hide identities/CRCs and fields that can expose identity under ambiguity."""
    ambiguous = set()
    ordered = sorted(enumerate(result['frames']), key=lambda item: item[1]['address_time_s'])
    for j, (index, original) in enumerate(ordered):
        for k in range(j+1, len(ordered)):
            other_index, other = ordered[k]
            if other['address_time_s'] - original['address_time_s'] > 2e-6:
                break
            if other['channel_hz'] == original['channel_hz'] and other['framing'] != original['framing']:
                ambiguous.update((index, other_index))
    frames = []
    for index, original in enumerate(result['frames']):
        frame = dict(original)
        frame['payload_hex'] = 'xxxx' + frame['payload_hex'][4:]
        frame['remote_id'] = '[redacted]'
        frame['crc_hex'] = '[redacted]'
        for field in ('pcf_payload_length', 'pid', 'no_ack'):
            if frame.get(field) is not None:
                frame[field] = '[redacted]'
        if index in ambiguous:
            frame['payload_hex'] = '[redacted: ambiguous framing]'
            for field in ('mode', 'group_mask', 'action_code'):
                frame[field] = '[redacted: ambiguous framing]'
            frame['action'] = 'ambiguous-framing'
        frames.append(frame)
    return dict(result, frames=frames, action_counts=dict(Counter(f['action'] for f in frames)))
