# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Durable allocator and checked duplex backend tests without radio hardware."""
import ctypes as C
import json
import multiprocessing
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from hd_platinum.bladerf import BURST_END, Metadata, RadioError, RX1, TX1
from hd_platinum.bladerf_bridge import BladeRFBridgeBackend, BridgeRadio, SequenceStore
from hd_platinum.bridge import JogCommand, PositionCommand, ShadeConfig, SyncCommand

try:
    import numpy
except ImportError:
    numpy = None


def _reserve_process(directory, queue):
    store = SequenceStore(directory)
    queue.put([store.reserve() for _ in range(3)])


def _set(pointer, kind, value):
    C.cast(pointer, C.POINTER(kind))[0] = value


class FakeLibrary:
    """Fake synchronous C ABI, including RX ownership during TX enable."""
    def __init__(self, *, first_status=0, bad_gain=False, bad_dsa=False, bad_frequency=False,
                 fail_tx=False, fail_rx_after_tx=False):
        self.enabled = set()
        self.rates, self.gains, self.frequencies = {}, {}, {}
        self.first_status, self.bad_gain, self.bad_dsa = first_status, bad_gain, bad_dsa
        self.bad_frequency, self.fail_tx = bad_frequency, fail_tx
        self.fail_rx_after_tx = fail_rx_after_tx
        self.rx_count = self.rx_calls = self.tx_calls = 0
        self.tx_samples = 0
        self.clock = 1000
        self.closed = False
        self.release_rx = threading.Event()
        self.bias_off_calls = []

    def bladerf_open(self, pointer, device):
        _set(pointer, C.c_void_p, 123)
        return 0

    def bladerf_close(self, device):
        self.closed = True

    def bladerf_strerror(self, error):
        return b"fake radio failure"

    def bladerf_get_board_name(self, device):
        return b"bladerf2"

    def bladerf_is_fpga_configured(self, device):
        return 1

    def bladerf_enable_module(self, device, channel, enabled):
        if enabled:
            self.enabled.add(channel)
        else:
            if channel == TX1 and channel in self.enabled:
                self.release_rx.set()
            self.enabled.discard(channel)
        return 0

    def bladerf_set_bias_tee(self, device, channel, enabled):
        assert not enabled
        self.bias_off_calls.append(channel)
        return 0

    def bladerf_get_bias_tee(self, device, channel, value):
        _set(value, C.c_bool, False)
        return 0

    def bladerf_set_sample_rate(self, device, channel, rate, actual):
        self.rates[RX1] = self.rates[TX1] = rate
        _set(actual, C.c_uint, rate)
        return 0

    def bladerf_get_sample_rate(self, device, channel, value):
        _set(value, C.c_uint, self.rates[channel])
        return 0

    def bladerf_set_bandwidth(self, device, channel, bandwidth, actual):
        _set(actual, C.c_uint, bandwidth)
        return 0

    def bladerf_set_frequency(self, device, channel, frequency):
        self.frequencies[channel] = frequency
        return 0

    def bladerf_get_frequency(self, device, channel, value):
        _set(value, C.c_uint64, self.frequencies[channel] + (1000 if self.bad_frequency else 0))
        return 0

    def bladerf_set_gain(self, device, channel, gain):
        self.gains[channel] = gain
        return 0

    def bladerf_set_gain_mode(self, *args):
        return 0

    def bladerf_get_gain(self, device, channel, value):
        assert channel in self.enabled
        _set(value, C.c_int, self.gains[channel] + int(self.bad_gain))
        return 0

    def bladerf_get_gain_stage(self, device, channel, stage, value):
        assert channel in self.enabled and stage == b"dsa"
        _set(value, C.c_int, -90 if self.bad_dsa else self.gains[channel] - 66)
        return 0

    def bladerf_sync_config(self, *args):
        return 0

    def bladerf_get_timestamp(self, device, direction, value):
        _set(value, C.c_uint64, self.clock)
        return 0

    def bladerf_sync_rx(self, device, buffer, count, metadata, timeout):
        self.rx_calls += 1
        if self.rx_calls == 2 and not self.release_rx.wait(3):
            return -1
        if self.rx_calls == 2 and self.fail_rx_after_tx:
            return -1
        meta = C.cast(metadata, C.POINTER(Metadata)).contents
        meta.timestamp, meta.actual_count = self.rx_count, count
        meta.status = self.first_status if self.rx_calls == 1 else 0
        self.rx_count += count
        return 0

    def bladerf_sync_tx(self, device, buffer, count, metadata, timeout):
        self.tx_calls += 1
        assert RX1 in self.enabled and TX1 in self.enabled
        if self.fail_tx:
            return -1
        self.tx_samples += count
        meta = C.cast(metadata, C.POINTER(Metadata)).contents
        if meta.flags & BURST_END:
            self.clock = meta.timestamp + count + 4096
        return 0


class SequenceStoreTests(unittest.TestCase):
    def test_requires_seed_burns_failure_and_resumes_without_reseed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                SequenceStore(directory)
            store = SequenceStore(directory, initial_sequence=100)
            with self.assertRaises(RuntimeError):
                with store.transaction() as value:
                    self.assertEqual(value, 100)
                    raise RuntimeError("uncertain submission")
            self.assertEqual(SequenceStore(directory).reserve(), 101)
            self.assertEqual(SequenceStore(directory, initial_sequence=100).reserve(), 102)
            with self.assertRaises(ValueError):
                SequenceStore(directory, initial_sequence=0)
            for filename in ("sequence.json", "sequence.lock"):
                self.assertEqual(stat.S_IMODE((Path(directory) / filename).stat().st_mode), 0o600)

    def test_concurrent_processes_never_reuse_reserved_values(self):
        with tempfile.TemporaryDirectory() as directory:
            SequenceStore(directory, initial_sequence=100)
            context = multiprocessing.get_context("spawn")
            queue = context.Queue()
            processes = [context.Process(target=_reserve_process, args=(directory, queue)) for _ in range(3)]
            for process in processes:
                process.start()
            values = [item for _ in processes for item in queue.get(timeout=10)]
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
            queue.close()
            self.assertEqual(sorted(values), list(range(100, 109)))

    def test_corrupt_state_and_exhaustion_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(directory, initial_sequence=65535)
            self.assertEqual(store.reserve(), 65535)
            with self.assertRaises(ValueError):
                store.reserve()
            store.path.write_text('{"version":1,"initial_sequence":0,"next_sequence":false}')
            with self.assertRaises(ValueError):
                store.reserve()

    def test_deferred_device_owner_keeps_other_instances_locked_out(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(directory, initial_sequence=100)
            other = SequenceStore(directory)
            finished, reserved = threading.Event(), threading.Event()
            values = []
            with store.transaction():
                store.retain_lock_until(finished.is_set)
            def reserve():
                values.append(other.reserve())
                reserved.set()
            worker = threading.Thread(target=reserve)
            worker.start()
            try:
                self.assertFalse(reserved.wait(.05))
            finally:
                finished.set()
                worker.join(2)
            self.assertTrue(reserved.is_set())
            self.assertEqual(values, [101])


@unittest.skipIf(numpy is None, "analysis extra not installed")
class BridgeBackendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.command = PositionCommand(3, 128, ShadeConfig("Test shade", 2, b"\x12\x34", 8,
                                                          position_enabled=True), "fake-request")

    def backend(self, library, *, initial=100, keep=4, **options):
        return BladeRFBridgeBackend(self.directory.name, initial_sequence=initial,
            keep_artifacts=keep, radio_factory=lambda **kwargs: BridgeRadio(library=library, **kwargs),
            **options)

    def wide_sync(self, library, *, on_submitted=None):
        backend = self.backend(library, profile="wide", rx_gain_db=30)
        # Exercise the real receive/count/coverage paths with a bounded fixture.
        backend.sync_receive_duration_seconds = .75
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, sync_enabled=True)
        with patch("hd_platinum.bladerf_bridge.WIDE_SYNC_POST_TX_SECONDS", .2):
            return backend.submit(SyncCommand(3, target, "wide-sync"),
                                  on_transmit_submitted=on_submitted)

    def test_wide_sync_scales_samples_and_metadata_without_changing_duration(self):
        library, notifications = FakeLibrary(first_status=0x30000), []
        result = self.wide_sync(library, on_submitted=lambda: notifications.append("submitted"))
        self.assertEqual(result["duration_seconds"], .112134)
        self.assertEqual(library.rates, {RX1: 32_000_000, TX1: 32_000_000})
        self.assertEqual(library.frequencies, {RX1: 2_446_000_000, TX1: 2_440_000_000})
        self.assertEqual(library.gains, {RX1: 30, TX1: 50})
        self.assertEqual(library.tx_samples, 3_588_288)
        self.assertEqual(library.tx_calls, 14)
        self.assertEqual(library.rx_count, 24_000_000)
        self.assertEqual(notifications, ["submitted"])
        run = next((Path(self.directory.name) / "runs").iterdir())
        plan = json.loads((run / "plan.json").read_text())
        self.assertEqual((plan["sample_rate_hz"], plan["sample_count"]), (32_000_000, 3_588_288))
        self.assertEqual(plan["source_sample_rate_hz"], 8_000_000)
        self.assertEqual((run / "transmit.sc16q11").stat().st_size, 3_588_288 * 4)
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertEqual(receipt["rf_profile"], "wide")
        self.assertTrue(receipt["wide_timestamp_check"]["passed"])
        self.assertTrue(receipt["active_rx_readback"]["passed"])
        self.assertGreaterEqual(receipt["wide_post_tx_capture_seconds"], .2)
        self.assertEqual(receipt["configuration_readbacks"][str(RX1)]["bandwidth_hz"], 32_000_000)
        self.assertTrue(library.closed and receipt["bias_tees_off_verified"])
        self.assertFalse(receipt["rx_worker_alive"])
        # A second backend/profile consumes the next shared sequence.
        self.assertEqual(self.backend(FakeLibrary(), initial=None)(self.command)["sequence"], 101)

    def test_wide_invalid_profile_does_not_create_sequence_state(self):
        with self.assertRaisesRegex(ValueError, "profile"):
            self.backend(FakeLibrary(), profile="unrecognized")
        self.assertFalse((Path(self.directory.name) / "sequence.json").exists())

    def test_receive_center_is_restricted_before_sequence_state_creation(self):
        for profile, center in (("narrow", 2_461_500_000), ("narrow", 2_446_000_000),
                                ("wide", 2_440_000_000), ("wide", 2_461_000_000),
                                ("wide", 2_461_500_000.0), ("wide", True), ("wide", "2461500000")):
            with self.subTest(profile=profile, center=center), self.assertRaisesRegex(ValueError, "rx_center_hz"):
                self.backend(FakeLibrary(), profile=profile, rx_center_hz=center)
        self.assertFalse((Path(self.directory.name) / "sequence.json").exists())

    def test_wide_active_clock_rate_status_and_window_failures_refuse_iq(self):
        class WrongEpoch(FakeLibrary):
            def bladerf_get_timestamp(self, device, direction, value):
                _set(value, C.c_uint64, self.clock + (2_000_000 if direction else 0))
                return 0
        class ChangedRate(FakeLibrary):
            def bladerf_get_sample_rate(self, device, channel, value):
                _set(value, C.c_uint, 8_000_000 if TX1 in self.enabled else self.rates[channel])
                return 0
        cases = ((WrongEpoch(), .2, "timestamp epoch"),
                 (ChangedRate(), .2, "wide RX configuration"),
                 (FakeLibrary(first_status=4), .2, "healthy first block"),
                 (FakeLibrary(), 16, "wide RX window"))
        for library, tail_seconds, expected_error in cases:
            with self.subTest(library=type(library).__name__), tempfile.TemporaryDirectory() as directory:
                backend = BladeRFBridgeBackend(directory, initial_sequence=100, profile="wide",
                    radio_factory=lambda **kwargs: BridgeRadio(library=library, **kwargs))
                backend.sync_receive_duration_seconds = .75
                target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, sync_enabled=True)
                # The final case retains the real16-second tail requirement;
                # its shortened receive window must refuse before submission.
                with patch("hd_platinum.bladerf_bridge.WIDE_SYNC_POST_TX_SECONDS", tail_seconds):
                    with self.assertRaisesRegex(RadioError, expected_error):
                        backend(SyncCommand(3, target, "refused-wide"))
                self.assertEqual(library.tx_calls, 0)
                self.assertTrue(library.closed)
                self.assertEqual(SequenceStore(directory).reserve(), 101)

    def test_wide_late_schedule_loses_tail_after_notification_without_retry(self):
        class LateSchedule(FakeLibrary):
            tx_queries = 0
            def bladerf_get_timestamp(self, device, direction, value):
                if direction:
                    self.tx_queries += 1
                    if self.tx_queries == 2:
                        self.clock += 12_800_000
                return super().bladerf_get_timestamp(device, direction, value)
        library, notifications = LateSchedule(), []
        with self.assertRaisesRegex(RadioError, "native response window"):
            self.wide_sync(library, on_submitted=lambda: notifications.append("submitted"))
        self.assertEqual(notifications, ["submitted"])
        self.assertEqual(library.tx_calls, 14)
        self.assertTrue(library.closed)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_wide_receive_failure_after_submission_cleans_up_without_retry(self):
        library, notifications = FakeLibrary(fail_rx_after_tx=True), []
        with self.assertRaisesRegex(RadioError, "receive capture failed"):
            self.wide_sync(library, on_submitted=lambda: notifications.append("submitted"))
        self.assertEqual(notifications, ["submitted"])
        self.assertEqual(library.tx_calls, 14)
        self.assertTrue(library.closed)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_success_opens_new_session_with_checked_active_gain_and_private_artifacts(self):
        first = FakeLibrary()
        result = self.backend(first)(self.command)
        self.assertEqual((result["status"], result["frames_sent"], result["sequence"]), ("submitted", 10, 100))
        self.assertEqual(result["duration_seconds"], .112134)
        self.assertTrue(first.closed)
        self.assertFalse(first.enabled)
        self.assertEqual(set(first.bias_off_calls), {0, 1, 2, 3})
        self.assertGreater(first.tx_calls, 0)
        self.assertEqual(first.rx_count, 24_000_000)
        second = FakeLibrary()
        self.assertEqual(self.backend(second, initial=None, keep=1)(self.command)["sequence"], 101)
        runs = list((Path(self.directory.name) / "runs").iterdir())
        self.assertEqual(len(runs), 1)
        receipt = json.loads((runs[0] / "receipt.json").read_text())
        self.assertTrue(receipt["active_readback"]["passed"])
        self.assertTrue(receipt["radio_session_closed"])
        self.assertTrue(receipt["bias_tees_off_verified"])
        for path in runs[0].iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("1234", json.dumps(result))
        self.assertNotIn("Test shade", json.dumps(result))

    def test_transaction_byte_wrap_preserves_command_count_and_persistent_ordinal(self):
        first = self.backend(FakeLibrary(), initial=511)(self.command)
        second = self.backend(FakeLibrary(), initial=None)(self.command)
        self.assertEqual((first["sequence"], first["command_count"], first["transaction_counter"]),
                         (511, 1, 255))
        self.assertEqual((second["sequence"], second["command_count"], second["transaction_counter"]),
                         (512, 1, 0))
        plans = {}
        for run in (Path(self.directory.name) / "runs").iterdir():
            plan = json.loads((run / "plan.json").read_text())
            receipt = json.loads((run / "receipt.json").read_text())
            plans[plan["sequence"]] = plan
            self.assertEqual(receipt["command_count"], 1)
            self.assertEqual(receipt["transaction_counter"], plan["transaction_counter"])
            for frame in plan["frames"][1::2]:
                self.assertEqual(bytes.fromhex(frame["payload_hex"])[4:6],
                                 bytes((1, plan["transaction_counter"])))
        self.assertEqual(set(plans), {511, 512})
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 513)

    def test_first_rx_status_failure_refuses_iq_and_burns_sequence(self):
        lib = FakeLibrary(first_status=1)
        with self.assertRaises(RadioError):
            self.backend(lib)(self.command)
        self.assertEqual(lib.tx_calls, 0)
        self.assertTrue(lib.closed)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_sync_submits_one_finite_burst_with_longer_rx_and_closes(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, sync_enabled=True)
        library = FakeLibrary()
        result = self.backend(library)(SyncCommand(3, target, "sync-test"))
        self.assertEqual(result["frames_sent"], 10)
        self.assertEqual(result["duration_seconds"], .112134)
        self.assertEqual(library.rx_count, 144_000_000)
        self.assertTrue(library.closed)
        self.assertFalse(library.enabled)
        run = next((Path(self.directory.name) / "runs").iterdir())
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertEqual(receipt["operation"], "sync")
        self.assertEqual(receipt["receive_duration_seconds"], 18.0)
        self.assertTrue(receipt["bias_tees_off_verified"])

    def test_jog_uses_narrow_three_second_capture_and_shared_sequence(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
        library = FakeLibrary()
        result = self.backend(library)(JogCommand(3, target, "jog-test"))
        self.assertEqual((result["frames_sent"], result["duration_seconds"], result["sequence"]),
                         (10, .112134, 100))
        self.assertEqual(library.rx_count, 24_000_000)
        self.assertTrue(library.closed)
        self.assertFalse(library.enabled)
        run = next((Path(self.directory.name) / "runs").iterdir())
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertEqual((receipt["operation"], receipt["rf_profile"], receipt["receive_duration_seconds"]),
                         ("jog", "narrow", 3.0))
        self.assertEqual(receipt["tx_configuration"]["sample_rate_hz"], 8_000_000)
        self.assertTrue(receipt["bias_tees_off_verified"])
        self.assertEqual(self.backend(FakeLibrary(), initial=None)(self.command)["sequence"], 101)

    def test_disabled_jog_refuses_before_sequence_reservation(self):
        library = FakeLibrary()
        backend = self.backend(library, profile="wide")
        disabled = ShadeConfig("Test shade", 2, b"\x12\x34", 8)
        with self.assertRaises(ValueError):
            backend(JogCommand(3, disabled, "disabled-jog"))
        self.assertEqual(library.tx_calls, 0)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 100)
        narrow = self.backend(library, initial=None)
        with self.assertRaises(ValueError):
            narrow(JogCommand(3, disabled, "disabled-jog"))
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_wide_jog_records_both_upper_native_channels_with_unchanged_finite_tx(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
        library, notifications = FakeLibrary(first_status=0x30000), []
        backend = self.backend(library, profile="wide", rx_center_hz=2_461_500_000, rx_gain_db=30)
        result = backend.submit(JogCommand(3, target, "wide-jog"),
                                on_transmit_submitted=lambda: notifications.append("submitted"))
        self.assertEqual((result["frames_sent"], result["duration_seconds"], result["sequence"]),
                         (10, .112134, 100))
        self.assertEqual(library.rates, {RX1: 32_000_000, TX1: 32_000_000})
        self.assertEqual(library.frequencies, {RX1: 2_461_500_000, TX1: 2_440_000_000})
        self.assertEqual(library.gains, {RX1: 30, TX1: 50})
        self.assertEqual((library.tx_calls, library.tx_samples, library.rx_count),
                         (14, 3_588_288, 96_000_000))
        self.assertEqual(notifications, ["submitted"])
        run = next((Path(self.directory.name) / "runs").iterdir())
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertEqual((receipt["operation"], receipt["receive_duration_seconds"],
                          receipt["minimum_post_tx_seconds"]), ("jog", 3.0, 2.25))
        self.assertEqual(receipt["capture_coverage"]["covered_known_channels_hz"],
                         [2_452_000_000, 2_471_000_000])
        self.assertEqual(receipt["capture_coverage"]["excluded_known_channels_hz"],
                         [2_433_000_000, 2_440_000_000])
        self.assertEqual(receipt["wide_receive_window"]["required_remaining_seconds"], 2.75)
        self.assertGreaterEqual(receipt["wide_post_tx_capture_seconds"], 2.25)
        self.assertTrue(receipt["active_rx_readback"]["passed"])
        self.assertTrue(receipt["radio_session_closed"] and receipt["bias_tees_off_verified"])
        self.assertFalse(receipt["rx_worker_alive"] or library.enabled)
        plan = json.loads((run / "plan.json").read_text())
        self.assertEqual((plan["sample_count"], plan["source_sample_rate_hz"]), (3_588_288, 8_000_000))
        self.assertEqual(bytes.fromhex(plan["frames"][0]["payload_hex"])[6:11], bytes((12, 8, 1, 0, 1)))
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_wide_jog_window_or_changed_receive_center_refuses_before_iq(self):
        class DelayedPreparation(FakeLibrary):
            def bladerf_get_timestamp(self, device, direction, value):
                _set(value, C.c_uint64, self.clock + 12_800_000)
                return 0
        class ChangedCenter(FakeLibrary):
            def bladerf_get_frequency(self, device, channel, value):
                _set(value, C.c_uint64, 2_446_000_000 if channel == RX1 else self.frequencies[channel])
                return 0
        for library, error in ((DelayedPreparation(), "wide RX window"),
                               (ChangedCenter(), "healthy first block")):
            with self.subTest(library=type(library).__name__), tempfile.TemporaryDirectory() as directory:
                backend = BladeRFBridgeBackend(directory, initial_sequence=100, profile="wide",
                    rx_center_hz=2_461_500_000,
                    radio_factory=lambda **kwargs: BridgeRadio(library=library, **kwargs))
                target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
                with self.assertRaisesRegex(RadioError, error):
                    backend(JogCommand(3, target, "refused-wide-jog"))
                self.assertEqual(library.tx_calls, 0)
                self.assertTrue(library.closed)
                self.assertFalse(library.enabled)
                self.assertEqual(SequenceStore(directory).reserve(), 101)

    def test_wide_jog_late_schedule_fails_coverage_without_resubmission(self):
        class LateSchedule(FakeLibrary):
            tx_queries = 0
            def bladerf_get_timestamp(self, device, direction, value):
                if direction:
                    self.tx_queries += 1
                    if self.tx_queries == 2:
                        self.clock += 16_000_000
                return super().bladerf_get_timestamp(device, direction, value)
        library, notifications = LateSchedule(), []
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
        backend = self.backend(library, profile="wide", rx_center_hz=2_461_500_000)
        with self.assertRaisesRegex(RadioError, "native response window"):
            backend.submit(JogCommand(3, target, "late-wide-jog"),
                           on_transmit_submitted=lambda: notifications.append("submitted"))
        self.assertEqual(notifications, ["submitted"])
        self.assertEqual(library.tx_calls, 14)
        self.assertTrue(library.closed)
        self.assertFalse(library.enabled)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_jog_failed_transmission_burns_sequence_without_retry_and_closes(self):
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, jog_enabled=True)
        library = FakeLibrary(fail_tx=True)
        with self.assertRaises(RadioError):
            self.backend(library)(JogCommand(3, target, "failed-jog"))
        self.assertEqual(library.tx_calls, 1)
        self.assertTrue(library.closed)
        self.assertFalse(library.enabled)
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_submission_hook_failure_keeps_capture_cleanup_and_stage_times(self):
        library = FakeLibrary()
        backend = self.backend(library)
        target = ShadeConfig("Test shade", 2, b"\x12\x34", 8, sync_enabled=True)
        notifications = []
        def submitted():
            self.assertFalse(library.closed)
            self.assertNotIn(TX1, library.enabled)
            self.assertGreater(library.tx_calls, 0)
            notifications.append("submitted")
            raise OSError("fake disconnected client")
        with self.assertLogs("hd_platinum.bladerf_bridge", level="ERROR"):
            result = backend.submit(SyncCommand(3, target, "sync-hook"),
                                    on_transmit_submitted=submitted)
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(notifications, ["submitted"])
        self.assertEqual(library.rx_count, 144_000_000)
        self.assertTrue(library.closed)
        run = next((Path(self.directory.name) / "runs").iterdir())
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertTrue(receipt["submission_notification_failed"])
        self.assertIsNone(receipt["failure"])
        stages = receipt["stage_times"]
        ordered = ("reserved", "waveform_ready", "radio_opened", "radio_configured",
                   "receive_started", "first_rx_block_returned", "transmit_called",
                   "active_tx_verified", "tx_submitted", "cleanup_checked")
        self.assertEqual(sorted(stages[name]["elapsed_seconds"] for name in ordered),
                         [stages[name]["elapsed_seconds"] for name in ordered])
        self.assertIn("receive_finished", stages)
        self.assertTrue(all(stage["utc"].endswith("+00:00") for stage in stages.values()))

    def test_failed_transmit_never_notifies_submission(self):
        for flag in ("bad_gain", "fail_tx"):
            with self.subTest(flag=flag):
                library, notifications = FakeLibrary(**{flag: True}), []
                with self.assertRaises(RadioError):
                    self.backend(library).submit(self.command,
                        on_transmit_submitted=lambda: notifications.append("unexpected"))
                self.assertEqual(notifications, [])
                self.assertTrue(library.closed)

    def test_receive_failure_after_submission_still_cleans_up_without_retry(self):
        library, notifications = FakeLibrary(fail_rx_after_tx=True), []
        with self.assertRaisesRegex(RadioError, "receive capture failed"):
            self.backend(library).submit(self.command,
                on_transmit_submitted=lambda: notifications.append("submitted"))
        self.assertEqual(notifications, ["submitted"])
        self.assertEqual(library.tx_calls, 4)
        self.assertTrue(library.closed)
        run = next((Path(self.directory.name) / "runs").iterdir())
        receipt = json.loads((run / "receipt.json").read_text())
        self.assertIn("tx_submitted", receipt["stage_times"])
        self.assertEqual(receipt["state"], "failed")
        self.assertFalse(receipt["automatic_retry"])
        self.assertEqual(SequenceStore(self.directory.name).reserve(), 101)

    def test_active_gain_dsa_and_frequency_failures_refuse_iq(self):
        for flag in ("bad_gain", "bad_dsa", "bad_frequency"):
            with self.subTest(flag=flag):
                lib = FakeLibrary(**{flag: True})
                with self.assertRaises(RadioError):
                    self.backend(lib)(self.command)
                self.assertEqual(lib.tx_calls, 0)
                self.assertTrue(lib.closed)
                self.assertFalse(lib.enabled)

    def test_uncertain_transmission_failure_closes_and_never_reuses_sequence(self):
        lib = FakeLibrary(fail_tx=True)
        with self.assertRaises(RadioError):
            self.backend(lib)(self.command)
        self.assertEqual(lib.tx_calls, 1)
        self.assertTrue(lib.closed)
        self.assertFalse(lib.enabled)
        next_lib = FakeLibrary()
        self.assertEqual(self.backend(next_lib, initial=None)(self.command)["sequence"], 101)


if __name__ == "__main__":
    unittest.main()
