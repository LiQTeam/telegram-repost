"""
تنظیماتِ مرکزیِ دکمه‌های رنگی — همه‌ی دکمه‌ها (زیرِ پستِ مقصد، تبلیغات، و منوهای
ادمین/کاربری) از همین یک فایل کنترل می‌شن. برای تغییرِ رنگ/متن/لینک/زمان‌بندی فقط
همین فایل رو ویرایش کن و ربات رو ری‌استارت کن.

رنگ‌های مجاز (همون رنگ‌های ازپیش‌تعریف‌شده‌ی تلگرام):
    "primary"  → آبیِ تیره
    "danger"   → قرمز
    "success"  → سبز
    None        → پیش‌فرض (بی‌رنگ/شفاف)

نکته: رنگ فقط با اپلیکیشن‌های به‌روزِ تلگرام دیده می‌شه؛ نسخه‌های قدیمی همون دکمه‌ی
پیش‌فرض رو نشون می‌دن. هیچ کتابخانه‌ی جدیدی لازم نیست.
"""
from __future__ import annotations

# رنگ‌های معتبر (برای اعتبارسنجی؛ مقدارِ نامعتبر نادیده گرفته و بی‌رنگ فرض می‌شه)
VALID_COLORS = {"primary", "danger", "success"}


# ============================================================================
# ۱) دکمه‌های زیرِ پست‌های ری‌پست‌شده — به تفکیکِ کانالِ مقصد
# ----------------------------------------------------------------------------
# هر مقصد رو با «آیدیِ عددیِ کانال» (chat_id، مثل -1001234567890) یا با
# «یوزرنیم» (مثل "@myChannel") کلید می‌زنی. برای هر مقصد می‌تونی:
#   - enabled: True/False  → این مقصد اصلاً دکمه بگیره یا نه
#   - time_window: بازه‌ی ساعتی که دکمه‌ها می‌شینن (وقتِ تهران، ۰ تا ۲۴)
#         {"start": 8, "end": 23}  → فقط بینِ ۸ صبح تا ۲۳ دکمه بذار
#         {"start": 22, "end": 6}  → بازه‌ی شبانه (از ۲۲ تا ۶ صبح)
#         None                      → همیشه (۲۴ساعته)
#   - buttons: لیستِ ۱ تا ۴ دکمه؛ هر دکمه {"text", "url", "color"}
#         url = همون کانالی که با زدنِ دکمه کاربر بهش می‌ره.
#
# هر مقصدی که این‌جا تعریف نشه، از DEFAULT_REPOST پیروی می‌کنه.
REPOST_BUTTONS: dict = {
    # نمونه (کامنت رو بردار و ویرایش کن):
    # -1001234567890: {
    #     "enabled": True,
    #     "time_window": {"start": 8, "end": 23},
    #     "buttons": [
    #         {"text": "دریافت کانفیگ رایگان | نامحدود", "url": "https://t.me/vfreepn", "color": "danger"},
    #         {"text": "کانالِ دوم",                      "url": "https://t.me/second",  "color": "primary"},
    #     ],
    # },
    # "@myChannel": {
    #     "enabled": False,   # این مقصد هیچ دکمه‌ای نگیره
    # },
}

# پیش‌فرض برای هر مقصدی که در REPOST_BUTTONS تعریف نشده.
# اگه می‌خوای مقصدهای تعریف‌نشده هیچ دکمه‌ای نگیرن، "enabled" رو False کن.
DEFAULT_REPOST: dict = {
    "enabled": True,
    "time_window": None,   # همیشه
    "buttons": [
        {"text": "دریافت کانفیگ رایگان | نامحدود", "url": "https://t.me/vfreepn", "color": "danger"},
    ],
}

# چند دکمه در هر ردیف چیده بشه (۱ تا ۴).
REPOST_BUTTONS_PER_ROW = 1

# اگه متنِ یک پست شاملِ این نشانه باشه، زیرِ اون پستِ خاص هیچ دکمه‌ای گذاشته نمی‌شه.
# (برای وقتی دستی می‌خوای زیرِ یه پستِ مشخص دکمه نیاد.) خالی بذاری یعنی غیرفعال.
NO_BUTTON_MARKER = "#nobtn"


# ============================================================================
# ۲) رنگِ دکمه‌های بخشِ تبلیغات
# ----------------------------------------------------------------------------
# متن و لینکِ دکمه‌های تبلیغ همون‌جای همیشگی (منوی تبلیغات) تنظیم می‌شن؛ این‌جا فقط
# رنگ اضافه می‌شه. اگه یه دکمه‌ی تبلیغ رنگِ اختصاصیِ ذخیره‌شده نداشته باشه، این رنگ
# روش می‌شینه. None یعنی بی‌رنگ.
ADS_DEFAULT_COLOR = "primary"


# ============================================================================
# ۳) رنگِ دکمه‌های منوی ادمین/کاربری
# ----------------------------------------------------------------------------
# هر دکمه‌ی منو یک callback_data داره (شناسه‌ی داخلیِ دکمه). این‌جا با اون
# callback_data (یا پیشوندش) رنگ رو تعیین می‌کنی. تطبیق: اول تطبیقِ کامل، بعد
# طولانی‌ترین پیشوندِ منطبق. کلیدِ "*" رنگِ پیش‌فرضِ همه‌ی دکمه‌های منوست.
#
# این دیکشنری («رنگِ ثابت») بالاترین اولویت رو داره — حتی جلوترِ از رنگِ
# خودکارِ ایموجی (بخشِ بعدی) می‌شینه. برای همینه که مثلاً "adf:file_toggle"
# با اینکه توی متنش 🟢/🔴 داره، همیشه آبیِ ثابت می‌مونه.
#
# مثال:
#   "*": "primary",         # همه‌ی دکمه‌های منو آبی
#   "del_": "danger",       # هر دکمه‌ای که callback_dataش با del_ شروع شه قرمز
#   "confirm": "success",   # دکمه‌ی دقیقاً confirm سبز
MENU_BUTTON_COLORS: dict = {
    # --- primary: تکِ اکشنِ اصلیِ هر صفحه («این یکی رو بزن») ---
    "menu:main": "primary",       # 🔙 بازگشت به منو / 🏠 بازگشت به منویِ اصلی (همه‌جا)
    "res:stats": "primary",       # صفحه‌ی مانیتورینگ
    "res:set_cpu": "success",     # صفحه‌ی مانیتورینگ — «آستانه CPU»
    "res:set_ram": "success",     # صفحه‌ی مانیتورینگ — «آستانه RAM»
    "res:set_disk": "success",    # صفحه‌ی مانیتورینگ — «آستانه دیسک»
    "logs:all": "primary",        # صفحه‌ی فیلترِ لاگ — همه‌ی گزینه‌ها هم‌رتبه‌ن
    "logs:errors": "primary",
    "logs:success": "primary",
    "logs:by_channel": "primary",
    "logs:by_destination": "primary",
    "logs:by_user": "primary",
    "src:destmap:": "primary",    # جزئیاتِ کانال مبدأ/اکستنشن — «کانال‌های مقصدِ این کانال»
    "src:mode_menu:": "primary",  # جزئیاتِ کانال مبدأ — «حالتِ ارسال»
    "usr:setapproval:": "primary", # جزئیاتِ کاربر — «تغییر کانال تایید»
    "usr:perms:": "primary",      # جزئیاتِ کاربر — «دسترسی‌ها» (هم‌رتبه با دو تایِ بالا؛
                                   # قبلاً جا افتاده بود و تنها دکمه‌ی بی‌رنگِ این صفحه بود)
    "backup:restore": "primary",  # صفحه‌ی بکاپ — «بازیابی از بکاپ»
    "dst:cfg:": "primary",        # جزئیاتِ مقصد — «تنظیماتِ اختصاصیِ این مقصد»
    "adf:min_mentions": "primary",  # فیلترِ تبلیغات — «آستانه‌ی تعداد منشن»
    "adf:min_links": "primary",     # فیلترِ تبلیغات — «آستانه‌ی تعداد لینک»
    "adf:file_toggle": "primary", # فیلترِ تبلیغات — «فیلترِ فایل/اپ»؛ عمداً آبیِ ثابته،
                                   # با اینکه بجِش (🟢/🔴) عوض می‌شه (نه رنگِ خودکار).
    "pp:editcap:": "primary",     # صفِ تایید — «ویرایش کپشن»
    "pp:editphoto:": "primary",   # صفِ تایید — «تغییر عکس»
    "pp:editvideo:": "primary",   # صفِ تایید — «تغییر ویدیو»
    "dst:add": "primary",         # ➕ افزودن کانال مقصد (هم توی لیستِ مقصدها هم توی منوی مقصدها؛ هر دو یک callback دارن)
    "src:add": "primary",         # ➕ افزودن کانال مبدأ

    # --- success: افزودن/ایجاد/تاییدِ نهایی/ویرایشِ فهرست‌ها ---
    "usr:add": "success",
    "adf:phrases_add": "success",
    "pp:approve:": "success",   # ✅ تایید و ارسالِ پستِ صفِ تایید
    "adf:keywords": "success",  # فیلترِ تبلیغات — «ویرایش کلیدواژه‌ها»
    "adf:file_ext": "success",  # فیلترِ تبلیغات — «ویرایشِ پسوندهای مسدود»
    "usr:srcmap:": "success",   # جزئیاتِ کاربر — «کانال‌های مبدأ این کاربر»
    "usr:dstmap:": "success",   # جزئیاتِ کاربر — «کانال‌های مقصد این کاربر»
    "pp:adfb:1:": "success",    # صفِ تایید — فیدبک «✅ درست بود» (اتوکالر هم همینو می‌ده، صریح‌تر بهتره)
    "ai:status_services": "success",  # منویِ هوشِ مصنوعی — «وضعیت AI»
    "ai:rewrite": "primary",          # منویِ هوشِ مصنوعی — «بازنویسی خلاقانه»
    "ai:summarize": "primary",        # منویِ هوشِ مصنوعی — «خلاصه‌سازی»

    # --- danger: حذف/رد/پاک‌سازی/ریست — مخرب یا غیرقابلِ‌برگشت ---
    # (توجه: اگه متنِ دکمه ✅ داشته باشه، رنگِ خودکارِ سبز رو بجای این‌ها
    # می‌گیره — چون رنگِ خودکارِ ایموجی جلوترِ از این لیست چک می‌شه. مثلاً
    # "src:remove_confirm:" با اینکه اینجا danger تعریف شده، چون متنش
    # «✅ بله، حذف کن» ه، سبز نشون داده می‌شه.)
    "src:remove_confirm:": "danger",
    "backup:now": "danger",       # صفحه‌ی بکاپ — «ایجاد بکاپ فوری»
    "res:logs": "danger",         # صفحه‌ی مانیتورینگ — «مشاهده لاگ‌ها»
    "pp:adfb:0:": "danger",       # صفِ تایید — فیدبک «❌ اشتباه بود»
    "dst:remove_confirm:": "danger",
    "extsrc:remove_confirm:": "danger",
    "usr:remove_confirm:": "danger",
    "src:remove:": "danger",
    "dst:remove:": "danger",
    "extsrc:remove:": "danger",
    "usr:remove:": "danger",
    "adf:phrases_clear": "danger",
    "adf:reset_keywords": "danger",
    "adf:file_reset_ext": "danger",
    "notif:clearchat": "danger",
    "ai:cache_clear": "danger",
    "pp:reject:": "danger",     # ❌ ردِ پستِ صفِ تایید
    "pp:wm_reset:": "danger",   # ♻️ پاک‌کردنِ واترمارک‌های چیده‌شده روی یک پست
}

# ============================================================================
# ۴) رنگِ خودکار بر اساسِ ایموجیِ متنِ دکمه (برای دکمه‌های فعال/غیرفعال)
# ----------------------------------------------------------------------------
# خیلی از دکمه‌های toggle (مثلِ "adf:toggle" یا "dst:toggle:") وضعیتِ فعلی‌شون
# رو با ✅/🟢/🔴 توی خودِ متنِ دکمه نشون می‌دن؛ چون یک callback_data می‌تونه دو
# وضعیتِ متفاوت داشته باشه (مثلاً "adf:toggle" هم موقعِ فعال هم غیرفعال)، رنگش
# نمی‌تونه فقط از رویِ callback_data تعیین بشه — باید متنِ لحظه‌ایِ دکمه رو هم
# دید. اولویت: اول ✅ (سبز)، بعد 🔴 (قرمز)، بعد 🟢 (سبز).
#
# استثنا: فهرستِ کانال‌های مقصد/مبدأ (نقطه‌ی 🟢/⚪️ کنارِ اسمِ هر کانال توی
# لیست) صرفاً یک نشانگرِ وضعیته، نه یک دکمه‌ی toggle — رنگی نمی‌شن و همیشه
# سفید/بی‌رنگ می‌مونن، حتی وقتی کانال فعاله (🟢).
EMOJI_AUTOCOLOR_EXCLUDED_PREFIXES = ("src:view:", "dst:view:")


# ============================================================================
# ۳-الف) رنگِ ثابتِ اولویت‌دار برای دکمه‌هایی که شناسه‌ی دینامیک دارن
# ----------------------------------------------------------------------------
# تطبیقِ پیشوندیِ MENU_BUTTON_COLORS (بخشِ ۳) عمداً بعد از رنگِ خودکارِ ایموجی
# چک می‌شه — همون چیزی که باعث می‌شه مثلاً «✅ بله، حذف کن» سبز بشه، نه قرمزِ
# پیش‌فرضِ src:remove_confirm:. برای بیشترِ toggleها این رفتار درسته. ولی
# بعضی دکمه‌ها (toggle یا یه اکشنِ یک‌طرفه) یک شناسه‌ی دینامیک (مثلِ
# destination_id) توی callback_data دارن، پس نمی‌شه براشون در MENU_BUTTON_COLORS
# تطبیقِ کامل نوشت؛ اگه فقط با پیشوند تعریف بشن و متن‌شون ایموجیِ خودکاررنگ‌کن
# (✅/🔴/🟢) داشته باشه، رنگِ خودکار رو می‌گیرن نه رنگِ دلخواه. این دیکشنری
# دقیقاً برای همین موردهاست: تطبیقِ پیشوندی، ولی جلوترِ از رنگِ خودکار چک
# می‌شه (مثلِ رفتارِ تطبیقِ کاملِ بخشِ ۳) — یعنی رنگش تضمینیه، مستقلِ از هر
# ایموجی‌ای که الان یا بعداً توی متنِ دکمه باشه.
FORCED_PREFIX_COLORS: dict = {
    "dst:footertoggle:": "primary",  # ✍️ امضای اختصاصی: روشن/خاموش (تنظیماتِ اختصاصیِ مقصد)
    "dst:adftoggle:": "primary",     # 🚫 فیلترِ تبلیغاتِ اختصاصی: روشن/خاموش (همون منو)
    "dst:adfph:": "danger",          # 🧹 حذفِ عبارت/ایموجی از متن (منوی فیلترِ تبلیغاتِ مقصد)
    "dst:adfkw:": "danger",          # 🔑 کلیدواژه‌ها (منوی فیلترِ تبلیغاتِ مقصد)
    "src:ov_clear_all:": "danger",   # ♻️ حذفِ همه‌ی تنظیماتِ اختصاصیِ کانال — قرمزِ قطعی،
                                      # صرفِ‌نظر از هر ایموجی‌ای که توی متنش باشه
}


# ============================================================================
# ۵) رنگِ ثابتِ دکمه‌های ناوبریِ «بازگشت» (بر اساسِ متنِ دکمه)
# ----------------------------------------------------------------------------
# این دکمه‌ها (بازگشت به منوی اصلی/منو/لیست/کانال) توی کلِ ربات تکرار می‌شن و
# بعضی‌هاشون callback_data مشترک دارن (مثلاً «🏠 بازگشت به منوی اصلی» و
# «🔙 بازگشت به منو» هر دو به menu:main می‌رن) پس رنگ‌شون رو باید از رویِ
# خودِ متنِ دکمه تعیین کرد، نه callback. تطبیق: اول متنِ کامل، بعد پیشوند
# (مثلاً «🔙 بازگشت به لیست اسلات‌ها» هم زیرِ «🔙 بازگشت به لیست» می‌شینه).
#
# جفت‌بندیِ رنگ: منو + منویِ اصلی هر دو سبز؛ لیست + کانال هر دو آبی.
BACK_NAV_TEXT_COLORS: dict = {
    "🏠 بازگشت به منوی اصلی": "success",   # سبز
    "🔙 بازگشت به منو": "success",         # سبز
    "🔙 بازگشت به لیست": "primary",        # آبی
    "🔙 بازگشت به کانال": "primary",       # آبی
}


# ============================================================================
# منطقِ خالص (بدونِ وابستگی به تلگرام) — تست‌پذیر
# ============================================================================
def _norm_color(color):
    """رنگِ نامعتبر یا خالی → None (بی‌رنگ)."""
    return color if color in VALID_COLORS else None


def within_time_window(window, now_hour: int) -> bool:
    """آیا ساعتِ فعلی (۰-۲۳) داخلِ بازه‌ست؟ بازه‌ی شبانه (start>end) هم پشتیبانی می‌شه.
    window=None یا ناقص یا start==end → همیشه True (۲۴ساعته)."""
    if not window:
        return True
    start = window.get("start")
    end = window.get("end")
    if start is None or end is None:
        return True
    try:
        start = int(start) % 24
        end = int(end) % 24
        now_hour = int(now_hour) % 24
    except (TypeError, ValueError):
        return True
    if start == end:
        return True  # بازه‌ی صفر یا کاملِ ۲۴ساعته
    if start < end:
        return start <= now_hour < end
    # بازه‌ی شبانه، مثلاً ۲۲ تا ۶
    return now_hour >= start or now_hour < end


def resolve_repost_config(chat_id) -> dict:
    """کانفیگِ دکمه‌ی مربوط به یک مقصد رو برمی‌گردونه. اول با کلیدهای مختلف (خودِ
    مقدار، رشته، عدد) داخلِ REPOST_BUTTONS می‌گرده؛ اگه نبود DEFAULT_REPOST."""
    for key in _candidate_keys(chat_id):
        if key in REPOST_BUTTONS:
            return REPOST_BUTTONS[key] or {}
    return DEFAULT_REPOST or {}


def _candidate_keys(chat_id):
    """شکل‌های مختلفِ کلیدِ ممکن برای یک chat_id (عدد/رشته/یوزرنیم)."""
    keys = []
    if chat_id is None:
        return keys
    keys.append(chat_id)
    s = str(chat_id)
    keys.append(s)
    # یوزرنیم با/بدون @
    if s.startswith("@"):
        keys.append(s[1:])
    else:
        keys.append("@" + s)
    # عدد
    try:
        keys.append(int(chat_id))
    except (TypeError, ValueError):
        pass
    # حذفِ تکراری‌ها با حفظِ ترتیب
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def sanitized_repost_buttons(cfg: dict) -> list[dict]:
    """لیستِ دکمه‌های معتبرِ یک کانفیگ رو (حداکثر ۴ تا) با رنگِ نرمال‌شده برمی‌گردونه.
    دکمه‌ی بدونِ text یا url نادیده گرفته می‌شه."""
    raw = (cfg or {}).get("buttons") or []
    out = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        text = (b.get("text") or "").strip()
        url = (b.get("url") or "").strip()
        if not text or not url:
            continue
        out.append({"text": text, "url": url, "color": _norm_color(b.get("color"))})
        if len(out) >= 4:  # سقفِ ۴ دکمه
            break
    return out


def has_no_button_marker(text) -> bool:
    """آیا این متن نشانه‌ی «دکمه نذار» رو داره؟"""
    if not NO_BUTTON_MARKER:
        return False
    return NO_BUTTON_MARKER in (text or "")


def _static_style_for_text(text) -> str | None:
    """رنگِ ثابتِ دکمه‌های ناوبریِ برگشت، بر اساسِ خودِ متنِ دکمه (بخشِ ۵). اول
    تطبیقِ کامل، بعد پیشوند (طولانی‌ترین برنده)."""
    if not text or not BACK_NAV_TEXT_COLORS:
        return None
    if text in BACK_NAV_TEXT_COLORS:
        return _norm_color(BACK_NAV_TEXT_COLORS[text])
    best = None
    for key in BACK_NAV_TEXT_COLORS:
        if text.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is not None:
        return _norm_color(BACK_NAV_TEXT_COLORS[best])
    return None


def _static_style_for_callback(callback_data) -> str | None:
    """رنگِ ثابتِ تعریف‌شده توی MENU_BUTTON_COLORS برای یک callback_data: اول
    تطبیقِ کامل، بعد طولانی‌ترین پیشوندِ منطبق، در نهایت کلیدِ عمومیِ "*"."""
    if not MENU_BUTTON_COLORS or not callback_data:
        return None
    if callback_data in MENU_BUTTON_COLORS:
        return _norm_color(MENU_BUTTON_COLORS[callback_data])
    best = None
    for key in MENU_BUTTON_COLORS:
        if key in ("*", ""):
            continue
        if callback_data.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is not None:
        return _norm_color(MENU_BUTTON_COLORS[best])
    if "*" in MENU_BUTTON_COLORS:
        return _norm_color(MENU_BUTTON_COLORS["*"])
    return None


def _forced_prefix_style(callback_data) -> str | None:
    """رنگِ ثابتِ پیشوندیِ اولویت‌دار (بخشِ ۳-الف) — جلوترِ از رنگِ خودکارِ ایموجی
    چک می‌شه. برخلافِ MENU_BUTTON_COLORS اینجا فقط تطبیقِ پیشوندیه (بدونِ
    تطبیقِ کامل یا کلیدِ "*")."""
    if not FORCED_PREFIX_COLORS or not callback_data:
        return None
    best = None
    for key in FORCED_PREFIX_COLORS:
        if callback_data.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is not None:
        return _norm_color(FORCED_PREFIX_COLORS[best])
    return None


def _autocolor_for_text(text) -> str | None:
    """رنگِ خودکار بر اساسِ ایموجیِ متنِ دکمه (بخشِ ۴ در بالای فایل).
    اولویت: ✅ (سبز) > 🔴 (قرمز) > 🟢 (سبز)."""
    if not text:
        return None
    if "✅" in text:
        return "success"
    if "🔴" in text:
        return "danger"
    if "🟢" in text:
        return "success"
    return None


def style_for_callback(callback_data, text: str | None = None) -> str | None:
    """رنگِ یک دکمه‌ی منو رو تعیین می‌کنه. ترتیبِ اولویت:
      ۱) استثنایِ فهرستِ کانال (EMOJI_AUTOCOLOR_EXCLUDED_PREFIXES) → همیشه بی‌رنگ
      ۲) رنگِ ثابتِ دکمه‌های بازگشت بر اساسِ متن (BACK_NAV_TEXT_COLORS)
      ۳) رنگِ ثابتِ اختصاصیِ همون callback با تطبیقِ کامل (MENU_BUTTON_COLORS)
      ۴) رنگِ ثابتِ پیشوندیِ اولویت‌دار (FORCED_PREFIX_COLORS، بخشِ ۳-الف)
      ۵) رنگِ خودکار بر اساسِ ایموجیِ متنِ دکمه (✅/🔴/🟢)
      ۶) بقیه‌ی رنگ‌های ثابتِ پیشوندیِ MENU_BUTTON_COLORS (مثلِ src:add یا src:remove:)
      ۷) بی‌رنگ
    `text` اختیاریه؛ اگه ندی، مرحله‌ی ۱، ۳، ۴ و ۶ اجرا می‌شه (سازگار با
    فراخوانی‌های قدیمی)."""
    text_color = _static_style_for_text(text)
    if text_color is not None:
        return text_color
    if callback_data and any(callback_data.startswith(p) for p in EMOJI_AUTOCOLOR_EXCLUDED_PREFIXES):
        return None
    if callback_data and callback_data in MENU_BUTTON_COLORS:
        return _norm_color(MENU_BUTTON_COLORS[callback_data])
    forced = _forced_prefix_style(callback_data)
    if forced is not None:
        return forced
    auto = _autocolor_for_text(text)
    if auto is not None:
        return auto
    return _static_style_for_callback(callback_data)
