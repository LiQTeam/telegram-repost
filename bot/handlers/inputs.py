from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import keyboards as kb
from ..ad_filter import (
    analyze as ad_analyze,
    classify_async as ad_classify_async,
    parse_keywords as ad_parse_keywords,
    parse_extensions as ad_parse_extensions,
    DEFAULT_KEYWORDS as AD_DEFAULT_KEYWORDS,
)
from ..database import db
from ..utils import extract_username, extract_chat_id, clamp
from ..formatter import ensure_rtl_lines
from .common import authorized_only, is_admin, scope_owner

from ..resource_monitor import ResourceMonitor
from ..backup_manager import BackupManager
from ..public_report_channel import PublicReportChannel

log = logging.getLogger("repost_bot.inputs")


def _user_keyboard(uid: int | None):
    """کیبورد مناسب بر اساس نوع کاربر برمی‌گردونه (ادمین کامل، کاربر مجاز با دسترسی‌های فیلترشده)."""
    if is_admin(uid):
        return kb.main_reply_keyboard(is_admin=True)
    u = db.get_user_by_telegram_id(uid) if uid else None
    if u:
        perms = db.get_permissions(u["id"])
        return kb.main_reply_keyboard(is_admin=False, permissions=perms)
    return kb.main_reply_keyboard(is_admin=False)

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# ساعتِ ۱۲ساعته برای ورودیِ زمانِ بکاپ (۱ تا ۱۲)؛ بعدش کاربر AM/PM رو با دکمه انتخاب می‌کنه.
TIME_12H_RE = re.compile(r"^(0?[1-9]|1[0-2]):([0-5]\d)$")


@authorized_only
async def text_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return

    uid = update.effective_user.id if update.effective_user else None

    # تأیید بازیابی بکاپ (چون هندلر عمومی متن، پیش از هندلر «تایید» اجرا می‌شود،
    # این حالت را مستقیماً به تابع مربوطه واگذار می‌کنیم تا نادیده گرفته نشود).
    if awaiting == "backup_restore_confirm":
        await backup_restore_confirm(update, context)
        return

    # حالت‌هایی که همه‌ی کاربران مجاز (غیرادمین) مجاز به ورود در اون‌ها هستن
    _owner_allowed_states = awaiting.startswith(("pp_caption:", "pp_photo:", "usr_", "myapp_"))
    # حالت‌هایی که بر اساس دسترسی کاربر مجاز هستن
    if not _owner_allowed_states and not is_admin(uid):
        from .common import has_perm
        if awaiting.startswith("src_") and has_perm(uid, "src"):
            _owner_allowed_states = True
        elif awaiting.startswith("dst_") and has_perm(uid, "dst"):
            _owner_allowed_states = True
        elif awaiting.startswith(("wm_text:", "wm_fontsize:", "wm_margin:", "wm_opacity:", "wm_color:")) and has_perm(uid, "wm"):
            _owner_allowed_states = True
        elif awaiting.startswith("footer_") and has_perm(uid, "footer"):
            _owner_allowed_states = True
        elif awaiting.startswith("fmt_") and has_perm(uid, "format"):
            _owner_allowed_states = True
        elif awaiting.startswith("adf_") and has_perm(uid, "adfilter"):
            _owner_allowed_states = True
        elif awaiting.startswith("ai_") and has_perm(uid, "ai"):
            _owner_allowed_states = True
    if not _owner_allowed_states and not is_admin(uid):
        return

    text = (update.message.text or "").strip()
    context.user_data.pop("awaiting", None)

    # ==================== افزودن کانال مبدأ ====================
    if awaiting == "src_add_name":
        name = "" if text in (".", "-", "رد", "skip") else text[:80]
        context.user_data["new_src_name"] = name
        context.user_data["awaiting"] = "src_add_username"
        await update.message.reply_text(
            "یوزرنیم یا لینک کانال مبدأ رو بفرست (مثلا @channelname یا https://t.me/channelname).\n"
            "کانال باید پابلیک باشه.",
            reply_markup=kb.cancel_input_menu(),
        )
        return

    if awaiting == "src_add_username":
        username = extract_username(text)
        name = context.user_data.pop("new_src_name", "")
        if not username:
            await update.message.reply_text("❌ ورودی نامعتبره. دوباره از منو تلاش کن.")
            return
        _owner_uid = None
        if not is_admin(uid):
            _u = db.get_user_by_telegram_id(uid) if uid else None
            _owner_uid = _u["id"] if _u else None
        ok = db.add_channel(username, title=name, owner_user_id=_owner_uid)
        if ok:
            ch_row = next((c for c in db.list_channels() if c["username"] == username.lower()), None)
            cid = ch_row["id"] if ch_row else None
            if cid:
                try:
                    from ..scraper import fetch_latest_post_id
                    baseline_id = await fetch_latest_post_id(username)
                    if baseline_id:
                        db.update_last_post(cid, baseline_id)
                except Exception:
                    log.warning("پایه‌گذاریِ last_post_id برای @%s ناموفق بود؛ روی 0 می‌مونه.", username)
            await update.message.reply_text(
                f"✅ کانال @{username}{f' ({name})' if name else ''} اضافه شد.\n\n"
                "حالا این تنظیمات رو برای همین کانال مشخص کن (هر موقع هم می‌تونی از همینجا "
                "عوضشون کنی):\n"
                "🛡 آیا پست‌هاش قبل از ارسال باید تایید/ویرایش بشن؟\n"
                "🚀 حالت ارسال: زمان‌بندی هفت‌گانه / لحظه‌ای / بازه‌ای؟\n"
                "🎯 و یادت نره حداقل یک کانال مقصد هم بهش وصل کنی، وگرنه چیزی ارسال نمیشه.",
                reply_markup=kb.source_detail_menu(cid) if cid else kb.sources_menu(_owner_uid),
            )
        else:
            await update.message.reply_text(f"⚠️ کانال @{username} قبلا اضافه شده.", reply_markup=kb.sources_menu(_owner_uid))
        return

    # ==================== افزودن کانال مقصد ====================
    if awaiting == "dst_add_name":
        name = "" if text in (".", "-", "رد", "skip") else text[:80]
        context.user_data["new_dst_name"] = name
        context.user_data["awaiting"] = "dst_add_id"
        await update.message.reply_text(
            "آیدی عددی کانال مقصد (مثلا -1001234567890) یا یوزرنیمش رو بفرست.\n"
            "یادت نره ربات باید توی اون کانال ادمین باشه.",
            reply_markup=kb.cancel_input_menu(),
        )
        return

    if awaiting == "dst_add_id":
        chat_id = extract_chat_id(text)
        name = context.user_data.pop("new_dst_name", "")
        _owner_uid = None
        if not is_admin(uid):
            _u = db.get_user_by_telegram_id(uid) if uid else None
            _owner_uid = _u["id"] if _u else None
        ok = db.add_destination(chat_id, title=name, owner_user_id=_owner_uid)
        if ok:
            await update.message.reply_text(
                f"✅ کانال مقصد <code>{chat_id}</code>{f' ({name})' if name else ''} اضافه شد.\n"
                "حالا از داخل هر کانال مبدأ، با «🎯 کانال‌های مقصدِ این کانال» این مقصد رو بهش وصل کن.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb.destinations_menu(_owner_uid),
            )
        else:
            await update.message.reply_text(
                f"⚠️ کانال مقصد <code>{chat_id}</code> قبلا اضافه شده.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb.destinations_menu(_owner_uid),
            )
        return

    # ==================== ساعت اسلات ====================
    if awaiting.startswith("src_slot_time:"):
        _, cid_s, idx_s = awaiting.split(":")
        cid, idx = int(cid_s), int(idx_s)
        if not TIME_RE.match(text):
            await update.message.reply_text("❌ فرمت درست نیست. ساعت رو مثل 08:00 یا 21:30 بفرست (24 ساعته).")
            return
        db.set_slot_time(cid, idx, text)
        await update.message.reply_text(
            f"✅ ساعت اسلات {idx} به {text} (وقت تهران) تغییر کرد.",
            reply_markup=kb.slot_detail_menu(cid, idx),
        )
        return

    # ==================== واترمارک ====================
    if awaiting.startswith("wm_text:"):
        owner = scope_owner(uid)
        prefix = "wm_" + awaiting.split(":")[1]
        db.setting_set(f"{prefix}_text", text[:60], owner_user_id=owner)
        await update.message.reply_text("✅ متن واترمارک تغییر کرد.", reply_markup=kb.watermark_platform_menu(awaiting.split(":")[1], owner))
        return

    if awaiting.startswith("wm_opacity:"):
        owner = scope_owner(uid)
        plat = awaiting.split(":")[1]
        prefix = "wm_" + plat
        try:
            val = clamp(int(text), 0, 100)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد بین 0 تا 100 بفرستی.")
            return
        db.setting_set(f"{prefix}_bg_opacity", val, owner_user_id=owner)
        await update.message.reply_text("✅ شفافیت بروزرسانی شد.", reply_markup=kb.watermark_platform_menu(plat, owner))
        return

    if awaiting.startswith("wm_fontsize:"):
        owner = scope_owner(uid)
        plat = awaiting.split(":")[1]
        prefix = "wm_" + plat
        try:
            val = clamp(int(text), 10, 120)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد بفرستی.")
            return
        db.setting_set(f"{prefix}_font_size", val, owner_user_id=owner)
        await update.message.reply_text("✅ اندازه‌ی فونت بروزرسانی شد.", reply_markup=kb.watermark_platform_menu(plat, owner))
        return

    if awaiting.startswith("wm_margin:"):
        owner = scope_owner(uid)
        plat = awaiting.split(":")[1]
        prefix = "wm_" + plat
        try:
            val = clamp(int(text), 0, 300)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد بفرستی.")
            return
        db.setting_set(f"{prefix}_margin", val, owner_user_id=owner)
        await update.message.reply_text("✅ فاصله از لبه بروزرسانی شد.", reply_markup=kb.watermark_platform_menu(plat, owner))
        return

    if awaiting.startswith("wm_badgescale:"):
        owner = scope_owner(uid)
        plat = awaiting.split(":")[1]
        prefix = "wm_" + plat
        try:
            val = clamp(int(text), 8, 100)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد بین 8 تا 100 بفرستی.")
            return
        db.setting_set(f"{prefix}_badge_scale", val, owner_user_id=owner)
        await update.message.reply_text("✅ اندازه‌ی نشان بروزرسانی شد.", reply_markup=kb.watermark_platform_menu(plat, owner))
        return

    # ==================== امضای پایان پست ====================
    if awaiting == "footer_handle":
        owner = scope_owner(uid)
        handle = extract_username(text)
        if not handle:
            await update.message.reply_text("❌ ورودی نامعتبره. یوزرنیم رو دوباره بفرست.")
            return
        db.setting_set("footer_channel_handle", handle, owner_user_id=owner)
        await update.message.reply_text(f"✅ یوزرنیم به @{handle} تغییر کرد.", reply_markup=kb.footer_menu(owner))
        return

    if awaiting == "footer_url":
        owner = scope_owner(uid)
        db.setting_set("footer_channel_url", text, owner_user_id=owner)
        await update.message.reply_text("✅ لینک کانال ذخیره شد.", reply_markup=kb.footer_menu(owner))
        return

    if awaiting == "footer_template":
        owner = scope_owner(uid)
        db.setting_set("footer_text_template", text, owner_user_id=owner)
        await update.message.reply_text("✅ قالب امضا بروزرسانی شد.", reply_markup=kb.footer_menu(owner))
        return

    if awaiting == "footer_custom_text":
        owner = scope_owner(uid)
        if text == ".":
            db.setting_set("footer_custom_text", "", owner_user_id=owner)
            await update.message.reply_text("✅ متنِ دلخواهِ امضا پاک شد.", reply_markup=kb.footer_menu(owner))
            return
        custom_html = update.message.text_html or text
        db.setting_set("footer_custom_text", custom_html, owner_user_id=owner)
        await update.message.reply_text(
            "✅ متنِ دلخواهِ امضا ذخیره شد. از این به بعد همین زیرِ پست‌ها اضافه می‌شه.",
            reply_markup=kb.footer_menu(owner),
        )
        return

    # ============ تنظیماتِ اختصاصیِ هر مقصد: امضا + فیلترِ تبلیغات ============
    # (ورودی‌ها با prefixِ dst_ هستن و آیدیِ مقصد در dst_cfg_id ذخیره شده؛
    #  مالکیت از قبل موقعِ بازکردنِ منو چک شده و این تنظیمات per-destination و
    #  کاملاً ایزوله‌ان.)
    if awaiting.startswith(("dst_footer_", "dst_adf_")):
        did = context.user_data.pop("dst_cfg_id", None)
        if not did:
            await update.message.reply_text("⚠️ مقصد مشخص نیست؛ دوباره از منوی همون مقصد تلاش کن.")
            return
        d = db.get_destination(did)
        if not d:
            await update.message.reply_text("⚠️ این کانالِ مقصد دیگه وجود نداره.")
            return

        if awaiting == "dst_footer_handle":
            handle = extract_username(text)
            if not handle:
                await update.message.reply_text("❌ ورودی نامعتبره. یوزرنیم رو دوباره بفرست.")
                context.user_data["dst_cfg_id"] = did
                context.user_data["awaiting"] = awaiting
                return
            db.dest_setting_set(did, "footer_channel_handle", handle)
            await update.message.reply_text(f"✅ هندلِ امضای این مقصد روی @{handle} تنظیم شد.", reply_markup=kb.dest_footer_menu(did))
            return

        if awaiting == "dst_footer_url":
            db.dest_setting_set(did, "footer_channel_url", text)
            await update.message.reply_text("✅ لینکِ امضای این مقصد ذخیره شد.", reply_markup=kb.dest_footer_menu(did))
            return

        if awaiting == "dst_footer_template":
            db.dest_setting_set(did, "footer_text_template", text)
            await update.message.reply_text("✅ قالبِ امضای این مقصد بروزرسانی شد.", reply_markup=kb.dest_footer_menu(did))
            return

        if awaiting == "dst_footer_custom":
            if text == ".":
                db.dest_setting_set(did, "footer_custom_text", "")
                await update.message.reply_text("✅ متنِ دلخواهِ امضای این مقصد پاک شد.", reply_markup=kb.dest_footer_menu(did))
                return
            custom_html = update.message.text_html or text
            db.dest_setting_set(did, "footer_custom_text", custom_html)
            await update.message.reply_text("✅ متنِ دلخواهِ امضای این مقصد ذخیره شد.", reply_markup=kb.dest_footer_menu(did))
            return

        if awaiting == "dst_adf_keywords":
            if text == ".":
                db.dest_setting_set(did, "ad_filter_keywords", "")
                await update.message.reply_text("✅ کلیدواژه‌های این مقصد به پیش‌فرض برگشت.", reply_markup=kb.dest_adfilter_menu(did))
                return
            keywords = [k.strip() for k in text.split(",") if k.strip()]
            if not keywords:
                await update.message.reply_text("❌ حداقل یک کلیدواژه لازمه. دوباره بفرست یا انصراف بزن.")
                context.user_data["dst_cfg_id"] = did
                context.user_data["awaiting"] = awaiting
                return
            db.dest_setting_set(did, "ad_filter_keywords", ", ".join(keywords))
            await update.message.reply_text(f"✅ {len(keywords)} کلیدواژه برای این مقصد ذخیره شد.", reply_markup=kb.dest_adfilter_menu(did))
            return

        if awaiting == "dst_adf_phrases":
            from ..formatter import parse_phrases
            if text.strip() == ".":
                db.dest_setting_set(did, "ad_filter_remove_phrases", "")
                await update.message.reply_text(
                    "✅ لیستِ اختصاصیِ این مقصد خالی شد (لیستِ سراسری اعمال می‌شه).",
                    reply_markup=kb.dest_adfilter_menu(did),
                )
                return
            phrases = parse_phrases(text)
            if not phrases:
                await update.message.reply_text("❌ حداقل یک عبارت لازمه. دوباره بفرست یا انصراف بزن.")
                context.user_data["dst_cfg_id"] = did
                context.user_data["awaiting"] = awaiting
                return
            db.dest_setting_set(did, "ad_filter_remove_phrases", "\n".join(phrases))
            await update.message.reply_text(
                f"✅ {len(phrases)} عبارت برای این مقصد ذخیره شد.",
                reply_markup=kb.dest_adfilter_menu(did),
            )
            return

        _adf_num_keys = {
            "dst_adf_min_mentions": "ad_filter_min_mentions",
            "dst_adf_min_links": "ad_filter_min_links",
            "dst_adf_threshold": "ad_filter_score_threshold",
        }
        if awaiting in _adf_num_keys:
            try:
                val = clamp(int(text), 1, 99)
            except ValueError:
                await update.message.reply_text("❌ باید یک عددِ صحیح بفرستی. دوباره تلاش کن.")
                context.user_data["dst_cfg_id"] = did
                context.user_data["awaiting"] = awaiting
                return
            db.dest_setting_set(did, _adf_num_keys[awaiting], val)
            await update.message.reply_text("✅ ذخیره شد.", reply_markup=kb.dest_adfilter_menu(did))
            return
        return

    # ==================== بازه ارسال ====================
    if awaiting.startswith("src_interval:"):
        cid = int(awaiting.split(":")[1])
        try:
            minutes = clamp(int(text), 1, 1440)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد صحیح (بین ۱ تا ۱۴۴۰) بفرستی. دوباره از دکمه‌ی «✏️ تغییر بازه» تلاش کن.")
            return
        db.set_channel_interval_minutes(cid, minutes)
        ch = db.get_channel(cid)
        await update.message.reply_text(
            f"✅ بازه‌ی ارسال روی هر {minutes} دقیقه تنظیم شد.",
            reply_markup=kb.send_mode_menu(cid) if ch else kb.sources_menu(),
        )
        return

    # ==================== ویرایش کپشن پست در صف تایید ====================
    if awaiting.startswith("pp_caption:"):
        pid = int(awaiting.split(":")[1])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await update.message.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
            return
        new_caption = "" if text == "." else (update.message.text_html or text)
        # ⚠️ باگ: اینجا ensure_rtl_lines صدا زده نمی‌شد، برخلافِ مسیرِ ساختِ کپشنِ
        # اولیه (build_caption_html). نتیجه: کپشنی که ادمین دستی توی صفِ تایید
        # ویرایش می‌کرد، نه علامتِ راست‌چینِ خطوطِ فارسی می‌گرفت و نه نرمال‌سازیِ
        # فاصله‌ی بینِ دو quote روش اعمال می‌شد.
        if new_caption:
            new_caption = ensure_rtl_lines(new_caption)
        db.set_pending_caption(pid, new_caption)
        await update.message.reply_text("✅ کپشن بروزرسانی شد. پیش‌نمایشِ جدید:")
        from ..poster import send_pending_preview
        await send_pending_preview(context.bot, pid)
        return

    # ==================== فیلتر تبلیغات ====================
    if awaiting == "adf_keywords":
        owner = scope_owner(uid)
        keywords = [k.strip() for k in text.split(",") if k.strip()]
        if not keywords:
            await update.message.reply_text("❌ حداقل یک کلیدواژه لازمه. دوباره بفرست یا انصراف بزن.")
            return
        db.setting_set("ad_filter_keywords", ", ".join(keywords), owner_user_id=owner)
        await update.message.reply_text(f"✅ {len(keywords)} کلیدواژه ذخیره شد.", reply_markup=kb.ad_filter_menu(owner))
        return

    if awaiting in ("adf_phrases", "adf_phrases_add"):
        owner = scope_owner(uid)
        from ..formatter import parse_phrases
        if text.strip() == "." and awaiting == "adf_phrases":
            db.setting_set("ad_filter_remove_phrases", "", owner_user_id=owner)
            await update.message.reply_text(
                "✅ لیستِ عبارت‌های حذفی خالی شد؛ دیگه چیزی از متنِ پست‌ها حذف نمی‌شه.",
                reply_markup=kb.ad_filter_menu(owner),
            )
            return
        new_phrases = parse_phrases(text)
        if not new_phrases:
            await update.message.reply_text("❌ حداقل یک عبارت (توی یک خط) لازمه. دوباره بفرست یا انصراف بزن.")
            context.user_data["awaiting"] = awaiting
            return
        if awaiting == "adf_phrases_add":
            existing = parse_phrases(db.setting_get("ad_filter_remove_phrases", "", owner_user_id=owner))
            merged = existing + [p for p in new_phrases if p not in existing]
        else:
            merged = []
            for p in new_phrases:
                if p not in merged:
                    merged.append(p)
        db.setting_set("ad_filter_remove_phrases", "\n".join(merged), owner_user_id=owner)
        preview = "\n".join(f"• {p}" for p in merged[:10])
        if len(merged) > 10:
            preview += f"\n• ... و {len(merged) - 10} مورد دیگه"
        await update.message.reply_text(
            f"✅ {len(merged)} عبارت ذخیره شد. از این به بعد هرجا توی متنِ پست دیده بشن، "
            f"قبل از ارسال پاک می‌شن:\n{preview}",
            reply_markup=kb.ad_filter_menu(owner),
        )
        return

    if awaiting == "adf_min_mentions":
        owner = scope_owner(uid)
        try:
            val = clamp(int(text), 1, 50)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد صحیح بفرستی.")
            return
        db.setting_set("ad_filter_min_mentions", val, owner_user_id=owner)
        await update.message.reply_text("✅ آستانه‌ی منشن بروزرسانی شد.", reply_markup=kb.ad_filter_menu(owner))
        return

    if awaiting == "adf_min_links":
        owner = scope_owner(uid)
        try:
            val = clamp(int(text), 1, 50)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد صحیح بفرستی.")
            return
        db.setting_set("ad_filter_min_links", val, owner_user_id=owner)
        await update.message.reply_text("✅ آستانه‌ی لینک بروزرسانی شد.", reply_markup=kb.ad_filter_menu(owner))
        return

    if awaiting == "adf_threshold":
        owner = scope_owner(uid)
        try:
            val = clamp(int(text), 1, 30)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد صحیح بفرستی.")
            return
        db.setting_set("ad_filter_score_threshold", val, owner_user_id=owner)
        await update.message.reply_text("✅ حساسیتِ فیلتر بروزرسانی شد.", reply_markup=kb.ad_filter_menu(owner))
        return

    if awaiting == "adf_test":
        owner = scope_owner(uid)
        keywords = ad_parse_keywords(db.setting_get("ad_filter_keywords", "", owner_user_id=owner)) or list(AD_DEFAULT_KEYWORDS)
        smart = db.setting_get_bool("ad_filter_smart", True, owner_user_id=owner)
        is_ad, reason, detail = await ad_classify_async(
            text,
            "",
            keywords,
            min_mentions=db.setting_get_int("ad_filter_min_mentions", 3, owner_user_id=owner),
            min_links=db.setting_get_int("ad_filter_min_links", 2, owner_user_id=owner),
            score_threshold=db.setting_get_int("ad_filter_score_threshold", 4, owner_user_id=owner),
            use_llm=smart,
        )
        verdict = "🚩 تبلیغاتی تشخیص داده شد" if is_ad else "✅ تبلیغاتی تشخیص داده نشد"
        llm_line = ""
        if detail.get("llm"):
            llm_line = f"\n🧠 داوریِ هوشِ مصنوعی: {detail['llm']}"
        elif detail.get("borderline"):
            llm_line = "\n🧠 موردِ مرزی بود (کلیدِ هوشِ مصنوعی ست نیست؛ فقط موتورِ قاعده‌محور)."
        await update.message.reply_text(
            f"{verdict}\n\nاطمینان: {detail['score']} از ۱۰۰ (آستانه: {detail['threshold']})"
            f"{llm_line}\n\nدلیل: {reason}",
            reply_markup=kb.ad_filter_menu(owner),
        )
        return

    if awaiting == "adf_file_ext":
        owner = scope_owner(uid)
        extensions = ad_parse_extensions(text)
        if not extensions:
            await update.message.reply_text("❌ حداقل یک پسوند لازمه (مثلاً apk). دوباره بفرست یا انصراف بزن.")
            return
        db.setting_set("file_filter_extensions", ", ".join(extensions), owner_user_id=owner)
        await update.message.reply_text(f"✅ {len(extensions)} پسوند ذخیره شد.", reply_markup=kb.ad_filter_menu(owner))
        return

    # ==================== قالب‌بندی متن ====================
    if awaiting == "fmt_maxlen":
        owner = scope_owner(uid)
        try:
            val = clamp(int(text), 50, 1024)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد بفرستی.")
            return
        db.setting_set("max_caption_length", val, owner_user_id=owner)
        await update.message.reply_text("✅ حداکثر طول کپشن بروزرسانی شد.", reply_markup=kb.format_menu(owner))
        return

    if awaiting == "fmt_minwords":
        owner = scope_owner(uid)
        try:
            val = clamp(int(text), 1, 50)
        except ValueError:
            await update.message.reply_text("❌ باید یه عدد صحیح بفرستی.")
            return
        db.setting_set("min_content_words", val, owner_user_id=owner)
        await update.message.reply_text("✅ حداقل تعداد کلمه بروزرسانی شد.", reply_markup=kb.format_menu(owner))
        return

    # ==================== مدیریت کاربران ====================
    if awaiting == "usr_name":
        context.user_data["usr_draft"] = {"name": text[:80]}
        context.user_data["awaiting"] = "usr_tid"
        await update.message.reply_text(
            "آیدی عددی تلگرام کاربر رو بفرست (از @userinfobot بگیر):",
            reply_markup=kb.cancel_input_menu(),
        )
        return

    if awaiting == "usr_tid":
        try:
            tid = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد. دوباره بفرست:")
            context.user_data["awaiting"] = "usr_tid"
            return
        context.user_data.setdefault("usr_draft", {})["telegram_id"] = tid
        context.user_data["awaiting"] = "usr_approval_new"
        await update.message.reply_text(
            f"آیدی تلگرام کاربر ثبت شد: <code>{tid}</code>\n\n"
            "الان آیدی کانال/گروهِ تایید اختصاصی رو بفرست.\n"
            "اگه می‌خوای پیام‌های تایید مستقیم به چت خصوصی کاربر بره، "
            "همون آیدی تلگرام (<code>⏭ رد کردن</code>) رو بزن تا خودکار ست بشه.",
            reply_markup=kb.skip_input_menu(),
            parse_mode="HTML",
        )
        return

    if awaiting == "usr_approval_new":
        d = context.user_data.pop("usr_draft", {})
        # اگه کاربر skip کرد، approval_chat_id = telegram_id (چت خصوصی)
        if text in ("⏭ رد کردن", "skip", ".", "-"):
            approval_id = d.get("telegram_id")
        else:
            try:
                approval_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("❌ فقط عدد (یا «⏭ رد کردن» برای چت خصوصی). دوباره بفرست:")
                context.user_data["usr_draft"] = d
                context.user_data["awaiting"] = "usr_approval_new"
                return
        if not approval_id:
            await update.message.reply_text("❌ آیدی تلگرام کاربر تنظیم نشده. دوباره از مرحله‌ی اول شروع کن.")
            return
        db.add_user(d.get("name", "بی‌نام"), d.get("telegram_id"), approval_id)
        await update.message.reply_text(
            f"✅ کاربر «{d.get('name', 'بی‌نام')}» اضافه شد.\n"
            f"کانال تایید: <code>{approval_id}</code>\n\n"
            "⚠️ یادآوری: کاربر باید یک بار ربات رو /start کنه تا ربات بتونه پیام بفرسته.",
            parse_mode="HTML",
            reply_markup=_user_keyboard(uid),
        )
        return

    if awaiting == "usr_approval":
        try:
            approval_id = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد. دوباره بفرست:")
            context.user_data["awaiting"] = "usr_approval"
            return
        uid_ = context.user_data.pop("usr_edit_id", None)
        if uid_:
            db.set_user_approval_chat(uid_, approval_id)
        await update.message.reply_text("✅ کانال تایید به‌روزرسانی شد.")
        return

    # ==================== کانال تایید من ====================
    if awaiting == "myapp_approval":
        try:
            approval_id = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد. دوباره بفرست:")
            context.user_data["awaiting"] = "myapp_approval"
            return
        my_id = context.user_data.pop("myapp_edit_id", None)
        current = db.get_user_by_telegram_id(uid) if uid else None
        if not my_id or not current or current["id"] != my_id:
            await update.message.reply_text("❌ خطا در تشخیصِ کاربر؛ دوباره از منو امتحان کن.")
            return
        db.set_user_approval_chat(my_id, approval_id)
        await update.message.reply_text(
            "✅ کانال تایید شما به‌روزرسانی شد. از این به بعد پست‌های در انتظارِ "
            "تایید و نوتیف‌های کانال‌های شما به همین‌جا ارسال میشه.\n"
            "یادت نباشه ربات باید توی اون کانال/گروه ادمین باشه."
        )
        return

    if awaiting == "usr_tid_edit":
        try:
            tid = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد. دوباره بفرست:")
            context.user_data["awaiting"] = "usr_tid_edit"
            return
        uid_ = context.user_data.pop("usr_edit_id", None)
        if uid_:
            db.set_user_telegram_id(uid_, tid)
        await update.message.reply_text("✅ آیدی تلگرام کاربر به‌روزرسانی شد.")
        return

    # ==================== ورودی‌های جدید برای قابلیت‌های ۱۰ گانه ====================
    if awaiting == "backup_time":
        m = TIME_12H_RE.match(text.strip())
        if not m:
            await update.message.reply_text(
                "❌ فرمت ساعت نادرست. ساعت رو به فرمت ۱۲ ساعته وارد کن (بین 1:00 تا 12:59)، مثلاً 03:00:"
            )
            return
        hour_12, minute = int(m.group(1)), int(m.group(2))
        await update.message.reply_text(
            f"ساعت <b>{hour_12:02d}:{minute:02d}</b> رو صبح (AM) می‌خوای یا بعدازظهر/شب (PM)؟",
            reply_markup=kb.backup_ampm_menu(hour_12, minute),
            parse_mode=ParseMode.HTML,
        )
        return

    if awaiting == "backup_chat":
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی عددی) وارد کنید.")
            return
        settings = BackupManager.get_settings()
        settings["chat_id"] = chat_id
        BackupManager.save_settings(settings)
        await update.message.reply_text("✅ کانال بکاپ ذخیره شد.", reply_markup=kb.backup_menu())
        return

    if awaiting == "backup_password_set":
        pwd = text.strip()
        if len(pwd) < 6:
            await update.message.reply_text("❌ رمز باید حداقل ۶ کاراکتر باشد. دوباره وارد کنید:")
            return
        from ..backup_manager import set_backup_password
        set_backup_password(pwd)
        context.user_data.pop("awaiting", None)
        # پیامِ حاویِ رمز رو حذف می‌کنیم تا توی تاریخچه‌ی چت باقی نمونه.
        try:
            await update.message.delete()
        except Exception:
            pass
        await update.message.reply_text(
            "✅ رمزِ بکاپ ذخیره شد. از این به بعد بکاپ‌های جدید با این رمز محافظت می‌شن و "
            "برایِ بازیابی (حتی روی رباتِ دیگر) همین رمز لازم است.",
            reply_markup=kb.backup_menu(),
        )
        return

    if awaiting == "backup_restore_password":
        pwd = text.strip()
        encrypted = context.user_data.get("backup_data")
        if not encrypted:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text("❌ خطا: داده بکاپ یافت نشد. دوباره فایل را ارسال کنید.", reply_markup=kb.backup_menu())
            return
        try:
            await update.message.delete()
        except Exception:
            pass
        from ..backup_manager import decrypt_data_with_password
        from cryptography.fernet import InvalidToken
        import json as _json
        try:
            decrypted = decrypt_data_with_password(encrypted, pwd)
            data = _json.loads(decrypted.decode("utf-8"))
            if "backup_metadata" not in data:
                raise ValueError("فایل بکاپ معتبر نیست")
        except InvalidToken:
            await update.message.reply_text("❌ رمز اشتباه است. دوباره رمز را وارد کنید یا برای لغو /cancel را بزنید:")
            return
        except Exception as e:
            context.user_data.pop("awaiting", None)
            context.user_data.pop("backup_data", None)
            await update.message.reply_text(f"❌ فایل بکاپ معتبر نیست: {e}", reply_markup=kb.backup_menu())
            return

        context.user_data["backup_password_input"] = pwd
        context.user_data["awaiting"] = "backup_restore_confirm"
        await update.message.reply_text(
            "✅ رمز درست بود.\n\n"
            "⚠️ <b>هشدار برگشت‌ناپذیری</b>\n"
            "بازیابی این بکاپ تمام اطلاعات فعلی ربات را کاملاً بازنویسی می‌کند.\n"
            "بعدِ بازیابی، ربات بلافاصله پستِ قدیمی نمی‌ذاره؛ فقط تنظیمات/کانال‌ها/کاربرها بازیابی می‌شن و "
            "ارسال فقط از اولین پستِ <b>تازه‌ای</b> که از این لحظه به بعد در مبدأ منتشر بشه شروع می‌شه.\n\n"
            "آیا مطمئن هستید؟\n"
            "برای تأیید، کلمه «تایید» را بفرستید.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb.cancel_input_menu(),
        )
        return

    if awaiting == "backup_restore":
        await update.message.reply_text("❌ لطفاً یک فایل بکاپ ارسال کنید (نه متن).", reply_markup=kb.backup_menu())
        return

    if awaiting == "res_cpu":
        try:
            val = clamp(int(text), 1, 100)
        except ValueError:
            await update.message.reply_text("❌ باید عددی بین 1 تا 100 وارد کنید.")
            return
        settings = ResourceMonitor.get_settings()
        settings["cpu_threshold"] = val
        ResourceMonitor.save_settings(settings)
        await update.message.reply_text("✅ آستانه CPU ذخیره شد.", reply_markup=kb.resource_menu())
        return

    if awaiting == "res_ram":
        try:
            val = clamp(int(text), 1, 100)
        except ValueError:
            await update.message.reply_text("❌ باید عددی بین 1 تا 100 وارد کنید.")
            return
        settings = ResourceMonitor.get_settings()
        settings["ram_threshold"] = val
        ResourceMonitor.save_settings(settings)
        await update.message.reply_text("✅ آستانه RAM ذخیره شد.", reply_markup=kb.resource_menu())
        return

    if awaiting == "res_disk":
        try:
            val = clamp(int(text), 1, 100)
        except ValueError:
            await update.message.reply_text("❌ باید عددی بین 1 تا 100 وارد کنید.")
            return
        settings = ResourceMonitor.get_settings()
        settings["disk_threshold"] = val
        ResourceMonitor.save_settings(settings)
        await update.message.reply_text("✅ آستانه دیسک ذخیره شد.", reply_markup=kb.resource_menu())
        return

    if awaiting == "res_chat":
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی عددی) وارد کنید.")
            return
        settings = ResourceMonitor.get_settings()
        settings["notification_chat_id"] = chat_id
        ResourceMonitor.save_settings(settings)
        await update.message.reply_text("✅ کانال اعلان‌های سرور ذخیره شد.", reply_markup=kb.resource_menu())
        return

    if awaiting == "pub_chat":
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی عددی) وارد کنید.")
            return
        PublicReportChannel.set_chat_id(chat_id)
        await update.message.reply_text("✅ کانال عمومی گزارش‌ها ذخیره شد.", reply_markup=kb.public_channel_menu())
        return

    if awaiting == "notif_chat":
        try:
            chat_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی عددی) وارد کنید.")
            return
        from ..notification_manager import NotificationManager
        s = NotificationManager.get_settings()
        s["chat_id"] = chat_id
        NotificationManager.save_settings(s)
        await update.message.reply_text("✅ کانال اختصاصی اعلان‌های ادمین ذخیره شد.", reply_markup=kb.resource_menu())
        return

    if awaiting.startswith("ai_tool_"):
        tool = awaiting.split("_", 2)[2]
        if not text.strip():
            # awaiting قبلاً بالای تابع پاک شده؛ چون هنوز منتظر متنیم، دوباره برش می‌گردونیم
            # تا با «دوباره بفرست» واقعاً بشه دوباره فرستاد، نه این‌که حالت گم بشه.
            context.user_data["awaiting"] = awaiting
            await update.message.reply_text("❌ متن خالیه. دوباره بفرست یا انصراف بزن.", reply_markup=kb.cancel_input_menu())
            return
        await update.message.reply_text("⏳ در حال پردازش با هوش مصنوعی...")
        from ..ai_router import AIRouter
        router = AIRouter()
        try:
            if tool == "translate":
                out = await router.translate_to_persian(text)
            elif tool == "summarize":
                out = await router.summarize(text)
            else:
                out = await router.rewrite(text)
        except Exception as e:
            log.exception("خطا در ابزار مستقلِ هوش مصنوعی: %s", e)
            await update.message.reply_text("❌ خطا در پردازش. دوباره تلاش کن.", reply_markup=kb.ai_services_menu())
            return
        finally:
            await router.close()
        out = (out or "—")[:4000]
        await update.message.reply_text(out, reply_markup=kb.ai_services_menu())
        return

    # ==================== تولید تصویر با هوش مصنوعی ====================
    if awaiting == "ai_image":
        if not text.strip():
            context.user_data["awaiting"] = "ai_image"
            await update.message.reply_text(
                "❌ متن خالیه. توضیح تصویر مورد نظرت رو بفرست یا انصراف بزن.",
                reply_markup=kb.cancel_input_menu(),
            )
            return

        prompt = text.strip()[:1000]
        await update.message.reply_text("⏳ در حال تولید تصویر... (ممکنه تا حدود یک دقیقه طول بکشه)")

        from ..image_router import ImageRouter
        router = ImageRouter()
        image_bytes = None
        try:
            image_bytes = await router.generate_image(prompt)
        except Exception as e:
            log.exception("خطا در تولید تصویر با هوش مصنوعی: %s", e)
        finally:
            await router.close()

        if not image_bytes:
            await update.message.reply_text(
                "❌ متأسفانه در حال حاضر هیچ‌کدوم از سرویس‌های تولید تصویر (Pollinations، DeepAI، "
                "Stable Horde) در دسترس نیستن. کمی بعد دوباره امتحان کن.",
                reply_markup=kb.ai_services_menu(),
            )
            return

        caption = f"🖼 تصویر تولیدشده برای:\n«{prompt[:200]}»"
        try:
            await update.message.reply_photo(
                photo=image_bytes,
                caption=caption[:1024],
                reply_markup=kb.ai_services_menu(),
            )
        except Exception as e:
            log.exception("خطا در ارسال تصویر تولیدشده: %s", e)
            await update.message.reply_text(
                "❌ تصویر تولید شد ولی هنگام ارسالش خطا پیش اومد. دوباره امتحان کن.",
                reply_markup=kb.ai_services_menu(),
            )
        return

    # ==================== چت پیوسته و چندمرحله‌ای با هوش مصنوعی ====================
    if awaiting == "ai_chat":
        if not text.strip():
            context.user_data["awaiting"] = "ai_chat"
            await update.message.reply_text(
                "❌ متن خالیه. یه پیام بفرست یا «پایان چت» رو بزن.",
                reply_markup=kb.ai_chat_menu(),
            )
            return

        history = context.user_data.get("ai_chat_history") or []
        history.append({"role": "user", "content": text})
        # فقط ۲۰ پیام آخر رو نگه می‌داریم تا حجم درخواست زیاد نشه
        history = history[-20:]

        await update.message.reply_text("⏳ در حال تایپ...")
        from ..ai_router import AIRouter
        router = AIRouter()
        try:
            out = await router.chat(history)
        except Exception as e:
            log.exception("خطا در چتِ هوش مصنوعی: %s", e)
            out = "❌ خطا در پردازش. دوباره پیام بده یا «پایان چت» رو بزن."
        finally:
            await router.close()

        history.append({"role": "assistant", "content": out})
        context.user_data["ai_chat_history"] = history[-20:]
        # چت هنوز ادامه داره، پس دوباره منتظر پیام بعدی می‌مونیم
        context.user_data["awaiting"] = "ai_chat"
        context.user_data["nav_back"] = "menu:ai_services"

        out = out[:4000]
        await update.message.reply_text(out, reply_markup=kb.ai_chat_menu())
        return

    if awaiting == "logs_channel":
        try:
            ch_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی کانال) وارد کنید.")
            return
        logs = db.get_system_logs(limit=50, channel_id=ch_id)
        if not logs:
            await update.message.reply_text("📋 هیچ لاگی برای این کانال یافت نشد.", reply_markup=kb.resource_menu())
            return
        lines = ["📋 <b>لاگ‌های کانال</b>\n" + DIVIDER]
        for log_row in logs[:20]:
            lines.append(f"🕒 {log_row['jalali_date']}\n📌 {log_row['event_type']}\n📝 {log_row['message'][:100]}...")
        await update.message.reply_text("\n\n".join(lines), reply_markup=kb.resource_menu(), parse_mode=ParseMode.HTML)
        return

    if awaiting == "logs_destination":
        try:
            dst_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی کانال مقصد) وارد کنید.")
            return
        logs = db.get_system_logs(limit=50, destination_id=dst_id)
        if not logs:
            await update.message.reply_text("📋 هیچ لاگی برای این کانال مقصد یافت نشد.", reply_markup=kb.resource_menu())
            return
        lines = ["📋 <b>لاگ‌های کانال مقصد</b>\n" + DIVIDER]
        for log_row in logs[:20]:
            lines.append(f"🕒 {log_row['jalali_date']}\n📌 {log_row['event_type']}\n📝 {log_row['message'][:100]}...")
        await update.message.reply_text("\n\n".join(lines), reply_markup=kb.resource_menu(), parse_mode=ParseMode.HTML)
        return

    if awaiting == "logs_user":
        try:
            usr_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ باید یک عدد (آیدی کاربر) وارد کنید.")
            return
        logs = db.get_system_logs(limit=50, user_id=usr_id)
        if not logs:
            await update.message.reply_text("📋 هیچ لاگی برای این کاربر یافت نشد.", reply_markup=kb.resource_menu())
            return
        lines = ["📋 <b>لاگ‌های کاربر</b>\n" + DIVIDER]
        for log_row in logs[:20]:
            lines.append(f"🕒 {log_row['jalali_date']}\n📌 {log_row['event_type']}\n📝 {log_row['message'][:100]}...")
        await update.message.reply_text("\n\n".join(lines), reply_markup=kb.resource_menu(), parse_mode=ParseMode.HTML)
        return


@authorized_only
async def photo_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("pp_photo:"):
        return

    pid = int(awaiting.split(":")[1])
    context.user_data.pop("awaiting", None)

    row = db.get_pending_post(pid)
    if not row or row["status"] != "pending":
        await update.message.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
        return

    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("❌ عکس معتبری پیدا نشد. دوباره تلاش کن.")
        return

    tg_file = await photo.get_file()
    raw = bytes(await tg_file.download_as_bytearray())

    from ..poster import process_photo_bytes
    processing_failed = False
    try:
        raw = await process_photo_bytes(raw)
    except Exception as e:
        processing_failed = True
        log.exception("پردازشِ واترمارک/AI روی عکسِ جایگزینِ پستِ %s شکست خورد؛ عکسِ خامِ ادمین "
                      "بدونِ تغییر ذخیره شد: %s", pid, e)

    db.set_pending_override_photo(pid, raw)
    if processing_failed:
        await update.message.reply_text(
            "⚠️ عکس بدونِ واترمارک ذخیره شد چون پردازشِ واترمارک/AI روی این عکس خطا داد "
            "(جزئیات توی لاگ ربات ثبت شد). می‌تونی دوباره امتحان کنی یا همین‌طور تایید کنی."
        )
    else:
        await update.message.reply_text("✅ عکس بروزرسانی شد. پیش‌نمایشِ جدید:")
    from ..poster import send_pending_preview
    await send_pending_preview(context.bot, pid)


@authorized_only
async def video_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافتِ ویدیویی که ادمین به‌جایِ ویدیوی اصلیِ یک پستِ در صفِ تایید فرستاده.
    برخلافِ عکس (که واترمارک روش زده میشه)، این ویدیو دست‌نخورده و عیناً همون
    چیزی که ادمین فرستاده، جایِ ویدیوی اصلی می‌شینه."""
    awaiting = context.user_data.get("awaiting")
    if not awaiting or not awaiting.startswith("pp_video:"):
        return

    pid = int(awaiting.split(":")[1])
    context.user_data.pop("awaiting", None)

    row = db.get_pending_post(pid)
    if not row or row["status"] != "pending":
        await update.message.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
        return

    video = update.message.video
    if not video:
        await update.message.reply_text("❌ ویدیوی معتبری پیدا نشد. دوباره تلاش کن.")
        return

    tg_file = await video.get_file()
    raw = bytes(await tg_file.download_as_bytearray())

    db.set_pending_override_video(pid, raw)
    await update.message.reply_text("✅ ویدیو بروزرسانی شد. پیش‌نمایشِ جدید:")
    from ..poster import send_pending_preview
    await send_pending_preview(context.bot, pid)


@authorized_only
async def document_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if awaiting != "backup_restore":
        return

    doc = update.message.document
    if not doc:
        return

    if not doc.file_name or not doc.file_name.endswith(".backup"):
        await update.message.reply_text("❌ فایل بکاپ باید با پسوند .backup باشد.", reply_markup=kb.backup_menu())
        return

    context.user_data.pop("awaiting", None)

    tg_file = await doc.get_file()
    encrypted = bytes(await tg_file.download_as_bytearray())

    from ..backup_manager import is_password_protected_backup
    if is_password_protected_backup(encrypted):
        # این بکاپ با فرمتِ رمزِ‌عبوری (قابلِ‌جابجایی بینِ توکن‌ها/اکانت‌ها) گرفته
        # شده - قبل از هر چیزی باید رمز از کاربر گرفته بشه، چون بدونِ رمز اصلاً
        # نمی‌شه محتوا رو خوند تا اعتبارش سنجیده بشه.
        context.user_data["backup_data"] = encrypted
        context.user_data["awaiting"] = "backup_restore_password"
        await update.message.reply_text(
            "🔑 این فایل بکاپ با رمزِ عبور محافظت شده. رمز را وارد کنید:",
            reply_markup=kb.cancel_input_menu(),
        )
        return

    # فرمتِ قدیمی (وابسته به BOT_TOKEN) - بررسی صحت فایل بدونِ نیاز به رمز
    try:
        from ..backup_manager import decrypt_data
        decrypted = decrypt_data(encrypted)
        import json
        data = json.loads(decrypted.decode('utf-8'))
        if "backup_metadata" not in data:
            raise ValueError("فایل بکاپ معتبر نیست")
    except Exception as e:
        await update.message.reply_text(f"❌ فایل بکاپ معتبر نیست: {e}", reply_markup=kb.backup_menu())
        return

    # تأیید نهایی
    await update.message.reply_text(
        "⚠️ <b>هشدار برگشت‌ناپذیری</b>\n"
        "بازیابی این بکاپ تمام اطلاعات فعلی ربات را کاملاً بازنویسی می‌کند.\n"
        "بعدِ بازیابی، ربات بلافاصله پستِ قدیمی نمی‌ذاره؛ فقط تنظیمات/کانال‌ها/کاربرها بازیابی می‌شن و "
        "ارسال فقط از اولین پستِ <b>تازه‌ای</b> که از این لحظه به بعد در مبدأ منتشر بشه شروع می‌شه.\n\n"
        "آیا مطمئن هستید؟\n"
        "برای تأیید، کلمه «تایید» را بفرستید.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.cancel_input_menu()
    )
    context.user_data["awaiting"] = "backup_restore_confirm"
    context.user_data["backup_data"] = encrypted


@authorized_only
async def backup_restore_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    if awaiting != "backup_restore_confirm":
        return

    text = (update.message.text or "").strip()
    if text != "تایید":
        context.user_data.pop("awaiting", None)
        context.user_data.pop("backup_data", None)
        context.user_data.pop("backup_password_input", None)
        await update.message.reply_text("❌ عملیات بازیابی لغو شد.", reply_markup=kb.backup_menu())
        return

    encrypted = context.user_data.pop("backup_data", None)
    password = context.user_data.pop("backup_password_input", None)
    context.user_data.pop("awaiting", None)

    if not encrypted:
        await update.message.reply_text("❌ خطا: داده بکاپ یافت نشد.", reply_markup=kb.backup_menu())
        return

    uid = update.effective_user.id if update.effective_user else None
    ok, msg = BackupManager.restore_backup(encrypted, password=password)
    if ok:
        await update.message.reply_text(
            "⏳ بازیابی انجام شد؛ در حال همگام‌سازیِ کانال‌ها تا ربات از پست‌های قدیمی رد بشه و "
            "فقط پست‌های تازه رو در نظر بگیره...",
        )
        try:
            from ..backup_manager import resync_channels_after_restore
            synced_ok, synced_failed = await resync_channels_after_restore()
            resync_note = f"\n🔄 {synced_ok} کانال همگام‌سازی شد"
            if synced_failed:
                resync_note += f" ({synced_failed} کانال ناموفق - بعداً خودش تصحیح می‌شه)"
            resync_note += "."
        except Exception as e:
            log.exception("همگام‌سازیِ کانال‌ها بعدِ بازیابی با خطا مواجه شد: %s", e)
            resync_note = "\n⚠️ همگام‌سازیِ خودکارِ کانال‌ها ناموفق بود؛ ممکنه اولین اجرا چند پستِ قدیمی هم بفرسته."

        await update.message.reply_text(
            "✅ <b>بازیابی با موفقیت انجام شد.</b>\n"
            "تنظیمات/کانال‌ها/مقصدها/کاربرها به حالت زمان تهیه بکاپ برگشت." + resync_note + "\n\n"
            "🚫 ربات هیچ پستِ قدیمی/عقب‌افتاده‌ای نمی‌فرسته؛ فقط از اولین پستِ تازه‌ای که از این لحظه به بعد "
            "در کانال‌های مبدأ منتشر بشه، شروع به ارسال می‌کنه.\n\n"
            "ربات برای اعمال کامل تغییرات ری‌استارت می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=_user_keyboard(uid)
        )
        # ری‌استارت خودکار
        import sys
        sys.exit(0)
    else:
        await update.message.reply_text(f"❌ بازیابی ناموفق بود: {msg}", reply_markup=kb.backup_menu())

async def channel_edit_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    جایگزینِ عکس/ویدیو/کپشنِ یک پستِ در صفِ تایید، وقتی مستقیماً توی خودِ کانالِ
    تایید فرستاده میشه (نه توی چتِ خصوصی با ربات).

    برخلافِ بقیه‌ی هندلرها که با context.user_data (مالِ خودِ کاربر) کار
    می‌کنن، این تابع از context.chat_data استفاده می‌کنه؛ چون یه پستِ کانال
    (channel_post) هیچ from_user ای نداره - از طرفِ خودِ کانال میاد نه یه
    کاربرِ خاص - پس تنها چیزی که می‌تونیم باهاش تشخیص بدیم «این کانال منتظرِ
    چیه» خودِ چت (کانال) هست، نه کاربر. به همین دلیل هم این تابع
    authorized_only نیست: تلگرام خودش تضمین می‌کنه که فقط کسی که توی این
    کانال حق پست کردن داره (ادمینِ کانال) می‌تونه این پیام رو بفرسته؛ سطح
    دسترسیِ داخلِ ربات (pp_edit/owner و...) از قبل، همون لحظه‌ای که دکمه‌ی
    «ویرایش کپشن/تغییر عکس/تغییر ویدیو» زده شده، چک شده بود.

    این مسیر مکمّلِ جریانِ پیامِ خصوصیه (context.user_data["awaiting"]) که در
    handlers/menu.py هم‌زمان تنظیم می‌شه؛ یعنی ادمین می‌تونه یا توی پیامِ
    خصوصی‌ای که ربات برایش فرستاده جواب بده، یا مستقیماً همین‌جا توی خودِ
    کانالِ تایید - هر کدوم زودتر برسه.
    """
    msg = update.channel_post
    if not msg:
        return

    awaiting = context.chat_data.get("awaiting")
    if not awaiting:
        return

    if awaiting.startswith("pp_caption:"):
        pid = int(awaiting.split(":")[1])
        context.chat_data.pop("awaiting", None)
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await msg.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
            return
        text = msg.text_html or msg.caption_html or msg.text or msg.caption or ""
        new_caption = "" if text.strip() == "." else text
        # همون فیکس: نرمال‌سازیِ راست‌چین/فاصله‌ی quote روی متنی که مستقیم توی
        # کانالِ تایید فرستاده می‌شه هم اعمال بشه (قبلاً فقط برای پستِ اسکرِیپ‌شده
        # اعمال می‌شد، نه کپشنِ دستیِ ادمین).
        if new_caption:
            new_caption = ensure_rtl_lines(new_caption)
        db.set_pending_caption(pid, new_caption)
        await msg.reply_text("✅ کپشن بروزرسانی شد. پیش‌نمایشِ جدید:")
        from ..poster import send_pending_preview
        await send_pending_preview(context.bot, pid)
        return

    if awaiting.startswith("pp_photo:"):
        if not msg.photo:
            # چیزِ دیگه‌ای غیر از عکس فرستاده شده؛ منتظر می‌مونیم، کاربر
            # می‌تونه با دکمه‌ی «انصراف» لغوش کنه.
            return
        pid = int(awaiting.split(":")[1])
        context.chat_data.pop("awaiting", None)
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await msg.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
            return

        tg_file = await msg.photo[-1].get_file()
        raw = bytes(await tg_file.download_as_bytearray())

        from ..poster import process_photo_bytes
        processing_failed = False
        try:
            raw = await process_photo_bytes(raw, channel_id=row["channel_id"] if row["channel_id"] else None)
        except Exception as e:
            processing_failed = True
            log.exception("پردازشِ واترمارک/AI روی عکسِ جایگزینِ پستِ %s شکست خورد؛ عکسِ خامِ ادمین "
                          "بدونِ تغییر ذخیره شد: %s", pid, e)

        db.set_pending_override_photo(pid, raw)
        if processing_failed:
            await msg.reply_text(
                "⚠️ عکس بدونِ واترمارک ذخیره شد چون پردازشِ واترمارک/AI روی این عکس خطا داد "
                "(جزئیات توی لاگ ربات ثبت شد). می‌تونی دوباره امتحان کنی یا همین‌طور تایید کنی."
            )
        else:
            await msg.reply_text("✅ عکس بروزرسانی شد. پیش‌نمایشِ جدید:")
        from ..poster import send_pending_preview
        await send_pending_preview(context.bot, pid)
        return

    if awaiting.startswith("pp_video:"):
        if not msg.video:
            return
        pid = int(awaiting.split(":")[1])
        context.chat_data.pop("awaiting", None)
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await msg.reply_text("⚠️ این پست دیگه در دسترس نیست (شاید قبلا تایید/رد شده).")
            return

        tg_file = await msg.video.get_file()
        raw = bytes(await tg_file.download_as_bytearray())

        db.set_pending_override_video(pid, raw)
        await msg.reply_text("✅ ویدیو بروزرسانی شد. پیش‌نمایشِ جدید:")
        from ..poster import send_pending_preview
        await send_pending_preview(context.bot, pid)
        return
