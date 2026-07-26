# -*- coding: utf-8 -*-
import _harness
import asyncio, time
import bot.scraper as S

fails = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond: fails.append(name)
run = asyncio.get_event_loop().run_until_complete

def msg(pid, text="", photo=False):
    ph = f'<a class="tgme_widget_message_photo_wrap" style="background-image:url(\'http://img/{pid}.jpg\')"></a>' if photo else ""
    txt = f'<div class="tgme_widget_message_text">{text}</div>' if text else ""
    return f'''<div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="chan/{pid}">{txt}{ph}</div>
    </div>'''

def album(pids, text=""):
    subs = ""
    for i,pid in enumerate(pids):
        t = f'<div class="tgme_widget_message_text">{text}</div>' if (i==len(pids)-1 and text) else ""
        subs += f'''<div class="tgme_widget_message_wrap">
          <div class="tgme_widget_message" data-post="chan/{pid}">{t}
          <a class="tgme_widget_message_photo_wrap" style="background-image:url('http://img/{pid}.jpg')"></a>
          </div></div>'''
    return f'<div class="tgme_widget_message_grouped_wrap">{subs}</div>'

def page(html): return f"<html><body>{html}</body></html>"

# ---- Fake httpx client returning fixtures by ?before= ----
class FakeResp:
    def __init__(self, text, code=200): self.text=text; self.status_code=code
class FakeClient:
    def __init__(self, pages, raise_exc=None):
        self.pages = pages  # dict: before_id (or None) -> html
        self.raise_exc = raise_exc
        self.gets = []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url):
        self.gets.append(url)
        if self.raise_exc: raise self.raise_exc
        import re
        m = re.search(r"before=(\d+)", url)
        key = int(m.group(1)) if m else None
        return FakeResp(self.pages.get(key, "<html></html>"))

def patch_client(client):
    S.httpx.AsyncClient = lambda *a, **k: client

_orig_client = S.httpx.AsyncClient

# ---------- ه-4: آلبوم چندتایی → یک پست واحد ----------
html = page(album([101,102,103], text="کپشن آلبوم"))
patch_client(FakeClient({None: html}))
posts = run(S.fetch_channel_posts("chan"))
S.httpx.AsyncClient = _orig_client
check("scraper.album_single_post", len(posts)==1, f"got {len(posts)} posts")
if posts:
    p = posts[0]
    check("scraper.album_id_is_max", p.id==103, f"id={p.id}")
    check("scraper.album_media_count", len([m for m in p.media if m.type=='photo'])==3, f"media={len(p.media)}")
    check("scraper.album_single_caption", "کپشن آلبوم" in p.html_text, repr(p.html_text))

# ---------- ه-3: صفحه‌بندی کل بازه بین last_post_id و جدیدترین را پوشش دهد ----------
# صفحه اول: پست‌های 30..34 ؛ before=30 → 25..29 ؛ before=25 → 20..24
p1 = page("".join(msg(i, text=f"post{i}") for i in range(30,35)))
p2 = page("".join(msg(i, text=f"post{i}") for i in range(25,30)))
p3 = page("".join(msg(i, text=f"post{i}") for i in range(20,25)))
patch_client(FakeClient({None: p1, 30: p2, 25: p3}))
new_posts = run(S.fetch_new_posts("chan", last_post_id=22, limit=100))
S.httpx.AsyncClient = _orig_client
ids = [p.id for p in new_posts]
check("scraper.pagination_covers_range", ids==list(range(23,35)), f"ids={ids}")

# ---------- ه-1 + ه-2: کش «امبد شکست» فقط برای شکست واقعی، نه خطای گذرا ----------
S._embed_fail_cache.clear()
# شکست واقعی (embed برمی‌گرداند None) → کش شود
class C1:
    async def __aenter__(self): return self
    async def __aexit__(self,*a): return False
    async def get(self,url): return FakeResp("<html></html>")  # no video → None
run(S._resolve_video_via_embed(C1(), "chan", 500)) # returns None
S._mark_embed_failed("chan", 500)
check("scraper.real_fail_cached", S._embed_recently_failed("chan",500), "")
# خطای گذرا باید _TransientEmbedError بدهد (کش نشود)
class C2:
    async def get(self,url): raise S.httpx.HTTPError("network down")
raised = False
try:
    run(S._resolve_video_via_embed(C2(), "chan", 501))
except S._TransientEmbedError:
    raised = True
check("scraper.transient_raises", raised, "expected _TransientEmbedError")
check("scraper.transient_not_cached", not S._embed_recently_failed("chan",501), "")

# ه-2 (تکمیلی): status غیر 200 هم گذرا حساب شود
class C3:
    async def get(self,url): return FakeResp("", 502)
raised2 = False
try:
    run(S._resolve_video_via_embed(C3(), "chan", 502))
except S._TransientEmbedError:
    raised2 = True
check("scraper.http_5xx_transient", raised2, "expected transient on 502")

print("\n=== SCRAPER:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
