# -*- coding: utf-8 -*-
"""Stage 4: end-to-end — exact final text that goes to Telegram."""
import _poster_harness as H
from bot import poster
from bot.formatter import clean_post_html, strip_html_tags
from bot.scraper import Post, MediaItem
from bs4 import BeautifulSoup

# فوتر را فعال کنیم تا امضا هم دیده شود
H.fake_db.settings["footer_channel_handle"] = "VFREEPN"
H.fake_db.settings["footer_channel_url"] = "https://t.me/VFREEPN"
# footer_enabled/preserve_formatting از get_effective_bool default=True می‌آید

def build(node_html, username):
    node = BeautifulSoup(f"<div>{node_html}</div>", "html.parser").div
    cleaned = clean_post_html(node, username)
    cap = poster.build_caption_html(cleaned, channel_id=1, destination_id=None)
    return cleaned, cap

def show(title, cleaned, cap):
    print("\n" + "="*70)
    print(title)
    print("-"*70)
    print("[متن پاک‌شده‌ی بدنه]:")
    print(cleaned)
    print("\n[کپشن نهایی که به تلگرام می‌رود]:")
    print(cap)
    print(f"[طول متن ساده: {len(strip_html_tags(cap))} نویسه]")

# سناریو ۱: پست چند-کانفیگی با هدر ایموجی‌دار + نقل‌قول + منشن منبع در ته
s1 = (
    '🎯 <b>کانفیگ‌های پرسرعت امروز</b>\n'
    '<blockquote>vless://uuid@1.2.3.4:443?type=tcp#SourceChan</blockquote>\n'
    'برای کانفیگ بیشتر به @SourceChan سر بزنید\n'
    '📥 دانلود از : @SourceChan'
)
cleaned, cap = build(s1, "SourceChan")
show("سناریو ۱: چند-کانفیگی + هدر ایموجی + نقل‌قول + منشن منبع ته", cleaned, cap)

# سناریو ۵: بولد چندخطی که </b> روی خط منشن (حذف‌شونده) است
s5 = '<b>خبر فوری ورزشی\nجزئیات کامل در ادامه\nمنبع خبر @SportSource</b>'
cleaned, cap = build(s5, "SportSource")
show("سناریو ۵: بولد چندخطی با </b> روی خط منشنِ حذف‌شده", cleaned, cap)
# چک توازن
print("توازن <b>:", cap.count("<b>"), "</b>:", cap.count("</b>"),
      "=> ", "OK" if cap.count("<b>")==cap.count("</b>") else "نامتوازن!")

# سناریو ۶: پست تبلیغاتی که یک لینک پروکسی هم دارد (ad_filter)
from bot import ad_filter as adf
s6_text = "بهترین سایت شرط بندی و کازینو آنلاین با بونوس ثبت نام\nپروکسی: https://t.me/proxy?server=a&port=1"
is_ad, reason, detail = adf.analyze(s6_text, "src", adf.DEFAULT_KEYWORDS)
print("\n" + "="*70)
print("سناریو ۶: پست تبلیغاتیِ حاوی لینک پروکسی")
print("-"*70)
print(f"تبلیغ تشخیص داده شد؟ {is_ad}  | دلیل: {reason}\n| score={detail['score']} threshold={detail['threshold']}")
# با کلیدواژه سفارشی
is_ad2, reason2, d2 = adf.analyze(s6_text, "src", ["کازینو"]+adf.DEFAULT_KEYWORDS)
print(f"با کلیدواژه سفارشیِ «کازینو»: تبلیغ؟ {is_ad2} | {reason2}")

# سناریو ۳: عکس + کپشن ~1200 نویسه (بررسی سرریز و متن جدا)
import asyncio
run = asyncio.get_event_loop().run_until_complete
async def fake_dl(url, timeout=30.0, retries=3, channel_id=None): return b"IMG"
poster._download = fake_dl
poster._photo_needs_processing = lambda channel_id=None, destination_id=None: False
long_body = "این یک خط از متنِ طولانی است. " * 45  # ~1300+ chars
class RecBot:
    def __init__(s): s.calls=[]; s._m=1
    async def _r(s,mth,**kw): s.calls.append((mth,kw)); s._m+=1
    async def send_photo(s,**kw):
        await s._r("send_photo",**kw)
        class M: message_id=s._m
        return M()
    async def send_message(s,**kw):
        await s._r("send_message",**kw)
        class M: message_id=s._m
        return M()
    async def edit_message_reply_markup(s,**kw): return None
b = RecBot()
post = Post(id=99, html_text=long_body.strip(), media=[MediaItem("photo","http://x/1.jpg")])
ok, reason, link = run(poster.send_post(b, "dst", post, channel_id=1, destination_id=2))
print("\n" + "="*70)
print("سناریو ۳: عکس + کپشن ~۱۳۰۰ نویسه")
print("-"*70)
photo = [kw for m,kw in b.calls if m=="send_photo"][0]
msg = [kw for m,kw in b.calls if m=="send_message"]
print(f"موفق؟ {ok}")
print(f"عکس با کپشن؟ caption={photo.get('caption')!r}")
print(f"تعداد پیام‌ها: 1 عکس + {len(msg)} پیام متنی جدا")
if msg:
    print(f"طول متن جدا: {len(strip_html_tags(msg[0]['text']))} نویسه (کلِ متن، بدون بریدن)")
print(f"جمع: هیچ متنی بریده نشد => {'OK' if msg and len(strip_html_tags(msg[0]['text']))>=1000 else 'FAIL'}")

print("\nDONE E2E")
