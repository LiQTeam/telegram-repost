"""
توابع کمکی عمومی برای استفاده در سراسر پروژه
شامل: استخراج یوزرنیم، استخراج آیدی، محدود کردن عدد، کوتاه‌سازی HTML،
ایجاد نام فایل امن، تولید checksum، تبدیل به boolean، فرمت‌دهی اعداد،
تشخیص نوع فایل و ...
"""
from __future__ import annotations

import hashlib
import json
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

def format_log_entry(log_row) -> str:
    """
    یک ردیفِ system_logs رو برای نمایش توی تلگرام (HTML) فرمت می‌کنه.
    علاوه بر پیام، این‌ها رو هم نشون می‌ده تا معلوم بشه دقیقاً «داشته چیکار
    می‌کرده» که این ارور به‌وجود اومده:
    - نوعِ عملیات (log_type) + شناسه‌ی کانال/مقصد/کاربر/پستِ مرتبط (اگه بود)
    - هر پارامترِ دیگه‌ای که خودِ همون بخش از کد موقعِ ثبتِ لاگ فرستاده
      (مثلاً task_type، طولِ متن، آخرین خطای Provider و ...)
    و برای لاگ‌های ERROR/WARNING که details._debug دارن (نگاه کن به
    Database.add_system_log)، مشخصاتِ فنیِ منشأِ خطا (فایل/خط/تابع + نوعِ
    استثنا) رو هم زیرِ همه اضافه می‌کنه تا دیباگ بدونِ نیاز به لاگِ خامِ
    سرور ممکن باشه.
    """
    import html as _html

    # برچسبِ فارسیِ نوعِ عملیات، فقط برای خواناتر شدن (اگه log_type ناشناخته
    # بود، خودِ کدِ خامش نمایش داده می‌شه - چیزی گم نمی‌شه)
    _OP_LABELS = {
        "AI": "پردازشِ هوش مصنوعی",
        "MEDIA": "پردازشِ رسانه",
        "POST": "ارسال/پردازشِ پست",
        "NOTIFICATION": "اعلان‌رسانی",
        "AD_FILTER": "فیلترِ تبلیغات",
        "DUPLICATE": "تشخیصِ محتوایِ تکراری",
        "IMAGE_GEN": "تولیدِ تصویر با هوش مصنوعی",
        "MONITOR": "مانیتورینگِ منابعِ سرور",
    }

    severity = log_row["severity"] if "severity" in log_row.keys() else ""
    icon = {"ERROR": "🔴", "WARNING": "🟠", "INFO": "🟢"}.get(severity, "📌")

    message = log_row["message"] or ""
    message_short = message if len(message) <= 200 else message[:200] + "…"

    lines = [
        f"🕒 {log_row['jalali_date']}",
        f"{icon} {_html.escape(log_row['event_type'])}",
        f"📝 {_html.escape(message_short)}",
    ]

    # «داشته چیکار می‌کرده» - نوعِ عملیات + رویِ کدوم کانال/پست/کاربر
    keys = log_row.keys()
    op_label = _OP_LABELS.get(log_row["log_type"], log_row["log_type"]) if "log_type" in keys else None
    target_bits = []
    if "channel_id" in keys and log_row["channel_id"]:
        target_bits.append(f"کانالِ مبدأ {log_row['channel_id']}")
    if "destination_id" in keys and log_row["destination_id"]:
        target_bits.append(f"کانالِ مقصد {log_row['destination_id']}")
    if "post_id" in keys and log_row["post_id"]:
        target_bits.append(f"پستِ {log_row['post_id']}")
    if "user_id" in keys and log_row["user_id"]:
        target_bits.append(f"کاربرِ {log_row['user_id']}")
    op_line_bits = []
    if op_label:
        op_line_bits.append(f"عملیات: {op_label}")
    if target_bits:
        op_line_bits.append("روی " + "، ".join(target_bits))
    if "status" in keys and log_row["status"]:
        op_line_bits.append(f"(نتیجه: {log_row['status']})")
    if op_line_bits:
        lines.append("🎬 " + _html.escape(" — ".join(op_line_bits)))

    details_raw = log_row["details"] if "details" in keys else None
    details = None
    if details_raw:
        try:
            details = json.loads(details_raw)
        except Exception:
            details = None

    if isinstance(details, dict):
        # پارامترهایی که خودِ همون بخش از کد موقعِ ثبتِ ارور فرستاده (هر چیزی
        # جز _debug که داخلی و فنیه) - این‌ها دقیقاً می‌گن ورودی/وضعیتِ
        # عملیاتی که خطا داد چی بوده (مثلاً task_type، طولِ متن، پرامپت،
        # آخرین خطای هر Provider و ...)
        extra = {k: v for k, v in details.items() if k != "_debug"}
        if extra:
            param_bits = []
            for k, v in extra.items():
                v_str = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                if len(v_str) > 90:
                    v_str = v_str[:90] + "…"
                param_bits.append(f"{k}={v_str}")
            params_line = " | ".join(param_bits)
            if len(params_line) > 300:
                params_line = params_line[:300] + "…"
            lines.append("🧩 پارامترهای عملیات: " + _html.escape(params_line))

        debug = details.get("_debug")
        if debug:
            loc_bits = []
            if debug.get("caller_file"):
                loc_bits.append(f"{debug['caller_file']}:{debug.get('caller_line', '?')}")
            if debug.get("caller_function"):
                loc_bits.append(f"در {debug['caller_function']}()")
            if loc_bits:
                lines.append("📂 منشأ: " + _html.escape(" ".join(loc_bits)))

            if debug.get("exception_type"):
                exc_line = f"⚠️ {debug['exception_type']}"
                if debug.get("exception_message"):
                    exc_line += f": {debug['exception_message']}"
                lines.append(_html.escape(exc_line))

            if debug.get("origin_file"):
                origin = f"🎯 محلِ دقیقِ خطا: {debug['origin_file']}:{debug.get('origin_line', '?')}"
                if debug.get("origin_function"):
                    origin += f" در {debug['origin_function']}()"
                lines.append(_html.escape(origin))
                if debug.get("origin_code"):
                    lines.append(f"<code>{_html.escape(debug['origin_code'])}</code>")

    return "\n".join(lines)


# محدودیتِ واقعیِ تلگرام برایِ متنِ پیام؛ کمی پایین‌تر می‌گیریم که جا برایِ
# هدر و کیبورد هم بمونه و ریسکِ رد شدن از حد صفر بشه.
_TELEGRAM_SAFE_TEXT_LIMIT = 3800


def build_logs_message(header: str, logs, limit: int = 20) -> str:
    """
    هدر + فرمتِ چندتا ردیفِ system_logs رو می‌سازه، ولی برخلافِ یک لوپِ ساده،
    تضمین می‌کنه که طولِ نهایی هیچ‌وقت از حدِ مجازِ پیامِ تلگرام (۴۰۹۶ کاراکتر)
    رد نشه؛ چون با جزئیاتِ فنیِ ارورها (فایل/خط/exception/پارامترها)، چند تا
    لاگِ طولانی می‌تونن به‌راحتی از این حد رد بشن و باعثِ کرش‌شدنِ منو با
    خطای MESSAGE_TOO_LONG بشن. اگه همه جا نشن، به‌جاش می‌گه چندتا مورد جا
    مونده تا کاربر با فیلترِ دقیق‌تر (کانال/کاربر خاص) بقیه رو ببینه.
    """
    parts = [header]
    total_len = len(header)
    shown = 0
    logs_slice = list(logs[:limit])

    for log_row in logs_slice:
        entry = format_log_entry(log_row)
        # +2 برایِ فاصله‌ی "\n\n" بینِ بخش‌ها
        added_len = len(entry) + 2
        if shown > 0 and (total_len + added_len) > _TELEGRAM_SAFE_TEXT_LIMIT:
            break
        parts.append(entry)
        total_len += added_len
        shown += 1

    remaining = len(logs_slice) - shown
    if remaining > 0:
        parts.append(f"… و {remaining} موردِ دیگر (برایِ دیدن، از فیلترِ کانال/کاربر/مقصد استفاده کن)")

    return "\n\n".join(parts)
