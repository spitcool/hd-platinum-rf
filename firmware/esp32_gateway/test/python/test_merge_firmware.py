# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline regression checks for the physical-upload and merged-image layout.

Run: python3 firmware/esp32_gateway/test/python/test_merge_firmware.py
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "merge_firmware.py"
spec = importlib.util.spec_from_file_location("merge_firmware", SCRIPT)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)

FACTORY = """# Name, Type, SubType, Offset, Size, Flags
nvs, data, nvs, 0x9000, 0x70000,
phy_init, data, phy, 0x79000, 0x1000,
factory, app, factory, 0x80000, 0x700000,
"""
OTA = """nvs, data, nvs, , 20K,
otadata, data, ota, , 8K,
factory, app, factory, , 1M,
ota_0, app, ota_0, , 1M,
"""


class FakeBoard(dict):
    def get(self, key, *default):
        # PlatformIO raises for absent keys unless a default is explicit.
        return super().get(key, default[0]) if default else self[key]


class FakeEnvironment(dict):
    def __init__(self, project):
        self.project = project
        self.board = FakeBoard({"build.mcu": "esp32s3", "upload.flash_size": "16MB"})
        self.framework = project / "framework"
        self.esptool = project / "esptool"
        self.framework.mkdir()
        self.esptool.mkdir()
        (self.esptool / "esptool.py").write_text("# offline fixture\n")
        build = project / "build"
        build.mkdir()
        self.boot_app = self.framework / "tools" / "partitions" / "boot_app0.bin"
        self.boot_app.parent.mkdir(parents=True)
        self.boot_app.write_bytes(b"B" * 0x2000)
        (build / "bootloader.bin").write_bytes(b"L" * 0x1000)
        (build / "partitions.bin").write_bytes(b"P" * 0xc00)
        (build / "firmware.bin").write_bytes(b"A" * 0x10000)
        self.csv = project / "partitions.csv"
        self.csv.write_text(FACTORY)
        extras = [("0x0", "$BUILD_DIR/bootloader.bin"),
                  ("0x8000", "$BUILD_DIR/partitions.bin"),
                  ("0xe000", str(self.boot_app))]
        super().__init__(PROJECT_DIR=str(project), BUILD_DIR=str(build), PROGNAME="firmware",
                         PYTHONEXE="python3", ESP32_APP_OFFSET="0x10000",
                         PARTITIONS_TABLE_CSV=str(self.csv), FLASH_EXTRA_IMAGES=extras)
        flags = ["--chip", "esp32s3", "--port", "$UPLOAD_PORT", "write_flash", "-z"]
        for address, image in extras:
            flags.extend((address, self.subst(image)))
        self["UPLOADERFLAGS"] = flags
        self["UPLOADCMD"] = '"$PYTHONEXE" "$UPLOADER" $UPLOADERFLAGS $ESP32_APP_OFFSET $SOURCE'
        self["INTEGRATION_EXTRA_DATA"] = {"application_offset": "0x10000", "other": "preserved"}

    def BoardConfig(self):
        return self.board

    def PioPlatform(self):
        return self

    def get_package_dir(self, package):
        return str({"framework-arduinoespressif32": self.framework,
                    "tool-esptoolpy": self.esptool}[package])

    def subst(self, value):
        if value == "${__get_board_flash_mode(__env__)}":
            return "dio"
        if value == "${__get_board_f_image(__env__)}":
            return "80m"
        for key, replacement in self.items():
            if isinstance(replacement, str):
                value = value.replace("$" + key, replacement)
        return value

    def Replace(self, **values):
        self.update(values)


class FlashLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gateway flash $ fixture ")
        self.addCleanup(self.temporary.cleanup)
        self.environment = FakeEnvironment(Path(self.temporary.name))

    def configure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            merge.configure_flash_images(self.environment)

    def test_factory_image_and_physical_upload_both_omit_ota_initializer(self):
        self.configure()
        environment = self.environment
        self.assertEqual([address for address, _ in environment["FLASH_EXTRA_IMAGES"]], ["0x0", "0x8000"])
        self.assertNotIn(str(environment.boot_app), environment["UPLOADERFLAGS"])
        self.assertNotIn("0xe000", environment["UPLOADERFLAGS"])
        self.assertEqual(environment["UPLOADERFLAGS"][:6],
                         ["--chip", "esp32s3", "--port", "$UPLOAD_PORT", "write_flash", "-z"])
        self.assertEqual(environment["ESP32_APP_OFFSET"], "0x80000")
        self.assertIn(" 0x80000 $SOURCE", environment.subst(environment["UPLOADCMD"]))
        self.assertEqual(environment["INTEGRATION_EXTRA_DATA"],
                         {"application_offset": "0x80000", "other": "preserved"})
        plan = merge.merge_inputs(environment)
        self.assertEqual([address for address, _ in plan["images"]], [0, 0x8000, 0x80000])
        before = dict(environment)
        self.configure()
        self.assertEqual(before, environment)  # configuration is idempotent

    def test_application_offset_follows_changed_partition_not_a_constant(self):
        self.environment.csv.write_text(FACTORY.replace("0x80000, 0x700000", "0x90000, 0x600000"))
        self.configure()
        self.assertEqual(self.environment["ESP32_APP_OFFSET"], "0x90000")
        self.assertEqual(merge.merge_inputs(self.environment)["images"][-1][0], 0x90000)

    def test_ota_only_layout_selects_first_ota_application(self):
        self.environment.csv.write_text(OTA.replace("factory, app, factory, , 1M,\n", ""))
        self.environment["ESP32_APP_OFFSET"] = "0x80000"
        self.configure()
        self.assertEqual(self.environment["ESP32_APP_OFFSET"], "0x10000")
        self.assertEqual(merge.merge_inputs(self.environment)["images"][-1][0], 0x10000)

    def test_explicit_board_offset_must_name_an_application_partition(self):
        self.environment.board["upload.offset_address"] = "0x10000"
        with self.assertRaisesRegex(ValueError, "must match an application"):
            self.configure()

    def test_explicit_board_offset_can_select_an_ota_partition(self):
        self.environment.csv.write_text(OTA)
        self.environment.board["upload.offset_address"] = "0x110000"
        self.configure()
        self.assertEqual(self.environment["ESP32_APP_OFFSET"], "0x110000")
        self.assertEqual(merge.merge_inputs(self.environment)["images"][-1][0], 0x110000)

    def test_later_offset_change_prevents_upload(self):
        self.configure()
        self.environment["ESP32_APP_OFFSET"] = "0x10000"
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            merge.validate_upload([], [], self.environment)

    def test_application_must_fit_its_partition_not_just_flash(self):
        self.configure()
        image = Path(self.environment["BUILD_DIR"]) / "firmware.bin"
        image.write_bytes(b"A" * (0x700000 + 1))
        with self.assertRaisesRegex(ValueError, "exceeds partition"):
            merge.merge_inputs(self.environment)

    def test_valid_ota_layout_keeps_both_upload_and_merge_initializer(self):
        environment = self.environment
        environment.csv.write_text(OTA)
        environment["ESP32_APP_OFFSET"] = "0x10000"
        extras, flags = list(environment["FLASH_EXTRA_IMAGES"]), list(environment["UPLOADERFLAGS"])
        self.configure()
        self.assertEqual(environment["FLASH_EXTRA_IMAGES"], extras)
        self.assertEqual(environment["UPLOADERFLAGS"], flags)
        plan = merge.merge_inputs(environment)
        self.assertEqual([address for address, _ in plan["images"]], [0, 0x8000, 0xe000, 0x10000])

    def test_numeric_types_and_subtypes_are_recognized(self):
        self.environment.csv.write_text(FACTORY.replace("data, nvs", "0x1, 0x2")
                                      .replace("data, phy", "1, 1").replace("app, factory", "0, 0"))
        self.configure()
        self.assertEqual(len(self.environment["FLASH_EXTRA_IMAGES"]), 2)

    def test_numeric_otadata_is_preserved(self):
        self.environment.csv.write_text(OTA.replace("data, ota", "0x1, 0x0"))
        self.configure()
        self.assertEqual(len(self.environment["FLASH_EXTRA_IMAGES"]), 3)

    def test_unknown_same_named_image_is_never_silently_removed(self):
        image = self.environment.project / "boot_app0.bin"
        image.write_bytes(b"custom")
        self.environment["FLASH_EXTRA_IMAGES"][-1] = ("0xe000", str(image))
        with self.assertRaisesRegex(ValueError, "overlaps NVS"):
            self.configure()
        self.assertIn(("0xe000", str(image)), self.environment["FLASH_EXTRA_IMAGES"])

    def test_unrelated_extra_image_is_preserved(self):
        image = self.environment.project / "custom.bin"
        image.write_bytes(b"custom")
        self.environment["FLASH_EXTRA_IMAGES"].append(("0x780000", str(image)))
        self.environment["UPLOADERFLAGS"].extend(("0x780000", str(image)))
        self.configure()
        self.assertIn(("0x780000", str(image)), self.environment["FLASH_EXTRA_IMAGES"])
        self.assertEqual(self.environment["UPLOADERFLAGS"][-2:], ["0x780000", str(image)])

    def test_range_overlapping_nvs_fails_even_if_it_starts_before_nvs(self):
        image = self.environment.project / "unknown.bin"
        image.write_bytes(b"?" * 0x2000)
        self.environment["FLASH_EXTRA_IMAGES"].append(("0x8000", str(image)))
        with self.assertRaisesRegex(ValueError, "overlaps NVS"):
            self.configure()

    def test_generated_image_range_is_rechecked_before_upload(self):
        image = Path(self.environment["BUILD_DIR"]) / "partitions.bin"
        image.unlink()
        self.configure()  # generated file does not exist at post-script load
        image.write_bytes(b"?" * 0x2000)  # unexpectedly extends into NVS
        with self.assertRaisesRegex(ValueError, "overlaps NVS"):
            merge.validate_upload([], [], self.environment)

    def test_missing_generated_file_prevents_upload(self):
        self.configure()
        (Path(self.environment["BUILD_DIR"]) / "firmware.bin").unlink()
        with self.assertRaisesRegex(ValueError, "Missing flash input"):
            merge.validate_upload([], [], self.environment)

    def test_ota_initializer_must_match_otadata_offset_and_size(self):
        for text in (OTA.replace("otadata, data, ota, , 8K", "otadata, data, ota, 0xf000, 8K"),
                     OTA.replace("otadata, data, ota, , 8K", "otadata, data, ota, , 4K")):
            with self.subTest(csv=text):
                self.environment.csv.write_text(text)
                with self.assertRaisesRegex(ValueError, "does not fit"):
                    self.configure()

    def test_ota_application_without_otadata_is_not_treated_as_factory_only(self):
        self.environment.csv.write_text(FACTORY.replace("factory, app, factory", "ota_0, app, ota_0"))
        with self.assertRaisesRegex(ValueError, "requires otadata"):
            self.configure()

    def test_embedded_stale_upload_command_fails_instead_of_silently_remaining(self):
        self.environment["UPLOADERFLAGS"] = ["-c", f"program_esp {{{self.environment.boot_app}}} 0xe000 verify"]
        with self.assertRaisesRegex(ValueError, "Cannot safely remove"):
            self.configure()

    def test_invalid_or_overlapping_csv_fails_closed(self):
        for text in ("nvs, data, nvs, 0x9000, broken\n", FACTORY + "bad, data, 0x99, 0x9000, 4K\n", "# empty\n"):
            with self.subTest(csv=text):
                self.environment.csv.write_text(text)
                with self.assertRaises(ValueError):
                    self.configure()


if __name__ == "__main__":
    unittest.main()
