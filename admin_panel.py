"""Private, authenticated administration router."""
import csv
import io
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import calendar_utils as cal
import config
import store
import ui

router = Router(name='administration')


def admin_button(text, data, color='primary'):
    return ui.button(text, data, color)


def admin_keyboard(rows):
    return ui.inline(rows)


class AdminFlow(StatesGroup):
    input = State()
    content = State()


def back():
    return [admin_button('↩️ پنل مدیریت', 'adm:home')]


def cancel_keyboard():
    return ui.inline([[ui.button('✖️ لغو', 'adm:home', 'danger')]])


def dashboard():
    return admin_keyboard([
        [ui.button('📊 آمار دقیق', 'adm:stats', 'success'), ui.button('👥 کاربران', 'adm:users:0')],
        [ui.button('🔒 قفل کانال', 'adm:channel'), ui.button('📣 پیام همگانی', 'adm:broadcast', 'success')],
        [ui.button('✉️ پیام به کاربر', 'adm:prompt:direct'), ui.button('📨 گزارش ارسال‌ها', 'adm:jobs')],
        [ui.button('👁 گروه‌ها و پیام‌ها', 'adm:groups:0'), ui.button('⚙️ تنظیمات', 'adm:settings')],
        [ui.button('🛡 مدیران', 'adm:admins'), ui.button('📁 خروجی کاربران', 'adm:export')],
        [ui.button('📋 گزارش مدیریت', 'adm:audit')],
        [admin_button('Recent errors', 'adm:errors', 'primary')],
    ])


async def render(callback, text, keyboard):
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    except TelegramBadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            raise


async def show_home(message):
    await message.answer('🛠 <b>مرکز مدیریت ربات</b>\n\nبخش موردنظر را انتخاب کنید.',
                         reply_markup=dashboard(), parse_mode='HTML')


@router.message(Command('admin'), F.chat.type == 'private')
@router.message(F.text == ui.BTN_ADMIN, F.chat.type == 'private')
async def admin_entry(message: Message, state: FSMContext):
    if message.from_user.id not in store.admins():
        await message.answer('⛔ دسترسی به پنل مدیریت ندارید.')
        return
    await state.clear()
    await show_home(message)


def stats_text():
    today, week = cal.stat_boundaries()
    d = cal.today()
    s = store.stats(today, week, d.month, d.day)
    return (f'📊 <b>آمار ربات</b> · {d}\n\n'
            f'👥 کل کاربران خصوصی: <b>{s["total"]}</b>\n'
            f'🆕 کاربران جدید امروز / ۷ روز: {s["new_today"]} / {s["new_week"]}\n'
            f'🟢 فعال امروز / ۷ روز: {s["active_today"]} / {s["active_week"]}\n'
            f'🎂 تولدهای ثبت‌شده: {s["birthdays"]}\n'
            f'🎉 تولد امروز / این ماه شمسی: {s["birthday_today"]} / {s["birthday_month"]}\n'
            f'🔔 اعلان فعال و قابل ارسال: {s["notifications"]}\n'
            f'🚫 بلاک تلگرام / مسدود در ربات: {s["blocked"]} / {s["banned"]}\n'
            f'💬 پیام / کلیک امروز: {s["messages_today"]} / {s["callbacks_today"]}\n'
            f'👁 گروه‌های دیده‌شده: {s["groups"]}\n'
            f'📝 پیام‌های گروه دریافت‌شده: {s["group_messages"]}\n'
            f'📨 ارسال مدیریتی موفق / ناموفق: {s["sent"]} / {s["failed"]}\n\n'
            f'🕒 مبنای روز: {escape(config.TIMEZONE)}\n'
            f'اطلاعات فعالیت از زمان نصب این پنل ثبت می‌شود. '
            f'{s["imported"]} کاربر از نسخه قبلی با تاریخ ورود نامعلوم منتقل شده‌اند. '
            'بلاک تلگرام هنگام تلاش ارسال مشخص می‌شود.')


def user_text(u):
    birthday = cal.birthday_text(u['month'], u['day']) if u['month'] else 'ثبت نشده'
    return (f'👤 <b>{ui.safe_name(u["name"])}</b>\n'
            f'شناسه: <code>{u["id"]}</code>\nنام کاربری: {escape(u["username"] or "ندارد")}\n'
            f'🎂 تولد: {birthday}\n🔔 اعلان: {"فعال" if u["notification"] else "خاموش"}\n'
            f'بلاک تلگرام: {"بله" if u["blocked"] else "خیر"}\n'
            f'مسدود در ربات: {"بله" if u["banned"] else "خیر"}\n'
            f'اولین ورود (UTC): {escape(u["first_seen"] or "نامعلوم؛ انتقال از نسخه قبل")}\n'
            f'آخرین فعالیت (UTC): {escape(u["last_seen"] or "نامعلوم")}')


def error_page():
    records = store.recent_errors(8)
    lines = ['<b>Recent errors</b>']
    if not records:
        lines.append('\nNo recorded errors.')
    else:
        for error in records:
            lines.append(
                f'\n<code>{escape(error["created_at"][:19])}</code> | '
                f'<b>{escape(error["source"])}</b>\n{escape(error["detail"][:220])}')
    keyboard = admin_keyboard([
        [admin_button('Refresh', 'adm:errors', 'primary')],
        [admin_button('Clear', 'adm:errors_clear', 'danger')],
        back(),
    ])
    return '\n'.join(lines), keyboard


PROMPTS = {
    'channel': '🔒 کانال عمومی را به شکل @channel بفرستید.\nبرای کانال خصوصی: شناسه عددی کانال و لینک دعوت را با فاصله بفرستید.\nربات باید ادمین کانال باشد.',
    'direct': '✉️ آیدی عددی کاربری که ربات را استارت کرده وارد کنید.',
    'search': '🔎 آیدی عددی کاربر را وارد کنید.',
    'welcome': 'متن خوشامدگویی جدید را بفرستید (حداکثر ۳۰۰۰ نویسه). می‌توانید از {name} استفاده کنید؛ ایموجی‌های معمولی هنگام ارسال به نسخه پریمیوم تبدیل می‌شوند.',
    'group_date_reply': 'متن پاسخ گروه را بفرستید. متغیرها: {since} {date} {birthday} (حداکثر ۳۰۰۰ نویسه).',
    'group_date_keywords': 'کلمات کلیدی پاسخ تاریخ در گروه را با کاما جدا کنید (حداکثر ۲۰۰ نویسه).\nنمونه: تاریخ,تولدم,تولد من',
    'birthday_hint': 'متن راهنمای ثبت تولد را بفرستید (حداکثر ۵۰۰ نویسه).',
    'reminder_time': '🕒 ساعت یادآوری را با فرمت 09:00 وارد کنید.',
    'send_rate': '🚀 حداکثر تعداد ارسال در ثانیه را از ۱ تا ۲۵ وارد کنید.',
    'admin_add': '🛡 آیدی عددی ادمین جدید را وارد کنید.',
    'admin_remove': '🛡 آیدی عددی ادمینی که می‌خواهید حذف کنید را وارد کنید. ادمین‌های .env قابل حذف نیستند.',
}


@router.callback_query(F.data.startswith('adm:'))
async def admin_callback(callback: CallbackQuery, state: FSMContext, bot):
    aid = callback.from_user.id
    if aid not in store.admins() or not callback.message or callback.message.chat.type != 'private':
        await callback.answer('⛔ دسترسی غیرمجاز', show_alert=True)
        return
    await callback.answer()
    parts = callback.data.split(':')
    action = parts[1]
    if action != 'admin_confirm':
        await state.clear()
    if action == 'home':
        await state.clear()
        await render(callback, '🛠 <b>مرکز مدیریت ربات</b>\n\nبخش موردنظر را انتخاب کنید.', dashboard())
    elif action == 'stats':
        await render(callback, stats_text(), ui.inline([[ui.button('🔄 تازه‌سازی', 'adm:stats', 'success')], back()]))
    elif action == 'users':
        offset = max(0, int(parts[2]))
        users = store.list_users(offset, 10)
        rows = [[ui.button(f'{u["id"]} · {u["name"][:25]}', f'adm:user:{u["id"]}')] for u in users]
        nav = []
        if offset:
            nav.append(ui.button('⬅️ قبلی', f'adm:users:{max(0, offset-10)}'))
        if len(users) == 10:
            nav.append(ui.button('بعدی ➡️', f'adm:users:{offset+10}'))
        if nav:
            rows.append(nav)
        rows.extend([[ui.button('🔎 جستجوی شناسه', 'adm:prompt:search')], back()])
        await render(callback, f'👥 <b>کاربران</b> · صفحه {offset//10+1}', ui.inline(rows))
    elif action == 'user':
        uid = int(parts[2])
        u = store.user(uid)
        if not u:
            await callback.message.answer('کاربر پیدا نشد.')
            return
        rows = [[ui.button('✉️ ارسال پیام', f'adm:direct:{uid}', 'success')],
                [ui.button('🔔 تغییر اعلان', f'adm:unotify:{uid}')],
                [ui.button('✅ رفع مسدودی' if u['banned'] else '🚫 مسدود کردن', f'adm:ban:{uid}', 'danger')],
                [ui.button('👥 فهرست کاربران', 'adm:users:0')], back()]
        await render(callback, user_text(u), ui.inline(rows))
    elif action in ('ban', 'unotify'):
        uid = int(parts[2])
        u = store.user(uid)
        if not u:
            return
        if action == 'ban' and uid in store.admins():
            await callback.message.answer('ادمین را نمی‌توان مسدود کرد.')
            return
        key = 'banned' if action == 'ban' else 'notification'
        store.update_user(uid, **{key: 1-int(u[key])})
        store.audit(aid, action, uid)
        await callback.message.answer('✅ وضعیت کاربر به‌روز شد.', reply_markup=ui.inline([[ui.button('👤 مشاهده کاربر', f'adm:user:{uid}')]]))
    elif action == 'channel':
        channel = store.setting('required_channel', 'تنظیم نشده')
        enabled = store.setting('channel_lock', '0') == '1'
        await render(callback, f'🔒 <b>قفل عضویت کانال</b>\n\nکانال: {escape(channel)}\nوضعیت: {"فعال" if enabled else "خاموش"}',
            ui.inline([[ui.button('✏️ تغییر کانال', 'adm:prompt:channel')],
                       [ui.button('🔓 خاموش کردن' if enabled else '🔒 فعال کردن', 'adm:lock', 'danger' if enabled else 'success')], back()]))
    elif action == 'lock':
        if store.setting('channel_lock', '0') == '1':
            store.set_setting('channel_lock', '0')
        else:
            channel = store.setting('required_channel')
            if not channel:
                await callback.message.answer('ابتدا کانال را تنظیم کنید.')
                return
            try:
                target = int(channel) if channel.lstrip('-').isdigit() else channel
                member = await bot.get_chat_member(target, bot.id)
                if member.status not in ('administrator', 'creator'):
                    raise ValueError()
            except (TelegramAPIError, ValueError):
                await callback.message.answer('فعال‌سازی ممکن نیست؛ دسترسی ادمین ربات در کانال را بررسی کنید.')
                return
            store.set_setting('channel_lock', '1')
        store.audit(aid, 'channel_lock', store.setting('channel_lock'))
        await callback.message.answer('✅ وضعیت قفل تغییر کرد.', reply_markup=ui.inline([[ui.button('🔒 تنظیمات کانال', 'adm:channel')]]))
    elif action == 'prompt':
        mode = parts[2]
        if mode.startswith('admin_') and aid not in config.ADMIN_IDS:
            await callback.message.answer('مدیریت ادمین‌ها فقط برای مالک اصلی فعال است.')
            return
        await state.set_state(AdminFlow.input)
        await state.set_data({'mode': mode})
        await callback.message.answer(PROMPTS[mode], reply_markup=cancel_keyboard())
    elif action in ('broadcast', 'direct'):
        if action == 'direct':
            u = store.user(int(parts[2]))
            if not u or u['blocked'] or u['banned']:
                await callback.message.answer('کاربر در دسترس نیست؛ باید ربات را استارت کرده باشد و مسدود نباشد.')
                return
        await state.set_state(AdminFlow.content)
        await state.set_data({'target': int(parts[2]) if action == 'direct' else None})
        await callback.message.answer('📨 پیام موردنظر را ارسال کنید؛ متن، عکس، ویدیو، فایل یا صدا پذیرفته می‌شود.\nپیش از ارسال، پیش‌نمایش و تأیید نمایش داده می‌شود.', reply_markup=cancel_keyboard())
    elif action in ('send', 'discard'):
        jid = int(parts[2])
        job = store.job(jid)
        if not job or job['admin_id'] != aid or job['status'] != 'draft':
            await callback.message.answer('این پیش‌نمایش قبلاً استفاده شده یا متعلق به شما نیست.')
            return
        if action == 'discard':
            with store.connection() as c:
                c.execute("UPDATE bot_jobs SET status='cancelled' WHERE id=?", (jid,))
            await render(callback, '✖️ ارسال لغو شد.', ui.inline([back()]))
        else:
            if store.enqueue(jid, aid):
                store.audit(aid, 'send_message', jid)
                counts = store.job_counts(jid)
                await render(callback, f'📨 ارسال #{jid} برای {counts["total"]} کاربر در صف قرار گرفت.',
                             ui.inline([[ui.button('📊 پیگیری', 'adm:jobs')], back()]))
        await state.clear()
    elif action == 'jobs':
        with store.connection() as c:
            jobs = c.execute('SELECT * FROM bot_jobs WHERE admin_id=? ORDER BY id DESC LIMIT 8', (aid,)).fetchall()
        lines, rows = ['📨 <b>ارسال‌های اخیر</b>'], []
        labels = {'draft':'منتظر تأیید', 'queued':'در صف', 'running':'در حال ارسال', 'done':'تمام‌شده', 'cancelled':'لغوشده'}
        for j in jobs:
            counts = store.job_counts(j['id'])
            lines.append(f'#{j["id"]} · {labels.get(j["status"], j["status"])}\n✅ {counts["sent"]}  ❌ {counts["failed"]}  ⏳ {counts["pending"]}')
            if j['status'] in ('running', 'queued'):
                rows.append([ui.button(f'✖️ توقف ارسال #{j["id"]}', f'adm:stop:{j["id"]}', 'danger')])
            if counts['failed'] and j['status'] in ('done', 'cancelled'):
                rows.append([ui.button(f'🔁 تلاش مجدد ناموفق‌ها #{j["id"]}', f'adm:retry:{j["id"]}')])
        rows.extend([[ui.button('🔄 تازه‌سازی', 'adm:jobs')], back()])
        await render(callback, '\n\n'.join(lines), ui.inline(rows))
    elif action == 'retry':
        jid = int(parts[2])
        moved = store.requeue_failed(jid, aid)
        if not moved:
            await callback.message.answer('موردی برای تلاش مجدد نیست؛ ممکن است ارسال‌های ناموفق این کار متعلق به شما نباشد.')
            return
        store.audit(aid, 'retry_failed', f'{jid}:{moved}')
        await callback.message.answer(f'🔁 {moved} ارسال ناموفق دوباره در صف قرار گرفت.',
                                      reply_markup=ui.inline([[ui.button('📨 گزارش ارسال‌ها', 'adm:jobs')]]))
    elif action == 'stop':
        jid = int(parts[2])
        with store.connection() as c:
            c.execute("UPDATE bot_jobs SET status='cancelled' WHERE id=? AND admin_id=? AND status IN ('queued','running')", (jid, aid))
        store.audit(aid, 'stop_send', jid)
        await callback.message.answer('✖️ ارسال‌های باقی‌مانده متوقف شدند؛ پیام‌های ارسال‌شده باقی می‌مانند.')
    elif action == 'settings':
        switches = [('maintenance', '🚧 توقف خدمات کاربران', '0'), ('reminders_enabled', '🔔 یادآوری روزانه', '0'),
                    ('notify_admin', '🔔 خبر ورود کاربران', '0'), ('group_reading', '👁 دریافت پیام گروه', '1'), ('custom_emoji', '✨ ایموجی پریمیوم', '0')]
        rows = [[ui.button(f'{label}: {"روشن" if store.setting(key, default)=="1" else "خاموش"}', f'adm:toggle:{key}')]
                for key, label, default in switches]
        rows.extend([[ui.button('✏️ متن خوشامد', 'adm:prompt:welcome'), ui.button('🗓 پاسخ تاریخ گروه', 'adm:prompt:group_date_reply')],
                     [ui.button('🎂 راهنمای ثبت تولد', 'adm:prompt:birthday_hint'), ui.button('💬 کلمات کلیدی تاریخ', 'adm:prompt:group_date_keywords')],
                     [ui.button('🕒 ساعت یادآوری', 'adm:prompt:reminder_time'), ui.button('🚀 سرعت ارسال', 'adm:prompt:send_rate')], back()])
        await render(callback, '⚙️ <b>تنظیمات ربات</b>\n\n'
            f'یادآوری: {store.setting("reminder_time", f"{config.REMINDER_HOUR:02}:{config.REMINDER_MINUTE:02}")} · {escape(config.TIMEZONE)}\n'
            f'سرعت: {store.setting("send_rate", str(config.SEND_RATE))} پیام/ثانیه\n'
            'ایموجی پریمیوم به مجوز تلگرام برای بات وابسته است؛ در صورت خطا آیکن حذف می‌شود و متن باقی می‌ماند.', ui.inline(rows))
    elif action == 'toggle':
        key = parts[2]
        defaults = {'maintenance':'0', 'reminders_enabled':'0', 'notify_admin':'0', 'group_reading':'1', 'custom_emoji':'0'}
        if key not in defaults:
            return
        store.set_setting(key, '0' if store.setting(key, defaults[key]) == '1' else '1')
        store.audit(aid, 'setting', key)
        await callback.message.answer('✅ تنظیم تغییر کرد.', reply_markup=ui.inline([[ui.button('⚙️ تنظیمات', 'adm:settings')]]))
    elif action == 'admins':
        text = '🛡 <b>مدیران ربات</b>\n\n' + '\n'.join(f'<code>{uid}</code>' + (' · مالک' if uid in config.ADMIN_IDS else '') for uid in sorted(store.admins()))
        rows = []
        if aid in config.ADMIN_IDS:
            rows = [[ui.button('➕ افزودن مدیر', 'adm:prompt:admin_add', 'success'), ui.button('➖ حذف مدیر', 'adm:prompt:admin_remove', 'danger')]]
        await render(callback, text, ui.inline([*rows, back()]))
    elif action == 'admin_confirm':
        if aid not in config.ADMIN_IDS:
            return
        data = await state.get_data()
        mode, uid = data.get('admin_mode'), data.get('admin_uid')
        if mode not in ('admin_add', 'admin_remove') or not uid:
            await callback.message.answer('درخواست منقضی شده؛ دوباره شروع کنید.')
            return
        with store.connection() as c:
            if mode == 'admin_add':
                c.execute('INSERT OR IGNORE INTO bot_admins VALUES(?)', (uid,))
                c.execute('UPDATE bot_users SET banned=0 WHERE id=?', (uid,))
            elif uid not in config.ADMIN_IDS:
                c.execute('DELETE FROM bot_admins WHERE id=?', (uid,))
        store.audit(aid, mode, uid)
        await state.clear()
        await render(callback, '✅ دسترسی مدیر به‌روز شد.', ui.inline([[ui.button('🛡 مدیران', 'adm:admins')], back()]))
    elif action == 'groups':
        offset = max(0, int(parts[2]))
        groups = store.groups()
        rows = [[ui.button(f'{g["title"][:30]} · {g["messages"]}', f'adm:group:{g["id"]}:0')] for g in groups[offset:offset+8]]
        nav = []
        if offset:
            nav.append(ui.button('⬅️ قبلی', f'adm:groups:{max(0,offset-8)}'))
        if offset+8 < len(groups):
            nav.append(ui.button('بعدی ➡️', f'adm:groups:{offset+8}'))
        if nav:
            rows.append(nav)
        await render(callback, '👁 <b>گروه‌ها</b>\n\nفقط پیام‌هایی که تلگرام از زمان اجرای این نسخه به بات تحویل می‌دهد قابل مشاهده‌اند.\nبرای دریافت همه پیام‌ها، بات را ادمین گروه کنید یا Privacy Mode را در BotFather خاموش کنید.\nآخرین ۱۰۰۰ پیام هر گروه نگه داشته می‌شود.', ui.inline([*rows, back()]))
    elif action == 'group':
        gid, offset = int(parts[2]), max(0, int(parts[3]))
        g = next((g for g in store.groups() if g['id'] == gid), None)
        if not g:
            return
        lines = [(f'👁 <b>{escape(g["title"])}</b>\nشناسه: <code>{gid}</code>\n'
                  f'ثبت پیام: {"روشن" if g["enabled"] else "خاموش"} · دریافت‌شده: {g["messages"]}')]
        rows = []
        messages = store.group_messages(gid, offset)
        for m in messages:
            lines.append(f'👤 {escape(m["name"])} · <code>{m["user_id"]}</code>\n'
                         f'{escape(m["body"][:450]) or "["+escape(m["kind"])+"]"}')
            rows.append([ui.button(f'📩 مشاهده اصل پیام {m["message_id"]}', f'adm:gcopy:{gid}:{m["message_id"]}')])
        nav = []
        if offset:
            nav.append(ui.button('⬅️ جدیدتر', f'adm:group:{gid}:{max(0,offset-5)}'))
        if len(messages) == 5:
            nav.append(ui.button('قدیمی‌تر ➡️', f'adm:group:{gid}:{offset+5}'))
        if nav:
            rows.append(nav)
        rows.extend([[ui.button('🔄 تازه‌سازی', f'adm:group:{gid}:{offset}')],
                     [ui.button('🔕 توقف ثبت' if g['enabled'] else '🔔 فعال‌سازی ثبت', f'adm:gtoggle:{gid}', 'danger' if g['enabled'] else 'success')],
                     [ui.button('👁 گروه‌ها', 'adm:groups:0')], back()])
        await render(callback, '\n\n'.join(lines), ui.inline(rows))
    elif action == 'gtoggle':
        gid = int(parts[2])
        with store.connection() as c:
            c.execute('UPDATE bot_groups SET enabled=1-enabled WHERE id=?', (gid,))
        store.audit(aid, 'group_toggle', gid)
        await callback.message.answer('✅ وضعیت ثبت پیام گروه تغییر کرد.', reply_markup=ui.inline([[ui.button('👁 گروه', f'adm:group:{gid}:0')]]))
    elif action == 'gcopy':
        gid, mid = int(parts[2]), int(parts[3])
        with store.connection() as c:
            exists = c.execute('SELECT 1 FROM bot_group_messages WHERE chat_id=? AND message_id=?', (gid,mid)).fetchone()
        if not exists:
            return
        try:
            await bot.copy_message(aid, gid, mid)
        except TelegramAPIError:
            await callback.message.answer('اصل پیام در دسترس نیست؛ ممکن است حذف شده یا محتوا محافظت‌شده باشد. متن ثبت‌شده در پنل قابل مشاهده است.')
    elif action == 'export':
        output = io.StringIO()
        writer = csv.writer(output)
        fields = ['id','name','username','month','day','notification','blocked','banned','first_seen','last_seen']
        writer.writerow(fields)
        for u in store.all_users():
            writer.writerow([csv_cell(u[k]) for k in fields])
        await callback.message.answer_document(BufferedInputFile(output.getvalue().encode('utf-8-sig'), filename='bot-users.csv'), caption='📁 خروجی کاربران')
        store.audit(aid, 'export_users')
    elif action == 'errors':
        text, keyboard = error_page()
        await render(callback, text, keyboard)
    elif action == 'errors_clear':
        await render(callback, 'Clear the recent error history?', admin_keyboard([
            [admin_button('Confirm clear', 'adm:errors_clear_confirm', 'danger')],
            [admin_button('Cancel', 'adm:errors', 'primary')],
        ]))
    elif action == 'errors_clear_confirm':
        removed = store.clear_errors()
        store.audit(aid, 'clear_errors', removed)
        await render(callback, f'Cleared {removed} error records.', admin_keyboard([
            [admin_button('Recent errors', 'adm:errors', 'primary')],
            back(),
        ]))
    elif action == 'audit':
        with store.connection() as c:
            records = c.execute('SELECT * FROM bot_audit ORDER BY id DESC LIMIT 12').fetchall()
        text = '📋 <b>آخرین عملیات مدیران</b>\n\n' + '\n\n'.join(
            f'{escape(r["created_at"][:19])} UTC · {r["admin_id"]}\n{escape(r["action"])} · {escape(r["detail"])}' for r in records)
        await render(callback, text, ui.inline([back()]))


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


@router.message(StateFilter(AdminFlow.input), F.chat.type == 'private', ~F.text.startswith('/'))
async def admin_input(message: Message, state: FSMContext, bot):
    aid = message.from_user.id
    if aid not in store.admins():
        await state.clear()
        return
    text = (message.text or '').strip()
    data = await state.get_data()
    mode = data.get('mode')
    try:
        if mode == 'channel':
            items = text.split()
            channel = items[0]
            if not channel.startswith('@') and not (channel.startswith('-100') and channel[1:].isdigit()):
                raise ValueError('کانال باید @username یا شناسه -100 باشد.')
            target = int(channel) if channel.startswith('-100') else channel
            chat = await bot.get_chat(target)
            if chat.type != 'channel':
                raise ValueError('مقصد باید کانال باشد.')
            member = await bot.get_chat_member(chat.id, bot.id)
            if member.status not in ('administrator', 'creator'):
                raise ValueError('ابتدا ربات را ادمین کانال کنید.')
            if chat.username:
                channel, url = '@'+chat.username, 'https://t.me/'+chat.username
            else:
                url = items[1] if len(items)>1 else ''
                if not url.startswith(('https://t.me/+', 'https://t.me/joinchat/')):
                    raise ValueError('برای کانال خصوصی، لینک دعوت t.me را هم بفرستید.')
                channel = str(chat.id)
            store.set_setting('required_channel', channel)
            store.set_setting('channel_url', url)
            store.audit(aid, 'set_channel', channel)
        elif mode in ('direct', 'search'):
            uid = int(text)
            u = store.user(uid)
            if uid <= 0 or not u:
                raise ValueError('کاربر پیدا نشد؛ باید قبلاً ربات را استارت کرده باشد.')
            if mode == 'search':
                await state.clear()
                await message.answer(user_text(u), parse_mode='HTML', reply_markup=ui.inline([[ui.button('👤 مدیریت کاربر', f'adm:user:{uid}')], back()]))
                return
            if u['blocked'] or u['banned']:
                raise ValueError('کاربر بلاک یا مسدود است.')
            await state.set_state(AdminFlow.content)
            await state.set_data({'target': uid})
            await message.answer('📨 حالا پیام موردنظر را بفرستید.', reply_markup=cancel_keyboard())
            return
        elif mode in ('welcome', 'group_date_reply'):
            if not text or len(text)>3000:
                raise ValueError('متن باید بین ۱ تا ۳۰۰۰ نویسه باشد.')
            store.set_setting(mode, text)
        elif mode == 'group_date_keywords':
            keywords = [' '.join(item.split()) for item in text.replace('،', ',').split(',')]
            keywords = [item for item in keywords if item]
            joined = ','.join(keywords)
            if not keywords or len(joined) > 200:
                raise ValueError('حداقل یک کلمه کلیدی و حداکثر ۲۰۰ نویسه.')
            store.set_setting(mode, joined)
        elif mode == 'birthday_hint':
            if not text or len(text) > 500:
                raise ValueError('متن باید بین ۱ تا ۵۰۰ نویسه باشد.')
            store.set_setting(mode, text)
        elif mode == 'reminder_time':
            hour, minute = map(int, text.split(':'))
            if not 0<=hour<=23 or not 0<=minute<=59:
                raise ValueError('ساعت معتبر نیست.')
            store.set_setting(mode, f'{hour:02}:{minute:02}')
        elif mode == 'send_rate':
            value = int(text)
            if not 1<=value<=25:
                raise ValueError('عدد باید بین ۱ و ۲۵ باشد.')
            store.set_setting(mode, value)
        elif mode in ('admin_add', 'admin_remove'):
            if aid not in config.ADMIN_IDS:
                await state.clear()
                return
            uid = int(text)
            if uid<=0 or uid in config.ADMIN_IDS:
                raise ValueError('شناسه معتبر مدیر غیرمالک را وارد کنید.')
            if mode == 'admin_add' and not store.user(uid):
                raise ValueError('مدیر جدید باید ابتدا ربات را استارت کند.')
            if mode == 'admin_remove' and uid not in store.admins():
                raise ValueError('این کاربر ادمین نیست.')
            await state.set_data({'admin_mode': mode, 'admin_uid': uid})
            await message.answer(f'دسترسی مدیریت برای {uid} {"اضافه" if mode=="admin_add" else "حذف"} شود؟',
                reply_markup=ui.inline([[ui.button('✅ تأیید', 'adm:admin_confirm', 'success')], [ui.button('✖️ لغو', 'adm:home', 'danger')]]))
            return
        else:
            raise ValueError('دوباره از پنل شروع کنید.')
    except (ValueError, IndexError):
        await message.answer('❌ ورودی معتبر نیست؛ راهنمای بالا را بررسی کنید و دوباره بفرستید.', reply_markup=cancel_keyboard())
        return
    except TelegramAPIError:
        await message.answer('❌ تلگرام کانال یا دسترسی ربات را تأیید نکرد؛ شناسه کانال و ادمین بودن ربات را بررسی کنید.', reply_markup=cancel_keyboard())
        return
    store.audit(aid, 'setting', mode)
    await state.clear()
    await message.answer('✅ تنظیم ذخیره شد.', reply_markup=ui.inline([back()]))


@router.message(StateFilter(AdminFlow.content), F.chat.type == 'private', ~F.text.startswith('/'))
async def admin_content(message: Message, state: FSMContext, bot):
    aid = message.from_user.id
    if aid not in store.admins():
        await state.clear()
        return
    if message.content_type not in ('text','photo','video','animation','audio','voice','document','sticker','video_note'):
        await message.answer('این نوع پیام پشتیبانی نمی‌شود؛ متن یا رسانه بفرستید.')
        return
    target = (await state.get_data()).get('target')
    try:
        await bot.copy_message(aid, message.chat.id, message.message_id)
    except TelegramAPIError:
        await message.answer('پیش‌نمایش ممکن نیست؛ پیام قابل کپی دیگری بفرستید.')
        return
    jid = store.create_draft(aid, message.chat.id, message.message_id, target)
    count = 1 if target else sum(not u['blocked'] and not u['banned'] and u['id']>0 for u in store.all_users())
    text = f'👁 پیش‌نمایش بالا را بررسی کنید.\nمقصد: {target if target else "همه کاربران قابل ارسال"}\nتعداد فعلی: {count}\nتا تأیید شما، برای کاربران ارسال نمی‌شود.'
    await state.clear()
    await message.answer(text, reply_markup=ui.inline([
        [ui.button('✅ تأیید و ارسال', f'adm:send:{jid}', 'success')],
        [ui.button('✖️ لغو', f'adm:discard:{jid}', 'danger')]]))
