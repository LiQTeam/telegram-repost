"""
لایه‌ی دیتابیس (SQLite). همه‌ی تنظیمات قابل‌تغییر از داخل ربات + کانال‌های
مبدأ + کانال‌های مقصد + نگاشتِ مبدأ‌به‌مقصد + زمان‌بندی هفت‌گانه‌ی هر کانال +
لاگ ارسال‌ها اینجا نگهداری میشه.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import sqlite3
import sys
import threading
import traceback
from datetime import datetime, date
from typing import Any, Optional

from . import config

log = logging.getLogger("repost_bot.database")

_lock = threading.Lock()

# ریشه‌ی پروژه، برای این‌که مسیرِ فایل‌ها توی لاگ کوتاه و خوانا باشه
# (مثلاً "bot/poster.py" به‌جای مسیرِ کاملِ سرور)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _short_path(path: str) -> str:
    try:
        rel = os.path.relpath(path, _PROJECT_ROOT)
        return rel if not rel.startswith("..") else os.path.basename(path)
    except Exception:
        return os.path.basename(path)


def _capture_log_debug_info() -> Optional[dict]:
    """
    مشخصاتِ فنیِ منشأِ یک لاگِ ERROR/WARNING رو جمع می‌کنه:
    - فایل/خط/تابعی که واقعاً add_system_log رو صدا زده (نه خودِ database.py)
    - اگه توی یک بلاکِ except صدا زده شده باشه، نوع/پیامِ استثنا و
      آخرین فریمِ traceback (یعنی جایی که خطا واقعاً رخ داده، نه جایی که
      catch شده) رو هم اضافه می‌کنه.
    هیچ‌وقت نباید خودش استثنا پرتاب کنه؛ لاگ نباید به‌خاطرِ این کمکی خراب بشه.
    """
    info: dict = {}
    try:
        caller = None
        for frame_info in inspect.stack()[1:8]:
            if os.path.abspath(frame_info.filename) != os.path.abspath(__file__):
                caller = frame_info
                break
        if caller:
            info["caller_file"] = _short_path(caller.filename)
            info["caller_line"] = caller.lineno
            info["caller_function"] = caller.function
    except Exception:
        pass

    try:
        exc_type, exc_value, exc_tb = sys.exc_info()
        if exc_type is not None:
            info["exception_type"] = exc_type.__name__
            info["exception_message"] = str(exc_value)[:150]
            frames = traceback.extract_tb(exc_tb)
            if frames:
                origin = frames[-1]  # فریمِ آخر = جایی که خطا واقعاً اتفاق افتاده
                info["origin_file"] = _short_path(origin.filename)
                info["origin_line"] = origin.lineno
                info["origin_function"] = origin.name
                info["origin_code"] = (origin.line or "").strip()[:200]
                # یک ردِ فشرده از کل زنجیره‌ی فراخوانی (حداکثر ۵ فریمِ آخر)
                info["trace_chain"] = [
                    f"{_short_path(f.filename)}:{f.lineno} در {f.name}()"
                    for f in frames[-5:]
                ]
    except Exception:
        pass

    return info or None

SLOTS_PER_CHANNEL = 7
DEFAULT_SLOT_TIMES = ["08:00", "10:30", "13:00", "15:30", "18:00", "20:30", "23:00"]

SEND_MODE_SCHEDULE = "schedule"
SEND_MODE_INSTANT = "instant"
SEND_MODE_INTERVAL = "interval"
DEFAULT_INTERVAL_MINUTES = 30

PENDING_PENDING = "pending"
PENDING_APPROVED = "approved"
PENDING_REJECTED = "rejected"

# نامِ کوتاه و یک‌دستِ هر تاگل برای نمایش روی دکمه‌ها. عمداً کوتاه نگه داشته شدن
# تا کنارِ نشانگرِ وضعیت روی یک خط جا بشن و توی دکمه بریده/ناخوانا نشن (توضیحِ
# کاملِ هر کدوم در متنِ بالای منوی «تنظیماتِ اختصاصی» اومده).
OVERRIDABLE_TOGGLES: dict[str, str] = {
    "wm_tg_enabled": "🏷 واترمارک تلگرام",
    "wm_ig_enabled": "📸 واترمارک اینستاگرام",
    "ai_removal_enabled": "🧹 حذفِ واترمارکِ قبلی (AI)",
    "ad_filter_enabled": "🚫 فیلترِ تبلیغات",
    "ad_filter_smart_enabled": "🧠 فیلترِ هوشمند (AI)",
    "config_only_enabled": "🧩 فقط کانفیگ/پروکسی",
    "premium_emoji_enabled": "⭐️ ایموجیِ پرمیوم",
    "file_filter_enabled": "📦 فیلترِ فایل/اَپ",
    "min_content_filter_enabled": "✂️ فیلترِ پست‌های کوتاه",
    "footer_enabled": "✍️ امضای پایان پست",
    "preserve_formatting": "🔠 حفظِ قالب‌بندیِ متن",
    "remove_source_links": "🔗 حذفِ لینک/منشنِ مبدأ",
    "download_cache_enabled": "💾 کشِ دانلود",
    "vpn_howto_cleanup_enabled": "🧽 پاکسازیِ کپشنِ Netmod/NPV",
    "vpn_signature_footer_enabled": "🚩 امضای VFREEPN",
}

OVERRIDABLE_TOGGLE_DEFAULTS: dict[str, bool] = {
    "wm_tg_enabled": True,
    "wm_ig_enabled": False,
    "ai_removal_enabled": False,
    "ad_filter_enabled": False,
    "ad_filter_smart_enabled": True,
    "config_only_enabled": False,
    "premium_emoji_enabled": False,
    "file_filter_enabled": True,
    "min_content_filter_enabled": True,
    "footer_enabled": True,
    "preserve_formatting": True,
    "remove_source_links": True,
    "download_cache_enabled": True,
    "vpn_howto_cleanup_enabled": False,
    "vpn_signature_footer_enabled": False,
}

# این تاگل‌ها می‌تونن به‌ازای هر کاربر (owner_user_id) جدا ذخیره بشن.
# تاگل‌هایی که اینجا نیستن (مثل ai_removal_enabled، ad_filter_enabled، download_cache_enabled)
# همیشه سراسری هستن و فقط ادمین می‌تونه اونا رو تغییر بده.
USER_SCOPED_TOGGLES: set[str] = {
    "wm_tg_enabled",
    "wm_ig_enabled",
    "min_content_filter_enabled",
    "footer_enabled",
    "preserve_formatting",
    "remove_source_links",
}

DEFAULT_SETTINGS: dict[str, str] = {
    "footer_enabled": "1",
    "footer_channel_handle": "",
    "footer_channel_url": "",
    "footer_text_template": "@{handle}",
    "footer_mode": "link",
    "footer_custom_text": "",
    "watermark_enabled": "1",
    "watermark_text": "MR LiQ",
    "watermark_position": "bottom_left",
    "watermark_color_start": "#F0143C",
    "watermark_color_end": "#F0B84E",
    "watermark_bg_opacity": "70",
    "watermark_font_size": "34",
    "watermark_margin": "28",
    "watermark_all_album_photos": "1",
    "wm_tg_enabled": "1",
    "wm_tg_text": "MR LiQ",
    "wm_tg_position": "bottom_left",
    "wm_tg_color_mode": "gradient",
    "wm_tg_color_a": "#E53935",
    "wm_tg_color_b": "#1E88E5",
    "wm_tg_bg_opacity": "70",
    "wm_tg_font_size": "34",
    "wm_tg_margin": "28",
    "wm_tg_album_all": "1",
    "wm_ig_enabled": "0",
    "wm_ig_text": "MR LiQ",
    "wm_ig_position": "bottom_right",
    "wm_ig_color_mode": "gradient",
    "wm_ig_color_a": "#EC407A",
    "wm_ig_color_b": "#8E24AA",
    "wm_ig_bg_opacity": "70",
    "wm_ig_font_size": "34",
    "wm_ig_margin": "28",
    "wm_ig_album_all": "1",
    "ai_removal_enabled": "0",
    "download_cache_enabled": "1",
    "ad_filter_enabled": "0",
    "ad_filter_action": "skip",
    "ad_filter_keywords": "",
    "ad_filter_min_mentions": "3",
    "ad_filter_min_links": "2",
    "ad_filter_score_threshold": "4",
    "file_filter_enabled": "1",
    "file_filter_extensions": "",
    "min_content_filter_enabled": "1",
    "min_content_words": "4",
    "preserve_formatting": "1",
    "remove_source_links": "1",
    "max_caption_length": "1024",
    "scheduler_active": "1",
    "target_chat_id": config.TARGET_CHAT_ID_ENV,
    "target_chat_title": "",
    # تنظیمات جدید برای قابلیت‌های ۱۰ گانه
    "backup_encryption_key": "",
    "resource_monitor_settings": "{}",
    "backup_settings": "{}",
    "notification_settings": "{}",
    "public_report_channel": "",
    "smart_schedule_settings": "{}",
}

# تنظیماتِ «مختصِ کاربر» - واترمارک/امضای پایان‌پست/قالب‌بندیِ متن. این‌ها برخلافِ
# بقیه‌ی SETTINGS (که سراسری و مشترکِ بینِ همه هستند)، به‌ازای هر کاربر (owner_user_id)
# جدا ذخیره می‌شوند تا تنظیمِ یک کاربر روی پست‌های کاربرِ دیگر یا بخشِ ادمین اثر نگذارد.
DEFAULT_USER_SETTINGS: dict[str, str] = {
    "footer_enabled": "1",
    "footer_channel_handle": "",
    "footer_channel_url": "",
    "footer_text_template": "@{handle}",
    "footer_mode": "link",
    "footer_custom_text": "",
    "wm_tg_enabled": "1",
    "wm_tg_text": "",
    "wm_tg_position": "bottom_left",
    "wm_tg_color_mode": "gradient",
    "wm_tg_color_a": "#E53935",
    "wm_tg_color_b": "#1E88E5",
    "wm_tg_bg_opacity": "70",
    "wm_tg_font_size": "34",
    "wm_tg_margin": "28",
    "wm_tg_album_all": "1",
    "wm_tg_badge_scale": "32",
    "wm_ig_enabled": "0",
    "wm_ig_text": "",
    "wm_ig_position": "bottom_right",
    "wm_ig_color_mode": "gradient",
    "wm_ig_color_a": "#EC407A",
    "wm_ig_color_b": "#8E24AA",
    "wm_ig_bg_opacity": "70",
    "wm_ig_font_size": "34",
    "wm_ig_margin": "28",
    "wm_ig_album_all": "1",
    "wm_ig_badge_scale": "32",
    "min_content_filter_enabled": "1",
    "min_content_words": "4",
    "preserve_formatting": "1",
    "remove_source_links": "1",
    "max_caption_length": "1024",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    username           TEXT NOT NULL,
    title              TEXT DEFAULT '',
    active             INTEGER NOT NULL DEFAULT 1,
    last_post_id       INTEGER NOT NULL DEFAULT 0,
    last_sent_at       TEXT,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    approval_required  INTEGER NOT NULL DEFAULT 0,
    send_mode          TEXT NOT NULL DEFAULT 'schedule',
    interval_minutes   INTEGER NOT NULL DEFAULT 30,
    last_interval_run  TEXT DEFAULT '',
    overrides          TEXT NOT NULL DEFAULT '{}',
    owner_user_id      INTEGER
);

CREATE TABLE IF NOT EXISTS destinations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    title       TEXT DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    last_sent_at TEXT DEFAULT '',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    owner_user_id INTEGER,
    total_warnings INTEGER NOT NULL DEFAULT 0,
    last_post_link TEXT DEFAULT ''
);

-- یک کانالِ مبدأ (username) یا مقصد (chat_id) ممکنه توسطِ چند مالکِ مختلف
-- (ادمین + چند کاربر، یا چند کاربرِ مختلف) هم‌زمان ثبت بشه؛ هرکدوم رکوردِ
-- کاملاً جدا و مستقلِ خودشون رو دارن. فقط برایِ یک مالکِ مشخص، تکراری نباشه.
-- توجه: در SQLite مقادیرِ NULL در UNIQUE INDEX هیچ‌وقت با هم برابر در نظر
-- گرفته نمی‌شن (یعنی چند ردیفِ owner_user_id=NULL هیچ‌وقت باهم تداخل
-- نمی‌کنن) - برایِ همینه که این‌جا با COALESCE(owner_user_id, 0)، مالکِ
-- «ادمین» (owner_user_id خالی) هم مثلِ یک مالکِ واقعی و ثابت (۰) در نظر
-- گرفته می‌شه تا خودِ ادمین هم نتونه یک کانال/مقصدِ تکراری اضافه کنه.
CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_username_owner
    ON channels (username, COALESCE(owner_user_id, 0));
CREATE UNIQUE INDEX IF NOT EXISTS idx_destinations_chatid_owner
    ON destinations (chat_id, COALESCE(owner_user_id, 0));

-- تنظیماتِ اختصاصیِ هر کانالِ مقصد (override) — مثلِ امضای پایانِ پست و فیلترِ
-- تبلیغاتِ جدا برای همون مقصد. چون به destination_id گره خورده و خودِ مقصد
-- owner_user_id داره (و کاربر فقط مقصدهای خودش رو می‌بینه/ویرایش می‌کنه)،
-- این تنظیمات هم به‌صورتِ خودکار برای هر کاربر/ادمین کاملاً جدا و ایزوله‌ان.
CREATE TABLE IF NOT EXISTS destination_settings (
    destination_id INTEGER NOT NULL,
    key            TEXT NOT NULL,
    value          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (destination_id, key)
);

CREATE TABLE IF NOT EXISTS channel_destinations (
    channel_id      INTEGER NOT NULL,
    destination_id  INTEGER NOT NULL,
    PRIMARY KEY (channel_id, destination_id)
);

CREATE TABLE IF NOT EXISTS schedule_slots (
    channel_id     INTEGER NOT NULL,
    slot_index     INTEGER NOT NULL,
    slot_time      TEXT DEFAULT '',
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_run_date  TEXT DEFAULT '',
    PRIMARY KEY (channel_id, slot_index)
);

CREATE TABLE IF NOT EXISTS sent_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL,
    post_id      INTEGER NOT NULL,
    media_type   TEXT,
    sent_date    TEXT NOT NULL,
    sent_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sent_log_date ON sent_log(channel_id, sent_date);

-- نگاشتِ «پستِ مبدأ → آیدیِ پیامِ ارسال‌شده در هر مقصد». برای بازسازیِ ریپلای:
-- وقتی یک پستِ مبدأ روی پستِ دیگری ریپلای شده، با این جدول پیامِ متناظرِ همون
-- پستِ ریپلای‌شده در مقصد پیدا می‌شه تا پستِ جدید هم در مقصد روی همون ریپلای بشه.
CREATE TABLE IF NOT EXISTS sent_message_map (
    source_channel_id INTEGER NOT NULL,
    source_post_id    INTEGER NOT NULL,
    destination_id    INTEGER NOT NULL,
    dest_message_id   INTEGER NOT NULL,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_channel_id, source_post_id, destination_id)
);

CREATE INDEX IF NOT EXISTS idx_sent_map_created ON sent_message_map(created_at);

CREATE TABLE IF NOT EXISTS pending_posts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id         INTEGER NOT NULL,
    source_post_id     INTEGER NOT NULL,
    caption_html       TEXT DEFAULT '',
    original_caption_html TEXT DEFAULT '',
    body_html          TEXT DEFAULT '',
    media_json         TEXT DEFAULT '[]',
    override_photo     BLOB,
    override_video     BLOB,
    status             TEXT NOT NULL DEFAULT 'pending',
    admin_chat_id       INTEGER,
    admin_message_id    INTEGER,
    flag_reason        TEXT DEFAULT '',
    ad_filter_detail   TEXT DEFAULT '',              -- جزئیاتِ ساختاریافته‌ی موتورِ فیلترِ تبلیغات (JSON: score/threshold/llm/llm2/keywords/...) - برایِ خروجیِ اکسلِ فیدبک، نگاه کن به ad_feedback_report.py
    ad_feedback        TEXT DEFAULT '',              -- فیدبکِ ادمین به تشخیصِ فیلترِ تبلیغات: ''/'correct'/'incorrect'
    flag_chat_id        INTEGER,        -- چت/پیامِ ریپلایِ توضیحاتِ فلگ (مکانیزمِ قدیمی‌تر؛ نگاه کن به set_pending_flag_message - فعلاً پیش‌فرض ازش استفاده نمی‌شه چون دکمه‌ها مستقیم رویِ خودِ پست‌ان)
    flag_message_id     INTEGER,
    owner_user_id      INTEGER,
    wm_base_photo      BLOB,                     -- عکسِ پایه قبل از چیدنِ واترمارک‌های دلخواهِ دستی
    wm_picks_json      TEXT NOT NULL DEFAULT '[]', -- لیستِ واترمارک‌های دلخواهِ دستی‌چیده‌شده روی این پست
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_posts(status);

CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    telegram_id       INTEGER,
    approval_chat_id  INTEGER NOT NULL,
    active            INTEGER NOT NULL DEFAULT 1,
    permissions       TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS destination_warnings (
    destination_id   INTEGER NOT NULL,
    owner_user_id    INTEGER NOT NULL DEFAULT 0,
    warned_at        TEXT DEFAULT '',
    chat_id          INTEGER,
    message_id       INTEGER,
    public_chat_id   INTEGER,
    public_message_id INTEGER,
    PRIMARY KEY (destination_id, owner_user_id)
);

-- جدول‌های جدید برای قابلیت‌های ۱۰ گانه
CREATE TABLE IF NOT EXISTS duplicate_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,
    media_hash TEXT,
    source_channel_id INTEGER NOT NULL,
    source_post_id INTEGER NOT NULL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_duplicate_hash ON duplicate_log(content_hash);
CREATE INDEX IF NOT EXISTS idx_duplicate_media ON duplicate_log(media_hash);

-- ردِ محتوایی که واقعاً به هر مقصد ارسال شده (نه هر پستِ رسیده از هر مبدأ)؛
-- برای این‌که اگه چند کانالِ مبدأ به یک مقصد وصل باشن، پستِ مشابه دوباره به
-- همون مقصد نره - فارغ از این‌که از کدوم کانالِ مبدأ اومده باشه.
CREATE TABLE IF NOT EXISTS destination_content_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    dup_words TEXT,
    source_channel_id INTEGER,
    source_post_id INTEGER,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_dest_content_dest ON destination_content_log(destination_id);
CREATE INDEX IF NOT EXISTS idx_dest_content_hash ON destination_content_log(content_hash);

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

-- جدول لاگ‌های حرفه‌ای
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    channel_id INTEGER,
    destination_id INTEGER,
    user_id INTEGER,
    post_id INTEGER,
    status TEXT,
    jalali_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_type ON system_logs(log_type);
CREATE INDEX IF NOT EXISTS idx_logs_severity ON system_logs(severity);
CREATE INDEX IF NOT EXISTS idx_logs_date ON system_logs(jalali_date);

-- تنظیماتِ اختصاصیِ هر کاربر (واترمارک/امضا/قالب‌بندی) - جدا از settings سراسری
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, key)
);

-- ==========================================================================
-- سیستمِ ارسالِ دستی + زمان‌بندی (فازِ ۱و۲و۳). هر ردیف = یک «پست» برایِ یک
-- مقصدِ مشخص. اگه یک پست باید به چند مقصد بره، چند ردیف جدا ساخته می‌شه (هر
-- مقصد یک ردیفِ مستقل با scheduled_at یکسان) - این باعث می‌شه شمارشِ «تعداد
-- پستِ هر تاریخ» و مدیریتِ جداگانه‌ی هر مقصد ساده و بدونِ ابهام بمونه.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS manual_posts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id      INTEGER,
    created_by_tg_id   INTEGER,
    status             TEXT NOT NULL DEFAULT 'draft',
    media_json         TEXT NOT NULL DEFAULT '[]',
    caption_html       TEXT NOT NULL DEFAULT '',
    buttons_json       TEXT NOT NULL DEFAULT '[]',
    watermark_enabled  INTEGER NOT NULL DEFAULT 1,
    destination_id     INTEGER,
    scheduled_at       TEXT DEFAULT '',
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_at            TEXT DEFAULT '',
    error_reason       TEXT DEFAULT '',
    retry_count        INTEGER NOT NULL DEFAULT 0,
    sent_chat_id       TEXT DEFAULT '',
    sent_message_id    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_manual_status ON manual_posts(status);
CREATE INDEX IF NOT EXISTS idx_manual_sched ON manual_posts(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_manual_owner ON manual_posts(owner_user_id);

-- ==========================================================================
-- واترمارکِ سفارشی (بخشِ ۷، ۸، ۹، ۱۰): هر ردیف یک واترمارکِ نام‌دارِ
-- اختصاصی (تصویری یا متنیِ محو) که owner_user_id مالکشه (Isolation کاملِ
-- کاربران - بخشِ ۹) و می‌تونه به چند مقصد اختصاص داده بشه.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS custom_watermarks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id     INTEGER,
    name              TEXT NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'image',   -- 'image' یا 'text'
    image_file_id     TEXT DEFAULT '',                  -- برایِ kind='image' (لوگویِ آپلودی)
    text              TEXT DEFAULT '',                  -- برایِ kind='text'
    font              TEXT DEFAULT 'Vazirmatn-Bold.ttf',
    transparency      INTEGER NOT NULL DEFAULT 60,       -- 0-100
    size_pct          INTEGER NOT NULL DEFAULT 30,       -- درصدِ عرضِ عکس
    rotation          INTEGER NOT NULL DEFAULT 0,        -- درجه
    position          TEXT NOT NULL DEFAULT 'bottom_right',
    x_pos             INTEGER,                           -- اگه ست بشه، بجایِ position از X/Y دقیق استفاده میشه
    y_pos             INTEGER,
    tiled             INTEGER NOT NULL DEFAULT 0,        -- فقط برایِ kind='text': کاشی‌شده روی قطرِ عکس (پس‌زمینه‌ای)
    color_a           TEXT NOT NULL DEFAULT '#FFFFFF',   -- رنگِ اصلیِ متنِ محو (یا شروعِ گرادیانت)
    color_b           TEXT NOT NULL DEFAULT '',          -- رنگِ پایانِ گرادیانت (خالی = بدونِ گرادیانت)
    color_mode        TEXT NOT NULL DEFAULT 'single',    -- 'single' یا 'gradient'
    album_all         INTEGER NOT NULL DEFAULT 1,        -- برایِ آلبوم: رویِ همه‌ی عکس‌ها (1) یا فقط اولی (0)
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wm_owner ON custom_watermarks(owner_user_id);

CREATE TABLE IF NOT EXISTS watermark_destinations (
    watermark_id   INTEGER NOT NULL,
    destination_id INTEGER NOT NULL,
    PRIMARY KEY (watermark_id, destination_id)
);

-- ==========================================================================
-- سیستمِ مدیریتِ API هوش مصنوعی (متنی + تصویری، ۱۶ سرویس) - ایزوله بین
-- ادمین (owner_user_id = NULL) و هر کاربر (owner_user_id = users.id). دقیقاً
-- مثلِ الگویِ channels/destinations، برای یکتاییِ (owner, service) از یک
-- UNIQUE INDEX جدا با COALESCE استفاده می‌شه چون NULL در UNIQUE ستونیِ
-- SQLite هیچ‌وقت با NULL دیگه‌ای برابر در نظر گرفته نمی‌شه.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS ai_providers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id       INTEGER,
    service_id          TEXT NOT NULL,
    api_key_encrypted   TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'not_set',
    status_detail       TEXT NOT NULL DEFAULT '',
    last_checked_at     TEXT NOT NULL DEFAULT '',
    total_requests      INTEGER NOT NULL DEFAULT 0,
    total_errors        INTEGER NOT NULL DEFAULT 0,
    total_response_ms   INTEGER NOT NULL DEFAULT 0,
    last_used_at        TEXT NOT NULL DEFAULT '',
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_providers_owner_service
    ON ai_providers (COALESCE(owner_user_id, 0), service_id);
CREATE INDEX IF NOT EXISTS idx_ai_providers_owner ON ai_providers(owner_user_id);

-- چندکلیدی: به‌ازایِ هر (owner, service) تا ۵ کلیدِ API قابلِ ثبته (slot ۱ تا ۵).
-- وقتی چند اکانت برایِ یک سرویس (مثلاً چند اکانتِ Gemini) داری، بعدِ اتمامِ
-- Quota یک کلید یا به‌طورِ چرخشی بعدِ هر درخواست، خودکار می‌ره سراغِ کلیدِ بعدی.
-- منطقِ چرخش/Fallback در ai_provider_manager.py (_pick_key / call_text / call_image).
CREATE TABLE IF NOT EXISTS ai_provider_keys (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id       INTEGER,
    service_id          TEXT NOT NULL,
    slot                INTEGER NOT NULL,
    label               TEXT NOT NULL DEFAULT '',
    api_key_encrypted   TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'not_set',
    status_detail       TEXT NOT NULL DEFAULT '',
    last_checked_at     TEXT NOT NULL DEFAULT '',
    cooldown_until      TEXT NOT NULL DEFAULT '',
    total_requests      INTEGER NOT NULL DEFAULT 0,
    total_errors        INTEGER NOT NULL DEFAULT 0,
    total_response_ms   INTEGER NOT NULL DEFAULT 0,
    last_used_at        TEXT NOT NULL DEFAULT '',
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_keys_owner_service_slot
    ON ai_provider_keys (COALESCE(owner_user_id, 0), service_id, slot);
CREATE INDEX IF NOT EXISTS idx_ai_provider_keys_owner_service
    ON ai_provider_keys (COALESCE(owner_user_id, 0), service_id);

-- مسیریابیِ وظایف: برایِ هر (owner, task) یک Provider اصلی و یک Provider
-- زاپاس (Fallback) اختیاری. اگه provider_service_id خالی باشه یعنی «پیش‌فرضِ
-- سیستم» (کلیدهایِ .env / منطقِ داخلیِ فعلی) استفاده می‌شه.
CREATE TABLE IF NOT EXISTS ai_task_routes (
    owner_user_id         INTEGER,
    task_id               TEXT NOT NULL,
    provider_service_id   TEXT NOT NULL DEFAULT '',
    fallback_service_id   TEXT NOT NULL DEFAULT '',
    updated_at            TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_task_routes_owner_task
    ON ai_task_routes (COALESCE(owner_user_id, 0), task_id);
"""

DEFAULT_USER_PERMISSIONS: dict[str, bool] = {
    # مدیریتِ کاربرانِ دیگه («usr») دیگه یه دسترسیِ قابل‌اعطا نیست — این کار
    # همیشه فقط مخصوصِ ادمین‌های سراسریه (ADMIN_IDS)، حتی اگه توی دیتابیسِ
    # قدیمیِ یک کاربر مقدارِ ذخیره‌شده‌ی "usr" هنوز باشه، get_permissions
    # چون این کلید دیگه توی این دیکشنری نیست، نادیده‌ش می‌گیره.
    "src": True,
    "dst": True,
    "wm": True,
    "ai": True,
    "format": True,
    "footer": True,
    "adfilter": True,
    "pp_own": True,
    "pp_edit": True,
    "pp_all": False,
    "manual": False,
}


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        try:
            self._init_schema()
        except sqlite3.Error as e:
            log.exception("ساختِ اسکیمای اولیه‌ی دیتابیس (%s) شکست خورد: %s", self.path, e)
            raise
        try:
            self._migrate_legacy_target()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ کانالِ مقصدِ قدیمی (target_chat_id) شکست خورد: %s", e)
            raise
        try:
            self._migrate_new_columns()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ ستون‌های جدیدِ جدولِ channels/pending_posts شکست خورد: %s", e)
            raise
        try:
            self._migrate_watermark_platforms()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ تنظیماتِ واترمارکِ قدیمی به تلگرام/اینستاگرام شکست خورد: %s", e)
            raise
        try:
            self._init_new_tables()
        except sqlite3.Error as e:
            log.exception("ساخت جداول جدید (duplicate_log, channel_stats, system_logs) شکست خورد: %s", e)
            raise
        try:
            self._migrate_manual_phase4to14()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ ستون‌های فازِ ۴ تا ۱۴ (صفِ حرفه‌ای/واترمارکِ سفارشی) شکست خورد: %s", e)
            raise
        try:
            self._migrate_watermark_tiled_gradient()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ ستون‌هایِ کاشی‌شده/گرادیانتِ واترمارکِ سفارشی شکست خورد: %s", e)
            raise
        try:
            self._migrate_pending_wm_picks()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ ستون‌های جدیدِ سیستمِ ارسالِ دستی (صف/واترمارکِ سفارشی) شکست خورد: %s", e)
            raise
        try:
            self._migrate_channel_dest_ownership_unique()
        except sqlite3.Error as e:
            log.exception(
                "مهاجرتِ رفعِ یکتاییِ سراسریِ کانال/مقصد (اجازه‌ی ثبتِ یک کانال توسطِ چند مالک) شکست خورد: %s",
                e,
            )
            raise
        try:
            self._migrate_ai_provider_keys_from_legacy()
        except sqlite3.Error as e:
            log.exception("مهاجرتِ کلیدهایِ تک‌اسلاتیِ قدیمیِ AI به سیستمِ چندکلیدی شکست خورد: %s", e)
            raise

    def _init_schema(self):
        with _lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
            for k, v in DEFAULT_SETTINGS.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
                )
            self._conn.commit()

    def _init_new_tables(self):
        # جداول جدید قبلاً در SCHEMA تعریف شده‌اند
        pass

    def _migrate_new_columns(self):
        with _lock:
            existing_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(channels)").fetchall()
            }
            alters = {
                "approval_required": "ALTER TABLE channels ADD COLUMN approval_required INTEGER NOT NULL DEFAULT 0",
                "send_mode": "ALTER TABLE channels ADD COLUMN send_mode TEXT NOT NULL DEFAULT 'schedule'",
                "interval_minutes": "ALTER TABLE channels ADD COLUMN interval_minutes INTEGER NOT NULL DEFAULT 30",
                "last_interval_run": "ALTER TABLE channels ADD COLUMN last_interval_run TEXT DEFAULT ''",
                "overrides": "ALTER TABLE channels ADD COLUMN overrides TEXT NOT NULL DEFAULT '{}'",
                "owner_user_id": "ALTER TABLE channels ADD COLUMN owner_user_id INTEGER",
                # منابعِ اکستنشنِ مرورگر: source_type='extension' یعنی این کانال فقط
                # از طریقِ اکستنشنِ کروم/اج تغذیه میشه (نه اسکرپِ عمومیِ t.me/s/...)
                # و send_mode برای این نوع همیشه 'extension' ثبت میشه (نه یکی از سه
                # حالتِ schedule/instant/interval) تا scheduler.py اصلاً بهش دست نزنه.
                "source_type": "ALTER TABLE channels ADD COLUMN source_type TEXT NOT NULL DEFAULT 'scrape'",
                "ext_peer_ref": "ALTER TABLE channels ADD COLUMN ext_peer_ref TEXT DEFAULT ''",
            }
            for col, ddl in alters.items():
                if col not in existing_cols:
                    self._conn.execute(ddl)

            pending_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(pending_posts)").fetchall()
            }
            if "flag_reason" not in pending_cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN flag_reason TEXT DEFAULT ''")
            if "owner_user_id" not in pending_cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN owner_user_id INTEGER")
            if "override_video" not in pending_cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN override_video BLOB")
            if "original_caption_html" not in pending_cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN original_caption_html TEXT DEFAULT ''")
                # برای پست‌های قدیمی‌ای که از قبلِ این ستون توی صف موندن، تنها
                # مقدارِ در دسترس همون کپشنِ فعلیه (ممکنه از قبل با AI عوض شده
                # باشه، ولی بهتره از هیچی داشتنِ نسخه‌ی اصلی).
                self._conn.execute(
                    "UPDATE pending_posts SET original_caption_html = caption_html "
                    "WHERE original_caption_html IS NULL OR original_caption_html = ''"
                )
            if "body_html" not in pending_cols:
                # متنِ بدنه‌ی خامِ پست (بدونِ امضا) — برای ساختنِ امضای مختصِ هر
                # مقصد در لحظه‌ی ارسالِ پست‌های تاییدشده. برای پست‌های قدیمیِ توی
                # صف که این ستون رو ندارن، خالی می‌مونه و اون‌ها طبقِ روالِ قبلی
                # (کپشنِ ذخیره‌شده‌ی سطحِ کانال) فرستاده می‌شن.
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN body_html TEXT DEFAULT ''")
            if "ad_feedback" not in pending_cols:
                # فیدبکِ ادمین به تصمیمِ فیلترِ تبلیغات، برای همون پستی که به‌خاطرِ
                # مشکوک بودن به تبلیغ به صفِ تایید فرستاده شده: ''=هنوز فیدبکی
                # ثبت نشده، 'correct'=تشخیص درست بود (واقعاً تبلیغ بود)،
                # 'incorrect'=اشتباه بود (تبلیغ نبود). نگاه کن به
                # set_pending_ad_feedback/get_ad_feedback_channel_stats.
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN ad_feedback TEXT DEFAULT ''")
            if "flag_chat_id" not in pending_cols:
                # چت/پیامِ جداگانه‌ای که توضیحاتِ کاملِ فلگِ فیلترِ تبلیغات توش
                # ریپلای‌شده روی خودِ پست (نگاه کن به poster.send_pending_preview و
                # poster.set_pending_flag_message/_pending_flag_kb) - این مکانیزم
                # فعلاً به‌صورتِ پیش‌فرض غیرفعاله (دکمه‌های فیدبک مستقیم رویِ خودِ
                # پست‌ان)، ولی ستون‌هاش برای سازگاریِ عقب‌رو نگه داشته شدن.
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN flag_chat_id INTEGER")
            if "flag_message_id" not in pending_cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN flag_message_id INTEGER")
            if "ad_filter_detail" not in pending_cols:
                # جزئیاتِ ساختاریافته‌ی موتورِ فیلترِ تبلیغات (JSON) به‌ازایِ هر پستی
                # که به‌خاطرِ مشکوک‌بودن به تبلیغ به صفِ تایید افتاده: امتیاز/آستانه‌ی
                # موتورِ قاعده‌محور، نتیجه‌ی هر داورِ AI، کلیدواژه‌های تطبیق‌یافته و....
                # پست‌های قدیمی که این ستون رو ندارن، خالی می‌مونه (در اکسل فقط
                # ستون‌های ساختاریافته‌شون خالی می‌مونه، بدونِ خطا).
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN ad_filter_detail TEXT DEFAULT ''")

            user_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "permissions" not in user_cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '{}'")

            dest_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(destinations)").fetchall()
            }
            if "last_sent_at" not in dest_cols:
                self._conn.execute("ALTER TABLE destinations ADD COLUMN last_sent_at TEXT DEFAULT ''")
            if "owner_user_id" not in dest_cols:
                self._conn.execute("ALTER TABLE destinations ADD COLUMN owner_user_id INTEGER")
            if "total_warnings" not in dest_cols:
                self._conn.execute("ALTER TABLE destinations ADD COLUMN total_warnings INTEGER NOT NULL DEFAULT 0")
            if "last_post_link" not in dest_cols:
                self._conn.execute("ALTER TABLE destinations ADD COLUMN last_post_link TEXT DEFAULT ''")

            dw_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(destination_warnings)").fetchall()
            }
            if "public_chat_id" not in dw_cols:
                self._conn.execute("ALTER TABLE destination_warnings ADD COLUMN public_chat_id INTEGER")
            if "public_message_id" not in dw_cols:
                self._conn.execute("ALTER TABLE destination_warnings ADD COLUMN public_message_id INTEGER")

            dup_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(duplicate_log)").fetchall()
            }
            if "dup_words" not in dup_cols:
                # کلماتِ معنادارِ نرمال‌شده‌ی متنِ پست (برای تشخیصِ تشابهِ فازی، نه
                # فقط تطابقِ دقیقِ هش). NULL برای ردیف‌های قدیمی، بی‌مشکل.
                self._conn.execute("ALTER TABLE duplicate_log ADD COLUMN dup_words TEXT")

            ai_prov_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(ai_providers)").fetchall()
            }
            if "rotation_cursor" not in ai_prov_cols:
                # اشاره‌گرِ چرخشِ کلیدها: بعدِ هر فراخوانیِ موفق روی slotِ بعدی
                # تنظیم می‌شه تا درخواست‌هایِ بعدی به‌طورِ چرخشی بینِ کلیدهایِ
                # ثبت‌شده‌ی این سرویس (ai_provider_keys) تقسیم بشن.
                self._conn.execute("ALTER TABLE ai_providers ADD COLUMN rotation_cursor INTEGER NOT NULL DEFAULT 0")

            self._conn.commit()

    def _migrate_ai_provider_keys_from_legacy(self):
        """کلیدِ تک‌اسلاتیِ قدیمیِ هر (owner, service) در ai_providers رو - اگه
        هنوز توی ai_provider_keys منتقل نشده - به‌عنوانِ slot=1 کپی می‌کنه، تا
        کاربرهایی که از قبلِ این آپدیت یک کلید ثبت کرده بودن چیزی رو از دست
        ندن. Idempotent: فقط وقتی این (owner, service) هیچ ردیفی توی
        ai_provider_keys نداشته باشه اجرا می‌شه."""
        with _lock:
            legacy_rows = self._conn.execute(
                "SELECT * FROM ai_providers WHERE api_key_encrypted != ''"
            ).fetchall()
            for row in legacy_rows:
                exists = self._conn.execute(
                    "SELECT 1 FROM ai_provider_keys WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
                    (row["owner_user_id"], row["service_id"]),
                ).fetchone()
                if exists:
                    continue
                self._conn.execute(
                    """INSERT INTO ai_provider_keys
                       (owner_user_id, service_id, slot, api_key_encrypted, status, status_detail,
                        last_checked_at, total_requests, total_errors, total_response_ms, last_used_at)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["owner_user_id"], row["service_id"], row["api_key_encrypted"],
                        row["status"], row["status_detail"], row["last_checked_at"],
                        row["total_requests"], row["total_errors"], row["total_response_ms"],
                        row["last_used_at"],
                    ),
                )
            self._conn.commit()

    def _migrate_channel_dest_ownership_unique(self):
        """قبلاً username کانال و chat_id مقصد به‌صورتِ سراسری UNIQUE بودن؛
        یعنی اگه ادمین یا یک کاربر یه کانال/مقصدِ خاص رو ثبت کرده بود، هیچ
        مالکِ دیگه‌ای (نه ادمین، نه کاربرِ دیگه) نمی‌تونست دقیقاً همون کانال/
        مقصد رو مستقل و با تنظیماتِ خودش ثبت کنه. حالا یکتایی فقط در سطحِ
        (username, owner_user_id) / (chat_id, owner_user_id) اعمال می‌شه.
        اگه دیتابیسِ قدیمی هنوز اون UNIQUE سراسری رو روی خودِ جدول داشته باشه
        (که ALTER TABLE نمی‌تونه حذفش کنه)، جدول رو با ساختارِ جدید بازسازی
        می‌کنیم و داده‌ها رو منتقل می‌کنیم."""
        def _has_global_unique(table: str, column: str) -> bool:
            """تشخیصِ این‌که آیا جدول هنوز یک UNIQUE تک‌ستونیِ خودکار (autoindex)
            روی این ستون داره یا نه - مستقل از فاصله‌ها/فرمتِ متنِ SQL."""
            for idx in self._conn.execute(f"PRAGMA index_list({table})").fetchall():
                if not idx["unique"]:
                    continue
                cols = self._conn.execute(f"PRAGMA index_info({idx['name']})").fetchall()
                if len(cols) == 1 and cols[0]["name"] == column:
                    return True
            return False

        with _lock:
            if _has_global_unique("channels", "username"):
                log.info("بازسازیِ جدولِ channels برایِ حذفِ یکتاییِ سراسریِ username ...")
                self._conn.execute("ALTER TABLE channels RENAME TO channels_old_unique")
                self._conn.executescript(
                    """
                    CREATE TABLE channels (
                        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                        username           TEXT NOT NULL,
                        title              TEXT DEFAULT '',
                        active             INTEGER NOT NULL DEFAULT 1,
                        last_post_id       INTEGER NOT NULL DEFAULT 0,
                        last_sent_at       TEXT,
                        created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
                        approval_required  INTEGER NOT NULL DEFAULT 0,
                        send_mode          TEXT NOT NULL DEFAULT 'schedule',
                        interval_minutes   INTEGER NOT NULL DEFAULT 30,
                        last_interval_run  TEXT DEFAULT '',
                        overrides          TEXT NOT NULL DEFAULT '{}',
                        owner_user_id      INTEGER
                    );
                    """
                )
                old_cols = {
                    row["name"] for row in self._conn.execute(
                        "PRAGMA table_info(channels_old_unique)"
                    ).fetchall()
                }
                common = [c for c in (
                    "id", "username", "title", "active", "last_post_id", "last_sent_at",
                    "created_at", "approval_required", "send_mode", "interval_minutes",
                    "last_interval_run", "overrides", "owner_user_id",
                ) if c in old_cols]
                cols_sql = ", ".join(common)
                self._conn.execute(
                    f"INSERT INTO channels ({cols_sql}) SELECT {cols_sql} FROM channels_old_unique"
                )
                self._conn.execute("DROP TABLE channels_old_unique")

            if _has_global_unique("destinations", "chat_id"):
                log.info("بازسازیِ جدولِ destinations برایِ حذفِ یکتاییِ سراسریِ chat_id ...")
                self._conn.execute("ALTER TABLE destinations RENAME TO destinations_old_unique")
                self._conn.executescript(
                    """
                    CREATE TABLE destinations (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id     TEXT NOT NULL,
                        title       TEXT DEFAULT '',
                        active      INTEGER NOT NULL DEFAULT 1,
                        last_sent_at TEXT DEFAULT '',
                        created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                        owner_user_id INTEGER,
                        total_warnings INTEGER NOT NULL DEFAULT 0,
                        last_post_link TEXT DEFAULT ''
                    );
                    """
                )
                old_cols = {
                    row["name"] for row in self._conn.execute(
                        "PRAGMA table_info(destinations_old_unique)"
                    ).fetchall()
                }
                common = [c for c in (
                    "id", "chat_id", "title", "active", "last_sent_at", "created_at",
                    "owner_user_id", "total_warnings", "last_post_link",
                ) if c in old_cols]
                cols_sql = ", ".join(common)
                self._conn.execute(
                    f"INSERT INTO destinations ({cols_sql}) SELECT {cols_sql} FROM destinations_old_unique"
                )
                self._conn.execute("DROP TABLE destinations_old_unique")

            # ایندکسِ یکتاییِ جدید (به‌ازایِ هر مالک) - اگه از قبل نباشه ساخته می‌شه.
            # این‌جا هم (نه فقط توی SCHEMA) دوباره اجرا می‌شه چون برایِ دیتابیس‌هایِ
            # قدیمی که تازه بازسازی شدن، باید بعدِ بازسازی ساخته بشه.
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_username_owner "
                "ON channels (username, COALESCE(owner_user_id, 0))"
            )
            self._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_destinations_chatid_owner "
                "ON destinations (chat_id, COALESCE(owner_user_id, 0))"
            )
            self._conn.commit()

    def _migrate_manual_phase4to14(self):
        """اضافه‌کردنِ ستون‌هایِ جدیدِ فازِ ۴ تا ۱۴ (صفِ حرفه‌ای + واترمارکِ
        سفارشی) به جدولِ manual_posts که در فازِ اول ساخته شده بود."""
        with _lock:
            cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(manual_posts)").fetchall()
            }
            if "watermark_id" not in cols:
                self._conn.execute("ALTER TABLE manual_posts ADD COLUMN watermark_id INTEGER")
            if "queue_order" not in cols:
                self._conn.execute("ALTER TABLE manual_posts ADD COLUMN queue_order INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def _migrate_watermark_tiled_gradient(self):
        """ادغامِ قابلیتِ «واترمارکِ متنیِ کاشی‌شده روی قطر + رنگِ گرادیانت» از
        نسخه‌ی جداگانه‌ای که این افکت مستقیماً توی watermark.py پیاده شده بود؛
        این ستون‌ها به همون جدولِ custom_watermarks (سیستمِ کامل‌ترِ منو/دیتابیس/
        اختصاصِ مقصد) اضافه می‌شن تا هر دو قابلیت زیرِ یک سیستمِ واحد باشن."""
        with _lock:
            cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(custom_watermarks)").fetchall()
            }
            if "tiled" not in cols:
                self._conn.execute("ALTER TABLE custom_watermarks ADD COLUMN tiled INTEGER NOT NULL DEFAULT 0")
            if "color_a" not in cols:
                self._conn.execute("ALTER TABLE custom_watermarks ADD COLUMN color_a TEXT NOT NULL DEFAULT '#FFFFFF'")
            if "color_b" not in cols:
                self._conn.execute("ALTER TABLE custom_watermarks ADD COLUMN color_b TEXT NOT NULL DEFAULT ''")
            if "color_mode" not in cols:
                self._conn.execute("ALTER TABLE custom_watermarks ADD COLUMN color_mode TEXT NOT NULL DEFAULT 'single'")
            if "album_all" not in cols:
                self._conn.execute("ALTER TABLE custom_watermarks ADD COLUMN album_all INTEGER NOT NULL DEFAULT 1")
            self._conn.commit()

    def _migrate_pending_wm_picks(self):
        """اضافه‌کردنِ ستون‌هایِ لازم برایِ «چیدنِ دستیِ واترمارک‌هایِ دلخواه رویِ
        یک پستِ خاص در صفِ تایید» (پورت‌شده از نسخه‌ای که این قابلیت رو مستقیم
        توی poster.py پیاده کرده بود)."""
        with _lock:
            cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(pending_posts)").fetchall()
            }
            if "wm_base_photo" not in cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN wm_base_photo BLOB")
            if "wm_picks_json" not in cols:
                self._conn.execute("ALTER TABLE pending_posts ADD COLUMN wm_picks_json TEXT NOT NULL DEFAULT '[]'")
            self._conn.commit()


    def _migrate_watermark_platforms(self):
        flag_key = "_migrated_watermark_platforms_v1"
        if self.get_setting(flag_key):
            return
        old_text = self.get_setting("watermark_text")
        old_pos = self.get_setting("watermark_position")
        old_c1 = self.get_setting("watermark_color_start")
        old_c2 = self.get_setting("watermark_color_end")
        old_opacity = self.get_setting("watermark_bg_opacity")
        old_fontsize = self.get_setting("watermark_font_size")
        old_margin = self.get_setting("watermark_margin")
        old_album = self.get_setting("watermark_all_album_photos")
        if old_text:
            self.set_setting("wm_tg_text", old_text)
        if old_pos:
            self.set_setting("wm_tg_position", old_pos)
        if old_c1:
            self.set_setting("wm_tg_color_a", old_c1)
        if old_c2:
            self.set_setting("wm_tg_color_b", old_c2)
        if old_opacity:
            self.set_setting("wm_tg_bg_opacity", old_opacity)
        if old_fontsize:
            self.set_setting("wm_tg_font_size", old_fontsize)
        if old_margin:
            self.set_setting("wm_tg_margin", old_margin)
        if old_album:
            self.set_setting("wm_tg_album_all", old_album)
        self.set_setting(flag_key, "1")

    def _migrate_legacy_target(self):
        with _lock:
            existing = self._conn.execute("SELECT COUNT(*) c FROM destinations").fetchone()["c"]
            if existing:
                return
            legacy = (self.get_setting("target_chat_id") or config.TARGET_CHAT_ID_ENV or "").strip()
            if not legacy:
                return
            try:
                self._conn.execute(
                    "INSERT INTO destinations (chat_id, title) VALUES (?, ?)", (legacy, "")
                )
                dest_id = self._conn.execute(
                    "SELECT id FROM destinations WHERE chat_id=?", (legacy,)
                ).fetchone()["id"]
                for ch in self._conn.execute("SELECT id FROM channels").fetchall():
                    self._conn.execute(
                        "INSERT OR IGNORE INTO channel_destinations (channel_id, destination_id) VALUES (?, ?)",
                        (ch["id"], dest_id),
                    )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                log.warning(
                    "مهاجرتِ کانالِ مقصدِ قدیمی (%s) با یک تداخلِ کلیدِ تکراری مواجه شد: %s", legacy, e,
                )

    # ---------------- settings ----------------
    def get_setting(self, key: str, default: str = "") -> str:
        cur = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row and row["value"] is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        raw = self.get_setting(key, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            log.warning(
                "مقدارِ ذخیره‌شده برای تنظیمِ '%s' عددِ صحیح نیست (مقدار: %r)؛ "
                "مقدارِ پیش‌فرضِ %s جایگزین شد.", key, raw, default,
            )
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.get_setting(key, "1" if default else "0")
        return v in ("1", "true", "True", "yes")

    def set_setting(self, key: str, value: Any):
        with _lock:
            self._conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, str(value)),
            )
            self._conn.commit()

    def all_settings(self) -> dict[str, str]:
        cur = self._conn.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}

    # ---------------- تنظیماتِ مختصِ کاربر (واترمارک/امضا/قالب‌بندی) ----------------
    def get_user_setting(self, user_id: int, key: str, default: str | None = None) -> str:
        cur = self._conn.execute(
            "SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key)
        )
        row = cur.fetchone()
        if row is not None and row["value"] is not None:
            return row["value"]
        if default is not None:
            return default
        return DEFAULT_USER_SETTINGS.get(key, "")

    def get_user_int(self, user_id: int, key: str, default: int = 0) -> int:
        raw = self.get_user_setting(user_id, key, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def get_user_bool(self, user_id: int, key: str, default: bool = False) -> bool:
        v = self.get_user_setting(user_id, key, "1" if default else "0")
        return v in ("1", "true", "True", "yes")

    def set_user_setting(self, user_id: int, key: str, value: Any) -> None:
        with _lock:
            self._conn.execute(
                """INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value""",
                (user_id, key, str(value)),
            )
            self._conn.commit()

    def all_user_settings(self, user_id: int) -> dict[str, str]:
        cur = self._conn.execute("SELECT key, value FROM user_settings WHERE user_id=?", (user_id,))
        merged = dict(DEFAULT_USER_SETTINGS)
        merged.update({r["key"]: r["value"] for r in cur.fetchall()})
        return merged

    # ---- نگاشتِ عمومی «سراسری یا مختصِ کاربر» ----
    # owner_user_id=None یعنی تنظیمِ سراسری/ادمین (رفتارِ قبلی)؛ owner_user_id یک
    # عدد یعنی تنظیمِ اختصاصیِ همون کاربر - کاملاً جدا از بقیه‌ی کاربران و از ادمین.
    def setting_get(self, key: str, default: str = "", owner_user_id: int | None = None) -> str:
        if owner_user_id:
            return self.get_user_setting(owner_user_id, key, default)
        return self.get_setting(key, default)

    def setting_get_int(self, key: str, default: int = 0, owner_user_id: int | None = None) -> int:
        if owner_user_id:
            return self.get_user_int(owner_user_id, key, default)
        return self.get_int(key, default)

    def setting_get_bool(self, key: str, default: bool = False, owner_user_id: int | None = None) -> bool:
        if owner_user_id:
            return self.get_user_bool(owner_user_id, key, default)
        return self.get_bool(key, default)

    def setting_set(self, key: str, value: Any, owner_user_id: int | None = None) -> None:
        if owner_user_id:
            self.set_user_setting(owner_user_id, key, value)
        else:
            self.set_setting(key, value)

# ---------------- channels (منابع) ----------------
    def add_channel(self, username: str, title: str = "", owner_user_id: int | None = None) -> bool:
        try:
            with _lock:
                cur = self._conn.execute(
                    "INSERT INTO channels (username, title, owner_user_id) VALUES (?, ?, ?)",
                    (username.lower(), title, owner_user_id),
                )
                channel_id = cur.lastrowid
                for idx in range(1, SLOTS_PER_CHANNEL + 1):
                    default_time = DEFAULT_SLOT_TIMES[idx - 1] if idx - 1 < len(DEFAULT_SLOT_TIMES) else ""
                    self._conn.execute(
                        "INSERT INTO schedule_slots (channel_id, slot_index, slot_time, enabled) "
                        "VALUES (?, ?, ?, 1)",
                        (channel_id, idx, default_time),
                    )
                self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            log.info("افزودنِ کانالِ مبدأ @%s رد شد چون از قبل ثبت شده بود.", username)
            return False

    # ---------------- منابعِ اکستنشنِ مرورگر ----------------
    def get_extension_channel_by_ref(self, ext_peer_ref: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM channels WHERE source_type='extension' AND ext_peer_ref=?",
            (ext_peer_ref,),
        )
        return cur.fetchone()

    def upsert_extension_channel(self, ext_peer_ref: str, title: str = "") -> sqlite3.Row:
        """اگه این گروه/کانال قبلاً از طرفِ اکستنشن گزارش شده، فقط عنوانش رو
        به‌روز می‌کنه؛ وگرنه یک ردیفِ جدید می‌سازه که تا وقتی ادمین از داخلِ
        منویِ «منابع اکستنشن» فعالش نکنه، غیرفعال (active=0) و بی‌اثر می‌مونه.
        پیش‌فرض روی تاییدِ دستی (approval_required=1) قرار می‌گیره تا اولین
        پست‌های هر منبعِ جدید بدونِ چک ادمین جایی ارسال نشن."""
        with _lock:
            existing = self._conn.execute(
                "SELECT * FROM channels WHERE source_type='extension' AND ext_peer_ref=?",
                (ext_peer_ref,),
            ).fetchone()
            if existing:
                if title and title != existing["title"]:
                    self._conn.execute(
                        "UPDATE channels SET title=? WHERE id=?", (title, existing["id"])
                    )
                    self._conn.commit()
                return existing
            cur = self._conn.execute(
                "INSERT INTO channels "
                "(username, title, active, source_type, ext_peer_ref, send_mode, approval_required) "
                "VALUES (?, ?, 0, 'extension', ?, 'extension', 1)",
                (ext_peer_ref, title or ext_peer_ref, ext_peer_ref),
            )
            self._conn.commit()
            return self._conn.execute(
                "SELECT * FROM channels WHERE id=?", (cur.lastrowid,)
            ).fetchone()

    def list_extension_channels(self) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM channels WHERE source_type='extension' ORDER BY active DESC, id DESC"
        )
        return cur.fetchall()

    def remove_channel(self, channel_id: int):
        with _lock:
            self._conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
            self._conn.execute("DELETE FROM sent_log WHERE channel_id=?", (channel_id,))
            self._conn.execute("DELETE FROM schedule_slots WHERE channel_id=?", (channel_id,))
            self._conn.execute("DELETE FROM channel_destinations WHERE channel_id=?", (channel_id,))
            self._conn.commit()

    def toggle_channel(self, channel_id: int):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET active = 1 - active WHERE id=?", (channel_id,)
            )
            self._conn.commit()

    def set_channel_title(self, channel_id: int, title: str):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET title=? WHERE id=?", (title, channel_id)
            )
            self._conn.commit()

    def set_channel_approval(self, channel_id: int, required: bool):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET approval_required=? WHERE id=?",
                (1 if required else 0, channel_id),
            )
            self._conn.commit()

    def toggle_channel_approval(self, channel_id: int) -> bool:
        with _lock:
            self._conn.execute(
                "UPDATE channels SET approval_required = 1 - approval_required WHERE id=?",
                (channel_id,),
            )
            self._conn.commit()
        ch = self.get_channel(channel_id)
        return bool(ch["approval_required"]) if ch else False

    def set_channel_send_mode(self, channel_id: int, mode: str):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET send_mode=? WHERE id=?", (mode, channel_id)
            )
            self._conn.commit()

    def set_channel_interval_minutes(self, channel_id: int, minutes: int):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET interval_minutes=? WHERE id=?", (minutes, channel_id)
            )
            self._conn.commit()

    def set_channel_last_interval_run(self, channel_id: int, iso_ts: str):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET last_interval_run=? WHERE id=?", (iso_ts, channel_id)
            )
            self._conn.commit()

    def channels_by_send_mode(self, mode: str, active_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM channels WHERE send_mode=?"
        params: list[Any] = [mode]
        if active_only:
            q += " AND active=1"
        q += " ORDER BY id"
        return self._conn.execute(q, params).fetchall()

    def update_last_post(self, channel_id: int, post_id: int):
        with _lock:
            self._conn.execute(
                "UPDATE channels SET last_post_id=?, last_sent_at=? WHERE id=?",
                (post_id, datetime.utcnow().isoformat(), channel_id),
            )
            self._conn.commit()

    def get_channel(self, channel_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,))
        return cur.fetchone()

    def list_channels(self, active_only: bool = False, owner_user_id: int | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM channels"
        conds = []
        params: list = []
        if active_only:
            conds.append("active=1")
        if owner_user_id is not None:
            conds.append("owner_user_id=?")
            params.append(owner_user_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id"
        return self._conn.execute(q, params).fetchall()

    # ---------------- destinations (مقصدها) ----------------
    def add_destination(self, chat_id: str, title: str = "", owner_user_id: int | None = None) -> bool:
        try:
            with _lock:
                self._conn.execute(
                    "INSERT INTO destinations (chat_id, title, owner_user_id) VALUES (?, ?, ?)",
                    (chat_id, title, owner_user_id),
                )
                self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            log.info("افزودنِ مقصدِ %s رد شد چون از قبل ثبت شده بود.", chat_id)
            return False

    def remove_destination(self, destination_id: int):
        with _lock:
            self._conn.execute("DELETE FROM destinations WHERE id=?", (destination_id,))
            self._conn.execute(
                "DELETE FROM channel_destinations WHERE destination_id=?", (destination_id,)
            )
            self._conn.execute(
                "DELETE FROM destination_settings WHERE destination_id=?", (destination_id,)
            )
            self._conn.commit()

    # ----- تنظیماتِ اختصاصیِ هر مقصد (override): امضا و فیلترِ تبلیغاتِ جدا -----
    def dest_setting_get(self, destination_id: int, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM destination_settings WHERE destination_id=? AND key=?",
            (destination_id, key),
        ).fetchone()
        return row["value"] if row is not None else default

    def dest_setting_set(self, destination_id: int, key: str, value: Any) -> None:
        with _lock:
            self._conn.execute(
                "INSERT INTO destination_settings (destination_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(destination_id, key) DO UPDATE SET value=excluded.value",
                (destination_id, key, str(value)),
            )
            self._conn.commit()

    def dest_setting_get_bool(self, destination_id: int, key: str, default: bool = False) -> bool:
        raw = self.dest_setting_get(destination_id, key, "")
        if raw == "":
            return default
        return raw == "1"

    def dest_setting_get_int(self, destination_id: int, key: str, default: int = 0) -> int:
        raw = self.dest_setting_get(destination_id, key, "")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def toggle_destination(self, destination_id: int):
        with _lock:
            self._conn.execute(
                "UPDATE destinations SET active = 1 - active WHERE id=?", (destination_id,)
            )
            # بدونِ این commit، فعال/غیرفعال‌کردنِ مقصد توی تراکنشِ باز می‌موند و
            # فقط تصادفی (وقتی یک عملیاتِ دیگه commit می‌کرد) ذخیره می‌شد؛ یعنی
            # گاهی بعد از ری‌استارت تنظیم به حالتِ قبل برمی‌گشت.
            self._conn.commit()

    # ---------------------------------------------------------------------
    # سیستمِ ارسالِ دستی + زمان‌بندی (manual_posts)
    # ---------------------------------------------------------------------

    def create_manual_post(
        self,
        owner_user_id: int | None,
        created_by_tg_id: int | None,
        media_json: str = "[]",
        caption_html: str = "",
        buttons_json: str = "[]",
        watermark_enabled: bool = True,
        destination_id: int | None = None,
        scheduled_at: str = "",
        status: str = "draft",
    ) -> int:
        with _lock:
            cur = self._conn.execute(
                "INSERT INTO manual_posts "
                "(owner_user_id, created_by_tg_id, media_json, caption_html, buttons_json, "
                " watermark_enabled, destination_id, scheduled_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_user_id, created_by_tg_id, media_json, caption_html, buttons_json,
                    1 if watermark_enabled else 0, destination_id, scheduled_at, status,
                ),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_manual_post(self, post_id: int) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM manual_posts WHERE id=?", (post_id,)).fetchone()

    def update_manual_post(self, post_id: int, **fields) -> None:
        if not fields:
            return
        allowed = {
            "status", "media_json", "caption_html", "buttons_json", "watermark_enabled",
            "destination_id", "scheduled_at", "sent_at", "error_reason", "retry_count",
            "sent_chat_id", "sent_message_id", "watermark_id", "queue_order",
        }
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        with _lock:
            set_clause = ", ".join(f"{c}=?" for c in cols)
            values = [fields[c] for c in cols] + [post_id]
            self._conn.execute(f"UPDATE manual_posts SET {set_clause} WHERE id=?", values)
            self._conn.commit()

    def delete_manual_post(self, post_id: int) -> None:
        with _lock:
            self._conn.execute("DELETE FROM manual_posts WHERE id=?", (post_id,))
            self._conn.commit()

    def list_manual_posts(
        self, status: str | None = None, owner_user_id: int | None = None,
        all_scopes: bool = False,
    ) -> list[sqlite3.Row]:
        # ایزوله‌سازیِ چندکاربره: به‌صورتِ پیش‌فرض همیشه به یک «حوزه» محدود می‌شه؛
        # owner_user_id=None یعنی حوزه‌ی ادمینِ سراسری (فقط پست‌هایی که
        # owner_user_id-شون NULL است)، و یک عددِ صحیح یعنی فقط پست‌های همون کاربر.
        # فقط اگه صراحتاً all_scopes=True داده بشه، بدونِ فیلترِ مالک همه‌چیز برمی‌گرده.
        q = "SELECT * FROM manual_posts WHERE 1=1"
        params: list = []
        if status:
            q += " AND status=?"
            params.append(status)
        if not all_scopes:
            if owner_user_id is None:
                q += " AND owner_user_id IS NULL"
            else:
                q += " AND owner_user_id=?"
                params.append(owner_user_id)
        q += " ORDER BY COALESCE(NULLIF(scheduled_at, ''), created_at) ASC"
        return self._conn.execute(q, params).fetchall()

    def list_manual_dates(
        self, owner_user_id: int | None = None, all_scopes: bool = False
    ) -> list[sqlite3.Row]:
        """گروه‌بندیِ پست‌هایِ زمان‌بندی‌شده/در صف بر اساسِ تاریخ (بخشِ اولِ scheduled_at، یعنی YYYY-MM-DD میلادی).

        ایزوله‌سازیِ چندکاربره: owner_user_id=None یعنی فقط حوزه‌ی ادمینِ سراسری
        (پست‌هایِ با owner_user_id=NULL) و یک عددِ صحیح یعنی فقط همون کاربر؛ پس
        هیچ‌وقت پست‌های کاربرها با ادمین (یا کاربرها با هم) قاطی نمی‌شن."""
        q = (
            "SELECT substr(scheduled_at, 1, 10) AS d, COUNT(*) AS cnt "
            "FROM manual_posts WHERE scheduled_at != '' "
            "AND status IN ('scheduled', 'processing', 'sent', 'failed')"
        )
        params: list = []
        if not all_scopes:
            if owner_user_id is None:
                q += " AND owner_user_id IS NULL"
            else:
                q += " AND owner_user_id=?"
                params.append(owner_user_id)
        q += " GROUP BY d ORDER BY d ASC"
        return self._conn.execute(q, params).fetchall()

    def list_manual_posts_by_date(
        self, date_str: str, owner_user_id: int | None = None, all_scopes: bool = False
    ) -> list[sqlite3.Row]:
        # ایزوله‌سازیِ چندکاربره (مثلِ list_manual_dates): owner_user_id=None یعنی
        # فقط حوزه‌ی ادمین (owner_user_id=NULL)، عددِ صحیح یعنی فقط همون کاربر.
        q = "SELECT * FROM manual_posts WHERE substr(scheduled_at, 1, 10) = ?"
        params: list = [date_str]
        if not all_scopes:
            if owner_user_id is None:
                q += " AND owner_user_id IS NULL"
            else:
                q += " AND owner_user_id=?"
                params.append(owner_user_id)
        q += " ORDER BY queue_order ASC, scheduled_at ASC"
        return self._conn.execute(q, params).fetchall()

    def list_due_manual_posts(self, now_str: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM manual_posts WHERE status='scheduled' AND scheduled_at != '' "
            "AND scheduled_at <= ? ORDER BY queue_order ASC, scheduled_at ASC",
            (now_str,),
        ).fetchall()

    def claim_manual_post_for_sending(self, post_id: int) -> bool:
        """انتقالِ اتمیکِ وضعیت scheduled -> processing. اگه ردیف دیگه scheduled نبود
        (مثلاً یه تسکِ موازیِ دیگه قبلاً قاپیده)، False برمی‌گردونه - این همون
        محافظتِ در برابرِ ارسالِ دوباره/ناهماهنگیِ Crash هست."""
        with _lock:
            cur = self._conn.execute(
                "UPDATE manual_posts SET status='processing' WHERE id=? AND status='scheduled'",
                (post_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def force_claim_manual_post(self, post_id: int) -> bool:
        """برایِ دکمه‌ی دستیِ «ارسالِ فوری»: برخلافِ claim_manual_post_for_sending،
        از هر وضعیتی (draft/pending/scheduled/failed/cancelled) به processing
        می‌ره - فقط اگه همین الان 'processing' نباشه (یعنی یه تسکِ دیگه در حالِ
        ارسالش نباشه) قبول می‌کنه."""
        with _lock:
            cur = self._conn.execute(
                "UPDATE manual_posts SET status='processing' WHERE id=? AND status != 'processing'",
                (post_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def recover_stuck_manual_posts(self) -> int:
        """موقعِ استارتِ ربات صدا زده می‌شه: اگه ربات وسطِ ارسالِ یک پستِ دستی
        کرش کرده باشه، اون پست توی وضعیتِ 'processing' جا مونده - این تابع
        همه‌ی این‌ها رو به 'scheduled' برمی‌گردونه تا اسکجولرِ دستی دوباره
        امتحانشون کنه (نه اینکه برایِ همیشه گیر بمونن)."""
        with _lock:
            cur = self._conn.execute(
                "UPDATE manual_posts SET status='scheduled' WHERE status='processing'"
            )
            self._conn.commit()
            return cur.rowcount

    # ---------------------------------------------------------------------
    # واترمارکِ سفارشی (بخشِ ۷، ۸، ۹، ۱۰)
    # ---------------------------------------------------------------------

    def create_custom_watermark(
        self, owner_user_id: int | None, name: str, kind: str = "image",
        image_file_id: str = "", text: str = "", font: str = "Vazirmatn-Bold.ttf",
        transparency: int = 60, size_pct: int = 30, rotation: int = 0,
        position: str = "bottom_right", x_pos: int | None = None, y_pos: int | None = None,
        tiled: int = 0, color_a: str = "#FFFFFF", color_b: str = "", color_mode: str = "single",
        album_all: int = 1,
    ) -> int:
        with _lock:
            cur = self._conn.execute(
                "INSERT INTO custom_watermarks "
                "(owner_user_id, name, kind, image_file_id, text, font, transparency, size_pct, "
                " rotation, position, x_pos, y_pos, tiled, color_a, color_b, color_mode, album_all) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner_user_id, name[:64], kind, image_file_id, text[:200], font,
                 transparency, size_pct, rotation, position, x_pos, y_pos,
                 int(bool(tiled)), color_a[:16], color_b[:16], color_mode, int(bool(album_all))),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_custom_watermark(self, wm_id: int) -> Optional[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM custom_watermarks WHERE id=?", (wm_id,)).fetchone()

    def list_custom_watermarks(self, owner_user_id: int | None = None, active_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM custom_watermarks WHERE 1=1"
        params: list = []
        if active_only:
            q += " AND active=1"
        if owner_user_id is not None:
            q += " AND owner_user_id=?"
            params.append(owner_user_id)
        q += " ORDER BY id ASC"
        return self._conn.execute(q, params).fetchall()

    def update_custom_watermark(self, wm_id: int, **fields) -> None:
        allowed = {
            "name", "kind", "image_file_id", "text", "font", "transparency", "size_pct",
            "rotation", "position", "x_pos", "y_pos", "active",
            "tiled", "color_a", "color_b", "color_mode", "album_all",
        }
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        with _lock:
            set_clause = ", ".join(f"{c}=?" for c in cols)
            values = [fields[c] for c in cols] + [wm_id]
            self._conn.execute(f"UPDATE custom_watermarks SET {set_clause} WHERE id=?", values)
            self._conn.commit()

    def delete_custom_watermark(self, wm_id: int) -> None:
        with _lock:
            self._conn.execute("DELETE FROM custom_watermarks WHERE id=?", (wm_id,))
            self._conn.execute("DELETE FROM watermark_destinations WHERE watermark_id=?", (wm_id,))
            self._conn.commit()

    def set_watermark_destinations(self, wm_id: int, destination_ids: list[int]) -> None:
        with _lock:
            self._conn.execute("DELETE FROM watermark_destinations WHERE watermark_id=?", (wm_id,))
            for did in destination_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO watermark_destinations (watermark_id, destination_id) VALUES (?, ?)",
                    (wm_id, did),
                )
            self._conn.commit()

    def get_watermark_destinations(self, wm_id: int) -> list[int]:
        return [
            row["destination_id"] for row in
            self._conn.execute("SELECT destination_id FROM watermark_destinations WHERE watermark_id=?", (wm_id,)).fetchall()
        ]

    def get_watermark_for_destination(self, destination_id: int) -> Optional[sqlite3.Row]:
        row = self._conn.execute(
            "SELECT cw.* FROM custom_watermarks cw "
            "JOIN watermark_destinations wd ON wd.watermark_id = cw.id "
            "WHERE wd.destination_id = ? AND cw.active = 1 LIMIT 1",
            (destination_id,),
        ).fetchone()
        return row

    def get_watermarks_for_destination(self, destination_id: int) -> list[sqlite3.Row]:
        """برخلافِ get_watermark_for_destination (که فقط یکی برمی‌گردونه)،
        همه‌ی واترمارک‌های دلخواهِ فعالِ متصل به این مقصد رو برمی‌گردونه - یک
        مقصد می‌تونه چند واترمارکِ دلخواهِ هم‌زمان داشته باشه (مثلاً یه لوگو +
        یه متنِ محو)."""
        return self._conn.execute(
            "SELECT cw.* FROM custom_watermarks cw "
            "JOIN watermark_destinations wd ON wd.watermark_id = cw.id "
            "WHERE wd.destination_id = ? AND cw.active = 1",
            (destination_id,),
        ).fetchall()

    # ---------------------------------------------------------------------
    # چیدنِ دستیِ واترمارک‌های دلخواه رویِ یک پستِ خاص در صفِ تایید
    # ---------------------------------------------------------------------

    def get_pending_wm_pick(self, pending_id: int) -> tuple[bytes | None, list]:
        row = self._conn.execute(
            "SELECT wm_base_photo, wm_picks_json FROM pending_posts WHERE id=?", (pending_id,),
        ).fetchone()
        if not row:
            return None, []
        base = bytes(row["wm_base_photo"]) if row["wm_base_photo"] else None
        try:
            picks = json.loads(row["wm_picks_json"]) if row["wm_picks_json"] else []
        except (json.JSONDecodeError, TypeError):
            picks = []
        return base, picks

    def set_pending_wm_base(self, pending_id: int, photo_bytes: bytes) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET wm_base_photo=? WHERE id=?", (photo_bytes, pending_id),
            )
            self._conn.commit()

    def set_pending_wm_picks(self, pending_id: int, picks: list) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET wm_picks_json=? WHERE id=?",
                (json.dumps(picks, ensure_ascii=False), pending_id),
            )
            self._conn.commit()

    def clear_pending_wm_pick(self, pending_id: int) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET wm_base_photo=NULL, wm_picks_json='[]' WHERE id=?", (pending_id,),
            )
            self._conn.commit()

    # ---------------------------------------------------------------------
    # صفِ حرفه‌ای (بخشِ ۴): Pause/Resume سراسری + Reorder
    # ---------------------------------------------------------------------

    @staticmethod
    def _manual_pause_key(owner_user_id: int | None) -> str:
        """کلیدِ توقفِ صف به‌ازای هر «حوزه» (scope):
        - ادمینِ سراسری (owner_user_id=None) کلیدِ قدیمیِ سراسری «manual_queue_paused»
          رو نگه می‌داره (سازگاریِ عقب‌رو با تنظیماتِ ذخیره‌شده‌ی قبلی).
        - هر کاربرِ غیرادمین کلیدِ مختصِ خودش («manual_queue_paused_u{id}») رو داره،
          تا توقف/ازسرگیریِ صفِ او هیچ اثری روی صفِ ادمین یا بقیه‌ی کاربرها نذاره
          (ایزوله‌سازیِ کاملِ چندکاربره - بخشِ ۱۱)."""
        return "manual_queue_paused" if owner_user_id is None else f"manual_queue_paused_u{owner_user_id}"

    def is_manual_queue_paused(self, owner_user_id: int | None = None) -> bool:
        return self.get_setting(self._manual_pause_key(owner_user_id)) == "1"

    def set_manual_queue_paused(self, paused: bool, owner_user_id: int | None = None) -> None:
        self.set_setting(self._manual_pause_key(owner_user_id), "1" if paused else "0")

    def swap_manual_queue_order(self, post_id_a: int, post_id_b: int) -> None:
        with _lock:
            row_a = self._conn.execute("SELECT queue_order FROM manual_posts WHERE id=?", (post_id_a,)).fetchone()
            row_b = self._conn.execute("SELECT queue_order FROM manual_posts WHERE id=?", (post_id_b,)).fetchone()
            if not row_a or not row_b:
                return
            self._conn.execute("UPDATE manual_posts SET queue_order=? WHERE id=?", (row_b["queue_order"], post_id_a))
            self._conn.execute("UPDATE manual_posts SET queue_order=? WHERE id=?", (row_a["queue_order"], post_id_b))
            self._conn.commit()


    def set_destination_title(self, destination_id: int, title: str):
        with _lock:
            self._conn.execute(
                "UPDATE destinations SET title=? WHERE id=?", (title, destination_id)
            )
            self._conn.commit()

    def get_destination(self, destination_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM destinations WHERE id=?", (destination_id,))
        return cur.fetchone()

    def list_destinations(self, active_only: bool = False, owner_user_id: int | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM destinations"
        conds = []
        params: list = []
        if active_only:
            conds.append("active=1")
        if owner_user_id is not None:
            conds.append("owner_user_id=?")
            params.append(owner_user_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id"
        return self._conn.execute(q, params).fetchall()

    def set_destination_owner(self, destination_id: int, user_id: int | None) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE destinations SET owner_user_id=? WHERE id=?", (user_id, destination_id)
            )
            self._conn.commit()

    def toggle_destination_owner(self, destination_id: int, user_id: int) -> None:
        d = self.get_destination(destination_id)
        if not d:
            return
        new_owner = None if d["owner_user_id"] == user_id else user_id
        self.set_destination_owner(destination_id, new_owner)

    def destinations_of_user(self, user_id: int) -> set[int]:
        rows = self._conn.execute(
            "SELECT id FROM destinations WHERE owner_user_id=?", (user_id,)
        ).fetchall()
        return {r["id"] for r in rows}

    # ---------------- هشدارِ عدم‌فعالیتِ کانال مقصد ----------------
    def mark_destination_sent(
        self, destination_id: int, when: str | None = None, post_link: str | None = None,
    ) -> None:
        """last_sent_at رو به‌روز می‌کنه؛ اگه لینکِ پستِ تازه‌ارسال‌شده هم داده
        بشه (post_link)، آخرین لینک رو هم ذخیره می‌کنه تا بعداً (مثلاً موقعِ
        جبرانِ اخطارِ عدم‌فعالیت) بشه توی گزارش‌ها همون لینک رو نشون داد."""
        ts = when or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            if post_link:
                self._conn.execute(
                    "UPDATE destinations SET last_sent_at=?, last_post_link=? WHERE id=?",
                    (ts, post_link, destination_id),
                )
            else:
                self._conn.execute(
                    "UPDATE destinations SET last_sent_at=? WHERE id=?", (ts, destination_id)
                )
            self._conn.commit()

    def owners_of_destination(self, destination_id: int) -> set[int]:
        cur = self._conn.execute(
            "SELECT DISTINCT c.owner_user_id AS oid FROM channel_destinations cd "
            "JOIN channels c ON c.id = cd.channel_id WHERE cd.destination_id=?",
            (destination_id,),
        )
        return {(row["oid"] or 0) for row in cur.fetchall()}

    def get_destination_warning(self, destination_id: int, owner_key: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM destination_warnings WHERE destination_id=? AND owner_user_id=?",
            (destination_id, owner_key),
        )
        return cur.fetchone()

    def set_destination_warning(
        self,
        destination_id: int,
        owner_key: int,
        chat_id: Optional[int],
        message_id: Optional[int],
        warned_at: str | None = None,
        public_chat_id: Optional[int] = None,
        public_message_id: Optional[int] = None,
    ) -> None:
        ts = warned_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            self._conn.execute(
                "INSERT INTO destination_warnings "
                "(destination_id, owner_user_id, warned_at, chat_id, message_id, public_chat_id, public_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(destination_id, owner_user_id) DO UPDATE SET "
                "warned_at=excluded.warned_at, chat_id=excluded.chat_id, message_id=excluded.message_id, "
                "public_chat_id=excluded.public_chat_id, public_message_id=excluded.public_message_id",
                (destination_id, owner_key, ts, chat_id, message_id, public_chat_id, public_message_id),
            )
            self._conn.commit()

    def has_open_destination_warning(self, destination_id: int) -> bool:
        """آیا این مقصد (فارغ از اینکه کدوم مالک) الان اخطارِ بازِ فعال داره؟
        برای اینکه شمارنده‌ی دائمیِ total_warnings توی یک اپیزودِ بی‌فعالیتیِ
        واحد، حتی اگه چند مالک داشته باشه، فقط یک‌بار بالا بره."""
        cur = self._conn.execute(
            "SELECT 1 FROM destination_warnings WHERE destination_id=? LIMIT 1",
            (destination_id,),
        )
        return cur.fetchone() is not None

    def bump_destination_warning_count(self, destination_id: int) -> int:
        """شمارنده‌ی total_warnings مقصد رو یک واحد بالا می‌بره و مقدارِ جدید رو برمی‌گردونه."""
        with _lock:
            self._conn.execute(
                "UPDATE destinations SET total_warnings = total_warnings + 1 WHERE id=?",
                (destination_id,),
            )
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT total_warnings FROM destinations WHERE id=?",
                (destination_id,),
            )
            row = cur.fetchone()
            return row["total_warnings"] if row else 1

    def clear_destination_warning(self, destination_id: int, owner_key: int) -> None:
        with _lock:
            self._conn.execute(
                "DELETE FROM destination_warnings WHERE destination_id=? AND owner_user_id=?",
                (destination_id, owner_key),
            )
            self._conn.commit()

    # ---------------- نگاشتِ مبدأ -> مقصد ----------------
    def is_linked(self, channel_id: int, destination_id: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM channel_destinations WHERE channel_id=? AND destination_id=?",
            (channel_id, destination_id),
        )
        return cur.fetchone() is not None

    def toggle_link(self, channel_id: int, destination_id: int) -> bool:
        with _lock:
            if self.is_linked(channel_id, destination_id):
                self._conn.execute(
                    "DELETE FROM channel_destinations WHERE channel_id=? AND destination_id=?",
                    (channel_id, destination_id),
                )
                self._conn.commit()
                return False
            self._conn.execute(
                "INSERT OR IGNORE INTO channel_destinations (channel_id, destination_id) VALUES (?, ?)",
                (channel_id, destination_id),
            )
            self._conn.commit()
            return True

    def linked_destination_ids(self, channel_id: int) -> set[int]:
        cur = self._conn.execute(
            "SELECT destination_id FROM channel_destinations WHERE channel_id=?", (channel_id,)
        )
        return {r["destination_id"] for r in cur.fetchall()}

    def active_destinations_for_channel(self, channel_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """SELECT d.* FROM destinations d
               JOIN channel_destinations cd ON cd.destination_id = d.id
               WHERE cd.channel_id = ? AND d.active = 1
               ORDER BY d.id""",
            (channel_id,),
        )
        return cur.fetchall()

    def linked_channels_for_destination(self, destination_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """SELECT c.* FROM channels c
               JOIN channel_destinations cd ON cd.channel_id = c.id
               WHERE cd.destination_id = ?
               ORDER BY c.id""",
            (destination_id,),
        )
        return cur.fetchall()

    # ---------------- زمان‌بندی هفت‌گانه‌ی هر کانال ----------------
    def get_slots(self, channel_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM schedule_slots WHERE channel_id=? ORDER BY slot_index", (channel_id,)
        )
        rows = list(cur.fetchall())
        if len(rows) >= SLOTS_PER_CHANNEL:
            return rows
        existing_idx = {r["slot_index"] for r in rows}
        with _lock:
            for idx in range(1, SLOTS_PER_CHANNEL + 1):
                if idx in existing_idx:
                    continue
                default_time = DEFAULT_SLOT_TIMES[idx - 1] if idx - 1 < len(DEFAULT_SLOT_TIMES) else ""
                self._conn.execute(
                    "INSERT OR IGNORE INTO schedule_slots (channel_id, slot_index, slot_time, enabled) "
                    "VALUES (?, ?, ?, 1)",
                    (channel_id, idx, default_time),
                )
            self._conn.commit()
        cur = self._conn.execute(
            "SELECT * FROM schedule_slots WHERE channel_id=? ORDER BY slot_index", (channel_id,)
        )
        return cur.fetchall()

    def get_slot(self, channel_id: int, slot_index: int) -> Optional[sqlite3.Row]:
        for row in self.get_slots(channel_id):
            if row["slot_index"] == slot_index:
                return row
        return None

    def set_slot_time(self, channel_id: int, slot_index: int, hhmm: str):
        with _lock:
            self._conn.execute(
                "UPDATE schedule_slots SET slot_time=? WHERE channel_id=? AND slot_index=?",
                (hhmm, channel_id, slot_index),
            )
            self._conn.commit()

    def toggle_slot(self, channel_id: int, slot_index: int):
        with _lock:
            self._conn.execute(
                "UPDATE schedule_slots SET enabled = 1 - enabled WHERE channel_id=? AND slot_index=?",
                (channel_id, slot_index),
            )
            self._conn.commit()

    def mark_slot_run(self, channel_id: int, slot_index: int, run_date: str):
        with _lock:
            self._conn.execute(
                "UPDATE schedule_slots SET last_run_date=? WHERE channel_id=? AND slot_index=?",
                (run_date, channel_id, slot_index),
            )
            self._conn.commit()

    def due_slots(self, now_hhmm: str, today: str) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """SELECT s.channel_id, s.slot_index, s.slot_time, c.username, c.last_post_id
               FROM schedule_slots s
               JOIN channels c ON c.id = s.channel_id
               WHERE s.enabled = 1
                 AND c.active = 1
                 AND c.send_mode = 'schedule'
                 AND s.slot_time != ''
                 AND s.slot_time <= ?
                 AND (s.last_run_date IS NULL OR s.last_run_date != ?)
               ORDER BY s.channel_id, s.slot_index""",
            (now_hhmm, today),
        )
        return cur.fetchall()
    # ---------------- sent log / آمار ----------------
    def sent_count_today(self, channel_id: int) -> int:
        today = date.today().isoformat()
        cur = self._conn.execute(
            "SELECT COUNT(*) c FROM sent_log WHERE channel_id=? AND sent_date=?",
            (channel_id, today),
        )
        return cur.fetchone()["c"]

    def log_sent(self, channel_id: int, post_id: int, media_type: str = ""):
        today = date.today().isoformat()
        with _lock:
            self._conn.execute(
                "INSERT INTO sent_log (channel_id, post_id, media_type, sent_date) "
                "VALUES (?, ?, ?, ?)",
                (channel_id, post_id, media_type, today),
            )
            self._conn.commit()

    # ---------------- نگاشتِ پیام برای بازسازیِ ریپلای ----------------
    def set_mapped_message_id(
        self, source_channel_id: int, source_post_id: int,
        destination_id: int, dest_message_id: int,
    ) -> None:
        """ثبتِ اینکه پستِ مبدأ (source_post_id) در مقصدِ مشخص با چه message_id ارسال شد."""
        if not dest_message_id:
            return
        with _lock:
            self._conn.execute(
                """INSERT INTO sent_message_map
                   (source_channel_id, source_post_id, destination_id, dest_message_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source_channel_id, source_post_id, destination_id)
                   DO UPDATE SET dest_message_id=excluded.dest_message_id""",
                (source_channel_id, source_post_id, destination_id, dest_message_id),
            )
            # هرازگاهی (نه هربار، برای صرفه‌جویی) نگاشت‌های خیلی قدیمی رو پاک می‌کنیم
            # تا جدول بی‌نهایت بزرگ نشه. ریپلای‌ها معمولاً به پست‌های اخیر می‌خورن،
            # پس نگه‌داشتنِ ~۳۰ روز کافیه.
            if source_post_id % 200 == 0:
                self._conn.execute(
                    "DELETE FROM sent_message_map WHERE created_at < datetime('now', '-30 days')"
                )
            self._conn.commit()

    def get_mapped_message_id(
        self, source_channel_id: int, source_post_id: int, destination_id: int,
    ) -> Optional[int]:
        """آیدیِ پیامِ متناظرِ یک پستِ مبدأ در یک مقصد (یا None اگه ثبت نشده)."""
        row = self._conn.execute(
            """SELECT dest_message_id FROM sent_message_map
               WHERE source_channel_id=? AND source_post_id=? AND destination_id=?""",
            (source_channel_id, source_post_id, destination_id),
        ).fetchone()
        return int(row["dest_message_id"]) if row else None

    def prune_message_map(self, days: int = 30) -> int:
        """پاک‌سازیِ نگاشت‌های قدیمی‌تر از N روز تا جدول بی‌نهایت بزرگ نشه."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM sent_message_map WHERE created_at < datetime('now', ?)",
                (f'-{int(days)} days',),
            )
            self._conn.commit()
            return cur.rowcount

    # ==================================================================
    # پاک‌سازیِ خودکارِ جدول‌های انباشتی (نگه‌داشتنِ حجمِ دیتابیس و بکاپ)
    # این جدول‌ها هر روز ردیف اضافه می‌کنن و اگه پاک نشن، هم فایلِ دیتابیس و هم
    # فایلِ بکاپ (که JSONِ همه‌ی جدول‌هاست) بی‌نهایت بزرگ می‌شن. مقصرهای اصلی:
    # pending_posts (صفِ تایید)، sent_log و duplicate_log.
    # ==================================================================
    def prune_finished_pending_posts(self, hours: int = 24) -> int:
        """پست‌های صفِ تایید که تصمیمشون گرفته شده (approved/rejected) و بیشتر از
        N ساعت از ساختشون گذشته، پاک می‌شن. این‌ها دیگه به‌درد نمی‌خورن ولی متنِ
        کاملِ پست رو نگه می‌داشتن."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM pending_posts "
                "WHERE status IN ('approved', 'rejected') "
                "AND created_at < datetime('now', ?)",
                (f'-{int(hours)} hours',),
            )
            self._conn.commit()
            return cur.rowcount

    def prune_stale_pending_posts(self, hours: int = 48) -> int:
        """پست‌هایی که توی صفِ تایید مونده‌ن و نه تایید شده‌ن نه رد (هنوز
        status='pending') و بیشتر از N ساعت از ساختشون گذشته، منقضی حساب می‌شن و
        پاک می‌شن. پیش‌فرض ۴۸ ساعته: اگه توی این مدت تصمیمی گرفته نشه، پست دیگه
        محتوای تازه‌ای نیست و ارزشِ نگه‌داشتن نداره."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM pending_posts "
                "WHERE status = 'pending' "
                "AND created_at < datetime('now', ?)",
                (f'-{int(hours)} hours',),
            )
            self._conn.commit()
            return cur.rowcount

    def prune_sent_log(self, days: int = 45) -> int:
        """تاریخچه‌ی «چی قبلاً ارسال شده» قدیمی‌تر از N روز پاک می‌شه. بی‌خطره چون
        اسکرَیپر اون‌قدر عقب نمی‌ره که پست‌های این‌قدر قدیمی رو دوباره ببینه
        (last_post_id همیشه جلو می‌ره)."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM sent_log WHERE sent_date < date('now', ?)",
                (f'-{int(days)} days',),
            )
            self._conn.commit()
            return cur.rowcount

    def prune_duplicate_log(self, days: int = 30) -> int:
        """هش‌های تشخیصِ پستِ تکراری قدیمی‌تر از N روز پاک می‌شن (بر اساسِ آخرین
        باری که دیده شدن). پست‌های تکراری معمولاً در بازه‌ی کوتاه اتفاق می‌افتن."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM duplicate_log "
                "WHERE COALESCE(last_seen, first_seen) < datetime('now', ?)",
                (f'-{int(days)} days',),
            )
            self._conn.commit()
            return cur.rowcount

    def prune_destination_content_log(self, days: int = 30) -> int:
        """تاریخچه‌ی «چی به هر مقصد ارسال شده» (برای تشخیصِ تکراریِ بینِ چند
        کانالِ مبدأ در یک مقصد) قدیمی‌تر از N روز پاک می‌شه."""
        with _lock:
            cur = self._conn.execute(
                "DELETE FROM destination_content_log WHERE sent_at < datetime('now', ?)",
                (f'-{int(days)} days',),
            )
            self._conn.commit()
            return cur.rowcount

    def vacuum(self) -> bool:
        """فایلِ دیتابیس رو فشرده می‌کنه تا فضایی که با DELETE آزاد شده واقعاً از
        رویِ دیسک هم پس گرفته بشه. VACUUM نباید داخلِ تراکنش اجرا بشه، پس اول
        تراکنشِ باز رو می‌بندیم و isolation_level رو موقتاً None می‌کنیم."""
        with _lock:
            try:
                self._conn.commit()  # هر تراکنشِ ضمنیِ باز رو ببند
                old_isolation = self._conn.isolation_level
                self._conn.isolation_level = None
                try:
                    self._conn.execute("VACUUM")
                finally:
                    self._conn.isolation_level = old_isolation
                return True
            except Exception as e:  # noqa: BLE001 - VACUUM نباید هیچ‌وقت جریانِ اصلی رو بشکنه
                log.warning("VACUUM شکست خورد (نادیده گرفته شد): %s", e)
                return False

    def run_maintenance(
        self,
        *,
        pending_finished_hours: int = 24,
        pending_stale_hours: int = 48,
        sent_log_days: int = 45,
        duplicate_log_days: int = 30,
        message_map_days: int = 30,
        do_vacuum: bool = True,
    ) -> dict:
        """همه‌ی پاک‌سازی‌های نگه‌دارنده‌ی حجم رو یکجا اجرا می‌کنه و تعدادِ ردیف‌های
        پاک‌شده رو برمی‌گردونه. روزی یک‌بار (درست قبل از بکاپ) صدا زده می‌شه تا هم
        دیتابیس و هم فایلِ بکاپ کوچیک بمونن. هر مرحله جدا try/except نمی‌خواد چون
        خودِ متدها امن‌ان؛ ولی کلِ تابع در برابرِ خطا مقاومه تا بکاپ هیچ‌وقت به‌خاطرِ
        پاک‌سازی از دست نره."""
        counts: dict = {}
        steps = (
            ("pending_finished", lambda: self.prune_finished_pending_posts(pending_finished_hours)),
            ("pending_stale", lambda: self.prune_stale_pending_posts(pending_stale_hours)),
            ("sent_log", lambda: self.prune_sent_log(sent_log_days)),
            ("duplicate_log", lambda: self.prune_duplicate_log(duplicate_log_days)),
            ("destination_content_log", lambda: self.prune_destination_content_log(duplicate_log_days)),
            ("message_map", lambda: self.prune_message_map(message_map_days)),
        )
        for name, fn in steps:
            try:
                counts[name] = fn()
            except Exception as e:  # noqa: BLE001
                log.warning("پاک‌سازیِ «%s» شکست خورد (نادیده گرفته شد): %s", name, e)
                counts[name] = 0

        total_deleted = sum(counts.values())
        if do_vacuum and total_deleted > 0:
            counts["vacuumed"] = self.vacuum()
        else:
            counts["vacuumed"] = False

        log.info(
            "پاک‌سازیِ دیتابیس: pending(تمام‌شده=%s، کهنه=%s)، sent_log=%s، "
            "duplicate_log=%s، message_map=%s، جمعاً %s ردیف پاک شد، vacuum=%s.",
            counts.get("pending_finished"), counts.get("pending_stale"),
            counts.get("sent_log"), counts.get("duplicate_log"),
            counts.get("message_map"), total_deleted, counts.get("vacuumed"),
        )
        return counts

    def increment_ad_filtered(self) -> None:
        with _lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key='ad_filter_skipped_count'"
            ).fetchone()
            current = int(row["value"]) if row and row["value"] else 0
            self._conn.execute(
                """INSERT INTO settings (key, value) VALUES ('ad_filter_skipped_count', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(current + 1),),
            )
            self._conn.commit()

    def increment_config_only_filtered(self) -> None:
        with _lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key='config_only_skipped_count'"
            ).fetchone()
            current = int(row["value"]) if row and row["value"] else 0
            self._conn.execute(
                """INSERT INTO settings (key, value) VALUES ('config_only_skipped_count', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(current + 1),),
            )
            self._conn.commit()

    def increment_file_filtered(self) -> None:
        with _lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key='file_filter_skipped_count'"
            ).fetchone()
            current = int(row["value"]) if row and row["value"] else 0
            self._conn.execute(
                """INSERT INTO settings (key, value) VALUES ('file_filter_skipped_count', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(current + 1),),
            )
            self._conn.commit()

    def stats(self, owner_user_id: int | None = None) -> dict:
        if owner_user_id is None:
            total_channels = self._conn.execute("SELECT COUNT(*) c FROM channels").fetchone()["c"]
            active_channels = self._conn.execute(
                "SELECT COUNT(*) c FROM channels WHERE active=1"
            ).fetchone()["c"]
            total_destinations = self._conn.execute("SELECT COUNT(*) c FROM destinations").fetchone()["c"]
            active_destinations = self._conn.execute(
                "SELECT COUNT(*) c FROM destinations WHERE active=1"
            ).fetchone()["c"]
            today = date.today().isoformat()
            sent_today = self._conn.execute(
                "SELECT COUNT(*) c FROM sent_log WHERE sent_date=?", (today,)
            ).fetchone()["c"]
            sent_total = self._conn.execute("SELECT COUNT(*) c FROM sent_log").fetchone()["c"]
            ad_filtered_total = int(self.get_setting("ad_filter_skipped_count", "0") or 0)
            file_filtered_total = int(self.get_setting("file_filter_skipped_count", "0") or 0)
            return {
                "total_channels": total_channels,
                "active_channels": active_channels,
                "total_destinations": total_destinations,
                "active_destinations": active_destinations,
                "sent_today": sent_today,
                "sent_total": sent_total,
                "ad_filtered_total": ad_filtered_total,
                "file_filtered_total": file_filtered_total,
            }
        # ---- آمار مخصوصِ یک کاربرِ خاص (فقط کانال‌ها/مقصدهای خودش) ----
        chan_ids = list(self.channels_of_user(owner_user_id))
        dest_ids = list(self.destinations_of_user(owner_user_id))
        total_channels = len(chan_ids)
        total_destinations = len(dest_ids)
        if chan_ids:
            ph = ",".join("?" * len(chan_ids))
            active_channels = self._conn.execute(
                f"SELECT COUNT(*) c FROM channels WHERE active=1 AND id IN ({ph})", chan_ids
            ).fetchone()["c"]
            today = date.today().isoformat()
            sent_today = self._conn.execute(
                f"SELECT COUNT(*) c FROM sent_log WHERE sent_date=? AND channel_id IN ({ph})",
                [today, *chan_ids],
            ).fetchone()["c"]
            sent_total = self._conn.execute(
                f"SELECT COUNT(*) c FROM sent_log WHERE channel_id IN ({ph})", chan_ids
            ).fetchone()["c"]
        else:
            active_channels = 0
            sent_today = 0
            sent_total = 0
        if dest_ids:
            ph_d = ",".join("?" * len(dest_ids))
            active_destinations = self._conn.execute(
                f"SELECT COUNT(*) c FROM destinations WHERE active=1 AND id IN ({ph_d})", dest_ids
            ).fetchone()["c"]
        else:
            active_destinations = 0
        return {
            "total_channels": total_channels,
            "active_channels": active_channels,
            "total_destinations": total_destinations,
            "active_destinations": active_destinations,
            "sent_today": sent_today,
            "sent_total": sent_total,
            "ad_filtered_total": 0,
            "file_filtered_total": 0,
        }

    # ---------------- pending_posts (اپشن ۱ و ۴: تایید/ویرایش قبل از ارسال) ----------------
    def add_pending_post(
        self,
        channel_id: int,
        source_post_id: int,
        caption_html: str,
        media: list[dict],
        flag_reason: str = "",
        owner_user_id: int | None = None,
        body_html: str = "",
        ad_filter_detail: str = "",
    ) -> int:
        with _lock:
            cur = self._conn.execute(
                "INSERT INTO pending_posts "
                "(channel_id, source_post_id, caption_html, original_caption_html, body_html, media_json, status, flag_reason, owner_user_id, ad_filter_detail) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (channel_id, source_post_id, caption_html, caption_html, body_html,
                 json.dumps(media, ensure_ascii=False), flag_reason, owner_user_id, ad_filter_detail),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_pending_post(self, pending_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM pending_posts WHERE id=?", (pending_id,))
        return cur.fetchone()

    def get_all_pending_posts(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM pending_posts WHERE status='pending'").fetchall()

    def get_pending_posts_by_user(self, user_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM pending_posts WHERE owner_user_id=? AND status='pending'",
            (user_id,)
        ).fetchall()

    def set_pending_caption(self, pending_id: int, caption_html: str):
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET caption_html=? WHERE id=?", (caption_html, pending_id)
            )
            self._conn.commit()

    def restore_pending_caption(self, pending_id: int) -> str:
        """کپشن رو به همون نسخه‌ی اولیه (قبل از هر ترجمه/خلاصه‌سازی/بازنویسی یا
        ویرایشِ دستی) برمی‌گردونه و مقدارِ بازگشتی رو هم برمی‌گردونه."""
        with _lock:
            row = self._conn.execute(
                "SELECT original_caption_html FROM pending_posts WHERE id=?", (pending_id,)
            ).fetchone()
            original = row["original_caption_html"] if row else ""
            self._conn.execute(
                "UPDATE pending_posts SET caption_html=? WHERE id=?", (original, pending_id)
            )
            self._conn.commit()
            return original

    def set_pending_override_photo(self, pending_id: int, photo_bytes: bytes):
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET override_photo=? WHERE id=?", (photo_bytes, pending_id)
            )
            self._conn.commit()

    def set_pending_override_video(self, pending_id: int, video_bytes: bytes):
        """خودِ ویدیوی پست رو (نه فقط کاورش) با ویدیویی که ادمین فرستاده جایگزین می‌کنه."""
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET override_video=? WHERE id=?", (video_bytes, pending_id)
            )
            self._conn.commit()

    def set_pending_admin_message(self, pending_id: int, chat_id: int, message_id: int):
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET admin_chat_id=?, admin_message_id=? WHERE id=?",
                (chat_id, message_id, pending_id),
            )
            self._conn.commit()

    def set_pending_status(self, pending_id: int, status: str):
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET status=? WHERE id=?", (status, pending_id)
            )
            self._conn.commit()

    def claim_pending_post(self, pending_id: int, new_status: str) -> bool:
        """تلاش می‌کنه وضعیتِ یک پستِ در صفِ تایید رو به‌صورتِ اتمیک از
        'pending' به new_status ('approved' یا 'rejected') تغییر بده.
        خروجی True یعنی این فراخوانی برنده شد (واقعاً از pending تغییر کرد)؛
        False یعنی یه فراخوانیِ دیگه (مثلاً دو کلیکِ هم‌زمانِ تایید روی یک پست،
        از دو دستگاه/دو نفرِ متفاوتِ همون اکانتِ مشترک) زودتر برده و این پست
        دیگه pending نیست - تا از ارسالِ دوبله‌ی یک پست به مقصد جلوگیری بشه."""
        with _lock:
            cur = self._conn.execute(
                "UPDATE pending_posts SET status=? WHERE id=? AND status='pending'",
                (new_status, pending_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def count_pending(self) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) c FROM pending_posts WHERE status='pending'"
        )
        return cur.fetchone()["c"]

    def set_pending_ad_feedback(self, pending_id: int, verdict: str) -> bool:
        """فیدبکِ ادمین به تشخیصِ فیلترِ تبلیغات رو برایِ یک پستِ مشخص ثبت می‌کنه.
        verdict باید 'correct' (تشخیص درست بود، واقعاً تبلیغ بود) یا 'incorrect'
        (اشتباه بود، تبلیغ نبود) باشه. این دقیقاً همون دیتایِ واقعی‌ایه که برای
        فهمیدنِ کجایِ پرامپت/فیلتر اشتباه می‌کنه لازمه - نگاه کن به
        get_ad_feedback_channel_stats/get_ad_feedback_posts. فقط یک‌بار قابلِ ثبته (اگه قبلاً فیدبک داشته
        باشه، دوباره‌نویسی نمی‌شه) تا از تغییرِ دستیِ آمار توسطِ چند کلیکِ
        پشتِ‌سرِ‌هم جلوگیری بشه."""
        if verdict not in ("correct", "incorrect"):
            return False
        with _lock:
            cur = self._conn.execute(
                "UPDATE pending_posts SET ad_feedback=? "
                "WHERE id=? AND (ad_feedback IS NULL OR ad_feedback='')",
                (verdict, pending_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    # ---------------- مکانیزمِ قدیمی‌ترِ پیامِ ریپلایِ جداگانه (فعلاً پیش‌فرض غیرفعال) ----------------
    # این دو تابع (set_pending_flag_message و get_ad_feedback_stats) مالِ نسخه‌ای
    # هستن که توش دکمه‌های فیدبک رویِ یک پیامِ *جداگانه* (ریپلای‌شده روی خودِ پست)
    # نشون داده می‌شدن، نه مستقیم رویِ خودِ پست. اون مکانیزم با ورودِ
    # get_ad_feedback_channel_stats/get_ad_feedback_posts (پایین‌تر) و دکمه‌های
    # ad_flagged رویِ خودِ پست جایگزین شد، ولی این دو تابع عمداً حذف نشدن -
    # نگاه کن به poster._pending_flag_kb و کامنتِ بالای اون برایِ نحوه‌ی
    # فعال‌سازیِ دوباره‌شون در صورتِ نیاز.
    def set_pending_flag_message(self, pending_id: int, chat_id: int, message_id: int):
        """چت/پیامِ ریپلایِ توضیحاتِ فلگِ فیلترِ تبلیغات (نگاه کن به
        send_pending_preview) رو ذخیره می‌کنه تا بعداً (تایید/رد/فیدبک) بشه
        همون پیام رو پیدا و ویرایش کرد."""
        with _lock:
            self._conn.execute(
                "UPDATE pending_posts SET flag_chat_id=?, flag_message_id=? WHERE id=?",
                (chat_id, message_id, pending_id),
            )
            self._conn.commit()

    def get_ad_feedback_stats(self, limit_examples: int = 5) -> dict:
        """آمارِ خلاصه‌ی فیدبکِ ادمین به فیلترِ تبلیغات (نسخه‌ی سراسری، بدونِ
        تفکیکِ کانال/مالک): تعدادِ 'درست بود'، تعدادِ 'اشتباه بود'، و چند
        نمونه‌ی آخرِ اشتباه (متن+دلیلِ فیلتر). برایِ آمارِ به‌تفکیکِ کانال/مالک
        از get_ad_feedback_channel_stats/get_ad_feedback_posts استفاده کن."""
        cur = self._conn.execute(
            "SELECT ad_feedback, COUNT(*) c FROM pending_posts "
            "WHERE ad_feedback IN ('correct','incorrect') GROUP BY ad_feedback"
        )
        counts = {row["ad_feedback"]: row["c"] for row in cur.fetchall()}
        examples_cur = self._conn.execute(
            "SELECT id, caption_html, body_html, flag_reason, created_at FROM pending_posts "
            "WHERE ad_feedback='incorrect' ORDER BY id DESC LIMIT ?",
            (limit_examples,),
        )
        examples = [dict(row) for row in examples_cur.fetchall()]
        return {
            "correct": counts.get("correct", 0),
            "incorrect": counts.get("incorrect", 0),
            "examples": examples,
        }

    # ---------------- آمارِ فیدبکِ فیلترِ تبلیغات (به‌تفکیکِ کانال/کاربر) ----------------
    # نکته‌ی مهم: برخلافِ بقیه‌ی جاهای این فایل (مثلِ list_channels) که
    # owner_user_id=None یعنی «بدونِ فیلتر / همه‌چیز» (فقط برای دیدِ ادمین)،
    # این دو تابع همچین رفتاری ندارن: طبقِ درخواستِ صریح (آمارِ هر کاربر باید
    # کاملاً جدا از بقیه باشه، حتی برای ادمین)، owner_user_id=None این‌جا یعنی
    # «دقیقاً owner_user_id IS NULL» (یعنی کانال‌های خودِ ادمین)، نه «همه‌ی
    # کاربرها با هم». یعنی هیچ‌وقت آمارِ دو مالکِ مختلف با هم جمع نمی‌شن.
    @staticmethod
    def _ad_feedback_owner_clause(owner_user_id: int | None) -> tuple[str, list]:
        if owner_user_id is None:
            return " AND p.owner_user_id IS NULL", []
        return " AND p.owner_user_id = ?", [owner_user_id]

    def get_ad_feedback_channel_stats(self, owner_user_id: int | None = None) -> list[dict]:
        """آمارِ فیدبکِ ادمین به فیلترِ تبلیغات، به تفکیکِ هر کانالِ مبدأ - برایِ
        منویِ «📊 آمارِ فیدبکِ فیلترِ تبلیغات». هر آیتم شاملِ: نامِ کانالِ مبدأ،
        لیستِ کانال‌های مقصدِ همون کانال، تعدادِ «✅ درست بود»، تعدادِ «❌ اشتباه
        بود» و درصدِ دقت. فقط کانال‌هایی که حداقل یک فیدبک ثبت‌شده دارن برمی‌گردن.
        owner_user_id: نگاه کن به _ad_feedback_owner_clause - همیشه دقیقاً
        محدود به همون یک مالک (کاربر/ادمین)."""
        clause, params = self._ad_feedback_owner_clause(owner_user_id)
        q = (
            "SELECT p.channel_id AS channel_id, "
            "SUM(CASE WHEN p.ad_feedback='correct' THEN 1 ELSE 0 END) AS correct_n, "
            "SUM(CASE WHEN p.ad_feedback='incorrect' THEN 1 ELSE 0 END) AS incorrect_n "
            "FROM pending_posts p WHERE p.ad_feedback IN ('correct','incorrect')" + clause +
            " GROUP BY p.channel_id"
        )
        rows = self._conn.execute(q, params).fetchall()
        result: list[dict] = []
        for r in rows:
            cid = r["channel_id"]
            ch = self.get_channel(cid)
            ch_name = (ch["title"] or f"@{ch['username']}") if ch else f"کانالِ حذف‌شده #{cid}"
            dest_rows = self._conn.execute(
                "SELECT d.title, d.chat_id FROM channel_destinations cd "
                "JOIN destinations d ON d.id = cd.destination_id "
                "WHERE cd.channel_id = ? ORDER BY d.id",
                (cid,),
            ).fetchall()
            dest_names = [(d["title"] or d["chat_id"]) for d in dest_rows]
            correct = int(r["correct_n"] or 0)
            incorrect = int(r["incorrect_n"] or 0)
            total = correct + incorrect
            result.append({
                "channel_id": cid,
                "channel_name": ch_name,
                "destinations": dest_names,
                "correct": correct,
                "incorrect": incorrect,
                "total": total,
                "accuracy": round(100 * correct / total) if total else 0,
            })
        result.sort(key=lambda x: x["total"], reverse=True)
        return result

    def get_ad_feedback_posts(
        self,
        owner_user_id: int | None = None,
        channel_id: int | None = None,
        verdict: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """لیستِ تک‌تکِ پست‌هایی که فیدبکِ فیلترِ تبلیغات دارن (برایِ نمایشِ
        نمونه‌ها یا ساختنِ خروجیِ اکسل). owner_user_id مثلِ همیشه دقیقاً محدود
        به یک مالک - نگاه کن به _ad_feedback_owner_clause."""
        clause, params = self._ad_feedback_owner_clause(owner_user_id)
        q = (
            "SELECT id, channel_id, caption_html, body_html, flag_reason, ad_feedback, "
            "ad_filter_detail, created_at "
            "FROM pending_posts p WHERE p.ad_feedback IN ('correct','incorrect')" + clause
        )
        if channel_id is not None:
            q += " AND p.channel_id = ?"
            params.append(channel_id)
        if verdict in ("correct", "incorrect"):
            q += " AND p.ad_feedback = ?"
            params.append(verdict)
        q += " ORDER BY p.id DESC"
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        return self._conn.execute(q, params).fetchall()

    # ---------------- مدیریت کاربران (چندکاربره) ----------------
    def add_user(self, name: str, telegram_id: int | None, approval_chat_id: int) -> int:
        with _lock:
            cur = self._conn.execute(
                "INSERT INTO users (name, telegram_id, approval_chat_id) VALUES (?, ?, ?)",
                (name.strip(), telegram_id, approval_chat_id),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
        return cur.fetchone()

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM users WHERE telegram_id=? AND active=1", (telegram_id,))
        return cur.fetchone()

    def get_user_by_approval_chat(self, chat_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM users WHERE approval_chat_id=? AND active=1", (chat_id,)
        )
        return cur.fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM users ORDER BY id").fetchall()

    def toggle_user(self, user_id: int) -> None:
        with _lock:
            self._conn.execute("UPDATE users SET active = 1 - active WHERE id=?", (user_id,))
            self._conn.commit()

    def remove_user(self, user_id: int) -> None:
        with _lock:
            self._conn.execute("UPDATE channels SET owner_user_id=NULL WHERE owner_user_id=?", (user_id,))
            self._conn.execute("UPDATE destinations SET owner_user_id=NULL WHERE owner_user_id=?", (user_id,))
            self._conn.execute(
                "UPDATE pending_posts SET owner_user_id=NULL "
                "WHERE owner_user_id=? AND status='pending'",
                (user_id,),
            )
            self._conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            self._conn.commit()

    def set_channel_owner(self, channel_id: int, user_id: int | None) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE channels SET owner_user_id=? WHERE id=?", (user_id, channel_id)
            )
            self._conn.commit()

    def toggle_channel_owner(self, channel_id: int, user_id: int) -> None:
        ch = self.get_channel(channel_id)
        if not ch:
            return
        new_owner = None if ch["owner_user_id"] == user_id else user_id
        self.set_channel_owner(channel_id, new_owner)

    def channels_of_user(self, user_id: int) -> set[int]:
        rows = self._conn.execute(
            "SELECT id FROM channels WHERE owner_user_id=?", (user_id,)
        ).fetchall()
        return {r["id"] for r in rows}

    def set_user_approval_chat(self, user_id: int, approval_chat_id: int) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE users SET approval_chat_id=? WHERE id=?", (approval_chat_id, user_id)
            )
            self._conn.commit()

    def set_user_telegram_id(self, user_id: int, telegram_id: int) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE users SET telegram_id=? WHERE id=?", (telegram_id, user_id)
            )
            self._conn.commit()

    # ---------------- دسترسی‌های ریزدانه ----------------
    def get_permissions(self, user_id: int) -> dict[str, bool]:
        perms = dict(DEFAULT_USER_PERMISSIONS)
        u = self.get_user(user_id)
        if not u:
            return perms
        try:
            stored = json.loads(u["permissions"] or "{}")
        except (json.JSONDecodeError, TypeError):
            stored = {}
        for k, v in stored.items():
            if k in perms:
                perms[k] = bool(v)
        return perms

    def get_permissions_by_telegram_id(self, telegram_id: int) -> dict[str, bool]:
        u = self.get_user_by_telegram_id(telegram_id)
        if not u:
            return dict(DEFAULT_USER_PERMISSIONS)
        return self.get_permissions(u["id"])

    def set_permission(self, user_id: int, key: str, value: bool) -> None:
        if key not in DEFAULT_USER_PERMISSIONS:
            return
        with _lock:
            u = self.get_user(user_id)
            if not u:
                return
            try:
                stored = json.loads(u["permissions"] or "{}")
            except (json.JSONDecodeError, TypeError):
                stored = {}
            stored[key] = bool(value)
            self._conn.execute(
                "UPDATE users SET permissions=? WHERE id=?",
                (json.dumps(stored, ensure_ascii=False), user_id),
            )
            self._conn.commit()

    def toggle_permission(self, user_id: int, key: str) -> bool:
        """خواندن و نوشتنِ مقدارِ دسترسی به‌صورتِ اتمیک (زیرِ یک قفلِ واحد)؛ قبلاً
        خواندنِ مقدارِ فعلی (get_permissions) و نوشتنِ مقدارِ جدید (set_permission)
        دو عملیاتِ جداگانه بودن و هرکدوم قفلِ خودشون رو جدا می‌گرفتن - یعنی اگه
        دو کلیکِ هم‌زمان روی همون دکمه‌ی toggle می‌اومد، ممکن بود هر دو مقدارِ
        فعلیِ یکسون رو بخونن و هر دو یک مقدارِ یکسون بنویسن (به‌جایِ toggle
        واقعی، هر دو کلیک نتیجه‌ی یکسون بدن)."""
        if key not in DEFAULT_USER_PERMISSIONS:
            return False
        with _lock:
            u = self.get_user(user_id)
            if not u:
                return False
            try:
                stored = json.loads(u["permissions"] or "{}")
            except (json.JSONDecodeError, TypeError):
                stored = {}
            current = bool(stored.get(key, DEFAULT_USER_PERMISSIONS.get(key, False)))
            new_val = not current
            stored[key] = new_val
            self._conn.execute(
                "UPDATE users SET permissions=? WHERE id=?",
                (json.dumps(stored, ensure_ascii=False), user_id),
            )
            self._conn.commit()
            return new_val

    # ---------------- شخصی‌سازیِ به‌ازای هر کانال مبدأ ----------------
    def get_channel_overrides(self, channel_id: int) -> dict[str, bool]:
        ch = self.get_channel(channel_id)
        if not ch:
            return {}
        try:
            raw = json.loads(ch["overrides"] or "{}") if "overrides" in ch.keys() else {}
        except (json.JSONDecodeError, TypeError):
            raw = {}
        return {k: bool(v) for k, v in raw.items() if k in OVERRIDABLE_TOGGLES}

    def get_channel_override(self, channel_id: int, key: str) -> Optional[bool]:
        return self.get_channel_overrides(channel_id).get(key)

    def set_channel_override(self, channel_id: int, key: str, value: bool) -> None:
        if key not in OVERRIDABLE_TOGGLES:
            return
        with _lock:
            ch = self.get_channel(channel_id)
            if not ch:
                return
            try:
                raw = json.loads(ch["overrides"] or "{}") if "overrides" in ch.keys() else {}
            except (json.JSONDecodeError, TypeError):
                raw = {}
            raw[key] = bool(value)
            self._conn.execute(
                "UPDATE channels SET overrides=? WHERE id=?",
                (json.dumps(raw, ensure_ascii=False), channel_id),
            )
            self._conn.commit()

    def clear_channel_override(self, channel_id: int, key: str) -> None:
        with _lock:
            ch = self.get_channel(channel_id)
            if not ch:
                return
            try:
                raw = json.loads(ch["overrides"] or "{}") if "overrides" in ch.keys() else {}
            except (json.JSONDecodeError, TypeError):
                raw = {}
            if key in raw:
                del raw[key]
                self._conn.execute(
                    "UPDATE channels SET overrides=? WHERE id=?",
                    (json.dumps(raw, ensure_ascii=False), channel_id),
                )
                self._conn.commit()

    def clear_all_channel_overrides(self, channel_id: int) -> None:
        with _lock:
            self._conn.execute(
                "UPDATE channels SET overrides='{}' WHERE id=?", (channel_id,)
            )
            self._conn.commit()

    def cycle_channel_override(self, channel_id: int, key: str) -> Optional[bool]:
        current = self.get_channel_override(channel_id, key)
        if current is None:
            new: Optional[bool] = True
        elif current is True:
            new = False
        else:
            new = None
        if new is None:
            self.clear_channel_override(channel_id, key)
        else:
            self.set_channel_override(channel_id, key, new)
        return new

    def get_effective_bool(self, channel_id: Optional[int], key: str, default: bool = False,
                            owner_user_id: Optional[int] = None) -> bool:
        if channel_id is not None:
            override = self.get_channel_override(channel_id, key)
            if override is not None:
                return override
        return self.setting_get_bool(key, default, owner_user_id=owner_user_id)

    # ---------------- متدهای جدید برای قابلیت‌های ۱۰ گانه ----------------
    def add_system_log(self, log_type: str, event_type: str, severity: str, message: str,
                       details: dict = None, channel_id: int = None,
                       destination_id: int = None, user_id: int = None,
                       post_id: int = None, status: str = None) -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        jalali_date = format_jalali_datetime(now_jalali())
        # فیکس: برای خطاها (ERROR/WARNING) به‌صورتِ خودکار مشخصاتِ فنیِ منشأ
        # ارور (فایل/خط/تابعِ فراخوان + اگه داخلِ except بودیم، نوع/پیامِ
        # استثنا و آخرین فریمِ traceback که واقعاً باعثِ خطا شده) رو به details
        # اضافه می‌کنیم تا از منویِ «لاگ‌ها» بدونِ نیاز به لاگِ خامِ سرور بشه
        # فهمید ارور از کدوم فایل و برای چه دلیلی اومده.
        if severity in ("ERROR", "WARNING"):
            debug_info = _capture_log_debug_info()
            if debug_info:
                details = dict(details) if details else {}
                details["_debug"] = debug_info
        with _lock:
            self._conn.execute(
                """INSERT INTO system_logs
                   (log_type, event_type, severity, message, details, channel_id,
                    destination_id, user_id, post_id, status, jalali_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (log_type, event_type, severity, message,
                 json.dumps(details, ensure_ascii=False) if details else None,
                 channel_id, destination_id, user_id, post_id, status, jalali_date)
            )
            self._conn.commit()

    def get_system_logs(self, limit: int = 100, log_type: str = None,
                        severity: str = None, channel_id: int = None,
                        destination_id: int = None, user_id: int = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM system_logs WHERE 1=1"
        params = []
        if log_type:
            query += " AND log_type=?"
            params.append(log_type)
        if severity:
            query += " AND severity=?"
            params.append(severity)
        if channel_id:
            query += " AND channel_id=?"
            params.append(channel_id)
        if destination_id:
            query += " AND destination_id=?"
            params.append(destination_id)
        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return self._conn.execute(query, params).fetchall()

    def get_settings_by_prefix(self, prefix: str) -> dict:
        rows = self._conn.execute("SELECT key, value FROM settings WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return {row["key"]: row["value"] for row in rows}

    # ==================== سیستمِ مدیریتِ API هوش مصنوعی ====================
    def ai_get_provider(self, owner_user_id: Optional[int], service_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
            (owner_user_id, service_id),
        ).fetchone()

    def ai_list_providers(self, owner_user_id: Optional[int]) -> dict[str, sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT * FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0)",
            (owner_user_id,),
        ).fetchall()
        return {r["service_id"]: r for r in rows}

    def ai_upsert_key(self, owner_user_id: Optional[int], service_id: str,
                       api_key_encrypted: str, status: str, status_detail: str = "") -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            existing = self._conn.execute(
                "SELECT id FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
                (owner_user_id, service_id),
            ).fetchone()
            if existing:
                self._conn.execute(
                    """UPDATE ai_providers SET api_key_encrypted=?, status=?, status_detail=?,
                       last_checked_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (api_key_encrypted, status, status_detail, now, existing["id"]),
                )
            else:
                self._conn.execute(
                    """INSERT INTO ai_providers
                       (owner_user_id, service_id, api_key_encrypted, status, status_detail, last_checked_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (owner_user_id, service_id, api_key_encrypted, status, status_detail, now),
                )
            self._conn.commit()

    def ai_update_status(self, owner_user_id: Optional[int], service_id: str,
                          status: str, status_detail: str = "") -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            self._conn.execute(
                """UPDATE ai_providers SET status=?, status_detail=?, last_checked_at=?,
                   updated_at=CURRENT_TIMESTAMP
                   WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?""",
                (status, status_detail, now, owner_user_id, service_id),
            )
            self._conn.commit()

    def ai_delete_provider(self, owner_user_id: Optional[int], service_id: str) -> None:
        with _lock:
            self._conn.execute(
                "DELETE FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
                (owner_user_id, service_id),
            )
            self._conn.commit()

    def ai_record_usage(self, owner_user_id: Optional[int], service_id: str,
                         success: bool, response_ms: int = 0) -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            self._conn.execute(
                """UPDATE ai_providers SET
                     total_requests = total_requests + 1,
                     total_errors = total_errors + ?,
                     total_response_ms = total_response_ms + ?,
                     last_used_at = ?,
                     updated_at = CURRENT_TIMESTAMP
                   WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?""",
                (0 if success else 1, max(0, response_ms), now, owner_user_id, service_id),
            )
            self._conn.commit()

    # ---- چندکلیدیِ AI (تا ۵ کلید به‌ازایِ هر (owner, service)) ----
    MAX_AI_KEYS_PER_SERVICE = 5

    def ai_list_keys(self, owner_user_id: Optional[int], service_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT * FROM ai_provider_keys
               WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?
               ORDER BY slot""",
            (owner_user_id, service_id),
        ).fetchall()

    def ai_get_key(self, owner_user_id: Optional[int], service_id: str, slot: int) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            """SELECT * FROM ai_provider_keys
               WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=? AND slot=?""",
            (owner_user_id, service_id, slot),
        ).fetchone()

    def ai_add_key(self, owner_user_id: Optional[int], service_id: str,
                    api_key_encrypted: str, status: str, status_detail: str = "") -> Optional[int]:
        """اولین slotِ خالیِ ۱ تا ۵ رو برایِ این کلیدِ جدید پیدا می‌کنه و ثبتش
        می‌کنه. اگه هر ۵ slot پر باشه None برمی‌گردونه (لایه‌ی بالاتر باید قبل
        از فراخوانی چک کنه و پیام مناسب بده)."""
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            used = {
                r["slot"] for r in self._conn.execute(
                    "SELECT slot FROM ai_provider_keys WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
                    (owner_user_id, service_id),
                ).fetchall()
            }
            slot = next((s for s in range(1, self.MAX_AI_KEYS_PER_SERVICE + 1) if s not in used), None)
            if slot is None:
                return None
            self._conn.execute(
                """INSERT INTO ai_provider_keys
                   (owner_user_id, service_id, slot, api_key_encrypted, status, status_detail, last_checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (owner_user_id, service_id, slot, api_key_encrypted, status, status_detail, now),
            )
            self._conn.commit()
            return slot

    def ai_update_key_status(self, owner_user_id: Optional[int], service_id: str, slot: int,
                              status: str, status_detail: str = "", cooldown_until: str = "") -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            self._conn.execute(
                """UPDATE ai_provider_keys SET status=?, status_detail=?, last_checked_at=?,
                   cooldown_until=?, updated_at=CURRENT_TIMESTAMP
                   WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=? AND slot=?""",
                (status, status_detail, now, cooldown_until, owner_user_id, service_id, slot),
            )
            self._conn.commit()

    def ai_delete_key(self, owner_user_id: Optional[int], service_id: str, slot: int) -> None:
        with _lock:
            self._conn.execute(
                """DELETE FROM ai_provider_keys
                   WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=? AND slot=?""",
                (owner_user_id, service_id, slot),
            )
            self._conn.commit()

    def ai_record_key_usage(self, owner_user_id: Optional[int], service_id: str, slot: int,
                             success: bool, response_ms: int = 0) -> None:
        from .jdatetime_utils import now_jalali, format_jalali_datetime
        now = format_jalali_datetime(now_jalali())
        with _lock:
            self._conn.execute(
                """UPDATE ai_provider_keys SET
                     total_requests = total_requests + 1,
                     total_errors = total_errors + ?,
                     total_response_ms = total_response_ms + ?,
                     last_used_at = ?,
                     updated_at = CURRENT_TIMESTAMP
                   WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=? AND slot=?""",
                (0 if success else 1, max(0, response_ms), now, owner_user_id, service_id, slot),
            )
            self._conn.commit()

    def ai_get_rotation_cursor(self, owner_user_id: Optional[int], service_id: str) -> int:
        row = self._conn.execute(
            "SELECT rotation_cursor FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
            (owner_user_id, service_id),
        ).fetchone()
        return int(row["rotation_cursor"]) if row and row["rotation_cursor"] is not None else 0

    def ai_set_rotation_cursor(self, owner_user_id: Optional[int], service_id: str, cursor: int) -> None:
        """cursor رو روی ردیفِ aggregate این سرویس (ai_providers) ذخیره می‌کنه؛
        اگه ردیف هنوز وجود نداشته باشه (کاربر هنوز از aiapi:svc بازدید نکرده)
        یکی با وضعیتِ not_set می‌سازه تا cursor گم نشه."""
        with _lock:
            existing = self._conn.execute(
                "SELECT id FROM ai_providers WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND service_id=?",
                (owner_user_id, service_id),
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE ai_providers SET rotation_cursor=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (cursor, existing["id"]),
                )
            else:
                self._conn.execute(
                    """INSERT INTO ai_providers (owner_user_id, service_id, status, rotation_cursor)
                       VALUES (?, ?, 'not_set', ?)""",
                    (owner_user_id, service_id, cursor),
                )
            self._conn.commit()

    def ai_get_task_route(self, owner_user_id: Optional[int], task_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ai_task_routes WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND task_id=?",
            (owner_user_id, task_id),
        ).fetchone()

    def ai_list_task_routes(self, owner_user_id: Optional[int]) -> dict[str, sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT * FROM ai_task_routes WHERE COALESCE(owner_user_id,0)=COALESCE(?,0)",
            (owner_user_id,),
        ).fetchall()
        return {r["task_id"]: r for r in rows}

    def ai_set_task_route(self, owner_user_id: Optional[int], task_id: str,
                           provider_service_id: str = "", fallback_service_id: str = "") -> None:
        with _lock:
            existing = self._conn.execute(
                "SELECT rowid FROM ai_task_routes WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND task_id=?",
                (owner_user_id, task_id),
            ).fetchone()
            if existing:
                self._conn.execute(
                    """UPDATE ai_task_routes SET provider_service_id=?, fallback_service_id=?,
                       updated_at=CURRENT_TIMESTAMP
                       WHERE COALESCE(owner_user_id,0)=COALESCE(?,0) AND task_id=?""",
                    (provider_service_id, fallback_service_id, owner_user_id, task_id),
                )
            else:
                self._conn.execute(
                    """INSERT INTO ai_task_routes (owner_user_id, task_id, provider_service_id, fallback_service_id)
                       VALUES (?, ?, ?, ?)""",
                    (owner_user_id, task_id, provider_service_id, fallback_service_id),
                )
            self._conn.commit()


db = Database()