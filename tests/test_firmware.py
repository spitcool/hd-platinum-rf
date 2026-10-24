# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Firmware loader checks using generated, fictional Intel HEX fixtures."""

import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

from hd_platinum.cli import main
from hd_platinum.firmware import FirmwareImage, MAX_HEX_BYTES


def record(address=0, data=b"", kind=0):
    raw = bytes((len(data),)) + address.to_bytes(2, "big") + bytes((kind,)) + data
    return b":" + (raw + bytes((-sum(raw) & 255,))).hex().upper().encode() + b"\n"


IMAGE = record(0, b"\x02\x01\x00") + record(0x100, b"\x22HD gateway 9.99\0") + record(kind=1)


class FirmwareTests(unittest.TestCase):
    def test_sparse_code_checksums_versions_and_reset(self):
        image = FirmwareImage.parse(IMAGE)
        self.assertEqual(image.code[:3], b"\x02\x01\x00")
        self.assertEqual(image.code[3:0x100], b"\xff" * 253)
        self.assertNotIn(3, image.mapped_addresses)
        summary = image.summary()
        self.assertEqual(summary["reset_ljmp_target"], 0x100)
        self.assertEqual(summary["embedded_version_labels"], ["HD gateway 9.99"])
        self.assertFalse(summary["execution_performed"] or summary["device_access_performed"])
        self.assertEqual(summary["mapped_bytes"], len(b"\x02\x01\x00\x22HD gateway 9.99\0"))

    def test_extended_records_and_entry_metadata(self):
        text = (record(data=b"\0\x10", kind=2) + record(0, b"\x22")
                + record(data=b"\0\0", kind=4) + record(0, b"\x02\x01\x00")
                + record(data=b"\0\0\x01\0", kind=5) + record(kind=1))
        image = FirmwareImage.parse(text)
        self.assertEqual(image.code[0x100], 0x22)
        self.assertEqual(image.summary()["entry_records"], [{"type": 5, "hex": "00000100"}])

    def test_identical_overlap_is_allowed_conflicting_overlap_is_not(self):
        repeated = record(0, b"\x02\x01\0")
        self.assertEqual(FirmwareImage.parse(repeated + IMAGE).code, FirmwareImage.parse(IMAGE).code)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            FirmwareImage.parse(record(0, b"\x22") + IMAGE)

    def test_malformed_or_unbounded_inputs_are_rejected(self):
        cases = [b"", b"x" * (MAX_HEX_BYTES + 1), b":03000000020100FF\n" + record(kind=1),
                 b":00000001F\n", b":00 000001FF\n", record(0, b"\x22"),
                 record(kind=1), IMAGE + record(0, b"\x22"),
                 record(0xffff, b"\x01\x02") + record(kind=1),
                 record(data=b"\0\1", kind=4) + record(0, b"\x22") + record(kind=1),
                 record(kind=6) + IMAGE, record(1, kind=1),
                 record(data=b"\0", kind=2) + IMAGE,
                 record(data=b"\0", kind=5) + IMAGE]
        for data in cases:
            with self.subTest(data=data[:35]), self.assertRaises(ValueError):
                FirmwareImage.parse(data)

    def test_extract_is_private_and_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "extracted"
            image = FirmwareImage.parse(IMAGE)
            image.extract(output)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual((output / "firmware.hex").read_bytes(), IMAGE)
            self.assertEqual((output / "firmware.bin").read_bytes(), image.code)
            self.assertEqual(json.loads((output / "manifest.private.json").read_text()), image.summary())
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir()))
            with self.assertRaises(FileExistsError):
                image.extract(output)

    def test_apk_selects_only_the_expected_asset_without_unpacking_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.apk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("assets/HiMemGateway.hex", IMAGE)
                archive.writestr("../../unwanted", b"never extracted")
            self.assertEqual(FirmwareImage.from_apk(path).code, FirmwareImage.parse(IMAGE).code)
            with self.assertRaises(ValueError):
                FirmwareImage.from_apk(path, "bridge")
            with self.assertRaises(ValueError):
                FirmwareImage.from_apk(path, "other")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as archive:
                    archive.writestr("assets/HiMemGateway.hex", IMAGE)
            with self.assertRaises(ValueError):
                FirmwareImage.from_apk(path)

    def test_cli_inspection_does_not_write_or_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.hex"
            path.write_bytes(IMAGE)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["firmware-inspect", "--hex", str(path)]), 0)
            self.assertFalse(json.loads(output.getvalue())["execution_performed"])
            self.assertEqual(list(Path(directory).iterdir()), [path])
            path.write_bytes(b"bad")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["firmware-inspect", "--hex", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
