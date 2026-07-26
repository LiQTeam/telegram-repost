"""
توابع کمکی عمومی برای استفاده در سراسر پروژه
شامل: استخراج یوزرنیم، استخراج آیدی، محدود کردن عدد، کوتاه‌سازی HTML،
ایجاد نام فایل امن، تولید checksum، تبدیل به boolean، فرمت‌دهی اعداد،
تشخیص نوع فایل و ...
"""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Optional, Union


def extract_username(text: str) -> Optional[str]:
    """
    استخراج یوزرنیم از متن ورودی

    پشتیبانی از فرمت‌ها:
    - @username
    - username
    - https://t.me/username
    - t.me/username
    - telegram.me/username

    Args:
        text: متن ورودی

    Returns:
        یوزرنیم استخراج‌شده یا None در صورت عدم وجود
    """
    text = text.strip()

    # حذف @ اگر در ابتدا باشد
    if text.startswith("@"):
        text = text[1:]

    # حذف لینک t.me
    match = re.search(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]+)", text, re.I)
    if match:
        return match.group(1)

    # فقط یوزرنیم (حداقل ۳ کاراکتر، شامل حروف، اعداد و زیرخط)
    if re.match(r"^[A-Za-z0-9_]{3,}$", text):
        return text

    return None


def extract_chat_id(text: str) -> str:
    """
    استخراج آیدی چت از متن ورودی

    پشتیبانی از فرمت‌ها:
    - عدد منفی (آیدی عددی): -1001234567890
    - یوزرنیم: @username
    - لینک t.me

    Args:
        text: متن ورودی

    Returns:
        آیدی چت (به همان فرمتی که تشخیص داده شد)
    """
    text = text.strip()

    # اگر عدد منفی است (آیدی عددی)
    if re.match(r"^-?\d+$", text):
        return text

    # اگر یوزرنیم است
    if text.startswith("@"):
        return text

    # اگر لینک t.me است
    match = re.search(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]+)", text, re.I)
    if match:
        return f"@{match.group(1)}"

    # اگر آیدی عددی با خط تیره است (مثل -1001234567890)
    match = re.search(r"(-?\d+)", text)
    if match:
        return match.group(1)

    return text


def clamp(value: int, min_val: int, max_val: int) -> int:
    """
    محدود کردن عدد بین دو مقدار

    Args:
        value: عدد ورودی
        min_val: حداقل مجاز
        max_val: حداکثر مجاز

    Returns:
        عدد محدودشده بین min_val و max_val
    """
    return max(min_val, min(max_val, value))


def tg_text_len(text: str) -> int:
    """طولِ متن بر حسبِ واحدهای UTF-16 — همون چیزی که تلگرام برای سقفِ پیام
    (۴۰۹۶) و کپشن (۱۰۲۴) می‌شماره. هر نویسه‌ی فراصفحه‌ای (astral، مثلِ ایموجی و
    پرچم) ۲ واحد حساب می‌شه، نه ۱. برای همینه که یک متنِ ۴۰۹۶ code-point‌ی که
    ایموجی داره ممکنه از سقفِ واقعیِ تلگرام رد بشه."""
    if not text:
        return 0
    return len(text.encode("utf-16-le")) // 2


class _HTMLTruncator(HTMLParser):
    """پارسِ HTML و کوتاه‌کردنش تا یک تعداد کاراکترِ متنیِ مشخص، بدون اینکه
    وسطِ یک تگ (مثلاً <code>) قطع بشه. تگ‌های بازِ باقی‌مانده در پایان با
    close_open_tags() به‌ترتیبِ درست بسته می‌شن."""

    _VOID_TAGS = {"br", "hr", "img"}

    def __init__(self, max_length: int):
        super().__init__(convert_charrefs=False)
        self.max_length = max_length
        self.count = 0
        self.out: list[str] = []
        self.stack: list[str] = []
        self.done = False

    @staticmethod
    def _attrs_to_str(attrs) -> str:
        parts = []
        for k, v in attrs:
            parts.append(f' {k}="{v}"' if v is not None else f" {k}")
        return "".join(parts)

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        self.out.append(f"<{tag}{self._attrs_to_str(attrs)}>")
        if tag not in self._VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self.done:
            return
        self.out.append(f"<{tag}{self._attrs_to_str(attrs)}/>")

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
            self.out.append(f"</{tag}>")
        # اگه تگِ بسته‌ای بدونِ تگِ بازِ متناظر باشه (HTML نامعتبر)، نادیده گرفته می‌شه

    def handle_data(self, data):
        if self.done:
            return
        remaining = self.max_length - self.count
        if remaining <= 0:
            self.done = True
            return
        # طول بر حسبِ واحدهای UTF-16 شمرده می‌شه (همون چیزی که تلگرام برای سقفِ
        # ۱۰۲۴/۴۰۹۶ می‌شماره)؛ هر ایموجی/نویسه‌ی فراصفحه‌ای (astral) ۲ واحد حساب
        # می‌شه، نه ۱. اگه code-point بشماریم، متنِ پُر از ایموجی از سقفِ واقعیِ
        # تلگرام رد می‌شه و خطای «Message is too long» می‌گیریم.
        units = 0
        idx = 0
        for i, ch in enumerate(data):
            w = 2 if ord(ch) > 0xFFFF else 1
            if units + w > remaining:
                break
            units += w
            idx = i + 1
        if idx >= len(data):
            self.out.append(data)
            self.count += units
        else:
            self.out.append(data[:idx])
            self.count = self.max_length
            self.done = True

    def handle_entityref(self, name):
        if self.done or self.count >= self.max_length:
            self.done = True
            return
        self.out.append(f"&{name};")
        self.count += 1

    def handle_charref(self, name):
        if self.done or self.count >= self.max_length:
            self.done = True
            return
        self.out.append(f"&#{name};")
        self.count += 1

    def close_open_tags(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def truncate_html_safe(html_text: str, max_length: int) -> str:
    """
    کوتاه کردن HTML به صورت امن (با حفظ و بستنِ درستِ تگ‌ها)

    برخلافِ نسخه‌ی قبلی که رشته‌ی خام رو با html_text[:max_length] می‌برید
    (و ممکن بود وسطِ یک تگ مثلِ <code> قطع بشه و تلگرام خطای
    "Can't parse entities: can't find end tag..." بده)، این نسخه HTML رو
    پارس می‌کنه، فقط تا سقفِ کاراکترِ متنیِ مجاز پیش می‌ره و در پایان هر
    تگِ بازِ باقی‌مانده رو به‌ترتیبِ درست می‌بنده.

    Args:
        html_text: متن HTML
        max_length: حداکثر طول مجاز (بر اساسِ متنِ ساده، بدونِ تگ)

    Returns:
        متن کوتاه‌شده با تگ‌های سالم
    """
    if not html_text:
        return ""

    # طول بر حسبِ واحدهای UTF-16 (ملاکِ واقعیِ تلگرام)، نه code-point.
    from .formatter import strip_html_tags
    plain = strip_html_tags(html_text)

    if tg_text_len(plain) <= max_length:
        return html_text

    # یک واحد برای «…» رزرو می‌شه
    budget = max(max_length - 1, 0)
    parser = _HTMLTruncator(budget)
    parser.feed(html_text)
    parser.out.append("…")
    parser.close_open_tags()
    return "".join(parser.out)


def safe_filename(name: str) -> str:
    """
    ایجاد نام فایل امن (حذف کاراکترهای غیرمجاز)

    Args:
        name: نام فایل

    Returns:
        نام فایل با کاراکترهای امن
    """
    return re.sub(r'[^\w\-_.]', '_', name)


def generate_checksum(data: bytes) -> str:
    """
    تولید checksum با SHA-256 برای داده‌ها

    Args:
        data: داده

    Returns:
        هش SHA-256 به صورت هگزادسیمال
    """
    return hashlib.sha256(data).hexdigest()


def parse_bool(value: Union[str, int, bool, None]) -> bool:
    """
    تبدیل مقادیر مختلف به boolean

    Args:
        value: مقدار ورودی

    Returns:
        مقدار boolean
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on", "active", "enabled")
    return False


def format_number(num: Union[int, float]) -> str:
    """
    فرمت‌دهی اعداد با جداکننده هزارگان

    Args:
        num: عدد

    Returns:
        رشته فرمت‌شده با جداکننده هزارگان
    """
    if isinstance(num, float):
        num = round(num, 2)
        if num.is_integer():
            num = int(num)
    return f"{num:,}"


def get_file_extension(filename: str) -> str:
    """
    دریافت پسوند فایل

    Args:
        filename: نام فایل

    Returns:
        پسوند فایل (بدون نقطه) یا رشته خالی
    """
    if not filename:
        return ""
    return filename.split(".")[-1].lower() if "." in filename else ""


def is_image_file(filename: str) -> bool:
    """
    بررسی اینکه آیا فایل تصویر است

    Args:
        filename: نام فایل

    Returns:
        True اگر تصویر باشد
    """
    ext = get_file_extension(filename)
    return ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "ico", "tiff", "tif")


def is_video_file(filename: str) -> bool:
    """
    بررسی اینکه آیا فایل ویدیو است

    Args:
        filename: نام فایل

    Returns:
        True اگر ویدیو باشد
    """
    ext = get_file_extension(filename)
    return ext in ("mp4", "webm", "avi", "mov", "mkv", "flv", "wmv", "m4v", "3gp", "mpeg", "mpg")


def is_audio_file(filename: str) -> bool:
    """
    بررسی اینکه آیا فایل صوتی است

    Args:
        filename: نام فایل

    Returns:
        True اگر صوتی باشد
    """
    ext = get_file_extension(filename)
    return ext in ("mp3", "wav", "ogg", "flac", "m4a", "aac", "wma", "opus", "aiff", "alac")


def is_document_file(filename: str) -> bool:
    """
    بررسی اینکه آیا فایل سند است

    Args:
        filename: نام فایل

    Returns:
        True اگر سند باشد
    """
    ext = get_file_extension(filename)
    return ext in (
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
        "txt", "rtf", "odt", "ods", "odp", "odg", "csv", "tsv",
        "md", "markdown", "json", "xml", "yaml", "yml", "toml"
    )


def is_archive_file(filename: str) -> bool:
    """
    بررسی اینکه آیا فایل آرشیو است

    Args:
        filename: نام فایل

    Returns:
        True اگر آرشیو باشد
    """
    ext = get_file_extension(filename)
    return ext in ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "tbz2")


def get_mime_type(filename: str) -> str:
    """
    دریافت MIME type بر اساس پسوند فایل

    Args:
        filename: نام فایل

    Returns:
        MIME type
    """
    ext = get_file_extension(filename)
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
        "ico": "image/x-icon",
        "mp4": "video/mp4",
        "webm": "video/webm",
        "avi": "video/x-msvideo",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
        "flv": "video/x-flv",
        "wmv": "video/x-ms-wmv",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "aac": "audio/aac",
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain",
        "rtf": "application/rtf",
        "zip": "application/zip",
        "rar": "application/x-rar-compressed",
        "7z": "application/x-7z-compressed",
        "tar": "application/x-tar",
        "gz": "application/gzip",
        "json": "application/json",
        "xml": "application/xml",
        "html": "text/html",
        "css": "text/css",
        "js": "application/javascript",
    }
    return mime_map.get(ext, "application/octet-stream")