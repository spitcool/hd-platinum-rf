# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Opt-in bounded private TCP wire journal for client compatibility research.

Records contain raw bytes and may expose household identity. Callers must catch
journal errors independently of command results: a logging failure must never
turn an already submitted RF command into a reason to retry it.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import threading


class WireJournal:
    """Append JSONL records, retaining at most ``backups + 1`` bounded files.

    The current file, numbered backups, and a separate process lock are mode
    0600. File opens refuse symlinks, nonregular files, and hard links. Parent
    directory aliases are resolved once; operations use a pinned directory
    descriptor. The journal owns no long-lived descriptor and needs no close().
    Oversized records raise ValueError without writing a partial record.
    """

    def __init__(self, path, max_bytes=1048576, backups=1):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if type(backups) is not int or not 0 <= backups <= 32:
            raise ValueError("backups must be an integer within 0..32")
        requested = Path(path)
        if not requested.name or requested.name in (".", ".."):
            raise ValueError("journal path must name a file")
        requested.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = requested.parent.resolve() / requested.name
        self.max_bytes, self.backups = max_bytes, backups
        self._lock = threading.Lock()
        # Fail startup on an unsafe existing destination, before serving clients.
        with self._locked_directory() as directory:
            self._check_files(directory)
            descriptor = self._open_file(directory, self.path.name, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            os.close(descriptor)

    def _open_file(self, directory, name, flags):
        descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("journal files must be regular files with one link")
            os.fchmod(descriptor, 0o600)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _locked_directory(self):
        with self._lock:
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            lock = None
            try:
                lock = self._open_file(directory, self.path.name + ".lock", os.O_RDWR | os.O_CREAT)
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield directory
            finally:
                if lock is not None:
                    os.close(lock)
                os.close(directory)

    def _check_files(self, directory):
        for suffix in ("", *(f".{number}" for number in range(1, self.backups + 1))):
            try:
                descriptor = self._open_file(directory, self.path.name + suffix, os.O_RDONLY)
            except FileNotFoundError:
                continue
            try:
                if os.fstat(descriptor).st_size > self.max_bytes:
                    raise ValueError("existing journal exceeds max_bytes")
            finally:
                os.close(descriptor)

    def _rotate(self, directory):
        if self.backups:
            for number in range(self.backups, 1, -1):
                try:
                    os.replace(f"{self.path.name}.{number - 1}", f"{self.path.name}.{number}",
                               src_dir_fd=directory, dst_dir_fd=directory)
                except FileNotFoundError:
                    pass
            os.replace(self.path.name, self.path.name + ".1",
                       src_dir_fd=directory, dst_dir_fd=directory)
        else:
            os.unlink(self.path.name, dir_fd=directory)
        os.fsync(directory)

    def __call__(self, direction, peer, connection_id, data):
        if direction not in ("send", "receive"):
            raise ValueError("journal direction must be send or receive")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("journal data must be bytes-like")
        # Avoid allocating an unbounded hex string before the complete limit check.
        if len(data) * 2 > self.max_bytes:
            raise ValueError("journal record exceeds max_bytes")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "direction": direction,
            "peer": peer,
            "connection_id": connection_id,
            "hex": bytes(data).hex(),
        }
        encoded = (json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        if len(encoded) > self.max_bytes:
            raise ValueError("journal record exceeds max_bytes")
        with self._locked_directory() as directory:
            self._check_files(directory)
            descriptor = self._open_file(directory, self.path.name, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            try:
                if os.fstat(descriptor).st_size + len(encoded) > self.max_bytes:
                    os.close(descriptor)
                    descriptor = None
                    self._rotate(directory)
                    descriptor = self._open_file(directory, self.path.name, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
                pending = memoryview(encoded)
                while pending:
                    written = os.write(descriptor, pending)
                    if written <= 0:
                        raise OSError("journal write made no progress")
                    pending = pending[written:]
                os.fsync(descriptor)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
