"""
مدیریت پردازش هم‌زمان با Semaphore و ترد جداگانه
برای جلوگیری از قفل شدن ربات هنگام پردازش‌های سنگین
با قابلیت آمارگیری و مدیریت خطا
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import threading
import time
from typing import Any, Callable

from .config import MAX_CONCURRENT_HEAVY_JOBS

# سمافور برای محدود کردن پردازش‌های سنگین هم‌زمان
_semaphore = asyncio.Semaphore(max(1, MAX_CONCURRENT_HEAVY_JOBS))

# ThreadPoolExecutor برای اجرای توابع سنگین در ترد جداگانه
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(MAX_CONCURRENT_HEAVY_JOBS * 2, 4),
    thread_name_prefix="heavy_worker"
)

# شمارنده پردازش‌های فعال
_active_count = 0
_active_lock = threading.Lock()

# آمار
_total_processed = 0
_total_errors = 0
_max_processing_time = 0
_min_processing_time = float('inf')
_total_processing_time = 0


async def run_heavy(func: Callable, *args, **kwargs) -> Any:
    """
    اجرای یک تابع سنگین در ترد جداگانه با محدودیت هم‌زمان

    Args:
        func: تابعی که باید اجرا شود
        *args, **kwargs: آرگومان‌های تابع

    Returns:
        خروجی تابع

    Raises:
        Exception: هر خطایی که در تابع رخ دهد
    """
    global _active_count, _total_processed, _total_errors
    global _max_processing_time, _min_processing_time, _total_processing_time

    async with _semaphore:
        with _active_lock:
            _active_count += 1

        try:
            start_time = time.time()

            # اجرای تابع در ترد جداگانه
            # run_in_executor کیورد آرگومان قبول نمی‌کند، پس با functools.partial بایند می‌کنیم
            loop = asyncio.get_event_loop()
            bound_func = functools.partial(func, *args, **kwargs) if kwargs else func
            call_args = () if kwargs else args
            result = await loop.run_in_executor(
                _executor,
                bound_func,
                *call_args
            )

            elapsed = time.time() - start_time
            _total_processing_time += elapsed
            _max_processing_time = max(_max_processing_time, elapsed)
            _min_processing_time = min(_min_processing_time, elapsed)
            _total_processed += 1

            return result

        except Exception:
            _total_errors += 1
            raise

        finally:
            with _active_lock:
                _active_count -= 1


async def current_load() -> dict:
    """دریافت بار فعلی پردازش"""
    return {
        "active": _active_count,
        "max_concurrent": MAX_CONCURRENT_HEAVY_JOBS,
        "total_processed": _total_processed,
        "total_errors": _total_errors,
        "max_processing_time": round(_max_processing_time, 3),
        "min_processing_time": round(_min_processing_time, 3) if _min_processing_time != float('inf') else 0,
        "avg_processing_time": round(_total_processing_time / max(1, _total_processed), 3),
        "executor_workers": _executor._max_workers,
    }


def shutdown():
    """خاموش کردن Executor (برای توقف ربات).

    ⚠️ باگِ مهم: این تابع از قبل وجود داشت ولی هیچ‌جای پروژه صدا زده
    نمی‌شد. نتیجه: تردهای heavy_worker (تا سقفِ MAX_CONCURRENT_HEAVY_JOBS*2)
    بعد از هر پردازشِ AI (واترمارک/بهبودِ کیفیت) idle می‌موندن و چون
    non-daemon هستن، خودِ پروسه‌ی پایتون نمی‌تونست واقعاً exit کنه - حتی
    بعد از این‌که Application.stop() و scheduler.shutdown() تموم می‌شدن.
    نتیجه‌ش این بود که systemd مجبور می‌شد تا تایم‌اوتِ TimeoutStopSec صبر
    کنه و بعد با SIGKILL کلِ پردازه‌ها رو به‌زور بکشه. wait=True اینجا
    عمداً استفاده شده (نه wait=False مثلِ قبل) تا خودِ این تابع تضمین کنه
    تردها واقعاً قبل از برگشتن بسته شدن، نه این‌که فقط سیگنالِ بسته‌شدن
    بفرسته و بی‌خبر برگرده."""
    _executor.shutdown(wait=True, cancel_futures=True)


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """دریافت Executor برای استفاده مستقیم (در موارد خاص)"""
    return _executor