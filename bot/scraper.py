"""
گرفتن پست‌ها از صفحه‌ی پیش‌نمایش عمومی تلگرام (t.me/s/USERNAME).
معادل پایتونیِ includes/scraper.php ولی با حفظ فرمت‌بندی متن (بولد/ایتالیک/...)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from .formatter import clean_post_html

log = logging.getLogger("repost_bot.scraper")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# چند بار برای خطاهای *گذرا*ی شبکه (تایم‌اوت، قطعیِ اتصال، ۵xx) دوباره امتحان
# کنیم، قبل از این‌که ScraperError پرت بشه و کل کانال برای این تیک رد بشه.
# بدونِ این retry، یک قطعیِ چندصدمیلی‌ثانیه‌ایِ شبکه (خیلی معمول روی سرورهای
# ایران) باعث می‌شد کانال کاملاً از این تیک جا بمونه و تا تیکِ بعدی (۳۰ ثانیه)
# صبر کنه؛ همین باعثِ حسِ «نامنظم» بودنِ ارسال می‌شه، مخصوصاً وقتی همین اتفاق
# پشتِ‌سرِهم برایِ چند کانال بیفته.
_TRANSIENT_HTTP_RETRIES = 2
_TRANSIENT_HTTP_BACKOFF_BASE = 0.7  # ثانیه؛ backoff نمایی: 0.7, 1.4


@dataclass
class MediaItem:
    type: str          # photo / video / document / voice
    url: str
    filename: str = ""


@dataclass
class Post:
    id: int
    html_text: str = ""
    media: list[MediaItem] = field(default_factory=list)
    raw_text: str = ""  # متنِ خامِ کامل (پیش از حذفِ لینک/منشن) - برای تشخیصِ پست تبلیغاتی
    # پستی که ویدیو داشت ولی URLِ مستقیمش از صفحه‌ی پیش‌نمایش استخراج نشد. در این
    # حالت ویدیو داخلِ media نمی‌آید و اگر جلوش گرفته نشود، پست به‌شکلِ فقط‌متن/خالی
    # (بدونِ ویدیو) به مقصد می‌رود. این پرچم به poster اجازه می‌دهد چنین پستی را
    # به‌جای ارسالِ ناقص، رد کند.
    # اگه این پست توی کانالِ مبدأ روی یک پستِ دیگه ریپلای شده باشه، آیدیِ همون
    # پستِ مبدأ اینجا نگه داشته می‌شه تا در مقصد هم همون ریپلای بازسازی بشه.
    reply_to_post_id: int | None = None
    has_unresolved_video: bool = False


class ScraperError(Exception):
    pass


class _TransientEmbedError(Exception):
    """خطای گذرا هنگام گرفتنِ صفحه‌ی امبد (شبکه/پاسخِ نامعتبر). نتیجه‌ش
    کش نمی‌شه تا دفعه‌ی بعد دوباره امتحان بشه."""


# ---------------------------------------------------------------------------
# کشِ «امبدِ ویدیو جواب نداد»
# ---------------------------------------------------------------------------
# برای هر پستی که ویدیوش از صفحه‌ی لیست حل نشده، یک درخواستِ اضافه به صفحه‌ی امبد
# فرستاده می‌شه. مشکل: تا وقتی last_post_id از اون پست رد نشده، این پست سرِ *هر
# تیک* دوباره اسکن و دوباره امبدش گرفته می‌شه - یعنی چند درخواستِ بی‌فایده در هر
# تیک (توی لاگ هم همون چند خطِ تکراریِ «URL مستقیم پیدا نشد» دیده می‌شد). چون
# تلگرام برای این ویدیوها معمولاً هیچ‌وقت src نمی‌ده، نتیجه‌ی شکست رو مدتی کش
# می‌کنیم تا وقتِ تیک هدر نره.
_EMBED_FAIL_TTL = 6 * 3600  # ۶ ساعت
_embed_fail_cache: dict[tuple[str, int], float] = {}


def _embed_recently_failed(username: str, post_id: int) -> bool:
    ts = _embed_fail_cache.get((username, post_id))
    if ts is None:
        return False
    if time.time() - ts > _EMBED_FAIL_TTL:
        _embed_fail_cache.pop((username, post_id), None)
        return False
    return True


def _mark_embed_failed(username: str, post_id: int) -> None:
    if len(_embed_fail_cache) > 5000:  # جلوگیری از رشدِ بی‌پایانِ حافظه
        # حذفِ ۵۰۰ ورودیِ قدیمی‌ترین به‌جای پاک‌کردنِ کامل کش؛ clear() باعث
        # می‌شد همه‌ی ۵۰۰۰ ورودیِ معتبر هم پاک بشن و بلافاصله ۵۰۰۰ درخواستِ
        # embed دوباره به سرور فرستاده بشه (طوفانِ درخواست).
        oldest_keys = sorted(_embed_fail_cache, key=lambda k: _embed_fail_cache[k])[:500]
        for k in oldest_keys:
            _embed_fail_cache.pop(k, None)
    _embed_fail_cache[(username, post_id)] = time.time()


async def fetch_channel_posts(
    username: str,
    before_id: int | None = None,
    remove_self_links: bool = True,
    timeout: float = 15.0,
) -> list[Post]:
    url = f"https://t.me/s/{username}"
    if before_id:
        url += f"?before={int(before_id)}"

    last_exc: Exception | None = None
    resp = None
    for attempt in range(_TRANSIENT_HTTP_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url)
            break  # درخواست موفق بود (حتی اگه status غیر ۲۰۰ باشه، پایین‌تر چک می‌شه)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt >= _TRANSIENT_HTTP_RETRIES:
                # ⚠️ باگ: بعضی خطاهای httpx (مخصوصاً تایم‌اوت/قطعیِ اتصال) وقتی
                # مستقیم به رشته تبدیل بشن (str(e)) خالی‌ان - نتیجه‌ش لاگی مثلِ
                # «خطای شبکه هنگام گرفتن X: » بود که هیچ سرنخی برای دیباگ نمی‌داد
                # (دقیقاً همینو توی لاگِ سرور می‌دیدیم). حالا اگه پیام خالی بود، از
                # اسمِ نوعِ خطا (مثلاً ReadTimeout/ConnectError) به‌جاش استفاده می‌شه.
                detail = str(e) or type(e).__name__
                raise ScraperError(f"خطای شبکه هنگام گرفتن {username}: {detail}") from e
            wait = _TRANSIENT_HTTP_BACKOFF_BASE * (2 ** attempt)
            log.debug(
                "خطای گذرای شبکه هنگام گرفتن @%s (تلاش %s از %s)؛ %.1f ثانیه دیگه دوباره: %s",
                username, attempt + 1, _TRANSIENT_HTTP_RETRIES + 1, wait, e,
            )
            await asyncio.sleep(wait)

    if resp is None:  # نباید برسه اینجا (بالا یا break شده یا raise شده)، محضِ اطمینان
        detail = str(last_exc) if last_exc else "نامشخص"
        raise ScraperError(f"خطای شبکه هنگام گرفتن {username}: {detail}")

    # خطاهای سمتِ سرور (۵xx) هم گذرا حساب می‌شن؛ اینجا رسیدیم یعنی کلِ retry
    # بالا تمومِ شده یا اصلاً status اولین‌بار ۲۰۰ نبوده - یک بارِ دیگه، این‌بار
    # صریح، برای ۵xx retry می‌کنیم چون httpx خودش برای status code استثنا پرت
    # نمی‌کنه (فقط برای خطاهای اتصال/تایم‌اوت پرت می‌کنه).
    if resp.status_code >= 500:
        for attempt in range(_TRANSIENT_HTTP_RETRIES):
            wait = _TRANSIENT_HTTP_BACKOFF_BASE * (2 ** attempt)
            log.debug(
                "پاسخِ %s (سمتِ سرور) از @%s؛ %.1f ثانیه دیگه دوباره امتحان می‌شه.",
                resp.status_code, username, wait,
            )
            await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(
                    headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
                ) as client:
                    resp = await client.get(url)
            except httpx.HTTPError as e:
                detail = str(e) or type(e).__name__
                raise ScraperError(f"خطای شبکه هنگام گرفتن {username}: {detail}") from e
            if resp.status_code < 500:
                break

    if resp.status_code != 200 or not resp.text:
        raise ScraperError(f"پاسخ نامعتبر از {url} (status={resp.status_code})")

    soup = BeautifulSoup(resp.text, "lxml")
    posts: list[Post] = []

    # ---------------------------------------------------------------------
    # آلبوم‌های چندتایی (چند عکس/ویدیو با هم در یک پست):
    # صفحه‌ی پیش‌نمایشِ عمومیِ تلگرام هر آیتمِ آلبوم رو در یک
    # ".tgme_widget_message_wrap" جداگانه (با data-post خودش) رندر می‌کنه، همه
    # زیرِ یک والدِ مشترکِ ".tgme_widget_message_grouped_wrap". فقط یکی از
    # این آیتم‌ها (معمولا آخری) متنِ/کپشنِ واقعیِ کل آلبوم رو داره؛ بقیه متنِ
    # خالی دارن. اگه هر آیتم رو مثلِ یک پستِ کاملاً مستقل پردازش کنیم (رفتارِ
    # قبلی)، نتیجه دقیقاً همون باگیه که مشاهده شد: مدیا و کپشن از هم جدا
    # می‌شن و توی پیام‌های مجزا (با فاصله‌ی زمانیِ ارسال) به مقصد می‌رسن.
    # برای همین اول تمام آیتم‌های هر گروه رو جمع می‌کنیم و یک Post واحد
    # می‌سازیم؛ آیدیِ نهایی = بزرگ‌ترین آیدیِ زیرمجموعه (تا last_post_id
    # درست جلو بره و هیچ‌کدوم از زیرپست‌ها دوباره پردازش نشن).
    grouped_wrap_ids: set[int] = set()

    for group in soup.select(".tgme_widget_message_grouped_wrap"):
        sub_wraps = group.select(".tgme_widget_message_wrap")
        if not sub_wraps:
            continue

        sub_ids: list[int] = []
        combined_media: list[MediaItem] = []
        combined_html_text = ""
        combined_raw_text = ""
        combined_unresolved_video = False
        combined_reply_to: int | None = None

        for wrap in sub_wraps:
            grouped_wrap_ids.add(id(wrap))
            msg = wrap.select_one(".tgme_widget_message")
            if not msg:
                continue
            parsed = _parse_message(msg, username, remove_self_links)
            if parsed is None:
                continue
            post_id, html_text, raw_text, media, unresolved_video, reply_to = parsed
            sub_ids.append(post_id)
            combined_media.extend(media)
            if unresolved_video:
                combined_unresolved_video = True
            if combined_reply_to is None and reply_to is not None:
                combined_reply_to = reply_to
            # طبق مشاهده‌ی معمولِ صفحه‌ی پیش‌نمایش، فقط یکی از آیتم‌های گروه
            # متنِ غیرخالی داره؛ اگه به‌هر دلیلی چندتاشون متن داشتن، اولینِ
            # غیرخالی رو نگه می‌داریم (بقیه رد میشن) تا کپشن تکراری نشه.
            if not combined_html_text and html_text.strip():
                combined_html_text = html_text
            if not combined_raw_text and raw_text.strip():
                combined_raw_text = raw_text

        if not sub_ids:
            continue

        posts.append(Post(
            id=max(sub_ids),
            html_text=combined_html_text,
            media=combined_media,
            raw_text=combined_raw_text,
            has_unresolved_video=combined_unresolved_video,
            reply_to_post_id=combined_reply_to,
        ))

    for wrap in soup.select(".tgme_widget_message_wrap"):
        if id(wrap) in grouped_wrap_ids:
            continue  # قبلاً به‌عنوانِ بخشی از یک آلبوم پردازش شد
        msg = wrap.select_one(".tgme_widget_message")
        if not msg:
            continue

        parsed = _parse_message(msg, username, remove_self_links)
        if parsed is None:
            continue
        post_id, html_text, raw_text, media, unresolved_video, reply_to = parsed
        posts.append(Post(
            id=post_id, html_text=html_text, media=media, raw_text=raw_text,
            has_unresolved_video=unresolved_video, reply_to_post_id=reply_to,
        ))

    # ---------- تلاشِ بازیابیِ ویدیوهایی که URLشون توی صفحه‌ی لیست نبود ----------
    # صفحه‌ی t.me/s گاهی src مستقیمِ ویدیو رو نمی‌ذاره؛ ولی صفحه‌ی امبدِ تکیِ همون
    # پست (t.me/USERNAME/ID?embed=1) اغلب همون URL رو داره. برای هر پستی که ویدیوش
    # حل‌نشده مونده، یک‌بار امبد رو می‌گیریم و اگه ویدیو پیدا شد اضافه‌ش می‌کنیم.
    unresolved = [
        p for p in posts
        if p.has_unresolved_video
        and not any(m.type == "video" for m in p.media)
        and not _embed_recently_failed(username, p.id)
    ]
    if unresolved:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
            ) as client:
                for p in unresolved:
                    try:
                        vid_url = await _resolve_video_via_embed(client, username, p.id)
                    except _TransientEmbedError as _te:
                        # خطای گذرا: کش نکن تا دفعه‌ی بعد دوباره امتحان بشه.
                        log.debug(
                            "گرفتنِ امبدِ پست %s از @%s موقتاً ناموفق بود: %s", p.id, username, _te,
                        )
                        continue
                    if vid_url:
                        p.media.append(MediaItem(type="video", url=vid_url))
                        p.has_unresolved_video = False
                        log.info("ویدیوی پست %s از @%s از صفحه‌ی امبد بازیابی شد.", p.id, username)
                    else:
                        # تلگرام برای این ویدیو src نمی‌ده؛ تا مدتی دوباره امتحان نکن
                        # تا هر تیک یک درخواستِ بی‌فایده فرستاده نشه.
                        _mark_embed_failed(username, p.id)
        except Exception as e:  # noqa: BLE001 - بازیابی best-effort است و نباید کلِ اسکرِیپ رو بترکونه
            log.debug("بازیابیِ امبدِ ویدیو برای @%s با خطا مواجه شد: %s", username, e)

    # صفحه از قدیم به جدید نیست همیشه؛ مرتب‌سازی صعودی بر اساس آیدی پست
    posts.sort(key=lambda p: p.id)
    return posts


async def _resolve_video_via_embed(client, username: str, post_id: int) -> str | None:
    """صفحه‌ی امبدِ یک پستِ تکی رو می‌گیره و اگه URLِ مستقیمِ ویدیو داشت برمی‌گردونه.
    best-effort است؛ اگه چیزی پیدا نشد None برمی‌گردونه.

    اگه خطا «گذرا» باشه (قطعیِ شبکه یا پاسخِ نامعتبرِ سرور)، استثنای
    _TransientEmbedError پرتاب می‌شه تا صداکننده این نتیجه رو *کش نکنه* و سرِ
    فرصتِ بعدی دوباره امتحان کنه؛ وگرنه یک قطعیِ لحظه‌ایِ اینترنت باعث می‌شد
    ویدیوی یک پستِ کاملاً سالم تا ساعت‌ها دیگه بازیابی نشه."""
    url = f"https://t.me/{username}/{post_id}?embed=1&mode=tme"
    try:
        resp = await client.get(url)
    except httpx.HTTPError as e:
        raise _TransientEmbedError(str(e)) from e
    if resp.status_code != 200 or not resp.text:
        raise _TransientEmbedError(f"status={resp.status_code}")
    soup = BeautifulSoup(resp.text, "lxml")
    # ۱) تگِ <video ...> با src یا <source>
    for v in soup.select("video"):
        src = v.get("src") or v.get("data-src")
        if not src:
            source_tag = v.select_one("source")
            if source_tag:
                src = source_tag.get("src") or source_tag.get("data-src")
        if src and src.startswith("http"):
            return src
    # ۲) متاtگِ og:video (بعضی امبدها ویدیو رو اینجا می‌ذارن)
    for prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
        meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content", "").startswith("http"):
            content = meta["content"]
            if content.lower().split("?")[0].endswith((".mp4", ".mov", ".webm")):
                return content
    return None


def _parse_message(
    msg, username: str, remove_self_links: bool
) -> tuple[int, str, str, list[MediaItem], bool, int | None] | None:
    """یک <div class="tgme_widget_message"> رو پارس می‌کنه و
    (post_id, html_text, raw_text, media) برمی‌گردونه. اگه data-post معتبر
    نداشت None برمی‌گردونه."""
    data_post = msg.get("data-post", "")
    if not data_post or "/" not in data_post:
        return None
    try:
        post_id = int(data_post.rsplit("/", 1)[-1])
    except ValueError:
        return None

    # ---------- حذفِ بلاکِ ریپلای/کوت (پیش‌نمایشِ پیامِ قبلی) ----------
    # کانال‌های پوشش زنده (مثل varzesh3) هر پستِ تازه رو روی پستِ قبلیِ خودشون
    # ریپلای می‌کنن. تلگرام این ریپلای رو داخلِ همون بلاکِ HTMLِ پیامِ جدید، به
    # شکلِ یک پیش‌نمایشِ کوچیک از پیامِ قبلی رندر می‌کنه - و دقیقاً همون کلاسِ
    # ".tgme_widget_message_text" رو برای متنِ آن پیش‌نمایش هم به‌کار می‌بره.
    # چون این بلاکِ ریپلای همیشه قبل از متنِ اصلیِ پست توی DOM میاد، اگه حذفش
    # نکنیم، select_one پایین‌تر به‌جای متنِ خودِ پست، متنِ پستِ *قبلی* (ریپلای‌شده)
    # رو برمی‌داره - دقیقاً همون باگیه که باعثِ می‌شد کپشنِ هر پست با پستِ دیگه
    # عوض بشه و هماهنگیِ متن/مدیا به‌هم بریزه. برای همین قبل از هرگونه
    # استخراجِ متن یا مدیا، این بلاک کاملاً از درختِ پیام حذف میشه.
    # ولی *قبل* از حذف، آیدیِ پستی که این پست بهش ریپلای شده رو از روی لینکِ
    # همون بلاک درمیاریم (href مثلِ https://t.me/username/12345) تا بتونیم در
    # مقصد همون ریپلای رو بازسازی کنیم.
    reply_to_post_id: int | None = None
    for reply_block in msg.select(".tgme_widget_message_reply"):
        if reply_to_post_id is None:
            href = reply_block.get("href", "") or ""
            m_reply = re.search(r"/(\d+)(?:\?[^/]*)?$", href)
            if m_reply:
                try:
                    reply_to_post_id = int(m_reply.group(1))
                except ValueError:
                    reply_to_post_id = None
        reply_block.decompose()

    html_text = ""
    raw_text = ""
    text_node = msg.select_one(".tgme_widget_message_text")
    if text_node:
        # متنِ خامِ کامل رو قبل از هرگونه حذفِ لینک/منشن نگه می‌داریم؛ فیلترِ
        # پستِ تبلیغاتی باید روی همین متنِ اصلی کار کنه، نه نسخه‌ی پاک‌شده
        # (چون اگه «حذف لینک/آدرس» فعال باشه، تا وقتی نسخه‌ی پاک‌شده رو
        # بررسی کنیم، دقیقاً همون نشونه‌های تبلیغاتی [لینک/منشنِ زیاد] از
        # بین رفتن).
        raw_text = text_node.get_text(" ", strip=True)
        html_text = clean_post_html(text_node, username, remove_self_links)

    media: list[MediaItem] = []

    for a in msg.select(".tgme_widget_message_photo_wrap"):
        style = a.get("style", "")
        m = re.search(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)", style, flags=re.I)
        if m:
            media.append(MediaItem(type="photo", url=m.group(1)))

    # ---------- ویدیو ----------
    # نکته‌ی مهم: صفحه‌ی پیش‌نمایشِ عمومیِ تلگرام (t.me/s/...) همیشه URL
    # مستقیمِ قابل‌دانلودِ ویدیو رو توی HTMLِ استاتیک نمی‌ذاره (بعضی‌وقتا
    # فقط تصویرِ بندانگشتی + مدت‌زمان رو نشون می‌ده و src واقعی فقط با
    # اجرای جاوااسکریپت/داخلِ اپ در دسترسه). برای همین چند جا رو با
    # اولویت‌های مختلف چک می‌کنیم تا بیشترین شانس رو برای پیدا کردنِ src
    # داشته باشیم؛ اگه هیچ‌کدوم جواب نداد، به‌جای سکوت، توی لاگ ثبت میشه
    # که این پست ویدیو داشته ولی URLش پیدا نشده (برای دیباگ).
    def _extract_video_src(video_tag) -> str | None:
        if video_tag is None:
            return None
        src = video_tag.get("src") or video_tag.get("data-src")
        if src:
            return src
        source_tag = video_tag.select_one("source")
        if source_tag:
            return source_tag.get("src") or source_tag.get("data-src")
        return None

    video_found_wrapper = False
    has_unresolved_video = False
    for video_wrap in msg.select(
        ".tgme_widget_message_video_player, .tgme_widget_message_roundvideo_player"
    ):
        video_found_wrapper = True
        src = _extract_video_src(video_wrap.select_one("video")) or video_wrap.get("data-src")
        if src:
            media.append(MediaItem(type="video", url=src))
        else:
            has_unresolved_video = True
            log.info(
                "پست %s از @%s ویدیو داره ولی URLِ مستقیمی توی صفحه‌ی پیش‌نمایش پیدا "
                "نشد (احتمالاً تلگرام برای این ویدیو src مستقیم نمی‌ده).",
                post_id, username,
            )

    # جاافتاده‌های احتمالی: اگه رَپرِ استانداردِ بالا پیدا نشد ولی یک تگِ
    # <video> مستقل توی پیام هست، همون رو هم امتحان می‌کنیم.
    if not video_found_wrapper:
        for v in msg.select("video"):
            src = _extract_video_src(v)
            if src:
                media.append(MediaItem(type="video", url=src))

    for d in msg.select(".tgme_widget_message_document_wrap"):
        href = d.get("href")
        title_node = d.select_one(".tgme_widget_message_document_title")
        # فایل‌هایی مثل APK معمولاً توی خودِ عنوان پسوند ندارن (مثلاً "app (7)")
        # و نوعِ فایل جدا، توی زیرنویسِ حجم/نوع (مثلاً "53.07 MiB APK") میاد؛
        # برای همین هر دو رو با هم ذخیره می‌کنیم تا تشخیصِ پسوند (ad_filter)
        # هر دو حالت رو پوشش بده.
        extra_node = d.select_one(".tgme_widget_message_document_extra")
        title = title_node.get_text(strip=True) if title_node else ""
        extra = extra_node.get_text(strip=True) if extra_node else ""
        filename = " ".join(p for p in (title, extra) if p) or "file"
        if href:
            media.append(MediaItem(type="document", url=href, filename=filename))

    # ویسِ صوتی (Voice) و فایلِ موزیک/صوتی (Audio) هر دو با تگِ <audio> رندر
    # می‌شن، ولی توی یک کانتینرِ متفاوت (voice_player در برابرِ audio_player)
    # قرار می‌گیرن. تفکیک‌شون لازمه چون طبقِ تنظیمات، ویس اصلاً ارسال نمیشه
    # ولی موزیک/فایلِ صوتی ارسال میشه.
    for voice_wrap in msg.select(".tgme_widget_message_voice_player"):
        audio_tag = voice_wrap.select_one("audio")
        src = audio_tag.get("src") if audio_tag else voice_wrap.get("data-src")
        if src:
            media.append(MediaItem(type="voice", url=src))

    for audio_wrap in msg.select(".tgme_widget_message_audio_player"):
        audio_tag = audio_wrap.select_one("audio")
        src = audio_tag.get("src") if audio_tag else audio_wrap.get("data-src")
        if not src:
            continue
        title_node = audio_wrap.select_one(".tgme_widget_message_audio_title")
        performer_node = audio_wrap.select_one(".tgme_widget_message_audio_performer")
        parts = [n.get_text(strip=True) for n in (performer_node, title_node) if n and n.get_text(strip=True)]
        filename = " - ".join(parts) if parts else "audio"
        media.append(MediaItem(type="audio", url=src, filename=filename))

    # جاافتاده‌های احتمالی: بعضی نسخه‌های صفحه‌ی پیش‌نمایش ممکنه audio رو
    # بدون کلاسِ کانتینرِ بالا رندر کنن؛ هر <audio> باقی‌مونده‌ای که توی
    # دو حلقه‌ی بالا گرفته نشده، به‌صورتِ محافظه‌کارانه «voice» در نظر
    # گرفته میشه.
    # ⚠️ توجه: برخلافِ نسخه‌های قدیمی، الان poster.py پیام‌های نوعِ «voice» رو
    # هم واقعاً ارسال می‌کنه (send_voice)، نه اینکه نادیده گرفته بشن. یعنی این
    # fallback دیگه یک «قفلِ ایمنیِ ساکت» نیست؛ اگه یک آهنگِ واقعی این مسیرِ
    # جاافتاده رو بگیره، به‌جای send_audio (با عنوان/خواننده) با send_voice
    # ارسال می‌شه (بدون عنوان). این فقط برای موارد جاافتاده/نادرِ ساختارِ HTML
    # پیش میاد، نه مسیرِ عادی؛ اگه رفتارِ دیگه‌ای (مثلاً رد کردنِ کاملِ این موارد
    # به‌جای حدس زدن) ترجیح داده میشه، همین‌جا باید عوض بشه.
    already_handled_srcs = {m.url for m in media if m.type in ("voice", "audio")}
    for a_tag in msg.select("audio"):
        src = a_tag.get("src")
        if src and src not in already_handled_srcs:
            media.append(MediaItem(type="voice", url=src))

    return post_id, html_text, raw_text, media, has_unresolved_video, reply_to_post_id


async def fetch_new_posts(
    username: str,
    last_post_id: int,
    remove_self_links: bool = True,
    limit: int = 20,
    max_pages: int = 15,
) -> list[Post]:
    """
    پست‌های جدیدتر از last_post_id رو برمی‌گردونه (حداکثر limit تا، مرتب‌شده
    از قدیم به جدید).

    باگِ قبلی («بعضی پست‌ها جا می‌مونن»): این تابع فقط یک صفحه (t.me/s/username،
    آخرین ~۲۰ پست) رو می‌گرفت. اگه از آخرین باری که چک شده بود بیشتر از یک
    صفحه پستِ تازه منتشر شده باشه (کانال پرکار، یا ربات مدتی خاموش/کند بوده،
    یا حالتِ schedule که فقط ۱ پست در هر اسلات می‌فرسته و ممکنه backlog جمع
    بشه)، پست‌های قدیمی‌ترِ آن بازه اصلاً توی همون یک صفحه دیده نمی‌شدن، و چون
    این تابع هیچ صفحه‌ی قبلی‌ای رو چک نمی‌کرد، وقتی last_post_id ازشون فاصله
    می‌گرفت، برای همیشه از دست می‌رفتن (نه اینکه دیر برسن - اصلاً هیچ‌وقت
    ارسال نمی‌شدن).

    راه‌حل: از آخرین صفحه شروع می‌کنیم و تا وقتی که قدیمی‌ترین پستِ صفحه‌ی
    فعلی هنوز جدیدتر از last_post_id باشه، با پارامترِ before به صفحه‌ی قبلی
    (قدیمی‌تر) می‌ریم؛ این‌طوری کلِ بازه‌ی [last_post_id, جدیدترین پست] پوشش
    داده میشه، نه فقط آخرین صفحه. max_pages صرفاً یک سقفِ ایمنی است (مثلاً
    برای اولین اجرا با last_post_id=0 که وگرنه تا ابتدای کانال می‌رفت جلو).
    """
    all_new: dict[int, Post] = {}
    before_id: int | None = None
    pages_fetched = 0

    while pages_fetched < max_pages:
        try:
            page_posts = await fetch_channel_posts(
                username, before_id=before_id, remove_self_links=remove_self_links
            )
        except ScraperError:
            if pages_fetched == 0:
                raise  # صفحه‌ی اول اگه خطا داد، باید بالا گزارش بشه
            break  # حداقل صفحه‌ی اول رو گرفتیم؛ خطای صفحه‌ی قبل رو نادیده می‌گیریم
        pages_fetched += 1

        if not page_posts:
            break

        for p in page_posts:
            if p.id > last_post_id:
                all_new[p.id] = p

        oldest_on_page = page_posts[0].id
        if oldest_on_page <= last_post_id:
            break  # به پست‌هایی رسیدیم که قبلاً دیده شدن؛ نیازی به عقب‌تر رفتن نیست

        # فیکسِ S3 (ایمنی/کارایی): اگه صفحه‌ی بعدی همون before_id رو داد (یعنی
        # قدیمی‌ترین آیدی جلو نرفت)، ادامه‌دادن فقط همون صفحه رو بارها می‌گیره و
        # تا سقفِ max_pages درخواستِ بی‌فایده می‌فرسته. t.me/s در حالتِ عادی درست
        # صفحه‌بندی می‌کنه، ولی این نگهبان تضمین می‌کنه هیچ‌وقت روی یک صفحه گیر نکنیم.
        if before_id is not None and oldest_on_page >= before_id:
            break

        before_id = oldest_on_page

    fresh = sorted(all_new.values(), key=lambda p: p.id)
    return fresh[:limit] if limit else fresh


async def fetch_latest_post_id(username: str, remove_self_links: bool = True) -> int:
    """
    آیدیِ آخرین پستِ فعلیِ کانال رو برمی‌گردونه (یا 0 اگه کانال خالی/غیرقابل‌دسترس بود).
    برای «پایه‌گذاریِ» last_post_id استفاده میشه: وقتی کانالی تازه اضافه میشه یا حالت‌ِ
    ارسال لحظه‌ای‌اش روشن میشه، last_post_id رو روی همین مقدار می‌ذاریم تا فقط پست‌هایی
    که *بعد از همین لحظه* منتشر میشن جدید حساب بشن، نه پست‌های قدیمی‌تر (مثلا از چند
    دقیقه/ساعت قبل).
    """
    posts = await fetch_channel_posts(username, remove_self_links=remove_self_links)
    if not posts:
        return 0
    return max(p.id for p in posts)


async def fetch_latest_posts(
    username: str, limit: int, remove_self_links: bool = True, max_pages: int = 6
) -> list[Post]:
    """
    آخرین `limit` پستِ کانال رو برمی‌گردونه (مرتب‌شده از قدیم به جدید)، صرف‌نظر از
    اینکه قبلا ارسال شدن یا نه - برای اپشن «ارسال ۱۰/۲۰/۳۰ پست آخر». چون هر صفحه‌ی
    t.me/s معمولا حدود ۲۰ پست داره، در صورت نیاز به صفحه‌ی قبلی هم می‌ره (پارامتر
    before) تا به تعداد کافی پست برسه؛ نهایتا با max_pages محدود میشه که خیلی
    عقب نره یا برای همیشه لوپ نزنه.
    """
    all_posts: list[Post] = await fetch_channel_posts(username, remove_self_links=remove_self_links)
    pages_fetched = 1
    while len(all_posts) < limit and pages_fetched < max_pages:
        if not all_posts:
            break
        oldest_id = all_posts[0].id
        older = await fetch_channel_posts(
            username, before_id=oldest_id, remove_self_links=remove_self_links
        )
        older = [p for p in older if p.id < oldest_id]
        if not older:
            break
        all_posts = older + all_posts
        pages_fetched += 1

    all_posts.sort(key=lambda p: p.id)
    return all_posts[-limit:] if limit else all_posts
