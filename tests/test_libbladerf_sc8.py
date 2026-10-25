# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Offline tool safeguards; optional supplied-source C regression, no devices."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "tools/libbladerf_sc8/check.py"
spec = importlib.util.spec_from_file_location("libbladerf_sc8_check", TOOL)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Sc8ToolTests(unittest.TestCase):
    def test_wrong_upstream_source_refused_before_outputs_or_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source_file = source / check.SOURCE
            source_file.parent.mkdir(parents=True)
            source_file.write_bytes(b"not the pinned upstream source\n")
            output = root / "output"
            with patch.object(check.subprocess, "run") as process:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    check.run(source, output)
                process.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(source_file.read_bytes(), b"not the pinned upstream source\n")

    def test_each_header_is_hash_checked(self):
        # Small independently generated inputs test the all-input guard without
        # distributing upstream files or relaxing the real tool's pinned hashes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = {name: ("fixture " + name).encode() for name in check.INPUT_HASHES}
            hashes = {name: check.digest(data) for name, data in content.items()}
            for name, data in content.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            with patch.object(check, "INPUT_HASHES", hashes):
                self.assertEqual(check.read_inputs(root), content)
                for name, original in content.items():
                    (root / name).write_bytes(original + b"changed")
                    with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                        check.read_inputs(root)
                    (root / name).write_bytes(original)

    def test_output_cannot_modify_supplied_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for output in (root, root / "generated"):
                with patch.object(check, "read_inputs") as read:
                    with self.assertRaisesRegex(ValueError, "outside"):
                        check.run(root, output)
                    read.assert_not_called()

    def test_patch_refuses_missing_or_ambiguous_anchors(self):
        fictional = check.START + "\n" + check.END
        self.assertEqual(
            check.patched_source(fictional), check.START_FIXED + "\n" + check.END_FIXED,
        )
        self.assertEqual(
            check.patched_source(fictional, end_condition=False),
            check.START_FIXED + "\n" + check.END,
        )
        for source in (check.START, check.END, fictional + "\n" + check.START):
            with self.assertRaisesRegex(ValueError, "anchors"):
                check.patched_source(source)

    def test_published_diff_changes_only_two_conditions_and_keeps_license(self):
        text = (TOOL.parent / "sc8-metadata.patch").read_text()
        additions = [line[1:].strip() for line in text.splitlines()
                     if line.startswith("+") and not line.startswith("+++")]
        removals = [line[1:].strip() for line in text.splitlines()
                    if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(additions, [check.START_FIXED, check.END_FIXED])
        self.assertEqual(removals, [check.START, check.END])
        self.assertIn("SPDX-License-Identifier: LGPL-2.1-or-later", text)
        self.assertIn("Nuand LLC", text)
        self.assertEqual(
            check.digest((TOOL.parent / "LICENSE").read_bytes()),
            "592987e8510228d546540b84a22444bde98e48d03078d3b2eefcd889bec5ce8c",
        )

    @unittest.skipUnless(os.environ.get("LIBBLADERF_SC8_SOURCE"),
                         "Set LIBBLADERF_SC8_SOURCE for the actual-source offline C matrix")
    def test_actual_pinned_upstream_source(self):
        source = Path(os.environ["LIBBLADERF_SC8_SOURCE"])
        flags = json.loads(os.environ.get("LIBBLADERF_SC8_CFLAGS", "[]"))
        self.assertIsInstance(flags, list)
        self.assertTrue(all(isinstance(value, str) for value in flags))
        before = check.read_inputs(source)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "regression"
            report = check.run(
                source, output, cc=os.environ.get("CC", "cc"), cflags=flags,
                sanitize=os.environ.get("LIBBLADERF_SC8_SANITIZE") == "1",
            )
            self.assertTrue(report["passed"])
            self.assertEqual(report["SC16_byte_identical"]["bytes_per_variant"], 13369344)
            self.assertEqual(report["results"]["two_conditions"]["SC8_second_pass"], 21)
            self.assertEqual(report["results"]["unmodified"]["SC8_first_pass"], 0)
            self.assertEqual(check.read_inputs(source), before)
            # A rerun must not overwrite the first run's evidence.
            report_bytes = (output / "report.json").read_bytes()
            with self.assertRaises(FileExistsError):
                check.run(source, output)
            self.assertEqual((output / "report.json").read_bytes(), report_bytes)


if __name__ == "__main__":
    unittest.main()
