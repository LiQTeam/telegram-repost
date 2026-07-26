"""
گزارشِ فیدبکِ ادمین به فیلترِ تبلیغات.

این ماژول دو چیز می‌سازه:
  ۱) متنِ نمایشِ داخلِ خودِ ربات (خلاصه + جزئیاتِ هر کانال) - از رویِ
     database.get_ad_feedback_channel_stats / get_ad_feedback_posts.
  ۲) فایلِ اکسلِ کامل (دو برگه: خلاصه + جزئیات) برایِ دانلود.

هیچ کوئریِ مستقیمی به دیتابیس نمی‌زنه؛ فقط از توابعِ عمومیِ database.py که
از قبل owner_user_id رو درست فیلتر می‌کنن استفاده می‌کنه - پس ایزوله‌بودنِ
آمارِ هر کاربر/ادمین این‌جا تضمین‌شده‌ست، نه این‌جا دوباره پیاده‌سازی شده.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _esc
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .database import db
from .formatter import strip_html_tags
from .jdatetime_utils import format_jalali_datetime, now_jalali

_REASON_PREFIX = "🚩 مشکوک به تبلیغاتی: "


def _clean_reason(flag_reason: str | None) -> str:
    flag_reason = flag_reason or ""
    if flag_reason.startswith(_REASON_PREFIX):
        flag_reason = flag_reason[len(_REASON_PREFIX):]
    return flag_reason.strip() or "—"


def _snippet(row, limit: int = 160) -> str:
    body = (row["body_html"] or row["caption_html"] or "") if row else ""
    try:
        plain = strip_html_tags(body).strip()
    except Exception:
        plain = body
    plain = " ".join(plain.split())
    if len(plain) > limit:
        plain = plain[:limit].rstrip() + "…"
    return plain or "(بدونِ متن)"


def _jalali(created_at: str | None) -> str:
    """created_at از pending_posts رشته‌ی خامِ SQLite است (مثلِ
    '2026-07-20 14:03:11')؛ اگه پارس نشد، همون رشته‌ی خام برگردونده می‌شه تا
    گزارش هیچ‌وقت به‌خاطرِ یک تاریخِ عجیب کلاً خطا نده."""
    if not created_at:
        return "—"
    try:
        dt = datetime.strptime(created_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
        return format_jalali_datetime(dt)
    except Exception:
        return created_at


# ===========================================================================
#  متنِ نمایشِ داخلِ ربات
# ===========================================================================
def overview_text(stats: list[dict]) -> str:
    if not stats:
        return (
            "📊 <b>آمارِ فیدبکِ فیلترِ تبلیغات</b>\n\n"
            "هنوز هیچ فیدبکی برایِ کانال‌های شما ثبت نشده.\n"
            "وقتی پستی به‌خاطرِ مشکوک بودن به تبلیغ به صفِ تایید بیفته، زیرِ "
            "پیش‌نمایشش دو دکمه‌ی «✅ درست بود» و «❌ اشتباه بود» دیده می‌شه؛ با "
            "زدنِ اون دکمه‌ها این آمار کم‌کم پر می‌شه."
        )
    total_correct = sum(s["correct"] for s in stats)
    total_incorrect = sum(s["incorrect"] for s in stats)
    total = total_correct + total_incorrect
    pct = round(100 * total_correct / total) if total else 0
    lines = [
        "📊 <b>آمارِ فیدبکِ فیلترِ تبلیغات</b>",
        f"مجموع: {total} فیدبک · ✅ {total_correct} درست · ❌ {total_incorrect} اشتباه · دقتِ کلی ≈ {pct}٪",
        "",
        "یک کانالِ مبدأ رو از لیستِ زیر انتخاب کن تا مقصد(ها)، دلیلِ تشخیصِ "
        "فیلتر و چند نمونه‌ی اخیرش رو ببینی؛ یا کلِ این گزارش رو به‌صورتِ "
        "فایلِ اکسل دریافت کن.",
    ]
    return "\n".join(lines)


def channel_detail_text(stat: dict, posts: list, sample: int = 8) -> str:
    dest_txt = "، ".join(stat["destinations"]) if stat["destinations"] else "— (بدونِ مقصدِ متصل)"
    lines = [
        f"📡 <b>{_esc(stat['channel_name'])}</b>",
        f"🎯 مقصد(ها): {_esc(dest_txt)}",
        "",
        f"✅ درست بود: <b>{stat['correct']}</b>",
        f"❌ اشتباه بود: <b>{stat['incorrect']}</b>",
        f"📈 دقتِ فیلتر برایِ این کانال: <b>{stat['accuracy']}٪</b> (از {stat['total']} فیدبک)",
    ]
    if posts:
        lines.append("")
        lines.append(f"🕓 <b>آخرین {min(sample, len(posts))} نمونه:</b>")
        for row in posts[:sample]:
            mark = "✅" if row["ad_feedback"] == "correct" else "❌"
            reason = _clean_reason(row["flag_reason"])
            snip = _snippet(row, 110)
            lines.append(f"\n{mark} «{_esc(snip)}»\n   ↳ دلیلِ تشخیصِ فیلتر: {_esc(reason)}")
    return "\n".join(lines)


# ===========================================================================
#  خروجیِ اکسل
# ===========================================================================
_FONT_NAME = "Tahoma"  # فونتِ رایج و باکیفیت برایِ فارسی روی ویندوز/آفیس
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(name=_FONT_NAME, size=11, bold=True, color="FFFFFF")
_TITLE_FONT = Font(name=_FONT_NAME, size=14, bold=True, color="1F4E78")
_SUBTITLE_FONT = Font(name=_FONT_NAME, size=10, italic=True, color="666666")
_BASE_FONT = Font(name=_FONT_NAME, size=10)
_BOLD_FONT = Font(name=_FONT_NAME, size=10, bold=True)
_CORRECT_FILL = PatternFill("solid", fgColor="E2EFDA")
_INCORRECT_FILL = PatternFill("solid", fgColor="FCE4E4")
_TOTAL_FILL = PatternFill("solid", fgColor="F2F2F2")
_THIN = Side(style="thin", color="B7B7B7")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP_RIGHT = Alignment(horizontal="right", vertical="center", wrap_text=True)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _style_header_row(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        c = ws.cell(row=row, column=col)
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.alignment = _CENTER
        c.border = _BORDER
    ws.row_dimensions[row].height = 22


def _autofit(ws, widths: dict[int, int]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def build_ad_feedback_workbook(
    owner_user_id: int | None = None,
    channel_id: int | None = None,
    scope_label: str = "",
) -> bytes | None:
    """فایلِ اکسلِ کامل رو می‌سازه و بایت‌های خامش رو برمی‌گردونه (برایِ ارسالِ
    مستقیم با send_document، بدون نوشتنِ فایلِ موقت رویِ دیسک).
    owner_user_id: نگاه کن به database._ad_feedback_owner_clause - همیشه
    دقیقاً محدود به همون یک مالک (هیچ‌وقت «همه با هم»).
    channel_id: اگه پر باشه، فقط همون یک کانال (خروجیِ تک‌کانالی).
    اگه هیچ فیدبکی توی محدوده‌ی درخواستی نباشه، None برمی‌گردونه."""
    stats = db.get_ad_feedback_channel_stats(owner_user_id=owner_user_id)
    if channel_id is not None:
        stats = [s for s in stats if s["channel_id"] == channel_id]
    if not stats:
        return None

    posts_by_channel = {
        s["channel_id"]: db.get_ad_feedback_posts(owner_user_id=owner_user_id, channel_id=s["channel_id"])
        for s in stats
    }

    wb = Workbook()

    # ---------------- برگه‌ی ۱: خلاصه ----------------
    ws = wb.active
    ws.title = "خلاصه"
    ws.sheet_view.rightToLeft = True
    ws.freeze_panes = "A5"

    ncols = 6
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.cell(row=1, column=1, value="📊 گزارشِ فیدبکِ فیلترِ تبلیغات")
    ws["A1"].font = _TITLE_FONT
    ws["A1"].alignment = _CENTER
    ws.row_dimensions[1].height = 28

    subtitle = f"تاریخِ تولیدِ گزارش: {format_jalali_datetime(now_jalali())}"
    if scope_label:
        subtitle = f"{scope_label}  ·  {subtitle}"
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
    ws.cell(row=2, column=1, value=subtitle)
    ws["A2"].font = _SUBTITLE_FONT
    ws["A2"].alignment = _CENTER

    headers = ["📡 کانالِ مبدأ", "🎯 کانال‌های مقصد", "✅ درست بود", "❌ اشتباه بود", "مجموع", "📈 دقت"]
    header_row = 4
    for i, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=i, value=h)
    _style_header_row(ws, header_row, ncols)

    r = header_row + 1
    total_correct = total_incorrect = 0
    for s in stats:
        ws.cell(row=r, column=1, value=s["channel_name"])
        ws.cell(row=r, column=2, value="، ".join(s["destinations"]) or "—")
        c_correct = ws.cell(row=r, column=3, value=s["correct"])
        c_incorrect = ws.cell(row=r, column=4, value=s["incorrect"])
        ws.cell(row=r, column=5, value=s["total"])
        ws.cell(row=r, column=6, value=f"{s['accuracy']}٪")
        for col in range(1, ncols + 1):
            cell = ws.cell(row=r, column=col)
            cell.font = _BASE_FONT
            cell.border = _BORDER
            cell.alignment = _WRAP_RIGHT if col in (1, 2) else _CENTER
        c_correct.fill = _CORRECT_FILL
        c_incorrect.fill = _INCORRECT_FILL
        total_correct += s["correct"]
        total_incorrect += s["incorrect"]
        r += 1

    total_all = total_correct + total_incorrect
    overall_pct = round(100 * total_correct / total_all) if total_all else 0
    ws.cell(row=r, column=1, value="🔢 جمعِ کل")
    ws.cell(row=r, column=2, value="")
    ws.cell(row=r, column=3, value=total_correct)
    ws.cell(row=r, column=4, value=total_incorrect)
    ws.cell(row=r, column=5, value=total_all)
    ws.cell(row=r, column=6, value=f"{overall_pct}٪")
    for col in range(1, ncols + 1):
        cell = ws.cell(row=r, column=col)
        cell.font = _BOLD_FONT
        cell.border = _BORDER
        cell.fill = _TOTAL_FILL
        cell.alignment = _WRAP_RIGHT if col == 1 else _CENTER

    _autofit(ws, {1: 30, 2: 38, 3: 12, 4: 12, 5: 10, 6: 10})

    # ---------------- برگه‌ی ۲: جزئیات ----------------
    ws2 = wb.create_sheet("جزئیات")
    ws2.sheet_view.rightToLeft = True
    ws2.freeze_panes = "A2"

    headers2 = ["📡 کانالِ مبدأ", "🎯 کانال‌های مقصد", "نتیجه‌ی فیدبک", "دلیلِ تشخیصِ فیلتر", "متنِ پست", "🗓 تاریخ"]
    ncols2 = len(headers2)
    for i, h in enumerate(headers2, start=1):
        ws2.cell(row=1, column=i, value=h)
    _style_header_row(ws2, 1, ncols2)

    channel_dest_map = {s["channel_id"]: ("، ".join(s["destinations"]) or "—") for s in stats}
    channel_name_map = {s["channel_id"]: s["channel_name"] for s in stats}

    r2 = 2
    for s in stats:
        for row in posts_by_channel.get(s["channel_id"], []):
            verdict = row["ad_feedback"]
            mark = "✅ درست بود" if verdict == "correct" else "❌ اشتباه بود"
            ws2.cell(row=r2, column=1, value=channel_name_map.get(s["channel_id"], "—"))
            ws2.cell(row=r2, column=2, value=channel_dest_map.get(s["channel_id"], "—"))
            v_cell = ws2.cell(row=r2, column=3, value=mark)
            ws2.cell(row=r2, column=4, value=_clean_reason(row["flag_reason"]))
            ws2.cell(row=r2, column=5, value=_snippet(row, 400))
            ws2.cell(row=r2, column=6, value=_jalali(row["created_at"]))
            for col in range(1, ncols2 + 1):
                cell = ws2.cell(row=r2, column=col)
                cell.font = _BASE_FONT
                cell.border = _BORDER
                cell.alignment = _CENTER if col in (3, 6) else _WRAP_RIGHT
            v_cell.fill = _CORRECT_FILL if verdict == "correct" else _INCORRECT_FILL
            r2 += 1

    _autofit(ws2, {1: 24, 2: 28, 3: 15, 4: 42, 5: 55, 6: 18})

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
