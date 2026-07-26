#!/usr/bin/env python3
"""
Generate localized hero banners (assets/banner.<lang>.png) that match the
project's dark + green→blue glow aesthetic.

The rich Persian/English banners are supplied artwork; this builds clean,
brand-consistent banners for other languages from scratch with Pillow:
a deep dark background with aurora glow and a faint dot-grid, the
"Messrs LiQ" wordmark with a gradient + glow, a localized tagline, and a
row of dark glass stat chips with high-contrast text.

Usage:  python3 scripts/make_lang_banner.py ru zh
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_TITLE = ROOT / "fonts" / "Vazirmatn-Bold.ttf"                        # Latin wordmark
FONT_CYR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")   # Cyrillic
FONT_CJK = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")           # Chinese

W, H = 1536, 740
BG_TOP = (7, 11, 18)
BG_BOTTOM = (12, 20, 34)
GRAD_TOP = (45, 233, 168)      # spring green
GRAD_BOTTOM = (58, 162, 255)   # azure blue
CYAN = (94, 232, 255)
SUB = (200, 216, 236)
CHIP_TITLE = (240, 247, 255)
CHIP_SUB = (150, 170, 198)
ACCENTS = [(45, 233, 168), (58, 162, 255), (94, 232, 255), (140, 130, 255), (58, 205, 220)]

LANGS = {
    "ru": {
        "font": FONT_CYR,
        "tagline": "Умный бот репостинга для Telegram",
        "kicker": "Продвинуто · Умно · Автоматически",
        "chips": [("СКОРОСТЬ", "Высокая"), ("НАДЁЖНО", "Стабильно"),
                  ("24/7", "Всегда онлайн"), ("УМНЫЙ", "На базе ИИ"),
                  ("БЕЗОПАСНО", "Приватность")],
    },
    "zh": {
        "font": FONT_CJK,
        "tagline": "智能 Telegram 转发机器人",
        "kicker": "先进 · 智能 · 自动化",
        "chips": [("快速", "高性能"), ("可靠", "稳定强大"),
                  ("24/7", "始终在线"), ("智能", "AI 驱动"),
                  ("安全", "注重隐私")],
    },
}


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def vgrad(size, top, bottom) -> Image.Image:
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return strip.resize((w, h))


def tsize(draw, text, fnt):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l, b - t, l, t


def center_text(draw, text, fnt, cx, y, fill):
    tw, th, l, t = tsize(draw, text, fnt)
    draw.text((cx - tw // 2 - l, y - t), text, font=fnt, fill=fill)
    return th


def gradient_wordmark(base, text, fnt, cx, y):
    tmp = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(tmp)
    tw, th, l, t = tsize(d, text, fnt)
    d.text((cx - tw // 2 - l, y - t), text, font=fnt, fill=255)
    grad = vgrad(base.size, GRAD_TOP, GRAD_BOTTOM).convert("RGBA")
    grad.putalpha(tmp)
    base.alpha_composite(grad.filter(ImageFilter.GaussianBlur(24)))  # glow
    base.alpha_composite(grad)                                       # crisp
    return th


def build(lang: str) -> Path:
    cfg = LANGS[lang]
    img = vgrad((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")

    # faint dot-grid texture
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for gy in range(40, H, 46):
        for gx in range(40, W, 46):
            gd.ellipse((gx, gy, gx + 2, gy + 2), fill=(120, 150, 190, 22))
    img = Image.alpha_composite(img, grid)

    # aurora glow blobs
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(glow)
    bd.ellipse((-220, 120, 480, 820), fill=(45, 233, 168, 55))
    bd.ellipse((W - 520, -280, W + 240, 400), fill=(58, 162, 255, 55))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(150)))

    draw = ImageDraw.Draw(img)
    cx = W // 2

    center_text(draw, "</>", font(FONT_TITLE, 48), cx, 46, CYAN)
    center_text(draw, "Messrs", font(FONT_TITLE, 54), cx, 112, SUB)
    gradient_wordmark(img, "{ LiQ }", font(FONT_TITLE, 176), cx, 182)
    draw = ImageDraw.Draw(img)

    # tagline (well below the wordmark to avoid overlap)
    center_text(draw, cfg["tagline"], font(cfg["font"], 46), cx, 430, SUB)

    # gradient underline
    lw = 400
    img.alpha_composite(vgrad((lw, 6), GRAD_TOP, GRAD_BOTTOM).convert("RGBA"), (cx - lw // 2, 502))
    draw = ImageDraw.Draw(img)

    center_text(draw, cfg["kicker"], font(cfg["font"], 34), cx, 534, CYAN)

    # stat chips — dark glass panels with a colored accent dot + high-contrast text
    chips = cfg["chips"]
    n = len(chips)
    gap, chip_h, y0, side = 28, 108, 604, 96
    chip_w = (W - 2 * side - (n - 1) * gap) // n
    f_ct = font(cfg["font"], 32)
    f_cs = font(cfg["font"], 23)

    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    x = side
    boxes = []
    for i in range(n):
        box = (x, y0, x + chip_w, y0 + chip_h)
        boxes.append(box)
        pd.rounded_rectangle(box, radius=18, fill=(20, 30, 48, 210),
                             outline=(70, 100, 150, 160), width=2)
        x += chip_w + gap
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

    for i, (title, subtitle) in enumerate(chips):
        bx0, by0, bx1, by1 = boxes[i]
        mid = (bx0 + bx1) // 2
        acc = ACCENTS[i % len(ACCENTS)]
        draw.ellipse((mid - 5, by0 + 16, mid + 5, by0 + 26), fill=acc)  # accent dot
        center_text(draw, title, f_ct, mid, by0 + 40, CHIP_TITLE)
        center_text(draw, subtitle, f_cs, mid, by0 + 78, CHIP_SUB)

    out = ROOT / "assets" / f"banner.{lang}.png"
    img.convert("RGB").save(out, "PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes) {img.size}")
    return out


def main() -> None:
    for lg in (sys.argv[1:] or ["ru", "zh"]):
        if lg in LANGS:
            build(lg)
        else:
            print(f"skip unknown lang: {lg}")


if __name__ == "__main__":
    main()
