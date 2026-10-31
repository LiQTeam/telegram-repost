"""
جست‌وجویِ وب (تصویر/خبر) — فقط با SerpAPI.

طراحی (طبقِ درخواستِ کاربر):
--------------------------------
۱) تک‌موتوره: کاملاً روی SerpAPI. هیچ Providerِ دیگری (Google CSE/CX) استفاده نمی‌شود.
۲) پنج کلیدِ SerpAPI قابلِ‌واردکردن است و بعد از هر جست‌وجو، انتخابِ کلید بینِ پنج
   کلیدِ تنظیم‌شده به‌صورتِ چرخشی (round-robin) جلو می‌رود تا سهمیه‌ی رایگانِ همه‌ی
   کلیدها یکنواخت مصرف شود. اگر کلیدِ انتخابی خطا/۴۲۹ داد، خودکار سراغِ کلیدِ بعدی
   می‌رود (تا وقتی همه‌ی کلیدها امتحان شوند).
۳) یک ورودیِ واحد: خودِ متنِ جست‌وجو نوعش را تعیین می‌کند.
   • اگر شاملِ کلمه‌ی «عکس» (یا مترادف‌های عکس‌محور) باشد → فقط تصویر، بدونِ هیچ
     توضیح/کپشنی زیرِ عکس‌ها.
   • اگر شاملِ «خبر/اخبار» باشد → خبر همراه با لینکِ سایتِ منبع (و در صورتِ وجود،
     عکسِ خبر).
   • در غیرِ این‌صورت پیش‌فرض: تصویر.
۴) همیشه جدیدترین‌ها بالا: هم برای عکس و هم خبر، مرتب‌سازیِ زمانی (SerpAPI: tbs=qdr
   برای تازگی + مرتب‌سازیِ نتایج بر اساسِ تاریخ در صورتِ در دسترس بودن).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from .database import db
from . import ai_crypto as crypto

log = logging.getLogger("repost_bot.web_search")

SETTINGS_KEY = "web_search_settings"
ROTATION_KEY = "web_search_serpapi_cursor"  # اندیسِ کلیدِ بعدی برای چرخش

SERPAPI_URL = "https://serpapi.com/search.json"

TIMEOUT = 20
MIN_IMAGE_DIMENSION = 400  # زیرِ این سایز، عکس رد می‌شه (thumbnailِ بی‌کیفیت)
MAX_PER_DOMAIN = 2
MAX_KEYS = 5

# کلمات کلیدیِ تشخیصِ نوعِ جست‌وجو (فارسی)
_NEWS_WORDS = ("اخبار", "خبر", "خبری", "خبرها")
_IMAGE_WORDS = ("عکس", "تصویر", "کاور", "پوستر", "والپیپر", "wallpaper")

# اعرابِ عربی/فارسی (فتحه/کسره/ضمه/تشدید/سکون/تنوین) و کشیده. این‌ها نویسه‌ی
# «کلمه» (\w) حساب نمی‌شن، پس مرزِ کلمه‌ی regex درست‌شون رو نمی‌گیره و مثلاً در
# «عکسِ گربه» بعد از حذفِ «عکس» یک کسره‌ی سرگردان («ِ گربه») توی کوئری می‌مونْد
# و همون هم به SerpAPI فرستاده می‌شد. قبل از هر تطبیقی حذف‌شون می‌کنیم.
_DIACRITICS_RE = re.compile(r"[ً-ْٰـ]")

# طولانی‌ترین کلمه اول، تا «اخبار» قبل از «خبر» تطبیق بخوره و تکه‌ی نصفه نمونه.
_ALL_KIND_WORDS = tuple(sorted((*_NEWS_WORDS, *_IMAGE_WORDS), key=len, reverse=True))


def _normalize(query: str) -> str:
    return _DIACRITICS_RE.sub("", query or "")


def _first_word_index(text: str, words) -> int | None:
    """اندیسِ اولین تطبیقِ *کلمه‌ی کامل* از میانِ words، یا None.

    تطبیقِ زیررشته‌ای عمداً استفاده نمی‌شود: «خبر» زیررشته‌ی «خبرنگار» هم هست و
    قبلاً باعث می‌شد «عکس خبرنگار» به‌اشتباه «خبر» تشخیص داده شود.
    """
    best = None
    for w in words:
        m = re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def detect_search_kind(query: str) -> str:
    """نوعِ جست‌وجو را از متن تشخیص می‌دهد: 'news' یا 'image'.

    تطبیق فقط روی «کلمه‌ی کامل» انجام می‌شود؛ اگر هر دو نوع کلمه در متن بودند،
    هر کدام که *زودتر* آمده برنده است (یعنی «عکس خبرنگار» عکس است و «اخبار
    عکس‌دار» خبر). اگر هیچ‌کدام نبود، پیش‌فرض image است (طبقِ درخواستِ کاربر).
    """
    q = _normalize(query)
    news_at = _first_word_index(q, _NEWS_WORDS)
    image_at = _first_word_index(q, _IMAGE_WORDS)
    if news_at is not None and (image_at is None or news_at < image_at):
        return "news"
    return "image"


def _strip_kind_words(query: str) -> str:
    """کلمه‌ی «عکس/تصویر/خبر/...» را از متنِ جست‌وجو حذف می‌کند تا کوئریِ ارسالی به
    SerpAPI فقط خودِ موضوع باشد (مثلاً «عکس گربه» → «گربه»)."""
    q = _normalize(query)
    for w in _ALL_KIND_WORDS:
        q = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q or _normalize(query).strip() or query.strip()


class WebSearchSettings:
    """مدیریتِ پنج کلیدِ SerpAPI (رمزنگاری‌شده در دیتابیس) + چرخشِ round-robin."""

    @staticmethod
    def get() -> dict:
        raw = db.get_setting(SETTINGS_KEY, "{}")
        try:
            data = json.loads(raw) or {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        keys = data.get("serpapi_keys")
        # سازگاری با نسخه‌ی قدیمی که یک کلیدِ تکی داشت.
        if keys is None:
            keys = []
            legacy = data.get("serpapi_key", "")
            if legacy:
                keys = [legacy]
        # همیشه دقیقاً MAX_KEYS خانه (رمزنگاری‌شده یا رشته‌ی خالی) برمی‌گردونیم.
        keys = list(keys)[:MAX_KEYS]
        keys += [""] * (MAX_KEYS - len(keys))
        return {"serpapi_keys": keys}

    @staticmethod
    def get_decrypted_keys() -> list[str]:
        raw = WebSearchSettings.get()["serpapi_keys"]
        out = []
        for enc in raw:
            if enc:
                try:
                    out.append(crypto.decrypt_text(enc))
                except Exception:  # noqa: BLE001 - کلیدِ خراب نباید کلِ جست‌وجو رو بترکونه
                    out.append("")
            else:
                out.append("")
        return out

    @staticmethod
    def active_keys() -> list[str]:
        """فقط کلیدهایِ ناتهیِ رمزگشایی‌شده، به ترتیبِ خانه‌ها."""
        return [k for k in WebSearchSettings.get_decrypted_keys() if k]

    @staticmethod
    def set_key(index: int, value: str):
        if not (0 <= index < MAX_KEYS):
            raise ValueError("اندیسِ کلید نامعتبر است")
        data = WebSearchSettings.get()
        keys = data["serpapi_keys"]
        keys[index] = crypto.encrypt_text(value) if value else ""
        db.set_setting(SETTINGS_KEY, json.dumps({"serpapi_keys": keys}, ensure_ascii=False))

    @staticmethod
    def clear_all():
        db.set_setting(SETTINGS_KEY, json.dumps({"serpapi_keys": [""] * MAX_KEYS}, ensure_ascii=False))

    # --------- چرخشِ round-robin بینِ کلیدهای فعال ---------
    @staticmethod
    def _cursor() -> int:
        try:
            return int(db.get_setting(ROTATION_KEY, "0") or "0")
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _advance_cursor(n_active: int):
        if n_active <= 0:
            return
        nxt = (WebSearchSettings._cursor() + 1) % n_active
        db.set_setting(ROTATION_KEY, str(nxt))

    @staticmethod
    def ordered_keys_for_search() -> list[str]:
        """لیستِ کلیدهای فعال را طوری مرتب می‌کند که کلیدِ «نوبتِ این سرچ» اول باشد
        و بقیه پشتِ سرش (برای فالبک اگر این کلید خطا داد). بعد از فراخوانی، مکان‌نما
        یک قدم جلو می‌رود تا سرچِ بعدی از کلیدِ بعدی شروع شود."""
        active = WebSearchSettings.active_keys()
        if not active:
            return []
        start = WebSearchSettings._cursor() % len(active)
        ordered = active[start:] + active[:start]
        WebSearchSettings._advance_cursor(len(active))
        return ordered

    @staticmethod
    def status_text() -> str:
        keys = WebSearchSettings.get()["serpapi_keys"]
        lines = ["🔎 <b>SerpAPI</b> (تنها موتورِ جست‌وجو)"]
        for i, k in enumerate(keys, start=1):
            mark = "🟢 تنظیم‌شده" if k else "🔴 خالی"
            lines.append(f"  کلیدِ {i}: {mark}")
        n = sum(1 for k in keys if k)
        lines.append(f"— {n} از {MAX_KEYS} کلید فعال (چرخش بعد از هر سرچ)")
        return "\n".join(lines)


class WebSearchRouter:
    def __init__(self, timeout: float = TIMEOUT):
        self.session = httpx.AsyncClient(timeout=timeout)
        self._last_error: Optional[str] = None

    async def close(self):
        await self.session.aclose()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @staticmethod
    def _domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower().replace("www.", "")
        except Exception:
            return ""

    @classmethod
    def _rank_and_dedupe(cls, results: list[dict], count: int) -> list[dict]:
        filtered = [
            r for r in results
            if (r.get("width") or MIN_IMAGE_DIMENSION) >= MIN_IMAGE_DIMENSION
            and (r.get("height") or MIN_IMAGE_DIMENSION) >= MIN_IMAGE_DIMENSION
        ]
        if not filtered:
            filtered = results
        filtered.sort(key=lambda r: (r.get("width") or 0) * (r.get("height") or 0), reverse=True)
        out: list[dict] = []
        domain_count: dict[str, int] = {}
        for r in filtered:
            d = cls._domain(r.get("source_url") or r.get("image_url") or "")
            if domain_count.get(d, 0) >= MAX_PER_DOMAIN:
                continue
            domain_count[d] = domain_count.get(d, 0) + 1
            out.append(r)
            if len(out) >= count:
                break
        return out

    # ------------------------------------------------------------------
    # فراخوانیِ SerpAPI با چرخش/فالبکِ کلید
    # ------------------------------------------------------------------
    async def _serpapi_call(self, base_params: dict) -> dict:
        """SerpAPI را با کلیدهای چرخشی صدا می‌زند. اولین کلیدی که موفق شد، نتیجه‌اش
        برمی‌گردد. اگر کلیدی خطا/۴۲۹ داد، کلیدِ بعدی امتحان می‌شود."""
        keys = WebSearchSettings.ordered_keys_for_search()
        if not keys:
            raise RuntimeError("هیچ کلیدِ SerpAPI تنظیم نشده")
        last_exc: Optional[Exception] = None
        for i, key in enumerate(keys):
            params = dict(base_params)
            params["api_key"] = key
            try:
                resp = await self.session.get(SERPAPI_URL, params=params)
                if resp.status_code == 429:
                    last_exc = RuntimeError(f"SerpAPI کلیدِ #{i+1}: سهمیه تمام شده (HTTP 429)")
                    log.info("SerpAPI کلیدِ #%s سهمیه تمام؛ کلیدِ بعدی امتحان می‌شود.", i + 1)
                    continue
                resp.raise_for_status()
                data = resp.json()
                # SerpAPI حتی با ۲۰۰ گاهی خطا را در بدنه می‌گذارد.
                if isinstance(data, dict) and data.get("error"):
                    last_exc = RuntimeError(f"SerpAPI کلیدِ #{i+1}: {data.get('error')}")
                    log.info("SerpAPI کلیدِ #%s خطا داد (%s)؛ کلیدِ بعدی.", i + 1, data.get("error"))
                    continue
                return data
            except Exception as e:  # noqa: BLE001 - هر خطا → کلیدِ بعدی
                last_exc = e
                log.info("SerpAPI کلیدِ #%s ناموفق (%s)؛ کلیدِ بعدی امتحان می‌شود.", i + 1, e)
                continue
        raise last_exc or RuntimeError("همه‌ی کلیدهای SerpAPI ناموفق بودند")

    # ------------------------------------------------------------------
    # تصویر
    # ------------------------------------------------------------------
    async def image_search(self, query: str, count: int = 4) -> list[dict]:
        self._last_error = None
        q = _strip_kind_words(query)
        params = {
            "engine": "google_images",
            "q": q,
            "num": min(max(count * 2, 4), 20),
            # جدیدترین‌ها بالا: محدودیتِ زمانیِ «سالِ اخیر» + مرتب‌سازیِ نتایجِ تصویری
            # بر اساسِ تازگی (SerpAPI این را با tbs پشتیبانی می‌کند).
            "tbs": "qdr:y,sbd:1",
        }
        try:
            data = await self._serpapi_call(params)
        except Exception as e:
            self._last_error = f"serpapi: {e}"
            data = {}
        items = data.get("images_results") or []
        out = []
        for it in items:
            out.append({
                "title": it.get("title") or "",
                "image_url": it.get("original") or it.get("thumbnail") or "",
                "source_url": it.get("link") or it.get("source") or "",
                "source_name": it.get("source") or "",
                "width": it.get("original_width"),
                "height": it.get("original_height"),
                "provider": "serpapi",
            })
        if not out:
            self._log_failure("image_search_failure", query)
            return []
        return self._rank_and_dedupe(out, count)

    # ------------------------------------------------------------------
    # خبر (متن + منبع + تاریخ + لینکِ سایت + در صورتِ وجود عکس)
    # ------------------------------------------------------------------
    async def news_search(self, query: str, count: int = 4) -> list[dict]:
        self._last_error = None
        q = _strip_kind_words(query)
        params = {
            "engine": "google_news",
            "q": q,
            # جدیدترین‌ها بالا برای خبر.
            "tbs": "sbd:1",
        }
        try:
            data = await self._serpapi_call(params)
        except Exception as e:
            self._last_error = f"serpapi: {e}"
            data = {}
        items = (data.get("news_results") or [])
        out = []
        for it in items:
            # SerpAPI google_news گاهی نتایجِ تو در تو (highlight/stories) می‌دهد.
            if it.get("stories"):
                for st in it["stories"][:count]:
                    out.append(self._map_news_item(st))
            else:
                out.append(self._map_news_item(it))
            if len(out) >= count:
                break
        if not out:
            self._log_failure("news_search_failure", query)
            return []
        return out[:count]

    @staticmethod
    def _map_news_item(it: dict) -> dict:
        source = it.get("source") or {}
        if isinstance(source, dict):
            source_name = source.get("name", "")
        else:
            source_name = str(source)
        return {
            "title": it.get("title") or "",
            "snippet": it.get("snippet") or "",
            "source_url": it.get("link") or "",
            "source_name": source_name,
            "date": it.get("date") or "",
            "image_url": it.get("thumbnail") or "",
            "width": None,
            "height": None,
            "provider": "serpapi",
        }

    def _log_failure(self, event_type: str, query: str):
        try:
            db.add_system_log(
                log_type="WEB_SEARCH",
                event_type=event_type,
                severity="ERROR",
                message="جست‌وجویِ SerpAPI ناموفق بود یا هیچ کلیدی تنظیم نشده/سهمیه تمام شده",
                details={"query": query[:300], "last_error": self._last_error},
                status="failed",
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # نقطه‌ی ورودیِ واحد
    # ------------------------------------------------------------------
    async def search(self, query: str, count: int = 4) -> tuple[str, list[dict]]:
        """جست‌وجویِ یک‌مرحله‌ای: نوع را از متن تشخیص می‌دهد و نتیجه را برمی‌گرداند.
        خروجی: (kind, results) که kind یکی از 'image' یا 'news' است."""
        kind = detect_search_kind(query)
        if kind == "news":
            return "news", await self.news_search(query, count=count)
        return "image", await self.image_search(query, count=count)
