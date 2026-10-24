# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Research, finite RF transmission, and local group-control entry points."""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
from typing import Sequence

from .lan import DEFAULT_PORT, ProtocolError, SnapshotTimeout, query_inventory
from .rf import (
    ACTION_CODES,
    REMOTE_ADDRESS,
    REMOTE_CHANNELS,
    REMOTE_DATA_RATE,
    REMOTE_FREQUENCIES_HZ,
    build_esb_candidate_frame,
    build_remote_payload,
    decode_remote_payload,
)


def _finite_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("must be finite")
    return number


def _positive_float(value: str) -> float:
    number = _finite_float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _nonnegative_float(value: str) -> float:
    number = _finite_float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def _iq_sample_rate(value: str) -> int:
    try:
        rate = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer number of samples per second") from exc
    if rate < 8_000_000 or rate > 256_000_000 or rate % 8_000_000:
        raise argparse.ArgumentTypeError("must be an integer multiple of 8000000 within 8..256 MS/s")
    return rate


def _iq_channels(value: str) -> tuple[int, ...]:
    try:
        channels = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be comma-separated integer frequencies in Hz") from exc
    if any(channel <= 0 for channel in channels) or len(set(channels)) != len(channels):
        raise argparse.ArgumentTypeError("channel frequencies must be positive and distinct")
    return channels


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hd-platinum",
        description="LAN research, RF tools, and local group/position control for Platinum shades",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    firmware = subparsers.add_parser(
        "firmware-inspect", help="inspect or extract user-supplied firmware offline; no device access")
    firmware_source = firmware.add_mutually_exclusive_group(required=True)
    firmware_source.add_argument("--apk", help="local Platinum APK containing firmware assets")
    firmware_source.add_argument("--hex", help="local Intel HEX firmware image")
    firmware.add_argument("--image", choices=("gateway", "bridge"), default="gateway",
                          help="APK firmware asset to inspect (default: gateway)")
    firmware.add_argument("--output-dir", help="extract into a new private directory; omit for inspection only")

    probe = subparsers.add_parser(
        "firmware-probe", help="run the original firmware keepalive handler in an offline simulator")
    probe_source = probe.add_mutually_exclusive_group(required=True)
    probe_source.add_argument("--apk", help="local Platinum APK containing the gateway image")
    probe_source.add_argument("--hex", help="local gateway Intel HEX image")
    probe.add_argument("--simulator", required=True, help="path to a separately built uCsim 8051 executable")
    probe.add_argument("--output-dir", required=True, help="new private directory for execution reports")
    probe.add_argument("--instruction-limit", type=int, default=100_000)
    probe.add_argument("--timeout", type=_positive_float, default=30.0)

    inventory = subparsers.add_parser(
        "inventory",
        help="send the read-only $dat query and print a redacted inventory",
    )
    inventory.add_argument("host")
    inventory.add_argument("--port", type=int, default=DEFAULT_PORT)
    inventory.add_argument("--timeout", type=float, default=10.0)
    inventory.add_argument(
        "--include-names",
        action="store_true",
        help="include private room/shade names and room RF identifiers",
    )
    inventory.add_argument(
        "--include-mac",
        action="store_true",
        help="include the bridge MAC address",
    )

    rf = subparsers.add_parser("rf-payload", help="build an offline five-byte remote payload")
    rf.add_argument("--remote-id", required=True, help="two-byte ID, for example 03c1")
    rf.add_argument("--groups", required=True, help="1..4, comma list, explicit 0xNN mask, or all")
    rf.add_argument("--action", required=True, choices=tuple(ACTION_CODES))
    rf.add_argument(
        "--candidate-frame",
        action="store_true",
        help="also print a parameterized ESB frame hypothesis (not a transmit waveform)",
    )
    rf.add_argument("--pid", type=int, default=0, choices=range(4))
    rf.add_argument(
        "--pcf-length",
        type=lambda value: int(value, 0),
        help="override unresolved static-payload PCF length bits",
    )

    decode = subparsers.add_parser("rf-decode", help="decode an offline five-byte payload")
    decode.add_argument("payload", help="ten hexadecimal digits")

    iq = subparsers.add_parser(
        "rf-iq-decode",
        help="decode saved SC16Q11 IQ and print redacted CRC-valid frame results",
    )
    iq.add_argument("path", help="little-endian signed 16-bit interleaved I,Q recording")
    iq.add_argument(
        "--sample-rate", type=_iq_sample_rate, required=True, metavar="SAMPLES_PER_SECOND",
        help="recorded sample rate in samples/s; an integer multiple of 8000000, at most 256000000",
    )
    iq.add_argument(
        "--center", type=_positive_float, required=True, metavar="HZ",
        help="recorded center frequency in Hz",
    )
    iq.add_argument(
        "--channels", type=_iq_channels, default=REMOTE_FREQUENCIES_HZ, metavar="HZ,HZ,...",
        help="comma-separated channel frequencies in Hz (default: 2433000000,2452000000,2471000000)",
    )
    iq.add_argument(
        "--start", type=_nonnegative_float, default=0.0, metavar="SECONDS",
        help="start decoding at this file offset in seconds (default: 0)",
    )
    iq.add_argument(
        "--duration", type=_positive_float, metavar="SECONDS",
        help="decode this many seconds (default: through the end of the file)",
    )
    iq.add_argument(
        "--include-private", action="store_true",
        help="include installation identity, complete payloads, and identity-derived CRCs",
    )

    waveform = subparsers.add_parser("rf-waveform", help="generate a finite offline SC16Q11 command")
    waveform.add_argument("path")
    waveform.add_argument("--remote-id", required=True)
    waveform.add_argument("--groups", required=True)
    waveform.add_argument("--action", choices=("up", "down"), required=True)
    waveform.add_argument("--sample-rate", type=int, default=48_000_000)
    waveform.add_argument("--center", type=int, default=2_452_000_000)
    waveform.add_argument("--channels", type=_iq_channels, default=REMOTE_FREQUENCIES_HZ)
    waveform.add_argument("--action-repetitions", type=int, default=500)
    waveform.add_argument("--release-repetitions", type=int, default=500)
    waveform.add_argument("--overwrite", action="store_true")

    position_waveform = subparsers.add_parser("rf-position-waveform", help="generate an offline candidate shade-position waveform")
    position_waveform.add_argument("path")
    position_waveform.add_argument("--room-rf-id", required=True, help="two-byte room RF identity, e.g. aabb")
    position_waveform.add_argument("--shade-mask", type=lambda value: int(value, 0), required=True, help="one-hot byte, e.g. 0x04")
    position_waveform.add_argument("--position", type=int, required=True, help="native primary position 0..255")
    position_waveform.add_argument("--sample-rate", type=int, default=48_000_000)
    position_waveform.add_argument("--center", type=int, default=2_452_000_000)
    position_waveform.add_argument("--channels", type=_iq_channels, default=REMOTE_FREQUENCIES_HZ)
    position_waveform.add_argument("--command-repetitions", type=int, default=2100)
    position_waveform.add_argument("--followup-repetitions", type=int, default=425)
    position_waveform.add_argument("--overwrite", action="store_true")

    def radio_options(command):
        command.add_argument("--sample-rate", type=int, default=48_000_000)
        command.add_argument("--center", type=int, default=2_452_000_000)
        command.add_argument("--bandwidth", type=int, default=46_000_000)
        command.add_argument("--device", help="libbladeRF device selector (optional)")
        command.add_argument("--fpga", help="compatible FPGA image to load temporarily if needed")

    transmit = subparsers.add_parser("rf-transmit", help="transmit a finite SC16Q11 file on TX1 (maximum two seconds)")
    transmit.add_argument("path")
    radio_options(transmit)
    transmit.add_argument("--gain", type=int, default=0, help="TX system gain in dB (default: 0)")

    capture = subparsers.add_parser("rf-capture", help="record RX1 with timestamps and discontinuity reporting")
    capture.add_argument("path")
    radio_options(capture)
    capture.add_argument("--gain", type=int, default=15)
    capture.add_argument("--duration", type=_positive_float, required=True)

    loopback = subparsers.add_parser("rf-loopback", help="finite TX1/RX1 test; requires connected 40 dB pads and DC block")
    loopback.add_argument("tx_path")
    loopback.add_argument("rx_path")
    radio_options(loopback)
    loopback.set_defaults(sample_rate=8_000_000, bandwidth=6_000_000)
    loopback.add_argument("--gain", type=int, default=0, help="TX gain")
    loopback.add_argument("--rx-gain", type=int, default=50)
    loopback.add_argument("--rx-sample-rate", type=int)
    loopback.add_argument("--rx-center", type=int)
    loopback.add_argument("--rx-bandwidth", type=int)
    loopback.add_argument("--duration", type=_positive_float, default=1.0)

    serve = subparsers.add_parser("bridge-serve", help="serve the local group and shade-position dashboard and JSON API")
    serve.add_argument("--config", required=True, help="private RF identities, groups, optional shade mappings, and API token JSON")
    serve.add_argument("--backend", choices=("dry-run", "bladerf"), default="dry-run")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8077)
    serve.add_argument("--allowed-host", action="append", help="accepted Host header; required for wildcard bind")
    serve.add_argument("--cache-dir", default="tmp/bridge-waveforms")
    serve.add_argument("--tx-gain", type=int, default=35)
    serve.add_argument("--device")
    serve.add_argument("--fpga")

    emulate = subparsers.add_parser("bridge-emulate", help="serve original Platinum TCP protocol and shared HTTP controls")
    emulate.add_argument("--config", required=True, help="private shade mappings with explicit position/Sync/Jog permissions and HTTP API token")
    emulate.add_argument("--inventory", required=True, help="saved original bridge inventory, preserving raw records")
    emulate.add_argument("--backend", choices=("dry-run", "bladerf-bridge"), default="dry-run")
    emulate.add_argument("--state-dir", default="tmp/bridge-emulator")
    emulate.add_argument("--initial-sequence", type=int, help="next 16-bit RF sequence, required only for a new live state store")
    emulate.add_argument("--host", default="127.0.0.1")
    emulate.add_argument("--port", type=int, default=522)
    emulate.add_argument("--allowed-client", action="append", help="trusted IPv4/IPv6 client CIDR; required for LAN binding")
    emulate.add_argument("--http-host", default="127.0.0.1")
    emulate.add_argument("--http-port", type=int, default=8077)
    emulate.add_argument("--allowed-host", action="append", help="HTTP Host header allowlist for wildcard HTTP binding")
    emulate.add_argument("--tx-gain", type=int, default=50)
    emulate.add_argument("--rx-gain", type=int, default=40)
    emulate.add_argument("--sync-rf-profile", choices=("narrow", "wide"), default="narrow",
                         help="Sync recording profile: wide records 2440 and covered native channels at 32 MS/s; position and Jog controls stay narrow")
    emulate.add_argument("--device")
    emulate.add_argument("--fpga")
    emulate.add_argument("--discovery", action="store_true", help="also answer Platinum NetBIOS discovery on UDP 137")
    emulate.add_argument("--advertise-host", help="this emulator's LAN IPv4 address for discovery")
    emulate.add_argument("--discovery-host", default="0.0.0.0")
    emulate.add_argument("--discovery-port", type=int, default=137)
    emulate.add_argument("--discovery-reuse-port", action="store_true", help="request OS UDP port sharing; successful discovery still needs validation")
    emulate.add_argument("--protocol-log", help="optional bounded private TCP wire journal for client compatibility work")
    return parser


def _run_inventory(args: argparse.Namespace) -> int:
    result = query_inventory(args.host, port=args.port, timeout=args.timeout)
    print(
        json.dumps(
            result.public_summary(
                include_names=args.include_names,
                include_mac=args.include_mac,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_rf_payload(args: argparse.Namespace) -> int:
    payload = build_remote_payload(args.remote_id, args.groups, args.action)
    output: dict[str, object] = {
        "payload": decode_remote_payload(payload).as_dict(),
        "radio_profile": {
            "channels": list(REMOTE_CHANNELS),
            "frequencies_mhz": [2400 + channel for channel in REMOTE_CHANNELS],
            "data_rate_bps": REMOTE_DATA_RATE,
            "address_hex": REMOTE_ADDRESS.hex(),
            "status": "community-derived; verify against a capture from your remote",
        },
    }
    if args.candidate_frame:
        frame = build_esb_candidate_frame(
            payload,
            pid=args.pid,
            pcf_payload_length=args.pcf_length,
        )
        output["candidate_frame"] = {
            "bit_length": frame.bit_length,
            "packed_hex_with_zero_tail_padding": frame.packed.hex(),
            "crc_hex": f"{frame.crc:04x}",
            "pid": frame.pid,
            "no_ack": frame.no_ack,
            "pcf_payload_length": frame.pcf_payload_length,
            "duration_us": frame.duration_seconds * 1_000_000,
            "warning": "97-bit comparison hypothesis; initial local IQ supports an 88-bit no-PCF frame",
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _run_rf_decode(args: argparse.Namespace) -> int:
    print(json.dumps(decode_remote_payload(args.payload).as_dict(), indent=2, sort_keys=True))
    return 0


def _run_rf_iq_decode(args: argparse.Namespace) -> int:
    from .rf_iq import decode_iq_file, redact_result

    result = decode_iq_file(
        args.path,
        sample_rate_hz=args.sample_rate,
        center_hz=args.center,
        channels_hz=args.channels,
        start_seconds=args.start,
        duration_seconds=args.duration,
    )
    if not args.include_private:
        result = redact_result(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _run_rf_waveform(args: argparse.Namespace) -> int:
    from .rf_waveform import WaveformConfig, build_command_plan, write_waveform
    config = WaveformConfig(sample_rate_hz=args.sample_rate, center_hz=args.center, channels_hz=args.channels)
    plan = build_command_plan(args.remote_id, args.groups, args.action, config=config,
                              action_repetitions=args.action_repetitions,
                              release_repetitions=args.release_repetitions)
    result = write_waveform(args.path, plan, overwrite=args.overwrite)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _run_radio(args: argparse.Namespace) -> int:
    from .bladerf import BladeRF, RadioConfig, RX1, TX1, conducted_test
    config = RadioConfig(args.sample_rate, args.center, args.bandwidth, args.gain)
    if args.command == "rf-loopback":
        rx_config = RadioConfig(args.rx_sample_rate or args.sample_rate, args.rx_center or args.center,
                                args.rx_bandwidth or args.bandwidth, args.rx_gain)
        result = conducted_test(args.tx_path, args.rx_path, tx_config=config, rx_config=rx_config,
                                device=args.device, fpga=args.fpga, duration_seconds=args.duration)
    else:
        with BladeRF(device=args.device, fpga=args.fpga) as radio:
            if args.command == "rf-transmit":
                radio.configure(TX1, config)
                result = radio.transmit(args.path)
            else:
                radio.configure(RX1, config)
                result = radio.receive(args.path, duration_seconds=args.duration)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _run_position_waveform(args: argparse.Namespace) -> int:
    from .rf import parse_remote_id
    from .rf_positions import build_position_plan, write_position_waveform
    from .rf_waveform import WaveformConfig
    config = WaveformConfig(sample_rate_hz=args.sample_rate, center_hz=args.center,
        channels_hz=args.channels, slot_us=234, deviation_hz=320_000)
    plan = build_position_plan(parse_remote_id(args.room_rf_id), args.shade_mask, args.position,
        config=config, command_repetitions=args.command_repetitions,
        followup_repetitions=args.followup_repetitions)
    print(json.dumps(write_position_waveform(args.path, plan, overwrite=args.overwrite), indent=2, sort_keys=True))
    return 0


def _run_bridge(args: argparse.Namespace) -> int:
    from .bridge import BridgeService, DryRunBackend, load_config, make_server
    config = load_config(args.config)
    if args.backend == "bladerf":
        from .bladerf import BladeRFBackend, BladeRFPositionBackend
        backend = BladeRFBackend(args.cache_dir, gain_db=args.tx_gain, device=args.device, fpga=args.fpga)
        position_backend = BladeRFPositionBackend(args.cache_dir, gain_db=args.tx_gain, device=args.device, fpga=args.fpga)
    else:
        backend = DryRunBackend()
        position_backend = DryRunBackend()
    service = BridgeService(config, backend, backend_name=args.backend, position_backend=position_backend)
    server = make_server(service, host=args.host, port=args.port, allowed_hosts=args.allowed_host)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        print(json.dumps({"url": f"http://{args.host}:{server.server_address[1]}",
                          "backend": args.backend, "groups": sorted(config.groups),
                          "shades": sorted(config.shades)}, sort_keys=True), flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, previous)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "firmware-inspect":
            from .firmware import inspect_firmware
            return inspect_firmware(args)
        if args.command == "firmware-probe":
            from .firmware import FirmwareImage
            from .firmware_runtime import run_keepalive_probe
            image = (FirmwareImage.from_apk(args.apk) if args.apk
                     else FirmwareImage.from_hex(args.hex))
            report = run_keepalive_probe(
                image, simulator=args.simulator, output_dir=args.output_dir,
                instruction_limit=args.instruction_limit, timeout_seconds=args.timeout)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "rf-payload":
            return _run_rf_payload(args)
        if args.command == "rf-decode":
            return _run_rf_decode(args)
        if args.command == "rf-iq-decode":
            return _run_rf_iq_decode(args)
        if args.command == "rf-waveform":
            return _run_rf_waveform(args)
        if args.command == "rf-position-waveform":
            return _run_position_waveform(args)
        if args.command in ("rf-transmit", "rf-capture", "rf-loopback"):
            return _run_radio(args)
        if args.command == "bridge-serve":
            return _run_bridge(args)
        if args.command == "bridge-emulate":
            from .emulator import run_emulator
            return run_emulator(args)
    except (ValueError, OSError, RuntimeError, ProtocolError, SnapshotTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
