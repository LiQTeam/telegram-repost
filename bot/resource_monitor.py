"""
سیستم هشدار منابع سرور و لاگ‌برداری حرفه‌ای
با قابلیت مانیتورینگ لحظه‌ای CPU، RAM، دیسک و ارسال هشدار خودکار
"""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import sys
import time
from datetime import datetime, timedelta

import psutil
from telegram import Bot
from telegram.constants import ParseMode

from .database import db
from .jdatetime_utils import now_jalali, format_jalali_datetime

log = logging.getLogger("repost_bot.resource_monitor")

# آستانه‌های پیش‌فرض (درصد)
DEFAULT_CPU_THRESHOLD = 80
DEFAULT_RAM_THRESHOLD = 80
DEFAULT_DISK_THRESHOLD = 85

# زمان بررسی (ثانیه)
CHECK_INTERVAL = 60

# کلید تنظیمات در دیتابیس
SETTINGS_KEY = "resource_monitor_settings"


class ResourceMonitor:
    """مانیتورینگ منابع سرور با قابلیت هشدار خودکار"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.running = False
        self._last_alert_time = 0
        self._alert_cooldown = 1800  # 30 دقیقه بین هشدارهای تکراری

    @staticmethod
    def get_settings() -> dict:
        """دریافت تنظیمات مانیتورینگ"""
        raw = db.get_setting(SETTINGS_KEY, "{}")
        try:
            return json.loads(raw)
        except Exception:
            return {
                "cpu_threshold": DEFAULT_CPU_THRESHOLD,
                "ram_threshold": DEFAULT_RAM_THRESHOLD,
                "disk_threshold": DEFAULT_DISK_THRESHOLD,
                "notification_chat_id": None,
                "enabled": True,
                "last_alert": None,
            }

    @staticmethod
    def save_settings(settings: dict):
        """ذخیره تنظیمات مانیتورینگ"""
        db.set_setting(SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))

    @staticmethod
    def get_stats() -> dict:
        """دریافت آمار لحظه‌ای منابع"""
        # فیکسِ R7: cpu_percent(interval=0.5) حلقه‌ی رویداد رو نیم‌ثانیه بلاک
        # می‌کرد. با interval=None اندازه‌گیریِ غیرمسدودکننده (نسبت به آخرین
        # فراخوانی) انجام می‌شه؛ چون این تابع هر ۶۰ ثانیه صدا زده می‌شه، بازه‌ی
        # مرجعِ کافی برای عددِ معتبر وجود داره.
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            load = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)

            return {
                "cpu_percent": cpu,
                "cpu_count": psutil.cpu_count(),
                "cpu_load": load[0] / psutil.cpu_count() * 100 if psutil.cpu_count() else 0,
                "ram_percent": mem.percent,
                "ram_used_gb": mem.used / (1024**3),
                "ram_total_gb": mem.total / (1024**3),
                "ram_available_gb": mem.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_used_gb": disk.used / (1024**3),
                "disk_total_gb": disk.total / (1024**3),
                "disk_free_gb": disk.free / (1024**3),
                "hostname": platform.node(),
                "os": platform.platform(),
                "python_version": sys.version[:60],
                "uptime": datetime.now() - datetime.fromtimestamp(psutil.boot_time()),
            }
        except Exception as e:
            log.error("خطا در دریافت آمار منابع: %s", e)
            # فیکسِ R7: قبلاً اینجا یک dictِ ناقص (بدونِ ram_used_gb، cpu_count،
            # uptime و...) برگردانده می‌شد و check_and_alert / resource_stats_text
            # با KeyError می‌ترکید. حالا *همه‌ی* کلیدها با مقادیرِ امن پر می‌شن.
            return {
                "cpu_percent": 0.0, "cpu_count": 0, "cpu_load": 0.0,
                "ram_percent": 0.0, "ram_used_gb": 0.0, "ram_total_gb": 0.0,
                "ram_available_gb": 0.0,
                "disk_percent": 0.0, "disk_used_gb": 0.0, "disk_total_gb": 0.0,
                "disk_free_gb": 0.0,
                "hostname": "unknown", "os": "unknown",
                "python_version": sys.version[:60],
                "uptime": timedelta(0),
            }

    async def check_and_alert(self):
        """بررسی منابع و ارسال هشدار در صورت نیاز"""
        settings = self.get_settings()
        if not settings.get("enabled", True):
            return

        stats = self.get_stats()
        alerts = []
        now = time.time()

        cpu_th = settings.get("cpu_threshold", DEFAULT_CPU_THRESHOLD)
        ram_th = settings.get("ram_threshold", DEFAULT_RAM_THRESHOLD)
        disk_th = settings.get("disk_threshold", DEFAULT_DISK_THRESHOLD)

        if stats["cpu_percent"] >= cpu_th:
            alerts.append(f"🔴 پردازنده (CPU): {stats['cpu_percent']:.1f}% (آستانه: {cpu_th}%)")
        if stats["ram_percent"] >= ram_th:
            alerts.append(f"🔴 حافظه (RAM): {stats['ram_percent']:.1f}% (آستانه: {ram_th}%)")
        if stats["disk_percent"] >= disk_th:
            alerts.append(f"🔴 دیسک: {stats['disk_percent']:.1f}% (آستانه: {disk_th}%)")

        if not alerts:
            return

        # جلوگیری از ارسال هشدارهای تکراری
        last_alert = settings.get("last_alert", 0)
        if now - last_alert < self._alert_cooldown:
            log.debug("هشدار قبلی کمتر از %s ثانیه قبل ارسال شده، صرف‌نظر", self._alert_cooldown)
            return

        settings["last_alert"] = now
        self.save_settings(settings)

        # ساخت پیام هشدار
        now_jal = now_jalali()
        msg = (
            "⚠️ <b>هشدار منابع سرور</b>\n"
            f"🕒 {format_jalali_datetime(now_jal)}\n"
            f"🖥 {stats['hostname']}\n"
            f"─────────────────\n"
            + "\n".join(alerts)
            + "\n─────────────────\n"
            f"💾 رم استفاده‌شده: {stats['ram_used_gb']:.1f}GB / {stats['ram_total_gb']:.1f}GB\n"
            f"💿 دیسک استفاده‌شده: {stats['disk_used_gb']:.1f}GB / {stats['disk_total_gb']:.1f}GB\n"
            f"⏱ آپ‌تایم: {str(stats['uptime']).split('.')[0]}\n"
        )

        # ارسال به ادمین
        target_chat_id = settings.get("notification_chat_id")
        if not target_chat_id:
            from .config import ADMIN_IDS
            if ADMIN_IDS:
                target_chat_id = ADMIN_IDS[0]

        if target_chat_id:
            try:
                await self.bot.send_message(
                    chat_id=target_chat_id,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                    disable_notification=False,
                )
                log.info("هشدار منابع سرور ارسال شد: %s", alerts)

                # ثبت در لاگ سیستم
                db.add_system_log(
                    log_type="MONITOR",
                    event_type="resource_alert",
                    severity="WARNING",
                    message=f"هشدار منابع: {', '.join(alerts)}",
                    details={
                        "cpu": stats["cpu_percent"],
                        "ram": stats["ram_percent"],
                        "disk": stats["disk_percent"],
                        "thresholds": {"cpu": cpu_th, "ram": ram_th, "disk": disk_th}
                    },
                    status="alert"
                )

            except Exception as e:
                log.error("ارسال هشدار منابع سرور ناموفق: %s", e)

    async def run_loop(self):
        """حلقه اصلی مانیتورینگ"""
        self.running = True
        log.info("سرویس مانیتورینگ منابع راه‌اندازی شد (بررسی هر %s ثانیه)", CHECK_INTERVAL)

        # فیکسِ R7: اولین فراخوانیِ cpu_percent(interval=None) همیشه 0.0 برمی‌گردونه
        # (بازه‌ی مرجع نداره). یک‌بار اینجا «گرم»ش می‌کنیم تا اولین اندازه‌گیریِ
        # واقعیِ داخلِ حلقه عددِ معتبر بده، نه صفرِ گمراه‌کننده.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        while self.running:
            try:
                await self.check_and_alert()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("خطا در حلقه مانیتورینگ منابع: %s", e)
            await asyncio.sleep(CHECK_INTERVAL)

    def stop(self):
        """توقف سرویس مانیتورینگ"""
        self.running = False
        log.info("سرویس مانیتورینگ منابع در حال توقف...")


def resource_stats_text(stats: dict) -> str:
    """تولید متن زیبا برای نمایش آمار منابع"""
    cpu_bar = _progress_bar(stats["cpu_percent"])
    ram_bar = _progress_bar(stats["ram_percent"])
    disk_bar = _progress_bar(stats["disk_percent"])
    load_bar = _progress_bar(stats.get("cpu_load", 0))

    uptime = str(stats.get("uptime", 0)).split('.')[0]

    return (
        "📊 <b>وضعیت لحظه‌ای سرور</b>\n"
        f"🖥 {stats['hostname']}\n"
        f"─────────────────\n"
        f"🔹 پردازنده (CPU): {stats['cpu_percent']:.1f}% {cpu_bar}\n"
        f"   └ هسته‌ها: {stats['cpu_count']} · بار: {stats.get('cpu_load', 0):.1f}% {load_bar}\n"
        f"🔹 حافظه (RAM): {stats['ram_percent']:.1f}% {ram_bar}\n"
        f"   └ استفاده‌شده: {stats['ram_used_gb']:.1f}GB / {stats['ram_total_gb']:.1f}GB\n"
        f"   └ آزاد: {stats['ram_available_gb']:.1f}GB\n"
        f"🔹 دیسک: {stats['disk_percent']:.1f}% {disk_bar}\n"
        f"   └ استفاده‌شده: {stats['disk_used_gb']:.1f}GB / {stats['disk_total_gb']:.1f}GB\n"
        f"   └ آزاد: {stats['disk_free_gb']:.1f}GB\n"
        f"─────────────────\n"
        f"⏱ آپ‌تایم: {uptime}\n"
        f"🐍 پایتون: {stats.get('python_version', 'نامشخص')}\n"
        f"💻 سیستم‌عامل: {stats['os'][:50]}\n"
        f"🕒 {format_jalali_datetime(now_jalali())}"
    )


def _progress_bar(percent: float, width: int = 10) -> str:
    """ساخت نوار پیشرفت متنی"""
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100
    filled = int(round(percent / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"