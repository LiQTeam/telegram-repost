"""
بهبود کیفیت تصویر با مدل Real-ESRGAN (معماری SRVGGNetCompact)
با قابلیت اجرا روی CPU و بدون وابستگی به کتابخانه‌های سنگین
با fallback به روش‌های پایه و کش کردن مدل
"""
from __future__ import annotations

import io
import logging
import re
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

from .config import SR_MODEL_PATH

log = logging.getLogger("repost_bot.sr_model")

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
        # اگه قبلاً (مثلاً توسطِ lama_model.py) صدا زده شده باشه، این‌جا
        # RuntimeError می‌ده که کاملاً بی‌ضرره.
        pass
    _torch_threads_configured = True


def engine_status() -> str:
    """وضعیت موتور بهبود کیفیت"""
    if SR_MODEL_PATH.exists():
        return "🟢 مدل Real-ESRGAN موجود است"
    return "⚪️ مدل نصب نشده است (از روش‌های پایه استفاده می‌شود)"


def enhance_photo_sync(image_bytes: bytes) -> bytes:
    """
    بهبود کیفیت عکس با AI

    در صورت وجود مدل Real-ESRGAN از آن استفاده می‌کند،
    در غیر این صورت از روش‌های پایه (LANCZOS + UnsharpMask + کنتراست) استفاده می‌کند.

    Args:
        image_bytes: داده‌های تصویر

    Returns:
        داده‌های تصویر بهبودیافته
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # اگر عکس به اندازه کافی بزرگ است، بهبود نمی‌دهیم (بیشتر از 1000px)
        if img.width >= 1000 and img.height >= 1000:
            return image_bytes

        log.debug("بهبود کیفیت عکس (ابعاد: %sx%s)", img.width, img.height)

        # تلاش برای استفاده از Real-ESRGAN در صورت وجود
        if SR_MODEL_PATH.exists():
            try:
                enhanced = _enhance_with_realesrgan(img)
                if enhanced is not None:
                    log.debug("بهبود کیفیت با Real-ESRGAN انجام شد")
                    return enhanced
            except Exception as e:
                log.warning("Real-ESRGAN خطا داد، fallback به روش پایه: %s", e)

        # روش پایه: بزرگنمایی با LANCZOS + تیز کردن + کنتراست
        return _enhance_basic(img)

    except Exception as e:
        log.warning("بهبود کیفیت عکس ناموفق: %s", e)
        return image_bytes


def _enhance_basic(img: Image.Image) -> bytes:
    """
    روش پایه بهبود کیفیت: بزرگنمایی، تیز کردن، افزایش کنتراست
    """
    try:
        # بزرگنمایی تا حداکثر 1280px
        scale = min(1280 / max(img.width, img.height), 2.0)
        if scale > 1.0:
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # تیز کردن با UnsharpMask
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=0))

        # افزایش کمی کنتراست
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.05)

        # افزایش کمی شفافیت (Sharpness)
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.1)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=92)
        return out.getvalue()

    except Exception as e:
        log.warning("بهبود کیفیت با روش پایه ناموفق: %s", e)
        raise


def _build_srvgg(torch, num_conv: int):
    """معماریِ سبکِ Real-ESRGAN (SRVGGNetCompact) به‌صورتِ خوداتکا (بدونِ نیاز به
    basicsr/realesrgan). همون معماریِ رسمیه، پس وزن‌های استانداردِ دانلودی مستقیم
    روش لود می‌شن. num_conv از روی خودِ فایلِ وزن‌ها تشخیص داده می‌شه تا هم مدلِ
    عمومی (realesr-general-x4v3، با num_conv=32) و هم نسخه‌های دیگه کار کنن."""
    from torch import nn
    import torch.nn.functional as F

    class SRVGGNetCompact(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64,
                     num_conv=32, upscale=4):
            super().__init__()
            self.upscale = upscale
            self.body = nn.ModuleList()
            self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
            for _ in range(num_conv):
                self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
                self.body.append(nn.PReLU(num_parameters=num_feat))
            self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
            self.upsampler = nn.PixelShuffle(upscale)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            out = self.upsampler(out)
            # اتصالِ باقی‌مانده: تصویرِ بزرگ‌شده‌ی nearest به خروجی اضافه می‌شه
            base = F.interpolate(x, scale_factor=self.upscale, mode="nearest")
            return out + base

    return SRVGGNetCompact(num_conv=num_conv)


def _infer_num_conv(state: dict) -> int:
    """تعدادِ لایه‌های میانی رو از روی کلیدهای وزن (body.N.*) تشخیص می‌ده.
    ساختار: body.0=کانو، body.1=فعال‌ساز، سپس (کانو،فعال‌ساز)×n، و کانوی آخر در
    اندیسِ 2n+2. پس n = (بزرگ‌ترین‌اندیس - 2)//2."""
    idxs = [int(m.group(1)) for k in state
            if (m := re.match(r"body\.(\d+)\.", k))]
    if not idxs:
        return 32
    return max((max(idxs) - 2) // 2, 1)


def _load_sr_model(torch):
    """مدل رو با هر دو فرمت لود می‌کنه: اول TorchScript (سازگاری با نسخه‌ی قبلی)،
    و اگه نشد، فایلِ وزنِ استانداردِ رسمیِ Real-ESRGAN (state_dict) رو روی معماریِ
    داخلی سوار می‌کنه. خروجی مدلِ آماده‌ی eval یا None (اگه هیچ‌کدوم نشد)."""
    # ۱) تلاش برای TorchScript
    try:
        m = torch.jit.load(str(SR_MODEL_PATH), map_location="cpu")
        m.eval()
        log.info("مدل Real-ESRGAN (TorchScript) بارگذاری شد.")
        return m
    except Exception:
        pass  # فایلِ TorchScript نیست؛ به‌عنوانِ state_dict امتحان می‌کنیم

    # ۲) فایلِ وزنِ استاندارد (.pth) — امن‌ترین حالتِ لود، با fallback
    try:
        try:
            ckpt = torch.load(str(SR_MODEL_PATH), map_location="cpu", weights_only=True)
        except Exception:
            ckpt = torch.load(str(SR_MODEL_PATH), map_location="cpu")
        if isinstance(ckpt, dict):
            state = ckpt.get("params_ema") or ckpt.get("params") or ckpt
        else:
            state = ckpt
        model = _build_srvgg(torch, _infer_num_conv(state))
        model.load_state_dict(state, strict=True)
        model.eval()
        log.info("مدل Real-ESRGAN (state_dict استاندارد) بارگذاری شد.")
        return model
    except Exception as e:  # noqa: BLE001
        log.warning("لودِ فایلِ مدلِ Real-ESRGAN نشد: %s", e)
        return None


def _enhance_with_realesrgan(img: Image.Image) -> Optional[bytes]:
    """
    بهبود کیفیت با Real-ESRGAN (در صورت وجود مدل TorchScript)
    """
    global _loaded_model, _model_loaded

    try:
        import torch
    except ImportError:
        log.debug("torch نصب نیست، Real-ESRGAN در دسترس نیست.")
        return None

    _configure_torch_threads(torch)

    try:
        # لود مدل (یک‌بار، با کش). هم TorchScript و هم وزنِ استانداردِ رسمی قبوله.
        if not _model_loaded:
            _model_loaded = True  # چه موفق چه ناموفق، دیگه هر بار تلاش نمی‌کنیم
            if not SR_MODEL_PATH.exists():
                _loaded_model = None
                return None
            _loaded_model = _load_sr_model(torch)

        if _loaded_model is None:
            return None

        # تبدیل به tensor
        img_np = np.array(img).astype(np.float32) / 255.0
        if img_np.ndim != 3 or img_np.shape[2] != 3:
            return None

        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)

        # پردازش
        with torch.no_grad():
            output = _loaded_model(img_tensor)

        # تبدیل به تصویر
        output = output.squeeze(0).permute(1, 2, 0).clamp(0, 1).numpy() * 255
        output = output.astype(np.uint8)

        result_img = Image.fromarray(output)

        # محدود کردن به 1280px
        if max(result_img.width, result_img.height) > 1280:
            scale = 1280 / max(result_img.width, result_img.height)
            new_w = int(result_img.width * scale)
            new_h = int(result_img.height * scale)
            result_img = result_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        result_img.save(out, format="JPEG", quality=95)
        return out.getvalue()

    except Exception as e:
        log.warning("خطا در Real-ESRGAN: %s", e)
        return None