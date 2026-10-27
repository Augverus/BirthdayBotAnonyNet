"""Small authenticated API used by the Telegram Mini App."""
from datetime import datetime, timezone

from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web
import jdatetime

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
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
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
        raise web.HTTPUnauthorized(text="ورود تلگرام تأیید نشد.") from None
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
        "photo_url": user.photo_url,
    }


def _valid_month_day(month, day):
    return (isinstance(month, int) and not isinstance(month, bool)
            and isinstance(day, int) and not isinstance(day, bool)
            and cal.valid_birthday(month, day))


async def _json_payload(request):
    try:
        payload = await request.json()
    except (ValueError, web.HTTPBadRequest):
        return None
    return payload if isinstance(payload, dict) else None


def _birthday_record(year, month, day, notification=None):
    record = {
        "year": year,
        "month": month,
        "day": day,
        "date": cal.birthday_text(month, day, year),
        "days_remaining": cal.remaining(month, day),
    }
    if notification is not None:
        record["notification"] = bool(notification)
    return record


def _friend_record(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "year": row.get("year"),
        "month": row["month"],
        "day": row["day"],
        "date": cal.birthday_text(row["month"], row["day"], row.get("year")),
        "days_remaining": cal.remaining(row["month"], row["day"]),
        "notification": bool(row["notification"]),
    }


async def health(_request):
    return web.json_response({"ok": True})


async def mini_app_index(_request):
    """Serve the Mini App from the same origin as its authenticated API."""
    return web.FileResponse(config.BASE_DIR / "webapp" / "index.html")


async def preflight(_request):
    return web.Response(status=204)


async def dashboard(request):
    telegram_user = _telegram_user(request)
    record = store.user(telegram_user.id)
    birthday = None
    if record and record["month"] and record["day"]:
        birthday = _birthday_record(record.get("birth_year"), record["month"], record["day"],
                                     record["notification"])
    friends = [_friend_record(row) for row in store.friend_birthdays(telegram_user.id)]
    return web.json_response({"profile": _profile(telegram_user), "birthday": birthday, "friends": friends})


async def set_birthday_notification(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_birthday_notification", 2):
        return _json_error(429, "یک لحظه صبر کن و دوباره امتحان کن.")
    payload = await _json_payload(request)
    if payload is None:
        return _json_error(400, "اطلاعات فرم درست نیست.")
    notification = payload.get("notification")
    if not isinstance(notification, bool):
        return _json_error(400, "اطلاعات فرم درست نیست.")
    if not store.user(telegram_user.id):
        return _json_error(404, "اول ربات را در تلگرام استارت کن.")
    store.update_user(telegram_user.id, notification=int(notification))
    return web.json_response({"notification": notification})


async def save_birthday(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_save_birthday", 2):
        return _json_error(429, "یه لحظه صبر کن و دوباره امتحان کن.")
    payload = await _json_payload(request)
    if (payload is None
            or not {"calendar", "year", "month", "day"} <= set(payload)
            or set(payload) - {"calendar", "year", "month", "day", "notification"}):
        return _json_error(400, "اطلاعات تاریخ درست نیست.")
    year, month, day = payload["year"], payload["month"], payload["day"]
    user_record = store.user(telegram_user.id)
    notification = payload.get("notification", bool(user_record["notification"]) if user_record else True)
    if (payload["calendar"] != "solar_hijri"
            or any(type(value) is not int for value in (year, month, day))
            or not isinstance(notification, bool)
            or year < 1 or year > cal.today().year
            or not cal.valid_birthday(month, day)):
        return _json_error(400, "تاریخ تولد معتبر نیست.")
    try:
        jdatetime.date(year, month, day)
    except (ValueError, TypeError):
        return _json_error(400, "تاریخ تولد در این سال معتبر نیست.")
    if not user_record:
        return _json_error(404, "اول ربات را در تلگرام استارت کن.")
    store.update_user(telegram_user.id, birth_year=year, month=month, day=day,
                      notification=int(notification))
    callback = request.app.get("on_birthday_saved")
    if callback:
        try:
            await callback(telegram_user.id, year, month, day, notification)
        except Exception:
            # The birthday is already safely stored; a Telegram notification failure
            # must not turn a successful save into a retry that consumes the rate limit.
            pass
    return web.json_response({"birthday": _birthday_record(year, month, day, notification)})


async def add_friend(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_add_friend", 2):
        return _json_error(429, "یک لحظه صبر کن و دوباره امتحان کن.")
    payload = await _json_payload(request)
    if payload is None:
        return _json_error(400, "اطلاعات فرم درست نیست.")
    name = " ".join(str(payload.get("name", "")).split())
    year = payload.get("year")
    month = payload.get("month")
    day = payload.get("day")
    notification = payload.get("notification", True)
    if (not name or len(name) > 80 or type(year) is not int or year < 1
            or year > cal.today().year or not _valid_month_day(month, day)
            or not isinstance(notification, bool)):
        return _json_error(400, "نام یا تاریخ تولد را بررسی کن.")
    try:
        jdatetime.date(year, month, day)
        friend_id = store.add_friend_birthday(telegram_user.id, name, month, day,
                                              notification, year=year)
    except (ValueError, TypeError):
        return _json_error(400, "تاریخ تولد معتبر نیست.")
    if friend_id is None:
        return _json_error(409, "تا ۵۰ تولد می‌توانی ثبت کنی.")
    return web.json_response({"friend": _friend_record({
        "id": friend_id, "name": name, "year": year, "month": month, "day": day,
        "notification": int(notification),
    })}, status=201)


async def update_friend(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_update_friend", 1):
        return _json_error(429, "یک لحظه صبر کن و دوباره امتحان کن.")
    try:
        friend_id = int(request.match_info["friend_id"])
    except ValueError:
        return _json_error(400, "این مورد معتبر نیست.")
    payload = await _json_payload(request)
    notification = payload.get("notification") if payload else None
    if friend_id < 1 or not isinstance(notification, bool):
        return _json_error(400, "اطلاعات فرم درست نیست.")
    if not store.set_friend_notification(telegram_user.id, friend_id, notification):
        return _json_error(404, "این تولد پیدا نشد.")
    friend = store.friend_birthday(telegram_user.id, friend_id)
    return web.json_response({"friend": _friend_record(friend)})


async def delete_friend(request):
    telegram_user = _telegram_user(request)
    if not store.claim_rate_limit(telegram_user.id, "miniapp_delete_friend", 1):
        return _json_error(429, "یک لحظه صبر کن و دوباره امتحان کن.")
    try:
        friend_id = int(request.match_info["friend_id"])
    except ValueError:
        return _json_error(400, "این مورد معتبر نیست.")
    if friend_id < 1:
        return _json_error(400, "این مورد معتبر نیست.")
    if not store.delete_friend_birthday(telegram_user.id, friend_id):
        return _json_error(404, "این تولد پیدا نشد.")
    return web.json_response({"ok": True})


def create_app(on_birthday_saved=None):
    app = web.Application(client_max_size=16 * 1024, middlewares=[_cors])
    app["on_birthday_saved"] = on_birthday_saved
    app.router.add_get("/health", health)
    app.router.add_get("/api/dashboard", dashboard)
    app.router.add_post("/api/birthday", save_birthday)
    app.router.add_patch("/api/birthday/notification", set_birthday_notification)
    app.router.add_post("/api/friends", add_friend)
    app.router.add_patch("/api/friends/{friend_id}", update_friend)
    app.router.add_delete("/api/friends/{friend_id}", delete_friend)
    app.router.add_route("OPTIONS", "/{path:.*}", preflight)
    app.router.add_get("/", mini_app_index)
    # Only the static Mini App directory is exposed; project files, secrets,
    # SQLite databases, and backups are outside this mounted directory.
    app.router.add_static("/", config.BASE_DIR / "webapp", name="mini_app", show_index=False)
    return app


async def start(on_birthday_saved=None):
    runner = web.AppRunner(create_app(on_birthday_saved), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBAPP_API_HOST, config.WEBAPP_API_PORT)
    try:
        await site.start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
