"""خواندن تنظیمات از فایل .env — هیچ مقدار حساسی توی کد نیست."""

import os
from pathlib import Path
from urllib.parse import urlparse

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


def resolve_db_path(base_dir: Path, raw: str) -> str:
    """مسیرهای نسبی همیشه داخل پوشه پروژه باز شوند، نه پوشه جاری اجرا."""
    if raw == ":memory:":
        return raw
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base_dir) / candidate
    return str(candidate)


DB_PATH: str = resolve_db_path(BASE_DIR, os.getenv("DB_PATH", "birthdays.db"))

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

# --- Concurrent Telegram update handlers on this process ---
UPDATE_CONCURRENCY: int = int(os.getenv("UPDATE_CONCURRENCY", "32"))
if not 1 <= UPDATE_CONCURRENCY <= 256:
    raise RuntimeError("UPDATE_CONCURRENCY must be between 1 and 256")

# --- Public HTTPS URL for the optional Telegram date-converter Mini App ---
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "").strip()
if WEBAPP_URL:
    parsed_webapp_url = urlparse(WEBAPP_URL)
    if parsed_webapp_url.scheme != "https" or not parsed_webapp_url.netloc:
        raise RuntimeError("WEBAPP_URL must be a public HTTPS URL")
