"""
منویِ یکپارچه‌یِ مدیریتِ API هوش مصنوعی (Mistral، Groq، Gemini، HuggingFace).

هر سرویس حالا می‌تونه تا ۵ کلیدِ API داشته باشه (مثلاً چند اکانتِ جداگانه‌ی
Gemini). فراخوانی‌ها به‌طورِ چرخشی بینِ کلیدهایِ فعال پخش می‌شن و وقتی یک
کلید Quota تمام کنه، خودکار به کلیدِ بعدی سوییچ می‌شه (نگاه کن به
ai_provider_manager.py). این منو فقط CRUD رویِ کلیدهاست؛ منطقِ چرخش در
لایه‌ی پایین‌تره و روی همه‌ی وظایف (فیلتر، خلاصه‌سازی، بازنویسی، ترجمه،
تولیدِ تصویر، چت و ...) به‌طورِ یکسان اعمال می‌شه.

فضای‌نامِ callback_data: aiapi:*
دسترسی: ادمین + کاربرِ با پرمیشنِ «ai»
"""
from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import ai_catalog as cat
from .. import ai_crypto as crypto
from .. import ai_provider_manager as mgr
from .common import has_perm, is_admin, safe_edit, scope_owner

log = logging.getLogger("repost_bot.ai_providers_menu")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
MAX_KEYS = mgr.MAX_KEYS_PER_SERVICE


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _can_access(uid: int | None) -> bool:
    return is_admin(uid) or has_perm(uid, "ai")


def _cap_icons(info: cat.ProviderInfo) -> str:
    parts = []
    if info.has_text:
        parts.append("📝")
    if info.has_image:
        parts.append("🖼")
    return " ".join(parts)


def _status_icon(status: str) -> str:
    if status == cat.STATUS_ACTIVE:
        return "🟢"
    if status in (cat.STATUS_CHECKING, cat.STATUS_FALLBACK):
        return "🟡"
    if status == cat.STATUS_QUOTA_EXCEEDED:
        return "🟠"
    return "🔴"


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return key[:6] + "…" + key[-3:]


# ────────────────────────────────────────────────────────────────────────────
# صفحه‌ی اصلی
# ────────────────────────────────────────────────────────────────────────────

def home_text() -> str:
    return (
        "🔌 <b>مدیریتِ API هوش مصنوعی</b>\n"
        f"{DIVIDER}\n"
        "۴ سرویس موجود: <b>Mistral AI</b>، <b>Groq</b>، <b>Google Gemini</b>، <b>Hugging Face</b>\n\n"
        "📝 = پشتیبانیِ متن  |  🖼 = پشتیبانیِ تولیدِ تصویر\n\n"
        f"برایِ هر سرویس می‌تونی تا <b>{MAX_KEYS} کلیدِ API</b> (مثلاً از چند اکانتِ "
        "مختلف) ثبت کنی. فراخوانی‌ها به‌طورِ چرخشی بینِ کلیدهایِ فعال پخش "
        "می‌شن و وقتی یکی Quota تمام کنه، خودکار می‌ره سراغِ بعدی.\n\n"
        "⚠️ اگه هیچ کلیدی تنظیم نکنی، ربات با کلیدهایِ پیش‌فرضِ .env کار می‌کنه."
    )


def home_menu(owner_user_id: int | None) -> InlineKeyboardMarkup:
    rows = []
    for info, status in mgr.list_status(owner_user_id):
        icon = _status_icon(status)
        caps = _cap_icons(info)
        n = mgr.key_count(owner_user_id, info.id)
        count_str = f" ({n}/{MAX_KEYS})" if n else ""
        rows.append([_btn(f"{icon} {info.label}  {caps}{count_str}", f"aiapi:svc:{info.id}")])
    rows.append([_btn("🔀 مسیریابیِ وظایف", "aiapi:tasks")])
    rows.append([_btn("📊 آمارِ کلی", "aiapi:allstats")])
    rows.append([_btn("🧠 وضعیتِ زنده‌ی موتورهایِ AI", "ai:status_services")])
    rows.append([_btn("🔙 بازگشت به منو", "menu:ai_services")])
    return InlineKeyboardMarkup(rows)


# ────────────────────────────────────────────────────────────────────────────
# جزئیاتِ یک سرویس
# ────────────────────────────────────────────────────────────────────────────

def _model_list(models: tuple[str, ...], default: str, max_show: int = 5) -> str:
    lines = []
    for m in models[:max_show]:
        mark = " ✦" if m == default else ""
        lines.append(f"  • {html.escape(m)}{mark}")
    if len(models) > max_show:
        lines.append(f"  … و {len(models) - max_show} مدلِ دیگر")
    return "\n".join(lines) if lines else "  —"


def service_text(owner_user_id: int | None, service_id: str) -> str:
    info = cat.get_provider(service_id)
    if not info:
        return "❌ سرویسِ ناشناخته."
    keys = mgr.list_keys(owner_user_id, service_id)
    status = mgr.get_status(owner_user_id, service_id)

    caps_str = _cap_icons(info)
    if info.has_text and info.has_image:
        caps_str += "  (متن + تصویر)"
    elif info.has_text:
        caps_str += "  (فقط متن)"
    else:
        caps_str += "  (فقط تصویر)"

    lines = [
        f"🔌 <b>{html.escape(info.label)}</b>  {caps_str}",
        f"{DIVIDER}",
        f"وضعیتِ کلی: {cat.STATUS_LABELS.get(status, status)}",
        f"تعدادِ کلیدهایِ ثبت‌شده: {len(keys)}/{MAX_KEYS}",
    ]

    if info.has_text and info.text_models:
        lines.append(f"\n📝 <b>مدل‌هایِ متنی</b> (✦ = پیش‌فرض):\n{_model_list(info.text_models, info.default_text_model)}")

    if info.has_image and info.image_models:
        lines.append(f"\n🖼 <b>مدل‌هایِ تصویری</b> (✦ = پیش‌فرض):\n{_model_list(info.image_models, info.default_image_model)}")

    if info.key_prefixes:
        lines.append(f"\n🔑 فرمتِ کلید: <code>{'...</code> یا <code>'.join(info.key_prefixes)}...</code>")

    if keys:
        lines.append(f"\n{DIVIDER}\n<b>کلیدها:</b>")
        for row in keys:
            icon = _status_icon(row["status"])
            masked = _mask_key(crypto.decrypt_text(row["api_key_encrypted"]))
            st_label = cat.STATUS_LABELS.get(row["status"], row["status"])
            lines.append(f"{icon} #{row['slot']}  <code>{html.escape(masked)}</code>  —  {st_label}")

    lines.append(f"\n{DIVIDER}")
    if len(keys) < MAX_KEYS:
        lines.append("برایِ افزودنِ کلیدِ جدید از دکمه‌ی «➕ افزودنِ کلید» استفاده کن یا کلید رو مستقیم بفرست.")
    else:
        lines.append(f"سقفِ {MAX_KEYS} کلید برایِ این سرویس پر شده. برایِ افزودنِ کلیدِ جدید، اول یکی رو حذف کن.")
    return "\n".join(lines)


def service_menu(owner_user_id: int | None, service_id: str) -> InlineKeyboardMarkup:
    n = mgr.key_count(owner_user_id, service_id)
    rows: list[list[InlineKeyboardButton]] = []
    if n < MAX_KEYS:
        rows.append([_btn("➕ افزودنِ کلید", f"aiapi:enter_key:{service_id}")])
    if n:
        rows.append([_btn("🗂 مدیریتِ کلیدها", f"aiapi:keys:{service_id}")])
        rows.append([_btn("🔄 بررسیِ اتصالِ همه", f"aiapi:retest:{service_id}")])
    rows.append([_btn("📊 آمار", f"aiapi:stats:{service_id}")])
    rows.append([_btn("🔙 بازگشت", "aiapi:home")])
    return InlineKeyboardMarkup(rows)


# ────────────────────────────────────────────────────────────────────────────
# مدیریتِ تک‌تکِ کلیدها
# ────────────────────────────────────────────────────────────────────────────

def keys_text(owner_user_id: int | None, service_id: str) -> str:
    info = cat.get_provider(service_id)
    label = info.label if info else service_id
    keys = mgr.list_keys(owner_user_id, service_id)
    if not keys:
        return f"🗂 <b>کلیدهایِ {html.escape(label)}</b>\n{DIVIDER}\nهنوز کلیدی ثبت نشده."
    lines = [f"🗂 <b>کلیدهایِ {html.escape(label)}</b>  ({len(keys)}/{MAX_KEYS})", DIVIDER]
    for row in keys:
        icon = _status_icon(row["status"])
        masked = _mask_key(crypto.decrypt_text(row["api_key_encrypted"]))
        st_label = cat.STATUS_LABELS.get(row["status"], row["status"])
        lines.append(f"{icon} <b>#{row['slot']}</b>  <code>{html.escape(masked)}</code>")
        lines.append(f"   {st_label}")
        if row["status_detail"]:
            lines.append(f"   <i>{html.escape(row['status_detail'][:150])}</i>")
        req = row["total_requests"] or 0
        if req:
            lines.append(f"   {req} درخواست، {row['total_errors'] or 0} خطا")
    return "\n".join(lines)


def keys_menu(owner_user_id: int | None, service_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in mgr.list_keys(owner_user_id, service_id):
        slot = row["slot"]
        icon = _status_icon(row["status"])
        rows.append([
            _btn(f"{icon} #{slot} 🔄 بررسی", f"aiapi:retestkey:{service_id}:{slot}"),
            _btn(f"🗑 حذفِ #{slot}", f"aiapi:delkey:{service_id}:{slot}"),
        ])
    n = mgr.key_count(owner_user_id, service_id)
    if n < MAX_KEYS:
        rows.append([_btn("➕ افزودنِ کلیدِ جدید", f"aiapi:enter_key:{service_id}")])
    rows.append([_btn("🔙 بازگشت", f"aiapi:svc:{service_id}")])
    return InlineKeyboardMarkup(rows)


# ────────────────────────────────────────────────────────────────────────────
# مسیریابیِ وظایف
# ────────────────────────────────────────────────────────────────────────────

def tasks_text() -> str:
    return (
        "🔀 <b>مسیریابیِ وظایف</b>\n"
        f"{DIVIDER}\n"
        "برایِ هر وظیفه می‌تونی مشخص کنی کدوم سرویس اجراش کنه.\n"
        "اگه سرویسِ اصلی در دسترس نبود، Fallback استفاده می‌شه.\n"
        "توجه: اگه سرویسِ انتخابی چند کلید داشته باشه، بینِ اون کلیدها هم "
        "به‌طورِ خودکار چرخش انجام می‌شه."
    )


def tasks_menu(owner_user_id: int | None) -> InlineKeyboardMarkup:
    rows = []
    for task in cat.ALL_TASKS.values():
        p, f = mgr.get_task_route(owner_user_id, task.id)
        route_str = ""
        if p:
            pinfo = cat.get_provider(p)
            route_str = f" → {pinfo.label if pinfo else p}"
        rows.append([_btn(f"{task.label}{route_str}", f"aiapi:task:{task.id}")])
    rows.append([_btn("🔙 بازگشت", "aiapi:home")])
    return InlineKeyboardMarkup(rows)


def task_detail_text(owner_user_id: int | None, task_id: str) -> str:
    task = cat.ALL_TASKS.get(task_id)
    if not task:
        return "❌ وظیفه‌ی ناشناخته."
    p, f = mgr.get_task_route(owner_user_id, task_id)
    pinfo = cat.get_provider(p) if p else None
    finfo = cat.get_provider(f) if f else None
    lines = [
        f"⚙️ <b>{task.label}</b>",
        f"{DIVIDER}",
        f"سرویسِ اصلی: {pinfo.label if pinfo else '— (پیش‌فرضِ .env)'} ",
        f"سرویسِ جایگزین: {finfo.label if finfo else '—'}",
    ]
    return "\n".join(lines)


def task_detail_menu(owner_user_id: int | None, task_id: str) -> InlineKeyboardMarkup:
    task = cat.ALL_TASKS.get(task_id)
    if not task:
        return InlineKeyboardMarkup([[_btn("🔙 بازگشت", "aiapi:tasks")]])
    cap = task.category  # text یا image
    rows = []
    eligible = [p for p in cat.all_providers() if cap in p.capabilities]
    rows.append([_btn("── سرویسِ اصلی ──", "aiapi:noop")])
    rows.append([_btn("🚫 بدونِ سرویسِ سفارشی (پیش‌فرض)", f"aiapi:setprimary:{task_id}:")])
    for p in eligible:
        rows.append([_btn(p.label, f"aiapi:setprimary:{task_id}:{p.id}")])
    p_current, _ = mgr.get_task_route(owner_user_id, task_id)
    rows.append([_btn("── سرویسِ جایگزین (Fallback) ──", "aiapi:noop")])
    rows.append([_btn("🚫 بدونِ Fallback", f"aiapi:setfallback:{task_id}:")])
    for p in eligible:
        if p.id != p_current:
            rows.append([_btn(p.label, f"aiapi:setfallback:{task_id}:{p.id}")])
    rows.append([_btn("🔙 بازگشت", "aiapi:tasks")])
    return InlineKeyboardMarkup(rows)


# ────────────────────────────────────────────────────────────────────────────
# آمارِ همه‌ی سرویس‌ها
# ────────────────────────────────────────────────────────────────────────────

def allstats_text(owner_user_id: int | None) -> str:
    parts = [f"📊 <b>آمارِ کلیِ سرویس‌ها</b>\n{DIVIDER}"]
    for info in cat.all_providers():
        parts.append(mgr.get_stats_text(owner_user_id, info.id))
    return "\n\n".join(parts)


def allstats_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("🔙 بازگشت", "aiapi:home")]])


# ────────────────────────────────────────────────────────────────────────────
# Dispatcher (dispatch توسطِ handlers/__init__.py صدا می‌شه)
# ────────────────────────────────────────────────────────────────────────────

async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    uid = query.from_user.id if query.from_user else None
    if not _can_access(uid):
        await query.answer("⛔ دسترسی ندارید.", show_alert=True)
        return

    owner = scope_owner(uid)
    data  = query.data or ""

    # ─── home ───
    if data == "aiapi:home":
        await safe_edit(query, home_text(), home_menu(owner), ParseMode.HTML)

    # ─── service detail ───
    elif data.startswith("aiapi:svc:"):
        sid = data.split(":", 2)[2]
        await safe_edit(query, service_text(owner, sid), service_menu(owner, sid), ParseMode.HTML)

    # ─── enter key (افزودنِ کلیدِ جدید؛ جایگزینِ کلیدِ قبلی نمی‌شه) ───
    elif data.startswith("aiapi:enter_key:"):
        sid = data.split(":", 2)[2]
        info = cat.get_provider(sid)
        if not info:
            await query.answer("سرویسِ ناشناخته.", show_alert=True)
            return
        if mgr.key_count(owner, sid) >= MAX_KEYS:
            await query.answer(f"سقفِ {MAX_KEYS} کلید پر شده؛ اول یکی رو حذف کن.", show_alert=True)
            return
        context.user_data["aiapi_awaiting_key"] = sid
        hint = f"({', '.join(info.key_prefixes)}...)" if info.key_prefixes else ""
        n = mgr.key_count(owner, sid)
        await safe_edit(
            query,
            f"🔑 <b>افزودنِ کلیدِ جدیدِ {html.escape(info.label)}</b>  ({n}/{MAX_KEYS})\n{DIVIDER}\n"
            f"کلیدِ API رو بفرست {hint}\n\n"
            "می‌تونی از چند اکانتِ مختلف چند کلید اضافه کنی؛ ربات به‌طورِ خودکار "
            "بینشون چرخش می‌کنه.\n\n"
            "⚠️ کلید در همین لحظه اعتبارسنجی می‌شه.",
            InlineKeyboardMarkup([[_btn("🔙 انصراف", f"aiapi:svc:{sid}")]]),
            ParseMode.HTML,
        )

    # ─── retest all keys ───
    elif data.startswith("aiapi:retest:"):
        sid = data.split(":", 2)[2]
        info = cat.get_provider(sid)
        await safe_edit(
            query,
            f"🔄 در حالِ بررسیِ اتصالِ همه‌ی کلیدهایِ {html.escape(info.label if info else sid)}...",
            InlineKeyboardMarkup([]),
            ParseMode.HTML,
        )
        await mgr.retest_all_keys(owner, sid)
        await safe_edit(query, service_text(owner, sid), service_menu(owner, sid), ParseMode.HTML)

    # ─── مدیریتِ کلیدها (لیست) ───
    elif data.startswith("aiapi:keys:"):
        sid = data.split(":", 2)[2]
        await safe_edit(query, keys_text(owner, sid), keys_menu(owner, sid), ParseMode.HTML)

    # ─── retest تکی ───
    elif data.startswith("aiapi:retestkey:"):
        parts = data.split(":", 3)
        sid, slot = parts[2], int(parts[3])
        await mgr.retest_key(owner, sid, slot)
        await safe_edit(query, keys_text(owner, sid), keys_menu(owner, sid), ParseMode.HTML)

    # ─── حذفِ کلیدِ تکی ───
    elif data.startswith("aiapi:delkey:"):
        parts = data.split(":", 3)
        sid, slot = parts[2], int(parts[3])
        mgr.delete_key(owner, sid, slot)
        remaining = mgr.key_count(owner, sid)
        if remaining:
            await safe_edit(query, keys_text(owner, sid), keys_menu(owner, sid), ParseMode.HTML)
        else:
            await safe_edit(query, service_text(owner, sid), service_menu(owner, sid), ParseMode.HTML)

    # ─── stats single service ───
    elif data.startswith("aiapi:stats:"):
        sid = data.split(":", 2)[2]
        await safe_edit(
            query,
            mgr.get_stats_text(owner, sid),
            InlineKeyboardMarkup([[_btn("🔙 بازگشت", f"aiapi:svc:{sid}")]]),
            ParseMode.HTML,
        )

    # ─── allstats ───
    elif data == "aiapi:allstats":
        await safe_edit(query, allstats_text(owner), allstats_menu(), ParseMode.HTML)

    # ─── tasks ───
    elif data == "aiapi:tasks":
        await safe_edit(query, tasks_text(), tasks_menu(owner), ParseMode.HTML)

    elif data.startswith("aiapi:task:"):
        task_id = data.split(":", 2)[2]
        await safe_edit(query, task_detail_text(owner, task_id), task_detail_menu(owner, task_id), ParseMode.HTML)

    elif data.startswith("aiapi:setprimary:"):
        parts = data.split(":", 3)
        task_id     = parts[2]
        provider_id = parts[3] if len(parts) > 3 else ""
        _, fallback = mgr.get_task_route(owner, task_id)
        mgr.set_task_route(owner, task_id, provider_id, fallback)
        await safe_edit(query, task_detail_text(owner, task_id), task_detail_menu(owner, task_id), ParseMode.HTML)

    elif data.startswith("aiapi:setfallback:"):
        parts = data.split(":", 3)
        task_id     = parts[2]
        fallback_id = parts[3] if len(parts) > 3 else ""
        primary, _  = mgr.get_task_route(owner, task_id)
        mgr.set_task_route(owner, task_id, primary, fallback_id)
        await safe_edit(query, task_detail_text(owner, task_id), task_detail_menu(owner, task_id), ParseMode.HTML)

    elif data == "aiapi:noop":
        pass  # no-op برایِ هدرهایِ غیرقابلِ کلیک


async def handle_key_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    اگه کاربر در حالِ وارد کردنِ کلید بود (aiapi_awaiting_key)، پیامش رو بگیر،
    اعتبارسنجی کن و به‌عنوانِ کلیدِ جدید (در اولین slotِ خالی) ثبتش کن، و True
    برگردون (تا handler chain قطع بشه). در غیرِ این صورت False برگردون.
    """
    sid = context.user_data.get("aiapi_awaiting_key")
    if not sid or not update.message:
        return False

    uid   = update.message.from_user.id if update.message.from_user else None
    owner = scope_owner(uid)
    raw   = (update.message.text or "").strip()
    context.user_data.pop("aiapi_awaiting_key", None)

    # حذفِ پیامِ کاربر برایِ امنیت
    try:
        await update.message.delete()
    except Exception:
        pass

    info = cat.get_provider(sid)
    if not info or not raw:
        return True

    msg = await update.message.chat.send_message(
        f"🔄 در حالِ اعتبارسنجیِ کلیدِ <b>{html.escape(info.label)}</b>...",
        parse_mode=ParseMode.HTML,
    )
    slot, status, detail = await mgr.add_key(owner, sid, raw)

    status_label = cat.STATUS_LABELS.get(status, status)
    result_icon  = "✅" if status == cat.STATUS_ACTIVE else "❌"
    if slot is not None:
        caption = f"{result_icon} کلیدِ #{slot} ثبت شد — {status_label}"
    else:
        caption = f"{result_icon} {status_label}"
    if detail:
        caption += f"\n<i>{html.escape(detail[:200])}</i>"

    await msg.edit_text(
        caption,
        parse_mode=ParseMode.HTML,
        reply_markup=service_menu(owner, sid),
    )
    return True


# ────────────────────────────────────────────────────────────────────────────
# Backward-compat aliases (برایِ menu.py و inputs.py که با signature قدیمی صدا می‌زنن)
# ────────────────────────────────────────────────────────────────────────────

async def handle_callback(
    data: str,
    query,
    context: ContextTypes.DEFAULT_TYPE,
    uid: int | None,
) -> None:
    """
    menu.py این signature رو می‌خواد:
        handle_callback(data, query, context, uid)
    """
    from telegram import Update as _Update
    fake_update = _Update(0, callback_query=query)
    await dispatch(fake_update, context)


async def handle_text_input(
    update,
    context: ContextTypes.DEFAULT_TYPE,
    sub_key: str,
    text: str,
) -> None:
    """
    inputs.py این signature رو می‌خواد:
        handle_text_input(update, context, "setkey:service_id", text)
    """
    if sub_key.startswith("setkey:"):
        sid   = sub_key[len("setkey:"):]
        uid   = update.message.from_user.id if (update.message and update.message.from_user) else None
        owner = scope_owner(uid)
        info  = cat.get_provider(sid)
        if not info or not text:
            return
        msg = await update.message.chat.send_message(
            f"🔄 در حالِ اعتبارسنجیِ کلیدِ <b>{html.escape(info.label)}</b>...",
            parse_mode=ParseMode.HTML,
        )
        try:
            await update.message.delete()
        except Exception:
            pass
        slot, status, detail = await mgr.add_key(owner, sid, text)
        status_label = cat.STATUS_LABELS.get(status, status)
        result_icon  = "✅" if status == cat.STATUS_ACTIVE else "❌"
        caption = f"{result_icon} کلیدِ #{slot} ثبت شد — {status_label}" if slot is not None else f"{result_icon} {status_label}"
        if detail:
            caption += f"\n<i>{html.escape(detail[:200])}</i>"
        await msg.edit_text(
            caption,
            parse_mode=ParseMode.HTML,
            reply_markup=service_menu(owner, sid),
        )
