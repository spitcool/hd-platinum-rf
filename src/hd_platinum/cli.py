# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command-line entry points for the read-only and offline research tools."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .lan import DEFAULT_PORT, ProtocolError, SnapshotTimeout, query_inventory
from .rf import (
    ACTION_CODES,
    REMOTE_ADDRESS,
    REMOTE_CHANNELS,
    REMOTE_DATA_RATE,
    build_esb_candidate_frame,
    build_remote_payload,
    decode_remote_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hd-platinum",
        description="Read-only LAN and offline RF research tools for Platinum shades",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
            "warning": "analysis hypothesis only; PCF bits and waveform need IQ validation",
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _run_rf_decode(args: argparse.Namespace) -> int:
    print(json.dumps(decode_remote_payload(args.payload).as_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "rf-payload":
            return _run_rf_payload(args)
        if args.command == "rf-decode":
            return _run_rf_decode(args)
    except (ValueError, OSError, ProtocolError, SnapshotTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
