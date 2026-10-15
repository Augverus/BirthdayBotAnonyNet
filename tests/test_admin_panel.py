"""Tests for the authenticated administration router."""
from types import SimpleNamespace

import admin_panel
import config
import store
import ui
from tests.support import (AsyncBotTestCase, FakeBot, FakeCallback, FakeMessage,
                           FakeState, api_error, private_chat, user)

ADMIN = 1001
OTHER_OWNER = 1002


class AdminPanelTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()
        self.state = FakeState()
        store.track_user(user(ADMIN, 'Boss'), 'k', 'message')
        store.track_user(user(7, 'Plain', 'User', 'plain'), 'k2', 'message')

    def msg(self, text, uid=ADMIN, **kwargs):
        return FakeMessage(text=text, from_user=user(uid), chat=private_chat(uid), **kwargs)

    def cb(self, data, uid=ADMIN, message=None, cid='cb'):
        return FakeCallback(data, from_user=user(uid), message=message or self.msg(''), cid=cid)

    async def call(self, data, uid=ADMIN):
        callback = self.cb(data, uid=uid)
        await admin_panel.admin_callback(callback, self.state, self.bot)
        return callback

    # --- access control ----------------------------------------------------
    async def test_entry_denied_for_non_admin(self):
        message = self.msg('/admin', uid=7)
        await admin_panel.admin_entry(message, self.state)
        self.assertIn('دسترسی', message.last_answer)

    async def test_entry_allows_admin(self):
        message = self.msg('/admin')
        await admin_panel.admin_entry(message, self.state)
        datas = [b.callback_data for row in message.answers[-1]['reply_markup'].inline_keyboard for b in row]
        self.assertIn('adm:stats', datas)
        self.assertIn('adm:broadcast', datas)
        self.assertIn('adm:errors', datas)

    async def test_callback_denied_for_non_admin(self):
        callback = await self.call('adm:stats', uid=7)
        self.assertTrue(callback.answers[-1]['show_alert'])
        self.assertFalse(callback.message.edits)

    # --- dashboard and stats ----------------------------------------------
    async def test_home_and_stats_pages(self):
        home = await self.call('adm:home')
        self.assertIn('مرکز مدیریت', home.message.last_edit)
        stats = await self.call('adm:stats')
        self.assertIn('آمار ربات', stats.message.last_edit)
        self.assertIn('کل کاربران خصوصی', stats.message.last_edit)

    async def test_users_list_and_detail(self):
        listing = await self.call('adm:users:0')
        datas = [b.callback_data for row in listing.message.edits[-1]['reply_markup'].inline_keyboard for b in row]
        self.assertIn('adm:user:7', datas)
        detail = await self.call('adm:user:7')
        self.assertIn('Plain User', detail.message.last_edit)
        self.assertIn('شناسه', detail.message.last_edit)

    async def test_user_detail_for_missing_user(self):
        callback = await self.call('adm:user:99999')
        self.assertIn('پیدا نشد', callback.message.last_answer)

    async def test_search_prompt_and_input(self):
        await self.call('adm:prompt:search')
        self.assertEqual(self.state.data.get('mode'), 'search')
        message = self.msg('7')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('Plain User', message.last_answer)

    async def test_search_unknown_user(self):
        await self.call('adm:prompt:search')
        message = self.msg('99999')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('معتبر نیست', message.last_answer)

    # --- user moderation ---------------------------------------------------
    async def test_ban_and_unban(self):
        await self.call('adm:ban:7')
        self.assertEqual(store.user(7)['banned'], 1)
        await self.call('adm:ban:7')
        self.assertEqual(store.user(7)['banned'], 0)

    async def test_admin_cannot_be_banned(self):
        store.track_user(user(OTHER_OWNER, 'Other'), 'k3', 'message')
        callback = await self.call(f'adm:ban:{OTHER_OWNER}')
        self.assertEqual(store.user(OTHER_OWNER)['banned'], 0)
        self.assertIn('ادمین', callback.message.last_answer)

    async def test_toggle_user_notification(self):
        before = store.user(7)['notification']
        await self.call('adm:unotify:7')
        self.assertEqual(store.user(7)['notification'], 1 - before)

    # --- channel lock ------------------------------------------------------
    async def test_channel_page_and_lock_requires_channel(self):
        page = await self.call('adm:channel')
        self.assertIn('قفل عضویت', page.message.last_edit)
        lock = await self.call('adm:lock')
        self.assertIn('ابتدا کانال', lock.message.last_answer)
        self.assertEqual(store.setting('channel_lock', '0'), '0')

    async def test_public_channel_setup(self):
        self.bot.chat = SimpleNamespace(id=-100123, type='channel', username='mychannel')
        self.bot.member_status = 'administrator'
        await self.call('adm:prompt:channel')
        self.assertEqual(self.state.data.get('mode'), 'channel')
        message = self.msg('@mychannel')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertEqual(store.setting('required_channel'), '@mychannel')
        self.assertEqual(store.setting('channel_url'), 'https://t.me/mychannel')

    async def test_public_channel_setup_requires_bot_to_be_admin(self):
        self.bot.chat = SimpleNamespace(id=-100123, type='channel', username='mychannel')
        self.bot.member_status = 'member'
        await self.call('adm:prompt:channel')
        message = self.msg('@mychannel')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('معتبر نیست', message.last_answer)
        self.assertEqual(store.setting('required_channel'), '')

    async def test_channel_setup_rejects_bad_value(self):
        await self.call('adm:prompt:channel')
        message = self.msg('notachannel')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('معتبر نیست', message.last_answer)

    async def test_private_channel_requires_invite_link(self):
        self.bot.chat = SimpleNamespace(id=-100999, type='channel', username=None)
        self.bot.member_status = 'administrator'
        await self.call('adm:prompt:channel')
        message = self.msg('-100999')
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('معتبر نیست', message.last_answer)

        await self.call('adm:prompt:channel')
        with_link = self.msg('-100999 https://t.me/+abc')
        await admin_panel.admin_input(with_link, self.state, self.bot)
        self.assertEqual(store.setting('required_channel'), '-100999')
        self.assertEqual(store.setting('channel_url'), 'https://t.me/+abc')

    async def test_channel_lock_requires_verifiable_bot_membership(self):
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'administrator'
        await self.call('adm:lock')
        self.assertEqual(store.setting('channel_lock'), '1')
        await self.call('adm:lock')
        self.assertEqual(store.setting('channel_lock'), '0')

    async def test_channel_lock_rejects_when_bot_is_not_admin(self):
        store.set_setting('required_channel', '@mychannel')
        self.bot.member_status = 'member'
        callback = await self.call('adm:lock')
        self.assertIn('فعال‌سازی ممکن نیست', callback.message.last_answer)
        self.assertEqual(store.setting('channel_lock', '0'), '0')

    # --- settings ----------------------------------------------------------
    async def test_settings_page_lists_switches(self):
        page = await self.call('adm:settings')
        self.assertIn('تنظیمات ربات', page.message.last_edit)

    async def test_toggle_setting(self):
        await self.call('adm:toggle:maintenance')
        self.assertEqual(store.setting('maintenance'), '1')
        await self.call('adm:toggle:maintenance')
        self.assertEqual(store.setting('maintenance'), '0')

    async def test_toggle_unknown_setting_is_ignored(self):
        callback = await self.call('adm:toggle:bogus')
        self.assertFalse(callback.message.answers)

    async def test_welcome_text_validation(self):
        await self.call('adm:prompt:welcome')
        ok = self.msg('خوش آمدی')
        await admin_panel.admin_input(ok, self.state, self.bot)
        self.assertEqual(store.setting('welcome'), 'خوش آمدی')

        await self.call('adm:prompt:welcome')
        too_long = self.msg('x' * 3001)
        await admin_panel.admin_input(too_long, self.state, self.bot)
        self.assertIn('معتبر نیست', too_long.last_answer)
        self.assertEqual(self.state.state, admin_panel.AdminFlow.input)

    async def test_reminder_time_validation(self):
        await self.call('adm:prompt:reminder_time')
        await admin_panel.admin_input(self.msg('07:30'), self.state, self.bot)
        self.assertEqual(store.setting('reminder_time'), '07:30')

        await self.call('adm:prompt:reminder_time')
        bad = self.msg('25:00')
        await admin_panel.admin_input(bad, self.state, self.bot)
        self.assertIn('معتبر نیست', bad.last_answer)

    async def test_send_rate_validation(self):
        await self.call('adm:prompt:send_rate')
        await admin_panel.admin_input(self.msg('10'), self.state, self.bot)
        self.assertEqual(store.setting('send_rate'), '10')

        await self.call('adm:prompt:send_rate')
        too_fast = self.msg('30')
        await admin_panel.admin_input(too_fast, self.state, self.bot)
        self.assertIn('معتبر نیست', too_fast.last_answer)

    # --- admin management --------------------------------------------------
    async def test_owners_see_admin_management_buttons(self):
        callback = await self.call('adm:admins')
        datas = [b.callback_data for row in callback.message.edits[-1]['reply_markup'].inline_keyboard
                 for b in row if b.callback_data]
        self.assertIn('adm:prompt:admin_add', datas)
        self.assertIn('adm:prompt:admin_remove', datas)

    async def test_non_owner_admin_cannot_manage_admins(self):
        with store.connection() as c:
            c.execute('INSERT OR IGNORE INTO bot_admins VALUES(?)', (2002,))
        page = await self.call('adm:admins', uid=2002)
        datas = [b.callback_data for row in page.message.edits[-1]['reply_markup'].inline_keyboard
                 for b in row if b.callback_data]
        self.assertNotIn('adm:prompt:admin_add', datas)
        prompt = await self.call('adm:prompt:admin_add', uid=2002)
        self.assertIn('مالک اصلی', prompt.message.last_answer)

    async def test_admin_add_requires_started_user(self):
        await self.call('adm:prompt:admin_add')
        unknown = self.msg('999999')
        await admin_panel.admin_input(unknown, self.state, self.bot)
        self.assertIn('معتبر نیست', unknown.last_answer)

    async def test_admin_add_and_confirm(self):
        await self.call('adm:prompt:admin_add')
        await admin_panel.admin_input(self.msg('7'), self.state, self.bot)
        self.assertEqual(self.state.data.get('admin_uid'), 7)
        await self.call('adm:admin_confirm')
        self.assertIn(7, store.admins())

    async def test_admin_remove_protects_env_owners(self):
        await self.call('adm:prompt:admin_remove')
        message = self.msg(str(OTHER_OWNER))
        await admin_panel.admin_input(message, self.state, self.bot)
        self.assertIn('معتبر نیست', message.last_answer)

    async def test_admin_remove_rejects_non_admin(self):
        before = store.admins()
        await self.call('adm:prompt:admin_remove')
        message = self.msg('7')
        await admin_panel.admin_input(message, self.state, self.bot)
        # Every validation failure inside admin_input is reported as one generic
        # message; the specific reason is not surfaced to the admin.
        self.assertIn('معتبر نیست', message.last_answer)
        self.assertEqual(store.admins(), before)

    async def test_admin_confirm_without_pending_request(self):
        callback = await self.call('adm:admin_confirm')
        self.assertIn('منقضی', callback.message.last_answer)

    # --- broadcast ---------------------------------------------------------
    async def test_broadcast_draft_then_enqueue(self):
        await self.call('adm:broadcast')
        self.assertEqual(self.state.data, {'target': None})
        self.assertEqual(self.state.state, admin_panel.AdminFlow.content)

        content = self.msg('hello everyone')
        await admin_panel.admin_content(content, self.state, self.bot)
        self.assertIn('پیش‌نمایش', content.last_answer)

        with store.connection() as c:
            job = dict(c.execute('SELECT * FROM bot_jobs').fetchone())
        self.assertEqual(job['status'], 'draft')

        sent = await self.call(f'adm:send:{job["id"]}')
        self.assertEqual(store.job(job['id'])['status'], 'queued')
        self.assertEqual(store.job_counts(job['id'])['total'], 2)  # admin + plain user
        self.assertIn('صف', sent.message.last_edit)

    async def test_broadcast_discard(self):
        await self.call('adm:broadcast')
        await admin_panel.admin_content(self.msg('hi'), self.state, self.bot)
        with store.connection() as c:
            jid = c.execute('SELECT id FROM bot_jobs').fetchone()[0]
        discarded = await self.call(f'adm:discard:{jid}')
        self.assertEqual(store.job(jid)['status'], 'cancelled')
        self.assertIn('لغو', discarded.message.last_edit)

    async def test_send_rejects_foreign_or_used_draft(self):
        jid = store.create_draft(OTHER_OWNER, OTHER_OWNER, 5, None)
        callback = await self.call(f'adm:send:{jid}')
        self.assertIn('قبلاً استفاده شده', callback.message.last_answer)
        self.assertEqual(store.job(jid)['status'], 'draft')

    async def test_direct_message_to_single_user(self):
        callback = await self.call('adm:direct:7')
        self.assertEqual(self.state.data, {'target': 7})
        await admin_panel.admin_content(self.msg('hi 7'), self.state, self.bot)
        with store.connection() as c:
            job = dict(c.execute('SELECT * FROM bot_jobs').fetchone())
        self.assertEqual(job['target_id'], 7)
        self.assertTrue(store.enqueue(job['id'], ADMIN))
        self.assertEqual(store.job_counts(job['id'])['total'], 1)

    async def test_direct_message_unavailable_user(self):
        store.update_user(7, banned=1)
        callback = await self.call('adm:direct:7')
        self.assertIn('در دسترس نیست', callback.message.last_answer)

    async def test_admin_content_rejects_unsupported_type(self):
        await self.call('adm:broadcast')
        message = self.msg('x', content_type='poll')
        await admin_panel.admin_content(message, self.state, self.bot)
        self.assertIn('پشتیبانی نمی‌شود', message.last_answer)

    async def test_admin_content_handles_preview_failure(self):
        await self.call('adm:broadcast')
        self.bot.copy_error = api_error('copy failed')
        message = self.msg('x')
        await admin_panel.admin_content(message, self.state, self.bot)
        self.assertIn('پیش‌نمایش ممکن نیست', message.last_answer)

    async def test_jobs_page_and_stop(self):
        jid = store.create_draft(ADMIN, ADMIN, 5, None)
        store.enqueue(jid, ADMIN)
        page = await self.call('adm:jobs')
        self.assertIn(f'#{jid}', page.message.last_edit)
        await self.call(f'adm:stop:{jid}')
        self.assertEqual(store.job(jid)['status'], 'cancelled')

    # --- groups ------------------------------------------------------------
    async def test_group_pages_toggle_and_copy(self):
        from tests.support import group_chat
        gid = -1001
        store.group_message(FakeMessage(text='hello group', from_user=user(9, 'Neo'),
                                        chat=group_chat(gid), message_id=10))

        listing = await self.call('adm:groups:0')
        datas = [b.callback_data for row in listing.message.edits[-1]['reply_markup'].inline_keyboard
                 for b in row if b.callback_data]
        self.assertIn(f'adm:group:{gid}:0', datas)

        detail = await self.call(f'adm:group:{gid}:0')
        self.assertIn('hello group', detail.message.last_edit)

        await self.call(f'adm:gcopy:{gid}:10')
        self.assertEqual(self.bot.copied[-1], (ADMIN, gid, 10))

        await self.call(f'adm:gtoggle:{gid}')
        self.assertEqual(next(g for g in store.groups() if g['id'] == gid)['enabled'], 0)

    async def test_gcopy_unknown_message_is_ignored(self):
        await self.call('adm:gcopy:-1001:999')
        self.assertEqual(self.bot.copied, [])

    # --- export and diagnostics -------------------------------------------
    async def test_csv_cell_escapes_formulas(self):
        self.assertEqual(admin_panel.csv_cell('=1+1'), "'=1+1")
        self.assertEqual(admin_panel.csv_cell('+x'), "'+x")
        self.assertEqual(admin_panel.csv_cell('-5'), "'-5")
        self.assertEqual(admin_panel.csv_cell('@x'), "'@x")
        self.assertEqual(admin_panel.csv_cell('safe'), 'safe')
        self.assertEqual(admin_panel.csv_cell(7), 7)

    async def test_export_sends_csv_document(self):
        callback = await self.call('adm:export')
        self.assertTrue(callback.message.documents)
        self.assertEqual(callback.message.documents[0]['caption'], '📁 خروجی کاربران')

    async def test_errors_page_and_clear(self):
        empty = await self.call('adm:errors')
        self.assertIn('No recorded errors', empty.message.last_edit)

        store.record_error('worker', 'boom')
        populated = await self.call('adm:errors')
        self.assertIn('boom', populated.message.last_edit)

        await self.call('adm:errors_clear')
        confirmed = await self.call('adm:errors_clear_confirm')
        self.assertIn('Cleared 1', confirmed.message.last_edit)
        self.assertEqual(store.recent_errors(), [])

    async def test_audit_page(self):
        store.audit(ADMIN, 'setting', 'maintenance')
        callback = await self.call('adm:audit')
        self.assertIn('maintenance', callback.message.last_edit)

    async def test_unknown_action_is_ignored(self):
        callback = await self.call('adm:does_not_exist')
        self.assertFalse(callback.message.edits)
        self.assertFalse(callback.message.answers)


if __name__ == '__main__':
    import unittest
    unittest.main()
