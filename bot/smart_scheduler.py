"""
زمان‌بندی هوشمند بر اساس آمار بازدید مقصد
با قابلیت تحلیل بازدیدها، نمایش نمودار و پیشنهاد بهترین زمان
"""
from __future__ import annotations

import logging
from typing import Optional

from .database import db, _lock as _db_lock  # noqa: PLC2701 — قفلِ سراسریِ کانکشن
from .jdatetime_utils import now_jalali

log = logging.getLogger("repost_bot.smart_scheduler")

STATS_TABLE = """
CREATE TABLE IF NOT EXISTS channel_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id INTEGER NOT NULL,
    hour INTEGER NOT NULL,
    avg_views REAL DEFAULT 0,
    count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(destination_id, hour)
);
CREATE INDEX IF NOT EXISTS idx_stats_dest ON channel_stats(destination_id);
CREATE INDEX IF NOT EXISTS idx_stats_hour ON channel_stats(hour);
"""


class SmartScheduler:
    """زمان‌بندی هوشمند بر اساس آمار بازدید"""

    @staticmethod
    def is_enabled(destination_id: int) -> bool:
        """بررسی فعال بودن زمان‌بندی هوشمند برای مقصد"""
        return db.get_bool(f"smart_schedule_{destination_id}", False)

    @staticmethod
    def set_enabled(destination_id: int, enabled: bool):
        """فعال/غیرفعال کردن زمان‌بندی هوشمند"""
        db.set_setting(f"smart_schedule_{destination_id}", "1" if enabled else "0")

    @staticmethod
    def record_view(destination_id: int, views: int, hour: Optional[int] = None):
        """
        ثبت بازدید یک پست در ساعت مشخص.

        ⚠️ نکته‌ی مهم (فیکسِ R4): این تابع در حالِ حاضر از هیچ‌جای مسیرِ ارسال
        صدا زده نمی‌شود، چون Bot API تلگرام تعدادِ بازدیدِ هر پیام را در اختیارِ
        ربات نمی‌گذارد (این داده فقط از طریقِ MTProto/کلاینتِ کاربری مثل Telethon
        در دسترس است). پس «زمان‌بندیِ هوشمند» تا وقتی یک منبعِ بازدید به پروژه
        اضافه نشود عملاً داده‌ای ندارد. این محدودیتِ API است نه باگِ کد؛ خودِ تابع
        اصلاح شد تا هر وقت منبعی وصل شد، امن و بدونِ شرطِ رقابتی کار کند:
        - نوشتن روی db._conn حالا زیرِ قفلِ سراسری (_db_lock) است (قبلاً بی‌قفل
          بود ← ریسکِ «database is locked»).
        - ستونِ UNIQUE(destination_id, hour) از ردیف‌های تکراری جلوگیری می‌کند.
        """
        if hour is None:
            hour = now_jalali().hour
        hour = max(0, min(23, hour))

        conn = db._conn
        try:
            with _db_lock:
                row = conn.execute(
                    "SELECT id, avg_views, count FROM channel_stats WHERE destination_id=? AND hour=?",
                    (destination_id, hour),
                ).fetchone()
                if row:
                    new_count = row["count"] + 1
                    new_avg = (row["avg_views"] * row["count"] + views) / new_count
                    conn.execute(
                        "UPDATE channel_stats SET avg_views=?, count=?, last_updated=CURRENT_TIMESTAMP WHERE id=?",
                        (new_avg, new_count, row["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO channel_stats (destination_id, hour, avg_views, count) VALUES (?, ?, ?, 1)",
                        (destination_id, hour, views),
                    )
                conn.commit()
        except Exception as e:
            log.warning("خطا در ثبت آمار بازدید: %s", e)

    @staticmethod
    def get_peak_hours(destination_id: int, top_n: int = 3) -> list[dict]:
        """دریافت ساعات اوج بازدید"""
        rows = db._conn.execute(
            """SELECT hour, avg_views, count FROM channel_stats 
               WHERE destination_id=? ORDER BY avg_views DESC LIMIT ?""",
            (destination_id, top_n)
        ).fetchall()
        return [{"hour": r["hour"], "avg_views": r["avg_views"], "count": r["count"]} for r in rows]

    @staticmethod
    def get_low_hours(destination_id: int, top_n: int = 3) -> list[dict]:
        """دریافت ساعات کم‌بازدید"""
        rows = db._conn.execute(
            """SELECT hour, avg_views, count FROM channel_stats 
               WHERE destination_id=? AND count > 1 ORDER BY avg_views ASC LIMIT ?""",
            (destination_id, top_n)
        ).fetchall()
        return [{"hour": r["hour"], "avg_views": r["avg_views"], "count": r["count"]} for r in rows]

    @staticmethod
    def get_stats_text(destination_id: int) -> str:
        """تولید متن آماری برای نمایش با نمودار متنی"""
        rows = db._conn.execute(
            "SELECT hour, avg_views, count FROM channel_stats WHERE destination_id=? ORDER BY hour",
            (destination_id,)
        ).fetchall()

        if not rows:
            return "📊 هنوز آمار کافی برای این کانال وجود ندارد.\nبرای جمع‌آوری آمار، حداقل ۱۰ پست ارسال شود."

        # یافتن حداکثر میانگین برای مقیاس‌دهی
        max_avg = max(r["avg_views"] for r in rows) if rows else 1
        if max_avg == 0:
            max_avg = 1

        lines = ["📈 <b>آمار بازدید بر اساس ساعت</b>", "─────────────────"]

        # ساخت نمودار برای هر ساعت
        for r in rows:
            bar_len = int((r["avg_views"] / max_avg) * 10)
            bar = "█" * bar_len + "░" * (10 - bar_len)
            lines.append(f"{r['hour']:02d}:00 {bar} {r['avg_views']:.1f} بازدید (تعداد: {r['count']})")

        # ساعات اوج
        peak = SmartScheduler.get_peak_hours(destination_id, 1)
        if peak:
            p = peak[0]
            lines.append(f"\n⭐ <b>بهترین ساعت:</b> {p['hour']:02d}:00 با میانگین {p['avg_views']:.1f} بازدید")

        # ساعات خلوت
        low = SmartScheduler.get_low_hours(destination_id, 1)
        if low:
            l = low[0]
            lines.append(f"🌙 <b>خلوت‌ترین ساعت:</b> {l['hour']:02d}:00 با میانگین {l['avg_views']:.1f} بازدید")

        # مجموع
        total = sum(r["count"] for r in rows)
        lines.append(f"\n📊 تعداد کل پست‌های تحلیل‌شده: {total}")

        return "\n".join(lines)

    @staticmethod
    def suggest_best_hour(destination_id: int) -> Optional[int]:
        """پیشنهاد بهترین ساعت برای ارسال (بر اساس ساعات اوج)"""
        peak = SmartScheduler.get_peak_hours(destination_id, 1)
        if peak:
            return peak[0]["hour"]

        # اگر آماری وجود ندارد، ساعت فعلی را پیشنهاد کن
        return now_jalali().hour

    @staticmethod
    def get_all_stats(destination_id: int) -> dict:
        """دریافت تمام آمار به صورت دیکشنری برای نمایش گرافیکی"""
        rows = db._conn.execute(
            "SELECT hour, avg_views, count FROM channel_stats WHERE destination_id=? ORDER BY hour",
            (destination_id,)
        ).fetchall()

        return {
            "data": [{"hour": r["hour"], "avg_views": r["avg_views"], "count": r["count"]} for r in rows],
            "peak_hours": SmartScheduler.get_peak_hours(destination_id, 3),
            "low_hours": SmartScheduler.get_low_hours(destination_id, 3),
            "total_posts": sum(r["count"] for r in rows),
            "best_hour": SmartScheduler.suggest_best_hour(destination_id),
        }