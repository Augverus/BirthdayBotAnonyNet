from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import jdatetime

import config

MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


def local_now():
    return datetime.now(ZoneInfo(config.TIMEZONE))


def today():
    return jdatetime.date.fromgregorian(date=local_now().date())


def days_in_month(month):
    if not 1 <= month <= 12:
        raise ValueError('Invalid month')
    return 31 if month <= 6 else 30 if month < 12 or today().isleap() else 29


def valid_birthday(month, day):
    # Annual Esfand 30 birthdays are observed on Esfand 29 in non-leap years.
    return 1 <= month <= 12 and 1 <= day <= (31 if month <= 6 else 30)


def occurrence(year, month, day):
    if month == 12 and day == 30 and not jdatetime.date(year, 1, 1).isleap():
        day = 29
    return jdatetime.date(year, month, day).togregorian()


def remaining(month, day):
    t = local_now().date()
    year = today().year
    birthday = occurrence(year, month, day)
    if birthday < t:
        birthday = occurrence(year + 1, month, day)
    return (birthday - t).days


def elapsed(month, day):
    t = local_now().date()
    year = today().year
    birthday = occurrence(year, month, day)
    if birthday > t:
        birthday = occurrence(year - 1, month, day)
    return (t - birthday).days


def birthday_text(month, day):
    return f'{day} {MONTHS[month - 1]}'


def stat_boundaries():
    t = local_now()
    midnight = t.replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight.astimezone(timezone.utc).isoformat(),
            (t - timedelta(days=7)).astimezone(timezone.utc).isoformat())
