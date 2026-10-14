import asyncio
import json
import os
from datetime import date
from html import escape
from time import monotonic

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
import config

DB_FILE = "birthdays.json"

dp = Dispatcher()

MONTHS = [
    ("فروردین", 31),
    ("اردیبهشت", 31),
    ("خرداد", 31),
    ("تیر", 31),
    ("مرداد", 31),
    ("شهریور", 31),
    ("مهر", 30),
    ("آبان", 30),
    ("آذر", 30),
    ("دی", 30),
    ("بهمن", 30),
    ("اسفند", 29),
]

BTN_EDIT = " ویرایش تاریخ تولد"
BTN_DISABLE = " غیرفعال کردن اعلان ها"
BTN_ENABLE = " فعال کردن اعلان ها"
BTN_UNTIL = " چند روز تا تولدم مانده؟"
BTN_SINCE = " چند روز از تولدم گذشته؟"
BTN_REGISTER = " ثبت تولد"

BTN_EDIT_EMOJI_ID = "5395444784611480792"
BTN_DISABLE_EMOJI_ID = "5240241223632954241"
BTN_ENABLE_EMOJI_ID = "5836929837381456269"
BTN_UNTIL_EMOJI_ID = "5440621591387980068"
BTN_SINCE_EMOJI_ID = "5231012545799666522"
BTN_REGISTER_EMOJI_ID = "5206607081334906820"

BUTTON_STYLE = "primary"
ADMIN_NOTICE_COOLDOWN = 60
_admin_notice_times = {}


def allow_admin_notice(user_id):
    now = monotonic()
    expired = [uid for uid, sent_at in _admin_notice_times.items()
               if now - sent_at >= ADMIN_NOTICE_COOLDOWN]
    for uid in expired:
        del _admin_notice_times[uid]
    last_sent = _admin_notice_times.get(user_id)
    if last_sent is not None and now - last_sent < ADMIN_NOTICE_COOLDOWN:
        return False
    _admin_notice_times[user_id] = now
    return True


def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def birthday_text(month, day):
    return f"{day} {MONTHS[month - 1][0]}"


def normal_button(text, emoji_id):
    return KeyboardButton(
        text=text,
        icon_custom_emoji_id=emoji_id,
        style=BUTTON_STYLE,
    )


def main_keyboard(user_id=None):
    notification_enabled = True

    if user_id is not None:
        db = load_db()
        data = db.get(str(user_id))
        if data:
            notification_enabled = data.get("notification", True)

    if notification_enabled:
        notification_button = BTN_DISABLE
        notification_emoji_id = BTN_DISABLE_EMOJI_ID
    else:
        notification_button = BTN_ENABLE
        notification_emoji_id = BTN_ENABLE_EMOJI_ID

    return ReplyKeyboardMarkup(
        keyboard=[
            [normal_button(BTN_EDIT, BTN_EDIT_EMOJI_ID)],
            [normal_button(notification_button, notification_emoji_id)],
            [normal_button(BTN_UNTIL, BTN_UNTIL_EMOJI_ID)],
            [normal_button(BTN_SINCE, BTN_SINCE_EMOJI_ID)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="یک گزینه را انتخاب کنید",
    )


def register_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [normal_button(BTN_REGISTER, BTN_REGISTER_EMOJI_ID)]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def start_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="ثبت تاریخ تولد",
                    callback_data="set_birthday",
                    style="success",
                )
            ]
        ]
    )


def months_keyboard():
    buttons = []

    for i, (name, _) in enumerate(MONTHS, start=1):
        buttons.append(
            InlineKeyboardButton(
                text=name,
                callback_data=f"month:{i}",
                style="success",
            )
        )

    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def days_keyboard(month):
    total_days = MONTHS[month - 1][1]
    buttons = []

    for day in range(1, total_days + 1):
        buttons.append(
            InlineKeyboardButton(
                text=str(day),
                callback_data=f"day:{month}:{day}",
                style="success",
            )
        )

    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]

    keyboard.append([
        InlineKeyboardButton(
            text="بازگشت",
            callback_data="back_to_months",
            style="danger",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def gregorian_to_jalali(gy, gm, gd):
    g_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    gy -= 1600
    gm -= 1
    gd -= 1

    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400

    for i in range(gm):
        g_day_no += g_days[i]

    if gm > 1 and ((gy + 1600) % 4 == 0 and ((gy + 1600) % 100 != 0 or (gy + 1600) % 400 == 0)):
        g_day_no += 1

    g_day_no += gd
    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    while jm < 11 and j_day_no >= j_days[jm]:
        j_day_no -= j_days[jm]
        jm += 1

    return jy, jm + 1, j_day_no + 1


def jalali_to_gregorian(jy, jm, jd):
    j_days = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    g_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    jy -= 979
    jm -= 1
    jd -= 1

    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4)

    for i in range(jm):
        j_day_no += j_days[i]

    j_day_no += jd
    g_day_no = j_day_no + 79

    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097

    leap = True

    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524

        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False

    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461

    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365

    gm = 0
    while g_day_no >= g_days[gm] + (1 if gm == 1 and leap else 0):
        g_day_no -= g_days[gm] + (1 if gm == 1 and leap else 0)
        gm += 1

    return gy, gm + 1, g_day_no + 1


def days_until_birthday(month, day):
    today = date.today()
    jy, _, _ = gregorian_to_jalali(today.year, today.month, today.day)

    gy, gm, gd = jalali_to_gregorian(jy, month, day)
    birthday = date(gy, gm, gd)

    if birthday < today:
        gy, gm, gd = jalali_to_gregorian(jy + 1, month, day)
        birthday = date(gy, gm, gd)

    return (birthday - today).days


def days_since_birthday(month, day):
    today = date.today()
    jy, _, _ = gregorian_to_jalali(today.year, today.month, today.day)

    gy, gm, gd = jalali_to_gregorian(jy, month, day)
    birthday = date(gy, gm, gd)

    if birthday > today:
        gy, gm, gd = jalali_to_gregorian(jy - 1, month, day)
        birthday = date(gy, gm, gd)

    return (today - birthday).days


async def notify_admin_start(bot: Bot, user):
    if not allow_admin_notice(user.id):
        return
    db = load_db()
    data = db.get(str(user.id))

    birthday = "ثبت نشده"
    if data:
        birthday = birthday_text(data["month"], data["day"])

    username = f"@{user.username}" if user.username else "ندارد"
    profile = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"

    for admin_id in config.ADMIN_IDS:
        await bot.send_message(
            admin_id,
            "کاربر ربات را شروع کرد.\n\n"
        f"نام: {escape(user.full_name or 'Unknown')}\n"
        f"آیدی عددی: <code>{user.id}</code>\n"
        f"یوزرنیم: {escape(username)}\n"
        f"پروفایل: <a href='{escape(profile, quote=True)}'>باز کردن پروفایل</a>\n"
        f"تاریخ تولد: {birthday}",
        parse_mode="HTML",
    )


@dp.message(CommandStart())
async def start_handler(message: Message, bot: Bot):
    await notify_admin_start(bot, message.from_user)

    db = load_db()
    user_id = str(message.from_user.id)

    if user_id in db:
        data = db[user_id]

        if message.from_user.id in config.ADMIN_IDS:
            await message.answer(
                "سلام ادمین عزیز، خوش آمدید."
            )

        await message.answer(
            f"تاریخ تولد ثبت‌شده شما: {birthday_text(data['month'], data['day'])}",
            reply_markup=main_keyboard(message.from_user.id),
        )
        return

    if message.from_user.id in config.ADMIN_IDS:
        await message.answer(
            "سلام ادمین عزیز، خوش آمدید.\n\n"
            "برای ثبت تاریخ تولد، دکمه زیر را بزنید.",
            reply_markup=register_keyboard(),
        )
        return

    await message.answer(
        "سلام، خوش آمدید.\n\n"
        "لطفاً تاریخ تولد خود را ثبت کنید.",
        reply_markup=register_keyboard(),
    )


@dp.message(F.text == BTN_REGISTER)
async def register_button_handler(message: Message):
    await message.answer(
        "برای شروع ثبت تاریخ تولد، روی دکمه زیر بزنید:",
        reply_markup=start_inline_keyboard(),
    )


@dp.callback_query(F.data == "set_birthday")
async def set_birthday_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "ماه تولد خود را انتخاب کنید:",
        reply_markup=months_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_months")
async def back_to_months_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "ماه تولد خود را انتخاب کنید:",
        reply_markup=months_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("month:"))
async def month_handler(callback: CallbackQuery):
    try:
        parts = callback.data.split(":")
        month = int(parts[1])
        if len(parts) != 2 or not 1 <= month <= len(MONTHS):
            raise ValueError
    except (ValueError, IndexError):
        await callback.answer()
        return

    await callback.message.edit_text(
        f"ماه انتخاب‌شده: {MONTHS[month - 1][0]}\n\n"
        "روز تولد خود را انتخاب کنید:",
        reply_markup=days_keyboard(month),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("day:"))
async def day_handler(callback: CallbackQuery, bot: Bot):
    try:
        parts = callback.data.split(":")
        month, day = int(parts[1]), int(parts[2])
        if len(parts) != 3 or not 1 <= month <= len(MONTHS) or not 1 <= day <= MONTHS[month - 1][1]:
            raise ValueError
    except (ValueError, IndexError):
        await callback.answer()
        return

    db = load_db()
    user_id = str(callback.from_user.id)

    db[user_id] = {
        "month": month,
        "day": day,
        "username": callback.from_user.username,
        "full_name": callback.from_user.full_name,
        "notification": True,
    }

    save_db(db)

    remaining = days_until_birthday(month, day)
    username = f"@{callback.from_user.username}" if callback.from_user.username else "ندارد"
    profile = f"https://t.me/{callback.from_user.username}" if callback.from_user.username else f"tg://user?id={callback.from_user.id}"

    await callback.message.edit_text(
        "تاریخ تولد شما ثبت شد.\n\n"
        f"تاریخ تولد: {birthday_text(month, day)}\n"
        f"تا تولد شما {remaining} روز باقی مانده است."
    )

    await callback.message.answer(
        "گزینه‌های زیر برای شما فعال شد:",
        reply_markup=main_keyboard(callback.from_user.id),
    )

    await callback.answer()
    if allow_admin_notice(callback.from_user.id):
        for admin_id in config.ADMIN_IDS:
            await bot.send_message(
                admin_id,
                "تاریخ تولد کاربر ثبت شد.\n\n"
            f"نام: {escape(callback.from_user.full_name or 'Unknown')}\n"
            f"آیدی عددی: <code>{callback.from_user.id}</code>\n"
            f"یوزرنیم: {escape(username)}\n"
            f"پروفایل: <a href='{escape(profile, quote=True)}'>باز کردن پروفایل</a>\n"
            f"تاریخ تولد: {birthday_text(month, day)}\n"
            f"روزهای باقی‌مانده: {remaining}",
            parse_mode="HTML",
        )



@dp.message(F.text == BTN_EDIT)
async def edit_birthday_handler(message: Message):
    await message.answer(
        "ماه جدید تولد خود را انتخاب کنید:",
        reply_markup=months_keyboard(),
    )


@dp.message(F.text == BTN_DISABLE)
async def disable_notification_handler(message: Message):
    db = load_db()
    user_id = str(message.from_user.id)

    if user_id not in db:
        await message.answer("هنوز تاریخ تولدی ثبت نکرده‌اید.", reply_markup=register_keyboard())
        return

    db[user_id]["notification"] = False
    save_db(db)

    await message.answer(
        "اعلان تولد شما غیرفعال شد.",
        reply_markup=main_keyboard(message.from_user.id),
    )


@dp.message(F.text == BTN_ENABLE)
async def enable_notification_handler(message: Message):
    db = load_db()
    user_id = str(message.from_user.id)

    if user_id not in db:
        await message.answer("هنوز تاریخ تولدی ثبت نکرده‌اید.", reply_markup=register_keyboard())
        return

    db[user_id]["notification"] = True
    save_db(db)

    await message.answer(
        "اعلان تولد شما فعال شد.",
        reply_markup=main_keyboard(message.from_user.id),
    )


@dp.message(F.text == BTN_UNTIL)
async def until_handler(message: Message):
    db = load_db()
    user_id = str(message.from_user.id)

    if user_id not in db:
        await message.answer("هنوز تاریخ تولدی ثبت نکرده‌اید.", reply_markup=register_keyboard())
        return

    month = db[user_id]["month"]
    day = db[user_id]["day"]
    remaining = days_until_birthday(month, day)

    await message.answer(
        f"تاریخ تولد شما: {birthday_text(month, day)}\n"
        f"تا تولد شما {remaining} روز باقی مانده است.",
        reply_markup=main_keyboard(message.from_user.id),
    )


@dp.message(F.text == BTN_SINCE)
async def since_handler(message: Message):
    db = load_db()
    user_id = str(message.from_user.id)

    if user_id not in db:
        await message.answer("هنوز تاریخ تولدی ثبت نکرده‌اید.", reply_markup=register_keyboard())
        return

    month = db[user_id]["month"]
    day = db[user_id]["day"]
    passed = days_since_birthday(month, day)

    await message.answer(
        f"تاریخ تولد شما: {birthday_text(month, day)}\n"
        f"از آخرین تولد شما {passed} روز گذشته است.",
        reply_markup=main_keyboard(message.from_user.id),
    )


async def main():
    bot = Bot(token=config.BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
