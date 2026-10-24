# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared lifecycle for the Platinum LAN interface, HTTP controls and discovery."""

from __future__ import annotations

import json
import signal
import threading
from pathlib import Path

from .bridge import BridgeService, DryRunBackend, load_config, make_server
from .lan_server import make_lan_server


class EmulatorServer:
    """Bind every requested endpoint before accepting any command.

    Closing first stops acceptance, then waits for the finite handlers and RF
    operation to finish. Both control transports use the same dispatcher.
    """

    def __init__(self, service, inventory_source, *, host="127.0.0.1", port=522,
                 http_host="127.0.0.1", http_port=8077, allowed_clients=None,
                 allowed_hosts=None, state_path=None, discovery=False,
                 advertise_host=None, discovery_host="0.0.0.0", discovery_port=137,
                 discovery_reuse_port=False, protocol_log=None):
        self.service = service
        self.servers = []
        self.threads = []
        self.stop_event = threading.Event()
        self.closed = False
        try:
            journal = None
            if protocol_log is not None:
                from .lan_trace import WireJournal
                journal = WireJournal(protocol_log)
            self.lan = make_lan_server(service, inventory_source, host=host, port=port,
                                      allowed_clients=allowed_clients, state_path=state_path,
                                      wire_journal=journal)
            self.servers.append(self.lan)
            self.http = make_server(service, host=http_host, port=http_port,
                                    allowed_hosts=allowed_hosts)
            self.servers.append(self.http)
            self.discovery = None
            if discovery:
                if not advertise_host:
                    raise ValueError("discovery requires --advertise-host with this machine's LAN IPv4 address")
                from .lan_discovery import make_discovery_server
                self.discovery = make_discovery_server(
                    advertise_host, host=discovery_host, port=discovery_port,
                    allowed_clients=allowed_clients, reuse_port=discovery_reuse_port)
                self.servers.append(self.discovery)
        except BaseException:
            self.close()
            raise

    def start(self):
        if self.closed or self.threads:
            raise RuntimeError("emulator cannot be started twice")
        try:
            for index, server in enumerate(self.servers):
                thread = threading.Thread(target=server.serve_forever,
                                          kwargs={"poll_interval": .1},
                                          name=f"platinum-server-{index}", daemon=False)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            # Never retain/join a thread whose start failed. Close all bound
            # endpoints and stop any earlier listener before propagating failure.
            self.close()
            raise
        return self

    def status(self):
        return {"backend": self.service.backend_name,
                "lan": {"host": self.lan.server_address[0], "port": self.lan.server_address[1]},
                "http": {"host": self.http.server_address[0], "port": self.http.server_address[1]},
                "discovery": (None if self.discovery is None else
                              {"host": self.discovery.server_address[0],
                               "port": self.discovery.server_address[1]}),
                "configured_shades": sorted(self.service.config.shades),
                "position_confirmation_available": False}

    def wait(self):
        while not self.stop_event.wait(.25):
            if not all(thread.is_alive() for thread in self.threads):
                raise RuntimeError("an emulator listener stopped unexpectedly")

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        for server, thread in zip(self.servers, self.threads):
            if thread.is_alive():
                server.shutdown()
        for server in reversed(self.servers):
            server.server_close()
        for thread in self.threads:
            thread.join()


def run_emulator(args):
    config = load_config(args.config)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.backend == "bladerf-bridge":
        if config.groups:
            raise ValueError("the 2440 MHz bridge backend requires individual shade mappings; use an empty groups map")
        from .bladerf_bridge import BladeRFBridgeBackend
        position_backend = BladeRFBridgeBackend(
            state_dir / "rf", initial_sequence=args.initial_sequence,
            gain_db=args.tx_gain, rx_gain_db=args.rx_gain, device=args.device, fpga=args.fpga)
        sync_backend = position_backend
        if args.sync_rf_profile == "wide":
            sync_backend = BladeRFBridgeBackend(
                state_dir / "rf", initial_sequence=args.initial_sequence,
                gain_db=args.tx_gain, rx_gain_db=args.rx_gain,
                device=args.device, fpga=args.fpga, profile="wide")
    else:
        position_backend = DryRunBackend()
        sync_backend = position_backend
    service = BridgeService(config, DryRunBackend(), backend_name=args.backend,
                            position_backend=position_backend, sync_backend=sync_backend,
                            jog_backend=position_backend)
    emulator = EmulatorServer(
        service, args.inventory, host=args.host, port=args.port,
        http_host=args.http_host, http_port=args.http_port,
        allowed_clients=args.allowed_client, allowed_hosts=args.allowed_host,
        state_path=state_dir / "positions.json", discovery=args.discovery,
        advertise_host=args.advertise_host, discovery_host=args.discovery_host,
        discovery_port=args.discovery_port, discovery_reuse_port=args.discovery_reuse_port,
        protocol_log=args.protocol_log)
    previous = {}

    def stop(signum, frame):
        emulator.stop_event.set()

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, stop)
        emulator.start()
        print(json.dumps(emulator.status(), sort_keys=True), flush=True)
        emulator.wait()
    finally:
        try:
            emulator.close()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
    return 0
