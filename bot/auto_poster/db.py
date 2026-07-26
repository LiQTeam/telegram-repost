"""
دیتابیسِ کاملاً مجزای ماژولِ «تبلیغات» — data/auto_poster.db

هیچ جدول یا اتصالی با bot/database.py (دیتابیسِ اصلیِ ری‌پست) مشترک نیست؛
یعنی هیچ قفل/تراکنشی روی این دیتابیس، دیتابیسِ اصلی رو کند نمی‌کنه و برعکس.
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from typing import Optional

from . import config

log = logging.getLogger("repost_bot.auto_poster.db")

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextlib.contextmanager
def _get_conn():
    """
    ⚠️ نکته‌ی مهم: `with conn:` توی sqlite3 فقط تراکنش (commit/rollback) رو
    مدیریت می‌کنه و خودِ کانکشن رو نمی‌بنده! این تابع تضمین می‌کنه کانکشن
    همیشه بسته بشه (جلوگیری از نشتِ فایل‌هندل).
    """
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _lock, _get_conn() as conn:
        # ⚠️ حذفِ کاملِ جدول‌های زیرسیستمِ قدیمیِ «قیمت‌ها» (طبقِ درخواستِ کاربر،
        # کلِ اون بخش از کد و دیتابیس حذف شد؛ اگه این جدول‌ها از نصبِ قبلی روی
        # دیسک مونده باشن، اینجا پاک می‌شن تا چیزی یتیم نمونه).
        conn.executescript(
            """
            DROP TABLE IF EXISTS symbols;
            DROP TABLE IF EXISTS publish_times;
            """
        )
        conn.execute("DELETE FROM settings WHERE key IN ('price_module_enabled', 'price_target_chat_id')") \
            if _table_exists(conn, "settings") else None

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS ads_buttons (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                url        TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ads_schedule (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL UNIQUE
            );

            -- کانال‌های مقصدِ تبلیغات (چندتایی؛ جایگزینِ تنظیمِ تک‌کاناله‌ی قبلی)
            CREATE TABLE IF NOT EXISTS ads_targets (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                name    TEXT
            );

            CREATE TABLE IF NOT EXISTS run_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT NOT NULL,
                level   TEXT NOT NULL,
                message TEXT NOT NULL
            );
            """
        )

        # ⚠️ مهاجرتِ نرم: اگه از نسخه‌ی قبلی یک «کانالِ مقصدِ» تک‌تایی برای
        # تبلیغات ثبت شده بود (ads_target_chat_id)، همون رو به‌عنوانِ اولین
        # عضوِ جدولِ چندکاناله‌ی ads_targets منتقل می‌کنیم تا کاربر مجبور به
        # تنظیمِ دوباره نشه.
        row = conn.execute("SELECT value FROM settings WHERE key = 'ads_target_chat_id'").fetchone()
        if row and row["value"]:
            conn.execute(
                "INSERT OR IGNORE INTO ads_targets (chat_id, name) VALUES (?, ?)",
                (row["value"], "کانال قبلی"),
            )
            conn.execute("DELETE FROM settings WHERE key = 'ads_target_chat_id'")

    log.info("دیتابیسِ auto_poster (تبلیغات) مقداردهی اولیه شد: %s", config.DB_PATH)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


# ==================== تنظیمات کلی ====================
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with _lock, _get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_bool(key: str, default: bool = False) -> bool:
    v = get_setting(key, "1" if default else "0")
    return v == "1"


def set_bool(key: str, value: bool) -> None:
    set_setting(key, "1" if value else "0")


# ==================== لاگ اجرا (برای دیباگ سریع از داخل خودِ ربات) ====================
def add_log(level: str, message: str) -> None:
    from datetime import datetime, timezone
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO run_log (ts, level, message) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), level, message[:2000]),
        )
        # فقط ۵۰۰ رکورد آخر رو نگه دار
        conn.execute(
            "DELETE FROM run_log WHERE id NOT IN (SELECT id FROM run_log ORDER BY id DESC LIMIT 500)"
        )


def recent_logs(limit: int = 15) -> list[dict]:
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ==================== ماژولِ تبلیغات: دکمه‌ها ====================
def list_ads_buttons() -> list[dict]:
    with _lock, _get_conn() as conn:
        rows = conn.execute("SELECT * FROM ads_buttons ORDER BY sort_order ASC, id ASC").fetchall()
    return [dict(r) for r in rows]


def get_ads_button(button_id: int) -> Optional[dict]:
    with _lock, _get_conn() as conn:
        row = conn.execute("SELECT * FROM ads_buttons WHERE id = ?", (button_id,)).fetchone()
    return dict(row) if row else None


def add_ads_button(name: str, url: str) -> int:
    with _lock, _get_conn() as conn:
        cur = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM ads_buttons")
        next_order = cur.fetchone()["n"]
        cur = conn.execute(
            "INSERT INTO ads_buttons (name, url, sort_order) VALUES (?, ?, ?)",
            (name, url, next_order),
        )
        return cur.lastrowid


def update_ads_button(button_id: int, name: str, url: str) -> None:
    with _lock, _get_conn() as conn:
        conn.execute("UPDATE ads_buttons SET name = ?, url = ? WHERE id = ?", (name, url, button_id))


def delete_ads_button(button_id: int) -> None:
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM ads_buttons WHERE id = ?", (button_id,))


# ==================== ماژولِ تبلیغات: زمان‌بندی ====================
def list_ads_schedule() -> list[str]:
    with _lock, _get_conn() as conn:
        rows = conn.execute("SELECT time FROM ads_schedule ORDER BY time ASC").fetchall()
    return [r["time"] for r in rows]


def add_ads_schedule(hhmm: str) -> bool:
    with _lock, _get_conn() as conn:
        try:
            conn.execute("INSERT INTO ads_schedule (time) VALUES (?)", (hhmm,))
            return True
        except sqlite3.IntegrityError:
            return False


def remove_ads_schedule(hhmm: str) -> None:
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM ads_schedule WHERE time = ?", (hhmm,))


# ==================== ماژولِ تبلیغات: کانال‌های مقصد (چندتایی) ====================
def list_ads_targets() -> list[dict]:
    with _lock, _get_conn() as conn:
        rows = conn.execute("SELECT * FROM ads_targets ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def add_ads_target(chat_id: str, name: str = "") -> bool:
    with _lock, _get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO ads_targets (chat_id, name) VALUES (?, ?)",
                (chat_id, name or None),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_ads_target(target_id: int) -> None:
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM ads_targets WHERE id = ?", (target_id,))
