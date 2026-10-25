# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline regression of selected, hash-pinned libbladeRF TX functions."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REVISION = "fcf9423325ae49f5fdd2e5b52ab68bfc2576ad47"
SOURCE = "host/libraries/libbladeRF/src/streaming/sync.c"
INPUT_HASHES = {
    SOURCE: "7fdfa93cd7d999c5a7907f1b6926834ba442429bd1faa465eefa65a743a550ba",
    "host/libraries/libbladeRF/src/streaming/sync.h":
        "54e693a88a1954a11d58a164cf191dc062b5ebc2a89eb9a6aed706fe01d4b407",
    "host/libraries/libbladeRF/src/streaming/metadata.h":
        "26664747a99caeb5d15720e473bd92ffe887c06c7044a5978660dc05277074f4",
    "host/libraries/libbladeRF/include/libbladeRF.h":
        "49fff9b9c40a4e8f0341448e0a9ecc20d579ab598a6ba0241eac22fa28c9bf65",
    "host/libraries/libbladeRF/include/bladeRF1.h":
        "b010dd7d66ff804b8f1acf14bab44b2a0fd93376420c3e2da6f2a6b0d42399fa",
    "host/libraries/libbladeRF/include/bladeRF2.h":
        "ab8862aad3aa7aa9fcbabfdd9002d3fe72ba70ba74e2474557c313a6afcc6abb",
}
PATCHED_HASH = "8ae1f54865aacf2bae57a99ef0c86a728e12d5bab75cc01367031403e599a1fd"
VARIANTS = ("unmodified", "start_only", "two_conditions")
START = "if (s->stream_config.format == BLADERF_FORMAT_SC16_Q11_META) {"
START_FIXED = (
    "if (s->stream_config.format == BLADERF_FORMAT_SC16_Q11_META || "
    "s->stream_config.format == BLADERF_FORMAT_SC8_Q7_META) {"
)
END = "s->stream_config.format == BLADERF_FORMAT_SC16_Q11_META &&"
END_FIXED = (
    "(s->stream_config.format == BLADERF_FORMAT_SC16_Q11_META || "
    "s->stream_config.format == BLADERF_FORMAT_SC8_Q7_META) &&"
)
HERE = Path(__file__).resolve().parent
SCOPE = (
    "Actual extracted host TX serializer and state-machine functions with inert "
    "worker, mutex, and USB submission stubs. No device library is linked or "
    "loaded. sync_init, USB transport, FPGA, RF, and throughput are not tested."
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_inputs(source_dir):
    """Read and verify every upstream input before creating any output."""
    inputs = {}
    for name, expected in INPUT_HASHES.items():
        data = (source_dir / name).read_bytes()
        if digest(data) != expected:
            raise ValueError("Upstream input SHA-256 mismatch: " + name)
        inputs[name] = data
    return inputs


def patched_source(source, *, end_condition=True):
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError("Unexpected upstream patch anchors")
    result = source.replace(START, START_FIXED)
    return result.replace(END, END_FIXED) if end_condition else result


def extract(source):
    """Retain the upstream license and exact text of the selected functions."""
    spans = (
        (None, "#include"),
        ("static inline size_t samples2bytes", "int sync_init("),
        ("static inline unsigned int left_in_msg", "static inline void advance_rx_buffer"),
        ("/* Assumes buffer lock is held */", "unsigned int sync_buf2idx"),
    )
    return "\n".join(
        source[0 if start is None else source.index(start):source.index(end)]
        for start, end in spans
    )


def prepare(inputs, output_dir):
    source = inputs[SOURCE].decode("utf-8")
    fixed = patched_source(source)
    if digest(fixed.encode()) != PATCHED_HASH:
        raise ValueError("Patched source does not match the reviewed result")
    diff = "".join(difflib.unified_diff(
        source.splitlines(keepends=True), fixed.splitlines(keepends=True),
        fromfile="a/" + SOURCE, tofile="b/" + SOURCE,
    ))
    distributed_patch = (HERE / "sc8-metadata.patch").read_text()
    if distributed_patch[distributed_patch.index("--- a/"):] != diff:
        raise ValueError("Distributed patch differs from the tested modification")
    # A new directory keeps prior results and the supplied upstream tree intact.
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    variants = (source, patched_source(source, end_condition=False), fixed)
    for name, body in zip(VARIANTS, variants):
        (output_dir / (name + ".inc")).write_text(extract(body))
    for name, data in inputs.items():
        if name != SOURCE:
            (output_dir / Path(name).name).write_bytes(data)
    (output_dir / "thread.h").write_text(
        "/* Inert single-thread test substitutes; no platform thread API. */\n"
        "#define MUTEX int\n#define COND int\n"
        "#define MUTEX_LOCK(x) ((void)(x))\n"
        "#define MUTEX_UNLOCK(x) ((void)(x))\n"
    )
    shutil.copyfile(HERE / "probe.c", output_dir / "probe.c")


def invoke(command, output_dir, label, timeout):
    # The supplied source is hash-pinned and no shell is involved. Each process
    # has a wall bound; subprocess.run kills and reaps it on timeout.
    result = subprocess.run(
        command, cwd=output_dir, capture_output=True, text=True, timeout=timeout,
    )
    (output_dir / (label + ".stdout.log")).write_text(result.stdout)
    (output_dir / (label + ".stderr.log")).write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(label + " failed; see retained output logs")
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_results(results, output_dir):
    for variant, rows in results.items():
        require(len(rows) == 44, variant + ": incomplete output matrix")
        for row in rows:
            if variant != "two_conditions" and row["format"] != 2:
                continue
            if "first_ok" in row:
                require(row["first_ok"] and row["second_ok"], "TX case failed")
            if row.get("update_case"):
                require(row["passed"], "Timestamp update case failed")
            if row.get("parameters"):
                require(all(row[key] == -3 for key in (
                    "null_rc", "NOW_without_START_rc", "END_without_START_rc",
                )), "Invalid metadata was accepted")

    original = results["unmodified"]
    original_sc8 = [r for r in original if r["format"] == 5 and "first_ok" in r]
    require(len(original_sc8) == 21, "SC8 case coverage changed")
    require(not any(r["first_ok"] or r["second_ok"] for r in original_sc8),
            "Unmodified SC8 defect was not reproduced")
    require(any(r["buffers"] == 0 for r in original_sc8), "Missing tail-flush reproduction")
    require(any(r["buffers"] > 0 and r["first_header_timestamp"] == 0
                and not r["now"] for r in original_sc8), "Missing timestamp reproduction")
    bad_parameters = next(r for r in original if r["format"] == 5 and r.get("parameters"))
    require(all(bad_parameters[k] == 0 for k in (
        "null_rc", "NOW_without_START_rc", "END_without_START_rc",
    )), "Missing metadata-validation reproduction")
    start_only = [r for r in results["start_only"] if r["format"] == 5 and "first_ok" in r]
    require(all(r["first_rc"] == 0 and r["second_rc"] == -3 and r["buffers"] > 0
                and not any(r[k] for k in ("header_errors", "data_errors", "padding_errors", "guard_errors"))
                for r in start_only), "First-condition-only failure was not reproduced")

    sc16 = [[r for r in results[name] if r["format"] == 2] for name in VARIANTS]
    require(sc16[0] == sc16[1] == sc16[2], "SC16 results changed")
    # Compare every emitted SC16 byte, including both bursts, update gaps,
    # metadata, and all tail padding. SHA-256 is only a report identifier.
    wire = [(output_dir / (name + ".sc16-wire.bin")).read_bytes() for name in VARIANTS]
    require(bool(wire[0]) and wire[0] == wire[1] == wire[2], "SC16 wire bytes changed")
    return {"bytes_per_variant": len(wire[0]), "sha256": digest(wire[0])}


def run(source_dir, output_dir, *, cc="cc", cflags=(), sanitize=False):
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if source_dir == output_dir or source_dir in output_dir.parents:
        raise ValueError("Output must be outside the supplied upstream source tree")
    inputs = read_inputs(source_dir)
    prepare(inputs, output_dir)
    results = {}
    commands = []
    for variant in VARIANTS:
        executable = output_dir / ("probe-" + variant)
        command = [cc, "-std=c11", "-O1", "-g", *cflags]
        if sanitize:
            command.append("-fsanitize=address,undefined")
        command.extend([
            "-I.", '-DSOURCE_FILE="' + variant + '.inc"', "probe.c",
            "-o", str(executable),
        ])
        commands.append(command)
        invoke(command, output_dir, variant + ".build", 60)
        result = invoke(
            [str(executable), variant + ".sc16-wire.bin"], output_dir, variant, 90,
        )
        require(not result.stderr, "Probe emitted diagnostics; see retained stderr")
        results[variant] = [json.loads(line) for line in result.stdout.splitlines()]
    sc16 = validate_results(results, output_dir)
    # Re-read the inputs to detect accidental mutation, not merely hash the copy.
    require(read_inputs(source_dir) == inputs, "Supplied inputs changed during the run")
    report = {
        "passed": True, "scope": SCOPE, "upstream_revision": REVISION,
        "input_sha256": INPUT_HASHES, "patched_sync_c_sha256": PATCHED_HASH,
        "patch_sha256": digest((HERE / "sc8-metadata.patch").read_bytes()),
        "sanitizers_enabled": sanitize, "SC16_byte_identical": sc16,
        "results": {name: {
            "output_rows": len(rows),
            "SC16_burst_cases": sum("first_ok" in r and r["format"] == 2 for r in rows),
            "SC8_burst_cases": sum("first_ok" in r and r["format"] == 5 for r in rows),
            "SC8_first_pass": sum(r.get("first_ok", False) and r["format"] == 5 for r in rows),
            "SC8_second_pass": sum(r.get("second_ok", False) and r["format"] == 5 for r in rows),
        } for name, rows in results.items()},
        "build_commands": commands,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path, help="Unmodified pinned bladeRF source tree")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory outside that tree; parent must exist")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="C compiler executable (no shell words)")
    parser.add_argument("--cflag", action="append", default=[], help="Repeat for compiler arguments; use --cflag=-flag")
    parser.add_argument("--sanitize", action="store_true", help="Enable compiler ASan and UBSan")
    args = parser.parse_args(argv)
    try:
        report = run(args.source_dir, args.output_dir, cc=args.cc, cflags=args.cflag, sanitize=args.sanitize)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, "Regression check failed: " + str(error) + "\n")
    print(json.dumps({"passed": report["passed"], "results": report["results"],
                      "SC16_byte_identical": report["SC16_byte_identical"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
