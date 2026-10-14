"""Persistent runtime tables; legacy tables and JSON data are preserved."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config

_connections = threading.local()


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    db_path = str(config.DB_PATH)
    conn = getattr(_connections, 'conn', None)
    if conn is None or getattr(_connections, 'db_path', None) != db_path:
        if conn is not None:
            conn.close()
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        _connections.conn = conn
        _connections.db_path = db_path

    depth = getattr(_connections, 'depth', 0)
    savepoint = f'nested_{depth}'
    if depth:
        conn.execute(f'SAVEPOINT {savepoint}')
    _connections.depth = depth + 1
    try:
        yield conn
        if depth:
            conn.execute(f'RELEASE SAVEPOINT {savepoint}')
        else:
            conn.commit()
    except BaseException:
        if depth:
            conn.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
            conn.execute(f'RELEASE SAVEPOINT {savepoint}')
        else:
            conn.rollback()
        raise
    finally:
        _connections.depth = depth


def close_connection():
    """Close this thread's cached SQLite connection during shutdown."""
    conn = getattr(_connections, 'conn', None)
    if conn is not None:
        conn.close()
        del _connections.conn
        del _connections.db_path
        _connections.depth = 0


def init():
    with connection() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS bot_users(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', username TEXT,
            first_seen TEXT, last_seen TEXT, month INTEGER, day INTEGER,
            notification INTEGER NOT NULL DEFAULT 1, blocked INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS bot_admins(id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS bot_events(
            event_key TEXT PRIMARY KEY, user_id INTEGER, kind TEXT, created_at TEXT);
        CREATE INDEX IF NOT EXISTS bot_events_date ON bot_events(created_at);
        CREATE TABLE IF NOT EXISTS bot_groups(
            id INTEGER PRIMARY KEY, title TEXT, username TEXT, enabled INTEGER DEFAULT 1,
            first_seen TEXT, last_seen TEXT, messages INTEGER DEFAULT 0,
            bot_status TEXT DEFAULT 'unknown');
        CREATE TABLE IF NOT EXISTS bot_group_messages(
            chat_id INTEGER, message_id INTEGER, user_id INTEGER, name TEXT,
            body TEXT, kind TEXT, created_at TEXT, PRIMARY KEY(chat_id,message_id));
        CREATE TABLE IF NOT EXISTS bot_jobs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER,
            source_chat INTEGER, source_message INTEGER, target_id INTEGER,
            status TEXT DEFAULT 'draft', created_at TEXT, completed_at TEXT);
        CREATE TABLE IF NOT EXISTS bot_deliveries(
            job_id INTEGER, user_id INTEGER, status TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0, error TEXT, PRIMARY KEY(job_id,user_id));
        CREATE TABLE IF NOT EXISTS bot_reminders(
            user_id INTEGER, day TEXT, PRIMARY KEY(user_id,day));
        CREATE TABLE IF NOT EXISTS bot_rate_limits(
            user_id INTEGER, action TEXT, last_used REAL NOT NULL,
            PRIMARY KEY(user_id,action));
        CREATE TABLE IF NOT EXISTS bot_audit(
            id INTEGER PRIMARY KEY, admin_id INTEGER, action TEXT, detail TEXT, created_at TEXT);
        CREATE INDEX IF NOT EXISTS bot_users_last_seen ON bot_users(last_seen DESC,id);
        CREATE INDEX IF NOT EXISTS bot_deliveries_pending_job ON bot_deliveries(job_id,user_id)
            WHERE status='pending';
        ''')
        if not c.execute("SELECT 1 FROM settings WHERE key='runtime_migrated'").fetchone():
            legacy = Path(config.BASE_DIR) / 'birthdays.json'
            rows = json.loads(legacy.read_text()) if legacy.exists() else {}
            for uid, row in rows.items():
                c.execute('''INSERT OR IGNORE INTO bot_users
                    (id,name,username,month,day,notification) VALUES(?,?,?,?,?,?)''',
                    (int(uid), row.get('full_name', ''), row.get('username'),
                     row['month'], row['day'], int(row.get('notification', True))))
            exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
            if exists:
                for row in c.execute('SELECT * FROM users').fetchall():
                    c.execute('''INSERT OR IGNORE INTO bot_users(id,name,month,day)
                        VALUES(?,?,?,?)''', (row['chat_id'], row['name'] or '', row['birth_month'], row['birth_day']))
            c.execute("INSERT INTO settings(key,value) VALUES('runtime_migrated','1')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('custom_emoji','1')")


def setting(key, default=''):
    with connection() as c:
        row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default


def set_setting(key, value):
    with connection() as c:
        c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))


def audit(admin_id, action, detail=''):
    with connection() as c:
        c.execute('INSERT INTO bot_audit(admin_id,action,detail,created_at) VALUES(?,?,?,?)',
                  (admin_id, action, str(detail), now()))


def admins():
    with connection() as c:
        return config.ADMIN_IDS | {r['id'] for r in c.execute('SELECT id FROM bot_admins')}


def user(uid):
    with connection() as c:
        row = c.execute('SELECT * FROM bot_users WHERE id=?', (uid,)).fetchone()
        return dict(row) if row else None


def track_user(tg_user, key, kind):
    stamp = now()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with connection() as c:
        c.execute('''INSERT INTO bot_users(id,name,username,first_seen,last_seen)
            VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,username=excluded.username,last_seen=excluded.last_seen,blocked=0''',
            (tg_user.id, tg_user.full_name, tg_user.username, stamp, stamp))
        c.execute('INSERT OR IGNORE INTO bot_events VALUES(?,?,?,?)', (key, tg_user.id, kind, stamp))
        last_cleanup = c.execute("SELECT value FROM settings WHERE key='events_cleanup_date'").fetchone()
        if not last_cleanup or last_cleanup['value'] < stamp[:10]:
            c.execute('DELETE FROM bot_events WHERE created_at < ?', (cutoff,))
            c.execute('''INSERT INTO settings(key,value) VALUES('events_cleanup_date',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (stamp[:10],))


def claim_rate_limit(uid, action, cooldown_seconds=60):
    """Atomically allow one user action per cooldown window."""
    stamp = datetime.now(timezone.utc).timestamp()
    with connection() as c:
        result = c.execute('''INSERT INTO bot_rate_limits(user_id,action,last_used) VALUES(?,?,?)
            ON CONFLICT(user_id,action) DO UPDATE SET last_used=excluded.last_used
            WHERE bot_rate_limits.last_used <= ?''',
            (uid, action, stamp, stamp - cooldown_seconds))
        return result.rowcount == 1


def prune_reminders(before_day):
    """Keep only reminder markers for the current local day."""
    with connection() as c:
        c.execute('DELETE FROM bot_reminders WHERE day < ?', (before_day,))


def update_user(uid, **values):
    allowed = {'month', 'day', 'notification', 'blocked', 'banned'}
    if not values or not set(values) <= allowed:
        raise ValueError('Invalid user fields')
    with connection() as c:
        c.execute('UPDATE bot_users SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?',
                  (*values.values(), uid))


def list_users(offset=0, limit=10):
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM bot_users ORDER BY last_seen DESC,id LIMIT ? OFFSET ?', (limit, offset))]


def all_users():
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM bot_users ORDER BY id')]


def stats(since_today, since_week, month, day):
    with connection() as c:
        r = dict(c.execute('''SELECT COUNT(*) total,
            COALESCE(SUM(month IS NOT NULL),0) birthdays,
            COALESCE(SUM(notification=1 AND month IS NOT NULL AND blocked=0 AND banned=0),0) notifications,
            COALESCE(SUM(blocked),0) blocked, COALESCE(SUM(banned),0) banned,
            COALESCE(SUM(first_seen>=?),0) new_today,
            COALESCE(SUM(first_seen>=?),0) new_week,
            COALESCE(SUM(last_seen>=?),0) active_today,
            COALESCE(SUM(last_seen>=?),0) active_week,
            COALESCE(SUM(month=? AND day=?),0) birthday_today,
            COALESCE(SUM(month=?),0) birthday_month,
            COALESCE(SUM(first_seen IS NULL),0) imported
            FROM bot_users''', (since_today, since_week, since_today, since_week, month, day, month)).fetchone())
        r['messages_today'] = c.execute("SELECT COUNT(*) FROM bot_events WHERE created_at>=? AND kind='message'", (since_today,)).fetchone()[0]
        r['callbacks_today'] = c.execute("SELECT COUNT(*) FROM bot_events WHERE created_at>=? AND kind='callback'", (since_today,)).fetchone()[0]
        r['groups'] = c.execute('SELECT COUNT(*) FROM bot_groups').fetchone()[0]
        r['group_messages'] = c.execute('SELECT COALESCE(SUM(messages),0) FROM bot_groups').fetchone()[0]
        r['sent'] = c.execute("SELECT COUNT(*) FROM bot_deliveries WHERE status='sent'").fetchone()[0]
        r['failed'] = c.execute("SELECT COUNT(*) FROM bot_deliveries WHERE status='failed'").fetchone()[0]
        return r


def group_message(message, edited=False):
    stamp = now()
    sender = message.from_user
    sender_chat = message.sender_chat
    body = message.text or message.caption or ''
    with connection() as c:
        c.execute('''INSERT INTO bot_groups(id,title,username,first_seen,last_seen)
            VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
            username=excluded.username,last_seen=excluded.last_seen''',
            (message.chat.id, message.chat.title or '', message.chat.username, stamp, stamp))
        enabled = c.execute('SELECT enabled FROM bot_groups WHERE id=?', (message.chat.id,)).fetchone()[0]
        if not enabled or setting('group_reading', '1') != '1':
            return
        prior = c.execute('SELECT 1 FROM bot_group_messages WHERE chat_id=? AND message_id=?', (message.chat.id, message.message_id)).fetchone()
        c.execute('''INSERT INTO bot_group_messages VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(chat_id,message_id) DO UPDATE SET body=excluded.body,kind=excluded.kind''',
            (message.chat.id, message.message_id, sender.id if sender else (sender_chat.id if sender_chat else 0),
             sender.full_name if sender else (sender_chat.title if sender_chat else 'ناشناس'),
             body[:4000], message.content_type, stamp))
        if not prior and not edited:
            c.execute('UPDATE bot_groups SET messages=messages+1 WHERE id=?', (message.chat.id,))
        c.execute('''DELETE FROM bot_group_messages WHERE chat_id=? AND message_id NOT IN
            (SELECT message_id FROM bot_group_messages WHERE chat_id=? ORDER BY message_id DESC LIMIT 1000)''',
            (message.chat.id, message.chat.id))


def groups():
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM bot_groups ORDER BY last_seen DESC')]


def group_messages(gid, offset=0):
    with connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM bot_group_messages WHERE chat_id=? ORDER BY message_id DESC LIMIT 5 OFFSET ?', (gid, offset))]


def create_draft(admin_id, source_chat, source_message, target=None):
    with connection() as c:
        return c.execute('''INSERT INTO bot_jobs(admin_id,source_chat,source_message,target_id,created_at)
            VALUES(?,?,?,?,?)''', (admin_id, source_chat, source_message, target, now())).lastrowid


def job(jid):
    with connection() as c:
        row = c.execute('SELECT * FROM bot_jobs WHERE id=?', (jid,)).fetchone()
        return dict(row) if row else None


def enqueue(jid, admin_id):
    with connection() as c:
        row = c.execute("SELECT * FROM bot_jobs WHERE id=? AND admin_id=? AND status='draft'", (jid, admin_id)).fetchone()
        if not row:
            return False
        if row['target_id']:
            targets = [row['target_id']]
        else:
            targets = [r[0] for r in c.execute('SELECT id FROM bot_users WHERE blocked=0 AND banned=0 AND id>0')]
        c.executemany('INSERT INTO bot_deliveries(job_id,user_id) VALUES(?,?)', ((jid, uid) for uid in targets))
        c.execute("UPDATE bot_jobs SET status='queued' WHERE id=?", (jid,))
        return True


def job_counts(jid):
    with connection() as c:
        return dict(c.execute('''SELECT COUNT(*) total,
            COALESCE(SUM(status='sent'),0) sent, COALESCE(SUM(status='failed'),0) failed,
            COALESCE(SUM(status='pending'),0) pending FROM bot_deliveries WHERE job_id=?''', (jid,)).fetchone())
