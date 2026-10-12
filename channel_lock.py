# -*- coding: utf-8 -*-
"""قفل کانال — بررسی عضویت اجباری کاربر در کانال قبل از استفاده از ربات."""

import logging
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

import config
import database as db

logger = logging.getLogger(__name__)

# کلیدهای جدول تنظیمات
KEY_CHANNEL = "required_channel"   # مثل @mychannel
KEY_LOCK = "channel_lock"          # "1" یعنی فعال


def is_lock_enabled() -> bool:
    return db.get_setting(KEY_LOCK, "0") == "1" and bool(db.get_setting(KEY_CHANNEL))


async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی عضویت کاربر در کانال تنظیم‌شده."""
    channel = db.get_setting(KEY_CHANNEL)
    if not channel:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        # اگه ربات ادمین کانال نباشه یا کانال اشتباه باشه، کاربر رو بلاک نمی‌کنیم
        logger.exception("خطا در بررسی عضویت کانال %s", channel)
        return True


def _join_keyboard() -> InlineKeyboardMarkup:
    channel = db.get_setting(KEY_CHANNEL, "")
    url = f"https://t.me/{channel.lstrip('@')}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 عضویت در کانال", url=url)],
            [InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")],
        ]
    )


def channel_lock(handler):
    """دکوریتور: اگه قفل فعال باشه و کاربر عضو نباشه، پیام عضویت می‌فرسته."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # ادمین‌ها از قفل معاف هستن
        if user_id in config.ADMIN_IDS:
            return await handler(update, context)
        if is_lock_enabled() and not await is_member(user_id, context):
            await update.effective_message.reply_text(
                "برای استفاده از ربات اول باید عضو کانال ما بشی 👇",
                reply_markup=_join_keyboard(),
            )
            return
        return await handler(update, context)

    return wrapper


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر روی «عضو شدم» زده — دوباره بررسی می‌کنیم."""
    query = update.callback_query
    if await is_member(query.from_user.id, context):
        await query.answer("عضویتت تأیید شد! ✅")
        await query.message.edit_text(
            "عضویتت تأیید شد! ✅\nحالا می‌تونی از ربات استفاده کنی. با /start شروع کن."
        )
    else:
        await query.answer("هنوز عضو کانال نشدی! ❌", show_alert=True)
