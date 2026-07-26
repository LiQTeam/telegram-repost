"""
کانال عمومی گزارش عملکرد و شفافیت تیمی
با ارسال خودکار گزارش‌های موفقیت، هشدارهای عدم فعالیت (به همراه تگ‌کردنِ
مسئول)، و تشکرِ ریپلی‌شده به همون اخطار وقتی جبران می‌شه.

باگِ قبلی: توابعِ send_inactivity_warning و send_thanks_for_activity این‌جا
تعریف شده بودن ولی هیچ‌جای پروژه صدا زده نمی‌شدن - یعنی کانالِ عمومی فقط
گزارشِ «کی پست گذاشت» رو می‌گرفت، ولی هیچ‌وقت «کی پست نذاشت» یا «کی بعد از
اخطار جبران کرد» رو نشون نمی‌داد، چون اون منطق فقط توی scheduler.py (به یک
چتِ خصوصی، بدونِ گرافیکِ کانالِ عمومی) پیاده‌سازی شده بود. حالا این دو تابع
با مدلِ واقعیِ دیتابیس (بر اساسِ destination به‌جای فقط user) بازنویسی شدن و
از scheduler.py هم صدا زده می‌شن.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape as _esc
from typing import Optional

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import RetryAfter

from .database import db
from .jdatetime_utils import now_jalali, format_jalali_datetime, format_jalali_date

log = logging.getLogger("repost_bot.public_report_channel")

# فیکسِ R8: رفرنسِ تسکِ retryِ پس‌زمینه نگه داشته می‌شه. بدونِ این، حلقه‌ی رویداد
# فقط یک weak-reference به تسک نگه می‌داره و پایتون ممکنه تسک رو پیش از پایان
# garbage-collect کنه ← پیامِ گزارشی که به‌خاطرِ فلادِ ۴۲۹ به پس‌زمینه رفته بود
# بی‌سروصدا گم می‌شه. همون الگوی scheduler.py/_background_tasks.
_report_bg_tasks: set[asyncio.Task] = set()

PUBLIC_CHANNEL_KEY = "public_report_channel"

_SEPARATOR = "▫️▫️▫️▫️▫️▫️▫️▫️▫️▫️"


def _format_duration(seconds: float) -> str:
    """تبدیلِ یک بازه‌ی زمانی (به ثانیه) به متنِ خوانا مثلِ «۲ روز و ۳ ساعت»."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if not days and not hours and minutes:
        parts.append(f"{minutes} دقیقه")
    if not parts:
        parts.append("چند لحظه")
    return " و ".join(parts)


def _severity_badge(total_warnings: int) -> str:
    """نشانگرِ شدت بر اساسِ این‌که این مقصد چندمین بارِ کلیه که اخطار می‌گیره."""
    if total_warnings <= 1:
        return "🟡"
    if total_warnings == 2:
        return "🟠"
    return "🔴"


class PublicReportChannel:
    """
    مدیریت کانال عمومی گزارش‌ها برای شفافیت تیمی
    """

    @staticmethod
    def get_chat_id() -> Optional[int]:
        """دریافت آیدی کانال عمومی"""
        raw = db.get_setting(PUBLIC_CHANNEL_KEY, "")
        try:
            return int(raw) if raw else None
        except Exception:
            return None

    @staticmethod
    def set_chat_id(chat_id: Optional[int]):
        """تنظیم آیدی کانال عمومی"""
        db.set_setting(PUBLIC_CHANNEL_KEY, str(chat_id) if chat_id else "")

    @staticmethod
    def is_enabled() -> bool:
        """بررسی فعال بودن کانال عمومی"""
        return PublicReportChannel.get_chat_id() is not None

    @staticmethod
    def _mention_for(user_id: Optional[int]) -> str:
        """ساختِ یک منشنِ قابل‌کلیک برایِ مسئولِ یک مقصد (اگه آیدیِ تلگرام
        داشته باشه)، وگرنه فقط اسمش؛ اگه اصلاً مالکی نداشته باشه (کانالِ
        سراسریِ ادمین)، برچسبِ «ادمین» نشون داده می‌شه."""
        if not user_id:
            return "ادمین"
        user = db.get_user(user_id)
        if not user:
            return f"کاربر #{user_id}"
        name = _esc(user["name"] or f"کاربر #{user_id}")
        telegram_id = user["telegram_id"] if "telegram_id" in user.keys() else None
        if telegram_id:
            return f"<a href='tg://user?id={telegram_id}'>{name}</a>"
        return name

    @classmethod
    async def send_message(
        cls,
        bot: Bot,
        text: str,
        parse_mode=ParseMode.HTML,
        disable_notification: bool = False,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[Message]:
        """ارسال پیام به کانال عمومی. خروجی: خودِ پیامِ ارسالی (برایِ reply-هایِ بعدی) یا None."""
        chat_id = cls.get_chat_id()
        if not chat_id:
            return None

        kwargs = dict(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )
        try:
            return await bot.send_message(**kwargs)
        except RetryAfter as e:
            # ⚠️ باگِ مهم: این تابع مستقیماً (با await) وسطِ مسیرِ اصلیِ ارسالِ
            # *خودِ پست* به مقصد صدا زده می‌شه (poster.py). چون کانالِ گزارشِ
            # عمومی گزارشِ پست‌های *همه‌ی* کاربرها رو می‌گیره، خیلی زودتر از
            # بقیه‌ی مقصدها به کنترلِ سیل می‌خوره. قبلاً همین‌جا با هر بارِ
            # فلاد، پیام با سطحِ ERROR رها می‌شد و برای همیشه گم می‌شد (دیده
            # شده: ده‌ها بار توی چند دقیقه). صبرِ واقعی (مثلِ poster.py) هم
            # این‌جا جواب نمی‌ده، چون این صبر مستقیماً جلوی ارسالِ خودِ پستِ
            # اصلی به کاربر رو هم می‌گرفت. برای همین تلاشِ دوباره به یک تسکِ
            # پس‌زمینه‌ی جدا منتقل شد: نه پیام گم می‌شه، نه ارسالِ پستِ اصلی
            # معطل می‌مونه.
            log.info(
                "ارسالِ پیام به کانال عمومی به کنترلِ سیل خورد؛ %.1f ثانیه دیگه توی پس‌زمینه دوباره امتحان می‌شه.",
                e.retry_after,
            )
            # فیکسِ R8: رفرنسِ تسک نگه داشته می‌شه تا زودتر از موعد GC نشه.
            _t = asyncio.create_task(cls._retry_send_in_background(bot, kwargs, e.retry_after))
            _report_bg_tasks.add(_t)
            _t.add_done_callback(_report_bg_tasks.discard)
            return None
        except Exception as e:
            log.error("ارسال پیام به کانال عمومی ناموفق: %s", e)
            return None

    @classmethod
    async def _retry_send_in_background(cls, bot: Bot, kwargs: dict, retry_after: float) -> None:
        """تلاشِ دوباره برای پیامِ کانالِ عمومی که به کنترلِ سیل خورده بود -
        کاملاً جدا از مسیرِ ارسالِ پستِ اصلی، تا اون رو معطل نکنه."""
        await asyncio.sleep(retry_after + 1)
        try:
            await bot.send_message(**kwargs)
        except RetryAfter as e:
            # اگه بازم فلاد بود، یک‌بارِ دیگه (با زمانِ جدید) امتحان می‌کنیم؛
            # ولی بی‌نهایت ادامه نمی‌دیم که یک پیامِ گزارشیِ غیرِحیاتی تسکِ
            # پس‌زمینه رو تا ابد زنده نگه نداره.
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(**kwargs)
            except Exception as e2:
                log.warning("تلاشِ دوباره‌ی پس‌زمینه برای پیامِ کانال عمومی هم ناموفق بود: %s", e2)
        except Exception as e:
            log.warning("تلاشِ دوباره‌ی پس‌زمینه برای پیامِ کانال عمومی هم ناموفق بود: %s", e)

    @classmethod
    async def send_success_report(
        cls,
        bot: Bot,
        user_id: int,
        destinations,
        post_link: str = "",
        channel_id: Optional[int] = None,
    ) -> Optional[Message]:
        """
        گزارشِ پست‌گذاریِ موفق. `destinations` یا یک رشته (برایِ سازگاری با
        فراخوانی‌هایِ قدیمی) یا یک لیست از عنوان‌هاست - لیست ترجیح داده می‌شه
        چون نمایشِ چندمقصدی رو به‌صورتِ فهرست/بولت زیباتر می‌کنه.
        """
        if not cls.is_enabled():
            return None

        mention = cls._mention_for(user_id)
        now = now_jalali()

        lines = [
            "✅ <b>پستِ جدید ارسال شد</b>",
            _SEPARATOR,
            f"👤 {mention}",
            f"🕒 {format_jalali_datetime(now)}",
        ]

        if channel_id:
            ch = db.get_channel(channel_id)
            if ch:
                lines.append(f"📡 از: @{_esc(ch['username'])}")

        if isinstance(destinations, str):
            dest_list = [d.strip() for d in destinations.split("،") if d.strip()]
        else:
            dest_list = [str(d) for d in destinations if str(d).strip()]

        if len(dest_list) > 1:
            lines.append(f"🎯 مقصدها ({len(dest_list)}):")
            for d in dest_list:
                lines.append(f"   • {_esc(d)}")
        elif dest_list:
            lines.append(f"🎯 مقصد: {_esc(dest_list[0])}")

        if post_link:
            lines.append(f"🔗 <a href='{_esc(post_link)}'>مشاهده پست</a>")

        return await cls.send_message(bot, "\n".join(lines))

    @classmethod
    async def send_destination_warning_card(
        cls,
        bot: Bot,
        dest_row,
        owner_user_id: int,
        hours_inactive: float,
        total_warnings: int,
    ) -> Optional[Message]:
        """
        کارتِ گرافیکیِ اخطارِ عدم‌فعالیت برایِ یک مقصدِ مشخص در کانالِ عمومی؛
        مسئولش (اگه آیدیِ تلگرام داشته باشه) مستقیم تگ می‌شه. خروجی: خودِ
        پیامِ ارسالی، تا بعداً پیامِ تشکر بشه ریپلایِ همین پیام.
        """
        if not cls.is_enabled():
            return None

        title = _esc(dest_row["title"] or str(dest_row["chat_id"]))
        chat_id_str = _esc(str(dest_row["chat_id"]))
        badge = _severity_badge(total_warnings)
        duration_txt = _format_duration(hours_inactive * 3600)
        mention = cls._mention_for(owner_user_id)

        lines = [
            f"{badge} <b>هشدارِ عدم‌فعالیت</b>",
            _SEPARATOR,
            f"🎯 کانال: <b>{title}</b>",
            f"🆔 <code>{chat_id_str}</code>",
            f"👤 مسئول: {mention}",
            f"⏳ مدتِ بی‌فعالیتی: <b>{duration_txt}</b>",
        ]
        if total_warnings > 1:
            lines.append(f"📌 این <b>{total_warnings}اُمین</b> باریه که این کانال اخطار می‌گیره.")
        lines.append(_SEPARATOR)
        lines.append("لطفاً هرچه زودتر یک پستِ تازه بذارید 🙏")

        return await cls.send_message(bot, "\n".join(lines))

    @classmethod
    async def send_destination_thanks_card(
        cls,
        bot: Bot,
        dest_row,
        owner_user_id: int,
        response_seconds: float,
        reply_to_message_id: Optional[int] = None,
        post_link: str = "",
    ) -> Optional[Message]:
        """کارتِ تشکر بعدِ جبرانِ عدم‌فعالیت - همیشه ریپلایِ پیامِ اخطارِ اصلی
        (اگه هنوز وجود داشته باشه) تا کاملاً واضح باشه این تشکر مالِ کدوم
        اخطاره؛ اگه پیامِ اصلی دیگه در دسترس نبود (پاک شده)، به‌صورتِ یک پیامِ
        عادی ارسال می‌شه (allow_sending_without_reply). اگه لینکِ همون پستِ
        جبران‌کننده هم در دسترس باشه (post_link)، همراهِ کارت می‌آد تا مستقیم
        بشه رفت و پست رو دید."""
        if not cls.is_enabled():
            return None

        title = _esc(dest_row["title"] or str(dest_row["chat_id"]))
        mention = cls._mention_for(owner_user_id)
        duration_txt = _format_duration(response_seconds)

        lines = [
            "✅ <b>جبران شد!</b>",
            _SEPARATOR,
            f"🎯 کانال: <b>{title}</b>",
            f"👤 {mention}",
            f"⏱ پاسخ در عرضِ <b>{duration_txt}</b> بعدِ اخطار",
            _SEPARATOR,
            "دستِ‌مریزاد، فعالیت دوباره از سر گرفته شد 👏",
        ]
        if post_link:
            lines.append(f"🔗 <a href='{_esc(post_link)}'>مشاهده پست</a>")

        return await cls.send_message(
            bot, "\n".join(lines), reply_to_message_id=reply_to_message_id,
        )

    @classmethod
    async def send_destination_post_report(
        cls,
        bot: Bot,
        dest_row,
        owner_user_id: Optional[int],
        post_link: str = "",
    ) -> Optional[Message]:
        """
        گزارشِ «پستِ به‌موقع» برایِ یک مقصدِ مشخص در روالِ عادی - یعنی وقتی این
        مقصد بدونِ این‌که اخطارِ عدم‌فعالیت داشته باشه، طبقِ معمول پست گرفته.
        این با send_success_report فرق داره: اون یکی سطحِ «کانالِ مبدأ» و
        اسم‌بندیِ همه‌ی مقصدهاشو با هم گزارش می‌ده، ولی این یکی مالِ خودِ همین
        مقصدِ به‌خصوصه و مسئولش (owner_user_id) رو مستقیم تگ می‌کنه - دقیقاً
        هم‌سطحِ کارتِ اخطار/تشکر، تا شفافیتِ «کی الان به‌موقع پست گذاشت» هم
        مثلِ «کی اخطار گرفت» در کانالِ عمومی دیده بشه.
        """
        if not cls.is_enabled():
            return None

        title = _esc(dest_row["title"] or str(dest_row["chat_id"]))
        mention = cls._mention_for(owner_user_id)

        lines = [
            "✅ <b>پستِ به‌موقع</b>",
            _SEPARATOR,
            f"🎯 کانال: <b>{title}</b>",
            f"👤 {mention}",
            f"🕒 {format_jalali_datetime(now_jalali())}",
        ]
        if post_link:
            lines.append(f"🔗 <a href='{_esc(post_link)}'>مشاهده پست</a>")

        return await cls.send_message(bot, "\n".join(lines), disable_notification=True)

    @classmethod
    async def send_daily_scoreboard(cls, bot: Bot) -> Optional[Message]:
        """
        کارنامه‌ی روزانه، گروه‌بندی‌شده بر اساسِ کاربر: زیرِ منشنِ هر کاربر،
        وضعیتِ تک‌تکِ مقصدهایِ خودش (پست گذاشته/نذاشته/الان اخطار داره) لیست
        می‌شه - چون معمولاً یک کاربر چند مقصد داره و بهتره یک‌جا و به اسمِ خودش
        دیده بشه، نه پخش‌شده و قاطی با مقصدهایِ بقیه‌ی کاربرها.

        مقصدهایِ بدونِ مالک (owner_user_id=NULL، یعنی متعلق به خودِ ادمینِ
        سراسری) زیرِ یک گروهِ جدا با برچسبِ «ادمین» می‌رن.
        """
        if not cls.is_enabled():
            return None

        dests = db.list_destinations(active_only=True)
        if not dests:
            return None

        now = datetime.utcnow()
        rows: list[tuple] = []
        for d in dests:
            last_raw = (d["last_sent_at"] or d["created_at"] or "").strip()
            hours_since: Optional[float] = None
            if last_raw:
                try:
                    last_dt = datetime.strptime(last_raw[:19], "%Y-%m-%d %H:%M:%S")
                    hours_since = (now - last_dt).total_seconds() / 3600
                except ValueError:
                    hours_since = None
            rows.append((d, hours_since))

        active_today = sum(1 for _, h in rows if h is not None and h < 24)

        # گروه‌بندی بر اساسِ owner_user_id؛ ترتیبِ گروه‌ها بر اساسِ بدترین وضعیتِ
        # داخلِ همون گروه (کاربرهایی که الان بی‌فعال‌ترین/نگران‌کننده‌ترین مقصد رو
        # دارن، بالایِ گزارش می‌آن تا زودتر دیده بشن).
        groups: dict[Optional[int], list[tuple]] = {}
        for d, hours_since in rows:
            groups.setdefault(d["owner_user_id"], []).append((d, hours_since))

        def _group_sort_key(item) -> float:
            _, members = item
            worst = max(
                (h for _, h in members if h is not None), default=None,
            )
            any_unset = any(h is None for _, h in members)
            if any_unset and worst is None:
                return 1e9
            return max(worst or 0.0, 1e9 if any_unset else 0.0)

        sorted_groups = sorted(groups.items(), key=_group_sort_key, reverse=True)

        header = [
            "📊 <b>کارنامه‌ی روزانه (به تفکیکِ کاربر)</b>",
            f"🗓 {format_jalali_date(now_jalali())}",
            _SEPARATOR,
            f"جمعِ مقصدها: <b>{len(rows)}</b>   |   ✅ فعالِ امروز: <b>{active_today}</b>   |   👥 کاربرها: <b>{len(groups)}</b>",
            _SEPARATOR,
        ]

        def _row_badge_label(hours_since: Optional[float], warned: bool) -> tuple[str, str]:
            if hours_since is None:
                return "⚪", "بدونِ پستِ ثبت‌شده"
            if warned:
                return "🔴", f"{_format_duration(hours_since * 3600)} بی‌فعال — اخطار گرفته"
            if hours_since < 24:
                return "✅", "امروز فعال"
            if hours_since < 48:
                return "🟡", f"{_format_duration(hours_since * 3600)} بی‌فعال"
            return "🟠", f"{_format_duration(hours_since * 3600)} بی‌فعال"

        body_blocks = []
        MAX_GROUPS = 25
        for owner_user_id, members in sorted_groups[:MAX_GROUPS]:
            mention = cls._mention_for(owner_user_id)
            members_sorted = sorted(
                members, key=lambda m: (m[1] if m[1] is not None else 1e9), reverse=True,
            )
            group_active = sum(1 for _, h in members_sorted if h is not None and h < 24)
            lines = [f"👤 <b>{mention}</b>  ({group_active}/{len(members_sorted)} فعالِ امروز)"]
            for d, hours_since in members_sorted:
                title = _esc(d["title"] or str(d["chat_id"]))
                warned = db.has_open_destination_warning(d["id"])
                badge, label = _row_badge_label(hours_since, warned)
                lines.append(f"   {badge} {title} — {label}")
            body_blocks.append("\n".join(lines))

        text = "\n".join(header) + "\n\n" + "\n\n".join(body_blocks)
        if len(sorted_groups) > MAX_GROUPS:
            text += f"\n\n… و {len(sorted_groups) - MAX_GROUPS} کاربرِ دیگر"
        if len(text) > 4000:
            text = text[:3990] + "\n…"

        return await cls.send_message(bot, text, disable_notification=True)

    @classmethod
    async def send_weekly_summary(
        cls,
        bot: Bot,
        stats: dict,
        user_id: Optional[int] = None,
    ) -> Optional[Message]:
        """
        ارسال خلاصه هفتگی عملکرد
        """
        if not cls.is_enabled():
            return None

        now = now_jalali()
        lines = [
            "📊 <b>گزارش هفتگی</b>",
            f"🕒 هفته منتهی به {format_jalali_date(now)}",
            _SEPARATOR,
            f"📨 کل پست‌ها: {stats.get('total_posts', 0)}",
            f"✅ موفق: {stats.get('success_posts', 0)}",
            f"❌ ناموفق: {stats.get('failed_posts', 0)}",
            f"🚫 فیلتر شده: {stats.get('filtered_posts', 0)}",
            f"📊 میانگین بازدید: {stats.get('avg_views', 0):.0f}",
            _SEPARATOR,
            f"📡 کانال‌های مبدأ فعال: {stats.get('active_sources', 0)}",
            f"🎯 کانال‌های مقصد فعال: {stats.get('active_destinations', 0)}",
        ]

        if user_id:
            user = db.get_user(user_id)
            if user:
                lines.append(f"\n👤 گزارش برای: {_esc(user['name'])}")

        return await cls.send_message(bot, "\n".join(lines))
