# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Research helpers for the Hunter Douglas Platinum bridge."""

from .lan import BridgeInventory, BridgeRecord, query_inventory
from .rf import RemoteCommand, build_remote_payload, decode_remote_payload

__all__ = [
    "BridgeInventory",
    "BridgeRecord",
    "RemoteCommand",
    "build_remote_payload",
    "decode_remote_payload",
    "query_inventory",
]

__version__ = "0.1.0"
