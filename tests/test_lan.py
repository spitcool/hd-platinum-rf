# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest
from unittest.mock import patch

from hd_platinum.lan import (
    BridgeRecord,
    RecordFramer,
    parse_records,
    query_inventory,
)


class RecordFramerTests(unittest.TestCase):
    def test_fragmented_lf_cr_records_and_optional_prefix(self) -> None:
        framer = RecordFramer()
        self.assertEqual(framer.feed(b"12 $cr00-01-0x"), [])
        records = framer.feed(b"1A2B-Lab\n\r2018-HD gateway 2.18a\n\rpartial")

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].connection_id, 12)
        self.assertEqual(records[0].payload, b"$cr00-01-0x1A2B-Lab")
        self.assertIsNone(records[1].connection_id)
        self.assertEqual(records[1].kind, "firmware_text")
        self.assertEqual(framer.pending, b"partial")

    def test_prefix_is_not_assumed_to_be_one_digit(self) -> None:
        record = BridgeRecord.from_raw(b"107 $upd01-")
        self.assertEqual(record.connection_id, 107)
        self.assertEqual(record.payload, b"$upd01-")

    def test_nul_padded_actions_preserve_raw_bytes_and_optional_prefix(self) -> None:
        for prefix, connection_id in ((b"", None), (b"107 ", 107)):
            for payload in (b"$act00-00-", b"$act01-00-", b"$act02-03-"):
                with self.subTest(prefix=prefix, payload=payload):
                    raw = b"\x00" * 30 + prefix + payload
                    framer = RecordFramer()
                    self.assertEqual(framer.feed(raw[:17]), [])
                    self.assertEqual(framer.feed(raw[17:] + b"\n"), [])
                    record, = framer.feed(b"\r")
                    self.assertEqual(record.raw, raw)
                    self.assertEqual(record.payload, payload)
                    self.assertEqual(record.connection_id, connection_id)
                    self.assertEqual(record.kind, "action")

    def test_padding_normalization_leaves_opaque_or_malformed_records_unchanged(self) -> None:
        for raw in (
            b"\x00\x00binary\xff",
            b"\x00\x00107 $ct\xff\x00title$",
            b"\x00\x00107 $done",
            b"\x00\x00107 $act00-00-extra",
            b"\x00\x00107 $act00-00-\x00",
            b"\x00\x00107 $act0-00-",
            b"\x00\x00107 $act02-3-",
            b"\x00\x00107 $act03-00-",
            b"\x00\x00x107 $act00-00-",
        ):
            with self.subTest(raw=raw):
                record = BridgeRecord.from_raw(raw)
                self.assertEqual(record.raw, raw)
                self.assertEqual(record.payload, raw)
                self.assertIsNone(record.connection_id)
                self.assertEqual(record.kind, "unknown")

        raw = b"107 $ct\xff\x00title$"
        record = BridgeRecord.from_raw(raw)
        self.assertEqual(record.raw, raw)
        self.assertEqual(record.payload, b"$ct\xff\x00title$")


class InventoryParserTests(unittest.TestCase):
    def test_sanitized_live_shape_is_binary_safe(self) -> None:
        raw_records = (
            b"5 HunterDouglas Shade Controller",
            b"5 $firm03-2018-HD gateway 2.18a",
            b"5 $MAC0x02AABBCCDDEE-",
            b"5 $LEDl064-",
            b"5 $upd00-",
            b"5 $reset",
            b"5 $set006-",
            b"5 $ct\xff\x00private$",
            b"5 $cr00-02-0x1A2B-Room-With-Hyphens",
            b"5 $cs00-00-01-Shade-With-Hyphens",
            b"5 $cp00-04-128-",
            b"5 $upd01-",
        )
        inventory = parse_records(BridgeRecord.from_raw(item) for item in raw_records)

        self.assertTrue(inventory.update_started)
        self.assertTrue(inventory.update_complete)
        self.assertEqual(inventory.firmware, "2018-HD gateway 2.18a")
        self.assertEqual(inventory.firmware_record_code, 3)
        self.assertEqual(inventory.mac, "02AABBCCDDEE")
        self.assertEqual(inventory.led_level, 64)
        self.assertEqual(inventory.title_raw, b"\xff\x00private$")
        self.assertEqual(inventory.rooms[0].name, "Room-With-Hyphens")
        self.assertEqual(inventory.shades[0].name, "Shade-With-Hyphens")
        self.assertEqual(inventory.shades[0].positions, {4: 128})
        self.assertEqual(len(inventory.unknown_records), 1)

        redacted = inventory.public_summary()
        self.assertEqual(redacted["mac"], "<redacted>")
        self.assertNotIn("name", redacted["rooms"][0])
        self.assertEqual(redacted["rooms"][0]["rf_identifier"], "<redacted>")

        private = inventory.public_summary(include_names=True, include_mac=True)
        self.assertEqual(private["mac"], "02AABBCCDDEE")
        self.assertEqual(private["rooms"][0]["name"], "Room-With-Hyphens")


class ReadOnlyClientTests(unittest.TestCase):
    def test_query_waits_for_banner_and_sends_only_bare_dat(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.chunks = iter(
                    (
                        b"4 HunterDouglas Shade ",
                        b"Controller\n\r2018-HD gateway 2.18a\n\r",
                        b"4 $upd00-\n\r",
                        b"4 $cr00-01-0x1A2B-Test Room\n\r",
                        b"4 $cs00-00-01-Test Shade\n\r4 $cp00-04-255-\n\r",
                        b"4 $upd01-\n\r",
                    )
                )
                self.sent: list[bytes] = []

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def recv(self, size: int) -> bytes:
                return next(self.chunks, b"")

            def sendall(self, data: bytes) -> None:
                self.sent.append(data)

        fake_socket = FakeSocket()
        with patch("hd_platinum.lan.socket.create_connection", return_value=fake_socket):
            inventory = query_inventory("192.0.2.1", port=522, timeout=2.0)

        self.assertEqual(fake_socket.sent, [b"$dat"])
        self.assertTrue(inventory.update_complete)
        self.assertEqual(inventory.firmware, "2018-HD gateway 2.18a")
        self.assertEqual(inventory.shades[0].positions[4], 255)


if __name__ == "__main__":
    unittest.main()
