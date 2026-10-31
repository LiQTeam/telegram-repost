# -*- coding: utf-8 -*-
"""تستِ عملیِ دیتابیس روی یک فایلِ واقعیِ موقت.

پوشش:
  • ساختِ اسکیما + سلامتِ فایل (integrity_check)
  • idempotent بودنِ باز کردنِ دوباره‌ی همان دیتابیس (اجرایِ دوباره‌ی مهاجرت‌ها)
  • CRUDِ کانالِ مبدأ/مقصد/کاربر + نگاشتِ مبدأ↔مقصد
  • تنظیماتِ سراسری/کاربری/به‌ازای‌مقصد + overrideهای کانال
  • صفِ تایید (pending) و claimِ اتمیک
  • اسلات‌های زمان‌بندی + لاگِ ارسال
  • چندکلیدیِ AI + مکان‌نمایِ چرخش
  • آمار (stats) و نگه‌داری (run_maintenance/vacuum)

اجرا:  python3 tests/test_database.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="repost-db-")
_DB = os.path.join(_TMP, "bot.sqlite")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ["DB_PATH"] = _DB

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)


from bot.database import Database, db  # noqa: E402

# ===========================================================================
#  ۱) اسکیما و سلامتِ فایل
# ===========================================================================
raw = sqlite3.connect(_DB)
tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
_EXPECTED_TABLES = {
    "channels", "destinations", "channel_destinations", "destination_settings",
    "users", "user_settings", "settings", "schedule_slots", "sent_log",
    "pending_posts", "manual_posts", "custom_watermarks", "watermark_destinations",
    "duplicate_log", "channel_stats", "system_logs", "sent_message_map",
    "ai_providers", "ai_provider_keys", "ai_task_routes",
    "destination_content_log", "destination_warnings",
}
missing = _EXPECTED_TABLES - tables
check("db.schema.all_tables_created", not missing, f"جاافتاده: {sorted(missing)}")
check("db.schema.integrity_ok", list(raw.execute("PRAGMA integrity_check"))[0][0] == "ok")
check("db.schema.wal_mode", list(raw.execute("PRAGMA journal_mode"))[0][0].lower() == "wal")

# ⚠️ باز کردنِ دوباره‌ی همان فایل (یعنی هر ری‌استارتِ ربات) دوباره همه‌ی
# مهاجرت‌ها را اجرا می‌کند؛ باید بدونِ خطا و بدونِ تغییرِ داده باشد.
db2 = Database(_DB)
check("db.schema.reopen_is_idempotent", True)  # اگر مهاجرتی می‌ترکید، خطِ بالا استثنا می‌داد
check("db.schema.same_tables_after_reopen",
      {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")} == tables)

# ===========================================================================
#  ۲) کاربر / کانالِ مبدأ / کانالِ مقصد
# ===========================================================================
uid = db.add_user("کاربرِ تست", 555001, 555001)
check("db.user.created", isinstance(uid, int) and uid > 0, repr(uid))
check("db.user.lookup_by_telegram_id", db.get_user_by_telegram_id(555001)["id"] == uid)
check("db.user.in_list", any(u["id"] == uid for u in db.list_users()))

check("db.channel.add", db.add_channel("@src_a", "مبدأ A", uid) is True)
check("db.channel.duplicate_same_owner_rejected", db.add_channel("@src_a", "مبدأ A", uid) is False)
ch = db._conn.execute("SELECT * FROM channels WHERE username='@src_a'").fetchone()
cid = ch["id"]
check("db.channel.owner_stored", ch["owner_user_id"] == uid, repr(ch["owner_user_id"]))
check("db.channel.get", db.get_channel(cid)["username"] == "@src_a")

check("db.destination.add", db.add_destination("@dst_a", "مقصد A", uid) is True)
d = db._conn.execute("SELECT * FROM destinations WHERE chat_id='@dst_a'").fetchone()
did = d["id"]
check("db.destination.get", db.get_destination(did)["chat_id"] == "@dst_a")

# فعال/غیرفعال
_before = bool(db.get_channel(cid)["active"])
db.toggle_channel(cid)
check("db.channel.toggle", bool(db.get_channel(cid)["active"]) != _before)
db.toggle_channel(cid)

# ===========================================================================
#  ۳) نگاشتِ مبدأ ↔ مقصد
# ===========================================================================
check("db.link.absent_initially", db.is_linked(cid, did) is False)
check("db.link.toggle_on", db.toggle_link(cid, did) is True)
check("db.link.is_linked", db.is_linked(cid, did) is True)
check("db.link.ids", db.linked_destination_ids(cid) == {did}, repr(db.linked_destination_ids(cid)))
check("db.link.active_destinations", [r["id"] for r in db.active_destinations_for_channel(cid)] == [did])
check("db.link.reverse", [r["id"] for r in db.linked_channels_for_destination(did)] == [cid])
check("db.link.toggle_off", db.toggle_link(cid, did) is False)
db.toggle_link(cid, did)  # دوباره وصل، برای تست‌های بعدی

# ===========================================================================
#  ۴) تنظیمات (سراسری / کاربری / به‌ازای مقصد / overrideِ کانال)
# ===========================================================================
db.set_setting("probe_key", "probe_value")
check("db.setting.roundtrip", db.get_setting("probe_key") == "probe_value")
check("db.setting.default_when_absent", db.get_setting("no_such_key", "پیش‌فرض") == "پیش‌فرض")
db.set_setting("probe_bool", "1")
check("db.setting.bool", db.get_bool("probe_bool") is True)
db.set_setting("probe_int", 42)
check("db.setting.int", db.get_int("probe_int") == 42)
check("db.setting.int_bad_value_falls_back", db.get_int("probe_key", 7) == 7)

db.set_user_setting(uid, "u_key", "u_val")
check("db.user_setting.roundtrip", db.get_user_setting(uid, "u_key") == "u_val")
check("db.user_setting.isolated_from_global", db.get_setting("u_key", "") == "")

db.dest_setting_set(did, "footer_enabled", "0")
check("db.dest_setting.bool", db.dest_setting_get_bool(did, "footer_enabled", True) is False)
check("db.dest_setting.default", db.dest_setting_get(did, "nope", "x") == "x")

db.set_channel_override(cid, "ad_filter_smart_enabled", False)
check("db.override.set", db.get_channel_override(cid, "ad_filter_smart_enabled") is False)
db.clear_channel_override(cid, "ad_filter_smart_enabled")
check("db.override.clear", db.get_channel_override(cid, "ad_filter_smart_enabled") is None)

# ===========================================================================
#  ۵) اسلات‌های زمان‌بندی و لاگِ ارسال
# ===========================================================================
slots = db.get_slots(cid)
check("db.slots.autocreated", len(slots) > 0, str(len(slots)))
db.set_slot_time(cid, 1, "08:30")
check("db.slots.set_time", db.get_slot(cid, 1)["slot_time"] == "08:30", repr(db.get_slot(cid, 1)["slot_time"]))
_before = bool(db.get_slot(cid, 1)["enabled"])
db.toggle_slot(cid, 1)
check("db.slots.toggle", bool(db.get_slot(cid, 1)["enabled"]) != _before)

check("db.sent.count_starts_zero", db.sent_count_today(cid) == 0, str(db.sent_count_today(cid)))
db.log_sent(cid, 1001, "photo")
check("db.sent.count_after_log", db.sent_count_today(cid) == 1, str(db.sent_count_today(cid)))
db.update_last_post(cid, 1001)
check("db.channel.last_post_id", db.get_channel(cid)["last_post_id"] == 1001)

# ===========================================================================
#  ۶) صفِ تایید + claimِ اتمیک (نباید یک پست دوبار ارسال شود)
# ===========================================================================
pid = db.add_pending_post(
    cid, 2002, "<b>متنِ تست</b>", [{"type": "photo", "url": "http://x/y.jpg"}],
    flag_reason="تست", owner_user_id=uid,
)
check("db.pending.created", isinstance(pid, int) and pid > 0, repr(pid))
check("db.pending.count", db.count_pending() >= 1)
check("db.pending.get", db.get_pending_post(pid)["source_post_id"] == 2002)
check("db.pending.media_json_is_valid",
      json.loads(db.get_pending_post(pid)["media_json"])[0]["type"] == "photo",
      repr(db.get_pending_post(pid)["media_json"]))
check("db.pending.by_user", [r["id"] for r in db.get_pending_posts_by_user(uid)] == [pid])
db.set_pending_caption(pid, "<b>کپشنِ جدید</b>")
check("db.pending.caption_updated", "کپشنِ جدید" in db.get_pending_post(pid)["caption_html"])
check("db.pending.caption_restorable", "متنِ تست" in db.restore_pending_caption(pid))
check("db.pending.claim_first_wins", db.claim_pending_post(pid, "approved") is True)
check("db.pending.claim_second_loses", db.claim_pending_post(pid, "approved") is False)

# ===========================================================================
#  ۷) چندکلیدیِ AI + چرخش
# ===========================================================================
from bot import ai_catalog as _cat  # noqa: E402

slot_a = db.ai_add_key(None, "mistral", "enc-key-a", _cat.STATUS_ACTIVE)
slot_b = db.ai_add_key(None, "mistral", "enc-key-b", _cat.STATUS_ACTIVE)
check("db.ai.slots_assigned_sequentially", (slot_a, slot_b) == (1, 2), repr((slot_a, slot_b)))
check("db.ai.keys_stored", len(db.ai_list_keys(None, "mistral")) == 2)
check("db.ai.key_by_slot",
      db.ai_get_key(None, "mistral", slot_b)["api_key_encrypted"] == "enc-key-b",
      repr(dict(db.ai_get_key(None, "mistral", slot_b))))
# سقفِ تعدادِ کلیدِ هر سرویس باید رعایت شود (بعد از پر شدن، None برگردد).
_extra = [db.ai_add_key(None, "mistral", f"enc-{i}", _cat.STATUS_ACTIVE)
          for i in range(db.MAX_AI_KEYS_PER_SERVICE)]
check("db.ai.respects_max_keys", _extra[-1] is None, repr(_extra))
check("db.ai.keys_capped",
      len(db.ai_list_keys(None, "mistral")) == db.MAX_AI_KEYS_PER_SERVICE,
      str(len(db.ai_list_keys(None, "mistral"))))
# کلیدهای یک سرویس نباید توی سرویسِ دیگر دیده شوند.
db.ai_add_key(None, "groq", "enc-groq", _cat.STATUS_ACTIVE)
check("db.ai.keys_isolated_per_service", len(db.ai_list_keys(None, "groq")) == 1)

db.ai_set_rotation_cursor(None, "mistral", 3)
check("db.ai.rotation_cursor", db.ai_get_rotation_cursor(None, "mistral") == 3)
db.ai_delete_key(None, "mistral", slot_a)
check("db.ai.key_deleted", db.ai_get_key(None, "mistral", slot_a) is None)
db.ai_record_key_usage(None, "mistral", slot_b, success=True, response_ms=120)
check("db.ai.usage_recorded", db.ai_get_key(None, "mistral", slot_b)["total_requests"] == 1)

db.ai_set_task_route(None, "rewrite", "mistral", "groq")
_route = db.ai_get_task_route(None, "rewrite")
check("db.ai.task_route", _route["provider_service_id"] == "mistral", repr(dict(_route)))
check("db.ai.task_route_fallback", _route["fallback_service_id"] == "groq")
# نوشتنِ دوباره باید همان ردیف را به‌روزرسانی کند، نه ردیفِ دوم بسازد.
db.ai_set_task_route(None, "rewrite", "groq", "")
check("db.ai.task_route_upsert",
      db.ai_get_task_route(None, "rewrite")["provider_service_id"] == "groq")
check("db.ai.task_route_single_row",
      db._conn.execute(
          "SELECT COUNT(*) c FROM ai_task_routes WHERE COALESCE(owner_user_id,0)=0 AND task_id='rewrite'"
      ).fetchone()["c"] == 1)
check("db.ai.task_route_absent_is_none", db.ai_get_task_route(None, "no_such_task") is None)

# ===========================================================================
#  ۸) آمار و نگه‌داری
# ===========================================================================
st = db.stats()
check("db.stats.is_dict", isinstance(st, dict) and st, repr(type(st)))
check("db.stats.has_counts", all(isinstance(v, (int, float, str)) or v is None for v in st.values()),
      repr({k: type(v).__name__ for k, v in st.items()}))

db.increment_ad_filtered()
db.increment_config_only_filtered()
db.increment_file_filtered()
check("db.stats.counters_survive", isinstance(db.stats(), dict))

db.add_system_log("TEST", "probe", "INFO", "پیامِ تست", details={"k": "v"}, status="ok")
logs = db.get_system_logs(limit=5, log_type="TEST")
check("db.system_log.written", any("پیامِ تست" in (r["message"] or "") for r in logs), repr(len(logs)))

check("db.maintenance.runs", isinstance(db.run_maintenance(), dict))
check("db.maintenance.vacuum", db.vacuum() is True)
check("db.integrity_after_maintenance",
      list(sqlite3.connect(_DB).execute("PRAGMA integrity_check"))[0][0] == "ok")

# ===========================================================================
#  ۹) حذف‌ها (cascade نباید ردیفِ یتیم بگذارد)
# ===========================================================================
db.remove_destination(did)
check("db.destination.removed", db.get_destination(did) is None)
check("db.destination.link_cascaded",
      db._conn.execute("SELECT COUNT(*) c FROM channel_destinations WHERE destination_id=?",
                       (did,)).fetchone()["c"] == 0)
db.remove_channel(cid)
check("db.channel.removed", db.get_channel(cid) is None)
check("db.channel.slots_cascaded",
      db._conn.execute("SELECT COUNT(*) c FROM schedule_slots WHERE channel_id=?",
                       (cid,)).fetchone()["c"] == 0)
db.remove_user(uid)
check("db.user.removed", db.get_user(uid) is None)

print("\n=== DATABASE:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
raise SystemExit(1 if fails else 0)
