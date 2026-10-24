# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Exercise finite radio operations against a fake C ABI, without hardware."""
from __future__ import annotations

import ctypes as C
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from hd_platinum.bladerf import (
    BladeRF, BladeRFBackend, BladeRFPositionBackend, BURST_END, BURST_START, Metadata, META_FORMAT, RadioConfig,
    RadioError, RX1, RX2, RX_NOW, TX1, TX2, Version, conducted_test,
)
from hd_platinum.bridge import Command, PositionCommand, ShadeConfig
from hd_platinum.rf import REMOTE_FREQUENCIES_HZ


def write_pointer(pointer, ctype, value):
    C.cast(pointer, C.POINTER(ctype))[0] = value


class FakeLibrary:
    """Model the relevant libbladeRF buffer and stream lifetime contracts."""
    def __init__(self):
        self.calls = []
        self.initialized = set()
        self.enabled = set()
        self.rates = {RX1: 8_000_000, TX1: 8_000_000}
        self.clock = 1000
        self.tx_cursor = None
        self.tx_blocks = []
        self.rx_blocks = []
        self.fail_enable = None
        self.fail_tx = False
        self.fail_quiet_channel = None
        self.on_tx = None
        self.closed = threading.Event()

    def bladerf_open(self, pointer, device):
        write_pointer(pointer, C.c_void_p, 1234)
        self.calls.append(('open', device))
        return 0

    def bladerf_close(self, device):
        self.calls.append(('close', device.value))
        self.closed.set()

    def bladerf_strerror(self, error):
        return b'simulated error'

    def bladerf_get_board_name(self, device):
        return b'bladerf2'

    def bladerf_is_fpga_configured(self, device):
        return 1

    def bladerf_enable_module(self, device, channel, enabled):
        self.calls.append(('enable', channel, enabled))
        if enabled:
            self.enabled.add(channel)
            if self.fail_enable == channel:
                return -1
        else:
            self.enabled.discard(channel)
            self.initialized.discard(channel)
            if self.fail_quiet_channel == channel:
                return -1
        return 0

    def bladerf_set_bias_tee(self, device, channel, enabled):
        self.calls.append(('bias', channel, enabled))
        return 0

    def bladerf_set_sample_rate(self, device, channel, requested, actual):
        self.calls.append(('rate', channel, requested))
        # AD9361 rate changes configure both clock chains.
        self.rates[RX1] = self.rates[TX1] = requested
        write_pointer(actual, C.c_uint, requested)
        return 0

    def bladerf_get_sample_rate(self, device, channel, actual):
        write_pointer(actual, C.c_uint, self.rates[channel])
        return 0

    def bladerf_set_frequency(self, device, channel, frequency):
        return 0

    def bladerf_set_bandwidth(self, device, channel, requested, actual):
        write_pointer(actual, C.c_uint, requested)
        return 0

    def bladerf_set_gain(self, device, channel, gain):
        self.calls.append(('gain', channel, gain))
        return 0

    def bladerf_set_gain_mode(self, device, channel, mode):
        return 0

    def bladerf_sync_config(self, device, layout, format, buffers, size, transfers, timeout):
        self.calls.append(('sync_config', layout, format, buffers, size, transfers, timeout))
        self.initialized.add(layout)
        return 0

    def bladerf_get_timestamp(self, device, direction, timestamp):
        self.calls.append(('timestamp', direction, self.clock))
        write_pointer(timestamp, C.c_uint64, self.clock)
        return 0

    def bladerf_sync_tx(self, device, buffer, count, metadata, timeout):
        self.calls.append(('tx', count))
        if TX1 not in self.initialized or TX1 not in self.enabled:
            return -1
        meta = C.cast(metadata, C.POINTER(Metadata)).contents
        self.tx_blocks.append((meta.flags, meta.timestamp, C.string_at(buffer, count*4)))
        if self.on_tx:
            self.on_tx()
        if self.fail_tx:
            return -1
        if meta.flags & BURST_START:
            self.tx_cursor = meta.timestamp
        self.tx_cursor += count
        if meta.flags & BURST_END:
            self.clock = self.tx_cursor + 4096
        return 0

    def bladerf_sync_rx(self, device, buffer, wanted, metadata, timeout):
        self.calls.append(('rx', wanted))
        meta = C.cast(metadata, C.POINTER(Metadata)).contents
        if RX1 not in self.initialized or RX1 not in self.enabled:
            return -1
        if meta.flags != RX_NOW:
            return -1
        block = self.rx_blocks.pop(0)
        if isinstance(block, int):
            return block
        timestamp, count, status = block
        meta.timestamp, meta.actual_count, meta.status = timestamp, count, status
        C.memmove(buffer, b'\x01\x00\x02\x00' * min(count, wanted), min(count, wanted)*4)
        return 0


class BladeRFTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.lib = FakeLibrary()
        self.radio = BladeRF(library=self.lib)
        self.radio.__enter__()
        self.addCleanup(self.radio.close, suppress_errors=True)
        self.config = RadioConfig(sample_rate_hz=8_000_000, bandwidth_hz=6_000_000, gain_db=0)

    def waveform(self, count=10):
        path = self.root / 'tx.sc16q11'
        path.write_bytes(b'\x01\x00\x02\x00' * count)
        return path

    def test_metadata_abi_offsets_and_enum(self):
        self.assertEqual(META_FORMAT, 2)
        self.assertEqual(C.sizeof(Metadata), 56)
        self.assertEqual([getattr(Metadata, name).offset for name in
                          ('timestamp', 'flags', 'status', 'actual_count', 'reserved')], [0, 8, 12, 16, 20])
        self.assertEqual(Version.describe.offset, 8)
        self.assertEqual(C.sizeof(Version), 16)

    def test_entry_and_exit_disable_all_modules_and_bias_tees(self):
        for channel in (RX1, TX1, RX2, TX2):
            self.assertIn(('enable', channel, False), self.lib.calls)
            self.assertIn(('bias', channel, False), self.lib.calls)
        self.radio.close()
        self.assertTrue(self.lib.closed.is_set())
        self.assertFalse(self.radio.dev.value)

    def test_quiet_attempts_every_channel_even_after_one_failure(self):
        self.lib.calls.clear()
        self.lib.fail_quiet_channel = TX1
        with self.assertRaises(RadioError):
            self.radio.quiet()
        for channel in (RX1, TX1, RX2, TX2):
            self.assertIn(('enable', channel, False), self.lib.calls)
            self.assertIn(('bias', channel, False), self.lib.calls)
        self.lib.fail_quiet_channel = None

    def test_chunked_burst_has_single_start_end_and_drains_before_disable(self):
        self.radio.configure(TX1, self.config)
        path = self.waveform()
        with patch('hd_platinum.bladerf.CHUNK_SAMPLES', 4):
            result = self.radio.transmit(path, settle_seconds=.05)
        self.assertEqual([b[0] for b in self.lib.tx_blocks], [BURST_START, 0, BURST_END])
        self.assertEqual(b''.join(b[2] for b in self.lib.tx_blocks), path.read_bytes())
        self.assertEqual(result['start_timestamp'], 401000)
        self.assertEqual(result['end_timestamp'], 401010)
        self.assertEqual(result['samples_sent'], 10)
        self.assertIn('unavailable', result['tx_underrun_detection'])
        self.assertEqual(self.lib.calls[-2], ('timestamp', 1, 405106))
        self.assertEqual(self.lib.calls[-1], ('enable', TX1, False))

    def test_short_burst_flushes_and_second_run_reinitializes_stream(self):
        self.radio.configure(TX1, self.config)
        path = self.waveform(3)
        self.radio.transmit(path)
        self.radio.transmit(path)
        self.assertEqual([b[0] for b in self.lib.tx_blocks], [BURST_START | BURST_END] * 2)
        self.assertEqual(len([x for x in self.lib.calls if x[:2] == ('sync_config', TX1)]), 3)

    def test_receive_buffer_capacity_is_preserved_across_restart(self):
        self.radio.configure(RX1, self.config)
        self.lib.rx_blocks = [(100, 1, 0), (200, 1, 0)]
        self.radio.receive(self.root / 'first-rx', duration_seconds=1/8_000_000)
        self.radio.receive(self.root / 'second-rx', duration_seconds=1/8_000_000)
        setups = [call for call in self.lib.calls if call[:2] == ('sync_config', RX1)]
        self.assertEqual(setups, [('sync_config', RX1, META_FORMAT, 64, 65_536, 32, 3000)] * 3)

    def test_transmit_keeps_its_smaller_buffer_capacity(self):
        self.radio.configure(TX1, self.config)
        self.radio.transmit(self.waveform())
        setups = [call for call in self.lib.calls if call[:2] == ('sync_config', TX1)]
        self.assertEqual(setups, [('sync_config', TX1, META_FORMAT, 32, 65_536, 16, 3000)] * 2)

    def test_partial_enable_failure_is_followed_by_disable(self):
        self.radio.configure(TX1, self.config)
        self.lib.fail_enable = TX1
        with self.assertRaises(RadioError):
            self.radio.transmit(self.waveform())
        self.assertEqual(self.lib.calls[-1], ('enable', TX1, False))
        self.assertNotIn(TX1, self.lib.enabled)
        self.assertFalse(self.lib.tx_blocks)

    def test_tx_failure_disables_module(self):
        self.radio.configure(TX1, self.config)
        self.lib.fail_tx = True
        with self.assertRaises(RadioError):
            self.radio.transmit(self.waveform())
        self.assertEqual(self.lib.calls[-1], ('enable', TX1, False))

    def test_reconfigure_is_rejected_while_a_stream_is_active(self):
        self.radio.configure(TX1, self.config)
        before = len([x for x in self.lib.calls if x[0] == 'rate'])
        def during_tx():
            with self.assertRaisesRegex(RadioError, 'stop all streams'):
                self.radio.configure(RX1, self.config)
        self.lib.on_tx = during_tx
        self.radio.transmit(self.waveform())
        self.assertEqual(len([x for x in self.lib.calls if x[0] == 'rate']), before)

    def test_shared_rate_change_invalidates_prior_configuration(self):
        self.radio.configure(TX1, self.config)
        with self.assertRaisesRegex(RadioError, 'coupling'):
            self.radio.configure(RX1, RadioConfig(sample_rate_hz=16_000_000, bandwidth_hz=10_000_000))
        self.assertFalse(self.radio.configured)
        self.assertFalse(self.lib.enabled)

    def test_invalid_waveform_is_rejected_before_enabling_tx(self):
        self.radio.configure(TX1, self.config)
        path = self.root / 'bad.sc16q11'
        path.write_bytes(b'bad')
        before = len(self.lib.calls)
        with self.assertRaises(ValueError):
            self.radio.transmit(path)
        self.assertNotIn(('enable', TX1, True), self.lib.calls[before:])

    def test_rx_tracks_contiguity_and_writes_only_valid_samples(self):
        self.radio.configure(RX1, self.config)
        self.lib.rx_blocks = [(100, 4, 0), (110, 2, 1), (112, 2, 0)]
        path = self.root / 'rx.sc16q11'
        ready = threading.Event()
        with patch('hd_platinum.bladerf.CHUNK_SAMPLES', 4):
            result = self.radio.receive(path, duration_seconds=8/8_000_000, ready=ready)
        self.assertEqual(path.stat().st_size, 32)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result['sample_count'], 8)
        self.assertTrue(result['completed'])
        self.assertIsNone(result['failure'])
        self.assertEqual(result['overruns'], 1)
        self.assertEqual(result['timestamp_gaps'], 1)
        self.assertFalse(result['continuous'])
        self.assertEqual([x['offset_samples'] for x in result['blocks']], [0, 4, 6])
        self.assertTrue(ready.is_set())
        self.assertEqual(self.lib.calls[-1], ('enable', RX1, False))

    def test_partial_capture_failure_retains_timestamped_metadata(self):
        self.radio.configure(RX1, self.config)
        self.lib.rx_blocks = [(100, 4, 0), -1]
        path = self.root / 'partial.sc16q11'
        with patch('hd_platinum.bladerf.CHUNK_SAMPLES', 4):
            with self.assertRaisesRegex(RadioError, 'sync_rx'):
                self.radio.receive(path, duration_seconds=8/8_000_000)
        sidecar = Path(str(path) + '.metadata.json')
        result = json.loads(sidecar.read_text())
        self.assertEqual(path.stat().st_size, 16)
        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
        self.assertFalse(result['completed'])
        self.assertFalse(result['continuous'])
        self.assertEqual(result['sample_count'], 4)
        self.assertEqual(result['requested_sample_count'], 8)
        self.assertEqual(result['blocks'], [dict(offset_samples=0, timestamp=100, count=4, status=0)])
        self.assertIn('sync_rx', result['failure'])
        self.assertNotIn('payload', result)
        self.assertNotIn('remote_id', result)
        self.assertEqual(self.lib.calls[-1], ('enable', RX1, False))

    def test_capture_cleanup_failure_is_not_marked_complete(self):
        self.radio.configure(RX1, self.config)
        self.lib.rx_blocks = [(100, 1, 0)]
        self.lib.fail_quiet_channel = RX1
        path = self.root / 'cleanup-failed.sc16q11'
        try:
            with self.assertRaisesRegex(RadioError, 'enable_module'):
                self.radio.receive(path, duration_seconds=1/8_000_000)
        finally:
            self.lib.fail_quiet_channel = None
        result = json.loads(Path(str(path) + '.metadata.json').read_text())
        self.assertEqual(result['sample_count'], 1)
        self.assertFalse(result['completed'])
        self.assertFalse(result['continuous'])
        self.assertIn('enable_module', result['failure'])

    def test_existing_iq_and_metadata_are_not_changed_on_refused_capture(self):
        self.radio.configure(RX1, self.config)
        path = self.root / 'existing.sc16q11'
        path.write_bytes(b'existing')
        sidecar = Path(str(path) + '.metadata.json')
        sidecar.write_text('existing metadata')
        with self.assertRaises(FileExistsError):
            self.radio.receive(path, duration_seconds=1/8_000_000)
        self.assertEqual(path.read_bytes(), b'existing')
        self.assertEqual(sidecar.read_text(), 'existing metadata')

    def test_rx_invalid_count_and_partial_enable_failure_both_disable(self):
        self.radio.configure(RX1, self.config)
        self.lib.rx_blocks = [(100, 0, 0)]
        with self.assertRaisesRegex(RadioError, 'sample count'):
            self.radio.receive(self.root / 'bad-rx', duration_seconds=1/8_000_000)
        self.assertEqual(self.lib.calls[-1], ('enable', RX1, False))
        self.lib.fail_enable = RX1
        with self.assertRaises(RadioError):
            self.radio.receive(self.root / 'failed-rx', duration_seconds=1/8_000_000)
        self.assertEqual(self.lib.calls[-1], ('enable', RX1, False))

    def test_device_close_waits_for_live_receiver(self):
        release = threading.Event()
        worker = threading.Thread(target=lambda: release.wait(3), daemon=True)
        worker.start()
        self.radio._close_waiter = worker
        try:
            self.radio.close()
            self.assertFalse(self.lib.closed.is_set())
            self.assertTrue(self.radio.dev.value)
        finally:
            release.set()
            worker.join(1)
        self.assertTrue(self.lib.closed.wait(2))
        self.assertFalse(self.radio.dev.value)

    def test_conducted_rate_limit_rejects_before_opening_hardware(self):
        config = RadioConfig()
        with patch('hd_platinum.bladerf._load_library') as load:
            with self.assertRaisesRegex(ValueError, '80 MS/s'):
                conducted_test('missing', 'unused', tx_config=config, rx_config=config)
        load.assert_not_called()


class BladeRFBackendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'cache'
        self.backend = BladeRFBackend(self.cache, device='fictional-device', fpga='fictional.rbf')
        self.command = Command(1, 'up', bytes.fromhex('03c1'), 'request-one')
        self.context = MagicMock()
        self.radio = self.context.__enter__.return_value
        self.radio.transmit.return_value = {'duration_seconds': .195, 'status': 'submitted'}

    def test_all_three_private_narrowband_files_precede_separate_radio_sessions(self):
        events, plans = [], []
        def write(path, plan, **kwargs):
            events.append(('write', plan.config.channels_hz[0]))
            plans.append(plan)
            Path(path).write_bytes(b'\x01\x00\x02\x00')
        def open_radio(**kwargs):
            self.assertEqual(len(plans), 3)
            events.append(('open',))
            return self.context
        self.radio.configure.side_effect = lambda channel, config: events.append(('configure', config.center_hz))
        with patch('hd_platinum.rf_waveform.write_waveform', side_effect=write), \
             patch('hd_platinum.bladerf.BladeRF', side_effect=open_radio) as factory:
            receipt = self.backend(self.command)
        self.assertEqual(factory.call_count, 3)
        factory.assert_called_with(device='fictional-device', fpga='fictional.rbf')
        self.assertEqual(events[:3], [('write', frequency) for frequency in REMOTE_FREQUENCIES_HZ])
        self.assertEqual(events[3], ('open',))
        self.assertEqual(self.radio.transmit.call_count, 3)
        for plan, call in zip(plans, self.radio.configure.call_args_list):
            channel, config = call.args
            self.assertEqual(channel, TX1)
            self.assertEqual(config.sample_rate_hz, 8_000_000)
            self.assertEqual(config.bandwidth_hz, 6_000_000)
            self.assertEqual(config.gain_db, 35)
            self.assertEqual(plan.config.center_hz, config.center_hz)
            self.assertEqual(plan.config.channels_hz, (config.center_hz,))
            self.assertEqual(plan.config.sample_rate_hz, 8_000_000)
            self.assertEqual(plan.action_repetitions, 500)
            self.assertEqual(plan.release_repetitions, 500)
            self.assertEqual(plan.frame_count, 1000)
            self.assertAlmostEqual(plan.duration_seconds, .195)
        files = list(self.cache.glob('*.sc16q11'))
        self.assertEqual(len(files), 3)
        self.assertFalse(list(self.cache.glob('*.pending')))
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in files))
        self.assertEqual(receipt['status'], 'submitted')
        self.assertEqual(receipt['frames_sent'], 3000)
        self.assertAlmostEqual(receipt['duration_seconds'], .585)
        self.assertEqual(receipt['channels_hz'], list(REMOTE_FREQUENCIES_HZ))
        self.assertIn('retuning and settling gaps', receipt['detail'])
        self.assertIn('differs from', receipt['detail'])
        self.assertEqual(self.context.__exit__.call_count, 3)
        self.context.__exit__.assert_called_with(None, None, None)

    def test_each_channel_gets_fresh_host_cursor_after_hardware_clock_reset(self):
        class EpochResetLibrary(FakeLibrary):
            def bladerf_set_sample_rate(self, device, channel, requested, actual):
                self.clock = 1000
                return super().bladerf_set_sample_rate(device, channel, requested, actual)

            def bladerf_sync_tx(self, device, buffer, count, metadata, timeout):
                meta = C.cast(metadata, C.POINTER(Metadata)).contents
                # libbladeRF 2.6 retains curr_timestamp across sync_init; a
                # reset device clock can make a second burst look too old.
                if meta.flags & BURST_START and self.tx_cursor is not None and meta.timestamp < self.tx_cursor:
                    return -14
                return super().bladerf_sync_tx(device, buffer, count, metadata, timeout)

        target = ShadeConfig('Example shade', 1, b'XY', 4, position_enabled=True)
        cases = [
            (self.backend, self.command, 'hd_platinum.rf_waveform.write_waveform'),
            (BladeRFPositionBackend(self.cache), PositionCommand(6, 128, target, 'position'),
             'hd_platinum.rf_positions.write_position_waveform'),
        ]
        for backend, command, writer in cases:
            with self.subTest(backend=type(backend).__name__):
                libraries = []
                def fresh_library():
                    if libraries:
                        self.assertTrue(libraries[-1].closed.is_set())
                        self.assertFalse(libraries[-1].enabled)
                    library = EpochResetLibrary()
                    libraries.append(library)
                    return library
                def write(path, plan, **kwargs):
                    Path(path).write_bytes(b'\x00' * 40)
                with patch(writer, side_effect=write), \
                        patch('hd_platinum.bladerf._load_library', side_effect=fresh_library):
                    receipt = backend(command)
                self.assertEqual(receipt['status'], 'submitted')
                self.assertEqual(len(libraries), 3)
                for library in libraries:
                    self.assertTrue(library.closed.is_set())
                    self.assertFalse(library.enabled)
                    self.assertEqual(len(library.tx_blocks), 1)
                    self.assertEqual(library.tx_blocks[0][1], 1_201_000)

    def test_later_synthesis_failure_never_opens_radio_and_cleans_temporary(self):
        calls = []
        def write(path, plan, **kwargs):
            calls.append(plan)
            Path(path).write_bytes(b'partial')
            if len(calls) == 2:
                raise OSError('simulated disk failure')
        with patch('hd_platinum.rf_waveform.write_waveform', side_effect=write), \
             patch('hd_platinum.bladerf.BladeRF', return_value=self.context) as factory:
            with self.assertRaisesRegex(OSError, 'disk failure'):
                self.backend(self.command)
            factory.assert_not_called()
            self.assertFalse(list(self.cache.glob('*.pending')))
            # A failed preparation releases the command lock for a later retry.
            self.backend(self.command)
            self.assertEqual(factory.call_count, 3)
        self.assertFalse(list(self.cache.glob('*.pending')))

    def test_second_channel_failure_closes_radio_and_does_not_submit_third(self):
        def write(path, plan, **kwargs):
            Path(path).write_bytes(b'\x00' * 4)
        self.radio.transmit.side_effect = [
            {'duration_seconds': .195, 'status': 'submitted'}, RadioError('simulated TX failure')]
        with patch('hd_platinum.rf_waveform.write_waveform', side_effect=write) as writer, \
             patch('hd_platinum.bladerf.BladeRF', return_value=self.context):
            with self.assertRaisesRegex(RadioError, 'TX failure'):
                self.backend(self.command)
        self.assertEqual(writer.call_count, 3)
        self.assertEqual(self.radio.transmit.call_count, 2)
        self.assertEqual(self.radio.configure.call_count, 2)
        self.assertEqual(self.context.__exit__.call_count, 2)
        self.assertIs(self.context.__exit__.call_args.args[0], RadioError)
        self.assertFalse(list(self.cache.glob('*.pending')))


class BladeRFPositionBackendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'cache'
        self.backend = BladeRFPositionBackend(self.cache, gain_db=35,
                                             device='fictional-device', fpga='fictional.rbf')
        self.target = ShadeConfig('Example shade', 1, b'XY', 4, position_enabled=True)
        self.command = PositionCommand(6, 128, self.target, 'position-request')
        self.context = MagicMock()
        self.radio = self.context.__enter__.return_value
        self.radio.transmit.return_value = {'duration_seconds': 1.77255, 'status': 'submitted'}

    def test_position_plan_and_all_private_files_precede_separate_radio_sessions(self):
        plans, events = [], []
        def write(path, plan, **kwargs):
            plans.append(plan)
            events.append(('write', plan.config.channels_hz[0]))
            self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
            Path(path).write_bytes(b'\x00' * 4)
        def open_radio(**kwargs):
            self.assertEqual(len(plans), 3)
            events.append(('open',))
            return self.context
        with patch('hd_platinum.rf_positions.write_position_waveform', side_effect=write), \
             patch('hd_platinum.bladerf.BladeRF', side_effect=open_radio) as factory:
            receipt = self.backend(self.command)
        self.assertEqual(factory.call_count, 3)
        factory.assert_called_with(device='fictional-device', fpga='fictional.rbf')
        self.assertEqual(events[:3], [('write', frequency) for frequency in REMOTE_FREQUENCIES_HZ])
        self.assertEqual(events[3], ('open',))
        self.assertEqual(self.radio.transmit.call_count, 3)
        for plan, call in zip(plans, self.radio.configure.call_args_list):
            channel, radio_config = call.args
            self.assertEqual(channel, TX1)
            self.assertEqual(radio_config.sample_rate_hz, 8_000_000)
            self.assertEqual(radio_config.bandwidth_hz, 6_000_000)
            self.assertEqual(radio_config.gain_db, 35)
            self.assertEqual(plan.config.center_hz, radio_config.center_hz)
            self.assertEqual(plan.config.channels_hz, (radio_config.center_hz,))
            self.assertEqual(plan.config.sample_rate_hz, 8_000_000)
            self.assertEqual(plan.config.slot_us, 702)
            self.assertEqual(plan.config.slot_samples, 5616)
            self.assertEqual(plan.config.deviation_hz, 320_000)
            self.assertEqual(plan.config.lead_in_us, 49)
            self.assertEqual(plan.config.ramp_us, 2)
            self.assertEqual(plan.command_payload, b'XY\x50\x04\x80')
            self.assertEqual(plan.followup_payload, b'XY\x32\x04\x80')
            self.assertEqual(plan.command_repetitions, 2100)
            self.assertEqual(plan.followup_repetitions, 425)
            self.assertEqual(plan.frame_count, 2525)
            self.assertEqual(plan.sample_count, 14_180_400)
            self.assertAlmostEqual(plan.duration_seconds, 1.77255)
            self.assertLessEqual(plan.duration_seconds, plan.config.max_airtime_seconds)
        self.assertEqual(receipt['status'], 'submitted')
        self.assertEqual(receipt['frames_sent'], 7575)
        self.assertAlmostEqual(receipt['duration_seconds'], 5.31765)
        self.assertIn('702 us same-channel spacing', receipt['detail'])
        self.assertIn('includes inter-packet silence', receipt['detail'])
        self.assertIn('provisional', receipt['detail'])
        self.assertIn('position remains unverified', receipt['detail'])
        self.assertIn('retuning and settling gaps', receipt['detail'])
        for private in ('5859', 'room_rf_id', 'mask', 'command_payload', 'followup_payload'):
            self.assertNotIn(private, json.dumps(receipt))
        files = list(self.cache.glob('*.sc16q11'))
        self.assertEqual(len(files), 3)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in files))
        self.assertFalse(list(self.cache.glob('*.pending')))
        self.assertEqual(self.context.__exit__.call_count, 3)
        self.context.__exit__.assert_called_with(None, None, None)

    def test_disabled_or_invalid_position_target_is_rejected_before_synthesis(self):
        commands = [replace(self.command, target=replace(self.target, position_enabled=False)),
                    Command(1, 'up', b'XY', 'wrong-command-kind'),
                    replace(self.command, position=True), replace(self.command, position=-1),
                    replace(self.command, position=256), replace(self.command, shade=True)]
        # Recheck RF fields at the hardware boundary, even if a caller has
        # bypassed the frozen configuration object's constructor validation.
        for name, value in [('feature', 18), ('feature', 4.0), ('room_rf_id', b'X'),
                            ('room_rf_id', 2), ('mask', 3), ('mask', True),
                            ('mask', 256), ('position_enabled', 1)]:
            mutated = replace(self.target)
            object.__setattr__(mutated, name, value)
            commands.append(replace(self.command, target=mutated))
        with patch('hd_platinum.rf_positions.write_position_waveform') as writer, \
             patch('hd_platinum.bladerf.BladeRF') as factory:
            for command in commands:
                with self.subTest(command=command), self.assertRaises(ValueError):
                    self.backend(command)
        writer.assert_not_called()
        factory.assert_not_called()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_position_synthesis_failure_cleans_pending_file_and_never_opens_radio(self):
        calls = []
        def write(path, plan, **kwargs):
            calls.append(plan)
            Path(path).write_bytes(b'partial')
            if len(calls) == 3:
                raise OSError('simulated synthesis failure')
        with patch('hd_platinum.rf_positions.write_position_waveform', side_effect=write), \
             patch('hd_platinum.bladerf.BladeRF', return_value=self.context) as factory:
            with self.assertRaisesRegex(OSError, 'synthesis failure'):
                self.backend(self.command)
            factory.assert_not_called()
            self.assertFalse(list(self.cache.glob('*.pending')))
            self.backend(self.command)  # The command lock was released.
            self.assertEqual(factory.call_count, 3)

    def test_position_failure_on_second_channel_closes_and_skips_third(self):
        def write(path, plan, **kwargs):
            Path(path).write_bytes(b'\x00' * 4)
        self.radio.transmit.side_effect = [
            {'duration_seconds': 1.77255, 'status': 'submitted'}, RadioError('simulated TX failure')]
        with patch('hd_platinum.rf_positions.write_position_waveform', side_effect=write) as writer, \
             patch('hd_platinum.bladerf.BladeRF', return_value=self.context):
            with self.assertRaisesRegex(RadioError, 'TX failure'):
                self.backend(self.command)
        self.assertEqual(writer.call_count, 3)
        self.assertEqual(self.radio.transmit.call_count, 2)
        self.assertEqual(self.radio.configure.call_count, 2)
        self.assertEqual(self.context.__exit__.call_count, 2)
        self.assertIs(self.context.__exit__.call_args.args[0], RadioError)
        self.assertFalse(list(self.cache.glob('*.pending')))


if __name__ == '__main__':
    unittest.main()
