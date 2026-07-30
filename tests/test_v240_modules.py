# -*- coding: utf-8 -*-
"""تستِ ماژول‌هایِ نسخه‌ی ۲.۴.۰ که تا حالا هیچ پوششِ تستی نداشتند:

  • bot/web_search.py       — تشخیصِ نوعِ جست‌وجو، پاک‌سازیِ کوئری، چرخشِ کلیدها
  • bot/ai_crypto.py        — رمزنگاری/رمزگشاییِ کلیدهای API
  • bot/ai_catalog.py       — سلامتِ کاتالوگ + «یک منبعِ حقیقتِ واحد» برایِ برچسب‌ها
  • bot/button_config.py    — اعتبارِ مقادیرِ رنگ (در test_button_colors هم هست)

اجرا:  python3 tests/test_v240_modules.py
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="repost-v240-")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ["DB_PATH"] = os.path.join(_TMP, "bot.sqlite")

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)


# ===========================================================================
#  ۱) web_search — تشخیصِ نوعِ جست‌وجو
# ===========================================================================
from bot import web_search as ws  # noqa: E402

# پیش‌فرض و حالت‌های ساده
for q, want in [
    ("عکس گربه", "image"),
    ("تصویر ماشین", "image"),
    ("کاور فیلم اوپنهایمر", "image"),
    ("wallpaper 4k", "image"),
    ("گربه", "image"),            # بدونِ کلمه‌ی کلیدی → پیش‌فرض عکس
    ("اخبار ایران", "news"),
    ("خبر فوتبال", "news"),
]:
    got = ws.detect_search_kind(q)
    check(f"websearch.kind[{q}]", got == want, f"want={want} got={got}")

# ⚠️ رگرسیون: «خبر» زیررشته‌ی «خبرنگار»/«خبرگزاری» هم هست. تطبیق باید فقط روی
# کلمه‌ی کامل باشد، وگرنه «عکس خبرنگار» به‌اشتباه خبر تشخیص داده می‌شود.
check("websearch.kind.substring_not_matched[عکس خبرنگار]",
      ws.detect_search_kind("عکس خبرنگار") == "image", ws.detect_search_kind("عکس خبرنگار"))
check("websearch.kind.substring_not_matched[خبرگزاری فارس]",
      ws.detect_search_kind("خبرگزاری فارس") == "image", ws.detect_search_kind("خبرگزاری فارس"))

# اگر هر دو نوع کلمه بودند، هرکدام زودتر آمده برنده است.
check("websearch.kind.earliest_wins[اخبار عکس دار]",
      ws.detect_search_kind("اخبار عکس دار") == "news", ws.detect_search_kind("اخبار عکس دار"))
check("websearch.kind.earliest_wins[عکس اخبار]",
      ws.detect_search_kind("عکس اخبار") == "image", ws.detect_search_kind("عکس اخبار"))

# ===========================================================================
#  ۲) web_search — پاک‌سازیِ کوئریِ ارسالی به SerpAPI
# ===========================================================================
for q, want in [
    ("عکس گربه", "گربه"),
    ("تصویر ماشین", "ماشین"),
    ("اخبار ایران", "ایران"),
    ("خبر فوتبال", "فوتبال"),
    ("گربه", "گربه"),
]:
    got = ws._strip_kind_words(q)
    check(f"websearch.strip[{q}]", got == want, f"want={want!r} got={got!r}")

# ⚠️ رگرسیون: اعرابِ چسبیده («عکسِ» با کسره) نویسه‌ی \w نیست، پس مرزِ کلمه آن را
# نمی‌گیرد و قبلاً یک کسره‌ی سرگردان («ِ گربه») توی کوئریِ SerpAPI باقی می‌ماند.
for q, want in [("عکسِ گربه", "گربه"), ("تصویرِ ماشین", "ماشین"), ("خبرِ فوتبال", "فوتبال")]:
    got = ws._strip_kind_words(q)
    check(f"websearch.strip.diacritics[{q}]", got == want, f"want={want!r} got={got!r}")

# کوئری‌ای که فقط از کلمه‌ی نوع تشکیل شده نباید خالی برگردد.
check("websearch.strip.never_empty", ws._strip_kind_words("عکس") != "", repr(ws._strip_kind_words("عکس")))

# ===========================================================================
#  ۳) web_search — چرخشِ round-robinِ کلیدهای SerpAPI
# ===========================================================================
W = ws.WebSearchSettings
W.clear_all()
check("websearch.keys.empty_when_unset", W.active_keys() == [], repr(W.active_keys()))
check("websearch.keys.no_keys_returns_empty_order", W.ordered_keys_for_search() == [], "")

for i in range(3):
    W.set_key(i, f"KEY{i}")
check("websearch.keys.active", W.active_keys() == ["KEY0", "KEY1", "KEY2"], repr(W.active_keys()))

# هر خانه دقیقاً MAX_KEYS تاست و مقدارِ ذخیره‌شده رمزنگاری شده (نه متنِ خام).
raw = W.get()["serpapi_keys"]
check("websearch.keys.slot_count", len(raw) == ws.MAX_KEYS, str(len(raw)))
check("websearch.keys.stored_encrypted", all(k not in ("KEY0", "KEY1", "KEY2") for k in raw), repr(raw))

# بعد از هر سرچ، کلیدِ شروع یک قدم جلو می‌رود (تا سهمیه‌ی همه یکنواخت مصرف شود).
orders = [W.ordered_keys_for_search() for _ in range(4)]
check("websearch.keys.rotation",
      [o[0] for o in orders] == ["KEY0", "KEY1", "KEY2", "KEY0"],
      repr([o[0] for o in orders]))
check("websearch.keys.rotation_keeps_all_as_fallback",
      all(sorted(o) == ["KEY0", "KEY1", "KEY2"] for o in orders), repr(orders))

# پاک‌کردنِ یک خانه‌ی وسط نباید بقیه را جابه‌جا/خراب کند.
W.set_key(1, "")
check("websearch.keys.clear_one_slot", W.active_keys() == ["KEY0", "KEY2"], repr(W.active_keys()))
W.clear_all()
check("websearch.keys.clear_all", W.active_keys() == [], repr(W.active_keys()))

# ===========================================================================
#  ۴) ai_crypto — رفت‌وبرگشتِ رمزنگاری
# ===========================================================================
from bot import ai_crypto as crypto  # noqa: E402

secret = "sk-test-1234567890abcdefXYZ"
enc = crypto.encrypt_text(secret)
check("aicrypto.encrypt_changes_value", enc != secret and enc != "", repr(enc[:20]))
check("aicrypto.roundtrip", crypto.decrypt_text(enc) == secret, repr(crypto.decrypt_text(enc)))
check("aicrypto.empty_in_empty_out", crypto.encrypt_text("") == "" and crypto.decrypt_text("") == "")
# توکنِ خراب نباید استثنا پرت کند (وگرنه کلِ منو/جست‌وجو می‌ترکد).
check("aicrypto.corrupt_token_is_safe", crypto.decrypt_text("این-یک-توکنِ-خراب-است") == "")
# رمزنگاریِ دوباره‌ی همان متن نباید همان توکن بدهد (Fernet زمان/nonce دارد).
check("aicrypto.not_deterministic", crypto.encrypt_text(secret) != enc)
check("aicrypto.mask_hides_key",
      crypto.mask_key(secret).endswith(secret[-4:]) and secret[:-4] not in crypto.mask_key(secret),
      crypto.mask_key(secret))
check("aicrypto.mask_empty", crypto.mask_key("") == "—")
check("aicrypto.mask_short_hides_everything", set(crypto.mask_key("ab")) == {"•"}, crypto.mask_key("ab"))

# ===========================================================================
#  ۵) ai_catalog — سلامتِ کاتالوگ
# ===========================================================================
from bot import ai_catalog as cat  # noqa: E402

check("aicatalog.task_ids_match_keys",
      all(k == t.id for k, t in cat.ALL_TASKS.items()),
      repr([k for k, t in cat.ALL_TASKS.items() if k != t.id]))
check("aicatalog.tasks_have_labels", all(t.label.strip() for t in cat.ALL_TASKS.values()))
check("aicatalog.categories_valid",
      all(t.category in (cat.CAP_TEXT, cat.CAP_IMAGE) for t in cat.ALL_TASKS.values()))
check("aicatalog.text_image_disjoint",
      not (set(cat.TEXT_TASKS) & set(cat.IMAGE_TASKS)),
      repr(set(cat.TEXT_TASKS) & set(cat.IMAGE_TASKS)))
check("aicatalog.all_tasks_is_union",
      set(cat.ALL_TASKS) == set(cat.TEXT_TASKS) | set(cat.IMAGE_TASKS))
check("aicatalog.status_labels_cover_all_statuses",
      all(s in cat.STATUS_LABELS for s in (
          cat.STATUS_NOT_SET, cat.STATUS_INVALID, cat.STATUS_CONNECTION_ERROR,
          cat.STATUS_QUOTA_EXCEEDED, cat.STATUS_WRONG_SERVICE, cat.STATUS_CHECKING,
          cat.STATUS_ACTIVE, cat.STATUS_FALLBACK)))

# ===========================================================================
#  ۶) «یک منبعِ حقیقتِ واحد»: برچسبِ صفحه‌ی اصلیِ AI == برچسبِ کاتالوگ
#     (باگِ نسخه‌های قبل: نامِ یک سرویس در دو صفحه دو جور بود.)
# ===========================================================================
from bot import keyboards as kb  # noqa: E402

_AI_BUTTON_TASKS = {
    "ai:translate": "translate",
    "ai:summarize": "summarize",
    "ai:rewrite": "rewrite",
    "ai:fix_text": "fix_text",
    "ai:hashtags": "generate_hashtags",
    "ai:prompt_writer": "prompt_writer",
    "ai:caption": "generate_caption",
    "ai:title": "generate_title",
    "ai:auto_reply": "auto_reply",
    "ai:analyze_text": "analyze_text",
    "ai:image": "generate_image",
    "ai:style_image": "edit_image",
}
_menu_labels = {
    b.callback_data: b.text
    for row in kb.ai_services_menu().inline_keyboard for b in row
}
for cbd, task_id in _AI_BUTTON_TASKS.items():
    want = cat.ALL_TASKS[task_id].label
    got = _menu_labels.get(cbd)
    check(f"ai_menu.label_matches_catalog[{task_id}]", got == want, f"want={want!r} got={got!r}")

# هر وظیفه‌ی متنیِ کاتالوگ باید یک دکمه در صفحه‌ی اصلیِ AI داشته باشد (وگرنه
# سرویس تعریف شده ولی از منو در دسترس نیست — دقیقاً باگی که v2.4.0 رفعش کرد).
_covered = set(_AI_BUTTON_TASKS.values())
_missing = set(cat.TEXT_TASKS) - _covered
check("ai_menu.all_text_tasks_reachable", not _missing, f"بدونِ دکمه: {sorted(_missing)}")

# ===========================================================================
#  ۷) منویِ کلیدهای SerpAPI دقیقاً MAX_KEYS خانه دارد
# ===========================================================================
_slots = [
    b.callback_data for row in kb.ai_web_settings_menu().inline_keyboard for b in row
    if (b.callback_data or "").startswith("ai:web_set:")
]
check("ai_menu.serpapi_slot_count", len(_slots) == ws.MAX_KEYS, repr(_slots))

print("\n=== V240_MODULES:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
raise SystemExit(1 if fails else 0)
