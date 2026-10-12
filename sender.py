# -*- coding: utf-8 -*-
"""
ارسال انبوه پیام با رعایت محدودیت نرخ تلگرام.
پیام‌ها به‌صورت دسته‌ای (batch) و موازی ارسال می‌شن،
با مکث بین دسته‌ها تا از محدودیت ~۳۰ پیام/ثانیه رد نشیم.
"""

import asyncio
import logging

from telegram import Bot
from telegram.error import Forbidden, RetryAfter

import config
import database as db

logger = logging.getLogger(__name__)


async def _send_one(bot: Bot, chat_id: int, text: str) -> bool:
    """ارسال یک پیام؛ True یعنی موفق."""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except RetryAfter as e:
        # تلگرام گفته صبر کن — صبر می‌کنیم و یک بار دیگه تلاش می‌کنیم
        logger.warning("RetryAfter: %s ثانیه صبر برای %s", e.retry_after, chat_id)
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception:
            logger.exception("تلاش دوم برای %s هم ناموفق بود", chat_id)
            return False
    except Forbidden:
        # کاربر ربات رو بلاک کرده → از دیتابیس حذف می‌شه
        logger.info("کاربر %s ربات رو بلاک کرده؛ حذف از دیتابیس", chat_id)
        db.delete_birthday(chat_id)
        return False
    except Exception:
        logger.exception("ارسال به %s ناموفق بود", chat_id)
        return False


async def send_bulk(bot: Bot, messages: list[tuple[int, str]]) -> tuple[int, int]:
    """
    ارسال لیستی از (chat_id, text) به‌صورت دسته‌ای.
    خروجی: (تعداد موفق، تعداد ناموفق)
    """
    ok = failed = 0
    rate = max(1, config.SEND_RATE)

    for i in range(0, len(messages), rate):
        batch = messages[i : i + rate]
        results = await asyncio.gather(
            *(_send_one(bot, chat_id, text) for chat_id, text in batch)
        )
        ok += sum(results)
        failed += len(results) - sum(results)

        # مکث ۱ ثانیه‌ای بین دسته‌ها (به‌جز آخرین دسته)
        if i + rate < len(messages):
            await asyncio.sleep(1)

    logger.info("ارسال انبوه تمام شد: %d موفق، %d ناموفق", ok, failed)
    return ok, failed
