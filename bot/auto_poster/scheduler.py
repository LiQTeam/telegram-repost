"""
حلقه‌ی زمان‌بندیِ مستقلِ ماژولِ «تبلیغات» (asyncio.create_task جدا از هسته‌ی ربات).

- هر ۲۰ ثانیه تیک می‌زنه (سبک، فقط چک کردنِ ساعت).
- سرِ هر زمانِ ثبت‌شده در ads_schedule، پیامِ تبلیغاتی رو به همه‌ی کانال‌های
  مقصدِ ثبت‌شده می‌فرسته.

هر خطایی (شبکه، تلگرام) فقط لاگ می‌شه؛ حلقه هیچ‌وقت متوقف نمی‌شه و روی بقیه‌ی
ربات (به‌خصوص ری‌پست) هیچ تاثیری نمی‌ذاره چون در تسکِ asyncio جدای خودش
اجرا می‌شه.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Bot

from . import db
from . import ads as _ads

log = logging.getLogger("repost_bot.auto_poster.scheduler")

TICK_SECONDS = 20

# رفرنسِ تسک‌های پس‌زمینه‌ی انتشارِ تبلیغ تا تمومِ‌شدنشون. بدونِ نگه‌داشتنِ این
# رفرنس، حلقه‌ی رویداد فقط یک weak-reference به تسک نگه می‌داره و پایتون ممکنه
# تسک رو پیش از پایان garbage-collect کنه (گیرِ شناخته‌شده‌ی asyncio.create_task).
# هسته‌ی ربات (scheduler.py) هم دقیقاً همین الگو رو برای تسک‌های instant داره.
_background_tasks: set[asyncio.Task] = set()

try:
    from .. import config as _core_config
    _TZ = ZoneInfo(_core_config.TIMEZONE)
except Exception:  # noqa: BLE001
    _TZ = ZoneInfo("Asia/Tehran")


class AutoPosterScheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._ads_published_for: set[str] = set()

    async def run_loop(self) -> None:
        db.init_db()
        log.info("زمان‌بندِ ماژولِ تبلیغات (auto_poster) راه‌اندازی شد.")
        while True:
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("خطای غیرمنتظره در حلقه‌ی زمان‌بندیِ auto_poster: %s", e)
                db.add_log("ERROR", f"خطای حلقه‌ی زمان‌بندی: {e}")
            await asyncio.sleep(TICK_SECONDS)

    async def _tick(self) -> None:
        now = datetime.now(_TZ)
        today_key = now.strftime("%Y-%m-%d")
        now_hhmm = now.strftime("%H:%M")

        # پاکسازیِ روزانه‌ی مجموعه‌ی «امروز پابلیش شده»
        self._ads_published_for = {m for m in self._ads_published_for if m.startswith(today_key)}

        if db.get_bool("ads_module_enabled", False):
            await self._tick_ads(today_key, now_hhmm)

    async def _tick_ads(self, today_key: str, now_hhmm: str) -> None:
        for t in db.list_ads_schedule():
            marker = f"{today_key}_{t}_ads"
            if marker not in self._ads_published_for and now_hhmm == t:
                self._ads_published_for.add(marker)
                task = asyncio.create_task(self._safe_publish_ads())
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

    async def _safe_publish_ads(self) -> None:
        if not db.list_ads_targets():
            db.add_log("WARNING", "زمانِ انتشارِ تبلیغ رسید ولی هیچ کانالِ مقصدی ثبت نشده.")
            return
        try:
            await _ads.publish_now(self.bot)
        except Exception as e:  # noqa: BLE001
            log.exception("خطای انتشارِ زمان‌بندی‌شده‌ی تبلیغ: %s", e)
            db.add_log("ERROR", f"خطای انتشارِ زمان‌بندی‌شده‌ی تبلیغ: {e}")
