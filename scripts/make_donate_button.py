#!/usr/bin/env python3
"""
Generate assets/donate.png — a clean, transparent-background donate button.

Inspired by a simple pill-shaped "DONATE" button, rendered in a light color
scheme with a soft shadow so it reads on both light and dark GitHub themes.
Pure Pillow, reproducible: `python3 scripts/make_donate_button.py`.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_BOLD = ROOT / "fonts" / "Vazirmatn-Bold.ttf"
OUT = ROOT / "assets" / "donate.png"

# Render at 2x for crispness, then downscale.
SCALE = 2
W, H = 460 * SCALE, 132 * SCALE
PAD = 16 * SCALE
RADIUS = 40 * SCALE

# Light color scheme (transparent background around the pill).
FILL_TOP = (183, 148, 244)     # light lavender
FILL_BOTTOM = (146, 170, 248)  # light periwinkle
BORDER = (124, 92, 214)
TEXT = (255, 255, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_BOLD), size)
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


def main() -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    box = (PAD, PAD, W - PAD, H - PAD)

    # soft drop shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((box[0], box[1] + 6 * SCALE, box[2], box[3] + 6 * SCALE),
                         radius=RADIUS, fill=(80, 60, 140, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(9 * SCALE))
    img = Image.alpha_composite(img, shadow)

    # rounded mask for the gradient fill
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=RADIUS, fill=255)
    fill = vgrad((W, H), FILL_TOP, FILL_BOTTOM).convert("RGBA")
    fill.putalpha(mask)
    img = Image.alpha_composite(img, fill)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, radius=RADIUS, outline=BORDER, width=3 * SCALE)

    # DONATE text, centered
    label = "DONATE"
    font = load_font(46 * SCALE)
    l, t, r, b = draw.textbbox((0, 0), label, font=font)
    tw, th = r - l, b - t
    draw.text(((W - tw) // 2 - l, (H - th) // 2 - t), label, font=font, fill=TEXT)

    img = img.resize((W // SCALE, H // SCALE), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes) {img.size}")


if __name__ == "__main__":
    main()
