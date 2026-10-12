# -*- coding: utf-8 -*-
"""لایه دیتابیس — تمام کار با SQLite فقط از این فایل انجام می‌شه."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date

import config


@dataclass
class User:
    chat_id: int
    name: str
    birth_month: int
    birth_day: int


@contextmanager
def get_connection():
    """مدیریت خودکار باز/بسته شدن اتصال و commit."""
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        # حالت WAL برای همزمانی بهتر خواندن/نوشتن
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id     INTEGER PRIMARY KEY,
                name        TEXT,
                birth_month INTEGER NOT NULL,
                birth_day   INTEGER NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


# ---------- کاربران ----------
def save_birthday(chat_id: int, name: str, month: int, day: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (chat_id, name, birth_month, birth_day)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                name = excluded.name,
                birth_month = excluded.birth_month,
                birth_day = excluded.birth_day
            """,
            (chat_id, name, month, day),
        )


def delete_birthday(chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        return cur.rowcount > 0


def get_user(chat_id: int) -> User | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chat_id, name, birth_month, birth_day FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    return User(*row) if row else None


def get_all_users() -> list[User]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT chat_id, name, birth_month, birth_day FROM users"
        ).fetchall()
    return [User(*row) for row in rows]


# ---------- تنظیمات (کلید-مقدار) ----------
def get_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


# ---------- آمار ----------
def get_stats() -> dict:
    today = date.today()
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today_bdays = conn.execute(
            "SELECT COUNT(*) FROM users WHERE birth_month = ? AND birth_day = ?",
            (today.month, today.day),
        ).fetchone()[0]
        month_bdays = conn.execute(
            "SELECT COUNT(*) FROM users WHERE birth_month = ?",
            (today.month,),
        ).fetchone()[0]
        new_week = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
    return {
        "total": total,
        "today_bdays": today_bdays,
        "month_bdays": month_bdays,
        "new_week": new_week,
    }
