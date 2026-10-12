# -*- coding: utf-8 -*-
"""خواندن تنظیمات از فایل .env — هیچ مقدار حساسی توی کد نیست."""

import os
from pathlib import Path

from dotenv import load_dotenv

# فایل .env کنار همین فایل خونده می‌شه
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"متغیر {key} در فایل .env تعریف نشده!")
    return value


# --- توکن ربات (اجباری) ---
BOT_TOKEN: str = _get_required("BOT_TOKEN")

# --- دیتابیس ---
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "birthdays.db"))

# --- زمان ارسال یادآوری روزانه ---
REMINDER_HOUR: int = int(os.getenv("REMINDER_HOUR", "9"))
REMINDER_MINUTE: int = int(os.getenv("REMINDER_MINUTE", "0"))

# --- منطقه زمانی برای زمان‌بندی جاب ---
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Tehran")

# --- سطح لاگ ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# --- آیدی عددی ادمین‌ها (با کاما جدا شده) ---
ADMIN_IDS: set[int] = {
    int(value)
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if (value := item.strip())
}

# --- حداکثر تعداد پیام ارسالی در ثانیه (محدودیت تلگرام ~۳۰) ---
SEND_RATE: int = int(os.getenv("SEND_RATE", "25"))
