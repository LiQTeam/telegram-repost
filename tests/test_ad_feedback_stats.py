# -*- coding: utf-8 -*-
"""
تستِ آمارِ فیدبکِ فیلترِ تبلیغات (database.get_ad_feedback_channel_stats /
get_ad_feedback_posts) - مهم‌ترین چیزی که این‌جا باید تضمین بشه: ایزوله‌بودنِ
کاملِ آمارِ هر مالک (کاربر/ادمین) از بقیه، طبقِ درخواستِ صریح: هیچ‌وقت آمارِ دو
مالکِ مختلف نباید با هم قاطی بشه یا نشتی داشته باشه.

از یک Database(":memory:") جدا (نه singletonِ اصلی) استفاده می‌کنیم تا این
تست هیچ فایلِ واقعی‌ای رو دست نزنه و کاملاً مستقل باشه.
"""
import _harness
from bot.database import Database

fails = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)

d = Database(":memory:")

# ---- داده‌ی نمونه: یک کانالِ ادمین (owner=None) + یک کانالِ کاربرِ ۵ ----
d.add_channel("chan_a", title="کانالِ الف", owner_user_id=None)
d.add_channel("chan_b", title="", owner_user_id=5)
d.add_destination("-100111", title="مقصدِ یک", owner_user_id=None)
d.add_destination("-100222", title="مقصدِ دو", owner_user_id=None)
d.add_destination("-100333", title="مقصدِ کاربرِ ۵", owner_user_id=5)

ch_a = d.list_channels(owner_user_id=None)[0]
ch_b = d.list_channels(owner_user_id=5)[0]
_all_dests = {row["chat_id"]: row for row in d.list_destinations()}
dest1, dest2, dest3 = _all_dests["-100111"], _all_dests["-100222"], _all_dests["-100333"]

d._conn.execute("INSERT INTO channel_destinations (channel_id, destination_id) VALUES (?,?)", (ch_a["id"], dest1["id"]))
d._conn.execute("INSERT INTO channel_destinations (channel_id, destination_id) VALUES (?,?)", (ch_a["id"], dest2["id"]))
d._conn.execute("INSERT INTO channel_destinations (channel_id, destination_id) VALUES (?,?)", (ch_b["id"], dest3["id"]))
d._conn.commit()

pid1 = d.add_pending_post(ch_a["id"], 100, "تبلیغِ واقعی", "[]", flag_reason="🚩 مشکوک به تبلیغاتی: نشانه‌ی قوی", owner_user_id=None, body_html="")
pid2 = d.add_pending_post(ch_a["id"], 101, "پستِ عادی", "[]", flag_reason="🚩 مشکوک به تبلیغاتی: کالکشنِ لینک", owner_user_id=None, body_html="")
pid3 = d.add_pending_post(ch_a["id"], 102, "بدونِ فیدبک", "[]", flag_reason="🚩 مشکوک به تبلیغاتی: چیزی", owner_user_id=None, body_html="")
pid4 = d.add_pending_post(ch_b["id"], 200, "تبلیغِ کاربرِ ۵", "[]", flag_reason="🚩 مشکوک به تبلیغاتی: قمار", owner_user_id=5, body_html="")
pid5 = d.add_pending_post(ch_a["id"], 103, "تکراری (نباید در آمار بیاد)", "[]", flag_reason="♻️ تکراری", owner_user_id=None, body_html="")

d.set_pending_ad_feedback(pid1, "correct")
d.set_pending_ad_feedback(pid2, "incorrect")
d.set_pending_ad_feedback(pid4, "correct")
# pid3, pid5 عمداً بدونِ فیدبک می‌مونن

stats_admin = d.get_ad_feedback_channel_stats(owner_user_id=None)
stats_u5 = d.get_ad_feedback_channel_stats(owner_user_id=5)
stats_u999 = d.get_ad_feedback_channel_stats(owner_user_id=999)

check("fbstats.admin_one_channel", len(stats_admin) == 1, f"{stats_admin}")
check("fbstats.admin_counts", stats_admin and stats_admin[0]["correct"] == 1 and stats_admin[0]["incorrect"] == 1, f"{stats_admin}")
check("fbstats.admin_total_excludes_no_feedback_and_duplicate", stats_admin and stats_admin[0]["total"] == 2, f"{stats_admin}")
check("fbstats.admin_destinations", stats_admin and set(stats_admin[0]["destinations"]) == {"مقصدِ یک", "مقصدِ دو"}, f"{stats_admin}")
check("fbstats.admin_accuracy", stats_admin and stats_admin[0]["accuracy"] == 50, f"{stats_admin}")

check("fbstats.user5_one_channel", len(stats_u5) == 1, f"{stats_u5}")
check("fbstats.user5_counts", stats_u5 and stats_u5[0]["correct"] == 1 and stats_u5[0]["incorrect"] == 0, f"{stats_u5}")
check("fbstats.user5_destinations", stats_u5 and stats_u5[0]["destinations"] == ["مقصدِ کاربرِ ۵"], f"{stats_u5}")

# --- مهم‌ترین چک: هیچ نشتی‌ای بینِ مالک‌ها نباشه ---
admin_channel_ids = {s["channel_id"] for s in stats_admin}
user5_channel_ids = {s["channel_id"] for s in stats_u5}
check("fbstats.no_cross_owner_leak", admin_channel_ids.isdisjoint(user5_channel_ids), f"{admin_channel_ids} vs {user5_channel_ids}")

check("fbstats.unknown_owner_sees_nothing", stats_u999 == [], f"{stats_u999}")

# ---- get_ad_feedback_posts ----
posts_admin = d.get_ad_feedback_posts(owner_user_id=None, channel_id=ch_a["id"])
check("fbstats.posts_count_for_admin_channel", len(posts_admin) == 2, f"{len(posts_admin)}")
check("fbstats.posts_only_feedback_rows", all(p["ad_feedback"] in ("correct", "incorrect") for p in posts_admin), "")

posts_u5_scoped_to_admin_channel = d.get_ad_feedback_posts(owner_user_id=5, channel_id=ch_a["id"])
check("fbstats.user5_cannot_see_admin_channel_posts", posts_u5_scoped_to_admin_channel == [], f"{posts_u5_scoped_to_admin_channel}")

verdict_filtered = d.get_ad_feedback_posts(owner_user_id=None, channel_id=ch_a["id"], verdict="incorrect")
check("fbstats.verdict_filter_works", len(verdict_filtered) == 1 and verdict_filtered[0]["id"] == pid2, f"{verdict_filtered}")

# ---- محافظتِ دوباره‌فیدبک‌ندادن دست‌نخورده مونده ----
check("fbstats.feedback_is_write_once", d.set_pending_ad_feedback(pid1, "incorrect") is False, "")
stats_admin_after = d.get_ad_feedback_channel_stats(owner_user_id=None)
check("fbstats.stats_unaffected_by_rewrite_attempt", stats_admin_after[0]["correct"] == 1, f"{stats_admin_after}")

print()
if fails:
    print(f"{len(fails)} FAILED:", fails)
    raise SystemExit(1)
print("ALL PASSED")
