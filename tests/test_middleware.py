"""Tests for the access middleware and group observation."""
from unittest.mock import patch

import main
import store
from tests.support import (AsyncBotTestCase, FakeBot, FakeCallback, FakeMessage,
                           api_error, group_chat, private_chat, user)


class MiddlewareTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()
        self.forwarded = []

    async def handler(self, event, data):
        self.forwarded.append(event)
        return 'handled'

    async def run_mw(self, event, bot=None):
        middleware = main.AccessMiddleware()
        # The middleware checks isinstance against aiogram types; swap in the fakes.
        with patch.object(main, 'Message', FakeMessage, create=True), \
                patch.object(main, 'CallbackQuery', FakeCallback, create=True):
            return await middleware(self.handler, event, {'bot': bot or self.bot})

    def group_msg(self, text, message_id=1, uid=9, sender_chat=None):
        return FakeMessage(text=text, from_user=user(uid, 'Neo'), chat=group_chat(-1001),
                           message_id=message_id, sender_chat=sender_chat)

    def private_msg(self, text, uid=7, message_id=1):
        return FakeMessage(text=text, from_user=user(uid, 'Ali', username='ali'),
                           chat=private_chat(uid), message_id=message_id)

    # --- group observation -------------------------------------------------
    async def test_group_message_is_recorded_and_not_forwarded(self):
        message = self.group_msg('hello', message_id=5)
        self.assertIsNone(await self.run_mw(message))
        self.assertEqual(self.forwarded, [])
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'hello')

    async def test_group_id_command_replies(self):
        message = self.group_msg('/id')
        await self.run_mw(message)
        self.assertIn('شناسه گروه', message.last_answer)
        self.assertIn('-1001', message.last_answer)

    async def test_group_privacy_explains_monitoring(self):
        message = self.group_msg('/groupprivacy')
        await self.run_mw(message)
        self.assertIn('/groupmonitor off', message.last_answer)

    async def test_groupmonitor_requires_group_admin(self):
        self.bot.member_status = 'member'
        message = self.group_msg('/groupmonitor off')
        await self.run_mw(message)
        self.assertIn('فقط برای مدیر گروه', message.last_answer)
        self.assertEqual(store.groups()[0]['enabled'], 1)

    async def test_groupmonitor_toggles_for_group_admin(self):
        self.bot.member_status = 'administrator'
        message = self.group_msg('/groupmonitor off')
        await self.run_mw(message)
        self.assertIn('متوقف', message.last_answer)
        self.assertEqual(store.groups()[0]['enabled'], 0)

    async def test_groupmonitor_rejects_bad_format(self):
        self.bot.member_status = 'administrator'
        message = self.group_msg('/groupmonitor maybe')
        await self.run_mw(message)
        self.assertIn('فرمت', message.last_answer)

    async def test_groupmonitor_membership_error_is_reported(self):
        self.bot.member_error = api_error('boom')
        message = self.group_msg('/groupmonitor off')
        with patch('main.log'):
            await self.run_mw(message)
        self.assertIn('ممکن نیست', message.last_answer)

    # --- private chat gate -------------------------------------------------
    async def test_tracks_user_and_forwards(self):
        message = self.private_msg('hi')
        self.assertEqual(await self.run_mw(message), 'handled')
        self.assertIsNotNone(store.user(7))

    async def test_bot_sender_in_private_is_ignored(self):
        message = FakeMessage(text='hi', from_user=user(7, is_bot=True), chat=private_chat(7))
        self.assertIsNone(await self.run_mw(message))
        self.assertIsNone(store.user(7))

    async def test_banned_user_message_is_blocked(self):
        store.track_user(user(7), 'k', 'message')
        store.update_user(7, banned=1)
        message = self.private_msg('hi')
        self.assertIsNone(await self.run_mw(message))
        self.assertIn('محدود شده', message.last_answer)

    async def test_banned_user_callback_gets_alert(self):
        store.track_user(user(7), 'k', 'message')
        store.update_user(7, banned=1)
        callback = FakeCallback('x', from_user=user(7),
                                message=FakeMessage(text='', chat=private_chat(7)))
        await self.run_mw(callback)
        self.assertTrue(callback.answers[-1]['show_alert'])

    async def test_maintenance_blocks_regular_user(self):
        store.set_setting('maintenance', '1')
        message = self.private_msg('/start')
        self.assertIsNone(await self.run_mw(message))
        self.assertIn('بروزرسانی', message.last_answer)

    async def test_maintenance_exempts_id_help_cancel(self):
        store.set_setting('maintenance', '1')
        for command in ('/id', '/help', '/cancel'):
            message = self.private_msg(command)
            self.assertEqual(await self.run_mw(message), 'handled', command)

    async def test_admin_bypasses_maintenance_and_channel_lock(self):
        store.set_setting('maintenance', '1')
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_error = api_error('boom')
        message = self.private_msg('/start', uid=1001)
        with patch('main.log'):
            self.assertEqual(await self.run_mw(message), 'handled')

    async def test_channel_lock_blocks_non_member(self):
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'left'
        message = self.private_msg('/start')
        self.assertIsNone(await self.run_mw(message))
        self.assertIn('عضو کانال', message.last_answer)
        datas = [b.callback_data for row in message.answers[-1]['reply_markup'].inline_keyboard for b in row]
        self.assertIn('check_join', datas)

    async def test_channel_lock_fails_closed_on_verification_error(self):
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_error = api_error('boom')
        message = self.private_msg('/start')
        with patch('main.log'):
            self.assertIsNone(await self.run_mw(message))
        self.assertIn('ممکن نیست', message.last_answer)

    async def test_channel_lock_allows_member(self):
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'member'
        self.assertEqual(await self.run_mw(self.private_msg('/start')), 'handled')

    async def test_channel_lock_restricted_member_is_allowed(self):
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'restricted'
        self.assertEqual(await self.run_mw(self.private_msg('/start')), 'handled')

    async def test_callback_without_message_is_ignored(self):
        callback = FakeCallback('x', from_user=user(7), message=None)
        self.assertIsNone(await self.run_mw(callback))

    async def test_join_keyboard_offers_channel_link(self):
        store.set_setting('channel_lock', '1')
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'left'
        message = self.private_msg('/start')
        await self.run_mw(message)
        buttons = [b for row in message.answers[-1]['reply_markup'].inline_keyboard for b in row]
        urls = [b.url for b in buttons if b.url]
        self.assertEqual(urls, ['https://t.me/mychannel'])


if __name__ == '__main__':
    import unittest
    unittest.main()
