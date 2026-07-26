"""
ماژولِ «ارسالِ دستی + زمان‌بندی + مدیریتِ صف» (فازِ ۱، ۲، ۳ از درخواستِ ۱۵بخشی).

طراحیِ ایزوله، مثلِ auto_poster: یک فایلِ مستقل با پیشوندِ کالبکِ خودش
(`manual:`) و یک state جدا در context.user_data (کلیدِ manual_awaiting)، تا
هیچ تداخلی با فلوهای موجودِ ری‌پست/صفِ تاییدِ خودکار (pp:) پیش نیاد.

ایزوله‌سازیِ چندکاربره (بخشِ ۱۱) — کامل شده:
- این بخش هم برای ادمین‌های سراسری (config.ADMIN_IDS) و هم برای کاربرانِ
  غیرادمینِ ثبت‌شده‌ای که ادمین بهشون مجوزِ «manual» داده کار می‌کنه.
- تمامِ داده‌ها و تنظیمات به‌ازای هر کاربر کاملاً جدا هستن و با هم/با ادمین
  قاطی نمی‌شن: پست‌ها و زمان‌بندی‌ها (owner_user_id)، لیستِ تاریخ‌ها، مقصدها،
  واترمارک‌های سفارشی، و حتی «توقف/ازسرگیریِ صف» (که برای هر کاربر کلیدِ مختصِ
  خودش رو داره). هر کاربر فقط پست‌ها/مقصدها/واترمارک‌های خودش رو می‌بینه و صفِ
  اون فقط روی پست‌های خودش اثر می‌ذاره.
- حلقه‌ی زمان‌بندیِ پس‌زمینه پستِ هر کاربر رو با توجه به وضعیتِ توقفِ صفِ همون
  کاربر می‌فرسته؛ توقفِ صفِ یک کاربر مانعِ ارسالِ پست‌های بقیه/ادمین نمی‌شه.

نکته‌های فنی:
- انتخابِ واترمارک می‌تونه «پیش‌فرضِ ربات (روشن)»، «خاموش» یا یکی از
  واترمارک‌های سفارشیِ نام‌دارِ خودِ همون کاربر باشه.
- دکمه‌های اینلاین روی آلبوم (Media Group) از طرفِ خودِ تلگرام پشتیبانی
  نمی‌شن؛ اگه پستِ آلبومی دکمه داشته باشه، دکمه‌ها به‌صورتِ یک پیامِ جداگانه
  بلافاصله بعدِ آلبوم فرستاده می‌شن.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

import jdatetime
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter
from telegram.ext import ContextTypes

from . import config
from .database import db
from .jdatetime_utils import TEHRAN_TZ, now_jalali
from .poster import process_photo_bytes
from .formatter import ensure_rtl_lines
from .utils import truncate_html_safe

log = logging.getLogger("repost_bot.manual_poster")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

STATUS_LABELS = {
    "draft": "📝 پیش‌نویس",
    "pending": "⏳ در انتظار",
    "scheduled": "🗓 زمان‌بندی‌شده",
    "processing": "⚙️ در حالِ ارسال",
    "sent": "✅ ارسال‌شده",
    "failed": "❌ ناموفق",
    "cancelled": "🚫 لغوشده",
}

# تایمرهای Debounce برایِ جمع‌کردنِ آلبوم (Media Group) - هر کاربر یک تسکِ
# در حالِ انتظار دارد که با رسیدنِ آیتمِ بعدیِ همون آلبوم لغو و دوباره شروع میشه.
_album_timers: dict[int, asyncio.Task] = {}


def _is_admin(uid: int | None) -> bool:
    return bool(uid) and uid in config.ADMIN_IDS


def _can_use(uid: int | None) -> bool:
    """ادمین همیشه مجاز؛ کاربرِ غیرادمین فقط اگه ثبت‌شده باشه و مجوزِ
    "manual" رو ادمین بهش داده باشه (بخشِ ۱۱ - Multi-User Isolation)."""
    if _is_admin(uid):
        return True
    from .handlers.common import is_owner, has_perm
    return bool(uid) and is_owner(uid) and has_perm(uid, "manual")


def _owner_of(uid: int | None) -> int | None:
    """ادمین → None (بدون فیلتر، دسترسی به همه)؛ کاربرِ مجازِ غیرادمین → آیدیِ
    داخلیِ خودش (تا فقط پست‌ها/مقصدهای خودش رو ببینه - بخشِ ۱۱)."""
    if _is_admin(uid):
        return None
    from .database import db as _db
    u = _db.get_user_by_telegram_id(uid) if uid else None
    return u["id"] if u else -1


# رنگِ واقعیِ خودِ دکمه (نه ایموجی) — قابلیتِ Bot API 9.4 (از ۹ فوریه ۲۰۲۶).
# تلگرام فقط سه رنگِ ازپیش‌تعریف‌شده رو می‌پذیره: 'primary' (آبی)، 'success'
# (سبز)، 'danger' (قرمز)؛ رنگِ دلخواه با کدِ HEX (مثلِ #28a745) اصلاً وجود نداره
# و اگه فرستاده بشه تلگرام نادیده‌ش می‌گیره. چون python-telegram-bot نسخه‌ی
# 21.6 (که این پروژه پین کرده) هنوز فیلدِ style رو مستقیم نداره (از 22.7 اضافه
# شده)، فیلد رو از طریقِ api_kwargs می‌فرستیم تا در JSONِ نهایی به تلگرام برسه.
# روی کلاینت‌های قدیمی‌ترِ تلگرام (قبل از ۹ فوریه ۲۰۲۶) دکمه بدونِ رنگ دیده می‌شه.
_VALID_BTN_STYLES = {"primary", "success", "danger"}


def _btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    api_kwargs = {"style": style} if style in _VALID_BTN_STYLES else None
    return InlineKeyboardButton(text, callback_data=data, api_kwargs=api_kwargs)


def _own_post_or_none(uid: int | None, pid: int):
    """محافظتِ ضدِ callback_data دستکاری‌شده: حتی اگه کاربر بخواد با تغییرِ
    آیدیِ پست توی کالبک به پستِ کاربرِ دیگه دسترسی پیدا کنه، اینجا رد می‌شه."""
    p = db.get_manual_post(pid)
    if not p:
        return None
    owner = _owner_of(uid)
    if owner is not None and p["owner_user_id"] != owner:
        return None
    return p


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(
        "manual_draft",
        {"media": [], "caption_html": "", "buttons": [], "watermark_enabled": True,
         "watermark_id": None, "destination_id": None},
    )


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("manual_draft", "manual_awaiting", "manual_preview_chat_id", "manual_preview_msg_id", "manual_edit_post_id"):
        context.user_data.pop(k, None)


# ============================================================================
# ورودیِ منویِ اصلی
# ============================================================================

def root_content(uid: int | None = None):
    owner = _owner_of(uid)
    dates = db.list_manual_dates(owner_user_id=owner)
    if dates:
        lines = "\n".join(f"📅 {d['d']} — {d['cnt']} پست" for d in dates[:10])
    else:
        lines = "هنوز هیچ پستِ زمان‌بندی‌شده‌ای نیست."
    text = (
        "📮 <b>ارسالِ دستی و زمان‌بندی</b>\n"
        f"{DIVIDER}\n"
        f"{lines}\n\n"
        "برایِ ساختِ پستِ جدید، «➕ پستِ جدید» رو بزن و پست رو فوروارد کن."
    )
    rows = [
        [_btn("➕ پستِ جدید", "manual:new", style="primary")],
        [_btn("🗂 مدیریتِ پست‌های زمان‌بندی‌شده", "manual:dates")],
        [_btn("⏸ توقفِ صف", "manual:queue_toggle", style="success")
         if not db.is_manual_queue_paused(owner)
         else _btn("▶️ ازسرگیریِ صف", "manual:queue_toggle", style="danger")],
        [_btn("🏠 بازگشت به منویِ اصلی", "menu:main", style="success")],
    ]
    return text, InlineKeyboardMarkup(rows), ParseMode.HTML


# ============================================================================
# دریافتِ پست (متن/عکس/ویدیو/آلبوم/GIF/صدا/فایل)
# ============================================================================

def _extract_media_item(msg) -> Optional[dict]:
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id}
    if msg.animation:
        return {"type": "animation", "file_id": msg.animation.file_id}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id}
    if msg.document:
        return {"type": "document", "file_id": msg.document.file_id, "filename": msg.document.file_name or ""}
    return None


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """اگه ربات منتظرِ دریافتِ پستِ دستیه، این پیام رو مصرف می‌کنه و True برمی‌گردونه؛
    وگرنه False (تا هندلرهای دیگه‌ی ربات طبقِ روالِ عادی اجرا بشن)."""
    uid = update.effective_user.id if update.effective_user else None
    if not _can_use(uid):
        return False
    if context.user_data.get("manual_awaiting") != "collect_post":
        return False

    msg = update.message
    if msg is None:
        return False

    draft = _draft(context)
    item = _extract_media_item(msg)
    if item:
        draft["media"].append(item)

    cap = msg.text_html or msg.caption_html or msg.text or msg.caption or ""
    if cap and not draft.get("caption_html"):
        draft["caption_html"] = cap

    mgid = msg.media_group_id
    if mgid:
        old = _album_timers.get(uid)
        if old and not old.done():
            old.cancel()

        async def _finalize():
            try:
                await asyncio.sleep(1.3)
            except asyncio.CancelledError:
                return
            await _show_preview(update, context)

        _album_timers[uid] = context.application.create_task(_finalize())
    else:
        await _show_preview(update, context)
    return True


# ============================================================================
# پیش‌نمایش
# ============================================================================

def _preview_text(draft: dict) -> str:
    media = draft.get("media", [])
    if len(media) > 1:
        kind = f"آلبوم ({len(media)} آیتم)"
    elif media:
        kind_map = {"photo": "عکس", "video": "ویدیو", "animation": "GIF", "voice": "صدا", "document": "فایل"}
        kind = kind_map.get(media[0]["type"], media[0]["type"])
    else:
        kind = "فقط متن"

    dest_id = draft.get("destination_id")
    if dest_id:
        d = db.get_destination(dest_id)
        dest_text = d["title"] or d["chat_id"] if d else "نامشخص"
    else:
        dest_text = "❗️ هنوز انتخاب نشده"

    wm_id = draft.get("watermark_id")
    if wm_id:
        wm_row = db.get_custom_watermark(wm_id)
        wm_text = f"🏷 {wm_row['name']}" if wm_row else "🔴 خاموش"
    else:
        wm_text = "🟢 پیش‌فرضِ ربات (روشن)" if draft.get("watermark_enabled", True) else "🔴 خاموش"
    btn_count = len(draft.get("buttons", []))
    cap_preview = (draft.get("caption_html") or "").strip()
    # فیکس: پیش‌نمایشِ پستِ دستی (همین‌جا) از ensure_rtl_lines رد نمی‌شد، برخلافِ
    # _do_send که درست قبلِ ارسالِ واقعی صداش می‌زنه. نتیجه: چیزی که ادمین در
    # پیش‌نمایش می‌دید (خطوطِ فارسی بدونِ علامتِ راست‌چین) با چیزی که واقعاً به
    # مقصد می‌رفت فرق داشت. همین‌جا هم راست‌چین می‌کنیم تا پیش‌نمایش و ارسالِ
    # نهایی دقیقاً یکی باشن.
    cap_preview = ensure_rtl_lines(cap_preview) if cap_preview else cap_preview
    cap_preview = truncate_html_safe(cap_preview, 300) if cap_preview else "(بدونِ متن)"

    return (
        "👁 <b>پیش‌نمایشِ پست</b>\n"
        f"{DIVIDER}\n"
        f"نوع: {kind}\n"
        f"مقصد: {dest_text}\n"
        f"واترمارک: {wm_text}\n"
        f"دکمه‌های اینلاین: {btn_count} عدد\n\n"
        f"<b>متن/کپشن:</b>\n{cap_preview}"
    )


def _preview_keyboard(scheduled: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [_btn("✅ تایید ارسال", "manual:confirm", style="success"), _btn("🗓 زمان‌بندی ارسال", "manual:sched_start", style="primary")],
        [_btn("✏️ ویرایش کپشن", "manual:editcap"), _btn("🎯 تغییر مقصد", "manual:destpick")],
        [_btn("🏷 انتخابِ واترمارک", "manual:wmpick"), _btn("🔗 دکمه‌های اینلاین", "manual:buttons")],
        [_btn("📝 خلاصه‌سازی 🤖", "manual:ai_summarize"), _btn("🔄 بازنویسی 🤖", "manual:ai_rewrite")],
        [_btn("❌ لغو", "manual:cancel", style="danger")],
    ]
    return InlineKeyboardMarkup(rows)


async def _show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = _draft(context)
    context.user_data["manual_awaiting"] = "preview"
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_preview_text(draft),
        parse_mode=ParseMode.HTML,
        reply_markup=_preview_keyboard(),
    )
    context.user_data["manual_preview_chat_id"] = chat_id
    context.user_data["manual_preview_msg_id"] = msg.message_id


async def _refresh_preview(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = _draft(context)
    try:
        await query.edit_message_text(
            text=_preview_text(draft), parse_mode=ParseMode.HTML, reply_markup=_preview_keyboard(),
        )
    except TelegramError as e:
        # طبیعیه اگه پیام قدیمی باشه یا محتوا عوض نشده باشه — تغییری در وضعیت ارسال نمی‌ده
        log.debug("ویرایشِ پیش‌نمایشِ دستی ناموفق بود (طبیعیه اگه پیام قدیمی یا بدون تغییر باشه): %s", e)


# ============================================================================
# مسیریابیِ کالبک‌ها (پیشوندِ manual:)
# ============================================================================

async def handle_callback(data: str, query, context: ContextTypes.DEFAULT_TYPE, uid: int | None) -> None:
    if not _can_use(uid):
        await query.answer("⛔️ برایِ این بخش دسترسی نداری.", show_alert=True)
        return

    if data == "manual:new":
        _clear_draft(context)
        context.user_data["manual_awaiting"] = "collect_post"
        await query.edit_message_text(
            "📮 پست رو فوروارد کن (متن/عکس/ویدیو/آلبوم/GIF/صدا/فایل).\n"
            "برایِ آلبوم، همه‌ی آیتم‌ها رو پشتِ سرِ هم بفرست - چند ثانیه صبر می‌کنم "
            "تا همه برسن.",
            reply_markup=InlineKeyboardMarkup([[_btn("🏠 بازگشت به منویِ اصلی", "menu:main", style="success")]]),
        )
        return

    if data == "manual:cancel":
        _clear_draft(context)
        text, markup, pm = root_content(uid)
        await query.edit_message_text(text, parse_mode=pm, reply_markup=markup)
        return

    if data == "manual:wmpick":
        from .custom_watermark import _owner_of as _wmc_owner_of
        draft = _draft(context)
        rows = [
            [_btn("🟢 پیش‌فرضِ ربات", "manual:wmset:default")],
            [_btn("🔴 خاموش", "manual:wmset:off")],
        ]
        for w in db.list_custom_watermarks(owner_user_id=_wmc_owner_of(uid)):
            rows.append([_btn(f"🏷 {w['name']}", f"manual:wmset:{w['id']}")])
        rows.append([_btn("🔙 بازگشت", "manual:backtopreview")])
        await query.edit_message_text("واترمارکِ موردنظر رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("manual:wmset:"):
        val = data.split(":")[2]
        draft = _draft(context)
        if val == "default":
            draft["watermark_id"] = None
            draft["watermark_enabled"] = True
        elif val == "off":
            draft["watermark_id"] = None
            draft["watermark_enabled"] = False
        else:
            draft["watermark_id"] = int(val)
        context.user_data["manual_awaiting"] = "preview"
        await _refresh_preview(query, context)
        return

    if data == "manual:editcap":
        context.user_data["manual_awaiting"] = "edit_caption"
        await query.edit_message_text(
            "متنِ/کپشنِ جدید رو بفرست:",
            reply_markup=InlineKeyboardMarkup([[_btn("❌ انصراف", "manual:backtopreview")]]),
        )
        return

    if data == "manual:backtopreview":
        context.user_data["manual_awaiting"] = "preview"
        await _refresh_preview(query, context)
        return

    if data == "manual:destpick":
        rows = []
        for d in db.list_destinations(active_only=True, owner_user_id=_owner_of(uid)):
            label = d["title"] or d["chat_id"]
            rows.append([_btn(f"🎯 {label}", f"manual:destset:{d['id']}")])
        rows.append([_btn("🔙 بازگشت", "manual:backtopreview")])
        await query.edit_message_text(
            "کانالِ مقصد رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data.startswith("manual:destset:"):
        did = int(data.split(":")[2])
        draft = _draft(context)
        draft["destination_id"] = did
        if not draft.get("watermark_id"):
            auto_wm = db.get_watermark_for_destination(did)
            if auto_wm:
                draft["watermark_id"] = auto_wm["id"]
        context.user_data["manual_awaiting"] = "preview"
        await _refresh_preview(query, context)
        return

    if data == "manual:buttons":
        draft = _draft(context)
        lines = "\n".join(f"{i+1}. {b['text']} → {b['url']}" for i, b in enumerate(draft.get("buttons", [])))
        rows = [[_btn("➕ افزودنِ دکمه", "manual:btn_add")]]
        for i in range(len(draft.get("buttons", []))):
            rows.append([_btn(f"🗑 حذفِ دکمه‌ی {i+1}", f"manual:btn_del:{i}")])
        rows.append([_btn("🔙 بازگشت", "manual:backtopreview")])
        await query.edit_message_text(
            "🔗 <b>دکمه‌های اینلاین</b>\n" + (lines or "(هنوز دکمه‌ای اضافه نشده)"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data == "manual:btn_add":
        context.user_data["manual_awaiting"] = "btn_add_text"
        await query.edit_message_text(
            "متنِ دکمه رو بفرست:",
            reply_markup=InlineKeyboardMarkup([[_btn("❌ انصراف", "manual:buttons")]]),
        )
        return

    if data.startswith("manual:btn_del:"):
        idx = int(data.split(":")[2])
        draft = _draft(context)
        btns = draft.get("buttons", [])
        if 0 <= idx < len(btns):
            btns.pop(idx)
        data2 = "manual:buttons"
        await handle_callback(data2, query, context, uid)
        return

    if data in ("manual:ai_summarize", "manual:ai_rewrite"):
        draft = _draft(context)
        # باگِ قبلی: این‌جا از کلیدِ "caption" خونده/نوشته می‌شد، درحالی‌که در همه‌جای
        # دیگه‌ی این فایل (پیش‌نمایش، ویرایشِ دستیِ کپشن، ارسالِ نهایی) کلیدِ درست
        # "caption_html" ه. نتیجه: caption همیشه خالی بود، پس بلافاصله پیامِ «این
        # پست متنی ندارد» نشون داده می‌شد و هوش مصنوعی اصلاً صدا زده نمی‌شد.
        caption = draft.get("caption_html") or ""
        if not caption.strip():
            await query.answer("این پست متنی ندارد.", show_alert=True)
            return
        await query.answer("⏳ در حال پردازش با هوش مصنوعی...")
        from .ai_router import AIRouter
        router = AIRouter()
        try:
            if data == "manual:ai_summarize":
                new_caption = await router.summarize(caption)
                result_msg = "📝 خلاصه‌سازی انجام شد."
            else:
                new_caption = await router.rewrite(caption)
                result_msg = "🔄 بازنویسی خلاقانه انجام شد."
        except Exception as e:
            log.exception("خطا در پردازش AI (manual): %s", e)
            await query.answer("خطا در پردازش، دوباره تلاش کنید.", show_alert=True)
            return
        finally:
            await router.close()
        draft["caption_html"] = new_caption
        context.user_data["manual_draft"] = draft
        await query.answer(result_msg, show_alert=True)
        await _refresh_preview(query, context)
        return

    if data == "manual:sched_start":
        context.user_data["manual_awaiting"] = "sched_datetime"
        now = now_jalali()
        await query.edit_message_text(
            "🗓 تاریخ و ساعتِ ارسال رو به این فرمت بفرست:\n"
            "<code>1405/05/20 18:30</code>\n\n"
            f"الان: {now.strftime('%Y/%m/%d %H:%M')}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[_btn("❌ انصراف", "manual:backtopreview")]]),
        )
        return

    if data == "manual:confirm":
        draft = _draft(context)
        if not draft.get("destination_id"):
            await query.answer("❗️ اول باید مقصد رو انتخاب کنی.", show_alert=True)
            return
        await query.edit_message_text("⏳ در حالِ ارسال...")
        ok, err = await _send_draft_now(context.bot, draft)
        if ok:
            await query.edit_message_text("✅ پست با موفقیت ارسال شد.")
        else:
            await query.edit_message_text(f"❌ ارسال ناموفق بود:\n{err}")
        _clear_draft(context)
        return

    # ---------------- مدیریتِ پست‌های زمان‌بندی‌شده ----------------
    if data == "manual:queue_toggle":
        owner = _owner_of(uid)
        db.set_manual_queue_paused(not db.is_manual_queue_paused(owner), owner)
        text, markup, pm = root_content(uid)
        await query.edit_message_text(text, parse_mode=pm, reply_markup=markup)
        return

    if data.startswith("manual:moveup:") or data.startswith("manual:movedown:"):
        parts = data.split(":")
        pid = int(parts[2])
        post = _own_post_or_none(uid, pid)
        if not post:
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        siblings = db.list_manual_posts_by_date(post["scheduled_at"][:10], owner_user_id=_owner_of(uid))
        ids = [r["id"] for r in siblings]
        idx = ids.index(pid) if pid in ids else -1
        if idx >= 0:
            if data.startswith("manual:moveup:") and idx > 0:
                db.swap_manual_queue_order(pid, ids[idx - 1])
            elif data.startswith("manual:movedown:") and idx < len(ids) - 1:
                db.swap_manual_queue_order(pid, ids[idx + 1])
        await _show_date_posts(query, context, post["scheduled_at"][:10], uid)
        return

    if data == "manual:dates":
        await _show_dates(query, context, uid)
        return

    if data.startswith("manual:dateview:"):
        date_str = data.split(":", 2)[2]
        await _show_date_posts(query, context, date_str, uid)
        return

    if data.startswith("manual:postview:"):
        pid = int(data.split(":")[2])
        await _show_post_detail(query, context, pid, uid)
        return

    if data.startswith("manual:sendnow:"):
        pid = int(data.split(":")[2])
        post = _own_post_or_none(uid, pid)
        if not post:
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        if not db.force_claim_manual_post(pid):
            await query.answer("این پست الان توسطِ صف در حالِ پردازشه.", show_alert=True)
            return
        await query.edit_message_text("⏳ در حالِ ارسال...")
        fresh = db.get_manual_post(pid)
        await _send_manual_post_row(context.bot, fresh)
        text, markup, pm = root_content(uid)
        await query.edit_message_text(text, parse_mode=pm, reply_markup=markup)
        return

    if data.startswith("manual:delpost:"):
        pid = int(data.split(":")[2])
        if not _own_post_or_none(uid, pid):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        db.delete_manual_post(pid)
        await query.answer("حذف شد.")
        await _show_dates(query, context, uid)
        return

    if data.startswith("manual:editpostcap:"):
        pid = int(data.split(":")[2])
        if not _own_post_or_none(uid, pid):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        context.user_data["manual_edit_post_id"] = pid
        context.user_data["manual_awaiting"] = "edit_post_caption"
        await query.edit_message_text(
            "متنِ/کپشنِ جدید رو بفرست:",
            reply_markup=InlineKeyboardMarkup([[_btn("🔙 بازگشت", f"manual:postview:{pid}")]]),
        )
        return

    if data.startswith("manual:editpostsched:"):
        pid = int(data.split(":")[2])
        if not _own_post_or_none(uid, pid):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        context.user_data["manual_edit_post_id"] = pid
        context.user_data["manual_awaiting"] = "edit_post_sched"
        await query.edit_message_text(
            "تاریخ/ساعتِ جدید رو به فرمتِ <code>1405/05/20 18:30</code> بفرست:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[_btn("🔙 بازگشت", f"manual:postview:{pid}")]]),
        )
        return

    if data.startswith("manual:editpostdest:"):
        pid = int(data.split(":")[2])
        if not _own_post_or_none(uid, pid):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        rows = []
        for d in db.list_destinations(active_only=True, owner_user_id=_owner_of(uid)):
            label = d["title"] or d["chat_id"]
            rows.append([_btn(f"🎯 {label}", f"manual:setpostdest:{pid}:{d['id']}")])
        rows.append([_btn("🔙 بازگشت", f"manual:postview:{pid}")])
        await query.edit_message_text("مقصدِ جدید رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("manual:setpostdest:"):
        _, _, pid_s, did_s = data.split(":")
        if not _own_post_or_none(uid, int(pid_s)):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        db.update_manual_post(int(pid_s), destination_id=int(did_s))
        await _show_post_detail(query, context, int(pid_s), uid)
        return

    if data.startswith("manual:cancelpost:"):
        pid = int(data.split(":")[2])
        if not _own_post_or_none(uid, pid):
            await query.answer("پست پیدا نشد یا مالِ تو نیست.", show_alert=True)
            return
        db.update_manual_post(pid, status="cancelled")
        await _show_post_detail(query, context, pid, uid)
        return

    await query.answer()


# ============================================================================
# ورودیِ متنی (کپشن/زمان‌بندی/دکمه)
# ============================================================================

_JALALI_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$")


def _parse_jalali_to_iso(text: str) -> Optional[str]:
    m = _JALALI_RE.match(text.strip())
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    try:
        jdt = jdatetime.datetime(y, mo, d, h, mi)
    except ValueError:
        return None
    gdt = jdt.togregorian().replace(tzinfo=TEHRAN_TZ)
    return gdt.astimezone(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not _can_use(uid):
        return False
    awaiting = context.user_data.get("manual_awaiting")
    if awaiting not in (
        "edit_caption", "sched_datetime", "btn_add_text", "btn_add_url",
        "edit_post_caption", "edit_post_sched",
    ):
        return False

    text = (update.message.text or "").strip()
    # فیکس: مسیرهای «ویرایشِ کپشن با تایپِ متنِ جدید» (edit_caption/edit_post_caption)
    # فقط از update.message.text (متنِ خام) استفاده می‌کردن، نه text_html؛ یعنی
    # اگه ادمین موقعِ نوشتنِ کپشنِ جدید از فرمت‌بندیِ تلگرام (بولد/ایتالیک/لینک)
    # استفاده می‌کرد، کاملاً از بین می‌رفت - برخلافِ مسیرِ مشابه در
    # handlers/inputs.py (ویرایشِ کپشنِ صفِ تایید) که از text_html استفاده می‌کنه.
    # الان همینِ متنِ HTML گرفته می‌شه و مثلِ همون مسیر از ensure_rtl_lines هم رد
    # می‌شه، فقط برای دو حالتِ کپشن (بقیه‌ی حالت‌ها - تاریخ/متنِ دکمه/لینک - همون
    # متنِ ساده رو لازم دارن، پس دست‌نخورده می‌مونن).
    text_html = (update.message.text_html or text or "").strip()

    if awaiting == "edit_caption":
        draft = _draft(context)
        draft["caption_html"] = ensure_rtl_lines(text_html) if text_html else text_html
        context.user_data["manual_awaiting"] = "preview"
        await _resend_preview(update, context)
        return True

    if awaiting == "sched_datetime":
        iso = _parse_jalali_to_iso(text)
        if not iso:
            await update.message.reply_text("❗️ فرمت درست نیست. مثال: 1405/05/20 18:30")
            return True
        if iso <= datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S"):
            await update.message.reply_text("❗️ این زمان گذشته. یک زمانِ آینده بفرست.")
            return True
        draft = _draft(context)
        draft["scheduled_at"] = iso
        if not draft.get("destination_id"):
            context.user_data["manual_awaiting"] = "preview"
            await update.message.reply_text(
                "⏰ زمان ثبت شد. حالا از پیش‌نمایش، «🎯 تغییر مقصد» رو بزن و بعد «✅ تایید ارسال» رو بزن "
                "تا زمان‌بندی نهایی بشه."
            )
            await _resend_preview(update, context)
            return True
        # مقصد از قبل انتخاب شده - مستقیم ذخیره کن
        await _save_scheduled(update, context)
        return True

    if awaiting == "btn_add_text":
        context.user_data["manual_btn_draft_text"] = text[:64]
        context.user_data["manual_awaiting"] = "btn_add_url"
        await update.message.reply_text("حالا لینکِ دکمه رو بفرست (باید با http(s):// یا t.me/ شروع بشه):")
        return True

    if awaiting == "btn_add_url":
        if not (text.startswith("http://") or text.startswith("https://") or text.startswith("t.me/")):
            await update.message.reply_text("❗️ لینک باید با http(s):// یا t.me/ شروع بشه. دوباره بفرست:")
            return True
        url = text if text.startswith("http") else f"https://{text}"
        draft = _draft(context)
        btn_text = context.user_data.pop("manual_btn_draft_text", "دکمه")
        draft.setdefault("buttons", []).append({"text": btn_text, "url": url})
        context.user_data["manual_awaiting"] = "preview"
        await _resend_preview(update, context)
        return True

    if awaiting == "edit_post_caption":
        pid = context.user_data.get("manual_edit_post_id")
        if pid:
            db.update_manual_post(pid, caption_html=ensure_rtl_lines(text_html) if text_html else text_html)
            await update.message.reply_text("✅ کپشن به‌روزرسانی شد.")
        context.user_data.pop("manual_awaiting", None)
        return True

    if awaiting == "edit_post_sched":
        pid = context.user_data.get("manual_edit_post_id")
        iso = _parse_jalali_to_iso(text)
        if not iso:
            await update.message.reply_text("❗️ فرمت درست نیست. مثال: 1405/05/20 18:30")
            return True
        if iso <= datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S"):
            await update.message.reply_text("❗️ این زمان گذشته. یک زمانِ آینده بفرست.")
            return True
        if pid:
            db.update_manual_post(pid, scheduled_at=iso, status="scheduled")
            await update.message.reply_text("✅ زمان‌بندی به‌روزرسانی شد.")
        context.user_data.pop("manual_awaiting", None)
        return True

    return False


async def _resend_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = _draft(context)
    await update.message.reply_text(
        _preview_text(draft), parse_mode=ParseMode.HTML, reply_markup=_preview_keyboard(),
    )


async def _save_scheduled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = _draft(context)
    _uid = update.effective_user.id if update.effective_user else None
    pid = db.create_manual_post(
        owner_user_id=_owner_of(_uid),
        created_by_tg_id=_uid,
        media_json=json.dumps(draft.get("media", []), ensure_ascii=False),
        caption_html=draft.get("caption_html", ""),
        buttons_json=json.dumps(draft.get("buttons", []), ensure_ascii=False),
        watermark_enabled=draft.get("watermark_enabled", True),
        destination_id=draft.get("destination_id"),
        scheduled_at=draft.get("scheduled_at", ""),
        status="scheduled",
    )
    if draft.get("watermark_id"):
        db.update_manual_post(pid, watermark_id=draft["watermark_id"])
    db.add_system_log(
        log_type="manual_post", event_type="scheduled", severity="info",
        message=f"پستِ دستیِ #{pid} زمان‌بندی شد.", destination_id=draft.get("destination_id"),
        post_id=pid, status="scheduled",
    )
    await update.message.reply_text(f"✅ پست با شماره‌ی #{pid} زمان‌بندی شد.")
    _clear_draft(context)


# ============================================================================
# مدیریتِ پست‌های زمان‌بندی‌شده (بخشِ ۳)
# ============================================================================

async def _show_dates(query, context: ContextTypes.DEFAULT_TYPE, uid: int | None = None) -> None:
    dates = db.list_manual_dates(owner_user_id=_owner_of(uid))
    rows = [[_btn(f"📅 {d['d']} ({d['cnt']} پست)", f"manual:dateview:{d['d']}")] for d in dates]
    rows.append([_btn("🔙 بازگشت", "menu:manual")])
    text = "🗂 <b>مدیریتِ پست‌های زمان‌بندی‌شده</b>" if dates else "هنوز هیچ پستِ زمان‌بندی‌شده‌ای نیست."
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))


async def _show_date_posts(query, context: ContextTypes.DEFAULT_TYPE, date_str: str, uid: int | None = None) -> None:
    posts = db.list_manual_posts_by_date(date_str, owner_user_id=_owner_of(uid))
    rows = []
    for p in posts:
        label = f"{STATUS_LABELS.get(p['status'], p['status'])} — #{p['id']} — {p['scheduled_at'][11:16]}"
        rows.append([_btn(label, f"manual:postview:{p['id']}")])
        rows.append([_btn("⬆️", f"manual:moveup:{p['id']}"), _btn("⬇️", f"manual:movedown:{p['id']}")])
    rows.append([_btn("🔙 بازگشت", "manual:dates")])
    await query.edit_message_text(
        f"📅 <b>{date_str}</b>\n{DIVIDER}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
    )


async def _show_post_detail(query, context: ContextTypes.DEFAULT_TYPE, pid: int, uid: int | None = None) -> None:
    p = db.get_manual_post(pid)
    if not p:
        await query.answer("پست پیدا نشد.", show_alert=True)
        return
    owner = _owner_of(uid)
    if owner is not None and p["owner_user_id"] != owner:
        await query.answer("⛔️ این پست مالِ تو نیست.", show_alert=True)
        return
    dest = db.get_destination(p["destination_id"]) if p["destination_id"] else None
    dest_text = (dest["title"] or dest["chat_id"]) if dest else "تعیین‌نشده"
    # همون فیکس: جزئیاتِ پستِ زمان‌بندی‌شده هم باید راست‌چینِ خطوطِ فارسی رو مثلِ
    # لحظه‌ی ارسالِ واقعی (_do_send) نشون بده، وگرنه این صفحه با پستی که واقعاً
    # فرستاده می‌شه فرق می‌کنه.
    _cap_raw = (p["caption_html"] or "").strip()
    cap = truncate_html_safe(ensure_rtl_lines(_cap_raw), 300) if _cap_raw else "(بدونِ متن)"
    text = (
        f"📨 <b>پستِ #{p['id']}</b>\n{DIVIDER}\n"
        f"وضعیت: {STATUS_LABELS.get(p['status'], p['status'])}\n"
        f"زمان: {p['scheduled_at']}\n"
        f"مقصد: {dest_text}\n"
        f"واترمارک: {'روشن' if p['watermark_enabled'] else 'خاموش'}\n"
    )
    if p["error_reason"]:
        text += f"آخرین خطا: {p['error_reason']}\n"
    text += f"\n<b>متن/کپشن:</b>\n{cap}"

    rows = [
        [_btn("✏️ ویرایشِ کپشن", f"manual:editpostcap:{pid}"), _btn("🗓 تغییرِ زمان", f"manual:editpostsched:{pid}")],
        [_btn("🎯 تغییرِ مقصد", f"manual:editpostdest:{pid}"), _btn("🚀 ارسالِ فوری", f"manual:sendnow:{pid}", style="success")],
        [_btn("🚫 لغو", f"manual:cancelpost:{pid}", style="danger"), _btn("🗑 حذف", f"manual:delpost:{pid}", style="danger")],
        [_btn("🔙 بازگشت", f"manual:dateview:{p['scheduled_at'][:10]}")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))


# ============================================================================
# ارسالِ واقعی (پیاده‌سازیِ مستقلِ ارسال - جدا از poster.send_post چون این‌جا
# باید صدا/GIF هم پشتیبانی بشه که send_post پشتیبانی نمی‌کنه)
# ============================================================================

async def _apply_watermark_if_needed(bot, file_id: str, watermark_enabled: bool, watermark_id: int | None = None) -> str | bytes:
    """اگه watermark_id ست شده باشه (بخشِ ۷/۸)، از واترمارکِ سفارشیِ نام‌دار
    استفاده می‌شه؛ وگرنه رفتارِ قدیمی (روشن/خاموشِ سراسری) حفظ می‌شه."""
    if watermark_id:
        try:
            from .custom_watermark import apply_named_watermark
            f = await bot.get_file(file_id)
            raw = bytes(await f.download_as_bytearray())
            wm_row = db.get_custom_watermark(watermark_id)
            if wm_row:
                return await apply_named_watermark(bot, raw, wm_row)
        except Exception as e:
            log.warning("اعمالِ واترمارکِ سفارشی شکست خورد؛ رفتارِ پیش‌فرض استفاده می‌شود: %s", e)
    if not watermark_enabled:
        return file_id
    try:
        f = await bot.get_file(file_id)
        raw = bytes(await f.download_as_bytearray())
        return await process_photo_bytes(raw, channel_id=None)
    except Exception as e:
        log.warning("پردازشِ واترمارکِ پستِ دستی شکست خورد؛ عکسِ خام فرستاده می‌شود: %s", e)
        return file_id


def _buttons_markup(buttons: list[dict]) -> Optional[InlineKeyboardMarkup]:
    if not buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["text"], url=b["url"])] for b in buttons])


async def _send_with_retry(coro_factory, attempts: int = 3):
    last_exc = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            last_exc = e
        except TelegramError as e:
            last_exc = e
            await asyncio.sleep(2.0 * (i + 1))
    if last_exc:
        raise last_exc


async def _do_send(bot, chat_id: str, media: list[dict], caption_html: str, watermark_enabled: bool,
                    buttons: list[dict], watermark_id: int | None = None) -> tuple[bool, str]:
    # ⚠️ باگ: حالتِ «ارسالِ دستی» (این فایل) اصلاً از formatter.py استفاده
    # نمی‌کرد؛ برخلافِ مسیرِ ری‌پستِ خودکار که caption از build_caption_html
    # (که ensure_rtl_lines رو صدا می‌زنه) رد می‌شه. نتیجه: خطوطِ فارسیِ کپشنِ
    # دستی هیچ‌وقت علامتِ راست‌چین نمی‌گرفتن و فاصله‌ی بینِ دو quote هم نرمال
    # نمی‌شد. همین‌جا - تنها نقطه‌ای که همه‌ی مسیرهای ارسالِ دستی (متن‌تنها،
    # تک‌مدیا، آلبوم) قبل از ارسال از توش رد می‌شن - رفعش می‌کنیم.
    caption_html = ensure_rtl_lines(caption_html) if caption_html else caption_html
    cap = truncate_html_safe(caption_html, 1024) if caption_html else None
    parse_mode = ParseMode.HTML if cap else None
    markup = _buttons_markup(buttons)

    try:
        if not media:
            if not caption_html.strip():
                return False, "پست خالیه (نه متن دارد، نه مدیا)."
            safe_text = truncate_html_safe(caption_html, 4096)
            await _send_with_retry(lambda: bot.send_message(
                chat_id=chat_id, text=safe_text, parse_mode=ParseMode.HTML, reply_markup=markup,
            ))
            return True, ""

        if len(media) == 1:
            m = media[0]
            if m["type"] == "photo":
                photo = await _apply_watermark_if_needed(bot, m["file_id"], watermark_enabled, watermark_id)
                await _send_with_retry(lambda: bot.send_photo(
                    chat_id=chat_id, photo=photo, caption=cap, parse_mode=parse_mode, reply_markup=markup,
                ))
            elif m["type"] == "video":
                await _send_with_retry(lambda: bot.send_video(
                    chat_id=chat_id, video=m["file_id"], caption=cap, parse_mode=parse_mode,
                    reply_markup=markup, supports_streaming=True,
                ))
            elif m["type"] == "animation":
                await _send_with_retry(lambda: bot.send_animation(
                    chat_id=chat_id, animation=m["file_id"], caption=cap, parse_mode=parse_mode, reply_markup=markup,
                ))
            elif m["type"] == "voice":
                await _send_with_retry(lambda: bot.send_voice(
                    chat_id=chat_id, voice=m["file_id"], caption=cap, parse_mode=parse_mode, reply_markup=markup,
                ))
            elif m["type"] == "document":
                await _send_with_retry(lambda: bot.send_document(
                    chat_id=chat_id, document=m["file_id"], caption=cap, parse_mode=parse_mode, reply_markup=markup,
                ))
            return True, ""

        # آلبوم: فقط عکس/ویدیو در یک send_media_group قابل ترکیب هستن.
        group_items = [m for m in media if m["type"] in ("photo", "video")]
        others = [m for m in media if m["type"] not in ("photo", "video")]
        if group_items:
            input_media = []
            cap_used = False
            for m in group_items:
                item_cap = cap if not cap_used else None
                item_pm = parse_mode if item_cap else None
                if m["type"] == "photo":
                    photo = await _apply_watermark_if_needed(bot, m["file_id"], watermark_enabled, watermark_id)
                    input_media.append(InputMediaPhoto(media=photo, caption=item_cap, parse_mode=item_pm))
                else:
                    input_media.append(InputMediaVideo(
                        media=m["file_id"], caption=item_cap, parse_mode=item_pm, supports_streaming=True,
                    ))
                if item_cap:
                    cap_used = True
            await _send_with_retry(lambda: bot.send_media_group(chat_id=chat_id, media=input_media))
            if markup:
                # دکمه‌ی اینلاین روی آلبوم پشتیبانی نمی‌شه؛ به‌عنوانِ پیامِ جدا فرستاده میشه.
                await bot.send_message(chat_id=chat_id, text="🔗 لینک‌های مرتبط 👇", reply_markup=markup)

        for m in others:
            if m["type"] == "voice":
                await bot.send_voice(chat_id=chat_id, voice=m["file_id"])
            elif m["type"] == "animation":
                await bot.send_animation(chat_id=chat_id, animation=m["file_id"])
            elif m["type"] == "document":
                await bot.send_document(chat_id=chat_id, document=m["file_id"])

        return True, ""

    except TelegramError as e:
        reason = str(e)
        if "not enough rights" in reason.lower() or "chat not found" in reason.lower() or "kicked" in reason.lower():
            reason += " (احتمالاً ربات توی این کانال ادمین نیست یا حذف شده)"
        return False, reason
    except Exception as e:
        log.exception("خطای غیرمنتظره در ارسالِ پستِ دستی: %s", e)
        return False, f"خطای غیرمنتظره: {e}"


async def _send_draft_now(bot, draft: dict) -> tuple[bool, str]:
    d = db.get_destination(draft["destination_id"])
    if not d:
        return False, "مقصد پیدا نشد."
    return await _do_send(
        bot, d["chat_id"], draft.get("media", []), draft.get("caption_html", ""),
        draft.get("watermark_enabled", True), draft.get("buttons", []),
        watermark_id=draft.get("watermark_id"),
    )


async def _send_manual_post_row(bot, row) -> None:
    """ارسالِ یک ردیفِ manual_posts (چه از زمان‌بندی، چه دستی از دکمه‌ی «ارسالِ فوری»)."""
    dest = db.get_destination(row["destination_id"]) if row["destination_id"] else None
    if not dest:
        db.update_manual_post(row["id"], status="failed", error_reason="مقصد تعیین نشده یا حذف شده.")
        return
    media = json.loads(row["media_json"] or "[]")
    buttons = json.loads(row["buttons_json"] or "[]")
    ok, err = await _do_send(
        bot, dest["chat_id"], media, row["caption_html"] or "", bool(row["watermark_enabled"]), buttons,
        watermark_id=row["watermark_id"] if "watermark_id" in row.keys() else None,
    )
    now_iso = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    if ok:
        db.update_manual_post(row["id"], status="sent", sent_at=now_iso, error_reason="")
        db.add_system_log(
            log_type="manual_post", event_type="sent", severity="info",
            message=f"پستِ دستیِ #{row['id']} با موفقیت ارسال شد.",
            destination_id=row["destination_id"], post_id=row["id"], status="sent",
        )
    else:
        retry = (row["retry_count"] or 0) + 1
        if retry >= 3:
            db.update_manual_post(row["id"], status="failed", error_reason=err, retry_count=retry)
            db.add_system_log(
                log_type="manual_post", event_type="failed", severity="error",
                message=f"پستِ دستیِ #{row['id']} بعدِ {retry} تلاش ناموفق بود: {err}",
                destination_id=row["destination_id"], post_id=row["id"], status="failed",
            )
        else:
            # برگردوندن به scheduled برای تلاشِ بعدی (کنترلِ FloodWait/خطاهای موقت)
            db.update_manual_post(row["id"], status="scheduled", error_reason=err, retry_count=retry)
            db.add_system_log(
                log_type="manual_post", event_type="retry", severity="warning",
                message=f"پستِ دستیِ #{row['id']} ارسال نشد؛ تلاشِ دوباره در چرخشِ بعدی ({retry}/3): {err}",
                destination_id=row["destination_id"], post_id=row["id"], status="scheduled",
            )


# ============================================================================
# حلقه‌ی زمان‌بندیِ پس‌زمینه (بخشِ ۴ - سیستمِ صف)
# ============================================================================

async def run_manual_scheduler_loop(bot) -> None:
    """هر ۲۰ ثانیه چک می‌کنه چه پستِ زمان‌بندی‌شده‌ای الان باید بره. با
    claim_manual_post_for_sending از ارسالِ دوباره (مثلاً بعدِ Crash/ری‌استارت)
    جلوگیری می‌کنه."""
    recovered = db.recover_stuck_manual_posts()
    if recovered:
        log.info("سیستمِ ارسالِ دستی: %s پستِ نیمه‌کاره از قبل از کرش، به صف برگردوندن شد.", recovered)

    while True:
        try:
            now_str = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
            due = db.list_due_manual_posts(now_str)
            for row in due:
                # صفِ هر کاربر جداست: اگه صاحبِ این پست صفِ خودش رو متوقف کرده
                # باشه، فقط پست‌های خودش رد می‌شن؛ پست‌های ادمین و بقیه‌ی کاربرها
                # طبقِ روال ارسال می‌شن (ایزوله‌سازیِ کاملِ چندکاربره - بخشِ ۱۱).
                # owner_user_id برای پست‌های ادمین NULL است که به‌درستی به کلیدِ
                # سراسریِ توقفِ صفِ ادمین نگاشت می‌شه.
                if db.is_manual_queue_paused(row["owner_user_id"]):
                    continue
                if db.claim_manual_post_for_sending(row["id"]):
                    fresh = db.get_manual_post(row["id"])
                    await _send_manual_post_row(bot, fresh)
        except Exception:
            log.exception("خطا در حلقه‌ی اسکجولرِ ارسالِ دستی.")
        await asyncio.sleep(20)
