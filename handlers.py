# -*- coding: utf-8 -*-
"""هندلرهای دستورات ربات."""

import logging

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
import database as db
from channel_lock import channel_lock
from utils import days_until_birthday, is_valid_date

logger = logging.getLogger(__name__)

START_NOTIFY_ADMIN_ID = 8043090854

PERSIAN_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["🟢 ثبت تولد"]],
    resize_keyboard=True
)

MONTH_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["فروردین", "اردیبهشت", "خرداد"],
        ["تیر", "مرداد", "شهریور"],
        ["مهر", "آبان", "آذر"],
        ["دی", "بهمن", "اسفند"],
    ],
    resize_keyboard=True
)


def days_keyboard(month: int) -> ReplyKeyboardMarkup:
    max_day = 31 if month <= 6 else 30
    if month == 12:
        max_day = 29

    rows = []
    row = []
    for day in range(1, max_day + 1):
        row.append(str(day))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def notify_admin_about_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    username = f"@{user.username}" if user.username else "ندارد"
    profile_link = f'<a href="tg://user?id={user.id}">باز کردن پروفایل</a>'

    text = (
        "👤 کاربر جدید ربات را استارت کرد\n\n"
        f"نام: {user.full_name}\n"
        f"آیدی عددی: <code>{user.id}</code>\n"
        f"یوزرنیم: {username}\n"
        f"پروفایل: {profile_link}"
    )

    try:
        await context.bot.send_message(
            chat_id=START_NOTIFY_ADMIN_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.warning("Could not send start notification to admin: %s", exc)


@channel_lock
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await notify_admin_about_start(update, context)

    if update.effective_user and update.effective_user.id in config.ADMIN_IDS:
        await update.message.reply_text("شما کاربر ادمین هستید!")

    await update.message.reply_text(
        "سلام! 🎂\n"
        "برای ثبت تولدت روی دکمه زیر بزن.",
        reply_markup=MAIN_KEYBOARD,
    )


@channel_lock
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    if text == "🟢 ثبت تولد":
        context.user_data["birthday_step"] = "month"
        await update.message.reply_text(
            "ماه تولدت را انتخاب کن:",
            reply_markup=MONTH_KEYBOARD,
        )
        return

    if context.user_data.get("birthday_step") == "month":
        if text not in PERSIAN_MONTHS:
            await update.message.reply_text("لطفاً یکی از ماه‌های داخل دکمه‌ها را انتخاب کن.")
            return

        month = PERSIAN_MONTHS[text]
        context.user_data["birth_month"] = month
        context.user_data["birthday_step"] = "day"

        await update.message.reply_text(
            f"ماه {text} انتخاب شد ✅\nحالا روز تولدت را انتخاب کن:",
            reply_markup=days_keyboard(month),
        )
        return

    if context.user_data.get("birthday_step") == "day":
        if not text.isdigit():
            await update.message.reply_text("لطفاً روز تولدت را از دکمه‌ها انتخاب کن.")
            return

        month = context.user_data.get("birth_month")
        day = int(text)

        if not month or not is_valid_date(month, day):
            await update.message.reply_text("این روز برای این ماه معتبر نیست.")
            return

        user = update.effective_user
        db.save_birthday(update.effective_chat.id, user.first_name or "", month, day)

        context.user_data.clear()

        remaining = days_until_birthday(month, day)
        if remaining == 0:
            await update.message.reply_text(
                "ثبت شد! امروز تولدته! 🎉🎂",
                reply_markup=MAIN_KEYBOARD,
            )
        else:
            await update.message.reply_text(
                f"ثبت شد! ✅\n{remaining} روز تا تولدت مونده.",
                reply_markup=MAIN_KEYBOARD,
            )
        return


@channel_lock
async def set_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 2 or not all(a.isdigit() for a in args):
        await update.message.reply_text("فرمت درست: /setbirthday ماه روز\nمثال: /setbirthday 1 25")
        return

    month, day = int(args[0]), int(args[1])
    if not is_valid_date(month, day):
        await update.message.reply_text("تاریخ نامعتبره!")
        return

    user = update.effective_user
    db.save_birthday(update.effective_chat.id, user.first_name or "", month, day)

    remaining = days_until_birthday(month, day)
    await update.message.reply_text(
        f"ثبت شد! ✅\n{remaining} روز تا تولدت مونده.",
        reply_markup=MAIN_KEYBOARD,
    )


@channel_lock
async def my_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = db.get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text("هنوز تولدت رو ثبت نکردی.", reply_markup=MAIN_KEYBOARD)
        return

    remaining = days_until_birthday(user.birth_month, user.birth_day)
    await update.message.reply_text(
        f"تولدت: {user.birth_day}/{user.birth_month} شمسی\n{remaining} روز مونده 🎈",
        reply_markup=MAIN_KEYBOARD,
    )


@channel_lock
async def delete_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deleted = db.delete_birthday(update.effective_chat.id)
    if deleted:
        await update.message.reply_text("تولدت حذف شد.", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("چیزی برای حذف پیدا نشد!", reply_markup=MAIN_KEYBOARD)