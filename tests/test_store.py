"""Tests for the SQLite data layer."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import calendar_utils as cal
import config
import store
from tests.support import BotTestCase, FakeMessage, group_chat, user


class SettingsAndUsersTestCase(BotTestCase):
    def test_init_seeds_defaults(self):
        self.assertEqual(store.setting('custom_emoji'), '1')
        self.assertEqual(store.setting('missing-key', 'fallback'), 'fallback')

    def test_settings_roundtrip(self):
        store.set_setting('welcome', 'hi')
        self.assertEqual(store.setting('welcome'), 'hi')
        store.set_setting('welcome', 'bye')
        self.assertEqual(store.setting('welcome'), 'bye')

    def test_admins_is_env_union_table(self):
        self.assertEqual(store.admins(), {1001, 1002})
        with store.connection() as c:
            c.execute('INSERT OR IGNORE INTO bot_admins VALUES(?)', (4242,))
        self.assertEqual(store.admins(), {1001, 1002, 4242})

    def test_unknown_user_is_none(self):
        self.assertIsNone(store.user(7))

    def test_track_user_creates_row(self):
        store.track_user(user(7, 'Ali', 'A', 'ali'), 'm:7:1', 'message')
        u = store.user(7)
        self.assertEqual(u['name'], 'Ali A')
        self.assertEqual(u['username'], 'ali')
        self.assertEqual(u['notification'], 1)
        self.assertEqual(u['banned'], 0)
        self.assertEqual(u['blocked'], 0)

    def test_track_user_deduplicates_events_and_clears_blocked(self):
        store.track_user(user(7), 'm:7:1', 'message')
        store.update_user(7, blocked=1)
        store.track_user(user(7), 'm:7:1', 'message')
        self.assertEqual(store.user(7)['blocked'], 0)
        with store.connection() as c:
            count = c.execute('SELECT COUNT(*) FROM bot_events').fetchone()[0]
        self.assertEqual(count, 1)

    def test_update_user_whitelist(self):
        store.track_user(user(7), 'k', 'message')
        store.update_user(7, month=5, day=2, notification=0)
        u = store.user(7)
        self.assertEqual((u['month'], u['day'], u['notification']), (5, 2, 0))
        with self.assertRaises(ValueError):
            store.update_user(7, name='injected')
        with self.assertRaises(ValueError):
            store.update_user(7)

    def test_update_user_can_clear_birthday(self):
        store.track_user(user(7), 'k', 'message')
        store.update_user(7, month=5, day=2)
        store.update_user(7, month=None, day=None, notification=0)
        u = store.user(7)
        self.assertIsNone(u['month'])
        self.assertIsNone(u['day'])

    def test_rate_limit_allows_once_per_window(self):
        self.assertTrue(store.claim_rate_limit(7, 'admin_notice', 60))
        self.assertFalse(store.claim_rate_limit(7, 'admin_notice', 60))
        self.assertTrue(store.claim_rate_limit(7, 'admin_notice', 0))
        self.assertTrue(store.claim_rate_limit(7, 'other', 60))

    def test_list_and_all_users(self):
        store.track_user(user(8, 'B'), 'k1', 'message')
        store.track_user(user(7, 'A'), 'k2', 'message')
        self.assertEqual([u['id'] for u in store.all_users()], [7, 8])
        self.assertEqual(len(store.list_users(0, 10)), 2)
        self.assertEqual(len(store.list_users(1, 10)), 1)

    def test_stats_counts(self):
        store.track_user(user(7), 'k1', 'message')
        store.track_user(user(8), 'k2', 'callback')
        store.update_user(7, month=3, day=12)
        today, week = cal.stat_boundaries()
        d = cal.today()
        s = store.stats(today, week, d.month, d.day)
        self.assertEqual(s['total'], 2)
        self.assertEqual(s['birthdays'], 1)
        self.assertEqual(s['messages_today'], 1)
        self.assertEqual(s['callbacks_today'], 1)
        self.assertEqual(s['sent'], 0)
        self.assertEqual(s['failed'], 0)

    def test_audit_records_action(self):
        store.audit(1001, 'ban', 7)
        with store.connection() as c:
            row = c.execute('SELECT * FROM bot_audit').fetchone()
        self.assertEqual((row['admin_id'], row['action'], row['detail']), (1001, 'ban', '7'))


class FriendBirthdayTestCase(BotTestCase):
    def test_crud_and_ordering(self):
        first = store.add_friend_birthday(7, 'Zed', 5, 1, True)
        store.add_friend_birthday(7, 'Ali', 2, 3, False)
        rows = store.friend_birthdays(7)
        self.assertEqual([r['name'] for r in rows], ['Ali', 'Zed'])
        self.assertEqual(rows[1]['id'], first)
        self.assertTrue(store.delete_friend_birthday(7, first))
        self.assertFalse(store.delete_friend_birthday(7, first))

    def test_delete_is_scoped_to_owner(self):
        fid = store.add_friend_birthday(7, 'Ali', 2, 3, True)
        self.assertFalse(store.delete_friend_birthday(8, fid))
        self.assertEqual(len(store.friend_birthdays(7)), 1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            store.add_friend_birthday(7, '', 1, 1)
        with self.assertRaises(ValueError):
            store.add_friend_birthday(7, 'x' * 81, 1, 1)
        with self.assertRaises(ValueError):
            store.add_friend_birthday(7, 'ok', 13, 1)
        with self.assertRaises(ValueError):
            store.add_friend_birthday(7, 'ok', 1, 32)

    def test_name_is_whitespace_normalised(self):
        store.add_friend_birthday(7, '  Ali   Reza  ', 1, 1, True)
        self.assertEqual(store.friend_birthdays(7)[0]['name'], 'Ali Reza')

    def test_fifty_friend_limit(self):
        for i in range(50):
            self.assertIsNotNone(store.add_friend_birthday(7, f'friend {i}', 1, 1, True))
        self.assertIsNone(store.add_friend_birthday(7, 'extra', 1, 1, True))

    def test_birthdays_on_date_only_returns_notified(self):
        store.track_user(user(7), 'k', 'message')
        store.add_friend_birthday(7, 'On', 4, 16, True)
        store.add_friend_birthday(7, 'Off', 4, 16, False)
        rows = store.friend_birthdays_on(4, 16)
        self.assertEqual([r['name'] for r in rows], ['On'])
        self.assertEqual(rows[0]['owner_id'], 7)

    def test_reminder_markers_and_pruning(self):
        self.assertFalse(store.friend_reminder_sent(7, '2024-06-01'))
        store.mark_friend_reminder(7, '2024-06-01')
        self.assertTrue(store.friend_reminder_sent(7, '2024-06-01'))
        with store.connection() as c:
            c.execute('INSERT INTO bot_reminders VALUES(?,?)', (7, '2024-01-01'))
        store.prune_reminders('2024-06-01')
        with store.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM bot_reminders').fetchone()[0], 0)
        self.assertTrue(store.friend_reminder_sent(7, '2024-06-01'))

    def test_lookup_is_scoped_to_owner(self):
        fid = store.add_friend_birthday(7, 'Ali', 2, 3, True)
        self.assertEqual(store.friend_birthday(7, fid)['name'], 'Ali')
        self.assertIsNone(store.friend_birthday(8, fid))
        self.assertIsNone(store.friend_birthday(7, 999))

    def test_toggle_and_set_friend_notification(self):
        fid = store.add_friend_birthday(7, 'Ali', 2, 3, True)
        self.assertEqual(store.toggle_friend_notification(7, fid), 0)
        self.assertEqual(store.toggle_friend_notification(7, fid), 1)
        self.assertIsNone(store.toggle_friend_notification(7, 999))
        self.assertTrue(store.set_friend_notification(7, fid, False))
        self.assertEqual(store.friend_birthday(7, fid)['notification'], 0)
        self.assertFalse(store.set_friend_notification(7, 999, True))

    def test_users_to_remind_filters_and_marks(self):
        store.track_user(user(7, 'Due'), 'k1', 'message')
        store.update_user(7, month=3, day=5, notification=1)
        store.track_user(user(8, 'Muted'), 'k2', 'message')
        store.update_user(8, month=3, day=5, notification=0)
        store.track_user(user(9, 'Blocked'), 'k3', 'message')
        store.update_user(9, month=3, day=5, notification=1, blocked=1)
        store.track_user(user(10, 'NoBirthday'), 'k4', 'message')
        self.assertEqual([u['id'] for u in store.users_to_remind('2024-06-01')], [7])

        with store.connection() as c:
            c.execute('INSERT INTO bot_reminders VALUES(?,?)', (7, '2024-06-01'))
        self.assertEqual(store.users_to_remind('2024-06-01'), [])
        self.assertEqual([u['id'] for u in store.users_to_remind('2024-06-02')], [7])


class GroupMessageTestCase(BotTestCase):
    def test_records_message_and_counts_once(self):
        chat = group_chat(-1001)
        store.group_message(FakeMessage(text='hello', from_user=user(9, 'Neo'), chat=chat, message_id=10))
        group = next(g for g in store.groups() if g['id'] == -1001)
        self.assertEqual(group['messages'], 1)
        self.assertEqual(group['title'], 'Group')
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'hello')

        # An edit updates the stored body without counting a new message.
        store.group_message(
            FakeMessage(text='hello v2', from_user=user(9, 'Neo'), chat=chat, message_id=10),
            edited=True,
        )
        group = next(g for g in store.groups() if g['id'] == -1001)
        self.assertEqual(group['messages'], 1)
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'hello v2')

    def test_disabled_group_stops_reading(self):
        chat = group_chat(-1001)
        store.group_message(FakeMessage(text='first', from_user=user(9), chat=chat, message_id=1))
        with store.connection() as c:
            c.execute('UPDATE bot_groups SET enabled=0 WHERE id=?', (-1001,))
        store.group_message(FakeMessage(text='second', from_user=user(9), chat=chat, message_id=2))
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'first')

    def test_global_reading_switch_stops_reading(self):
        chat = group_chat(-1001)
        store.group_message(FakeMessage(text='first', from_user=user(9), chat=chat, message_id=1))
        store.set_setting('group_reading', '0')
        store.group_message(FakeMessage(text='second', from_user=user(9), chat=chat, message_id=2))
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'first')

    def test_keeps_only_latest_thousand_messages(self):
        chat = group_chat(-1001)
        for mid in range(1, 1006):
            store.group_message(FakeMessage(text=f'm{mid}', from_user=user(9), chat=chat, message_id=mid))
        with store.connection() as c:
            kept = c.execute('SELECT COUNT(*) FROM bot_group_messages WHERE chat_id=?', (-1001,)).fetchone()[0]
        self.assertEqual(kept, 1000)
        self.assertEqual(store.group_messages(-1001)[0]['body'], 'm1005')

    def test_group_messages_pagination(self):
        chat = group_chat(-1001)
        for mid in range(1, 13):
            store.group_message(FakeMessage(text=f'm{mid}', from_user=user(9), chat=chat, message_id=mid))
        first = store.group_messages(-1001, 0)
        second = store.group_messages(-1001, 5)
        self.assertEqual(len(first), 5)
        self.assertEqual(first[0]['body'], 'm12')
        self.assertEqual(second[0]['body'], 'm7')
        self.assertFalse({m['message_id'] for m in first} & {m['message_id'] for m in second})


class JobsTestCase(BotTestCase):
    def setUp(self):
        super().setUp()
        store.track_user(user(7, 'Plain'), 'k', 'message')
        store.track_user(user(8, 'Banned'), 'k2', 'message')
        store.update_user(8, banned=1)

    def test_draft_lifecycle(self):
        jid = store.create_draft(1001, 1001, 5, None)
        self.assertEqual(store.job(jid)['status'], 'draft')
        self.assertTrue(store.enqueue(jid, 1001))
        counts = store.job_counts(jid)
        self.assertEqual(counts['total'], 1)  # banned user excluded
        self.assertEqual(counts['pending'], 1)
        self.assertFalse(store.enqueue(jid, 1001))  # already queued
        self.assertFalse(store.enqueue(jid, 9999))  # wrong admin

    def test_targeted_draft(self):
        jid = store.create_draft(1001, 1001, 5, 7)
        self.assertTrue(store.enqueue(jid, 1001))
        self.assertEqual(store.job_counts(jid)['total'], 1)

    def test_job_counts_reflect_delivery_status(self):
        jid = store.create_draft(1001, 1001, 5, None)
        store.enqueue(jid, 1001)
        with store.connection() as c:
            c.execute("UPDATE bot_deliveries SET status='sent' WHERE job_id=?", (jid,))
        counts = store.job_counts(jid)
        self.assertEqual((counts['sent'], counts['failed'], counts['pending']), (1, 0, 0))

    def test_requeue_failed_is_scoped_and_restarts_job(self):
        jid = store.create_draft(1001, 1001, 5, 7)
        store.enqueue(jid, 1001)
        with store.connection() as c:
            c.execute("UPDATE bot_deliveries SET status='failed',error='BadRequest' WHERE job_id=?", (jid,))
            c.execute("UPDATE bot_jobs SET status='done' WHERE id=?", (jid,))
        self.assertEqual(store.requeue_failed(jid, 9999), 0)  # not the owner
        self.assertEqual(store.requeue_failed(jid, 1001), 1)
        self.assertEqual(store.job(jid)['status'], 'queued')
        counts = store.job_counts(jid)
        self.assertEqual((counts['failed'], counts['pending']), (0, 1))
        self.assertEqual(store.requeue_failed(jid, 1001), 0)  # nothing left to retry

    def test_requeue_failed_from_cancelled_job(self):
        jid = store.create_draft(1001, 1001, 5, 7)
        store.enqueue(jid, 1001)
        with store.connection() as c:
            c.execute("UPDATE bot_deliveries SET status='failed' WHERE job_id=?", (jid,))
            c.execute("UPDATE bot_jobs SET status='cancelled' WHERE id=?", (jid,))
        self.assertEqual(store.requeue_failed(jid, 1001), 1)
        self.assertEqual(store.job(jid)['status'], 'queued')


class ErrorLogTestCase(BotTestCase):
    def test_token_is_redacted(self):
        store.record_error('startup', 'boom ' + config.BOT_TOKEN)
        self.assertEqual(store.recent_errors(5)[0]['detail'], 'boom [redacted]')

    def test_bounded_history(self):
        for i in range(120):
            store.record_error('worker', f'e{i}')
        with store.connection() as c:
            total = c.execute('SELECT COUNT(*) FROM bot_errors').fetchone()[0]
        self.assertEqual(total, 100)
        self.assertEqual(len(store.recent_errors(1000)), 20)  # limit clamped to 20

    def test_clear(self):
        store.record_error('a', 'b')
        self.assertEqual(store.clear_errors(), 1)
        self.assertEqual(store.recent_errors(), [])
        self.assertEqual(store.clear_errors(), 0)


class MigrationTestCase(unittest.TestCase):
    """Exercises the one-time import of the legacy JSON file and users table."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._saved = (config.DB_PATH, config.BASE_DIR)
        config.BASE_DIR = self._tmp.name
        config.DB_PATH = str(self.dir / 'legacy.db')
        store.close_connection()
        (self.dir / 'birthdays.json').write_text(json.dumps({
            '42': {'month': 4, 'day': 16, 'username': 'u42',
                   'full_name': 'Imported 42', 'notification': False},
        }))
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute('CREATE TABLE users(chat_id INTEGER, name TEXT, birth_month INTEGER, birth_day INTEGER)')
        conn.execute('INSERT INTO users VALUES(77, "Legacy", 9, 9)')
        conn.commit()
        conn.close()

    def tearDown(self):
        store.close_connection()
        config.DB_PATH, config.BASE_DIR = self._saved
        self._tmp.cleanup()

    def test_imports_json_and_legacy_table_once(self):
        store.init()
        imported = store.user(42)
        self.assertEqual(imported['name'], 'Imported 42')
        self.assertEqual(imported['username'], 'u42')
        self.assertEqual(imported['notification'], 0)
        self.assertEqual(store.user(77)['month'], 9)
        self.assertEqual(store.setting('runtime_migrated'), '1')

        store.init()  # idempotent: no duplicates, no crash
        self.assertEqual(len(store.all_users()), 2)

    def test_malformed_rows_are_skipped(self):
        (self.dir / 'birthdays.json').write_text(json.dumps({
            '42': {'month': 4, 'day': 16, 'full_name': 'Good'},
            'not-a-number': {'month': 4, 'day': 16, 'full_name': 'Bad id'},
            '43': {'day': 16, 'full_name': 'Missing month'},
            '44': {'month': 13, 'day': 1, 'full_name': 'Bad month'},
            '45': ['not', 'a', 'dict'],
        }))
        with patch.object(store.log, 'warning'):
            store.init()
        self.assertEqual([u['id'] for u in store.all_users()], [42, 77])

    def test_corrupt_json_file_never_blocks_startup(self):
        (self.dir / 'birthdays.json').write_text('{ definitely not json')
        with patch.object(store.log, 'warning'):
            store.init()
        self.assertEqual(store.user(77)['month'], 9)  # legacy table still imported
        self.assertEqual(store.setting('runtime_migrated'), '1')


class MissingDatabaseGuardTestCase(unittest.TestCase):
    """Untracked DB files must never be replaced by an empty database silently."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._saved = (config.DB_PATH, config.BASE_DIR)
        config.BASE_DIR = self._tmp.name
        config.DB_PATH = str(self.dir / 'birthdays.db')
        store.close_connection()

    def tearDown(self):
        store.close_connection()
        config.DB_PATH, config.BASE_DIR = self._saved
        self._tmp.cleanup()

    def test_missing_database_with_backups_refuses_to_start(self):
        backup_dir = self.dir / 'backups' / 'automatic'
        backup_dir.mkdir(parents=True)
        (backup_dir / 'birthdays-20260101-000000-000000.db').write_bytes(b'')
        with self.assertRaises(RuntimeError):
            store.init()

    def test_missing_database_without_backups_starts_fresh(self):
        store.init()
        self.assertEqual(store.setting('custom_emoji'), '1')

    def test_memory_database_skips_the_guard(self):
        config.DB_PATH = ':memory:'
        store.init()
        self.assertEqual(store.setting('custom_emoji'), '1')


if __name__ == '__main__':
    unittest.main()
