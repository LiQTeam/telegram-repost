"""
تشخیص و حذف خودکار واترمارک/لوگوی کانال مبدأ از روی عکس، قبل از اینکه واترمارک
خودمان روی عکس زده شود.
"""
from __future__ import annotations

import io
import logging
import threading

import numpy as np
from PIL import Image

from . import config, lama_model

log = logging.getLogger("repost_bot.ai_watermark")

_templates: list[tuple[str, np.ndarray]] | None = None
_templates_lock = threading.Lock()


def engines_status() -> dict:
    tmpl_count = len(_templates) if _templates is not None else len(_list_template_files())
    return {
        "templates": (f"🟢 {tmpl_count} الگو بارگذاری‌شده" if tmpl_count else "⚪️ هیچ الگویی داخل data/watermark_templates نیست"),
        "lama_inpaint": lama_model.engine_status(),
    }


def _list_template_files() -> list:
    try:
        return sorted(
            p for p in config.WATERMARK_TEMPLATES_DIR.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and p.is_file()
        )
    except Exception:
        return []


def _load_templates() -> None:
    global _templates
    if _templates is not None:
        return
    with _templates_lock:
        if _templates is not None:
            return
        try:
            import cv2

            loaded = []
            for path in _list_template_files():
                img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if img is None:
                    continue
                if img.ndim == 3 and img.shape[2] == 4:
                    alpha = img[:, :, 3]
                    ys, xs = np.where(alpha > 10)
                    if xs.size == 0 or ys.size == 0:
                        continue
                    x0, x1 = xs.min(), xs.max() + 1
                    y0, y1 = ys.min(), ys.max() + 1
                    cropped_bgr = img[y0:y1, x0:x1, :3]
                    cropped_alpha = alpha[y0:y1, x0:x1]
                    gray = cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
                    opaque_mean = int(gray[cropped_alpha > 10].mean())
                    gray[cropped_alpha <= 10] = opaque_mean
                else:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
                loaded.append((path.name, gray))
            _templates = loaded
            if loaded:
                log.info("تعداد %d الگوی واترمارک از data/watermark_templates بارگذاری شد.", len(loaded))
        except Exception as e:
            log.warning("بارگذاری الگوهای واترمارک خطا داد: %s", e)
            _templates = []


def _detect_with_templates(pil_img: Image.Image) -> list[tuple[int, int, int, int]]:
    _load_templates()
    if not _templates:
        return []
    try:
        import cv2

        img_gray = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        h, w = img_gray.shape
        boxes = []
        for name, tmpl in _templates:
            th, tw = tmpl.shape
            best = None
            for scale in (0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0):
                rw, rh = int(tw * scale), int(th * scale)
                if rw < 8 or rh < 8 or rw > w or rh > h:
                    continue
                resized = cv2.resize(tmpl, (rw, rh), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(img_gray, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= config.TEMPLATE_MATCH_THRESHOLD and (best is None or max_val > best[0]):
                    x0, y0 = max_loc
                    best = (max_val, x0, y0, x0 + rw, y0 + rh)
            if best is not None:
                score, x0, y0, x1, y1 = best
                log.info("الگوی '%s' با امتیاز %.2f روی عکس تشخیص داده شد.", name, score)
                boxes.append((x0, y0, x1, y1))
        return boxes
    except Exception as e:
        log.warning("تشخیص با template matching خطا داد: %s", e)
        return []


def _detect_with_heuristic(pil_img: Image.Image) -> list[tuple[int, int, int, int]]:
    try:
        import cv2
    except Exception:
        return []

    try:
        arr = np.array(pil_img.convert("L"))
        h, w = arr.shape
        cw, ch = int(w * 0.30), int(h * 0.16)
        corners = {
            "top_left": (0, 0, cw, ch),
            "top_right": (w - cw, 0, w, ch),
            "bottom_left": (0, h - ch, cw, h),
            "bottom_right": (w - cw, h - ch, w, h),
        }
        edges = cv2.Canny(arr, 80, 160)
        boxes = []
        baseline = edges.mean()
        for x0, y0, x1, y1 in corners.values():
            region = edges[y0:y1, x0:x1]
            if region.size == 0:
                continue
            density = region.mean()
            if density > baseline * 2.2 and density > 8:
                boxes.append((x0, y0, x1, y1))
        return boxes
    except Exception as e:
        log.warning("تشخیص heuristic واترمارک خطا داد: %s", e)
        return []


def detect_watermark_boxes(pil_img: Image.Image) -> list[tuple[int, int, int, int]]:
    boxes = list(_detect_with_templates(pil_img))
    if boxes:
        return boxes
    return _detect_with_heuristic(pil_img)


def _mask_from_boxes(size: tuple[int, int], boxes: list[tuple[int, int, int, int]], pad_ratio: float = 0.15) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        bw, bh = x1 - x0, y1 - y0
        px, py = int(bw * pad_ratio), int(bh * pad_ratio)
        d.rectangle(
            [max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)], fill=255
        )
    return mask


def _inpaint(pil_img: Image.Image, boxes: list[tuple[int, int, int, int]], mask: Image.Image) -> Image.Image | None:
    return lama_model.inpaint_boxes_sync(pil_img, boxes)


def process_image_sync(image_bytes: bytes, *, remove_enabled: bool) -> bytes:
    if not remove_enabled:
        return image_bytes

    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        log.warning("عکس برای پردازش AI قابل خوندن نبود: %s", e)
        return image_bytes

    changed = False
    try:
        if remove_enabled:
            boxes = detect_watermark_boxes(pil_img)
            img_area = pil_img.width * pil_img.height
            box_area = sum(max(0, x1 - x0) * max(0, y1 - y0) for x0, y0, x1, y1 in boxes)
            if boxes and box_area > img_area * config.MAX_WATERMARK_AREA_RATIO:
                log.warning(
                    "ناحیه‌ی تشخیص‌داده‌شده (%.0f%% عکس) خیلی بزرگه؛ احتمالاً تشخیصِ "
                    "اشتباهه (false positive) - ترمیم رد شد تا عکس خراب نشه.",
                    100 * box_area / img_area,
                )
            elif boxes:
                mask = _mask_from_boxes(pil_img.size, boxes)
                result = _inpaint(pil_img, boxes, mask)
                if result is None:
                    log.warning(
                        "مدلِ LaMa در دسترس نیست یا خطا داد؛ ترمیمِ واترمارک رد شد "
                        "(برای فعال‌سازی، فایلِ big-lama.pt رو از طریق install.sh نصب کن)."
                    )
                else:
                    pil_img = result
                    changed = True
            else:
                log.info("هیچ واترمارکی روی این عکس تشخیص داده نشد؛ ترمیم رد شد.")

        if not changed:
            return image_bytes

        out = io.BytesIO()
        pil_img.save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as e:
        log.exception("پردازش AI عکس خطا داد؛ عکسِ اصلی بدون تغییر استفاده می‌شه: %s", e)
        return image_bytes