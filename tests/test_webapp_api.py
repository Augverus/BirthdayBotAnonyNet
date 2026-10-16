"""Tests for the authenticated Mini App API handlers."""
import hashlib
import hmac
import json
import time
import unittest
import urllib.parse
from unittest.mock import patch

from aiohttp import web

import config
import store
import webapp_api
from tests.support import AsyncBotTestCase, user


def init_data(uid=7, token=None, age=0):
    """Build a correctly signed ``WebAppInitData`` query string."""
    values = {
        'auth_date': str(int(time.time()) - age),
        'query_id': 'AAExample',
        'user': json.dumps({'id': uid, 'first_name': 'Ali', 'username': 'ali'},
                           separators=(',', ':')),
    }
    check_string = '\n'.join(f'{key}={values[key]}' for key in sorted(values))
    secret = hmac.new(b'WebAppData', (token or config.BOT_TOKEN).encode(), hashlib.sha256)
    values['hash'] = hmac.new(secret.digest(), check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


class FakeRequest:
    def __init__(self, init=None, method='GET', payload=None, match_info=None, origin=None):
        headers = {}
        if init is not None:
            headers['Authorization'] = f'tma {init}'
        if origin is not None:
            headers['Origin'] = origin
        self.headers = headers
        self.method = method
        self.match_info = match_info or {}
        self._payload = payload

    async def json(self):
        if self._payload is None:
            raise ValueError('no request body')
        return self._payload


async def payload_of(response):
    return json.loads(response.body.decode())


class MiniAppApiTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        store.track_user(user(7, 'Ali', username='ali'), 'k', 'message')

    def request(self, **kwargs):
        kwargs.setdefault('init', init_data())
        return FakeRequest(**kwargs)

    def reset_limits(self):
        """The handlers intentionally cooldown per user; bypass it between calls."""
        with store.connection() as c:
            c.execute('DELETE FROM bot_rate_limits')

    # --- authentication ----------------------------------------------------
    async def test_requests_without_init_data_are_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            await webapp_api.dashboard(FakeRequest())

    async def test_tampered_hash_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            await webapp_api.dashboard(FakeRequest(init=init_data(token='999:other-token')))

    async def test_stale_auth_date_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            await webapp_api.dashboard(FakeRequest(init=init_data(age=25 * 60 * 60)))

    async def test_future_auth_date_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            await webapp_api.dashboard(FakeRequest(init=init_data(age=-120)))

    # --- dashboard ---------------------------------------------------------
    async def test_dashboard_returns_profile_birthday_and_friends(self):
        store.update_user(7, month=5, day=10, notification=0)
        store.add_friend_birthday(7, 'Sara', 2, 3, True)
        response = await webapp_api.dashboard(self.request())
        data = await payload_of(response)
        self.assertEqual(data['profile']['id'], 7)
        self.assertEqual(data['profile']['username'], 'ali')
        self.assertEqual((data['birthday']['month'], data['birthday']['day']), (5, 10))
        self.assertFalse(data['birthday']['notification'])
        self.assertEqual([f['name'] for f in data['friends']], ['Sara'])

    async def test_dashboard_without_birthday_returns_none(self):
        response = await webapp_api.dashboard(self.request())
        data = await payload_of(response)
        self.assertIsNone(data['birthday'])

    # --- own birthday ------------------------------------------------------
    async def test_set_birthday_stores_date_and_notification(self):
        response = await webapp_api.set_birthday(self.request(
            method='POST', payload={'month': 12, 'day': 29, 'notification': False}))
        data = await payload_of(response)
        self.assertEqual((data['birthday']['month'], data['birthday']['day']), (12, 29))
        self.assertFalse(data['birthday']['notification'])
        saved = store.user(7)
        self.assertEqual((saved['month'], saved['day'], saved['notification']), (12, 29, 0))

    async def test_set_birthday_keeps_notification_when_omitted(self):
        store.update_user(7, notification=0)
        response = await webapp_api.set_birthday(self.request(
            method='POST', payload={'month': 1, 'day': 1}))
        data = await payload_of(response)
        self.assertFalse(data['birthday']['notification'])
        self.assertEqual(store.user(7)['notification'], 0)

    async def test_set_birthday_validates_input(self):
        for payload in ({'month': 13, 'day': 1}, {'month': True, 'day': 1},
                        {'month': '5', 'day': 2}, {'day': 2}, {}):
            self.reset_limits()
            response = await webapp_api.set_birthday(self.request(method='POST', payload=payload))
            self.assertEqual(response.status, 400, payload)
        self.assertIsNone(store.user(7)['month'])

    async def test_set_birthday_requires_started_user(self):
        response = await webapp_api.set_birthday(FakeRequest(
            init=init_data(uid=8), method='POST', payload={'month': 1, 'day': 1}))
        self.assertEqual(response.status, 404)

    async def test_set_birthday_is_rate_limited(self):
        payload = {'month': 1, 'day': 1}
        first = await webapp_api.set_birthday(self.request(method='POST', payload=payload))
        second = await webapp_api.set_birthday(self.request(method='POST', payload=payload))
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)

    # --- friends -----------------------------------------------------------
    async def test_add_friend_returns_created_record(self):
        response = await webapp_api.add_friend(self.request(method='POST', payload={
            'name': '  Sara  ', 'month': 4, 'day': 16, 'notification': True}))
        self.assertEqual(response.status, 201)
        data = await payload_of(response)
        self.assertEqual(data['friend']['name'], 'Sara')
        self.assertEqual(store.friend_birthdays(7)[0]['name'], 'Sara')

    async def test_add_friend_rejects_bad_payload(self):
        for payload in ({'name': '', 'month': 1, 'day': 1},
                        {'name': 'x', 'month': 1, 'day': 32},
                        {'name': 'x', 'month': 1, 'day': 1, 'notification': 'yes'}):
            self.reset_limits()
            response = await webapp_api.add_friend(self.request(method='POST', payload=payload))
            self.assertEqual(response.status, 400, payload)

    async def test_update_friend_toggles_notification(self):
        fid = store.add_friend_birthday(7, 'Sara', 2, 3, True)
        response = await webapp_api.update_friend(self.request(
            method='PATCH', match_info={'friend_id': str(fid)}, payload={'notification': False}))
        data = await payload_of(response)
        self.assertFalse(data['friend']['notification'])
        self.assertEqual(store.friend_birthday(7, fid)['notification'], 0)

    async def test_update_friend_rejects_bad_input_and_unknown_ids(self):
        fid = store.add_friend_birthday(7, 'Sara', 2, 3, True)
        bad_payload = await webapp_api.update_friend(self.request(
            method='PATCH', match_info={'friend_id': str(fid)}, payload={'notification': 'yes'}))
        self.assertEqual(bad_payload.status, 400)
        self.reset_limits()
        bad_id = await webapp_api.update_friend(self.request(
            method='PATCH', match_info={'friend_id': 'abc'}, payload={'notification': True}))
        self.assertEqual(bad_id.status, 400)
        self.reset_limits()
        missing = await webapp_api.update_friend(self.request(
            method='PATCH', match_info={'friend_id': '999'}, payload={'notification': True}))
        self.assertEqual(missing.status, 404)

    async def test_update_friend_only_touches_own_records(self):
        store.track_user(user(8, 'Other'), 'k2', 'message')
        fid = store.add_friend_birthday(8, 'NotMine', 2, 3, True)
        response = await webapp_api.update_friend(self.request(
            method='PATCH', match_info={'friend_id': str(fid)}, payload={'notification': False}))
        self.assertEqual(response.status, 404)
        self.assertEqual(store.friend_birthday(8, fid)['notification'], 1)

    async def test_delete_friend_is_scoped_to_owner(self):
        store.track_user(user(8, 'Other'), 'k2', 'message')
        other = store.add_friend_birthday(8, 'NotMine', 2, 3, True)
        response = await webapp_api.delete_friend(
            self.request(method='DELETE', match_info={'friend_id': str(other)}))
        self.assertEqual(response.status, 404)

        self.reset_limits()
        mine = store.add_friend_birthday(7, 'Mine', 2, 3, True)
        response = await webapp_api.delete_friend(
            self.request(method='DELETE', match_info={'friend_id': str(mine)}))
        self.assertEqual(response.status, 200)
        self.assertEqual(store.friend_birthdays(7), [])

    async def test_delete_friend_is_rate_limited(self):
        first_id = store.add_friend_birthday(7, 'One', 2, 3, True)
        second_id = store.add_friend_birthday(7, 'Two', 2, 4, True)
        first = await webapp_api.delete_friend(
            self.request(method='DELETE', match_info={'friend_id': str(first_id)}))
        second = await webapp_api.delete_friend(
            self.request(method='DELETE', match_info={'friend_id': str(second_id)}))
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 429)
        self.assertIsNotNone(store.friend_birthday(7, second_id))

    # --- CORS --------------------------------------------------------------
    async def ok_handler(self, request):
        return web.json_response({'ok': True})

    async def test_cors_blocks_unlisted_origins(self):
        response = await webapp_api._cors(FakeRequest(origin='https://evil.example'), self.ok_handler)
        self.assertEqual(response.status, 403)

    async def test_cors_allows_configured_origin_and_patch(self):
        with patch.object(config, 'WEBAPP_API_ALLOWED_ORIGINS', {'https://app.example'}):
            response = await webapp_api._cors(FakeRequest(origin='https://app.example'), self.ok_handler)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://app.example')
        self.assertIn('PATCH', response.headers['Access-Control-Allow-Methods'])
        self.assertEqual(response.headers['Vary'], 'Origin')

    async def test_cors_preflight_without_origin_is_allowed(self):
        response = await webapp_api._cors(FakeRequest(method='OPTIONS'), self.ok_handler)
        self.assertEqual(response.status, 204)

    async def test_health_endpoint(self):
        response = await webapp_api.health(FakeRequest())
        self.assertEqual(await payload_of(response), {'ok': True})


if __name__ == '__main__':
    unittest.main()
