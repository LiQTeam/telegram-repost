"""
سرورِ HTTP سبک (aiohttp) برای ارتباط با اکستنشنِ مرورگر (کروم/اج) که داخلِ
تبِ لاگین‌شده‌ی خودِ کاربر در web.telegram.org اجرا می‌شه و محتوایِ گروه‌ها/
کانال‌های خصوصی (که با اسکرپِ عمومیِ t.me/s/username قابل‌دسترسی نیستن) رو
می‌خونه و به این‌جا می‌فرسته.

نکته‌ی امنیتی: چون سرورِ ربات فقط IP داره (بدونِ گواهیِ SSL)، این API روی
HTTP سادهٔ رمزنگاری‌نشده اجرا میشه. حتماً:
  ۱. یک EXTENSION_API_TOKEN طولانی و تصادفی توی .env بذار.
  ۲. این پورت رو فقط برای IPِ خودت (یا یک VPN/شبکه‌ی محدود) توی فایروال باز کن،
     نه برایِ کلِ اینترنت.

مسیرها:
  POST /api/ext/tabs   - اکستنشن لیستِ تب‌های بازِ تلگرام‌وب رو گزارش می‌ده
  POST /api/ext/post    - اکستنشن یک پستِ تازه (متن + عکس/ویدیو) رو می‌فرسته
  GET  /media/{name}    - فایل‌های آپلودشده رو برای پردازشِ داخلیِ خودِ ربات
                           (process_new_post که مدیا رو با httpx دانلود می‌کنه)
                           روی خودِ همین سرور serve می‌کنه.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from aiohttp import web

from . import config
from .database import db
from .poster import process_new_post
from .scraper import MediaItem, Post

log = logging.getLogger("repost_bot.extension_api")

UPLOAD_DIR = config.BASE_DIR / "data" / "extension_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # ۲۰۰ مگابایت برای هر فایل (ویدیوهای حجیم)

_EXT_BY_KIND = {
    "photo": ".jpg",
    "video": ".mp4",
    "document": ".bin",
    "voice": ".ogg",
}


def _check_auth(request: web.Request) -> bool:
    if not config.EXTENSION_API_TOKEN:
        return False
    token = request.headers.get("X-Ext-Token", "")
    return token == config.EXTENSION_API_TOKEN


async def _handle_tabs(request: web.Request) -> web.Response:
    """اکستنشن لیستِ گروه/کانال‌هایی که الان توی تب‌های بازِ تلگرام‌وب دیده رو
    می‌فرسته. هرکدوم که قبلاً دیده نشده، به‌صورتِ «در انتظارِ تایید» (غیرفعال)
    توی جدولِ channels ثبت می‌شه تا ادمین از داخلِ ربات فعالش کنه."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    peers = body.get("peers") or []
    if not isinstance(peers, list):
        return web.json_response({"error": "peers must be a list"}, status=400)

    result = []
    for p in peers:
        ref = str(p.get("ref") or "").strip()
        title = str(p.get("title") or "").strip()
        if not ref:
            continue
        row = db.upsert_extension_channel(ref, title)
        result.append({
            "ref": ref,
            "channel_id": row["id"],
            "active": bool(row["active"]),
            "approval_required": bool(row["approval_required"]),
        })
    return web.json_response({"ok": True, "sources": result})


async def _handle_post(request: web.Request) -> web.Response:
    """اکستنشن یک پستِ تازه (متن + صفر یا چند فایلِ عکس/ویدیو) رو به‌صورتِ
    multipart/form-data می‌فرسته. فیلدها:
      ref   - شناسه‌ی داخلیِ گروه/کانال (همون‌که در /api/ext/tabs فرستاده شد)
      text  - متنِ پست (HTML ساده مجازه: <b> <i> <a> و...)
      files - صفر یا چند فایل (name=files، چندبار تکرار برای آلبوم)
    """
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    bot = request.app["bot"]
    reader = await request.multipart()

    ref = ""
    text_html = ""
    media: list[MediaItem] = []
    saved_paths: list[Path] = []

    try:
        field = await reader.next()
        while field is not None:
            if field.name == "ref":
                ref = (await field.text()).strip()
            elif field.name == "text":
                text_html = await field.text()
            elif field.name == "files":
                kind = (field.filename or "").rsplit(".", 1)
                suffix = "." + kind[1].lower() if len(kind) == 2 else ""
                media_type = "video" if suffix in (".mp4", ".mov", ".webm", ".mkv") else "photo"
                if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    media_type = "photo"
                if not suffix:
                    suffix = _EXT_BY_KIND.get(media_type, ".bin")

                fname = f"{uuid.uuid4().hex}{suffix}"
                fpath = UPLOAD_DIR / fname
                size = 0
                with open(fpath, "wb") as fh:
                    while True:
                        chunk = await field.read_chunk(1024 * 256)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > _MAX_UPLOAD_BYTES:
                            fh.close()
                            fpath.unlink(missing_ok=True)
                            # باگ: فایل‌هایی که *قبلِ* همین فایلِ حجیم، از همین درخواستِ
                            # چندفایلی (آلبوم) با موفقیت ذخیره شده بودن (توی saved_paths)
                            # اینجا پاک نمی‌شدن، چون این یک `return` مستقیمه، نه یک
                            # exception - پس بلاکِ except (که پاک‌سازی رو انجام می‌ده)
                            # اصلاً اجرا نمی‌شد. نتیجه: هر آپلودِ آلبومی که یکی از
                            # فایل‌هاش (نه لزوماً اولی) از سقف رد بشه، بقیه‌ی فایل‌های
                            # قبلیِ همون آلبوم برای همیشه روی دیسک می‌موندن (نشتِ دیسک).
                            for _p in saved_paths:
                                _p.unlink(missing_ok=True)
                            return web.json_response({"error": "file too large"}, status=413)
                        fh.write(chunk)
                saved_paths.append(fpath)
                # آدرسِ لوکال (127.0.0.1) عمداً استفاده میشه، نه IPِ عمومی: چون
                # فایل رو همینِ فرآیندِ ربات (poster._download) داره از خودِ همین
                # سرور می‌خونه، نیازی به دسترسی از بیرون نداره.
                url = f"http://127.0.0.1:{config.EXTENSION_API_PORT}/media/{fname}"
                media.append(MediaItem(type=media_type, url=url, filename=fname))
            field = await reader.next()
    except Exception:
        log.exception("خطا در خوندنِ multipart از اکستنشن.")
        for p in saved_paths:
            p.unlink(missing_ok=True)
        return web.json_response({"error": "bad multipart"}, status=400)

    if not ref:
        for p in saved_paths:
            p.unlink(missing_ok=True)
        return web.json_response({"error": "ref required"}, status=400)

    channel = db.get_extension_channel_by_ref(ref)
    if not channel:
        for p in saved_paths:
            p.unlink(missing_ok=True)
        return web.json_response({"error": "unknown source, report via /api/ext/tabs first"}, status=404)

    if not channel["active"]:
        # منبع هنوز توسطِ ادمین تایید/فعال نشده - پست نادیده گرفته میشه (نه خطا)
        for p in saved_paths:
            p.unlink(missing_ok=True)
        return web.json_response({"ok": True, "status": "pending_admin_approval"})

    if not text_html.strip() and not media:
        return web.json_response({"error": "empty post"}, status=400)

    new_post_id = max(int(channel["last_post_id"] or 0) + 1, int(time.time()))
    post = Post(id=new_post_id, html_text=text_html, media=media, raw_text=text_html)

    bypass = not bool(channel["approval_required"])
    try:
        result = await process_new_post(bot, channel, post, bypass_approval=bypass)
    except Exception:
        log.exception("خطای غیرمنتظره هنگام پردازشِ پستِ اکستنشن (ref=%s).", ref)
        return web.json_response({"error": "internal error"}, status=500)
    finally:
        # فیکسِ R1: فایل‌های آپلودی (تا ۲۰۰ مگابایت هر کدوم) در همه‌ی مسیرهای خطا
        # unlink می‌شدن ولی بعد از پردازشِ *موفق* هرگز حذف نمی‌شدن ← پرشدنِ تدریجیِ
        # دیسک. حالا در finally، مستقلِ از موفقیت/خطا، پاکسازی می‌شن. (اگه پست به
        # صفِ تایید رفته باشه، مدیا از قبل داخلِ دیتابیس ذخیره شده و این فایل‌های
        # موقتِ روی دیسک دیگه لازم نیستن.)
        for _p in saved_paths:
            try:
                _p.unlink(missing_ok=True)
            except OSError as e:
                log.warning("حذفِ فایلِ آپلودیِ اکستنشن «%s» ناموفق بود: %s", _p, e)

    db.update_last_post(channel["id"], new_post_id)
    return web.json_response({"ok": True, "result": result.value if hasattr(result, "value") else str(result)})


async def _handle_media(request: web.Request) -> web.StreamResponse:
    # این مسیر عمداً بدونِ توکن سِرو میشه (چون فقط از 127.0.0.1 توسطِ خودِ ربات
    # درخواست داده میشه) - فایل‌ها اسمِ تصادفیِ uuid دارن، حدس‌زدنی نیستن.
    name = request.match_info["name"]
    if "/" in name or "\\" in name or ".." in name:
        raise web.HTTPBadRequest()
    fpath = UPLOAD_DIR / name
    if not fpath.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(fpath)


async def _handle_ping(request: web.Request) -> web.Response:
    """برای دکمه‌ی «تست اتصال» توی پاپ‌آپِ اکستنشن. توکن رو هم چک می‌کنه تا
    اکستنشن بتونه هم «سرور بالاست؟» و هم «توکن درسته؟» رو با یک درخواست بفهمه."""
    authed = _check_auth(request)
    return web.json_response({
        "ok": True,
        "authenticated": authed,
        "server_time": int(time.time()),
    })


async def _handle_sources(request: web.Request) -> web.Response:
    """لیستِ فعلیِ منابعِ اکستنشن (برای نمایشِ زنده توی پاپ‌آپ، بدونِ نیاز به
    باز کردنِ ربات توی تلگرام)."""
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    rows = db.list_extension_channels()
    sources = [
        {
            "ref": r["ext_peer_ref"],
            "title": r["title"],
            "active": bool(r["active"]),
            "approval_required": bool(r["approval_required"]),
        }
        for r in rows
    ]
    return web.json_response({"ok": True, "sources": sources})


def _build_app(bot) -> web.Application:
    app = web.Application(client_max_size=_MAX_UPLOAD_BYTES + 1024 * 1024)
    app["bot"] = bot
    app.router.add_post("/api/ext/tabs", _handle_tabs)
    app.router.add_post("/api/ext/post", _handle_post)
    app.router.add_get("/api/ext/ping", _handle_ping)
    app.router.add_get("/api/ext/sources", _handle_sources)
    app.router.add_get("/media/{name}", _handle_media)
    return app


async def run_ext_api_server(bot) -> None:
    """به‌عنوانِ یک تسکِ asyncio جدا (application.create_task) اجرا میشه و تا
    خاموش‌شدنِ کلِ ربات زنده می‌مونه؛ هیچ تاثیری روی حلقه‌ی اصلیِ polling نداره."""
    if not config.EXTENSION_API_ENABLED:
        log.info("API اکستنشنِ مرورگر غیرفعاله (EXTENSION_API_ENABLED=false در .env).")
        return
    if not config.EXTENSION_API_TOKEN:
        log.warning(
            "EXTENSION_API_ENABLED=true ولی EXTENSION_API_TOKEN خالیه؛ برای امنیت، "
            "API اکستنشن راه‌اندازی نشد. یک توکنِ تصادفیِ طولانی توی .env بذار."
        )
        return

    app = _build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.EXTENSION_API_HOST, config.EXTENSION_API_PORT)
    await site.start()
    log.info(
        "API اکستنشنِ مرورگر روی %s:%s بالا اومد.",
        config.EXTENSION_API_HOST, config.EXTENSION_API_PORT,
    )
    try:
        # برای همیشه زنده می‌مونه؛ فقط با لغوِ خودِ تسک (موقعِ خاموشیِ ربات) متوقف میشه
        import asyncio
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
