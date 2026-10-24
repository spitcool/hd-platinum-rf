# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import json
import math
import socket
import unittest
from unittest.mock import patch

from hd_platinum.lan import BridgeRecord, ProtocolError, parse_records
from hd_platinum.lan_control import (
    BridgeCommandError,
    ControlTimeout,
    MAX_CONTROL_RECORDS,
    PositionTransaction,
    TransactionStateError,
    encode_position,
)


def inventory(*, definition=True, complete=True):
    records = [b"107 HunterDouglas Shade Controller", b"107 $upd00-"]
    if definition:
        records.extend((b"107 $cs00-00-01-Synthetic shade A", b"107 $cs03-00-01-Synthetic shade B"))
    records.append(b"107 $cp03-04-128-")
    if complete:
        records.append(b"107 $upd01-")
    return parse_records(BridgeRecord.from_raw(record) for record in records)


class FakeSocket:
    def __init__(self, chunks, *, send_failure=None):
        self.chunks = iter(chunks)
        self.sent = []
        self.seen_before_reads = []
        self.timeouts = []
        self.closed = False
        self.send_failure = send_failure

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self, _size):
        self.seen_before_reads.append(tuple(self.sent))
        chunk = next(self.chunks, b"")
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def sendall(self, data):
        self.sent.append(data)
        if self.send_failure is not None and len(self.sent) == self.send_failure:
            raise socket.timeout("synthetic partial write")

    def close(self):
        self.closed = True


class PositionEncodingTests(unittest.TestCase):
    def test_only_one_inventory_shade_and_feature04_are_encoded(self):
        self.assertEqual(encode_position(inventory(), 3, 0), b"$pss03-04-000-")
        self.assertEqual(encode_position(inventory(), 3, 128), b"$pss03-04-128-")
        self.assertEqual(encode_position(inventory(), 0, 255), b"$pss00-04-255-")
        for snapshot, shade_id, position in (
            (inventory(), 1, 255), (inventory(), True, 255), (inventory(), 3.0, 255),
            (inventory(), 3, True), (inventory(), 3, 1.5), (inventory(), 3, -1),
            (inventory(), 3, 256), (inventory(complete=False), 3, 128),
            (inventory(definition=False), 3, 128),
        ):
            with self.subTest(shade_id=shade_id, position=position), self.assertRaises(ValueError):
                encode_position(snapshot, shade_id, position)

    def test_invalid_endpoint_and_deadline_fail_before_connect(self):
        base = dict(host="192.0.2.1", inventory=inventory(), shade_id=3, position=255)
        bad_values = [
            {"host": ""}, {"host": "192.0.2.1\n"}, {"port": 0}, {"port": 65536},
            {"port": True}, {"timeout": 0}, {"timeout": 31}, {"timeout": True},
            {"timeout": float("nan")}, {"timeout": float("inf")}, {"timeout": "invalid"},
        ]
        with patch("hd_platinum.lan_control.socket.create_connection") as connect:
            for changes in bad_values:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    PositionTransaction(**dict(base, **changes))
            connect.assert_not_called()


class PositionTransactionTests(unittest.TestCase):
    def transaction(self, **kwargs):
        options = dict(inventory=inventory(), shade_id=3, position=255, timeout=.5)
        options.update(kwargs)
        return PositionTransaction("192.0.2.1", **options)

    def test_fragmented_banner_done_and_coalesced_action_records(self):
        fake = FakeSocket([
            b"107 HunterDouglas Shade ", b"Controller\n", b"\r2018-HD gateway 2.18a\n\r",
            b"107 $cp03-04-128-\n\r107 $do",
            b"ne\n\r107 $act02-00-private-intermediate\n\r",
            b"107 $act01-00-\n\r107 $cp03-04-255-\n\r107 $act00-00-\n\r107 $ack\n\r",
        ])
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake) as connect:
            with self.transaction() as tx:
                self.assertEqual(fake.sent, [])
                staged = tx.stage()
                self.assertEqual(fake.sent, [b"$pss03-04-255-"])
                self.assertTrue(staged["stage_acknowledged"])
                self.assertFalse(staged["release_sent"])
                result = tx.trigger()
                self.assertTrue(result["action_end_observed"])
                self.assertEqual(result["state"], "completed")
                self.assertEqual([e.position for e in tx.events if e.position is not None], [128, 255])
                self.assertEqual([e.action_phase for e in tx.events if e.action_phase is not None], [2, 1, 0])
                self.assertEqual(tx.events[-1].record.payload, b"$ack")
                self.assertNotIn("private-intermediate", json.dumps(result))
                self.assertEqual(tx.events[4].as_dict(include_raw=True)["payload_hex"],
                                 b"$act02-00-private-intermediate".hex())
                self.assertEqual(result["delivery"], "unverified")
                self.assertFalse(result["position_confirmed"])
            connect.assert_called_once_with(("192.0.2.1", 522), timeout=.5)
        self.assertTrue(fake.closed)
        self.assertEqual(fake.sent, [b"$pss03-04-255-", b"$rls"])
        self.assertEqual(fake.seen_before_reads[:3], [(), (), ()])
        self.assertTrue(all(0 < value <= .5 for value in fake.timeouts))

    def test_partial_old_completion_cannot_complete_trigger(self):
        fake = FakeSocket([
            b"1 HunterDouglas Shade Controller\n\r",
            b"1 $done\n\r1 $act00-",
            b"00-\n\r1 $act01-00-\n\r",
            b"1 $act00-00-\n\r",
        ])
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
            with self.transaction() as tx:
                tx.stage()
                result = tx.trigger()
                actions = [e for e in tx.events if e.kind == "action"]
                self.assertEqual([e.preexisting_partial for e in actions], [True, False, False])
                self.assertTrue(result["action_end_observed"])
        self.assertEqual(len(fake.seen_before_reads), 4)

    def test_complete_old_action_event_is_not_reused_after_release(self):
        fake = FakeSocket([
            b"1 HunterDouglas Shade Controller\n\r",
            b"1 $done\n\r1 $act00-00-\n\r",
            b"1 $act01-00-\n\r", b"",
        ])
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
            with self.transaction() as tx:
                tx.stage()
                with self.assertRaises(ProtocolError):
                    tx.trigger()
                self.assertTrue(tx.receipt()["release_sent"])
                self.assertFalse(tx.receipt()["action_end_observed"])
                self.assertEqual(tx.state, "failed")
        self.assertTrue(fake.closed)

    def test_stage_timeout_error_and_wrong_done_never_release(self):
        cases = (
            ([socket.timeout("waiting")], ControlTimeout),
            ([b"$done\n\r$error07-\n\r"], BridgeCommandError),
            ([b"$done-extra\n\r", b""], ProtocolError),
            ([b"$do", b""], ProtocolError),
        )
        for chunks, error in cases:
            with self.subTest(chunks=chunks):
                fake = FakeSocket([b"HunterDouglas Shade Controller\n\r", *chunks])
                with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
                    with self.transaction() as tx:
                        with self.assertRaises(error) as raised:
                            tx.stage()
                        if error is BridgeCommandError:
                            self.assertEqual(raised.exception.code, 7)
                        with self.assertRaises(TransactionStateError):
                            tx.trigger()
                self.assertEqual(fake.sent, [b"$pss03-04-255-"])
                self.assertTrue(fake.closed)

    def test_staging_can_be_closed_without_releasing_or_repeated(self):
        fake = FakeSocket([b"HunterDouglas Shade Controller\n\r", b"$done\n\r"])
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
            tx = self.transaction()
            with self.assertRaises(TransactionStateError):
                tx.trigger()
            with tx:
                with self.assertRaises(TransactionStateError):
                    tx.trigger()
                tx.stage()
                with self.assertRaises(TransactionStateError):
                    tx.stage()
            with self.assertRaises(TransactionStateError):
                tx.trigger()
            with self.assertRaises(TransactionStateError):
                tx.__enter__()
        self.assertEqual(fake.sent, [b"$pss03-04-255-"])

    def test_trigger_is_single_use_even_after_completion(self):
        fake = FakeSocket([b"HunterDouglas Shade Controller\n\r", b"$done\n\r", b"$act00-00-\n\r"])
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
            with self.transaction() as tx:
                tx.stage()
                tx.trigger()
                with self.assertRaises(TransactionStateError):
                    tx.trigger()
        self.assertEqual(fake.sent, [b"$pss03-04-255-", b"$rls"])

    def test_write_timeout_is_not_retried(self):
        for failure in (1, 2):
            fake = FakeSocket([b"HunterDouglas Shade Controller\n\r", b"$done\n\r"], send_failure=failure)
            with self.subTest(failure=failure), patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
                with self.transaction() as tx:
                    if failure == 1:
                        with self.assertRaises(ControlTimeout):
                            tx.stage()
                    else:
                        tx.stage()
                        with self.assertRaises(ControlTimeout):
                            tx.trigger()
                    self.assertEqual(tx.state, "failed")
                    self.assertEqual(len(fake.sent), failure)
                    self.assertTrue(tx.receipt()["stage_attempted"])
                    self.assertEqual(tx.receipt()["release_attempted"], failure == 2)
                    self.assertFalse(tx.receipt()["release_sent"])
                    self.assertFalse(tx.receipt()["position_confirmed"])

    def test_continuous_intermediate_data_does_not_reset_deadline(self):
        fake = FakeSocket([b"HunterDouglas Shade Controller\n\r"] + [b"$ack\n\r"] * 100)
        now = [0.]
        def clock():
            now[0] += .003
            return now[0]
        with patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
            with patch("hd_platinum.lan_control.time.monotonic", side_effect=clock):
                with self.transaction(timeout=.01) as tx:
                    with self.assertRaises(ControlTimeout):
                        tx.stage()
        self.assertLess(len(fake.seen_before_reads), 10)
        self.assertTrue(all(math.isfinite(value) and value > 0 for value in fake.timeouts))

    def test_invalid_banner_and_response_limits_close_connection(self):
        cases = [
            [b"unexpected service\n\r"],
            [b"HunterDouglas Shade Controller\n\r"] + [b"A" * 4096] * 20,
            [b"HunterDouglas Shade Controller\n\r", b"$ack\n\r" * MAX_CONTROL_RECORDS],
        ]
        for chunks in cases:
            fake = FakeSocket(chunks)
            with self.subTest(chunks=len(chunks)), patch("hd_platinum.lan_control.socket.create_connection", return_value=fake):
                with self.assertRaises(ProtocolError):
                    with self.transaction() as tx:
                        tx.stage()
            self.assertTrue(fake.closed)
            self.assertNotIn(b"$rls", fake.sent)


if __name__ == "__main__":
    unittest.main()
