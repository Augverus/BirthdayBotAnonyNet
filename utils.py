# -*- coding: utf-8 -*-
"""توابع کمکی برای تاریخ شمسی."""

from datetime import date
import jdatetime


def is_valid_date(month: int, day: int) -> bool:
    if month < 1 or month > 12:
        return False
    if month <= 6:
        return 1 <= day <= 31
    if month <= 11:
        return 1 <= day <= 30
    return 1 <= day <= 29


def days_until_birthday(month: int, day: int, today: date | None = None) -> int:
    today_gregorian = today or date.today()
    today_jalali = jdatetime.date.fromgregorian(date=today_gregorian)

    year = today_jalali.year
    next_birthday_jalali = jdatetime.date(year, month, day)

    if next_birthday_jalali < today_jalali:
        next_birthday_jalali = jdatetime.date(year + 1, month, day)

    next_birthday_gregorian = next_birthday_jalali.togregorian()
    return (next_birthday_gregorian - today_gregorian).days