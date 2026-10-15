"""Tests for the private user-facing flows in ``main``."""
from types import SimpleNamespace

import calendar_utils as cal
import config
import main
import store
import ui
from tests.support import (AsyncBotTestCase, FakeBot, FakeCallback, FakeMessage,
                           FakeState, private_chat, user)


class UserFlowTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()
        self.state = FakeState()
        store.track_user(user(7, 'Test', 'User', 'tuser'), 'seed', 'message')

    def msg(self, text, uid=7, **kwargs):
        return FakeMessage(text=text, from_user=user(uid), chat=private_chat(uid), **kwargs)

    def cb(self, data, uid=7, message=None, cid='cb'):
        return FakeCallback(data, from_user=user(uid), message=message or self.msg(''), cid=cid)

    # --- greeting and static commands -------------------------------------
    async def test_start_greets_user(self):
        message = self.msg('/start')
        await main.start_handler(message, self.state, self.bot)
        self.assertIn('Test User', message.last_answer)
        self.assertNotIn('/admin', message.last_answer)

    async def test_start_mentions_admin_panel_for_admins(self):
        store.track_user(user(1001, 'Boss'), 'k', 'message')
        message = self.msg('/start', uid=1001)
        await main.start_handler(message, self.state, self.bot)
        self.assertIn('/admin', message.last_answer)

    async def test_start_shows_birthday_when_registered(self):
        store.update_user(7, month=3, day=12, notification=1)
        message = self.msg('/start')
        await main.start_handler(message, self.state, self.bot)
        self.assertIn('12 خرداد', message.last_answer)

    async def test_id_help_and_cancel(self):
        message = self.msg('/id')
        await main.id_handler(message)
        self.assertIn('7', message.last_answer)

        help_message = self.msg('/help')
        await main.help_handler(help_message)
        self.assertIn('/mybirthday', help_message.last_answer)

        self.state.data = {'a': 1}
        cancel = self.msg('/cancel')
        await main.cancel_handler(cancel, self.state)
        self.assertEqual(self.state.data, {})

    async def test_fallback_guides_to_help(self):
        message = self.msg('سلام')
        await main.fallback(message)
        self.assertIn('/help', message.last_answer)

    async def test_edited_message_handler_is_a_noop(self):
        self.assertIsNone(await main.edited_message(self.msg('x')))

    # --- own birthday registration ----------------------------------------
    async def test_register_shows_all_twelve_months(self):
        message = self.msg(ui.BTN_REGISTER)
        await main.register_handler(message, self.state)
        labels = [b.text for row in message.answers[-1]['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(len([label for label in labels if label in cal.MONTHS]), 12)

    async def test_months_navigation_callback(self):
        callback = self.cb('back_to_months')
        await main.months_handler(callback)
        self.assertTrue(callback.message.edits)

    async def test_month_then_day_saves_birthday(self):
        await main.register_handler(self.msg(ui.BTN_REGISTER), self.state)
        await main.month_handler(self.cb('month:1'))
        await main.day_handler(self.cb('day:1:31'), self.bot)
        registered = store.user(7)
        self.assertEqual((registered['month'], registered['day'], registered['notification']), (1, 31, 1))

    async def test_month_handler_rejects_invalid_month(self):
        callback = self.cb('month:99')
        await main.month_handler(callback)
        self.assertTrue(callback.answers[-1]['show_alert'])
        self.assertFalse(callback.message.edits)

    async def test_day_handler_rejects_invalid_day(self):
        callback = self.cb('day:7:31')
        await main.day_handler(callback, self.bot)
        self.assertTrue(callback.answers[-1]['show_alert'])
        self.assertIsNone(store.user(7)['month'])

    async def test_setbirthday_command(self):
        await main.setbirthday_command(self.msg('/setbirthday 5 10'), self.bot)
        registered = store.user(7)
        self.assertEqual((registered['month'], registered['day']), (5, 10))

    async def test_setbirthday_rejects_bad_arguments(self):
        message = self.msg('/setbirthday 13 40')
        await main.setbirthday_command(message, self.bot)
        self.assertIn('فرمت', message.last_answer)
        self.assertIsNone(store.user(7)['month'])

    # --- notification and countdown ---------------------------------------
    async def test_notification_toggle(self):
        store.update_user(7, month=1, day=1, notification=1)
        await main.notification_handler(self.msg(ui.BTN_OFF))
        self.assertEqual(store.user(7)['notification'], 0)
        await main.notification_handler(self.msg(ui.BTN_ON))
        self.assertEqual(store.user(7)['notification'], 1)

    async def test_notification_requires_registered_birthday(self):
        message = self.msg(ui.BTN_ON)
        await main.notification_handler(message)
        self.assertIn('ثبت', message.last_answer)
        self.assertEqual(store.user(7)['notification'], 1)

    async def test_countdown_and_elapsed_buttons(self):
        store.update_user(7, month=1, day=1, notification=1)
        until = self.msg(ui.BTN_UNTIL)
        await main.birthday_handler(until)
        self.assertIn('روز', until.last_answer)
        since = self.msg(ui.BTN_SINCE)
        await main.birthday_handler(since)
        self.assertIn('گذشته', since.last_answer)

    async def test_countdown_requires_registration(self):
        message = self.msg(ui.BTN_UNTIL)
        await main.birthday_handler(message)
        self.assertIn('ثبت نکردی', message.last_answer)

    async def test_delete_birthday_flow(self):
        store.update_user(7, month=3, day=3, notification=1)
        prompt = self.msg('/deletebirthday')
        await main.deletebirthday_handler(prompt)
        self.assertTrue(prompt.answers[-1]['reply_markup'])
        await main.delete_callback(self.cb('user:delete'))
        deleted = store.user(7)
        self.assertIsNone(deleted['month'])
        self.assertEqual(deleted['notification'], 0)

    async def test_home_callback_clears_state(self):
        self.state.data = {'x': 1}
        callback = self.cb('user:home')
        await main.home_callback(callback, self.state)
        self.assertEqual(self.state.data, {})
        self.assertTrue(callback.message.answers)

    # --- friends birthdays -------------------------------------------------
    async def test_friends_listing_when_empty(self):
        message = self.msg(ui.BTN_FRIENDS)
        await main.friends_entry(message, self.state)
        self.assertIn('هنوز تولدی ثبت نکرده', message.last_answer)

    async def test_friend_add_flow_saves_friend(self):
        await main.friend_add_start(self.cb('friend:add'), self.state)
        self.assertEqual(self.state.state, main.FriendBirthdayFlow.name)

        await main.friend_name(self.msg('Sara'), self.state)
        self.assertEqual(self.state.state, main.FriendBirthdayFlow.month)

        await main.friend_month(self.cb('friend:month:2'), self.state)
        self.assertEqual(self.state.state, main.FriendBirthdayFlow.day)

        await main.friend_day(self.cb('friend:day:2:15'), self.state)
        self.assertIsNone(self.state.state)

        await main.friend_save(self.cb('friend:notify:1'), self.state)
        rows = store.friend_birthdays(7)
        self.assertEqual(
            [(r['name'], r['month'], r['day'], r['notification']) for r in rows],
            [('Sara', 2, 15, 1)],
        )

    async def test_friend_name_validation_and_cancel(self):
        await main.friend_add_start(self.cb('friend:add'), self.state)

        too_long = self.msg('x' * 81)
        await main.friend_name(too_long, self.state)
        self.assertIn('۸۰', too_long.last_answer)
        self.assertEqual(self.state.state, main.FriendBirthdayFlow.name)

        cancel = self.msg('/cancel')
        await main.friend_name(cancel, self.state)
        self.assertIsNone(self.state.state)

    async def test_friend_flow_rejects_bad_month_and_mismatched_day(self):
        await main.friend_add_start(self.cb('friend:add'), self.state)
        await main.friend_name(self.msg('Zed'), self.state)

        bad_month = self.cb('friend:month:13')
        await main.friend_month(bad_month, self.state)
        self.assertTrue(bad_month.answers[-1]['show_alert'])

        await main.friend_month(self.cb('friend:month:2'), self.state)
        mismatch = self.cb('friend:day:3:5')
        await main.friend_day(mismatch, self.state)
        self.assertTrue(mismatch.answers[-1]['show_alert'])
        self.assertEqual(store.friend_birthdays(7), [])

    async def test_friend_limit_message(self):
        for i in range(50):
            store.add_friend_birthday(7, f'friend {i}', 1, 1, True)
        await main.friend_add_start(self.cb('friend:add'), self.state)
        await main.friend_name(self.msg('Extra'), self.state)
        await main.friend_month(self.cb('friend:month:1'), self.state)
        await main.friend_day(self.cb('friend:day:1:1'), self.state)
        callback = self.cb('friend:notify:0')
        await main.friend_save(callback, self.state)
        self.assertIn('۵۰', callback.last_answer)
        self.assertEqual(len(store.friend_birthdays(7)), 50)

    async def test_friend_listing_and_delete(self):
        fid = store.add_friend_birthday(7, 'Sam', 3, 3, True)
        listing = self.msg(ui.BTN_FRIENDS)
        await main.friends_entry(listing, self.state)
        self.assertIn('Sam', listing.last_answer)

        delete = self.cb(f'friend:delete:{fid}')
        await main.friend_delete(delete)
        self.assertEqual(store.friend_birthdays(7), [])
        self.assertIn('حذف شد', delete.last_answer)

    async def test_friend_delete_unknown_id(self):
        callback = self.cb('friend:delete:999')
        await main.friend_delete(callback)
        self.assertIn('پیدا نشد', callback.last_answer)

    async def test_friend_delete_invalid_id(self):
        callback = self.cb('friend:delete:abc')
        await main.friend_delete(callback)
        self.assertTrue(callback.answers[-1]['show_alert'])

    # --- date converter mini app ------------------------------------------
    async def test_date_converter_guides_when_webapp_missing(self):
        message = self.msg(ui.BTN_DATE_CONVERTER)
        await main.date_converter_entry(message)
        self.assertIn('WEBAPP_URL', message.last_answer)
        first = message.answers[-1]['reply_markup'].inline_keyboard[0][0]
        self.assertEqual(first.callback_data, 'date:setup')

    async def test_date_converter_opens_webapp_when_configured(self):
        saved = config.WEBAPP_URL
        config.WEBAPP_URL = 'https://example.com/app'
        try:
            message = self.msg(ui.BTN_DATE_CONVERTER)
            await main.date_converter_entry(message)
            self.assertNotIn('WEBAPP_URL', message.last_answer)
            button = message.answers[-1]['reply_markup'].inline_keyboard[0][0]
            self.assertEqual(button.web_app.url, 'https://example.com/app')
        finally:
            config.WEBAPP_URL = saved

    async def test_date_setup_shows_alert(self):
        callback = self.cb('date:setup')
        await main.date_converter_setup(callback)
        self.assertTrue(callback.answers[-1]['show_alert'])

    # --- home keyboard -----------------------------------------------------
    async def test_home_keyboard_tracks_registration(self):
        before = [b.text for row in ui.home(7).keyboard for b in row]
        self.assertIn(ui.BTN_REGISTER, before)
        store.update_user(7, month=2, day=2, notification=1)
        after = [b.text for row in ui.home(7).keyboard for b in row]
        self.assertIn(ui.BTN_EDIT, after)
        self.assertIn(ui.BTN_OFF, after)
        self.assertIn(ui.BTN_UNTIL, after)

    async def test_bot_membership_registers_group(self):
        event = SimpleNamespace(
            chat=SimpleNamespace(id=-1005, type='supergroup', title='G', username='g'),
            new_chat_member=SimpleNamespace(status='administrator'),
        )
        await main.bot_membership(event)
        stored = next(g for g in store.groups() if g['id'] == -1005)
        self.assertEqual(stored['bot_status'], 'administrator')

    async def test_bot_membership_ignores_private_chats(self):
        event = SimpleNamespace(
            chat=SimpleNamespace(id=7, type='private', title=None, username=None),
            new_chat_member=SimpleNamespace(status='member'),
        )
        await main.bot_membership(event)
        self.assertEqual(store.groups(), [])

    async def test_ui_emoji_respects_setting(self):
        store.set_setting('custom_emoji', '1')
        markup = ui.emoji('birthday', '🎂')
        self.assertIn('<tg-emoji', markup)
        self.assertIn('🎂', markup)
        store.set_setting('custom_emoji', '0')
        self.assertEqual(ui.emoji('birthday', '🎂'), '')


if __name__ == '__main__':
    import unittest
    unittest.main()
