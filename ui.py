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

ORDINARY_EMOJI = re.compile(
    r'[\U0001F000-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF]'
    r'[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]*'
    r'(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*)*'
    r'|[0-9#*]\uFE0F?\u20E3'
)
EMOJI_KEYS = {
    '🎂': 'birthday', '🎉': 'birthday', '🎈': 'birthday', '✨': 'birthday',
    '🔔': 'on', '✅': 'on', '🟢': 'on', '🔕': 'off', '❌': 'off',
    '✖': 'off', '🚫': 'off', '🗑': 'off', '⏳': 'until', '🕒': 'until',
    '📅': 'since', '🗓': 'since', '📊': 'since', '✏': 'edit', '🛠': 'edit',
    '⚙': 'edit', '✍': 'edit',
}


def plain_label(text):
    return ORDINARY_EMOJI.sub('', text).strip()


LEGACY_LABELS = {}
for label_name in (
    'BTN_REGISTER', 'BTN_EDIT', 'BTN_OFF', 'BTN_ON', 'BTN_UNTIL',
    'BTN_SINCE', 'BTN_ADMIN', 'BTN_FRIENDS', 'BTN_DATE_CONVERTER',
):
    old_label = globals()[label_name]
    globals()[label_name] = plain_label(old_label)
    LEGACY_LABELS[old_label] = globals()[label_name]
LEGACY_LABELS['🟢 ثبت تولد'] = BTN_REGISTER


def emoji_key(text):
    found = ORDINARY_EMOJI.search(text)
    return EMOJI_KEYS.get(found.group().rstrip('\ufe0f\ufe0e'), 'edit') if found else None


def icon(key):
    return EMOJIS.get(key) if store.setting('custom_emoji', '0') == '1' else None


def emoji(key, fallback):
    eid = icon(key)
    alts = json.loads(store.setting('emoji_alts', '{}'))
    alt = escape(alts.get(eid, fallback))
    return f'<tg-emoji emoji-id="{eid}">{alt}</tg-emoji>' if eid else ''


def button(text, data=None, style='primary', key=None, url=None, web_app=None):
    return InlineKeyboardButton(text=plain_label(text), callback_data=data, url=url, style=style,
                                icon_custom_emoji_id=icon(key or emoji_key(text)), web_app=web_app)


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
    rows.append([b(BTN_FRIENDS, 'danger', 'birthday')])
    rows.append([b(BTN_DATE_CONVERTER, 'primary', 'since')])
    if uid in store.admins():
        rows.append([b(BTN_ADMIN, 'primary', 'edit')])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder='یک گزینه انتخاب کن')


def remove_custom(value):
    if isinstance(value, dict):
        return {k: remove_custom(v) for k, v in value.items() if k != 'icon_custom_emoji_id'}
    if isinstance(value, list):
        return [remove_custom(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'<tg-emoji\b[^>]*>.*?</tg-emoji>\s*', '', value, flags=re.S)
    return value


def premium_text(text):
    parts = re.split(r'(<tg-emoji\b[^>]*>.*?</tg-emoji>|<[^>]+>)', text, flags=re.S)
    for index in range(0, len(parts), 2):
        parts[index] = ORDINARY_EMOJI.sub(
            lambda match: emoji(emoji_key(match.group()), match.group()), parts[index])
    return ''.join(parts)


def prepare_method(method):
    updates = {}
    method_name = type(method).__name__
    field = 'text' if method_name in ('SendMessage', 'EditMessageText') else 'caption'
    caption_methods = ('SendPhoto', 'SendVideo', 'SendAnimation', 'SendAudio',
                       'SendDocument', 'SendVoice', 'EditMessageCaption')
    if method_name in ('SendMessage', 'EditMessageText') or (
        method_name in caption_methods and getattr(method, 'caption', None)
    ):
        text = getattr(method, field)
        entity_field = 'entities' if field == 'text' else 'caption_entities'
        mode = getattr(method, 'parse_mode', None)
        entities = getattr(method, entity_field, None)
        if entities:
            from aiogram.utils.text_decorations import html_decoration
            text = html_decoration.unparse(text, entities)
        elif mode != 'HTML':
            if isinstance(mode, str) and mode:
                return method
            text = escape(text)
        updates.update({field: premium_text(text), 'parse_mode': 'HTML', entity_field: None})
    elif method_name == 'AnswerCallbackQuery' and method.text:
        updates['text'] = plain_label(method.text)
    return method.model_copy(update=updates) if updates else method


class EmojiFallback(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        method = prepare_method(method)
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
