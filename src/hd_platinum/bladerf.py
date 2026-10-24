# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Finite bladeRF 2.0 transmissions and timestamped bench captures.

The ctypes ABI below deliberately requires libbladeRF 2.6: that release moved
SC16_Q11_META to enum value 2. Every device session disables all modules and
bias tees before configuration, and disables them again on exit. Hardware must
be connected appropriately by the operator before invoking a transmit method.
"""

from __future__ import annotations

import ctypes as C
import ctypes.util
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import threading
import time


RX1, TX1, RX2, TX2 = 0, 1, 2, 3
META_FORMAT = 2
BURST_START, BURST_END, RX_NOW = 1, 2, 1 << 31
CHUNK_SAMPLES = 262_144


class RadioError(RuntimeError):
    """A radio operation failed; callers must not report delivery."""


class Metadata(C.Structure):
    _fields_ = [("timestamp", C.c_uint64), ("flags", C.c_uint32),
                ("status", C.c_uint32), ("actual_count", C.c_uint),
                ("reserved", C.c_uint8 * 32)]


class Version(C.Structure):
    _fields_ = [("major", C.c_uint16), ("minor", C.c_uint16),
                ("patch", C.c_uint16), ("describe", C.c_char_p)]


def _load_library():
    name = ctypes.util.find_library("bladeRF")
    if not name:
        # Apple's system Python does not search Homebrew's library prefix.
        for candidate in ("/opt/homebrew/lib/libbladeRF.dylib", "/usr/local/lib/libbladeRF.dylib"):
            if Path(candidate).is_file():
                name = candidate
                break
    if not name:
        raise RadioError("libbladeRF 2.6 is required (on macOS: brew install libbladerf)")
    lib = C.CDLL(name)
    pointer, uint = C.c_void_p, C.c_uint
    definitions = {
        "bladerf_version": ([C.POINTER(Version)], None),
        "bladerf_open": ([C.POINTER(pointer), C.c_char_p], C.c_int),
        "bladerf_close": ([pointer], None),
        "bladerf_strerror": ([C.c_int], C.c_char_p),
        "bladerf_get_board_name": ([pointer], C.c_char_p),
        "bladerf_is_fpga_configured": ([pointer], C.c_int),
        "bladerf_load_fpga": ([pointer, C.c_char_p], C.c_int),
        "bladerf_enable_module": ([pointer, C.c_int, C.c_bool], C.c_int),
        "bladerf_set_bias_tee": ([pointer, C.c_int, C.c_bool], C.c_int),
        "bladerf_set_sample_rate": ([pointer, C.c_int, uint, C.POINTER(uint)], C.c_int),
        "bladerf_get_sample_rate": ([pointer, C.c_int, C.POINTER(uint)], C.c_int),
        "bladerf_set_bandwidth": ([pointer, C.c_int, uint, C.POINTER(uint)], C.c_int),
        "bladerf_set_frequency": ([pointer, C.c_int, C.c_uint64], C.c_int),
        "bladerf_set_gain": ([pointer, C.c_int, C.c_int], C.c_int),
        "bladerf_set_gain_mode": ([pointer, C.c_int, C.c_int], C.c_int),
        "bladerf_sync_config": ([pointer, C.c_int, C.c_int, uint, uint, uint, uint], C.c_int),
        "bladerf_get_timestamp": ([pointer, C.c_int, C.POINTER(C.c_uint64)], C.c_int),
        "bladerf_sync_tx": ([pointer, pointer, uint, C.POINTER(Metadata), uint], C.c_int),
        "bladerf_sync_rx": ([pointer, pointer, uint, C.POINTER(Metadata), uint], C.c_int),
    }
    for name, (args, result) in definitions.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    version = Version()
    lib.bladerf_version(C.byref(version))
    if (version.major, version.minor) != (2, 6):
        raise RadioError("this backend requires the verified libbladeRF 2.6 ABI")
    return lib


@dataclass(frozen=True)
class RadioConfig:
    sample_rate_hz: int = 48_000_000
    center_hz: int = 2_452_000_000
    bandwidth_hz: int = 46_000_000
    gain_db: int = 0

    def __post_init__(self):
        for name in ("sample_rate_hz", "center_hz", "bandwidth_hz", "gain_db"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.sample_rate_hz not in (8_000_000, 16_000_000, 24_000_000, 32_000_000, 48_000_000):
            raise ValueError("sample rate must be 8, 16, 24, 32, or 48 MS/s")
        if not 2_400_000_000 <= self.center_hz <= 2_483_500_000:
            raise ValueError("this backend is restricted to the Platinum 2.4 GHz band")
        if not 1_500_000 <= self.bandwidth_hz <= min(56_000_000, self.sample_rate_hz):
            raise ValueError("bandwidth must fit within the selected sample rate")
        if not -23 <= self.gain_db <= 60:
            raise ValueError("gain must be within -23..60 dB")


class BladeRF:
    def __init__(self, *, device: str | None = None, fpga: str | Path | None = None, library=None):
        self.lib = library if library is not None else _load_library()
        self.dev = C.c_void_p()
        self.device, self.fpga = device, fpga
        self.configured = {}
        self._active = set()
        self._state_lock = threading.RLock()
        self._close_waiter = None
        self._deferred_close = False

    def _enable(self, channel, enabled):
        with self._state_lock:
            # An enable can fail after changing hardware state. Retain the
            # active marker until a successful disable has completed.
            if enabled:
                self._active.add(channel)
            self._call("enable_module", self.dev, channel, enabled)
            if not enabled:
                self._active.discard(channel)

    def _reserve_stream(self, channel):
        with self._state_lock:
            if not self.dev.value:
                raise RadioError("radio is not open")
            if channel in self._active:
                raise RadioError("channel already has an active stream")
            self._active.add(channel)

    def _prepare_stream(self, channel):
        with self._state_lock:
            # Disabling the last module in a direction deinitializes that
            # direction's sync interface. Reinitialize for every finite run.
            self._configure_stream(channel)
            self._enable(channel, True)

    def _configure_stream(self, channel):
        # Wideband RX needs more buffering than finite TX. Preserve these
        # settings both at initial setup and when restarting a direction.
        buffers, transfers = (64, 32) if channel == RX1 else (32, 16)
        self._call("sync_config", self.dev, channel, META_FORMAT, buffers, 65_536, transfers, 3000)

    def _call(self, name, *args):
        result = getattr(self.lib, "bladerf_" + name)(*args)
        if result < 0:
            reason = self.lib.bladerf_strerror(result).decode("utf-8", "replace")
            raise RadioError(f"{name}: {reason}")
        return result

    def __enter__(self):
        self._call("open", C.byref(self.dev), self.device.encode() if self.device else None)
        try:
            if self.lib.bladerf_get_board_name(self.dev) != b"bladerf2":
                raise RadioError("this backend is only validated for bladeRF 2.0 micro")
            if not self._call("is_fpga_configured", self.dev):
                if self.fpga is None:
                    raise RadioError("FPGA is not loaded; provide a compatible temporary FPGA image")
                self._call("load_fpga", self.dev, os.fsencode(self.fpga))
            self.quiet()
            return self
        except BaseException:
            self.close(suppress_errors=True)
            raise

    def quiet(self):
        errors = []
        for channel in (TX1, TX2, RX1, RX2):
            for operation in ("enable_module", "set_bias_tee"):
                try:
                    if operation == "enable_module":
                        self._enable(channel, False)
                    else:
                        self._call(operation, self.dev, channel, False)
                except RadioError as exc:
                    errors.append(str(exc))
        if errors:
            raise RadioError("failed to disable radio: " + "; ".join(errors))

    def close(self, *, suppress_errors=False):
        if not self.dev.value:
            return
        if self._close_waiter is not None and self._close_waiter.is_alive():
            # A synchronous C call may still own the device pointer. Never free
            # it underneath that call, even after a cancellation timeout.
            if not self._deferred_close:
                self._deferred_close = True
                def finish_close():
                    self._close_waiter.join()
                    self.close(suppress_errors=True)
                threading.Thread(target=finish_close, name="bladerf-deferred-close", daemon=True).start()
            return
        try:
            self.quiet()
        except RadioError:
            if not suppress_errors:
                raise
        finally:
            self.lib.bladerf_close(self.dev)
            self.dev = C.c_void_p()
            self.configured.clear()

    def __exit__(self, exc_type, exc, traceback):
        self.close(suppress_errors=exc_type is not None)

    def configure(self, channel: int, config: RadioConfig):
        with self._state_lock:
            if not self.dev.value:
                raise RadioError("radio is not open")
            if self._active:
                raise RadioError("stop all streams before changing shared radio clocks")
            return self._configure(channel, config)

    def _configure(self, channel: int, config: RadioConfig):
        if channel not in (RX1, TX1):
            raise ValueError("only RX1 and TX1 are supported")
        self._enable(channel, False)
        actual_rate, actual_bandwidth = C.c_uint(), C.c_uint()
        self._call("set_sample_rate", self.dev, channel, config.sample_rate_hz, C.byref(actual_rate))
        if actual_rate.value != config.sample_rate_hz:
            raise RadioError("radio could not set the exact sample rate")
        self._call("set_frequency", self.dev, channel, config.center_hz)
        self._call("set_bandwidth", self.dev, channel, config.bandwidth_hz, C.byref(actual_bandwidth))
        if channel == RX1:
            self._call("set_gain_mode", self.dev, channel, 1)
        self._call("set_gain", self.dev, channel, config.gain_db)
        # RX_X1=0, TX_X1=1. Metadata is mandatory in both directions.
        self._configure_stream(channel)
        self.configured[channel] = config
        # Setting a second direction must not silently change the first rate.
        for configured_channel, wanted in self.configured.items():
            actual = C.c_uint()
            self._call("get_sample_rate", self.dev, configured_channel, C.byref(actual))
            if actual.value != wanted.sample_rate_hz:
                self.configured.clear()
                raise RadioError("RX/TX sample-rate coupling changed a configured rate")
        return {"sample_rate_hz": actual_rate.value, "bandwidth_hz": actual_bandwidth.value}

    def timestamp(self, direction):
        result = C.c_uint64()
        self._call("get_timestamp", self.dev, direction, C.byref(result))
        return result.value

    def transmit(self, path: str | Path, *, settle_seconds: float = .15) -> dict:
        config = self.configured[TX1]
        path = Path(path)
        size = path.stat().st_size
        if size % 4 or not 0 < size <= config.sample_rate_hz * 4 * 2:
            raise ValueError("TX input must contain complete SC16Q11 samples, at most two seconds")
        if not math.isfinite(settle_seconds) or not .05 <= settle_seconds <= .5:
            raise ValueError("settling time must be within 0.05..0.5 seconds")
        count = size // 4
        with path.open("rb") as source:
            self._reserve_stream(TX1)
            try:
                self._prepare_stream(TX1)
                start = self.timestamp(1) + round(config.sample_rate_hz * settle_seconds)
                sent = 0
                while sent < count:
                    block = source.read(min(CHUNK_SAMPLES, count-sent) * 4)
                    if len(block) % 4 or not block:
                        raise RadioError("waveform changed or was truncated during transmission")
                    samples = len(block) // 4
                    metadata = Metadata()
                    metadata.timestamp = start + sent
                    metadata.flags = (BURST_START if sent == 0 else 0) | (BURST_END if sent+samples == count else 0)
                    buffer = C.create_string_buffer(block)
                    self._call("sync_tx", self.dev, buffer, samples, C.byref(metadata), 3000)
                    sent += samples
                end = start + count
                deadline = time.monotonic() + 4
                while self.timestamp(1) < end + 4096:
                    if time.monotonic() > deadline:
                        raise RadioError("timed out waiting for the finite TX burst to finish")
                    time.sleep(.005)
            finally:
                self._enable(TX1, False)
        return {"status": "submitted", "samples_sent": count,
                "duration_seconds": count/config.sample_rate_hz,
                "start_timestamp": start, "end_timestamp": end,
                "tx_underrun_detection": "unavailable in libbladeRF; verify with a receiver",
                "gain_db": config.gain_db}

    def receive(self, path: str | Path, *, duration_seconds: float, ready=None) -> dict:
        config = self.configured[RX1]
        if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 120:
            raise ValueError("capture duration must be within 0..120 seconds")
        total = round(duration_seconds * config.sample_rate_hz)
        if total < 1:
            raise ValueError("capture duration must contain at least one sample")
        blocks, received, overruns, gaps = [], 0, 0, 0
        previous_end = None
        buffer = C.create_string_buffer(CHUNK_SAMPLES * 4)
        completed, failure = False, None
        # Create outside the try so refusing an existing IQ file cannot replace
        # its metadata. Once created, even a failed capture gets a sidecar.
        output = Path(path).open("xb")
        try:
            with output:
                os.chmod(path, 0o600)
                self._reserve_stream(RX1)
                try:
                    self._prepare_stream(RX1)
                    while received < total:
                        metadata = Metadata()
                        metadata.flags = RX_NOW
                        wanted = min(CHUNK_SAMPLES, total-received)
                        self._call("sync_rx", self.dev, buffer, wanted, C.byref(metadata), 3000)
                        actual = metadata.actual_count
                        if not 0 < actual <= wanted:
                            raise RadioError("receiver returned an invalid contiguous sample count")
                        output.write(buffer.raw[:actual * 4])
                        if previous_end is not None and metadata.timestamp != previous_end:
                            gaps += 1
                        overruns += bool(metadata.status & 1)
                        blocks.append({"offset_samples": received, "timestamp": metadata.timestamp,
                                       "count": actual, "status": metadata.status})
                        previous_end = metadata.timestamp + actual
                        received += actual
                        if ready is not None:
                            ready.set()
                finally:
                    self._enable(RX1, False)
            completed = True
        except BaseException as exc:
            failure = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            result = {"sample_rate_hz": config.sample_rate_hz, "center_hz": config.center_hz,
                      "requested_sample_count": total, "sample_count": received,
                      "completed": completed, "failure": failure,
                      "overruns": overruns, "timestamp_gaps": gaps,
                      "continuous": completed and overruns == 0 and gaps == 0, "blocks": blocks}
            metadata_path = Path(str(path)+".metadata.json")
            with metadata_path.open("w") as sidecar:
                os.chmod(metadata_path, 0o600)
                sidecar.write(json.dumps(result, indent=2)+"\n")
        return result


def conducted_test(tx_path, rx_path, *, tx_config: RadioConfig, rx_config: RadioConfig,
                   device=None, fpga=None, duration_seconds=1.0):
    """Use only after the operator connects TX1→40 dB attenuation→DC block→RX1."""
    if tx_config.sample_rate_hz + rx_config.sample_rate_hz > 80_000_000:
        raise ValueError("conducted test exceeds the 80 MS/s combined streaming limit")
    if duration_seconds < .5 + Path(tx_path).stat().st_size / (4*tx_config.sample_rate_hz):
        raise ValueError("receive window must cover settling and the complete waveform")
    result, errors, ready = {}, [], threading.Event()
    with BladeRF(device=device, fpga=fpga) as radio:
        radio.configure(TX1, tx_config)
        radio.configure(RX1, rx_config)
        def capture():
            try:
                result["rx"] = radio.receive(rx_path, duration_seconds=duration_seconds, ready=ready)
            except BaseException as exc:
                errors.append(exc)
                ready.set()
        worker = threading.Thread(target=capture, name="bladerf-bench-rx", daemon=True)
        worker.start()
        try:
            if not ready.wait(4):
                raise RadioError("receiver did not become ready")
            if errors:
                raise errors[0]
            result["tx"] = radio.transmit(tx_path)
        finally:
            worker.join(timeout=duration_seconds+5)
            if worker.is_alive():
                # Register before cancellation, which itself can fail. The
                # context manager will defer closing if the thread stays live.
                radio._close_waiter = worker
                try:
                    radio.quiet()
                finally:
                    worker.join(timeout=4)
                raise RadioError("receiver did not finish")
        if errors:
            raise errors[0]
    return result


class BladeRFBackend:
    """Submit three finite 8 MS/s channel bursts in separate radio sessions.

    This uses separately validated narrowband waveforms. Retuning and settling
    separate the bursts, so it does not reproduce the remote's rapid hopping.
    """
    def __init__(self, cache_dir, *, gain_db=35, device=None, fpga=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = RadioConfig(sample_rate_hz=8_000_000, bandwidth_hz=6_000_000, gain_db=gain_db)
        self.device, self.fpga = device, fpga
        self._command_lock = threading.Lock()

    def __call__(self, command):
        with self._command_lock:
            return self._send_command(command)

    def _send_command(self, command):
        import hashlib
        from .rf import REMOTE_FREQUENCIES_HZ
        from .rf_waveform import WaveformConfig, build_command_plan, write_waveform

        prepared = []
        # Complete every synthesis before opening the device. A failure on a
        # later channel must not occur after an earlier channel has transmitted.
        for channel in REMOTE_FREQUENCIES_HZ:
            waveform_config = WaveformConfig(sample_rate_hz=self.config.sample_rate_hz,
                center_hz=channel, channels_hz=(channel,))
            plan = build_command_plan(command.remote_id, str(command.group), command.action,
                action_repetitions=500, release_repetitions=500, config=waveform_config)
            # Names contain only a digest of payload + channel. A unique mode
            # 0600 temporary file stays private throughout atomic replacement.
            key = hashlib.sha256(command.payload + channel.to_bytes(8, "big")).hexdigest()[:16]
            path = self._write_private_waveform(key, plan, write_waveform)
            prepared.append((channel, path, plan))

        results = self._transmit_prepared(prepared)
        return {"status": "submitted", "frames_sent": sum(plan.frame_count for _, _, plan in prepared),
                "duration_seconds": sum(result["duration_seconds"] for result in results),
                "channels_hz": list(REMOTE_FREQUENCIES_HZ),
                "detail": "Three sequential channel bursts at 8 MS/s submitted. Duration excludes device setup, "
                          "retuning and settling gaps; this sequence differs from the remote's rapid "
                          "hopping. Shade movement requires observation."}

    def _write_private_waveform(self, key, plan, writer):
        import tempfile
        path = self.cache_dir / (key+".sc16q11")
        descriptor, temporary_name = tempfile.mkstemp(prefix=key+".", suffix=".pending", dir=self.cache_dir)
        temporary = Path(temporary_name)
        os.close(descriptor)
        try:
            writer(temporary, plan, overwrite=True)
            os.chmod(temporary, 0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def _transmit_prepared(self, prepared):
        results = []
        for channel, path, plan in prepared:
            # Reconfiguring a sample rate can reset the FPGA timestamp while
            # libbladeRF 2.6 retains its prior TX cursor across sync_config.
            # A fresh handle keeps the hardware and host timestamp epochs
            # consistent, and closes/disables one channel before the next.
            with BladeRF(device=self.device, fpga=self.fpga) as radio:
                config = RadioConfig(sample_rate_hz=self.config.sample_rate_hz, center_hz=channel,
                    bandwidth_hz=self.config.bandwidth_hz, gain_db=self.config.gain_db)
                radio.configure(TX1, config)
                results.append(radio.transmit(path))
        return results


class BladeRFPositionBackend(BladeRFBackend):
    """Submit a candidate position sequence for an explicitly enabled target.

    Only typed commands resolved from shade configuration are accepted. The
    fixed 0x50/0x32 profile is provisional and does not confirm shade movement.
    This backend never connects to the original bridge.
    """

    def _send_command(self, command):
        import hashlib
        from .bridge import PositionCommand, ShadeConfig
        from .rf import REMOTE_FREQUENCIES_HZ
        from .rf_positions import build_position_plan, write_position_waveform
        from .rf_waveform import WaveformConfig

        if not isinstance(command, PositionCommand) or not isinstance(command.target, ShadeConfig):
            raise ValueError("a PositionCommand with a configured shade target is required")
        target = command.target
        if target.position_enabled is not True:
            raise ValueError("position target is disabled until its RF mapping is validated")
        if type(target.feature) is not int or target.feature != 4:
            raise ValueError("only primary-position feature 4 is supported")
        room_rf_id, mask, position = target.room_rf_id, target.mask, command.position
        if not isinstance(room_rf_id, bytes) or len(room_rf_id) != 2:
            raise ValueError("room RF ID must contain exactly two bytes")
        if type(mask) is not int or not 1 <= mask <= 128 or mask & (mask-1):
            raise ValueError("shade mask must be a one-hot byte within 1..128")
        if type(position) is not int or not 0 <= position <= 255:
            raise ValueError("position must be an integer within 0..255")
        if type(command.shade) is not int or not 0 <= command.shade <= 99:
            raise ValueError("shade must be an integer within 0..99")

        prepared = []
        for channel in REMOTE_FREQUENCIES_HZ:
            # The original cycles three frequencies in 234 us slots, so a
            # single frequency repeats every 702 us. Preserve that cadence
            # while transmitting each channel in its own finite session.
            waveform_config = WaveformConfig(sample_rate_hz=self.config.sample_rate_hz,
                center_hz=channel, channels_hz=(channel,), slot_us=702,
                deviation_hz=320_000, lead_in_us=49, ramp_us=2)
            plan = build_position_plan(room_rf_id, mask, position, config=waveform_config,
                command_repetitions=2100, followup_repetitions=425)
            key = hashlib.sha256(b"position-v2\x00" + plan.command_payload + plan.followup_payload
                                 + channel.to_bytes(8, "big")).hexdigest()[:16]
            path = self._write_private_waveform(key, plan, write_position_waveform)
            prepared.append((channel, path, plan))

        results = self._transmit_prepared(prepared)
        return {"status": "submitted", "frames_sent": sum(plan.frame_count for _, _, plan in prepared),
                "duration_seconds": sum(result["duration_seconds"] for result in results),
                "channels_hz": list(REMOTE_FREQUENCIES_HZ),
                "detail": "Candidate position sequence submitted as three sequential 8 MS/s channel "
                          "bursts with 702 us same-channel spacing. Duration includes inter-packet silence "
                          "but excludes device setup, retuning and settling gaps. Phase timing and "
                          "repetition counts are provisional; physical position remains unverified."}
