# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Optional, local-only NetBIOS discovery for a Platinum bridge emulator.

Community Platinum clients query UDP 137 for PLATLINK-PDBU (some comments
spell it PLATLINK-FDBU). The original mobile app has not yet been validated.
Packet formats follow RFC 1002 sections 4.2.12-13 and 4.2.17-18. This is a
narrow name responder, not a NetBIOS registrar or an OS network configurator.
"""

from __future__ import annotations

from collections import deque
import ipaddress
import socket
import socketserver
import struct
import time


PLATINUM_NAMES = ("PLATLINK-PDBU", "PLATLINK-FDBU")
MAX_DATAGRAM = 576
_LOCAL_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8",
))
_HEADER = struct.Struct("!6H")


def _local_ipv4(value: str, label: str, *, wildcard: bool = False):
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, TypeError) as exc:
        raise ValueError(f"{label} must be a literal IPv4 address") from exc
    if wildcard and address.is_unspecified:
        return address
    if not any(address in network for network in _LOCAL_NETWORKS):
        raise ValueError(f"{label} must be an explicit private or local IPv4 address")
    return address


def _encoded_name(raw: bytes) -> bytes:
    return b"\x20" + bytes(part for value in raw for part in (65 + (value >> 4), 65 + (value & 15))) + b"\x00"


def _question(packet: bytes):
    # A single uncompressed, unscoped 16-byte NetBIOS name is sufficient for
    # Platinum discovery. Reject pointers, trailing records, and truncation.
    if len(packet) != 50:
        return None
    transaction, flags, questions, answers, authority, additional = _HEADER.unpack_from(packet)
    if flags & 0xF800 or (questions, answers, authority, additional) != (1, 0, 0, 0):
        return None
    if packet[12] != 32 or packet[45] != 0:
        return None
    label = packet[13:45]
    if any(not 65 <= value <= 80 for value in label):
        return None
    raw = bytes((label[i] - 65) * 16 + label[i + 1] - 65 for i in range(0, 32, 2))
    kind, klass = struct.unpack_from("!HH", packet, 46)
    if klass != 1 or kind not in (0x20, 0x21):
        return None
    base = raw[:15].rstrip(b" ").upper()
    known = raw[15] in (0, 0x20) and base in tuple(name.encode("ascii") for name in PLATINUM_NAMES)
    wildcard = raw == b"*" + b"\x00" * 15
    if not known and not (kind == 0x21 and wildcard):
        return None
    return transaction, flags, raw, kind


def discovery_response(packet: bytes, advertise_host: str) -> bytes | None:
    """Build one unicast reply, or return None for an unrelated/bad request.

    No I/O occurs. Only the two documented name variants and wildcard node
    status are answered. Reserved query flag bits are ignored, as some old
    community clients set them. Responses and registration requests are not.
    """
    address = _local_ipv4(advertise_host, "advertise_host")
    question = _question(packet)
    if question is None:
        return None
    transaction, flags, raw, kind = question
    if kind == 0x20:
        response_flags = 0x8480 | (flags & 0x0100)  # response, AA, RA, copied RD
        ttl = 30
        data = b"\x00\x00" + address.packed  # unique B-node address
    else:
        response_flags, ttl = 0x8400, 0
        names = b"".join(name.encode("ascii").ljust(15, b" ") + b"\x00\x04\x00"
                         for name in PLATINUM_NAMES)
        # RFC node statistics are 46 bytes, beginning with a 6-byte unit ID.
        # Zero means unspecified: do not reuse the original bridge's MAC.
        data = bytes((len(PLATINUM_NAMES),)) + names + bytes(46)
    return (_HEADER.pack(transaction, response_flags, 0, 1, 0, 0)
            + _encoded_name(raw) + struct.pack("!HHIH", kind, 1, ttl, len(data)) + data)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, sock = self.request
        response = discovery_response(packet, str(self.server.advertise_address))
        if response is not None:
            try:
                sock.sendto(response, self.client_address)
            except OSError:
                # A disappearing UDP peer must not stop the discovery loop.
                pass


class PlatinumDiscoveryServer(socketserver.UDPServer):
    """Bounded synchronous UDP server with an explicit local client allowlist.

    Construction binds the socket; serve_forever must be started explicitly.
    SO_REUSEPORT is opt-in and its delivery semantics depend on the OS. A
    successful shared bind is not evidence that the mobile app can discover us.
    """

    allow_reuse_address = True
    max_packet_size = MAX_DATAGRAM + 1

    def __init__(self, advertise_host, host="0.0.0.0", port=137, *, allowed_clients=None,
                 reuse_port=False):
        self.advertise_address = _local_ipv4(advertise_host, "advertise_host")
        bind_address = _local_ipv4(host, "host", wildcard=True)
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer within 0..65535")
        if not isinstance(reuse_port, bool):
            raise ValueError("reuse_port must be boolean")
        if allowed_clients is None:
            if not bind_address.is_loopback:
                raise ValueError("non-loopback binding requires explicit allowed_clients")
            allowed_clients = ("127.0.0.0/8",)
        if isinstance(allowed_clients, (str, bytes)):
            raise ValueError("allowed_clients must be a sequence of local IPv4 CIDRs")
        try:
            self.allowed_clients = tuple(ipaddress.IPv4Network(value, strict=False) for value in allowed_clients)
        except (ValueError, TypeError) as exc:
            raise ValueError("allowed_clients must contain local IPv4 CIDRs") from exc
        if not self.allowed_clients or any(not any(network.subnet_of(local) for local in _LOCAL_NETWORKS)
                                           for network in self.allowed_clients):
            raise ValueError("allowed_clients must contain explicit private or local IPv4 CIDRs")
        self.reuse_port = reuse_port
        self._recent = deque()
        super().__init__((str(bind_address), port), _Handler)

    def server_bind(self):
        if self.reuse_port:
            if not hasattr(socket, "SO_REUSEPORT"):
                raise ValueError("SO_REUSEPORT is not available on this platform")
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        super().server_bind()

    def verify_request(self, request, client_address):
        packet, _ = request
        try:
            address = ipaddress.IPv4Address(client_address[0])
        except ipaddress.AddressValueError:
            return False
        if len(packet) > MAX_DATAGRAM or not any(address in network for network in self.allowed_clients):
            return False
        # Fixed-size rate history: at most 20 responses/sec total and 5/client.
        # Malformed/unsupported packets do not consume a response allocation.
        if _question(packet) is None:
            return False
        now = time.monotonic()
        while self._recent and now - self._recent[0][0] >= 1:
            self._recent.popleft()
        if len(self._recent) >= 20 or sum(peer == address for _, peer in self._recent) >= 5:
            return False
        self._recent.append((now, address))
        return True


def make_discovery_server(advertise_host, host="0.0.0.0", port=137, *,
                          allowed_clients=None, reuse_port=False):
    """Create a UDP 137 responder; callers own startup and socket cleanup."""
    return PlatinumDiscoveryServer(advertise_host, host, port,
                                   allowed_clients=allowed_clients, reuse_port=reuse_port)
