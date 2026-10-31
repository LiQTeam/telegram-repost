"""
رمزنگاریِ متقارنِ API Keyها (Fernet/AES) قبل از ذخیره در دیتابیس.

کلیدِ رمزنگاری در یک فایلِ محلیِ جدا (data/.ai_secret.key) نگه‌داری می‌شه، نه
داخلِ دیتابیس و نه هاردکد در سورس - این‌طوری حتی اگه فایلِ دیتابیس لو بره،
کلیدهای API بدونِ اون فایلِ سکرت قابلِ‌خوندن نیستن. دسترسیِ فایل روی ۶۰۰
(فقط خودِ کاربر/پروسه) تنظیم می‌شه.
"""
from __future__ import annotations

import logging
import os
import stat
import threading

from cryptography.fernet import Fernet, InvalidToken

from . import config

log = logging.getLogger("repost_bot.ai_crypto")

_KEY_FILE = config.DATA_DIR / ".ai_secret.key"
_lock = threading.RLock()
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    with _lock:
        if _KEY_FILE.exists():
            try:
                data = _KEY_FILE.read_bytes().strip()
                if data:
                    return data
            except OSError as e:
                log.exception("خواندنِ فایلِ کلیدِ رمزنگاریِ API شکست خورد: %s", e)
        # فایل وجود نداره یا خرابه: یک کلیدِ جدید بساز و ذخیره کن.
        new_key = Fernet.generate_key()
        try:
            _KEY_FILE.write_bytes(new_key)
            try:
                os.chmod(_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass  # روی بعضی سیستم‌عامل‌ها (مثلاً ویندوز) chmod کامل کار نمی‌کنه؛ بی‌خطره.
        except OSError as e:
            log.exception("نوشتنِ فایلِ کلیدِ رمزنگاریِ API شکست خورد: %s", e)
            raise
        return new_key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        with _lock:
            if _fernet is None:
                _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_text(plain: str) -> str:
    """رمزنگاریِ یک رشته (مثل API Key) و برگردوندنِ متنِ رمزشده (base64 امنِ URL)."""
    if not plain:
        return ""
    token = _get_fernet().encrypt(plain.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(token: str) -> str:
    """رمزگشاییِ متنِ رمزشده. اگه نامعتبر/خراب باشه، رشته‌ی خالی برمی‌گردونه (نه Exception)."""
    if not token:
        return ""
    try:
        plain = _get_fernet().decrypt(token.encode("utf-8"))
        return plain.decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as e:
        log.error("رمزگشاییِ یک API Key ذخیره‌شده شکست خورد (احتمالاً کلیدِ سکرت عوض شده): %s", e)
        return ""


def mask_key(raw_key: str) -> str:
    """نمایشِ امنِ کلید برای UI: فقط ۴ کاراکترِ آخر دیده می‌شه."""
    if not raw_key:
        return "—"
    if len(raw_key) <= 4:
        return "•" * len(raw_key)
    return "•" * 6 + raw_key[-4:]
