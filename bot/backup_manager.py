"""
مدیریت بکاپ خودکار دیتابیس و بازیابی کامل (Restore)
با قابلیت رمزنگاری، ارسال به کانال و بازیابی کامل
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from telegram import Bot, InputFile
from telegram.constants import ParseMode

from .database import db, _lock as _db_lock  # noqa: PLC2701 — همان قفلِ سراسریِ کانکشن
from .jdatetime_utils import now_jalali, format_jalali_datetime

log = logging.getLogger("repost_bot.backup_manager")

BACKUP_SETTINGS_KEY = "backup_settings"
BACKUP_TIME_DEFAULT = "03:00"
BACKUP_ENCRYPTION_KEY = None

# حداکثر تعداد فایل بکاپ نگهداری‌شده در سرور
MAX_BACKUP_FILES = 7

# ==================================================================
# رمزِ عبورِ بکاپ (مستقل از BOT_TOKEN) - برای بازیابیِ «قابلِ‌جابجایی»
# ==================================================================
# هدف: کلیدِ رمزنگاریِ قبلی از روی BOT_TOKEN ساخته می‌شد؛ یعنی بکاپ فقط روی
# *همون* ربات/توکن قابلِ بازیابی بود. برای این‌که بشه یک بکاپ رو روی یک ربات/
# توکن/اکانتِ کاملاً جدید (آیدیِ تازه‌ی تلگرام) هم بازیابی کرد، اینجا یک لایه‌ی
# رمزنگاریِ دومِ *مبتنی بر رمزِ عبور* اضافه شده که کاملاً مستقل از BOT_TOKEN
# است. رمزِ عبور یک‌بار توسط ادمین ست می‌شه (و برای بکاپ‌های خودکار/فوریِ بعدی
# همینِ رمز به‌صورتِ خودکار استفاده می‌شه)، ولی موقعِ *بازیابی* - حتی روی همینِ
# ربات - همیشه باید دستی وارد بشه؛ این‌طوری هم فایلِ بکاپ اگه دستِ کسِ دیگه‌ای
# بیفته بی‌فایده‌ست (بدونِ رمز قابلِ بازگشایی نیست)، هم بازیابی هیچ‌وقت تصادفی/
# خودکار انجام نمی‌شه.
BACKUP_PASSWORD_SETTING_KEY = "backup_password"
_PW_MAGIC = b"PWBK1"  # پیشوندِ مشخص‌کننده‌یِ فرمتِ رمزِ‌عبوری (بدونِ رمزگشایی هم قابلِ تشخیصه)
_PW_SALT_LEN = 16
_PBKDF2_ITERATIONS = 390_000


def _derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def get_backup_password() -> str | None:
    """رمزِ عبورِ فعلیِ بکاپ (اگه ست شده باشه) رو برمی‌گردونه."""
    raw = db.get_setting(BACKUP_PASSWORD_SETTING_KEY, "")
    return raw or None


def set_backup_password(password: str) -> None:
    """رمزِ عبورِ بکاپ رو ذخیره می‌کنه. از این به بعد، هر بکاپِ جدید (خودکار/فوری)
    با همین رمز رمزنگاری می‌شه و برای بازیابی (روی هر ربات/توکنی) باید همین رمز
    وارد بشه."""
    db.set_setting(BACKUP_PASSWORD_SETTING_KEY, password.strip())


def has_backup_password() -> bool:
    return bool(get_backup_password())


def is_password_protected_backup(payload: bytes) -> bool:
    """بدونِ نیاز به رمزگشایی، مشخص می‌کنه که فایلِ بکاپ با رمزِ عبور محافظت
    شده (فرمتِ جدید، قابلِ‌جابجایی بینِ توکن‌ها) یا فرمتِ قدیمیِ وابسته به
    BOT_TOKEN است."""
    return payload.startswith(_PW_MAGIC)


def encrypt_data_with_password(data: bytes, password: str) -> bytes:
    """رمزنگاریِ داده با کلیدی که از رمزِ عبور (+ salt تصادفی) مشتق می‌شه.
    salt به‌صورتِ خام (رمزنگاری‌نشده) در ابتدایِ خروجی ذخیره می‌شه تا موقعِ
    بازیابی، با هر رمزی که کاربر وارد کنه بشه دوباره همون کلید رو ساخت."""
    salt = os.urandom(_PW_SALT_LEN)
    key = _derive_key_from_password(password, salt)
    token = Fernet(key).encrypt(data)
    return _PW_MAGIC + salt + token


def decrypt_data_with_password(payload: bytes, password: str) -> bytes:
    """رمزگشاییِ فایلِ بکاپِ رمزِعبوری. اگه رمز اشتباه باشه، Fernet با
    InvalidToken شکست می‌خوره (که در سطحِ بالاتر به‌عنوانِ «رمز اشتباه است»
    به کاربر نمایش داده می‌شه)."""
    if not payload.startswith(_PW_MAGIC):
        raise ValueError("این فایل با رمزِ عبور محافظت نشده (یا فرمتش قدیمی/متفاوت است).")
    salt = payload[len(_PW_MAGIC): len(_PW_MAGIC) + _PW_SALT_LEN]
    token = payload[len(_PW_MAGIC) + _PW_SALT_LEN:]
    key = _derive_key_from_password(password, salt)
    return Fernet(key).decrypt(token)

# جدول‌های پرحجمِ عملیاتی که در بکاپ گنجونده نمی‌شن. این‌ها لاگ/تاریخچه/آمار/نگاشتِ
# موقتی‌ان که با استفاده‌ی عادیِ ربات دوباره ساخته می‌شن؛ نبودشون در بکاپ هیچ
# تنظیمات یا کانال/مقصدی رو از دست نمی‌ده، ولی چون روزانه هزاران ردیف اضافه می‌کنن،
# گنجوندنشون باعث می‌شد فایلِ بکاپ چند مگابایت بی‌دلیل بزرگ بشه.
_BACKUP_SKIP_TABLES = {
    "sent_log",          # تاریخچه‌ی «چی ارسال شد» (جلوگیری از ارسالِ دوباره با last_post_id تضمین می‌شه)
    "duplicate_log",     # هش‌های تشخیصِ تکراری
    "sent_message_map",  # نگاشتِ موقتیِ ریپلای (خودش هر ۳۰ روز پروون می‌شه)
    "system_logs",       # لاگِ تشخیصی
    # صفِ تاییدِ ادمین (پست‌های در حالِ انتظار برای تایید/رد). عمداً بکاپ گرفته
    # نمی‌شه: اگه بازیابی بشه، همون لحظه‌ی بازیابی (روی رباتِ جدید یا حتی همونِ
    # ربات) یه مشت پستِ نیمه‌کاره‌ی قدیمی توی صفِ تایید ظاهر می‌شد که ادمین
    # ممکنه ندونسته تایید کنه و باعثِ ارسالِ ناخواسته بشه. با استفاده‌ی عادیِ
    # ربات، این صف از نو و فقط با پست‌های *جدید* پر می‌شه.
    "pending_posts",
}


def to_24h(hour_12: int, minute: int, ampm: str) -> str:
    """تبدیلِ ساعتِ ۱۲ساعته + AM/PM به فرمتِ ۲۴ساعتیِ HH:MM برای ذخیره‌سازی."""
    ampm = ampm.upper()
    h = hour_12 % 12
    if ampm == "PM":
        h += 12
    return f"{h:02d}:{minute:02d}"


def format_backup_time_12h(hhmm: str) -> str:
    """تبدیلِ ساعتِ ذخیره‌شده (۲۴ساعته HH:MM) به نمایشِ ۱۲ساعته با AM/PM
    برای نشون‌دادنِ خواناتر توی دکمه‌ها و پیام‌های تاییدیه."""
    try:
        hour, minute = map(int, hhmm.split(":"))
    except (ValueError, AttributeError):
        return hhmm
    ampm = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12
    if hour_12 == 0:
        hour_12 = 12
    return f"{hour_12:02d}:{minute:02d} {ampm}"


def get_encryption_key() -> bytes:
    """
    کلیدِ رمزنگاریِ بکاپ رو برمی‌گردونه.

    باگِ مهمِ قبلی: این کلید یک مقدارِ *تصادفی* بود که فقط داخلِ خودِ دیتابیس
    ذخیره می‌شد (db.get_setting/set_setting). دقیقاً همین‌جا مشکل بود: وقتی ربات
    پاک می‌شد و از نو نصب می‌شد، یک دیتابیسِ کاملاً خالی ساخته می‌شد، پس اولین
    بارِ اجرا یک کلیدِ رمزنگاریِ *جدید و کاملاً متفاوت* تصادفی تولید می‌کرد. نتیجه:
    فایلِ بکاپِ قدیمی با کلیدِ قدیمی رمزنگاری شده بود ولی نصبِ تازه سعی می‌کرد با
    کلیدِ جدید رمزگشایی‌اش کنه - که همیشه با خطای «فایل بکاپ معتبر نیست» شکست
    می‌خورد. یعنی هدفِ اصلیِ گرفتنِ بکاپ (بازیابیِ کامل بعدِ حذف/نصبِ دوباره) اصلاً
    عملی نبود.

    راه‌حل: کلید دیگه تصادفی و وابسته به دیتابیس نیست؛ به‌طورِ قطعی (deterministic)
    از روی BOT_TOKEN (که همیشه توی فایلِ .env ثابت می‌مونه، چون همون توکنِ همون
    رباته - حتی بعدِ حذف/نصبِ دوباره) ساخته میشه. یعنی تا وقتی همون BOT_TOKEN رو
    توی .env بذاری، دقیقاً همون کلید دوباره ساخته میشه و هر بکاپی که از این به
    بعد گرفته بشه، روی هر نصبِ تازه‌ای (با همون توکن) قابلِ بازیابیه.
    """
    global BACKUP_ENCRYPTION_KEY
    if BACKUP_ENCRYPTION_KEY is None:
        from . import config
        seed = f"uploadgram-backup-key-v2:{config.BOT_TOKEN}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        BACKUP_ENCRYPTION_KEY = base64.urlsafe_b64encode(digest)
    return BACKUP_ENCRYPTION_KEY


def _legacy_db_stored_key() -> bytes | None:
    """
    کلیدِ رمزنگاریِ (تصادفیِ) نسخه‌ی قدیمی که ممکنه هنوز توی جدولِ settings
    همینِ دیتابیسِ فعلی باقی مونده باشه - فقط برای «best effort» رمزگشاییِ
    بکاپ‌های خیلی قدیمی که با نسخه‌ی قبل از این اصلاح گرفته شدن و دیتابیس هم
    عوض نشده (سناریوی نادر، ولی رایگانه که امتحانش کنیم).
    """
    try:
        raw = db.get_setting("backup_encryption_key", "")
        if raw:
            return raw.encode("utf-8")
    except Exception:
        pass
    return None


def encrypt_data(data: bytes) -> bytes:
    """رمزنگاری داده با Fernet (همیشه با کلیدِ قطعیِ فعلی، برای بکاپ‌های جدید)"""
    fernet = Fernet(get_encryption_key())
    return fernet.encrypt(data)


def decrypt_data(encrypted: bytes) -> bytes:
    """
    رمزگشاییِ داده با Fernet. اول با کلیدِ قطعیِ فعلی (از روی BOT_TOKEN) امتحان
    می‌کنه؛ اگه نشد (مثلاً فایل با نسخه‌ی خیلی قدیمی‌تر از ربات گرفته شده)، به‌عنوانِ
    آخرین راه‌حل کلیدِ قدیمیِ ذخیره‌شده در همین دیتابیس (اگه هنوز باشه) رو هم
    امتحان می‌کنه.
    """
    candidates = [get_encryption_key()]
    legacy = _legacy_db_stored_key()
    if legacy and legacy not in candidates:
        candidates.append(legacy)

    last_error: Exception | None = None
    for key in candidates:
        try:
            return Fernet(key).decrypt(encrypted)
        except (InvalidToken, ValueError, Exception) as e:  # noqa: BLE001 - می‌خوایم هر خطایی رو رد کنیم و کلیدِ بعدی رو امتحان کنیم
            last_error = e
            continue
    raise last_error if last_error else InvalidToken("رمزگشایی با هیچ کلیدی موفق نشد.")


def _all_table_names() -> list[str]:
    """
    اسمِ همه‌ی جدول‌های واقعیِ دیتابیس رو برمی‌گردونه (نه یک لیستِ هاردکدشده).
    باگِ قبلی: create_backup فقط یک لیستِ ثابت از ۹ جدول رو بکاپ می‌گرفت و
    جدول‌های جدیدتر (duplicate_log، channel_stats، system_logs) اصلاً توی بکاپ
    نبودن - یعنی بعدِ بازیابی، لاگ‌های سیستم/آمار/تاریخچه‌ی فیلترِ تکراری برای
    همیشه گم می‌شدن. با گرفتنِ لیست مستقیماً از sqlite_master، هر جدولی که الان
    باشه یا در آینده اضافه بشه خودکار پوشش داده میشه.
    """
    rows = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def _row_to_json_safe(row: dict) -> dict:
    """
    ستون‌های BLOB (مثلِ override_photo/override_video توی pending_posts) رو به‌صورتِ base64
    نگه می‌داره. باگِ قبلی: json.dumps(..., default=str) روی bytes صدا زده
    می‌شد و str(b'...') یک نمایشِ متنیِ غیرقابل‌بازگشتِ بایت‌ها بود (مثلاً
    "b'\\x89PNG...'") - یعنی هر پستِ در صفِ تایید که عکسِ جایگزین (override) داشت،
    بعدِ بازیابی عکسش کاملاً خراب/غیرقابل‌استفاده می‌شد. حالا bytes با base64
    دقیق و کامل رفت‌وبرگشت می‌کنه.
    """
    out = {}
    for k, v in row.items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = {"__blob_b64__": base64.b64encode(bytes(v)).decode("ascii")}
        else:
            out[k] = v
    return out


def _json_safe_to_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, dict) and "__blob_b64__" in v:
            out[k] = base64.b64decode(v["__blob_b64__"])
        else:
            out[k] = v
    return out


# ==================================================================
# بکاپ/بازیابیِ تنظیماتِ فایلِ .env (توکن، آیدی ادمین‌ها، کلیدهای API، ...)
# ==================================================================
# باگِ مهمِ قبلی: بکاپ فقط از دیتابیس (sqlite) گرفته می‌شد. یعنی مهم‌ترین
# «ریزترین تنظیمات» ربات - BOT_TOKEN، ADMIN_IDS، TARGET_CHAT_ID و همه‌ی
# کلیدهای API (Mistral/Groq/Pollinations/DeepAI/Stable Horde) که همیشه توی
# فایلِ .env (نه دیتابیس) ذخیره می‌شن - اصلاً توی بکاپ نبودن. نتیجه: اگه
# سرور/ربات کاملاً پاک می‌شد، حتی با بازیابیِ موفقِ دیتابیس، باز هم باید همه‌ی
# این مقادیر رو از حفظ یا از یادداشتِ جدا دوباره وارد می‌کردی. حالا مقدارِ
# *واقعیِ در حالِ اجرا*ی هرکدوم (چه از .env خونده شده باشه، چه مقدارِ
# پیش‌فرضِ کدشده باشه) مستقیماً از ماژولِ config خونده و توی بکاپ ذخیره میشه.
_ENV_BACKUP_SPEC: list[tuple[str, str, "callable"]] = [
    ("BOT_TOKEN", "BOT_TOKEN", str),
    ("ADMIN_IDS", "ADMIN_IDS", lambda v: ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)),
    ("TARGET_CHAT_ID_ENV", "TARGET_CHAT_ID", str),
    ("DB_PATH", "DB_PATH", str),
    ("TIMEZONE", "TIMEZONE", str),
    ("MAX_CONCURRENT_HEAVY_JOBS", "MAX_CONCURRENT_HEAVY_JOBS", str),
    ("DOWNLOAD_CACHE_MAX_ITEMS", "DOWNLOAD_CACHE_MAX_ITEMS", str),
    ("DOWNLOAD_CACHE_TTL_SECONDS", "DOWNLOAD_CACHE_TTL_SECONDS", str),
    ("TEMPLATE_MATCH_THRESHOLD", "TEMPLATE_MATCH_THRESHOLD", str),
    ("MAX_WATERMARK_AREA_RATIO", "MAX_WATERMARK_AREA_RATIO", str),
    ("MISTRAL_API_KEY", "MISTRAL_API_KEY", str),
    ("GROQ_API_KEY", "GROQ_API_KEY", str),
    ("POLLINATIONS_API_KEY", "POLLINATIONS_API_KEY", str),
    ("DEEPAI_API_KEY", "DEEPAI_API_KEY", str),
    ("STABLEHORDE_API_KEY", "STABLEHORDE_API_KEY", str),
    ("IMAGE_GEN_TIMEOUT", "IMAGE_GEN_TIMEOUT", str),
    ("IMAGE_GEN_MAX_RETRIES", "IMAGE_GEN_MAX_RETRIES", str),
    ("STABLEHORDE_POLL_TIMEOUT", "STABLEHORDE_POLL_TIMEOUT", str),
    ("STABLEHORDE_POLL_INTERVAL", "STABLEHORDE_POLL_INTERVAL", str),
]


def _collect_env_backup() -> dict:
    """مقادیرِ فعلیِ در حالِ اجرای تنظیماتِ .env رو برای قرار گرفتن توی بکاپ جمع می‌کنه."""
    from . import config
    out: dict = {}
    for attr_name, env_key, formatter in _ENV_BACKUP_SPEC:
        if not hasattr(config, attr_name):
            continue
        try:
            value = getattr(config, attr_name)
            out[env_key] = formatter(value)
        except Exception as e:
            log.warning("خواندنِ مقدارِ «%s» برای بکاپِ تنظیمات ناموفق بود: %s", attr_name, e)
    return out



# کلیدهایی که موقعِ بازیابی هرگز نباید از بکاپ رونویسی بشن (توکنِ فعلی و مسیرِ
# دیتابیسِ فعلی همیشه باید ارجحیت داشته باشن؛ مثلاً اگه توکن به‌خاطرِ امنیت
# rotate شده باشه، بازیابیِ توکنِ قدیمی می‌تونه ربات رو از کار بندازه).
ENV_SKIP_KEYS = {"BOT_TOKEN", "DB_PATH"}
# کلیدهایی که به‌جای رونویسی، «اجتماع» (union) مقدارِ فعلی و بکاپ می‌شن؛ چون
# لیستی هستن (مثل آیدیِ ادمین‌ها) و رونویسیِ کامل ممکنه ادمین‌هایِ جدید رو حذف کنه.
ENV_MERGE_UNION_KEYS = {"ADMIN_IDS"}


def _apply_env_backup(env_dict: dict) -> tuple[list[str], list[str]]:
    """
    مقادیرِ بکاپ‌شده رو توی فایلِ .env می‌نویسه (خط‌های موجود رو آپدیت می‌کنه،
    خط‌های جدید رو به آخر اضافه می‌کنه، بقیه‌ی فایل دست‌نخورده می‌مونه).
    این عملیات «best effort» است: هر خطایی (مثلاً نبودِ دسترسیِ نوشتن) فقط
    لاگ/گزارش می‌شه و باعثِ شکستِ کلِ بازیابی نمیشه، چون دیتابیس مهم‌تره.

    قبل از نوشتن، اگه BOT_TOKEN/DB_PATH توی env_dict باشن نادیده گرفته می‌شن
    (مقدارِ فعلی حفظ می‌شه) و ADMIN_IDS به‌جای رونویسی، اجتماع (union) می‌شه.
    """
    from . import config
    updated: list[str] = []
    errors: list[str] = []
    if not env_dict:
        return updated, errors

    env_path = config.BASE_DIR / ".env"
    lines: list[str] = []
    try:
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        errors.append(f".env (خواندن): {e}")

    existing_keys: dict[str, int] = {}
    current_vals: dict[str, str] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            k = k.strip()
            existing_keys[k] = idx
            current_vals[k] = v.strip()

    # قبل از هر نوشتنی یک نسخه‌ی .bak_* از .env فعلی گرفته می‌شه تا در صورتِ
    # بروزِ مشکل، بازگردانیِ دستی ممکن باشه.
    if lines:
        try:
            backup_path = env_path.with_name(env_path.name + f".bak_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
            shutil.copyfile(env_path, backup_path)
        except Exception:
            log.warning("گرفتنِ نسخه‌ی پشتیبان از .env قبل از بازیابی ناموفق بود؛ نوشتن ادامه پیدا می‌کند.")

    for key, value in env_dict.items():
        if key in ENV_SKIP_KEYS:
            continue
        value = "" if value is None else str(value)
        if key in ENV_MERGE_UNION_KEYS:
            cur_ids = [x.strip() for x in current_vals.get(key, "").split(",") if x.strip()]
            bak_ids = [x.strip() for x in value.split(",") if x.strip()]
            value = ",".join(cur_ids + [x for x in bak_ids if x not in cur_ids])
            if value == current_vals.get(key, ""):
                continue
        new_line = f"{key}={value}"
        if key in existing_keys:
            lines[existing_keys[key]] = new_line
        else:
            lines.append(new_line)
        updated.append(key)

    if not updated:
        return updated, errors

    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        errors.append(f".env (نوشتن): {e}")
        updated.clear()

    return updated, errors


# ==================================================================
# بکاپ/بازیابیِ فایل‌های الگوهای واترمارک (data/watermark_templates)
# ==================================================================
# باگِ مهمِ قبلی: الگوهای دستیِ واترمارک (فایل‌های تصویریِ اضافه‌شده توسط
# ادمین برای تشخیصِ بهترِ حذفِ خودکار واترمارک) فقط روی دیسک بودن و توی هیچ
# جدولِ دیتابیسی ثبت نمی‌شدن - یعنی با پاک‌شدنِ سرور، این فایل‌ها برای همیشه
# از دست می‌رفتن، حتی با بازیابیِ کاملِ دیتابیس.
def _collect_watermark_templates() -> dict:
    from . import config
    result: dict = {}
    try:
        for p in sorted(config.WATERMARK_TEMPLATES_DIR.iterdir()):
            if not p.is_file() or p.name == ".gitkeep":
                continue
            try:
                result[p.name] = base64.b64encode(p.read_bytes()).decode("ascii")
            except Exception as e:
                log.warning("خواندنِ فایلِ الگوی واترمارکِ «%s» برای بکاپ ناموفق بود: %s", p.name, e)
    except Exception as e:
        log.warning("خواندنِ پوشه‌ی الگوهای واترمارک برای بکاپ ناموفق بود: %s", e)
    return result


def _apply_watermark_templates(templates: dict) -> tuple[list[str], list[str]]:
    from . import config
    restored: list[str] = []
    errors: list[str] = []
    if not templates:
        return restored, errors

    try:
        config.WATERMARK_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"پوشه‌ی الگوهای واترمارک: {e}")
        return restored, errors

    for filename, b64_content in templates.items():
        safe_name = os.path.basename(filename)
        if not safe_name:
            continue
        try:
            content = base64.b64decode(b64_content)
            (config.WATERMARK_TEMPLATES_DIR / safe_name).write_bytes(content)
            restored.append(safe_name)
        except Exception as e:
            log.warning("بازیابیِ فایلِ الگوی واترمارکِ «%s» ناموفق بود: %s", filename, e)
            errors.append(safe_name)

    # کشِ حافظه‌ای الگوهای واترمارک (اگه ربات بدونِ ری‌استارتِ کامل ادامه پیدا کنه) رو خالی می‌کنیم
    # تا فایل‌های تازه‌بازیابی‌شده در اولین استفاده‌ی بعدی دوباره از دیسک خونده بشن.
    try:
        from . import ai_watermark
        ai_watermark._templates = None
    except Exception:
        pass

    return restored, errors


# ==================================================================
# همگام‌سازیِ last_post_id بعدِ بازیابی (جلوگیری از سیلِ پست‌های عقب‌افتاده)
# ==================================================================
async def resync_channels_after_restore() -> tuple[int, int]:
    """
    بعدِ بازیابیِ موفقِ یک بکاپ - مخصوصاً وقتی روی یک ربات/توکن/اکانتِ کاملاً
    تازه انجام می‌شه - این تابع last_post_id هر کانالِ مبدأ رو روی «آخرین
    پستِ فعلیِ همون کانال در تلگرام» تنظیم می‌کنه (نه صفر، نه همون مقدارِ
    قدیمیِ داخلِ بکاپ).

    چرا لازمه: تنظیمات/کانال‌ها/مقصدها/کاربرها همه از بکاپ درست بازیابی
    می‌شن، ولی last_post_id قدیمی (مالِ لحظه‌ی گرفتنِ بکاپ) می‌تونه خیلی
    عقب‌تر از آخرین پستِ واقعیِ کانال باشه. اگه همون مقدار می‌موند، بلافاصله
    بعدِ بازیابی و روشن‌شدنِ ربات، همه‌ی پست‌هایی که در این فاصله منتشر شدن
    (شاید ده‌ها پست) یک‌جا به‌عنوانِ «پستِ جدید» شناسایی و به مقصد ارسال
    می‌شدن - یعنی دقیقاً همون چیزی که نمی‌خوایم (سیلِ پست‌های قدیمی بلافاصله
    بعدِ بازیابی). با این کار، فقط تنظیمات/چیدمان بازیابی می‌شه و ارسال فقط
    از *اولین پستِ تازه‌ای که از این لحظه به بعد در مبدأ منتشر بشه* شروع
    می‌شه - دقیقاً مثلِ اضافه‌کردنِ یک کانالِ کاملاً نو.

    این عملیات «best effort» است: خطای هر کانال (مثلاً یوزرنیمِ نامعتبر یا
    کانالِ موقتاً در دسترس‌نبودن) فقط لاگ می‌شه و روی بقیه‌ی کانال‌ها تاثیر
    نمی‌ذاره؛ چنین کانالی صرفاً last_post_id قدیمی‌اش می‌مونه.

    بازگشت: (تعدادِ کانال‌هایی که همگام‌سازی موفق بود، تعدادِ ناموفق)
    """
    from .scraper import fetch_latest_post_id, ScraperError

    ok, failed = 0, 0
    for ch in db.list_channels():
        username = ch["username"] if "username" in ch.keys() else None
        if not username:
            continue
        try:
            latest_id = await fetch_latest_post_id(username)
            db.update_last_post(ch["id"], latest_id)
            ok += 1
            log.info("last_post_id کانالِ @%s بعدِ بازیابی روی %s تنظیم شد.", username, latest_id)
        except ScraperError as e:
            failed += 1
            log.warning("همگام‌سازیِ last_post_id برایِ @%s بعدِ بازیابی ناموفق بود: %s", username, e)
        except Exception as e:
            failed += 1
            log.warning("خطای غیرمنتظره در همگام‌سازیِ last_post_id برایِ @%s: %s", username, e)
    return ok, failed


class BackupManager:
    """مدیریت بکاپ خودکار و بازیابی"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.running = False

    @staticmethod
    def get_settings() -> dict:
        """دریافت تنظیمات بکاپ"""
        raw = db.get_setting(BACKUP_SETTINGS_KEY, "{}")
        try:
            return json.loads(raw)
        except Exception:
            return {
                "enabled": True,
                "time": BACKUP_TIME_DEFAULT,
                "chat_id": None,  # آیدی کانال یا چت برای ارسال بکاپ
                "last_backup": None,
                "keep_local": True,  # نگهداری فایل بکاپ روی سرور
            }

    @staticmethod
    def save_settings(settings: dict):
        """ذخیره تنظیمات بکاپ"""
        db.set_setting(BACKUP_SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))

    @staticmethod
    def create_backup() -> bytes:
        """
        ایجاد فایل بکاپ رمزنگاری‌شده از دیتابیس. همه‌ی جدول‌ها گرفته می‌شن *به‌جز*
        جدول‌های پرحجمِ عملیاتی (لاگ/تاریخچه/آمار) که بعد از بازیابی به‌درد نمی‌خورن
        و فقط فایلِ بکاپ رو بی‌دلیل چند مگابایت بزرگ می‌کنن (نگاه کن به
        _BACKUP_SKIP_TABLES). این جدول‌ها با استفاده‌ی عادیِ ربات دوباره ساخته می‌شن،
        پس نبودشون در بکاپ هیچ تنظیمات/کانال/مقصدی رو از دست نمی‌ده.
        """
        log.info("شروع ایجاد بکاپ از دیتابیس...")

        all_tables = _all_table_names()
        table_names = [t for t in all_tables if t not in _BACKUP_SKIP_TABLES]
        skipped = [t for t in all_tables if t in _BACKUP_SKIP_TABLES]
        data: dict = {}
        for table in table_names:
            rows = db._conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [_row_to_json_safe(dict(row)) for row in rows]

        # تنظیماتِ فایلِ .env (توکن، آیدیِ ادمین‌ها، کلیدهای API و ...) - ریزترین تنظیمات
        env_config = _collect_env_backup()
        data["env_config"] = env_config

        # فایل‌های الگوی واترمارک (data/watermark_templates)
        watermark_templates = _collect_watermark_templates()
        data["watermark_templates"] = watermark_templates

        data["backup_metadata"] = {
            "created_at": datetime.utcnow().isoformat(),
            "version": "4.1.0",
            "tables": table_names,
            "skipped_tables": skipped,
            "env_keys": sorted(env_config.keys()),
            "watermark_template_files": sorted(watermark_templates.keys()),
            "checksum": "",
        }

        # JSONِ فشرده (بدونِ indent) - چون فایل رمزنگاری می‌شه و کسی خامش رو نمی‌خونه،
        # فاصله‌گذاریِ زیبا فقط حجم رو زیاد می‌کرد.
        _compact = dict(ensure_ascii=False, separators=(",", ":"), default=str)
        json_str = json.dumps(data, **_compact)

        # محاسبه checksum (برای تشخیصِ دستکاری/خرابیِ احتمالیِ فایل هنگامِ بازیابی)
        checksum = hashlib.sha256(json_str.encode('utf-8')).hexdigest()
        data["backup_metadata"]["checksum"] = checksum
        json_str = json.dumps(data, **_compact)

        payload = json_str.encode('utf-8')
        password = get_backup_password()
        if password:
            # فرمتِ جدید: با رمزِ عبورِ ادمین رمزنگاری می‌شه، مستقل از BOT_TOKEN -
            # قابلِ بازیابی روی هر ربات/توکن/اکانتِ دیگه‌ای، به شرطِ داشتنِ همین رمز.
            encrypted = encrypt_data_with_password(payload, password)
        else:
            # هنوز رمزی ست نشده: برای سازگاریِ عقب‌رو، فرمتِ قدیمیِ وابسته به
            # BOT_TOKEN استفاده می‌شه (فقط روی همین ربات/توکن قابلِ بازیابیه).
            encrypted = encrypt_data(payload)
            log.warning(
                "برای بکاپ هیچ رمزِ عبوری ست نشده؛ این بکاپ فقط با همین BOT_TOKEN قابلِ بازیابیه. "
                "برای بازیابیِ قابلِ‌جابجایی بینِ توکن‌ها/اکانت‌ها، از منویِ بکاپ یک رمز ست کن."
            )
        log.info(
            "بکاپ ایجاد شد (%s جدول، %s جدولِ عملیاتیِ رد شده، %s کلیدِ تنظیمات، "
            "%s فایلِ الگوی واترمارک، حجم: %s کیلوبایت، محافظت‌شده‌با‌رمز: %s)",
            len(table_names), len(skipped), len(env_config),
            len(watermark_templates), len(encrypted) // 1024, bool(password),
        )
        return encrypted

    @staticmethod
    def restore_backup(encrypted_data: bytes, password: str | None = None) -> tuple[bool, str]:
        """
        بازیابیِ کاملِ دیتابیس از فایل بکاپ - همه‌ی جدول‌هایی که توی فایلِ بکاپ
        هستن (نه فقط یک لیستِ ثابت)، با تلاشِ حداکثری برای برگردوندنِ هرچی که
        می‌شه، حتی اگه یک جدول یا یک ستون بینِ نسخه‌ی قدیمی و فعلیِ ربات فرق
        کرده باشه (به‌جای اینکه کلِ عملیات به‌خاطرِ یک جدول شکست بخوره و همه‌چیز
        خالی بمونه).

        اگه فایل با فرمتِ رمزِ‌عبوریِ جدید (PWBK1) باشه، پارامترِ password باید
        دستی از کاربر گرفته شده باشه (این تابع خودش هیچ رمزی رو حدس نمی‌زنه).
        بکاپ‌های قدیمیِ وابسته به BOT_TOKEN بدونِ password هم قابلِ بازیابی‌ان.

        بازگشت: (موفقیت, پیام)
        """
        log.info("شروع بازیابی دیتابیس از بکاپ...")

        try:
            if is_password_protected_backup(encrypted_data):
                if not password:
                    return False, "این فایل بکاپ با رمزِ عبور محافظت شده؛ لطفاً رمز را وارد کنید."
                decrypted = decrypt_data_with_password(encrypted_data, password)
            else:
                decrypted = decrypt_data(encrypted_data)
            data = json.loads(decrypted.decode('utf-8'))
        except InvalidToken:
            log.warning("رمزگشاییِ فایلِ بکاپ با رمزِ واردشده ناموفق بود (رمز اشتباه یا فایل خراب).")
            return False, "رمزِ واردشده اشتباه است یا فایلِ بکاپ خراب/دستکاری‌شده است."
        except Exception as e:
            log.error("خطا در رمزگشایی یا تحلیل فایل بکاپ: %s", e)
            return False, f"فایل بکاپ معتبر نیست یا با کلیدِ فعلی جور در نمیاد: {e}"

        # بررسی متادیتا
        metadata = data.get("backup_metadata", {})
        if not metadata:
            return False, "فایل بکاپ فاقد متادیتا است"

        log.info("بازیابی از بکاپ تاریخ: %s", metadata.get("created_at", "نامشخص"))

        # صحت‌سنجیِ checksum - فقط برای هشدار (مانعِ بازیابی نمیشه، چون شاید
        # بکاپ با نسخه‌ی قدیمی‌تری از ربات گرفته شده که فرمتِ دقیقاً یکسانی
        # نداشته و checksum اصلاً قابلِ مقایسه نیست).
        stored_checksum = metadata.get("checksum", "")
        if stored_checksum:
            try:
                check_data = dict(data)
                check_meta = dict(metadata)
                check_meta["checksum"] = ""
                check_data["backup_metadata"] = check_meta
                # فیکسِ R6: چک‌سام باید *دقیقاً* با همون سریال‌سازیِ زمانِ ساخت
                # محاسبه بشه (separators فشرده، نه indent=2). قبلاً اینجا indent=2
                # بود در حالی که create_backup فشرده می‌ساخت ← چک‌سام همیشه mismatch
                # می‌شد و هشدارِ «فایل ناقص/دستکاری‌شده» بی‌دلیل و همیشه چاپ می‌شد.
                recomputed = hashlib.sha256(
                    json.dumps(
                        check_data, ensure_ascii=False, separators=(",", ":"), default=str
                    ).encode("utf-8")
                ).hexdigest()
                if recomputed != stored_checksum:
                    log.warning(
                        "چک‌سامِ فایلِ بکاپ با محتوای آن یکی نیست (ممکنه فایل ناقص/دستکاری‌شده باشه یا "
                        "با نسخه‌ی قدیمی‌تری از ربات گرفته شده باشه) - بازیابی ادامه پیدا می‌کنه ولی احتیاط کن."
                    )
            except Exception:
                pass

        conn = db._conn
        cursor = conn.cursor()
        # فیکسِ M8: کلِ بازیابی روی کانکشنِ سراسریِ db._conn انجام می‌شه؛ باید با
        # همون قفلی که بقیه‌ی نوشتن‌های database.py می‌گیرن هماهنگ باشه، وگرنه یک
        # نوشتنِ هم‌زمان (مثلاً از حلقه‌ی scheduler) وسطِ DELETE/INSERTهای بازیابی
        # می‌تونه «database is locked» یا داده‌ی ناهماهنگ بسازه. این قفل غیرِری‌اِنترانته
        # و بازیابی هیچ تابعِ database.py ای که خودش قفل بگیره صدا نمی‌زنه، پس امنه.
        _db_lock.acquire()
        cursor.execute("PRAGMA foreign_keys = OFF")

        # این کلیدهای سطحِ بالا جدولِ دیتابیس نیستن (تنظیماتِ .env و فایل‌های
        # الگوی واترمارک)، پس نباید به‌عنوانِ جدول با آن‌ها رفتار بشه.
        _non_table_keys = {"backup_metadata", "env_config", "watermark_templates"}
        _valid_table_name = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        tables_in_backup = [
            k for k in data.keys()
            if k not in _non_table_keys and _valid_table_name.match(k)
        ]
        _rejected_table_keys = [
            k for k in data.keys()
            if k not in _non_table_keys and not _valid_table_name.match(k)
        ]
        if _rejected_table_keys:
            log.warning(
                "کلید(های) %s در فایلِ بکاپ به‌عنوانِ نامِ جدول نامعتبرن (کاراکترهای غیرمجاز) و "
                "به‌خاطرِ جلوگیری از SQL injection نادیده گرفته شدن.", _rejected_table_keys,
            )
        restored_tables: list[str] = []
        skipped_tables: list[str] = []
        failed_tables: list[str] = []

        try:
            for table in tables_in_backup:
                rows = data.get(table) or []
                # فیکسِ C1: هر جدول توی یک SAVEPOINTِ مستقل بازیابی می‌شه. قبلاً اگه
                # وسطِ INSERTهای یک جدول خطایی می‌داد، DELETEِ همون جدول از قبل اعمال
                # شده بود و در پایان commit می‌شد ← جدول برای همیشه خالی/نیمه‌کاره
                # (از دست رفتنِ قطعیِ داده). حالا خطای یک جدول فقط همون جدول رو به
                # حالتِ قبل برمی‌گردونه و بقیه‌ی جدول‌های سالم دست‌نخورده می‌مونن.
                savepoint = f"restore_{table}"
                try:
                    exists = cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    if not exists:
                        log.warning(
                            "جدولِ «%s» توی بکاپ هست ولی توی دیتابیسِ فعلی وجود نداره (احتمالاً نسخه‌ی خیلی "
                            "قدیمی‌تر یا خیلی جدیدتره)؛ رد شد.", table,
                        )
                        skipped_tables.append(table)
                        continue

                    cursor.execute(f'SAVEPOINT "{savepoint}"')
                    current_cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()]

                    cursor.execute(f"DELETE FROM {table}")
                    try:
                        cursor.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
                    except Exception:
                        pass

                    if rows:
                        backup_cols = list(rows[0].keys())
                        usable_cols = [c for c in backup_cols if c in current_cols]
                        dropped_cols = [c for c in backup_cols if c not in current_cols]
                        if dropped_cols:
                            log.warning(
                                "ستون(های) %s توی جدولِ «%s» دیگه در نسخه‌ی فعلیِ دیتابیس وجود نداره؛ "
                                "فقط همین ستون‌ها نادیده گرفته میشن (بقیه‌ی داده‌ی همون ردیف‌ها سالم بازیابی میشه).",
                                dropped_cols, table,
                            )
                        if usable_cols:
                            placeholders = ", ".join(["?"] * len(usable_cols))
                            query = f"INSERT INTO {table} ({', '.join(usable_cols)}) VALUES ({placeholders})"
                            for row in rows:
                                safe_row = _json_safe_to_row(row)
                                values = [safe_row.get(col) for col in usable_cols]
                                cursor.execute(query, values)

                        if "id" in current_cols and "id" in usable_cols:
                            try:
                                max_id = cursor.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
                                if max_id:
                                    cursor.execute(
                                        "UPDATE sqlite_sequence SET seq=? WHERE name=?", (max_id, table),
                                    )
                            except Exception:
                                pass

                    cursor.execute(f'RELEASE "{savepoint}"')
                    restored_tables.append(table)
                except Exception as e:
                    # فیکسِ C1: فقط همین جدول رو به حالتِ قبل از DELETE برگردون.
                    try:
                        cursor.execute(f'ROLLBACK TO "{savepoint}"')
                        cursor.execute(f'RELEASE "{savepoint}"')
                    except Exception:
                        log.debug("برگردوندنِ SAVEPOINTِ جدولِ «%s» ناموفق بود.", table, exc_info=True)
                    log.exception(
                        "بازیابیِ جدولِ «%s» با خطا مواجه شد؛ این جدول به حالتِ قبل برگشت و بازیابیِ بقیه ادامه پیدا می‌کنه: %s",
                        table, e,
                    )
                    failed_tables.append(table)
                    continue

            # فیکسِ C2: commit باید *قبل* از روشن‌کردنِ FK باشه. PRAGMA foreign_keys
            # داخلِ تراکنشِ باز no-op است؛ قبلاً درست قبل از commit صدا زده می‌شد و
            # هیچ‌وقت اثر نمی‌کرد ← FK تا آخرِ عمرِ کانکشنِ سراسری خاموش می‌موند.
            conn.commit()
            cursor.execute("PRAGMA foreign_keys = ON")

            # فیکسِ C1: اگه جدولی با خطا مواجه شده، سرتیترِ پیام «ناقص» باشه نه «✅
            # انجام شد»، تا کاربر متوجه بشه بازیابی کامل نبوده و بتونه تصمیم بگیره.
            head = "⚠️ بازیابی ناقص انجام شد" if failed_tables else "✅ بازیابی انجام شد"
            msg = f"{head} ({len(restored_tables)} جدول کامل بازیابی شد"
            if skipped_tables:
                msg += f"، {len(skipped_tables)} جدولِ ناموجود در نسخه‌ی فعلی رد شد ({', '.join(skipped_tables)})"
            if failed_tables:
                msg += f"، {len(failed_tables)} جدول با خطا مواجه شد و به حالتِ قبل برگشت ({', '.join(failed_tables)})"
            msg += ")."

            # ==================== بازیابیِ تنظیماتِ .env (بست‌افورت، هرگز باعثِ شکستِ کلِ بازیابی نمیشه) ====================
            env_config = dict(data.get("env_config") or {})
            # BOT_TOKEN رو هرگز خودکار بازنویسی نمی‌کنیم: توی مسیرِ عادی (رمزگشاییِ موفق با
            # کلیدِ فعلیِ مشتق‌شده از BOT_TOKEN) این مقدار همینِ الان هم با توکنِ فعال یکیه،
            # پس بازنویسی‌اش بی‌اثره؛ ولی توی مسیرِ کلیدِ قدیمیِ fallback ممکنه بکاپ متعلق به
            # توکنِ دیگه‌ای باشه که بازنویسیِ خودکارش می‌تونه رباتِ در حالِ اجرا رو بعدِ ری‌استارت
            # کاملاً از کار بندازه (توکنِ اشتباه/باطل‌شده).
            env_config.pop("BOT_TOKEN", None)
            if env_config:
                try:
                    updated_keys, env_errors = _apply_env_backup(env_config)
                    if updated_keys:
                        msg += f"\n🔑 {len(updated_keys)} کلیدِ تنظیماتِ .env بازیابی شد (ADMIN_IDS، کلیدهای API و بقیه‌ی تنظیمات؛ BOT_TOKEN برای احتیاط دست‌نخورده موند)."
                    if env_errors:
                        msg += f"\n⚠️ برخی تنظیماتِ .env بازیابی نشدن: {', '.join(env_errors)}"
                except Exception as e:
                    log.exception("بازیابیِ تنظیماتِ .env با خطای غیرمنتظره مواجه شد: %s", e)
                    msg += f"\n⚠️ بازیابیِ تنظیماتِ .env ناموفق بود: {e}"

            # ==================== بازیابیِ فایل‌های الگوی واترمارک (بست‌افورت) ====================
            watermark_templates = data.get("watermark_templates") or {}
            if watermark_templates:
                try:
                    restored_files, file_errors = _apply_watermark_templates(watermark_templates)
                    if restored_files:
                        msg += f"\n🖼 {len(restored_files)} فایلِ الگوی واترمارک بازیابی شد."
                    if file_errors:
                        msg += f"\n⚠️ برخی فایل‌های الگوی واترمارک بازیابی نشدن: {', '.join(file_errors)}"
                except Exception as e:
                    log.exception("بازیابیِ فایل‌های الگوی واترمارک با خطای غیرمنتظره مواجه شد: %s", e)
                    msg += f"\n⚠️ بازیابیِ فایل‌های الگوی واترمارک ناموفق بود: {e}"

            log.info(msg)
            return True, msg

        except Exception as e:
            conn.rollback()
            # فیکسِ C2: حتی در مسیرِ خطا هم FK باید دوباره روشن بشه؛ الان دیگه
            # rollback شده و تراکنشی باز نیست، پس این PRAGMA واقعاً اثر می‌کنه.
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
            except Exception:
                log.debug("روشن‌کردنِ دوباره‌ی FK بعد از خطای بازیابی ناموفق بود.", exc_info=True)
            log.exception("خطای کلی و غیرمنتظره در بازیابی دیتابیس: %s", e)
            return False, f"خطا در بازیابی: {e}"
        finally:
            # فیکسِ M8: قفلِ سراسری روی هر مسیرِ خروج (موفق/ناموفق) آزاد بشه.
            try:
                _db_lock.release()
            except RuntimeError:
                pass

    async def run_daily_backup(self):
        """حلقه اصلی بکاپ روزانه در ساعت مشخص"""
        self.running = True
        log.info("سرویس بکاپ روزانه راه‌اندازی شد")

        while self.running:
            try:
                settings = self.get_settings()
                if not settings.get("enabled", True):
                    await asyncio.sleep(60)
                    continue

                now = now_jalali()
                target_time = settings.get("time", BACKUP_TIME_DEFAULT)
                target_hour, target_minute = map(int, target_time.split(":"))

                # محاسبه زمان بعدی
                next_run = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                if now >= next_run:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                log.debug("زمان بعدی بکاپ: %s (انتظار %s ثانیه)", format_jalali_datetime(next_run), wait_seconds)
                await asyncio.sleep(wait_seconds)

                # باگِ قبلی: بعدِ بیدارشدن از خواب، همون شیِ settings قدیمی (که قبل از
                # sleep - یعنی تا ۲۴ ساعتِ پیش - خونده شده بود) استفاده می‌شد. یعنی اگه
                # کاربر توی همین بازه‌ی sleep ساعتِ بکاپ یا کانالِ مقصد رو عوض می‌کرد،
                # اون تغییر اصلاً روی همین دورِ بکاپ اعمال نمی‌شد (بکاپ به کانالِ
                # قدیمی/چتِ پیش‌فرضِ ادمین می‌رفت، نه کانالی که تازه ست شده بود) و فقط
                # از فردا اعمال می‌شد. الان درست قبل از اجرای بکاپ دوباره از دیتابیس
                # خونده میشه تا همیشه آخرین تنظیمات (فعال/غیرفعال، ساعت، chat_id) اعمال بشه.
                settings = self.get_settings()
                if not settings.get("enabled", True):
                    log.info("بکاپ روزانه غیرفعال شده (در حینِ انتظار)؛ این دور رد شد.")
                    continue

                # انجام بکاپ
                log.info("شروع بکاپ روزانه...")
                # اول دیتابیس رو پاک‌سازی می‌کنیم (جدول‌های انباشتیِ pending_posts/
                # sent_log/duplicate_log و...) تا هم فایلِ دیتابیس و هم خودِ بکاپ کوچیک
                # بمونن. چون بکاپ بعد از این گرفته می‌شه، مستقیماً از این پاک‌سازی سود می‌بره.
                try:
                    db.run_maintenance()
                except Exception as e:  # noqa: BLE001 - پاک‌سازی نباید جلوی بکاپ رو بگیره
                    log.warning("پاک‌سازیِ قبل از بکاپ شکست خورد (نادیده گرفته شد): %s", e)
                encrypted = self.create_backup()

                # ذخیره روی سرور
                # فیکسِ R5: قبلاً backup_dir با db.path.replace("bot.sqlite","backups")
                # ساخته می‌شد که فقط برای مسیرِ پیش‌فرض کار می‌کرد؛ با هر DB_PATHِ
                # سفارشی (مثلاً bot_prod.sqlite یا مسیری بدونِ کلمه‌ی bot.sqlite)
                # نتیجه یک مسیرِ غلط بود. حالا از دایرکتوریِ واقعیِ فایلِ دیتابیس
                # مشتق می‌شه، مستقل از نامِ فایل.
                backup_dir = os.path.join(os.path.dirname(os.path.abspath(db.path)) or ".", "backups")
                os.makedirs(backup_dir, exist_ok=True)

                backup_filename = f"backup_{now.strftime('%Y%m%d_%H%M')}.backup"
                backup_path = os.path.join(backup_dir, backup_filename)

                with open(backup_path, "wb") as f:
                    f.write(encrypted)
                log.info("فایل بکاپ ذخیره شد: %s", backup_path)

                # حذف بکاپ‌های قدیمی
                # فیکسِ R5: فایلِ بکاپ همیشه (بی‌قید به keep_local) نوشته می‌شه.
                # قبلاً پاکسازیِ قدیمی‌ها فقط وقتی keep_local=True بود اجرا می‌شد،
                # یعنی با keep_local=False فایل‌ها بی‌نهایت انباشته می‌شدن و دیسک پر
                # می‌شد. حالا: keep_local=True → فقط سقفِ MAX_BACKUP_FILES نگه‌داری
                # می‌شه؛ keep_local=False → بعد از ارسالِ موفق، همین فایلِ محلی هم
                # حذف می‌شه (پایین‌تر، بعد از ارسال).
                self._cleanup_old_backups(backup_dir)

                # ارسال به مقصد
                chat_id = settings.get("chat_id")
                if not chat_id:
                    from .config import ADMIN_IDS
                    if ADMIN_IDS:
                        chat_id = ADMIN_IDS[0]

                if chat_id:
                    try:
                        await self.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(encrypted, filename=backup_filename),
                            caption=(
                                f"📦 <b>بکاپ روزانه</b>\n"
                                f"🕒 {format_jalali_datetime(now)}\n"
                                f"📁 حجم: {len(encrypted) // 1024} کیلوبایت"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                        log.info("بکاپ روزانه ارسال شد به chat_id=%s", chat_id)
                        # فیکسِ R5: اگه کاربر نگه‌داریِ محلی رو نمی‌خواد، فقط بعد از
                        # ارسالِ موفق فایلِ محلی حذف می‌شه (وگرنه دیسک پر می‌شه).
                        if not settings.get("keep_local", True):
                            try:
                                os.remove(backup_path)
                            except OSError as e:
                                log.warning("حذفِ فایلِ بکاپِ محلی بعد از ارسال ناموفق بود: %s", e)
                    except Exception as e:
                        log.error("ارسال بکاپ ناموفق: %s", e)

                # به‌روزرسانی last_backup
                settings["last_backup"] = now.isoformat()
                self.save_settings(settings)

            except asyncio.CancelledError:
                log.info("سرویس بکاپ روزانه متوقف شد")
                break
            except Exception as e:
                log.exception("خطا در حلقه بکاپ روزانه: %s", e)
                await asyncio.sleep(300)

    def _cleanup_old_backups(self, backup_dir: str):
        """حذف بکاپ‌های قدیمی (بیش از MAX_BACKUP_FILES)"""
        try:
            files = sorted(
                [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".backup")],
                key=os.path.getmtime,
                reverse=True
            )
            if len(files) > MAX_BACKUP_FILES:
                for f in files[MAX_BACKUP_FILES:]:
                    os.remove(f)
                    log.debug("بکاپ قدیمی حذف شد: %s", f)
        except Exception as e:
            log.warning("خطا در پاکسازی بکاپ‌های قدیمی: %s", e)

    def stop(self):
        """توقف سرویس بکاپ"""
        self.running = False
        log.info("سرویس بکاپ روزانه در حال توقف...")