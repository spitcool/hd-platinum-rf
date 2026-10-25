#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build and run every portable firmware test, without PlatformIO or RF hardware.

macOS can have a selected SDK newer than its available linker. Probe a tiny
compile/link first; use another installed SDK only if the default fails. An
explicit --sdk never falls back silently. No SDK or compiler is downloaded.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def sdk_candidates(explicit: str | None):
    if explicit:
        yield Path(explicit).expanduser().resolve(strict=True)
        return
    yield None
    if platform.system() != "Darwin":
        return
    found: list[Path] = []
    xcrun = shutil.which("xcrun")
    if xcrun:
        selected = subprocess.run([xcrun, "--show-sdk-path"], capture_output=True, text=True)
        if selected.returncode == 0:
            found.append(Path(selected.stdout.strip()))
    roots = [Path("/Library/Developer/CommandLineTools/SDKs")]
    roots.extend(Path("/Applications").glob("Xcode*.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs"))
    for root in roots:
        # Prefer newer available versions; the compile/link probe decides which
        # are compatible, instead of depending on a particular machine's SDK.
        found.extend(sorted(root.glob("MacOSX*.sdk"),
                            key=lambda p: tuple(map(int, re.findall(r"\d+", p.name))),
                            reverse=True))
    seen: set[Path] = set()
    for candidate in found:
        actual = candidate.resolve()
        if actual not in seen and actual.is_dir():
            seen.add(actual)
            yield actual


def choose_sdk(compiler: str, explicit: str | None):
    failures = []
    with tempfile.TemporaryDirectory(prefix="platinum-native-probe-") as temporary:
        directory = Path(temporary)
        source = directory / "probe.cpp"
        source.write_text("#include <string>\nint main() { return std::string(\"ok\").size() != 2; }\n")
        for sdk in sdk_candidates(explicit):
            command = [compiler, "-std=c++17", str(source), "-o", str(directory / "probe")]
            if sdk is not None:
                command.extend(["-isysroot", str(sdk)])
            probe = subprocess.run(command, capture_output=True, text=True)
            if probe.returncode == 0:
                run = subprocess.run([str(directory / "probe")], capture_output=True, text=True)
                if run.returncode == 0:
                    if sdk is not None:
                        print(f"Native compiler SDK: {sdk}", flush=True)
                    return sdk
                failures.append(f"{sdk or 'default SDK'}: compiled probe could not run: {run.stderr}")
            else:
                failures.append(f"{sdk or 'default SDK'}: {probe.stderr[-2000:]}")
    raise RuntimeError("No working native compiler/SDK combination:\n" + "\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / ".native-build")
    parser.add_argument("--compiler", default=os.environ.get("CXX", "c++"))
    parser.add_argument("--sdk", help="Explicit macOS SDK path (no automatic fallback)")
    parser.add_argument("--sanitizers", action="store_true")
    arguments = parser.parse_args()
    compiler = shutil.which(arguments.compiler)
    cmake, ctest = shutil.which("cmake"), shutil.which("ctest")
    if not compiler or not cmake or not ctest:
        parser.error("A C++17 compiler, cmake and ctest must be installed and available on PATH")
    try:
        sdk = choose_sdk(compiler, arguments.sdk)
        configure = [cmake, "-S", str(ROOT), "-B", str(arguments.build_dir),
                     f"-DCMAKE_CXX_COMPILER={compiler}", "-DCMAKE_BUILD_TYPE=Debug",
                     f"-DGATEWAY_SANITIZERS={'ON' if arguments.sanitizers else 'OFF'}"]
        if platform.system() == "Darwin":
            configure.append(f"-DCMAKE_OSX_SYSROOT={sdk or ''}")
        subprocess.run(configure, check=True)
        subprocess.run([cmake, "--build", str(arguments.build_dir), "--parallel"], check=True)
        subprocess.run([ctest, "--test-dir", str(arguments.build_dir), "--output-on-failure"], check=True)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
