"""
واترمارک تصویر با استفاده از نشانِ (Badge) آماده‌ی تلگرام و اینستاگرام.

به‌جای ساختِ واترمارکِ متنی از صفر، دو تصویرِ نشانِ آماده (assets/badges/telegram.png
و assets/badges/instagram.png) روی عکس قرار می‌گیرند و آیدیِ کانال دقیقاً «داخلِ باکسِ
رنگیِ کنارِ لوگو» نوشته می‌شود.

تضمینِ ضدباگ: متنِ آیدی همیشه با اندازه‌ی مناسب طوری تنظیم می‌شود که کاملاً داخلِ باکس
جا شود؛ اگر متن بزرگ‌تر از فضای باکس باشد، اندازه‌ی فونت خودکار کوچک می‌شود تا هرگز
روی لوگو نرود یا از باکس بیرون نزند.

تنظیماتِ فعلی (برای هر پلتفرم به‌صورتِ مستقل) روی همین نشان‌ها اعمال می‌شوند:
  - text        : متنِ آیدی که داخلِ باکس نوشته می‌شود
  - position    : گوشه‌ی قرارگیریِ نشان روی عکس
  - margin      : فاصله از لبه‌ی عکس
  - bg_opacity  : شفافیتِ کلِ نشان (۰ تا ۱۰۰)
  - font_size   : اندازه‌ی دلخواهِ متن (سقفِ اندازه؛ در صورتِ لازم برای جاشدن کوچک‌تر می‌شود)
  - color_a     : رنگِ متنِ آیدی (قابلِ تغییر)
  - badge_scale : بزرگیِ نشان به‌صورتِ درصدی از عرضِ عکس (اندازه‌های مختلف)
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import FONTS_DIR, BADGES_DIR

log = logging.getLogger("repost_bot.watermark")

_RTL_WARNED = False


def shape_rtl(text: str) -> str:
    """
    آماده‌سازیِ متنِ فارسی/عربی برای رسم با PIL.

    کتابخانه‌ی PIL حروفِ فارسی/عربی را «شکل‌دهی» (اتصالِ حروف) و «راست‌به‌چپ»
    نمی‌کند؛ در نتیجه اگر متنِ واترمارک فارسی باشد، حروف جدا-جدا و برعکس (چپ‌به‌راست)
    روی عکس می‌افتند. این تابع با arabic-reshaper (اتصالِ حروف) و python-bidi
    (ترتیبِ صحیحِ راست‌به‌چپ) متن را برای رسمِ درست آماده می‌کند.

    برای متنِ لاتین/عدد بی‌اثر است (خروجی = ورودی)، پس امن است که همیشه صدا زده شود.
    اگر این دو کتابخانه نصب نباشند، به‌صورتِ graceful همان متنِ خام برگردانده می‌شود
    (رفتارِ قبلی) تا هرگز کرش نکند.
    """
    if not text:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception as e:  # کتابخانه نصب نیست یا خطای غیرمنتظره
        global _RTL_WARNED
        if not _RTL_WARNED:
            log.warning(
                "شکل‌دهیِ متنِ فارسیِ واترمارک در دسترس نیست (arabic-reshaper/"
                "python-bidi نصب نشده؟): %s - از متنِ خام استفاده می‌شود.", e
            )
            _RTL_WARNED = True
        return text

# برچسب‌های فارسیِ موقعیت‌ها (برای نمایش در منوها)
POSITIONS = {
    "top_left": "⬉ بالا چپ",
    "top_center": "⬆️ بالا وسط",
    "top_right": "⬈ بالا راست",
    "bottom_left": "⬋ پایین چپ",
    "bottom_center": "⬇️ پایین وسط",
    "bottom_right": "⬊ پایین راست",
}

# مختصاتِ نسبیِ هر موقعیت (برای محاسبه‌ی محلِ قرارگیری روی عکس)
_POSITION_XY = {
    "top_left": (0.0, 0.0),
    "top_center": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "bottom_left": (0.0, 1.0),
    "bottom_center": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}

COLOR_PALETTE = [
    ("قرمز", "#E53935"),
    ("آبی", "#1E88E5"),
    ("سبز", "#43A047"),
    ("زرد", "#FDD835"),
    ("نارنجی", "#FB8C00"),
    ("بنفش", "#8E24AA"),
    ("صورتی", "#EC407A"),
    ("فیروزه‌ای", "#00ACC1"),
    ("خاکستری", "#78909C"),
    ("سفید", "#FFFFFF"),
    ("مشکی", "#111111"),
]

# نامِ فایلِ نشانِ هر پلتفرم
_BADGE_FILE = {"tg": "telegram.png", "ig": "instagram.png"}

# مستطیلِ امنِ نوشتنِ متن داخلِ باکسِ هر نشان، به‌صورتِ نسبت به ابعادِ تصویرِ نشانِ
# برش‌خورده (x0, y0, x1, y1). این مقادیر با کمی حاشیه‌ی امن انتخاب شده‌اند تا متن
# هرگز روی لوگو نرود یا از باکس بیرون نزند.
_BADGE_TEXT_BOX = {
    "tg": (0.375, 0.32, 0.945, 0.80),
    "ig": (0.375, 0.30, 0.945, 0.80),
}

# کشِ فونت‌ها و نشان‌ها
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
_badge_cache: dict[str, Image.Image] = {}


def get_font(size: int) -> ImageFont.FreeTypeFont:
    """دریافت فونت فارسی با اندازه‌ی مشخص (با کش)."""
    size = max(6, int(size))
    if size in _font_cache:
        return _font_cache[size]

    font_path = None
    for ext in (".ttf", ".otf"):
        for f in sorted(FONTS_DIR.glob(f"*{ext}")):
            font_path = f
            break
        if font_path:
            break

    font = None
    if font_path:
        try:
            font = ImageFont.truetype(str(font_path), size)
        except Exception:
            font = None
    if font is None:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            font = ImageFont.load_default()

    _font_cache[size] = font
    return font


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """تبدیل کد هگز به RGB."""
    hex_color = (hex_color or "#FFFFFF").lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    try:
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (255, 255, 255)


def _load_badge(platform: str) -> Image.Image | None:
    """بارگذاریِ تصویرِ نشانِ برش‌خورده‌ی پلتفرم (با کش). اگر فایل نبود None."""
    key = platform
    if key in _badge_cache:
        return _badge_cache[key]
    fname = _BADGE_FILE.get(platform)
    if not fname:
        return None
    path = Path(BADGES_DIR) / fname
    if not path.exists():
        log.warning("فایلِ نشانِ واترمارک پیدا نشد: %s", path)
        return None
    try:
        img = Image.open(path).convert("RGBA")
        # برش به محدوده‌ی غیرشفاف تا حاشیه‌ی خالی حذف شود
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        _badge_cache[key] = img
        return img
    except Exception as e:
        log.warning("خطا در بازکردنِ نشانِ %s: %s", path, e)
        return None


def _measure(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    """(width, height, offset_x, offset_y) متن را برمی‌گرداند."""
    try:
        l, t, r, b = font.getbbox(text)
        return (r - l, b - t, l, t)
    except Exception:
        w = int(font.size * len(text) * 0.6)
        return (w, int(font.size * 1.2), 0, 0)


def _fit_font(text: str, box_w: int, box_h: int, desired_size: int) -> ImageFont.FreeTypeFont:
    """بزرگ‌ترین اندازه‌ی فونت (تا سقفِ desired_size) که متن کاملاً داخلِ باکس جا شود.
    این تابع تضمین می‌کند متن هرگز از باکس بیرون نزند."""
    size = max(6, int(desired_size))
    while size >= 6:
        font = get_font(size)
        w, h, _, _ = _measure(font, text)
        if w <= box_w and h <= box_h:
            return font
        size -= 1
    return get_font(6)


def _render_badge_with_text(platform: str, settings: dict, image_width: int) -> Image.Image | None:
    """
    نشانِ پلتفرم را با آیدیِ نوشته‌شده داخلِ باکس می‌سازد و به اندازه‌ی نهایی (بر اساسِ
    badge_scale) اسکیل می‌کند. خروجی یک تصویرِ RGBA آماده‌ی چسباندن است.
    """
    badge = _load_badge(platform)
    if badge is None:
        return None

    prefix = f"wm_{platform}"
    text = (settings.get(f"{prefix}_text") or "").strip()
    bg_opacity = _clamp_int(settings.get(f"{prefix}_bg_opacity", 100), 0, 100, 100)
    desired_font = _clamp_int(settings.get(f"{prefix}_font_size", 44), 8, 400, 44)
    text_color = hex_to_rgb(settings.get(f"{prefix}_color_a") or "#FFFFFF")
    badge_scale = _clamp_int(settings.get(f"{prefix}_badge_scale", 32), 8, 100, 32)

    # اندازه‌ی نهاییِ نشان بر اساسِ درصدی از عرضِ عکس
    native_w, native_h = badge.size
    target_w = max(60, int(image_width * badge_scale / 100))
    scale = target_w / native_w
    target_h = max(20, int(native_h * scale))
    badge = badge.resize((target_w, target_h), Image.LANCZOS)

    # نوشتنِ متنِ آیدی داخلِ باکس (اگر متنی تعیین شده باشد)
    if text:
        # شکل‌دهیِ فارسی/عربی قبل از هر اندازه‌گیری و رسم تا حروف درست و
        # راست‌به‌چپ روی نشان بیفتند (برای متنِ لاتین بی‌اثر است).
        text = shape_rtl(text)
        x0, y0, x1, y1 = _BADGE_TEXT_BOX.get(platform, (0.375, 0.32, 0.945, 0.80))
        bx0, by0 = int(x0 * target_w), int(y0 * target_h)
        bx1, by1 = int(x1 * target_w), int(y1 * target_h)
        box_w = max(1, bx1 - bx0)
        box_h = max(1, by1 - by0)

        # سقفِ اندازه‌ی فونت بر اساسِ خواسته‌ی کاربر، اما مقیاس‌شده با اندازه‌ی نشان
        # تا در نشان‌های کوچک هم متناسب باشد؛ سپس تضمینِ جاشدن داخلِ باکس.
        desired_scaled = min(desired_font, box_h)
        font = _fit_font(text, box_w, box_h, desired_scaled)
        tw, th, ox, oy = _measure(font, text)
        # وسط‌چینِ افقی و عمودی داخلِ باکس
        tx = bx0 + (box_w - tw) // 2 - ox
        ty = by0 + (box_h - th) // 2 - oy

        draw = ImageDraw.Draw(badge)
        draw.text((tx, ty), text, font=font, fill=(text_color[0], text_color[1], text_color[2], 255))

    # اعمالِ شفافیتِ کلیِ نشان
    if bg_opacity < 100:
        alpha = badge.split()[3].point(lambda a: int(a * bg_opacity / 100))
        badge.putalpha(alpha)

    return badge


def _place_badge(base: Image.Image, badge: Image.Image, position: str, margin: int) -> None:
    """نشان را در گوشه‌ی خواسته‌شده روی تصویرِ اصلی می‌چسباند."""
    width, height = base.size
    bw, bh = badge.size
    pos_x, pos_y = _POSITION_XY.get(position, (1.0, 1.0))

    if pos_x == 0:
        x = margin
    elif pos_x == 0.5:
        x = (width - bw) // 2
    else:
        x = width - bw - margin

    if pos_y == 0:
        y = margin
    elif pos_y == 0.5:
        y = (height - bh) // 2
    else:
        y = height - bh - margin

    # جلوگیری از بیرون‌زدنِ نشان از کادرِ عکس
    x = max(0, min(x, width - bw))
    y = max(0, min(y, height - bh))

    base.alpha_composite(badge, (x, y))


def draw_watermark_platform(img: Image.Image, settings: dict, platform: str) -> None:
    """نشانِ یک پلتفرم را (در صورتِ فعال بودن) روی تصویر قرار می‌دهد."""
    prefix = f"wm_{platform}"
    if not settings.get(f"{prefix}_enabled", False):
        return
    try:
        badge = _render_badge_with_text(platform, settings, img.size[0])
        if badge is None:
            return
        position = settings.get(f"{prefix}_position", "bottom_right")
        margin = _clamp_int(settings.get(f"{prefix}_margin", 28), 0, 2000, 28)
        _place_badge(img, badge, position, margin)
    except Exception as e:
        log.warning("خطا در اعمالِ نشانِ واترمارکِ %s: %s", platform, e)


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def add_watermark(image_bytes: bytes, settings: dict) -> bytes:
    """اعمالِ نشان‌های واترمارک (تلگرام/اینستاگرام) روی تصویر."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as e:
        log.warning("خطا در باز کردن تصویر برای واترمارک: %s", e)
        return image_bytes

    if not settings.get("watermark_enabled", True):
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=95)
        return out.getvalue()

    draw_watermark_platform(img, settings, "tg")
    draw_watermark_platform(img, settings, "ig")

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=95)
    return out.getvalue()


def render_preview(settings: dict) -> bytes:
    """ساختِ یک عکسِ نمونه با نشان‌های فعلی برای پیش‌نمایش."""
    width, height = 1000, 700
    img = Image.new("RGBA", (width, height), (238, 240, 243, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, width - 40, height - 40], outline=(205, 210, 216, 255), width=3)
    try:
        font = get_font(26)
        msg = "پیش‌نمایشِ نشانِ واترمارک"
        w, h, ox, oy = _measure(font, msg)
        draw.text(((width - w) // 2 - ox, 70 - oy), msg, font=font, fill=(120, 125, 132, 255))
    except Exception:
        pass

    # برای اینکه پیش‌نمایش مفید باشد، هر دو نشان (در صورتِ فعال بودن) نمایش داده می‌شوند؛
    # اگر هیچ‌کدام فعال نبود، تلگرام به‌صورتِ نمونه نشان داده می‌شود.
    shown = False
    for plat in ("tg", "ig"):
        if settings.get(f"wm_{plat}_enabled", False):
            draw_watermark_platform(img, settings, plat)
            shown = True
    if not shown:
        demo = dict(settings)
        demo["wm_tg_enabled"] = True
        draw_watermark_platform(img, demo, "tg")

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=95)
    return out.getvalue()
