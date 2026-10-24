# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Local HTTP control for configured Platinum groups and shade targets.

This is a new API, not an emulation of the original bridge's TCP protocol.
Backends receive validated commands one at a time. Successful idempotency keys
are retained only in memory, up to the configured cache size; restarting the
service or eviction ends that protection. One-way RF never confirms position.
Configuration files contain a private remote identity and bearer token.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
from pathlib import Path
import re
import secrets
import threading
from types import MappingProxyType
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from .rf import build_remote_payload, parse_remote_id


MAX_BODY_BYTES = 4096
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a duplicate key")
        result[key] = value
    return result


@dataclass(frozen=True)
class ShadeConfig:
    name: str
    room_id: int
    room_rf_id: bytes = field(repr=False)
    mask: int = field(repr=False)
    feature: int = 4
    position_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 128:
            raise ValueError("shade names must be nonempty strings of at most 128 characters")
        if type(self.room_id) is not int or not 0 <= self.room_id <= 99:
            raise ValueError("room_id must be an integer within 0..99")
        if not isinstance(self.room_rf_id, (bytes, bytearray)) or len(self.room_rf_id) != 2:
            raise ValueError("room_rf_id must contain exactly two bytes")
        if type(self.mask) is not int or not 1 <= self.mask <= 128 or self.mask & (self.mask-1):
            raise ValueError("shade mask must be a one-hot byte within 1..128")
        if type(self.feature) is not int or self.feature != 4:
            raise ValueError("only primary-position feature 4 is supported")
        if type(self.position_enabled) is not bool:
            raise ValueError("position_enabled must be a boolean")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "room_rf_id", bytes(self.room_rf_id))


@dataclass(frozen=True)
class BridgeConfig:
    remote_id: bytes = field(repr=False)
    groups: Mapping[int, str]
    api_token: str = field(repr=False)
    shades: Mapping[int, ShadeConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        identity = parse_remote_id(self.remote_id)
        if not isinstance(self.groups, Mapping):
            raise ValueError("groups must map group numbers to labels")
        groups = {}
        for group, label in self.groups.items():
            if type(group) is not int or not 1 <= group <= 4:
                raise ValueError("configured groups must be integer buttons 1 through 4")
            if not isinstance(label, str) or not label.strip() or len(label) > 128:
                raise ValueError("group labels must be nonempty strings of at most 128 characters")
            groups[group] = label.strip()
        token = self.api_token
        if (not isinstance(token, str) or not 16 <= len(token) <= 256
                or not token.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise ValueError("api_token must contain 16 to 256 visible ASCII characters without spaces")
        object.__setattr__(self, "remote_id", identity)
        object.__setattr__(self, "groups", MappingProxyType(groups))
        if not isinstance(self.shades, Mapping):
            raise ValueError("shades must map integer shade numbers to ShadeConfig entries")
        shades, targets = {}, set()
        for shade, target in self.shades.items():
            if type(shade) is not int or not 0 <= shade <= 99 or not isinstance(target, ShadeConfig):
                raise ValueError("shades require integer IDs within 0..99 and ShadeConfig entries")
            address = (target.room_rf_id, target.mask)
            if address in targets:
                raise ValueError("shade RF targets must be unique within each room identity")
            targets.add(address)
            shades[shade] = target
        if not groups and not shades:
            raise ValueError("configure at least one group or shade")
        object.__setattr__(self, "shades", MappingProxyType(shades))


def load_config(path: str | Path) -> BridgeConfig:
    """Read legacy group configuration plus an optional private shades map."""
    value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    required = {"remote_id", "groups", "api_token"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"shades"}:
        raise ValueError("configuration requires remote_id, groups, api_token, and optional shades")
    groups = value["groups"]
    if not isinstance(groups, dict) or any(key not in ("1", "2", "3", "4") for key in groups):
        raise ValueError("configuration group keys must be strings '1' through '4'")
    if not isinstance(value["remote_id"], str):
        raise ValueError("configuration remote_id must be a four-digit hexadecimal string")
    raw_shades = value.get("shades", {})
    if not isinstance(raw_shades, dict):
        raise ValueError("configuration shades must be an object")
    shades = {}
    shade_required = {"name", "room_id", "room_rf_id", "mask"}
    for key, target in raw_shades.items():
        if not isinstance(key, str) or not re.fullmatch(r"0|[1-9][0-9]?", key):
            raise ValueError("configuration shade keys must be decimal strings '0' through '99'")
        if (not isinstance(target, dict) or not shade_required <= set(target)
                or set(target) - shade_required - {"feature", "position_enabled"}):
            raise ValueError("shade entries require name, room_id, room_rf_id, mask, and optional feature/position_enabled")
        if not isinstance(target["room_rf_id"], str):
            raise ValueError("configuration room_rf_id must be a hexadecimal string")
        shades[int(key)] = ShadeConfig(target["name"], target["room_id"],
            parse_remote_id(target["room_rf_id"]), target["mask"],
            target.get("feature", 4), target.get("position_enabled", False))
    return BridgeConfig(parse_remote_id(value["remote_id"]),
                        {int(key): label for key, label in groups.items()}, value["api_token"], shades)


@dataclass(frozen=True)
class Command:
    group: int
    action: str
    remote_id: bytes = field(repr=False)
    request_id: str

    @property
    def payload(self) -> bytes:
        return build_remote_payload(self.remote_id, self.group, self.action)


@dataclass(frozen=True)
class PositionCommand:
    shade: int
    position: int
    target: ShadeConfig = field(repr=False)
    request_id: str


class BridgeError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class DryRunBackend:
    name = "dry-run"

    def __call__(self, command: Command | PositionCommand) -> Mapping[str, object]:
        return {"status": "simulated", "detail": "Dry run: no RF transmission", "frames_sent": 0}


class BridgeService:
    """Serialize backend calls; a sending backend must finish TX before returning.

    An asynchronous backend that returns ``submitted`` must own any later
    transmission serialization itself. The hardware backend should be finite
    and synchronous so service shutdown can wait for it to disable TX.
    """

    def __init__(self, config: BridgeConfig,
                 backend: Callable[[Command], Mapping[str, object]], *,
                 cache_size: int = 1024, backend_name: str | None = None,
                 position_backend: Callable[[PositionCommand], Mapping[str, object]] | None = None) -> None:
        if not isinstance(config, BridgeConfig) or not callable(backend):
            raise ValueError("a BridgeConfig and callable backend are required")
        if type(cache_size) is not int or not 1 <= cache_size <= 100_000:
            raise ValueError("cache_size must be between 1 and 100000")
        if position_backend is not None and not callable(position_backend):
            raise ValueError("position_backend must be callable when supplied")
        self.config = config
        self.backend = backend
        self.position_backend = position_backend
        self.backend_name = backend_name or getattr(backend, "name", type(backend).__name__)
        self.cache_size = cache_size
        self._send_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[tuple, dict]] = OrderedDict()

    def health(self) -> dict:
        return {"status": "ok", "service": "hd-platinum", "backend": self.backend_name,
                "transmit_status": "busy" if self._send_lock.locked() else "idle",
                "position_confirmation_available": False}

    def groups(self) -> dict:
        return {"groups": [{"group": group, "name": label}
                           for group, label in sorted(self.config.groups.items())],
                "position_confirmation_available": False}

    def shades(self) -> dict:
        return {"shades": [{"shade": shade, "name": target.name, "room_id": target.room_id,
                            "position_enabled": target.position_enabled}
                           for shade, target in sorted(self.config.shades.items())],
                "position_backend_available": self.position_backend is not None,
                "position_confirmation_available": False}

    def _cached(self, request_id: str, signature: tuple) -> dict | None:
        with self._cache_lock:
            item = self._cache.get(request_id)
            if item is None:
                return None
            if item[0] != signature:
                raise BridgeError(409, "idempotency_conflict", "request_id was already used for a different command")
            self._cache.move_to_end(request_id)
            return dict(deepcopy(item[1]), replayed=True)

    def dispatch(self, value: object) -> dict:
        if not isinstance(value, dict) or set(value) - {"group", "action", "request_id"}:
            raise BridgeError(400, "invalid_command", "expected group, action, and optional request_id")
        group, action = value.get("group"), value.get("action")
        if type(group) is not int or group not in self.config.groups:
            raise BridgeError(400, "invalid_group", "group must be one of the configured integer group numbers")
        if not isinstance(action, str) or action not in ("up", "down"):
            raise BridgeError(400, "invalid_action", "action must be 'up' or 'down'")
        request_id = self._request_id(value)
        command = Command(group, action, self.config.remote_id, request_id)
        return self._dispatch(command, ("group", group, action),
                              {"group": group, "action": action}, self.backend)

    @staticmethod
    def _request_id(value: dict) -> str:
        request_id = value.get("request_id", uuid4().hex)
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise BridgeError(400, "invalid_request_id", "request_id must contain 1 to 128 letters, digits, dots, colons, underscores, or hyphens")
        return request_id

    def dispatch_position(self, value: object) -> dict:
        if not isinstance(value, dict) or set(value) - {"shade", "position", "request_id"}:
            raise BridgeError(400, "invalid_command", "expected shade, position, and optional request_id")
        shade, position = value.get("shade"), value.get("position")
        if type(shade) is not int or shade not in self.config.shades:
            raise BridgeError(400, "invalid_shade", "shade must be one of the configured integer shade numbers")
        if type(position) is not int or not 0 <= position <= 255:
            raise BridgeError(400, "invalid_position", "position must be an integer within 0..255")
        request_id = self._request_id(value)
        signature = ("position", shade, position)
        cached = self._cached(request_id, signature)
        if cached is not None:
            return cached
        target = self.config.shades[shade]
        if not target.position_enabled:
            raise BridgeError(409, "validation_required", "position control is disabled until this shade's RF mapping is validated")
        if self.position_backend is None:
            raise BridgeError(503, "position_unavailable", "no position backend is configured")
        command = PositionCommand(shade, position, target, request_id)
        return self._dispatch(command, signature, {"shade": shade, "requested_position": position}, self.position_backend)

    def _dispatch(self, command, signature: tuple, public_fields: dict, backend) -> dict:
        request_id = command.request_id
        cached = self._cached(request_id, signature)
        if cached is not None:
            return cached
        if not self._send_lock.acquire(blocking=False):
            raise BridgeError(409, "busy", "another command is being sent; retry with the same request_id")
        try:
            cached = self._cached(request_id, signature)
            if cached is not None:
                return cached
            try:
                receipt = backend(command)
                if not isinstance(receipt, Mapping) or receipt.get("status") not in ("sent", "submitted", "simulated"):
                    raise ValueError("invalid backend receipt")
                details = {}
                if "detail" in receipt:
                    if not isinstance(receipt["detail"], str):
                        raise ValueError("invalid backend detail")
                    details["detail"] = receipt["detail"]
                if "frames_sent" in receipt:
                    count = receipt["frames_sent"]
                    if type(count) is not int or count < 0:
                        raise ValueError("invalid backend frame count")
                    details["frames_sent"] = count
                if "duration_seconds" in receipt:
                    duration = float(receipt["duration_seconds"])
                    if not math.isfinite(duration) or duration < 0:
                        raise ValueError("invalid backend duration")
                    details["duration_seconds"] = duration
                if "channels_hz" in receipt:
                    channels = tuple(receipt["channels_hz"])
                    if any(type(channel) is not int or channel <= 0 for channel in channels):
                        raise ValueError("invalid backend channels")
                    details["channels_hz"] = list(channels)
            except Exception as exc:
                raise BridgeError(502, "backend_error", "RF backend failed; delivery is unverified") from exc
            result = {"request_id": request_id, **public_fields,
                      "status": receipt["status"], "delivery": "unverified",
                      "position_confirmed": False, "backend": details, "replayed": False}
            with self._cache_lock:
                self._cache[request_id] = (signature, deepcopy(result))
                self._cache.move_to_end(request_id)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            return result
        finally:
            self._send_lock.release()


_DASHBOARD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Platinum shade control</title>
<style>body{font:17px system-ui;max-width:650px;margin:3rem auto;padding:0 1rem;color:#17202b}
label{display:block}input{width:100%;box-sizing:border-box;padding:.6rem;margin:.5rem 0 1.5rem}
.group{display:flex;align-items:center;gap:.7rem;padding:1rem 0;border-top:1px solid #ddd}
.group span{flex:1}.shade{padding:1rem 0;border-top:1px solid #ddd}.shade p{margin:.4rem 0}
button{font:inherit;padding:.5rem 1rem;cursor:pointer}button:disabled{cursor:default}#status{min-height:3rem}</style>
<h1>Platinum shade control</h1><p>Controls request movement. Actual shade position remains unverified.</p>
<label for="token">API token</label><input id="token" type="password" autocomplete="off" spellcheck="false">
<h2>Remote groups</h2><div id="groups"></div>
<h2>Individual shades</h2><div id="shades"></div><p id="status" role="status">Loading controls…</p>
<script>
const status=document.getElementById('status');
let busy=false;
function setBusy(value){busy=value;document.querySelectorAll('[data-command]').forEach(e=>e.disabled=busy||e.dataset.locked==='true');}
async function command(endpoint,value){
if(busy)return;
const token=document.getElementById('token').value;if(!token){status.textContent='Enter the API token first.';return;}
setBusy(true);status.textContent='Submitting command…';
try{const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
body:JSON.stringify({...value,request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('')})});const d=await r.json();
if(!r.ok)throw Error(d.error.message);status.textContent=d.status==='simulated'?'Dry run complete — no RF transmitted.':
(d.status==='sent'?'Command sent':'Command submitted')+' — shade position remains unverified.';
}catch(e){status.textContent=e.message||'Request outcome unknown.';}finally{setBusy(false);}}
async function get(path){const r=await fetch(path);if(!r.ok)throw Error('Unable to load controls');return r.json();}
Promise.all([get('/api/groups'),get('/api/shades')]).then(([groups,shades])=>{
for(const g of groups.groups){const row=document.createElement('div');row.className='group';const label=document.createElement('span');
label.textContent=g.name;row.append(label);for(const a of ['up','down']){const b=document.createElement('button');
b.dataset.command='true';b.textContent=a==='up'?'Up':'Down';b.onclick=()=>command('/api/commands',{group:g.group,action:a});row.append(b);}
document.getElementById('groups').append(row);}
if(!groups.groups.length)document.getElementById('groups').textContent='No remote groups configured.';
for(const s of shades.shades){const row=document.createElement('div');row.className='shade';const name=document.createElement('strong');
name.textContent=s.name;row.append(name);const label=document.createElement('label');label.htmlFor='shade-'+s.shade;
const slider=document.createElement('input');slider.type='range';slider.min='0';slider.max='100';slider.step='1';slider.value='50';
slider.id=label.htmlFor;slider.dataset.command='true';const button=document.createElement('button');button.textContent='Set requested position';
button.dataset.command='true';const locked=!s.position_enabled||!shades.position_backend_available;
slider.dataset.locked=button.dataset.locked=String(locked);slider.disabled=button.disabled=locked;
const update=()=>{label.textContent='Requested primary position: '+slider.value+'% ('+Math.round(Number(slider.value)*255/100)+'/255)';};
slider.oninput=update;update();button.onclick=()=>command('/api/positions',{shade:s.shade,position:Math.round(Number(slider.value)*255/100)});
row.append(label,slider,button);const note=document.createElement('p');note.textContent=!s.position_enabled?'Position control awaits validation.':
(!shades.position_backend_available?'Position control is unavailable.':'This target is a request, not a measured position.');row.append(note);
document.getElementById('shades').append(row);}
if(!shades.shades.length)document.getElementById('shades').textContent='No individual shades configured.';
status.textContent='Ready. Enter the API token to send a command.';}).catch(e=>status.textContent=e.message);
</script></html>"""


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True

    def __init__(self, address, service: BridgeService, allowed_hosts=None) -> None:
        self.service = service
        super().__init__(address, _Handler)
        bound = self.server_address[0]
        hosts = set(allowed_hosts or (bound,))
        if ipaddress.ip_address(bound).is_loopback:
            hosts.update(("127.0.0.1", "localhost", "::1"))
        self.allowed_hosts = frozenset(str(host).lower() for host in hosts)


class _Handler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    server_version = "PlatinumLocal/1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args) -> None:
        # Requests can contain private labels/tokens in malformed paths. The
        # caller can log command receipts without logging raw request lines.
        pass

    def _reply(self, status: int, value, *, html: bool = False) -> None:
        body = value.encode("utf-8") if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if html:
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: BridgeError) -> None:
        self._reply(error.status, {"error": {"code": error.code, "message": str(error)}})

    def _host(self) -> str:
        headers = self.headers.get_all("Host", [])
        if len(headers) != 1:
            raise BridgeError(400, "invalid_host", "a valid Host header is required")
        try:
            host = urlsplit("//" + headers[0])
            port = host.port or 80
            if (host.hostname not in self.server.allowed_hosts or port != self.server.server_port
                    or host.username is not None or host.password is not None
                    or host.path or host.query or host.fragment):
                raise ValueError("unexpected host")
        except ValueError as exc:
            raise BridgeError(400, "invalid_host", "Host does not match this service") from exc
        return host.hostname

    def _authorize(self, host: str) -> None:
        origins = self.headers.get_all("Origin", [])
        if origins:
            try:
                origin = urlsplit(origins[0])
                if (len(origins) != 1 or origin.scheme != "http" or origin.hostname != host
                        or (origin.port or 80) != self.server.server_port
                        or origin.username is not None or origin.password is not None
                        or origin.path or origin.query or origin.fragment):
                    raise ValueError("cross-origin request")
            except ValueError as exc:
                raise BridgeError(403, "invalid_origin", "cross-origin commands are not accepted") from exc
        headers = self.headers.get_all("Authorization", [])
        scheme, separator, token = headers[0].partition(" ") if len(headers) == 1 else ("", "", "")
        if (scheme.lower() != "bearer" or not separator
                or not secrets.compare_digest(token.encode("utf-8"), self.server.service.config.api_token.encode("ascii"))):
            raise BridgeError(401, "unauthorized", "a valid bearer token is required")

    def do_GET(self) -> None:
        try:
            self._host()
            path = urlsplit(self.path).path
            if path == "/health":
                self._reply(200, self.server.service.health())
            elif path == "/api/groups":
                self._reply(200, self.server.service.groups())
            elif path == "/api/shades":
                self._reply(200, self.server.service.shades())
            elif path == "/":
                self._reply(200, _DASHBOARD, html=True)
            elif path in ("/api/commands", "/api/positions"):
                raise BridgeError(405, "method_not_allowed", "commands require POST")
            else:
                raise BridgeError(404, "not_found", "resource not found")
        except BridgeError as exc:
            self._error(exc)

    def do_POST(self) -> None:
        try:
            host = self._host()
            path = urlsplit(self.path).path
            if path not in ("/api/commands", "/api/positions"):
                raise BridgeError(404, "not_found", "resource not found")
            self._authorize(host)
            if self.headers.get("Transfer-Encoding"):
                raise BridgeError(400, "invalid_body", "chunked requests are not supported")
            lengths = self.headers.get_all("Content-Length", [])
            if not lengths:
                raise BridgeError(411, "length_required", "Content-Length is required")
            try:
                length = int(lengths[0])
                if len(lengths) != 1 or length < 0:
                    raise ValueError("invalid length")
            except ValueError as exc:
                raise BridgeError(400, "invalid_body", "invalid Content-Length") from exc
            if length > MAX_BODY_BYTES:
                raise BridgeError(413, "body_too_large", "command body exceeds 4096 bytes")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise BridgeError(415, "unsupported_media_type", "Content-Type must be application/json")
            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("incomplete body")
                value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise BridgeError(400, "invalid_json", "body must be complete UTF-8 JSON") from exc
            dispatch = (self.server.service.dispatch_position if path == "/api/positions"
                        else self.server.service.dispatch)
            result = dispatch(value)
            self._reply(202 if result["status"] == "submitted" else 200, result)
        except BridgeError as exc:
            self._error(exc)
        except TimeoutError:
            self._error(BridgeError(408, "request_timeout", "request body timed out"))


def make_server(service: BridgeService, *, host: str = "127.0.0.1", port: int = 8077,
                allowed_hosts=None) -> BridgeHTTPServer:
    """Create a server; the caller owns serve_forever/shutdown/server_close.

    When binding a wildcard address, supply explicit allowed_hosts matching the
    hostnames clients will use. No CORS access or token-bearing URL is provided.
    """
    if not isinstance(service, BridgeService):
        raise ValueError("service must be a BridgeService")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    if host in ("0.0.0.0", "::") and not allowed_hosts:
        raise ValueError("wildcard binding requires explicit allowed_hosts")
    return BridgeHTTPServer((host, port), service, allowed_hosts)
