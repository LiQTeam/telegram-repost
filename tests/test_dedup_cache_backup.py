# -*- coding: utf-8 -*-
"""تستِ عملیِ سه زیرسیستمِ «پرریسک» که خرابی‌شان یا پستِ تکراری می‌فرستد،
یا رم را پر می‌کند، یا داده از دست می‌دهد:

  • bot/duplicate_filter.py — تشخیصِ تکراری (دقیق + فازی) و ثبتِ اتمیک
  • bot/cache.py            — سقفِ تعداد/بایت، انقضا، حسابداریِ حجم
  • bot/backup_manager.py   — رفت‌وبرگشتِ کاملِ بکاپ/بازیابی روی دیتابیسِ واقعی

اجرا:  python3 tests/test_dedup_cache_backup.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="repost-dcb-")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ["DB_PATH"] = os.path.join(_TMP, "bot.sqlite")

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)


def run(coro):
    return asyncio.run(coro)


# ===========================================================================
#  ۱) تشخیصِ تکراری
# ===========================================================================
from bot.duplicate_filter import DuplicateFilter as DF  # noqa: E402

TEXT_A = "تیمِ ملیِ فوتبالِ ایران در بازیِ دوستانه مقابلِ حریفِ خود به تساوی رسید و سرمربی از عملکردِ بازیکنان دفاع کرد"
TEXT_B = "قیمتِ دلار در بازارِ آزادِ امروز با نوسانِ محدود همراه بود و معامله‌گران منتظرِ خبرهای تازه هستند"

is_dup, prev = DF.check_and_log_atomic(TEXT_A, [], 1, 101)
check("dedup.first_post_not_duplicate", is_dup is False and prev is None, f"{is_dup} {prev}")

# دقیقاً همان متن از یک پستِ دیگر → تکراری
is_dup, prev = DF.check_and_log_atomic(TEXT_A, [], 1, 102)
check("dedup.exact_text_is_duplicate", is_dup is True, f"{is_dup} {prev}")
check("dedup.points_to_original", prev == 101, repr(prev))

# متنِ کاملاً متفاوت → تکراری نیست
is_dup, _ = DF.check_and_log_atomic(TEXT_B, [], 1, 103)
check("dedup.different_text_passes", is_dup is False, str(is_dup))

# ثبتِ دوباره‌ی *همان* پست (همان کانال و همان post_id) نباید ردیفِ دوم بسازد.
DF.check_and_log_atomic(TEXT_B, [], 1, 103)
from bot.database import db  # noqa: E402
_rows = db._conn.execute(
    "SELECT COUNT(*) c FROM duplicate_log WHERE source_channel_id=1 AND source_post_id=103"
).fetchone()["c"]
check("dedup.same_post_logged_once", _rows == 1, str(_rows))

# مدیای یکسان با متنِ خالی → تکراری
DF.check_and_log_atomic("", ["https://cdn.example.com/a.jpg"], 2, 201)
is_dup, _ = DF.check_and_log_atomic("", ["https://cdn.example.com/a.jpg"], 2, 202)
check("dedup.same_media_is_duplicate", is_dup is True, str(is_dup))

# پستِ بدونِ متن و بدونِ مدیا نباید با پستِ بی‌متنِ دیگری قاطی شود
# (content_hash باید از channel/post_id ساخته شود، نه یک مقدارِ ثابت).
DF.check_and_log_atomic("", [], 3, 301)
is_dup, _ = DF.check_and_log_atomic("", [], 3, 302)
check("dedup.empty_posts_not_conflated", is_dup is False, str(is_dup))

# هش‌ها پایدار و متفاوت‌اند
check("dedup.hash_stable", DF.get_hash_from_text(TEXT_A) == DF.get_hash_from_text(TEXT_A))
check("dedup.hash_differs", DF.get_hash_from_text(TEXT_A) != DF.get_hash_from_text(TEXT_B))

# پاک‌سازیِ لاگِ قدیمی نباید ردیفِ تازه را ببرد
_before = db._conn.execute("SELECT COUNT(*) c FROM duplicate_log").fetchone()["c"]
DF.clean_old_logs(days=7)
_after = db._conn.execute("SELECT COUNT(*) c FROM duplicate_log").fetchone()["c"]
check("dedup.clean_keeps_recent", _after == _before, f"{_before} -> {_after}")

# ===========================================================================
#  ۲) کش دانلود
# ===========================================================================
from bot import cache  # noqa: E402
from bot import config  # noqa: E402

run(cache.clear())
check("cache.starts_empty", run(cache.stats())["items"] == 0, repr(run(cache.stats())))

run(cache.set("k1", b"x" * 1000))
check("cache.roundtrip", run(cache.get("k1")) == b"x" * 1000)
check("cache.miss_is_none", run(cache.get("nope")) is None)
st = run(cache.stats())
check("cache.size_accounted", st["total_size_bytes"] == 1000, repr(st))

# نوشتنِ دوباره‌ی همان کلید نباید حجم را دوبار بشمارد (نشتِ حسابداری).
run(cache.set("k1", b"y" * 500))
st = run(cache.stats())
check("cache.overwrite_no_double_count", st["total_size_bytes"] == 500, repr(st))
check("cache.overwrite_value", run(cache.get("k1")) == b"y" * 500)

check("cache.remove", run(cache.remove("k1")) is True)
check("cache.removed_gone", run(cache.get("k1")) is None)
check("cache.size_zero_after_remove", run(cache.stats())["total_size_bytes"] == 0, repr(run(cache.stats())))

# سقفِ بایتی: نوشتنِ بیش از سقف نباید حافظه را بی‌نهایت بزرگ کند.
_max_bytes = getattr(config, "DOWNLOAD_CACHE_MAX_BYTES", 0)
if _max_bytes > 0:
    chunk = b"z" * 100_000
    for i in range(int(_max_bytes // len(chunk)) + 5):
        run(cache.set(f"big{i}", chunk))
    st = run(cache.stats())
    check("cache.respects_byte_cap", st["total_size_bytes"] <= _max_bytes,
          f"total={st['total_size_bytes']} cap={_max_bytes}")
    check("cache.evicted_something", st["items"] < int(_max_bytes // len(chunk)) + 5, repr(st))
else:
    check("cache.byte_cap_configured", False, "DOWNLOAD_CACHE_MAX_BYTES تنظیم نشده")

run(cache.clear())
check("cache.clear_resets_bytes", run(cache.stats())["total_size_bytes"] == 0)

# ===========================================================================
#  ۳) بکاپ / بازیابی — رفت‌وبرگشتِ کامل روی دیتابیسِ واقعی
# ===========================================================================
from bot.backup_manager import BackupManager  # noqa: E402

# ⚠️ مسیرِ بازیابی روی «BASE_DIR/.env» می‌نویسد و کنارش یک .env.bak_<ts> هم
# می‌گذارد. توی تست، BASE_DIR را به پوشه‌ی موقت می‌بریم تا .env واقعیِ پروژه
# دست نخورد و فایلِ .bak توی ریشه‌ی مخزن نیفتد.
import pathlib  # noqa: E402
config.BASE_DIR = pathlib.Path(_TMP)

uid = db.add_user("کاربرِ بکاپ", 777001, 777001)
db.add_channel("@backup_src", "مبدأ بکاپ", uid)
db.add_destination("@backup_dst", "مقصد بکاپ", uid)
db.set_setting("backup_probe", "مقدارِ قبل از بکاپ")

blob = BackupManager.create_backup()
check("backup.created", isinstance(blob, (bytes, bytearray)) and len(blob) > 0, str(type(blob)))
check("backup.is_encrypted_not_plain_sqlite", not bytes(blob).startswith(b"SQLite format 3"),
      repr(bytes(blob)[:16]))

# داده را عوض/حذف می‌کنیم تا مطمئن شویم بازیابی واقعاً برش می‌گرداند.
db.set_setting("backup_probe", "مقدارِ خراب‌شده")
_ch = db._conn.execute("SELECT id FROM channels WHERE username='@backup_src'").fetchone()
db.remove_channel(_ch["id"])
check("backup.precondition_data_changed",
      db.get_setting("backup_probe") == "مقدارِ خراب‌شده"
      and db._conn.execute("SELECT COUNT(*) c FROM channels WHERE username='@backup_src'").fetchone()["c"] == 0)

ok, msg = BackupManager.restore_backup(bytes(blob))
check("backup.restore_reports_success", ok is True, repr(msg))
check("backup.setting_restored", db.get_setting("backup_probe") == "مقدارِ قبل از بکاپ",
      repr(db.get_setting("backup_probe")))
check("backup.channel_restored",
      db._conn.execute("SELECT COUNT(*) c FROM channels WHERE username='@backup_src'").fetchone()["c"] == 1)
check("backup.destination_restored",
      db._conn.execute("SELECT COUNT(*) c FROM destinations WHERE chat_id='@backup_dst'").fetchone()["c"] == 1)
check("backup.user_restored", db.get_user_by_telegram_id(777001) is not None)

# ⚠️ کلیدیِ‌ترین ثابتِ این بخش: بازیابی نباید دیتابیس را نیمه‌کاره رها کند.
import sqlite3  # noqa: E402
check("backup.db_integrity_after_restore",
      list(sqlite3.connect(os.environ["DB_PATH"]).execute("PRAGMA integrity_check"))[0][0] == "ok")

# داده‌ی خراب نباید کرش کند؛ باید (False, پیام) بدهد.
bad_ok, bad_msg = BackupManager.restore_backup("این اصلاً فایلِ بکاپ نیست".encode("utf-8"))
check("backup.corrupt_input_rejected_gracefully", bad_ok is False and bool(bad_msg), repr(bad_msg))
check("backup.db_survives_corrupt_restore",
      list(sqlite3.connect(os.environ["DB_PATH"]).execute("PRAGMA integrity_check"))[0][0] == "ok")
check("backup.data_intact_after_failed_restore",
      db.get_setting("backup_probe") == "مقدارِ قبل از بکاپ",
      repr(db.get_setting("backup_probe")))

print("\n=== DEDUP_CACHE_BACKUP:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
raise SystemExit(1 if fails else 0)
