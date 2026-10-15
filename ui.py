"""Compact Telegram keyboards with optional premium icons and a text-only fallback."""
import re
import json
from html import escape

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

import config
import store

EMOJIS = {'edit': '5395444784611480792', 'off': '5240241223632954241',
          'on': '5836929837381456269', 'until': '5440621591387980068',
          'since': '5231012545799666522', 'birthday': '5206607081334906820'}
BTN_REGISTER = 'ثبت تولد'
BTN_EDIT = 'ویرایش تولد'
BTN_OFF = 'خاموش کردن اعلان'
BTN_ON = 'روشن کردن اعلان'
BTN_UNTIL = 'روزهای مانده'
BTN_SINCE = 'روزهای گذشته'
BTN_ADMIN = 'پنل مدیریت'


BTN_FRIENDS = 'تولد عزیزان'
BTN_DATE_CONVERTER = 'تبدیل تاریخ'

LEGACY_LABELS = {
    '\U0001f382 \u062b\u0628\u062a \u062a\u0648\u0644\u062f': BTN_REGISTER,
    '\u270f\ufe0f \u0648\u06cc\u0631\u0627\u06cc\u0634 \u062a\u0627\u0631\u06cc\u062e \u062a\u0648\u0644\u062f': BTN_EDIT,
    '\U0001f515 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644 \u06a9\u0631\u062f\u0646 \u0627\u0639\u0644\u0627\u0646': BTN_OFF,
    '\U0001f514 \u0641\u0639\u0627\u0644 \u06a9\u0631\u062f\u0646 \u0627\u0639\u0644\u0627\u0646': BTN_ON,
    '\u23f3 \u0686\u0646\u062f \u0631\u0648\u0632 \u062a\u0627 \u062a\u0648\u0644\u062f\u0645 \u0645\u0627\u0646\u062f\u0647\u061f': BTN_UNTIL,
    '\U0001f4c5 \u0686\u0646\u062f \u0631\u0648\u0632 \u0627\u0632 \u062a\u0648\u0644\u062f\u0645 \u06af\u0630\u0634\u062a\u0647\u061f': BTN_SINCE,
    '\U0001f6e0 \u067e\u0646\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a': BTN_ADMIN,
    '\U0001f465 \u062a\u0648\u0644\u062f \u0639\u0632\u06cc\u0632\u0627\u0646': BTN_FRIENDS,
    '\U0001f5d3 \u062a\u0628\u062f\u06cc\u0644 \u062a\u0627\u0631\u06cc\u062e': BTN_DATE_CONVERTER,
    '\U0001f7e2 \u062b\u0628\u062a \u062a\u0648\u0644\u062f': BTN_REGISTER,
}


def icon(key):
    return EMOJIS.get(key) if store.setting('custom_emoji', '0') == '1' else None


def emoji(key, fallback=''):
    eid = icon(key)
    alts = json.loads(store.setting('emoji_alts', '{}'))
    # Telegram requires a matching Unicode alt inside custom-emoji entities.
    # This alt is part of the premium entity, never a separate ordinary icon.
    alt = alts.get(eid) or fallback
    return f'<tg-emoji emoji-id="{eid}">{escape(alt)}</tg-emoji>' if eid and alt else ''


def fa_digits(value):
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def button(text, data=None, style='primary', key=None, url=None, web_app=None):
    return InlineKeyboardButton(text=text, callback_data=data, url=url, style=style,
                                icon_custom_emoji_id=icon(key), web_app=web_app)


def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def date_converter_keyboard():
    if config.WEBAPP_URL:
        return inline([[button('باز کردن مبدل تاریخ', style='success', key='since',
                               web_app=WebAppInfo(url=config.WEBAPP_URL))]])
    return inline([[button('راهنمای فعال‌سازی', 'date:setup')]])


def home(uid):
    u = store.user(uid)
    b = lambda text, style, key=None: KeyboardButton(text=text, style=style, icon_custom_emoji_id=icon(key))
    if u and u['month']:
        rows = [[b(BTN_UNTIL, 'success', 'until'), b(BTN_SINCE, 'primary', 'since')],
                [b(BTN_EDIT, 'primary', 'edit'),
                 b(BTN_OFF if u['notification'] else BTN_ON, 'primary' if u['notification'] else 'success', 'off' if u['notification'] else 'on')]]
    else:
        rows = [[b(BTN_REGISTER, 'success', 'birthday')]]
    rows.append([b(BTN_FRIENDS, 'primary', 'birthday'), b(BTN_DATE_CONVERTER, 'primary', 'since')])
    if uid in store.admins():
        rows.append([b(BTN_ADMIN, 'primary', 'edit')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True,
                               input_field_placeholder='یک گزینه انتخاب کن')


def remove_custom(value):
    if isinstance(value, dict):
        return {k: remove_custom(v) for k, v in value.items() if k != 'icon_custom_emoji_id'}
    if isinstance(value, list):
        return [remove_custom(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'<tg-emoji\b[^>]*>.*?</tg-emoji>\s*', '', value, flags=re.S)
    return value


class EmojiFallback(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            if 'emoji' not in str(exc).lower():
                raise
            raw = method.model_dump(mode='python', exclude_none=True)
            cleaned = remove_custom(raw)
            if raw == cleaned:
                raise
            store.set_setting('custom_emoji', '0')
            return await make_request(bot, type(method).model_validate(cleaned))


def safe_name(name):
    return escape(name or 'بدون نام')
