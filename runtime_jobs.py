"""Persistent message delivery queue, rate limiting and daily reminders."""
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest, TelegramAPIError

import calendar_utils as cal
import config
import store
import ui

log = logging.getLogger(__name__)


def create_backup():
    source_path = Path(config.DB_PATH)
    if not source_path.exists() or str(config.DB_PATH) == ':memory:':
        return None
    backup_dir = Path(config.BASE_DIR) / 'backups' / 'automatic'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    target_path = backup_dir / f'birthdays-{stamp}.db'
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    target_path.chmod(0o600)
    backups = sorted(backup_dir.glob('birthdays-*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[7:]:
        old.unlink(missing_ok=True)
    return target_path


async def backup_worker(bot):
    while True:
        try:
            path = await asyncio.to_thread(create_backup)
            if path:
                log.info('Automatic database backup created: %s', path)
        except Exception as exc:
            log.exception('Automatic database backup failed: %s', exc)
            try:
                store.record_error('backup_worker', f'{type(exc).__name__}: {exc}')
            except Exception:
                log.exception('Could not persist backup error')
        await asyncio.sleep(24 * 60 * 60)


def rate():
    return max(1, min(25, int(store.setting('send_rate', str(config.SEND_RATE)))))


async def send_slot(bot):
    # Both workers share a limiter, so reminders cannot double broadcast traffic.
    if not hasattr(bot, '_bulk_lock'):
        bot._bulk_lock = asyncio.Lock()
        bot._bulk_next = 0
    async with bot._bulk_lock:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0, bot._bulk_next - loop.time()))
        bot._bulk_next = loop.time() + 1 / rate()


async def copy_one(bot, uid, source_chat, source_message):
    for retry in range(3):
        try:
            await send_slot(bot)
            await bot.copy_message(uid, source_chat, source_message)
            return True, ''
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError:
            store.update_user(uid, blocked=1)
            return False, 'Forbidden'
        except TelegramBadRequest:
            return False, 'BadRequest'
        except TelegramAPIError:
            await asyncio.sleep(2 ** retry)
    return False, 'NetworkOrRateLimit'


async def delivery_worker(bot):
    while True:
        with store.connection() as c:
            row = c.execute("SELECT * FROM bot_jobs WHERE status IN ('queued','running') ORDER BY id LIMIT 1").fetchone()
            job = dict(row) if row else None
            if job:
                c.execute("UPDATE bot_jobs SET status='running' WHERE id=? AND status='queued'", (job['id'],))
        if not job:
            await asyncio.sleep(1)
            continue
        if job['admin_id'] not in store.admins():
            with store.connection() as c:
                c.execute("UPDATE bot_jobs SET status='cancelled' WHERE id=?", (job['id'],))
            continue
        with store.connection() as c:
            items = c.execute("SELECT user_id FROM bot_deliveries WHERE job_id=? AND status='pending' LIMIT ?", (job['id'], rate())).fetchall()
        for row in items:
            current = store.job(job['id'])
            if current['status'] == 'cancelled':
                break
            uid = row['user_id']
            u = store.user(uid)
            if u and (u['blocked'] or u['banned']):
                ok, error = False, 'Unavailable'
            else:
                ok, error = await copy_one(bot, uid, job['source_chat'], job['source_message'])
            with store.connection() as c:
                c.execute('''UPDATE bot_deliveries SET status=?,attempts=attempts+1,error=?
                    WHERE job_id=? AND user_id=?''', ('sent' if ok else 'failed', error, job['id'], uid))
        if store.job(job['id'])['status'] == 'cancelled':
            continue
        counts = store.job_counts(job['id'])
        if counts['pending'] == 0:
            with store.connection() as c:
                c.execute("UPDATE bot_jobs SET status='done',completed_at=? WHERE id=?", (store.now(), job['id']))
            try:
                await bot.send_message(job['admin_id'],
                    f"✅ ارسال #{job['id']} تمام شد.\nموفق: {counts['sent']}\nناموفق: {counts['failed']}")
            except TelegramAPIError:
                log.warning('Could not deliver completion report for job %s', job['id'])


async def reminder_worker(bot):
    last_pruned_day = None
    while True:
        t = cal.local_now()
        day_key = t.date().isoformat()
        if day_key != last_pruned_day:
            store.prune_reminders(day_key)
            last_pruned_day = day_key
        hour, minute = map(int, store.setting('reminder_time', f'{config.REMINDER_HOUR:02}:{config.REMINDER_MINUTE:02}').split(':'))
        if store.setting('reminders_enabled', '0') == '1' and (t.hour, t.minute) >= (hour, minute):
            # One consolidated annual birthday note per owner, even when several
            # friends share the same date. Each owner has an independent marker.
            friend_groups = {}
            for friend in store.friend_birthdays_on(cal.today().month, cal.today().day):
                if friend['blocked'] or friend['banned']:
                    continue
                friend_groups.setdefault(friend['owner_id'], []).append(friend['name'])
            for owner_id, names in friend_groups.items():
                if store.friend_reminder_sent(owner_id, day_key):
                    continue
                people = ', '.join(f'<b>{escape(name)}</b>' for name in names)
                text = f'{ui.emoji("birthday", "🎂")} امروز تولد {people} است!'
                try:
                    await send_slot(bot)
                    await bot.send_message(owner_id, text, parse_mode='HTML')
                except TelegramForbiddenError:
                    store.update_user(owner_id, blocked=1)
                    store.mark_friend_reminder(owner_id, day_key)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    continue
                except TelegramAPIError:
                    continue
                else:
                    store.mark_friend_reminder(owner_id, day_key)
            for u in store.all_users():
                if not u['month'] or not u['notification'] or u['blocked'] or u['banned']:
                    continue
                with store.connection() as c:
                    sent = c.execute('SELECT 1 FROM bot_reminders WHERE user_id=? AND day=?', (u['id'], day_key)).fetchone()
                if sent:
                    continue
                days = cal.remaining(u['month'], u['day'])
                text = f'{ui.emoji("birthday", "🎂")} تولدت مبارک! امروز روز توئه!' if days == 0 else f'{ui.emoji("until", "⏳")} {days} روز تا تولدت مونده!\n{ui.emoji("birthday", "🎂")} {cal.birthday_text(u["month"], u["day"])}'
                try:
                    await send_slot(bot)
                    await bot.send_message(u['id'], text, parse_mode='HTML')
                except TelegramForbiddenError:
                    store.update_user(u['id'], blocked=1)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    continue
                except TelegramAPIError:
                    continue
                else:
                    with store.connection() as c:
                        c.execute('INSERT OR IGNORE INTO bot_reminders VALUES(?,?)', (u['id'], day_key))
        await asyncio.sleep(30)


async def supervised(worker, bot):
    while True:
        try:
            await worker(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception('Background worker failed: %s', worker.__name__)
            try:
                store.record_error(worker.__name__, f'{type(exc).__name__}: {exc}')
            except Exception:
                log.exception('Could not persist background worker error')
            await asyncio.sleep(5)
