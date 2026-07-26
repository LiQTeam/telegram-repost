"""
حذف واترمارک با مدل LaMa (Large Mask Inpainting with Fourier Convolutions)
با fallback به OpenCV در صورت عدم وجود مدل
با قابلیت بارگذاری TorchScript و پردازش روی CPU
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from PIL import Image

from .config import LAMA_MODEL_PATH

log = logging.getLogger("repost_bot.lama_model")

_loaded_model = None
_model_loaded = False
_torch_threads_configured = False


def _configure_torch_threads(torch_module) -> None:
    """محدودسازیِ صریحِ تعدادِ تردهای داخلیِ torch (علاوه بر envِ
    OMP_NUM_THREADS/... که توی main.py ست می‌شه) - یک‌بار در طولِ عمرِ
    پروسه. برای جلوگیری از باقی‌موندنِ تردهای داخلیِ torch بعد از SIGTERM
    که باعثِ timeoutِ ۹۰ثانیه‌ایِ systemd موقعِ ری‌استارت/استاپ می‌شد."""
    global _torch_threads_configured
    if _torch_threads_configured:
        return
    try:
        torch_module.set_num_threads(1)
    except Exception:
        pass
    try:
        torch_module.set_num_interop_threads(1)
    except Exception:
        # set_num_interop_threads فقط یک‌بار قبل از هر پردازشِ موازی قابلِ
        # صدا زدنه؛ اگه قبلاً (مثلاً توسطِ sr_model.py) صدا زده شده باشه،
        # این‌جا RuntimeError می‌ده که کاملاً بی‌ضرره.
        pass
    _torch_threads_configured = True


def engine_status() -> str:
    """وضعیت موتور LaMa"""
    if LAMA_MODEL_PATH.exists():
        return "🟢 مدل LaMa موجود است (نسخه TorchScript)"
    return "⚪️ مدل LaMa نصب نشده است (fallback: OpenCV)"


def inpaint_boxes_sync(
    pil_img: Image.Image,
    boxes: list[tuple[int, int, int, int]]
) -> Optional[Image.Image]:
    """
    ترمیم باکس‌های مشخص‌شده با LaMa

    در صورت عدم دسترسی به LaMa، از OpenCV استفاده می‌کند.

    Args:
        pil_img: تصویر PIL
        boxes: لیست باکس‌ها به فرمت (x0, y0, x1, y1)

    Returns:
        تصویر ترمیم‌شده یا None در صورت خطا
    """
    try:
        import cv2
        cv2.setNumThreads(1)  # همون دلیلِ محدودسازیِ تردهای torch؛ نگاه کن به _configure_torch_threads
    except ImportError:
        log.warning("OpenCV نصب نیست، ترمیم ممکن نیست.")
        return None

    try:
        img_array = np.array(pil_img.convert("RGB"))
        mask = np.zeros((pil_img.height, pil_img.width), dtype=np.uint8)

        # ساخت ماسک برای تمام باکس‌ها با حاشیه
        for x0, y0, x1, y1 in boxes:
            # حاشیه برای ترمیم بهتر
            pad_x = max(5, int((x1 - x0) * 0.1))
            pad_y = max(5, int((y1 - y0) * 0.1))
            x0 = max(0, x0 - pad_x)
            y0 = max(0, y0 - pad_y)
            x1 = min(pil_img.width, x1 + pad_x)
            y1 = min(pil_img.height, y1 + pad_y)
            cv2.rectangle(mask, (x0, y0), (x1, y1), 255, -1)

        # اگر LaMa در دسترس است از آن استفاده کن
        if LAMA_MODEL_PATH.exists():
            try:
                result = _inpaint_with_lama(img_array, mask)
                if result is not None:
                    log.debug("ترمیم با LaMa انجام شد")
                    return result
            except Exception as e:
                log.warning("LaMa خطا داد، fallback به OpenCV: %s", e)

        # Fallback: OpenCV inpaint
        log.debug("استفاده از OpenCV inpaint برای ترمیم")
        result = cv2.inpaint(img_array, mask, 3, cv2.INPAINT_TELEA)
        return Image.fromarray(result)

    except Exception as e:
        log.warning("ترمیم ناموفق: %s", e)
        return None


def _inpaint_with_lama(img_array: np.ndarray, mask: np.ndarray) -> Optional[Image.Image]:
    """
    ترمیم با LaMa (در صورت وجود مدل TorchScript)
    """
    global _loaded_model, _model_loaded

    try:
        import torch
    except ImportError:
        log.debug("torch نصب نیست، LaMa در دسترس نیست.")
        return None

    _configure_torch_threads(torch)

    try:
        # لود مدل
        if not _model_loaded:
            if not LAMA_MODEL_PATH.exists():
                log.warning("فایل مدل LaMa وجود ندارد: %s", LAMA_MODEL_PATH)
                return None

            try:
                _loaded_model = torch.jit.load(str(LAMA_MODEL_PATH), map_location="cpu")
                _loaded_model.eval()
                _model_loaded = True
                log.info("مدل LaMa با موفقیت بارگذاری شد")
            except Exception as e:
                log.warning("خطا در لود LaMa: %s", e)
                return None

        if _loaded_model is None:
            return None

        # تبدیل به tensor
        img_tensor = torch.from_numpy(img_array).permute(2, 0, 1).float() / 255.0
        mask_tensor = torch.from_numpy(mask).float() / 255.0

        # پردازش با LaMa
        # ⚠️ باگِ مهم: img_tensor بعدِ permute شکلش (3, H, W)ه و با یک unsqueeze(0)
        # می‌شه (1, 3, H, W) - چهاربعدی. ولی mask (که از اول تک‌کاناله و شکلش
        # فقط (H, W)ه) با همون یک unsqueeze(0) فقط می‌شه (1, H, W) - سه‌بعدی؛
        # بعدِ کانال (که مدلِ LaMa برای ماسک هم انتظار داره، یعنی (1, 1, H, W))
        # اصلاً اضافه نمی‌شد. نتیجه دقیقاً همون خطایی بود که توی لاگ می‌دیدیم:
        # "Tensors must have same number of dimensions: got 4 and 3" - و چون
        # این تابع همیشه با except گسترده قورت می‌شد، LaMa هیچ‌وقت واقعاً کار
        # نمی‌کرد و همیشه (بی‌صدا) به OpenCV سقوط می‌کرد. حالا با unsqueeze
        # دوم، بعدِ کانالِ ماسک هم اضافه می‌شه.
        with torch.no_grad():
            result = _loaded_model(img_tensor.unsqueeze(0), mask_tensor.unsqueeze(0).unsqueeze(0))

        # تبدیل به تصویر
        result = result.squeeze(0).permute(1, 2, 0).clamp(0, 1).numpy() * 255
        result = result.astype(np.uint8)

        return Image.fromarray(result)

    except Exception as e:
        log.warning("ترمیم با LaMa ناموفق: %s", e)
        return None


def load_model() -> bool:
    """
    پیش‌لود مدل LaMa (اختیاری - برای کاهش زمان اولین پردازش)

    Returns:
        True در صورت بارگذاری موفق
    """
    global _loaded_model, _model_loaded

    if _model_loaded:
        return True

    if not LAMA_MODEL_PATH.exists():
        log.info("فایل مدل LaMa وجود ندارد.")
        return False

    try:
        import torch
        _configure_torch_threads(torch)
        _loaded_model = torch.jit.load(str(LAMA_MODEL_PATH), map_location="cpu")
        _loaded_model.eval()
        _model_loaded = True
        log.info("مدل LaMa پیش‌لود شد")
        return True
    except Exception as e:
        log.warning("پیش‌لود LaMa ناموفق: %s", e)
        return False