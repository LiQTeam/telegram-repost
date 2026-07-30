from __future__ import annotations

import asyncio
import logging
from html import escape as _esc

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import ad_filter, ad_feedback_report, ai_watermark, cache, concurrency, sr_model, keyboards as kb
from ..database import db, OVERRIDABLE_TOGGLES
from ..formatter import ensure_rtl_lines
from .common import (
    authorized_only, has_perm, is_admin, is_owner, safe_edit, safe_answer,
    is_expired_callback_query_error, scope_owner,
)
from ..jdatetime_utils import now_jalali, format_jalali_datetime

log = logging.getLogger("repost_bot.menu")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

WELCOME = (
    "✨ <b>ربات ری‌پست هوشمند MR LiQ</b>\n"
    f"{DIVIDER}\n"
    "همه‌چیز رو از منوی پایین صفحه مدیریت کن:\n\n"
    "📡 <b>کانال‌های مبدأ</b> — منابعی که ازشون پست می‌گیریم\n"
    "🎯 <b>کانال‌های مقصد</b> — جاهایی که پست ارسال می‌شه\n"
    "🏷 <b>واترمارک</b> — لوگو یا نوشته روی تصاویر\n"
    "✍️ <b>امضای پایان پست</b> — متن یا لینک انتهای هر پست\n"
    "🔠 <b>قالب‌بندی متن</b> — فرمت و طول کپشن\n"
    "🚫 <b>فیلتر تبلیغات</b> — حذف خودکار پست‌های تبلیغاتی\n"
    "🖥 <b>مانیتورینگ سرور</b> — وضعیت منابع و لاگ‌ها\n"
    "📦 <b>بکاپ و بازیابی</b> — پشتیبان‌گیری خودکار\n"
    "🧠 <b>هوش مصنوعی</b> — ترجمه و بازنویسی پست‌ها\n"
    "📢 <b>کانال گزارش‌ها</b> — شفافیت تیمی\n"
    f"{DIVIDER}\n"
    "برای شروع 👇 یکی از گزینه‌های پایین رو انتخاب کن."
)

_PLATFORM_FA = {"tg": "تلگرام", "ig": "اینستاگرام"}


SIGNATURE_LINE = "𝘊 𝘳 𝘦 𝘢 𝘵 𝘦 𝘥   𝘣 𝘺   𝘔 𝘙   𝘓 𝘐 𝘘"


def _stats_text(uid: int | None = None) -> str:
    scoped = uid is not None and not is_admin(uid)
    owner_id = _owner_scope(uid) if scoped else None
    s = db.stats(owner_user_id=owner_id)
    lines = [
        "📊 <b>آمار شما</b>" if scoped else "📊 <b>آمار ربات</b>",
        DIVIDER,
        f"📡 کانال‌های مبدأ: <b>{s['total_channels']}</b> (فعال: {s['active_channels']})",
        f"🎯 کانال‌های مقصد: <b>{s['total_destinations']}</b> (فعال: {s['active_destinations']})",
        DIVIDER,
        f"📨 پست ارسال‌شده امروز: <b>{s['sent_today']}</b>",
        f"🗂 مجموع پست‌های ارسال‌شده: <b>{s['sent_total']}</b>",
    ]
    if not scoped:
        lines.append(f"🚫 پست‌های تبلیغاتیِ فیلترشده: <b>{s['ad_filtered_total']}</b>")
    lines.append(DIVIDER)
    lines.append(f"<i>{SIGNATURE_LINE}</i>")
    return "\n".join(lines)


def _ad_filter_text(owner_user_id: int | None = None) -> str:
    enabled = "🟢 فعال" if db.setting_get_bool("ad_filter_enabled", False, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    action = db.setting_get("ad_filter_action", "skip", owner_user_id=owner_user_id)
    action_fa = "رد کردنِ کامل (ارسال نمیشه)" if action == "skip" else "ارسال برای بررسیِ دستیِ ادمین"
    custom_kw = ad_filter.parse_keywords(db.setting_get("ad_filter_keywords", "", owner_user_id=owner_user_id))
    kw_source = "سفارشی" if custom_kw else "پیش‌فرض"
    kw_count = len(custom_kw) if custom_kw else len(ad_filter.DEFAULT_KEYWORDS)
    filtered_total = db.stats()["ad_filtered_total"]
    file_enabled = "🟢 فعال" if db.setting_get_bool("file_filter_enabled", True, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    custom_ext = ad_filter.parse_extensions(db.setting_get("file_filter_extensions", "", owner_user_id=owner_user_id))
    ext_source = "سفارشی" if custom_ext else "پیش‌فرض"
    ext_list = custom_ext or ad_filter.DEFAULT_BLOCKED_EXTENSIONS
    file_filtered_total = db.stats()["file_filtered_total"]
    from ..formatter import parse_phrases as _parse_phrases
    _phrases = _parse_phrases(db.setting_get("ad_filter_remove_phrases", "", owner_user_id=owner_user_id))
    if _phrases:
        _phrases_preview = "\n".join(f"• <code>{_esc(x)}</code>" for x in _phrases[:10])
        if len(_phrases) > 10:
            _phrases_preview += f"\n• ... و {len(_phrases) - 10} مورد دیگه"
    else:
        _phrases_preview = "<i>(خالی - چیزی حذف نمی‌شه)</i>"
    smart = "🟢 فعال" if db.setting_get_bool("ad_filter_smart", True, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    _smart_channels = db.list_channels() if owner_user_id is None else db.list_channels(owner_user_id=owner_user_id)
    _smart_exempt = sum(
        1 for _ch in _smart_channels
        if db.get_channel_override(_ch["id"], "ad_filter_smart_enabled") is False
    )
    smart_exempt_line = f"↳ هوشمند برای {_smart_exempt} کانالِ مبدأ به‌صورتِ اختصاصی خاموشه.\n" if _smart_exempt else ""
    return (
        "🚫 <b>فیلتر پست‌های تبلیغاتی</b>\n"
        f"{DIVIDER}\n"
        "موتورِ هوشمندِ بافت‌محور: به‌جای اینکه یک کلمه‌ی تنها (مثلِ «VPN»، «کمیسیون» یا "
        "«قیمت») باعثِ ردِ پست شه، کلِ متن خونده می‌شه و فقط وقتی پست تبلیغ حساب "
        "می‌شه که نشانه‌های تبلیغاتی کنارِ هم باشن (سفارشِ تبلیغ، سایت/اپِ شرط‌بندی، "
        "فراخوانِ خرید/ثبت‌نام، کالکشنِ کانال و...). اگر کلیدِ هوشِ مصنوعی ست شده "
        "باشه، این داوریِ انسان‌گونه دیگه فقط برایِ موارد مرزی نیست: روی متنِ کاملِ "
        "همه‌یِ پست‌ها (به‌جز کانفیگ/پروکسیِ خالص) انجام می‌شه و می‌تونه نتیجه‌ی موتورِ "
        "قاعده‌محور رو در هر دو جهت اصلاح کنه.\n"
        f"{DIVIDER}\n"
        f"🔘 وضعیت: {enabled}\n"
        f"🧠 تشخیصِ هوشمند (AI): {smart}\n"
        f"{smart_exempt_line}"
        f"اقدام هنگامِ تشخیص: {action_fa}\n"
        f"کلیدواژه‌ها: {kw_source} ({kw_count} کلمه)\n"
        f"🎚 حساسیتِ کلی: <b>{db.setting_get_int('ad_filter_score_threshold', 4, owner_user_id=owner_user_id)}</b> "
        "(کوچک‌تر = سخت‌گیرتر)\n\n"
        f"📌 تا الان <b>{filtered_total}</b> پست فیلتر شده.\n"
        f"{DIVIDER}\n"
        "🧹 <b>حذفِ عبارت/ایموجی از متنِ پست</b> - هر عبارت یا ایموجی که اینجا تعریف کنی، "
        "هرجا توی متنِ پست دیده بشه قبل از ارسال پاک می‌شه و بقیه‌ی پست عادی می‌ره "
        "(توی همه‌ی حالت‌ها: لحظه‌ای، زمان‌بندی، بازه‌ای و صفِ تایید). خودِ پست حذف نمی‌شه، "
        "فقط اون عبارت از متن برداشته می‌شه.\n"
        f"📝 عبارت‌های فعلی ({len(_phrases)}):\n{_phrases_preview}\n"
        f"{DIVIDER}\n"
        "📦 <b>فیلترِ فایل/اپ</b> - پستی که به‌جایِ عکس/ویدیو یه فایل (سند) پیوست "
        "داره و پسوندِ فایل جزوِ لیستِ زیره (مثلِ APK اپ‌های شرط‌بندی)، بدونِ استثنا "
        "و مستقل از فیلترِ بالا رد می‌شه.\n"
        f"🔘 وضعیت: {file_enabled}\n"
        f"پسوندهای مسدود: {ext_source} ({', '.join(ext_list)})\n"
        f"📌 تا الان <b>{file_filtered_total}</b> پست به‌خاطرِ فایل رد شده."
    )


def _watermark_overview_text() -> str:
    return (
        "🏷 <b>واترمارک تصویر</b>\n"
        f"{DIVIDER}\n"
        "هر پلتفرم (تلگرام/اینستاگرام) تنظیمات کاملاً جدا و مستقل دارد و جدا "
        "فعال/غیرفعال می‌شود. اگر هر دو فعال باشند، هر دو باکس روی عکس زده می‌شوند "
        "(بهتره موقعیتِ هرکدوم رو فرق بذاری تا روی هم نیفتن).\n\n"
        "🧹 «حذف واترمارک قبلی» با هوش مصنوعی، قبل از زدنِ واترمارکِ خودت، سعی می‌کند "
        "لوگو/نوشته‌ی کانال مبدأ را از روی عکس تشخیص و پاک کند.\n"
        "🔎 «بهبود کیفیت تصویر» چون عکس از صفحه‌ی وبِ فشرده‌ی تلگرام گرفته می‌شود، "
        "قبل از واترمارک با یک مدلِ سبکِ AI (روی CPU) تیزتر/بزرگ‌تر می‌شود؛ برای "
        "عکس‌هایی که از قبل به‌اندازه‌ی کافی بزرگ‌اند اعمال نمی‌شود.\n"
        "💾 «کش دانلود» فایل‌های دانلود‌شده را موقتاً در حافظه نگه می‌دارد تا سریع‌تر "
        "و کم‌مصرف‌تر دوباره استفاده شوند."
    )


def _platform_text(plat: str, owner_user_id: int | None = None) -> str:
    from ..watermark import POSITIONS
    prefix = f"wm_{plat}"
    fa = _PLATFORM_FA.get(plat, plat)
    ca = db.setting_get(f"{prefix}_color_a", "#FFFFFF", owner_user_id=owner_user_id)
    pos = db.setting_get(f"{prefix}_position", "bottom_left", owner_user_id=owner_user_id)
    return (
        f"🏷 <b>واترمارک {fa} (نشانِ آماده)</b>\n"
        f"{DIVIDER}\n"
        f"روی هر عکس، نشانِ آماده‌ی {fa} گذاشته می‌شود و آیدیِ زیر دقیقاً داخلِ باکسِ "
        f"کنارِ لوگو نوشته می‌شود:\n"
        f"📝 متن آیدی: <b>{_esc(db.setting_get(f'{prefix}_text', owner_user_id=owner_user_id))}</b>\n"
        f"📍 موقعیت: {POSITIONS.get(pos, pos)}\n"
        f"🎨 رنگ متن آیدی: {_esc(ca)}\n"
        f"🔤 اندازه متن: {db.setting_get(f'{prefix}_font_size', owner_user_id=owner_user_id) or 'خودکار'}\n"
        f"📐 اندازه نشان: {db.setting_get_int(f'{prefix}_badge_scale', 32, owner_user_id=owner_user_id)}% از عرضِ عکس\n"
        f"🌫 شفافیت نشان: {db.setting_get(f'{prefix}_bg_opacity', owner_user_id=owner_user_id) or 100}%\n"
        f"↔️ فاصله از لبه: {db.setting_get(f'{prefix}_margin', owner_user_id=owner_user_id) or 28}px"
    )


def _footer_text(owner_user_id: int | None = None) -> str:
    from ..formatter import strip_html_tags
    mode = db.setting_get("footer_mode", "link", owner_user_id=owner_user_id)
    handle = db.setting_get("footer_channel_handle", owner_user_id=owner_user_id) or "❌ تنظیم نشده"
    if mode == "custom":
        custom = db.setting_get("footer_custom_text", "", owner_user_id=owner_user_id)
        if custom.strip():
            preview = strip_html_tags(custom).strip() or "(فقط فرمت/لینک، بدون متنِ ساده)"
        else:
            preview = "❌ هنوز چیزی ننوشتی"
        if len(preview) > 300:
            preview = preview[:300] + " …"
        return (
            "✍️ <b>امضای پایان پست</b>\n"
            f"{DIVIDER}\n"
            "🗂 حالت: 📝 متنِ کاملاً دلخواه\n\n"
            f"پیش‌نمایشِ متنِ فعلی (بدون فرمت):\n{_esc(preview)}\n\n"
            "خودِ متنِ ذخیره‌شده فرمتش (بولد/لینک/چندخطی) رو حفظ می‌کنه و دقیقاً همون‌طوری "
            "زیرِ هر پست اضافه می‌شه. اگه {link} یا {handle} داخلش گذاشته باشی، با لینکِ "
            "کانال/منشنِ ساده جایگزین می‌شه."
        )
    template = db.setting_get("footer_text_template", "@{handle}", owner_user_id=owner_user_id)
    return (
        "✍️ <b>امضای پایان پست</b>\n"
        f"{DIVIDER}\n"
        "🗂 حالت: 🧩 لینکِ ساده\n"
        f"👤 یوزرنیم: @{_esc(handle)}\n"
        f"🧩 قالب نمایش: <code>{_esc(template)}</code>\n\n"
        "این امضا به‌صورت لینک (نه متن ساده) به انتهای هر پست اضافه می‌شه.\n"
        "اگه دلت می‌خواد یک متنِ کاملاً دلخواه/چندخطی بنویسی، از «🗂 حالت امضا» رو "
        "بزن و برو روی «📝 متنِ کاملاً دلخواه»."
    )


def _format_text(owner_user_id: int | None = None) -> str:
    preserve = "🟢 فعال" if db.setting_get_bool("preserve_formatting", True, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    remove_links = "🟢 فعال" if db.setting_get_bool("remove_source_links", True, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    min_len_on = "🟢 فعال" if db.setting_get_bool("min_content_filter_enabled", True, owner_user_id=owner_user_id) else "🔴 غیرفعال"
    return (
        "🔠 <b>قالب‌بندی متن</b>\n"
        f"{DIVIDER}\n"
        f"حفظ بولد/ایتالیک/زیرخط/لینک: {preserve}\n"
        f"حذف لینک/آدرس‌سایت/شماره‌تلفن/منشنِ کانال مبدأ: {remove_links}\n"
        f"✂️ حداکثر طول کپشن: <b>{db.setting_get_int('max_caption_length', 1024, owner_user_id=owner_user_id)}</b> کاراکتر\n"
        f"{DIVIDER}\n"
        f"رد کردنِ پست‌های خیلی کوتاهِ فقط‌متنی: {min_len_on}\n"
        f"🔢 حداقل تعداد کلمه: <b>{db.setting_get_int('min_content_words', 4, owner_user_id=owner_user_id)}</b>"
    )


_MODE_FA = {"schedule": "⏱ زمان‌بندی هفت‌گانه (ساعتی)", "instant": "⚡️ لحظه‌ای", "interval": "🔁 بازه‌ای"}


def _source_detail_text(ch) -> str:
    cid = ch["id"]
    slots = db.get_slots(cid)
    active_slots = [s for s in slots if s["enabled"] and s["slot_time"]]
    times = "، ".join(s["slot_time"] for s in active_slots) if active_slots else "هیچ‌کدوم فعال نیست"
    dests = db.linked_destination_ids(cid)
    if dests:
        titles = []
        for did in dests:
            d = db.get_destination(did)
            if d:
                titles.append(d["title"] or d["chat_id"])
        dest_text = "، ".join(titles) if titles else "—"
    else:
        dest_text = "⚠️ هنوز هیچ کانال مقصدی وصل نشده"

    mode = (ch["send_mode"] or "schedule")
    mode_text = _MODE_FA.get(mode, mode)
    if mode == "interval":
        mode_text += f" (هر {ch['interval_minutes']} دقیقه)"
    approval_text = "🟢 فعال (پست‌ها اول برای تایید/ویرایش می‌رن پیشِ ادمین)" if ch["approval_required"] else "🔴 غیرفعال (مستقیم ارسال میشه)"
    title_line = f"اسم: <b>{_esc(ch['title'])}</b>\n" if ch["title"] else ""

    return (
        f"📡 <b>@{ch['username']}</b>\n"
        f"{DIVIDER}\n"
        f"{title_line}"
        f"🔘 وضعیت: {'🟢 فعال' if ch['active'] else '⚪️ غیرفعال'}\n"
        f"🚀 حالت ارسال: {mode_text}\n"
        f"🛡 تایید قبل از ارسال: {approval_text}\n"
        f"⏱ ساعت‌های فعال ارسال (تهران، فقط در حالت زمان‌بندی): {_esc(times)}\n"
        f"🎯 کانال(های) مقصد: {_esc(dest_text)}\n"
        f"{DIVIDER}\n"
        f"📌 آخرین پست پردازش‌شده: <code>{ch['last_post_id']}</code>"
    )


def _destination_detail_text(d) -> str:
    linked = db.linked_channels_for_destination(d["id"])
    src_text = "، ".join(f"@{c['username']}" for c in linked) if linked else "هنوز به هیچ کانال مبدأیی وصل نشده"
    return (
        f"🎯 <b>{_esc(d['title'] or d['chat_id'])}</b>\n"
        f"{DIVIDER}\n"
        f"🆔 آیدی/یوزرنیم: <code>{_esc(d['chat_id'])}</code>\n"
        f"🔘 وضعیت: {'🟢 فعال' if d['active'] else '⚪️ غیرفعال'}\n"
        f"📡 کانال‌های مبدأیی که به اینجا می‌فرستن: {_esc(src_text)}\n"
        f"{DIVIDER}\n"
        "💡 ربات باید توی این کانال ادمین باشه (با دسترسی ارسال پیام)."
    )


def _dest_config_text(d) -> str:
    did = d["id"]
    footer_on = db.dest_setting_get_bool(did, "footer_override", False)
    adf_on = db.dest_setting_get_bool(did, "ad_filter_override", False)
    return (
        f"⚙️ <b>تنظیماتِ اختصاصیِ مقصد</b>\n"
        f"🎯 {_esc(d['title'] or d['chat_id'])}\n"
        f"{DIVIDER}\n"
        f"✍️ امضای اختصاصیِ این مقصد: {'🟢 روشن' if footer_on else '🔴 خاموش (از امضای عمومی استفاده می‌شه)'}\n"
        f"🚫 فیلترِ تبلیغاتِ اختصاصیِ این مقصد: {'🟢 روشن' if adf_on else '🔴 خاموش (از فیلترِ عمومی استفاده می‌شه)'}\n"
        f"{DIVIDER}\n"
        "این تنظیمات فقط روی همین کانالِ مقصد اعمال می‌شن و روی بقیه‌ی مقصدها اثری ندارن."
    )


def _dest_footer_text(d) -> str:
    did = d["id"]
    override_on = db.dest_setting_get_bool(did, "footer_override", False)
    mode = db.dest_setting_get(did, "footer_mode", "link")
    handle = db.dest_setting_get(did, "footer_channel_handle", "")
    url = db.dest_setting_get(did, "footer_channel_url", "")
    custom = db.dest_setting_get(did, "footer_custom_text", "")
    lines = [
        "✍️ <b>امضای اختصاصیِ این مقصد</b>",
        f"🎯 {_esc(d['title'] or d['chat_id'])}",
        DIVIDER,
        f"وضعیت: {'🟢 روشن' if override_on else '🔴 خاموش'}",
        f"حالت: {'🔗 لینک' if mode == 'link' else '📝 متنِ دلخواه'}",
        f"هندل: <code>{_esc(handle or '—')}</code>",
        f"لینک: <code>{_esc(url or '—')}</code>",
    ]
    if mode == "custom":
        lines.append(f"متنِ دلخواه: {_esc((custom[:60] + '…') if len(custom) > 60 else (custom or '—'))}")
    if not override_on:
        lines.append(f"{DIVIDER}\n⚠️ تا وقتی «روشن» نشه، این مقصد از امضای عمومی استفاده می‌کنه.")
    return "\n".join(lines)


def _dest_adf_text(d) -> str:
    did = d["id"]
    override_on = db.dest_setting_get_bool(did, "ad_filter_override", False)
    enabled = db.dest_setting_get_bool(did, "ad_filter_enabled", True)
    kw = ad_filter.parse_keywords(db.dest_setting_get(did, "ad_filter_keywords", ""))
    kw_count = len(kw) if kw else len(ad_filter.DEFAULT_KEYWORDS)
    kw_src = "دلخواه" if kw else "پیش‌فرض"
    action = db.dest_setting_get(did, "ad_filter_action", "skip")
    action_txt = "ارسال به صفِ تایید" if action == "review" else "رد کردنِ همین مقصد"
    return (
        f"🚫 <b>فیلترِ تبلیغاتِ اختصاصیِ این مقصد</b>\n"
        f"🎯 {_esc(d['title'] or d['chat_id'])}\n"
        f"{DIVIDER}\n"
        f"وضعیتِ اختصاصی: {'🟢 روشن' if override_on else '🔴 خاموش'}\n"
        f"فیلتر: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
        f"اقدام هنگامِ تشخیصِ تبلیغ: <b>{action_txt}</b>\n"
        f"کلیدواژه‌ها: <b>{kw_count}</b> ({kw_src})\n"
        f"آستانه‌ی منشن: <b>{db.dest_setting_get_int(did, 'ad_filter_min_mentions', 3)}</b> · "
        f"آستانه‌ی لینک: <b>{db.dest_setting_get_int(did, 'ad_filter_min_links', 2)}</b> · "
        f"حساسیت: <b>{db.dest_setting_get_int(did, 'ad_filter_score_threshold', 4)}</b>\n"
        f"{DIVIDER}\n"
        "اگه «روشن» باشه، این مقصد از همین تنظیمات استفاده می‌کنه؛ اگه «خاموش» باشه، "
        "از فیلترِ تبلیغاتِ عمومیِ ادمین استفاده می‌شه."
    )


HELP_TEXT = (
    "ℹ️ <b>راهنمای کامل ربات</b>\n"
    f"{DIVIDER}\n"
    "۱. از «کانال‌های مقصد» یک یا چند کانال که پست‌های ری‌پست‌شده باید توشون بره رو اضافه کن "
    "(ربات باید توی هرکدوم ادمین باشه).\n"
    "۲. از «کانال‌های مبدأ» کانال‌هایی که می‌خوای ازشون پست بگیری رو اضافه کن "
    "(کافیه یوزرنیمشون رو بفرستی، کانال باید پابلیک باشه).\n"
    "۳. روی هر کانال مبدأ بزن و از «🎯 کانال‌های مقصدِ این کانال» انتخاب کن که پست‌هاش به کدوم "
    "مقصد(ها) بره؛ یک مبدأ می‌تونه به چند مقصد بره.\n"
    "۴. از «🚀 حالت ارسال» همون کانال، وقتی «زمان‌بندی هفت‌گانه» انتخابه، دکمه‌ی «✏️ تنظیم "
    "ساعت‌های ارسال» هفت اسلاتِ ساعتی رو نشون می‌ده؛ هرکدوم رو که نمی‌خواد فعال باشه، غیرفعالش "
    "کن. ساعت‌ها به وقت تهران هستن.\n"
    "۵. از «واترمارک تصویر»، تلگرام و اینستاگرام رو جدا از هم شخصی‌سازی کن: متن، موقعیت "
    "(۶ گزینه)، رنگ (تک‌رنگ یا گرادیانی از بین ۱۰ رنگ آماده)، شفافیت، فونت و فاصله.\n"
    "۶. «🧹 حذف واترمارک قبلی» اگه فعال باشه، قبل از زدنِ واترمارکِ خودت، ربات با هوش "
    "مصنوعی سعی می‌کنه واترمارک/لوگوی کانال مبدأ رو از عکس پاک کنه.\n"
    "۷. «💾 کش دانلود» فایل‌های تکراری رو دوباره دانلود نمی‌کنه - سریع‌تر و کم‌مصرف‌تر.\n"
    "۸. ربات به‌صورت خودکار، سرِ هر اسلاتِ فعال، یک پستِ جدید از همون کانال مبدأ رو با فرمت "
    "اصلی (بولد و...) به مقصدهای وصل‌شده ری‌پست می‌کنه.\n"
    "۹. از داخل هر کانال مبدأ، «🚀 حالت ارسال» رو می‌تونی بین سه حالت عوض کنی: "
    "زمان‌بندی هفت‌گانه (پیش‌فرض)، لحظه‌ای یا بازه‌ای (هر چند دقیقه).\n"
    "۱۰. «🛡 تایید قبل از ارسال» رو برای هر کانال مبدأ می‌تونی جدا فعال کنی؛ وقتی فعاله، "
    "پست‌ها (در هر سه حالتِ ارسال) اول برای تو با دکمه‌ی تایید/ویرایش کپشن/تغییر عکس/رد کردن "
    "ارسال میشن و فقط بعد از تاییدت به مقصد می‌رن.\n"
    "۱۱. از «📤 ارسال پست‌های آخر» می‌تونی همون لحظه ۱۰/۲۰/۳۰ پستِ آخرِ یک کانال مبدأ رو بفرستی.\n"
    "۱۲. هر کاربرِ اضافه‌شده (از «👥 مدیریت کاربران») از بخشِ «📥 کانال تایید من» می‌تونه "
    "خودش، بدون نیازِ به دسترسیِ مدیریتِ کاربران، کانال/گروهِ تاییدِ اختصاصیِ خودش رو عوض کنه؛ "
    "ادمینِ سراسری هم از «👥 مدیریت کاربران» → کاربرِ موردنظر → «✏️ تغییر کانال تایید» همین کار "
    "رو براش انجام می‌ده.\n"
    "۱۳. «🖥 مانیتورینگ سرور»: وضعیت لحظه‌ای CPU، RAM، دیسک، تنظیم آستانه‌های هشدار و مشاهده "
    "لاگ‌های کامل با فیلترهای مختلف.\n"
    "۱۴. «📦 بکاپ و بازیابی»: بکاپ‌گیری خودکار روزانه با رمزنگاری، ارسال به کانال دلخواه و "
    "قابلیت بازیابی کامل - دیتابیس، تنظیماتِ .env (ادمین‌ها، کلیدهای API) و فایل‌های الگوی واترمارک - "
    "حتی بعدِ پاک‌شدن و نصبِ دوباره‌ی کاملِ ربات.\n"
    "۱۵. «🧠 هوش مصنوعی»: ترجمه خودکار پست‌ها به فارسی، خلاصه‌سازی و بازنویسی خلاقانه با حفظ محتوا.\n"
    "۱۶. «📢 کانال گزارش‌ها»: ارسال گزارش‌های موفقیت و هشدارهای عدم فعالیت به کانال عمومی تیم.\n\n"
    "هر موقع خواستی یه مقدار متنی/عددی وارد کنی، کافیه فقط پیامت رو بفرستی؛ "
    "دکمه‌ی «❌ انصراف» همیشه دقیقاً یک پله برمی‌گردونه به همون منویی که ازش وارد شدی، "
    "و «🏠 بازگشت به منوی اصلی» هم همیشه در دسترسه."
)


_MAIN_SECTION_KEYS = {
    "stats", "help", "sources", "extsources", "destinations", "watermark", "footer", "format", "adfilter",
    "users", "myapproval", "resources", "backup", "ai_services", "public_channel", "ads_hub", "manual", "customwm",
}

_SECTION_PERM: dict[str, str] = {
    "sources": "src",
    "destinations": "dst",
    "watermark": "wm",
    "footer": "footer",
    "format": "format",
    "adfilter": "adfilter",
    "ai_services": "ai",
    "manual": "manual",
    "customwm": "manual",
}

# اکشن‌های مربوط به هوش‌مصنوعیِ داخلِ منوی واترمارک (حذف واترمارک/بهبود کیفیت/کش) که با
# دسترسیِ "wm" کنترل می‌شن، نه دسترسیِ "ai" (که مخصوصِ منوی جدای «هوش مصنوعی» - ترجمه/بازنویسیه)
_WM_AI_ACTIONS = {"ai:removal_toggle", "ai:quality_toggle", "ai:cache_toggle", "ai:cache_clear", "ai:status"}


def _owner_scope(uid: int | None) -> int | None:
    """برای ادمین None برمی‌گردونه (یعنی بدون فیلتر، همه چیز دیده میشه)؛
    برای کاربرِ مجازِ غیرادمین، آیدیِ داخلیِ خودش رو برمی‌گردونه تا لیست‌های کانال
    مبدأ/مقصد فقط شامل موارد خودش بشه. اگه به هر دلیلی کاربر پیدا نشه، یک آیدیِ
    نامعتبر (-1) برمی‌گردونه تا هیچ چیزی نشون داده نشه (به جای نشون‌دادنِ همه‌چیز)."""
    if is_admin(uid):
        return None
    u = db.get_user_by_telegram_id(uid) if uid else None
    return u["id"] if u else -1


def _settings_owner(uid: int | None) -> int | None:
    """مشابهِ _owner_scope اما برای تنظیماتِ مختصِ کاربر (واترمارک/امضا/قالب‌بندی):
    فقط یک آیدیِ داخلیِ معتبر یا None برمی‌گردونه (هیچ‌وقت -1)."""
    owner = _owner_scope(uid)
    return owner if owner and owner > 0 else None


def _fb_scope_label(uid: int | None) -> str:
    """یک خطِ توضیحی برایِ برگه‌ی اولِ اکسلِ آمارِ فیدبک، که مشخص کنه این گزارش
    مالِ کدوم مالکه - تا هیچ‌وقت با نگاه‌کردن به یک فایل، آمارِ دو کاربر/ادمینِ
    مختلف با هم قاطی به‌نظر نرسه."""
    if is_admin(uid):
        return "🔐 مالکِ این گزارش: ادمین (فقط کانال‌های خودِ ادمین؛ کانال‌های سایرِ کاربران در این فایل نیست)"
    u = db.get_user_by_telegram_id(uid) if uid else None
    name = (u["name"] if u else None) or "این حساب"
    return f"🔐 مالکِ این گزارش: {name} (فقط کانال‌های همین حساب)"


def _own_channel_or_deny(uid: int | None, channel_id: int) -> bool:
    if is_admin(uid):
        return True
    u = db.get_user_by_telegram_id(uid) if uid else None
    ch = db.get_channel(channel_id)
    return bool(u and ch and ch["owner_user_id"] == u["id"])


def _own_destination_or_deny(uid: int | None, destination_id: int) -> bool:
    if is_admin(uid):
        return True
    u = db.get_user_by_telegram_id(uid) if uid else None
    d = db.get_destination(destination_id)
    return bool(u and d and d["owner_user_id"] == u["id"])


def _section_allowed(uid: int | None, key: str) -> bool:
    if is_admin(uid):
        return True
    # کاربر مجاز (غیرادمین) باید اول ثبت‌شده باشه
    if not is_owner(uid):
        return False
    # این بخش‌ها برای همه‌ی کاربران مجاز همیشه قابل دسترسه
    if key in ("myapproval", "stats", "help"):
        return True
    # بقیه‌ی بخش‌ها بر اساس دسترسی‌های تنظیم‌شده توسط ادمین
    perm_key = _SECTION_PERM.get(key)
    if not perm_key:
        return False
    return has_perm(uid, perm_key)


def _pending_post_denial(uid: int | None, row, action: str, chat_id: int | None = None) -> str | None:
    if is_admin(uid):
        return None
    # اعتمادِ مبتنی‌بر «چت»: اگه این کلیک/پیام داخلِ همون چت/کانالِ تاییدی
    # اتفاق افتاده که خودِ این پست براش فرستاده شده، دیگه نیازی به چک کردنِ
    # ثبت‌بودنِ کاربر یا مالکیتِ پست نیست - چون تلگرام از قبل تضمین کرده که
    # فقط اعضا/ادمین‌های همون چت می‌تونن اونجا دکمه بزنن یا پیام بفرستن.
    # این دقیقاً همون منطقیه که channel_edit_input_router هم برای ورودی‌های
    # مستقیمِ کانال استفاده می‌کنه؛ اینجا هم برای خودِ دکمه‌ها اعمال شد تا یه
    # اکانتِ غیرِ«ادمینِ اصلی» که فقط عضوِ همین چتِ تاییده هم بتونه کار کنه.
    if chat_id is not None:
        try:
            from ..poster import _approval_targets
            channel_row = db.get_channel(row["channel_id"]) if row["channel_id"] else None
            targets, _owner_id = _approval_targets(channel_row if channel_row else row["owner_user_id"])
            if chat_id in targets:
                return None
        except Exception as e:
            # اگه _approval_targets به هر دلیل خطا داد، به بررسیِ معمولِ مجوز ادامه می‌دیم
            log.debug("بررسیِ approval_targets برای پستِ %s ناموفق بود (ادامه با بررسیِ عادی): %s", row.get("id"), e)
    from ..database import db as _db
    u = _db.get_user_by_telegram_id(uid) if uid else None
    if not u:
        return "⛔️ دسترسی نداری."
    owns_post = bool(row["owner_user_id"]) and u["id"] == row["owner_user_id"]
    perms = _db.get_permissions(u["id"])
    can_manage_all = perms.get("pp_all", False)
    if owns_post:
        needed = "pp_edit" if action == "edit" else "pp_own"
        if perms.get(needed, True):
            return None
        return "⛔️ این دسترسی برات فعال نیست."
    if can_manage_all:
        # قبلاً کاربرِ دارایِ «تایید/رد همه‌ی پست‌ها» (pp_all) فقط می‌تونست
        # پست‌هایی که مالکش نبود رو approve/reject کنه، ولی ویرایش/AI روشون
        # همیشه رد می‌شد (چون فقط owns_post چک می‌شد). حالا برای ویرایش هم
        # فقط باید pp_edit فعال باشه، نه اینکه حتماً صاحبِ پست باشه.
        if action == "edit" and not perms.get("pp_edit", True):
            return "⛔️ این دسترسی برات فعال نیست."
        return None
    return "⛔️ این پست متعلق به شما نیست."


def _my_approval_text(uid: int | None) -> str:
    u = db.get_user_by_telegram_id(uid) if uid else None
    if not u:
        return (
            "📥 <b>کانال تایید من</b>\n"
            f"{DIVIDER}\n"
            "شما به‌عنوانِ ادمینِ سراسری ثبت نشدی؛ این بخش فقط برای کاربرانِ "
            "اضافه‌شده (غیرادمین) معنی داره."
        )
    pending_count = len(db.get_pending_posts_by_user(u["id"]))
    perms = db.get_permissions(u["id"])
    perm_lines = []
    perm_map = {
        "src": "📡 مدیریت کانال‌های مبدأ",
        "dst": "🎯 مدیریت کانال‌های مقصد",
        "wm": "🏷 واترمارک تصویر",
        "ai": "🧠 هوش مصنوعی",
        "format": "🔠 قالب‌بندی متن",
        "footer": "✍️ امضای پایان پست",
        "pp_own": "✅ تایید پست‌های خودم",
        "pp_edit": "✏️ ویرایش پست‌های خودم",
        "pp_all": "🔎 تایید/رد همه‌ی پست‌ها",
    }
    for k, label in perm_map.items():
        val = perms.get(k, False)
        perm_lines.append(f"{'🟢' if val else '⚫️'} {label}")
    perms_text = "\n".join(perm_lines)
    approval_chat = u["approval_chat_id"] or u["telegram_id"] or "تنظیم نشده"
    return (
        "📥 <b>کانال تایید من</b>\n"
        f"{DIVIDER}\n"
        f"👤 {_esc(u['name'])}\n"
        f"✅ کانال تایید: <code>{approval_chat}</code>\n"
        f"📨 پست‌های در انتظار: <b>{pending_count}</b>\n\n"
        f"<b>دسترسی‌های شما:</b>\n{perms_text}\n\n"
        "همه‌ی پست‌های در انتظارِ تایید به کانال تایید ارسال می‌شن.\n"
        "برای تغییر کانال تایید روی دکمه‌ی زیر بزن 👇"
    )


def _section_content(key: str, uid: int | None = None, page: int = 0):
    if key == "stats":
        return _stats_text(uid), kb.back_to_main(), ParseMode.HTML
    if key == "help":
        return HELP_TEXT, kb.back_to_main(), ParseMode.HTML
    if key == "sources":
        return (
            "📡 <b>کانال‌های مبدأ</b>\n"
            f"{DIVIDER}\n"
            "روی هرکدوم بزن برای مدیریت 👇",
            kb.sources_menu(_owner_scope(uid), page),
            ParseMode.HTML,
        )
    if key == "extsources":
        from .. import config as _cfg
        token_line = (
            f"🔑 توکن: <code>{_esc(_cfg.EXTENSION_API_TOKEN)}</code>\n"
            f"🔌 پورت: <code>{_cfg.EXTENSION_API_PORT}</code>\n"
            if _cfg.EXTENSION_API_ENABLED and _cfg.EXTENSION_API_TOKEN
            else "⚠️ API اکستنشن غیرفعاله. اول EXTENSION_API_ENABLED=true و یک "
                 "EXTENSION_API_TOKEN توی .env بذار و ربات رو ری‌استارت کن.\n"
        )
        return (
            "🧩 <b>منابع اکستنشن (گروه‌های خصوصی)</b>\n"
            f"{DIVIDER}\n"
            "این لیست، گروه/کانال‌هایی هست که اکستنشنِ مرورگر از تب‌های بازِ "
            "تلگرام‌وب گزارش کرده. هرکدوم رو باز کن، فعالش کن و مقصد بهش وصل کن "
            "تا پست‌هاش شروع به رسیدن کنن.\n\n"
            f"{token_line}\n"
            "این توکن رو داخلِ تنظیماتِ اکستنشن (پاپ‌آپ) وارد کن.\n\n"
            "روی هرکدوم بزن برای مدیریت 👇",
            kb.extsources_menu(page),
            ParseMode.HTML,
        )
    if key == "destinations":
        return (
            "🎯 <b>کانال‌های مقصد</b>\n"
            f"{DIVIDER}\n"
            "روی هرکدوم بزن برای مدیریت 👇",
            kb.destinations_menu(_owner_scope(uid), page),
            ParseMode.HTML,
        )
    if key == "watermark":
        owner = _settings_owner(uid)
        return _watermark_overview_text(), kb.watermark_menu(owner), ParseMode.HTML
    if key == "footer":
        owner = _settings_owner(uid)
        return _footer_text(owner), kb.footer_menu(owner), ParseMode.HTML
    if key == "format":
        owner = _settings_owner(uid)
        return _format_text(owner), kb.format_menu(owner), ParseMode.HTML
    if key == "adfilter":
        owner = _settings_owner(uid)
        return _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML
    if key == "users":
        return "👥 <b>مدیریت کاربران</b>", kb.users_menu(), ParseMode.HTML
    if key == "myapproval":
        return _my_approval_text(uid), kb.my_approval_menu(), ParseMode.HTML
    if key == "resources":
        from ..resource_monitor import ResourceMonitor, resource_stats_text
        return resource_stats_text(ResourceMonitor.get_stats()), kb.resource_menu(), ParseMode.HTML
    if key == "backup":
        return (
            "📦 <b>مدیریت بکاپ و بازیابی</b>\n"
            f"{DIVIDER}\n"
            "هر بکاپ شاملِ همه‌چیزه:\n"
            "• کل دیتابیس (کاربرها، ادمین‌ها، کانال‌ها، تنظیمات، لاگ‌ها، صفِ تایید و ...)\n"
            "• تنظیماتِ فایلِ .env (آیدیِ ادمین‌ها، کلیدهای API هوش مصنوعی و تولید تصویر و ...)\n"
            "• فایل‌های الگوی واترمارک\n\n"
            "یعنی حتی اگه ربات کاملاً پاک و از نو نصب شه، با همون توکن می‌تونی این بکاپ رو "
            "بارگذاری کنی و همه‌چیز دقیقاً به همون حالتِ قبل برگرده.",
            kb.backup_menu(),
            ParseMode.HTML,
        )
    if key == "ai_services":
        return "🧠 <b>خدمات هوش مصنوعی</b>", kb.ai_services_menu(), ParseMode.HTML
    if key == "public_channel":
        from ..public_report_channel import PublicReportChannel
        chat_id = PublicReportChannel.get_chat_id()
        return f"📢 <b>کانال عمومی گزارش‌ها</b>\n\nکانال فعلی: {chat_id or 'تنظیم نشده'}", kb.public_channel_menu(), ParseMode.HTML
    if key == "ads_hub":
        from ..auto_poster.menu import root_content as _npz_root_content
        return _npz_root_content()
    if key == "manual":
        from ..manual_poster import root_content as _manual_root_content
        return _manual_root_content(uid)
    if key == "customwm":
        from ..custom_watermark import root_content as _wmc_root_content
        return _wmc_root_content(uid)
    raise KeyError(key)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ادمین‌ها همه چیز رو می‌بینن؛ کاربران مجاز (غیرادمین) فقط بخش‌هایی که دسترسی دارن."""
    context.user_data.clear()
    uid = update.effective_user.id if update.effective_user else None
    if is_admin(uid):
        await update.message.reply_text(
            WELCOME, reply_markup=kb.main_reply_keyboard(is_admin=True), parse_mode=ParseMode.HTML
        )
    elif is_owner(uid):
        u = db.get_user_by_telegram_id(uid)
        perms = db.get_permissions(u["id"]) if u else {}
        name = _esc(u["name"]) if u else "کاربر"
        # اگه approval_chat_id برابر telegram_id یا صفر بود، آیدی چت خصوصی رو ثبت می‌کنیم
        # (در تلگرام، آیدی چت خصوصی = آیدی تلگرام کاربره)
        if u and (not u["approval_chat_id"] or u["approval_chat_id"] == u["telegram_id"]):
            private_chat_id = update.effective_chat.id if update.effective_chat else uid
            if private_chat_id and private_chat_id != u["approval_chat_id"]:
                db.set_user_approval_chat(u["id"], private_chat_id)
                log.info("approval_chat_id کاربر %s به %s به‌روزرسانی شد.", u["name"], private_chat_id)
        welcome_user = (
            f"👋 سلام <b>{name}</b>!\n"
            "به پنل کاربری ربات ری‌پست خوش اومدی.\n"
            "بخش‌هایی که دسترسی داری پایینِ صفحه نشون داده شده 👇"
        )
        await update.message.reply_text(
            welcome_user,
            reply_markup=kb.main_reply_keyboard(is_admin=False, permissions=perms),
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("⛔️ شما دسترسی به این ربات ندارید.")


@authorized_only
async def main_menu_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    key = kb.resolve_main_key(text)
    if not key:
        return
    uid = update.effective_user.id if update.effective_user else None
    if not _section_allowed(uid, key):
        await update.message.reply_text("⛔️ دسترسی این بخش رو نداری.")
        return
    _clear_input_state(context)
    content_text, markup, parse_mode = _section_content(key, uid)
    await update.message.reply_text(content_text, reply_markup=markup, parse_mode=parse_mode)


@authorized_only
async def section_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text.split()[0].lstrip("/").split("@")[0].lower()
    if cmd not in _MAIN_SECTION_KEYS:
        return
    uid = update.effective_user.id if update.effective_user else None
    if not _section_allowed(uid, cmd):
        await update.message.reply_text("⛔️ دسترسی این بخش رو نداری.")
        return
    content_text, markup, parse_mode = _section_content(cmd, uid)
    await update.message.reply_text(content_text, reply_markup=markup, parse_mode=parse_mode)


def _clear_input_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "awaiting", "new_src_name", "new_dst_name", "nav_back", "color_pick", "usr_draft",
        "usr_edit_id", "myapp_edit_id", "ai_chat_history", "backup_data", "backup_password_input",
    ):
        context.user_data.pop(key, None)


def _set_awaiting(context: ContextTypes.DEFAULT_TYPE, awaiting: str, nav_back: str) -> None:
    context.user_data["awaiting"] = awaiting
    context.user_data["nav_back"] = nav_back


@authorized_only
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    uid = update.effective_user.id if update.effective_user else None
    # ⚠️ باگِ مهم (فیکسِ قبلی): قبلاً همین‌جا اول `await query.answer()` صدا زده
    # می‌شد. هر callback_query در تلگرام فقط و فقط یک بار قابلِ answer شدنه؛ در
    # نتیجه همه‌ی answer(..., show_alert=True) هایی که بعداً داخلِ _dispatch صدا
    # زده می‌شدن (پیام‌های «⛔️ فقط ادمین»، «✅ وضعیت تغییر کرد»، «🗑 حذف شد» و ...)
    # با خطای BadRequest شکست می‌خوردن؛ نه پاپ‌آپی نمایش داده می‌شد و نه کاربر
    # می‌فهمید چی شد (فقط ارورِ سراسری لاگ می‌شد). حالا answerِ خالی به انتهای
    # کار منتقل شده تا فقط وقتی هیچ answerی نخورده باشه اجرا بشه.
    #
    # ⚠️ باگِ دوم (این فیکس): اون تغییر فقط answerِ خالیِ انتهایی رو امن کرده
    # بود؛ ده‌ها جای دیگه‌ی این فایل/manual_poster.py/auto_poster/menu.py/
    # custom_watermark.py مستقیماً `await query.answer("...", show_alert=True)`
    # صدا می‌زنن و try/except ندارن. اگه پردازشِ آپدیت کند شده باشه (مثلاً یک
    # کارِ سنگین قبلش) یا کاربر دوبار پشتِ سرِ هم دکمه رو زده باشه، همون
    # BadRequestِ «Query is too old and response timeout expired or query id is
    # invalid» از داخلِ یکی از این answerهای محافظت‌نشده raise می‌شد، از
    # try/finally پایین رد می‌شد و مستقیم به هندلرِ سراسریِ خطا می‌رسید -
    # نتیجه: هم لاگِ پر از تریس‌بکِ تکراری، هم اسپمِ پیامِ «یه خطای غیرمنتظره
    # پیش اومد» توی چتِ/کانالِ کاربر (درحالی‌که خودِ عملیات، مثلاً approve پست،
    # معمولاً از قبل با موفقیت انجام شده بود - فقط پاپ‌آپِ تاییدش نمایش داده
    # نمی‌شد). الان این خطای خاص همین‌جا قورت داده می‌شه و بقیه‌ی خطاها
    # (خطاهای واقعی) طبقِ قبل به هندلرِ سراسری می‌رسن.
    try:
        await _dispatch(data, query, context, uid)
    except BadRequest as e:
        if is_expired_callback_query_error(e):
            log.warning(
                "کالبک‌کوئریِ منقضی/نامعتبر حینِ پردازشِ «%s» (uid=%s) - نادیده گرفته شد: %s",
                data, uid, e,
            )
            return
        raise
    finally:
        await safe_answer(query)


async def _dispatch(data: str, query, context: ContextTypes.DEFAULT_TYPE, uid: int | None = None) -> None:
    # ==================== ماژولِ ایزوله‌ی «تبلیغات» ====================
    # کاملاً جدا از بقیه‌ی این تابع: خودش داخلِ handle_callback چکِ is_admin
    # رو انجام می‌ده، پس نیازی به قاطی‌شدن با زنجیره‌ی مجوزهای زیر نیست.
    if data.startswith("npz:"):
        from ..auto_poster.menu import handle_callback as _npz_handle_callback
        await _npz_handle_callback(data, query, context, uid)
        return

    if data.startswith("manual:"):
        from ..manual_poster import handle_callback as _manual_handle_callback
        await _manual_handle_callback(data, query, context, uid)
        return

    # دکمه‌های بی‌اثرِ ناوبریِ صفحه (نشانگرِ «صفحه i از n» و دکمه‌های لبه‌ی نقطه‌چین)
    # فقط باید callback رو ack کنن و هیچ کاری نکنن. عمداً قبل از زنجیره‌ی مجوزها
    # هست تا برای کاربرانِ غیرادمین هم پیامِ «فقط ادمین» نده.
    if data == "nav:noop":
        return

    if data.startswith("wmc:"):
        # واترمارکِ سفارشی هم بخشی از «ارسالِ دستی» است (انتخابِ واترمارکِ نام‌دار)
        # و هم می‌تونه مستقل استفاده بشه؛ پس دسترسیِ «wm» یا «manual» هردو کافیه.
        # این با نگاشتِ منو (customwm ↔ مجوزِ manual) و صفحه‌ی دسترسی‌ها هماهنگه.
        if not is_admin(uid) and not has_perm(uid, "wm") and not has_perm(uid, "manual"):
            await query.answer("⛔️ این بخش فقط برای ادمینه.", show_alert=True)
            return
        from ..custom_watermark import handle_callback as _wmc_handle_callback
        await _wmc_handle_callback(data, query, context, uid)
        return

    _owner_allowed = data.startswith("pp:")
    if not _owner_allowed and not is_admin(uid):
        # بخش‌هایی که همه‌ی کاربران مجاز (is_owner) می‌تونن استفاده کنن
        if data in ("menu:main", "menu:stats", "menu:help"):
            _granted = is_owner(uid)
        elif data.startswith("src:") or data in ("menu:sources",):
            _granted = has_perm(uid, "src")
        elif data.startswith("dst:") or data in ("menu:destinations",):
            _granted = has_perm(uid, "dst")
        elif data.startswith("wmp:") or data == "menu:watermark" or data == "wm:preview" or data == "menu:customwm":
            _granted = has_perm(uid, "wm")
        elif data.startswith("usr:") or data in ("menu:users", "usr:list"):
            # مدیریتِ کاربرانِ دیگه دیگه یه دسترسیِ قابل‌واگذاری نیست؛ همیشه فقط
            # مخصوصِ ادمین‌های سراسریه (که همین‌جا چون not is_admin(uid) رد شدیم، پس نه).
            _granted = False
        elif data.startswith("myapp:") or data == "menu:myapproval":
            _granted = is_owner(uid)
        elif data in _WM_AI_ACTIONS:
            _granted = has_perm(uid, "wm")
        elif data.startswith("ai:") or data == "menu:ai_services":
            _granted = has_perm(uid, "ai")
        elif data.startswith("aiapi:"):
            _granted = has_perm(uid, "ai")
        elif data.startswith("input:"):
            # دکمه‌های عمومیِ ورودی (رد کردن/انصراف) همیشه برای همه‌ی کاربرانِ مجاز آزادن
            _granted = is_owner(uid)
        elif data.startswith("footer:") or data == "menu:footer":
            _granted = has_perm(uid, "footer")
        elif data.startswith("fmt:") or data == "menu:format":
            _granted = has_perm(uid, "format")
        elif data.startswith("adf:") or data == "menu:adfilter":
            _granted = has_perm(uid, "adfilter")
        else:
            # مانیتورینگِ سرور، بکاپ و کانال گزارشِ عمومی سراسری‌اند و فقط مخصوصِ ادمین می‌مونن
            _granted = False
        if not _granted:
            await query.answer("⛔️ این بخش فقط برای ادمینه.", show_alert=True)
            return

        # برای کاربرانِ غیرادمین، هر عملیاتِ روی یک کانالِ مبدأ/مقصدِ خاص فقط روی
        # کانال/مقصدِ خودشون مجازه (نه کانال‌های ادمین یا کاربرانِ دیگه)
        if data.startswith("src:") and not data.startswith(("src:add", "src:page:")):
            try:
                _cid = int(data.split(":")[2])
            except (IndexError, ValueError):
                _cid = None
            if _cid is None or not _own_channel_or_deny(uid, _cid):
                await query.answer("⛔️ این کانال متعلق به شما نیست.", show_alert=True)
                return
            if data.startswith("src:destmap_toggle:"):
                try:
                    _did = int(data.split(":")[3])
                except (IndexError, ValueError):
                    _did = None
                if _did is None or not _own_destination_or_deny(uid, _did):
                    await query.answer("⛔️ این کانال مقصد متعلق به شما نیست.", show_alert=True)
                    return
        elif data.startswith("dst:") and not data.startswith(("dst:add", "dst:page:")):
            try:
                _did = int(data.split(":")[2])
            except (IndexError, ValueError):
                _did = None
            if _did is None or not _own_destination_or_deny(uid, _did):
                await query.answer("⛔️ این کانال مقصد متعلق به شما نیست.", show_alert=True)
                return

    if data == "menu:main":
        _clear_input_state(context)
        # ⚠️ باگ: قبلاً اینجا فقط safe_edit صدا زده می‌شد که تنها اینلاین‌کیبوردِ
        # همون پیام رو برمی‌داشت. ویرایشِ پیام (edit_message_text/caption) هیچ‌وقت
        # نمی‌تونه کیبوردِ پایینِ صفحه (ReplyKeyboardMarkup) رو دوباره باز کنه -
        # این کیبورد فقط با فرستادنِ یک پیامِ *جدید* که reply_markup داره به
        # کلاینتِ تلگرام تحویل داده/بازآوری می‌شه. برای همین اگه کاربر قبلاً
        # کیبورد رو دستی جمع کرده بود (فلش/شورونِ کنارِ باکسِ پیام)، با زدنِ
        # «بازگشت به منوی اصلی» دکمه‌ها بالا نمی‌اومدن - باید خودش اول دستی
        # بازش می‌کرد و بعد یه دکمه‌ی دیگه می‌زد تا اثر کنه. حالا به‌جایِ
        # ویرایشِ پیامِ قبلی، اول فقط اینلاین‌کیبوردِ همون پیام پاک می‌شه و بعد
        # یک پیامِ جدید با همون کیبوردِ منوی اصلی فرستاده می‌شه تا همون لحظه و
        # بدونِ نیاز به تپِ دستی بالا بیاد.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                log.warning("پاک‌کردنِ اینلاین‌کیبوردِ پیامِ قبلی هنگامِ بازگشت به منو شکست خورد: %s", e)
        if is_admin(uid):
            reply_kb = kb.main_reply_keyboard(is_admin=True)
        else:
            perms = db.get_permissions_by_telegram_id(uid) if uid else {}
            reply_kb = kb.main_reply_keyboard(is_admin=False, permissions=perms)
        chat_id = query.message.chat.id if query.message else query.from_user.id
        await context.bot.send_message(
            chat_id=chat_id,
            text="🏠 منوی اصلی همیشه پایینِ صفحه در دسترسه 👇\nاز اونجا بخشِ موردنظر رو انتخاب کن.",
            reply_markup=reply_kb,
        )
        return

    if data == "wmp:noop":
        await query.answer("هنوز به تعداد کافی رنگ انتخاب نکردی.", show_alert=True)
        return

    if data.startswith("menu:") and data.split(":", 1)[1] in _MAIN_SECTION_KEYS:
        key = data.split(":", 1)[1]
        text, markup, parse_mode = _section_content(key, uid)
        await safe_edit(query, text, markup, parse_mode)
        return

    # ==================== کانال تایید من ====================
    if data == "myapp:edit":
        u = db.get_user_by_telegram_id(uid) if uid else None
        if not u:
            await query.answer(
                "⛔️ شما به‌عنوانِ کاربرِ ثبت‌شده تعریف نشدی؛ این بخش فقط برای "
                "کاربرانِ اضافه‌شده‌ست.",
                show_alert=True,
            )
            return
        context.user_data["myapp_edit_id"] = u["id"]
        _set_awaiting(context, "myapp_approval", "menu:myapproval")
        await safe_edit(
            query,
            "آیدی عددی کانال/گروهِ تاییدِ جدیدِ خودت رو بفرست (مثل -1001234567890):\n"
            "ربات باید داخلِ اون کانال/گروه ادمین باشه.",
            kb.cancel_input_menu(),
        )
        return

    # ==================== منابع (کانال‌های مبدأ) ====================
    if data == "src:add":
        context.user_data.pop("new_src_name", None)
        _set_awaiting(context, "src_add_name", "menu:sources")
        await safe_edit(
            query,
            "اول یه اسم دلخواه برای این کانال مبدأ بفرست (فقط برای اینکه توی لیست راحت‌تر "
            "پیداش کنی - مثلا «کانال خبری X»). اگه نمی‌خوای اسم بذاری، «⏭ رد کردن» رو بزن.",
            kb.skip_input_menu(),
        )
        return

    if data.startswith("src:page:"):
        try:
            _page = int(data.split(":")[2])
        except (IndexError, ValueError):
            _page = 0
        text, markup, parse_mode = _section_content("sources", uid, _page)
        await safe_edit(query, text, markup, parse_mode)
        return

    if data.startswith("src:view:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
            return
        await safe_edit(query, _source_detail_text(ch), kb.source_detail_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:toggle:"):
        cid = int(data.split(":")[2])
        db.toggle_channel(cid)
        await query.answer("✅ وضعیت کانال تغییر کرد.", show_alert=True)
        ch = db.get_channel(cid)
        if ch:
            await safe_edit(query, _source_detail_text(ch), kb.source_detail_menu(cid), ParseMode.HTML)
        else:
            await safe_edit(query, "کانال حذف شد.", kb.sources_menu(_owner_scope(uid)))
        return

    if data.startswith("src:remove_confirm:"):
        cid = int(data.split(":")[2])
        db.remove_channel(cid)
        await query.answer("🗑 کانال حذف شد.", show_alert=True)
        await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
        return

    if data.startswith("src:remove:"):
        cid = int(data.split(":")[2])
        await safe_edit(query, "⚠️ مطمئنی می‌خوای این کانال رو حذف کنی؟", kb.confirm_remove_menu(cid))
        return

    if data.startswith("src:approval_toggle:"):
        cid = int(data.split(":")[2])
        new_val = db.toggle_channel_approval(cid)
        await query.answer(
            "✅ از این به بعد پست‌های این کانال اول برای تایید می‌رن." if new_val
            else "✅ از این به بعد پست‌های این کانال مستقیم ارسال میشن.",
            show_alert=True,
        )
        ch = db.get_channel(cid)
        if ch:
            await safe_edit(query, _source_detail_text(ch), kb.source_detail_menu(cid), ParseMode.HTML)
        return

    # ==================== منابع اکستنشن (گروه‌های خصوصیِ تلگرام‌وب) ====================
    if data.startswith("extsrc:page:"):
        try:
            _page = int(data.split(":")[2])
        except (IndexError, ValueError):
            _page = 0
        text, markup, parse_mode = _section_content("extsources", uid, _page)
        await safe_edit(query, text, markup, parse_mode)
        return

    if data.startswith("extsrc:view:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این منبع دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "🧩 منابع اکستنشن", kb.extsources_menu())
            return
        status = "🟢 فعال" if ch["active"] else "🟡 در انتظار تایید"
        approval = "🛡 قبل از ارسال تایید می‌خواد" if ch["approval_required"] else "⚡️ خودکار (بدون تایید)"
        n_dest = len(db.linked_destination_ids(cid))
        text = (
            f"🧩 <b>{_esc(ch['title'] or ch['ext_peer_ref'])}</b>\n"
            f"{DIVIDER}\n"
            f"وضعیت: {status}\n"
            f"حالتِ ارسال: {approval}\n"
            f"کانال‌های مقصدِ وصل‌شده: {n_dest}\n"
        )
        await safe_edit(query, text, kb.extsource_detail_menu(cid), ParseMode.HTML)
        return

    if data.startswith("extsrc:toggle:"):
        cid = int(data.split(":")[2])
        db.toggle_channel(cid)
        await query.answer("✅ وضعیت منبع تغییر کرد.", show_alert=True)
        await _dispatch("extsrc:view:" + str(cid), query, context, uid)
        return

    if data.startswith("extsrc:approval_toggle:"):
        cid = int(data.split(":")[2])
        new_val = db.toggle_channel_approval(cid)
        await query.answer(
            "✅ از این به بعد پست‌های این منبع اول برای تایید می‌رن." if new_val
            else "✅ از این به بعد پست‌های این منبع مستقیم ارسال میشن.",
            show_alert=True,
        )
        await _dispatch("extsrc:view:" + str(cid), query, context, uid)
        return

    if data.startswith("extsrc:remove:"):
        cid = int(data.split(":")[2])
        await safe_edit(query, "⚠️ مطمئنی می‌خوای این منبع رو حذف کنی؟", kb.confirm_remove_extsource_menu(cid))
        return

    if data.startswith("extsrc:remove_confirm:"):
        cid = int(data.split(":")[2])
        db.remove_channel(cid)
        await query.answer("🗑 منبع حذف شد.", show_alert=True)
        await safe_edit(query, "🧩 منابع اکستنشن", kb.extsources_menu())
        return

    if data.startswith("src:dupmenu:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        await safe_edit(
            query,
            "♻️ <b>فیلترِ محتوای تکراری</b>\n\n"
            "این فیلتر محتوای دریافتی از کانال‌های مبدأ را با پست‌های اخیر مقایسه می‌کند و "
            "در صورتِ تشخیصِ تکرار (متنِ مشابه، لینکِ یکسان یا مدیای یکسان) طبقِ حالتِ "
            "انتخاب‌شده رفتار می‌کند:\n\n"
            "🔴 <b>غیرفعال</b>: تکرار مجاز است.\n"
            "🗑 <b>حذف خودکار</b>: پستِ تکراری خودکار رد و در لاگ ثبت می‌شود.\n"
            "🛡 <b>ارسال به تایید</b>: پستِ تکراری برای تصمیمِ دستی به صفِ تایید می‌رود.",
            kb.duplicate_mode_menu(cid),
            ParseMode.HTML,
        )
        return

    if data.startswith("src:dupset:"):
        parts = data.split(":")
        cid = int(parts[2])
        new_mode = parts[3]
        from ..duplicate_filter import DuplicateFilter
        DuplicateFilter.set_mode(cid, new_mode)
        await query.answer("✅ حالتِ فیلترِ تکراری تغییر کرد.", show_alert=True)
        await safe_edit(
            query,
            "♻️ <b>فیلترِ محتوای تکراری</b>\n\nحالتِ فعلی ذخیره شد. می‌تونی تغییرش بدی:",
            kb.duplicate_mode_menu(cid),
            ParseMode.HTML,
        )
        return

    if data.startswith("src:mode_menu:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        text = (
            f"🚀 <b>حالت ارسال @{ch['username']}</b>\n\n"
            "دقیقا یکی از این سه حالت می‌تونه فعال باشه؛ با انتخاب یکی، دوتای دیگه "
            "خودکار غیرفعال میشن:\n\n"
            "⏱ <b>زمان‌بندی هفت‌گانه</b>: طبق ساعت‌های تنظیم‌شده (پیش‌فرض).\n"
            "⚡️ <b>لحظه‌ای</b>: به محض اینکه پست جدید توی کانال مبدأ منتشر شد، همون لحظه "
            "پردازش میشه. اگه «تایید قبل از ارسال» فعال باشه، ابتدا به کانالِ تایید می‌ره.\n"
            "🔁 <b>بازه‌ای</b>: هر چند دقیقه که تو تعیین کنی، آخرین پست تازه فرستاده میشه."
        )
        await safe_edit(query, text, kb.send_mode_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:setmode:"):
        _, _, cid_s, mode = data.split(":")
        cid = int(cid_s)
        db.set_channel_send_mode(cid, mode)
        mode_fa = {"schedule": "زمان‌بندی هفت‌گانه", "instant": "لحظه‌ای", "interval": "بازه‌ای"}.get(mode, mode)
        if mode == "instant":
            ch = db.get_channel(cid)
            if ch:
                try:
                    from ..scraper import fetch_latest_post_id
                    baseline_id = await fetch_latest_post_id(ch["username"])
                    if baseline_id:
                        db.update_last_post(cid, baseline_id)
                except Exception:
                    log.warning("پایه‌گذاریِ last_post_id هنگام سوییچ به لحظه‌ای برای @%s ناموفق بود.", ch["username"])
        await query.answer(f"✅ حالت ارسال به «{mode_fa}» تغییر کرد.", show_alert=True)
        if mode == "interval":
            ch = db.get_channel(cid)
            interval = ch["interval_minutes"] if ch else 30
            if not interval or int(interval) <= 0:
                _set_awaiting(context, f"src_interval:{cid}", f"src:mode_menu:{cid}")
                await safe_edit(
                    query,
                    "هر چند دقیقه یک‌بار آخرین پستِ این کانال فرستاده بشه؟ یه عدد صحیح بفرست (مثلا 30):",
                    kb.cancel_input_menu(),
                )
                return
        ch_final = db.get_channel(cid)
        if not ch_final:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        text = (
            f"🚀 <b>حالت ارسال @{ch_final['username']}</b>\n\n"
            "دقیقا یکی از این سه حالت می‌تونه فعال باشه؛ با انتخاب یکی، دوتای دیگه خودکار غیرفعال میشن."
        )
        await safe_edit(query, text, kb.send_mode_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:setinterval:"):
        cid = int(data.split(":")[2])
        _set_awaiting(context, f"src_interval:{cid}", f"src:mode_menu:{cid}")
        await safe_edit(
            query,
            "هر چند دقیقه یک‌بار آخرین پستِ این کانال فرستاده بشه؟ یه عدد صحیح بفرست (مثلا 30):",
            kb.cancel_input_menu(),
        )
        return

    if data.startswith("src:bulk_menu:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        approval_note = (
            "چون «تایید قبل از ارسال» این کانال فعاله، همه‌شون اول برای تو می‌رن."
            if ch["approval_required"] else
            "چون «تایید قبل از ارسال» این کانال غیرفعاله، مستقیم به مقصد می‌رن."
        )
        text = f"📤 <b>ارسال پست‌های آخر @{ch['username']}</b>\n\nچند پستِ آخر رو بفرستم؟ {approval_note}"
        await safe_edit(query, text, kb.bulk_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:bulk_run:"):
        _, _, cid_s, n_s = data.split(":")
        cid, n = int(cid_s), int(n_s)
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        await query.answer(f"⏳ در حال گرفتن {n} پستِ آخر... چند لحظه صبر کن.", show_alert=True)
        from ..scraper import fetch_latest_posts, ScraperError as _SE
        from ..poster import process_new_post, PostResult
        remove_links = db.get_effective_bool(
            cid, "remove_source_links", True,
            owner_user_id=(ch["owner_user_id"] if ch["owner_user_id"] else None),
        )
        try:
            posts = await fetch_latest_posts(ch["username"], n, remove_self_links=remove_links)
        except _SE as e:
            log.warning("گرفتنِ %s پستِ آخرِ @%s (دکمه‌ی ارسالِ لحظه‌ای) شکست خورد: %s", n, ch["username"], e)
            await context.bot.send_message(chat_id=query.from_user.id, text=f"❌ خطا در گرفتن پست‌ها: {e}")
            return
        if not posts:
            await context.bot.send_message(chat_id=query.from_user.id, text="پستی پیدا نشد.")
            return
        sent_direct = 0
        queued = 0
        skipped = 0
        stopped_early = False
        # posts از قدیم به جدید مرتبه؛ اگه یکی به‌خاطرِ خطای فنی شکست بخوره،
        # ترتیب رو حفظ می‌کنیم و بقیه‌ی پست‌های جدیدتر رو نمی‌فرستیم - وگرنه
        # مثلِ قبل last_post_id از روی پستِ شکست‌خورده هم رد می‌شد و آن پست
        # برای همیشه گم می‌شد و پستِ بعدی زودتر از موقع می‌رفت.
        for post in posts:
            result = await process_new_post(context.bot, ch, post, force_resend=True)
            if result == PostResult.FAILED:
                stopped_early = True
                log.warning(
                    "ارسالِ پستِ %s از @%s (دکمه‌ی پست‌های آخر) به‌دلیلِ خطای فنی متوقف شد.",
                    post.id, ch["username"],
                )
                break
            db.update_last_post(cid, post.id)
            if result == PostResult.SENT:
                sent_direct += 1
            elif result == PostResult.QUEUED:
                queued += 1
            else:
                skipped += 1
            await asyncio.sleep(1.0)
        summary = f"✅ از {len(posts)} پستِ آخرِ @{ch['username']}:\n"
        if sent_direct:
            summary += f"• {sent_direct} تا مستقیم به مقصد ارسال شد.\n"
        if queued:
            summary += f"• {queued} تا برای تایید/ویرایش فرستاده شد به همین چت.\n"
        if skipped:
            summary += f"• {skipped} تا طبقِ فیلترهای فعال رد شد.\n"
        if stopped_early:
            summary += (
                "⚠️ یکی از پست‌ها به‌خاطرِ خطای فنی (مثلاً دانلود/آپلودِ ویدیو) ارسال نشد؛ "
                "برای حفظِ ترتیب، بقیه‌ی پست‌های جدیدتر فعلاً فرستاده نشدن. "
                "چند لحظه دیگه دوباره همین دکمه رو بزن تا از همون‌جا ادامه بده."
            )
        await context.bot.send_message(chat_id=query.from_user.id, text=summary)
        return

    if data.startswith("src:sched:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
            return
        text = (
            f"⏱ <b>زمان‌بندی @{ch['username']}</b>\n\n"
            "هفت اسلات ساعتی (به وقت تهران). روی هرکدوم بزن تا ساعتش رو عوض کنی یا "
            "فعال/غیرفعالش کنی. 🟢 = فعال، ⚪️ = غیرفعال."
        )
        await safe_edit(query, text, kb.source_schedule_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:slot:"):
        _, _, cid_s, idx_s = data.split(":")
        cid, idx = int(cid_s), int(idx_s)
        slot = db.get_slot(cid, idx)
        ch = db.get_channel(cid)
        if not slot or not ch:
            await query.answer("این اسلات یا کانال پیدا نشد.", show_alert=True)
            return
        text = (
            f"⏱ <b>اسلات {idx} از @{ch['username']}</b>\n\n"
            f"🕒 ساعت فعلی: <b>{_esc(slot['slot_time'] or '--:--')}</b> (وقت تهران)\n"
            f"🔘 وضعیت: {'🟢 فعال' if slot['enabled'] else '⚪️ غیرفعال'}"
        )
        await safe_edit(query, text, kb.slot_detail_menu(cid, idx), ParseMode.HTML)
        return

    if data.startswith("src:slot_toggle:"):
        _, _, cid_s, idx_s = data.split(":")
        cid, idx = int(cid_s), int(idx_s)
        db.toggle_slot(cid, idx)
        slot = db.get_slot(cid, idx)
        ch = db.get_channel(cid)
        await query.answer("✅ وضعیت اسلات تغییر کرد.", show_alert=True)
        if slot and ch:
            text = (
                f"⏱ <b>اسلات {idx} از @{ch['username']}</b>\n\n"
                f"🕒 ساعت فعلی: <b>{_esc(slot['slot_time'] or '--:--')}</b> (وقت تهران)\n"
                f"🔘 وضعیت: {'🟢 فعال' if slot['enabled'] else '⚪️ غیرفعال'}"
            )
            await safe_edit(query, text, kb.slot_detail_menu(cid, idx), ParseMode.HTML)
        return

    if data.startswith("src:slot_time:"):
        _, _, cid_s, idx_s = data.split(":")
        cid, idx = int(cid_s), int(idx_s)
        _set_awaiting(context, f"src_slot_time:{cid}:{idx}", f"src:slot:{cid}:{idx}")
        await safe_edit(
            query,
            "ساعت این اسلات رو به فرمت ۲۴ ساعته بفرست (مثلا 08:00 یا 21:30) - به وقت تهران:",
            kb.cancel_input_menu(),
        )
        return

    if data.startswith("src:destmap:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
            return
        _owner_id = _owner_scope(uid)
        _dest_list = db.list_destinations() if _owner_id is None else db.list_destinations(owner_user_id=_owner_id)
        if not _dest_list:
            hint = "" if _owner_id is None else " (کانال‌های مقصدِ ادمین یا کاربرانِ دیگه اینجا نشون داده نمی‌شه)"
            text = f"🎯 <b>مقصدهای @{ch['username']}</b>\n\nهنوز هیچ کانال مقصدی نداری.{hint} اول یکی اضافه کن."
        else:
            text = f"🎯 <b>مقصدهای @{ch['username']}</b>\n\nروی هرکدوم بزن تا وصل/قطع بشه. ✅ = وصله، ⬜️ = وصل نیست."
        await safe_edit(query, text, kb.source_destmap_menu(cid, _owner_id), ParseMode.HTML)
        return

    if data.startswith("src:destmap_toggle:"):
        _, _, cid_s, did_s = data.split(":")
        cid, did = int(cid_s), int(did_s)
        now_linked = db.toggle_link(cid, did)
        await query.answer("✅ وصل شد." if now_linked else "قطع شد.", show_alert=False)
        ch = db.get_channel(cid)
        text = f"🎯 <b>مقصدهای @{ch['username']}</b>\n\nروی هرکدوم بزن تا وصل/قطع بشه." if ch else "کانال حذف شد."
        await safe_edit(query, text, kb.source_destmap_menu(cid, _owner_scope(uid)), ParseMode.HTML)
        return

    if data.startswith("src:overrides:"):
        cid = int(data.split(":")[2])
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
            return
        text = (
            f"⚙️ <b>تنظیماتِ اختصاصیِ @{ch['username']}</b>\n"
            f"{DIVIDER}\n"
            "هر تاگل رو می‌تونی فقط برای همین کانال جدا کنی؛ بقیه‌ی کانال‌ها و "
            "تنظیمِ عمومیِ ربات دست‌نخورده می‌مونن.\n\n"
            "🟢 روشن · 🔴 خاموش   |   🔁 پیرو عمومی · 📌 اختصاصیِ این کانال\n\n"
            "روی هر دکمه بزن تا بینِ سه حالت بچرخه:\n"
            "🔁 پیرو عمومی ← 🟢 همیشه روشن ← 🔴 همیشه خاموش"
        )
        await safe_edit(query, text, kb.source_override_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:ov_cycle:"):
        _, _, cid_s, key = data.split(":", 3)
        cid = int(cid_s)
        ch = db.get_channel(cid)
        if not ch:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "📡 کانال‌های مبدأ", kb.sources_menu(_owner_scope(uid)))
            return
        new_val = db.cycle_channel_override(cid, key)
        label = OVERRIDABLE_TOGGLES.get(key, key)
        if new_val is None:
            msg = f"🔁 «{label}» برای این کانال دوباره پیرو تنظیمِ عمومی شد."
        elif new_val:
            msg = f"🟢 «{label}» فقط برای این کانال همیشه فعال شد."
        else:
            msg = f"🔴 «{label}» فقط برای این کانال همیشه غیرفعال شد."
        await query.answer(msg, show_alert=False)
        await safe_edit(query, "⚙️ به‌روزرسانی شد 👇", kb.source_override_menu(cid), ParseMode.HTML)
        return

    if data.startswith("src:ov_clear_all:"):
        cid = int(data.split(":")[2])
        db.clear_all_channel_overrides(cid)
        await query.answer("♻️ همه‌ی تنظیماتِ اختصاصیِ این کانال پاک شد؛ حالا کامل پیرو تنظیمِ عمومیه.", show_alert=True)
        await safe_edit(query, "⚙️ به‌روزرسانی شد 👇", kb.source_override_menu(cid), ParseMode.HTML)
        return

    # ==================== کانال‌های مقصد ====================
    if data == "dst:add":
        context.user_data.pop("new_dst_name", None)
        _set_awaiting(context, "dst_add_name", "menu:destinations")
        await safe_edit(
            query,
            "اول یه اسم دلخواه برای این کانال مقصد بفرست (فقط برای نمایش راحت‌تر توی لیست). "
            "اگه نمی‌خوای اسم بذاری، «⏭ رد کردن» رو بزن.",
            kb.skip_input_menu(),
        )
        return

    if data.startswith("dst:page:"):
        try:
            _page = int(data.split(":")[2])
        except (IndexError, ValueError):
            _page = 0
        text, markup, parse_mode = _section_content("destinations", uid, _page)
        await safe_edit(query, text, markup, parse_mode)
        return

    if data.startswith("dst:view:"):
        did = int(data.split(":")[2])
        d = db.get_destination(did)
        if not d:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            await safe_edit(query, "🎯 کانال‌های مقصد", kb.destinations_menu(_owner_scope(uid)))
            return
        await safe_edit(query, _destination_detail_text(d), kb.destination_detail_menu(did), ParseMode.HTML)
        return

    if data.startswith("dst:toggle:"):
        did = int(data.split(":")[2])
        db.toggle_destination(did)
        await query.answer("✅ وضعیت کانال مقصد تغییر کرد.", show_alert=True)
        d = db.get_destination(did)
        if d:
            await safe_edit(query, _destination_detail_text(d), kb.destination_detail_menu(did), ParseMode.HTML)
        else:
            await safe_edit(query, "کانال حذف شد.", kb.destinations_menu(_owner_scope(uid)))
        return

    if data.startswith("dst:remove_confirm:"):
        did = int(data.split(":")[2])
        db.remove_destination(did)
        await query.answer("🗑 کانال مقصد حذف شد.", show_alert=True)
        await safe_edit(query, "🎯 کانال‌های مقصد", kb.destinations_menu(_owner_scope(uid)))
        return

    if data.startswith("dst:remove:"):
        did = int(data.split(":")[2])
        await safe_edit(query, "⚠️ مطمئنی می‌خوای این کانال مقصد رو حذف کنی؟", kb.confirm_remove_destination_menu(did))
        return

    # ---------------- آمار و زمان‌بندیِ هوشمندِ هر مقصد ----------------
    # ⚠️ فیکس: دکمه‌ی «📊 آمار و زمان‌بندی هوشمند» (kb.destination_detail_menu) و
    # دکمه‌های داخلِ صفحه‌ش (kb.dst_smart_menu) از قبل ساخته می‌شدن ولی هیچ شاخه‌ای
    # اینجا نداشتن؛ یعنی زدنِ اون دکمه‌ها هیچ کاری نمی‌کرد و فقط لاگِ
    # «callback_data ناشناخته» می‌خورد. حالا هر دو به SmartScheduler وصل شدن.
    async def _show_dst_smart(did_: int):
        from ..smart_scheduler import SmartScheduler  # وارداتِ تنبل، مثلِ بقیه‌ی این فایل
        d = db.get_destination(did_)
        if not d:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        title = _esc(d["title"] or d["chat_id"])
        on = SmartScheduler.is_enabled(did_)
        text = (
            f"📊 <b>آمار و زمان‌بندیِ هوشمند</b>\n"
            f"🎯 {title}\n"
            f"{DIVIDER}\n"
            f"🧠 وضعیت: {'🟢 فعال' if on else '🔴 غیرفعال'}\n\n"
            f"{SmartScheduler.get_stats_text(did_)}"
        )
        await safe_edit(query, text, kb.dst_smart_menu(did_), ParseMode.HTML)

    if data.startswith("dst:smarttoggle:"):
        from ..smart_scheduler import SmartScheduler
        did = int(data.split(":")[2])
        SmartScheduler.set_enabled(did, not SmartScheduler.is_enabled(did))
        await query.answer("✅ وضعیتِ زمان‌بندیِ هوشمند تغییر کرد.", show_alert=True)
        await _show_dst_smart(did)
        return

    if data.startswith("dst:smart:"):
        await _show_dst_smart(int(data.split(":")[2]))
        return

    # ---------------- تنظیماتِ اختصاصیِ هر مقصد (امضا + فیلترِ تبلیغات) ----------------
    # نکته‌ی ایزوله‌سازی: همه‌ی این callbackها آیدیِ مقصد رو در جایگاهِ سوم
    # (split(":")[2]) دارن، پس گِیتِ مالکیتِ بالا (_own_destination_or_deny) خودکار
    # تضمین می‌کنه هر کاربر فقط رو مقصدهای خودش دست می‌بره؛ ادمین هم فقط مالِ خودش.
    def _dst_from(data_str: str) -> int:
        return int(data_str.split(":")[2])

    async def _show_dest_cfg(did_: int):
        d = db.get_destination(did_)
        if not d:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        await safe_edit(query, _dest_config_text(d), kb.destination_config_menu(did_), ParseMode.HTML)

    async def _show_dest_footer(did_: int):
        d = db.get_destination(did_)
        if not d:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        await safe_edit(query, _dest_footer_text(d), kb.dest_footer_menu(did_), ParseMode.HTML)

    async def _show_dest_adf(did_: int):
        d = db.get_destination(did_)
        if not d:
            await query.answer("این کانال دیگه وجود نداره.", show_alert=True)
            return
        await safe_edit(query, _dest_adf_text(d), kb.dest_adfilter_menu(did_), ParseMode.HTML)

    if data.startswith("dst:cfg:"):
        await _show_dest_cfg(_dst_from(data))
        return

    if data.startswith("dst:footertoggle:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "footer_override", False)
        db.dest_setting_set(did, "footer_override", "0" if cur else "1")
        await _show_dest_footer(did)
        return

    if data.startswith("dst:footerenable:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "footer_enabled", True)
        db.dest_setting_set(did, "footer_enabled", "0" if cur else "1")
        await _show_dest_footer(did)
        return

    if data.startswith("dst:footermode:"):
        did = _dst_from(data)
        await safe_edit(query, "حالتِ امضای این مقصد رو انتخاب کن:", kb.dest_footer_mode_menu(did))
        return

    if data.startswith("dst:footersetmode:"):
        did = _dst_from(data)
        mode = data.split(":")[3]
        db.dest_setting_set(did, "footer_mode", "custom" if mode == "custom" else "link")
        await _show_dest_footer(did)
        return

    if data.startswith("dst:footerhandle:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_footer_handle", f"dst:footer:{did}")
        await safe_edit(query, "یوزرنیم/هندلِ کانال برای امضای این مقصد رو بفرست (مثلاً @mychannel).", kb.cancel_input_menu())
        return

    if data.startswith("dst:footerurl:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_footer_url", f"dst:footer:{did}")
        await safe_edit(query, "لینکِ کاملِ کانال برای امضای این مقصد رو بفرست (مثلاً https://t.me/mychannel).", kb.cancel_input_menu())
        return

    if data.startswith("dst:footertpl:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_footer_template", f"dst:footer:{did}")
        await safe_edit(query, "قالبِ متنِ امضا رو بفرست؛ باید شاملِ {handle} باشه. مثال:\n<code>🔷 join us: {handle}</code>", kb.cancel_input_menu(), ParseMode.HTML)
        return

    if data.startswith("dst:footercustom:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_footer_custom", f"dst:footer:{did}")
        await safe_edit(query, "متنِ کاملاً دلخواهِ امضای این مقصد رو بفرست (چندخطی و با فرمتِ تلگرام مجازه). برای پاک‌کردن، یک نقطه «.» بفرست.", kb.cancel_input_menu())
        return

    if data.startswith("dst:adfstripm:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "ad_strip_mentions", False)
        db.dest_setting_set(did, "ad_strip_mentions", "0" if cur else "1")
        db.dest_setting_set(did, "ad_strip_override", "1")
        await query.answer(
            "منشن‌ها دیگه از متنِ پست حذف می‌شن (به‌جای این‌که پست رد شه)." if not cur
            else "حذفِ منشن‌ها خاموش شد.", show_alert=True,
        )
        await _show_dest_adf(did)
        return

    if data.startswith("dst:adfstripl:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "ad_strip_links", False)
        db.dest_setting_set(did, "ad_strip_links", "0" if cur else "1")
        db.dest_setting_set(did, "ad_strip_override", "1")
        await query.answer(
            "لینک‌های سایت دیگه از متنِ پست حذف می‌شن (کانفیگ/پروکسی دست‌نخورده می‌مونه)." if not cur
            else "حذفِ لینک‌ها خاموش شد.", show_alert=True,
        )
        await _show_dest_adf(did)
        return

    if data.startswith("dst:adftoggle:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "ad_filter_override", False)
        db.dest_setting_set(did, "ad_filter_override", "0" if cur else "1")
        await _show_dest_adf(did)
        return

    if data.startswith("dst:duptoggle:"):
        did = _dst_from(data)
        from ..duplicate_filter import DuplicateFilter
        cur = DuplicateFilter.get_dest_dedup_enabled(did)
        DuplicateFilter.set_dest_dedup_enabled(did, not cur)
        await _show_dest_cfg(did)
        return

    if data.startswith("dst:adfenable:"):
        did = _dst_from(data)
        cur = db.dest_setting_get_bool(did, "ad_filter_enabled", True)
        db.dest_setting_set(did, "ad_filter_enabled", "0" if cur else "1")
        await _show_dest_adf(did)
        return

    if data.startswith("dst:adfaction:"):
        did = _dst_from(data)
        cur = db.dest_setting_get(did, "ad_filter_action", "skip")
        db.dest_setting_set(did, "ad_filter_action", "review" if cur != "review" else "skip")
        await _show_dest_adf(did)
        return

    if data.startswith("dst:adf:"):
        await _show_dest_adf(_dst_from(data))
        return

    if data.startswith("dst:footer:"):
        await _show_dest_footer(_dst_from(data))
        return

    if data.startswith("dst:adfkw:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_adf_keywords", f"dst:adf:{did}")
        cur = db.dest_setting_get(did, "ad_filter_keywords", "")
        await safe_edit(query, f"کلیدواژه‌های فیلترِ این مقصد رو با کاما جدا کن بفرست. برای برگشت به پیش‌فرض، یک نقطه «.» بفرست.\n\nفعلی: {_esc(cur or 'پیش‌فرض')}", kb.cancel_input_menu(), ParseMode.HTML)
        return

    if data.startswith("dst:adfph:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_adf_phrases", f"dst:adf:{did}")
        cur = db.dest_setting_get(did, "ad_filter_remove_phrases", "")
        await safe_edit(
            query,
            "🧹 عبارت‌ها/ایموجی‌هایی که باید <b>فقط برای این مقصد</b> از متنِ پست حذف بشن رو "
            "بفرست؛ هر عبارت توی یک خطِ جدا. برای خالی‌کردن یک نقطه «.» بفرست.\n"
            "(اگه اینجا خالی باشه، همون لیستِ سراسریِ بخشِ «فیلتر تبلیغات» اعمال می‌شه.)\n\n"
            f"فعلی:\n<code>{_esc(cur) if cur else '(خالی)'}</code>",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    if data.startswith("dst:adfmm:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_adf_min_mentions", f"dst:adf:{did}")
        await safe_edit(query, "آستانه‌ی تعدادِ منشن (@) رو به‌صورتِ یک عدد بفرست (مثلاً 3).", kb.cancel_input_menu())
        return

    if data.startswith("dst:adfml:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_adf_min_links", f"dst:adf:{did}")
        await safe_edit(query, "آستانه‌ی تعدادِ لینک رو به‌صورتِ یک عدد بفرست (مثلاً 2).", kb.cancel_input_menu())
        return

    if data.startswith("dst:adfth:"):
        did = _dst_from(data)
        context.user_data["dst_cfg_id"] = did
        _set_awaiting(context, "dst_adf_threshold", f"dst:adf:{did}")
        await safe_edit(query, "حساسیتِ کلیِ فیلتر رو به‌صورتِ یک عدد بفرست (هرچه کمتر، سخت‌گیرتر؛ پیش‌فرض 4).", kb.cancel_input_menu())
        return
    # ==================== صفِ تایید/ویرایش پست ====================
    if data.startswith("pp:approve:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row:
            await query.answer("این پست دیگه پیدا نشد.", show_alert=True)
            return
        if row["status"] != "pending":
            await query.answer("این پست قبلا پردازش شده.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "approve", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        await query.answer("⏳ در حال ارسال به مقصد...")
        from ..poster import approve_pending_post
        ok = await approve_pending_post(context.bot, pid)
        if ok:
            final_caption = "✅ تایید شد و به مقصد ارسال شد."
        else:
            # اگه وضعیت الان دیگه pending نیست، یعنی یه کلیکِ هم‌زمانِ دیگه
            # (مثلاً از یه دستگاهِ دیگه‌ی همون اکانتِ مشترک) زودتر همین پست رو
            # claim و ارسال کرده - نه این‌که ارسالِ همین کلیک ناموفق بوده باشه.
            _after = db.get_pending_post(pid)
            if _after and _after["status"] != "pending":
                final_caption = "ℹ️ این پست همین الان با یه کلیکِ دیگه تایید و ارسال شد."
            else:
                final_caption = "⚠️ تایید شد ولی ارسال به مقصد ناموفق بود (لاگ رو چک کن)."
        try:
            await query.edit_message_caption(caption=final_caption)
        except Exception:
            try:
                await query.edit_message_text(final_caption)
            except Exception as e:
                log.warning("ویرایشِ پیامِ پیش‌نمایشِ پستِ %s بعد از تایید ناموفق بود (نه خودِ ارسال): %s", pid, e)
        return

    if data.startswith("pp:reject:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row:
            await query.answer("این پست دیگه پیدا نشد.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "reject", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        if row["status"] != "pending":
            await query.answer("این پست قبلا پردازش شده.", show_alert=True)
            return
        if not db.claim_pending_post(pid, "rejected"):
            # یه فراخوانیِ هم‌زمانِ دیگه (مثلاً تاییدِ همین پست از یه دستگاهِ
            # دیگه‌ی همون اکانتِ مشترک) زودتر بردتش؛ دیگه چیزی برایِ رد کردن نیست.
            await query.answer("این پست همین الان با یه کلیکِ دیگه پردازش شد.", show_alert=True)
            return
        await query.answer("❌ پست رد شد.", show_alert=True)
        try:
            await query.edit_message_caption(caption="❌ این پست رد شد و ارسال نمیشه.")
        except Exception:
            try:
                await query.edit_message_text("❌ این پست رد شد و ارسال نمیشه.")
            except Exception as e:
                log.warning("ویرایشِ پیامِ پیش‌نمایشِ پستِ %s بعد از رد کردن ناموفق بود (نه خودِ رد کردن): %s", pid, e)
        return

    if data.startswith("pp:adfb:"):
        # فیدبکِ ادمین به تشخیصِ فیلترِ تبلیغات (نگاه کن به ad_filter.py و
        # database.set_pending_ad_feedback) - تنها راهیه که واقعاً معلوم می‌شه
        # فیلتر کجاها اشتباه می‌کنه. برخلافِ approve/reject، به pending بودنِ
        # پست وابسته نیست: حتی بعد از تایید/ردِ پست هم می‌شه در موردِ درستیِ
        # خودِ تشخیص فیدبک داد.
        parts = data.split(":")
        verdict = "correct" if parts[2] == "1" else "incorrect"
        pid = int(parts[3])
        row = db.get_pending_post(pid)
        if not row:
            await query.answer("این پست دیگه پیدا نشد.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        if not db.set_pending_ad_feedback(pid, verdict):
            await query.answer("فیدبک برایِ این پست قبلاً ثبت شده بود.", show_alert=True)
            return
        await query.answer("✅ فیدبک ثبت شد. ممنون!")
        note = (
            "🧠 فیدبک: تشخیصِ فیلتر درست بود (واقعاً تبلیغ بود)."
            if verdict == "correct" else
            "🧠 فیدبک: تشخیصِ فیلتر اشتباه بود (این پست تبلیغ نبود)."
        )
        from ..poster import pending_post_flags, pending_preview_caption, _pending_kb
        has_video, has_photo, show_restore, ad_flagged, _old_feedback = pending_post_flags(row)
        new_caption = f"{pending_preview_caption(row)}\n\n{note}"
        new_markup = _pending_kb(
            pid, has_video=has_video, has_photo=has_photo, show_restore=show_restore,
            ad_flagged=ad_flagged, ad_feedback=verdict,
        )
        try:
            await query.edit_message_caption(caption=new_caption, reply_markup=new_markup, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await query.edit_message_text(new_caption, reply_markup=new_markup, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("ویرایشِ پیامِ پیش‌نمایشِ پستِ %s بعد از ثبتِ فیدبک ناموفق بود (نه خودِ فیدبک): %s", pid, e)
        return

    if data.startswith("pp:editcap:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگه در دسترس نیست.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return

        prompt_text = (
            "✏️ کپشن جدید رو بفرست (می‌تونی بولد/ایتالیک/لینک و... استفاده کنی، فرمتش حفظ میشه). "
            "برای خالی کردن کپشن، یک نقطه «.» بفرست."
        )
        # باگِ قبلی: این پیامِ راهنما همیشه به‌صورتِ پیامِ خصوصی به ادمین فرستاده
        # می‌شد، حتی وقتی دکمه مستقیماً زیرِ خودِ پستِ توی کانالِ تایید زده شده
        # بود - یعنی راهنما توی چتِ دیگه‌ای (خصوصی) ظاهر می‌شد، نه زیرِ همون
        # پستِ کانال. حالا اگه دکمه توی یه چتِ غیرخصوصی (کانال/گروه) زده شده
        # باشه، راهنما مستقیماً همون‌جا زیرِ همون پیام فرستاده می‌شه.
        if query.message and query.message.chat.type != "private":
            context.chat_data["awaiting"] = f"pp_caption:{pid}"
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text=prompt_text,
                )
            except Exception as e:
                log.warning("ارسالِ راهنمای ویرایشِ کپشن توی کانالِ تایید ناموفق بود (پستِ %s): %s", pid, e)
                context.chat_data.pop("awaiting", None)
                await query.answer("⚠️ نتونستم راهنما رو توی همین کانال بفرستم.", show_alert=True)
                return
            await query.answer()
            return

        context.user_data["awaiting"] = f"pp_caption:{pid}"
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=prompt_text,
                reply_markup=kb.cancel_input_menu(),
            )
        except Exception:
            context.user_data.pop("awaiting", None)
            await query.answer(
                "⚠️ نتونستم بهت پیام خصوصی بدم. اول یه بار ربات رو توی چت خصوصی /start کن، بعد دوباره امتحان کن.",
                show_alert=True,
            )
            return
        await query.answer()
        return

    if data.startswith("pp:editphoto:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگه در دسترس نیست.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        from ..poster import json_to_media_items
        _media = json_to_media_items(row["media_json"])
        if not any(m.type == "photo" for m in _media):
            # کیبورد ممکنه قدیمی/کش‌شده باشه (قبل از فیکس) و هنوز این دکمه رو
            # برای یک پستِ ویدیویی نشون بده؛ این پست عکس نداره پس عوض‌کردنِ
            # عکس بی‌معنیه (قبلاً این حالت بی‌صدا نادیده گرفته می‌شد).
            await query.answer("این پست عکس نداره (ویدیوعه)؛ برای عوض کردنِ ویدیو از دکمه‌ی «تغییر ویدیو» استفاده کن.", show_alert=True)
            return

        prompt_text = (
            "🖼 عکس جدید رو بفرست؛ همون واترمارکِ تنظیم‌شده روش زده میشه و جای عکسِ اصلی پست می‌نشینه."
        )
        if query.message and query.message.chat.type != "private":
            context.chat_data["awaiting"] = f"pp_photo:{pid}"
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text=prompt_text,
                )
            except Exception as e:
                log.warning("ارسالِ راهنمای ویرایشِ عکس توی کانالِ تایید ناموفق بود (پستِ %s): %s", pid, e)
                context.chat_data.pop("awaiting", None)
                await query.answer("⚠️ نتونستم راهنما رو توی همین کانال بفرستم.", show_alert=True)
                return
            await query.answer()
            return

        context.user_data["awaiting"] = f"pp_photo:{pid}"
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=prompt_text,
                reply_markup=kb.cancel_input_menu(),
            )
        except Exception:
            context.user_data.pop("awaiting", None)
            await query.answer(
                "⚠️ نتونستم بهت پیام خصوصی بدم. اول یه بار ربات رو توی چت خصوصی /start کن، بعد دوباره امتحان کن.",
                show_alert=True,
            )
            return
        await query.answer()
        return

    if data.startswith("pp:editvideo:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگه در دسترس نیست.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        from ..poster import json_to_media_items
        _media = json_to_media_items(row["media_json"])
        if not any(m.type == "video" for m in _media):
            # کیبورد ممکنه قدیمی/کش‌شده باشه و این دکمه رو برای یه پستِ عکسی نشون بده؛
            # اگه ویدیو override ذخیره بشه ولی پست عکسی باشه، توی poster.py بی‌صدا
            # نادیده گرفته میشه (چون elif len(photos)==1 زودتر از elif video_override اجرا میشه).
            await query.answer("این پست ویدیو نداره (عکسه)؛ برای تغییر عکس از دکمه «تغییر عکس» استفاده کن.", show_alert=True)
            return
        context.user_data["awaiting"] = f"pp_video:{pid}"
        # مشابهِ ویرایشِ کپشن/عکس: اگه دکمه توی خودِ کانالِ تایید زده شده باشه،
        # می‌شه ویدیوی جدید رو مستقیماً همون‌جا توی کانال هم فرستاد.
        if query.message:
            context.chat_data["awaiting"] = f"pp_video:{pid}"
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="🎬 ویدیوی جدید رو بفرست؛ کاملاً جای خودِ ویدیوی پست رو می‌گیره (نه فقط کاورش). "
                     "یا اگه این پیام توی کانالِ تایید بود، می‌تونی ویدیوی جدید رو مستقیماً همین‌جا توی همین کانال هم بفرستی.",
                reply_markup=kb.cancel_input_menu(),
            )
        except Exception:
            context.user_data.pop("awaiting", None)
            if context.chat_data.get("awaiting") == f"pp_video:{pid}":
                await query.answer(
                    "🎬 نتونستم پیامِ خصوصی بفرستم؛ ویدیوی جدید رو مستقیماً همین‌جا توی همین کانال بفرست.",
                    show_alert=True,
                )
            else:
                await query.answer(
                    "⚠️ نتونستم بهت پیام خصوصی بدم. اول یه بار ربات رو توی چت خصوصی /start کن، بعد دوباره امتحان کن.",
                    show_alert=True,
                )
            return
        await query.answer()
        return

    # ==================== مدیریت کاربران ====================
    if data in ("menu:users", "usr:list"):
        await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu())
        return

    if data.startswith("usr:page:"):
        try:
            _page = int(data.split(":")[2])
        except (IndexError, ValueError):
            _page = 0
        await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu(_page))
        return

    if data == "usr:add":
        _set_awaiting(context, "usr_name", "menu:users")
        await safe_edit(query, "نام کاربر رو بفرست (مثلاً: مهدی):", kb.cancel_input_menu())
        return

    if data.startswith("usr:view:"):
        uid_ = int(data.split(":")[2])
        u = db.get_user(uid_)
        if not u:
            await query.answer("این کاربر پیدا نشد.", show_alert=True)
            await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu())
            return
        txt = (
            f"👤 <b>{_esc(u['name'])}</b>\n"
            f"🆔 تلگرام: <code>{u['telegram_id'] or '—'}</code>\n"
            f"✅ کانال تایید: <code>{u['approval_chat_id']}</code>\n"
            f"🔘 وضعیت: {'🟢 فعال' if u['active'] else '⚪️ غیرفعال'}"
        )
        await safe_edit(query, txt, kb.user_detail_menu(uid_), ParseMode.HTML)
        return

    if data.startswith("usr:toggle:"):
        uid_ = int(data.split(":")[2])
        db.toggle_user(uid_)
        u = db.get_user(uid_)
        await query.answer("✅ وضعیت کاربر تغییر کرد.", show_alert=True)
        if u:
            txt = (
                f"👤 <b>{_esc(u['name'])}</b>\n"
                f"🆔 تلگرام: <code>{u['telegram_id'] or '—'}</code>\n"
                f"✅ کانال تایید: <code>{u['approval_chat_id']}</code>\n"
                f"🔘 وضعیت: {'🟢 فعال' if u['active'] else '⚪️ غیرفعال'}"
            )
            await safe_edit(query, txt, kb.user_detail_menu(uid_), ParseMode.HTML)
        return

    if data.startswith("usr:srcmap_toggle:"):
        _, _, uid_s, ch_id_s = data.split(":")
        db.toggle_channel_owner(int(ch_id_s), int(uid_s))
        await safe_edit(query, "کانال‌های مبدأ این کاربر رو تیک بزن:", kb.user_srcmap_menu(int(uid_s)))
        return

    if data.startswith("usr:srcmap:"):
        uid_ = int(data.split(":")[2])
        await safe_edit(query, "📡 کانال‌های مبدأ این کاربر رو تیک بزن:", kb.user_srcmap_menu(uid_))
        return

    if data.startswith("usr:dstmap_toggle:"):
        _, _, uid_s, did_s = data.split(":")
        db.toggle_destination_owner(int(did_s), int(uid_s))
        await safe_edit(query, "🎯 کانال‌های مقصدِ این کاربر رو تیک بزن:", kb.user_dstmap_menu(int(uid_s)))
        return

    if data.startswith("usr:dstmap:"):
        uid_ = int(data.split(":")[2])
        await safe_edit(query, "🎯 کانال‌های مقصدِ این کاربر رو تیک بزن:", kb.user_dstmap_menu(uid_))
        return

    if data.startswith("usr:perms:"):
        uid_ = int(data.split(":")[2])
        if not db.get_user(uid_):
            await query.answer("این کاربر پیدا نشد.", show_alert=True)
            await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu())
            return
        await safe_edit(
            query,
            "🔒 <b>دسترسی‌های این کاربر</b>\nروی هرکدوم بزن تا فعال/غیرفعال بشه:",
            kb.user_permissions_menu(uid_),
            ParseMode.HTML,
        )
        return

    if data.startswith("usr:permtoggle:"):
        _, _, perm_key, uid_s = data.split(":")
        uid_ = int(uid_s)
        if not db.get_user(uid_):
            await query.answer("این کاربر پیدا نشد.", show_alert=True)
            await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu())
            return
        db.toggle_permission(uid_, perm_key)
        await safe_edit(
            query,
            "🔒 <b>دسترسی‌های این کاربر</b>\nروی هرکدوم بزن تا فعال/غیرفعال بشه:",
            kb.user_permissions_menu(uid_),
            ParseMode.HTML,
        )
        return

    if data.startswith("usr:setapproval:"):
        uid_ = int(data.split(":")[2])
        context.user_data["usr_edit_id"] = uid_
        _set_awaiting(context, "usr_approval", f"usr:view:{uid_}")
        await safe_edit(query, "آیدی عددی کانال تایید جدید رو بفرست (مثل -1001234567890):", kb.cancel_input_menu())
        return

    if data.startswith("usr:settid:"):
        uid_ = int(data.split(":")[2])
        context.user_data["usr_edit_id"] = uid_
        _set_awaiting(context, "usr_tid_edit", f"usr:view:{uid_}")
        await safe_edit(query, "آیدی عددی تلگرام کاربر رو بفرست:", kb.cancel_input_menu())
        return

    if data.startswith("usr:remove_confirm:"):
        uid_ = int(data.split(":")[2])
        db.remove_user(uid_)
        await query.answer("🗑 کاربر حذف شد.", show_alert=True)
        await safe_edit(query, "👥 کاربران مجاز:", kb.users_menu())
        return

    if data.startswith("usr:remove:"):
        uid_ = int(data.split(":")[2])
        await safe_edit(query, "⚠️ مطمئنی می‌خوای این کاربر رو حذف کنی؟", kb.confirm_remove_user_menu(uid_))
        return

    # ==================== واترمارک ====================
    if data.startswith("wmp:") and data.count(":") >= 1:
        parts = data.split(":")
        plat = parts[1] if len(parts) > 1 else ""
        owner = _settings_owner(uid)

        if plat in ("tg", "ig") and len(parts) == 2:
            await safe_edit(query, _platform_text(plat, owner), kb.watermark_platform_menu(plat, owner), ParseMode.HTML)
            return

        if plat in ("tg", "ig") and len(parts) >= 3:
            action = parts[2]
            prefix = f"wm_{plat}"

            if action == "toggle":
                new_val = not db.setting_get_bool(f"{prefix}_enabled", plat == "tg", owner_user_id=owner)
                db.setting_set(f"{prefix}_enabled", "1" if new_val else "0", owner_user_id=owner)
                await query.answer("✅ بروزرسانی شد.", show_alert=True)
                await safe_edit(query, _platform_text(plat, owner), kb.watermark_platform_menu(plat, owner), ParseMode.HTML)
                return

            if action == "text":
                _set_awaiting(context, f"wm_text:{plat}", f"wmp:{plat}")
                await safe_edit(query, "متنی که داخل واترمارک نشون داده بشه رو بفرست (مثلا اسم کانالت):",
                                 kb.cancel_input_menu())
                return

            if action == "position_menu":
                await safe_edit(query, "📍 موقعیت واترمارک رو انتخاب کن:", kb.watermark_position_menu(plat, owner))
                return

            if action == "setpos" and len(parts) == 4:
                pos = parts[3]
                db.setting_set(f"{prefix}_position", pos, owner_user_id=owner)
                await query.answer("✅ موقعیت بروزرسانی شد.", show_alert=True)
                await safe_edit(query, _platform_text(plat, owner), kb.watermark_platform_menu(plat, owner), ParseMode.HTML)
                return

            if action == "color_menu":
                mode = db.setting_get(f"{prefix}_color_mode", "gradient", owner_user_id=owner)
                ca = db.setting_get(f"{prefix}_color_a", "#E53935", owner_user_id=owner)
                cb = db.setting_get(f"{prefix}_color_b", "#1E88E5", owner_user_id=owner)
                selected = [ca] if mode == "single" else [ca, cb]
                context.user_data["color_pick"] = {"plat": plat, "mode": mode, "selected": selected}
                await safe_edit(
                    query,
                    "🎨 اول تک‌رنگ یا گرادیانی رو انتخاب کن، بعد از بین رنگ‌های آماده انتخاب کن "
                    "(نیازی به کد رنگ نیست). در آخر «✅ تایید» رو بزن.",
                    kb.watermark_color_menu(plat, selected, mode),
                )
                return

            if action == "color_mode" and len(parts) == 4:
                new_mode = parts[3]
                state = context.user_data.get("color_pick") or {"plat": plat, "mode": new_mode, "selected": []}
                state["mode"] = new_mode
                need = 1 if new_mode == "single" else 2
                state["selected"] = state.get("selected", [])[:need]
                context.user_data["color_pick"] = state
                await safe_edit(
                    query,
                    "🎨 اول تک‌رنگ یا گرادیانی رو انتخاب کن، بعد از بین رنگ‌های آماده انتخاب کن. "
                    "در آخر «✅ تایید» رو بزن.",
                    kb.watermark_color_menu(plat, state["selected"], state["mode"]),
                )
                return

            if action == "color_pick" and len(parts) == 4:
                hexv = parts[3]
                state = context.user_data.get("color_pick") or {"plat": plat, "mode": "gradient", "selected": []}
                need = 1 if state["mode"] == "single" else 2
                selected = state.get("selected", [])
                selected_upper = [s.upper() for s in selected]
                if hexv.upper() in selected_upper:
                    selected = [s for s in selected if s.upper() != hexv.upper()]
                elif len(selected) < need:
                    selected = selected + [hexv]
                else:
                    selected = selected[1:] + [hexv]
                state["selected"] = selected
                context.user_data["color_pick"] = state
                await safe_edit(
                    query,
                    "🎨 اول تک‌رنگ یا گرادیانی رو انتخاب کن، بعد از بین رنگ‌های آماده انتخاب کن. "
                    "در آخر «✅ تایید» رو بزن.",
                    kb.watermark_color_menu(plat, selected, state["mode"]),
                )
                return

            if action == "color_confirm":
                state = context.user_data.get("color_pick") or {}
                mode = state.get("mode", "gradient")
                selected = state.get("selected", [])
                need = 1 if mode == "single" else 2
                if len(selected) != need:
                    await query.answer("هنوز به تعداد کافی رنگ انتخاب نکردی.", show_alert=True)
                    return
                db.setting_set(f"{prefix}_color_mode", mode, owner_user_id=owner)
                db.setting_set(f"{prefix}_color_a", selected[0], owner_user_id=owner)
                db.setting_set(f"{prefix}_color_b", selected[1] if mode == "gradient" else selected[0], owner_user_id=owner)
                context.user_data.pop("color_pick", None)
                await query.answer("✅ رنگ ذخیره شد.", show_alert=True)
                await safe_edit(query, _platform_text(plat, owner), kb.watermark_platform_menu(plat, owner), ParseMode.HTML)
                return

            if action == "opacity":
                _set_awaiting(context, f"wm_opacity:{plat}", f"wmp:{plat}")
                await safe_edit(
                    query,
                    "عدد شفافیتِ رنگ بین 0 تا 100 رو بفرست (0 = خیلی کم‌رنگ، 100 = کاملاً پررنگ):",
                    kb.cancel_input_menu(),
                )
                return

            if action == "fontsize":
                _set_awaiting(context, f"wm_fontsize:{plat}", f"wmp:{plat}")
                await safe_edit(query, "اندازه‌ی متنِ آیدی رو به پیکسل بفرست (پیشنهاد: 30 تا 70).\n"
                                       "اگر بزرگ‌تر از فضای باکس باشه، خودکار کوچک می‌شه تا داخلِ باکس جا بشه:",
                                 kb.cancel_input_menu())
                return

            if action == "badgescale":
                _set_awaiting(context, f"wm_badgescale:{plat}", f"wmp:{plat}")
                await safe_edit(query, "اندازه‌ی نشان رو به‌صورتِ درصدی از عرضِ عکس بفرست (بین 8 تا 100، پیشنهاد: 28 تا 40):",
                                 kb.cancel_input_menu())
                return

            if action == "margin":
                _set_awaiting(context, f"wm_margin:{plat}", f"wmp:{plat}")
                await safe_edit(query, "فاصله‌ی نشان از لبه‌ی عکس رو به پیکسل بفرست:", kb.cancel_input_menu())
                return

            if action == "album_toggle":
                new_val = not db.setting_get_bool(f"{prefix}_album_all", True, owner_user_id=owner)
                db.setting_set(f"{prefix}_album_all", "1" if new_val else "0", owner_user_id=owner)
                await query.answer("✅ بروزرسانی شد.", show_alert=True)
                await safe_edit(query, _platform_text(plat, owner), kb.watermark_platform_menu(plat, owner), ParseMode.HTML)
                return

            if action == "preview":
                await query.answer("⏳ در حال ساخت پیش‌نمایش...")
                settings = {
                    "watermark_enabled": True,
                    "wm_tg_enabled": plat == "tg",
                    "wm_ig_enabled": plat == "ig",
                }
                for k in ("text", "position", "color_mode", "color_a", "color_b", "bg_opacity", "font_size", "margin", "badge_scale"):
                    settings[f"{prefix}_{k}"] = db.setting_get(f"{prefix}_{k}", owner_user_id=owner)
                from ..watermark import render_preview
                img = await concurrency.run_heavy(render_preview, settings)
                await context.bot.send_photo(chat_id=query.from_user.id, photo=img,
                                              caption=f"🖼 پیش‌نمایش واترمارک {_PLATFORM_FA.get(plat, plat)}")
                return

    # ==================== حذف واترمارک با AI / کش دانلود ====================
    if data == "ai:removal_toggle":
        new_val = not db.get_bool("ai_removal_enabled", False)
        db.set_setting("ai_removal_enabled", "1" if new_val else "0")
        await query.answer(
            "✅ حذف واترمارک با AI فعال شد." if new_val else "✅ حذف واترمارک با AI غیرفعال شد.", show_alert=True
        )
        await safe_edit(query, _watermark_overview_text(), kb.watermark_menu(), ParseMode.HTML)
        return

    if data == "ai:quality_toggle":
        new_val = not db.get_bool("quality_enhance_enabled", False)
        db.set_setting("quality_enhance_enabled", "1" if new_val else "0")
        await query.answer(
            "✅ بهبود کیفیت تصویر با AI فعال شد." if new_val else "✅ بهبود کیفیت تصویر با AI غیرفعال شد.",
            show_alert=True,
        )
        await safe_edit(query, _watermark_overview_text(), kb.watermark_menu(), ParseMode.HTML)
        return

    if data == "ai:cache_toggle":
        new_val = not db.get_bool("download_cache_enabled", True)
        db.set_setting("download_cache_enabled", "1" if new_val else "0")
        await query.answer("✅ بروزرسانی شد.", show_alert=True)
        await safe_edit(query, _watermark_overview_text(), kb.watermark_menu(), ParseMode.HTML)
        return

    if data == "ai:cache_clear":
        n = await cache.clear()
        await query.answer(f"🗑 کش دانلود پاک شد ({n} آیتم حذف شد).", show_alert=True)
        await safe_edit(query, _watermark_overview_text(), kb.watermark_menu(), ParseMode.HTML)
        return

    if data == "ai:status":
        status = ai_watermark.engines_status()
        cache_stats = await cache.stats()
        load = await concurrency.current_load()
        text = (
            "🧠 <b>وضعیتِ موتورهای پردازش تصویر</b>\n"
            f"{DIVIDER}\n"
            f"🔎 تشخیص با الگوهای ذخیره‌شده (Template Matching): {status['templates']}\n"
            f"🦙 ترمیم/حذف واترمارک (LaMa): {status['lama_inpaint']}\n"
            f"🔎 بهبودِ کیفیتِ تصویر (Super-Resolution): {sr_model.engine_status()}\n"
            f"{DIVIDER}\n"
            f"⚙️ پردازشِ هم‌زمانِ در حالِ اجرا: {load['active']}/{load['max_concurrent']}\n"
            f"💾 کش دانلود: {cache_stats['items']}/{cache_stats['max_items']} آیتم "
            f"(hit-rate: {cache_stats['hit_rate']}٪)\n\n"
            "💡 اگه واترمارکی حذف نمی‌شه، یا الگویی داخل data/watermark_templates اضافه "
            "کن، یا به heuristicِ گوشه‌ها (خودکار) اعتماد کن.\n"
            "💡 LaMa باید نصب باشه تا ترمیم انجام شه؛ بدونِ اون عکس بدون تغییر ارسال می‌شه."
        )
        await safe_edit(query, text, kb.ai_status_menu("menu:watermark"), ParseMode.HTML)
        return

    # ==================== فیلترِ پست‌های تبلیغاتی ====================
    if data == "adf:toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("ad_filter_enabled", False, owner_user_id=owner)
        db.setting_set("ad_filter_enabled", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ فیلترِ تبلیغات " + ("فعال شد." if new_val else "غیرفعال شد."), show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:smart_toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("ad_filter_smart", True, owner_user_id=owner)
        db.setting_set("ad_filter_smart", "1" if new_val else "0", owner_user_id=owner)
        await query.answer(
            ("✅ تشخیصِ هوشمند فعال شد؛ اگر کلیدِ هوش مصنوعی ست شده باشد، روی متنِ کاملِ "
             "همه‌ی پست‌ها (نه فقط موارد مرزی) داوریِ انسان‌گونه انجام می‌شود.") if new_val else "تشخیصِ هوشمند خاموش شد (فقط موتورِ قاعده‌محور).",
            show_alert=True,
        )
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:smart_channels":
        owner = _owner_scope(uid)
        if owner == -1:
            await query.answer("❌ دسترسی نداری.", show_alert=True)
            return
        text = (
            "🧠 <b>غیرفعال‌سازیِ فیلترِ هوشمند برای کانال‌های خاص</b>\n"
            f"{DIVIDER}\n"
            "با زدنِ هر کانال، وضعیتش عوض می‌شه. وقتی یک کانال «🔴 هوشمند خاموش» باشه، "
            "پست‌های اون کانال دیگه هیچ‌وقت با هوشِ مصنوعی داوری نمی‌شن - نه برایِ فیلترِ "
            "عمومی، نه برایِ فیلترِ اختصاصیِ هیچ مقصدی (حتی اگه اون مقصد خودش فیلترِ "
            "اختصاصی روشن کرده باشه) - و فقط موتورِ قاعده‌محور (کلیدواژه/لینک/منشن) روی "
            "پست‌هاشون اجرا می‌شه.\n\n"
            "این لیست و این تنظیم فقط مربوط به کانال‌های خودته؛ هر کاربر جدا و مستقل از "
            "بقیه‌ی کاربرها (و ادمین) کانال‌ها و وضعیتِ فیلترِ هوشمندِ خودش رو مدیریت می‌کنه."
        )
        await safe_edit(query, text, kb.ad_filter_smart_channels_menu(owner), ParseMode.HTML)
        return

    if data.startswith("adf:smart_ch_toggle:"):
        cid = int(data.split(":")[2])
        if not _own_channel_or_deny(uid, cid):
            await query.answer("❌ این کانال متعلق به تو نیست.", show_alert=True)
            return
        cur = db.get_channel_override(cid, "ad_filter_smart_enabled")
        if cur is False:
            db.clear_channel_override(cid, "ad_filter_smart_enabled")
            await query.answer("🟢 فیلترِ هوشمند برایِ این کانال دوباره روشن شد.", show_alert=True)
        else:
            db.set_channel_override(cid, "ad_filter_smart_enabled", False)
            await query.answer(
                "🔴 فیلترِ هوشمند برایِ این کانال خاموش شد؛ از این به بعد فقط موتورِ "
                "قاعده‌محور روی پست‌هاش تصمیم می‌گیره (نه AI).",
                show_alert=True,
            )
        owner = _owner_scope(uid)
        await safe_edit(query, "🧠 وضعیت به‌روزرسانی شد 👇", kb.ad_filter_smart_channels_menu(owner), ParseMode.HTML)
        return

    if data == "adf:action_menu":
        owner = _settings_owner(uid)
        await safe_edit(query, "⚙️ وقتی پستی تبلیغاتی تشخیص داده بشه، چیکار بشه؟", kb.ad_filter_action_menu(owner))
        return

    if data.startswith("adf:setaction:"):
        owner = _settings_owner(uid)
        action = data.split(":")[2]
        db.setting_set("ad_filter_action", action, owner_user_id=owner)
        await query.answer("✅ بروزرسانی شد.", show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:keywords":
        owner = _settings_owner(uid)
        _set_awaiting(context, "adf_keywords", "menu:adfilter")
        current = db.setting_get("ad_filter_keywords", "", owner_user_id=owner) or ad_filter.default_keywords_text()
        await safe_edit(
            query,
            "📝 لیستِ کلیدواژه‌های تبلیغاتی رو با ویرگول (,) از هم جدا بفرست. لیستِ فعلی:\n\n"
            f"<code>{_esc(current)}</code>\n\n"
            "می‌تونی این متن رو کپی، ویرایش و دوباره کامل بفرستی.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    if data in ("adf:phrases", "adf:phrases_add"):
        owner = _settings_owner(uid)
        current = db.setting_get("ad_filter_remove_phrases", "", owner_user_id=owner)
        append_mode = data == "adf:phrases_add"
        _set_awaiting(context, "adf_phrases_add" if append_mode else "adf_phrases", "menu:adfilter")
        if append_mode:
            txt = (
                "➕ عبارت‌های <b>جدید</b> رو بفرست تا به لیستِ فعلی <b>اضافه</b> بشن "
                "(هر عبارت توی یک خطِ جدا). می‌تونه یه جمله‌ی کامل، یه کلمه یا یه ایموجی باشه.\n\n"
                "مثال:\n<code>عضو کانال ما بشید\n@channel_ads\n🔥</code>"
            )
        else:
            txt = (
                "🧹 <b>لیستِ عبارت‌هایی که باید از متنِ پست حذف بشن</b>\n\n"
                "کلِ لیستِ جدید رو بفرست؛ <b>هر عبارت توی یک خطِ جدا</b>. هر خط می‌تونه یه "
                "جمله‌ی کامل، یه کلمه، یه منشن یا یه ایموجی باشه.\n"
                "برای خالی‌کردنِ لیست یک نقطه «.» بفرست.\n\n"
                "نکته: نیم‌فاصله/فاصله و «ی/ي» و «ک/ك» خودکار یکسان در نظر گرفته می‌شن، پس "
                "لازم نیست دقیقاً مثلِ متنِ پست تایپ کنی.\n\n"
                f"لیستِ فعلی:\n<code>{_esc(current) if current else '(خالی)'}</code>"
            )
        await safe_edit(query, txt, kb.cancel_input_menu(), ParseMode.HTML)
        return

    if data == "adf:phrases_clear":
        owner = _settings_owner(uid)
        db.setting_set("ad_filter_remove_phrases", "", owner_user_id=owner)
        await query.answer("🗑 لیستِ عبارت‌های حذفی خالی شد.", show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:reset_keywords":
        owner = _settings_owner(uid)
        db.setting_set("ad_filter_keywords", "", owner_user_id=owner)
        await query.answer("✅ کلیدواژه‌ها به پیش‌فرض برگشت.", show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:min_mentions":
        _set_awaiting(context, "adf_min_mentions", "menu:adfilter")
        await safe_edit(
            query,
            "از چند منشنِ کانالِ دیگه (توی یک پست) به بالا مشکوک به تبلیغاتی باشه؟ "
            "یه عدد صحیح بفرست (پیشنهاد: 3):",
            kb.cancel_input_menu(),
        )
        return

    if data == "adf:min_links":
        _set_awaiting(context, "adf_min_links", "menu:adfilter")
        await safe_edit(
            query,
            "از چند لینک (توی یک پست) به بالا مشکوک به تبلیغاتی باشه؟ یه عدد صحیح بفرست (پیشنهاد: 2):",
            kb.cancel_input_menu(),
        )
        return

    if data == "adf:threshold":
        _set_awaiting(context, "adf_threshold", "menu:adfilter")
        await safe_edit(
            query,
            "حساسیتِ کلیِ تشخیص (آستانه‌ی امتیاز) رو بفرست - عددِ کمتر یعنی سخت‌گیرانه‌تر "
            "(پست‌های بیشتری تبلیغاتی تشخیص داده میشن)، عددِ بیشتر یعنی محتاطانه‌تر. "
            "پیشنهاد: 4:",
            kb.cancel_input_menu(),
        )
        return

    if data == "adf:feedback_stats" or data.startswith("adf:fbstats_page:"):
        # آمارِ فیدبکِ ادمین به فیلترِ تبلیغات، به تفکیکِ کانال - نگاه کن به
        # database.get_ad_feedback_channel_stats و بردارِ کاملِ توضیحات توی
        # ad_feedback_report.py. owner همیشه دقیقاً مالِ همین کاربر/ادمینه؛
        # هیچ‌وقت با آمارِ کاربرِ دیگه‌ای قاطی نمی‌شه.
        owner = _settings_owner(uid)
        page = 0
        if data.startswith("adf:fbstats_page:"):
            try:
                page = int(data.split(":")[2])
            except (IndexError, ValueError):
                page = 0
        stats = db.get_ad_feedback_channel_stats(owner_user_id=owner)
        await safe_edit(
            query,
            ad_feedback_report.overview_text(stats),
            kb.ad_feedback_stats_menu(owner_user_id=owner, page=page),
            ParseMode.HTML,
        )
        return

    if data.startswith("adf:fbstats_ch:"):
        try:
            cid = int(data.split(":")[2])
        except (IndexError, ValueError):
            cid = None
        if cid is None or not _own_channel_or_deny(uid, cid):
            await query.answer("⛔️ این کانال متعلق به شما نیست.", show_alert=True)
            return
        owner = _settings_owner(uid)
        stats = db.get_ad_feedback_channel_stats(owner_user_id=owner)
        stat = next((s for s in stats if s["channel_id"] == cid), None)
        if not stat:
            await query.answer("این کانال هنوز فیدبکی نداره.", show_alert=True)
            return
        posts = db.get_ad_feedback_posts(owner_user_id=owner, channel_id=cid)
        await safe_edit(
            query,
            ad_feedback_report.channel_detail_text(stat, posts),
            kb.ad_feedback_channel_menu(cid),
            ParseMode.HTML,
        )
        return

    if data == "adf:fbstats_excel" or data.startswith("adf:fbstats_excel_ch:"):
        cid = None
        if data.startswith("adf:fbstats_excel_ch:"):
            try:
                cid = int(data.split(":")[2])
            except (IndexError, ValueError):
                cid = None
            if cid is None or not _own_channel_or_deny(uid, cid):
                await query.answer("⛔️ این کانال متعلق به شما نیست.", show_alert=True)
                return
        owner = _settings_owner(uid)
        xlsx_bytes = ad_feedback_report.build_ad_feedback_workbook(
            owner_user_id=owner, channel_id=cid, scope_label=_fb_scope_label(uid),
        )
        if not xlsx_bytes:
            await query.answer("هنوز فیدبکی برایِ ساختِ گزارش وجود نداره.", show_alert=True)
            return
        # نکته: هر callback_query فقط یک‌بار می‌تونه answer بشه (نگاه کن به
        # توضیحِ callback_router بالایِ همین فایل)؛ برایِ همین اول فایل کاملاً
        # ساخته می‌شه و فقط اگه واقعاً می‌خوایم ادامه بدیم (داده وجود داره)
        # این‌جا answer می‌کنیم - نه قبل و بعدِ چکِ بالا هردو.
        await query.answer("⏳ در حالِ ارسالِ فایلِ اکسل...")
        fname = f"ad_feedback_report_{now_jalali().strftime('%Y%m%d_%H%M')}.xlsx"
        await context.bot.send_document(
            chat_id=query.from_user.id,
            document=xlsx_bytes,
            filename=fname,
            caption="📊 گزارشِ کاملِ فیدبکِ فیلترِ تبلیغات (به‌تفکیکِ کانال + جزئیاتِ هر پست).",
        )
        return

    if data == "adf:test":
        _set_awaiting(context, "adf_test", "menu:adfilter")
        await safe_edit(
            query,
            "🧪 یک متنِ نمونه (مثلاً کپشنِ یه پستِ واقعی) بفرست تا بهت بگم با تنظیماتِ "
            "فعلی، تبلیغاتی تشخیص داده میشه یا نه و چرا.",
            kb.cancel_input_menu(),
        )
        return

    if data == "adf:file_toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("file_filter_enabled", True, owner_user_id=owner)
        db.setting_set("file_filter_enabled", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ فیلترِ فایل/اپ " + ("فعال شد." if new_val else "غیرفعال شد."), show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    if data == "adf:file_ext":
        owner = _settings_owner(uid)
        _set_awaiting(context, "adf_file_ext", "menu:adfilter")
        current = db.setting_get("file_filter_extensions", "", owner_user_id=owner) or ad_filter.default_extensions_text()
        await safe_edit(
            query,
            "📝 لیستِ پسوندهایی که باید مسدود بشن رو با ویرگول (,) از هم جدا بفرست "
            "(بدونِ نقطه، مثلاً apk, exe). لیستِ فعلی:\n\n"
            f"<code>{_esc(current)}</code>\n\n"
            "می‌تونی این متن رو کپی، ویرایش و دوباره کامل بفرستی.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    if data == "adf:file_reset_ext":
        owner = _settings_owner(uid)
        db.setting_set("file_filter_extensions", "", owner_user_id=owner)
        await query.answer("✅ پسوندها به پیش‌فرض برگشت.", show_alert=True)
        await safe_edit(query, _ad_filter_text(owner), kb.ad_filter_menu(owner), ParseMode.HTML)
        return

    # ==================== امضای پایان پست ====================
    if data == "footer:toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("footer_enabled", True, owner_user_id=owner)
        db.setting_set("footer_enabled", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ امضا " + ("فعال شد." if new_val else "غیرفعال شد."), show_alert=True)
        await safe_edit(query, _footer_text(owner), kb.footer_menu(owner), ParseMode.HTML)
        return

    if data == "footer:handle":
        _set_awaiting(context, "footer_handle", "menu:footer")
        await safe_edit(query, "یوزرنیم کانالت رو بدون @ بفرست (مثلا mrliq):", kb.cancel_input_menu())
        return

    if data == "footer:url":
        _set_awaiting(context, "footer_url", "menu:footer")
        await safe_edit(
            query,
            "لینک کامل کانال رو بفرست (اختیاری - اگه خالی بذاری از یوزرنیم ساخته میشه):",
            kb.cancel_input_menu(),
        )
        return

    if data == "footer:template":
        _set_awaiting(context, "footer_template", "menu:footer")
        await safe_edit(
            query,
            "قالب متن امضا رو بفرست. از <code>{handle}</code> برای جای یوزرنیم استفاده کن.\n"
            "پیشفرض: <code>@{handle}</code>",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    if data == "footer:mode_menu":
        owner = _settings_owner(uid)
        text = (
            "🗂 <b>حالتِ امضای پایانِ پست</b>\n\n"
            "🧩 <b>لینکِ ساده</b>: فقط یک @یوزرنیمِ کلیک‌پذیر (رفتارِ پیش‌فرض).\n\n"
            "📝 <b>متنِ کاملاً دلخواه</b>: هرچی خودت بخوای بنویسی - چند خط، توضیحات، "
            "قیمت، شماره تماس، هرچی - دقیقاً همون‌طوری (حتی با بولد/لینکِ خودِ تلگرام) "
            "زیرِ هر پست میاد."
        )
        await safe_edit(query, text, kb.footer_mode_menu(owner), ParseMode.HTML)
        return

    if data.startswith("footer:setmode:"):
        mode = data.split(":")[2]
        if mode not in ("link", "custom"):
            return
        owner = _settings_owner(uid)
        db.setting_set("footer_mode", mode, owner_user_id=owner)
        await query.answer("✅ حالتِ امضا تغییر کرد.", show_alert=True)
        await safe_edit(query, _footer_text(owner), kb.footer_menu(owner), ParseMode.HTML)
        return

    if data == "footer:custom_text":
        _set_awaiting(context, "footer_custom_text", "menu:footer")
        await safe_edit(
            query,
            "📝 متنِ دلخواهت رو بفرست - چند خط می‌تونه باشه، هر توضیحی که بخوای، حتی با "
            "بولد/ایتالیک/لینک (از همون قابلیتِ فرمت‌دهیِ خودِ تلگرام موقعِ تایپ استفاده کن).\n\n"
            "اگه بخوای یه‌جای متن لینکِ کلیکیِ کانالت هم باشه، <code>{link}</code> بذار؛ "
            "اگه فقط منشنِ ساده (بدونِ لینک) کافیه، <code>{handle}</code> بذار.\n"
            "برای پاک کردنِ کاملِ این متن، فقط یک نقطه (.) بفرست.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    # ==================== قالب‌بندی متن ====================
    if data == "fmt:preserve_toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("preserve_formatting", True, owner_user_id=owner)
        db.setting_set("preserve_formatting", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ بروزرسانی شد.", show_alert=True)
        await safe_edit(query, _format_text(owner), kb.format_menu(owner), ParseMode.HTML)
        return

    if data == "fmt:removelinks_toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("remove_source_links", True, owner_user_id=owner)
        db.setting_set("remove_source_links", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ بروزرسانی شد.", show_alert=True)
        await safe_edit(query, _format_text(owner), kb.format_menu(owner), ParseMode.HTML)
        return

    if data == "fmt:maxlen":
        owner = _settings_owner(uid)
        _set_awaiting(context, "fmt_maxlen", "menu:format")
        await safe_edit(query, "حداکثر طول کپشن رو بفرست (حداکثر مجاز تلگرام: 1024):",
                         kb.cancel_input_menu())
        return

    if data == "fmt:minlen_toggle":
        owner = _settings_owner(uid)
        new_val = not db.setting_get_bool("min_content_filter_enabled", True, owner_user_id=owner)
        db.setting_set("min_content_filter_enabled", "1" if new_val else "0", owner_user_id=owner)
        await query.answer("✅ بروزرسانی شد.", show_alert=True)
        await safe_edit(query, _format_text(owner), kb.format_menu(owner), ParseMode.HTML)
        return

    if data == "fmt:minwords":
        _set_awaiting(context, "fmt_minwords", "menu:format")
        await safe_edit(
            query,
            "پست‌های کاملاً متنی (بدون هیچ عکس/ویدیو/فایلی) که کمتر از چند کلمه باشن "
            "اصلاً ارسال نشن؟ یه عدد صحیح بفرست (پیشنهاد: 4):",
            kb.cancel_input_menu(),
        )
        return

    # ==================== زمان‌بندی سراسری ====================
    if data == "sched:toggle":
        new_val = not db.get_bool("scheduler_active", True)
        db.set_setting("scheduler_active", "1" if new_val else "0")
        await query.answer("✅ " + ("زمان‌بند فعال شد." if new_val else "زمان‌بند متوقف شد."), show_alert=True)
        await safe_edit(query, "📡 <b>کانال‌های مبدأ</b>\n\nروی هرکدوم بزن برای مدیریت:",
                         kb.sources_menu(_owner_scope(uid)), ParseMode.HTML)
        return

    # ==================== پیش‌نمایش واترمارک ====================
    if data == "wm:preview":
        owner = _settings_owner(uid)
        await query.answer("⏳ در حال ساخت پیش‌نمایش...")
        settings = {
            "watermark_enabled": True,
            "wm_tg_enabled": True,
            "wm_ig_enabled": False,
        }
        for k in ("text", "position", "color_mode", "color_a", "color_b", "bg_opacity", "font_size", "margin", "badge_scale"):
            settings[f"wm_tg_{k}"] = db.setting_get(f"wm_tg_{k}", owner_user_id=owner)
        from ..watermark import render_preview
        img = await concurrency.run_heavy(render_preview, settings)
        await context.bot.send_photo(
            chat_id=query.from_user.id,
            photo=img,
            caption="🖼 پیش‌نمایش واترمارک تلگرام با تنظیمات فعلی"
        )
        return

    # ==================== منوهای جدید برای قابلیت‌های ۱۰ گانه ====================
    # مانیتورینگ منابع
    if data.startswith("res:"):
        from ..resource_monitor import ResourceMonitor, resource_stats_text
        action = data.split(":")[1]
        if action == "stats":
            text = resource_stats_text(ResourceMonitor.get_stats())
            await safe_edit(query, text, kb.resource_menu(), ParseMode.HTML)
            return
        if action == "toggle":
            settings = ResourceMonitor.get_settings()
            settings["enabled"] = not settings.get("enabled", True)
            ResourceMonitor.save_settings(settings)
            await query.answer("✅ وضعیت مانیتورینگ تغییر کرد.", show_alert=True)
            await safe_edit(query, "🖥 مانیتورینگ سرور", kb.resource_menu())
            return
        if action == "set_cpu":
            _set_awaiting(context, "res_cpu", "menu:resources")
            await safe_edit(query, "آستانه CPU (درصد، مثلاً 80):", kb.cancel_input_menu())
            return
        if action == "set_ram":
            _set_awaiting(context, "res_ram", "menu:resources")
            await safe_edit(query, "آستانه RAM (درصد، مثلاً 80):", kb.cancel_input_menu())
            return
        if action == "set_disk":
            _set_awaiting(context, "res_disk", "menu:resources")
            await safe_edit(query, "آستانه دیسک (درصد، مثلاً 85):", kb.cancel_input_menu())
            return
        if action == "set_chat":
            _set_awaiting(context, "res_chat", "menu:resources")
            await safe_edit(query, "آیدی عددی کانال/چت برای ارسال هشدارها:", kb.cancel_input_menu())
            return
        if action == "logs":
            _set_awaiting(context, "logs_filter", "menu:resources")
            await safe_edit(query, "فیلتر لاگ‌ها را انتخاب کنید:", kb.logs_filter_menu())
            return

    # بکاپ
    if data.startswith("backup:"):
        from ..backup_manager import BackupManager
        action = data.split(":")[1]
        if action == "toggle":
            settings = BackupManager.get_settings()
            settings["enabled"] = not settings.get("enabled", True)
            BackupManager.save_settings(settings)
            await query.answer("✅ وضعیت بکاپ تغییر کرد.", show_alert=True)
            await safe_edit(query, "📦 مدیریت بکاپ", kb.backup_menu())
            return
        if action == "set_time":
            _set_awaiting(context, "backup_time", "menu:backup")
            await safe_edit(
                query,
                "ساعتِ بکاپ رو به فرمتِ ۱۲ساعته وارد کن (بین 1:00 تا 12:59)، مثلاً 03:00 - "
                "بعدش می‌تونی مشخص کنی صبحه (AM) یا بعدازظهر/شب (PM):",
                kb.cancel_input_menu(),
            )
            return
        if action == "ampm":
            _, _, ampm, hh, mm = data.split(":")
            from ..backup_manager import to_24h, format_backup_time_12h
            time_24h = to_24h(int(hh), int(mm), ampm)
            settings = BackupManager.get_settings()
            settings["time"] = time_24h
            BackupManager.save_settings(settings)
            await query.answer("✅ ساعت بکاپ ذخیره شد.", show_alert=True)
            await safe_edit(
                query,
                f"✅ ساعتِ بکاپِ روزانه روی <b>{format_backup_time_12h(time_24h)}</b> (وقت تهران) تنظیم شد.",
                kb.backup_menu(),
                ParseMode.HTML,
            )
            return
        if action == "set_chat":
            _set_awaiting(context, "backup_chat", "menu:backup")
            await safe_edit(query, "آیدی عددی کانال یا چت برای ارسال بکاپ را وارد کنید:", kb.cancel_input_menu())
            return
        if action == "set_password":
            _set_awaiting(context, "backup_password_set", "menu:backup")
            await safe_edit(
                query,
                "🔑 رمزِ عبورِ بکاپ را وارد کنید (حداقل ۶ کاراکتر).\n\n"
                "این رمز از این به بعد برایِ رمزنگاریِ همه‌ی بکاپ‌های جدید (خودکار/فوری) استفاده می‌شه. "
                "موقعِ <b>بازیابی</b> - حتی روی همینِ ربات، و حتی روی یک ربات/توکن/اکانتِ کاملاً دیگر - "
                "باید همینِ رمز دوباره وارد بشه.\n\n"
                "⚠️ این رمز رو جایی امن یادداشت کن؛ اگه گم بشه، بکاپ‌های گرفته‌شده با این رمز دیگه قابلِ بازیابی نیستن.",
                kb.cancel_input_menu(),
                ParseMode.HTML,
            )
            return
        if action == "now":
            await query.answer("⏳ در حال ایجاد بکاپ...")
            encrypted = BackupManager.create_backup()
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=encrypted,
                filename=f"backup_{now_jalali().strftime('%Y%m%d_%H%M')}.backup",
                caption=f"📦 بکاپ فوری - {format_jalali_datetime(now_jalali())}"
            )
            return
        if action == "restore":
            _set_awaiting(context, "backup_restore", "menu:backup")
            await safe_edit(query, "لطفاً فایل بکاپ را ارسال کنید.", kb.cancel_input_menu())
            return

    # کانال عمومی گزارش‌ها
    if data.startswith("pub:"):
        action = data.split(":")[1]
        if action == "set_chat":
            _set_awaiting(context, "pub_chat", "menu:public_channel")
            await safe_edit(query, "آیدی عددی کانال عمومی گزارش‌ها را وارد کنید:", kb.cancel_input_menu())
            return

    # تنظیمات اعلان‌های ادمین (تفکیک اعلان‌ها - قابلیت ۸)
    if data.startswith("notif:"):
        from ..notification_manager import NotificationManager
        action = data.split(":")[1]
        if action == "menu":
            await safe_edit(
                query,
                "🔔 <b>تنظیمات اعلان‌های ادمین</b>\n\n"
                "اگر یک کانال اختصاصی تنظیم کنید، اعلان‌های مربوط به ری‌پست‌ها و خطاهای "
                "کانال‌های خودِ ادمین اصلی به آنجا ارسال می‌شود؛ در غیر این صورت همین‌جا در ربات.\n"
                "اعلان‌های کاربران عادی هیچ‌گاه به کانال‌های تایید آن‌ها نمی‌رود.",
                kb.notification_menu(),
                ParseMode.HTML,
            )
            return
        if action == "toggle":
            s = NotificationManager.get_settings()
            s["enabled"] = not s.get("enabled", True)
            NotificationManager.save_settings(s)
            await query.answer("✅ وضعیت اعلان‌ها تغییر کرد.", show_alert=True)
            await safe_edit(query, "🔔 <b>تنظیمات اعلان‌های ادمین</b>", kb.notification_menu(), ParseMode.HTML)
            return
        if action == "setchat":
            _set_awaiting(context, "notif_chat", "menu:resources")
            await safe_edit(query, "آیدی عددی کانال اختصاصی اعلان‌های ادمین را وارد کنید:", kb.cancel_input_menu())
            return
        if action == "clearchat":
            s = NotificationManager.get_settings()
            s["chat_id"] = None
            NotificationManager.save_settings(s)
            await query.answer("🧹 کانال اختصاصی حذف شد؛ اعلان‌ها در خود ربات ارسال می‌شود.", show_alert=True)
            await safe_edit(query, "🔔 <b>تنظیمات اعلان‌های ادمین</b>", kb.notification_menu(), ParseMode.HTML)
            return

    # ==================== سیستمِ مدیریتِ API هوش مصنوعی (۱۶ سرویس) ====================
    if data.startswith("aiapi:"):
        from .ai_providers_menu import handle_callback as _aiapi_callback
        await _aiapi_callback(data, query, context, uid)
        return

    if data == "ai:web_search":
        from ..web_search import WebSearchSettings
        await safe_edit(
            query,
            "🔎 <b>جست‌وجویِ وب (فقط SerpAPI)</b>\n"
            f"{DIVIDER}\n"
            f"{WebSearchSettings.status_text()}\n\n"
            "یک ورودیِ واحد: کافیه بنویسی چی می‌خوای.\n"
            "• اگه اولش «عکس/تصویر/کاور...» باشه → فقط عکس (بدونِ توضیح).\n"
            "• اگه «خبر/اخبار» باشه → خبر با لینکِ سایت و جدیدترین‌ها بالا.\n"
            "• در غیرِ این‌صورت → عکس.",
            kb.ai_web_search_menu(),
            ParseMode.HTML,
        )
        return

    if data == "ai:web_search_go":
        _set_awaiting(context, "ai_web_search", "menu:ai_services")
        await safe_edit(
            query,
            "✍️ چی می‌خوای؟ مثال:\n"
            "• «عکس گربه‌ی ایرانی»\n"
            "• «اخبار هوش مصنوعی»\n"
            "بنویس و بفرست:",
            kb.cancel_input_menu(),
        )
        return

    if data == "ai:web_settings":
        from ..web_search import WebSearchSettings
        await safe_edit(
            query,
            "⚙️ <b>تنظیمِ کلیدهایِ SerpAPI</b>\n"
            f"{DIVIDER}\n"
            f"{WebSearchSettings.status_text()}\n\n"
            "🔑 تا ۵ کلیدِ SerpAPI می‌تونی وارد کنی؛ بعد از هر سرچ به‌طورِ خودکار "
            "بینِ کلیدها می‌چرخه تا سهمیه‌ی رایگانِ همه‌شون یکنواخت مصرف بشه.\n"
            "کلید رو از پنلِ serpapi.com بگیر (رایگان).",
            kb.ai_web_settings_menu(),
            ParseMode.HTML,
        )
        return

    if data.startswith("ai:web_set:"):
        idx = data.split(":", 2)[2]
        _set_awaiting(context, f"ai_web_setkey:{idx}", "menu:ai_services")
        await safe_edit(
            query,
            f"✍️ کلیدِ SerpAPI شماره‌ی {int(idx)+1} رو بفرست (برایِ پاک‌کردن، یک فاصله بفرست):",
            kb.cancel_input_menu(),
        )
        return

    if data == "ai:web_clear":
        from ..web_search import WebSearchSettings
        WebSearchSettings.clear_all()
        await query.answer("✅ همه‌ی کلیدها پاک شدن.")
        await safe_edit(
            query,
            f"⚙️ <b>تنظیمِ کلیدهایِ SerpAPI</b>\n{DIVIDER}\n{WebSearchSettings.status_text()}",
            kb.ai_web_settings_menu(),
            ParseMode.HTML,
        )
        return

    # ابزارهای مستقل هوش مصنوعی (ترجمه/خلاصه/بازنویسی/اصلاح/هشتگ/پرامپت‌نویسِ هر متنِ دلخواه)
    if data == "ai:translate":
        await safe_edit(
            query,
            "🌐 <b>ترجمه‌ی هوشمند</b>\n"
            f"{DIVIDER}\n"
            "اول زبانِ مبدأ رو خودکار تشخیص می‌دم، بعد بر اساسِ انتخابِ تو ترجمه می‌کنم:",
            kb.ai_translate_lang_menu(),
            ParseMode.HTML,
        )
        return

    if data.startswith("ai:translate_lang:"):
        lang = data.split(":")[2]
        _set_awaiting(context, f"ai_tool_translate:{lang}", "menu:ai_services")
        await safe_edit(query, "✍️ متنی که می‌خوای ترجمه بشه رو بفرست:", kb.cancel_input_menu())
        return

    if data == "ai:summarize":
        await safe_edit(
            query,
            "📝 <b>خلاصه‌سازیِ چندسطحی</b>\n"
            f"{DIVIDER}\n"
            "چقدر خلاصه می‌خوای؟",
            kb.ai_summarize_level_menu(),
            ParseMode.HTML,
        )
        return

    if data.startswith("ai:summarize_level:"):
        level = data.split(":")[2]
        _set_awaiting(context, f"ai_tool_summarize:{level}", "menu:ai_services")
        await safe_edit(query, "✍️ متنی که می‌خوای خلاصه بشه رو بفرست:", kb.cancel_input_menu())
        return

    if data in ("ai:rewrite", "ai:fix_text", "ai:hashtags",
                "ai:caption", "ai:title", "ai:auto_reply", "ai:analyze_text"):
        tool = {
            "ai:rewrite": "rewrite", "ai:fix_text": "fix_text", "ai:hashtags": "hashtags",
            "ai:caption": "generate_caption", "ai:title": "generate_title",
            "ai:auto_reply": "auto_reply", "ai:analyze_text": "analyze_text",
        }[data]
        labels = {
            "rewrite": "بازنویسیِ خلاقانه",
            "fix_text": "اصلاحِ املا و گرامر",
            "hashtags": "تولیدِ هشتگ",
            "generate_caption": "تولیدِ کپشن",
            "generate_title": "تولیدِ عنوان",
            "auto_reply": "پاسخِ خودکار",
            "analyze_text": "تحلیلِ متن",
        }
        _set_awaiting(context, f"ai_tool_{tool}", "menu:ai_services")
        await safe_edit(query, f"✍️ متنی که می‌خوای «{labels[tool]}» بشه رو بفرست:", kb.cancel_input_menu())
        return

    if data == "ai:prompt_writer":
        _set_awaiting(context, "ai_tool_prompt_writer", "menu:ai_services")
        await safe_edit(
            query,
            "🧠 <b>پرامپت‌نویسِ تصویر</b>\n"
            f"{DIVIDER}\n"
            "ایده‌ت رو کوتاه بنویس (مثلاً «یک گربه‌ی فضانورد روی کهکشان»)؛ یک پرامپتِ حرفه‌ایِ انگلیسی، "
            "دقیقاً طبقِ اصولِ Prompt Engineering، براش می‌سازم که مستقیم توی هر ابزارِ تولیدِ تصویری قابلِ استفاده‌ست.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    # ==================== تغییرِ استایلِ عکس ====================
    if data == "ai:style_image":
        context.user_data.pop("ai_style_image_bytes", None)
        _set_awaiting(context, "ai_style_photo", "menu:ai_services")
        await safe_edit(
            query,
            "🎨 <b>تغییرِ استایلِ عکس</b>\n"
            f"{DIVIDER}\n"
            "اول خودِ عکس رو بفرست، بعد از بینِ استایل‌ها انتخاب کن.\n"
            "⚠️ این قابلیت فقط با کلیدِ <b>Gemini</b> فعال (توی «مدیریتِ API هوش مصنوعی») کار می‌کنه.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    if data.startswith("ai:style_preset:"):
        preset = data.split(":")[2]
        image_bytes = context.user_data.get("ai_style_image_bytes")
        if not image_bytes:
            await query.answer("❌ اول باید عکس رو بفرستی.", show_alert=True)
            return
        if preset == "custom":
            _set_awaiting(context, "ai_tool_style_custom", "menu:ai_services")
            await safe_edit(query, "✍️ استایلِ دلخواهت رو توضیح بده (مثلاً «تبدیل به نقاشیِ آبرنگِ رمانتیک»):", kb.cancel_input_menu())
            return

        style_labels = {
            "oil": "a classical oil painting, visible brush strokes, rich textured canvas",
            "sketch": "a detailed black and white pencil sketch, hand-drawn shading",
            "cyberpunk": "a cyberpunk style with neon lights, futuristic city colors, high contrast",
            "anime": "a Japanese anime / manga illustration style, clean lines, vibrant colors",
            "3dcartoon": "a 3D cartoon render style, Pixar-like, soft lighting, playful colors",
            "vintage": "a vintage retro photograph style, warm faded colors, film grain, 1970s look",
        }
        instruction = (
            "Transform this image into " + style_labels.get(preset, preset) +
            ". Keep the main subject, composition and identity recognizable; only change the artistic style."
        )
        await query.answer("⏳ در حال تغییرِ استایل...")
        from ..image_router import ImageRouter
        router = ImageRouter(owner_user_id=scope_owner(uid))
        try:
            result = await router.edit_image(image_bytes, instruction)
        finally:
            await router.close()
        if not result:
            await query.message.reply_text(
                "❌ تغییرِ استایل انجام نشد. مطمئن شو کلیدِ Gemini در «مدیریتِ API هوش مصنوعی» فعال و معتبره.",
                reply_markup=kb.ai_services_menu(),
            )
            return
        await query.message.reply_photo(photo=result, caption="🎨 استایلِ عکس تغییر کرد.", reply_markup=kb.ai_services_menu())
        return

    # ==================== تولید تصویر با هوش مصنوعی ====================
    if data == "ai:image":
        _set_awaiting(context, "ai_image", "menu:ai_services")
        await safe_edit(
            query,
            "🖼 <b>تولید تصویر با هوش مصنوعی</b>\n"
            f"{DIVIDER}\n"
            "توضیح تصویری که می‌خوای ساخته بشه رو بنویس و بفرست "
            "(هر چه دقیق‌تر و با جزئیات بیشتر بنویسی، نتیجه بهتره).\n"
            "⏳ ساخت تصویر ممکنه چند ثانیه تا حدود یک دقیقه طول بکشه.",
            kb.cancel_input_menu(),
            ParseMode.HTML,
        )
        return

    # لاگ‌ها
    if data.startswith("logs:"):
        action = data.split(":")[1]
        if action == "all":
            logs = db.get_system_logs(limit=50)
        elif action == "errors":
            logs = db.get_system_logs(limit=50, severity="ERROR")
        elif action == "success":
            logs = db.get_system_logs(limit=50, severity="INFO")
        elif action == "by_channel":
            _set_awaiting(context, "logs_channel", "menu:resources")
            await safe_edit(query, "آیدی کانال مبدأ را وارد کنید:", kb.cancel_input_menu())
            return
        elif action == "by_destination":
            _set_awaiting(context, "logs_destination", "menu:resources")
            await safe_edit(query, "آیدی کانال مقصد را وارد کنید:", kb.cancel_input_menu())
            return
        elif action == "by_user":
            _set_awaiting(context, "logs_user", "menu:resources")
            await safe_edit(query, "آیدی کاربر را وارد کنید:", kb.cancel_input_menu())
            return
        else:
            return

        if not logs:
            await safe_edit(query, "📋 هیچ لاگی یافت نشد.", kb.logs_filter_menu())
            return

        from ..utils import build_logs_message
        text = build_logs_message("📋 <b>لاگ‌های سیستم</b>\n" + DIVIDER, logs)
        await safe_edit(query, text, kb.logs_filter_menu(), ParseMode.HTML)
        return

    # ==================== واترمارکِ دلخواهِ دستی روی یک پستِ خاص ====================
    if data.startswith("pp:view:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row:
            await query.answer("این پست دیگه پیدا نشد.", show_alert=True)
            return
        # فیکس: برخلافِ همه‌ی خواهروبرادرهای pp:*، این هندلر تا الان هیچ چکِ
        # مالکیت/دسترسی نداشت — هر pidِ موجود رو بدونِ بررسی می‌پذیرفت. حالا
        # مثلِ approve/reject همون _pending_post_denial رو رد می‌کنه.
        _denial = _pending_post_denial(uid, row, "view", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        from ..poster import pending_post_flags
        has_video, has_photo, show_restore, ad_flagged, ad_feedback = pending_post_flags(row)
        markup = kb.pending_post_menu(
            pid, has_video=has_video, has_photo=has_photo, show_restore=show_restore,
            ad_flagged=ad_flagged, ad_feedback=ad_feedback,
        )
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:  # noqa: BLE001
            pass
        await query.answer()
        return

    if data.startswith("pp:wm_reset:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگه در دسترس نیست.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        from ..poster import reset_pending_wm_picks
        reset_pending_wm_picks(pid)
        await query.answer("♻️ همه‌ی واترمارک‌های دستی از رویِ این پست پاک شدن.")
        await safe_edit(query, "🏷 واترمارک‌های دلخواهِ این پست:", kb.pending_wm_menu(pid, owner_user_id=row["owner_user_id"]))
        return

    if data.startswith("pp:wm_toggle:"):
        parts = data.split(":")
        pid, wm_id = int(parts[2]), int(parts[3])
        row = db.get_pending_post(pid)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگه در دسترس نیست.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        from ..poster import apply_pending_wm_pick, remove_pending_wm_pick
        _base, picks = db.get_pending_wm_pick(pid)
        already_picked = any(p.get("watermark_id") == wm_id for p in picks)
        await query.answer("⏳ در حالِ اعمالِ واترمارک...")
        if already_picked:
            await remove_pending_wm_pick(context.bot, pid, wm_id)
        else:
            await apply_pending_wm_pick(context.bot, pid, wm_id)
        await safe_edit(query, "🏷 واترمارک‌های دلخواهِ این پست:", kb.pending_wm_menu(pid, owner_user_id=row["owner_user_id"]))
        return

    if data.startswith("pp:wm:"):
        pid = int(data.split(":")[2])
        row = db.get_pending_post(pid)
        if not row:
            await query.answer("این پست دیگه پیدا نشد.", show_alert=True)
            return
        _denial = _pending_post_denial(uid, row, "edit", chat_id=query.message.chat.id if query.message else None)
        if _denial:
            await query.answer(_denial, show_alert=True)
            return
        await safe_edit(query, "🏷 واترمارک‌های دلخواهِ این پست:", kb.pending_wm_menu(pid, owner_user_id=row["owner_user_id"]))
        return

    # ==================== هوش مصنوعی برای پست‌های در صف ====================
    if data.startswith("pp:translate:") or data.startswith("pp:summarize:") or data.startswith("pp:rewrite:"):
        parts = data.split(":")
        action = parts[1]
        pending_id = int(parts[2])
        row = db.get_pending_post(pending_id)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگر در دسترس نیست.", show_alert=True)
            return

        if not is_admin(uid):
            user = db.get_user_by_telegram_id(uid)
            if not user or user["id"] != row["owner_user_id"]:
                await query.answer("شما اجازه ویرایش این پست را ندارید.", show_alert=True)
                return
            if not db.get_permissions(user["id"]).get("pp_edit", True):
                await query.answer("دسترسی ویرایش برای شما فعال نیست.", show_alert=True)
                return

        caption = row["caption_html"] or ""
        if not caption.strip():
            await query.answer("این پست متنی ندارد.", show_alert=True)
            return

        await query.answer("⏳ در حال پردازش با هوش مصنوعی...")

        from ..ai_router import AIRouter
        router = AIRouter(owner_user_id=row["owner_user_id"])
        try:
            if action == "translate":
                new_caption = await router.translate_to_persian(caption)
                result_msg = "🌐 ترجمه به فارسی انجام شد."
            elif action == "summarize":
                new_caption = await router.summarize(caption)
                result_msg = "📝 خلاصه‌سازی انجام شد."
            else:
                new_caption = await router.rewrite(caption)
                result_msg = "🔄 بازنویسی خلاقانه انجام شد."
        except Exception as e:
            log.exception("خطا در پردازش AI: %s", e)
            await query.answer("خطا در پردازش، دوباره تلاش کنید.", show_alert=True)
            return
        finally:
            await router.close()

        # همون فیکس: خروجیِ هوش مصنوعی (ترجمه/خلاصه/بازنویسی) هم مثلِ ویرایشِ
        # دستی باید از ensure_rtl_lines رد بشه؛ وگرنه ترجمه‌ی فارسیِ تازه‌تولیدشده
        # نه علامتِ راست‌چین می‌گیره نه نرمال‌سازیِ فاصله‌ی بینِ quote.
        if new_caption:
            new_caption = ensure_rtl_lines(new_caption)
        db.set_pending_caption(pending_id, new_caption)

        # باگِ قبلی: این‌جا send_pending_preview صدا زده می‌شد که همیشه یک پیامِ
        # کاملاً *جدید* می‌فرسته (به چتِ خصوصیِ ادمین/مالک) و پیامِ فعلی‌ای که
        # کاربر داشت روش دکمه می‌زد دست‌نخورده می‌موند - یعنی کپشنِ همون پست
        # همون لحظه آپدیت نمی‌شد. حالا مستقیماً کپشن/متنِ همین پیام ویرایش
        # می‌شه تا تغییر بلافاصله همون‌جا دیده بشه.
        display_caption = new_caption or "(بدون متن)"
        flag_reason = row["flag_reason"] if "flag_reason" in row.keys() else ""
        if flag_reason:
            display_caption = f"{flag_reason}\n\n{display_caption}"

        markup = query.message.reply_markup if query.message else None
        try:
            if query.message and (query.message.photo or query.message.video or query.message.document
                                   or query.message.animation or query.message.audio):
                await query.edit_message_caption(
                    caption=display_caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                )
            else:
                await query.edit_message_text(
                    text=display_caption, parse_mode=ParseMode.HTML, reply_markup=markup,
                )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                log.warning("ویرایشِ درجای کپشن بعدِ پردازشِ AI ناموفق بود، به‌جاش پیش‌نمایشِ جدید فرستاده می‌شه: %s", e)
                from ..poster import send_pending_preview
                await send_pending_preview(context.bot, pending_id)

        await query.answer(result_msg)
        return

    # ==================== بازگردوندنِ کپشن به نسخه‌ی اصلی (قبل از AI/ویرایش) ====================
    if data.startswith("pp:restorecap:"):
        pending_id = int(data.split(":")[2])
        row = db.get_pending_post(pending_id)
        if not row or row["status"] != "pending":
            await query.answer("این پست دیگر در دسترس نیست.", show_alert=True)
            return

        if not is_admin(uid):
            user = db.get_user_by_telegram_id(uid)
            if not user or user["id"] != row["owner_user_id"]:
                await query.answer("شما اجازه ویرایش این پست را ندارید.", show_alert=True)
                return
            if not db.get_permissions(user["id"]).get("pp_edit", True):
                await query.answer("دسترسی ویرایش برای شما فعال نیست.", show_alert=True)
                return

        db.restore_pending_caption(pending_id)
        await query.answer("↩️ کپشن به حالت اول برگشت.")
        from ..poster import send_pending_preview
        await send_pending_preview(context.bot, pending_id)
        return

    # ==================== وضعیت AI (ترجمه/خلاصه‌سازی/بازنویسی) ====================
    if data == "ai:status_services":
        await query.answer("⏳ در حال تست زنده‌ی Groq و Mistral...")
        from ..ai_router import AIRouter, GROQ_MODEL, MISTRAL_MODEL
        router = AIRouter(owner_user_id=scope_owner(uid))
        try:
            status = await router.check_status()
        finally:
            await router.close()

        def _fmt(p: str) -> str:
            info = status[p]
            return "✅ فعال و پاسخگو" if info["ok"] else f"❌ خطا ({info['error']})"

        text = (
            "🧠 <b>وضعیتِ موتورهای هوش مصنوعی (ترجمه / خلاصه‌سازی / بازنویسی)</b>\n"
            f"{DIVIDER}\n"
            f"⚡️ Groq ({GROQ_MODEL}): {_fmt('groq')}\n"
            f"🔷 Mistral ({MISTRAL_MODEL}): {_fmt('mistral')}\n"
            f"{DIVIDER}\n"
            "💡 اگه یکی از دو موتور خطا بده، ربات به‌صورت خودکار درخواست رو به موتور دیگه سوییچ می‌کنه.\n"
            "💡 این وضعیت هیچ ربطی به موتورهای پردازش تصویر (بخش واترمارک) نداره."
        )
        from .ai_providers_menu import home_menu as _aiapi_home_menu
        await safe_edit(query, text, _aiapi_home_menu(scope_owner(uid)), ParseMode.HTML)
        return

    # ==================== چت پیوسته با هوش مصنوعی ====================
    if data == "ai:request":
        context.user_data["ai_chat_history"] = []
        _set_awaiting(context, "ai_chat", "menu:ai_services")
        await safe_edit(
            query,
            "💬 <b>چت با هوش مصنوعی</b>\n"
            f"{DIVIDER}\n"
            "هر چی بنویسی جواب می‌ده و مکالمه ادامه پیدا می‌کنه، دقیقاً مثل یک چت معمولی. "
            "هر کدوم از دو موتور Groq یا Mistral که در دسترس باشه جوابت رو می‌ده.\n"
            "هر وقت خواستی تمومش کنی، «🔚 پایان چت» رو بزن.",
            kb.ai_chat_menu(),
            ParseMode.HTML,
        )
        return

    if data == "ai:chat_end":
        context.user_data.pop("ai_chat_history", None)
        _clear_input_state(context)
        await safe_edit(query, "✅ چت با هوش مصنوعی پایان یافت.", kb.ai_services_menu())
        return

    # ==================== ورودی‌های انصراف ====================
    if data == "input:skip_name":
        awaiting = context.user_data.get("awaiting")
        if awaiting == "src_add_name":
            context.user_data["new_src_name"] = ""
            _set_awaiting(context, "src_add_username", "menu:sources")
            await safe_edit(
                query,
                "یوزرنیم یا لینک کانال مبدأ رو بفرست (مثلا @channelname یا https://t.me/channelname).\n"
                "کانال باید پابلیک باشه.",
                kb.cancel_input_menu(),
            )
        elif awaiting == "dst_add_name":
            context.user_data["new_dst_name"] = ""
            _set_awaiting(context, "dst_add_id", "menu:destinations")
            await safe_edit(
                query,
                "آیدی عددی کانال مقصد (مثلا -1001234567890) یا یوزرنیمش رو بفرست.\n"
                "یادت نره ربات باید توی اون کانال ادمین باشه.",
                kb.cancel_input_menu(),
            )
        else:
            await _dispatch("menu:main", query, context, uid)
        return

    if data == "input:cancel":
        back = context.user_data.get("nav_back")
        _clear_input_state(context)
        if back:
            await _dispatch(back, query, context, uid)
        else:
            await _dispatch("menu:main", query, context, uid)
        return

    log.warning("callback_data ناشناخته: %s", data)