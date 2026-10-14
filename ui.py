"""Telegram keyboard styles and optional custom emoji with a server-error fallback."""
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
BTN_REGISTER = '🎂 ثبت تولد'
BTN_EDIT = '✏️ ویرایش تاریخ تولد'
BTN_OFF = '🔕 غیرفعال کردن اعلان'
BTN_ON = '🔔 فعال کردن اعلان'
BTN_UNTIL = '⏳ چند روز تا تولدم مانده؟'
BTN_SINCE = '📅 چند روز از تولدم گذشته؟'
BTN_ADMIN = '🛠 پنل مدیریت'


BTN_FRIENDS = '👥 تولد عزیزان'
BTN_DATE_CONVERTER = '🗓 تبدیل تاریخ'


def icon(key):
    return EMOJIS.get(key) if store.setting('custom_emoji', '0') == '1' else None


def emoji(key, fallback):
    eid = icon(key)
    alts = json.loads(store.setting('emoji_alts', '{}'))
    alt = escape(alts.get(eid, fallback))
    return f'<tg-emoji emoji-id="{eid}">{alt}</tg-emoji>' if eid else fallback


def button(text, data=None, style='primary', key=None, url=None, web_app=None):
    return InlineKeyboardButton(text=text, callback_data=data, url=url, style=style,
                                icon_custom_emoji_id=icon(key), web_app=web_app)


def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def date_converter_keyboard():
    if config.WEBAPP_URL:
        return inline([[button('🚀 باز کردن مبدل تاریخ', style='primary',
                               web_app=WebAppInfo(url=config.WEBAPP_URL))]])
    return inline([[button('⚙️ راهنمای فعال‌سازی', 'date:setup', 'primary')]])


def home(uid):
    u = store.user(uid)
    b = lambda text, style, key=None: KeyboardButton(text=text, style=style, icon_custom_emoji_id=icon(key))
    if u and u['month']:
        rows = [[b(BTN_EDIT, 'primary', 'edit')],
                [b(BTN_OFF if u['notification'] else BTN_ON, 'danger' if u['notification'] else 'success', 'off' if u['notification'] else 'on')],
                [b(BTN_UNTIL, 'success', 'until'), b(BTN_SINCE, 'primary', 'since')]]
    else:
        rows = [[b(BTN_REGISTER, 'success', 'birthday')]]
    rows.append([b(BTN_FRIENDS, 'primary')])
    rows.append([b(BTN_DATE_CONVERTER, 'primary')])
    if uid in store.admins():
        rows.append([b(BTN_ADMIN, 'primary')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder='✨ یک گزینه انتخاب کن')


def remove_custom(value):
    if isinstance(value, dict):
        return {k: remove_custom(v) for k, v in value.items() if k != 'icon_custom_emoji_id'}
    if isinstance(value, list):
        return [remove_custom(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', r'\1', value, flags=re.S)
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
