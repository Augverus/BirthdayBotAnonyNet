"""Tests for the delivery queue, reminder worker and supervisor."""
import asyncio
import contextlib
import sqlite3
from unittest.mock import AsyncMock, patch

import jdatetime

import calendar_utils as cal
import runtime_jobs
import store
from tests.support import AsyncBotTestCase, FakeBot, api_error, bad_request, forbidden, retry_after, run_until, user


class CopyOneTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()

    async def test_success_sets_up_shared_rate_limiter(self):
        ok, error = await runtime_jobs.copy_one(self.bot, 7, 1, 2)
        self.assertTrue(ok)
        self.assertEqual(error, '')
        self.assertEqual(self.bot.copied[-1], (7, 1, 2))
        self.assertTrue(hasattr(self.bot, '_bulk_lock'))

    async def test_forbidden_marks_user_blocked(self):
        store.track_user(user(7), 'k', 'message')
        self.bot.copy_error = forbidden()
        ok, error = await runtime_jobs.copy_one(self.bot, 7, 1, 2)
        self.assertFalse(ok)
        self.assertEqual(error, 'Forbidden')
        self.assertEqual(store.user(7)['blocked'], 1)

    async def test_bad_request_does_not_block_user(self):
        store.track_user(user(7), 'k', 'message')
        self.bot.copy_error = bad_request()
        ok, error = await runtime_jobs.copy_one(self.bot, 7, 1, 2)
        self.assertFalse(ok)
        self.assertEqual(error, 'BadRequest')
        self.assertEqual(store.user(7)['blocked'], 0)

    async def test_retry_after_is_retried_then_succeeds(self):
        calls = {'n': 0}

        class Bot(FakeBot):
            async def copy_message(self, *args, **kwargs):
                calls['n'] += 1
                if calls['n'] == 1:
                    raise retry_after(1)
                self.copied.append(args)

        with patch('runtime_jobs.asyncio.sleep', new=AsyncMock()):
            ok, _ = await runtime_jobs.copy_one(Bot(), 7, 1, 2)
        self.assertTrue(ok)
        self.assertEqual(calls['n'], 2)

    async def test_exhausted_retries_report_network_error(self):
        class Bot(FakeBot):
            async def copy_message(self, *args, **kwargs):
                raise api_error('boom')

        with patch('runtime_jobs.asyncio.sleep', new=AsyncMock()):
            ok, error = await runtime_jobs.copy_one(Bot(), 7, 1, 2)
        self.assertFalse(ok)
        self.assertEqual(error, 'NetworkOrRateLimit')


class BackupTestCase(AsyncBotTestCase):
    async def test_create_backup_copies_database_and_retains_seven(self):
        for _ in range(8):
            path = runtime_jobs.create_backup()
            self.assertIsNotNone(path)
        from pathlib import Path
        files = list(Path(self._tmp.name, 'backups', 'automatic').glob('*.db'))
        self.assertEqual(len(files), 7)
        with sqlite3.connect(files[0]) as conn:
            self.assertIsNotNone(conn.execute('SELECT 1 FROM settings LIMIT 1').fetchone())

    async def test_rate_is_clamped_between_one_and_twenty_five(self):
        store.set_setting('send_rate', '0')
        self.assertEqual(runtime_jobs.rate(), 1)
        store.set_setting('send_rate', '999')
        self.assertEqual(runtime_jobs.rate(), 25)
        store.set_setting('send_rate', '10')
        self.assertEqual(runtime_jobs.rate(), 10)


class DeliveryWorkerTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()
        store.track_user(user(1001, 'Boss'), 'k', 'message')
        store.track_user(user(7, 'Plain'), 'k2', 'message')

    async def test_broadcast_is_delivered_and_reported(self):
        jid = store.create_draft(1001, 1001, 5, None)
        store.enqueue(jid, 1001)
        await run_until(lambda: store.job(jid)['status'] == 'done',
                        lambda: runtime_jobs.delivery_worker(self.bot))
        counts = store.job_counts(jid)
        self.assertEqual((counts['sent'], counts['failed'], counts['pending']), (2, 0, 0))
        self.assertEqual(len(self.bot.copied), 2)
        self.assertTrue(any(m['chat_id'] == 1001 and f'#{jid}' in m['text'] for m in self.bot.sent))

    async def test_recipient_that_blocked_is_marked_unavailable(self):
        jid = store.create_draft(1001, 1001, 5, 7)
        store.enqueue(jid, 1001)
        store.update_user(7, blocked=1)
        await run_until(lambda: store.job(jid)['status'] == 'done',
                        lambda: runtime_jobs.delivery_worker(self.bot))
        with store.connection() as c:
            error = c.execute('SELECT error FROM bot_deliveries WHERE job_id=? AND user_id=7',
                              (jid,)).fetchone()[0]
        self.assertEqual(error, 'Unavailable')
        self.assertEqual(self.bot.copied, [])

    async def test_forbidden_recipient_is_marked_failed(self):
        self.bot.copy_error = forbidden()
        jid = store.create_draft(1001, 1001, 5, 7)
        store.enqueue(jid, 1001)
        await run_until(lambda: store.job(jid)['status'] == 'done',
                        lambda: runtime_jobs.delivery_worker(self.bot))
        with store.connection() as c:
            error = c.execute('SELECT error FROM bot_deliveries WHERE job_id=? AND user_id=7',
                              (jid,)).fetchone()[0]
        self.assertEqual(error, 'Forbidden')
        self.assertEqual(store.user(7)['blocked'], 1)

    async def test_job_from_removed_admin_is_cancelled(self):
        jid = store.create_draft(9999, 9999, 5, None)
        store.enqueue(jid, 9999)
        await run_until(lambda: store.job(jid)['status'] == 'cancelled',
                        lambda: runtime_jobs.delivery_worker(self.bot))
        self.assertEqual(self.bot.copied, [])

    async def test_requeued_failed_delivery_is_sent_again(self):
        jid = store.create_draft(1001, 1001, 5, 7)
        store.enqueue(jid, 1001)
        with store.connection() as c:
            c.execute("UPDATE bot_deliveries SET status='failed' WHERE job_id=?", (jid,))
            c.execute("UPDATE bot_jobs SET status='done' WHERE id=?", (jid,))
        self.assertEqual(store.requeue_failed(jid, 1001), 1)
        await run_until(lambda: store.job(jid)['status'] == 'done',
                        lambda: runtime_jobs.delivery_worker(self.bot))
        counts = store.job_counts(jid)
        self.assertEqual((counts['sent'], counts['failed'], counts['pending']), (1, 0, 0))
        self.assertEqual(self.bot.copied[-1], (7, 1001, 5))

    async def test_cancelled_job_sends_nothing(self):
        jid = store.create_draft(1001, 1001, 5, None)
        store.enqueue(jid, 1001)
        with store.connection() as c:
            c.execute("UPDATE bot_jobs SET status='cancelled' WHERE id=?", (jid,))
        task = asyncio.create_task(runtime_jobs.delivery_worker(self.bot))
        await asyncio.sleep(0.15)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.assertEqual(self.bot.copied, [])


class ReminderWorkerTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()

    async def run_one_pass(self):
        """The worker's body runs before its 30 second sleep."""
        task = asyncio.create_task(runtime_jobs.reminder_worker(self.bot))
        await asyncio.sleep(0.2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_reminders_are_off_by_default(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, month=1, day=1, notification=1)
        await self.run_one_pass()
        self.assertEqual(self.bot.sent, [])

    async def test_disabled_notification_is_skipped(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, month=1, day=1, notification=0)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        await self.run_one_pass()
        self.assertEqual(self.bot.sent, [])

    async def test_daily_reminder_is_sent_once_per_day(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, month=1, day=1, notification=1)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        await self.run_one_pass()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertEqual(self.bot.sent[0]['chat_id'], 7)
        await self.run_one_pass()
        self.assertEqual(len(self.bot.sent), 1, 'reminder must not repeat the same day')

    async def test_birthday_today_message(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, month=1, day=1, notification=1)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        with patch.object(cal, 'today', return_value=jdatetime.date(1403, 1, 1)), \
                patch.object(cal, 'remaining', return_value=0):
            await self.run_one_pass()
        self.assertIn('تولدت مبارک', self.bot.sent[0]['text'])

    async def test_friend_reminder_batches_same_day_friends(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.add_friend_birthday(7, 'Sara', 1, 1, True)
        store.add_friend_birthday(7, 'Reza', 1, 1, True)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        with patch.object(cal, 'today', return_value=jdatetime.date(1403, 1, 1)):
            await self.run_one_pass()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn('Sara', self.bot.sent[0]['text'])
        self.assertIn('Reza', self.bot.sent[0]['text'])

    async def test_friend_reminder_skips_blocked_owner(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, blocked=1)
        store.add_friend_birthday(7, 'Sara', 1, 1, True)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        with patch.object(cal, 'today', return_value=jdatetime.date(1403, 1, 1)):
            await self.run_one_pass()
        self.assertEqual(self.bot.sent, [])

    async def test_blocked_recipient_is_flagged_when_reminder_fails(self):
        store.track_user(user(7, 'Ali'), 'k', 'message')
        store.update_user(7, month=1, day=1, notification=1)
        store.set_setting('reminders_enabled', '1')
        store.set_setting('reminder_time', '00:00')
        self.bot.send_error = forbidden()
        await self.run_one_pass()
        self.assertEqual(store.user(7)['blocked'], 1)


class SupervisorTestCase(AsyncBotTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bot = FakeBot()

    async def test_crash_is_recorded_and_worker_restarts(self):
        calls = {'n': 0}

        async def flaky(bot):
            calls['n'] += 1
            if calls['n'] >= 2:
                raise asyncio.CancelledError
            raise RuntimeError('boom')

        with patch('runtime_jobs.asyncio.sleep', new=AsyncMock()), \
                patch('runtime_jobs.log'), self.assertRaises(asyncio.CancelledError):
            await runtime_jobs.supervised(flaky, self.bot)
        self.assertEqual(calls['n'], 2)
        self.assertTrue(any('RuntimeError' in e['detail'] for e in store.recent_errors()))

    async def test_cancellation_propagates(self):
        async def worker(bot):
            raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await runtime_jobs.supervised(worker, self.bot)
        self.assertEqual(store.recent_errors(), [])


if __name__ == '__main__':
    import unittest
    unittest.main()
