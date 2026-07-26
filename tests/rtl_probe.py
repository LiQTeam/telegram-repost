# -*- coding: utf-8 -*-
"""
تشخیصِ راست‌چینی روی تلگرامِ واقعی.

چند «استراتژیِ» مختلفِ راست‌چینی را برای یک خطِ نمونه به یک چت می‌فرستد.
تو نگاه می‌کنی کدام پیام درست راست‌چین شد و شماره‌اش را به من می‌گویی.

اجرا روی سرور:
    # توکن از .env یا متغیرِ محیطی خوانده می‌شود؛ یا با آرگومان بده
    python3 tests/rtl_probe.py <CHAT_ID> [BOT_TOKEN]

نمونه:
    python3 tests/rtl_probe.py -1001234567890
    python3 tests/rtl_probe.py @mychannel 123456789:AAExampleTokenPlaceholder

CHAT_ID می‌تواند آیدیِ عددیِ کانال (مثلِ -100...) یا @username باشد.
ربات باید در آن چت ادمین/عضو باشد.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

RLM = "‏"   # RIGHT-TO-LEFT MARK (bidi=R)
ALM = "؜"   # ARABIC LETTER MARK (bidi=AL)
RLE = "‫"   # RIGHT-TO-LEFT EMBEDDING
PDF = "‬"
RLI = "⁧"   # RIGHT-TO-LEFT ISOLATE
PDI = "⁩"

HEADER = "👑 کانفیگ فیلترشکن"       # خط با ایموجیِ خنثی در ابتدا
FLAGS = "🇵🇱🇩🇪🇺🇸 موقعیت سرور :"   # خط با پرچم (چپ‌به‌راست) در ابتدا ← موردِ سختِ فعلی
LETTER = "پرامپت کاپلی:"             # خط با حرفِ فارسی در ابتدا


def _token():
    if len(sys.argv) >= 3:
        return sys.argv[2]
    if os.environ.get("BOT_TOKEN"):
        return os.environ["BOT_TOKEN"]
    # تلاش برای خواندن از .env کنارِ پروژه
    for p in (".env", os.path.join(os.path.dirname(__file__), "..", ".env")):
        try:
            for line in open(p, encoding="utf-8"):
                if line.strip().startswith("BOT_TOKEN"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    sys.exit("BOT_TOKEN پیدا نشد؛ به‌عنوانِ آرگومانِ دوم بده یا در .env بگذار.")


def send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
        out = json.load(r)
    if not out.get("ok"):
        print("  ❌ خطا:", out)
    return out.get("ok", False)


def main():
    if len(sys.argv) < 2:
        sys.exit("استفاده: python3 tests/rtl_probe.py <CHAT_ID> [BOT_TOKEN]")
    chat_id = sys.argv[1]
    token = _token()

    # هر استراتژی: (شماره‌ی نمایشی، توضیح، سازنده‌ی متن از روی یک خط)
    strategies = [
        ("1", "بدونِ هیچ نشانگر (خام)", lambda s: s),
        ("2", "RLM در ابتدای خط (روشِ فعلی)", lambda s: RLM + s),
        ("3", "ALM (Arabic Letter Mark) در ابتدا", lambda s: ALM + s),
        ("4", "دو RLM در ابتدا", lambda s: RLM + RLM + s),
        ("5", "RLE...PDF (روشِ قدیمیِ ربات)", lambda s: RLE + s + PDF),
        ("6", "RLI...PDI (ایزوله‌ی راست‌به‌چپ)", lambda s: RLI + s + PDI),
        ("7", "RLM در ابتدا + انتها", lambda s: RLM + s + RLM),
        ("8", "توکنِ اولِ خط (ایموجی/پرچم) به آخر منتقل شد",
         lambda s: (s.split(" ", 1)[1] + " " + s.split(" ", 1)[0]) if (" " in s and not s[0].isalpha()) else s),
        ("9", "RLM + توکنِ اول به آخر (راست‌چین + جهتِ اجباری)",
         lambda s: RLM + ((s.split(" ", 1)[1] + " " + s.split(" ", 1)[0]) if (" " in s and not s[0].isalpha()) else s)),
    ]

    print(f"ارسالِ {len(strategies)} نمونه به {chat_id} ...\n")
    for num, desc, fn in strategies:
        # هر پیام: یک برچسبِ شماره (لاتین) + سه خطِ آزمایشی. خطِ وسط (پرچم‌دار) مهم‌ترینه.
        body = (
            f"[TEST {num}] {desc}\n"
            f"{fn(HEADER)}\n"
            f"{fn(FLAGS)}\n"
            f"{fn(LETTER)}"
        )
        ok = send(token, chat_id, body)
        print(f"  نمونه {num}: {'✅ ارسال شد' if ok else '❌'}  — {desc}")

    print(
        "\nحالا در آن چت نگاه کن: در کدام نمونه(ها) هر دو خطِ فارسی به سمتِ راست چسبیده‌اند؟\n"
        "شماره‌ی نمونه‌ای که درست راست‌چین شده را به من بگو (مثلاً «نمونه ۳ درست شد»).\n"
        "برچسبِ [TEST n] خودش لاتین است و طبیعتاً چپ می‌ماند — فقط دو خطِ فارسیِ زیرش مهم‌اند."
    )


if __name__ == "__main__":
    main()
