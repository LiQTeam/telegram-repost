"""
ماژولِ ایزوله‌ی «تبلیغات».

نقطه‌ی اتصال به هسته‌ی ربات فقط همینِ setup() هست که در main.py صدا زده می‌شه؛
هیچ فایلِ دیگه‌ای از bot/auto_poster لازم نیست مستقیماً از بیرون import بشه
(به‌جز menu.py که هندلرهای منو/کالبک ازش استفاده می‌کنن).
"""
from __future__ import annotations

import logging

from telegram.ext import Application

log = logging.getLogger("repost_bot.auto_poster")


def setup(application: Application) -> None:
    from . import db
    from .scheduler import AutoPosterScheduler

    db.init_db()
    scheduler = AutoPosterScheduler(application.bot)
    application.bot_data["auto_poster_scheduler"] = scheduler
    application.create_task(scheduler.run_loop())
    log.info("ماژولِ auto_poster (تبلیغات) با موفقیت راه‌اندازی شد (تسکِ asyncio جدا).")


async def shutdown() -> None:
    """
    موقعِ خاموش‌شدنِ ربات صدا زده می‌شه (از main.py، هوکِ post_shutdown). این
    ماژول دیگه هیچ منبعِ خارجی (مرورگر/فایلِ باز) نداره که نیاز به تمیزکاری
    داشته باشه؛ فقط برای سازگاری با نقطه‌ی اتصالِ قبلی نگه داشته شده.
    """
    return None
