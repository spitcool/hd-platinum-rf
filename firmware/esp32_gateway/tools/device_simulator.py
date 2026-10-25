#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build and run the gateway binary in the native CoreS3 hardware emulator.

Everything downloaded or generated stays in the repository's ignored tmp/ tree.
The source archive and mask ROM are pinned and verified before use. Existing
experimental checkouts are never reset or patched.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import urlopen

from test_native import ROOT, choose_sdk
from wokwi_serial import inventory_hex

REPO = ROOT.parents[1]
CACHE = REPO / "tmp" / "cores3-emulator"
EMULATION = ROOT / "emulation"
COMMIT = "964c26c1a6dac335e849195d2cabc15c713015a3"
ARCHIVE_SHA = "8fe8bb0ddb0b9c3e6f45ece5339773608f2c5dbb7e94ee24f2d398540aad704a"
ROM_SHA = "c0ce0f338d1de1bdc6efbef1591779a2a42c1ab7d759d3c6ae8ae63a7dd34cfd"
PORTS = (18079, 18080, 1523)
URL = "ws://127.0.0.1:18079/ws"


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked(path: Path, expected: str) -> Path:
    if not path.is_file() or digest(path) != expected:
        raise RuntimeError(f"Missing or SHA-256-mismatched file: {path}")
    return path


def tool(local: Path | None, name: str) -> str:
    if local is not None and local.is_file():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Required tool is unavailable: {name}")
    return found


def run(command, log: Path, *, cwd=REPO, env=None):
    with log.open("ab") as output:
        result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-25:])
        raise RuntimeError(f"Command failed ({result.returncode}); log: {log}\n{tail}")


@contextlib.contextmanager
def build_lock():
    with (CACHE / "build.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another native simulator build is using this cache") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def archive() -> Path:
    destination = REPO / "tmp" / "esp32-tools" / "esp32sim-964c26c.tar.gz"
    if destination.exists():
        return checked(destination, ARCHIVE_SHA)
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://codeload.github.com/mikroverk/esp32sim/tar.gz/{COMMIT}"
    print("Downloading pinned emulator source", flush=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with urlopen(url, timeout=60) as response:
                size = 0
                while data := response.read(1024 * 1024):
                    size += len(data)
                    if size > 64 * 1024 * 1024:
                        raise RuntimeError("Emulator archive exceeds its size limit")
                    temporary.write(data)
            temporary.flush()
            checked(temporary_path, ARCHIVE_SHA)
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    return destination


def extract(source: Path, destination: Path):
    """Extract only ordinary files/directories beneath the pinned archive root."""
    prefix = f"esp32sim-{COMMIT}"
    with tarfile.open(source, "r:gz") as package:
        entries = package.getmembers()
        if len(entries) > 20000 or sum(item.size for item in entries) > 256 * 1024 * 1024:
            raise RuntimeError("Emulator archive exceeds extraction limits")
        for item in entries:
            parts = PurePosixPath(item.name).parts
            if not parts or parts[0] != prefix or any(part in ("..", ".") for part in parts):
                raise RuntimeError(f"Unsafe archive path: {item.name}")
            if not (item.isdir() or item.isfile()):
                raise RuntimeError(f"Archive links/devices are not permitted: {item.name}")
            relative = Path(*parts[1:])
            target = destination / relative
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(item) as original, target.open("xb") as output:
                    shutil.copyfileobj(original, output)
                target.chmod(0o755 if item.mode & 0o111 else 0o644)


def inputs():
    patch = (EMULATION / "esp32sim" / "cores3.patch").read_bytes()
    board = (EMULATION / "esp32sim" / "cores3.rs").read_bytes()
    identity = hashlib.sha256(COMMIT.encode() + b"\0" + patch + b"\0" + board).hexdigest()
    return identity, patch, board


def tree_hashes(source: Path):
    return {str(path.relative_to(source)): digest(path)
            for path in sorted(source.rglob("*")) if path.is_file()}


def prepare(identity: str, patch: bytes, board: bytes, log: Path) -> Path:
    source = CACHE / f"source-{identity}"
    receipt = CACHE / f"source-{identity}.json"
    if source.exists():
        expected = json.loads(receipt.read_text()) if receipt.is_file() else None
        if expected != tree_hashes(source):
            raise RuntimeError(f"Immutable emulator source cache was modified: {source}")
        return source
    print("Preparing pinned CoreS3 emulator source", flush=True)
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=CACHE) as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        extract(archive(), staging)
        patch_file = Path(temporary) / "cores3.patch"
        patch_file.write_bytes(patch)
        run([tool(None, "patch"), "--batch", "--forward", "-p1", "-i", patch_file], log, cwd=staging)
        (staging / "esp32s3" / "src" / "board" / "cores3.rs").write_bytes(board)
        hashes = tree_hashes(staging)
        staging.rename(source)
    receipt.write_text(json.dumps(hashes, sort_keys=True, indent=2) + "\n")
    # Builds write into a separate target directory. Cached source is immutable.
    for path in source.rglob("*"):
        path.chmod((0o555 if path.stat().st_mode & 0o111 else 0o444) if path.is_file() else 0o555)
    source.chmod(0o555)
    return source


def rom(source: Path, log: Path) -> Path:
    directory = REPO / "tmp" / "esp32-roms"
    image = directory / "esp32s3_rev0_rom.elf"
    if not image.exists():
        print("Downloading pinned Espressif mask ROM", flush=True)
        # The verified upstream script itself pins the release archive and ELFs.
        run(["/bin/sh", source / "tools" / "fetch-rom-elfs.sh", directory], log)
    return checked(image, ROM_SHA)


def build(identity: str, source: Path, output: Path, log: Path, headless: bool):
    cargo_local = REPO / "tmp" / "esp32-cargo" / "bin" / "cargo"
    try:
        cargo = tool(cargo_local, "cargo")
    except RuntimeError as error:
        raise RuntimeError("Rust is required. Install a stable toolchain with rustup, then run "
                           "`rustup toolchain install stable --profile minimal`. "
                           "No Rust installation was attempted.") from error
    compiler = tool(None, "c++")
    sdk = choose_sdk(compiler, None)
    environment = os.environ.copy()
    if cargo_local.is_file():
        environment.update(CARGO_HOME=str(REPO / "tmp" / "esp32-cargo"),
                           RUSTUP_HOME=str(REPO / "tmp" / "esp32-rustup"))
    environment["CARGO_TARGET_DIR"] = str(CACHE / "rust-target")
    if sdk is not None:
        environment["SDKROOT"] = str(sdk)
    print("Building native emulator", flush=True)
    run([cargo, "build", "--manifest-path", source / "Cargo.toml", "--release", "--locked",
         "-p", "esp32sim", "--bin", "esp32sim"], log, env=environment)
    shutil.copy2(CACHE / "rust-target" / "release" / "esp32sim", output / "esp32sim")

    print("Building CoreS3 emulator firmware", flush=True)
    pio_environment = os.environ.copy()
    pio_environment["PLATFORMIO_CORE_DIR"] = str(REPO / "tmp" / "esp32-platformio")
    run([tool(REPO / ".venv" / "bin" / "pio", "pio"), "run", "-d", ROOT,
         "-e", "cores3_emulator"], log, env=pio_environment)
    for name in ("firmware.merged.bin", "firmware.elf"):
        shutil.copy2(ROOT / ".pio" / "build" / "cores3_emulator" / name, output / name)

    print("Building sample inventory", flush=True)
    cmake = tool(None, "cmake")
    native = CACHE / "native-build"
    configure = [cmake, "-S", ROOT, "-B", native, f"-DCMAKE_CXX_COMPILER={compiler}",
                 "-DCMAKE_BUILD_TYPE=Release", "-DGATEWAY_SANITIZERS=OFF"]
    if platform.system() == "Darwin":
        configure.append(f"-DCMAKE_OSX_SYSROOT={sdk or ''}")
    run(configure, log)
    run([cmake, "--build", native, "--target", "sample_inventory", "--parallel"], log)
    shutil.copy2(native / "sample_inventory", output / "sample_inventory")

    if platform.system() == "Darwin":
        print("Building native CoreS3 window", flush=True)
        contents = output / "CoreS3Simulator.app" / "Contents"
        binary = contents / "MacOS" / "CoreS3Simulator"
        binary.parent.mkdir(parents=True, exist_ok=True)
        swift_source = EMULATION / "macos" / "CoreS3.swift"
        command = [tool(None, "swiftc"), "-swift-version", "5", "-O", "-framework", "AppKit",
                   "-target", f"{platform.machine()}-apple-macos13.0",
                   "-module-cache-path", CACHE / "swift-module-cache",
                   swift_source, "-o", binary]
        if sdk is not None:
            command.extend(["-sdk", sdk])
        run(command, log, env=environment)
        with (contents / "Info.plist").open("wb") as plist:
            plistlib.dump({"CFBundleIdentifier": "org.hdplatinum.CoreS3Simulator",
                           "CFBundleName": "Platinum gateway", "CFBundleExecutable": binary.name,
                           "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
                           "NSHighResolutionCapable": True}, plist)
        run([binary, "--self-test"], log)
    elif not headless:
        raise RuntimeError("The native window requires macOS; use --headless on this platform")
    receipt = {"upstream": COMMIT, "source_identity": identity,
               "files": {name: digest(output / name) for name in
                         ("esp32sim", "firmware.merged.bin", "firmware.elf", "sample_inventory")}}
    (output / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")


def check_ports():
    held = []
    try:
        for port in PORTS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as error:
                raise RuntimeError(f"Cannot use 127.0.0.1:{port}; stop the service occupying that port") from error
    finally:
        for sock in held:
            sock.close()


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def launch(output: Path, image: Path, args, logs: Path) -> int:
    receipt = json.loads((output / "build.json").read_text())
    for name, expected in receipt["files"].items():
        checked(output / name, expected)
    check_ports()
    command = [output / "esp32sim", "--chip", "s3", "--boot", "rom", "--rom", image,
               "--board", "cores3-se", "--flash-image", output / "firmware.merged.bin",
               "--elf", output / "firmware.elf", "--flash-mb", "16", "--psram-mb", "8",
               "--wifi", "ssid=Wokwi-GUEST,chan=6", "--net", "nat", "--web", "18079",
               "--hostfwd", "18080:8077", "--hostfwd", "1523:522", "--console", "usb", "--no-dump"]
    if args.seconds is not None:
        command.extend(["--max-seconds", str(args.seconds)])
    if not args.no_seed:
        line = "import " + inventory_hex(output / "sample_inventory")
        chunks = [line[start:start + 64] for start in range(0, len(line), 64)]
        script = logs / "seed.script"
        script.write_text("\n".join(f"{3 + index * .025:.3f} "
                          + ("serial " if index == len(chunks) - 1 else "serialraw ") + chunk
                          for index, chunk in enumerate(chunks)) + "\n3.5 serial status\n")
        command.extend(["--script", script])
    gui = emulator = None
    with (logs / "emulator.log").open("wb") as emulator_log, (logs / "window.log").open("wb") as window_log:
        try:
            emulator = subprocess.Popen([str(arg) for arg in command], cwd=REPO,
                                        stdin=subprocess.DEVNULL, stdout=emulator_log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 20
            while True:
                if emulator.poll() is not None:
                    raise RuntimeError(f"Emulator exited before opening its display socket; see {logs / 'emulator.log'}")
                try:
                    with socket.create_connection(("127.0.0.1", 18079), timeout=.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"Emulator display socket did not open; see {logs / 'emulator.log'}")
                    time.sleep(.1)
            print(f"Gateway: http://127.0.0.1:18080  TCP: 127.0.0.1:1523\nLogs: {logs}", flush=True)
            if not args.headless:
                binary = output / "CoreS3Simulator.app" / "Contents" / "MacOS" / "CoreS3Simulator"
                gui = subprocess.Popen([str(binary), "--url", URL], cwd=REPO, stdin=subprocess.DEVNULL,
                                       stdout=window_log, stderr=subprocess.STDOUT, start_new_session=True)
            while emulator.poll() is None and (gui is None or gui.poll() is None):
                time.sleep(.1)
            return emulator.returncode or (gui.returncode if gui is not None else 0) or 0
        finally:
            stop(gui)
            stop(emulator)


def seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("seconds must be finite and greater than zero")
    return number


def main(argv=None):
    arguments = argparse.ArgumentParser(description=__doc__)
    modes = arguments.add_mutually_exclusive_group()
    modes.add_argument("--no-build", action="store_true", help="launch the existing verified build")
    modes.add_argument("--build-only", action="store_true", help="prepare and build without starting processes")
    arguments.add_argument("--headless", action="store_true", help="run the hardware emulator without its native window")
    arguments.add_argument("--seconds", type=seconds, help="stop after this many emulated seconds")
    arguments.add_argument("--no-seed", action="store_true", help="boot with an empty shade inventory")
    args = arguments.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    logs = CACHE / "logs" / (time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
    logs.mkdir(parents=True)
    try:
        identity, patch, board = inputs()
        output = CACHE / f"build-{identity}"
        output.mkdir(exist_ok=True)
        if args.no_build:
            image = checked(REPO / "tmp" / "esp32-roms" / "esp32s3_rev0_rom.elf", ROM_SHA)
        else:
            with build_lock():
                source = prepare(identity, patch, board, logs / "build.log")
                image = rom(source, logs / "build.log")
                build(identity, source, output, logs / "build.log", args.headless)
        if args.build_only:
            print(f"Built native simulator: {output}\nBuild log: {logs / 'build.log'}")
            return 0
        return launch(output, image, args, logs)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
