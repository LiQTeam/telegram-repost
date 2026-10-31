"""
پکیج اصلی ربات ری‌پست هوشمند MR LiQ

⚠️ این فایل عمداً «همه‌ی» ماژول‌ها را eager import نمی‌کند. ماژول‌های سنگین یا
اختیاری (ai_adapters/ai_provider_manager/web_search/manual_poster/auto_poster/…)
هرکدام سرِ جای خودشان lazy وارد می‌شوند تا زمانِ بالا آمدنِ ربات کوتاه بماند؛
فهرستِ زیر فقط هسته‌ی همیشه-لازم است.
"""
from . import (
    config,
    database,
    scraper,
    formatter,
    watermark,
    poster,
    scheduler,
    keyboards,
    utils,
    ad_filter,
    ad_feedback_report,
    ai_watermark,
    cache,
    concurrency,
    sr_model,
    lama_model,
    jdatetime_utils,
    ai_router,
    image_router,
    resource_monitor,
    backup_manager,
    duplicate_filter,
    smart_scheduler,
    notification_manager,
    public_report_channel,
    handlers,
)

__version__ = "2.4.2"
__author__ = "MR LiQ Team"

__all__ = [
    "config",
    "database",
    "scraper",
    "formatter",
    "watermark",
    "poster",
    "scheduler",
    "keyboards",
    "utils",
    "ad_filter",
    "ad_feedback_report",
    "ai_watermark",
    "cache",
    "concurrency",
    "sr_model",
    "lama_model",
    "jdatetime_utils",
    "ai_router",
    "image_router",
    "resource_monitor",
    "backup_manager",
    "duplicate_filter",
    "smart_scheduler",
    "notification_manager",
    "public_report_channel",
    "handlers",
]