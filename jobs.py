# -*- coding: utf-8 -*-
"""جاب‌های زمان‌بندی‌شده — یادآوری روزانه با ارسال دسته‌ای."""

import logging

from telegram.ext import ContextTypes

import database as db
from sender import send_bulk
from utils import days_until_birthday

logger = logging.getLogger(__name__)


def build_message(name: str, remaining: int) -> str:
    if remaining == 0:
        return f"🎉🎂 {name} جان تولدت مبارک! امروز روز توئه!"
    if remaining == 1:
        return "🎈 فقط ۱ روز تا تولدت مونده! فردا جشنه!"
    return f"🎂 {remaining} روز تا تولدت مونده!"


async def daily_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.get_all_users()
    if not users:
        return
    logger.info("شروع یادآوری روزانه برای %d کاربر", len(users))

    messages = [
        (u.chat_id, build_message(u.name, days_until_birthday(u.birth_month, u.birth_day)))
        for u in users
    ]
    await send_bulk(context.bot, messages)
