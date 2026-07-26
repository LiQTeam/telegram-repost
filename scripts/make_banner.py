#!/usr/bin/env python3
"""
Generate assets/banner.png — a dark gradient/glow text banner for the README.

Pure-Pillow, no network. Reproducible: run `python3 scripts/make_banner.py`.
The title text is rendered with a green→blue vertical gradient plus a soft
outer glow on a dark, subtly-vignetted background.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_BOLD = ROOT / "fonts" / "Vazirmatn-Bold.ttf"
FONT_MED = ROOT / "fonts" / "Vazirmatn-Medium.ttf"
OUT = ROOT / "assets" / "banner.png"

W, H = 1280, 420

# Palette (dark bg + green→blue accent, matching the in-bot watermark style)
BG_TOP = (13, 17, 23)      # GitHub-ish near-black
BG_BOTTOM = (16, 24, 32)
GRAD_TOP = (34, 230, 160)   # spring green
GRAD_BOTTOM = (56, 160, 255)  # azure blue


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def vertical_gradient(size, top, bottom) -> Image.Image:
    """A vertical top→bottom gradient as an RGB image."""
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (
            round(top[0] + (bottom[0] - top[0]) * t),
            round(top[1] + (bottom[1] - top[1]) * t),
            round(top[2] + (bottom[2] - top[2]) * t),
        )
    return base.resize((w, h))


def text_mask(text: str, font: ImageFont.FreeTypeFont, pad: int = 60) -> tuple[Image.Image, int, int]:
    """Render `text` to a grayscale alpha mask, tightly cropped with padding."""
    tmp = Image.new("L", (10, 10))
    d = ImageDraw.Draw(tmp)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    mask = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(mask).text((pad - l, pad - t), text, font=font, fill=255)
    return mask, tw, th


def main() -> None:
    # --- background: vertical gradient + soft radial vignette + accent glows ---
    img = vertical_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")

    # two blurred accent blobs (green left, blue right) for a subtle aurora
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-160, 120, 380, 620), fill=(34, 230, 160, 70))
    gd.ellipse((W - 420, -220, W + 180, 300), fill=(56, 160, 255, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img, glow)

    # --- title with gradient fill + outer glow ---
    title = "MR LiQ"
    tfont = load_font(FONT_BOLD, 190)
    mask, tw, th = text_mask(title, tfont)
    mw, mh = mask.size
    tx = (W - mw) // 2
    ty = (H - mh) // 2 - 34

    # glow layer: colored, heavily blurred copy of the mask
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad = vertical_gradient((mw, mh), GRAD_TOP, GRAD_BOTTOM).convert("RGBA")
    grad.putalpha(mask)
    glow_src = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_src.paste(grad, (tx, ty), grad)
    glow_layer = glow_src.filter(ImageFilter.GaussianBlur(26))
    img = Image.alpha_composite(img, glow_layer)
    img = Image.alpha_composite(img, glow_src)  # crisp gradient text on top

    draw = ImageDraw.Draw(img)

    # --- subtitle ---
    sub = "Smart Telegram Repost Bot"
    sfont = load_font(FONT_MED, 46)
    sl, st, sr, sb = draw.textbbox((0, 0), sub, font=sfont)
    sw = sr - sl
    draw.text(((W - sw) // 2 - sl, ty + mh - 46), sub, font=sfont, fill=(197, 214, 232, 255))

    # --- thin accent underline under the subtitle ---
    line_w = 360
    lx = (W - line_w) // 2
    ly = ty + mh + 30
    underline = Image.new("RGBA", (line_w, 6), (0, 0, 0, 0))
    ug = vertical_gradient((line_w, 6), GRAD_TOP, GRAD_BOTTOM).convert("RGBA")
    img.alpha_composite(ug, (lx, ly))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes) {img.size}")


if __name__ == "__main__":
    main()
