#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the portable gateway and touchscreen on localhost with sample shades."""

from __future__ import annotations

import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import threading
from urllib.parse import urlsplit

from test_native import ROOT, choose_sdk


def build(directory: Path) -> Path:
    compiler, cmake = shutil.which("c++"), shutil.which("cmake")
    if not compiler or not cmake:
        raise RuntimeError("Install a C++17 compiler and CMake first")
    sdk = choose_sdk(compiler, None)
    command = [cmake, "-S", str(ROOT), "-B", str(directory),
               f"-DCMAKE_CXX_COMPILER={compiler}", "-DCMAKE_BUILD_TYPE=Debug",
               "-DGATEWAY_SANITIZERS=OFF"]
    if platform.system() == "Darwin":
        command.append(f"-DCMAKE_OSX_SYSROOT={sdk or ''}")
    subprocess.run(command, check=True)
    subprocess.run([cmake, "--build", str(directory), "--target", "gateway_simulator", "--parallel"], check=True)
    return directory / "gateway_simulator"


class Gateway:
    def __init__(self, executable: Path):
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(24)
        self.services = {"tcp522": True, "http": True, "web": True}
        self.operation = {"id": "", "status": "idle"}
        self.receipts = OrderedDict()

    def request(self, line="state"):
        with self.lock:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
            response = self.process.stdout.readline()
            if not response:
                raise RuntimeError("The native gateway process stopped")
            state = json.loads(response)
            # The core can finish a job and start the next in a single request.
            # Explicit completion flags keep the previous receipt accurate.
            if self.operation["status"] == "submitted" and state["finished"]:
                self.operation["status"] = "completed" if state["finished_ok"] else "failed"
                receipt = self.receipts.get(self.operation["id"])
                if receipt:
                    receipt[1]["operation"] = dict(self.operation)
                    receipt[1]["status"] = self.operation["status"]
            return state

    def status(self, state):
        return {"storage_ok": True, "busy": state["busy"], "backend": "simulated",
                "services": dict(self.services), "operation": dict(self.operation)}

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=2)
        self.process.stdout.close()


def handler(gateway, port):
    page = Path(__file__).with_name("simulator.html").read_bytes()
    web_page = (ROOT / "include/web_ui.h").read_text().split('R"PLATINUM_HTML(', 1)[1].split(')PLATINUM_HTML"', 1)[0].encode()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, value, content_type="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            expected = "Bearer " + gateway.token
            if not secrets.compare_digest(self.headers.get("Authorization", ""), expected):
                self.reply(401, {"error": "unauthorized"})
                return False
            return True

        def body(self):
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ValueError("application/json required")
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 4096:
                raise ValueError("invalid body size")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value

        def dispatch(self):
            host, origin = self.headers.get("Host"), self.headers.get("Origin")
            if host not in hosts or (origin and origin != "http://" + host):
                return self.reply(403, {"error": "host or origin rejected"})
            path = urlsplit(self.path).path
            with gateway.lock:
                if self.command == "GET":
                    if path == "/":
                        return self.reply(200, page, "text/html; charset=utf-8")
                    if path == "/sim/info":
                        return self.reply(200, {"token": gateway.token})
                    if path == "/sim/state":
                        return self.reply(200, gateway.request())
                    if path == "/web":
                        if not gateway.services["http"] or not gateway.services["web"]:
                            return self.reply(503, {"error": "Web interface disabled. Use Reset on the local screen preview to restore it."})
                        return self.reply(200, web_page, "text/html; charset=utf-8")
                if self.command == "POST" and path.startswith("/sim/"):
                    value = self.body()
                    if path == "/sim/reset":
                        gateway.services = {"tcp522": True, "http": True, "web": True}
                        gateway.operation = {"id": "", "status": "idle"}
                        gateway.receipts.clear()
                        return self.reply(200, gateway.request("reset"))
                    if path == "/sim/cancel":
                        return self.reply(200, gateway.request("cancel"))
                    if path == "/sim/touch":
                        down, x, y = value.get("down"), value.get("x"), value.get("y")
                        if type(down) is not bool or type(x) is not int or type(y) is not int or not (-10000 <= x <= 10000 and -10000 <= y <= 10000):
                            raise ValueError("invalid touch sample")
                        state = gateway.request(f"touch\t{int(down)}\t{x}\t{y}")
                        if state.get("accepted") and state["started"]:
                            gateway.operation = {"id": "screen-" + secrets.token_hex(6), "status": "submitted"}
                        return self.reply(200, state)
                    return self.reply(404, {"error": "not found"})
                if not path.startswith("/api/"):
                    return self.reply(404, {"error": "not found"})
                if not gateway.services["http"]:
                    return self.reply(503, {"error": "HTTP disabled"})
                if not self.authorized():
                    return
                state = gateway.request()
                if self.command == "GET":
                    if path == "/api/settings":
                        return self.reply(200, gateway.services)
                    status = gateway.status(state)
                    if path == "/api/status":
                        return self.reply(200, status)
                    if path == "/api/shades":
                        return self.reply(200, {**status, "shades": state["shades"]})
                    if path == "/api/rooms":
                        return self.reply(200, {"rooms": state["rooms"]})
                    return self.reply(404, {"error": "not found"})
                value = self.body()
                if self.command == "PATCH" and path == "/api/settings":
                    if not value or any(key not in gateway.services or type(item) is not bool for key, item in value.items()):
                        raise ValueError("expected boolean tcp522, http or web settings")
                    gateway.services.update(value)
                    return self.reply(200, gateway.services)
                if self.command != "POST":
                    return self.reply(405, {"error": "method not allowed"})
                if path == "/api/command":
                    command = value.get("command")
                elif path in ("/api/positions", "/api/sync", "/api/jog"):
                    shade = value.get("shade")
                    if type(shade) is not int or not 0 <= shade < 100:
                        raise ValueError("invalid shade")
                    if path == "/api/positions":
                        position = value.get("position")
                        if type(position) is not int or not 0 <= position <= 255:
                            raise ValueError("invalid position")
                        command = f"$pss{shade:02}-04-{position:03}-$rls"
                    elif path == "/api/sync":
                        command = f"$rsc{shade:02}-"
                    else:
                        command = f"$pss{shade:02}-12-000-$rls"
                else:
                    return self.reply(404, {"error": "not found"})
                if not isinstance(command, str) or not 1 <= len(command) <= 1024 or any(ord(c) < 32 for c in command):
                    raise ValueError("invalid command")
                request_id = value.get("request_id")
                if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", request_id):
                    raise ValueError("invalid request_id")
                if request_id in gateway.receipts:
                    previous, response = gateway.receipts[request_id]
                    if command != previous:
                        return self.reply(409, {"error": "request_id already used"})
                    return self.reply(200, response)
                state = gateway.request("command\t" + command)
                if not state.get("accepted"):
                    return self.reply(409, {"error": state.get("error") or "command rejected"})
                if state["started"]:
                    gateway.operation = {"id": request_id, "status": "submitted"}
                response = {"request_id": request_id, "status": "submitted" if state["started"] else "processed",
                            "operation": dict(gateway.operation), "backend": "simulated"}
                gateway.receipts[request_id] = (command, response)
                while len(gateway.receipts) > 16:
                    gateway.receipts.popitem(last=False)
                self.reply(200, response)

        def handle_request(self):
            self.connection.settimeout(5)
            try:
                self.dispatch()
            except (ValueError, KeyError) as error:
                self.reply(400, {"error": str(error)})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except (RuntimeError, OSError) as error:
                self.reply(503, {"error": str(error)})

        do_GET = do_POST = do_PATCH = handle_request

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18077)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/simulator")
    parser.add_argument("--no-build", action="store_true", help="Use a previously built gateway_simulator")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    directory = args.build_dir.resolve()
    gateway = None
    try:
        executable = directory / "gateway_simulator" if args.no_build else build(directory)
        gateway = Gateway(executable)
        gateway.request()
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler(gateway, args.port)) as server:
            print(f"Gateway running at http://127.0.0.1:{args.port}/ — Ctrl-C to stop", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    finally:
        if gateway:
            gateway.close()


if __name__ == "__main__":
    main()
