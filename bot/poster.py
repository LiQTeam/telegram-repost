"""
هسته‌ی ارسال: از روی یک Post خام (اسکرِیپ‌شده)، کپشن نهایی (با فرمت حفظ‌شده +
امضای انتهایی که لینک به کانال هست) رو می‌سازه، واترمارک رو روی عکس‌ها اعمال
می‌کنه و پیام رو به کانال مقصد می‌فرسته.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from enum import Enum
from typing import Optional

import httpx
from html import escape as _esc, unescape as _unescape
from html.parser import HTMLParser
from telegram import Bot, InputMediaPhoto, InputMediaVideo, LinkPreviewOptions, ReplyParameters
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

from . import ad_filter, ai_watermark, cache, concurrency, config, sr_model
from .database import db
from .formatter import (
    append_footer,
    append_vpn_signature,
    apply_fixed_config_caption,
    apply_netmod_npvtunnel_caption,
    ensure_rtl_lines,
    make_footer_html,
    parse_phrases,
    rename_avocado_proxy_links_in_html,
    rename_configs_in_html,
    render_custom_footer,
    strip_custom_emoji,
    strip_html_tags,
    strip_phrases_html,
    strip_vpn_source_boilerplate,
)
from .scraper import MediaItem, Post
from .utils import truncate_html_safe, tg_text_len
from .watermark import add_watermark

log = logging.getLogger("repost_bot.poster")


def _build_post_link(chat_id: str, message_id: Optional[int]) -> str:
    """
    ساختِ لینکِ قابل‌کلیکِ یک پیام در تلگرام، از رویِ chat_id مقصد و آیدیِ پیام.
    - کانالِ عمومی (یوزرنیم، مثلِ @mychannel یا mychannel): https://t.me/mychannel/123
    - کانالِ خصوصی با آیدیِ عددیِ استاندارد (مثلِ -1001234567890):
      https://t.me/c/1234567890/123 (پیشوندِ -100 حذف می‌شه، چون فرمتِ لینکِ
      خصوصیِ تلگرام همینه)
    - اگه message_id نداشته باشیم (مثلاً پیام گروهی/چندتایی بود و نتونستیم
      آیدیِ دقیق رو بگیریم)، رشته‌ی خالی برمی‌گرده (یعنی لینک اصلاً نشون داده نمی‌شه).
    """
    if not message_id:
        return ""
    chat_id = str(chat_id).strip()
    if chat_id.startswith("@"):
        return f"https://t.me/{chat_id[1:]}/{message_id}"
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    if re.match(r"^[A-Za-z0-9_]{3,}$", chat_id):
        return f"https://t.me/{chat_id}/{message_id}"
    return ""

_DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _owner_of_channel(channel_id: int | None) -> int | None:
    """Return owner user id (internal users.id) of a source channel, if any."""
    if channel_id is None:
        return None
    ch = db.get_channel(channel_id)
    if ch and ch["owner_user_id"]:
        return ch["owner_user_id"]
    return None


def _approval_targets(channel_or_owner_id) -> tuple[list[int], int | None]:
    """
    مقصدهای ارسال پیش‌نمایش + owner_user_id رو برمی‌گردونه.
    اگه کانال مالک فعال داشته باشه → کانال تایید اختصاصی او.
    وگرنه → ADMIN_IDS (رفتار قبلی).
    پارامتر می‌تونه یه sqlite3.Row از channels یا یه int (owner_user_id) باشه.
    """
    owner_id: int | None = None
    if isinstance(channel_or_owner_id, int):
        owner_id = channel_or_owner_id
    else:
        try:
            owner_id = channel_or_owner_id["owner_user_id"]
        except (TypeError, KeyError, IndexError):
            pass

    if owner_id:
        user = db.get_user(owner_id)
        if user and user["active"]:
            # اگه approval_chat_id تنظیم شده، اون رو بده
            # وگرنه از telegram_id استفاده کن (چت خصوصی = telegram_id)
            approval_chat = user["approval_chat_id"] or user["telegram_id"]
            if approval_chat:
                return [int(approval_chat)], owner_id

    return list(config.ADMIN_IDS), None


_MAX_CACHEABLE_BYTES = 8 * 1024 * 1024  # 8 مگابایت

_FAILURE_NOTIFY_COOLDOWN_SECONDS = 1800
_last_failure_notify: dict[str, float] = {}


class PostResult(Enum):
    """
    نتیجه‌ی پردازشِ «یک پستِ تازه» (خروجیِ process_new_post). قبلاً این تابع فقط
    True/False برمی‌گردوند که کافی نبود: هم «رد شدنِ قانونی» (فیلترِ تبلیغات/
    تکراری/کوتاه‌بودن)، هم «رفتن به صفِ تایید»، هم «شکستِ فنیِ واقعی» (مثلاً
    دانلود/آپلودِ ویدیو شکست خورد) همه با False گزارش می‌شدن - و کدِ زمان‌بند
    (scheduler.py) هر سه حالت رو یکسان می‌دید و همیشه last_post_id رو جلو
    می‌برد، حتی وقتی شکست فنی بود. نتیجه: اگه پستِ ۳۰۰ به‌خاطرِ یک خطای موقتی
    (مثلاً قطعیِ لحظه‌ایِ شبکه هنگامِ دانلود/آپلودِ ویدیو) نمی‌رفت، بلافاصله سراغِ
    پستِ ۳۰۱ می‌رفت و پستِ ۳۰۰ برای همیشه گم می‌شد - نه اینکه بعداً دوباره
    امتحان بشه.

    - SENT: با موفقیت مستقیم به حداقلِ یک مقصد فرستاده شد.
    - QUEUED: به صفِ تاییدِ ادمین اضافه شد (این «رد شدن» نیست؛ پست هنوز زنده‌ست).
    - SKIPPED: به‌طورِ کاملاً قانونی و همیشگی رد شد (فیلترِ تبلیغات/تکراری/خیلی‌
      کوتاه/بدونِ مقصدِ فعال/بدونِ محتوای قابل‌ارسال) - تلاشِ دوباره هیچ‌وقت نتیجه‌ی
      متفاوتی نمی‌ده، پس باید last_post_id جلو بره.
    - FAILED: یک مشکلِ فنی/موقتی (دانلود یا آپلود شکست خورد) باعث شد این پست به
      هیچ مقصدی نرسه. last_post_id نباید جلو بره - باید سرِ تیکِ بعدی *همین*
      پست دوباره امتحان بشه، تا پست‌ها هیچ‌وقت جاش عوض نشه یا گم نشه.
    """
    SENT = "sent"
    QUEUED = "queued"
    SKIPPED = "skipped"
    FAILED = "failed"


# نشونه‌های متنیِ خطاهایی که تلاشِ دوباره واقعاً می‌تونه کمک کنه (شبکه/تایم‌اوت/
# ازدحامِ لحظه‌ای سمتِ تلگرام) - این‌ها با فاصله دوباره امتحان می‌شن.
_RETRYABLE_ERROR_MARKERS = (
    "timed out", "timeout", "network", "connection", "temporarily",
    "try again", "flood", "pool timeout", "bad gateway", "server error",
    "internal server error", "service unavailable",
)
# نشونه‌های خطاهای «دائمی» (تلاشِ دوباره بی‌فایده‌ست، چون خودِ فایل/تنظیمات مشکل
# داره نه شبکه) - بلافاصله رها می‌شن تا پست زودتر (به‌جای معطلیِ طولانی) رد بشه.
_PERMANENT_ERROR_MARKERS = (
    "too large", "too big", "entity too large", "file is too big",
    "wrong file identifier", "unsupported", "webpage_media_empty",
    # فیکسِ M1: خطاهای «دائمیِ» رایجِ تلگرام که retry هیچ‌وقت درستشون نمی‌کنه.
    # اضافه‌کردنشون این‌جا باعث می‌شه به‌جای ۳ تلاشِ بی‌فایده، بلافاصله رها بشن.
    "chat not found", "bot was blocked", "user is deactivated",
    "not enough rights", "have no rights", "chat_write_forbidden",
    "peer_id_invalid", "message text is empty", "can't parse entities",
    "forbidden", "chat_admin_required",
)


async def _send_with_retry(send_coro_factory, attempts: int = 3, base_delay: float = 3.0, label: str = ""):
    """
    یک عملیاتِ ارسال به تلگرام (مثلاً bot.send_video) رو اجرا می‌کنه و اگه با یک
    خطای «موقتی/شبکه‌ای» مواجه شد، چند بار دیگه (با فاصله‌ی بیشتر هر بار) دوباره
    امتحان می‌کنه - تا جایی که ممکنه، ویدیو/عکس هرچقدرم سنگین باشه یا شبکه
    لحظه‌ای قطع بشه، باز هم تلاشِ ارسال ادامه پیدا کنه و پست جا نمونه. خطاهای
    «دائمی» (مثلاً حجمِ فایل بیشتر از سقفِ مجازِ تلگرام) بلافاصله (بدونِ تلفِ‌وقت
    برای تلاشِ بی‌فایده) بالا پرتاب می‌شن.
    """
    last_exc: Exception | None = None
    flood_retries = 0
    attempt = 0
    while True:
        try:
            return await send_coro_factory()
        except RetryAfter as e:
            # ۴۲۹ (Flood control) یک استثنای جدا (RetryAfter) با فیلدِ retry_after
            # دقیقاً همون چیزیه که تلگرام می‌گه: «الان صبر کن، دقیقاً N ثانیه».
            # قبلاً این حالت هم مثلِ بقیه‌ی خطاهای موقتی با بک‌آفِ ثابتِ
            # base_delay*attempt (مثلاً ۳ یا ۶ ثانیه برایِ پیامِ متنی) دوباره
            # امتحان می‌شد - که تقریباً همیشه از ۱۷+ ثانیه‌ای که تلگرام واقعاً
            # می‌خواد کمتره، پس تلاشِ دوباره هم بلافاصله دوباره ۴۲۹ می‌گرفت و بعدِ
            # چند تلاشِ بی‌فایده، attempts تموم می‌شد و پست FAILED گزارش می‌شد
            # (دقیقاً همون چیزی که باعثِ توقفِ زودهنگامِ دکمه‌ی «پست‌های آخر» شد).
            # الان دقیقاً همون مدتی که تلگرام خواسته (+۱ ثانیه حاشیه‌ی اطمینان)
            # صبر می‌کنیم و این تلاش جزوِ سقفِ attempts حساب نمی‌شه، چون این
            # اصلاً «شکست» نیست - فقط باید صبر کرد.
            last_exc = e
            flood_retries += 1
            if flood_retries > 5:
                raise
            log.info(
                "ارسالِ %s با کنترلِ سیلِ تلگرام (Flood control) مواجه شد؛ طبقِ خودِ "
                "تلگرام %.1f ثانیه صبر می‌شه (تلاشِ فلادِ %s/5).",
                label or "مدیا", e.retry_after, flood_retries,
            )
            await asyncio.sleep(e.retry_after + 1)
        except TelegramError as e:
            attempt += 1
            last_exc = e
            reason_l = str(e).lower()
            if any(m in reason_l for m in _PERMANENT_ERROR_MARKERS):
                raise
            # فیکسِ M1: قبلاً _RETRYABLE_ERROR_MARKERS تعریف شده بود ولی *هیچ‌جا*
            # استفاده نمی‌شد؛ یعنی هر خطایی که «دائمیِ شناخته‌شده» نبود (مثلِ
            # «chat not found»، «bot was blocked»، «not enough rights»،
            # «user is deactivated») هم ۳ بار با backoff دوباره امتحان می‌شد -
            # اتلافِ چند ثانیه وقت و چند تلاشِ محکوم‌به‌شکست به‌ازای هر مقصد.
            # حالا فقط خطاهایی که واقعاً «گذرا/شبکه‌ای»‌اند (در این لیست) retry
            # می‌شن؛ بقیه بلافاصله بالا پرتاب می‌شن تا پست زودتر (به‌جای معطلی)
            # به‌عنوانِ ناموفق گزارش/رد بشه. اگه یک خطای ناشناخته‌ی جدید بیاد که
            # توی هیچ‌کدوم از دو لیست نیست، محافظه‌کارانه retry می‌کنیم (رفتارِ قبلی
            # برای حالتِ نامشخص حفظ می‌شه تا خطای گذرای واقعی به‌اشتباه رها نشه).
            is_known_retryable = any(m in reason_l for m in _RETRYABLE_ERROR_MARKERS)
            is_unknown = not is_known_retryable
            if is_known_retryable or is_unknown:
                if attempt >= attempts:
                    raise
                log.info(
                    "ارسالِ %s ناموفق بود (تلاشِ %s/%s): %s - بعدِ %.1f ثانیه دوباره امتحان می‌شه.",
                    label or "مدیا", attempt, attempts, e, base_delay * attempt,
                )
                await asyncio.sleep(base_delay * attempt)
            else:
                raise


async def _maybe_public_success_report(bot: Bot, owner_user_id, destinations, channel_id: int) -> None:
    """اگر «کانال عمومی گزارش‌ها» تنظیم شده باشد و این کانالِ مبدأ مالک داشته باشد،
    گزارشِ پست‌گذاریِ موفق را در آن کانال منتشر می‌کند (شفافیتِ تیمی - قابلیت ۹).
    اگر کانال عمومی تنظیم نشده باشد، هیچ کاری نمی‌کند.

    توجه: این گزارش برایِ کانال‌هایِ خودِ ادمین (owner_user_id خالی/None) هم
    باید فرستاده بشه، نه فقط برایِ کانال‌هایِ کاربرانِ اضافه‌شده - قبلاً یه
    خروجِ زودهنگام این‌جا بود که باعث می‌شد پستِ کانال‌هایِ ادمین اصلاً به
    کانالِ عمومی گزارش نشه؛ الان _mention_for خودش None رو به «ادمین» تبدیل
    می‌کنه، پس نیازی به رد کردنِ زودهنگام نیست."""
    try:
        from .public_report_channel import PublicReportChannel
        if not PublicReportChannel.is_enabled():
            return
        dest_titles = "، ".join(str(d["title"] or d["chat_id"]) for d in destinations)
        await PublicReportChannel.send_success_report(
            bot, owner_user_id, dest_titles, channel_id=channel_id,
        )
    except Exception as e:
        log.warning("ارسالِ گزارشِ عمومیِ موفقیت ناموفق بود: %s", e)


async def _maybe_public_destination_post_report(bot: Bot, dest, post_link: str = "") -> None:
    """گزارشِ «پستِ به‌موقع» برایِ همین مقصدِ به‌خصوص، مستقل از گزارشِ سطحِ کانالِ
    مبدأ بالا - چون اون یکی همه‌ی مقصدهایِ یک کانال رو با هم گزارش می‌ده و مالکِ
    کانالِ مبدأ رو تگ می‌کنه، ولی این یکی مالِ خودِ همین مقصدِ به‌خصوصه و مسئولش
    (owner_user_id ثبت‌شده روی خودِ همون مقصد) رو مستقیم تگ می‌کنه - دقیقاً
    هم‌سطحِ کارتِ اخطار/تشکر، تا شفافیتِ «کی الان به‌موقع پست گذاشت» هم مثلِ
    «کی اخطار گرفت» در کانالِ عمومی دیده بشه. اگه لینکِ خودِ پست هم ساخته شده
    باشه (post_link)، همراهِ گزارش می‌آد تا بشه مستقیم رفت و پست رو دید.

    اگه این مقصد الان اخطارِ بازِ عدم‌فعالیت داره، این‌جا چیزی نمی‌فرستیم؛ چون
    اون حالت («جبرانِ اخطار») توسطِ send_destination_thanks_card در
    scheduler.py گزارش می‌شه و فرستادنِ این کارت هم باعثِ دوتا پیامِ تکراری
    برای یک پست می‌شد.
    """
    owner_user_id = dest["owner_user_id"] if "owner_user_id" in dest.keys() else None
    try:
        if db.has_open_destination_warning(dest["id"]):
            return
        from .public_report_channel import PublicReportChannel
        if not PublicReportChannel.is_enabled():
            return
        await PublicReportChannel.send_destination_post_report(bot, dest, owner_user_id, post_link=post_link)
    except Exception as e:
        log.warning("ارسالِ گزارشِ پستِ به‌موقعِ مقصدِ %s ناموفق بود: %s", dest["id"], e)


async def _notify_admins_of_failures(
    bot: Bot, failures: list[tuple[str, str]], channel_id: int | None = None,
) -> None:
    """failures: لیستی از (اسم/آیدیِ مقصد، دلیلِ خطا). فقط اگه از آخرین اطلاع‌رسانیِ
    همون مقصد مدتی گذشته باشه دوباره پیام می‌فرسته، تا اسپم نشه.

    اگه این کانالِ مبدأ مالکِ (owner_user_id) فعال داشته باشه، اعلان فقط به
    کانالِ تاییدِ اختصاصیِ همون مالک می‌ره - نه به ادمین‌های سراسری. کانال‌های
    بدونِ مالک (متعلق به خودِ ادمینِ سراسری) طبق رفتارِ قبلی به ADMIN_IDS می‌ره.
    """
    now = time.monotonic()
    to_report = []
    for dest_label, reason in failures:
        last = _last_failure_notify.get(dest_label)
        if last is None or (now - last) >= _FAILURE_NOTIFY_COOLDOWN_SECONDS:
            to_report.append((dest_label, reason))
            _last_failure_notify[dest_label] = now
    if not to_report:
        return

    lines = ["⚠️ <b>ارسال به بعضی مقصدها ناموفق بود</b>\n"]
    for dest_label, reason in to_report:
        lines.append(f"• <b>{_esc(str(dest_label))}</b>: {_esc(reason)}")
    lines.append(
        "\nاگه دلیلش «ادمین نبودنِ ربات» هست، ربات رو توی اون کانال ادمین کن "
        "(با دسترسیِ ارسال پیام) و دوباره تلاش می‌شه."
    )
    text = "\n".join(lines)

    targets = list(config.ADMIN_IDS)
    used_owner_targets = False
    if channel_id is not None:
        channel_row = db.get_channel(channel_id)
        if channel_row is not None:
            owned_targets, owner_id = _approval_targets(channel_row)
            if owner_id:
                targets = owned_targets
                used_owner_targets = True

    if not used_owner_targets:
        # کانالِ خودِ ادمینِ اصلی: از مدیریتِ اعلان‌ها استفاده می‌کنیم تا در صورتِ
        # تنظیمِ «کانالِ اختصاصیِ اعلان‌ها» پیام آنجا برود (قابلیت ۸)؛ در غیر این
        # صورت به‌صورتِ پیش‌فرض در خودِ رباتِ ادمین ارسال می‌شود.
        try:
            from .notification_manager import NotificationManager
            await NotificationManager.send_admin_notification(bot, text, notification_type="error")
            return
        except Exception as e:
            log.warning("اطلاع‌رسانیِ خطا از طریقِ مدیریتِ اعلان‌ها ناموفق بود؛ به روشِ مستقیم برمی‌گردیم: %s", e)

    for admin_id in targets:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode=ParseMode.HTML)
        except TelegramError as e:
            log.warning("اطلاع‌رسانیِ خطای ارسال به ادمین %s ناموفق بود: %s", admin_id, e)

_PLATFORM_SETTING_KEYS = [
    "text", "position", "color_mode", "color_a", "color_b",
    "bg_opacity", "font_size", "margin", "album_all", "badge_scale",
]


def gather_watermark_settings(channel_id: int | None = None) -> dict:
    owner = _owner_of_channel(channel_id)
    s: dict = {
        "watermark_enabled": db.get_effective_bool(channel_id, "watermark_enabled", True),
        "wm_tg_enabled": db.get_effective_bool(channel_id, "wm_tg_enabled", True, owner_user_id=owner),
        "wm_ig_enabled": db.get_effective_bool(channel_id, "wm_ig_enabled", False, owner_user_id=owner),
    }
    for prefix in ("wm_tg", "wm_ig"):
        for k in _PLATFORM_SETTING_KEYS:
            s[f"{prefix}_{k}"] = db.setting_get(f"{prefix}_{k}", owner_user_id=owner)
    return s


def gather_ai_settings(channel_id: int | None = None) -> dict:
    return {
        "remove_enabled": db.get_effective_bool(channel_id, "ai_removal_enabled", False),
    }


def _dest_wms_for_slot(destination_id: int | None, first_slot: bool = True) -> list:
    """واترمارک‌های دلخواهِ متصل به این مقصد که باید روی این اسلاتِ خاصِ عکس
    (اولین عکسِ پست، یا یکی از عکس‌های بعدیِ آلبوم) اعمال بشن؛ واترمارک‌هایی که
    album_all=0 دارن فقط روی اولین عکس اعمال میشن، نه بقیه‌ی آلبوم."""
    if not destination_id:
        return []
    rows = db.get_watermarks_for_destination(destination_id)
    if not first_slot:
        rows = [r for r in rows if r["album_all"]]
    return list(rows)


async def _apply_dest_watermarks_to_bytes(
    bot, raw: bytes | None, destination_id: int | None, first_slot: bool = True,
) -> bytes | None:
    """اعمالِ واترمارک‌های دلخواهِ متصل به این مقصد روی بایت‌هایی که از قبل
    نهایی شدن (مثلاً عکسِ جایگزینِ ادمین) - برخلافِ process_photo_bytes که
    خودش این کار رو داخلی انجام می‌ده."""
    if raw is None:
        return raw
    wms = _dest_wms_for_slot(destination_id, first_slot=first_slot)
    if not wms:
        return raw
    from .custom_watermark import apply_named_watermarks
    return await apply_named_watermarks(bot, raw, wms)


def _photo_needs_processing(channel_id: int | None = None, destination_id: int | None = None) -> bool:
    """آیا این عکس اصلاً نیاز به پردازش (حذفِ واترمارک/بهبودِ کیفیت/واترمارکِ خودمان)
    دارد؟ اگر نه، می‌توان عکس را مستقیماً با URL به تلگرام سپرد و از دانلود و
    آپلودِ دوباره صرف‌نظر کرد تا ارسال به‌مراتب سریع‌تر شود."""
    if db.get_effective_bool(channel_id, "ai_removal_enabled", False):
        return True
    if db.get_bool("quality_enhance_enabled", False):
        return True
    wm = gather_watermark_settings(channel_id)
    if bool(wm.get("watermark_enabled", True)) and (
        bool(wm.get("wm_tg_enabled", True)) or bool(wm.get("wm_ig_enabled", False))
    ):
        return True
    if _dest_wms_for_slot(destination_id, first_slot=True):
        return True
    return False


async def process_photo_bytes(
    raw: bytes, channel_id: int | None = None, bot=None,
    destination_id: int | None = None, first_slot: bool = True,
) -> bytes:
    """
    یک عکسِ خام رو کامل پردازش می‌کنه: اول (اگه فعال بود) با هوش مصنوعی واترمارکِ
    قبلی/لوگوی کانال مبدأ رو حذف/ترمیم می‌کند، بعد (اگه فعال بود) کیفیتِ عکس رو با
    AI بهبود می‌ده (چون منبع از صفحه‌ی وبِ فشرده‌ی تلگرام میاد)، بعد واترمارک(های)
    خودمان (تلگرام/اینستاگرام) را روی آن می‌چسباند، و در آخر (اگه به این مقصدِ
    مشخص واترمارکِ دلخواه‌ای وصل شده باشه) واترمارک‌های دلخواهِ همون مقصد رو هم
    اضافه می‌کنه. هر مرحله‌ی سنگین از طریق `concurrency.run_heavy` در ترد جدا و
    زیر Semaphore اجرا می‌شود تا ربات هیچ‌وقت برای کاربر «هنگ‌کرده» به نظر نرسد.

    channel_id: اگه داده بشه، تنظیماتِ اختصاصیِ همون کانالِ مبدأ (در صورتِ وجود)
    به‌جای تنظیمِ عمومی/سراسری استفاده میشه (نگاه کن به OVERRIDABLE_TOGGLES در database.py).
    bot / destination_id: اگه داده بشن، واترمارک‌های دلخواهِ متصل‌شده به همین
    مقصد هم (علاوه بر واترمارکِ عمومیِ تلگرام/اینستاگرام) روی عکس اعمال میشه؛
    اعمالِ واترمارک‌های تصویری نیاز به bot داره چون لوگو از رویِ file_id تلگرام
    دانلود می‌شه.
    """
    ai_settings = gather_ai_settings(channel_id)
    remove_on = ai_settings["remove_enabled"]
    quality_on = db.get_bool("quality_enhance_enabled", False)
    wm_settings = gather_watermark_settings(channel_id)
    wm_on = bool(wm_settings.get("watermark_enabled", True)) and (
        bool(wm_settings.get("wm_tg_enabled", True)) or bool(wm_settings.get("wm_ig_enabled", False))
    )
    dest_wms = _dest_wms_for_slot(destination_id, first_slot=first_slot)
    if dest_wms and bot is None:
        log.warning("مقصدِ #%s واترمارکِ دلخواه داره ولی bot به process_photo_bytes پاس داده نشده؛ نادیده گرفته شد.", destination_id)
        dest_wms = []

    # مسیرِ سریع: اگر هیچ پردازشی لازم نباشد (حذفِ واترمارک، بهبودِ کیفیت،
    # واترمارکِ خودمان و واترمارک‌های دلخواهِ این مقصد همه خاموش‌اند)، عکسِ خام
    # بدونِ باز/بسته‌کردن و رمزگذاریِ دوباره‌ی JPEG برگردانده می‌شود؛ این هم
    # سرعت را بیشتر می‌کند و هم از افتِ کیفیتِ ناشی از رمزگذاریِ بی‌مورد جلوگیری می‌کند.
    if not remove_on and not quality_on and not wm_on and not dest_wms:
        return raw

    if remove_on:
        raw = await concurrency.run_heavy(
            ai_watermark.process_image_sync,
            raw,
            remove_enabled=remove_on,
        )
    if quality_on:
        raw = await concurrency.run_heavy(sr_model.enhance_photo_sync, raw)
    raw = await concurrency.run_heavy(add_watermark, raw, wm_settings)
    if dest_wms:
        from .custom_watermark import apply_named_watermarks
        raw = await apply_named_watermarks(bot, raw, dest_wms)
    return raw


def _build_footer_html(channel_id: int | None = None, destination_id: int | None = None) -> str:
    """
    امضای پایانِ پست رو طبقِ حالتِ فعلی می‌سازه:
    - حالتِ «link» (پیش‌فرض/رفتار قبلی): فقط یک لینکِ کلیکی به @handle.
    - حالتِ «custom»: متنِ کاملاً دلخواهِ ادمین (چندخطی، با فرمتِ خودِ تلگرام)،
      که در صورتِ وجودِ {link}/{handle} داخلش، اونا هم جایگزین میشن.

    اگه این مقصد (destination_id) امضای اختصاصیِ خودش رو روشن کرده باشه
    (footer_override)، به‌جای تنظیماتِ عمومیِ کاربر/کانالِ مبدأ، از امضای مختصِ
    همون مقصد استفاده می‌شه — پس هر کانالِ مقصد می‌تونه امضای کاملاً جدا داشته باشه.
    """
    if destination_id and db.dest_setting_get_bool(destination_id, "footer_override", False):
        if not db.dest_setting_get_bool(destination_id, "footer_enabled", True):
            return ""
        handle = db.dest_setting_get(destination_id, "footer_channel_handle", "").lstrip("@")
        url = db.dest_setting_get(destination_id, "footer_channel_url", "") or (f"https://t.me/{handle}" if handle else "")
        mode = db.dest_setting_get(destination_id, "footer_mode", "link")
        if mode == "custom":
            custom_html = db.dest_setting_get(destination_id, "footer_custom_text", "")
            if not custom_html.strip():
                return ""
            template = db.dest_setting_get(destination_id, "footer_text_template", "@{handle}")
            return render_custom_footer(custom_html, handle, url, template)
        if not handle:
            return ""
        template = db.dest_setting_get(destination_id, "footer_text_template", "@{handle}")
        return make_footer_html(handle, url, template)

    owner = _owner_of_channel(channel_id)
    if not db.get_effective_bool(channel_id, "footer_enabled", True, owner_user_id=owner):
        return ""
    handle = db.setting_get("footer_channel_handle", "", owner_user_id=owner).lstrip("@")
    url = db.setting_get("footer_channel_url", "", owner_user_id=owner) or (f"https://t.me/{handle}" if handle else "")
    mode = db.setting_get("footer_mode", "link", owner_user_id=owner)
    if mode == "custom":
        custom_html = db.setting_get("footer_custom_text", "", owner_user_id=owner)
        if not custom_html.strip():
            return ""
        template = db.setting_get("footer_text_template", "@{handle}", owner_user_id=owner)
        return render_custom_footer(custom_html, handle, url, template)
    if not handle:
        return ""
    template = db.setting_get("footer_text_template", "@{handle}", owner_user_id=owner)
    return make_footer_html(handle, url, template)




def _remove_phrases(body_html: str, channel_id: int | None, destination_id: int | None) -> str:
    """حذفِ عبارت‌ها/ایموجی‌هایی که کاربر برای پاک‌شدن از متنِ پست تعریف کرده.
    اولویت با لیستِ خودِ کانالِ مقصده (اگه براش تعریف شده باشه)؛ وگرنه لیستِ
    سراسریِ صاحبِ کانالِ مبدأ (ادمین یا کاربر) اعمال می‌شه. چون این تابع داخلِ
    build_caption_html/build_message_html صدا زده می‌شه، همه‌ی حالت‌های ارسال
    (لحظه‌ای، زمان‌بندی، بازه‌ای و صفِ تایید) رو پوشش می‌ده."""
    raw = ""
    if destination_id:
        raw = db.dest_setting_get(destination_id, "ad_filter_remove_phrases", "")
    if not raw:
        owner = _owner_of_channel(channel_id)
        raw = db.setting_get("ad_filter_remove_phrases", "", owner_user_id=owner)
    phrases = parse_phrases(raw)
    if not phrases:
        return body_html
    return strip_phrases_html(body_html, phrases)


# ============================================================================
# دکمه‌های شیشه‌ایِ رنگی زیرِ پست‌های ری‌پست‌شده
# ----------------------------------------------------------------------------
# همه‌ی تنظیمات (متن/لینک/رنگ/زمان‌بندی/فعال‌بودن به تفکیکِ مقصد) در فایلِ
# bot/button_config.py هست. این‌جا فقط بر اساسِ اون کانفیگ، کیبوردِ مناسبِ همین
# مقصد و همین پست ساخته می‌شه (با درنظرگرفتنِ بازه‌ی ساعتی و نشانه‌ی «دکمه نذار»).
from .button_style import build_repost_markup as _build_repost_markup


def _apply_vpn_howto_cleanup(body: str, channel_id: int | None, media: list | None) -> str:
    """فقط وقتی تاگلِ اختصاصیِ «vpn_howto_cleanup_enabled» برای این کانالِ مبدأ
    روشن باشه: خط‌های «نحوه اتصال داخل ...» / «اینترنت آزاد برای ...» / نقل‌قولِ
    «برای دریافت ... کلیک کن» حذف می‌شن و اگه پست فایلِ .nm/.npvt داشته باشه،
    کپشنِ ثابتِ استاندارد‌شده جایگزینِ خطِ توضیحی می‌شه (نگاه کن به formatter.py)."""
    owner = _owner_of_channel(channel_id)
    if not db.get_effective_bool(channel_id, "vpn_howto_cleanup_enabled", False, owner_user_id=owner):
        return body
    body = strip_vpn_source_boilerplate(body)
    body = apply_netmod_npvtunnel_caption(body, media or [])
    return body


def build_caption_html(
    post_text_html: str, channel_id: int | None = None, destination_id: int | None = None,
    media: list | None = None,
) -> str:
    owner = _owner_of_channel(channel_id)
    preserve = db.get_effective_bool(channel_id, "preserve_formatting", True, owner_user_id=owner)
    body = post_text_html if preserve else _esc(strip_html_tags(post_text_html))
    body = _remove_phrases(body, channel_id, destination_id)
    body = _apply_vpn_howto_cleanup(body, channel_id, media)
    body = rename_avocado_proxy_links_in_html(body)  # متنِ لینکِ «آواکادوپروکسی» → «پروکسی»/«پروکسی N»
    body = rename_configs_in_html(body)  # اسمِ کانفیگ‌ها → نامِ ثابت (آدرسِ مبدأ حذف)
    body = apply_fixed_config_caption(body)  # کپشنِ کانالِ مبدأ حذف و کپشنِ ثابتِ کانفیگ/پروکسی جایگزین می‌شه
    if db.get_effective_bool(channel_id, "vpn_signature_footer_enabled", False, owner_user_id=owner):
        body = append_vpn_signature(body, media)  # امضای VFREEPN زیرِ پست‌های کانفیگ/پروکسی/فایل

    footer_html = _build_footer_html(channel_id, destination_id)

    full = append_footer(body, footer_html)
    full = ensure_rtl_lines(full)
    limit = db.setting_get_int("max_caption_length", 1024, owner_user_id=owner)
    return truncate_html_safe(full, limit)


TELEGRAM_TEXT_LIMIT = 4096


def build_message_html(
    post_text_html: str, channel_id: int | None = None, destination_id: int | None = None,
    limit: int = TELEGRAM_TEXT_LIMIT, media: list | None = None,
) -> str:
    owner = _owner_of_channel(channel_id)
    preserve = db.get_effective_bool(channel_id, "preserve_formatting", True, owner_user_id=owner)
    body = post_text_html if preserve else _esc(strip_html_tags(post_text_html))
    body = _remove_phrases(body, channel_id, destination_id)
    body = _apply_vpn_howto_cleanup(body, channel_id, media)
    body = rename_avocado_proxy_links_in_html(body)  # متنِ لینکِ «آواکادوپروکسی» → «پروکسی»/«پروکسی N»
    body = rename_configs_in_html(body)  # اسمِ کانفیگ‌ها → نامِ ثابت (آدرسِ مبدأ حذف)
    body = apply_fixed_config_caption(body)  # کپشنِ کانالِ مبدأ حذف و کپشنِ ثابتِ کانفیگ/پروکسی جایگزین می‌شه
    if db.get_effective_bool(channel_id, "vpn_signature_footer_enabled", False, owner_user_id=owner):
        body = append_vpn_signature(body, media)  # امضای VFREEPN زیرِ پست‌های کانفیگ/پروکسی/فایل

    footer_html = _build_footer_html(channel_id, destination_id)

    full = append_footer(body, footer_html)
    full = ensure_rtl_lines(full)
    # limit خیلی بزرگ = بدونِ بریدن (متنِ کامل برگردانده می‌شه تا send_post خودش
    # در صورتِ نیاز به چند پیام تقسیمش کنه و هیچ کانفیگی گم نشه).
    return truncate_html_safe(full, limit)


_TAG_RE = re.compile(r"<[^>]+>")


def _visible_len(s: str) -> int:
    """طولِ متنِ دیده‌شدنی (بدونِ تگ، با entityهای HTML باز‌شده) بر حسبِ UTF-16 —
    همون چیزی که تلگرام می‌شماره. سریع و بی‌سروصدا (بدونِ BeautifulSoup)."""
    return tg_text_len(_unescape(_TAG_RE.sub("", s)))


class _StackTracker(HTMLParser):
    """برای هر خطِ متن، پشته‌ی تگ‌های بازِ همون لحظه رو ثبت می‌کنه؛ تا موقعِ تقسیم
    بدونیم چه تگ‌هایی باید ته یک تکه بسته و اولِ تکه‌ی بعد دوباره باز بشن (با همون
    صفت‌ها، مثلِ expandable)."""

    _VOID = {"br", "hr", "img"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, str]] = []
        self.line_stacks: list[list[tuple[str, str]]] = []

    @staticmethod
    def _attrs(attrs) -> str:
        return "".join(f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs)

    def handle_starttag(self, tag, attrs):
        if tag not in self._VOID:
            self.stack.append((tag, f"<{tag}{self._attrs(attrs)}>"))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i]
                break

    def handle_data(self, data):
        for _ in range(data.count("\n")):
            self.line_stacks.append(list(self.stack))

    def close(self):
        super().close()
        self.line_stacks.append(list(self.stack))


def _line_open_stacks(full_html: str, n_lines: int) -> list[list[tuple[str, str]]]:
    t = _StackTracker()
    t.feed(full_html)
    t.close()
    ls = t.line_stacks
    if len(ls) < n_lines:
        ls += [ls[-1] if ls else []] * (n_lines - len(ls))
    return ls[:n_lines]


def _split_message_html(
    full_html: str, limit: int = TELEGRAM_TEXT_LIMIT, max_chunks: int = 6,
) -> list[str]:
    """پستِ متنیِ طولانی‌تر از سقفِ تلگرام رو به چند پیامِ *معتبر* تقسیم می‌کنه:
    - برشْ فقط سرِ خط انجام می‌شه؛ یک کانفیگِ کامل هیچ‌وقت وسطش بین دو پیام نصف
      نمی‌شه (اگه توی تکه‌ی فعلی جا نشه، کلاً می‌ره تکه‌ی بعدی). فقط اگه یک خط خودش
      از سقفِ یک پیام بزرگ‌تر باشه، به‌ناچار بریده می‌شه.
    - اگه برشْ وسطِ یک نقل‌قول/کدِ چندخطی بیفته، تگ‌های باز ته این تکه بسته و اولِ
      تکه‌ی بعدی دوباره باز می‌شن (با همون صفت‌ها) → تیکه‌ی دوم هم quote/code/expandable
      می‌مونه، نه متنِ ساده. هر دو ساختار (یک بلاک‌کوتِ بزرگ یا یک بلاک‌کوت به‌ازای هر
      کانفیگ) درست کار می‌کنن.
    - خطِ خالیِ بینِ کپشن و نقل‌قول حفظ می‌شه.
    - طولْ بر حسبِ واحدهای UTF-16 (ملاکِ واقعیِ تلگرام) شمرده می‌شه."""
    from .formatter import _balance_html, _tighten_blockquotes
    if _visible_len(full_html) <= limit:
        return [full_html]
    lines = full_html.split("\n")
    stacks = _line_open_stacks(full_html, len(lines))
    chunks: list[str] = []
    prefix = ""          # تگ‌های بازِ دوباره‌بازشده در ابتدای تکه‌ی فعلی
    buf: list[str] = []
    buf_vis = 0
    for i, line in enumerate(lines):
        lv = _visible_len(line)
        sep = 1 if buf else 0
        if buf and (buf_vis + sep + lv) > limit:
            open_stack = stacks[i - 1] if i > 0 else []
            closing = "".join(f"</{t}>" for t, _ in reversed(open_stack))
            chunks.append(prefix + "\n".join(buf) + closing)
            prefix = "".join(op for _, op in open_stack)
            buf = []
            buf_vis = 0
            sep = 0
        buf.append(line)
        buf_vis += sep + lv
    if buf:
        chunks.append(prefix + "\n".join(buf))
    if len(chunks) > max_chunks:
        merged = "\n".join(chunks[max_chunks - 1:])
        chunks = chunks[: max_chunks - 1] + [merged]
    out = []
    for c in chunks:
        c = _balance_html(c)
        # BeautifulSoup (توی _balance_html) خطِ خالیِ بینِ کپشن و اولین نقل‌قول رو
        # وقتی مستقیم بینِ دو تگ باشه (بعدِ </b> قبلِ <blockquote>) بی‌سروصدا به یک
        # خط تبدیل می‌کنه؛ اینجا دوباره تضمینش می‌کنیم تا تکه‌ی اولِ پستِ تقسیم‌شده
        # هم مثلِ حالتِ تک‌پیامی، بینِ کپشن و نقل‌قول یک خطِ خالی داشته باشه.
        c = _tighten_blockquotes(c)
        if _visible_len(c) > limit:
            c = truncate_html_safe(c, limit)
        out.append(c)
    return [c for c in out if strip_html_tags(c).strip()]


async def _download(
    url: str, timeout: float = 30.0, retries: int = 3, channel_id: int | None = None
) -> bytes | None:
    """
    فایل رو دانلود می‌کنه. طبقِ درخواستِ صریح، پست هیچ‌وقت نباید ناقص (بدون
    مدیا) فرستاده بشه، پس این تابع سرِ اولین شکستِ موقتی (تایم‌اوت، قطعیِ
    لحظه‌ایِ شبکه، خطای 5xx سمتِ سرورِ تلگرام) تسلیم نمیشه؛ چند بار با فاصله
    و تایم‌اوتِ بیشتر دوباره امتحان می‌کنه. فقط بعد از تمام‌شدنِ همه‌ی تلاش‌ها
    None برمی‌گردونه (و آن‌وقت است که poster.py کلِ پست را رد می‌کند، نه یک
    تلاشِ نصفه‌ونیمه).
    """
    cache_on = db.get_effective_bool(channel_id, "download_cache_enabled", True)
    if cache_on:
        cached = await cache.get(url)
        if cached is not None:
            log.debug("فایل از کش دانلود برگردانده شد: %s", url)
            return cached

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        attempt_timeout = timeout * attempt
        try:
            # فیکسِ C4: به‌جای r.content (که کلِ فایل رو - هرچقدر هم بزرگ - یک‌جا
            # توی رم می‌ریخت و با یک ویدیوی چندصد مگابایتی باعثِ OOM-kill می‌شد)،
            # استریمی می‌خونیم و به محضِ ردشدن از سقفِ MAX_DOWNLOAD_BYTES رهاش
            # می‌کنیم. اول هم اگه Content-Length از سقف بزرگ‌تر بود، اصلاً شروع
            # نمی‌کنیم. این خطای «حجمِ زیاد» دائمیه، پس با raise کردنِ یک خطای
            # نشانه‌دارِ «too large» بلافاصله (بدونِ retryِ بی‌فایده) رد می‌شه.
            async with httpx.AsyncClient(
                headers=_DOWNLOAD_HEADERS, timeout=attempt_timeout, follow_redirects=True
            ) as c:
                async with c.stream("GET", url) as r:
                    r.raise_for_status()
                    clen = int(r.headers.get("content-length") or 0)
                    if clen and clen > config.MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"فایل بیش از حدِ مجاز است (too large: {clen} بایت)"
                        )
                    buf = bytearray()
                    async for chunk in r.aiter_bytes(256 * 1024):
                        buf += chunk
                        if len(buf) > config.MAX_DOWNLOAD_BYTES:
                            raise ValueError("فایل وسطِ دانلود از حدِ مجاز گذشت (too large)")
                    data = bytes(buf)
            if not data:
                raise ValueError("پاسخِ خالی از سرور")
            if cache_on and len(data) <= _MAX_CACHEABLE_BYTES:
                await cache.set(url, data)
            return data
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500 and status != 429:
                log.warning("دانلود شکست خورد (%s) - وضعیتِ %s، تلاشِ مجدد بی‌فایده‌ست: %s", url, status, e)
                break
            log.warning("دانلود شکست خورد (تلاشِ %s/%s، وضعیتِ %s): %s", attempt, retries, status, url)
        except Exception as e:
            last_error = e
            # فیکسِ C4: خطای «حجمِ زیاد» دائمیه؛ retry بی‌فایده‌ست و فقط وقت تلف
            # می‌کنه (و می‌تونه سه بار پشتِ‌سرِ‌هم رمِ زیاد بگیره). بلافاصله رها می‌شه.
            if "too large" in str(e).lower():
                log.warning("دانلود رها شد (فایل بیش از حدِ مجاز): %s - %s", url, e)
                break
            log.warning("دانلود شکست خورد (تلاشِ %s/%s): %s - %s", attempt, retries, url, e)

        if attempt < retries:
            await asyncio.sleep(1.5 * attempt)

    log.error("دانلودِ فایل بعد از %s تلاش کاملاً شکست خورد: %s (%s)", retries, url, last_error)
    return None


async def send_post(
    bot: Bot,
    chat_id: str,
    post: Post,
    caption_override: str | None = None,
    photo_override: bytes | None = None,
    video_override: bytes | None = None,
    channel_id: int | None = None,
    destination_id: int | None = None,
    _strip_premium_emoji: bool = False,
) -> tuple[bool, str | None, str]:
    """
    یک پست رو کامل به یک کانال مقصدِ مشخص می‌فرسته.
    خروجی: (موفقیت، دلیلِ خطا-اگه‌ناموفق‌بود، لینکِ پستِ ارسال‌شده-اگه‌موفق‌بود).
    قبلاً این تابع فقط True/False برمی‌گردوند و دلیلِ شکست فقط توی فایلِ لاگ
    می‌موند - یعنی اگه ربات مثلاً توی یکی از دو کانال مقصد ادمین نبود، ادمین
    هیچ خبری از این نمی‌شد و فقط حس می‌کرد «ارسال به هر دو مقصد هم‌زمان کار
    نمی‌کنه». حالا دلیل دقیق برمی‌گرده تا بشه به ادمین اطلاع داد. لینکِ پست هم
    برای این اضافه شده که گزارش‌های کانالِ عمومی بتونن مستقیم به خودِ پست لینک
    بدن (اگه ساختنِ لینک ممکن نبود - مثلاً چندتایی/آلبومِ بدونِ آیدیِ قابلِ‌اتکا -
    رشته‌ی خالی برمی‌گرده و گزارش بدونِ لینک نمایش داده می‌شه).

    caption_override: اگه مقدار داشته باشه (حتی رشته‌ی خالی)، به‌جای ساختنِ کپشن از
    روی post.html_text، همین مقدار عینا استفاده میشه.
    photo_override: اگه بایتِ عکس داده شده باشه، به‌جای دانلود کردنِ عکسِ اولِ پست،
    همین عکس (که قبلا واترمارک روش زده شده) به‌عنوان عکسِ اصلی/جلدِ پست فرستاده میشه.
    video_override: اگه بایتِ ویدیو داده شده باشه، به‌جای دانلود کردنِ ویدیوی اصلیِ
    پست، عیناً همین ویدیو (که ادمین جایگزین کرده) به‌جای خودِ ویدیو فرستاده میشه.
    channel_id: کانالِ مبدأیی که این پست ازش اومده - اگه داده بشه، override های
    اختصاصیِ همون کانال (واترمارک/فیلتر/امضا/قالب‌بندی/کش) به‌جای تنظیمِ عمومی
    اعمال میشه.
    destination_id: کانالِ مقصدِ همینِ ارسال - اگه داده بشه، واترمارک‌های دلخواهِ
    متصل‌شده به همین مقصد (تنظیم‌شده در بخشِ «واترمارکِ سفارشی») هم روی عکسِ
    ارسالی اعمال میشن (علاوه بر واترمارکِ خودکارِ تلگرام/اینستاگرام).
    """
    if not chat_id:
        log.error("chat_id مقصد خالیه؛ ارسال ممکن نیست.")
        return False, "آیدی/یوزرنیم کانال مقصد خالیه.", ""

    sent_message = None  # اولین پیامِ واقعاً ارسال‌شده - برایِ ساختنِ لینکِ پست

    # ---------- بازسازیِ ریپلای در مقصد ----------
    # اگه این پستِ مبدأ روی یک پستِ دیگه ریپلای شده و اون پستِ ریپلای‌شده قبلاً
    # به همین مقصد ارسال شده باشه، پیامِ جدید هم توی مقصد روی همون پیام ریپلای
    # می‌شه. اگه پیامِ متناظر پیدا نشد (مثلاً پستِ ریپلای‌شده فیلتر/رد شده بود یا
    # قدیمی‌تر از شروعِ ری‌پست بود)، بدونِ ریپلای ارسال می‌شه (allow_sending_without_reply).
    _reply_params: Optional[ReplyParameters] = None
    _reply_src_pid = getattr(post, "reply_to_post_id", None)
    if _reply_src_pid and channel_id is not None and destination_id is not None:
        _target_mid = db.get_mapped_message_id(channel_id, _reply_src_pid, destination_id)
        if _target_mid:
            _reply_params = ReplyParameters(
                message_id=_target_mid, allow_sending_without_reply=True
            )

    photos = [m for m in post.media if m.type == "photo"]
    videos = [m for m in post.media if m.type == "video"]
    others = [m for m in post.media if m.type not in ("photo", "video")]
    sendable_media = list(post.media)
    _owner_for_album = _owner_of_channel(channel_id)
    wm_all_album = (
        db.setting_get_bool("wm_tg_album_all", True, owner_user_id=_owner_for_album)
        or db.setting_get_bool("wm_ig_album_all", True, owner_user_id=_owner_for_album)
    )

    if caption_override is not None:
        # حتی وقتی کپشن از قبل ساخته/ویرایش شده (مثلاً صفِ تایید)، بازم اسمِ کانفیگ‌ها
        # رو ثابت می‌کنیم تا آدرسِ مبدأ روی کانفیگِ کپی‌شده نمونه، و لینک‌هایی که
        # متن‌شون «آواکادوپروکسی» است رو هم به «پروکسی»/«پروکسی N» تبدیل می‌کنیم
        # (idempotent - اگه قبلاً تبدیل شده باشن، تغییری نمی‌کنه).
        caption_override = rename_avocado_proxy_links_in_html(caption_override)
        caption_override = rename_configs_in_html(caption_override)
        limit = db.setting_get_int("max_caption_length", 1024, owner_user_id=_owner_for_album)
        caption_html = truncate_html_safe(caption_override, limit)
        # متنِ کامل (بدونِ بریدن) نگه داشته می‌شه تا اگه از سقفِ یک پیام بیشتر بود،
        # send_post خودش به چند پیام تقسیمش کنه و چیزی گم نشه.
        message_html = caption_override
    else:
        caption_html = build_caption_html(post.html_text, channel_id, destination_id, media=post.media)
        message_html = build_message_html(post.html_text, channel_id, destination_id, limit=10**7, media=post.media)

    # ---------- ایموجیِ پرمیوم (سفارشی) ----------
    # به‌طورِ پیش‌فرض آیدیِ ایموجیِ پرمیوم حذف می‌شه و فقط ایموجیِ عادی می‌مونه.
    # فقط اگه گزینه‌ی «ایموجیِ پرمیوم» برای این کانال روشن باشه، تگِ <tg-emoji>
    # با آیدی حفظ می‌شه تا در مقصد هم پرمیوم نمایش داده بشه. توجه: ارسالِ ایموجیِ
    # پرمیوم به کانال فقط وقتی کار می‌کنه که خودِ ربات یوزرنیمِ Fragment داشته باشه؛
    # اگه نداشته باشه، تلگرام خطا می‌ده و ما (در بلاکِ except) خودکار بدونِ ایموجیِ
    # پرمیوم دوباره می‌فرستیم تا پست از دست نره. _strip_premium_emoji=True یعنی
    # همین تلاشِ دوباره‌ی بدونِ ایموجیِ پرمیوم.
    _premium_on = db.get_effective_bool(
        channel_id, "premium_emoji_enabled", False, owner_user_id=_owner_for_album
    )
    if _strip_premium_emoji or not _premium_on:
        caption_html = strip_custom_emoji(caption_html)
        message_html = strip_custom_emoji(message_html)

    # ---------- کپشنِ بلندتر از سقفِ رسانه → متنِ کامل در پیامِ جدا ----------
    # سقفِ کپشنِ عکس/ویدیو برای بات‌ها ۱۰۲۴ نویسه‌ست (کانالِ مبدأ اگه پرمیوم باشه تا
    # ۲۰۴۸ می‌فرسته، برای همین اونجا کامله). اگه متنِ پست از این سقف بیشتر باشه،
    # به‌جای بریدنِ تهِ کپشن، رسانه رو *بدونِ کپشن* می‌فرستیم و متنِ کامل رو در یک
    # پیامِ متنیِ جدا (سقف ۴۰۹۶) بلافاصله بعدش می‌فرستیم تا هیچ‌چیز از متن/پرامپت
    # گم نشه. (طولِ متنِ ساده‌ی بدونِ تگ ملاکه، چون سقفِ تلگرام روی متنِ نمایشیه.)
    _media_caption_limit = db.setting_get_int("max_caption_length", 1024, owner_user_id=_owner_for_album)
    # طولْ بر حسبِ واحدهای UTF-16 (ملاکِ واقعیِ تلگرام) سنجیده می‌شه، هم‌راستا با
    # سقفِ کپشن و برشِ truncate_html_safe؛ وگرنه یک کپشنِ پُر از ایموجی که از سقفِ
    # UTF-16 رد شده ولی از سقفِ code-point نه، به‌اشتباه «سرریز نشده» تشخیص داده
    # می‌شد و متنِ اضافه‌اش (به‌جای رفتن به پیامِ جدا) بی‌صدا بریده می‌شد.
    _caption_overflows = bool(sendable_media) and tg_text_len(strip_html_tags(message_html)) > _media_caption_limit
    if _caption_overflows:
        caption_html = None

    caption_used = False

    try:
        # ---------- آلبومِ ترکیبی (عکس + ویدیو) یا آلبومِ چندعکسی ----------
        visual_items = list(post.media)
        visual_items = [m for m in visual_items if m.type in ("photo", "video")]

        if len(visual_items) > 1:
            media_group = []
            first_ok_used = False
            video_override_used = False
            for idx, m in enumerate(visual_items):
                is_first_slot = not first_ok_used
                if idx == 0 and m.type == "photo" and photo_override is not None:
                    raw = photo_override
                    raw = await _apply_dest_watermarks_to_bytes(bot, raw, destination_id, first_slot=True)
                elif m.type == "photo":
                    raw = await _download(m.url, channel_id=channel_id)
                    if raw is None:
                        # دانلود نشد → همون لینک رو به تلگرام می‌دیم تا خودش
                        # برداره (بدونِ واترمارک)، به‌جای این‌که این عکس از آلبوم
                        # حذف شه.
                        log.warning(
                            "دانلودِ یکی از عکس‌های آلبومِ پست %s شکست خورد؛ با لینکِ مستقیم "
                            "فرستاده می‌شه (بدونِ واترمارک).",
                            post.id,
                        )
                        raw = m.url
                    elif wm_all_album or is_first_slot:
                        raw = await process_photo_bytes(
                            raw, channel_id, bot=bot, destination_id=destination_id, first_slot=is_first_slot,
                        )
                    else:
                        raw = await _apply_dest_watermarks_to_bytes(bot, raw, destination_id, first_slot=False)
                elif m.type == "video" and video_override is not None and not video_override_used:
                    raw = video_override
                    video_override_used = True
                else:  # video
                    raw = await _download(m.url, timeout=120.0, retries=5, channel_id=channel_id)
                    if raw is None:
                        log.warning(
                            "دانلودِ ویدیوی پست %s شکست خورد (%s)؛ این آیتمِ آلبوم رد شد.",
                            post.id, m.url,
                        )
                        continue

                cap = caption_html if (is_first_slot and not caption_used) else None
                if cap:
                    caption_used = True
                first_ok_used = True
                if m.type == "photo":
                    media_group.append(
                        InputMediaPhoto(media=raw, caption=cap, parse_mode=ParseMode.HTML if cap else None)
                    )
                else:
                    media_group.append(
                        InputMediaVideo(
                            media=raw, caption=cap, parse_mode=ParseMode.HTML if cap else None,
                            supports_streaming=True,
                        )
                    )
            if media_group:
                _group_msgs = await _send_with_retry(
                    lambda: bot.send_media_group(
                        chat_id=chat_id, media=media_group, reply_parameters=_reply_params
                    ),
                    attempts=3, label="آلبوم",
                )
                if _group_msgs:
                    sent_message = _group_msgs[0]

        elif len(photos) == 1:
            _cap = caption_html if not caption_used else None
            if photo_override is None and not _photo_needs_processing(channel_id, destination_id):
                # مسیرِ سریع: هیچ پردازشی لازم نیست؛ عکس مستقیم با URL فرستاده می‌شود
                # (بدونِ دانلود و آپلودِ دوباره). اگر تلگرام نتوانست URL را بگیرد،
                # به روشِ مطمئنِ دانلود+آپلود برمی‌گردیم تا هیچ عکسی جا نماند.
                try:
                    sent_message = await bot.send_photo(
                        chat_id=chat_id, photo=photos[0].url,
                        caption=_cap, parse_mode=ParseMode.HTML if _cap else None,
                        reply_parameters=_reply_params,
                    )
                    caption_used = True
                except TelegramError as e:
                    log.info("ارسالِ مستقیمِ عکس با URL برای پست %s ناموفق بود (%s)؛ به دانلود برمی‌گردیم.", post.id, e)
                    raw = await _download(photos[0].url, retries=5, channel_id=channel_id)
                    if raw is not None:
                        sent_message = await _send_with_retry(
                            lambda: bot.send_photo(
                                chat_id=chat_id, photo=raw,
                                caption=_cap, parse_mode=ParseMode.HTML if _cap else None,
                                reply_parameters=_reply_params,
                            ),
                            attempts=3, label="عکس",
                        )
                        caption_used = True
            else:
                if photo_override is not None:
                    raw = await _apply_dest_watermarks_to_bytes(bot, photo_override, destination_id, first_slot=True)
                else:
                    raw = await _download(photos[0].url, channel_id=channel_id)
                    if raw is not None:
                        raw = await process_photo_bytes(raw, channel_id, bot=bot, destination_id=destination_id, first_slot=True)
                if raw is not None:
                    sent_message = await bot.send_photo(
                        chat_id=chat_id,
                        photo=raw,
                        caption=_cap,
                        parse_mode=ParseMode.HTML,
                        reply_parameters=_reply_params,
                    )
                    caption_used = True
                elif photo_override is None and photos[0].url:
                    # دانلود از سرورِ منبع شکست خورد. به‌جای دورانداختنِ کلِ پست،
                    # عکس رو مستقیم با لینک می‌فرستیم و اجازه می‌دیم خودِ تلگرام
                    # برش داره. تنها هزینه‌ش اینه که واترمارک/پردازش روی این یک
                    # عکس اعمال نمی‌شه - که خیلی بهتر از گم‌شدنِ کاملِ پسته.
                    log.warning(
                        "دانلودِ عکسِ پست %s شکست خورد؛ عکس مستقیم با لینک فرستاده می‌شه "
                        "(بدونِ واترمارک) تا پست از دست نره.",
                        post.id,
                    )
                    sent_message = await _send_with_retry(
                        lambda: bot.send_photo(
                            chat_id=chat_id, photo=photos[0].url,
                            caption=_cap, parse_mode=ParseMode.HTML if _cap else None,
                            reply_parameters=_reply_params,
                        ),
                        attempts=2, label="عکس (لینکِ مستقیم)",
                    )
                    caption_used = True

        elif len(videos) == 1:
            # ویدیو: تا جای ممکن سعی می‌کنیم ارسال بشه، هرچقدرم سنگین باشه یا
            # شبکه لحظه‌ای قطع بشه - هم توی دانلود (retries بیشتر، timeout روبه‌رشد)
            # هم توی خودِ آپلود به تلگرام (_send_with_retry). اگه با همه‌ی این
            # تلاش‌ها بازم نشه (دانلود شکست خورد یا خطای دائمی مثل «حجم بیش از حد
            # مجاز» بود)، پست کاملاً رد میشه و کپشن هم به‌صورتِ جدا فرستاده
            # نمیشه - چون خروجیِ ناقص (کپشن بدونِ ویدیو) بدتر از رد کردنِ کامل پسته.
            # video_override: اگه ادمین ویدیوی جایگزین فرستاده باشه، دانلودِ ویدیوی
            # اصلی اصلاً لازم نیست - همون بایتِ جایگزین مستقیم استفاده میشه.
            if video_override is not None:
                raw_video = video_override
            else:
                raw_video = await _download(videos[0].url, timeout=120.0, retries=5, channel_id=channel_id)
            if raw_video is None:
                log.warning(
                    "دانلودِ ویدیوی پست %s شکست خورد (%s)؛ این ویدیو (و کپشنش) رد شد.",
                    post.id, videos[0].url,
                )
            else:
                _cap = caption_html if not caption_used else None
                sent_message = await _send_with_retry(
                    lambda: bot.send_video(
                        chat_id=chat_id,
                        video=raw_video,
                        caption=_cap,
                        parse_mode=ParseMode.HTML if _cap else None,
                        supports_streaming=True,
                        reply_parameters=_reply_params,
                    ),
                    attempts=4, base_delay=4.0, label="ویدیو",
                )
                caption_used = True

        elif video_override is not None:
            _cap = caption_html if not caption_used else None
            sent_message = await bot.send_video(
                chat_id=chat_id,
                video=video_override,
                caption=_cap,
                parse_mode=ParseMode.HTML if _cap else None,
                supports_streaming=True,
                reply_parameters=_reply_params,
            )
            caption_used = True

        elif photo_override is not None:
            sent_message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_override,
                caption=caption_html if not caption_used else None,
                parse_mode=ParseMode.HTML,
                reply_parameters=_reply_params,
            )
            caption_used = True

        # ---------- بقیه‌ی مدیا (فایل/موزیک) ----------
        for m in others:
            cap = caption_html if not caption_used else None
            parse_mode = ParseMode.HTML if cap else None
            # ریپلای فقط روی اولین پیامِ این پست اعمال می‌شه؛ اگه قبلاً چیزی از این
            # پست ارسال شده (sent_message پر شده) دیگه ریپلای تکرار نمی‌شه.
            _rp = _reply_params if sent_message is None else None
            if m.type == "document":
                _m = await bot.send_document(
                    chat_id=chat_id, document=m.url, caption=cap, parse_mode=parse_mode,
                    reply_parameters=_rp,
                )
                sent_message = sent_message or _m
            elif m.type == "audio":
                _m = await bot.send_audio(
                    chat_id=chat_id, audio=m.url, caption=cap, parse_mode=parse_mode,
                    title=(m.filename or None), reply_parameters=_rp,
                )
                sent_message = sent_message or _m
            elif m.type == "voice":
                # ویسِ (پیامِ صوتیِ) کانالِ مبدأ. اول با URLِ مستقیم امتحان می‌کنیم؛
                # اگه تلگرام نتونست خودش فایل رو برداره، دانلود می‌کنیم و بایت
                # می‌فرستیم تا ویس جا نمونه.
                try:
                    _m = await bot.send_voice(
                        chat_id=chat_id, voice=m.url, caption=cap, parse_mode=parse_mode,
                        reply_parameters=_rp,
                    )
                except TelegramError as _ve:
                    log.info(
                        "ارسالِ مستقیمِ ویسِ پست %s با URL ناموفق بود (%s)؛ به دانلود برمی‌گردیم.",
                        post.id, _ve,
                    )
                    _raw_voice = await _download(m.url, retries=5, channel_id=channel_id)
                    if _raw_voice is None:
                        log.warning("دانلودِ ویسِ پست %s شکست خورد؛ این ویس رد شد.", post.id)
                        continue
                    _m = await _send_with_retry(
                        lambda: bot.send_voice(
                            chat_id=chat_id, voice=_raw_voice, caption=cap,
                            parse_mode=parse_mode, reply_parameters=_rp,
                        ),
                        attempts=3, label="ویس",
                    )
                sent_message = sent_message or _m
            else:
                continue
            caption_used = True

        # ---------- پست فقط متنی ----------
        if not sendable_media and not caption_used:
            has_source_text = bool(caption_override) if caption_override is not None else bool(post.html_text.strip())
            if not has_source_text:
                return False, None, ""
            text = message_html.strip()
            if not text:
                return False, None, ""
            # پستِ متنیِ طولانی‌تر از سقفِ تلگرام (مثلاً پستِ پُر از کانفیگ) به چند
            # پیام تقسیم می‌شه تا هیچ کانفیگی گم نشه و خطای «Message is too long»
            # نگیریم. اولین پیام روی ریپلایِ اصلی می‌شینه؛ بقیه پشتِ‌سرش می‌آن.
            for _part in _split_message_html(text, TELEGRAM_TEXT_LIMIT):
                _rp = _reply_params if sent_message is None else None
                _m = await _send_with_retry(
                    lambda p=_part, rp=_rp: bot.send_message(
                        chat_id=chat_id, text=p, parse_mode=ParseMode.HTML,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                        reply_parameters=rp,
                    ),
                    attempts=3, label="متن",
                )
                if sent_message is None:
                    sent_message = _m
            caption_used = True

        # موفقیت را با «آیا واقعاً چیزی ارسال شد» می‌سنجیم، نه با «آیا کپشن مصرف
        # شد». قبلاً caption_used ملاک بود؛ ولی وقتی پست کپشن نداره یا کپشنش
        # به‌خاطرِ طولانی‌بودن جدا فرستاده می‌شه، هیچ کپشنی به مدیا نمی‌چسبه و
        # caption_used بی‌جهت False می‌مونه - نتیجه‌ش این بود که آلبوم/عکس با موفقیت
        # ارسال می‌شد (200 OK) ولی ربات اون رو «ناموفق» گزارش می‌کرد، پست هر تیک
        # دوباره فرستاده می‌شد (تکراری) و last_post_id هم جلو نمی‌رفت.
        if sent_message is None and sendable_media:
            return False, "دانلودِ مدیای پست (عکس/ویدیو/فایل) از سرورِ منبع شکست خورد؛ پست ناقص ارسال نشد.", ""

        # ---------- متنِ کاملِ کپشنِ طولانی در پیامِ جدا ----------
        # اگه متنِ پست از سقفِ کپشنِ رسانه بیشتر بود، رسانه بدونِ کپشن رفت؛ حالا
        # متنِ کامل رو در یک پیامِ متنیِ جدا (ریپلای به همون رسانه) می‌فرستیم تا
        # کلِ متن برسه و چیزی نصفه/بریده نشه.
        if _caption_overflows and sent_message is not None:
            _full_text = (message_html or "").strip()
            if _full_text:
                _reply_to_mid = sent_message.message_id
                try:
                    for _part in _split_message_html(_full_text, TELEGRAM_TEXT_LIMIT):
                        await _send_with_retry(
                            lambda p=_part, rt=_reply_to_mid: bot.send_message(
                                chat_id=chat_id, text=p, parse_mode=ParseMode.HTML,
                                link_preview_options=LinkPreviewOptions(is_disabled=True),
                                reply_parameters=ReplyParameters(message_id=rt),
                            ),
                            attempts=3, label="متنِ کاملِ کپشن",
                        )
                except TelegramError as _e:
                    log.warning(
                        "ارسالِ متنِ کاملِ پست %s در پیامِ جدا ناموفق بود: %s", post.id, _e,
                    )

        # ---------- دکمه‌ی شیشه‌ایِ رنگی زیرِ پست ----------
        # روی پیامِ اصلیِ ارسال‌شده یک دکمه‌ی لینک‌دارِ رنگی اضافه می‌کنیم.
        # نکته: تلگرام برای آلبوم (media_group) دکمه‌ی اینلاین رو قبول نمی‌کنه؛ در اون
        # حالت این ادیت با خطا برمی‌گرده و بی‌سروصدا نادیده گرفته می‌شه (پست سالم
        # می‌مونه). خطای این مرحله هیچ‌وقت نباید ارسالِ موفق رو خراب کنه.
        if sent_message is not None:
            _post_text_for_marker = caption_override if caption_override is not None else (post.raw_text or "")
            _btn_markup = _build_repost_markup(chat_id, _post_text_for_marker)
            if _btn_markup is not None:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        reply_markup=_btn_markup,
                    )
                except Exception as _btn_err:  # noqa: BLE001 - دکمه نباید جلوی ارسال رو بگیره
                    log.debug(
                        "افزودنِ دکمه‌ی رنگی به پست %s ناموفق بود (نادیده گرفته شد؛ احتمالاً آلبوم بوده): %s",
                        post.id, _btn_err,
                    )

        # ثبتِ نگاشتِ «پستِ مبدأ → پیامِ مقصد» تا اگه بعداً پستی به این پست ریپلای
        # کرد، بتونیم همون ریپلای رو در مقصد بازسازی کنیم.
        if sent_message is not None and channel_id is not None and destination_id is not None:
            try:
                db.set_mapped_message_id(channel_id, post.id, destination_id, sent_message.message_id)
            except Exception as _map_err:  # noqa: BLE001 - نگاشت نباید جلوی ارسال رو بگیره
                log.debug("ثبتِ نگاشتِ ریپلای برای پست %s ناموفق بود: %s", post.id, _map_err)

        post_link = _build_post_link(chat_id, sent_message.message_id if sent_message else None)
        # موفقیت = واقعاً چیزی ارسال شد. قبلاً caption_used برگردونده می‌شد؛ ولی
        # پستی که کپشن نداره (مثلاً آلبومِ بدونِ متن) یا کپشنش جدا فرستاده شده،
        # هیچ کپشنی به مدیا نمی‌چسبونه و caption_used False می‌مونه - اون‌وقت پستِ
        # کاملاً موفق «ناموفق» گزارش می‌شد، هر تیک دوباره ارسال می‌شد (تکراری) و
        # صفِ ترتیب هم قفل می‌موند.
        _ok = (sent_message is not None) or caption_used
        return _ok, (None if _ok else "پست هیچ محتوای قابل‌ارسالی نداشت."), post_link

    except TelegramError as e:
        reason = str(e)
        # اگه ارسال به‌خاطرِ ایموجیِ پرمیوم شکست خورد (ربات یوزرنیمِ Fragment نداره
        # یا آیدیِ ایموجی نامعتبره)، یک‌بار بدونِ ایموجیِ پرمیوم دوباره می‌فرستیم تا
        # پست از دست نره. این تلاشِ دوباره فقط یک‌بار انجام می‌شه.
        _r = reason.lower()
        if (not _strip_premium_emoji) and (
            "custom_emoji" in _r
            or "custom emoji" in _r
            or ("emoji" in _r and "invalid" in _r)
            # خطای پارسِ HTML برای تگِ ایموجیِ سفارشی. تلگرام گاهی اسمِ تگ رو بدونِ
            # خط تیره گزارش می‌ده (tgemoji به‌جای tg-emoji)، پس هر دو حالت رو می‌گیریم.
            # مثال: can't parse entities: unsupported start tag "tgemoji"
            or "tg-emoji" in _r
            or "tgemoji" in _r
            or ("parse" in _r and "emoji" in _r)
            or ("unsupported" in _r and "emoji" in _r)
        ):
            log.info(
                "ارسالِ پست %s با ایموجیِ پرمیوم شکست خورد (%s)؛ بدونِ ایموجیِ پرمیوم دوباره تلاش می‌شه.",
                post.id, e,
            )
            return await send_post(
                bot, chat_id, post,
                caption_override=caption_override,
                photo_override=photo_override,
                video_override=video_override,
                channel_id=channel_id,
                destination_id=destination_id,
                _strip_premium_emoji=True,
            )
        log.error("خطای تلگرام هنگام ارسال پست %s به %s: %s", post.id, chat_id, e)
        if "not enough rights" in reason.lower() or "chat not found" in reason.lower() or "bot is not a member" in reason.lower() or "kicked" in reason.lower():
            reason += " (احتمالاً ربات توی این کانال ادمین نیست یا از کانال حذف/بلاک شده)"
        return False, reason, ""
    except Exception as e:
        log.exception("خطای غیرمنتظره هنگام ارسال پست %s به %s: %s", post.id, chat_id, e)
        return False, f"خطای غیرمنتظره: {e}", ""


# ============================================================================
# اپشن ۱ و ۴: صفِ تایید/ویرایش قبل از ارسال (ارسال به ادمین -> تایید/ویرایش -> مقصد)
# ============================================================================

def media_items_to_json(media: list[MediaItem]) -> list[dict]:
    return [{"type": m.type, "url": m.url, "filename": m.filename} for m in media]


def json_to_media_items(raw: str) -> list[MediaItem]:
    try:
        data = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [MediaItem(type=d.get("type", ""), url=d.get("url", ""), filename=d.get("filename", "")) for d in data]


def _pending_kb(
    pending_id: int, has_video: bool = False, has_photo: bool = True, show_restore: bool = False,
    ad_flagged: bool = False, ad_feedback: str = "",
):
    from . import keyboards as kb
    return kb.pending_post_menu(
        pending_id, has_video=has_video, has_photo=has_photo, show_restore=show_restore,
        ad_flagged=ad_flagged, ad_feedback=ad_feedback,
    )


# نکته‌ی ادغام: کیبورد/دیتابیسِ نسخه‌ی فعلی (keyboards.pending_post_menu +
# database بدونِ ستون‌های flag_chat_id/flag_message_id) دیگه پیامِ ریپلایِ
# جداگانه برای فیدبکِ فیلترِ تبلیغات نمی‌سازه - دکمه‌های فیدبک حالا مستقیماً
# رویِ خودِ پست (از طریقِ _pending_kb با ad_flagged/ad_feedback بالا) نشون داده
# می‌شن. این تابع و pending_flag_banner پایین‌تر عمداً حذف نشدن (فقط دیگه از
# send_pending_preview صدا زده نمی‌شن) تا در صورتِ نیاز به بازگردوندنِ مکانیزمِ
# پیامِ جداگانه، کدش همچنان در دسترس باشه.
def _pending_flag_kb(pending_id: int, ad_feedback: str = ""):
    from . import keyboards as kb
    return kb.pending_flag_menu(pending_id, ad_feedback=ad_feedback)


def pending_post_flags(row) -> tuple[bool, bool, bool, bool, str]:
    """(has_video, has_photo, show_restore, ad_flagged, ad_feedback) رو از رویِ یک
    ردیفِ pending_posts محاسبه می‌کنه - دقیقاً همون منطقی که send_pending_preview
    برای ساختنِ کیبورد استفاده می‌کنه. ad_flagged یعنی این پست به‌خاطرِ مشکوک
    بودن به تبلیغ به صف افتاده (نگاه کن به flag_reason که در _run_ad_filter با
    پیشوندِ "🚩" ساخته می‌شه - جداییِ روشن از پیشوندِ "♻️" فیلترِ تکراری)."""
    media = json_to_media_items(row["media_json"])
    has_video = any(m.type == "video" for m in media)
    has_photo = any(m.type == "photo" for m in media)
    original_caption = row["original_caption_html"] if "original_caption_html" in row.keys() else None
    show_restore = bool(original_caption) and (row["caption_html"] or "") != original_caption
    flag_reason = row["flag_reason"] if "flag_reason" in row.keys() else ""
    ad_flagged = flag_reason.startswith("🚩")
    ad_feedback = row["ad_feedback"] if "ad_feedback" in row.keys() else ""
    return has_video, has_photo, show_restore, ad_flagged, ad_feedback


async def _pending_wm_base_photo(row) -> bytes | None:
    """عکسِ پایه (قبل از اعمالِ هر واترمارکِ دلخواهِ دستی) برای یک پستِ در صفِ
    تایید - یا از override_photo فعلی، یا (اگه هیچ‌کدوم ست نشده) با
    دانلود+پردازشِ خودکارِ عکسِ اصلیِ پست."""
    if row["override_photo"]:
        return bytes(row["override_photo"])
    media = json_to_media_items(row["media_json"])
    photos = [m for m in media if m.type == "photo"]
    if not photos:
        return None
    raw = await _download(photos[0].url, channel_id=row["channel_id"])
    if raw is None:
        return None
    return await process_photo_bytes(raw, row["channel_id"])


async def _rebuild_pending_wm_photo(bot, pending_id: int, base: bytes, picks: list) -> None:
    """بازسازیِ عکسِ نهایی از رویِ عکسِ پایه + همه‌ی واترمارک‌های دلخواهِ چیده‌شده
    (با درنظرگرفتنِ override موقعیتِ هرکدوم، اگه برای این پست جداگانه تنظیم شده باشه)."""
    from .custom_watermark import apply_named_watermarks
    wm_list = []
    for p in picks:
        row = db.get_custom_watermark(p.get("watermark_id"))
        if not row:
            continue
        wm = dict(row)
        override = p.get("position_override")
        if override:
            wm["position"] = override.get("position", wm["position"])
            if override.get("position") == "xy":
                wm["x_pos"] = override.get("x_pos", wm["x_pos"])
                wm["y_pos"] = override.get("y_pos", wm["y_pos"])
        wm_list.append(wm)
    new_bytes = await apply_named_watermarks(bot, base, wm_list)
    db.set_pending_override_photo(pending_id, new_bytes)


async def apply_pending_wm_pick(bot, pending_id: int, watermark_id: int, position_override: dict | None = None) -> bool:
    """افزودن/به‌روزرسانیِ یک واترمارکِ دلخواهِ دستی روی عکسِ یک پستِ در صفِ تایید."""
    row = db.get_pending_post(pending_id)
    if not row:
        return False
    base, picks = db.get_pending_wm_pick(pending_id)
    if base is None:
        base = await _pending_wm_base_photo(row)
        if base is None:
            return False
        db.set_pending_wm_base(pending_id, base)
    picks = [p for p in picks if p.get("watermark_id") != watermark_id]
    entry = {"watermark_id": watermark_id}
    if position_override:
        entry["position_override"] = position_override
    picks.append(entry)
    db.set_pending_wm_picks(pending_id, picks)
    await _rebuild_pending_wm_photo(bot, pending_id, base, picks)
    return True


async def remove_pending_wm_pick(bot, pending_id: int, watermark_id: int) -> bool:
    """حذفِ یک واترمارکِ دلخواهِ قبلاً اضافه‌شده از رویِ عکسِ این پست."""
    base, picks = db.get_pending_wm_pick(pending_id)
    if base is None:
        return False
    picks = [p for p in picks if p.get("watermark_id") != watermark_id]
    db.set_pending_wm_picks(pending_id, picks)
    await _rebuild_pending_wm_photo(bot, pending_id, base, picks)
    return True


def reset_pending_wm_picks(pending_id: int) -> None:
    """حذفِ همه‌ی واترمارک‌های دلخواهِ دستیِ اضافه‌شده به این پست و بازگشت به
    عکسِ پایه (یعنی وضعیتی که قبل از استفاده از این قابلیت وجود داشت)."""
    base, _picks = db.get_pending_wm_pick(pending_id)
    if base is not None:
        db.set_pending_override_photo(pending_id, base)
    db.clear_pending_wm_pick(pending_id)


def pending_preview_caption(row) -> str:
    """کپشنِ خودِ پست در صفِ تایید: اگه پست به‌خاطرِ فیلترِ تبلیغات/تکراری فلگ
    خورده باشه، فقط یک خطِ کوتاهِ بولد (بدونِ جزئیات) بالای کپشنِ خودِ پست
    اضافه می‌شه؛ توضیحاتِ کاملِ دلیلِ فلگ توی یک پیامِ جداگانه (ریپلای‌شده روی
    همین پست) فرستاده می‌شه - نگاه کن به pending_flag_banner و
    send_pending_preview. مشترک بینِ send_pending_preview و فیدبکِ فیلترِ
    تبلیغات (pp:adfb در menu.py) که بعد از ثبتِ فیدبک باید همین کپشنِ دقیق رو
    دوباره بسازه."""
    caption = row["caption_html"] or "(بدون متن)"
    flag_reason = row["flag_reason"] if "flag_reason" in row.keys() else ""
    if flag_reason.startswith("🚩"):
        caption = f"🚩 <b>مشکوک به تبلیغاتی</b>\n\n{caption}"
    elif flag_reason.startswith("♻️"):
        # فلگِ پستِ تکراری هنوز به‌همون‌شکلِ قبلی (متنِ کامل روی کپشن) می‌مونه -
        # این یکی کوتاهه و توضیحِ جداگانه‌ای نداره که نیاز به پیامِ ریپلای باشه.
        caption = f"{_esc(flag_reason)}\n\n{caption}"
    return caption


def pending_flag_banner(row) -> str:
    """متنِ کاملِ توضیحاتِ فلگِ فیلترِ تبلیغات (بنرِ تمیزِ چندخطی که
    ad_filter.format_ad_flag_banner می‌سازه) - برایِ پیامِ جداگانه‌ای که
    ریپلایِ خودِ پست در صفِ تایید می‌شه. فقط برای پستِ فلگ‌شده به تبلیغ کاربرد
    داره؛ اگه فلگی در کار نباشه، رشته‌ی خالی برمی‌گردونه."""
    flag_reason = row["flag_reason"] if "flag_reason" in row.keys() else ""
    if not flag_reason.startswith("🚩"):
        return ""
    return flag_reason


async def send_pending_preview(bot: Bot, pending_id: int) -> None:
    """پیش‌نمایشِ فعلیِ یک پستِ در صف تایید رو می‌فرسته — به کانال تایید مالک یا ادمین‌ها.
    اگه پست به‌خاطرِ فیلترِ تبلیغات فلگ شده باشه، بلافاصله بعدِ خودِ پست یک پیامِ
    جداگانه (ریپلای‌شده رویِ همون پست، تا مشخص باشه کدوم توضیح مالِ کدوم پسته)
    با توضیحاتِ کاملِ دلیلِ فلگ + دکمه‌های فیدبک فرستاده می‌شه.

    این تابع همیشه یک پیامِ *جدید* برایِ خودِ پست می‌فرسته (نه ویرایشِ درجا) - پس
    اگه پیامِ ریپلایِ فلگِ قبلی از فراخوانیِ قبلیِ همین تابع مونده باشه (مثلاً بعدِ
    ویرایشِ دستیِ کپشن یا «بازگشت به کپشنِ اصلی»)، اول حذف می‌شه تا با پستِ تازه
    قاطی/گم نشه؛ بعد یک ریپلایِ تازه رویِ پیامِ جدید فرستاده می‌شه."""
    row = db.get_pending_post(pending_id)
    if not row:
        return
    media = json_to_media_items(row["media_json"])
    photos = [m for m in media if m.type == "photo"]
    videos = [m for m in media if m.type == "video"]
    has_video = any(m.type == "video" for m in media)
    has_photo = bool(photos)
    original_caption = row["original_caption_html"] if "original_caption_html" in row.keys() else None
    show_restore = bool(original_caption) and (row["caption_html"] or "") != original_caption
    caption = pending_preview_caption(row)
    flag_banner = pending_flag_banner(row)
    ad_flagged = bool(flag_banner)
    ad_feedback = row["ad_feedback"] if "ad_feedback" in row.keys() else ""
    # دکمه‌های فیدبکِ فیلترِ تبلیغات (در صورتِ ad_flagged) حالا مستقیماً رویِ
    # همین کیبورد نشون داده می‌شن - نگاه کن به توضیحِ بالایِ _pending_flag_kb.
    markup = _pending_kb(
        pending_id, has_video=has_video, has_photo=has_photo, show_restore=show_restore,
        ad_flagged=ad_flagged, ad_feedback=ad_feedback,
    )

    # پیامِ ریپلایِ فلگِ قبلی (اگه از یک نسخه‌ی قدیمی‌تر مونده باشه) رو حذف کن -
    # چون داریم پیامِ اصلیِ تازه‌ای می‌فرستیم و ریپلایِ قدیمی دیگه به هیچ پستی
    # وصل نیست. این‌جا با get هایِ محافظت‌شده نوشته شده چون ستون‌های
    # flag_chat_id/flag_message_id دیگه توی اسکیمایِ فعلیِ دیتابیس ساخته
    # نمی‌شن (فقط برایِ سازگاری با یک ردیفِ خیلی قدیمی که ممکنه این ستون‌ها رو
    # هنوز داشته باشه، بی‌خطر نگه داشته شده).
    old_flag_chat_id = row["flag_chat_id"] if "flag_chat_id" in row.keys() else None
    old_flag_message_id = row["flag_message_id"] if "flag_message_id" in row.keys() else None
    if old_flag_chat_id and old_flag_message_id:
        try:
            await bot.delete_message(chat_id=old_flag_chat_id, message_id=old_flag_message_id)
        except Exception:
            pass

    preview_targets, _ = _approval_targets(row["owner_user_id"] if row["owner_user_id"] else None)

    for admin_id in preview_targets:
        try:
            sent_msg = None
            override_video = row["override_video"] if "override_video" in row.keys() else None
            if override_video:
                sent_msg = await bot.send_video(
                    chat_id=admin_id, video=bytes(override_video),
                    caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                    supports_streaming=True,
                )
            elif row["override_photo"]:
                sent_msg = await bot.send_photo(
                    chat_id=admin_id, photo=bytes(row["override_photo"]),
                    caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                )
            elif videos:
                # باگ اصلی: قبلاً این حالت (ویدیوی خودِ پستِ اسکرِیپ‌شده، نه ویدیوی
                # جایگزینِ ادمین) اصلاً هندل نمی‌شد و مستقیم می‌رفت روی حالتِ
                # نهاییِ «فقط متن» - یعنی به کانال تایید فقط کپشن می‌رسید و خودِ
                # ویدیو اصلاً دیده نمی‌شد.
                raw = await _download(videos[0].url, timeout=120.0, retries=5, channel_id=row["channel_id"])
                if raw is not None:
                    sent_msg = await bot.send_video(
                        chat_id=admin_id, video=raw,
                        caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                        supports_streaming=True,
                    )
                else:
                    sent_msg = await bot.send_message(
                        chat_id=admin_id,
                        text=f"⚠️ دانلودِ ویدیوی این پست ناموفق بود؛ فقط متن:\n\n{caption}",
                        parse_mode=ParseMode.HTML, reply_markup=markup,
                    )
            elif photos:
                raw = await _download(photos[0].url, channel_id=row["channel_id"])
                if raw is not None:
                    raw = await process_photo_bytes(raw, row["channel_id"])
                    sent_msg = await bot.send_photo(
                        chat_id=admin_id, photo=raw,
                        caption=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                    )
                else:
                    sent_msg = await bot.send_message(
                        chat_id=admin_id, text=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                    )
            else:
                sent_msg = await bot.send_message(
                    chat_id=admin_id, text=caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                )

            if sent_msg is not None:
                # نگه‌داشتنِ چت/آیدیِ پیامِ خودِ پست - برایِ وقتی که بعداً لازمه
                # این پیام از یه جای دیگه (مثلاً بعدِ فیدبکِ رویِ پیامِ ریپلای)
                # پیدا و ویرایش بشه، بدونِ نیاز به چتِ فعلیِ همون کلیک.
                db.set_pending_admin_message(pending_id, admin_id, sent_msg.message_id)

            # اگه پست فلگ‌دار بود، بلافاصله یک پیامِ ریپلای با توضیحاتِ کامل +
            # دکمه‌های فیدبک بفرست، تا با یه ریپلای مشخص باشه مالِ کدوم پسته.
            # نکته‌ی ادغام: قبلاً این‌جا یک پیامِ ریپلایِ *جداگانه* با
            # flag_banner + دکمه‌های فیدبک فرستاده می‌شد (و chat/message_id ش با
            # db.set_pending_flag_message ذخیره می‌شد). نسخه‌ی فعلیِ
            # database.py دیگه ستون‌ها/تابعِ لازم برای این کارو نداره، چون
            # دکمه‌های فیدبک (بالاتر، از طریقِ ad_flagged=True روی خودِ
            # markup) مستقیماً زیرِ خودِ پست نشون داده می‌شن - نیازی به پیامِ
            # جداگانه نمونده. این بلاک عمداً حذف نشده، فقط غیرفعاله؛ اگه واقعاً
            # می‌خوای پیامِ جداگانه هم دوباره برگرده، هم این‌جا رو فعال کن هم
            # ستون‌های flag_chat_id/flag_message_id + تابعِ
            # set_pending_flag_message رو به database.py برگردون (نسخه‌ی
            # قبلی‌شون توی زیپِ اصلی موجوده).
            if False and flag_banner and sent_msg is not None:
                try:
                    flag_msg = await bot.send_message(
                        chat_id=admin_id, text=flag_banner, parse_mode=ParseMode.HTML,
                        reply_markup=_pending_flag_kb(pending_id, ad_feedback=ad_feedback),
                        reply_parameters=ReplyParameters(message_id=sent_msg.message_id),
                    )
                    db.set_pending_flag_message(pending_id, admin_id, flag_msg.message_id)
                except TelegramError as e:
                    log.warning("ارسالِ پیامِ توضیحاتِ فلگِ پستِ %s ناموفق بود: %s", pending_id, e)
        except TelegramError as e:
            err_msg = str(e).lower()
            # اگه ربات توسط کاربر بلاک شده یا هنوز /start نکرده، به ادمین‌ها اطلاع بده
            if "forbidden" in err_msg or "bot was blocked" in err_msg or "chat not found" in err_msg or "user is deactivated" in err_msg:
                log.warning(
                    "ارسال پیش‌نمایشِ پستِ %s به کانالِ تایید %s ناموفق بود (کاربر ربات رو استارت نکرده یا بلاک کرده): %s",
                    pending_id, admin_id, e,
                )
                # ارسال هشدار به ادمین‌های سراسری
                for fallback_id in config.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=fallback_id,
                            text=(
                                f"⚠️ <b>هشدار ارسال پست به صف تایید</b>\n"
                                f"پست #{pending_id} به کانالِ تایید <code>{admin_id}</code> ارسال نشد.\n"
                                "احتمالاً کاربر هنوز ربات رو /start نکرده یا ربات رو بلاک کرده.\n"
                                "پست در صف انتظار موند — برای تایید/رد از بخش ادمین اقدام کن."
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        pass
            else:
                log.warning("ارسال پیش‌نمایش پستِ در صف تایید به ادمین %s ناموفق بود: %s", admin_id, e)


async def enqueue_for_approval(bot: Bot, channel_id: int, post: Post, flag_reason: str = "") -> int:
    """
    یک پستِ تازه‌ی اسکرِیپ‌شده رو به صفِ تایید اضافه می‌کنه: کپشنِ نهایی (با امضا و
    قالب‌بندی) رو از الان می‌سازه (تا ادمین دقیقا همون چیزی که می‌خواد فرستاده بشه رو
    ببینه و در صورت نیاز ویرایش کنه) و پیش‌نمایشش رو برای ادمین(ها) می‌فرسته.
    flag_reason: اگه پر باشه (مثلاً فیلترِ تبلیغات پست رو مشکوک تشخیص داده)، یک
    بنرِ هشدار بالای پیش‌نمایش نشون داده میشه.
    """
    caption_html = build_caption_html(post.html_text, channel_id, media=post.media)
    media_json = media_items_to_json(post.media)

    ch = db.get_channel(channel_id)
    _, owner_user_id = _approval_targets(ch)

    pending_id = db.add_pending_post(
        channel_id, post.id, caption_html, media_json,
        flag_reason=flag_reason,
        owner_user_id=owner_user_id,
        body_html=post.html_text or "",
    )
    await send_pending_preview(bot, pending_id)
    return pending_id


async def approve_pending_post(bot: Bot, pending_id: int) -> bool:
    """پستِ تاییدشده رو (با کپشن/عکسِ نهایی، حتی اگه ادمین ویرایش کرده باشه) به همه‌ی مقصدهای وصل‌شده می‌فرسته.

    اول با claim_pending_post به‌صورتِ اتمیک وضعیت رو از 'pending' به
    'approved' می‌بریم (قبل از هر ارسالی) - نه بعدش. این‌طوری اگه دو کلیکِ
    تاییدِ هم‌زمان روی یک پست بیاد (مثلاً از دو دستگاهِ همون اکانتِ مشترک)، فقط
    اولی برنده می‌شه و واقعاً می‌فرسته؛ دومی چون دیگه pending نمی‌بینتش، خارج
    می‌شه - وگرنه هر دو رد می‌شدن و پست دوبار به مقصد می‌رفت.
    """
    row = db.get_pending_post(pending_id)
    if not row or row["status"] != "pending":
        return False

    if not db.claim_pending_post(pending_id, "approved"):
        # یه فراخوانیِ دیگه (کلیکِ هم‌زمان) زودتر همین پست رو claim کرده.
        return False

    channel_id = row["channel_id"]
    destinations = db.active_destinations_for_channel(channel_id)
    if not destinations:
        return False

    media = json_to_media_items(row["media_json"])
    photo_override = bytes(row["override_photo"]) if row["override_photo"] else None
    override_video = row["override_video"] if "override_video" in row.keys() else None
    video_override = bytes(override_video) if override_video else None

    # تصمیم درباره‌ی امضای پایانِ پستِ تاییدشده:
    # - اگه ادمین کپشن رو دست‌کاری کرده باشه (یا با AI عوض شده باشه؛ یعنی
    #   caption_html با نسخه‌ی اصلیِ زمانِ ورود به صف فرق کنه)، همون متنِ نهاییِ
    #   ادمین بی‌کم‌وکاست به همه‌ی مقصدها می‌ره (امضای per-مقصد اعمال نمی‌شه، تا
    #   انتخابِ صریحِ ادمین محترم بمونه). رفتارِ قبلی.
    # - اگه دست‌نخورده باشه و متنِ بدنه‌ی خام (body_html) رو داشته باشیم، امضا
    #   برای هر مقصد جداگانه ساخته می‌شه (body + امضای اختصاصیِ همون مقصد).
    _cap = row["caption_html"] or ""
    _orig = (row["original_caption_html"] if "original_caption_html" in row.keys() else "") or ""
    _body = (row["body_html"] if "body_html" in row.keys() else "") or ""
    caption_edited = _cap != _orig
    use_per_dest_footer = (not caption_edited) and bool(_body)

    any_success = False
    failures: list[tuple[str, str]] = []
    for dest in destinations:
        if use_per_dest_footer:
            # کپشن در خودِ send_post برای همین مقصد ساخته می‌شه (بدنه + امضای
            # اختصاصیِ مقصد). destination_id هم پاس داده می‌شه تا واترمارک‌های
            # اختصاصیِ همون مقصد هم اعمال بشن.
            post_obj = Post(id=row["source_post_id"], html_text=_body, media=media)
            ok, reason, post_link = await send_post(
                bot, dest["chat_id"], post_obj,
                photo_override=photo_override,
                video_override=video_override,
                channel_id=channel_id,
                destination_id=dest["id"],
            )
        else:
            fake_post = Post(id=row["source_post_id"], html_text="", media=media)
            ok, reason, post_link = await send_post(
                bot, dest["chat_id"], fake_post,
                caption_override=_cap,
                photo_override=photo_override,
                video_override=video_override,
                channel_id=channel_id,
                destination_id=dest["id"],
            )
        any_success = any_success or ok
        if ok:
            db.mark_destination_sent(dest["id"], post_link=post_link)
            await _maybe_public_destination_post_report(bot, dest, post_link)
        if not ok and reason:
            failures.append((dest["title"] or dest["chat_id"], reason))
    if any_success:
        media_type = media[0].type if media else "text"
        db.log_sent(channel_id, row["source_post_id"], media_type)
        await _maybe_public_success_report(bot, row["owner_user_id"], destinations, channel_id)
    if failures:
        await _notify_admins_of_failures(bot, failures, channel_id=channel_id)
    return any_success



_EMOJI_CHAR_RE = re.compile(
    r"^[\s"
    r"\U0001F000-\U0001FFFF"
    r"\U00002600-\U000027BF"
    r"\U00002300-\U000023FF"
    r"\U000025A0-\U000025FF"
    r"\U00002190-\U000021FF"
    r"\uFE00-\uFE0F"
    r"\u200D"
    r"\u20E3"
    r"\U0001F1E0-\U0001F1FF"
    r"]+$",
    re.UNICODE,
)


def _is_emoji_only(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(_EMOJI_CHAR_RE.match(stripped))


def _is_too_short_text_only(post: Post, channel_id: int | None = None) -> bool:
    if post.media:
        return False
    owner = _owner_of_channel(channel_id)
    if not db.get_effective_bool(channel_id, "min_content_filter_enabled", True, owner_user_id=owner):
        return False
    plain = strip_html_tags(post.html_text or "").strip()
    if not plain:
        return False
    if _is_emoji_only(plain):
        return True
    words = [w for w in re.split(r"\s+", plain) if w]
    min_words = db.setting_get_int("min_content_words", 4, owner_user_id=owner)
    return len(words) < max(1, min_words)


async def _run_ad_filter(
    post: Post, username: str, *, keywords_raw: str,
    min_mentions: int, min_links: int, score_threshold: int, smart: bool = True,
) -> tuple[bool, str]:
    """یک بار اجرای موتورِ تشخیصِ تبلیغ روی متنِ پست با تنظیماتِ داده‌شده.
    این تابع بدونِ حالت (stateless) است و هم برای فیلترِ عمومی (کاربر/کانالِ
    مبدأ) و هم برای فیلترِ اختصاصیِ هر مقصد استفاده می‌شه.

    از classify_async (نه analyze) استفاده می‌کنه تا وقتی «فیلترِ هوشمند» روشنه
    و کلیدِ AI ست شده، داوریِ نهایی با خواندنِ کاملِ متن انجام بشه - نه فقط
    تطبیقِ کلیدواژه؛ این همون لایه‌ای بود که قبلاً فقط در منوی «تستِ فیلتر»
    کار می‌کرد و هیچ‌وقت به مسیرِ واقعیِ ری‌پست وصل نشده بود.

    analyze_text از post.raw_text میاد که فقط متنِ دیده‌شدنیه (get_text)؛ اگه
    لینکِ کانفیگ/پروکسیِ منبع به‌شکلِ متنِ لینک‌شده بوده (مثلِ «آواکادوپروکسی»)،
    خودِ آدرس (vless://، t.me/proxy؟...) فقط توی href میمونه و از raw_text
    ساقط می‌شه؛ در نتیجه معافیتِ کانفیگِ analyze() هیچ‌وقت تشخیص نمی‌داد این
    پست کانفیگه، پست وارد مسیرِ AI می‌شد و AI (که فقط یک لیستِ تکراری از
    «پروکسی ۱، پروکسی ۲...» می‌دید) گاهی به‌اشتباه تبلیغاتی تشخیصش می‌داد -
    دقیقاً همون پستی که با فیلترِ هوشمندِ خاموش رد می‌شد ولی روشن رد نمی‌شد.
    برای همین post.html_text (که href رو نگه می‌داره) هم به‌عنوانِ
    config_source پاس داده می‌شه تا این لینک‌ها هم دیده بشن."""
    keywords = ad_filter.parse_keywords(keywords_raw) or ad_filter.DEFAULT_KEYWORDS
    analyze_text = post.raw_text or post.html_text
    is_ad, reason, _detail = await ad_filter.classify_async(
        analyze_text, username, keywords,
        min_mentions=min_mentions, min_links=min_links, score_threshold=score_threshold,
        use_llm=smart, config_source=post.html_text,
    )
    return is_ad, reason


def _effective_adfilter_cfg(channel_id, destination_id, owner) -> dict:
    """تنظیماتِ مؤثرِ فیلترِ تبلیغات برای یک مقصدِ مشخص، با مدلِ ساده:
    - اگه این مقصد فیلترِ اختصاصی رو «روشن» کرده باشه → از تنظیماتِ خودش
      (با همه‌ی اپشن‌ها، دقیقاً مثلِ ادمین) استفاده می‌شه.
    - اگه «خاموش» باشه → از فیلترِ تبلیغاتِ عمومیِ ادمین/کانالِ مبدأ استفاده می‌شه.
    """
    # «فیلترِ هوشمند» (تاییدِ نهایی با AI) پایه‌اش یک سوییچِ سراسریِ سطحِ مالک است - مثلِ
    # کلیدِ Mistral/Groq - و اپشنِ اختصاصیِ per-مقصد نداره؛ پس همیشه از تنظیمِ سراسری
    # خونده می‌شه، چه مقصد override داشته باشه چه نه.
    # با این حال، یک کانالِ مبدأ می‌تونه از منویِ «فیلترِ تبلیغات → غیرفعال‌سازیِ
    # هوشمند برای کانال‌های خاص» صراحتاً از این لایه معاف بشه (src override رویِ کلیدِ
    # ad_filter_smart_enabled=False)؛ این معافیت روی هر دو حالتِ زیر (چه مقصد override
    # داشته باشه چه فقط از فیلترِ عمومی پیروی کنه) اثر می‌ذاره - یعنی حتی اگه یک مقصدِ
    # خاص فیلترِ اختصاصیِ خودش رو روشن کرده باشه، برایِ این کانال باز هم AI اجرا نمی‌شه
    # و فقط موتورِ قاعده‌محور تصمیم می‌گیره.
    smart_global = db.setting_get_bool("ad_filter_smart", True, owner_user_id=owner)
    smart_ch_override = db.get_channel_override(channel_id, "ad_filter_smart_enabled")
    smart = False if smart_ch_override is False else smart_global
    if db.dest_setting_get_bool(destination_id, "ad_filter_override", False):
        return {
            "enabled": db.dest_setting_get_bool(destination_id, "ad_filter_enabled", True),
            "keywords": db.dest_setting_get(destination_id, "ad_filter_keywords", ""),
            "min_mentions": db.dest_setting_get_int(destination_id, "ad_filter_min_mentions", 3),
            "min_links": db.dest_setting_get_int(destination_id, "ad_filter_min_links", 2),
            "threshold": db.dest_setting_get_int(destination_id, "ad_filter_score_threshold", 4),
            "action": db.dest_setting_get(destination_id, "ad_filter_action", "skip"),
            "smart": smart,
        }
    return {
        "enabled": db.get_effective_bool(channel_id, "ad_filter_enabled", False, owner_user_id=owner),
        "keywords": db.setting_get("ad_filter_keywords", "", owner_user_id=owner),
        "min_mentions": db.setting_get_int("ad_filter_min_mentions", 3, owner_user_id=owner),
        "min_links": db.setting_get_int("ad_filter_min_links", 2, owner_user_id=owner),
        "threshold": db.setting_get_int("ad_filter_score_threshold", 4, owner_user_id=owner),
        "action": db.setting_get("ad_filter_action", "skip", owner_user_id=owner),
        "smart": smart,
    }


async def process_new_post(
    bot: Bot, channel, post: Post, bypass_approval: bool = False, force_resend: bool = False,
) -> PostResult:
    """
    نقطه‌ی مشترکِ پردازشِ «یک پستِ تازه»ی هر کانال مبدأ - چه از زمان‌بندیِ هفت‌گانه
    بیاد، چه از ارسال بازه‌ای، چه از دکمه‌ی «ارسال ۱۰/۲۰/۳۰ پست آخر». اگه اپشنِ
    تاییدِ ادمین برای این کانال فعال باشه (و bypass_approval هم True نباشه)، پست میره
    توی صفِ تایید؛ وگرنه مستقیم به مقصدها می‌فرسته. bypass_approval=True فقط برای
    مواردِ خاص استفاده میشه و در حالتِ عادی (شامل instant) نباید پاس بشه.

    خروجی: یک PostResult (نگاه کن به تعریفِ کلاس بالا). نکته‌ی مهم برای
    فراخوان‌ها (scheduler.py و...): فقط وقتی نتیجه FAILED باشه last_post_id
    نباید جلو بره - در بقیه‌ی حالت‌ها (SENT/QUEUED/SKIPPED) پست به‌طورِ قطعی
    «تمام‌شده» حساب میشه و باید رد بشه.

    قبل از هر چیزی، اگه پست شاملِ فایل/اپلیکیشن (APK و مشابه‌ش، طبقِ «فیلترِ
    فایل/اپ») باشه، بدونِ استثنا رد می‌شه (این نوع پست‌ها معمولاً تبلیغِ اپِ
    سایت‌های شرط‌بندی هستن). بعدش، اگه «فیلترِ پست‌های تبلیغاتی» فعال باشه، پست بررسی میشه؛ اگه
    تبلیغاتی تشخیص داده بشه طبق تنظیمِ «اقدام» یا کامل رد میشه (skip) یا برای
    بررسیِ دستیِ ادمین می‌ره صفِ تایید (review) - در هر دو حالت مستقیم به مقصد
    نمی‌ره، چون کل ایده‌ی این فیلتر همینه که این‌جور پست‌ها لابه‌لای پست‌های عادی
    خودکار ری‌پست نشن.
    """
    channel_id = channel["id"]
    _adf_owner = _owner_of_channel(channel_id)

    # ---------- فیلترِ «فقط کانفیگ/پروکسی» ----------
    # اگه این اپشن برای کانالِ مبدأ روشن باشه، فقط پست‌هایی ارسال می‌شن که
    # داخلشون کانفیگِ فیلترشکن یا لینکِ پروکسی هست (vless/vmess/trojan/ss/
    # hysteria/tuic/wireguard/socks/tg://proxy/t.me/proxy و...). خودِ پست
    # کاملاً دست‌نخورده منتقل می‌شه (همراهِ متن و عکس/مدیایی که داره)؛ هر پستی
    # که کانفیگ/پروکسی نداشته باشه اصلاً ارسال نمی‌شه.
    config_only = db.get_effective_bool(
        channel_id, "config_only_enabled", False, owner_user_id=_adf_owner
    )
    if config_only and not ad_filter.post_has_config(post):
        log.info(
            "پست %s از @%s رد شد (حالتِ «فقط کانفیگ/پروکسی» روشن است و این پست کانفیگ/پروکسی نداشت).",
            post.id, channel["username"],
        )
        db.increment_config_only_filtered()
        return PostResult.SKIPPED

    # ---------- کانفیگ/پروکسیِ همراهِ عکس یا ویدیو ----------
    # طبقِ درخواست: اگه یک پست هم کانفیگ/پروکسی داشته باشه و هم عکس یا ویدیو ضمیمه‌ش
    # باشه، اصلاً به مقصد فرستاده نمی‌شه. (کانفیگ باید تنها/متنی برسه؛ کانفیگی که با
    # عکس یا ویدیو بسته‌بندی شده معمولاً تبلیغه یا آدرسِ منبع رو روی خودِ مدیا داره و
    # با تغییرِ اسمِ لینک هم پاک نمی‌شه.) توجه: فایل/موزیک/ویس مانعِ ارسال نیستن،
    # فقط عکس و ویدیو.
    _has_visual = any(getattr(m, "type", "") in ("photo", "video") for m in post.media)
    if _has_visual and ad_filter.post_has_config(post):
        log.info(
            "پست %s از @%s رد شد (کانفیگ/پروکسی همراهِ عکس یا ویدیو بود؛ طبقِ تنظیم ارسال نشد).",
            post.id, channel["username"],
        )
        return PostResult.SKIPPED

    # ---------- ویدیویی که URLش استخراج نشد ----------
    # اگه پست ویدیو داشته ولی لینکِ مستقیمش از صفحه‌ی پیش‌نمایشِ تلگرام به‌دست
    # نیامده (has_unresolved_video) و هیچ محتوای قابل‌ارسالِ دیگری هم نداره (نه
    # عکس، نه فایل، نه موزیک)، اون رو رد می‌کنیم. وگرنه پست به‌شکلِ «فقط متن» یا
    # حتی یک پیامِ خالی (وقتی کپشن هم نداره) به مقصد می‌رفت - یعنی همون باگی که
    # دیده شد: ویدیو ارسال نمی‌شد ولی یک پستِ خالی/بی‌ویدیو توی مقصد ساخته می‌شد.
    _sendable_now = list(post.media)
    if getattr(post, "has_unresolved_video", False) and not _sendable_now:
        log.info(
            "پست %s از @%s رد شد (ویدیو داشت ولی URLِ مستقیمش قابلِ استخراج نبود و "
            "محتوای قابل‌ارسالِ دیگری نداشت؛ برای جلوگیری از ارسالِ پستِ خالی/فقط‌متن رد شد).",
            post.id, channel["username"],
        )
        try:
            db.add_system_log(
                log_type="MEDIA",
                event_type="unresolved_video_skipped",
                severity="WARNING",
                message=(
                    f"ویدیوی پست {post.id} از @{channel['username']} از صفحه‌ی پیش‌نمایش و امبد "
                    "قابلِ استخراج نبود (تلگرام لینکِ مستقیم نمی‌ده). این پست ارسال نشد."
                ),
                channel_id=channel_id,
                post_id=post.id,
                status="skipped",
            )
        except Exception:  # noqa: BLE001
            pass
        return PostResult.SKIPPED

    # فیلترِ «متنِ خیلی کوتاه» وقتی حالتِ «فقط کانفیگ/پروکسی» روشنه دور زده می‌شه،
    # چون گاهی یک لینکِ کانفیگِ تنها (بدونِ متنِ اضافه) هم دقیقاً همون چیزیه که
    # کاربر می‌خواد ارسال بشه و نباید به‌عنوانِ «خیلی کوتاه» رد بشه.
    if not config_only and _is_too_short_text_only(post, channel_id):
        plain_check = strip_html_tags(post.html_text or "").strip()
        reason_fa = (
            "فقط ایموجیه و مدیا نداره"
            if _is_emoji_only(plain_check)
            else f"کمتر از {db.setting_get_int('min_content_words', 4, owner_user_id=_adf_owner)} کلمه داره و مدیا نداره"
        )
        log.info("پست %s از @%s رد شد (%s).", post.id, channel["username"], reason_fa)
        return PostResult.SKIPPED

    if db.get_effective_bool(channel_id, "file_filter_enabled", True, owner_user_id=_adf_owner):
        ext_raw = db.setting_get("file_filter_extensions", "", owner_user_id=_adf_owner)
        extensions = ad_filter.parse_extensions(ext_raw) or ad_filter.DEFAULT_BLOCKED_EXTENSIONS
        is_blocked, filename = ad_filter.blocked_file(post.media, extensions)
        if is_blocked:
            log.info(
                "پست %s از @%s رد شد (فایل مسدودشده: %s).",
                post.id, channel["username"], filename,
            )
            db.increment_file_filtered()
            return PostResult.SKIPPED

    # مقصدهای فعالِ این کانال رو یک‌بار می‌گیریم.
    destinations = db.active_destinations_for_channel(channel_id)

    # ---------- فیلترِ تبلیغات (مدلِ ساده و per-مقصد) ----------
    # برای هر مقصد: اگه فیلترِ اختصاصیش روشن باشه از تنظیماتِ خودش، وگرنه از
    # فیلترِ عمومیِ ادمین استفاده می‌شه. اگه پست تبلیغاتی تشخیص داده شد:
    #   - اقدام «skip» → همون مقصد از لیستِ ارسال حذف می‌شه.
    #   - اقدام «review» → کلِ پست می‌ره صفِ تاییدِ ادمین (چون صفِ تایید کلِ پسته).
    # مقصدهایی که پست براشون مجازه توی allowed_dest_ids جمع می‌شن.
    allowed_dest_ids: Optional[set[int]] = None
    if destinations:
        allowed_dest_ids = set()
        ad_counted = False
        # دلایلِ ردِ هر مقصد (برای لاگِ قابل‌مشاهده‌ی زیر، اگه پست از *همه‌ی*
        # مقصدها رد بشه) - قبلاً این دلایل فقط توی log.info (لاگِ سرور، نه
        # چیزی که ادمین از داخلِ ربات ببینه) ثبت می‌شدن؛ برای کانال‌های
        # لحظه‌ای این یعنی از دیدِ ادمین پست بی‌هیچ توضیحی «گم» می‌شد.
        _skip_reasons: list[str] = []
        # کش برای این‌که وقتی چند مقصد دقیقاً همون تنظیماتِ فیلترِ تبلیغات رو دارن
        # (حالتِ رایج: بدونِ override اختصاصی)، به‌ازای هر کدوم یک بارِ دیگه به AI
        # درخواست نزنیم - همون نتیجه از کش برمی‌گرده.
        _adf_cache: dict[tuple, tuple[bool, str]] = {}
        for dest in destinations:
            cfg = _effective_adfilter_cfg(channel_id, dest["id"], _adf_owner)
            if cfg["enabled"]:
                cache_key = (
                    cfg["keywords"], cfg["min_mentions"], cfg["min_links"],
                    cfg["threshold"], cfg["smart"],
                )
                if cache_key in _adf_cache:
                    is_ad, reason = _adf_cache[cache_key]
                else:
                    is_ad, reason = await _run_ad_filter(
                        post, channel["username"],
                        keywords_raw=cfg["keywords"], min_mentions=cfg["min_mentions"],
                        min_links=cfg["min_links"], score_threshold=cfg["threshold"],
                        smart=cfg["smart"],
                    )
                    _adf_cache[cache_key] = (is_ad, reason)
                if is_ad:
                    if cfg["action"] == "review":
                        log.info("پست %s از @%s برای مقصدِ «%s» مشکوک به تبلیغ بود؛ کلِ پست به صفِ تایید رفت (%s).",
                                 post.id, channel["username"], dest["title"] or dest["chat_id"], reason)
                        db.increment_ad_filtered()
                        flag_banner = ad_filter.format_ad_flag_banner(reason)
                        await enqueue_for_approval(bot, channel_id, post, flag_reason=flag_banner)
                        return PostResult.QUEUED
                    log.info("پست %s برای مقصدِ «%s» طبقِ فیلترِ تبلیغات رد شد (%s).",
                             post.id, dest["title"] or dest["chat_id"], reason)
                    _skip_reasons.append(f"{dest['title'] or dest['chat_id']}: {reason}")
                    if not ad_counted:
                        db.increment_ad_filtered()
                        ad_counted = True
                    continue  # این مقصد حذف
            allowed_dest_ids.add(dest["id"])
        if not allowed_dest_ids:
            # پست از همه‌ی مقصدها به‌خاطرِ فیلترِ تبلیغات حذف شد → کلاً رد.
            # این‌جا رو - برخلافِ قبل - توی system_logs هم ثبت می‌کنیم (نه فقط
            # log.info که فقط توی لاگِ فایلِ سرور می‌مونه)، چون از دیدِ ادمینِ
            # کانالِ لحظه‌ای، این دقیقاً همون لحظه‌ایه که پست «بی‌دلیل» گم به‌نظر
            # می‌رسه؛ حالا از منویِ «لاگ‌ها» قابلِ دیدنه و می‌شه فهمید false-positive
            # بوده یا نه، بدونِ نیاز به لاگِ سرور.
            try:
                db.add_system_log(
                    log_type="AD_FILTER",
                    event_type="post_skipped_all_destinations",
                    severity="INFO",
                    message=(
                        f"پست {post.id} از @{channel['username']} برایِ همه‌ی مقصدها طبقِ فیلترِ "
                        f"تبلیغات رد شد و اصلاً ارسال نشد. جزئیات: " + " | ".join(_skip_reasons)
                    ),
                    channel_id=channel_id,
                    post_id=post.id,
                    status="skipped",
                )
            except Exception:  # noqa: BLE001 - لاگ نباید جلوی ادامه‌ی کار رو بگیره
                pass
            return PostResult.SKIPPED

    # ---------- فیلترِ محتوای تکراری بین کانال‌های مبدأ ----------
    from .duplicate_filter import DuplicateFilter
    dup_mode = DuplicateFilter.get_mode(channel_id)
    if dup_mode != DuplicateFilter.MODE_DISABLED:
        dup_text = post.raw_text or strip_html_tags(post.html_text or "")
        media_urls = [m.url for m in post.media if getattr(m, "url", None)]
        # فیکسِ R3: چک‌کردن و ثبت در یک عملیاتِ اتمیک (یک قفل)، تا با چند کانالِ
        # instant موازی، دو کانال هم‌زمان «تکراری نیست» نبینن و هر دو پست رو نفرستن.
        # اگه تکراری نبود، همین متد خودش پست رو ثبت می‌کنه (log_post جدا لازم نیست).
        is_dup, prev_post_id = DuplicateFilter.check_and_log_atomic(dup_text, media_urls, channel_id, post.id)
        if is_dup:
            db.add_system_log(
                log_type="DUPLICATE",
                event_type="duplicate_detected",
                severity="INFO",
                message=f"محتوای تکراری از @{channel['username']} تشخیص داده شد (پستِ مشابه قبلی: {prev_post_id})",
                channel_id=channel_id,
                post_id=post.id,
                status="duplicate",
            )
            if dup_mode == DuplicateFilter.MODE_AUTO_REJECT:
                log.info("پست %s از @%s به‌دلیلِ تکراری بودن به‌صورتِ خودکار رد شد.", post.id, channel["username"])
                return PostResult.SKIPPED
            if dup_mode == DuplicateFilter.MODE_SEND_TO_APPROVAL:
                await enqueue_for_approval(
                    bot, channel_id, post,
                    flag_reason=(
                        "♻️ این پست به‌دلیلِ تکراری بودن (محتوای مشابه از کانالِ دیگری قبلاً دیده شده) "
                        "به‌صورتِ خودکار رد نشد. لطفاً تصمیم بگیرید: ارسال یا رد."
                    ),
                )
                return PostResult.QUEUED
        # فیکسِ R3: ثبت دیگر اینجا لازم نیست؛ check_and_log_atomic در حالتِ
        # «تکراری نبود» خودش پست را زیرِ همان قفل ثبت کرده است.

    if bool(channel["approval_required"]) and not bypass_approval:
        await enqueue_for_approval(bot, channel_id, post)
        return PostResult.QUEUED

    if not destinations:
        log.warning("کانال @%s پستی داره ولی به هیچ مقصدِ فعالی وصل نیست؛ رد شد.", channel["username"])
        return PostResult.SKIPPED

    any_success = False
    failures: list[tuple[str, str]] = []
    _dedup_text = post.raw_text or strip_html_tags(post.html_text or "")
    _dedup_media_urls = [m.url for m in post.media if getattr(m, "url", None)]
    for dest in destinations:
        # مقصدهایی که فیلترِ تبلیغات حذفشون کرده رد می‌شن.
        if allowed_dest_ids is not None and dest["id"] not in allowed_dest_ids:
            continue

        # ---------- جلوگیری از ارسالِ دوباره‌ی دقیقاً همین پست به همین مقصد ----------
        # این چک فقط برای جریانِ عادی (زمان‌بندِ خودکار و امثالش) اجرا می‌شه. دکمه‌ی
        # «ارسال ۱۰/۲۰/۳۰ پستِ آخر» با force_resend=True صدا زده می‌شه چون کارش
        # دقیقاً همینه: هر بار که زده بشه، همون N پستِ آخر رو دوباره بفرسته حتی اگه
        # قبلاً از همین طریق یا زمان‌بند فرستاده شده باشن.
        if not force_resend and db.get_mapped_message_id(channel_id, post.id, dest["id"]) is not None:
            log.info(
                "پست %s از @%s قبلاً به مقصدِ «%s» ارسال شده بود؛ دوباره فرستاده نشد.",
                post.id, channel["username"], dest["title"] or dest["chat_id"],
            )
            continue

        # ---------- جلوگیری از پستِ تکراریِ بینِ‌کانالی، مخصوصِ این مقصد ----------
        # اگه چند کانالِ مبدأ به این مقصد وصلن و محتوای مشابه از یکی دیگه‌شون
        # همین اواخر به همین مقصد رفته، این یکی رو نفرست - فارغ از این‌که از
        # کدوم کانالِ مبدأ اومده باشه.
        if DuplicateFilter.get_dest_dedup_enabled(dest["id"]):
            is_dest_dup, prev_src_post_id = DuplicateFilter.is_duplicate_for_destination(
                _dedup_text, _dedup_media_urls, dest["id"]
            )
            if is_dest_dup:
                log.info(
                    "پست %s از @%s برای مقصدِ «%s» رد شد (محتوای مشابه همین اواخر از کانالِ دیگری به همین مقصد رفته؛ پستِ مشابه: %s).",
                    post.id, channel["username"], dest["title"] or dest["chat_id"], prev_src_post_id,
                )
                continue

        ok, reason, post_link = await send_post(
            bot, dest["chat_id"], post, channel_id=channel_id, destination_id=dest["id"],
        )
        any_success = any_success or ok
        if ok:
            db.mark_destination_sent(dest["id"], post_link=post_link)
            await _maybe_public_destination_post_report(bot, dest, post_link)
            if DuplicateFilter.get_dest_dedup_enabled(dest["id"]):
                DuplicateFilter.log_sent_to_destination(
                    _dedup_text, _dedup_media_urls, dest["id"], channel_id, post.id
                )
        if not ok and reason:
            failures.append((dest["title"] or dest["chat_id"], reason))

    if any_success:
        media_type = post.media[0].type if post.media else "text"
        db.log_sent(channel_id, post.id, media_type)
        await _maybe_public_success_report(bot, channel["owner_user_id"], destinations, channel_id)
    if failures:
        await _notify_admins_of_failures(bot, failures, channel_id=channel_id)

    if any_success:
        return PostResult.SENT
    if failures:
        # حداقل یک مقصد با یک دلیلِ فنیِ واقعی (نه صرفاً «بدونِ محتوا») شکست
        # خورد - یعنی این شکست موقتیه (شبکه/دانلود/آپلود) و ارزشِ تلاشِ دوباره
        # داره؛ پس last_post_id نباید جلو بره تا سرِ تیکِ بعدی همینPost دوباره
        # امتحان بشه.
        return PostResult.FAILED
    # هیچ مقصدی موفق نشد ولی هیچ دلیلِ فنی‌ای هم ثبت نشد - یعنی پست اصلاً
    # محتوای قابل‌ارسالی نداشت (مثلاً فقط ویس بود که فیلتر میشه)؛ این یک
    # رد-شدنِ قطعیه، نه شکستِ فنی.
    return PostResult.SKIPPED