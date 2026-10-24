# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Private wire journal checks using only fictional loopback data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from hd_platinum.lan_trace import WireJournal


class WireJournalTests(unittest.TestCase):
    def test_raw_bytes_fields_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "wire.jsonl"
            journal = WireJournal(path)
            journal("receive", ("127.0.0.1", 1234), 8, b"$unknown\x00\xff")
            row = json.loads(path.read_text())
            self.assertEqual(row["hex"], b"$unknown\x00\xff".hex())
            self.assertEqual(row["direction"], "receive")
            self.assertEqual(row["peer"], ["127.0.0.1", 1234])
            self.assertEqual(row["connection_id"], 8)
            self.assertIsNotNone(datetime.fromisoformat(row["timestamp"]).tzinfo)
            for name in (path, Path(str(path) + ".lock")):
                self.assertEqual(stat.S_IMODE(name.stat().st_mode), 0o600)

    def test_rotation_preserves_order_with_bounded_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.jsonl"
            journal = WireJournal(path, max_bytes=256, backups=2)
            for number in range(5):
                journal("send", ("127.0.0.1", 1234), number, bytes([number]) * 30)
            rows = []
            for name in (Path(str(path) + ".2"), Path(str(path) + ".1"), path):
                self.assertLessEqual(name.stat().st_size, 256)
                self.assertEqual(stat.S_IMODE(name.stat().st_mode), 0o600)
                rows.extend(json.loads(line) for line in name.read_text().splitlines())
            self.assertEqual([row["connection_id"] for row in rows], [2, 3, 4])
            self.assertFalse(Path(str(path) + ".3").exists())

    def test_zero_backups_and_oversized_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.jsonl"
            journal = WireJournal(path, max_bytes=256, backups=0)
            for number in range(3):
                journal("send", ("127.0.0.1", 1234), number, b"x" * 30)
            previous = path.read_bytes()
            with self.assertRaises(ValueError):
                journal("receive", ("127.0.0.1", 1234), 4, b"x" * 256)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(json.loads(previous)["connection_id"], 2)
            self.assertFalse(Path(str(path) + ".1").exists())

    def test_refuses_symlink_journal_backup_and_lock(self):
        for suffix in ("", ".1", ".lock"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "wire.jsonl"
                other = Path(temporary) / "other"
                other.write_bytes(b"untouched")
                Path(str(path) + suffix).symlink_to(other)
                with self.assertRaises((OSError, ValueError)):
                    WireJournal(path)
                self.assertEqual(other.read_bytes(), b"untouched")

    def test_refuses_hard_link_and_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.jsonl"
            other = Path(temporary) / "other"
            other.write_bytes(b"untouched")
            os.link(other, path)
            with self.assertRaises(ValueError):
                WireJournal(path)
            self.assertEqual(other.read_bytes(), b"untouched")
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(ValueError):
                WireJournal(path)

    def test_two_instances_serialize_concurrent_writers(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wire.jsonl"
            journals = [WireJournal(path), WireJournal(path)]

            def append(number):
                journals[number % 2]("receive", ("127.0.0.1", 1234), number, b"$dat")

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(append, range(40)))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(sorted(row["connection_id"] for row in rows), list(range(40)))


if __name__ == "__main__":
    unittest.main()
