# -*- coding: utf-8 -*-
"""تستِ سیاستِ رنگِ دکمه‌های منو (bot/button_config.py:MENU_BUTTON_COLORS +
رنگِ خودکارِ ایموجی).

هدف: قفل کردنِ تضمین‌هایی که کل ایده‌ی «رنگِ مرکزی» بهشون متکیه:
  ۱) «بازگشت به منو»/«بازگشت به منویِ اصلی» (menu:main) همه‌جا آبیه.
  ۲) فهرستِ کانال‌های مقصد/مبدأ (src:view:*, dst:view:*) با اینکه نقطه‌ی
     وضعیتِ 🟢 دارن، همیشه بی‌رنگ (سفید) می‌مونن.
  ۳) دکمه‌های toggle که وضعیت‌شون با ✅/🔴/🟢 توی متن معلومه، رنگِ خودکار
     می‌گیرن (سبز/قرمز بسته به ایموجی) — به‌جز مواردی که رنگِ ثابتِ اختصاصی
     دارن (مثلِ adf:file_toggle که همیشه آبیه).
  ۴) مجموعه‌ای از اکشن‌های یک‌طرفه (افزودن/حذف/...) رنگِ موردانتظارشون رو دارن.
اگه بعداً کسی MENU_BUTTON_COLORS یا منطقِ رنگِ خودکار رو تغییر داد و یکی از
این تضمین‌ها رو شکست، این تست باید FAIL بشه تا موقعِ ریویو دیده بشه.
"""
import _harness  # noqa: F401 - بسته‌ی سبکِ bot را می‌سازد (اثرِ جانبی، نه استفاده‌ی مستقیم)
from bot import button_config as bc

fails = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)

# ۱) «بازگشت به منو»/«بازگشت به منویِ اصلی» همه‌جا آبیه (بدونِ متن هم، چون
# رنگِ ثابتِ اختصاصی داره).
for cb in ["menu:main"]:
    got = bc.style_for_callback(cb)
    check(f"button_colors.menu_main_primary[{cb}]", got == "primary", f"got={got!r}")
# وقتی متنِ دکمه هم داده شود، BACK_NAV_TEXT_COLORS (که جلوترِ از رنگِ ثابتِ
# callback چک می‌شود) حرفِ آخر را می‌زند: «بازگشت به منو»/«بازگشت به منوی اصلی»
# هر دو سبزند، و «بازگشت به لیست»/«بازگشت به کانال» آبی — این جفت‌بندیِ عمدیِ
# سیاستِ رنگ است، نه استثنا.
got = bc.style_for_callback("menu:main", "🔙 بازگشت به منو")
check("button_colors.back_to_menu_text_success", got == "success", f"got={got!r}")
got = bc.style_for_callback("menu:main", "🏠 بازگشت به منوی اصلی")
check("button_colors.back_to_home_text_success", got == "success", f"got={got!r}")
# متنی که در BACK_NAV_TEXT_COLORS نیست، رنگِ ثابتِ خودِ callback را می‌گیرد.
got = bc.style_for_callback("menu:main", "🏠 منوی اصلی")
check("button_colors.menu_main_primary_other_text", got == "primary", f"got={got!r}")
for text, want in [("🔙 بازگشت به لیست", "primary"), ("🔙 بازگشت به کانال", "primary")]:
    got = bc.style_for_callback("menu:sources", text)
    check(f"button_colors.back_nav_text[{text}]", got == want, f"want={want} got={got!r}")

# ۲) بقیه‌ی دکمه‌های «بازگشت»/«انصراف» (غیر از menu:main) باید بی‌رنگ بمونن —
# این‌ها هیچ‌وقت به‌عنوانِ رنگِ ثابت تعریف نشدن و متن‌شون هم ✅/🔴/🟢 نداره.
BACK_AND_CANCEL_TARGETS = [
    "menu:sources", "menu:destinations", "menu:extsources",
    "menu:watermark", "menu:footer", "menu:adfilter", "menu:resources",
    "menu:users", "menu:customwm",
    "extsrc:view:123", "src:sched:123",
    "dst:footer:5",
    "pp:view:9", "input:cancel", "nav:noop",
    "wmp:tg", "wmp:ig", "wmc:view:3",
]
for cb in BACK_AND_CANCEL_TARGETS:
    got = bc.style_for_callback(cb)
    check(f"button_colors.back_stays_neutral[{cb}]", got is None, f"got={got!r}")

# ۳) فهرستِ کانال‌های مقصد/مبدأ: با اینکه نقطه‌ی وضعیتِ 🟢 توی متنِ لیست هست،
# باید همیشه بی‌رنگ بمونن (حتی وقتی کانال فعاله و متن ✅/🟢 داره).
CHANNEL_LIST_EXCLUDED = [
    ("src:view:123", "🟢 کانالِ من · ⏱ · 🎯2"),
    ("dst:view:5", "🟢 مقصدِ من"),
    ("src:view:123", "⚪️ کانالِ من · ⏱ · 🎯2"),
    ("dst:view:5", "⚪️ مقصدِ من"),
]
for cb, text in CHANNEL_LIST_EXCLUDED:
    got = bc.style_for_callback(cb, text)
    check(f"button_colors.channel_list_excluded[{cb}]", got is None, f"got={got!r}")

# ۴) دکمه‌های toggle: رنگِ خودکار بر اساسِ ایموجیِ متن (بدونِ رنگِ ثابتِ اختصاصی).
AUTOCOLOR_CASES = [
    ("adf:toggle", "🔘 وضعیت: 🟢 فعال", "success"),
    ("adf:toggle", "🔘 وضعیت: 🔴 غیرفعال", "danger"),
    ("dst:toggle:5", "▶️ فعال کن", None),          # ⏸/▶️ نه ✅/🔴/🟢‌ست
    ("footer:toggle", "🔘 وضعیت: 🟢 فعال", "success"),
    ("res:toggle", "🔘 وضعیت: 🔴 غیرفعال", "danger"),
    ("backup:toggle", "🔘 وضعیت: 🟢 فعال", "success"),
    ("wmp:tg:toggle", "🔘 وضعیت: 🔴 غیرفعال", "danger"),
    ("notif:toggle", "وضعیت اعلان‌ها: 🟢 فعال", "success"),
    ("src:slot_toggle:1:2", "✅ تایید", "success"),
    # ✅ همیشه اولویتِ اول رو داره، حتی اگه 🔴 هم توی متن باشه (مثلاً یک
    # گزینه‌ی انتخابی که اسمش خودش شاملِ 🔴ه).
    ("src:dupset:1:disabled", "✅ 🔴 غیرفعال (تکرار مجاز است)", "success"),
    ("src:dupset:1:disabled", "⬜️ 🔴 غیرفعال (تکرار مجاز است)", "danger"),
]
for cb, text, want in AUTOCOLOR_CASES:
    got = bc.style_for_callback(cb, text)
    check(f"button_colors.autocolor[{cb}|{text}]", got == want, f"want={want!r} got={got!r}")

# ۵) adf:file_toggle همیشه آبیِ ثابته، صرفِ‌نظر از بجِ 🟢/🔴 توی متنش (استثنای
# صریح؛ رنگِ ثابت جلوترِ از رنگِ خودکار چک می‌شه).
for text in ["📦 فیلترِ فایل/اپ (APK و...): 🟢 فعال", "📦 فیلترِ فایل/اپ (APK و...): 🔴 غیرفعال"]:
    got = bc.style_for_callback("adf:file_toggle", text)
    check(f"button_colors.file_toggle_forced_primary[{text}]", got == "primary", f"got={got!r}")

# ۶) مجموعه‌ای از اکشن‌های یک‌طرفه/ناوبری با رنگِ ثابتِ موردانتظار.
EXPECTED = {
    "res:stats": "primary",
    "logs:all": "primary", "logs:errors": "primary", "logs:success": "primary",
    "logs:by_channel": "primary", "logs:by_destination": "primary", "logs:by_user": "primary",
    "src:destmap:5": "primary", "src:mode_menu:5": "primary", "usr:perms:9": "primary",
    "backup:restore": "primary", "dst:cfg:5": "primary",
    # ➕ افزودنِ کانال مبدأ/مقصد عمداً آبیه (اکشنِ اصلیِ اون صفحه)، نه سبز —
    # سبز برای «ایجاد/تاییدِ نهایی/ویرایشِ فهرست» نگه داشته شده.
    "src:add": "primary", "dst:add": "primary",
    "usr:add": "success",
    "adf:phrases_add": "success",
    # ⚠️ «ایجاد بکاپ فوری» و «مشاهده لاگ‌ها» عمداً قرمزن (عملیاتِ سنگین/حساسِ
    # سرور)، نه سبز/آبی.
    "backup:now": "danger", "res:logs": "danger",
    "adf:keywords": "success", "adf:file_ext": "success",
    "src:remove:1": "danger", "dst:remove:1": "danger",
    "extsrc:remove:1": "danger", "usr:remove:1": "danger",
    "adf:phrases_clear": "danger", "adf:reset_keywords": "danger",
    "adf:file_reset_ext": "danger", "notif:clearchat": "danger",
    "ai:cache_clear": "danger", "pp:wm_reset:9": "danger",
}
for cb, want in EXPECTED.items():
    got = bc.style_for_callback(cb)
    check(f"button_colors.expected[{cb}]", got == want, f"want={want} got={got!r}")

# ۷) دکمه‌های «✅ بله، حذف کن» (تاییدِ حذف): با اینکه callback_dataشون توی
# MENU_BUTTON_COLORS به‌عنوانِ danger ثبت شده، چون متن‌شون ✅ داره، رنگِ
# خودکارِ سبز رو می‌گیرن (رنگِ خودکار جلوترِ از این نوع تطبیقِ پیشوندی چک
# می‌شه). دکمه‌ی «✅ تایید و ارسال»ِ صفِ تایید هم همینه.
CONFIRM_GREEN = [
    "src:remove_confirm:1", "dst:remove_confirm:1",
    "extsrc:remove_confirm:1", "usr:remove_confirm:1",
    "pp:approve:9",
]
for cb in CONFIRM_GREEN:
    got = bc.style_for_callback(cb, "✅ بله، حذف کن")
    check(f"button_colors.confirm_forced_green[{cb}]", got == "success", f"got={got!r}")

# ۸) دکمه‌ی «❌ رد کردن»/«❌ انصراف» (بدونِ ✅/🔴/🟢): pp:reject همچنان رنگِ
# ثابتِ danger رو از MENU_BUTTON_COLORS می‌گیره (❌ باعثِ رنگِ خودکار نمی‌شه).
got = bc.style_for_callback("pp:reject:9", "❌ رد کردن پست")
check("button_colors.reject_stays_danger", got == "danger", f"got={got!r}")

# ۹) رنگِ نامعتبر توی کانفیگ نباید کرش کنه — باید نادیده گرفته بشه (بی‌رنگ).
_orig = dict(bc.MENU_BUTTON_COLORS)
try:
    bc.MENU_BUTTON_COLORS["zz:bad_color_test"] = "not_a_real_color"
    check("button_colors.invalid_color_ignored", bc.style_for_callback("zz:bad_color_test") is None)
finally:
    bc.MENU_BUTTON_COLORS.clear()
    bc.MENU_BUTTON_COLORS.update(_orig)

# ۱۰) فراخوانیِ قدیمی بدونِ آرگومانِ text نباید کرش کنه (سازگاریِ عقب‌رو) و باید
# همون رنگِ ثابتِ callback رو بده.
got = bc.style_for_callback("src:add")
check("button_colors.backward_compatible_no_text", got == "primary", f"got={got!r}")

# ۱۱) هر مقداری که توی MENU_BUTTON_COLORS/FORCED_PREFIX_COLORS/BACK_NAV_TEXT_COLORS
# نوشته شده باید یکی از رنگ‌های معتبر باشه؛ یک تایپو (مثلاً "sucess") بی‌سروصدا
# به «بی‌رنگ» تبدیل می‌شه و کسی متوجه نمی‌شه.
for name, table in (
    ("MENU_BUTTON_COLORS", bc.MENU_BUTTON_COLORS),
    ("FORCED_PREFIX_COLORS", bc.FORCED_PREFIX_COLORS),
    ("BACK_NAV_TEXT_COLORS", bc.BACK_NAV_TEXT_COLORS),
):
    bad = {k: v for k, v in table.items() if v not in bc.VALID_COLORS}
    check(f"button_colors.config_values_valid[{name}]", not bad, f"نامعتبر: {bad}")

print("\n=== BUTTON_COLORS:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
if fails:
    raise SystemExit(1)
