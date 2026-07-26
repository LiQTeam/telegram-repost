"""
پکیج اصلی ربات ری‌پست هوشمند MR LiQ
نسخه 2.0.0 - با تمام قابلیت‌های جدید (۱۰ گانه)
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

__version__ = "2.0.0"
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