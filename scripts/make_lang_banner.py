#!/usr/bin/env python3
"""
Generate localized hero banners (assets/banner.<lang>.png) that match the
project's dark + green→blue glow aesthetic.

The rich English/Persian banners are supplied artwork; this builds clean,
brand-consistent banners for other languages from scratch with Pillow:
a deep dark background with aurora glow, the "Messrs LiQ" wordmark with a
gradient + glow, a localized tagline, and a row of stat chips.

Usage:  python3 scripts/make_lang_banner.py ru zh
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_TITLE = ROOT / "fonts" / "Vazirmatn-Bold.ttf"          # Latin wordmark (brand-consistent)
FONT_CYR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")  # Cyrillic
FONT_CJK = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")          # Chinese

W, H = 1536, 660
BG_TOP = (7, 11, 18)
BG_BOTTOM = (11, 18, 32)
GRAD_TOP = (34, 230, 160)     # spring green
GRAD_BOTTOM = (56, 160, 255)  # azure blue
CYAN = (64, 224, 255)
SUB = (198, 214, 234)
CHIP_TXT = (222, 232, 246)

LANGS = {
    "ru": {
        "font": FONT_CYR,
        "tagline": "Умный бот репостинга для Telegram",
        "kicker": "Продвинуто · Умно · Автоматически",
        "chips": [("СКОРОСТЬ", "Высокая"), ("НАДЁЖНОСТЬ", "Стабильно"),
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


def text_size(draw, text, fnt):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l, b - t, l, t


def gradient_text(base: Image.Image, text: str, fnt, cx: int, y: int):
    """Draw center-anchored gradient text with an outer glow at vertical y."""
    tmp = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(tmp)
    tw, th, lx, ty = text_size(d, text, fnt)
    x = cx - tw // 2 - lx
    d.text((x, y - ty), text, font=fnt, fill=255)
    grad = vgrad(base.size, GRAD_TOP, GRAD_BOTTOM).convert("RGBA")
    grad.putalpha(tmp)
    glow = grad.filter(ImageFilter.GaussianBlur(22))
    base.alpha_composite(glow)
    base.alpha_composite(grad)
    return th


def build(lang: str) -> Path:
    cfg = LANGS[lang]
    img = vgrad((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")

    # aurora glow blobs
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-200, 120, 460, 760), fill=(34, 230, 160, 60))
    gd.ellipse((W - 500, -260, W + 220, 360), fill=(56, 160, 255, 60))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(140)))

    draw = ImageDraw.Draw(img)
    cx = W // 2

    # code-bracket motif
    f_code = font(FONT_TITLE, 46)
    cw, ch, cl, ct = text_size(draw, "</>", f_code)
    draw.text((cx - cw // 2 - cl, 42 - ct), "</>", font=f_code, fill=CYAN)

    # "Messrs" kicker over the wordmark
    f_small = font(FONT_TITLE, 52)
    sw, sh, sl, st = text_size(draw, "Messrs", f_small)
    draw.text((cx - sw // 2 - sl, 104 - st), "Messrs", font=f_small, fill=SUB)

    # "{ LiQ }" big gradient wordmark
    f_big = font(FONT_TITLE, 170)
    gradient_text(img, "{ LiQ }", f_big, cx, 170)
    draw = ImageDraw.Draw(img)

    # tagline (localized)
    f_tag = font(cfg["font"], 44)
    tw, th, tl, tt = text_size(draw, cfg["tagline"], f_tag)
    draw.text((cx - tw // 2 - tl, 372 - tt), cfg["tagline"], font=f_tag, fill=SUB)

    # gradient underline
    lw = 380
    ug = vgrad((lw, 6), GRAD_TOP, GRAD_BOTTOM).convert("RGBA")
    img.alpha_composite(ug, (cx - lw // 2, 442))
    draw = ImageDraw.Draw(img)

    # kicker line
    f_kick = font(cfg["font"], 34)
    kw, kh, kl, kt = text_size(draw, cfg["kicker"], f_kick)
    draw.text((cx - kw // 2 - kl, 470 - kt), cfg["kicker"], font=f_kick, fill=CYAN)

    # stat chips row
    chips = cfg["chips"]
    n = len(chips)
    gap = 26
    chip_w = (W - 2 * 90 - (n - 1) * gap) // n
    chip_h = 92
    y0 = 536
    f_ct = font(cfg["font"], 30)
    f_cs = font(cfg["font"], 22)
    x = 90
    for title, subtitle in chips:
        box = (x, y0, x + chip_w, y0 + chip_h)
        draw.rounded_rectangle(box, radius=16, fill=(255, 255, 255, 10),
                               outline=(90, 130, 190, 150), width=2)
        tw, th, tl, tt = text_size(draw, title, f_ct)
        draw.text((x + chip_w // 2 - tw // 2 - tl, y0 + 20 - tt), title, font=f_ct, fill=CHIP_TXT)
        sw, sh, sl, stt = text_size(draw, subtitle, f_cs)
        draw.text((x + chip_w // 2 - sw // 2 - sl, y0 + 56 - stt), subtitle, font=f_cs, fill=SUB)
        x += chip_w + gap

    out = ROOT / "assets" / f"banner.{lang}.png"
    img.convert("RGB").save(out, "PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes) {img.size}")
    return out


def main() -> None:
    langs = sys.argv[1:] or ["ru", "zh"]
    for lg in langs:
        if lg not in LANGS:
            print(f"skip unknown lang: {lg}")
            continue
        build(lg)


if __name__ == "__main__":
    main()
