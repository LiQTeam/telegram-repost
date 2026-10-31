from __future__ import annotations

import re as _re

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from . import button_style as _button_style
from .database import db
from .watermark import COLOR_PALETTE, POSITIONS


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


# کلیدهای MAIN_BUTTONS که دکمه‌ی رِپلای‌شون (کیبوردِ پایینِ صفحه) رنگی باشه.
_MAIN_REPLY_BUTTON_COLORS: dict[str, str] = {
    "sources": "success",
    "destinations": "success",
    "myapproval": "primary",
    "public_channel": "primary",
    "stats": "primary",
    "help": "primary",
}


def _main_reply_btn(label: str, key: str) -> KeyboardButton:
    color = _MAIN_REPLY_BUTTON_COLORS.get(key)
    if color:
        return _button_style.colored_reply_button(label, color)
    return KeyboardButton(label)


def _badge(on: bool) -> str:
    return "🟢 فعال" if on else "🔴 غیرفعال"


MAIN_BUTTONS: list[list[tuple[str, str]]] = [
    [("📡 کانال‌های مبدأ", "sources"), ("🎯 کانال‌های مقصد", "destinations")],
    [("🏷 واترمارک تصویر", "watermark"), ("✍️ امضای پایان پست", "footer")],
    [("🔠 قالب‌بندی متن", "format"), ("🚫 فیلتر تبلیغات", "adfilter")],
    [("📢 تبلیغات", "ads_hub"), ("📮 ارسالِ دستی", "manual")],
    [("👥 مدیریت کاربران", "users"), ("🧠 هوش مصنوعی", "ai_services")],
    [("📥 کانال تایید من", "myapproval")],
    [("🖥 مانیتورینگ سرور", "resources"), ("📦 بکاپ و بازیابی", "backup")],
    [("📢 کانال گزارش‌ها", "public_channel")],
    [("📊 آمار ربات", "stats"), ("ℹ️ راهنما", "help")],
]

# ردیفی که فقط باید برای کاربرانِ غیرِادمینِ اضافه‌شده نمایش داده بشه (نه ادمینِ سراسری)
_USER_ONLY_KEYS = {"myapproval"}

MAIN_LABEL_TO_KEY: dict[str, str] = {
    label: key for row in MAIN_BUTTONS for label, key in row
}

# کلیدِ دومِ جست‌وجو: بخشِ بعد از اولین فاصله‌ی لیبل (بدونِ ایموجی)، برای
# اطمینان از تشخیصِ درستِ دکمه حتی اگه فقط بخشی از متن ارسال بشه.
_LABEL_TAIL_TO_KEY: dict[str, str] = {}
for _row in MAIN_BUTTONS:
    for _label, _key in _row:
        _parts = _label.split(" ", 1)
        if len(_parts) == 2:
            _LABEL_TAIL_TO_KEY[_parts[1]] = _key
del _row, _label, _key, _parts


def resolve_main_key(text: str) -> str | None:
    """کلیدِ بخشِ متناظر با متنِ یک دکمه‌ی رِپلای‌کیبورد رو برمی‌گردونه."""
    key = MAIN_LABEL_TO_KEY.get(text)
    if key:
        return key
    parts = text.split(" ", 1)
    if len(parts) == 2:
        return _LABEL_TAIL_TO_KEY.get(parts[1])
    return None


MAIN_MENU_REGEX = _re.compile(
    r"^\S+\s+(" + "|".join(_re.escape(tail) for tail in _LABEL_TAIL_TO_KEY) + ")$"
)

def main_reply_keyboard(is_admin: bool = True, permissions: dict | None = None) -> ReplyKeyboardMarkup:
    if is_admin:
        # ادمین همه چیز رو می‌بینه به‌جز بخش‌های مخصوص کاربران (myapproval)
        def _is_allowed(key: str) -> bool:
            return key not in _USER_ONLY_KEYS
    else:
        # کاربر غیرادمین فقط بخش‌هایی که دسترسی داره رو می‌بینه
        _always_for_owners = {"myapproval", "stats", "help"}
        _perm_to_keys: dict[str, set] = {
            "src": {"sources"},
            "dst": {"destinations"},
            "wm": {"watermark"},
            "ai": {"ai_services"},
            "format": {"format"},
            "footer": {"footer"},
            "adfilter": {"adfilter"},
            "manual": {"manual", "customwm"},
        }
        allowed_keys = set(_always_for_owners)
        if permissions:
            for perm_k, section_keys in _perm_to_keys.items():
                if permissions.get(perm_k):
                    allowed_keys |= section_keys

        def _is_allowed(key: str) -> bool:
            return key in allowed_keys

    # ردیف‌های دوتاییِ MAIN_BUTTONS (طراحیِ اصلی: دو دکمه کنارِ هم) رو جمع
    # می‌کنیم و بعدِ فیلترِ دسترسی، دوباره دوتاییِ منظم می‌چینیم. قبلاً فیلتر
    # داخلِ همون جفتِ اصلی انجام می‌شد، پس اگه یکی از دو تا دسترسی نداشت، اون
    # یکی تنها و تمام‌عرض می‌موند (مثلِ «ارسالِ دستی» و «هوش مصنوعی» وقتی
    # جفتِشون یعنی «تبلیغات»/«مدیریتِ کاربران» برای اون کاربر مجاز نبود). حالا
    # این تک‌افتاده‌ها با اولین موردِ مجازِ بعدی جفت می‌شن. ردیف‌هایی که از اول
    # عمداً تک‌ستونه و تمام‌عرض طراحی شدن («کانال تایید من»، «کانال گزارش‌ها»)
    # دست‌نخورده می‌مونن و مرزِ گروه‌بندیِ گریدها رو هم همون‌جا نگه می‌دارن.
    rows: list[list[KeyboardButton]] = []
    pending: list[KeyboardButton] = []

    def _flush_pending() -> None:
        if pending:
            rows.extend(_chunk(pending, 2))
            pending.clear()

    for row in MAIN_BUTTONS:
        if len(row) == 1:
            _flush_pending()
            label, key = row[0]
            if _is_allowed(key):
                rows.append([_main_reply_btn(label, key)])
            continue
        pending.extend(_main_reply_btn(label, key) for label, key in row if _is_allowed(key))
    _flush_pending()

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        # ⚠️ قبلاً اینجا is_persistent=True بود که به کلاینتِ تلگرام می‌گه «همیشه
        # این کیبورد رو نشون بده، حتی اگه کاربر خودش با فلش/شورونِ کنارِ باکسِ
        # پیام جمعش کرده باشه». دقیقاً همین باعث می‌شد هر بار که کاربر کیبورد رو
        # می‌بست و بعد هر پیامِ جدیدی از ربات می‌رسید (مثلاً موقعِ برگشت به منو)،
        # کیبورد خودکار دوباره باز بشه. حذفش شد تا حالتِ باز/بسته‌ی دستیِ کاربر
        # محترم شمرده بشه.
        input_field_placeholder="یک گزینه رو از منو انتخاب کن...",
    )


def _chunk(buttons: list[InlineKeyboardButton], size: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


# ==================== گرید و صفحه‌بندیِ لیست‌های بلند ====================
# لیست‌های کانالِ مبدأ/مقصد/اکستنشن قبلاً هر آیتم رو توی یک ردیفِ کاملِ تک‌ستونه
# نشون می‌دادن؛ با زیاد شدنِ کانال‌ها لیست خیلی بلند و بدقواره می‌شد. حالا آیتم‌ها
# توی گریدِ چندستونه چیده و به صفحه‌های کوچک‌تر تقسیم می‌شن و بینشون دکمه‌ی
# «صفحه‌ی بعد/قبل» گذاشته می‌شه.
GRID_COLS = 2          # تعدادِ ستونِ کنارِ هم
GRID_ROWS = 6          # تعدادِ ردیف در هر صفحه
PER_PAGE = GRID_COLS * GRID_ROWS  # آیتم در هر صفحه (۱۲)


def _paginate(items: list, page: int, per_page: int = PER_PAGE):
    """(آیتم‌های همین صفحه، شماره‌ی صفحه‌ی نرمال‌شده، تعداد کل صفحه‌ها) رو برمی‌گردونه.
    شماره‌ی صفحه به بازه‌ی معتبر محدود می‌شه تا اگه بعد از حذفِ چند آیتم صفحه از
    محدوده بیرون زد، به آخرین صفحه‌ی موجود برگرده."""
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return items[start:start + per_page], page, total_pages


def _grid(buttons: list[InlineKeyboardButton], cols: int = GRID_COLS) -> list[list[InlineKeyboardButton]]:
    """دکمه‌ها رو توی ردیف‌هایی با حداکثر `cols` ستون می‌چینه."""
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _page_nav_row(page: int, total_pages: int, cb_prefix: str) -> list[InlineKeyboardButton] | None:
    """ردیفِ ناوبریِ صفحه: «◀️ قبلی · صفحه i از n · بعدی ▶️». فقط وقتی بیش از یک
    صفحه باشه ساخته می‌شه؛ دکمه‌های لبه (قبلی در صفحه‌ی اول، بعدی در صفحه‌ی آخر)
    به نشانه‌ی بی‌اثر بودن نقطه‌چین می‌شن. cb_prefix باید به «:» ختم بشه (مثلِ
    "src:page:") تا شماره‌ی صفحه‌ی مقصد بهش چسبیده بشه."""
    if total_pages <= 1:
        return None
    prev_txt = "◀️ قبلی" if page > 0 else "▫️"
    next_txt = "بعدی ▶️" if page < total_pages - 1 else "▫️"
    prev_cb = f"{cb_prefix}{page - 1}" if page > 0 else "nav:noop"
    next_cb = f"{cb_prefix}{page + 1}" if page < total_pages - 1 else "nav:noop"
    return [
        _btn(prev_txt, prev_cb),
        _btn(f"صفحه {page + 1} از {total_pages}", "nav:noop"),
        _btn(next_txt, next_cb),
    ]


def _home_row() -> list[InlineKeyboardButton]:
    return [_btn("🏠 بازگشت به منوی اصلی", "menu:main")]


def with_home(rows: list[list[InlineKeyboardButton]], skip_home: bool = False) -> InlineKeyboardMarkup:
    if not skip_home:
        rows = rows + [_home_row()]
    return InlineKeyboardMarkup(rows)


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("🔙 بازگشت به منو", "menu:main")]])


# ==================== کانال‌های مبدأ ====================

_MODE_ICON = {"schedule": "⏱", "instant": "⚡️", "interval": "🔁"}


def sources_menu(owner_id: int | None = None, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if owner_id is None:
        # فقط ادمین وضعیت کلیِ زمان‌بند رو می‌بینه (سراسریه و روی همه‌ی کاربرها اثر می‌ذاره)
        active = db.get_bool("scheduler_active", True)
        rows.append([_btn(f"وضعیت کلیِ زمان‌بند: {'🟢 فعال' if active else '🔴 متوقف'}", "sched:toggle")])
    channels = db.list_channels() if owner_id is None else db.list_channels(owner_user_id=owner_id)
    buttons = []
    for ch in channels:
        status = "🟢" if ch["active"] else "⚪️"
        n_dest = len(db.linked_destination_ids(ch["id"]))
        mode = ch["send_mode"] or "schedule"
        mode_icon = _MODE_ICON.get(mode, "⏱")
        name = ch["title"] or f"@{ch['username']}"
        label = f"{status} {name} · {mode_icon} · 🎯{n_dest}"
        buttons.append(_btn(label, f"src:view:{ch['id']}"))
    page_items, page, total_pages = _paginate(buttons, page)
    rows.extend(_grid(page_items))
    nav = _page_nav_row(page, total_pages, "src:page:")
    if nav:
        rows.append(nav)
    rows.append([_btn("➕ افزودن کانال مبدأ", "src:add")])
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def extsources_menu(page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    buttons = []
    for ch in db.list_extension_channels():
        if ch["active"]:
            status = "🟢"
        else:
            status = "🟡"
        n_dest = len(db.linked_destination_ids(ch["id"]))
        name = ch["title"] or ch["ext_peer_ref"]
        label = f"{status} {name} · 🎯{n_dest}"
        buttons.append(_btn(label, f"extsrc:view:{ch['id']}"))
    page_items, page, total_pages = _paginate(buttons, page)
    rows.extend(_grid(page_items))
    nav = _page_nav_row(page, total_pages, "extsrc:page:")
    if nav:
        rows.append(nav)
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def extsource_detail_menu(channel_id: int) -> InlineKeyboardMarkup:
    ch = db.get_channel(channel_id)
    toggle_label = "🟢 غیرفعال کن" if ch and ch["active"] else "🔴 فعال کن (شروع دریافت پست)"
    approval_on = bool(ch["approval_required"]) if ch else True
    approval_label = f"🛡 تایید قبل از ارسال: {'🟢 فعال' if approval_on else '🔴 غیرفعال (خودکار)'}"
    rows = [
        [_btn(approval_label, f"extsrc:approval_toggle:{channel_id}")],
        [_btn("🎯 کانال‌های مقصدِ این منبع", f"src:destmap:{channel_id}")],
        [_btn(toggle_label, f"extsrc:toggle:{channel_id}"), _btn("🗑 حذف", f"extsrc:remove:{channel_id}")],
        [_btn("🔙 بازگشت به لیست", "menu:extsources")],
    ]
    return with_home(rows)


def confirm_remove_extsource_menu(channel_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_btn("✅ بله، حذف کن", f"extsrc:remove_confirm:{channel_id}")],
        [_btn("❌ انصراف", f"extsrc:view:{channel_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def source_detail_menu(channel_id: int) -> InlineKeyboardMarkup:
    ch = db.get_channel(channel_id)
    toggle_label = "🟢 غیرفعال کن" if ch and ch["active"] else "🔴 فعال کن"
    approval_on = bool(ch["approval_required"]) if ch else False
    approval_label = f"🛡 تایید قبل از ارسال: {'🟢 فعال' if approval_on else '🔴 غیرفعال'}"
    mode = (ch["send_mode"] if ch else "schedule") or "schedule"
    mode_fa = {"schedule": "زمان‌بندی هفت‌گانه", "instant": "لحظه‌ای", "interval": "بازه‌ای"}.get(mode, mode)
    from .duplicate_filter import DuplicateFilter
    dup_fa = {
        DuplicateFilter.MODE_DISABLED: "🔴 غیرفعال",
        DuplicateFilter.MODE_AUTO_REJECT: "🗑 حذف خودکار",
        DuplicateFilter.MODE_SEND_TO_APPROVAL: "🛡 ارسال به تایید",
    }.get(DuplicateFilter.get_mode(channel_id), "🔴 غیرفعال")
    rows = [
        [_btn(f"🚀 حالت ارسال: {mode_fa}", f"src:mode_menu:{channel_id}")],
        [_btn(approval_label, f"src:approval_toggle:{channel_id}")],
        [_btn(f"♻️ فیلتر تکراری: {dup_fa}", f"src:dupmenu:{channel_id}")],
        [_btn("🎯 کانال‌های مقصدِ این کانال", f"src:destmap:{channel_id}")],
        [_btn("⚙️ تنظیمات اختصاصیِ این کانال", f"src:overrides:{channel_id}")],
        [_btn("📤 ارسال پست‌های آخر", f"src:bulk_menu:{channel_id}")],
        [_btn(toggle_label, f"src:toggle:{channel_id}"), _btn("🗑 حذف", f"src:remove:{channel_id}")],
        [_btn("🔙 بازگشت به لیست", "menu:sources")],
    ]
    return with_home(rows)


def send_mode_menu(channel_id: int) -> InlineKeyboardMarkup:
    ch = db.get_channel(channel_id)
    mode = (ch["send_mode"] if ch else "schedule") or "schedule"
    interval = ch["interval_minutes"] if ch else 30

    def mk(key, label):
        mark = "✅ " if key == mode else "⬜️ "
        return _btn(mark + label, f"src:setmode:{channel_id}:{key}")

    rows = [
        [mk("schedule", "⏱ زمان‌بندی هفت‌گانه (ساعتی)")],
        [mk("instant", "⚡️ ارسال لحظه‌ای (مستقیم، بدون تایید)")],
        [mk("interval", f"🔁 ارسال بازه‌ای (هر {interval} دقیقه)")],
    ]
    if mode == "schedule":
        rows.append([_btn("✏️ تنظیم ساعت‌های ارسال (۷ اسلات)", f"src:sched:{channel_id}")])
    if mode == "interval":
        rows.append([_btn("✏️ تغییر بازه (دقیقه)", f"src:setinterval:{channel_id}")])
    rows.append([_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")])
    return with_home(rows)


def duplicate_mode_menu(channel_id: int) -> InlineKeyboardMarkup:
    from .duplicate_filter import DuplicateFilter
    current = DuplicateFilter.get_mode(channel_id)

    def mk(key, label):
        mark = "✅ " if key == current else "⬜️ "
        return _btn(mark + label, f"src:dupset:{channel_id}:{key}")

    rows = [
        [mk(DuplicateFilter.MODE_DISABLED, "🔴 غیرفعال (تکرار مجاز است)")],
        [mk(DuplicateFilter.MODE_AUTO_REJECT, "🗑 حذف خودکارِ پست‌های تکراری")],
        [mk(DuplicateFilter.MODE_SEND_TO_APPROVAL, "🛡 ارسال پست‌های تکراری به تایید")],
        [_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")],
    ]
    return with_home(rows)


def bulk_menu(channel_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("۱۰ پست آخر", f"src:bulk_run:{channel_id}:10"),
            _btn("۲۰ پست آخر", f"src:bulk_run:{channel_id}:20"),
            _btn("۳۰ پست آخر", f"src:bulk_run:{channel_id}:30"),
        ],
        [_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")],
    ]
    return with_home(rows)


def pending_post_menu(
    pending_id: int, has_video: bool = False, has_photo: bool = True, show_restore: bool = False,
    ad_flagged: bool = False, ad_feedback: str = "",
) -> InlineKeyboardMarkup:
    row1 = [_btn("✏️ ویرایش کپشن", f"pp:editcap:{pending_id}")]
    # دکمه‌ی «تغییر عکس» فقط وقتی نشون داده میشه که پست واقعاً عکس داشته باشه؛
    # برای پستِ ویدیویی این دکمه بی‌معنی بود (عکسِ جایگزین همیشه نادیده گرفته
    # می‌شد، بدونِ هیچ خطایی) - دقیقاً مثلِ منطقِ «تغییر ویدیو» زیر.
    if has_photo:
        row1.append(_btn("🖼 تغییر عکس", f"pp:editphoto:{pending_id}"))
    rows = [
        [_btn("✅ تایید و ارسال", f"pp:approve:{pending_id}")],
        row1,
    ]
    # دکمه‌ی «تغییر ویدیو» فقط وقتی نشون داده میشه که پست واقعاً ویدیو داشته باشه؛
    # این دکمه خودِ فایلِ ویدیو رو عوض می‌کنه (نه فقط کاور/عکسِ آن، که کارِ دکمه‌ی بالاست).
    if has_video:
        rows.append([_btn("🎬 تغییر ویدیو", f"pp:editvideo:{pending_id}")])
    rows.append([_btn("🌐 ترجمه به فارسی", f"pp:translate:{pending_id}"), _btn("📝 خلاصه‌سازی", f"pp:summarize:{pending_id}")])
    rows.append([_btn("🔄 بازنویسی خلاقانه", f"pp:rewrite:{pending_id}")])
    if has_photo:
        rows.append([_btn("🏷 واترمارکِ دلخواه", f"pp:wm:{pending_id}")])
    if show_restore:
        # فقط وقتی نشون داده میشه که کپشنِ فعلی با نسخه‌ی اصلیِ اسکرِیپ‌شده فرق
        # داشته باشه (یعنی حداقل یه بار ترجمه/خلاصه‌سازی/بازنویسی/ویرایشِ دستی
        # روش انجام شده)؛ اینجوری برای پست‌های دست‌نخورده کیبورد شلوغ نمیشه.
        rows.append([_btn("↩️ بازگشت به کپشن اصلی", f"pp:restorecap:{pending_id}")])
    if ad_flagged and not ad_feedback:
        # فیدبکِ ادمین به تشخیصِ فیلترِ تبلیغات — فقط وقتی این پست به‌خاطرِ
        # مشکوک بودن به تبلیغ فلگ شده و هنوز فیدبکی براش ثبت نشده.
        rows.append([
            _btn("✅ درست بود (واقعاً تبلیغ)", f"pp:adfb:1:{pending_id}"),
            _btn("❌ اشتباه بود (تبلیغ نبود)", f"pp:adfb:0:{pending_id}"),
        ])
    rows.append([_btn("❌ رد کردن پست", f"pp:reject:{pending_id}")])
    return InlineKeyboardMarkup(rows)


# نکته‌ی ادغام: این تابع مالِ مکانیزمِ قدیمی‌ترِ پیامِ ریپلایِ جداگانه‌ست (نگاه کن
# به poster._pending_flag_kb و database.set_pending_flag_message). فعلاً هیچ‌جا
# به‌صورتِ پیش‌فرض صدا زده نمی‌شه چون دکمه‌های فیدبک حالا مستقیم رویِ خودِ پست
# (بالا، ad_flagged/ad_feedback در pending_post_menu) نشون داده می‌شن؛ عمداً
# حذف نشده تا در صورتِ نیاز به بازگردوندنِ اون مکانیزم، کدش آماده باشه.
def pending_flag_menu(pending_id: int, ad_feedback: str = "") -> InlineKeyboardMarkup:
    """کیبوردِ پیامِ ریپلایِ توضیحاتِ فلگِ فیلترِ تبلیغات - فقط دکمه‌های فیدبک
    (درست بود/اشتباه بود)، جدا از کیبوردِ خودِ پست. بعد از ثبتِ فیدبک، کیبورد
    خالی می‌مونه (دکمه‌ها دیگه لازم نیستن)."""
    if ad_feedback:
        return InlineKeyboardMarkup([])
    rows = [[
        _btn("✅ درست بود (واقعاً تبلیغ)", f"pp:adfb:1:{pending_id}"),
        _btn("❌ اشتباه بود (تبلیغ نبود)", f"pp:adfb:0:{pending_id}"),
    ]]
    return InlineKeyboardMarkup(rows)


def pending_wm_menu(pending_id: int, owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    """لیستِ واترمارک‌های دلخواهِ فعالِ کاربر برایِ چیدنِ دستی روی یک پستِ
    مشخص در صفِ تایید - با تیکِ سبز رویِ اونهایی که الان روی این پست چیده شدن."""
    _base, picks = db.get_pending_wm_pick(pending_id)
    picked_ids = {p.get("watermark_id") for p in picks}
    wms = db.list_custom_watermarks(owner_user_id=owner_user_id, active_only=True)
    rows = []
    for wm in wms:
        mark = "✅" if wm["id"] in picked_ids else "▫️"
        rows.append([_btn(f"{mark} {wm['name']}", f"pp:wm_toggle:{pending_id}:{wm['id']}")])
    if not wms:
        rows.append([_btn("هیچ واترمارکِ دلخواهی نساختی — از منویِ اصلی بساز", "menu:customwm")])
    if picks:
        rows.append([_btn("♻️ پاک‌کردنِ همه", f"pp:wm_reset:{pending_id}")])
    rows.append([_btn("🔙 بازگشت", f"pp:view:{pending_id}")])
    return InlineKeyboardMarkup(rows)


def confirm_remove_menu(channel_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_btn("✅ بله، حذف کن", f"src:remove_confirm:{channel_id}"), _btn("❌ انصراف", f"src:view:{channel_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def source_schedule_menu(channel_id: int) -> InlineKeyboardMarkup:
    slots = db.get_slots(channel_id)
    slot_buttons = []
    for s in slots:
        mark = "🟢" if s["enabled"] else "⚪️"
        time_label = s["slot_time"] or "--:--"
        slot_buttons.append(_btn(f"{mark} {s['slot_index']}) {time_label}", f"src:slot:{channel_id}:{s['slot_index']}"))
    rows = _chunk(slot_buttons, 2)
    rows.append([_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")])
    return with_home(rows)


def slot_detail_menu(channel_id: int, slot_index: int) -> InlineKeyboardMarkup:
    slot = db.get_slot(channel_id, slot_index)
    toggle_label = "🔴 غیرفعال کن" if slot and slot["enabled"] else "🟢 فعال کن"
    rows = [
        [_btn("✏️ تغییر ساعت", f"src:slot_time:{channel_id}:{slot_index}"), _btn(toggle_label, f"src:slot_toggle:{channel_id}:{slot_index}")],
        [_btn("🔙 بازگشت به لیست اسلات‌ها", f"src:sched:{channel_id}")],
    ]
    return with_home(rows)


def source_destmap_menu(channel_id: int, owner_id: int | None = None) -> InlineKeyboardMarkup:
    linked = db.linked_destination_ids(channel_id)
    dest_buttons = []
    destinations = db.list_destinations() if owner_id is None else db.list_destinations(owner_user_id=owner_id)
    for d in destinations:
        mark = "✅" if d["id"] in linked else "⬜️"
        active_mark = "" if d["active"] else " (غیرفعال)"
        label = f"{mark} {d['title'] or d['chat_id']}{active_mark}"
        dest_buttons.append(_btn(label, f"src:destmap_toggle:{channel_id}:{d['id']}"))
    rows = _chunk(dest_buttons, 2)
    rows.append([_btn("➕ افزودن کانال مقصد جدید", "dst:add")])
    rows.append([_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")])
    return with_home(rows)


# لیبلِ کاملِ هر تاگل + آیکنِ اختصاصیِ خودش، برای نمایشِ تک‌ستونه توی
# منوی «تنظیماتِ اختصاصیِ کانال». هر ردیف یک دکمه‌ی مجزاست تا تایتلِ کامل
# جا بشه و بریده/ناخوانا نشه.
_OVERRIDE_FULL_LABELS: dict[str, str] = {
    "wm_tg_enabled": "🏷 واترمارک تلگرام",
    "wm_ig_enabled": "📸 واترمارک اینستاگرام",
    "ai_removal_enabled": "🧹 حذفِ واترمارکِ قبلی (AI)",
    "ad_filter_enabled": "🚫 فیلترِ تبلیغات",
    "ad_filter_smart_enabled": "🧠 فیلترِ هوشمند (AI)",
    "config_only_enabled": "🧩 فقط کانفیگ/پروکسی",
    "premium_emoji_enabled": "⭐ ایموجیِ پرمیوم",
    "file_filter_enabled": "📦 فیلترِ فایل/آپ",
    "min_content_filter_enabled": "✂️ فیلترِ پست‌های کوتاه",
    "footer_enabled": "✍️ امضای پایان پست",
    "preserve_formatting": "🔤 حفظِ قالب‌بندیِ متن",
    "remove_source_links": "🔗 حذفِ لینک/منشنِ مبدأ",
    "download_cache_enabled": "💾 کِشِ دانلود",
    "vpn_howto_cleanup_enabled": "🧽 پاکسازیِ کپشنِ Netmod/NPV",
    "vpn_signature_footer_enabled": "🔏 امضایِ VFREEPN",
}


def source_override_menu(channel_id: int) -> InlineKeyboardMarkup:
    from .database import OVERRIDABLE_TOGGLES, OVERRIDABLE_TOGGLE_DEFAULTS, USER_SCOPED_TOGGLES

    ch = db.get_channel(channel_id)
    channel_owner = ch["owner_user_id"] if ch and ch["owner_user_id"] else None
    overrides = db.get_channel_overrides(channel_id)
    rows = []
    for key, label in OVERRIDABLE_TOGGLES.items():
        override = overrides.get(key)
        default = OVERRIDABLE_TOGGLE_DEFAULTS.get(key, False)
        owner_user_id = channel_owner if key in USER_SCOPED_TOGGLES else None
        effective = db.get_effective_bool(channel_id, key, default, owner_user_id=owner_user_id)
        # نشانگرِ وضعیت در *انتهای* دکمه: آیکنِ منبعِ تصمیم (🔁 پیرو عمومی /
        # 📌 اختصاصیِ همین کانال) + نقطه‌ی رنگیِ وضعیتِ مؤثر (🟢 روشن / 🔴 خاموش).
        dot = "🟢" if effective else "🔴"
        src_icon = "🔁" if override is None else "📌"
        full_label = _OVERRIDE_FULL_LABELS.get(key, label)
        rows.append([_btn(f"{full_label} {src_icon}{dot}", f"src:ov_cycle:{channel_id}:{key}")])
    rows.append([_btn("♻️ حذفِ همه‌ی تنظیماتِ اختصاصی", f"src:ov_clear_all:{channel_id}")])
    rows.append([_btn("🔙 بازگشت به کانال", f"src:view:{channel_id}")])
    return with_home(rows)


# ==================== کانال‌های مقصد ====================

def destinations_menu(owner_id: int | None = None, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    destinations = db.list_destinations() if owner_id is None else db.list_destinations(owner_user_id=owner_id)
    buttons = []
    for d in destinations:
        status = "🟢" if d["active"] else "⚪️"
        label = f"{status} {d['title'] or d['chat_id']}"
        buttons.append(_btn(label, f"dst:view:{d['id']}"))
    page_items, page, total_pages = _paginate(buttons, page)
    rows.extend(_grid(page_items))
    nav = _page_nav_row(page, total_pages, "dst:page:")
    if nav:
        rows.append(nav)
    rows.append([_btn("➕ افزودن کانال مقصد", "dst:add")])
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def destination_detail_menu(destination_id: int) -> InlineKeyboardMarkup:
    d = db.get_destination(destination_id)
    toggle_label = "🟢 غیرفعال کن" if d and d["active"] else "🔴 فعال کن"
    rows = [
        [_btn("📊 آمار و زمان‌بندی هوشمند", f"dst:smart:{destination_id}")],
        [_btn("⚙️ تنظیماتِ اختصاصیِ این مقصد", f"dst:cfg:{destination_id}")],
        [_btn(toggle_label, f"dst:toggle:{destination_id}"), _btn("🗑 حذف", f"dst:remove:{destination_id}")],
        [_btn("🔙 بازگشت به لیست", "menu:destinations")],
    ]
    return with_home(rows)


def destination_config_menu(destination_id: int) -> InlineKeyboardMarkup:
    footer_on = db.dest_setting_get_bool(destination_id, "footer_override", False)
    adf_on = db.dest_setting_get_bool(destination_id, "ad_filter_override", False)
    from .duplicate_filter import DuplicateFilter
    dedup_on = DuplicateFilter.get_dest_dedup_enabled(destination_id)
    f_label = "✍️ امضای اختصاصی: 🟢 روشن" if footer_on else "✍️ امضای اختصاصی: 🔴 خاموش"
    a_label = "🚫 فیلترِ تبلیغاتِ اختصاصی: 🟢 روشن" if adf_on else "🚫 فیلترِ تبلیغاتِ اختصاصی: 🔴 خاموش"
    d_label = "♻️ جلوگیری از پستِ تکراریِ بینِ‌کانالی: 🟢 روشن" if dedup_on else "♻️ جلوگیری از پستِ تکراریِ بینِ‌کانالی: 🔴 خاموش"
    rows = [
        [_btn(f_label, f"dst:footertoggle:{destination_id}")],
        [_btn("✍️ تنظیمِ امضای این مقصد", f"dst:footer:{destination_id}")],
        [_btn(a_label, f"dst:adftoggle:{destination_id}")],
        [_btn("🚫 تنظیمِ فیلترِ تبلیغاتِ این مقصد", f"dst:adf:{destination_id}")],
        [_btn(d_label, f"dst:duptoggle:{destination_id}")],
        [_btn("🔙 بازگشت به کانال", f"dst:view:{destination_id}")],
    ]
    return with_home(rows)


def dest_footer_menu(destination_id: int) -> InlineKeyboardMarkup:
    override_on = db.dest_setting_get_bool(destination_id, "footer_override", False)
    enabled = db.dest_setting_get_bool(destination_id, "footer_enabled", True)
    mode = db.dest_setting_get(destination_id, "footer_mode", "link")
    rows = [
        [_btn(f"وضعیتِ امضای اختصاصی: {'🟢 روشن' if override_on else '🔴 خاموش'}", f"dst:footertoggle:{destination_id}")],
        [_btn(f"نمایشِ امضا: {'🟢 روشن' if enabled else '🔴 خاموش'}", f"dst:footerenable:{destination_id}")],
        [_btn(f"حالت: {'🔗 لینک' if mode == 'link' else '📝 متنِ دلخواه'}", f"dst:footermode:{destination_id}")],
        [_btn("✏️ یوزرنیم/هندل", f"dst:footerhandle:{destination_id}")],
        [_btn("🔗 لینک", f"dst:footerurl:{destination_id}")],
    ]
    if mode == "custom":
        rows.append([_btn("📝 متنِ دلخواهِ امضا", f"dst:footercustom:{destination_id}")])
    else:
        rows.append([_btn("🔤 قالبِ متنِ لینک", f"dst:footertpl:{destination_id}")])
    rows.append([_btn("🔙 بازگشت", f"dst:cfg:{destination_id}")])
    return with_home(rows)


def dest_footer_mode_menu(destination_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_btn("🔗 فقط لینکِ کانال", f"dst:footersetmode:{destination_id}:link")],
        [_btn("📝 متنِ کاملاً دلخواه", f"dst:footersetmode:{destination_id}:custom")],
        [_btn("🔙 بازگشت", f"dst:footer:{destination_id}")],
    ]
    return with_home(rows)


def dest_adfilter_menu(destination_id: int) -> InlineKeyboardMarkup:
    override_on = db.dest_setting_get_bool(destination_id, "ad_filter_override", False)
    enabled = db.dest_setting_get_bool(destination_id, "ad_filter_enabled", True)
    action = db.dest_setting_get(destination_id, "ad_filter_action", "skip")
    action_label = "🎬 اقدام: رد کردن (skip)" if action != "review" else "🎬 اقدام: ارسال به تایید (review)"
    rows = [
        [_btn(f"وضعیتِ فیلترِ اختصاصی: {'🟢 روشن' if override_on else '🔴 خاموش'}", f"dst:adftoggle:{destination_id}")],
        [_btn(f"فیلتر: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", f"dst:adfenable:{destination_id}")],
        [_btn(action_label, f"dst:adfaction:{destination_id}")],
        [_btn("🔑 کلیدواژه‌ها", f"dst:adfkw:{destination_id}")],
        [_btn("🧹 حذفِ عبارت/ایموجی از متن", f"dst:adfph:{destination_id}")],
        [_btn("🔹 آستانه‌ی منشن", f"dst:adfmm:{destination_id}"), _btn("🔹 آستانه‌ی لینک", f"dst:adfml:{destination_id}")],
        [_btn("🔹 حساسیتِ کلی", f"dst:adfth:{destination_id}")],
        [_btn(f"🚫@ حذفِ منشن‌ها از متن: {'🟢' if db.dest_setting_get_bool(destination_id, 'ad_strip_mentions', False) else '🔴'}", f"dst:adfstripm:{destination_id}")],
        [_btn(f"🚫🔗 حذفِ لینک‌های سایت از متن: {'🟢' if db.dest_setting_get_bool(destination_id, 'ad_strip_links', False) else '🔴'}", f"dst:adfstripl:{destination_id}")],
        [_btn("🔙 بازگشت", f"dst:cfg:{destination_id}")],
    ]
    return with_home(rows)


def confirm_remove_destination_menu(destination_id: int) -> InlineKeyboardMarkup:
    rows = [
        [_btn("✅ بله، حذف کن", f"dst:remove_confirm:{destination_id}"), _btn("❌ انصراف", f"dst:view:{destination_id}")],
    ]
    return InlineKeyboardMarkup(rows)


# ==================== واترمارک (تلگرام + اینستاگرام + هوش مصنوعی + کش) ====================

_PLATFORM_FA = {"tg": "تلگرام", "ig": "اینستاگرام"}


def watermark_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    tg_on = db.setting_get_bool("wm_tg_enabled", True, owner_user_id=owner_user_id)
    ig_on = db.setting_get_bool("wm_ig_enabled", False, owner_user_id=owner_user_id)
    rows = [
        [_btn("🖼 واترمارکِ سفارشی", "menu:customwm")],
        [_btn(f"📨 واترمارک تلگرام: {_badge(tg_on)}", "wmp:tg")],
        [_btn(f"📸 واترمارک اینستاگرام: {_badge(ig_on)}", "wmp:ig")],
    ]
    if owner_user_id is None:
        ai_removal = db.get_bool("ai_removal_enabled", False)
        quality_enhance = db.get_bool("quality_enhance_enabled", False)
        cache_on = db.get_bool("download_cache_enabled", True)
        rows += [
            [_btn(f"🧹 حذف واترمارک قبلی (AI): {_badge(ai_removal)}", "ai:removal_toggle")],
            [_btn(f"🔎 بهبود کیفیت تصویر (AI): {_badge(quality_enhance)}", "ai:quality_toggle")],
            [_btn(f"💾 کش دانلود: {_badge(cache_on)}", "ai:cache_toggle")],
            [_btn("🗑 پاک‌سازی کش", "ai:cache_clear"), _btn("🧠 وضعیت موتورهای AI", "ai:status")],
        ]
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def watermark_platform_menu(plat: str, owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    prefix = f"wm_{plat}"
    enabled = db.setting_get_bool(f"{prefix}_enabled", plat == "tg", owner_user_id=owner_user_id)
    album_all = db.setting_get_bool(f"{prefix}_album_all", True, owner_user_id=owner_user_id)
    badge_scale = db.setting_get_int(f"{prefix}_badge_scale", 32, owner_user_id=owner_user_id)
    rows = [
        [_btn(f"🔘 وضعیت: {_badge(enabled)}", f"wmp:{plat}:toggle")],
        [_btn("✏️ متن آیدی (داخل باکس)", f"wmp:{plat}:text"), _btn("📍 موقعیت", f"wmp:{plat}:position_menu")],
        [_btn("🎨 رنگ متن آیدی", f"wmp:{plat}:color_menu"), _btn("🔤 اندازه متن", f"wmp:{plat}:fontsize")],
        [_btn(f"📐 اندازه نشان: {badge_scale}%", f"wmp:{plat}:badgescale"), _btn("🌫 شفافیت نشان", f"wmp:{plat}:opacity")],
        [_btn("↔️ فاصله از لبه", f"wmp:{plat}:margin")],
        [_btn(f"آلبوم: {'همه‌ی عکس‌ها' if album_all else 'فقط عکس اول'}", f"wmp:{plat}:album_toggle")],
        [_btn("🖼 ارسال پیش‌نمایش", f"wmp:{plat}:preview")],
        [_btn("🔙 بازگشت", "menu:watermark")],
    ]
    return with_home(rows)


def watermark_position_menu(plat: str, owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    current = db.setting_get(f"wm_{plat}_position", "bottom_left", owner_user_id=owner_user_id)

    def mk(key):
        mark = "✅ " if key == current else ""
        return _btn(mark + POSITIONS[key], f"wmp:{plat}:setpos:{key}")

    rows = [
        [mk("top_left"), mk("top_center"), mk("top_right")],
        [mk("bottom_left"), mk("bottom_center"), mk("bottom_right")],
        [_btn("🔙 بازگشت", f"wmp:{plat}")],
    ]
    return with_home(rows)


def watermark_color_menu(plat: str, selected: list[str], mode: str) -> InlineKeyboardMarkup:
    single_mark = "✅ " if mode == "single" else ""
    grad_mark = "✅ " if mode == "gradient" else ""
    rows = [
        [
            _btn(f"{single_mark}⚫️ تک‌رنگ", f"wmp:{plat}:color_mode:single"),
            _btn(f"{grad_mark}🌈 گرادیانی (دو رنگ)", f"wmp:{plat}:color_mode:gradient"),
        ],
    ]
    color_buttons = []
    selected_upper = [s.upper() for s in selected]
    for name, hexv in COLOR_PALETTE:
        order = selected_upper.index(hexv.upper()) + 1 if hexv.upper() in selected_upper else None
        mark = f"✅{order} " if order else ""
        color_buttons.append(_btn(f"{mark}{name}", f"wmp:{plat}:color_pick:{hexv}"))
    rows += _chunk(color_buttons, 2)

    need = 1 if mode == "single" else 2
    can_confirm = len(selected) == need
    confirm_label = "✅ تایید رنگ(ها)" if can_confirm else f"رنگ‌های لازم را انتخاب کن ({len(selected)}/{need})"
    rows.append([_btn(confirm_label, f"wmp:{plat}:color_confirm" if can_confirm else "wmp:noop")])
    rows.append([_btn("🔙 بازگشت (بدون ذخیره)", f"wmp:{plat}")])
    return with_home(rows)


def ai_status_menu(plat_back: str = "menu:watermark") -> InlineKeyboardMarkup:
    rows = [[_btn("🔙 بازگشت", plat_back)]]
    return with_home(rows)


# ==================== امضای پایان پست ====================

def footer_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    enabled = db.setting_get_bool("footer_enabled", True, owner_user_id=owner_user_id)
    mode = db.setting_get("footer_mode", "link", owner_user_id=owner_user_id)
    mode_fa = "🧩 لینکِ ساده" if mode == "link" else "📝 متنِ کاملاً دلخواه"
    rows = [
        [_btn(f"🔘 وضعیت: {_badge(enabled)}", "footer:toggle")],
        [_btn(f"🗂 حالت امضا: {mode_fa}", "footer:mode_menu")],
    ]
    if mode == "custom":
        rows.append([_btn("✏️ ویرایشِ متنِ دلخواه (چندخطی)", "footer:custom_text")])
        rows.append([_btn("✏️ یوزرنیم کانال", "footer:handle"), _btn("🔗 لینک سفارشی", "footer:url")])
    else:
        rows.append([_btn("✏️ یوزرنیم کانال", "footer:handle"), _btn("🔗 لینک سفارشی", "footer:url")])
        rows.append([_btn("🧩 قالب متن امضا", "footer:template")])
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def footer_mode_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    mode = db.setting_get("footer_mode", "link", owner_user_id=owner_user_id)

    def mk(key, label):
        mark = "✅ " if key == mode else "⬜️ "
        return _btn(mark + label, f"footer:setmode:{key}")

    rows = [
        [mk("link", "🧩 لینکِ ساده (فقط @یوزرنیم، همیشه کلیک‌پذیر)")],
        [mk("custom", "📝 متنِ کاملاً دلخواه (چندخطی، هرچی خودت بخوای)")],
        [_btn("🔙 بازگشت به امضا", "menu:footer")],
    ]
    return with_home(rows)


# ==================== قالب‌بندی متن ====================

def format_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    preserve = db.setting_get_bool("preserve_formatting", True, owner_user_id=owner_user_id)
    remove_links = db.setting_get_bool("remove_source_links", True, owner_user_id=owner_user_id)
    min_len_on = db.setting_get_bool("min_content_filter_enabled", True, owner_user_id=owner_user_id)
    rows = [
        [_btn(f"حفظ بولد/ایتالیک/...: {_badge(preserve)}", "fmt:preserve_toggle")],
        [_btn(f"حذف لینک/آدرس/شماره‌تلفن/منشنِ کانال مبدأ: {_badge(remove_links)}", "fmt:removelinks_toggle")],
        [_btn("✂️ حداکثر طول کپشن", "fmt:maxlen")],
        [_btn(f"رد کردنِ پست‌های خیلی کوتاه (فقط متنی): {_badge(min_len_on)}", "fmt:minlen_toggle")],
        [_btn("🔢 حداقل تعداد کلمه", "fmt:minwords")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


# ==================== فیلترِ پست‌های تبلیغاتی ====================

def _phrase_count(owner_user_id: int | None = None) -> int:
    from .formatter import parse_phrases
    return len(parse_phrases(db.setting_get("ad_filter_remove_phrases", "", owner_user_id=owner_user_id)))


def ad_filter_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    enabled = db.setting_get_bool("ad_filter_enabled", False, owner_user_id=owner_user_id)
    action = db.setting_get("ad_filter_action", "skip", owner_user_id=owner_user_id)
    action_fa = "🗑 رد کردنِ کامل" if action == "skip" else "🚩 ارسال برای بررسیِ دستی"
    file_enabled = db.setting_get_bool("file_filter_enabled", True, owner_user_id=owner_user_id)
    smart = db.setting_get_bool("ad_filter_smart", True, owner_user_id=owner_user_id)
    fb_total = sum(s["total"] for s in db.get_ad_feedback_channel_stats(owner_user_id=owner_user_id))
    rows = [
        [_btn(f"🔘 وضعیت: {_badge(enabled)}", "adf:toggle")],
        [_btn(f"🧠 تشخیصِ هوشمند (داوریِ AI روی همه‌ی پست‌ها): {_badge(smart)}", "adf:smart_toggle")],
        [_btn("🚫 غیرفعال‌سازیِ هوشمند برای کانال‌های خاص", "adf:smart_channels")],
        [_btn(f"⚙️ اقدام: {action_fa}", "adf:action_menu")],
        [_btn("📝 ویرایش کلیدواژه‌ها", "adf:keywords"), _btn("♻️ ریست کلیدواژه‌ها", "adf:reset_keywords")],
        [_btn("👥 آستانه‌ی تعداد منشن", "adf:min_mentions"), _btn("🔗 آستانه‌ی تعداد لینک", "adf:min_links")],
        [_btn("🎚 حساسیتِ کلی (آستانه‌ی امتیاز)", "adf:threshold")],
        [_btn("🧪 تستِ یک متنِ نمونه", "adf:test")],
        [_btn(f"📊 آمارِ فیدبکِ فیلترِ تبلیغات ({fb_total})", "adf:feedback_stats")],
        [_btn(f"🧹 حذفِ عبارت/ایموجی از متنِ پست ({_phrase_count(owner_user_id)})", "adf:phrases")],
        [_btn("➕ افزودنِ عبارت", "adf:phrases_add"), _btn("🗑 پاک‌کردنِ لیست", "adf:phrases_clear")],
        [_btn(f"📦 فیلترِ فایل/اپ (APK و...): {_badge(file_enabled)}", "adf:file_toggle")],
        [_btn("✏️ ویرایشِ پسوندهای مسدود", "adf:file_ext"), _btn("♻️ ریست پسوندها", "adf:file_reset_ext")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


# ==================== منویِ آمارِ فیدبکِ فیلترِ تبلیغات ====================
# owner_user_id این‌جا هم مثلِ همه‌جایِ دیگه‌یِ این فایل پاس داده می‌شه، ولی
# معنیِ None توی لایه‌ی دیتابیس فرق می‌کنه - نگاه کن به
# database._ad_feedback_owner_clause (هیچ‌وقت «همه‌ی کاربرها با هم» نیست).
def ad_feedback_stats_menu(owner_user_id: int | None = None, page: int = 0) -> InlineKeyboardMarkup:
    stats = db.get_ad_feedback_channel_stats(owner_user_id=owner_user_id)
    rows: list[list[InlineKeyboardButton]] = []
    buttons = []
    for s in stats:
        name = s["channel_name"]
        if len(name) > 22:
            name = name[:21] + "…"
        label = f"{name} · ✅{s['correct']} ❌{s['incorrect']} ({s['accuracy']}٪)"
        buttons.append(_btn(label, f"adf:fbstats_ch:{s['channel_id']}"))
    page_items, page, total_pages = _paginate(buttons, page, per_page=8)
    rows.extend(_grid(page_items, cols=1))
    nav = _page_nav_row(page, total_pages, "adf:fbstats_page:")
    if nav:
        rows.append(nav)
    if stats:
        rows.append([_btn("📥 دریافتِ خروجیِ اکسلِ کامل", "adf:fbstats_excel")])
    rows.append([_btn("🔙 بازگشت", "menu:adfilter")])
    return InlineKeyboardMarkup(rows)


def ad_feedback_channel_menu(channel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("📥 خروجیِ اکسلِ همین کانال", f"adf:fbstats_excel_ch:{channel_id}")],
        [_btn("🔙 بازگشت به لیستِ کانال‌ها", "adf:feedback_stats")],
    ])




def ad_filter_smart_channels_menu(owner_id: int | None = None) -> InlineKeyboardMarkup:
    """لیستِ کانال‌های مبدأ (فقط مالِ همون کاربر، یا همه اگه ادمین) با وضعیتِ
    فیلترِ هوشمند (AI) برای هر کدوم؛ با زدنِ هر کانال، وضعیتش toggle می‌شه."""
    channels = db.list_channels() if owner_id is None else db.list_channels(owner_user_id=owner_id)
    rows = []
    for ch in channels:
        off = db.get_channel_override(ch["id"], "ad_filter_smart_enabled") is False
        mark = "🔴 هوشمند خاموش" if off else "🟢 هوشمند روشن"
        name = ch["title"] or f"@{ch['username']}"
        rows.append([_btn(f"{mark} — {name}", f"adf:smart_ch_toggle:{ch['id']}")])
    rows.append([_btn("🔙 بازگشت", "menu:adfilter")])
    return with_home(rows)


def ad_filter_action_menu(owner_user_id: int | None = None) -> InlineKeyboardMarkup:
    action = db.setting_get("ad_filter_action", "skip", owner_user_id=owner_user_id)

    def mk(key, label):
        mark = "✅ " if key == action else "⬜️ "
        return _btn(mark + label, f"adf:setaction:{key}")

    rows = [
        [mk("skip", "🗑 رد کردنِ کامل (اصلاً ارسال نشه)")],
        [mk("review", "🚩 ارسال برای بررسیِ دستیِ ادمین")],
        [_btn("🔙 بازگشت", "menu:adfilter")],
    ]
    return with_home(rows)


# ==================== مدیریت کاربران ====================

def users_menu(page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    buttons = []
    for u in db.list_users():
        status = "🟢" if u["active"] else "⚪️"
        tid = f" ({u['telegram_id']})" if u["telegram_id"] else ""
        buttons.append(_btn(f"{status} {u['name']}{tid}", f"usr:view:{u['id']}"))
    page_items, page, total_pages = _paginate(buttons, page)
    rows.extend(_grid(page_items))
    nav = _page_nav_row(page, total_pages, "usr:page:")
    if nav:
        rows.append(nav)
    rows.append([_btn("➕ افزودن کاربر", "usr:add")])
    rows.append([_btn("🔙 بازگشت به منو", "menu:main")])
    return InlineKeyboardMarkup(rows)


def user_detail_menu(user_id: int) -> InlineKeyboardMarkup:
    u = db.get_user(user_id)
    toggle_label = "🟢 غیرفعال کن" if u and u["active"] else "🔴 فعال کن"
    rows = [
        [_btn("📡 کانال‌های مبدأ این کاربر", f"usr:srcmap:{user_id}")],
        [_btn("🎯 کانال‌های مقصد این کاربر", f"usr:dstmap:{user_id}")],
        [_btn("🔒 دسترسی‌ها", f"usr:perms:{user_id}")],
        [_btn("✏️ تغییر کانال تایید", f"usr:setapproval:{user_id}")],
        [_btn("🔑 تنظیم آیدی تلگرام", f"usr:settid:{user_id}")],
        [_btn(toggle_label, f"usr:toggle:{user_id}"), _btn("🗑 حذف", f"usr:remove:{user_id}")],
        [_btn("🔙 بازگشت به لیست", "menu:users")],
    ]
    return with_home(rows)


PERMISSION_LABELS: dict[str, str] = {
    # توجه: عمداً ✅ نداره (برخلافِ بقیه‌ی لیبل‌ها که هرکدوم ایموجیِ خودشون رو
    # دارن) — چون این لیبل با نشانگرِ 🟢/⬜️ِ روشن/خاموش ترکیب می‌شه، اگه ✅
    # ثابت داشت، دکمه صرفِ‌نظر از وضعیتِ واقعی همیشه سبز نشون داده می‌شد
    # (رنگِ خودکارِ ایموجی در button_config.py اول دنبالِ ✅ می‌گرده).
    "pp_own": "🙋 تایید پست خودش",
    "pp_edit": "✏️ ویرایش پست خودش",
    "pp_all": "👑 تایید پست همه",
    "src": "📡 کانال‌های مبدأ",
    "dst": "🎯 کانال‌های مقصد",
    "wm": "🏷 واترمارک",
    "ai": "🧠 هوش مصنوعی",
    "format": "🔠 قالب‌بندی متن",
    "footer": "✍️ امضای پایان پست",
    "adfilter": "🚫 فیلتر تبلیغات",
    "manual": "📮 ارسالِ دستی و زمان‌بندی",
}


def user_permissions_menu(user_id: int) -> InlineKeyboardMarkup:
    perms = db.get_permissions(user_id)
    rows = []
    for key, label in PERMISSION_LABELS.items():
        mark = "🟢" if perms.get(key) else "⬜️"
        rows.append([_btn(f"{mark} {label}", f"usr:permtoggle:{key}:{user_id}")])
    rows.append([_btn("🔙 بازگشت", f"usr:view:{user_id}")])
    return with_home(rows)


def user_srcmap_menu(user_id: int) -> InlineKeyboardMarkup:
    owned = db.channels_of_user(user_id)
    rows = []
    for ch in db.list_channels():
        mark = "✅" if ch["id"] in owned else "⬜️"
        label = ch["title"] or f"@{ch['username']}"
        rows.append([_btn(f"{mark} {label}", f"usr:srcmap_toggle:{user_id}:{ch['id']}")])
    rows.append([_btn("🔙 بازگشت", f"usr:view:{user_id}")])
    return with_home(rows)


def user_dstmap_menu(user_id: int) -> InlineKeyboardMarkup:
    owned = db.destinations_of_user(user_id)
    rows = []
    for d in db.list_destinations():
        mark = "✅" if d["id"] in owned else "⬜️"
        label = d["title"] or d["chat_id"]
        rows.append([_btn(f"{mark} {label}", f"usr:dstmap_toggle:{user_id}:{d['id']}")])
    rows.append([_btn("🔙 بازگشت", f"usr:view:{user_id}")])
    return with_home(rows)


def my_approval_menu() -> InlineKeyboardMarkup:
    rows = [
        [_btn("✏️ تغییر کانال تایید", "myapp:edit")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def confirm_remove_user_menu(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("✅ بله، حذف کن", f"usr:remove_confirm:{user_id}"),
         _btn("❌ انصراف", f"usr:view:{user_id}")],
    ])


def cancel_input_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("❌ انصراف", "input:cancel")]])


def skip_input_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("⏭ رد کردن (بدون اسم)", "input:skip_name")],
        [_btn("❌ انصراف", "input:cancel")],
    ])


# ==================== منوهای جدید برای قابلیت‌های ۱۰ گانه ====================

def resource_menu() -> InlineKeyboardMarkup:
    from .resource_monitor import ResourceMonitor
    settings = ResourceMonitor.get_settings()
    cpu_th = settings.get("cpu_threshold", 80)
    ram_th = settings.get("ram_threshold", 80)
    disk_th = settings.get("disk_threshold", 85)
    enabled = settings.get("enabled", True)
    rows = [
        [_btn("🖥 وضعیت لحظه‌ای", "res:stats")],
        [_btn(f"🔧 آستانه CPU: {cpu_th}%", "res:set_cpu"), _btn(f"آستانه RAM: {ram_th}%", "res:set_ram")],
        [_btn(f"آستانه دیسک: {disk_th}%", "res:set_disk"), _btn(f"🔘 وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", "res:toggle")],
        [_btn("✉️ کانال اعلان‌های منابع", "res:set_chat")],
        [_btn("🔔 تنظیمات اعلان‌های ادمین", "notif:menu")],
        [_btn("📋 مشاهده لاگ‌ها", "res:logs")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def notification_menu() -> InlineKeyboardMarkup:
    from .notification_manager import NotificationManager
    s = NotificationManager.get_settings()
    enabled = s.get("enabled", True)
    chat_id = s.get("chat_id") or "تنظیم نشده"
    rows = [
        [_btn(f"وضعیت اعلان‌ها: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", "notif:toggle")],
        [_btn(f"📢 کانال اختصاصی اعلان‌ها: {chat_id}", "notif:setchat")],
        [_btn("🧹 حذف کانال اختصاصی", "notif:clearchat")],
        [_btn("🔙 بازگشت به مانیتورینگ", "menu:resources")],
    ]
    return with_home(rows)


def dst_smart_menu(destination_id: int) -> InlineKeyboardMarkup:
    from .smart_scheduler import SmartScheduler
    on = SmartScheduler.is_enabled(destination_id)
    rows = [
        [_btn(f"🧠 زمان‌بندی هوشمند: {'🟢 فعال' if on else '🔴 غیرفعال'}", f"dst:smarttoggle:{destination_id}")],
        [_btn("🔄 بروزرسانی آمار", f"dst:smart:{destination_id}")],
        [_btn("🔙 بازگشت به کانال", f"dst:view:{destination_id}")],
    ]
    return with_home(rows)


def backup_menu() -> InlineKeyboardMarkup:
    from .backup_manager import BackupManager, format_backup_time_12h, has_backup_password
    settings = BackupManager.get_settings()
    enabled = settings.get("enabled", True)
    time = settings.get("time", "03:00")
    time_label = format_backup_time_12h(time)
    chat_id = settings.get("chat_id", "تنظیم نشده")
    pw_label = "🟢 تنظیم‌شده" if has_backup_password() else "🔴 تنظیم‌نشده (لازم برای بازیابی روی ربات/توکنِ دیگر)"
    rows = [
        [_btn(f"🔘 وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}", "backup:toggle")],
        [_btn(f"⏰ ساعت بکاپ: {time_label}", "backup:set_time")],
        [_btn(f"📤 ارسال به کانال: {chat_id}", "backup:set_chat")],
        [_btn(f"🔑 رمزِ بکاپ: {pw_label}", "backup:set_password")],
        [_btn("📦 ایجاد بکاپ فوری", "backup:now")],
        [_btn("🔄 بازیابی از بکاپ", "backup:restore")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def backup_ampm_menu(hour_12: int, minute: int) -> InlineKeyboardMarkup:
    """انتخابِ AM/PM بعدِ وارد کردنِ ساعتِ ۱۲ساعته برای زمان‌بندیِ بکاپ."""
    return InlineKeyboardMarkup([
        [
            _btn("🌅 صبح (AM)", f"backup:ampm:AM:{hour_12}:{minute}"),
            _btn("🌇 بعدازظهر/شب (PM)", f"backup:ampm:PM:{hour_12}:{minute}"),
        ],
        [_btn("❌ انصراف", "input:cancel")],
    ])


def ai_services_menu() -> InlineKeyboardMarkup:
    # برچسب‌ها از همان کاتالوگِ «مسیریابیِ وظایف» خوانده می‌شن تا نامِ هر سرویس در
    # صفحه‌ی اصلیِ هوش مصنوعی و در مسیریابیِ وظایف همیشه دقیقاً یکی باشه (یک منبعِ
    # حقیقتِ واحد). callbackها ثابت می‌مونن؛ فقط متنِ دکمه از کاتالوگ میاد.
    from . import ai_catalog as _cat

    def _lbl(task_id: str, fallback: str) -> str:
        t = _cat.ALL_TASKS.get(task_id)
        return t.label if t else fallback

    rows = [
        [_btn(_lbl("translate", "🌐 ترجمه"), "ai:translate"),
         _btn(_lbl("summarize", "📝 خلاصه‌سازی"), "ai:summarize"),
         _btn(_lbl("rewrite", "🔄 بازنویسی"), "ai:rewrite")],
        [_btn(_lbl("fix_text", "🩹 اصلاح املا/گرامر"), "ai:fix_text"),
         _btn(_lbl("generate_hashtags", "#️⃣ تولید هشتگ"), "ai:hashtags"),
         _btn(_lbl("prompt_writer", "🧠 پرامپت‌نویس"), "ai:prompt_writer")],
        [_btn(_lbl("generate_caption", "💬 تولید کپشن"), "ai:caption"),
         _btn(_lbl("generate_title", "🏷 تولید عنوان"), "ai:title"),
         _btn(_lbl("analyze_text", "🔍 تحلیل متن"), "ai:analyze_text")],
        # ⚠️ «🤖 پاسخ خودکار» عمداً از این صفحه برداشته شد (درخواستِ کاربر).
        # خودِ وظیفه‌ی auto_reply زنده می‌مونه: «💬 چت با AI» از همین مسیر
        # استفاده می‌کنه (ai_router.chat → try_custom_text("auto_reply", ...))،
        # پس ردیفش در «🔀 مسیریابیِ وظایف» هم سرِ جاش می‌مونه و کارآمده.
        [_btn(_lbl("generate_image", "🖼 تولید تصویر"), "ai:image"),
         _btn(_lbl("edit_image", "🎨 تغییر استایل عکس"), "ai:style_image")],
        [_btn("🔎 جست‌وجویِ وب", "ai:web_search")],
        [_btn("💬 چت با AI", "ai:request")],
        [_btn("🔌 مدیریتِ API هوش مصنوعی", "aiapi:home")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def ai_web_search_menu() -> InlineKeyboardMarkup:
    # یک ورودیِ واحد؛ نوعِ جست‌وجو (عکس/خبر) از خودِ متن تشخیص داده می‌شه.
    rows = [
        [_btn("🔎 جست‌وجو (بنویس: «عکس ...» یا «اخبار ...»)", "ai:web_search_go")],
        [_btn("⚙️ تنظیمِ کلیدهای SerpAPI", "ai:web_settings")],
        [_btn("🔙 بازگشت", "menu:ai_services")],
    ]
    return InlineKeyboardMarkup(rows)


def ai_web_settings_menu() -> InlineKeyboardMarkup:
    from .web_search import MAX_KEYS
    rows = [[_btn(f"🔑 کلیدِ SerpAPI شماره‌ی {i+1}", f"ai:web_set:{i}")] for i in range(MAX_KEYS)]
    rows.append([_btn("🗑 پاک‌کردنِ همه‌ی کلیدها", "ai:web_clear")])
    rows.append([_btn("🔙 بازگشت", "ai:web_search")])
    return InlineKeyboardMarkup(rows)


def ai_translate_lang_menu() -> InlineKeyboardMarkup:
    """انتخابِ زبانِ مقصد قبل از ترجمه‌ی هوشمند."""
    rows = [
        [_btn("🔁 خودکار (برعکسِ زبانِ متن)", "ai:translate_lang:auto")],
        [_btn("🇮🇷 فارسی", "ai:translate_lang:fa"), _btn("🇬🇧 انگلیسی", "ai:translate_lang:en"), _btn("🇸🇦 عربی", "ai:translate_lang:ar")],
        [_btn("🔙 بازگشت", "menu:ai_services")],
    ]
    return InlineKeyboardMarkup(rows)


def ai_summarize_level_menu() -> InlineKeyboardMarkup:
    """انتخابِ سطحِ خلاصه‌سازی قبل از دریافتِ متن."""
    rows = [
        [_btn("⚡️ فوق‌کوتاه", "ai:summarize_level:short"), _btn("📄 متوسط", "ai:summarize_level:medium"), _btn("📚 مفصل", "ai:summarize_level:detailed")],
        [_btn("🔙 بازگشت", "menu:ai_services")],
    ]
    return InlineKeyboardMarkup(rows)


def ai_style_options_menu() -> InlineKeyboardMarkup:
    """پریست‌هایِ آماده‌ی تغییرِ استایلِ عکس (بعد از دریافتِ خودِ عکس)."""
    rows = [
        [_btn("🎨 نقاشیِ رنگ‌روغن", "ai:style_preset:oil"), _btn("🖊 سیاه‌قلم", "ai:style_preset:sketch")],
        [_btn("🌆 سایبرپانک", "ai:style_preset:cyberpunk"), _btn("🧊 انیمه", "ai:style_preset:anime")],
        [_btn("🧱 سه‌بعدیِ کارتونی", "ai:style_preset:3dcartoon"), _btn("🕰 وینتیج", "ai:style_preset:vintage")],
        [_btn("✍️ توضیحِ دلخواه...", "ai:style_preset:custom")],
        [_btn("🔙 بازگشت", "menu:ai_services")],
    ]
    return InlineKeyboardMarkup(rows)


def ai_chat_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("🔚 پایان چت", "ai:chat_end")]])


def public_channel_menu() -> InlineKeyboardMarkup:
    from .public_report_channel import PublicReportChannel
    chat_id = PublicReportChannel.get_chat_id()
    rows = [
        [_btn(f"📢 کانال فعلی: {chat_id or 'تنظیم نشده'}", "pub:set_chat")],
        [_btn("🔙 بازگشت به منو", "menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def logs_filter_menu() -> InlineKeyboardMarkup:
    rows = [
        [_btn("📋 همه لاگ‌ها", "logs:all")],
        [_btn("❌ خطاها", "logs:errors")],
        [_btn("✅ موفقیت‌ها", "logs:success")],
        [_btn("📡 بر اساس کانال مبدأ", "logs:by_channel")],
        [_btn("🎯 بر اساس کانال مقصد", "logs:by_destination")],
        [_btn("👤 بر اساس کاربر", "logs:by_user")],
        [_btn("🔙 بازگشت", "menu:resources")],
    ]
    return InlineKeyboardMarkup(rows)

# ============================================================================
# اعمالِ رنگِ دکمه‌های منو (طبقِ bot/button_config.py:MENU_BUTTON_COLORS)
# ----------------------------------------------------------------------------
# همه‌ی توابعِ این ماژول که InlineKeyboardMarkup برمی‌گردونن، به‌صورتِ مرکزی از
# فیلترِ رنگ رد می‌شن — بدونِ نیاز به دست‌زدن به تک‌تکِ منوها. اگه هیچ رنگی توی
# button_config تعریف نشده باشه، این کار هیچ اثری نداره (منوها دست‌نخورده می‌مونن).
# (_button_style بالای فایل import شده - برای رنگِ دکمه‌های کیبوردِ رِپلای هم
# همون importِ بالا استفاده می‌شه.)
import sys as _sys  # noqa: E402

_button_style.install_menu_colors(_sys.modules[__name__])
