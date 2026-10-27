"""Birthday bot runtime: private user flows, admin router and group observation."""
import asyncio
import json
import logging
from contextlib import suppress
from html import escape

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import CallbackQuery, ErrorEvent, Message
import jdatetime

import admin_panel
import calendar_utils as cal
import config
import runtime_jobs
import store
import ui
import webapp_api

log = logging.getLogger(__name__)
dp = Dispatcher(events_isolation=SimpleEventIsolation())
user_router = Router(name='users')


def configured_text(key, default, **values):
    template = store.setting(key, default)
    rendered = escape(template)
    for name, value in values.items():
        rendered = rendered.replace('{' + name + '}', str(value))
    return rendered


DEFAULT_DATE_KEYWORDS = 'تاریخ,تولدم,تولد من'


def date_question(body):
    """True when a group message asks for the date; keywords come from settings."""
    configured = store.setting('group_date_keywords', DEFAULT_DATE_KEYWORDS)
    return any(word.strip() in body for word in configured.split(',') if word.strip())


@dp.errors()
async def capture_update_error(event: ErrorEvent):
    error = event.exception
    log.error('Unhandled Telegram update error',
              exc_info=(type(error), error, error.__traceback__))
    try:
        store.record_error('telegram_update', f'{type(error).__name__}: {error}')
    except Exception:
        log.exception('Could not persist Telegram update error')


class FriendBirthdayFlow(StatesGroup):
    name = State()
    year = State()
    month = State()
    day = State()


class MyBirthdayFlow(StatesGroup):
    year = State()
    month = State()
    day = State()


def _cancel_requested(message):
    text = (message.text or '').strip()
    return bool(text and text.split(maxsplit=1)[0].split('@')[0] == '/cancel')


async def _cancel_flow(message, state):
    if not _cancel_requested(message):
        return False
    await state.clear()
    await message.answer('✖️ عملیات جاری لغو شد.', reply_markup=ui.home(message.from_user.id))
    return True


def join_keyboard():
    channel = store.setting('required_channel')
    url = store.setting('channel_url') or ('https://t.me/'+channel.lstrip('@') if channel.startswith('@') else '')
    rows = [[ui.button('✅ عضو شدم؛ بررسی کن', 'check_join', 'success')]]
    if url:
        rows.insert(0, [ui.button('📢 عضویت در کانال', url=url)])
    return ui.inline(rows)


async def membership(bot, uid):
    channel = store.setting('required_channel')
    if not channel:
        return False
    target = int(channel) if channel.lstrip('-').isdigit() else channel
    try:
        m = await bot.get_chat_member(target, uid)
        return m.status in ('member', 'administrator', 'creator') or (m.status == 'restricted' and m.is_member)
    except TelegramAPIError:
        log.warning('Channel membership verification unavailable')
        return None


async def group_event(message, bot, edited=False):
    store.group_message(message, edited)
    text = (message.text or '').split()
    command = text[0].split('@')[0] if text else ''
    if edited:
        return
    if text and '@' in text[0] and command in ('/id','/start','/groupprivacy','/groupmonitor'):
        me = await bot.me()
        if text[0].split('@', 1)[1].lower() != (me.username or '').lower():
            return
    body = ' '.join((message.text or message.caption or '').casefold().split())
    if date_question(body):
        try:
            member = await bot.get_chat_member(message.chat.id, bot.id)
        except TelegramAPIError:
            member = None
        if member and member.status in ('administrator', 'creator'):
            today = cal.today()
            user = store.user(message.from_user.id) if message.from_user else None
            if user and user['month'] and user['day']:
                birthday_line = f'{ui.emoji("until", "⏳")} <b>{cal.remaining(user["month"], user["day"])}</b> روز'
            else:
                birthday_line = configured_text('birthday_hint', 'برای ثبت تاریخ تولد خود به پیوی ربات مراجعه کنید.')
            reply = configured_text(
                'group_date_reply',
                '{since} <b>تاریخ</b> :\n▪️ تاریخ امروز : <b>{date}</b>\n┘─\n▪️ روز باقی مانده تا تولدم : {birthday}',
                since=ui.emoji('since', '📅'), date=f'{today.year}/{today.month:02}/{today.day:02}',
                birthday=birthday_line)
            await message.answer(reply, parse_mode='HTML', reply_to_message_id=message.message_id)
            return
    if command == '/id':
        uid = message.from_user.id if message.from_user else 'نامعلوم'
        await message.answer(f'شناسه شما: {uid}\nشناسه گروه: {message.chat.id}')
    elif command in ('/groupprivacy', '/start'):
        await message.answer('👁 این ربات پیام‌هایی را که تلگرام در اختیارش قرار می‌دهد برای پنل مدیران ثبت می‌کند.\n'
                             'آخرین ۱۰۰۰ پیام نگه داشته می‌شود. مدیر گروه می‌تواند با /groupmonitor off ثبت را متوقف کند.\n'
                             'برای ثبت تولد، در گفتگوی خصوصی ربات /start بفرستید.')
    elif command == '/groupmonitor':
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            authorized = True
        elif message.from_user:
            try:
                member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            except TelegramAPIError:
                await message.answer('بررسی دسترسی مدیر فعلاً ممکن نیست؛ دوباره تلاش کنید.')
                return
            authorized = member.status in ('administrator', 'creator')
        else:
            authorized = False
        if not authorized:
            await message.answer('این دستور فقط برای مدیر گروه است.')
            return
        if len(text) != 2 or text[1] not in ('on', 'off'):
            await message.answer('فرمت: /groupmonitor on یا /groupmonitor off')
            return
        with store.connection() as c:
            c.execute('UPDATE bot_groups SET enabled=? WHERE id=?', (int(text[1]=='on'), message.chat.id))
        await message.answer('✅ ثبت پیام‌های این گروه '+('فعال' if text[1]=='on' else 'متوقف')+' شد.')


class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data['bot']
        if isinstance(event, Message) and event.chat.type in ('group', 'supergroup'):
            await group_event(event, bot, bool(event.edit_date))
            return
        if isinstance(event, Message) and event.text in ui.LEGACY_LABELS:
            event = event.model_copy(update={'text': ui.LEGACY_LABELS[event.text]})
        message = event if isinstance(event, Message) else event.message
        if not message or message.chat.type != 'private' or not event.from_user or event.from_user.is_bot:
            return
        uid = event.from_user.id
        kind = 'message' if isinstance(event, Message) else 'callback'
        key = f'm:{message.chat.id}:{message.message_id}' if kind=='message' else f'c:{event.id}'
        store.track_user(event.from_user, key, kind)
        admins = store.admins()
        if uid in admins:
            return await handler(event, data)
        u = store.user(uid)
        text = message.text or ''
        command = text.split()[0].split('@')[0] if text else ''
        bypass = isinstance(event, Message) and command in ('/id', '/help', '/cancel')
        if u['banned']:
            if isinstance(event, CallbackQuery):
                await event.answer('⛔ دسترسی شما محدود شده.', show_alert=True)
            else:
                await message.answer('⛔ دسترسی شما به ربات محدود شده است.')
            return
        if not bypass and store.setting('maintenance', '0') == '1':
            if isinstance(event, CallbackQuery):
                await event.answer('🚧 ربات در حال بروزرسانی است.', show_alert=True)
            else:
                await message.answer('🚧 ربات در حال بروزرسانی است. کمی بعد دوباره سر بزن ✨')
            return
        if not bypass and store.setting('channel_lock', '0') == '1':
            member = await membership(bot, uid)
            if member is not True:
                if isinstance(event, CallbackQuery):
                    await event.answer('عضویت تأیید نشد؛ دوباره بررسی کن.' if member is False else 'بررسی عضویت فعلاً ممکن نیست.', show_alert=True)
                else:
                    await message.answer('🔒 برای استفاده از ربات، اول عضو کانال شو 👇' if member is False else '⏳ بررسی عضویت فعلاً ممکن نیست؛ کمی بعد دوباره تلاش کن.', reply_markup=join_keyboard())
                return
        return await handler(event, data)


dp.message.outer_middleware(AccessMiddleware())
dp.callback_query.outer_middleware(AccessMiddleware())
dp.edited_message.outer_middleware(AccessMiddleware())
dp.include_router(admin_panel.router)


async def greet(message, uid):
    u = store.user(uid)
    welcome = store.setting('welcome', 'به خونهٔ تولدها خوش اومدی! ✨\nتاریخ تولدت رو ثبت کن و شمارش معکوس روز خاصت رو ببین.')
    text = f'{ui.emoji("birthday", "🎂")} <b>سلام {ui.safe_name(u["name"])}!</b>\n\n{configured_text("welcome", welcome, name=ui.safe_name(u["name"]))}'
    if u['month']:
        text += f'\n\n{ui.emoji("birthday", "🎂")} تولدت: <b>{cal.birthday_text(u["month"], u["day"], u.get("birth_year"))}</b>\n{ui.emoji("until", "⏳")} <b>{cal.remaining(u["month"], u["day"])} روز</b> تا جشن تو!'
    if uid in store.admins():
        text += '\n\n🛠 پنل مدیریت: /admin'
    await message.answer(text, parse_mode='HTML', reply_markup=ui.home(uid))


async def notify_admin(bot, text, uid):
    if (store.setting('notify_admin', '0') != '1'
            or not store.claim_rate_limit(uid, 'admin_notice', 60)):
        return
    for aid in store.admins():
        if aid == uid:
            continue
        try:
            await bot.send_message(aid, text, parse_mode='HTML', reply_markup=ui.inline([[ui.button('👤 مدیریت کاربر', f'adm:user:{uid}')]]))
        except TelegramAPIError:
            log.warning('Admin notification unavailable: %s', aid)


@user_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, bot):
    await state.clear()
    uid = message.from_user.id
    await greet(message, uid)
    await notify_admin(bot, f'👤 کاربر ربات را شروع کرد.\n{ui.safe_name(message.from_user.full_name)}\nشناسه: <code>{uid}</code>', uid)


@user_router.message(Command('id'))
async def id_handler(message: Message):
    await message.answer(f'🪪 آیدی عددی شما: <code>{message.from_user.id}</code>', parse_mode='HTML')


@user_router.message(F.text == ui.BTN_FRIENDS)
@user_router.message(Command('friends'))
async def friends_entry(message: Message, state: FSMContext):
    await state.clear()
    text, keyboard = friends_listing(message.from_user.id)
    await message.answer(text, parse_mode='HTML', reply_markup=keyboard)


@user_router.message(F.text == ui.BTN_DATE_CONVERTER)
async def date_converter_entry(message: Message):
    if config.WEBAPP_URL:
        text = f'{ui.emoji("since", "📅")} <b>مبدل تاریخ</b>\n\nتقویم شمسی و میلادی را به‌سادگی به هم تبدیل کن.'
    else:
        text = ('🗓 <b>مبدل تاریخ شمسی و میلادی</b>\n\n'
                'برای فعال شدن مینی‌اپ، نشانی HTTPS آن را در <code>WEBAPP_URL</code> فایل .env قرار بده.')
    await message.answer(text, parse_mode='HTML', reply_markup=ui.date_converter_keyboard())


@user_router.callback_query(F.data == 'date:setup')
async def date_converter_setup(callback: CallbackQuery):
    await callback.answer('ابتدا WEBAPP_URL را در فایل .env تنظیم کن.', show_alert=True)


@user_router.message(F.web_app_data)
async def mini_app_data_handler(message: Message, bot):
    """Accept only a validated birthday payload from Telegram's Mini App message."""
    raw = message.web_app_data.data if message.web_app_data else None
    try:
        payload_size = len(raw.encode('utf-8')) if isinstance(raw, str) else 4097
    except UnicodeEncodeError:
        payload_size = 4097
    if (message.chat.type != 'private' or not message.from_user
            or message.from_user.is_bot or not isinstance(raw, str)
            or message.web_app_data.button_text != ui.DATE_CONVERTER_WEBAPP_BUTTON
            or payload_size > 4096):
        await message.answer('اطلاعات ارسالی معتبر نیست.')
        return
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
        if (not isinstance(payload, dict)
                or set(payload) != {'action', 'calendar', 'year', 'month', 'day'}
                or payload['action'] != 'save_birthday'
                or payload['calendar'] != 'solar_hijri'
                or any(type(payload[key]) is not int for key in ('year', 'month', 'day'))):
            raise ValueError
        year, month, day = payload['year'], payload['month'], payload['day']
        birthday = jdatetime.date(year, month, day)
        # A birthday may be later this year; its original Solar Hijri year is saved.
        if year > cal.today().year or not cal.valid_birthday(month, day):
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, RecursionError):
        await message.answer('تاریخ ارسالی معتبر نیست؛ تاریخ را دوباره بررسی کن.')
        return
    await save_birthday(message, message.from_user.id, year, month, day, bot, notification=None)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


FRIENDS_PAGE_SIZE = 5


def friends_listing(uid, offset=0):
    rows = store.friend_birthdays(uid)
    if not rows:
        return ((f'{ui.emoji("birthday", "🎂")} <b>تولد عزیزان</b>\n\nهنوز تولدی ثبت نکرده‌ای.\n'
                 'با افزودن تاریخ تولد عزیزانت، روز تولدشان را فراموش نکن.'),
                ui.inline([[ui.button('➕ افزودن تولد', 'friend:add', 'success')]]))
    offset = max(0, min(int(offset), (len(rows) - 1) // FRIENDS_PAGE_SIZE * FRIENDS_PAGE_SIZE))
    page = rows[offset:offset + FRIENDS_PAGE_SIZE]
    digits = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
    lines = [f'{ui.emoji("birthday", "🎂")} <b>تولد عزیزان</b>']
    buttons = []
    for row in page:
        days_left = cal.remaining(row['month'], row['day'])
        days = str(days_left).translate(digits)
        timing = f'{ui.emoji("birthday", "🎂")} امروز تولدشه!' if days_left == 0 else f'{ui.emoji("until", "⏳")} {days} روز تا تولدش مانده'
        reminder = f'{ui.emoji("on", "🔔")} یادآوری روشن' if row['notification'] else f'{ui.emoji("off", "🔕")} یادآوری خاموش'
        lines.append(f"<b>{escape(row['name'])}</b> — {cal.birthday_text(row['month'], row['day'], row.get('year'))}\n{timing} · {reminder}")
        buttons.append([
            ui.button('🔕 خاموش کردن یادآوری' if row['notification'] else '🔔 روشن کردن یادآوری',
                      f"friend:toggle:{row['id']}:{offset}"),
            ui.button('🗑 حذف', f"friend:del:{row['id']}:{offset}", 'danger'),
        ])
    nav = []
    if offset:
        nav.append(ui.button('⬅️ قبلی', f'friend:list:{max(0, offset - FRIENDS_PAGE_SIZE)}'))
    if offset + FRIENDS_PAGE_SIZE < len(rows):
        nav.append(ui.button('بعدی ➡️', f'friend:list:{offset + FRIENDS_PAGE_SIZE}'))
    if nav:
        buttons.append(nav)
    buttons.append([ui.button('➕ افزودن تولد', 'friend:add', 'success')])
    if len(rows) > FRIENDS_PAGE_SIZE:
        pages = (len(rows) + FRIENDS_PAGE_SIZE - 1) // FRIENDS_PAGE_SIZE
        current = str(offset // FRIENDS_PAGE_SIZE + 1).translate(digits)
        lines.append(f'📄 صفحه {current} از {str(pages).translate(digits)}')
    return '\n\n'.join(lines), ui.inline(buttons)


def parse_friend_reference(data):
    """Extract (friend_id, page_offset) from friend callbacks; None when malformed."""
    parts = data.split(':')
    if len(parts) < 3:
        return None
    try:
        friend_id = int(parts[2])
    except ValueError:
        return None
    offset = 0
    if len(parts) > 3:
        try:
            offset = max(0, int(parts[3]))
        except ValueError:
            offset = 0
    return friend_id, offset


@user_router.callback_query(F.data == 'friend:add')
async def friend_add_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(FriendBirthdayFlow.name)
    await callback.answer()
    await callback.message.answer('✍️ اسم عزیزت را بفرست (حداکثر ۸۰ نویسه). برای لغو /cancel را بزن.')


@user_router.message(FriendBirthdayFlow.name)
async def friend_name(message: Message, state: FSMContext):
    name = ' '.join((message.text or '').split())
    if _cancel_requested(message):
        await state.clear()
        await message.answer('افزودن تولد لغو شد.', reply_markup=ui.home(message.from_user.id))
        return
    if not name or len(name) > 80:
        await message.answer('لطفاً نامی کوتاه‌تر از ۸۰ نویسه بفرست.')
        return
    await state.update_data(friend_name=name)
    await state.set_state(FriendBirthdayFlow.year)
    await message.answer('سال تولدش را با عدد وارد کن (شمسی؛ اعداد فارسی، عربی یا انگلیسی پذیرفته می‌شوند).')


@user_router.message(FriendBirthdayFlow.year)
async def friend_year(message: Message, state: FSMContext):
    if await _cancel_flow(message, state):
        return
    try:
        year = cal.parse_number(message.text)
        if not 1 <= year <= cal.today().year:
            raise ValueError
    except ValueError:
        await message.answer('سال تولد را با عدد معتبر و نه در آینده وارد کن.')
        return
    await state.update_data(friend_year=year)
    await state.set_state(FriendBirthdayFlow.month)
    await message.answer('ماه تولدش را با عدد وارد کن (۱ تا ۱۲).')


@user_router.message(FriendBirthdayFlow.month)
async def friend_month(message: Message, state: FSMContext):
    if await _cancel_flow(message, state):
        return
    try:
        month = cal.parse_number(message.text)
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await message.answer('ماه را با عددی بین ۱ تا ۱۲ وارد کن.')
        return
    await state.update_data(friend_month=month)
    await state.set_state(FriendBirthdayFlow.day)
    await message.answer('روز تولدش را با عدد وارد کن.')


@user_router.message(FriendBirthdayFlow.day)
async def friend_day(message: Message, state: FSMContext):
    if await _cancel_flow(message, state):
        return
    data = await state.get_data()
    try:
        day = cal.parse_number(message.text)
        jdatetime.date(data['friend_year'], data['friend_month'], day)
    except (ValueError, TypeError, KeyError):
        await message.answer('این روز در آن سال و ماه معتبر نیست؛ روز را دوباره با عدد وارد کن.')
        return
    await state.update_data(friend_day=day)
    await state.set_state()
    await message.answer(
        f"{ui.emoji('birthday', '🎂')} تولد <b>{escape(data['friend_name'])}</b>: "
        f"{cal.birthday_text(data['friend_month'], day, data['friend_year'])}\n\n"
        'دوست داری روزهای نزدیک تولدش بهت یادآوری کنم؟', parse_mode='HTML', reply_markup=ui.inline([
            [ui.button('🔔 بله، یادآوری کن', 'friend:notify:1', 'success'),
             ui.button('🔕 بدون یادآوری', 'friend:notify:0', 'primary')]]))


@user_router.callback_query(F.data.startswith('friend:notify:'))
async def friend_save(callback: CallbackQuery, state: FSMContext):
    try:
        enabled = int(callback.data.rsplit(':', 1)[1])
        data = await state.get_data()
        year, month, day, name = (data['friend_year'], data['friend_month'],
                                  data['friend_day'], data['friend_name'])
        if enabled not in (0, 1):
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        await callback.answer('لطفاً دوباره از بخش تولد عزیزان شروع کن.', show_alert=True)
        return
    friend_id = store.add_friend_birthday(callback.from_user.id, name, month, day,
                                          enabled, year=year)
    await state.clear()
    if friend_id is None:
        await callback.answer('حداکثر می‌توانی ۵۰ تولد ثبت کنی.', show_alert=True)
        return
    await callback.answer('ثبت شد!')
    await callback.message.edit_text(
        f"{ui.emoji('on' if enabled else 'off', '🔔' if enabled else '🔕')} "
        f"<b>{escape(name)}</b> — {cal.birthday_text(month, day, year)} ثبت شد.\n"
        + ('یادآوری روزهای نزدیک تولد روشن است.' if enabled else 'یادآوری خاموش است.'), parse_mode='HTML')


@user_router.callback_query(F.data == 'friend:list')
@user_router.callback_query(F.data.startswith('friend:list:'))
async def friend_list(callback: CallbackQuery):
    await callback.answer()
    offset = 0
    if callback.data.startswith('friend:list:'):
        with suppress(ValueError):
            offset = max(0, int(callback.data.rsplit(':', 1)[1]))
    text, keyboard = friends_listing(callback.from_user.id, offset)
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=keyboard)


@user_router.callback_query(F.data.startswith('friend:del:'))
async def friend_delete_prompt(callback: CallbackQuery):
    parsed = parse_friend_reference(callback.data)
    friend = store.friend_birthday(callback.from_user.id, parsed[0]) if parsed else None
    if not friend:
        await callback.answer('تولد پیدا نشد.', show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"🗑 تولد <b>{escape(friend['name'])}</b> حذف شود؟",
        parse_mode='HTML',
        reply_markup=ui.inline([
            [ui.button('🗑 بله، حذف کن', f"friend:delete:{parsed[0]}:{parsed[1]}", 'danger')],
            [ui.button('↩️ انصراف', f'friend:list:{parsed[1]}')]]))


@user_router.callback_query(F.data.startswith('friend:toggle:'))
async def friend_toggle(callback: CallbackQuery):
    parsed = parse_friend_reference(callback.data)
    if not parsed:
        await callback.answer('این مورد معتبر نیست.', show_alert=True)
        return
    friend_id, offset = parsed
    state = store.toggle_friend_notification(callback.from_user.id, friend_id)
    if state is None:
        await callback.answer('تولد پیدا نشد.', show_alert=True)
    else:
        await callback.answer('🔔 یادآوری روشن شد.' if state else '🔕 یادآوری خاموش شد.')
    text, keyboard = friends_listing(callback.from_user.id, offset)
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=keyboard)


@user_router.callback_query(F.data.startswith('friend:delete:'))
async def friend_delete(callback: CallbackQuery):
    parsed = parse_friend_reference(callback.data)
    if not parsed:
        await callback.answer('این مورد معتبر نیست.', show_alert=True)
        return
    friend_id, offset = parsed
    deleted = store.delete_friend_birthday(callback.from_user.id, friend_id)
    await callback.answer('حذف شد.' if deleted else 'تولد پیدا نشد.', show_alert=not deleted)
    text, keyboard = friends_listing(callback.from_user.id, offset)
    await callback.message.edit_text(text, parse_mode='HTML', reply_markup=keyboard)


@user_router.message(Command('help'))
async def help_handler(message: Message):
    await message.answer('''🎂 تولدت را با سال، ماه و روز ثبت کن و روزهای مانده تا آن را ببین.
👥 در بخش تولد عزیزان، تولد خانواده و دوستانت را ذخیره کن.
🗓 مبدل تاریخ، تقویم شمسی و میلادی را تبدیل می‌کند.
🔔 یادآوری تولد در روز تولد و ۱۰، ۷ و ۳ روز مانده فعال می‌شود.

/mybirthday — شمارش معکوس تولد خودت
/setbirthday سال ماه روز — ثبت تاریخ شمسی با عدد فارسی، عربی یا انگلیسی
/deletebirthday — حذف تولد خودت
/friends — دیدن تولدهای عزیزان
/id — شناسه عددی
/cancel — لغو عملیات
/admin — پنل مدیران''')


@user_router.message(Command('cancel'))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('✖️ عملیات جاری لغو شد.', reply_markup=ui.home(message.from_user.id))


@user_router.message(F.text.in_({ui.BTN_REGISTER, '🟢 ثبت تولد', ui.BTN_EDIT}))
async def register_handler(message: Message, state: FSMContext):
    await state.clear()
    current = store.user(message.from_user.id)
    if current and current['month'] and current['day']:
        date = cal.birthday_text(current['month'], current['day'], current.get('birth_year'))
        year_note = '' if current.get('birth_year') else '\nسال در ثبت قبلی ذخیره نشده؛ با تأیید، فقط سال را وارد می‌کنی.'
        await message.answer(
            f'{ui.emoji("birthday", "🎂")} <b>تاریخ تولد ثبت‌شده‌ات</b>\n{date}{year_note}\n\n'
            'این تاریخ درسته؟', parse_mode='HTML', reply_markup=ui.inline([[
                ui.button('✅ تأیید', 'mybirthday:confirm', 'success', key='on'),
                ui.button('✏️ تغییر تاریخ تولد', 'mybirthday:change', 'primary', key='edit')
            ]]))
        return
    await ask_birthday_year(message, state)


async def ask_birthday_year(message, state, existing_month=None, existing_day=None):
    if existing_month is not None and existing_day is not None:
        await state.update_data(existing_birthday=True, existing_month=existing_month,
                                existing_day=existing_day)
    await state.set_state(MyBirthdayFlow.year)
    await message.answer('سال تولدت رو با عدد وارد کن (شمسی؛ اعداد فارسی، عربی یا انگلیسی پذیرفته می‌شن).')


@user_router.callback_query(F.data == 'mybirthday:confirm')
async def confirm_birthday(callback: CallbackQuery, state: FSMContext):
    current = store.user(callback.from_user.id)
    if not current or not current['month'] or not current['day']:
        await callback.answer('تاریخی برای تأیید پیدا نشد.', show_alert=True)
        return
    if current.get('birth_year'):
        await callback.answer('تاریخ تولدت تأیید شد.')
        await callback.message.edit_text(
            f'{ui.emoji("on", "✅")} تاریخ تولدت تأیید شد: '
            f'<b>{cal.birthday_text(current["month"], current["day"], current["birth_year"])}</b>',
            parse_mode='HTML', reply_markup=ui.inline([]))
        return
    await callback.answer()
    await state.update_data(existing_birthday=True, existing_month=current['month'],
                            existing_day=current['day'])
    await state.set_state(MyBirthdayFlow.year)
    await callback.message.edit_text(
        f'{ui.emoji("birthday", "🎂")} تاریخ ثبت‌شده: '
        f'<b>{cal.birthday_text(current["month"], current["day"])}</b>\n'
        'فقط سال شمسی تولدت رو با عدد بفرست تا به همین تاریخ اضافه بشه.', parse_mode='HTML',
        reply_markup=ui.inline([]))


@user_router.callback_query(F.data == 'mybirthday:change')
async def change_birthday(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(MyBirthdayFlow.year)
    await callback.message.edit_text(
        'سال تولدت رو با عدد وارد کن (شمسی؛ اعداد فارسی، عربی یا انگلیسی پذیرفته می‌شن).',
        reply_markup=ui.inline([]))


@user_router.message(MyBirthdayFlow.year)
async def my_birthday_year(message: Message, state: FSMContext, bot):
    if await _cancel_flow(message, state):
        return
    try:
        year = cal.parse_number(message.text)
        if not 1 <= year <= cal.today().year:
            raise ValueError
    except ValueError:
        await message.answer('سال تولد رو با عدد معتبر و نه در آینده وارد کن.')
        return
    data = await state.get_data()
    if data.get('existing_birthday'):
        month, day = data['existing_month'], data['existing_day']
        try:
            jdatetime.date(year, month, day)
        except ValueError:
            await message.answer('این روز در سالی که فرستادی وجود نداره. سال درست رو بفرست یا «تغییر تاریخ تولد» رو انتخاب کن.')
            return
        await state.clear()
        await save_birthday(message, message.from_user.id, year, month, day, bot,
                            notification=None)
        return
    await state.update_data(birthday_year=year)
    await state.set_state(MyBirthdayFlow.month)
    await message.answer('ماه تولدت رو با عدد وارد کن (۱ تا ۱۲).')


@user_router.message(MyBirthdayFlow.month)
async def my_birthday_month(message: Message, state: FSMContext):
    if await _cancel_flow(message, state):
        return
    try:
        month = cal.parse_number(message.text)
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await message.answer('ماه رو با عددی بین ۱ تا ۱۲ وارد کن.')
        return
    await state.update_data(birthday_month=month)
    await state.set_state(MyBirthdayFlow.day)
    await message.answer('روز تولدت رو با عدد وارد کن.')


@user_router.message(MyBirthdayFlow.day)
async def my_birthday_day(message: Message, state: FSMContext, bot):
    if await _cancel_flow(message, state):
        return
    data = await state.get_data()
    try:
        day = cal.parse_number(message.text)
        jdatetime.date(data['birthday_year'], data['birthday_month'], day)
    except (ValueError, TypeError, KeyError):
        await message.answer('این روز در آن سال و ماه معتبر نیست؛ روز رو دوباره با عدد وارد کن.')
        return
    await state.clear()
    current = store.user(message.from_user.id)
    notification = None if current and current['month'] else 1
    await save_birthday(message, message.from_user.id, data['birthday_year'],
                        data['birthday_month'], day, bot, notification=notification)


async def save_birthday(message, uid, year, month, day, bot, notification=1):
    changes = {'birth_year': year, 'month': month, 'day': day}
    if notification is not None:
        changes['notification'] = notification
    store.update_user(uid, **changes)
    days = cal.remaining(month, day)
    text = f'{ui.emoji("on", "✅")} <b>تولدت ثبت شد!</b>\n\n{ui.emoji("birthday", "🎂")} {cal.birthday_text(month, day, year)}\n'
    text += f'{ui.emoji("birthday", "🎂")} امروز روز توئه؛ تولدت مبارک!' if days==0 else f'{ui.emoji("until", "⏳")} <b>{days} روز</b> تا جشن تولدت!'
    if message is None:
        await bot.send_message(uid, text, parse_mode='HTML', reply_markup=ui.home(uid))
    else:
        await message.answer(text, parse_mode='HTML', reply_markup=ui.home(uid))
    await notify_admin(bot, f'🎂 تولد ثبت شد.\nشناسه: <code>{uid}</code>\n{cal.birthday_text(month, day)}', uid)


@user_router.callback_query(F.data.in_({'set_birthday', 'back_to_months'}))
@user_router.callback_query(F.data.startswith('month:'))
@user_router.callback_query(F.data.startswith('day:'))
async def obsolete_birthday_keyboard(callback: CallbackQuery):
    await callback.answer('برای ثبت تاریخ، دکمهٔ ثبت تولد را دوباره بزن و سال، ماه و روز را با عدد وارد کن.', show_alert=True)


@user_router.callback_query(F.data == 'user:home')
@user_router.callback_query(F.data == 'check_join')
async def home_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer('✅ آماده‌ای!')
    await state.clear()
    await greet(callback.message, callback.from_user.id)


@user_router.message(Command('setbirthday'))
async def setbirthday_command(message: Message, bot):
    try:
        _, year, month, day = message.text.split()
        year, month, day = map(cal.parse_number, (year, month, day))
        if year > cal.today().year:
            raise ValueError
        jdatetime.date(year, month, day)
    except ValueError:
        await message.answer('فرمت: /setbirthday سال ماه روز\nمثال شمسی: /setbirthday ۱۳۷۰ ۷ ۲۵')
        return
    await save_birthday(message, message.from_user.id, year, month, day, bot)


@user_router.message(F.text.in_({ui.BTN_OFF, ui.BTN_ON}))
async def notification_handler(message: Message):
    uid = message.from_user.id
    u = store.user(uid)
    if not u['month']:
        await message.answer('اول تولدت رو ثبت کن 🎂', reply_markup=ui.home(uid))
        return
    enabled = message.text == ui.BTN_ON
    store.update_user(uid, notification=int(enabled))
    text = f'{ui.emoji("on", "🔔")} اعلان‌های تولدت فعال شد.' if enabled else f'{ui.emoji("off", "🔕")} اعلان‌های تولدت خاموش شد.'
    await message.answer(text, parse_mode='HTML', reply_markup=ui.home(uid))


@user_router.message(Command('mybirthday'))
@user_router.message(F.text.in_({ui.BTN_UNTIL, ui.BTN_SINCE}))
async def birthday_handler(message: Message):
    u = store.user(message.from_user.id)
    if not u['month']:
        await message.answer('هنوز تولدت رو ثبت نکردی 🎂', reply_markup=ui.home(message.from_user.id))
        return
    since = message.text == ui.BTN_SINCE
    days = cal.elapsed(u['month'],u['day']) if since else cal.remaining(u['month'],u['day'])
    text = f'{ui.emoji("birthday", "🎂")} <b>{cal.birthday_text(u["month"], u["day"], u.get("birth_year"))}</b>\n\n'
    text += f'{ui.emoji("since", "📅")} {days} روز از آخرین تولدت گذشته.' if since else (f'{ui.emoji("birthday", "🎂")} تولدت مبارک! امروز روز توئه!' if days==0 else f'{ui.emoji("until", "⏳")} فقط <b>{days} روز</b> تا تولدت!')
    await message.answer(text, parse_mode='HTML', reply_markup=ui.home(message.from_user.id))


@user_router.message(Command('deletebirthday'))
async def deletebirthday_handler(message: Message):
    await message.answer('تاریخ تولد و اعلان‌هایت حذف شود؟', reply_markup=ui.inline([
        [ui.button('🗑 حذف تولد', 'user:delete', 'danger')], [ui.button('↩️ انصراف', 'user:home')]]))


@user_router.callback_query(F.data == 'user:delete')
async def delete_callback(callback: CallbackQuery):
    store.update_user(callback.from_user.id, birth_year=None, month=None, day=None, notification=0)
    await callback.answer('حذف شد')
    await callback.message.edit_text('✅ تاریخ تولدت حذف شد.')
    await callback.message.answer('هر وقت خواستی، دوباره ثبتش کن 🎂', reply_markup=ui.home(callback.from_user.id))


@user_router.message()
async def fallback(message: Message):
    await message.answer('✨ از دکمه‌ها یک گزینه انتخاب کن؛ برای راهنما /help بفرست.', reply_markup=ui.home(message.from_user.id))


@user_router.edited_message()
async def edited_message(message: Message):
    pass


@user_router.my_chat_member()
async def bot_membership(event):
    if event.chat.type not in ('group','supergroup'):
        return
    with store.connection() as c:
        c.execute('''INSERT INTO bot_groups(id,title,username,first_seen,last_seen,bot_status)
            VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
            username=excluded.username,last_seen=excluded.last_seen,bot_status=excluded.bot_status''',
            (event.chat.id, event.chat.title or '', event.chat.username, store.now(), store.now(), event.new_chat_member.status))


dp.include_router(user_router)


async def _run_bot():
    logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    # HTTP request URLs include bot tokens in some libraries. Never log them.
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    async with Bot(token=config.BOT_TOKEN) as bot:
        bot.session.middleware(ui.EmojiFallback())
        info = await bot.get_webhook_info()
        if info.url:
            raise RuntimeError('An active webhook prevents local polling. Remove it explicitly before running.')
        me = await bot.get_me()
        log.info('Bot connected: @%s; group privacy disabled: %s', me.username, me.can_read_all_group_messages)
        if store.setting('custom_emoji', '0') == '1' and not store.setting('emoji_alts'):
            try:
                stickers = await bot.get_custom_emoji_stickers(list(ui.EMOJIS.values()))
                alts = {s.custom_emoji_id: s.emoji for s in stickers if s.custom_emoji_id and s.emoji}
                store.set_setting('emoji_alts', json.dumps(alts, ensure_ascii=False))
                if not alts:
                    store.set_setting('custom_emoji', '0')
            except TelegramAPIError:
                store.set_setting('custom_emoji', '0')
                log.warning('Custom emoji lookup unavailable; using text without icons')
        try:
            async def mini_app_birthday_saved(uid, year, month, day, notification):
                await save_birthday(None, uid, year, month, day, bot, int(notification))

            api_runner = await webapp_api.start(mini_app_birthday_saved)
            log.info('Mini App profile API listening on %s:%s',
                     config.WEBAPP_API_HOST, config.WEBAPP_API_PORT)
        except OSError:
            api_runner = None
            log.exception('Mini App profile API could not start; profile and friends data will be unavailable')
        tasks = [asyncio.create_task(runtime_jobs.supervised(worker, bot))
                 for worker in (runtime_jobs.delivery_worker, runtime_jobs.reminder_worker,
                                runtime_jobs.backup_worker)]
        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                close_bot_session=False,
                tasks_concurrency_limit=config.UPDATE_CONCURRENCY,
            )
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            if api_runner:
                await api_runner.cleanup()


async def main():
    try:
        store.init()
        await _run_bot()
    except Exception as exc:
        try:
            store.record_error('startup', f'{type(exc).__name__}: {exc}')
        except Exception:
            log.exception('Could not persist startup error')
        raise
    finally:
        store.close_connection()


if __name__ == '__main__':
    asyncio.run(main())
