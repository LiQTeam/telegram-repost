"""
واترمارکِ سفارشی (فازِ ۷، ۸، ۹، ۱۰).

- بخشِ ۷: آپلودِ لوگو/تصویر توسطِ کاربر، ذخیره‌ی دائمی، چند واترمارکِ نام‌دار،
  تنظیماتِ Transparency/Size/Rotation/Position (+ X/Y دقیق)، اختصاصِ هر
  واترمارک به یک یا چند مقصد.
- بخشِ ۸: انتخاب/تغییرِ واترمارک در پیش‌نمایشِ ارسالِ دستی (سیمِ اتصال در
  bot/manual_poster.py، تابعِ apply_watermark_for_post اینجا).
- بخشِ ۹: هر واترمارک owner_user_id دارد؛ لیست‌ها همیشه بر اساسِ owner فیلتر
  می‌شوند - کاربرها واترمارکِ همدیگه رو نمی‌بینن.
- بخشِ ۱۰: نوعِ متنیِ محو (kind='text') - متنِ بزرگِ کم‌رنگِ زاویه‌دار روی تصویر.
"""
from __future__ import annotations

import io
import logging
import math

from PIL import Image, ImageDraw

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import config
from .database import db
from .watermark import get_font, hex_to_rgb, POSITIONS, shape_rtl

log = logging.getLogger("repost_bot.custom_watermark")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

_POSITION_XY = {
    "top_left": (0.0, 0.0),
    "top_center": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "bottom_left": (0.0, 1.0),
    "bottom_center": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
    "center": (0.5, 0.5),
}
_POSITIONS_FULL = dict(POSITIONS)
_POSITIONS_FULL["center"] = "⏺ مرکز"


def _is_admin(uid: int | None) -> bool:
    return bool(uid) and uid in config.ADMIN_IDS


def _owner_of(uid: int | None) -> int | None:
    """ادمین → None (یعنی واترمارک‌های سراسری/بدونِ owner)؛ کاربرِ مجاز → آیدیِ داخلی‌اش."""
    if _is_admin(uid):
        return None
    u = db.get_user_by_telegram_id(uid) if uid else None
    return u["id"] if u else None


# ============================================================================
# رندر
# ============================================================================

def _resolve_xy(pos: str, x_pos, y_pos, canvas_w: int, canvas_h: int, item_w: int, item_h: int, margin: int = 16):
    if x_pos is not None and y_pos is not None:
        return int(x_pos), int(y_pos)
    fx, fy = _POSITION_XY.get(pos, (1.0, 1.0))
    if fx == 1.0:
        x = canvas_w - item_w - margin
    elif fx == 0.0:
        x = margin
    else:
        x = int(fx * canvas_w - item_w / 2)
    if fy == 1.0:
        y = canvas_h - item_h - margin
    elif fy == 0.0:
        y = margin
    else:
        y = int(fy * canvas_h - item_h / 2)
    return x, y


def render_image_watermark(base_bytes: bytes, logo_bytes: bytes, wm_row) -> bytes:
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")

    target_w = max(8, int(base.width * (wm_row["size_pct"] / 100.0)))
    ratio = target_w / logo.width
    target_h = max(8, int(logo.height * ratio))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    if wm_row["rotation"]:
        logo = logo.rotate(wm_row["rotation"], expand=True)

    alpha = logo.split()[3].point(lambda p: int(p * (wm_row["transparency"] / 100.0)))
    logo.putalpha(alpha)

    x, y = _resolve_xy(wm_row["position"], wm_row["x_pos"], wm_row["y_pos"], base.width, base.height, logo.width, logo.height)
    base.alpha_composite(logo, (x, y))

    out = io.BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def render_text_watermark(base_bytes: bytes, wm_row) -> bytes:
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(10, int(base.width * (wm_row["size_pct"] / 100.0) / 4))
    font = get_font(font_size)
    # شکل‌دهیِ فارسی/عربی تا حروفِ متنِ واترمارک درست و راست‌به‌چپ رسم شوند.
    text = shape_rtl(wm_row["text"] or "")
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    txt_layer = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(txt_layer)
    alpha = max(0, min(255, int(255 * (wm_row["transparency"] / 100.0))))
    tdraw.text((10, 10), text, font=font, fill=(255, 255, 255, alpha))

    rotation = wm_row["rotation"] or 0
    txt_layer = txt_layer.rotate(rotation, expand=True)

    x, y = _resolve_xy(
        wm_row["position"], wm_row["x_pos"], wm_row["y_pos"],
        base.width, base.height, txt_layer.width, txt_layer.height,
    )
    overlay.alpha_composite(txt_layer, (x, y))
    base = Image.alpha_composite(base, overlay)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def render_text_watermark_tiled(base_bytes: bytes, wm_row) -> bytes:
    """حالتِ دومِ متنِ محو: به‌جایِ یک بلوکِ متنیِ چرخیده در یک نقطه، همون متن
    به‌صورتِ کاشی‌شده و تکرارشونده، دقیقاً رویِ خطِ قطریِ خودِ عکس (از گوشه به
    گوشه‌ی مقابل) چاپ می‌شه - مثلِ واترمارکِ زمینه‌ایِ سایت‌های استوک-عکس.
    رنگ می‌تونه تکی (color_a) یا گرادیانت (color_a → color_b) باشه."""
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    width, height = base.size
    # شکل‌دهیِ فارسی/عربی تا کاشی‌هایِ متنِ واترمارک درست و راست‌به‌چپ رسم شوند.
    text = shape_rtl((wm_row["text"] or "").strip())
    if not text:
        out = io.BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()

    opacity = max(0, min(100, int(wm_row["transparency"])))
    font_size = max(8, min(400, int(base.width * (wm_row["size_pct"] / 100.0) / 4)))
    color_mode = wm_row["color_mode"] or "single"
    color_a = hex_to_rgb(wm_row["color_a"] or "#FFFFFF")
    color_b = hex_to_rgb(wm_row["color_b"] or wm_row["color_a"] or "#FFFFFF")
    font = get_font(font_size)

    angle_deg = math.degrees(math.atan2(height, width))
    diag_len = int((width ** 2 + height ** 2) ** 0.5) + font_size * 4

    draw_probe = ImageDraw.Draw(base)
    bbox = draw_probe.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0:
        out = io.BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()

    gap = max(int(tw * 0.9), 30)
    layer_h = max(th * 3, font_size * 3)
    layer = Image.new("RGBA", (diag_len, layer_h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    alpha = int(255 * opacity / 100)

    x = -gap
    while x < diag_len:
        if color_mode == "gradient":
            t = max(0.0, min(1.0, x / diag_len)) if diag_len else 0.0
            fill = (
                int(color_a[0] + (color_b[0] - color_a[0]) * t),
                int(color_a[1] + (color_b[1] - color_a[1]) * t),
                int(color_a[2] + (color_b[2] - color_a[2]) * t),
                alpha,
            )
        else:
            fill = (color_a[0], color_a[1], color_a[2], alpha)
        ld.text((x, (layer_h - th) // 2 - bbox[1]), text, font=font, fill=fill)
        x += tw + gap

    rotated = layer.rotate(-angle_deg, expand=True, resample=Image.BICUBIC)
    rx = (width - rotated.width) // 2
    ry = (height - rotated.height) // 2
    base.alpha_composite(rotated, (rx, ry))

    out = io.BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


async def apply_named_watermark(bot, base_bytes: bytes, wm_row) -> bytes:
    """اعمالِ یک واترمارکِ سفارشی (تصویری یا متنیِ محو - تکی یا کاشی‌شده) رویِ
    بایتِ خامِ عکس."""
    # ⚠️ رندرِ PIL سنگین و کاملاً همزمانه (sync). قبلاً مستقیم داخلِ حلقه‌ی
    # asyncio اجرا می‌شد و تا آخرِ کارش کلِ ربات (همه‌ی کلیک‌ها و پیام‌های بقیه)
    # قفل می‌موند - همون علتِ «باید چند بار دکمه رو بزنم تا جواب بده». حالا مثلِ
    # واترمارکِ اصلی (poster.py) از طریقِ concurrency.run_heavy توی ThreadPool
    # اجرا می‌شه.
    from . import concurrency
    try:
        if wm_row["kind"] == "text":
            if "tiled" in wm_row.keys() and wm_row["tiled"]:
                return await concurrency.run_heavy(render_text_watermark_tiled, base_bytes, wm_row)
            return await concurrency.run_heavy(render_text_watermark, base_bytes, wm_row)
        if wm_row["image_file_id"]:
            f = await bot.get_file(wm_row["image_file_id"])
            logo_bytes = bytes(await f.download_as_bytearray())
            return await concurrency.run_heavy(render_image_watermark, base_bytes, logo_bytes, wm_row)
        return base_bytes
    except Exception as e:
        log.warning("اعمالِ واترمارکِ سفارشیِ #%s شکست خورد؛ عکسِ خام برگردانده شد: %s", wm_row["id"], e)
        return base_bytes


async def apply_named_watermarks(bot, base_bytes: bytes, wm_rows: list) -> bytes:
    """اعمالِ چند واترمارکِ دلخواه پشتِ سرِ هم رویِ یک عکس (مثلاً یه لوگو + یه
    متنِ محو هم‌زمان روی یک مقصد، یا چندتا واترمارکِ دستی‌چیده‌شده روی یک پستِ
    خاص در صفِ تایید). ترتیبِ اعمال همون ترتیبِ لیستِ ورودیه."""
    for wm_row in wm_rows:
        base_bytes = await apply_named_watermark(bot, base_bytes, wm_row)
    return base_bytes


def _sample_canvas() -> bytes:
    """ساختِ یک عکسِ نمونه‌ی خام (بدونِ هیچ واترمارکی) که پیش‌نمایشِ هر واترمارکِ
    سفارشی روی همین ساخته می‌شه - تا معلوم بشه هرکدوم دقیقاً کجا/چه‌شکلی روی
    عکس میفته."""
    width, height = 1000, 700
    img = Image.new("RGB", (width, height), (238, 240, 243))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, width - 40, height - 40], outline=(205, 210, 216), width=3)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95)
    return out.getvalue()


async def send_all_previews(bot, chat_id: int, uid: int | None = None) -> int:
    """
    برایِ هر واترمارکِ سفارشیِ فعالِ کاربر، یک عکسِ نمونه با همون واترمارک
    اعمال‌شده می‌فرسته - اگه ۳ تا واترمارکِ سفارشی ست شده باشه، ۳ تا عکسِ
    جداگانه فرستاده می‌شه تا معلوم بشه هرکدوم دقیقاً کجا قرار می‌گیره.
    خروجی: تعدادِ پیش‌نمایش‌هایی که فرستاده شد.
    """
    owner = _owner_of(uid)
    items = db.list_custom_watermarks(owner_user_id=owner)
    base = _sample_canvas()
    sent = 0
    for wm_row in items:
        try:
            preview_bytes = await apply_named_watermark(bot, base, wm_row)
        except Exception as e:
            log.warning("ساختِ پیش‌نمایشِ واترمارکِ سفارشیِ #%s شکست خورد: %s", wm_row["id"], e)
            continue
        kind_fa = "متنی" if wm_row["kind"] == "text" else "تصویری"
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=preview_bytes,
                caption=f"🖼 پیش‌نمایشِ واترمارکِ سفارشی «{wm_row['name']}» ({kind_fa})",
            )
            sent += 1
        except Exception as e:
            log.warning("ارسالِ پیش‌نمایشِ واترمارکِ سفارشیِ #%s ناموفق بود: %s", wm_row["id"], e)
    return sent


# ============================================================================
# منویِ مدیریت (پیشوندِ کالبک: wmc:)
# ============================================================================

def root_content(uid: int | None = None):
    owner = _owner_of(uid)
    items = db.list_custom_watermarks(owner_user_id=owner)
    lines = "\n".join(f"🏷 {w['name']} ({'متنی' if w['kind']=='text' else 'تصویری'})" for w in items) or "هنوز واترمارکی نساختی."
    text = f"🖼 <b>واترمارکِ سفارشی</b>\n{DIVIDER}\n{lines}"
    rows = [[InlineKeyboardButton(w["name"], callback_data=f"wmc:view:{w['id']}")] for w in items]
    rows.append([InlineKeyboardButton("➕ واترمارکِ تصویریِ جدید", callback_data="wmc:new_image")])
    rows.append([InlineKeyboardButton("➕ واترمارکِ متنیِ محو جدید", callback_data="wmc:new_text")])
    rows.append([InlineKeyboardButton("🏠 بازگشت به منویِ اصلی", callback_data="menu:main", api_kwargs={"style": "primary"})])
    return text, InlineKeyboardMarkup(rows), ParseMode.HTML


def _detail_view(wm_row):
    is_text = wm_row["kind"] == "text"
    is_tiled = is_text and bool(wm_row["tiled"])
    kind = ("متنیِ محوِ کاشی‌شده (پس‌زمینه‌ای)" if is_tiled else "متنی محو") if is_text else "تصویری"
    dests = db.get_watermark_destinations(wm_row["id"])
    dest_names = []
    for did in dests:
        d = db.get_destination(did)
        if d:
            dest_names.append(d["title"] or d["chat_id"])
    text = (
        f"🏷 <b>{wm_row['name']}</b>\n{DIVIDER}\n"
        f"نوع: {kind}\n"
        f"شفافیت: {wm_row['transparency']}%\n"
        f"اندازه: {wm_row['size_pct']}%\n"
    )
    if is_tiled:
        color_desc = (
            f"گرادیانت ({wm_row['color_a']} ← {wm_row['color_b'] or wm_row['color_a']})"
            if wm_row["color_mode"] == "gradient" else f"تکی ({wm_row['color_a']})"
        )
        text += f"رنگ: {color_desc}\n"
    else:
        text += f"چرخش: {wm_row['rotation']}°\n"
        text += (
            f"موقعیت: {_POSITIONS_FULL.get(wm_row['position'], wm_row['position'])}"
            + (f" (X:{wm_row['x_pos']}, Y:{wm_row['y_pos']})" if wm_row["x_pos"] is not None else "")
            + "\n"
        )
    text += f"مقصدهایِ متصل: {', '.join(dest_names) or 'هیچکدام'}\n"
    text += f"روی آلبوم: {'همه‌ی عکس‌ها' if wm_row['album_all'] else 'فقط عکسِ اول'}"

    wid = wm_row["id"]
    rows = [
        [InlineKeyboardButton("🎯 تنظیمِ مقصدها", callback_data=f"wmc:destpick:{wid}")],
        [InlineKeyboardButton("🔁 شفافیت", callback_data=f"wmc:set_transparency:{wid}"),
         InlineKeyboardButton("📐 اندازه", callback_data=f"wmc:set_size:{wid}")],
    ]
    if is_text:
        rows.append([InlineKeyboardButton(
            "🧱 حالتِ کاشی‌شده: " + ("روشن ✅" if is_tiled else "خاموش ▫️"),
            callback_data=f"wmc:toggle_tiled:{wid}",
        )])
    if is_tiled:
        rows.append([
            InlineKeyboardButton("🎨 رنگ", callback_data=f"wmc:set_color_a:{wid}"),
            InlineKeyboardButton(
                "🌈 گرادیانت: " + ("روشن ✅" if wm_row["color_mode"] == "gradient" else "خاموش ▫️"),
                callback_data=f"wmc:toggle_gradient:{wid}",
            ),
        ])
        if wm_row["color_mode"] == "gradient":
            rows.append([InlineKeyboardButton("🎨 رنگِ دوم (پایانِ گرادیانت)", callback_data=f"wmc:set_color_b:{wid}")])
    else:
        rows.append([InlineKeyboardButton("🔄 چرخش", callback_data=f"wmc:set_rotation:{wid}"),
                     InlineKeyboardButton("📍 موقعیت", callback_data=f"wmc:set_position:{wid}")])
    rows.append([InlineKeyboardButton(
        "🖼 آلبوم: " + ("همه‌ی عکس‌ها ✅" if wm_row["album_all"] else "فقط عکسِ اول ▫️"),
        callback_data=f"wmc:toggle_album_all:{wid}",
    )])
    rows.append([InlineKeyboardButton("🔍 پیش‌نمایش", callback_data=f"wmc:preview:{wid}")])
    rows.append([InlineKeyboardButton("🗑 حذف", callback_data=f"wmc:delete:{wid}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu:customwm")])
    return text, InlineKeyboardMarkup(rows)


async def handle_callback(data: str, query, context: ContextTypes.DEFAULT_TYPE, uid: int | None) -> None:
    owner = _owner_of(uid)

    if data == "wmc:new_image":
        context.user_data["wmc_new"] = {"kind": "image"}
        context.user_data["wmc_awaiting"] = "new_name"
        await query.edit_message_text(
            "اسمِ این واترمارک رو بفرست (مثلا «لوگوی اصلی»):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="menu:customwm")]]),
        )
        return

    if data == "wmc:new_text":
        context.user_data["wmc_new"] = {"kind": "text"}
        context.user_data["wmc_awaiting"] = "new_name"
        await query.edit_message_text(
            "اسمِ این واترمارکِ متنی رو بفرست:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="menu:customwm")]]),
        )
        return

    if data.startswith("wmc:new_text_mode:"):
        mode = data.split(":")[2]
        draft = context.user_data.get("wmc_new", {})
        wid = db.create_custom_watermark(
            owner, draft.get("name", "واترمارک"), kind="text",
            text=draft.get("text", ""), tiled=1 if mode == "tiled" else 0,
        )
        context.user_data.pop("wmc_new", None)
        context.user_data.pop("wmc_awaiting", None)
        wm = db.get_custom_watermark(wid)
        detail_text, markup = _detail_view(wm)
        await query.edit_message_text(
            f"✅ واترمارکِ متنیِ «{draft.get('name')}» ساخته شد (#{wid}).\n\n" + detail_text,
            parse_mode=ParseMode.HTML, reply_markup=markup,
        )
        return

    if data.startswith("wmc:view:"):
        wid = int(data.split(":")[2])
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        text, markup = _detail_view(wm)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data.startswith("wmc:preview:"):
        wid = int(data.split(":")[2])
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        await query.answer("در حالِ ساختِ پیش‌نمایش...")
        base = _sample_canvas()
        try:
            preview_bytes = await apply_named_watermark(context.bot, base, wm)
        except Exception as e:
            log.warning("ساختِ پیش‌نمایشِ واترمارکِ سفارشیِ #%s شکست خورد: %s", wid, e)
            await context.bot.send_message(chat_id=query.message.chat.id, text="❌ ساختِ پیش‌نمایش شکست خورد.")
            return
        kind_fa = "متنی" if wm["kind"] == "text" else "تصویری"
        await context.bot.send_photo(
            chat_id=query.message.chat.id,
            photo=preview_bytes,
            caption=f"🖼 پیش‌نمایشِ واترمارکِ سفارشی «{wm['name']}» ({kind_fa})",
        )
        return

    if data.startswith("wmc:delete:"):
        wid = int(data.split(":")[2])
        db.delete_custom_watermark(wid)
        text, markup, pm = root_content(uid)
        await query.edit_message_text(text, parse_mode=pm, reply_markup=markup)
        return

    if data.startswith("wmc:destpick:"):
        wid = int(data.split(":")[2])
        current = set(db.get_watermark_destinations(wid))
        rows = []
        for d in db.list_destinations(active_only=True):
            mark = "✅" if d["id"] in current else "▫️"
            rows.append([InlineKeyboardButton(f"{mark} {d['title'] or d['chat_id']}", callback_data=f"wmc:desttoggle:{wid}:{d['id']}")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"wmc:view:{wid}")])
        await query.edit_message_text("مقصدهایی که این واترمارک روشون اعمال بشه رو انتخاب/لغو کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("wmc:desttoggle:"):
        _, _, wid_s, did_s = data.split(":")
        wid, did = int(wid_s), int(did_s)
        current = set(db.get_watermark_destinations(wid))
        if did in current:
            current.discard(did)
        else:
            current.add(did)
        db.set_watermark_destinations(wid, list(current))
        await handle_callback(f"wmc:destpick:{wid}", query, context, uid)
        return

    for field, prompt in (
        ("transparency", "عددِ شفافیت (۰ تا ۱۰۰) رو بفرست:"),
        ("size", "درصدِ اندازه نسبت به عرضِ عکس (مثلا 30) رو بفرست:"),
        ("rotation", "زاویه‌ی چرخش (۰ تا ۳۶۰) رو بفرست:"),
    ):
        if data.startswith(f"wmc:set_{field}:"):
            wid = int(data.split(":")[2])
            context.user_data["wmc_awaiting"] = f"edit_{field}"
            context.user_data["wmc_edit_id"] = wid
            await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"wmc:view:{wid}")]]
            ))
            return

    if data.startswith("wmc:set_position:"):
        wid = int(data.split(":")[2])
        rows = [[InlineKeyboardButton(label, callback_data=f"wmc:posset:{wid}:{key}")] for key, label in _POSITIONS_FULL.items()]
        rows.append([InlineKeyboardButton("📍 X/Y دقیق", callback_data=f"wmc:posxy:{wid}")])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"wmc:view:{wid}")])
        await query.edit_message_text("موقعیت رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("wmc:posset:"):
        wid = int(data.split(":")[2])
        pos = data.split(":")[3]
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        db.update_custom_watermark(wid, position=pos, x_pos=None, y_pos=None)
        wm = db.get_custom_watermark(wid)
        text, markup = _detail_view(wm)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data.startswith("wmc:posxy:"):
        wid = int(data.split(":")[2])
        context.user_data["wmc_awaiting"] = "edit_xy"
        context.user_data["wmc_edit_id"] = wid
        await query.edit_message_text(
            "مختصاتِ X و Y رو با فاصله بفرست (مثلا: 50 100):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"wmc:view:{wid}")]]),
        )
        return

    if data.startswith("wmc:toggle_album_all:"):
        wid = int(data.split(":")[2])
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        db.update_custom_watermark(wid, album_all=0 if wm["album_all"] else 1)
        wm = db.get_custom_watermark(wid)
        text, markup = _detail_view(wm)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data.startswith("wmc:toggle_tiled:"):
        wid = int(data.split(":")[2])
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        db.update_custom_watermark(wid, tiled=0 if wm["tiled"] else 1)
        wm = db.get_custom_watermark(wid)
        text, markup = _detail_view(wm)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data.startswith("wmc:toggle_gradient:"):
        wid = int(data.split(":")[2])
        wm = db.get_custom_watermark(wid)
        if not wm:
            await query.answer("پیدا نشد.", show_alert=True)
            return
        db.update_custom_watermark(wid, color_mode="single" if wm["color_mode"] == "gradient" else "gradient")
        wm = db.get_custom_watermark(wid)
        text, markup = _detail_view(wm)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    if data.startswith("wmc:set_color_a:") or data.startswith("wmc:set_color_b:"):
        field = "color_a" if data.startswith("wmc:set_color_a:") else "color_b"
        wid = int(data.split(":")[2])
        context.user_data["wmc_awaiting"] = f"edit_{field}"
        context.user_data["wmc_edit_id"] = wid
        await query.edit_message_text(
            "کدِ رنگ رو به‌صورتِ هگز بفرست (مثلا #FF0000 یا FF0000):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"wmc:view:{wid}")]]),
        )
        return

    await query.answer()


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get("wmc_awaiting")
    if not awaiting:
        return False
    text = (update.message.text or "").strip()

    if awaiting == "new_name":
        draft = context.user_data.get("wmc_new", {})
        draft["name"] = text[:64]
        if draft.get("kind") == "text":
            context.user_data["wmc_awaiting"] = "new_text_body"
            await update.message.reply_text("متنِ واترمارک رو بفرست:")
        else:
            context.user_data["wmc_awaiting"] = "new_image_upload"
            await update.message.reply_text(
                "حالا لوگو/تصویرِ واترمارک رو بفرست.\n"
                "⚠️ اگه تصویرت پس‌زمینه‌ی شفاف (PNG بدونِ بکگراند) داره، حتماً به‌صورتِ "
                "«فایل» بفرست (📎 → Document / گزینه‌ی «ارسال بدون فشرده‌سازی»)، نه "
                "به‌صورتِ عکسِ معمولی؛ چون تلگرام عکسِ معمولی رو فشرده و به JPEG "
                "تبدیل می‌کنه و شفافیتش از بین می‌ره (پشتش پرِ رنگِ سفید/مشکی می‌شه)."
            )
        return True

    if awaiting == "new_text_body":
        draft = context.user_data.get("wmc_new", {})
        draft["text"] = text[:200]
        context.user_data["wmc_new"] = draft
        context.user_data["wmc_awaiting"] = None
        await update.message.reply_text(
            "این متن یک‌بار توی یک گوشه/موقعیتِ مشخص چاپ بشه، یا به‌صورتِ کاشی‌شده و "
            "محو رویِ کلِ عکس (پس‌زمینه‌ای، مثلِ واترمارکِ سایت‌های استوک) پخش بشه؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 یک‌بار در یک نقطه", callback_data="wmc:new_text_mode:single")],
                [InlineKeyboardButton("🧱 کاشی‌شده روی کلِ عکس", callback_data="wmc:new_text_mode:tiled")],
            ]),
        )
        return True

    if awaiting.startswith("edit_"):
        wid = context.user_data.get("wmc_edit_id")
        field = awaiting[len("edit_"):]
        if not wid:
            context.user_data.pop("wmc_awaiting", None)
            return True
        if field == "xy":
            parts = text.split()
            if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
                await update.message.reply_text("❗️ فرمت درست نیست. مثال: 50 100")
                return True
            db.update_custom_watermark(wid, x_pos=int(parts[0]), y_pos=int(parts[1]))
        elif field in ("color_a", "color_b"):
            hexval = text.strip().lstrip("#").upper()
            if len(hexval) != 6 or not all(c in "0123456789ABCDEF" for c in hexval):
                await update.message.reply_text("❗️ کدِ رنگ نامعتبره. مثال: #FF0000")
                return True
            db.update_custom_watermark(wid, **{field: f"#{hexval}"})
        else:
            if not text.isdigit():
                await update.message.reply_text("❗️ فقط عدد بفرست.")
                return True
            val = int(text)
            col = {"transparency": "transparency", "size": "size_pct", "rotation": "rotation"}[field]
            if field == "transparency":
                val = max(0, min(100, val))
            elif field == "rotation":
                val = val % 360
            elif field == "size":
                # بدونِ این کلمپ، ورودیِ 0 باعثِ resize به عرضِ صفر (کرشِ PIL) و
                # ورودیِ مثلاً 5000 باعثِ ساختِ یک تصویرِ غول‌پیکر و مصرفِ رَمِ
                # کنترل‌نشده می‌شد.
                val = max(1, min(200, val))
            db.update_custom_watermark(wid, **{col: val})
        context.user_data.pop("wmc_awaiting", None)
        context.user_data.pop("wmc_edit_id", None)
        await update.message.reply_text("✅ به‌روزرسانی شد.")
        return True

    return False


async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("wmc_awaiting") != "new_image_upload":
        return False
    uid = update.effective_user.id if update.effective_user else None
    msg = update.message

    # ⚠️ اگه به‌صورتِ «فایل» (Document) بفرسته، بایتِ خامِ عکس دست‌نخورده و
    # شفافیتِ PNG سالم می‌مونه؛ اگه به‌صورتِ «عکسِ» معمولیِ تلگرام (msg.photo)
    # بفرسته، تلگرام خودش فشرده و به JPEG تبدیلش می‌کنه و پس‌زمینه‌ی شفاف از
    # بین می‌ره (پشتش پر می‌شه). پس اولویت با Document ـه، و فقط اگه Document
    # نبود/عکسِ غیرِتصویری بود، به photo برمی‌گردیم.
    file_id = None
    if msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id = msg.document.file_id
    elif msg.photo:
        file_id = msg.photo[-1].file_id
    else:
        return False

    draft = context.user_data.get("wmc_new", {})
    owner = _owner_of(uid)
    wid = db.create_custom_watermark(
        owner, draft.get("name", "واترمارک"), kind="image", image_file_id=file_id,
    )
    context.user_data.pop("wmc_new", None)
    context.user_data.pop("wmc_awaiting", None)
    await msg.reply_text(f"✅ واترمارکِ تصویریِ «{draft.get('name')}» ساخته شد (#{wid}).")
    return True
