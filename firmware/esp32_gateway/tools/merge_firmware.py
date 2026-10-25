# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""PlatformIO post script: merge the exact ESP32-S3 inputs into a flash image.

Configure with ``extra_scripts = post:tools/merge_firmware.py``. The buildprog
post action runs after application, partition and bootloader images exist. It
derives the application offset from the selected partition table for both merge
and physical upload, and uses PlatformIO's flash-header helpers.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def _number(value, label: str) -> int:
    try:
        result = int(str(value), 0)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid {label}: {value!r}") from error
    if result < 0:
        raise ValueError(f"Negative {label}")
    return result


def _flash_size(value: str) -> tuple[str, int]:
    match = re.fullmatch(r"([1-9][0-9]*)(KB|MB)", str(value).strip().upper())
    if not match:
        raise ValueError("Offline merge requires an explicit upload.flash_size, such as 16MB")
    count, unit = int(match[1]), match[2]
    size = count * (1024 if unit == "KB" else 1024 * 1024)
    if size != 16 * 1024 * 1024:
        raise ValueError("This CoreS3 image requires upload.flash_size = 16MB")
    return "16MB", size


def _path(environment, value, project: Path) -> Path:
    path = Path(environment.subst(str(value))).expanduser()
    return (path if path.is_absolute() else project / path).resolve()


def _partition_value(value, keywords=None):
    value = value.strip().lower()
    if keywords and value in keywords:
        return keywords[value]
    multiplier = {"k": 1024, "m": 1024 * 1024}.get(value[-1:] or "")
    return int(value[:-1], 0) * multiplier if multiplier else int(value, 0)


def partition_layout(environment):
    """Read the exact CSV selected by the framework, before binaries exist."""
    project = Path(environment.subst("$PROJECT_DIR")).resolve()
    selected = environment.get("PARTITIONS_TABLE_CSV")
    if not selected:
        raise ValueError("The framework must resolve PARTITIONS_TABLE_CSV before this post script")
    path = _path(environment, selected, project)
    # The pinned ESP32-S3 framework writes partitions.bin at 0x8000.
    next_offset = 0x9000
    partitions = []
    data_subtypes = {"ota": 0, "phy": 1, "nvs": 2, "coredump": 3, "nvs_keys": 4,
                     "efuse": 5, "undefined": 6, "esphttpd": 0x80, "fat": 0x81, "spiffs": 0x82}
    app_subtypes = {"factory": 0, "test": 0x20, **{f"ota_{i}": 0x10 + i for i in range(16)}}
    with path.open(newline="") as source:
        for line_number, line in enumerate(source, 1):
            line = os.path.expandvars(line).strip()
            if not line or line.startswith("#"):
                continue
            row = [field.strip() for field in next(csv.reader([line]))]
            try:
                name, kind, subtype, offset, size = row[:5]
                kind = _partition_value(kind, {"app": 0, "data": 1})
                subtype = _partition_value(subtype, app_subtypes if kind == 0 else data_subtypes)
                alignment = 0x10000 if kind == 0 else 4
                offset = _partition_value(offset) if offset else (next_offset + alignment - 1) & -alignment
                size = _partition_value(size)
                if size < 0:
                    size = -size - offset
                if not name or offset < next_offset or offset % alignment or size <= 0:
                    raise ValueError("invalid partition range")
            except (ValueError, TypeError) as error:
                raise ValueError(f"Invalid partition CSV {path}:{line_number}: {error}") from error
            partitions.append({"name": name, "type": kind, "subtype": subtype,
                               "offset": offset, "size": size})
            next_offset = offset + size
    if not partitions:
        raise ValueError(f"Empty partition table: {path}")
    return partitions


def _protect_nvs(images, partitions, require_files=False):
    for address, path in images:
        # Setup runs before generated files exist. Their complete ranges are
        # checked again after building and immediately before physical upload.
        if not path.is_file() and require_files:
            raise ValueError(f"Missing flash input: {path}")
        size = path.stat().st_size if path.is_file() else 1
        for partition in partitions:
            if (partition["type"], partition["subtype"]) != (1, 2):
                continue
            if address < partition["offset"] + partition["size"] and address + size > partition["offset"]:
                raise ValueError(f"Flash image {path} at {address:#x} overlaps NVS partition {partition['name']}")


def application_partition(environment, partitions):
    """Select the same factory/OTA entry the bootloader starts on a fresh image.

    The pinned Arduino PlatformIO builder defaults ESP32_APP_OFFSET to 0x10000;
    it does not update that value from a custom partition CSV. An explicit board
    upload offset is respected only when it names an actual application entry.
    """
    apps = [partition for partition in partitions if partition["type"] == 0]
    explicit = environment.BoardConfig().get("upload.offset_address", None)
    if explicit is not None:
        offset = _number(environment.subst(str(explicit)), "board application offset")
        matches = [partition for partition in apps if partition["offset"] == offset]
        if len(matches) != 1:
            raise ValueError("Explicit upload.offset_address must match an application partition")
        return matches[0]
    for subtype in (0, 0x10):  # factory first, then ota_0 when no factory exists
        matches = [partition for partition in apps if partition["subtype"] == subtype]
        if len(matches) > 1:
            raise ValueError("Ambiguous application partition layout")
        if matches:
            return matches[0]
    raise ValueError("A factory or ota_0 application partition is required")


def configure_flash_images(environment):
    """Remove only Arduino's unused OTA initializer from factory-only builds.

    This executes when the post script loads, not just when merging. PlatformIO
    has already copied extra images into UPLOADERFLAGS, so both representations
    must be updated before upload commands are expanded.
    """
    partitions = partition_layout(environment)
    application = application_partition(environment, partitions)
    project = Path(environment.subst("$PROJECT_DIR")).resolve()
    package = environment.PioPlatform().get_package_dir("framework-arduinoespressif32")
    if not package:
        raise ValueError("The Arduino framework package is required to identify boot_app0.bin")
    boot_app = (Path(package) / "tools" / "partitions" / "boot_app0.bin").resolve()
    ota = [p for p in partitions if (p["type"], p["subtype"]) == (1, 0)]
    apps = [p for p in partitions if p["type"] == 0]
    factory_only = bool(apps) and all(p["subtype"] == 0 for p in apps)
    kept, removed, resolved = [], [], []
    for entry in environment.get("FLASH_EXTRA_IMAGES", []):
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError("FLASH_EXTRA_IMAGES entries must be (address, filename) pairs")
        address = _number(environment.subst(str(entry[0])), "extra-image address")
        path = _path(environment, entry[1], project)
        if path == boot_app:
            if not ota:
                if not factory_only:
                    raise ValueError("Arduino boot_app0.bin requires otadata or a factory-only layout")
                removed.append((address, path, environment.subst(str(entry[1]))))
                continue
            if not path.is_file() or not any(address == p["offset"] and path.stat().st_size <= p["size"] for p in ota):
                raise ValueError("Arduino boot_app0.bin does not fit the configured otadata partition")
        kept.append(entry)
        resolved.append((address, path))
    _protect_nvs(resolved, partitions)

    flags = list(environment.get("UPLOADERFLAGS", []))
    for address, path, original_path in removed:
        index = 0
        while index + 1 < len(flags):
            try:
                matches = (_number(environment.subst(str(flags[index])), "upload address") == address
                           and _path(environment, flags[index + 1], project) == path)
            except ValueError:
                matches = False
            if matches:
                del flags[index:index + 2]
            else:
                index += 1
        # An unsupported uploader may embed the address/path in one command.
        # Stop instead of leaving a stale command which could overwrite NVS.
        if any(any(candidate in environment.subst(str(flag)) for candidate in (str(path), original_path))
               for flag in flags):
            raise ValueError("Cannot safely remove obsolete boot_app0.bin from this uploader's arguments")
    app_offset = hex(application["offset"])
    integration = dict(environment.get("INTEGRATION_EXTRA_DATA", {}))
    integration["application_offset"] = app_offset
    # UPLOADCMD uses $ESP32_APP_OFFSET at execution time. Updating it here keeps
    # the physical uploader, IDE integration metadata and offline image aligned.
    environment.Replace(FLASH_EXTRA_IMAGES=kept, UPLOADERFLAGS=flags,
                        ESP32_APP_OFFSET=app_offset, INTEGRATION_EXTRA_DATA=integration)
    if removed:
        print("Factory-only layout: omitting unused boot_app0.bin from merge and upload")


def merge_inputs(environment):
    """Resolve and validate a merge plan; kept separate for offline testing."""
    board = environment.BoardConfig()
    chip = str(board.get("build.mcu", ""))
    if chip != "esp32s3":
        raise ValueError("The CoreS3 merged image requires an ESP32-S3 build")
    project = Path(environment.subst("$PROJECT_DIR")).resolve()
    build = _path(environment, "$BUILD_DIR", project)
    program = environment.subst("$PROGNAME")
    if not program or Path(program).name != program:
        raise ValueError("Invalid PlatformIO program name")
    flash_size, flash_bytes = _flash_size(board.get("upload.flash_size", ""))
    # These are the same helpers used by the pinned platform's write_flash
    # command. In particular, qio board metadata may require a dio boot header.
    mode = environment.subst("${__get_board_flash_mode(__env__)}")
    frequency = environment.subst("${__get_board_f_image(__env__)}")
    if mode not in ("qio", "qout", "dio", "dout"):
        raise ValueError(f"PlatformIO did not resolve a supported boot flash mode: {mode!r}")
    if not re.fullmatch(r"[1-9][0-9]*m", frequency):
        raise ValueError(f"PlatformIO did not resolve the flash frequency: {frequency!r}")

    package = environment.PioPlatform().get_package_dir("tool-esptoolpy")
    if not package:
        raise ValueError("PlatformIO's pinned tool-esptoolpy package is unavailable")
    esptool = Path(package).resolve() / "esptool.py"
    if not esptool.is_file():
        raise ValueError(f"Missing pinned esptool executable: {esptool}")
    python = environment.subst("$PYTHONEXE") or sys.executable
    if "$" in python:
        raise ValueError("PlatformIO did not resolve PYTHONEXE")

    images = []
    for entry in environment.get("FLASH_EXTRA_IMAGES", []):
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError("FLASH_EXTRA_IMAGES entries must be (address, filename) pairs")
        address = _number(environment.subst(str(entry[0])), "extra-image address")
        images.append((address, _path(environment, entry[1], project)))
    if not images:
        raise ValueError("No bootloader/partition FLASH_EXTRA_IMAGES were supplied")
    partitions = partition_layout(environment)
    application = application_partition(environment, partitions)
    app_offset = _number(environment.subst("$ESP32_APP_OFFSET"), "application offset")
    if app_offset != application["offset"]:
        raise ValueError("ESP32_APP_OFFSET no longer matches the selected application partition")
    app_image = build / (program + ".bin")
    if app_image.is_file() and app_image.stat().st_size > application["size"]:
        raise ValueError(f"Application image exceeds partition {application['name']}")
    images.append((app_offset, app_image))
    images.sort(key=lambda image: image[0])
    if images[0][0] != 0:
        raise ValueError("An ESP32-S3 bootloader image at flash offset 0 is required")
    previous_end = 0
    for address, path in images:
        if not path.is_file():
            raise ValueError(f"Missing flash input: {path}")
        size = path.stat().st_size
        if size == 0 or address < previous_end or address + size > flash_bytes:
            raise ValueError(f"Empty, overlapping, or out-of-flash image at {address:#x}: {path}")
        previous_end = address + size
    _protect_nvs(images, partitions, require_files=True)
    return {
        "project": project, "build": build, "program": program,
        "python": python, "esptool": esptool, "chip": chip,
        "flash_size": flash_size, "flash_bytes": flash_bytes,
        "mode": mode, "frequency": frequency, "images": images,
    }


def merge_firmware(source, target, env):
    """SCons post-action callback; a failed merge fails the PlatformIO build."""
    del source, target
    plan = merge_inputs(env)
    output = plan["build"] / (plan["program"] + ".merged.bin")
    with tempfile.TemporaryDirectory(prefix=".merge-firmware-", dir=plan["build"]) as directory:
        temporary = Path(directory) / output.name
        command = [
            plan["python"], str(plan["esptool"]), "--chip", plan["chip"],
            "merge_bin", "--output", str(temporary), "--format", "raw",
            "--flash_mode", plan["mode"], "--flash_freq", plan["frequency"],
            "--flash_size", plan["flash_size"], "--fill-flash-size", plan["flash_size"],
            "--target-offset", "0",
        ]
        for address, image in plan["images"]:
            command.extend((hex(address), str(image)))
        print(f"Merging {len(plan['images'])} flash inputs into {output.name} ({plan['flash_size']})")
        subprocess.run(command, cwd=plan["project"], check=True, timeout=60)
        if not temporary.is_file() or temporary.stat().st_size != plan["flash_bytes"]:
            raise RuntimeError("esptool did not produce the complete 16MB merged flash image")
        os.replace(temporary, output)
    return 0


def validate_upload(source, target, env):
    del source, target
    merge_inputs(env)
    return 0


# PlatformIO injects Import and env. Normal Python import remains side-effect
# free so the resolver and subprocess arguments can be regression tested.
if "Import" in globals():
    Import("env")  # noqa: F821 - supplied by SCons
    configure_flash_images(env)  # noqa: F821
    env.AddPreAction("upload", validate_upload)  # noqa: F821
    env.AddPostAction("buildprog", merge_firmware)  # noqa: F821
    # The app can already be up to date after an earlier failed merge. A phony
    # buildprog alias would otherwise skip this post-action and report success
    # without ever producing the simulator image.
    env.AlwaysBuild("buildprog")  # noqa: F821
