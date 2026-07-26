"""
کش دانلود فایل‌ها با TTL و محدودیت تعداد
برای ذخیره موقت فایل‌های دانلود شده و جلوگیری از دانلود مجدد
با قابلیت آمارگیری و پاکسازی خودکار
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Optional

from .config import (
    DOWNLOAD_CACHE_MAX_BYTES,
    DOWNLOAD_CACHE_MAX_ITEMS,
    DOWNLOAD_CACHE_TTL_SECONDS,
)

_cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
_lock = asyncio.Lock()

# آمار کش
_hit_count = 0
_miss_count = 0
_total_size = 0


async def get(key: str) -> Optional[bytes]:
    """
    دریافت آیتم از کش

    Args:
        key: کلید (معمولاً URL)

    Returns:
        داده در صورت وجود و معتبر بودن، در غیر این صورت None
    """
    # فیکسِ C3(ج): _total_size هم اینجا تغییر می‌کنه (حذفِ آیتمِ منقضی)، پس باید
    # global بشه؛ قبلاً نبود و حذفِ آیتمِ منقضی حجمِ کش رو کم نمی‌کرد ← نشتِ
    # حساب‌داری که total_size_mb رو به‌تدریج بی‌معنی و همیشه بزرگ‌تر از واقعیت می‌کرد.
    global _hit_count, _miss_count, _total_size

    if not is_enabled():
        return None

    async with _lock:
        if key not in _cache:
            _miss_count += 1
            return None

        data, timestamp = _cache[key]
        if time.time() - timestamp > DOWNLOAD_CACHE_TTL_SECONDS:
            _total_size -= len(data)  # فیکسِ C3(ج): حساب‌داریِ حجم درست بمونه
            del _cache[key]
            _miss_count += 1
            return None

        # حرکت به انتها (آخرین استفاده)
        _cache.move_to_end(key)
        _hit_count += 1
        return data


async def set(key: str, value: bytes) -> None:
    """
    ذخیره آیتم در کش

    Args:
        key: کلید (معمولاً URL)
        value: داده
    """
    global _total_size

    if not is_enabled() or not value:
        return

    async with _lock:
        # فیکسِ M10: اول کلیدِ تکراری رو حذف کن تا هم حساب‌داریِ حجم دوباره‌شماری
        # نشه و هم موقعِ eviction اشتباهاً یک آیتمِ سالمِ دیگه بیرون نیفته.
        if key in _cache:
            old_data, _ = _cache.pop(key)
            _total_size -= len(old_data)

        # فیکسِ C3(الف): eviction هم بر اساس «تعداد» و هم بر اساس «حجمِ بایتی»
        # انجام می‌شه. قبلاً فقط سقفِ تعداد بود؛ با ۲۰۰ آیتمِ تا ۸ مگابایتی یعنی
        # تا ۱.۶ گیگابایت رم که روی VPSهای کوچیک باعثِ OOM-kill می‌شد. حالا تا
        # وقتی از هر دو سقف رد شدیم، قدیمی‌ترین (LRU) رو بیرون می‌بریم.
        while _cache and (
            len(_cache) >= DOWNLOAD_CACHE_MAX_ITEMS
            or _total_size + len(value) > DOWNLOAD_CACHE_MAX_BYTES
        ):
            _oldest_key, (old_data, _) = _cache.popitem(last=False)
            _total_size -= len(old_data)

        # اگر خودِ این آیتم از کلِ سقفِ بایتی بزرگ‌تره، اصلاً کشش نکن (وگرنه حلقه‌ی
        # بالا کلِ کش رو خالی می‌کنه و باز هم جا نمی‌شه).
        if len(value) > DOWNLOAD_CACHE_MAX_BYTES:
            return

        _cache[key] = (value, time.time())
        _cache.move_to_end(key)
        _total_size += len(value)


async def clear() -> int:
    """پاک کردن کل کش"""
    global _hit_count, _miss_count, _total_size

    async with _lock:
        count = len(_cache)
        _cache.clear()
        _hit_count = 0
        _miss_count = 0
        _total_size = 0
        return count


async def remove(key: str) -> bool:
    """حذف یک آیتم خاص از کش"""
    global _total_size

    async with _lock:
        if key in _cache:
            data, _ = _cache[key]
            _total_size -= len(data)
            del _cache[key]
            return True
        return False


async def stats() -> dict:
    """دریافت آمار کامل کش"""
    async with _lock:
        now = time.time()
        valid_items = 0
        valid_size = 0

        for data, ts in _cache.values():
            if now - ts <= DOWNLOAD_CACHE_TTL_SECONDS:
                valid_items += 1
                valid_size += len(data)

        total_requests = _hit_count + _miss_count
        hit_rate = (_hit_count / total_requests * 100) if total_requests > 0 else 0

        return {
            "items": len(_cache),
            "valid_items": valid_items,
            "max_items": DOWNLOAD_CACHE_MAX_ITEMS,
            "ttl_seconds": DOWNLOAD_CACHE_TTL_SECONDS,
            "total_size_bytes": _total_size,
            "total_size_mb": round(_total_size / (1024 * 1024), 2),
            "valid_size_bytes": valid_size,
            "valid_size_mb": round(valid_size / (1024 * 1024), 2),
            "hit_count": _hit_count,
            "miss_count": _miss_count,
            "hit_rate": round(hit_rate, 1),
        }


def is_enabled() -> bool:
    """بررسی فعال بودن کش"""
    return DOWNLOAD_CACHE_MAX_ITEMS > 0 and DOWNLOAD_CACHE_TTL_SECONDS > 0


async def cleanup_expired() -> int:
    """پاکسازی آیتم‌های منقضی‌شده"""
    global _total_size

    async with _lock:
        now = time.time()
        expired_keys = [k for k, (_, ts) in _cache.items() if now - ts > DOWNLOAD_CACHE_TTL_SECONDS]
        count = 0
        for k in expired_keys:
            data, _ = _cache[k]
            _total_size -= len(data)
            del _cache[k]
            count += 1
        return count