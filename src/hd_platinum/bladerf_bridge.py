# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Finite 250 kbps bridge backend with durable sequence reservation and RX.

This backend uses the exercised antenna/receive configuration. The caller must
have the corresponding physical RF setup. Receipts report sample submission,
never confirmed shade position. There are no automatic RF retries.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
from uuid import uuid4

from .bladerf import BladeRF, Metadata, RadioConfig, RadioError, RX1, RX2, TX1, TX2
from .rf_bridge import (BANDWIDTH_HZ, CENTER_HZ, DURATION_SECONDS, SAMPLE_COUNT,
                        SAMPLE_RATE_HZ, WIDE_SAMPLE_RATE_HZ, build_bridge_plan,
                        write_bridge_waveform)

WIDE_RX_CENTER_HZ = 2_446_000_000
WIDE_NATIVE_RX_CENTER_HZ = 2_461_500_000
WIDE_RX_BANDWIDTH_HZ = 32_000_000
WIDE_TIMESTAMP_UNCERTAINTY_SECONDS = .025
WIDE_SYNC_POST_TX_SECONDS = 16.0
WIDE_JOG_POST_TX_SECONDS = 2.25


def _now():
    return datetime.now(timezone.utc).isoformat()


def _private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("state directory must be a real directory")
    path.chmod(0o700)
    return path


def _atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SequenceStore:
    """Process-safe local ordinal allocator: reservation precedes every TX.

    Initial seeds are mandatory only for a new store. Supplying the original
    seed again is harmless; a different seed is rejected instead of resetting
    an existing store. The existing version-1 format retains a 16-bit local
    ordinal; its low byte is the firmware's wrapping transaction counter. The
    on-air command-count byte is independent and stays one for this backend.
    Local exhaustion requires operator attention, never silent reset.
    Reservations are not rolled back after exceptions or process death.
    """

    def __init__(self, state_dir, *, initial_sequence=None):
        if initial_sequence is not None and (type(initial_sequence) is not int
                                             or not 0 <= initial_sequence <= 65535):
            raise ValueError("initial_sequence must be an integer within 0..65535")
        self.directory = _private_directory(state_dir)
        self.path = self.directory / "sequence.json"
        self.lock_path = self.directory / "sequence.lock"
        self._local = threading.local()
        with self._locked():
            if self.path.exists() or self.path.is_symlink():
                state = self._read()
                if initial_sequence is not None and initial_sequence != state["initial_sequence"]:
                    raise ValueError("initial_sequence cannot reset an existing sequence store")
            else:
                if initial_sequence is None:
                    raise ValueError("initial_sequence is required for a new sequence store")
                _atomic_json(self.path, {"version": 1, "initial_sequence": initial_sequence,
                                         "next_sequence": initial_sequence})

    @contextmanager
    def _locked(self):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield descriptor
        finally:
            os.close(descriptor)

    def _read(self):
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            text = stream.read(4097)
        if len(text) > 4096:
            raise ValueError("sequence store is oversized")
        state = json.loads(text)
        if (not isinstance(state, dict) or set(state) != {"version", "initial_sequence", "next_sequence"}
                or type(state["version"]) is not int or state["version"] != 1
                or type(state["initial_sequence"]) is not int
                or type(state["next_sequence"]) is not int
                or not 0 <= state["initial_sequence"] <= state["next_sequence"] <= 65536
                or state["initial_sequence"] > 65535):
            raise ValueError("sequence store is invalid; refusing to reuse a sequence")
        return state

    @contextmanager
    def transaction(self):
        """Reserve a sequence and hold the process lock through the radio run."""
        with self._locked() as descriptor:
            state = self._read()
            sequence = state["next_sequence"]
            if sequence > 65535:
                raise ValueError("sequence store is exhausted; automatic wrap is disabled")
            state["next_sequence"] = sequence + 1
            _atomic_json(self.path, state)
            self._local.descriptor = descriptor
            try:
                yield sequence
            finally:
                self._local.descriptor = None

    def retain_lock_until(self, finished):
        """Keep other processes out while a deferred C stream still owns RF."""
        descriptor = os.dup(self._local.descriptor)

        def release():
            try:
                while not finished():
                    time.sleep(.01)
            finally:
                os.close(descriptor)

        try:
            threading.Thread(target=release, name="bridge-deferred-lock", daemon=True).start()
        except BaseException:
            os.close(descriptor)
            raise

    def reserve(self):
        with self.transaction() as sequence:
            return sequence


class BridgeRadio(BladeRF):
    """Checked adapter retaining the existing finite-stream lifetime rules."""

    def __init__(self, *, expected_gain, receive_healthy, receipt, checkpoint,
                 device=None, fpga=None, library=None, stage=None,
                 wide_receive_duration_seconds=None, minimum_post_tx_seconds=0):
        self.expected_gain = expected_gain
        self.receive_healthy = receive_healthy
        self.receipt, self.checkpoint = receipt, checkpoint
        self.stage = stage or (lambda name: None)
        self.wide_receive_duration_seconds = wide_receive_duration_seconds
        self.minimum_post_tx_seconds = minimum_post_tx_seconds
        self.tx_preparations = 0
        super().__init__(device=device, fpga=fpga, library=library)
        if library is None:
            definitions = {
                "get_gain": ([C.c_void_p, C.c_int, C.POINTER(C.c_int)], C.c_int),
                "get_gain_stage": ([C.c_void_p, C.c_int, C.c_char_p, C.POINTER(C.c_int)], C.c_int),
                "get_frequency": ([C.c_void_p, C.c_int, C.POINTER(C.c_uint64)], C.c_int),
                "get_bias_tee": ([C.c_void_p, C.c_int, C.POINTER(C.c_bool)], C.c_int),
            }
            for name, (arguments, result) in definitions.items():
                function = getattr(self.lib, "bladerf_" + name)
                function.argtypes, function.restype = arguments, result

    def quiet(self):
        self.receipt["bias_tees_off_verified"] = False
        super().quiet()
        for channel in (RX1, TX1, RX2, TX2):
            enabled = C.c_bool()
            self._call("get_bias_tee", self.dev, channel, C.byref(enabled))
            if enabled.value:
                raise RadioError("bias tee remains enabled after shutdown")
        self.receipt["bias_tees_off_verified"] = True

    def _prepare_stream(self, channel):
        if channel == RX1:
            super()._prepare_stream(channel)
            if self.wide_receive_duration_seconds is not None:
                self._check_wide_receiver()
            return
        self.tx_preparations += 1
        if channel != TX1 or self.tx_preparations != 1 or not self.receive_healthy():
            raise RadioError("a healthy running receiver is required before the one TX burst")
        super()._prepare_stream(channel)
        gain, dsa, frequency = C.c_int(), C.c_int(), C.c_uint64()
        self._call("get_gain", self.dev, TX1, C.byref(gain))
        self._call("get_gain_stage", self.dev, TX1, b"dsa", C.byref(dsa))
        self._call("get_frequency", self.dev, TX1, C.byref(frequency))
        passed = (gain.value == self.expected_gain and abs(dsa.value - (self.expected_gain - 66)) <= 1
                  and abs(frequency.value - CENTER_HZ) <= 2)
        self.receipt["active_readback"] = {"gain_db": gain.value, "dsa_db": dsa.value,
            "frequency_hz": frequency.value, "passed": passed}
        self.checkpoint()
        if not passed:
            raise RadioError("active TX gain, DSA or frequency differs; refusing IQ")
        if not self.receive_healthy():
            raise RadioError("receiver stopped during active TX verification; refusing IQ")
        if self.wide_receive_duration_seconds is not None:
            self._check_wide_receiver()
            rate = C.c_uint()
            self._call("get_sample_rate", self.dev, TX1, C.byref(rate))
            if rate.value != self.configured[TX1].sample_rate_hz:
                raise RadioError("active TX sample rate changed; refusing IQ")
            self._check_wide_window()
        self.stage("active_tx_verified")

    def _check_wide_receiver(self):
        config = self.configured[RX1]
        frequency, rate, gain = C.c_uint64(), C.c_uint(), C.c_int()
        self._call("get_frequency", self.dev, RX1, C.byref(frequency))
        self._call("get_sample_rate", self.dev, RX1, C.byref(rate))
        self._call("get_gain", self.dev, RX1, C.byref(gain))
        passed = (abs(frequency.value-config.center_hz) <= 2
                  and rate.value == config.sample_rate_hz and gain.value == config.gain_db)
        self.receipt["active_rx_readback"] = {"frequency_hz": frequency.value,
            "sample_rate_hz": rate.value, "gain_db": gain.value, "passed": passed}
        self.checkpoint()
        if not passed:
            raise RadioError("active wide RX configuration changed; refusing IQ")

    def _check_wide_window(self):
        rate = self.configured[RX1].sample_rate_hz
        if rate != self.configured[TX1].sample_rate_hz:
            raise RadioError("wide recording requires equal RX/TX sample rates")
        uncertainty = WIDE_TIMESTAMP_UNCERTAINTY_SECONDS
        before = time.monotonic()
        rx_before, tx, rx_after = self.timestamp(0), self.timestamp(1), self.timestamp(0)
        allowance = round(rate * uncertainty)
        passed = (rx_after >= rx_before and time.monotonic()-before <= uncertainty
                  and rx_before-allowance <= tx <= rx_after+allowance)
        self.receipt["wide_timestamp_check"] = {"rx_before": rx_before, "tx": tx,
            "rx_after": rx_after, "passed": passed, "uncertainty_seconds": uncertainty,
            "basis": "Equal rates and a coarse active shared-epoch bracket; not calibrated absolute timing"}
        if not passed:
            self.checkpoint()
            raise RadioError("RX/TX timestamp epoch check failed; refusing IQ")
        end = (self.receipt["first_rx_block"]["timestamp"]
               + round(self.wide_receive_duration_seconds * rate))
        remaining = (end-rx_after) / rate - uncertainty
        # Include the 150 ms scheduling lead, finite burst, and setup margin.
        required = self.minimum_post_tx_seconds + .5
        self.receipt["wide_receive_window"] = {"remaining_lower_bound_seconds": remaining,
            "required_remaining_seconds": required, "passed": remaining >= required}
        self.checkpoint()
        if remaining < required or not self.receive_healthy():
            raise RadioError("insufficient healthy wide RX window; refusing IQ")

    def _call(self, name, *args):
        if name == "sync_tx":
            if not self.receive_healthy():
                raise RadioError("receiver stopped before IQ submission")
            self.receipt["iq_submission_calls_attempted"] += 1
        result = super()._call(name, *args)
        if name == "sync_tx":
            self.receipt["iq_submission_calls_succeeded"] += 1
        elif name == "sync_rx":
            meta = C.cast(args[3], C.POINTER(Metadata)).contents
            status_mask = 3 if self.wide_receive_duration_seconds is None else ~0x30000
            if not 0 < meta.actual_count <= args[2] or meta.status & status_mask:
                raise RadioError("receiver returned an invalid block or status error")
            if self.receipt["first_rx_block"] is None:
                self.receipt["first_rx_block"] = {"timestamp": meta.timestamp,
                    "sample_count": meta.actual_count, "status": meta.status}
                self.stage("first_rx_block_returned")
        return result


class BladeRFBridgeBackend:
    """One fresh checked device session and bounded concurrent RX per command.

    ``radio_factory`` receives BridgeRadio's keyword arguments; tests can inject
    a BridgeRadio using a fake C library. At most ``keep_artifacts`` private run
    directories are retained, including failed runs. No payload enters the
    public receipt. State locking also serializes sessions across processes.
    The default ``narrow`` profile records the 2440 MHz link at 8 MS/s.
    Opt-in ``wide`` uses 32 MS/s in both directions. Its default RX center of
    2446 MHz covers the 2440 MHz link and native 2433/2452 MHz channels. The
    explicit 2461.5 MHz center instead covers native 2452/2471 MHz, excluding
    2440/2433 MHz. These are nominal passbands, not a reception guarantee.
    """

    name = "bladerf-bridge"
    receive_duration_seconds = 3.0
    sync_receive_duration_seconds = 18.0

    def __init__(self, state_dir, *, initial_sequence=None, gain_db=50, rx_gain_db=40,
                 device=None, fpga=None, radio_factory=None, keep_artifacts=4,
                 profile="narrow", rx_center_hz=None):
        if profile not in ("narrow", "wide"):
            raise ValueError("profile must be narrow or wide")
        self.profile = profile
        rate = WIDE_SAMPLE_RATE_HZ if profile == "wide" else SAMPLE_RATE_HZ
        if rx_center_hz is None:
            rx_center_hz = WIDE_RX_CENTER_HZ if profile == "wide" else CENTER_HZ
        allowed_centers = ((WIDE_RX_CENTER_HZ, WIDE_NATIVE_RX_CENTER_HZ)
                           if profile == "wide" else (CENTER_HZ,))
        if type(rx_center_hz) is not int or rx_center_hz not in allowed_centers:
            raise ValueError("rx_center_hz must be an allowed center for the selected profile")
        # Reuse the radio configuration's strict range/type validation.
        self.tx_config = RadioConfig(rate, CENTER_HZ, BANDWIDTH_HZ, gain_db)
        self.rx_config = RadioConfig(rate, rx_center_hz,
            WIDE_RX_BANDWIDTH_HZ if profile == "wide" else BANDWIDTH_HZ, rx_gain_db)
        known_channels = (2_433_000_000, CENTER_HZ, 2_452_000_000, 2_471_000_000)
        lower = rx_center_hz - self.rx_config.bandwidth_hz // 2
        upper = rx_center_hz + self.rx_config.bandwidth_hz // 2
        self.rx_observation = {
            "nominal_band_hz": [lower, upper],
            "covered_known_channels_hz": [value for value in known_channels if lower < value < upper],
            "excluded_known_channels_hz": [value for value in known_channels if not lower < value < upper],
            "note": "Nominal configured passband; does not guarantee packet reception",
        }
        self.sample_count = SAMPLE_COUNT * (rate // SAMPLE_RATE_HZ)
        if type(keep_artifacts) is not int or not 1 <= keep_artifacts <= 32:
            raise ValueError("keep_artifacts must be within 1..32")
        self.store = SequenceStore(state_dir, initial_sequence=initial_sequence)
        self.runs = _private_directory(self.store.directory / "runs")
        self.keep_artifacts = keep_artifacts
        self.device, self.fpga = device, fpga
        self.radio_factory = BridgeRadio if radio_factory is None else radio_factory

    def _prune(self, keep):
        candidates = sorted((p for p in self.runs.iterdir()
            if re.fullmatch(r"run-[0-9a-f]{32}", p.name) and p.is_dir() and not p.is_symlink()),
            key=lambda p: p.stat().st_mtime_ns, reverse=True)
        for path in candidates[keep:]:
            shutil.rmtree(path)

    def __call__(self, command):
        return self.submit(command)

    def submit(self, command, *, on_transmit_submitted=None):
        """Notify after finite TX, while retaining ownership through RX cleanup.

        The optional notification is observational: failure cannot turn an
        already submitted waveform into a retryable backend error. It neither
        confirms enrollment nor shortens the diagnostic capture.
        """
        from .bridge import JogCommand, SyncCommand
        if on_transmit_submitted is not None and not callable(on_transmit_submitted):
            raise ValueError("on_transmit_submitted must be callable when supplied")
        started, timing_origin = time.monotonic(), _now()
        syncing = isinstance(command, SyncCommand)
        jogging = isinstance(command, JogCommand)
        receive_duration = (self.sync_receive_duration_seconds if syncing
                            else self.receive_duration_seconds)
        wide = self.profile == "wide"
        minimum_post_tx = (WIDE_SYNC_POST_TX_SECONDS if wide and syncing
                           else WIDE_JOG_POST_TX_SECONDS if wide and jogging else 0)
        build_bridge_plan(command, 0)  # Invalid requests cannot consume state.
        with self.store.transaction() as sequence:
            self._prune(self.keep_artifacts - 1)
            directory = self.runs / ("run-" + uuid4().hex)
            directory.mkdir(mode=0o700)
            receipt_path = directory / "receipt.json"
            receipt = {"started_at_utc": _now(), "state": "reserved", "sequence": sequence,
                "operation": "sync" if syncing else "jog" if jogging else "position",
                "rf_profile": self.profile,
                "tx_configuration": vars(self.tx_config),
                "rx_configuration": vars(self.rx_config),
                "capture_coverage": self.rx_observation,
                "receive_duration_seconds": receive_duration,
                "minimum_post_tx_seconds": minimum_post_tx,
                "failure": None, "first_rx_block": None, "active_readback": None,
                "iq_submission_calls_attempted": 0, "iq_submission_calls_succeeded": 0,
                "bias_tees_off_verified": False, "radio_session_closed": False,
                "rx_result": None, "tx_result": None, "automatic_retry": False,
                "stage_times": {}, "timing_origin_utc": timing_origin,
                "submission_notification_failed": False}
            receipt_lock = threading.RLock()

            def stage(name):
                with receipt_lock:
                    receipt["stage_times"][name] = {
                        "utc": _now(), "elapsed_seconds": time.monotonic() - started}

            def checkpoint():
                with receipt_lock:
                    _atomic_json(receipt_path, receipt)

            stage("reserved")
            checkpoint()
            errors, ready = [], threading.Event()
            worker = radio = None

            def healthy():
                first = receipt["first_rx_block"]
                status_mask = ~0x30000 if wide else 3
                return (ready.is_set() and not errors and worker is not None and worker.is_alive()
                    and first is not None and first["sample_count"] > 0 and not first["status"] & status_mask
                    and radio is not None and RX1 in radio._active)

            try:
                plan = build_bridge_plan(command, sequence)
                wire_metadata = plan.as_dict()
                receipt.update({key: wire_metadata[key]
                                for key in ("command_count", "transaction_counter")})
                tx_path, rx_path = directory / "transmit.sc16q11", directory / "receive.sc16q11"
                waveform_options = {"sample_rate_hz": self.tx_config.sample_rate_hz} if wide else {}
                artifact = write_bridge_waveform(tx_path, plan, **waveform_options)
                _atomic_json(directory / "plan.json", {
                    **plan.as_dict(include_private=True, **waveform_options), **artifact})
                receipt["waveform_sha256"] = artifact["sha256"]
                stage("waveform_ready")
                radio_options = ({"wide_receive_duration_seconds": receive_duration,
                                  "minimum_post_tx_seconds": minimum_post_tx} if wide else {})
                radio = self.radio_factory(expected_gain=self.tx_config.gain_db,
                    receive_healthy=healthy, receipt=receipt, checkpoint=checkpoint,
                    device=self.device, fpga=self.fpga, stage=stage, **radio_options)
                with radio:
                    stage("radio_opened")
                    receipt["configuration_readbacks"] = {}
                    for channel, config in ((TX1, self.tx_config), (RX1, self.rx_config)):
                        actual = radio.configure(channel, config)
                        if (actual["sample_rate_hz"] != config.sample_rate_hz
                                or actual["bandwidth_hz"] != config.bandwidth_hz):
                            raise RadioError("radio configuration differs from the exercised profile")
                        receipt["configuration_readbacks"][str(channel)] = actual
                    stage("radio_configured")
                    receipt["state"] = "receiving"
                    checkpoint()

                    def capture():
                        try:
                            receipt["rx_result"] = radio.receive(rx_path,
                                duration_seconds=receive_duration, ready=ready)
                        except BaseException as exc:
                            errors.append(exc)
                            ready.set()
                        finally:
                            stage("receive_finished")

                    worker = threading.Thread(target=capture, name="bridge-rx", daemon=True)
                    # Register ownership before any wait that cancellation can
                    # interrupt. close() must never free a live sync_rx owner.
                    radio._close_waiter = worker
                    stage("receive_started")
                    worker.start()
                    try:
                        if not ready.wait(4) or not healthy():
                            raise RadioError("receiver did not supply a healthy first block; refusing TX")
                        receipt["state"] = "submitting"
                        stage("transmit_called")
                        checkpoint()
                        receipt["tx_result"] = radio.transmit(tx_path)
                        tx = receipt["tx_result"]
                        if (not tx or tx.get("status") != "submitted"
                                or tx.get("samples_sent") != self.sample_count):
                            raise RadioError("finite TX was incomplete")
                        stage("tx_submitted")
                        if on_transmit_submitted is not None:
                            try:
                                on_transmit_submitted()
                            except Exception:
                                receipt["submission_notification_failed"] = True
                                logging.getLogger(__name__).error(
                                    "TX lifecycle notification failed after submission")
                        checkpoint()
                    finally:
                        worker.join(timeout=receive_duration + 5)
                        if worker.is_alive():
                            radio._close_waiter = worker
                            try:
                                radio.quiet()
                            finally:
                                worker.join(timeout=4)
                            raise RadioError("receiver did not finish; device close may be deferred")
                    if errors:
                        raise RadioError("receive capture failed; RF delivery is uncertain") from errors[0]
                    rx, tx = receipt["rx_result"], receipt["tx_result"]
                    if (not rx or not rx["continuous"] or not tx
                            or rx.get("sample_count") != round(receive_duration * self.rx_config.sample_rate_hz)
                            or tx.get("status") != "submitted" or tx.get("samples_sent") != self.sample_count):
                        raise RadioError("finite TX or concurrent capture was incomplete")
                    blocks = rx.get("blocks", [])
                    allowance = (round(WIDE_TIMESTAMP_UNCERTAINTY_SECONDS * self.rx_config.sample_rate_hz)
                                 if wide else 0)
                    if (not blocks or blocks[0]["timestamp"] > tx["start_timestamp"]-allowance
                            or blocks[-1]["timestamp"] + blocks[-1]["count"] < tx["end_timestamp"]+allowance):
                        raise RadioError("receive timestamps do not cover the complete TX interval")
                    if wide:
                        post = ((blocks[-1]["timestamp"] + blocks[-1]["count"]
                                 - tx["end_timestamp"]-allowance) / self.rx_config.sample_rate_hz)
                        receipt["wide_post_tx_capture_seconds"] = post
                        if post < minimum_post_tx:
                            raise RadioError("wide capture lacks the required native response window")
                    receipt["state"] = "submitted"
            except BaseException as exc:
                receipt["state"] = "failed"
                receipt["failure"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                if radio is not None and bool(radio.dev.value) and worker is not None:
                    # The context manager may defer close even when a join was
                    # interrupted, rather than timing out normally.
                    self.store.retain_lock_until(lambda:
                        not worker.is_alive() and not bool(radio.dev.value))
                receipt["finished_at_utc"] = _now()
                receipt["radio_session_closed"] = radio is not None and not bool(radio.dev.value)
                receipt["rx_worker_alive"] = worker is not None and worker.is_alive()
                stage("cleanup_checked")
                checkpoint()
            return {"status": "submitted", "frames_sent": 10, "duration_seconds": DURATION_SECONDS,
                    "sequence": sequence, "command_count": receipt["command_count"],
                    "transaction_counter": receipt["transaction_counter"], "channels_hz": [CENTER_HZ],
                    "detail": ("Finite sync request submitted with concurrent RX; enrollment is unverified"
                               if syncing else
                               "Finite Jog request submitted with concurrent RX; movement is unverified"
                               if jogging else
                               "Finite bridge command submitted with concurrent RX; shade position is unverified")}
