# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fictional original-source vectors and independent secondary IQ checks."""
import binascii
from collections import Counter
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.rf_native_position import (
    NativePositionPlan, build_native_position_plan,
    iter_native_position_iq_chunks, write_native_position_waveform,
)
from hd_platinum.rf_native_secondary_position import (
    NativeSecondaryPositionPlan, build_native_secondary_position_payloads,
    build_native_secondary_position_plan, iter_native_secondary_position_iq_chunks,
    write_native_secondary_position_waveform,
)
from hd_platinum.rf_positions import build_position_plan, write_position_waveform

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:
    np = None


def fixture(**options):
    values = dict(prior_channel=33, command_frame_count=101,
                  followup_frame_count=8, slot_us=200.5)
    values.update(options)
    return build_native_secondary_position_plan(bytes.fromhex('1234'), 8, 128, **values)


class SecondaryPlanTests(unittest.TestCase):
    def test_original_feature18_builder_vectors_and_raw_byte_retention(self):
        # Unmodified original builder: flags1, phases2/3, C9A6, both prior
        # alternate states. These fictional vectors make no physical rail claim.
        for identity, mask, value, held, tail in (
                ('1234', 8, 0, '12346d0800', '1234320800'),
                ('1234', 8, 64, '12346d0840', '1234320840'),
                ('1234', 8, 128, '12346d0880', '1234320880'),
                ('1234', 8, 255, '12346d08ff', '12343208ff'),
                ('5678', 64, 0, '56786d4000', '5678324000'),
                ('5678', 64, 64, '56786d4040', '5678324040'),
                ('5678', 64, 128, '56786d4080', '5678324080'),
                ('5678', 64, 255, '56786d40ff', '56783240ff')):
            with self.subTest(identity=identity, value=value):
                pair = build_native_secondary_position_payloads(bytes.fromhex(identity), mask, value)
                self.assertEqual(tuple(p.hex() for p in pair), (held, tail))
        for value in range(256):
            held, tail = build_native_secondary_position_payloads(b'\x12\x34', 8, value)
            self.assertEqual((held[4], tail[4]), (value, value))

    def test_original_scheduler_continuity_and_fixed_body_across_counter100(self):
        # Counts are artificial fixture inputs, not derived from150/30 ticks.
        for prior, cycle in ((33, (52, 71, 33)), (52, (71, 33, 52)), (71, (33, 52, 71))):
            for held_count in (4, 5, 6, 101, 102, 103):
                plan = fixture(prior_channel=prior, command_frame_count=held_count,
                               followup_frame_count=7)
                events = list(plan.iter_events())
                self.assertEqual([e.channel_hz for e in events],
                    [(2400 + cycle[i % 3]) * 1_000_000 for i in range(held_count + 7)])
                self.assertEqual([e.payload.hex() for e in events],
                    ['12346d0880'] * held_count + ['1234320880'] * 7)
                self.assertEqual([e.start_sample for e in events], [i * 9624 for i in range(len(events))])
                self.assertEqual((events[held_count - 1].phase, events[held_count].phase), ('command', 'followup'))

    def test_secondary_validation_and_explicit_schedule_requirements(self):
        with self.assertRaises(TypeError):
            build_native_secondary_position_plan(b'\x12\x34', 8, 128)
        for value in (-1, 256, True, 128.0, '128', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_native_secondary_position_payloads(b'\x12\x34', 8, value)
        for identity, mask in [(b'x', 8), ('1234', 8), (b'\x12\x34', 3), (b'\x12\x34', True)]:
            with self.subTest(identity=identity, mask=mask), self.assertRaises(ValueError):
                build_native_secondary_position_payloads(identity, mask, 128)
        for options in ({'prior_channel': 34}, {'command_frame_count': 0},
                        {'followup_frame_count': True}, {'slot_us': 234},
                        {'command_frame_count': 9975, 'followup_frame_count': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                fixture(**options)

    def test_secondary_identity_metadata_and_type_are_separate(self):
        identity = bytearray.fromhex('1234')
        plan = NativeSecondaryPositionPlan(identity, 8, 128, 71, 5, 4, 200.5)
        identity[0] = 0
        self.assertEqual(plan.command_payload.hex(), '12346d0880')
        self.assertNotIsInstance(plan, NativePositionPlan)
        with self.assertRaises(FrozenInstanceError):
            plan.position = 0
        metadata = plan.as_dict()
        self.assertEqual((metadata['operation'], metadata['feature_decimal'], metadata['feature_hex']),
                         ('native_secondary_position', 18, '12'))
        self.assertEqual(metadata['command_payload'], 'xxxx6d0880')
        self.assertNotIn('1234', json.dumps(metadata))
        self.assertNotIn('room_rf_id=', repr(plan))
        self.assertTrue(metadata['phase_counts_are_assumed'] and metadata['idle_start_assumed'])
        self.assertFalse(metadata['hardware_qualified'] or metadata['prelude_included'])
        with self.assertRaises(ValueError):
            plan.as_dict(include_private='false')

    def test_primary_metadata_contract_has_no_secondary_fields(self):
        primary = build_native_position_plan(b'\x12\x34', 8, 128, prior_channel=71,
            command_frame_count=5, followup_frame_count=4, slot_us=200.5)
        metadata = primary.as_dict()
        self.assertEqual(metadata['operation'], 'native_primary_position')
        self.assertEqual((metadata['command_payload'], metadata['followup_payload']),
                         ('xxxx500880', 'xxxx320880'))
        self.assertNotIn('feature_decimal', metadata)
        self.assertNotIn('native_context_c9a', metadata)


@unittest.skipIf(np is None, 'optional NumPy/SciPy dependencies unavailable')
class SecondarySignalTests(unittest.TestCase):
    def test_written_secondary_signal_independently_decodes_all_channels_and_CRCs(self):
        from hd_platinum.rf_iq import decode_iq_file
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fictional-secondary.sc16q11'
            plan = fixture()
            metadata = write_native_secondary_position_waveform(path, plan, chunk_samples=10007)
            decoded = decode_iq_file(path, sample_rate_hz=48_000_000, center_hz=2_452_000_000,
                channels_hz=(2_433_000_000, 2_452_000_000, 2_471_000_000), chunk_seconds=.005)
            self.assertEqual(decoded['frame_count'], 109)
            self.assertEqual(Counter(f['payload_hex'] for f in decoded['frames']),
                             {'12346d0880': 101, '1234320880': 8})
            for ordinal, frame in enumerate(decoded['frames']):
                expected = '12346d0880' if ordinal < 101 else '1234320880'
                self.assertEqual(frame['payload_hex'], expected)
                self.assertEqual(frame['channel_hz'], (2_452_000_000, 2_471_000_000, 2_433_000_000)[ordinal % 3])
                self.assertEqual(int(frame['crc_hex'], 16), binascii.crc_hqx(bytes.fromhex('e7e7e7' + expected), 65535))
                self.assertAlmostEqual(frame['address_time_s'], (ordinal * 200.5 + 53) / 1e6, delta=1e-6)
            self.assertEqual(metadata['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_primary_golden_IQ_and_secondary_chunk_independence(self):
        primary = build_native_position_plan(b'\x12\x34', 8, 128, prior_channel=71,
            command_frame_count=5, followup_frame_count=4, slot_us=200.5)
        before_refactor_hash = 'de65fa31d4d031b2cc5b59ab7f9fb63a4d34470d9e826a14ed1e6485f19c9c2c'
        digest = hashlib.sha256(b''.join(c.tobytes() for c in iter_native_position_iq_chunks(primary, chunk_samples=997))).hexdigest()
        self.assertEqual(digest, before_refactor_hash)
        secondary = fixture(command_frame_count=5, followup_frame_count=4)
        def render(size):
            return np.concatenate(list(iter_native_secondary_position_iq_chunks(secondary, chunk_samples=size)))
        small, large = render(997), render(10007)
        self.assertTrue(np.array_equal(small, large))
        self.assertFalse(np.any(small.reshape(9, 9624, 2)[:, 4560:, :]))

    def test_public_writers_reject_cross_operation_plans_before_creating_file(self):
        secondary = fixture()
        primary = build_native_position_plan(b'\x12\x34', 8, 128, prior_channel=71,
            command_frame_count=1, followup_frame_count=1, slot_us=200.5)
        sequential = build_position_plan(b'\x12\x34', 8, 128)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'must-not-exist'
            for writer, plan in ((write_native_position_waveform, secondary),
                                 (write_native_secondary_position_waveform, primary),
                                 (write_native_secondary_position_waveform, sequential),
                                 (write_position_waveform, secondary)):
                with self.assertRaises(ValueError):writer(path, plan)
                self.assertFalse(path.exists())
            with self.assertRaises(ValueError):next(iter_native_position_iq_chunks(secondary))
            with self.assertRaises(ValueError):next(iter_native_secondary_position_iq_chunks(primary))
            path.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):write_native_secondary_position_waveform(path, secondary)
            self.assertEqual(path.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
