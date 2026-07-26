"""
تبدیل HTML خام صفحه‌ی پیش‌نمایش تلگرام (t.me/s/...) به HTML امن و مجاز
برای ارسال با parse_mode=HTML توی بات API.

این ماژول جایگزینِ منطق clean_post_text توی نسخه‌ی PHP هست، با این تفاوت
مهم که به‌جای گرفتن فقط متنِ خام، تگ‌های بولد/ایتالیک/زیرخط/خط‌خورده/کد/لینک
رو هم حفظ می‌کنه.
"""
from __future__ import annotations

import base64
import json
import re
from html import escape as _esc
import html as _html_mod
from html.parser import HTMLParser
from urllib.parse import quote as _url_quote

from bs4 import BeautifulSoup, NavigableString, Tag

_TAG_MAP = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code",
    "pre": "pre",
    "tg-spoiler": "tg-spoiler",
}

_EMOJI_CLASS = (
    r"[\U0001F1E6-\U0001F1FF"
    r"\U0001F100-\U0001F1FF"
    r"\U0001F200-\U0001F2FF"
    r"\U0001F300-\U0001FAFF"
    r"\u2600-\u27BF"
    r"\u2B00-\u2BFF"
    r"\u2300-\u23FF"
    r"\uFE0F\u200D]"
)
_EMOJI_SEQ = _EMOJI_CLASS + "+"

_GAP = r"(?:<[^>]+>|\s)*"

_URL_PATTERN = re.compile(
    r"(?:https?://\S+|www\.\S+|(?:t\.me|telegram\.me)/\S+)",
    flags=re.I,
)

_MARKER = "\x00__REMOVED__\x00"


# ==================== تغییرِ نامِ کانفیگ‌ها (پروکسی/فیلترشکن) ====================
# در لینکِ کانفیگ‌ها (vless/trojan/ss/...) هرچی بعد از # میاد، فقط «اسمِ نمایشی» است
# و هیچ نقشی در خودِ اتصال (آدرس/پورت/پارامترها) نداره. کانال‌های مبدأ معمولاً
# آدرسِ خودشون رو توی همین اسم می‌ذارن؛ برای همین وقتی کسی کانفیگ رو کپی می‌کنه و
# توی گوشیش می‌ذاره، اسمِ کانالِ مبدأ روی کانفیگ می‌مونه. اینجا فقط همین اسم (فرگمنتِ
# بعد از #، و برای vmess فیلدِ ps) به نامِ ثابتِ زیر عوض می‌شه؛ چون به بخشِ قبل از #
# دست نمی‌زنیم، کانفیگ هیچ‌وقت خراب نمی‌شه.
CONFIG_RENAME_TO = "@VFREEPN [🎯 جوین شو به منبع وصل شو]"

# اسکیم‌هایی که اسمِ کانفیگ رو به‌شکلِ فرگمنت (#name) در انتهای لینک نگه می‌دارن.
# به ترتیبِ طول (بلندتر اول) مرتب می‌شن تا مثلاً «ssr» قبل از «ss» و «hysteria2»
# قبل از «hy2» تطبیق داده بشه و نصفه‌match نشه.
_FRAGMENT_SCHEMES = sorted(
    [
        "vless", "trojan", "ssr", "ss", "hysteria2", "hysteria", "hy2", "hy",
        "tuic", "juicity", "naive+https", "naive", "socks5", "socks",
        "wireguard", "warp", "snell",
    ],
    key=len,
    reverse=True,
)

# یک توکنِ کاملِ لینکِ کانفیگ: از اسکیم تا اولین کاراکترِ مرزی. کاراکترهای مرزی
# (فاصله/تب/خطِ جدید و < > " ' `) یعنی جایی که لینک قطعاً تموم شده - چه لینکِ خام
# باشه، چه داخلِ href="..."، چه داخلِ متنِ نمایشیِ <a>...</a>. کاراکترِ # عمداً
# داخلِ توکن نگه داشته می‌شه تا فرگمنتِ فعلی هم گرفته و بازنویسی بشه.
# lookbehind: اسکیم نباید وسطِ یه کلمه‌ی دیگه match بشه. مثلاً «ss» نباید داخلِ
# «vmess://» گیر بیفته (که باعث می‌شد vmess دوباره و اشتباه پردازش بشه). با این
# لوک‌بی‌هایند فقط وقتی اسکیم match می‌شه که قبلش کاراکترِ مجازِ اسکیم (حرف/عدد/.+-_)
# نباشه - یعنی ابتدای متن، فاصله، خطِ جدید، " ' < > ( و... .
_CONFIG_URI_RE = re.compile(
    r"(?<![A-Za-z0-9._+\-])"
    r"(?P<scheme>(?:" + "|".join(re.escape(s) for s in _FRAGMENT_SCHEMES) + r"))://"
    r"(?P<rest>[^\s\"'<>`]*)",
    flags=re.I,
)

# vmess جداست چون اسمش داخلِ JSONِ base64 (فیلدِ ps) قرار داره، نه بعد از #.
_VMESS_URI_RE = re.compile(r"vmess://(?P<b64>[A-Za-z0-9+/=_\-]+)", flags=re.I)


def _encoded_config_name() -> str:
    # فرگمنت باید URL-encode بشه تا فاصله/پرانتز/ایموجی/حروفِ فارسی لینک رو نشکنن.
    # همه‌ی کلاینت‌های v2ray/xray موقعِ ایمپورت، فرگمنت رو URL-decode می‌کنن و اسمِ
    # کامل و درست رو نمایش می‌دن.
    return _url_quote(CONFIG_RENAME_TO, safe="")


def _rename_fragment_uri(m: "re.Match") -> str:
    scheme = m.group("scheme")
    rest = m.group("rest")
    base = rest.split("#", 1)[0]  # هرچی قبل از # هست عیناً حفظ می‌شه (آدرس/پارامترها)
    return f"{scheme}://{base}#{_encoded_config_name()}"


def _rename_vmess(m: "re.Match") -> str:
    raw = m.group("b64")
    try:
        s = raw.replace("-", "+").replace("_", "/")
        s += "=" * (-len(s) % 4)  # padding درست‌کردن (base64 با/بدون = و urlsafe)
        obj = json.loads(base64.b64decode(s).decode("utf-8"))
        if not isinstance(obj, dict) or "add" not in obj:
            return m.group(0)  # JSONِ vmess معتبر نیست → دست نمی‌زنیم
        obj["ps"] = CONFIG_RENAME_TO
        new_json = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        new_b64 = base64.b64encode(new_json.encode("utf-8")).decode("ascii")
        return "vmess://" + new_b64
    except Exception:  # noqa: BLE001 - اگه decode/parse نشد، کانفیگ رو دست‌نخورده می‌ذاریم
        return m.group(0)


def rename_configs_in_html(html_text: str) -> str:
    """اسمِ نمایشیِ همه‌ی کانفیگ‌ها/پروکسی‌های داخلِ متن رو به CONFIG_RENAME_TO عوض
    می‌کنه. فقط بخشِ اسم (فرگمنتِ بعد از # یا فیلدِ ps در vmess) تغییر می‌کنه؛ آدرس،
    پورت، sni، host و بقیه‌ی پارامترهای اتصال دست‌نخورده می‌مونن تا کانفیگ سالم بمونه.
    تابع idempotent است: اجرای دوباره روی متنی که قبلاً تغییر کرده، نتیجه رو عوض نمی‌کنه."""
    if not html_text:
        return html_text
    out = _CONFIG_URI_RE.sub(_rename_fragment_uri, html_text)
    out = _VMESS_URI_RE.sub(_rename_vmess, out)
    return out


# ==================== تغییرِ نامِ لینک‌هایی که متنِ نمایشی‌شون «آواکادوپروکسی» است ====================
# بعضی کانال‌های مبدأ به‌جای یک لینکِ پروکسیِ ساده با متنِ نمایشیِ «پروکسی»، از
# برندِ خودشون («آواکادوپروکسی») به‌عنوانِ متنِ لینک استفاده می‌کنن (گاهی همون
# لینک چندبار توی یک پست تکرار می‌شه). این تابع فقط *متنِ نمایشیِ* لینک‌هایی که
# دقیقاً کلمه‌ی «آواکادوپروکسی» هستن رو به «پروکسی» تغییر می‌ده؛ لینک/آدرسِ href
# دست‌نخورده می‌مونه. اگه بیش‌از یکی از این لینک‌ها توی همون پست باشه، به‌ترتیب
# شماره‌گذاری می‌شن: «پروکسی ۱»، «پروکسی ۲»، ... . اگه فقط یکی باشه، بدونِ شماره
# («پروکسی») باقی می‌مونه. لینک‌هایی که از قبل متنِ نمایشی‌شون «پروکسی» (یا هر
# چیزِ دیگه‌ای) بود، دست‌نخورده می‌مونن و مسیرِ عادیِ پست‌شدن رو طی می‌کنن.
AVOCADO_PROXY_LINK_TEXT = "آواکادوپروکسی"
PROXY_LINK_TEXT = "پروکسی"

# کاراکترهای نامرئی (zero-width) که ممکنه دورِ متنِ لینک باشن و نباید مانعِ
# تطبیقِ «دقیقاً همین کلمه» بشن.
_ZW_CHARS = "\u200b\u200c\u200d\ufeff\u2060"

# یک تگِ <a ...>...</a> کامل (بدونِ تگِ تودرتوی <a> دیگه - لینک‌ها توی HTML
# تلگرام تودرتو نمی‌شن، پس non-greedy کافیه).
_ANCHOR_TAG_RE = re.compile(r"(<a\b[^>]*>)(.*?)(</a>)", re.I | re.S)


_INNER_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _anchor_text_is_avocado_proxy(inner_html: str) -> bool:
    # متنِ داخلِ <a> ممکنه تگ‌های ساده (بولد/ایتالیک و...) هم داشته باشه؛ برای
    # تشخیصِ «دقیقاً همین کلمه» فقط متنِ خام (بدونِ تگ) و بدونِ کاراکترهای
    # نامرئی/فاصله‌ی اضافی مقایسه می‌شه.
    plain = _INNER_TAG_STRIP_RE.sub("", inner_html)
    plain = _html_mod.unescape(plain)
    for ch in _ZW_CHARS:
        plain = plain.replace(ch, "")
    return plain.strip() == AVOCADO_PROXY_LINK_TEXT


def rename_avocado_proxy_links_in_html(html_text: str) -> str:
    """متنِ نمایشیِ هر لینکی که دقیقاً «آواکادوپروکسی» است رو به «پروکسی» عوض
    می‌کنه؛ اگه چندتا از این لینک‌ها توی همون متن باشن، شماره‌گذاری می‌شن
    («پروکسی ۱»، «پروکسی ۲»، ...). لینک‌هایی که متنِ نمایشی‌شون از قبل چیزِ
    دیگه‌ای (مثلاً همون «پروکسی») بود، دست‌نخورده می‌مونن. تابع idempotent
    است: اجرای دوباره روی خروجیِ خودش (که دیگه متنش «آواکادوپروکسی» نیست)
    هیچ تغییرِ دیگه‌ای ایجاد نمی‌کنه."""
    if not html_text or AVOCADO_PROXY_LINK_TEXT not in html_text:
        return html_text

    matches = list(_ANCHOR_TAG_RE.finditer(html_text))
    target_count = sum(1 for m in matches if _anchor_text_is_avocado_proxy(m.group(2)))
    if not target_count:
        return html_text
    numbered = target_count > 1

    out: list[str] = []
    last_end = 0
    seen = 0
    for m in matches:
        out.append(html_text[last_end:m.start()])
        if _anchor_text_is_avocado_proxy(m.group(2)):
            seen += 1
            new_text = f"{PROXY_LINK_TEXT} {seen}" if numbered else PROXY_LINK_TEXT
            out.append(f"{m.group(1)}{new_text}{m.group(3)}")
        else:
            out.append(m.group(0))
        last_end = m.end()
    out.append(html_text[last_end:])
    return "".join(out)


def _strip_marker_with_adjacent_emoji(text: str, marker: str) -> str:
    lines = text.split("\n")
    before_re = re.compile(r"(" + _EMOJI_SEQ + r")(" + _GAP + r")$")
    after_re = re.compile(r"^(" + _GAP + r")(" + _EMOJI_SEQ + r")")
    out_lines = []
    for line in lines:
        while marker in line:
            idx = line.index(marker)
            before = line[:idx]
            after = line[idx + len(marker):]
            m_before = before_re.search(before)
            if m_before:
                before = before[: m_before.start()] + m_before.group(2)
            m_after = after_re.match(after)
            if m_after:
                after = m_after.group(1) + after[m_after.end():]
            line = before + after
        out_lines.append(line)
    return "\n".join(out_lines)


# ---------------------------------------------------------------------------
# حذفِ کاملِ خطی که منشن/لینکِ حذف‌شده داشته.
# ---------------------------------------------------------------------------
# وقتی کانالِ مبدأ آیدی/لینکِ خودش رو توی متن می‌ذاره (چه به‌شکلِ یک برچسبِ تنها
# مثلِ «📥 دانلود از : @Source»، چه وسطِ یک جمله مثلِ «برای اطلاعات بیشتر @Source
# رو ببینید»)، اگه فقط خودِ منشن/لینک پاک بشه، باقیِ جمله بی‌معنی و مسخره می‌مونه
# («برای اطلاعات بیشتر رو ببینید»). پس هر خطی که توش منشن/لینکِ حذف‌شده باشه
# (یعنی _MARKER داره) به‌طورِ کامل برداشته می‌شه.
#
# تنها استثنا: خط‌های کانفیگ/پروکسی (<code>/<pre> یا لینکِ خودِ کانفیگ مثلِ
# vless:// و tg://proxy). این‌ها خودِ محتوای اصلیِ پستن و هیچ‌وقت نباید حذف بشن؛
# اسمِ داخلِ کانفیگ جداگانه با rename_configs_in_html به نامِ ثابت عوض می‌شه.

# اسکیم‌هایِ «کانفیگ» (پروتکل‌های v2ray/xray و مشابه) در برابرِ اسکیم‌هایِ
# «پروکسی» (پروکسیِ نیتیوِ خودِ تلگرام/mtproto: tg://proxy، tg://socks،
# t.me/proxy، t.me/socks) جدا نگه داشته می‌شن تا کپشنِ پستِ نهایی بتونه بگه
# محتوایِ نگه‌داشته‌شده کدوم دسته‌ست (فقط کانفیگ، فقط پروکسی، یا هر دو).
# نکته: «socks://» به‌تنهایی (بدونِ tg:// یا t.me/) یک اسکیمِ کانفیگِ عمومیه
# (مثلِ دیگر پروتکل‌های v2ray)، نه پروکسیِ نیتیوِ تلگرام؛ برای همین توی
# گروهِ کانفیگه، نه گروهِ پروکسی.
_CONFIG_ONLY_SCHEME_RE = re.compile(
    r"(?:vless|vmess|trojan|ssr|ss|hysteria2|hysteria|hy2|hy|tuic|juicity|"
    r"naive\+https|naive|socks5|socks|wireguard|warp|snell|clash|sing-box)://",
    re.I,
)
_PROXY_ONLY_SCHEME_RE = re.compile(
    r"tg://(?:proxy|socks)"
    r"|t(?:elegram)?\.me/(?:proxy|socks)",
    re.I,
)

# مجموعِ هر دو - برایِ حفظِ رفتارِ قبلی (تشخیصِ خط/بلاکِ «کانفیگ یا پروکسی»)
# جایی که فرقی بینِ این دو لازم نیست (مثلاً کدامیک نگه داشته بشه).
_CONFIG_SCHEME_LINE_RE = re.compile(
    _CONFIG_ONLY_SCHEME_RE.pattern + r"|" + _PROXY_ONLY_SCHEME_RE.pattern, re.I
)


def _line_is_config(line: str) -> bool:
    low = line.lower()
    if "<code" in low or "<pre" in low:
        return True
    return bool(_CONFIG_SCHEME_LINE_RE.search(line))


# ==================== کپشنِ ثابت برای پست‌هایی که نقل‌قولِ کانفیگ/پروکسی دارن ====================
# وقتی پست یک نقل‌قول (blockquote) داره که خودش یک لینکِ کانفیگ/پروکسیِ خام
# (vless/vmess/trojan/ss/hysteria2/.../tg://proxy/t.me/proxy) توشه، کپشنِ
# کانالِ مبدأ (که هر بار فرق می‌کنه: «کانفیگ فیلترشکن»، «موقعیتِ سرور»،
# «وضعیت»، لینک/امضای تبلیغاتی و...) دیگه به کارمون نمی‌آد؛ به‌جاش یک کپشنِ
# ثابت گذاشته می‌شه که بسته به نوعِ محتوایِ نگه‌داشته‌شده فرق می‌کنه:
#   - هم کانفیگ هم پروکسی: 🔐 کانفیگ ها و پروکسی های رایگان جدید:
#   - فقط کانفیگ:            🚀 کانفینگ های رایگان جدید:
#   - فقط پروکسی:            📡 پروکسی های رایگان جدید:
# فقط نقل‌قول‌هایی که *خودشون* کانفیگ/پروکسی دارن نگه داشته می‌شن؛ هر چیزِ
# دیگه‌ای — چه متنِ بیرونِ نقل‌قول‌ها (بالا/پایین/وسط)، چه یک نقل‌قولِ دیگه که
# فقط متنِ ساده‌ست (مثلاً بعضی کانال‌های مبدأ حتی خودِ کپشن، مثلِ «New Config
# For iran : 🇩🇪»، رو هم داخلِ یک نقل‌قولِ جداگانه می‌ذارن) — کامل حذف می‌شه.
# فوترِ خودِ ربات (امضای کانالِ مقصد) بعداً با append_footer اضافه می‌شه و این
# تابع کاری باهاش نداره.
FIXED_CONFIG_CAPTION = "<b>🚀 کانفینگ های رایگان جدید:</b>"
FIXED_PROXY_CAPTION = "<b>📡 پروکسی های رایگان جدید:</b>"
FIXED_CONFIG_AND_PROXY_CAPTION = "<b>🔐 کانفیگ ها و پروکسی های رایگان جدید:</b>"

_BLOCKQUOTE_BLOCK_RE = re.compile(
    r"<blockquote(?:\s+expandable)?>.*?</blockquote>", re.I | re.S
)


def apply_fixed_config_caption(body_html: str) -> str:
    """اگه body_html حداقل یک نقل‌قول داشته باشه که خودش کانفیگ/پروکسی
    (vless/vmess/trojan/ss/hysteria2/.../tg://proxy/t.me/proxy) توشه، فقط
    همون نقل‌قول(های)ِ کانفیگ/پروکسی‌دار نگه داشته می‌شن و بقیه‌ی همه‌چیز —
    متنِ بیرونِ نقل‌قول‌ها و هر نقل‌قولِ دیگه‌ای که کانفیگ/پروکسی نداره
    (نقل‌قولِ متنیِ ساده) — حذف می‌شه؛ به‌جاش یکی از سه کپشنِ ثابتِ بالا (بسته
    به این‌که نقل‌قول‌هایِ نگه‌داشته‌شده کانفیگ دارن، پروکسی دارن، یا هر دو) با
    یک خطِ خالی قبلِ اولین نقل‌قولِ باقی‌مانده گذاشته می‌شه. اگه پست اصلاً
    نقل‌قول نداشته باشه، یا هیچ‌کدوم از نقل‌قول‌هاش کانفیگ/پروکسی نداشته
    باشن، بدونِ تغییر برمی‌گرده — این تابع idempotent است (اجرای دوباره روی
    خروجیِ خودش نتیجه رو عوض نمی‌کنه، چون خروجی همیشه با یکی از کپشن‌های ثابت
    شروع می‌شه و بلافاصله فقط همون نقل‌قول‌های کانفیگ/پروکسی‌دار رو داره)."""
    if not body_html or "<blockquote" not in body_html.lower():
        return body_html
    blocks = list(_BLOCKQUOTE_BLOCK_RE.finditer(body_html))
    if not blocks:
        return body_html
    config_blocks = [m.group(0) for m in blocks if _CONFIG_SCHEME_LINE_RE.search(m.group(0))]
    if not config_blocks:
        return body_html

    has_config = any(_CONFIG_ONLY_SCHEME_RE.search(b) for b in config_blocks)
    has_proxy = any(_PROXY_ONLY_SCHEME_RE.search(b) for b in config_blocks)
    if has_config and has_proxy:
        caption = FIXED_CONFIG_AND_PROXY_CAPTION
    elif has_proxy:
        caption = FIXED_PROXY_CAPTION
    else:
        caption = FIXED_CONFIG_CAPTION

    quotes_html = "\n".join(config_blocks)
    return f"{caption}\n\n{quotes_html}"


_STRUCT_TAG_RE = re.compile(r"</?(?:blockquote|pre|code)\b", re.I)

# بلاک‌کوت/pre/code یی که بعدِ حذفِ متنِ داخلش (چون کلِ خط منشن/جمله‌ی
# بی‌ربط بود) کاملاً خالی مونده - یعنی فقط تگِ باز بلافاصله با تگِ بسته‌ی خودش
# جفت شده - هیچ فایده‌ای نداره و باید کاملاً پاک بشه؛ وگرنه یک نقل‌قولِ خالی و
# بی‌معنی (یا یک خطِ خالیِ عجیب) توی پستِ نهایی می‌مونه.
_EMPTY_STRUCTURAL_RE = re.compile(
    r"<blockquote(?:\s+expandable)?>\s*</blockquote>"
    r"|<pre(?:\s+[^>]*)?>\s*</pre>"
    r"|<code(?:\s+[^>]*)?>\s*</code>",
    re.I | re.S,
)


def _drop_empty_structural_blocks(text: str) -> str:
    """بلاک‌کوت/pre/code هایی که بعدِ حذفِ خط/جمله‌ی داخلشون کاملاً خالی موندن
    رو کامل برمی‌داره (نه فقط محتواشون رو) - تا نقل‌قولِ خالی/بی‌معنی جا نمونه.
    حلقه‌ای اجرا می‌شه چون گاهی حذفِ یک بلاکِ خالی، بلاکِ اطرافش رو هم خالی
    می‌کنه (نادره ولی محضِ اطمینان)."""
    if "<" not in text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _EMPTY_STRUCTURAL_RE.sub("", text)
    return text


def _drop_removed_link_lines(text: str, marker: str) -> str:
    """هر خطی که منشن/لینکِ حذف‌شده داشته باشه رو *کامل* برمی‌داره (نه فقط خودِ
    منشن/لینک رو)، تا جمله‌ی نصفه و بی‌معنی به‌جا نمونه. خط‌های کانفیگ/پروکسی
    استثنان و حفظ می‌شن. خط‌هایی که اصلاً منشن/لینکِ حذف‌شده نداشتن دست‌نخورده
    می‌مونن، پس محتوای واقعیِ پست از بین نمی‌ره.

    خطی که تگِ ساختاری (blockquote/pre/code) هم داشته باشه *هم* از این قاعده
    مستثنا نیست: کلِ متنِ خط حذف می‌شه، ولی خودِ تگ‌های ساختاری برای حفظِ
    توازنِ HTML نگه داشته می‌شن. اگه این کار یک بلاکِ کاملاً خالی به‌جا بذاره
    (مثلاً نقل‌قولی که تنها محتواش همون جمله/منشنِ حذف‌شده بود)، آخرِ کار با
    _drop_empty_structural_blocks پاک می‌شه - وگرنه یک نقل‌قولِ خالی و بی‌معنی
    جا می‌موند.

    نکته‌ی مهمِ توازنِ تگ: وقتی یک خط حذف می‌شه، *تگ‌های HTMLش* (مثلِ </b> که ممکنه
    بولدِ چندخطی رو ببنده، یا <i> و...) نباید گم بشن؛ وگرنه یک تگِ باز و بی‌جفت
    به‌جا می‌مونه و تلگرام کلِ پیام رو با خطای «can't find end tag» رد می‌کنه.
    پس فقط *متنِ* خط حذف می‌شه و تگ‌هاش به تهِ خطِ قبلی می‌چسبن تا توازن دقیقاً
    مثلِ قبل بمونه و بولد/ایتالیک هم بی‌جهت پخش نشه."""
    out_lines: list[str] = []
    for line in text.split("\n"):
        if marker in line and not _line_is_config(line):
            # متنِ خط حذف می‌شه ولی تگ‌های HTMLش برای حفظِ توازن نگه داشته می‌شن.
            tags = "".join(re.findall(r"</?[a-zA-Z][^>]*>", line))
            if tags:
                if out_lines:
                    out_lines[-1] += tags
                else:
                    out_lines.append(tags)
            continue  # متنِ این خط به‌خاطرِ منشن/لینکِ حذف‌شده برداشته می‌شه
        out_lines.append(line)
    return _drop_empty_structural_blocks("\n".join(out_lines))


# ==================== پاکسازیِ کپشنِ کانال‌های Netmod (.nm) / Npv Tunnel (.npvt) ====================
# بعضی کانال‌های مبدأ (مثلِ «اینترنت آزاد») فایل‌های .nm و .npvt رو با یک کپشنِ
# استانداردِ تکراری می‌فرستن که شاملِ: یک خطِ توضیحی (با ایموجیِ 📱)، یک یا دو
# خطِ «نحوه‌ی اتصال داخل ویندوز/اندروید/آیفون ... کلیک کن»، شعارِ «اینترنت آزاد
# برای همه, یا هیچکس»، و یک نقل‌قولِ تبلیغاتیِ رباتِ خودشون («برای دریافت کانفیگ
# نت ملی کلیک کن @...») هست. این دو تابع این خط‌ها رو کامل حذف می‌کنن و خطِ
# توضیحیِ 📱 رو با یک کپشنِ ثابتِ استاندارد‌شده (بسته به پسوندِ فایل) جایگزین
# می‌کنن. هر دو فقط وقتی صدا زده می‌شن که تاگلِ اختصاصیِ
# «vpn_howto_cleanup_enabled» برای کانالِ مبدأ روشن باشه (نگاه کن به
# OVERRIDABLE_TOGGLES در database.py) - پس هیچ کانالِ دیگه‌ای تحتِ تاثیر قرار
# نمی‌گیره مگر این‌که ادمین صراحتاً از منویِ کانال فعالش کنه.
_VPN_HOWTO_LINE_RE = re.compile(r"نحوه[‌\s]*ی?\s*اتصال\s*داخل", re.I)
_VPN_SLOGAN_LINE_RE = re.compile(r"اینترنت\s*آزاد\s*برای", re.I)


def _line_has_vpn_source_boilerplate(line: str) -> bool:
    plain = _visible_text(line)
    if not plain:
        return False
    if _VPN_HOWTO_LINE_RE.search(plain):
        return True
    if _VPN_SLOGAN_LINE_RE.search(plain):
        return True
    if "برای دریافت" in plain and "کلیک کن" in plain:
        return True
    return False


_VPN_STRUCT_KEEP_TAG_RE = re.compile(r"</?(?:blockquote|pre)\b[^>]*>", re.I)


def strip_vpn_source_boilerplate(html_text: str) -> str:
    """حذفِ کاملِ خط‌های «نحوه اتصال داخل ...»، «اینترنت آزاد برای همه/هیچکس» و
    نقل‌قولِ «برای دریافت ... کلیک کن». مشابهِ _drop_removed_link_lines، *متنِ*
    خط برداشته می‌شه؛ ولی برخلافِ اون تابع، فقط تگ‌های *ساختاری* (blockquote/pre -
    که اگه گم بشن نقل‌قول/بلاک رو می‌شکنن) به تهِ خطِ قبل منتقل می‌شن. تگ‌های
    اینلاین مثلِ <a>...</a> (که معمولاً دقیقاً همون «کلیک کن»یِ لینک‌دارِ داخلِ
    این خط‌هان) عمداً به‌طورِ کامل دور ریخته می‌شن - وگرنه یک <a href="..."></a>
    خالی و بی‌فایده جا می‌مونه. خط‌های کانفیگ/پروکسی هیچ‌وقت حذف نمی‌شن."""
    if not html_text:
        return html_text
    out_lines: list[str] = []
    for line in html_text.split("\n"):
        if not _line_is_config(line) and _line_has_vpn_source_boilerplate(line):
            struct_tags = "".join(_VPN_STRUCT_KEEP_TAG_RE.findall(line))
            if struct_tags:
                if out_lines:
                    out_lines[-1] += struct_tags
                else:
                    out_lines.append(struct_tags)
            continue
        out_lines.append(line)
    out = "\n".join(out_lines)
    # اگه نگه‌داشتنِ تگ‌های ساختاری یک نقل‌قول/pre کاملاً خالی به‌جا گذاشته
    # (مثلاً نقل‌قولی که تنها محتواش همون جمله‌ی حذف‌شده بود)، خودِ تگ‌ها هم
    # پاک می‌شن - وگرنه یک نقل‌قولِ خالی و بی‌معنی توی پستِ نهایی می‌مونه.
    out = _drop_empty_structural_blocks(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip("\n")


NETMOD_FIXED_CAPTION = (
    "<b>📱 کانفیگ Netmod اختصاصی ویندوز و اندروید برای تمومی اپراتور ها نامحدود "
    "آیپی ثابت پرسرعت مخصوص دانلود وب گردی</b>"
)
NPVTUNNEL_FIXED_CAPTION = (
    "<b>📱 کانفیگ فول پرسرعت برای نت ملی Npv Tunnel مخصوص دانلود وب گردی نامحدود "
    "برای اندروید و آیفون</b>"
)


def _vpn_source_extension(media: list) -> str:
    """پسوندِ فایلِ Netmod/Npv Tunnel رو از رویِ لیستِ مدیایِ پست تشخیص می‌ده.
    برمی‌گردونه: "nm"، "npvt" یا رشته‌ی خالی (اگه هیچ‌کدوم نبود). چون
    filenameِ اسکرِیپ‌شده معمولاً «عنوان + زیرنویسِ حجم/نوع» به‌هم‌چسبیده‌ست
    (مثلاً «Windows🇺🇸.nm 737 B NM»، نه صرفاً یک نامِ فایلِ تمیز)، مثلِ
    ad_filter.blocked_file هم پسوندِ بعدِ آخرین نقطه و هم توکن‌های مستقلِ
    الفبایی-عددیِ داخلِ رشته رو چک می‌کنیم."""
    for m in media or []:
        if getattr(m, "type", "") != "document":
            continue
        name = (getattr(m, "filename", "") or getattr(m, "url", "") or "").strip().lower()
        if not name:
            continue
        suffix_ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if suffix_ext == "npvt" or suffix_ext == "nm":
            return suffix_ext
        tokens = set(re.findall(r"[a-z0-9]+", name))
        if "npvt" in tokens:
            return "npvt"
        if "nm" in tokens:
            return "nm"
    return ""


def apply_netmod_npvtunnel_caption(body_html: str, media: list) -> str:
    """اگه پست شاملِ فایلی با پسوندِ .nm یا .npvt باشه، اولین خطِ غیرخالیِ کپشن
    (خطِ توضیحیِ کانالِ مبدأ - چه با ایموجیِ 📱 شروع بشه چه 📥 یا هرچیزِ دیگه؛
    ایموجیِ سرِخط بینِ پست‌های این کانال ثابت نیست) با کپشنِ ثابتِ استاندارد‌شده
    جایگزین می‌شه. اگه کپشن کاملاً خالی بود (مثلاً بعدِ حذفِ خط‌های راهنما چیزی
    نموند)، کپشنِ ثابت تنها محتوای کپشن می‌شه. اگه پست فایلِ Netmod/Npv Tunnel
    نداشته باشه، بدونِ تغییر برمی‌گرده."""
    ext = _vpn_source_extension(media)
    if not ext:
        return body_html
    fixed = NETMOD_FIXED_CAPTION if ext == "nm" else NPVTUNNEL_FIXED_CAPTION

    lines = (body_html or "").split("\n")
    for i, line in enumerate(lines):
        if _visible_text(line):
            lines[i] = fixed
            return "\n".join(lines)
    return fixed


_MENTION_ONLY_RE = re.compile(r"^@[A-Za-z0-9_]{3,}$")

_IRAN_PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"(?:\+98|0098|98)[\s\-]?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}"
    r"|0?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}"
    r"|0[1-8]\d[\s\-]?\d{3,4}[\s\-]?\d{4}"
    r")(?!\d)"
)

_HREF_LINK_RE = re.compile(
    r"^(?:https?://|www\.|tg://resolve|(?:t\.me|telegram\.me)/)",
    flags=re.I,
)

# لینک‌های پروکسیِ تلگرام (mtproto) - چه به‌شکلِ t.me/proxy?... چه tg://proxy یا
# tg://socks - نباید هیچ‌وقت به‌عنوانِ «لینکِ کانالِ مبدأ» حذف بشن، چون خودِ
# محتوای موردنیازِ کاربرن (کانفیگِ اتصال)، نه تبلیغِ کانال. طبقِ درخواستِ کاربر،
# هر لینکی که کلمه‌ی proxy توش باشه (به‌هر شکل: مسیر، دامنه، پارامتر) از این
# فیلتر معاف می‌شه.
_PROXY_LINK_RE = re.compile(r"proxy", flags=re.I)


def _is_proxy_link(url_or_text: str) -> bool:
    return bool(_PROXY_LINK_RE.search(url_or_text or ""))


def _href_is_removable_link(href: str) -> bool:
    href = (href or "").strip()
    if not href:
        return False
    if _is_proxy_link(href):
        return False
    return bool(_HREF_LINK_RE.match(href))


def _is_bare_address_text(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if _is_proxy_link(text):
        return False
    return bool(_URL_PATTERN.fullmatch(text)) or bool(_MENTION_ONLY_RE.fullmatch(text))


def _is_self_link(href: str, self_username: str) -> bool:
    if not href or not self_username:
        return False
    href = href.strip()
    target = re.escape(self_username)
    if re.search(rf"t\.me/(s/)?{target}(?:[/?#].*)?$", href, flags=re.I):
        return True
    if re.search(rf"tg://resolve\?domain={target}(?:&.*)?$", href, flags=re.I):
        return True
    return False


def _clean_text_run(raw: str, self_username: str, remove_self_links: bool) -> str:
    if not remove_self_links:
        return raw

    if self_username:
        target = re.escape(self_username)
        raw = re.sub(rf"@{target}\b", _MARKER, raw, flags=re.I)
        raw = re.sub(rf"(https?://)?t\.me/(s/)?{target}(\S*)?", _MARKER, raw, flags=re.I)

    raw = _URL_PATTERN.sub(lambda m: m.group(0) if _is_proxy_link(m.group(0)) else _MARKER, raw)
    raw = _IRAN_PHONE_RE.sub("", raw)
    return raw


def node_to_telegram_html(node: Tag, self_username: str = "", remove_self_links: bool = True) -> str:
    out = []
    for child in node.children:
        if isinstance(child, NavigableString):
            cleaned = _clean_text_run(str(child), self_username, remove_self_links)
            out.append(_esc(cleaned))
            continue
        if not isinstance(child, Tag):
            continue

        tag = child.name.lower()

        if tag == "br":
            out.append("\n")
            continue

        if tag == "a":
            href = child.get("href", "")
            if remove_self_links and (
                _is_self_link(href, self_username)
                or _href_is_removable_link(href)
                or _is_bare_address_text(child.get_text())
            ):
                out.append(_MARKER)
                continue
            inner = node_to_telegram_html(child, self_username, remove_self_links)
            if href and inner.strip():
                out.append(f'<a href="{_esc(href, quote=True)}">{inner}</a>')
            else:
                out.append(inner)
            continue

        if tag == "span" and "tg-spoiler" in (child.get("class") or []):
            inner = node_to_telegram_html(child, self_username, remove_self_links)
            out.append(f"<tg-spoiler>{inner}</tg-spoiler>")
            continue

        if tag == "tg-emoji":
            # ایموجیِ پرمیوم (سفارشی). صفحه‌ی پیش‌نمایشِ تلگرام آیدیِ ایموجی رو
            # روی همین تگ می‌ذاره (emoji-id / data-emoji-id / data-document-id).
            # آیدی رو حفظ می‌کنیم تا در صورتِ فعال‌بودنِ گزینه‌ی «ایموجیِ پرمیوم»،
            # پستِ مقصد هم با همون ایموجیِ پرمیوم ارسال بشه. اگه آیدی نبود، فقط
            # ایموجیِ سادهٔ جایگزین (متن) خروجی می‌شه.
            emoji_id = (
                child.get("emoji-id")
                or child.get("data-emoji-id")
                or child.get("data-document-id")
                or child.get("data-custom-emoji-id")
            )
            inner = _esc(child.get_text())
            if emoji_id and str(emoji_id).strip().isdigit() and inner.strip():
                out.append(f'<tg-emoji emoji-id="{_esc(str(emoji_id).strip(), quote=True)}">{inner}</tg-emoji>')
            else:
                out.append(inner)
            continue

        if tag == "blockquote":
            # حفظِ نقل‌قول (نقلِ متن) موقعِ انتقال. تلگرام هم <blockquote> و هم
            # <blockquote expandable> رو در parse_mode=HTML پشتیبانی می‌کنه. اگه
            # نقل‌قولِ منبع «قابل‌گسترش» بود، همون حالت حفظ می‌شه.
            inner = node_to_telegram_html(child, self_username, remove_self_links)
            if inner.strip():
                classes = " ".join(child.get("class") or []).lower()
                expandable = "expandable" in classes or child.has_attr("expandable")
                open_tag = "<blockquote expandable>" if expandable else "<blockquote>"
                # نقل‌قول یک عنصرِ بلوکیه؛ با خطِ جدید از قبل/بعدش جدا می‌شه تا (۱)
                # منشن/امضای بعدِ نقل‌قول روی خطِ جداگانه بیفته و حذفش کلِ نقل‌قول
                # رو نبره، و (۲) دو نقل‌قولِ پشتِ‌سرهم چسبیده و یکی‌شده نشن.
                out.append(f"\n{open_tag}{inner}</blockquote>\n")
            continue

        if tag in _TAG_MAP:
            mapped = _TAG_MAP[tag]
            inner = node_to_telegram_html(child, self_username, remove_self_links)
            out.append(f"<{mapped}>{inner}</{mapped}>")
            continue

        out.append(node_to_telegram_html(child, self_username, remove_self_links))

    return "".join(out)


def clean_post_html(text_node: Tag, self_username: str, remove_self_links: bool = True) -> str:
    html_text = node_to_telegram_html(text_node, self_username, remove_self_links)

    # اول خطِ کاملی که منشن/لینکِ حذف‌شده داشته رو بردار (تا جمله‌ی نصفه نمونه)،
    # بعد بقیه‌ی مارکرها (که فقط توی خطِ کانفیگ باقی موندن) رو پاک کن.
    html_text = _drop_removed_link_lines(html_text, _MARKER)
    html_text = _strip_marker_with_adjacent_emoji(html_text, _MARKER)

    # فاصله‌های داخلیِ متن (مثلِ ستون‌بندیِ «🕰 17:22   📇 1405/04/26») و توفرورفتگیِ
    # ابتدای خط عمداً دست‌نخورده می‌مونن تا چیدمان/استایلِ اصلیِ پست حفظ بشه؛
    # تلگرام فاصله‌های چندتایی رو نگه می‌داره، پس جمع‌کردنشون یعنی خراب‌کردنِ ظاهر.
    # فقط فاصله‌ی *آخرِ* خط (که نامرئیه) و خطِ خالیِ اضافه پاک می‌شن.
    html_text = re.sub(r"[ \t]+\n", "\n", html_text)
    html_text = re.sub(r"\n{2,}", "\n\n", html_text)

    # توفرورفتگیِ ابتدای خط رو بردار (فاصله‌های اولِ خط، برخلافِ فاصله‌های داخلی،
    # فقط باعثِ پهن‌شدنِ بیخودِ عرضِ پیام می‌شن و چیزی از استایل رو حفظ نمی‌کنن).
    html_text = re.sub(r"\n[ \t]+", "\n", html_text)

    # فاصله‌ی چسبیده به تگِ نقل‌قول رو هم بردار. خطِ *اولِ* داخلِ بلاک‌کوت (بلافاصله
    # بعدِ <blockquote>) با الگوی «\n + فاصله» گرفته نمی‌شه، پس فاصله‌ی ابتدایی‌اش
    # می‌مونه. در حالتِ راست‌به‌چپ این فاصله‌ها می‌رن سمتِ راست و متنِ نقل‌قول رو هل
    # می‌دن چپ (به‌نظر می‌رسه راست‌چین نیست و سمتِ راست خالیه). با این‌کار همه‌ی
    # خط‌های نقل‌قول یک‌دست به لبه‌ی راست می‌چسبن.
    html_text = re.sub(r"(<blockquote(?:\s+expandable)?>)[ \t]+", r"\1", html_text)
    html_text = re.sub(r"[ \t]+(</blockquote>)", r"\1", html_text)

    # بینِ دو نقل‌قولِ پشتِ‌سرهم دقیقاً یک خطِ جدید باشه (نه خطِ خالی، نه هیچی):
    #  - اگه هیچ فاصله‌ای نباشه، هر دو کوت روی یک خط می‌افتن و کوتِ دوم RLMِ خودشو
    #    نمی‌گیره و چپ می‌افته.
    #  - اگه خطِ خالی (\n\n) باشه، یک فاصله‌ی زشتِ اضافه وسطشون می‌افته.
    # پس یک \n: هر کوت خطِ خودشو داره (هر دو راست‌چین می‌شن) و کمترین فاصله‌ی ممکنه،
    # دقیقاً مثلِ کانالِ مبدأ.
    html_text = re.sub(
        r"</blockquote>[ \t\n]*<blockquote", "</blockquote>\n<blockquote", html_text
    )

    # نکته: بلاک‌کوتِ «قابل‌گسترش» با اتریبیوت expandable باز می‌شه
    # (<blockquote expandable>) نه فقط <blockquote>، پس باید اون اتریبیوتِ
    # اختیاری رو هم توی الگو پوشش بدیم؛ وگرنه یک بلاک‌کوتِ خالی (که مثلاً
    # فقط لینکِ خودِ کانال توش بوده و بعداً حذف شده) به‌صورتِ یک دکمه‌ی
    # نقل‌قولِ خالی و بی‌مصرف توی پیامِ نهایی باقی می‌مونه.
    # کاراکترهای نامرئی (zero-width) که ممکنه بعدِ حذفِ لینک/مارکر ته‌نشین
    # بشن و باعث بشن تگ به‌ظاهر «خالی» با \s معمولی تشخیص داده نشه.
    _ZW = "\u200b\u200c\u200d\ufeff\u2060"
    html_text = re.sub(f"[{_ZW}]+", "", html_text)

    empty_tag_re = re.compile(
        r"<(b|i|u|s|code|pre|tg-spoiler|blockquote)(?:\s+[^>]*)?>\s*</\1>"
    )
    while True:
        new_text = empty_tag_re.sub("", html_text)
        if new_text == html_text:
            break
        html_text = new_text

    html_text = re.sub(r"[ \t]+\n", "\n", html_text)
    html_text = re.sub(r"\n{3,}", "\n\n", html_text)

    html_text = html_text.strip()

    # تورِ ایمنیِ نهایی: اگه بعدِ همه‌ی پاک‌سازی‌ها هنوز یک تگِ بازِ بی‌جفت مونده
    # باشه (مثلاً بولد/ایتالیکی که بستنش روی خطِ حذف‌شده بوده)، اینجا بسته می‌شه؛
    # وگرنه تلگرام کلِ پیام رو با «can't find end tag» یا «unexpected end tag» رد
    # می‌کنه. اگه از قبل متوازن باشه، این کار چیزی رو عوض نمی‌کنه.
    html_text = _balance_html(html_text)
    return html_text


def strip_html_tags(html_text: str) -> str:
    return BeautifulSoup(html_text, "html.parser").get_text()


def strip_tatweel(text: str) -> str:
    """حذفِ کاراکترِ «کشیده/تطویل» (ـ، U+0640) از متن. این کاراکتر فقط حروف رو
    کشیده نشون می‌ده و معنای متن رو عوض نمی‌کنه، پس حذفش امنه."""
    if not text:
        return text
    return text.replace("\u0640", "")


# حروفِ راست‌به‌چپ (فارسی/عربی/عبری و فرم‌های نمایشی‌شون). فقط خط‌هایی که *حرفِ*
# راست‌به‌چپ دارن راست‌چین اجباری می‌شن؛ خط‌هایی که فقط عدد/ایموجی/لاتین/علامت‌ان
# (مثلِ سطرِ «🕰 17:22   📇 1405/04/26») دست‌نخورده می‌مونن تا چیدمانِ اصلیِ پست
# (جای ساعت/تاریخ، ستون‌بندی و...) با اجبارِ جهت به‌هم نریزه.
_HAS_RTL_CHAR_RE = re.compile(
    r"[\u0590-\u05FF\u0600-\u06FF\u0700-\u074F\u0750-\u077F\u08A0-\u08FF"
    r"\uFB1D-\uFDFF\uFE70-\uFEFF]"
)


class _RTLLineMarker(HTMLParser):
    """اولِ هر خطی که *حرفِ فارسی/عربی* داره یک RLM (U+200F) می‌ذاره تا حتی اگه
    خط با ایموجی/پرچم/عدد شروع بشه، درست راست‌چین دیده بشه.

    خط‌هایی که هیچ حرفِ راست‌به‌چپی ندارن (فقط عدد/ایموجی/لاتین، مثلِ سطرِ ساعت و
    تاریخ) عمداً دست‌نخورده می‌مونن؛ چون اجبارِ جهت روی این خط‌ها ترتیبِ بصریِ
    اجزا رو جابه‌جا می‌کنه (مثلاً جای ساعت و تاریخ عوض می‌شه) و استایلِ اصلیِ پست
    از بین می‌ره. داخلِ <code>/<pre> هم چیزی اضافه نمی‌شه تا کپیِ کانفیگ سالم بمونه.

    تصمیم برای هر خط بعد از دیدنِ کلِ خط گرفته می‌شه (خط بافر می‌شه و موقعِ رسیدن
    به \\n یا انتها با/بی RLM آزاد می‌شه). تابع idempotent است: خطی که از قبل با
    RLM شروع شده، دوباره مارک نمی‌شه."""

    # داخلِ این تگ‌ها RLM اضافه نمی‌شه:
    #  - code/pre: کانفیگِ قابلِ کپی نباید نویسه‌ی نامرئی بگیره.
    # نکته: بلاک‌کوت *عمداً* اینجا نیست. نسخه‌ی قدیمی و سالمِ ربات هم داخلِ نقل‌قول
    # RLM می‌ذاشت (بعدِ تگِ باز، قبلِ متن) و همین باعثِ راست‌چینیِ درستِ متنِ نقل‌قول
    # می‌شد. اگه بلاک‌کوت رو اینجا بذاریم، متنِ نقل‌قول چپ می‌افته (فضای راستش خالی).
    _SKIP_TAGS = {"code", "pre"}
    _RLM = "\u200f"
    # نشانگرِ راست‌چینی = RLM (U+200F)، که کلاسِ bidiش «R» (قویِ راست‌به‌چپ) است و
    # تلگرام آن را به‌عنوانِ اولین نویسه‌ی قویِ خط می‌بیند و خط را راست‌چین می‌کند —
    # حتی اگر خط با ایموجی/پرچم/عدد شروع شده باشد.
    # ⚠️ چرا RLE+PDF نه: کلاسِ bidiِ RLE برابرِ «RLE» است (نه R/AL)؛ تلگرام برای
    # تصمیمِ *راست‌چینی* دنبالِ اولین نویسه با کلاسِ R/AL می‌گردد و RLE را به حساب
    # نمی‌آورد، پس خط چپ می‌افتاد — حتی خطی که با حرفِ فارسی شروع شده بود (چون RLE
    # حالا در ابتدای خط می‌نشست). RLM نشانگرِ مستقل است و به closer/PDF نیاز ندارد.
    _RLE = "\u202b"
    _PDF = "\u202c"

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip_depth = 0
        self._reset_line()

    def _reset_line(self):
        self.line_parts: list[str] = []
        self.line_text: list[str] = []
        self.first_text_in_skip: bool | None = None  # اولین متنِ خط داخلِ code/pre بود؟

    def _note_text(self, visible: str):
        if visible == "":
            return
        if self.first_text_in_skip is None:
            self.first_text_in_skip = self.skip_depth > 0
        self.line_text.append(visible)

    _BQ_OPEN_RE = re.compile(r"^(<blockquote(?:\s+expandable)?>)", re.I)
    # آیا اولین نویسه‌ی معنادارِ متن، خودش حرفِ راست‌به‌چپه؟ (نشانگرهای نامرئی و
    # فاصله رد می‌شن) اگه آره، خط به‌طورِ طبیعی راست‌چین می‌شه و RLM کافیه.
    _LEADING_RTL_RE = re.compile(
        r"^[\s\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]*"
        r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]"
    )
    _BQ_CLOSE_TAIL_RE = re.compile(r"(</blockquote>)\s*$", re.I)

    def _flush_line(self, newline: bool):
        line = "".join(self.line_parts)
        text = "".join(self.line_text)
        # نشانگر دقیقاً کجا درج می‌شه؟ اولِ خط، یا داخلِ نقل‌قول بعدِ تگِ باز.
        _bq = self._BQ_OPEN_RE.match(line)
        insert_at = _bq.end() if _bq else 0
        # اگه همون‌جا از قبل نشانگر هست، دوباره اضافه نکن. (نگهبانِ قبلی فقط دو
        # نویسه‌ی اولِ خط رو نگاه می‌کرد و برای خطِ نقل‌قول - که نشانگرش بعدِ تگِ
        # بازه - کار نمی‌کرد؛ نتیجه‌ش نشانگرِ تکراری موقعِ پردازشِ دوباره بود.)
        already_marked = line[insert_at:insert_at + 1] in (self._RLM, self._RLE)
        need_rlm = (
            self.first_text_in_skip is False
            and bool(_HAS_RTL_CHAR_RE.search(text))
            and not already_marked
        )
        if need_rlm:
            # RLM روی *همه‌ی* خط‌هایی که حرفِ فارسی/عربی دارن گذاشته می‌شه (نه فقط
            # اونایی که با ایموجی شروع می‌شن)، تا مثلِ کانالِ مبدأ راست‌چین دیده بشن.
            # RLM فقط «جهتِ پایه‌ی خط» رو راست‌به‌چپ می‌کنه؛ ترتیبِ داخلیِ اجزا
            # (کلمه‌ی لاتین، عدد، ایموجی) همون چیزی می‌مونه که یک خطِ طبیعیِ فارسی
            # داره — پس چیدمانِ پست به‌هم نمی‌ریزه.
            marker = self._RLM
            if _bq:
                # نشانگر رو داخلِ نقل‌قول (بعدِ تگِ باز) بذار، نه قبلش؛ وگرنه یک نویسه‌ی
                # نامرئی بیرونِ بلاک‌کوت می‌مونه و ممکنه یک خطِ خالیِ اضافه بسازه.
                line = line[:insert_at] + marker + line[insert_at:]
            else:
                line = marker + line
        self.out.append(line)
        if newline:
            self.out.append("\n")
        self._reset_line()

    def handle_starttag(self, tag, attrs):
        attr_str = "".join(
            f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs
        )
        self.line_parts.append(f"<{tag}{attr_str}>")
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1

    def handle_startendtag(self, tag, attrs):
        attr_str = "".join(
            f' {k}="{v}"' if v is not None else f" {k}" for k, v in attrs
        )
        self.line_parts.append(f"<{tag}{attr_str}/>")

    def handle_endtag(self, tag):
        self.line_parts.append(f"</{tag}>")
        if tag in self._SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        parts = data.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                self._flush_line(newline=True)
            if part:
                self.line_parts.append(part)
                self._note_text(part)

    def handle_entityref(self, name):
        self.line_parts.append(f"&{name};")
        self._note_text(_html_mod.unescape(f"&{name};"))

    def handle_charref(self, name):
        self.line_parts.append(f"&#{name};")
        try:
            n = int(name[1:], 16) if name[:1] in ("x", "X") else int(name)
            self._note_text(chr(n))
        except (ValueError, OverflowError):
            pass

    def close(self):
        super().close()
        self._flush_line(newline=False)


# پرچمِ کشورها (regional indicator symbols) در یونیکد «چپ‌به‌راست» (strong-L) هستند،
# برخلافِ ایموجیِ خنثی مثلِ 👑/📍/🔌. برای همین خطی که پرچم *قبل از* متنِ فارسی‌اش
# باشد، در تلگرام چپ‌چین می‌شود — حتی با RLM یا خطِ خالی، چون کلاینت جهتِ خط را از
# اولین نویسه‌ی «قوی» می‌گیرد و آن نویسه پرچمِ چپ‌به‌راست است. راه‌حلِ مطمئن: *هر*
# پرچمی که قبل از اولین حرفِ فارسی/عربیِ خط بیاید (چه اولِ خط، چه بعد از ایموجیِ
# خنثی مثلِ 📍، چه بعد از تگ/فاصله/نویسه‌ی نامرئی) به آخرِ همان خط منتقل می‌شود تا
# خط با حرفِ فارسیِ «قوی» شروع شود و طبیعتاً راست‌چین شود. idempotent است.
#
# نکته‌ی مهم: پرچم ممکن است ایموجیِ ساده (🇫🇷) باشد یا داخلِ <tg-emoji> (ایموجیِ
# پرمیوم) بیاید: <tg-emoji emoji-id="...">🇫🇷</tg-emoji>. در حالتِ دوم باید کلِ تگ
# — نه فقط نویسه‌ی پرچم داخلش — به‌عنوانِ یک واحدِ کامل و سالم جابه‌جا شود؛ اگر
# فقط نویسه‌ی پرچم را از داخلِ تگ بیرون بکشیم، یک <tg-emoji></tg-emoji> خالی و
# بی‌معنی جا می‌ماند و emoji-id (که رندرِ پرمیوم به آن وابسته است) از دست می‌رود.
_FLAG_UNIT_RE = re.compile(
    r"<tg[-_]?emoji\b[^>]*>[\U0001F1E6-\U0001F1FF]+</tg[-_]?emoji>"
    r"|[\U0001F1E6-\U0001F1FF]",
    re.IGNORECASE,
)


def _relocate_leading_flags(html_text: str) -> str:
    if not re.search(r"[\U0001F1E6-\U0001F1FF]", html_text):
        return html_text
    return "\n".join(_relocate_flags_in_line(ln) for ln in html_text.split("\n"))


def _relocate_flags_in_line(line: str) -> str:
    m = _HAS_RTL_CHAR_RE.search(line)
    if not m:
        return line  # خطِ بدونِ حرفِ فارسی/عربی: دست نمی‌زنیم
    first_rtl = m.start()
    head = line[:first_rtl]
    flag_units = _FLAG_UNIT_RE.findall(head)
    if not flag_units:
        return line  # پرچمی قبل از متنِ فارسی نیست → کاری لازم نیست
    # واحدهای پرچمی (چه ساده، چه <tg-emoji>...</tg-emoji> کامل) را از قبلِ متنِ
    # فارسی برمی‌داریم (ایموجیِ خنثی/تگ‌های دیگر/فاصله سرِ جای خود می‌مانند) و
    # دست‌نخورده به آخرِ خط می‌چسبانیم تا اولین نویسه‌ی قوی، حرفِ فارسی شود.
    new_head = _FLAG_UNIT_RE.sub("", head)
    body = re.sub(r"[ \t]{2,}", " ", new_head + line[first_rtl:]).strip()
    return f"{body} {''.join(flag_units)}"


def ensure_rtl_lines(html_text: str) -> str:
    """راست‌چینیِ خط‌هایی که حرفِ فارسی/عربی دارن رو با RLM قفل می‌کنه؛ خط‌های
    فقط-عدد/ایموجی (مثلِ سطرِ ساعت/تاریخ) رو دست‌نخورده می‌ذاره تا چیدمان و
    استایلِ اصلیِ پست حفظ بشه. داخلِ <code>/<pre> هم دست نمی‌خوره تا کپیِ
    کانفیگ‌ها خراب نشه."""
    if not html_text or not html_text.strip():
        return html_text
    html_text = _relocate_leading_flags(html_text)
    # اول خطوطِ خالیِ داخلِ نقل‌قول‌ها رو جمع کن تا کانفیگ فضای خالیِ اضافه نگیره،
    # بعد چند خطِ خالیِ پشتِ‌سرِ‌هم/نامرئی رو به یک خطِ خالی کم کن. این در همه‌ی
    # مسیرها (کپشن، پیام، صفِ تایید) اجرا می‌شه، پس هیچ پستی فاصله‌ی اضافه نمی‌گیره.
    html_text = _tighten_blockquotes(html_text)
    html_text = _collapse_blankish_runs(html_text)
    parser = _RTLLineMarker()
    parser.feed(html_text)
    parser.close()
    result = "".join(parser.out)
    # تورِ ایمنیِ نهاییِ توازنِ تگ. ensure_rtl_lines آخرین مرحله‌ی پردازشِ متن قبل از
    # ارسال است (در هر سه مسیر: کپشنِ عادی، پیامِ متنی، و کپشنِ ویرایش‌شده‌ی صفِ
    # تایید). اگه هر مرحله‌ی قبلی — حذفِ منشن در clean_post_html، فیلترِ تبلیغات/لینک
    # در poster، یا حذفِ عبارت — یک تگِ باز و بی‌جفت (مثلِ <b> بدونِ </b>) به‌جا
    # گذاشته باشه، همین‌جا بسته می‌شه تا تلگرام کلِ پیام رو با «can't find end tag»
    # رد نکنه. اگه متن از قبل متوازن باشه، این کار هیچ‌چیزی رو عوض نمی‌کنه.
    result = _balance_html(result)
    # سپرِ نهایی: html.parser (داخلِ _balance_html) موقعِ سریالایزِ دوباره، خطِ
    # خالیِ بینِ متن و نقل‌قول را -هر وقت خطِ ماقبلِ نقل‌قول به یک تگِ بسته ختم شده
    # باشد (مثلاً </tg-emoji> بعدِ جابه‌جاییِ پرچم، یا </b>/</i>/هر تگِ دیگر)- به یک
    # \n تنها فشرده می‌کند؛ این رفتارِ خودِ کتابخانه‌ست، نه چیزی که اینجا نوشته‌ایم.
    # چون این خطِ خالی برای راست‌چینیِ درستِ آخرین خطِ کپشن حیاتی است (بالاتر توضیح
    # داده شد)، اینجا -به‌عنوانِ آخرین مرحله، بعدِ بالانس- دوباره تضمینش می‌کنیم؛
    # صرف‌نظر از این‌که خطِ دوم/سوم/هرخطِ ماقبلِ نقل‌قول با چه ایموجی (ساده یا
    # tg-emoji) یا چه متنی شروع یا تمام شده باشد. idempotent است.
    result = _BLANK_BEFORE_BLQ_RE.sub(r"\n\n\1", result)
    # آخرین مرحله: نشانه‌ی «خطِ خالیِ عمدی» برداشته می‌شه و خطِ واقعاً خالی می‌مونه.
    # از این‌جا به بعد هیچ تابعی نباید دوباره collapse بزنه.
    result = result.replace(_GAP_MARK, "")
    return result


# هم <tg-emoji> و هم <tgemoji> (بدونِ خط تیره) و <tg_emoji> رو پوشش می‌ده، چون
# منابع/نسخه‌های مختلف ممکنه هرکدوم رو بفرستن و تلگرام تگِ ناشناخته رو رد می‌کنه.
_TG_EMOJI_RE = re.compile(
    r"<tg[-_]?emoji\b[^>]*>(.*?)</tg[-_]?emoji>", re.IGNORECASE | re.DOTALL
)
_TG_EMOJI_STRAY_RE = re.compile(r"</?tg[-_]?emoji\b[^>]*>", re.IGNORECASE)


def strip_custom_emoji(html_text: str) -> str:
    """تگِ ایموجیِ پرمیوم رو به ایموجیِ سادهٔ داخلش تبدیل می‌کنه (آیدی رو حذف
    می‌کنه). وقتی گزینه‌ی «ایموجیِ پرمیوم» خاموشه یا ربات اجازه‌ی ارسالش رو
    نداره، ازش استفاده می‌شه تا پست بدونِ خطا و با ایموجیِ عادی ارسال بشه.
    هر دو شکلِ <tg-emoji> و <tgemoji> و همچنین تگِ بی‌جفت رو پاک می‌کنه تا
    خطای «unsupported start tag» از تلگرام نگیریم."""
    if not html_text:
        return html_text
    low = html_text.lower()
    if "tg-emoji" not in low and "tgemoji" not in low and "tg_emoji" not in low:
        return html_text
    html_text = _TG_EMOJI_RE.sub(r"\1", html_text)
    # هر تگِ باقی‌مانده‌ی بی‌جفت (باز یا بسته‌ی تنها) هم پاک می‌شه.
    html_text = _TG_EMOJI_STRAY_RE.sub("", html_text)
    return html_text


def make_footer_html(handle: str, url: str, template: str) -> str:
    display = template.replace("{handle}", handle) if template else f"@{handle}"
    return f'<a href="{_esc(url, quote=True)}">{_esc(display)}</a>'


_FOOTER_PLACEHOLDER_RE = re.compile(r"\{link\}|\{handle\}")


def render_custom_footer(custom_html: str, handle: str, url: str, link_template: str) -> str:
    handle = (handle or "").strip()
    if not _FOOTER_PLACEHOLDER_RE.search(custom_html):
        return custom_html

    display = link_template.replace("{handle}", handle) if link_template else (f"@{handle}" if handle else "")
    if handle and url:
        link_html = f'<a href="{_esc(url, quote=True)}">{_esc(display)}</a>'
    else:
        link_html = _esc(display)
    plain_handle_html = _esc(f"@{handle}") if handle else ""

    out = custom_html.replace("{link}", link_html)
    out = out.replace("{handle}", plain_handle_html)
    return out


# نویسه‌های نامرئی/جهت‌دهی که یک خطِ ظاهراً خالی رو «ناخالی» می‌کنن و از strip
# معمولی فرار می‌کنن: RLM/LRM/ZWNJ/ZWSP/ZWJ/BOM/word-joiner/embedding&isolate marks
# و فاصله‌ی سخت (NBSP). خطی که فقط از این‌ها ساخته شده، عملاً یک خطِ خالیه.
_BLANKISH = " \t\u00a0\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\u2066\u2067\u2068\u2069\ufeff"
_TRAILING_BLANKISH_RE = re.compile(f"(?:[{_BLANKISH}]*\n)+[{_BLANKISH}]*$")
_LEADING_BLANKISH_RE = re.compile(f"^(?:[{_BLANKISH}]*\n)+")

# ---------------------------------------------------------------------------
# نشانگرِ «خطِ خالیِ عمدی» (U+2063 INVISIBLE SEPARATOR)
# ---------------------------------------------------------------------------
# مشکل: append_footer فاصله‌ی خواسته‌شده رو با \n خالی می‌ساخت، ولی چند خط بعدتر
# _collapse_blankish_runs (داخلِ ensure_rtl_lines) هر رشته‌ی خطِ خالی رو به *یک*
# خط کم می‌کرد. نتیجه: گپِ دو-خطیِ امضای فایل‌های .nm/.npvt
# (_VPN_SIGNATURE_GAP_BY_KIND["file"] = 2) همیشه به یک خط تبدیل می‌شد.
# راه‌حل: خطِ خالیِ عمدی با این نویسه علامت‌گذاری می‌شه؛ collapse بهش دست نمی‌زنه
# و در آخرین مرحله‌ی ensure_rtl_lines خودِ نویسه پاک می‌شه و خطِ *واقعاً* خالی
# باقی می‌مونه. این نویسه در _BLANKISH نیست - عمداً - وگرنه دوباره حذف می‌شد.
_GAP_MARK = "\u2063"

# همه‌ی تگ‌های یک خط (برای وقتی متنِ خط حذف شده ولی تگ‌ها باید حفظ بشن).
_ANY_TAG_RE = re.compile(r"<[^>]+>")

# خطوطِ خالیِ چسبیده به تگ‌های بازِ/بسته‌ی بلاک‌کوت. لازمه چون وقتی امضا/منشنِ
# منبع *داخلِ* همون نقل‌قولِ کانفیگ بوده و حذف شده، یک خطِ خالی ته نقل‌قول (بینِ
# کانفیگ و </blockquote>) می‌مونه؛ تلگرام نقل‌قول رو با فضای خالیِ اضافه می‌کشه و
# مثلِ یک گپِ بزرگِ زیرِ کانفیگ دیده می‌شه.
_BLQ_OPEN_BLANKS_RE = re.compile(f"(<blockquote(?:\\s+expandable)?>)(?:[{_BLANKISH}]*\n)+")
_BLQ_CLOSE_BLANKS_RE = re.compile(f"(?:\n[{_BLANKISH}]*)+(</blockquote>)")
# خطِ خالیِ درست *قبل از* شروعِ نقل‌قول. تلگرام خودش بالای نقل‌قول حاشیه می‌ذاره،
# پس خطِ خالیِ اضافه باعث می‌شه بینِ متنِ بالا (مثلاً «Prompt:») و کادرِ نقل‌قول
# فاصله‌ی دوبرابر دیده بشه. فقط خطِ خالی حذف می‌شه، خودِ شکستِ خط می‌مونه.
# قبل از یک نقل‌قول که بعد از خطِ متنِ کپشن می‌آید، باید *دقیقاً یک خطِ خالی* باشد.
# چرا: بدونِ خطِ خالی، آخرین خطِ متن (که به نقل‌قول چسبیده) و خودِ نقل‌قولِ لاتین
# (کانفیگ) در تلگرام یک بلاکِ جهت‌دهیِ واحد حساب می‌شوند و جهتِ لاتینِ نقل‌قول،
# آن خطِ فارسی را هم چپ‌چین می‌کند؛ با یک خطِ خالی، آن خط بلاکِ جداگانه‌ی خودش
# می‌شود و درست راست‌چین می‌شود (کشفِ کاربر با تستِ واقعیِ تلگرام).
# لوک‌بی‌هایندها: بعد از </blockquote> خطِ خالی اضافه نمی‌شود (دو نقل‌قولِ
# پشتِ‌سرهم با یک \n جدا می‌مانند)، و وقتی قبلش خودش خطِ خالی است هم دوباره
# اضافه نمی‌شود (idempotent).
_BLANK_BEFORE_BLQ_RE = re.compile(
    f"(?<!</blockquote>)(?<![\n])\n(?:[{_BLANKISH}]*\n)*(<blockquote)"
)

# بینِ دو نقل‌قولِ پشتِ‌سرهم دقیقاً یک خطِ جدید باشه (نه خطِ خالی، نه هیچی).
# ⚠️ باگِ قبلی: این نرمال‌سازی فقط داخلِ clean_post_html (مسیرِ پستِ اسکرِیپ‌شده)
# انجام می‌شد، نه داخلِ _tighten_blockquotes که ensure_rtl_lines صداش می‌زنه.
# چون ensure_rtl_lines آخرین/تنها مرحله‌ایه که روی کپشنِ ویرایش‌شده‌ی کاربر در
# صفِ تایید اجرا می‌شه (بدونِ عبور از clean_post_html)، دو نقل‌قولِ چسبیده یا با
# خطِ خالی از هم جدا شده در اون مسیر هیچ‌وقت درست نمی‌شدن. حالا اینجا هم انجام
# می‌شه تا هر سه مسیر (کپشنِ عادی، پیامِ متنی، کپشنِ ویرایش‌شده) یک‌دست باشن.
_BLQ_ADJACENT_RE = re.compile(f"</blockquote>[{_BLANKISH}\n]*<blockquote", re.I)


def _tighten_blockquotes(text: str) -> str:
    """خطوطِ خالیِ ابتدا و انتهای *داخلِ* بلاک‌کوت رو حذف می‌کنه تا نقل‌قول فضای
    خالیِ اضافه (گپِ بزرگِ زیر/داخلِ کانفیگ) نگیره. فقط خطوطِ خالیِ چسبیده به تگِ
    باز/بسته برداشته می‌شن؛ محتوای واقعی و چندخطیِ کانفیگ هیچ تغییری نمی‌کنه.
    بینِ دو نقل‌قولِ جدا دقیقاً یک خطِ جدید، و بینِ متنِ کپشن و نقل‌قول یک خطِ
    خالی (برای راست‌چینیِ درستِ آخرین خطِ متن) تضمین می‌شه."""
    if "<blockquote" not in text:
        return text
    text = _BLQ_OPEN_BLANKS_RE.sub(r"\1", text)
    text = _BLQ_CLOSE_BLANKS_RE.sub(r"\1", text)
    # یک خطِ خالی بینِ متنِ کپشن و نقل‌قول بگذار تا آخرین خطِ متن هم راست‌چین شود.
    text = _BLANK_BEFORE_BLQ_RE.sub(r"\n\n\1", text)
    text = _BLQ_ADJACENT_RE.sub("</blockquote>\n<blockquote", text)
    return text


def _strip_blankish_edges(text: str) -> str:
    """خط‌های ابتدا/انتهای متن که فقط فاصله یا نویسه‌ی نامرئی دارن (و با strip
    معمولی پاک نمی‌شن) رو حذف می‌کنه. لازمه چون بعد از حذفِ تگ/منشنِ منبع از ته
    پست، گاهی یک خطِ خالی (یا خطی با فقط RLM/نیم‌فاصله) جا می‌مونه و باعث می‌شه
    فوترِ جدید با فاصله‌ی اضافه نوشته بشه."""
    if not text:
        return text
    text = _TRAILING_BLANKISH_RE.sub("", text)
    text = _LEADING_BLANKISH_RE.sub("", text)
    # فیکس: خط‌های لبه‌ای که «متنِ دیده‌شدنی» ندارن ولی تگِ توخالی دارن
    # (مثلِ «<b></b>» یا «<a href="..."></a>» که بعد از حذفِ لینک/عبارت مونده)
    # از دو regexِ بالا رد می‌شدن و به‌شکلِ خطِ خالیِ اضافه، فوتر/امضا رو هُل
    # می‌دادن پایین. تگ‌هاشون حفظ و به خطِ محتوادارِ همسایه چسبانده می‌شه تا
    # HTML نشکنه.
    lines = text.split("\n")
    keep = [i for i, ln in enumerate(lines) if not _line_is_visually_blank(ln)]
    if not keep:
        return ""
    first, last = keep[0], keep[-1]
    if first == 0 and last == len(lines) - 1:
        return text
    head_tags = "".join(_ANY_TAG_RE.findall("".join(lines[:first])))
    tail_tags = "".join(_ANY_TAG_RE.findall("".join(lines[last + 1:])))
    kept = lines[first:last + 1]
    kept[0] = head_tags + kept[0]
    kept[-1] = kept[-1] + tail_tags
    return "\n".join(kept)


def _line_is_visually_blank(line: str) -> bool:
    """True اگه کاربر از این خط *هیچ‌چیزی* نبینه: چه خطِ واقعاً خالی باشه، چه فقط
    نویسه‌ی نامرئی (RLM/ZWNJ/...) داشته باشه، چه فقط تگِ توخالی مثلِ «<b></b>» یا
    «<a href="..."></a>» که بعد از حذفِ عبارت/لینک/منشن به‌جا مونده. این سومی
    دقیقاً همون چیزیه که در تلگرام یک خطِ خالیِ اضافه رندر می‌شد و باعثِ گپِ بزرگِ
    بینِ کپشنِ فایل‌های .nm/.npvt و امضای انتهایی شده بود."""
    if not line:
        return True
    if _GAP_MARK in line:
        return False  # خطِ خالیِ عمدی (گپِ امضا) - نباید جمع بشه
    if line.strip(_BLANKISH) == "":
        return True
    # متنِ دیده‌شدنی: تگ‌ها حذف، entityهای HTML باز، نویسه‌های نامرئی برداشته
    visible = _html_mod.unescape(_ANY_TAG_RE.sub("", line))
    return visible.strip(_BLANKISH) == ""


def _collapse_blankish_runs(text: str) -> str:
    """چند خطِ خالیِ پشتِ‌سرِ‌هم (یا خطی که فقط نویسه‌ی نامرئی/فاصله داره و عملاً
    خالیه) رو به یک خطِ خالیِ استاندارد کم می‌کنه. این تضمین می‌کنه هیچ پستی
    فاصله‌ی اضافه بینِ بخش‌هاش (مثلاً بینِ هدر و کانفیگ) نداشته باشه، و خطِ خالیِ
    «نامرئی» که با strip معمولی پاک نمی‌شد هم عملاً از بین بره. فقط یک خطِ خالیِ
    عمدی بینِ دو بخش حفظ می‌شه — نه صفر، نه بیشتر."""
    if "\n" not in text:
        return text
    out: list[str] = []
    prev_blank = False
    pending_tags = ""  # تگ‌های یتیمِ خط‌های نامرئی که هنوز جایی نچسبیدن
    for ln in text.split("\n"):
        # خطِ خالیِ *عمدی* (گپِ امضا/فوتر) - هیچ‌وقت جمع نمی‌شه
        if _GAP_MARK in ln:
            if pending_tags and out:
                out[-1] += pending_tags
                pending_tags = ""
            out.append(ln)
            prev_blank = False
            continue
        if not _line_is_visually_blank(ln):
            out.append(pending_tags + ln if pending_tags else ln)
            pending_tags = ""
            prev_blank = False
            continue
        # ── از این‌جا به بعد: خطی که کاربر هیچ‌چیزی ازش نمی‌بینه ──────────
        # فیکسِ اصلی: قبلاً فقط خطی که *کاراکترش* نامرئی بود خالی حساب می‌شد؛
        # خطی مثلِ «<b></b>» یا «<a href="..."></a>» (باقی‌مانده‌ی حذفِ عبارت/
        # لینک/منشن) از این تست رد می‌شد و در تلگرام یک خطِ خالیِ کامل رندر
        # می‌شد. حالا ملاک، *متنِ دیده‌شدنی* است، نه رشته‌ی خام.
        tags = "".join(_ANY_TAG_RE.findall(ln))
        if tags:
            # تگ‌ها دور ریخته نمی‌شن (ممکنه نیمه‌ی یک جفتِ چندخطی باشن و
            # HTML رو بشکنن)؛ به تهِ آخرین خطِ محتوادار می‌چسبن - همون الگویی
            # که strip_vpn_source_boilerplate هم استفاده می‌کنه.
            anchor = next((i for i in range(len(out) - 1, -1, -1) if out[i]), None)
            if anchor is None:
                pending_tags += tags
            else:
                out[anchor] += tags
        if prev_blank:
            continue  # خطِ خالیِ دوم به بعد حذف می‌شه (بیش از یکی نداشته باشیم)
        out.append("")  # نویسه‌ی نامرئیِ خطِ خالی هم پاک و به خطِ خالیِ تمیز تبدیل می‌شه
        prev_blank = True
    if pending_tags:
        out.append(pending_tags)
    return "\n".join(out)


def append_footer(body_html: str, footer_html: str, blank_lines: int = 1) -> str:
    """بدنه و فوتر رو با blank_lines خطِ خالیِ عمدی به‌هم می‌چسبونه (پیش‌فرض یک
    خط، مطابقِ رفتارِ همیشگی). هم فاصله‌ی معمولی و هم خط‌های «فقط-نویسه‌ی-
    نامرئیِ» ته پست پاک می‌شن اول، تا فوتر دقیقاً با همون تعداد خطِ خالیِ
    خواسته‌شده بچسبه - نه کمتر، نه با فاصله‌ی اضافه‌ی باقی‌مونده از متنِ مبدأ."""
    body_html = _strip_blankish_edges(body_html.strip())
    if not footer_html:
        return body_html
    footer_html = _strip_blankish_edges(footer_html.strip())
    if not body_html:
        return footer_html
    # فیکس: قبلاً gap فقط «\n»ِ خالی بود و _collapse_blankish_runs بعداً هرچقدر
    # خطِ خالی رو به یک خط کم می‌کرد؛ برای همین blank_lines=2 (امضای فایل‌های
    # .nm/.npvt) عملاً همیشه یک خط می‌شد. حالا هر خطِ خالیِ عمدی با _GAP_MARK
    # علامت می‌خوره تا از collapse جونِ سالم به‌در ببره؛ خودِ نشانه در آخرین
    # مرحله‌ی ensure_rtl_lines پاک می‌شه و خطِ خالیِ تمیز باقی می‌مونه.
    gap = "\n" + (_GAP_MARK + "\n") * max(0, blank_lines)
    return f"{body_html}{gap}{footer_html}"


# ==================== امضای اختصاصیِ VFREEPN زیرِ پست‌های کانفیگ/پروکسی/فایل ====================
# طبقِ درخواستِ کاربر: هر پستی که کانفیگِ فیلترشکن (vless/vmess/trojan/.../
# tg://proxy/t.me/proxy) یا فایلِ Netmod (.nm) / Npv Tunnel (.npvt) داشته باشه،
# در انتهای پست - با دقیقاً یک خطِ خالی فاصله از محتوای بالاش - این امضا اضافه
# می‌شه: یک خطِ شعار و زیرش یک نقل‌قول (blockquote) با همون ایموجی‌هایی که توی
# نمونه‌ی کاربر بود، که متنِ VFREEPN داخلش به کانالِ https://t.me/vfreepn لینک
# شده. نکته‌ی مهم برای معافیت از فیلترها: این تابع در build_caption_html/
# build_message_html (poster.py) *بعد* از اجرایِ حذفِ عبارتِ دلخواه
# (_remove_phrases) و فیلترِ تبلیغاتِ عمومی/اختصاصیِ مقصد صدا زده می‌شه - یعنی
# اون مرحله‌ها اصلاً این امضا رو نمی‌بینن که بخوان حذفش کنن. برای اطمینانِ
# بیشتر، ad_filter._is_config_or_proxy هم صراحتاً هر لینک/متنی که کلمه‌ی
# vfreepn توش باشه رو معاف می‌کنه (نگاه کن به bot/ad_filter.py) تا اگه در
# آینده تابعِ strip_entities_html هم به مسیرِ اصلی وصل شد، بازم این لینک پاک
# نشه.
VFREEPN_URL = "https://t.me/vfreepn"
VFREEPN_LINK_TEXT = "VFREEPN"
VFREEPN_SIGNATURE_HTML = (
    "⚔️ اینترنت آزاد برای همه, یا هیچکس ⚔️\n"
    "<blockquote>🚩 دریافت کانفیگ نت ملی 🔐"
    f'<a href="{_esc(VFREEPN_URL, quote=True)}">{_esc(VFREEPN_LINK_TEXT)}</a>'
    "🔐</blockquote>"
)


def _vpn_signature_trigger_kind(body_html: str, media: list | None = None) -> str:
    """تشخیص می‌ده چه نوع محتوایی امضای VFREEPN رو ماشه زده: "config" اگه پست
    نقل‌قولِ کانفیگِ فیلترشکن/پروکسیِ تلگرامِ خام (توی متن، چه خام چه داخلِ
    href) داشته باشه، "file" اگه فایلِ Netmod/Npv Tunnel (توی مدیا) داشته
    باشه، یا رشته‌ی خالی اگه هیچ‌کدوم نبود. اولویت با کانفیگ/پروکسیه (اگه یک
    پست هم‌زمان هر دو رو داشته باشه - که عملاً نادره - طبقِ فاصله‌ی
    کانفیگ/پروکسی رفتار می‌کنه، نه فایل)."""
    if body_html and _CONFIG_SCHEME_LINE_RE.search(body_html):
        return "config"
    if _vpn_source_extension(media or []):
        return "file"
    return ""


def post_has_vpn_signature_trigger(body_html: str, media: list | None = None) -> bool:
    """True اگه پست کانفیگِ فیلترشکن/پروکسیِ تلگرام (توی متن، چه خام چه داخلِ
    href) یا فایلِ Netmod/Npv Tunnel (توی مدیا) داشته باشه - یعنی دقیقاً همون
    پست‌هایی که طبقِ درخواست باید امضای VFREEPN رو زیرشون بگیرن."""
    return bool(_vpn_signature_trigger_kind(body_html, media))


# تعدادِ خطِ خالیِ عمدیِ بینِ آخرین محتوای پست و امضای VFREEPN، به تفکیکِ نوعِ
# ماشه - طبقِ درخواستِ کاربر: پست‌های فایلِ اختصاصیِ Netmod/Npv Tunnel («file»)
# دو خطِ خالی می‌گیرن؛ پست‌های نقل‌قولِ کانفیگ/پروکسیِ متنی («config») بلافاصله
# بعدِ آخرین نقل‌قول فقط یک خطِ خالی می‌گیرن.
_VPN_SIGNATURE_GAP_BY_KIND = {"file": 2, "config": 1}


def append_vpn_signature(body_html: str, media: list | None = None) -> str:
    """اگه پست ماشه‌ی امضای VFREEPN رو بزنه (نگاه کن به
    _vpn_signature_trigger_kind)، امضا رو زیرِ کپشن اضافه می‌کنه - با دو خطِ
    خالیِ فاصله برای پست‌های فایلِ اختصاصی (nm/npvt)، یا یک خطِ خالیِ فاصله
    بلافاصله بعدِ آخرین نقل‌قول برای پست‌های کانفیگ/پروکسی؛ وگرنه بدونِ تغییر
    برمی‌گرده. idempotent است: اگه لینکِ vfreepn از قبل توی متن باشه (مثلاً
    امضا قبلاً اضافه شده)، دوباره اضافه نمی‌شه."""
    kind = _vpn_signature_trigger_kind(body_html, media)
    if not kind:
        return body_html
    if VFREEPN_URL.lower() in (body_html or "").lower():
        return body_html
    gap = _VPN_SIGNATURE_GAP_BY_KIND.get(kind, 1)
    return append_footer(body_html, VFREEPN_SIGNATURE_HTML, blank_lines=gap)


# ==================== حذفِ عبارت/ایموجیِ دلخواه از متنِ پست ====================
# قابلیتِ «حذفِ جمله/ایموجیِ مشخص»: کاربر (ادمین یا هر کاربرِ مجاز) چند عبارت یا
# ایموجی تعریف می‌کنه؛ هر جا توی متنِ پست دیده بشن، قبل از ارسال پاک می‌شن و بقیه‌ی
# پست عادی فرستاده می‌شه (فرقی نمی‌کنه حالتِ ارسال لحظه‌ای باشه یا زمان‌بندی/بازه‌ای/
# صفِ تایید - چون این پاک‌سازی توی ساختِ کپشنِ نهایی انجام می‌شه که مسیرِ مشترکِ همه‌ست).

# فاصله‌ی مجاز بینِ کلمه‌های یک عبارت: تگ‌های HTML (چون تلگرام ممکنه وسطِ جمله
# <b>/<i>/<a> بذاره)، فاصله‌ی معمولی، خطِ جدید و نیم‌فاصله (ZWNJ).
_PHRASE_GAP = r"(?:<[^>]+>|[\s\u200c\u200b])*"

# نویسه‌های عربی/فارسیِ هم‌ارز؛ تا اگه کاربر «ي» عربی نوشت، «ی» فارسیِ داخلِ پست هم
# پیدا بشه (و برعکس) - یکی از رایج‌ترین دلایلِ «چرا عبارتم پاک نشد؟».
_CHAR_EQUIV = {
    "ی": "[یي]", "ي": "[یي]",
    "ک": "[کك]", "ك": "[کك]",
    "ه": "[هة]", "ة": "[هة]",
    "أ": "[اأإآ]", "إ": "[اأإآ]", "آ": "[اأإآ]", "ا": "[اأإآ]",
}

_phrase_cache: dict[str, re.Pattern] = {}

# نویسه‌هایی که باعثِ «پاک نشدنِ» عبارت می‌شن ولی از نظرِ چشم دیده نمی‌شن یا فرقی
# ایجاد نمی‌کنن: کشیده/تطویل (ـ) که تلگرام برای justify کردنِ متن وسطِ کلمه‌ها
# اضافه می‌کنه، اعرابِ عربی/فارسی، و variation selector هایی که بعضی از ایموجی‌ها
# رو به شکلِ متفاوتی (ولی هم‌شکل) کدگذاری می‌کنن.
_TATWEEL_RE = re.compile("[\u0640]")
_DIACRITICS_RE = re.compile("[\u064b-\u0652\u0670\u06d6-\u06ed]")
_VARIATION_SEL_RE = re.compile("[\ufe0e\ufe0f]")
_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u200e\u200f]")


def _normalize_for_match(s: str) -> str:
    """نرمال‌سازیِ متن برای مقایسه: حذفِ تگِ HTML، کشیده، اعراب، variation selector
    و نویسه‌های نامرئی، یکسان‌سازیِ حروفِ عربی/فارسیِ هم‌ارز، و فشرده‌کردنِ فاصله‌ها.
    هدف اینه که تفاوت‌های نامرئی/ظاهریِ بینِ عبارتِ واردشده توسطِ کاربر و متنِ
    واقعیِ پست (معمولاً ناشی از فرمت‌بندیِ خودکارِ تلگرام یا اپ‌های موبایل) باعثِ
    عدمِ تطبیق نشه."""
    if not s:
        return ""
    out = re.sub(r"<[^>]+>", "", s)
    # متنِ پست قبل از ارسال با html.escape سِیف شده (& → &amp; و...)؛ برای
    # مقایسه‌ی درست با عبارتِ خامِ کاربر (که معمولاً "&" ساده داره نه "&amp;")
    # باید اینتیتی‌های HTML رو دیکد کنیم - وگرنه عبارت‌هایی که کاراکترِ &/</>
    # دارن (مثلِ "Casino & Sportsbook") هیچ‌وقت match نمی‌شن.
    out = _html_mod.unescape(out)
    out = _TATWEEL_RE.sub("", out)
    out = _DIACRITICS_RE.sub("", out)
    out = _VARIATION_SEL_RE.sub("", out)
    out = _INVISIBLE_RE.sub("", out)
    for ch, cls in _CHAR_EQUIV.items():
        canon = cls.strip("[]")[0]  # شکلِ استاندارد از کلاسِ رجکسِ هم‌ارزها
        out = out.replace(ch, canon)
    out = re.sub(r"\s+", " ", out).strip()
    return out.casefold()


def parse_phrases(raw: str) -> list[str]:
    """هر خط = یک عبارت. (برخلافِ کلیدواژه‌ها با ویرگول جدا نمی‌شن، چون خودِ جمله
    ممکنه ویرگول داشته باشه.)"""
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def _phrase_pattern(phrase: str) -> re.Pattern:
    cached = _phrase_cache.get(phrase)
    if cached is not None:
        return cached
    # کشیده/اعراب رو از خودِ عبارتِ کاربر هم پاک می‌کنیم (شاید کاربر متن رو از یک
    # پستِ کشیده‌شده کپی کرده باشه) و بینِ هر حرفِ کلمه یک «کشیده/اعرابِ اختیاری»
    # می‌ذاریم تا اگه متنِ اصلیِ پست وسطِ کلمه کشیده داشته باشه هم match بشه.
    clean_phrase = _TATWEEL_RE.sub("", phrase)
    clean_phrase = _DIACRITICS_RE.sub("", clean_phrase)
    words = [w for w in re.split(r"[\s\u200c\u200b]+", clean_phrase.strip()) if w]
    _CHAR_GAP = r"[\u0640\u064b-\u0652\u0670\u06d6-\u06ed]*"
    parts = []
    for w in words:
        # اگه کلمه شاملِ &, <, >, ", ' باشه، متنِ واقعیِ پست به‌شکلِ اینتیتیِ HTML
        # (&amp;, &lt;, ...) سِیو شده؛ پس هر حرف رو هم به‌شکلِ خام و هم به‌شکلِ
        # اینتیتیِ HTMLش قبول می‌کنیم تا فرقی نکنه کدوم فرم توی متنِ پست باشه.
        chars = []
        for ch in w:
            if ch in _CHAR_EQUIV:
                chars.append(_CHAR_EQUIV[ch])
            else:
                escaped = _esc(ch)
                if escaped != ch:
                    chars.append("(?:" + re.escape(ch) + "|" + re.escape(escaped) + ")")
                else:
                    chars.append(re.escape(ch))
        parts.append(_CHAR_GAP.join(chars))
    pattern = re.compile(_PHRASE_GAP.join(parts), re.IGNORECASE)
    _phrase_cache[phrase] = pattern
    return pattern


def _visible_text(html_fragment: str) -> str:
    """متنِ دیده‌شدنیِ یک تکه HTML (بدونِ تگ و فاصله‌ها) - برای تشخیصِ اینکه یک خط
    بعد از حذفِ عبارت، عملاً خالی شده یا نه."""
    return re.sub(r"<[^>]+>", "", html_fragment).replace("\u200c", "").strip()


def _tidy_fragment(html_fragment: str) -> str:
    out = html_fragment
    # تگ‌هایی که محتواشون حذف شده و خالی موندن (<b></b>، <a ...></a> و...)
    for _ in range(3):
        new = re.sub(r"<(b|i|u|s|code|pre|tg-spoiler)>\s*</\1>", "", out)
        new = re.sub(r"<a\b[^>]*>\s*</a>", "", new)
        if new == out:
            break
        out = new
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _balance_html(html_text: str) -> str:
    """بستنِ تگ‌های نیمه‌کاره. لازمه چون وقتی عبارتِ حذف‌شده وسطِ تگ‌ها پخش شده باشه
    (مثلِ «تبلیغ <b>عضو</b> <i>کانال ما</i> بشید») حذفش می‌تونه یک <b>ِ باز و بی‌جفت
    به‌جا بذاره؛ اون‌وقت تلگرام کلِ پیام رو با خطای «Can't parse entities» رد می‌کنه."""
    if "<" not in html_text:
        return html_text
    try:
        out = BeautifulSoup(html_text, "html.parser").decode()
        # BeautifulSoup صفتِ بی‌مقدارِ expandable رو به expandable="" تبدیل می‌کنه،
        # ولی تلگرام شکلِ استانداردِ <blockquote expandable> رو می‌خواد. اگه برنگردونیم
        # ممکنه بلاک‌کوتِ قابل‌گسترش خراب بشه یا به نقل‌قولِ عادی تبدیل بشه. این تنها
        # صفتِ بی‌مقداری‌ست که در HTMLِ تلگرام استفاده می‌شه، پس همینو برمی‌گردونیم.
        out = out.replace(' expandable=""', " expandable").replace(" expandable=''", " expandable")
        return out
    except Exception:
        # اگه به هر دلیلی پارس نشد، امن‌ترین کار حذفِ کاملِ تگ‌هاست تا پیام رد نشه
        return re.sub(r"<[^>]+>", "", html_text)


def strip_phrases_html(html_text: str, phrases: list[str]) -> str:
    """حذفِ همه‌ی عبارت‌ها/ایموجی‌های داده‌شده از HTMLِ پست.

    خط‌به‌خط کار می‌کنه: هر خطی که روش عبارت/منشن/ایموجیِ حذف‌شده بوده - چه بعدِ
    حذف کاملاً خالی بشه چه هنوز متنِ دیگه‌ای هم داشته باشه - *کاملاً* برداشته
    می‌شه (نه فقط خودِ عبارت)؛ تا جمله‌ی نصفه یا بی‌معنی به‌جا نمونه. فقط
    خط‌هایی که هیچ عبارتی توشون پیدا نشد دست‌نخورده می‌مونن.
    """
    if not html_text or not phrases:
        return html_text

    phrases = [ph for ph in phrases if ph.strip()]
    if not phrases:
        return html_text
    patterns = [_phrase_pattern(ph) for ph in phrases]
    # نسخه‌ی نرمال‌شده‌ی هر عبارت، برای تطبیقِ «کلِ خط» بدونِ حساسیت به کشیده/
    # اعراب/variation-selector؛ عبارت‌هایی که کاربر معمولاً به‌عنوانِ یک خطِ کاملِ
    # پست وارد می‌کنه (مثلِ «🔴 فوری سوالات امتحان نهایی لو رفت 😀») دقیقاً همین‌جا
    # پیدا می‌شن، حتی اگه متنِ اصلیِ پست کشیده/اعرابِ اضافه داشته باشه.
    normalized_phrases = [_normalize_for_match(ph) for ph in phrases]

    out_lines: list[str] = []
    for line in html_text.split("\n"):
        normalized_line = _normalize_for_match(line)
        if normalized_line and any(
            np and np == normalized_line for np in normalized_phrases
        ):
            continue  # کلِ این خط دقیقاً یکی از عبارت‌هاست (با چشم‌پوشی از کشیده/اعراب/...)

        original = line
        for pat in patterns:
            line = pat.sub("", line)
        if line != original:
            continue  # این خط عبارت/منشن/ایموجیِ حذف‌شده روش بود → کلِ خط حذف می‌شه
        out_lines.append(line)

    out = "\n".join(out_lines)
    out = _drop_empty_structural_blocks(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return _balance_html(out).strip()
