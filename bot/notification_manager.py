"""
مدیریت و تفکیک حرفه‌ای پیغام‌ها و اعلان‌ها
با قابلیت ارسال اعلان‌های ادمین به کانال خصوصی جداگانه
"""
from __future__ import annotations

import json
import logging
from html import escape as _esc
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode

from .database import db
from .jdatetime_utils import now_jalali, format_jalali_datetime

log = logging.getLogger("repost_bot.notification_manager")

NOTIFICATION_SETTINGS_KEY = "notification_settings"


class NotificationManager:
    """
    مدیریت اعلان‌ها با تفکیک کامل بین اعلان‌های ادمین و کاربران عادی
    """

    @staticmethod
    def get_settings() -> dict:
        """دریافت تنظیمات اعلان‌ها"""
        raw = db.get_setting(NOTIFICATION_SETTINGS_KEY, "{}")
        try:
            return json.loads(raw)
        except Exception as e:
            log.warning(
                "تنظیماتِ اعلان‌ها نامعتبر یا خراب بود، از مقادیرِ پیش‌فرض استفاده می‌شه: %s", e
            )
            return {
                "chat_id": None,  # آیدی کانال خصوصی برای اعلان‌های ادمین
                "enabled": True,
                "send_errors": True,
                "send_success": True,
                "send_warnings": True,
                "send_user_activity": True,
            }

    @staticmethod
    def save_settings(settings: dict):
        """ذخیره تنظیمات اعلان‌ها"""
        db.set_setting(NOTIFICATION_SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))

    @staticmethod
    def get_admin_chat_id() -> Optional[int]:
        """دریافت آیدی کانال اختصاصی اعلان‌های ادمین"""
        settings = NotificationManager.get_settings()
        return settings.get("chat_id")

    @classmethod
    def _should_send(cls, notification_type: str) -> bool:
        """بررسی اینکه آیا نوع اعلان باید ارسال شود"""
        settings = cls.get_settings()
        if not settings.get("enabled", True):
            return False

        mapping = {
            "error": "send_errors",
            "success": "send_success",
            "warning": "send_warnings",
            "user_activity": "send_user_activity",
        }
        key = mapping.get(notification_type, "send_errors")
        return settings.get(key, True)

    @classmethod
    async def send_admin_notification(cls, bot: Bot, text: str, parse_mode=ParseMode.HTML, notification_type: str = "info"):
        """
        ارسال اعلان به چت اختصاصی ادمین (در صورت تنظیم)
        در غیر این صورت به چت اصلی ادمین ارسال می‌شود
        """
        if not cls._should_send(notification_type):
            log.debug("اعلان نوع '%s' غیرفعال است", notification_type)
            return

        chat_id = cls.get_admin_chat_id()
        if chat_id:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_notification=False,
                )
                return
            except Exception as e:
                log.error("ارسال اعلان به کانال اختصاصی ادمین ناموفق: %s", e)

        # Fallback: ارسال به ادمین اصلی در چت ربات
        from .config import ADMIN_IDS
        if ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=ADMIN_IDS[0],
                    text=text,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                log.error("ارسال اعلان به ادمین اصلی ناموفق: %s", e)

    @classmethod
    async def notify_error(
        cls,
        bot: Bot,
        error_type: str,
        details: dict,
        user_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        destination_id: Optional[int] = None,
        post_id: Optional[int] = None,
    ):
        """
        ارسال اعلان خطا با جزئیات کامل
        """
        now = now_jalali()

        msg = (
            f"❌ <b>خطا: {_esc(str(error_type))}</b>\n"
            f"🕒 {format_jalali_datetime(now)}\n"
            f"─────────────────\n"
        )

        # اطلاعات کاربر
        if user_id:
            user = db.get_user(user_id)
            if user:
                msg += f"👤 کاربر: {_esc(str(user['name']))} (ID: {user['telegram_id'] or 'نامشخص'})\n"
            else:
                msg += f"👤 کاربر: {user_id}\n"

        # اطلاعات کانال مبدأ
        if channel_id:
            ch = db.get_channel(channel_id)
            if ch:
                msg += f"📡 کانال مبدأ: @{_esc(str(ch['username']))} (ID: {ch['id']})\n"

        # اطلاعات کانال مقصد
        if destination_id:
            dest = db.get_destination(destination_id)
            if dest:
                msg += f"🎯 کانال مقصد: {_esc(str(dest['title'] or dest['chat_id']))} (ID: {dest['id']})\n"

        # اطلاعات پست
        if post_id:
            msg += f"📨 پست: {post_id}\n"

        # جزئیات اضافی
        # نکته: مقادیرِ details معمولاً از متنِ خامِ خطا/استثنا میان (مثلاً پیامِ
        # خطای تلگرام یا یک کتابخانه‌ی خارجی) که ممکنه کاراکترهای </>/& داشته
        # باشه؛ چون این پیام با parse_mode=HTML فرستاده می‌شه، اگه escape نشه
        # تلگرام با خطای «Can't parse entities» کلِ پیام (حتی خودِ اعلانِ خطا) رو
        # رد می‌کنه - دقیقاً همون کلاس‌باگی که در ai_provider_manager.py و
        # poster.py._notify_admins_of_failures قبلاً فیکس شده.
        for key, value in details.items():
            msg += f"• {_esc(str(key))}: {_esc(str(value))}\n"

        # ثبت در لاگ سیستم
        db.add_system_log(
            log_type="NOTIFICATION",
            event_type=error_type,
            severity="ERROR",
            message=error_type,
            details=details,
            channel_id=channel_id,
            destination_id=destination_id,
            user_id=user_id,
            post_id=post_id,
            status="failed"
        )

        await cls.send_admin_notification(bot, msg, notification_type="error")

    @classmethod
    async def notify_success(
        cls,
        bot: Bot,
        message: str,
        user_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        destination_id: Optional[int] = None,
        post_id: Optional[int] = None,
        post_link: Optional[str] = None,
    ):
        """ارسال اعلان موفقیت"""
        now = now_jalali()

        msg = (
            f"✅ <b>{_esc(str(message))}</b>\n"
            f"🕒 {format_jalali_datetime(now)}\n"
        )

        if user_id:
            user = db.get_user(user_id)
            if user:
                msg += f"👤 کاربر: {_esc(str(user['name']))}\n"

        if channel_id:
            ch = db.get_channel(channel_id)
            if ch:
                msg += f"📡 کانال مبدأ: @{_esc(str(ch['username']))}\n"

        if destination_id:
            dest = db.get_destination(destination_id)
            if dest:
                msg += f"🎯 کانال مقصد: {_esc(str(dest['title'] or dest['chat_id']))}\n"

        if post_link:
            # post_link همیشه توسطِ خودِ کد (poster._build_post_link) ساخته می‌شه،
            # نه ورودیِ خارجی؛ ولی escape چیزی رو خراب نمی‌کنه و ایمن‌تره.
            msg += f"🔗 <a href='{_esc(str(post_link))}'>مشاهده پست</a>"

        if post_id:
            msg += f"📨 پست: {post_id}"

        db.add_system_log(
            log_type="NOTIFICATION",
            event_type=message,
            severity="INFO",
            message=message,
            channel_id=channel_id,
            destination_id=destination_id,
            user_id=user_id,
            post_id=post_id,
            status="success"
        )

        await cls.send_admin_notification(bot, msg, notification_type="success")

    @classmethod
    async def notify_warning(
        cls,
        bot: Bot,
        warning_type: str,
        details: dict,
        user_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        destination_id: Optional[int] = None,
    ):
        """ارسال اعلان هشدار"""
        now = now_jalali()

        msg = (
            f"⚠️ <b>هشدار: {_esc(str(warning_type))}</b>\n"
            f"🕒 {format_jalali_datetime(now)}\n"
            f"─────────────────\n"
        )

        if user_id:
            user = db.get_user(user_id)
            if user:
                msg += f"👤 کاربر: {_esc(str(user['name']))}\n"

        for key, value in details.items():
            msg += f"• {_esc(str(key))}: {_esc(str(value))}\n"

        db.add_system_log(
            log_type="NOTIFICATION",
            event_type=warning_type,
            severity="WARNING",
            message=warning_type,
            details=details,
            channel_id=channel_id,
            destination_id=destination_id,
            user_id=user_id,
            status="warning"
        )

        await cls.send_admin_notification(bot, msg, notification_type="warning")