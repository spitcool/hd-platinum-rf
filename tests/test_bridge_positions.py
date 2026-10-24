# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from dataclasses import replace
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from hd_platinum.bridge import (
    BridgeConfig, BridgeError, BridgeService, DryRunBackend, PositionCommand,
    ShadeConfig, load_config, make_server,
)

TOKEN = 'fictional-position-test-token-only'


def target(enabled=False, **changes):
    values = dict(name='Example shade', room_id=0, room_rf_id=b'XY', mask=8,
                  position_enabled=enabled)
    values.update(changes)
    return ShadeConfig(**values)


def configuration(enabled=False):
    return BridgeConfig(b'AB', {1: 'Example group'}, TOKEN, {0: target(enabled)})


class ShadeConfigTests(unittest.TestCase):
    def test_shades_only_configuration_exposes_no_group_commands(self):
        cfg = BridgeConfig(b'AB', {}, TOKEN, {6: target(room_id=1)})
        group_backend, position_backend = Mock(), Mock()
        service = BridgeService(cfg, group_backend, position_backend=position_backend)
        self.assertEqual(service.groups()['groups'], [])
        self.assertEqual([s['shade'] for s in service.shades()['shades']], [6])
        with self.assertRaises(BridgeError) as error:
            service.dispatch({'group': 1, 'action': 'up'})
        self.assertEqual(error.exception.code, 'invalid_group')
        with self.assertRaises(BridgeError) as error:
            service.dispatch_position({'shade': 6, 'position': 128})
        self.assertEqual(error.exception.code, 'validation_required')
        group_backend.assert_not_called()
        position_backend.assert_not_called()
        with self.assertRaises(ValueError):
            BridgeConfig(b'AB', {}, TOKEN)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(dict(remote_id='4142', groups={}, api_token=TOKEN,
                shades={'6': dict(name='Example', room_id=1, room_rf_id='5859', mask=4)})))
            self.assertEqual(dict(load_config(path).groups), {})

    def test_legacy_and_optional_private_shades_load_immutably(self):
        value = dict(remote_id='4142', groups={'1': 'Example group'}, api_token=TOKEN)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(value))
            self.assertEqual(dict(load_config(path).shades), {})
            value['shades'] = {'0': dict(name='  Example shade  ', room_id=0,
                                        room_rf_id='0x5859', mask=8)}
            path.write_text(json.dumps(value))
            loaded = load_config(path)
        self.assertEqual(loaded.shades[0].name, 'Example shade')
        self.assertEqual(loaded.shades[0].room_rf_id, b'XY')
        self.assertEqual(loaded.shades[0].feature, 4)
        self.assertFalse(loaded.shades[0].position_enabled)
        self.assertNotIn('XY', repr(loaded))
        self.assertNotIn(TOKEN, repr(loaded))
        self.assertNotIn('mask=', repr(loaded))
        with self.assertRaises(TypeError):
            loaded.shades[1] = target()

    def test_shade_fields_are_strict_and_primary_only(self):
        invalid = [dict(name=''), dict(name='x'*129), dict(room_id=True), dict(room_id=-1),
                   dict(room_id=100), dict(room_rf_id=b'x'), dict(room_rf_id=2),
                   dict(mask=True), dict(mask=0), dict(mask=3), dict(mask=256),
                   dict(feature=True), dict(feature=18), dict(position_enabled=1)]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                target(**values)
        self.assertEqual(target(mask=128).mask, 128)

    def test_room_identity_and_mask_form_unique_targets(self):
        cfg = configuration()
        with self.assertRaises(ValueError):
            replace(cfg, shades={0: target(), 1: target(name='Duplicate')})
        independent = replace(cfg, shades={0: target(), 1: target(room_id=1, room_rf_id=b'ZZ')})
        self.assertEqual(len(independent.shades), 2)
        for key in (True, -1, 100, '0'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(cfg, shades={key: target()})

    def test_json_shade_keys_and_fields_are_strict(self):
        original = dict(name='Example', room_id=0, room_rf_id='5859', mask=8)
        bad_shades = [[], {'00': original}, {'100': original}, {'true': original},
                      {'0': dict(original, extra=1)}, {'0': {'name': 'Missing'}},
                      {'0': dict(original, room_rf_id=2)}, {'0': dict(original, feature=18)}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for shades in bad_shades:
                path.write_text(json.dumps(dict(remote_id='4142', groups={'1': 'Example'},
                                                api_token=TOKEN, shades=shades)))
                with self.subTest(shades=shades), self.assertRaises(ValueError):
                    load_config(path)
            path.write_text('{"remote_id":"4142","groups":{"1":"Example"},"api_token":"'+TOKEN+
                            '","shades":{"0":{"name":"Example","room_id":0,"room_rf_id":"5859",'+
                            '"mask":8,"mask":16}}}')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                load_config(path)


class PositionServiceTests(unittest.TestCase):
    def setUp(self):
        self.groups = Mock(return_value={'status': 'sent'})
        self.positions = Mock(return_value={'status': 'submitted', 'frames_sent': 20})
        self.service = BridgeService(configuration(True), self.groups, position_backend=self.positions)

    def test_disabled_target_and_missing_backend_never_send(self):
        self.service.config = configuration(False)
        with self.assertRaises(BridgeError) as error:
            self.service.dispatch_position({'shade': 0, 'position': 128})
        self.assertEqual((error.exception.status, error.exception.code), (409, 'validation_required'))
        self.service.config = configuration(True)
        self.service.position_backend = None
        with self.assertRaises(BridgeError) as error:
            self.service.dispatch_position({'shade': 0, 'position': 128})
        self.assertEqual((error.exception.status, error.exception.code), (503, 'position_unavailable'))
        self.groups.assert_not_called()
        self.positions.assert_not_called()

    def test_typed_command_and_receipt_never_confirm_position(self):
        self.positions.return_value.update(position_confirmed=True, position=255, room_rf_id='5859', mask=8)
        for position in (0, 128, 255):
            receipt = self.service.dispatch_position({'shade': 0, 'position': position})
            command = self.positions.call_args.args[0]
            self.assertIsInstance(command, PositionCommand)
            self.assertEqual((command.shade, command.position, command.target.room_rf_id), (0, position, b'XY'))
            self.assertNotIn('XY', repr(command))
            self.assertEqual(receipt['requested_position'], position)
            self.assertEqual(receipt['delivery'], 'unverified')
            self.assertFalse(receipt['position_confirmed'])
            self.assertNotIn('position', receipt)
            self.assertNotIn('room_rf_id', receipt['backend'])
            self.assertNotIn('mask', receipt['backend'])
        self.groups.assert_not_called()

    def test_shade_listing_contains_only_public_configuration(self):
        listing = self.service.shades()
        self.assertEqual(listing['shades'], [{'shade': 0, 'name': 'Example shade', 'room_id': 0,
                                             'position_enabled': True}])
        self.assertTrue(listing['position_backend_available'])
        self.assertFalse(listing['position_confirmation_available'])
        serialized = json.dumps(listing)
        for secret in ('5859', 'room_rf_id', 'mask', TOKEN, '4142'):
            self.assertNotIn(secret, serialized)
        self.positions.assert_not_called()
        self.groups.assert_not_called()

    def test_position_inputs_rejected_without_backend_calls(self):
        values = [[], {}, {'shade': True, 'position': 0}, {'shade': 0.0, 'position': 0},
                  {'shade': 1, 'position': 0}, {'shade': 0, 'position': True},
                  {'shade': 0, 'position': 128.0}, {'shade': 0, 'position': '128'},
                  {'shade': 0, 'position': -1}, {'shade': 0, 'position': 256},
                  {'shade': 0, 'position': 0, 'feature': 18},
                  {'shade': 0, 'position': 0, 'mask': 16},
                  {'shade': 0, 'position': 0, 'request_id': ''}]
        for value in values:
            with self.subTest(value=value), self.assertRaises(BridgeError) as error:
                self.service.dispatch_position(value)
            self.assertEqual(error.exception.status, 400)
        self.positions.assert_not_called()
        self.groups.assert_not_called()

    def test_idempotency_replay_and_cross_endpoint_conflicts(self):
        group = {'group': 1, 'action': 'up', 'request_id': 'shared-group'}
        position = {'shade': 0, 'position': 128, 'request_id': 'shared-position'}
        self.service.dispatch(group)
        receipt = self.service.dispatch_position(position)
        receipt['backend']['frames_sent'] = 999
        replay = self.service.dispatch_position(position)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['backend']['frames_sent'], 20)
        self.positions.assert_called_once()
        conflicts = [lambda: self.service.dispatch_position(dict(position, request_id='shared-group')),
                     lambda: self.service.dispatch(dict(group, request_id='shared-position')),
                     lambda: self.service.dispatch_position(dict(position, position=255))]
        for action in conflicts:
            with self.assertRaises(BridgeError) as error:
                action()
            self.assertEqual((error.exception.status, error.exception.code), (409, 'idempotency_conflict'))

    def test_group_and_position_share_one_busy_lock(self):
        for position_first in (False, True):
            with self.subTest(position_first=position_first):
                entered, release = threading.Event(), threading.Event()
                results = []
                def blocking(command):
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError('test timeout')
                    return {'status': 'sent'}
                service = BridgeService(configuration(True), blocking, position_backend=blocking)
                first = lambda: service.dispatch_position({'shade': 0, 'position': 128})
                second = lambda: service.dispatch({'group': 1, 'action': 'up'})
                if not position_first:
                    first, second = second, first
                worker = threading.Thread(target=lambda: results.append(first()))
                worker.start()
                try:
                    self.assertTrue(entered.wait(1))
                    with self.assertRaises(BridgeError) as error:
                        second()
                    self.assertEqual((error.exception.status, error.exception.code), (409, 'busy'))
                finally:
                    release.set()
                    worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(results), 1)

    def test_failed_position_attempt_is_private_and_retryable(self):
        self.positions.side_effect = [RuntimeError('private identity5859 detail'), {'status': 'simulated'}]
        request = {'shade': 0, 'position': 128, 'request_id': 'retry-position'}
        with self.assertRaises(BridgeError) as error:
            self.service.dispatch_position(request)
        self.assertEqual(error.exception.status, 502)
        self.assertNotIn('5859', str(error.exception))
        self.assertEqual(self.service.dispatch_position(request)['status'], 'simulated')
        self.assertEqual(self.positions.call_count, 2)


class PositionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.positions = Mock(return_value={'status': 'submitted'})
        self.service = BridgeService(configuration(False), DryRunBackend(), position_backend=self.positions)
        self.server = make_server(self.service, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, method, path, value=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            body = raw if raw is not None else (json.dumps(value) if value is not None else None)
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    def auth(self, **extra):
        return {'Authorization': 'Bearer '+TOKEN, 'Content-Type': 'application/json', **extra}

    def test_public_shades_and_post_only_positions(self):
        status, body = self.request('GET', '/api/shades')
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['shades'][0]['position_enabled'])
        for secret in ('5859', '4142', TOKEN, 'mask', 'room_rf_id'):
            self.assertNotIn(secret, body)
        self.assertEqual(self.request('GET', '/api/positions?shade=0&position=128')[0], 405)
        status, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('Requested primary position:', html)
        self.assertIn('Set requested position', html)
        self.assertIn('Position control awaits validation.', html)
        self.positions.assert_not_called()

    def test_disabled_target_rejects_then_enabled_target_uses_position_backend(self):
        value = {'shade': 0, 'position': 128, 'request_id': 'http-position'}
        status, body = self.request('POST', '/api/positions', value, self.auth())
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)['error']['code'], 'validation_required')
        self.positions.assert_not_called()
        self.service.config = configuration(True)
        status, body = self.request('POST', '/api/positions', value, self.auth())
        self.assertEqual(status, 202)
        result = json.loads(body)
        self.assertEqual(result['requested_position'], 128)
        self.assertFalse(result['position_confirmed'])
        self.assertEqual(self.request('POST', '/api/positions', value, self.auth())[0], 202)
        self.positions.assert_called_once()

    def test_position_endpoint_preserves_auth_origin_host_and_body_validation(self):
        value = {'shade': 0, 'position': 128}
        for headers, expected in [({'Content-Type': 'application/json'}, 401),
                                  (self.auth(Origin='http://other.example'), 403),
                                  (self.auth(Host=f'other.example:{self.server.server_port}'), 400)]:
            self.assertEqual(self.request('POST', '/api/positions', value, headers)[0], expected)
        for raw in ('{"shade":0,"shade":1,"position":128}', '{"shade":0,"position":true}',
                    '{"shade":0,"position":128,"room_rf_id":"ffff"}'):
            self.assertEqual(self.request('POST', '/api/positions', headers=self.auth(), raw=raw)[0], 400)
        self.positions.assert_not_called()


if __name__ == '__main__':
    unittest.main()
