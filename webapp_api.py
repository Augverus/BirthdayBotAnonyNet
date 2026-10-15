"""Small authenticated API used by the Telegram Mini App."""
from datetime import datetime, timezone

from aiohttp import web
from aiogram.utils.web_app import safe_parse_webapp_init_data

import calendar_utils as cal
import config
import store


def _json_error(status, message):
    return web.json_response({"error": message}, status=status)


@web.middleware
async def _cors(request, handler):
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") not in config.WEBAPP_API_ALLOWED_ORIGINS:
        return _json_error(403, "این مبدأ اجازهٔ دسترسی ندارد.")
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = error
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers["Vary"] = "Origin"
    return response


def _telegram_user(request):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("tma "):
        raise web.HTTPUnauthorized(text="اطلاعات ورود تلگرام پیدا نشد.")
    init_data = authorization[4:]
    if not init_data or len(init_data) > 8192:
        raise web.HTTPUnauthorized(text="اطلاعات ورود تلگرام معتبر نیست.")
    try:
        data = safe_parse_webapp_init_data(config.BOT_TOKEN, init_data)
    except (ValueError, TypeError):
        raise web.HTTPUnauthorized(text="ورود تلگرام تأیید نشد.")
    if not data.user:
        raise web.HTTPUnauthorized(text="شناسهٔ تلگرام در اطلاعات ورود نیست.")
    auth_date = data.auth_date
    if auth_date.tzinfo is None:
        auth_date = auth_date.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - auth_date).total_seconds()
    if age < -60 or age > 24 * 60 * 60:
        raise web.HTTPUnauthorized(text="نشست منقضی شده؛ مینی‌اپ را ببند و دوباره باز کن.")
    return data.user


def _profile(user):
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": user.username,
    }


def _birthday_record(month, day):
    return {
        "month": month,
        "day": day,
        "date": cal.birthday_text(month, day),
        "days_remaining": cal.remaining(month, day),
    }


def _friend_record(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "month": row["month"],
        "day": row["day"],
        "date": cal.birthday_text(row["month"], row["day"]),
        "days_remaining": cal.remaining(row["month"], row["day"]),
        "notification": bool(row["notification"]),
    }


async def health(_request):
    return web.json_response({"ok": True})


async def preflight(_request):
    return web.Response(status=204)


async def dashboard(request):
    telegram_user = _telegram_user(request)
    record = store.user(telegram_user.id)
    birthday = None
    if record and record["month"] and record["day"]:
        birthday = _birthday_record(record["month"], record["day"])
    friends = [_friend_record(row) for row in store.friend_birthdays(telegram_user.id)]
    return web.json_response({"profile": _profile(telegram_user), "birthday": birthday, "friends": friends})


async def add_friend(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_add_friend", 2):
        return _json_error(429, "یک لحظه صبر کن و دوباره امتحان کن.")
    try:
        payload = await request.json()
    except (ValueError, web.HTTPBadRequest):
        return _json_error(400, "اطلاعات فرم درست نیست.")
    if not isinstance(payload, dict):
        return _json_error(400, "اطلاعات فرم درست نیست.")
    name = " ".join(str(payload.get("name", "")).split())
    month = payload.get("month")
    day = payload.get("day")
    notification = payload.get("notification", True)
    if (not name or len(name) > 80 or isinstance(month, bool) or not isinstance(month, int)
            or isinstance(day, bool) or not isinstance(day, int)
            or not cal.valid_birthday(month, day) or not isinstance(notification, bool)):
        return _json_error(400, "نام یا تاریخ تولد را بررسی کن.")
    try:
        friend_id = store.add_friend_birthday(telegram_user.id, name, month, day, notification)
    except ValueError:
        return _json_error(400, "تاریخ تولد معتبر نیست.")
    if friend_id is None:
        return _json_error(409, "تا ۵۰ تولد می‌توانی ثبت کنی.")
    return web.json_response({"friend": _friend_record({
        "id": friend_id, "name": name, "month": month, "day": day,
        "notification": int(notification),
    })}, status=201)


async def delete_friend(request):
    telegram_user = _telegram_user(request)
    try:
        friend_id = int(request.match_info["friend_id"])
    except ValueError:
        return _json_error(400, "این مورد معتبر نیست.")
    if friend_id < 1:
        return _json_error(400, "این مورد معتبر نیست.")
    if not store.delete_friend_birthday(telegram_user.id, friend_id):
        return _json_error(404, "این تولد پیدا نشد.")
    return web.json_response({"ok": True})


def create_app():
    app = web.Application(client_max_size=16 * 1024, middlewares=[_cors])
    app.router.add_get("/health", health)
    app.router.add_get("/api/dashboard", dashboard)
    app.router.add_post("/api/friends", add_friend)
    app.router.add_delete("/api/friends/{friend_id}", delete_friend)
    app.router.add_route("OPTIONS", "/{path:.*}", preflight)
    return app


async def start():
    runner = web.AppRunner(create_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBAPP_API_HOST, config.WEBAPP_API_PORT)
    try:
        await site.start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
