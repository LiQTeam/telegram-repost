# -*- coding: utf-8 -*-
"""تستِ عملیِ «هر دکمه‌ی منو واقعاً باز می‌شود».

هر دکمه‌ی اینلاینِ ربات یک callback_data داره. این تست تمامِ callback_dataهایی
که سازنده‌های کیبورد (bot/keyboards.py و بقیه) تولید می‌کنن رو از خودِ سورس
استخراج می‌کنه و بعد هر کدوم رو با یک queryِ ساختگی و یک دیتابیسِ موقتِ واقعی
از مسیرِ واقعیِ `handlers.menu._dispatch` عبور می‌ده.

هدف: گرفتنِ خطاهای زمانِ‌اجرا (AttributeError/TypeError/KeyError/SQL) در
صفحه‌هایی از منو که ممکنه هیچ‌وقت دستی باز نشن. هیچ درخواستِ شبکه‌ای زده
نمی‌شه؛ همه‌ی متدهای Bot و query استاب شده‌ن.

اجرا:  python3 tests/test_menu_smoke.py
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# دیتابیس/توکنِ موقت — قبل از هر importی از bot ست می‌شن، چون bot.config
# موقعِ import خونده می‌شه.
_TMP = tempfile.mkdtemp(prefix="repost-menu-smoke-")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_IDS", "424242")
os.environ["DB_PATH"] = os.path.join(_TMP, "bot.sqlite")

ADMIN_ID = 424242

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, ("" if cond else extra))
    if not cond:
        fails.append(name)


# ===========================================================================
#  استخراجِ callback_dataها از سورس
# ===========================================================================
_BUTTON_FUNCS = {"InlineKeyboardButton", "_btn", "btn"}

# مقدارِ نمونه‌ی هر placeholder بر اساسِ نامِ متغیرش، تا callback_dataیی که به
# دیسپچر داده می‌شه دقیقاً همون شکلی باشه که کاربرِ واقعی می‌فرسته (تعدادِ
# درستِ بخش‌ها + مقدارِ معتبرِ هر بخش). ترتیب مهمه: اولین تطبیق برنده‌ست.
_PLACEHOLDER_VALUES: list[tuple[tuple[str, ...], str]] = [
    (("perm_key", "permkey", "pkey"), "pp_own"),
    (("plat", "platform"), "tg"),
    (("pos",), "bottom_right"),
    (("slot",), "1"),
    (("kind",), "photo"),
    (("lang", "target"), "fa"),
    (("level",), "short"),
    (("style", "preset"), "oil"),
    (("mode",), "instant"),
    (("prov", "provider"), "mistral"),
    (("task",), "rewrite"),
    (("state", "flag", "val", "value", "on", "enabled"), "1"),
]


def _placeholder_value(expr_src: str, cid: int, did: int) -> str:
    low = expr_src.lower()
    for names, val in _PLACEHOLDER_VALUES:
        if any(n in low for n in names):
            return val
    if "did" in low or "dest" in low:
        return str(did)
    if "uid" in low or "user" in low or "tid" in low:
        return str(ADMIN_ID)
    if "cid" in low or "ch_id" in low or "chan" in low or "src" in low:
        return str(cid)
    return "1"


def _render(node: ast.AST, cid: int, did: int) -> str | None:
    """یک callback_dataِ کاملِ نمونه از رشته/f-stringِ سورس می‌سازد."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                out.append(_placeholder_value(ast.unparse(v.value), cid, did))
            else:
                return None
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _render(node.left, cid, did)
        right = _render(node.right, cid, did)
        if left is None:
            return None
        return left + (right if right is not None else "1")
    return None


def collect_callbacks(cid: int, did: int) -> dict[str, tuple[str, int]]:
    """همه‌ی callback_dataهای نمونه → (فایل، خط) جایی که دکمه ساخته می‌شه."""
    found: dict[str, tuple[str, int]] = {}
    for root, dirs, files in os.walk(os.path.join(ROOT, "bot")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, ROOT)
            tree = ast.parse(open(path, encoding="utf-8").read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name not in _BUTTON_FUNCS:
                    continue
                arg = node.args[1] if len(node.args) >= 2 else None
                for kw in node.keywords:
                    if kw.arg == "callback_data":
                        arg = kw.value
                if arg is None:
                    continue
                data = _render(arg, cid, did)
                if data:
                    found.setdefault(data, (rel, node.lineno))
    return found


# ===========================================================================
#  استاب‌های تلگرام
# ===========================================================================
class _FakeChat:
    def __init__(self, cid=ADMIN_ID, ctype="private"):
        self.id = cid
        self.type = ctype
        self.title = "chat"


class _FakeUser:
    def __init__(self, uid=ADMIN_ID):
        self.id = uid
        self.first_name = "Admin"
        self.username = "admin"
        self.full_name = "Admin"
        self.is_bot = False


class _FakeMessage:
    def __init__(self):
        self.chat = _FakeChat()
        self.message_id = 1
        self.chat_id = ADMIN_ID
        self.text = "متن"
        self.caption = None
        self.photo = None
        self.video = None
        self.document = None
        self.animation = None
        self.audio = None
        self.voice = None
        self.sticker = None
        self.media_group_id = None
        self.reply_markup = None
        self.date = None

    async def reply_text(self, *a, **k):
        return self

    async def reply_photo(self, *a, **k):
        return self

    async def reply_document(self, *a, **k):
        return self

    async def edit_text(self, *a, **k):
        return self

    async def delete(self, *a, **k):
        return True


class _FakeBot:
    """هر متدِ Bot به یک coroutine بی‌اثر تبدیل می‌شه (بدونِ شبکه)."""

    def __init__(self):
        self.calls: list[str] = []
        self.id = 999
        self.username = "testbot"

    def __getattr__(self, name):
        async def _call(*a, **k):
            self.calls.append(name)
            return _FakeMessage()
        return _call


class _FakeQuery:
    def __init__(self, data: str, bot: _FakeBot):
        self.data = data
        self.id = "q1"
        self.message = _FakeMessage()
        self.from_user = _FakeUser()
        self._bot = bot
        self.answered = False

    async def answer(self, *a, **k):
        self.answered = True
        return True

    async def edit_message_text(self, *a, **k):
        return _FakeMessage()

    async def edit_message_caption(self, *a, **k):
        return _FakeMessage()

    async def edit_message_reply_markup(self, *a, **k):
        return _FakeMessage()

    async def delete_message(self, *a, **k):
        return True

    async def get_bot(self):
        return self._bot


class _FakeContext:
    def __init__(self, bot: _FakeBot):
        self.bot = bot
        self.user_data: dict = {}
        self.chat_data: dict = {}
        self.bot_data: dict = {}
        self.application = None
        self.job_queue = None
        self.args: list[str] = []


# ===========================================================================
#  آماده‌سازیِ دیتابیسِ موقت با داده‌ی نمونه (تا صفحه‌های «جزئیات» خالی نباشن)
# ===========================================================================
def seed_db():
    from bot.database import db
    # ماژولِ ایزوله‌ی «تبلیغات» دیتابیسِ خودش رو داره که در main.py با
    # auto_poster.setup() ساخته می‌شه؛ اینجا هم همون مسیر تکرار می‌شه — منتها
    # روی همون پوشه‌ی موقت، تا تستْ data/ِ پروژه رو کثیف نکنه.
    import pathlib
    from bot.auto_poster import config as ads_config, db as ads_db
    ads_config.DB_PATH = pathlib.Path(_TMP) / "auto_poster.db"
    ads_db.init_db()
    db.add_user("ادمینِ تست", ADMIN_ID, ADMIN_ID)
    db.add_channel("@src_test", "کانالِ تست", ADMIN_ID)
    db.add_destination("@dst_test", "مقصدِ تست", ADMIN_ID)
    row = db._conn.execute("SELECT id FROM channels ORDER BY id LIMIT 1").fetchone()
    cid = row["id"] if row else 1
    row = db._conn.execute("SELECT id FROM destinations ORDER BY id LIMIT 1").fetchone()
    did = row["id"] if row else 1
    db.toggle_link(cid, did)
    return cid, did


async def run_all(cases: list[str]):
    from bot.handlers.menu import _dispatch

    bot = _FakeBot()
    errors: list[tuple[str, str]] = []
    for data in cases:
        query = _FakeQuery(data, bot)
        ctx = _FakeContext(bot)
        try:
            await _dispatch(data, query, ctx, ADMIN_ID)
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc().splitlines()
            frame = ""
            for i in range(len(tb) - 1, -1, -1):
                if "/bot/" in tb[i]:
                    frame = tb[i].strip() + " → " + (tb[i + 1].strip() if i + 1 < len(tb) else "")
                    break
            errors.append((data, f"{type(e).__name__}: {e}\n      {frame}"))
    return errors


def main() -> int:
    cid, did = seed_db()
    cases_map = collect_callbacks(cid, did)
    cases = sorted(cases_map)
    print(f"[i] {len(cases)} دکمه از سورس استخراج و برای اجرایِ واقعی ساخته شد")
    print(f"[i] دیتابیسِ موقت: {os.environ['DB_PATH']}")

    errors = asyncio.run(run_all(cases))

    for data, msg in errors:
        src = cases_map.get(data, ("?", 0))
        print(f"FAIL menu_smoke[{data}] ({src[0]}:{src[1]})\n      {msg}")
        fails.append(f"menu_smoke[{data}]")

    check("menu_smoke.no_runtime_errors", not errors, f"{len(errors)} از {len(cases)} دکمه خطا داد")

    print("\n=== MENU_SMOKE:", "ALL PASS" if not fails else f"{len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
