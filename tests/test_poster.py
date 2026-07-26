# -*- coding: utf-8 -*-
import _poster_harness as H
import asyncio
from bot import poster
from bot.scraper import Post, MediaItem
from telegram.error import TelegramError

fails = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond: fails.append(name)

class Msg:
    def __init__(self, mid=1, chat_id="dst"): self.message_id = mid; self.chat_id = chat_id

class FakeBot:
    def __init__(self, fail_rules=None):
        self.calls = []            # list of (method, kwargs)
        self.fail_rules = fail_rules or {}  # method -> callable(kwargs)->exc or None
        self._mid = 100
    async def _record(self, method, **kw):
        self.calls.append((method, kw))
        rule = self.fail_rules.get(method)
        if rule:
            exc = rule(kw, self.calls)
            if exc: raise exc
        self._mid += 1
        return Msg(self._mid)
    async def send_photo(self, **kw): return await self._record("send_photo", **kw)
    async def send_video(self, **kw): return await self._record("send_video", **kw)
    async def send_voice(self, **kw): return await self._record("send_voice", **kw)
    async def send_audio(self, **kw): return await self._record("send_audio", **kw)
    async def send_document(self, **kw): return await self._record("send_document", **kw)
    async def send_message(self, **kw): return await self._record("send_message", **kw)
    async def send_media_group(self, **kw):
        self.calls.append(("send_media_group", kw))
        rule = self.fail_rules.get("send_media_group")
        if rule:
            exc = rule(kw, self.calls)
            if exc: raise exc
        self._mid += 1
        return [Msg(self._mid), Msg(self._mid+1)]
    async def edit_message_reply_markup(self, **kw):
        self.calls.append(("edit_markup", kw)); return Msg()

def methods(bot): return [m for m,_ in bot.calls]

# Patch _download to avoid real network; default returns fake bytes
_orig_download = poster._download
async def fake_download_ok(url, timeout=30.0, retries=3, channel_id=None):
    return b"FAKEIMG"
async def fake_download_fail(url, timeout=30.0, retries=3, channel_id=None):
    return None

run = asyncio.get_event_loop().run_until_complete

# ---------- الف-1: آلبومِ بدونِ متن → موفق (SENT) ----------
poster._download = fake_download_ok
bot = FakeBot()
post = Post(id=10, html_text="", media=[
    MediaItem("photo","http://x/1.jpg"), MediaItem("photo","http://x/2.jpg")])
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
check("album.no_caption.sent_ok", ok is True, f"reason={reason}")
check("album.no_caption.used_media_group", "send_media_group" in methods(bot), methods(bot))

# ---------- الف-2 + الف-3: کپشن ~1200 نویسه → رسانه بدون کپشن + متن کامل جدا، بدون بریدن ----------
long_text = "الف " * 300   # ~1200 chars plain
long_text = long_text.strip()
bot = FakeBot()
post = Post(id=11, html_text=long_text, media=[MediaItem("photo","http://x/1.jpg")])
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
check("overflow.sent_ok", ok is True, f"reason={reason}")
# عکس باید بدون کپشن رفته باشد
photo_calls = [kw for m,kw in bot.calls if m=="send_photo"]
check("overflow.photo_no_caption", photo_calls and (photo_calls[0].get("caption") in (None,"")), photo_calls)
# متن کامل باید در پیام جدا رفته باشد و چیزی بریده نشده باشد
msg_calls = [kw for m,kw in bot.calls if m=="send_message"]
full_sent = any((long_text.split()[0] in (kw.get("text") or "")) and len(H.__dict__) or True for kw in msg_calls)
sep_text = (msg_calls[0]["text"] if msg_calls else "")
from bot.formatter import strip_html_tags
check("overflow.separate_full_text", bool(msg_calls) and len(strip_html_tags(sep_text)) >= 1000,
      f"len={len(strip_html_tags(sep_text)) if msg_calls else 0}")

# ---------- الف-4: ویس باید ارسال شود ----------
bot = FakeBot()
post = Post(id=12, html_text="کپشن ویس", media=[MediaItem("voice","http://x/v.ogg")])
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
check("voice.sent_ok", ok is True, f"reason={reason}")
check("voice.used_send_voice", "send_voice" in methods(bot), methods(bot))

# ---------- الف-5: دانلود عکس شکست خورد → با لینک مستقیم بفرست، پست دور ریخته نشود ----------
poster._download = fake_download_fail
bot = FakeBot()
# اجبار به مسیر پردازش (نه fast-path): با فعال‌کردن یک نیاز به پردازش؟ fast-path
# فقط وقتی هیچ پردازشی لازم نیست عکس را مستقیم با URL می‌فرستد. اینجا می‌خواهیم
# مسیر دانلود را تست کنیم؛ پس _photo_needs_processing را True می‌کنیم.
_orig_needs = poster._photo_needs_processing
poster._photo_needs_processing = lambda channel_id=None, destination_id=None: True
post = Post(id=13, html_text="کپشن", media=[MediaItem("photo","http://x/1.jpg")])
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
check("photo_dl_fail.sent_via_link", ok is True, f"reason={reason}")
# باید send_photo با photo=URL صدا زده شده باشد (لینک مستقیم)
photo_urls = [kw.get("photo") for m,kw in bot.calls if m=="send_photo"]
check("photo_dl_fail.used_url", any(str(u).startswith("http") for u in photo_urls), photo_urls)
poster._photo_needs_processing = _orig_needs
poster._download = fake_download_ok

# ---------- الف-6: خطای tgemoji unsupported → تلاش دوباره بدون ایموجی پرمیوم ----------
# اولین send_photo با خطای unsupported start tag "tgemoji" شکست بخورد، بار دوم موفق
state = {"n":0}
def emoji_rule(kw, calls):
    # فقط اولین باری که caption شامل tg-emoji است شکست بده
    cap = kw.get("caption") or ""
    if "tg-emoji" in cap and state["n"]==0:
        state["n"] += 1
        return TelegramError('Can\'t parse entities: unsupported start tag "tgemoji"')
    return None
bot = FakeBot(fail_rules={"send_photo": emoji_rule})
# فعال‌کردن premium تا tg-emoji در کپشن بماند
H.fake_db.get_effective_bool = (lambda channel_id, key, default=False, owner_user_id=None:
                                True if key=="premium_emoji_enabled" else default)
post = Post(id=14, html_text='<tg-emoji emoji-id="5">😀</tg-emoji> سلام', media=[MediaItem("photo","http://x/1.jpg")])
# fast path off so it goes через send_photo with URL (photo_override None, needs_processing False→fast path)
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
check("tgemoji.retry_succeeds", ok is True, f"reason={reason}")
# باید حداقل دو بار send_photo صدا زده شده باشد (اول با ایموجی، بعد بدون)
n_photo = methods(bot).count("send_photo")
check("tgemoji.retried", n_photo >= 2, f"n_photo={n_photo} calls={methods(bot)}")
# بار دوم نباید tg-emoji در کپشن باشد
last_photo_cap = [kw.get("caption") or "" for m,kw in bot.calls if m=="send_photo"][-1]
check("tgemoji.stripped_on_retry", "tg-emoji" not in last_photo_cap, repr(last_photo_cap))
# reset
H.fake_db.get_effective_bool = (lambda channel_id, key, default=False, owner_user_id=None: default)

print("\n=== POSTER:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")

# ---------- «Message is too long»: تقسیمِ پستِ متنیِ طولانی به چند پیام ----------
poster._download = fake_download_ok
from bot.utils import tg_text_len
from bot.formatter import strip_html_tags as _sht
_cfgs = [f'vless://{i:08d}-b289-4a64-86fa-a5b731b65384@185.159.108.{i}:443?security=reality&type=tcp&sni=ex{i}.com#S{i}' for i in range(25)]
_body = '🇺🇸🇩🇪🇵🇱 موقعیت سرور :\n' + '\n'.join(f'<blockquote expandable>{c}</blockquote>' for c in _cfgs)
bot = FakeBot()
post = Post(id=8679, html_text=_body, media=[])
ok, reason, link = run(poster.send_post(bot, "dst", post, channel_id=1, destination_id=2))
_texts = [kw["text"] for m,kw in bot.calls if m=="send_message"]
check("toolong.sent_ok", ok is True, f"reason={reason}")
check("toolong.split_into_multiple", len(_texts) >= 2, f"n={len(_texts)}")
check("toolong.each_under_limit", all(tg_text_len(_sht(t)) <= 4096 for t in _texts),
      [tg_text_len(_sht(t)) for t in _texts])
check("toolong.no_config_lost", sum(t.count("vless://") for t in _texts) == 25,
      sum(t.count("vless://") for t in _texts))

print("\n=== POSTER(2):", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")

# ---------- تقسیمِ blockquote/code چندخطی: تیکه‌ها باید quote/code/expandable بمانند ----------
from bot.formatter import clean_post_html as _cph
from bs4 import BeautifulSoup as _BS
_cfgs = '\n'.join(f'vless://{i:08d}-b289@host{i}.example.com:443?security=reality&encryption=none&pbk=Qoc{i}&type=tcp&sni=ex{i}.com#Src{i}' for i in range(60))
_raw = f'<div>👑 کانفیگ فیلترشکن\n<blockquote>{_cfgs}</blockquote></div>'
_full = poster.build_message_html(_cph(_BS(_raw,'html.parser').div,'Src'), channel_id=1, destination_id=None, limit=10**7)
_chunks = poster._split_message_html(_full, 4096)
check("splitbq.multiple", len(_chunks) >= 2, len(_chunks))
check("splitbq.every_chunk_has_blockquote", all("<blockquote" in c for c in _chunks),
      [("<blockquote" in c) for c in _chunks])
check("splitbq.each_under_limit", all(tg_text_len(_sht(c)) <= 4096 for c in _chunks),
      [tg_text_len(_sht(c)) for c in _chunks])
check("splitbq.tags_balanced", all(c.count("<blockquote")==c.count("</blockquote>") for c in _chunks), "")
check("splitbq.no_config_split", sum(c.count("vless://") for c in _chunks) == 60,
      sum(c.count("vless://") for c in _chunks))

print("\n=== POSTER(3):", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")

# ---------- خط خالیِ قبل از blockquote در تکه‌ی اول حفظ شود (split) ----------
from bot.formatter import clean_post_html as _cph2
from bs4 import BeautifulSoup as _BS2
_cfgs2 = '\n'.join(f'vless://{i:08d}@h{i}.example.com:443?security=reality&pbk=Q{i}&type=tcp#S{i}' for i in range(60))
_raw2 = f'<div>👑 کانفیگ فیلترشکن\n🇵🇱🇩🇪🇺🇸 موقعیت سرور :\n<blockquote expandable>{_cfgs2}</blockquote></div>'
_full2 = poster.build_message_html(_cph2(_BS2(_raw2,'html.parser').div,'Src'), channel_id=1, destination_id=None, limit=10**7)
_ch = poster._split_message_html(_full2, 4096)
check("split.blank_before_bq_kept", "\n\n<blockquote" in _ch[0], repr(_ch[0][:80]))
check("split.header_flag_relocated", "سرور : 🇵🇱🇩🇪🇺🇸" in _ch[0], "")
check("split.no_config_split2", sum(c.count("vless://") for c in _ch) == 60, sum(c.count("vless://") for c in _ch))

print("\n=== POSTER(4):", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
