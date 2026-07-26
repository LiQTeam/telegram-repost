"""
منطقِ پنلِ مدیریتِ ماژولِ «تبلیغات».

⚠️ این ماژول قبلاً شاملِ زیرسیستمِ «قیمت‌ها» هم بود؛ طبقِ درخواستِ کاربر اون
بخش کاملاً حذف شد (کد + HTML/CSS/فونت/آیکون‌ها + جدول‌های دیتابیس) و فقط
زیرسیستمِ تبلیغات باقی مونده. برای همینِ منظور، callback prefix داخلیِ «npz:»
(که قبلاً بینِ «npz:price:...» و «npz:ads:...» مشترک بود) دست‌نخورده مونده
تا سازگاریِ داده‌های قدیمی حفظ بشه، ولی همه‌ی مسیرها الان فقط زیرِ «npz:ads:»ان.

هیچ تابعی اینجا مستقیماً روی دیتابیس یا کشِ رَی‌پستِ اصلی کار نمی‌کنه.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import db, keyboards as kb
from . import ads as _ads

log = logging.getLogger("repost_bot.auto_poster.menu")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


# ==================== محتوای صفحات ====================
def _ads_root_text() -> str:
    enabled = db.get_bool("ads_module_enabled", False)
    times = db.list_ads_schedule()
    targets = db.list_ads_targets()
    target_labels = ", ".join(t.get("name") or t["chat_id"] for t in targets) if targets else "تنظیم نشده"
    btn_count = len(db.list_ads_buttons())
    caption = db.get_setting("ads_caption_text") or "(پیش‌فرض)"
    preview = caption if len(caption) <= 120 else caption[:120] + "…"
    return (
        "📢 <b>تنظیماتِ تبلیغات</b>\n"
        f"{DIVIDER}\n"
        f"وضعیت: {'🟢 روشن' if enabled else '🔴 خاموش'}\n"
        f"زمان‌بندی: {', '.join(times) if times else 'تنظیم نشده'}\n"
        f"کانال‌های مقصد ({len(targets)}): {target_labels}\n"
        f"تعدادِ دکمه‌ها: {btn_count}\n"
        f"{DIVIDER}\n"
        f"📝 <b>کپشنِ فعلی:</b>\n{preview}"
    )


def root_content():
    """نقطه‌ی ورودِ منویِ اصلیِ این ماژول (صداشده از هسته‌ی ربات)."""
    return _ads_root_text(), kb.ads_root_menu(), ParseMode.HTML


def ads_root_content():
    return _ads_root_text(), kb.ads_root_menu(), ParseMode.HTML


def ads_buttons_list_content():
    buttons = db.list_ads_buttons()
    text = (
        "🗑 <b>حذف/ویرایشِ دکمه‌های تبلیغاتی</b>\n"
        f"{DIVIDER}\n"
        + ("\n".join(f"• {b['name']} — {b['url']}" for b in buttons) if buttons else "هنوز دکمه‌ای اضافه نشده.")
    )
    return text, kb.ads_buttons_list_menu(buttons), ParseMode.HTML


def ads_schedule_content():
    times = db.list_ads_schedule()
    text = (
        "⏱ <b>زمان‌بندیِ انتشارِ تبلیغ</b>\n"
        f"{DIVIDER}\n"
        + ("\n".join(f"🕒 {t}" for t in times) if times else "هنوز زمانی تنظیم نشده.")
    )
    return text, kb.ads_schedule_menu(), ParseMode.HTML


def ads_targets_content():
    targets = db.list_ads_targets()
    lines = [f"• {t.get('name') or 'بدونِ اسم'} — <code>{t['chat_id']}</code>" for t in targets]
    text = (
        "📡 <b>کانال‌های مقصدِ تبلیغات</b>\n"
        f"{DIVIDER}\n"
        + ("\n".join(lines) if lines else "هنوز کانالی اضافه نشده.")
        + f"\n{DIVIDER}\nهر پیامِ تبلیغاتی به‌طورِ هم‌زمان به همه‌ی کانال‌های زیر فرستاده می‌شه."
    )
    return text, kb.ads_targets_menu(), ParseMode.HTML


# ==================== هندلرِ دکمه‌های اینلاین ====================
async def handle_callback(data: str, query, context: ContextTypes.DEFAULT_TYPE, uid: int | None) -> None:
    from ..handlers.common import is_admin, safe_edit

    if not is_admin(uid):
        await query.answer("⛔️ این بخش فقط برای ادمینه.", show_alert=True)
        return

    if data in ("npz:root", "npz:ads:root"):
        context.user_data.pop("npz_awaiting", None)
        text, markup, pm = ads_root_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:toggle":
        cur = db.get_bool("ads_module_enabled", False)
        db.set_bool("ads_module_enabled", not cur)
        text, markup, pm = ads_root_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:addbtn":
        context.user_data["npz_awaiting"] = "ads_add_name"
        context.user_data.pop("npz_ads_edit_id", None)
        await safe_edit(
            query,
            "➕ اسمِ دکمه رو بفرست (مثلاً <code>کانال اصلی</code>).",
            kb.back_only("npz:ads:root"),
            ParseMode.HTML,
        )
        return

    if data.startswith("npz:ads:editbtn:"):
        btn_id = int(data.rsplit(":", 1)[1])
        context.user_data["npz_awaiting"] = "ads_add_name"
        context.user_data["npz_ads_edit_id"] = btn_id
        await safe_edit(
            query,
            "✏️ اسمِ جدیدِ دکمه رو بفرست.",
            kb.back_only("npz:ads:list"),
            ParseMode.HTML,
        )
        return

    if data.startswith("npz:ads:delbtn:"):
        btn_id = int(data.rsplit(":", 1)[1])
        db.delete_ads_button(btn_id)
        text, markup, pm = ads_buttons_list_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:list":
        text, markup, pm = ads_buttons_list_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:caption":
        context.user_data["npz_awaiting"] = "ads_edit_caption"
        await safe_edit(
            query,
            "✍️ متنِ جدیدِ کپشن رو بفرست (تگ‌های HTML مثلِ &lt;b&gt; مجازن).",
            kb.back_only("npz:ads:root"),
            ParseMode.HTML,
        )
        return

    if data == "npz:ads:schedule":
        text, markup, pm = ads_schedule_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:schedule:add":
        context.user_data["npz_awaiting"] = "ads_schedule_add"
        await safe_edit(
            query,
            "⏱ زمانِ جدید رو به فرمِ 24 ساعته بفرست (مثلاً <code>20:00</code>).",
            kb.back_only("npz:ads:schedule"),
            ParseMode.HTML,
        )
        return

    if data.startswith("npz:ads:schedule:del:"):
        t = data.rsplit(":", 1)[1]
        db.remove_ads_schedule(t)
        text, markup, pm = ads_schedule_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:targets":
        text, markup, pm = ads_targets_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:targets:add":
        context.user_data["npz_awaiting"] = "ads_target_add_name"
        await safe_edit(
            query,
            "➕ یک اسمِ دلخواه برای این کانالِ مقصد بفرست (اختیاریه؛ برای ردشدن، فقط یک خط تیره «-» بفرست).",
            kb.back_only("npz:ads:targets"),
            ParseMode.HTML,
        )
        return

    if data.startswith("npz:ads:targets:del:"):
        target_id = int(data.rsplit(":", 1)[1])
        db.remove_ads_target(target_id)
        text, markup, pm = ads_targets_content()
        await safe_edit(query, text, markup, pm)
        return

    if data == "npz:ads:publishnow":
        targets = db.list_ads_targets()
        if not targets:
            await query.answer("⛔️ اول حداقل یک کانالِ مقصد اضافه کن.", show_alert=True)
            return
        if not db.list_ads_buttons():
            await query.answer("⛔️ اول حداقل یک دکمه اضافه کن.", show_alert=True)
            return
        await query.answer("⏳ در حالِ ارسال...")
        ok = await _ads.publish_now(context.bot)
        await context.bot.send_message(
            chat_id=uid,
            text="✅ تبلیغ به همه‌ی کانال‌های مقصد ارسال شد." if ok else "⚠️ ارسال به بعضی/همه‌ی کانال‌ها با خطا مواجه شد؛ لاگ رو چک کن.",
        )
        return


# ==================== ورودیِ متنی (زمان جدید / اسم و آیدیِ کانال) ====================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    اگه پیامِ متنیِ فعلی مربوط به یکی از ورودی‌های در انتظارِ این ماژول باشه،
    پردازشش می‌کنه و True برمی‌گردونه (تا هندلرِ اصلی دیگه روش کاری نکنه).
    در غیرِ این صورت هیچ کاری نمی‌کنه و False برمی‌گردونه.
    """
    awaiting = context.user_data.get("npz_awaiting")
    if not awaiting:
        return False

    from ..handlers.common import is_admin
    uid = update.effective_user.id if update.effective_user else None
    if not is_admin(uid):
        return False

    text = (update.message.text or "").strip()

    if awaiting == "ads_add_name":
        if not text:
            await update.message.reply_text("⛔️ اسم نمی‌تونه خالی باشه.")
            return True
        context.user_data["npz_ads_name"] = text[:64]
        context.user_data["npz_awaiting"] = "ads_add_url"
        await update.message.reply_text("🔗 حالا لینکِ کانال/گروه رو بفرست (باید با http:// یا https:// یا t.me/ شروع بشه).")
        return True

    if awaiting == "ads_add_url":
        import re
        if not re.match(r"^(https?://|t\.me/)", text, re.IGNORECASE):
            await update.message.reply_text("⛔️ لینکِ نامعتبر. باید با http(s):// یا t.me/ شروع بشه.")
            return True
        url = text if text.startswith("http") else f"https://{text}"
        name = context.user_data.pop("npz_ads_name", "کانال")
        edit_id = context.user_data.pop("npz_ads_edit_id", None)
        context.user_data.pop("npz_awaiting", None)
        if edit_id:
            db.update_ads_button(edit_id, name, url)
            msg = f"✅ دکمه‌ی «{name}» ویرایش شد."
        else:
            db.add_ads_button(name, url)
            msg = f"✅ دکمه‌ی «{name}» اضافه شد."
        text_, markup, pm = ads_buttons_list_content()
        await update.message.reply_text(f"{msg}\n\n{text_}", reply_markup=markup, parse_mode=pm)
        return True

    if awaiting == "ads_edit_caption":
        if not text:
            await update.message.reply_text("⛔️ کپشن نمی‌تونه خالی باشه.")
            return True
        db.set_setting("ads_caption_text", text)
        context.user_data.pop("npz_awaiting", None)
        text_, markup, pm = ads_root_content()
        await update.message.reply_text(f"✅ کپشن به‌روزرسانی شد.\n\n{text_}", reply_markup=markup, parse_mode=pm)
        return True

    if awaiting == "ads_schedule_add":
        import re
        if not re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", text):
            await update.message.reply_text("⛔️ فرمتِ نامعتبر. مثال: 20:00")
            return True
        added = db.add_ads_schedule(text)
        context.user_data.pop("npz_awaiting", None)
        msg = f"✅ زمانِ {text} اضافه شد." if added else "این زمان از قبل ثبت شده."
        text_, markup, pm = ads_schedule_content()
        await update.message.reply_text(f"{msg}\n\n{text_}", reply_markup=markup, parse_mode=pm)
        return True

    if awaiting == "ads_target_add_name":
        name = "" if text == "-" else text[:64]
        context.user_data["npz_ads_target_name"] = name
        context.user_data["npz_awaiting"] = "ads_target_add_chat"
        await update.message.reply_text(
            "🎯 حالا آیدیِ عددیِ کانالِ مقصد رو بفرست (مثلاً <code>-1001234567890</code>).\n"
            "ربات باید ادمینِ اون کانال باشه.",
            parse_mode=ParseMode.HTML,
        )
        return True

    if awaiting == "ads_target_add_chat":
        try:
            chat_id_int = int(text)
        except ValueError:
            await update.message.reply_text("⛔️ باید یک عددِ صحیح باشه (آیدیِ چت).")
            return True
        name = context.user_data.pop("npz_ads_target_name", "")
        context.user_data.pop("npz_awaiting", None)
        added = db.add_ads_target(str(chat_id_int), name)
        msg = "✅ کانالِ مقصد اضافه شد." if added else "⛔️ این کانال از قبل توی لیست هست."
        text_, markup, pm = ads_targets_content()
        await update.message.reply_text(f"{msg}\n\n{text_}", reply_markup=markup, parse_mode=pm)
        return True

    return False
