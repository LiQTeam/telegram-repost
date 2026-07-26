# -*- coding: utf-8 -*-
"""
چکِ استقرار: کدِ واقعیِ نصب‌شده روی سرور رو اجرا می‌کنه و می‌گه هر اصلاح
هست یا نه. روی سرور، از ریشه‌ی پروژه اجرا کن:

    cd /root/telegram-repost-bot   # یا هرجا پروژه هست
    python3 tests/check_deploy.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

RLM = "‏"
ok_all = True


def show(label, cond, extra=""):
    global ok_all
    mark = "✅" if cond else "❌ (نصب نشده)"
    print(f"{mark}  {label}" + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        ok_all = False


try:
    from bot.formatter import ensure_rtl_lines
except Exception as e:  # noqa: BLE001
    print("❌ نتونستم bot.formatter رو ایمپورت کنم:", e)
    sys.exit(1)

# نمونه‌ی دقیقِ کپشنِ دوخطی با پرچم در ابتدای خطِ دوم + بلاک‌کوت چسبیده
sample = "👑 کانفیگ فیلترشکن\n🇵🇱🇩🇪🇺🇸 موقعیت سرور :\n<blockquote expandable>vless://x@1.2.3.4:443</blockquote>"
out = ensure_rtl_lines(sample)
lines = out.split("\n")

# ۱) خط خالی بین کپشن و بلاک‌کوت
show("خط خالیِ قبل از quote (اصلاحِ blockquote)", "\n\n<blockquote" in out)

# ۲) نشانگرِ RLM (نه RLE)
show("نشانگرِ RTL از نوعِ RLM (U+200F)", RLM in out and "‫" not in out)

# ۳) انتقالِ پرچمِ ابتدای خط به آخر: خطِ «موقعیت سرور» باید به پرچم *ختم* شود
#    (نه با پرچم شروع شود) و اولین نویسه‌اش RLM باشد.
flag_line = next((l for l in lines if "موقعیت" in l), "")
_last = flag_line.rstrip()[-1:] if flag_line.rstrip() else ""
_flag_at_end = bool(_last) and 0x1F1E6 <= ord(_last) <= 0x1F1FF
show("پرچمِ ابتدای خط منتقل شده به آخرِ خط", _flag_at_end, repr(flag_line))

# ۴) تقسیمِ پیامِ طولانی (poster) با حفظِ ساختار: یک بلاک‌کوتِ چندخطیِ بزرگ باید به
#    چند تکه بشه که هرکدوم blockquote داشته باشن و هیچ کانفیگی نصف نشه.
try:
    from bot.poster import _split_message_html, build_message_html
    _cfgs = "\n".join(
        f"vless://{i:08d}@h{i}.example.com:443?security=reality&pbk=Q{i}&type=tcp#S{i}"
        for i in range(60)
    )
    _full = build_message_html(f"👑 کانفیگ\n<blockquote expandable>{_cfgs}</blockquote>", limit=10**7)
    _parts = _split_message_html(_full, 4096)
    _ok = (
        len(_parts) >= 2
        and all("<blockquote" in p for p in _parts)
        and sum(p.count("vless://") for p in _parts) == 60
    )
    show("تقسیمِ آگاه‌به‌تگ در poster (بلاک‌کوت در همه‌ی تکه‌ها + بی‌برشِ کانفیگ)", _ok)
except Exception as _e:  # noqa: BLE001
    show("تقسیمِ آگاه‌به‌تگ در poster", False, str(_e))

# ۵) شمارشِ UTF-16 در utils
try:
    from bot.utils import tg_text_len
    show("شمارشِ UTF-16 در utils (tg_text_len)", tg_text_len("🇺🇸") == 4)
except Exception:
    show("شمارشِ UTF-16 در utils (tg_text_len)", False)

print()
print("خروجیِ واقعیِ کدِ نصب‌شده روی نمونه:")
for i, l in enumerate(lines):
    print(f"  line{i}: {l[:60]!r}")

print()
if ok_all:
    print("🎉 همه‌ی اصلاح‌ها روی سرور نصب‌اند. اگه پستِ جدید هنوز مشکل داشت، خبر بده.")
else:
    print("⚠️ بعضی اصلاح‌ها نصب نشده‌اند — فایل‌های آخر (formatter.py/poster.py/utils.py) رو")
    print("   جایگزین کن، بعد:  find . -name __pycache__ -exec rm -rf {} + ; systemctl restart mrliq-bot")
