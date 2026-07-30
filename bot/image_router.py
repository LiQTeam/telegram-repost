"""
مسیریاب تولید تصویر (Image Generation Router)
با پشتیبانی از چند سرویس به‌صورت زنجیره‌ای (Failover Chain):

    اولویت ۱: Pollinations AI
    اولویت ۲: DeepAI
    اولویت ۳: Stable Horde

اگر سرویسِ با اولویت بالاتر با خطا / Timeout / Rate-Limit مواجه شود،
به‌صورت خودکار به سرویسِ بعدی سوییچ می‌شود. خروجیِ نهایی برای همه‌ی
سرویس‌ها یکسان‌سازی شده و همیشه `bytes` خام تصویر (PNG/JPEG) برگردانده
می‌شود؛ بنابراین بقیه‌ی بخش‌های ربات (واترمارک، ارسال به تلگرام و ...)
نیازی به تغییر ندارند.

مثال استفاده:

    from bot.image_router import ImageRouter

    router = ImageRouter()
    try:
        image_bytes = await router.generate_image("a cat sitting on the moon")
        if image_bytes:
            with open("out.png", "wb") as f:
                f.write(image_bytes)
    finally:
        await router.close()
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import urllib.parse
from typing import Optional

import httpx

from .config import (
    POLLINATIONS_API_KEY,
    DEEPAI_API_KEY,
    STABLEHORDE_API_KEY,
    IMAGE_GEN_TIMEOUT,
    IMAGE_GEN_MAX_RETRIES,
    STABLEHORDE_POLL_TIMEOUT,
    STABLEHORDE_POLL_INTERVAL,
)

log = logging.getLogger("repost_bot.image_router")

# ==================== آدرس‌های API ====================
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
DEEPAI_URL = "https://api.deepai.org/api/text2img"
STABLEHORDE_ASYNC_URL = "https://stablehorde.net/api/v2/generate/async"
STABLEHORDE_CHECK_URL = "https://stablehorde.net/api/v2/generate/check/{id}"
STABLEHORDE_STATUS_URL = "https://stablehorde.net/api/v2/generate/status/{id}"

# حداقل بایتِ یک پاسخِ معتبرِ تصویری (برای رد کردنِ پاسخ‌های خالی/خراب)
MIN_VALID_IMAGE_BYTES = 256


class ImageGenError(Exception):
    """خطای پایه برای تولید تصویر"""


class RetryableImageError(ImageGenError):
    """
    خطای موقتی که ارزشِ Retry (با Backoff) روی همان Provider را دارد:
    Timeout، خطاهای شبکه، Rate-Limit (429) و خطاهای سرور (5xx)
    """


class FatalImageError(ImageGenError):
    """
    خطای دائمی که تلاشِ مجدد روی همان Provider فایده‌ای ندارد
    (مثلاً کلید API نامعتبر یا درخواستِ نامعتبر - 4xx به‌جز 429)
    و باید بلافاصله به Provider بعدی سوییچ کرد.
    """


class ImageRouter:
    """
    مسیریاب تولید تصویر با Failover خودکار بین چند سرویس.
    ترتیب تلاش: Pollinations -> DeepAI -> Stable Horde
    """

    # نامِ Providerها به ترتیبِ اولویت (برای لاگ و گزارش)
    PROVIDER_ORDER = ("pollinations", "deepai", "stablehorde")

    def __init__(self, timeout: float = IMAGE_GEN_TIMEOUT, owner_user_id: "int | None" = None):
        self.timeout = timeout
        self.owner_user_id = owner_user_id
        self.session = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._last_error: Optional[str] = None
        self._errors_by_provider: dict[str, str] = {}

    # ==================================================================
    # ابزارهای عمومی
    # ==================================================================

    @staticmethod
    def _classify_http_status(status_code: int) -> None:
        """
        بر اساس status code تصمیم می‌گیرد که خطا موقتی است (قابل Retry)
        یا دائمی (باید فوراً سوییچ به Provider بعدی).
        در صورت لزوم Exception مناسب را raise می‌کند.
        """
        if status_code == 429:
            raise RetryableImageError("Rate limit شد (HTTP 429)")
        if status_code >= 500:
            raise RetryableImageError(f"خطای سرور (HTTP {status_code})")
        if status_code >= 400:
            raise FatalImageError(f"درخواست نامعتبر یا کلید نامعتبر (HTTP {status_code})")

    async def _download_bytes(self, url: str) -> bytes:
        """دانلودِ بایت‌های تصویر از یک URL (برای سرویس‌هایی که فقط لینک برمی‌گردانند)"""
        try:
            resp = await self.session.get(url, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise RetryableImageError(f"Timeout در دانلود تصویر: {e}") from e
        except httpx.HTTPError as e:
            raise RetryableImageError(f"خطای شبکه در دانلود تصویر: {e}") from e

        if resp.status_code != 200:
            self._classify_http_status(resp.status_code)

        content = resp.content
        if not content or len(content) < MIN_VALID_IMAGE_BYTES:
            raise RetryableImageError("پاسخِ دانلودشده خالی یا خیلی کوچک بود")
        return content

    # ==================================================================
    # Provider ۱: Pollinations AI
    # ==================================================================

    async def _call_pollinations(self, prompt: str, width: int, height: int, seed: Optional[int] = None) -> bytes:
        encoded_prompt = urllib.parse.quote(prompt, safe="")
        url = POLLINATIONS_URL.format(prompt=encoded_prompt)
        params = {
            "width": width,
            "height": height,
            "nologo": "true",
            "private": "true",
            "seed": seed if seed is not None else random.randint(0, 2_147_483_647),
        }
        headers = {}
        if POLLINATIONS_API_KEY:
            # Pollinations هم از هدر Authorization و هم از query param token پشتیبانی می‌کند؛
            # هر دو را برای سازگاری بیشتر ارسال می‌کنیم.
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"
            params["token"] = POLLINATIONS_API_KEY

        try:
            resp = await self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise RetryableImageError(f"Timeout (بیش از {self.timeout} ثانیه)") from e
        except httpx.HTTPError as e:
            raise RetryableImageError(f"خطای شبکه: {e}") from e

        if resp.status_code != 200:
            self._classify_http_status(resp.status_code)

        content_type = resp.headers.get("content-type", "")
        content = resp.content

        if "image" not in content_type and len(content) < MIN_VALID_IMAGE_BYTES:
            # گاهی Pollinations در صورت خطا یک پیامِ متنی/JSON برمی‌گرداند
            raise RetryableImageError(f"پاسخ نامعتبر (content-type={content_type})")

        if not content or len(content) < MIN_VALID_IMAGE_BYTES:
            raise RetryableImageError("پاسخِ Pollinations خالی یا خیلی کوچک بود")

        log.debug("Pollinations تصویر تولید کرد: %s بایت", len(content))
        return content

    # ==================================================================
    # Provider ۲: DeepAI
    # ==================================================================

    async def _call_deepai(self, prompt: str, width: int, height: int, **_kwargs) -> bytes:
        if not DEEPAI_API_KEY:
            raise FatalImageError("کلید DeepAI تنظیم نشده است")

        headers = {"api-key": DEEPAI_API_KEY}
        data = {"text": prompt}

        try:
            resp = await self.session.post(DEEPAI_URL, headers=headers, data=data, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise RetryableImageError(f"Timeout (بیش از {self.timeout} ثانیه)") from e
        except httpx.HTTPError as e:
            raise RetryableImageError(f"خطای شبکه: {e}") from e

        if resp.status_code != 200:
            self._classify_http_status(resp.status_code)

        try:
            payload = resp.json()
        except ValueError as e:
            raise RetryableImageError(f"پاسخ JSON نامعتبر: {e}") from e

        output_url = payload.get("output_url")
        if not output_url:
            err = payload.get("err") or payload.get("error") or "output_url در پاسخ موجود نیست"
            raise RetryableImageError(f"DeepAI خروجی معتبر برنگرداند: {err}")

        content = await self._download_bytes(output_url)
        log.debug("DeepAI تصویر تولید کرد: %s بایت", len(content))
        return content

    # ==================================================================
    # Provider ۳: Stable Horde
    # ==================================================================

    async def _stablehorde_submit(self, prompt: str, width: int, height: int) -> str:
        """ثبتِ درخواستِ تولیدِ تصویر در صفِ Stable Horde و برگرداندنِ شناسه‌ی Job"""
        if not STABLEHORDE_API_KEY:
            raise FatalImageError("کلید Stable Horde تنظیم نشده است")

        # ابعاد باید مضربی از ۶۴ باشند (محدودیتِ Stable Horde)
        safe_width = max(64, (width // 64) * 64) or 512
        safe_height = max(64, (height // 64) * 64) or 512

        headers = {
            "apikey": STABLEHORDE_API_KEY,
            "Content-Type": "application/json",
            "Client-Agent": "UploadGramBot:1.0:uploadgram",
        }
        payload = {
            "prompt": prompt,
            "params": {
                "width": safe_width,
                "height": safe_height,
                "steps": 25,
                "sampler_name": "k_euler",
                "n": 1,
                "cfg_scale": 7.5,
            },
            "nsfw": False,
            "censor_nsfw": True,
            "r2": True,
            "shared": False,
        }

        try:
            resp = await self.session.post(
                STABLEHORDE_ASYNC_URL, headers=headers, json=payload, timeout=self.timeout
            )
        except httpx.TimeoutException as e:
            raise RetryableImageError(f"Timeout در ثبت درخواست: {e}") from e
        except httpx.HTTPError as e:
            raise RetryableImageError(f"خطای شبکه در ثبت درخواست: {e}") from e

        if resp.status_code not in (200, 202):
            self._classify_http_status(resp.status_code)

        try:
            data = resp.json()
        except ValueError as e:
            raise RetryableImageError(f"پاسخ JSON نامعتبر هنگام ثبت درخواست: {e}") from e

        job_id = data.get("id")
        if not job_id:
            message = data.get("message", "شناسه‌ی Job برنگشت")
            raise RetryableImageError(f"Stable Horde درخواست را نپذیرفت: {message}")

        return job_id

    async def _stablehorde_poll(self, job_id: str) -> dict:
        """Poll کردنِ وضعیتِ Job تا زمانِ تکمیل یا رسیدن به Timeout کلی"""
        elapsed = 0.0
        while elapsed < STABLEHORDE_POLL_TIMEOUT:
            try:
                resp = await self.session.get(
                    STABLEHORDE_CHECK_URL.format(id=job_id), timeout=self.timeout
                )
            except httpx.TimeoutException as e:
                raise RetryableImageError(f"Timeout هنگام بررسیِ وضعیت: {e}") from e
            except httpx.HTTPError as e:
                raise RetryableImageError(f"خطای شبکه هنگام بررسیِ وضعیت: {e}") from e

            if resp.status_code != 200:
                self._classify_http_status(resp.status_code)

            try:
                status = resp.json()
            except ValueError as e:
                raise RetryableImageError(f"پاسخ JSON نامعتبر هنگام بررسیِ وضعیت: {e}") from e

            if status.get("faulted"):
                raise RetryableImageError("Job در Stable Horde با خطا مواجه شد (faulted)")

            if status.get("done"):
                try:
                    final_resp = await self.session.get(
                        STABLEHORDE_STATUS_URL.format(id=job_id), timeout=self.timeout
                    )
                except httpx.TimeoutException as e:
                    raise RetryableImageError(f"Timeout هنگام دریافت نتیجه‌ی نهایی: {e}") from e
                except httpx.HTTPError as e:
                    raise RetryableImageError(f"خطای شبکه هنگام دریافت نتیجه‌ی نهایی: {e}") from e

                if final_resp.status_code != 200:
                    self._classify_http_status(final_resp.status_code)

                try:
                    return final_resp.json()
                except ValueError as e:
                    raise RetryableImageError(f"پاسخ JSON نامعتبر در نتیجه‌ی نهایی: {e}") from e

            await asyncio.sleep(STABLEHORDE_POLL_INTERVAL)
            elapsed += STABLEHORDE_POLL_INTERVAL

        raise RetryableImageError(
            f"Stable Horde در بازه‌ی {STABLEHORDE_POLL_TIMEOUT} ثانیه‌ای نتیجه‌ای برنگرداند"
        )

    async def _call_stablehorde(self, prompt: str, width: int, height: int, **_kwargs) -> bytes:
        job_id = await self._stablehorde_submit(prompt, width, height)
        log.debug("Stable Horde Job ثبت شد: %s", job_id)
        final_status = await self._stablehorde_poll(job_id)

        generations = final_status.get("generations") or []
        if not generations:
            raise RetryableImageError("Stable Horde هیچ خروجی‌ای تولید نکرد")

        img_field = generations[0].get("img")
        if not img_field:
            raise RetryableImageError("فیلد تصویر در پاسخ Stable Horde خالی بود")

        # img_field می‌تواند یک URL (حالت r2=True) یا یک رشته‌ی base64 باشد
        if img_field.startswith("http://") or img_field.startswith("https://"):
            content = await self._download_bytes(img_field)
        else:
            b64_data = img_field
            if b64_data.startswith("data:") and "," in b64_data:
                # برخی نسخه‌ها ممکن است به‌صورت data URI (data:image/...;base64,....) برگردانند
                b64_data = b64_data.split(",", 1)[1]
            try:
                content = base64.b64decode(b64_data)
            except Exception as e:
                raise RetryableImageError(f"خطا در decode کردنِ base64: {e}") from e

        if not content or len(content) < MIN_VALID_IMAGE_BYTES:
            raise RetryableImageError("تصویرِ Stable Horde خالی یا خیلی کوچک بود")

        log.debug("Stable Horde تصویر تولید کرد: %s بایت", len(content))
        return content

    # ==================================================================
    # منطقِ Retry با Exponential Backoff (برای هر Provider جداگانه)
    # ==================================================================

    async def _run_with_retry(self, provider_name: str, coro_func, *args, **kwargs) -> Optional[bytes]:
        max_attempts = IMAGE_GEN_MAX_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            try:
                return await coro_func(*args, **kwargs)

            except FatalImageError as e:
                log.warning("خطای دائمی در %s: %s (بدون Retry، سوییچ به Provider بعدی)", provider_name, e)
                self._errors_by_provider[provider_name] = str(e)
                self._last_error = f"{provider_name}: {e}"
                return None

            except RetryableImageError as e:
                self._errors_by_provider[provider_name] = str(e)
                self._last_error = f"{provider_name}: {e}"
                if attempt < max_attempts:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0, 1)
                    log.warning(
                        "خطای موقت در %s (تلاش %s از %s): %s — تلاش مجدد بعد از %.1f ثانیه",
                        provider_name, attempt, max_attempts, e, backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    log.warning(
                        "%s پس از %s تلاش ناموفق بود: %s — سوییچ به Provider بعدی",
                        provider_name, max_attempts, e,
                    )
                    return None

            except Exception as e:
                # هر خطای پیش‌بینی‌نشده‌ی دیگر هم به‌عنوان خطای دائمی برای این Provider در نظر گرفته می‌شود
                log.exception("خطای غیرمنتظره در %s: %s", provider_name, e)
                self._errors_by_provider[provider_name] = str(e)
                self._last_error = f"{provider_name}: {e}"
                return None

        return None

    # ==================================================================
    # نقطه‌ی ورودیِ اصلی
    # ==================================================================

    async def generate_image(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
    ) -> Optional[bytes]:
        """
        تولیدِ تصویر با تلاشِ زنجیره‌ای روی چند Provider:
        Pollinations -> DeepAI -> Stable Horde

        در صورت موفقیت، بایت‌های خامِ تصویر (PNG/JPEG) برگردانده می‌شود.
        در صورت شکستِ هر سه سرویس، مقدار None برگردانده می‌شود و خطا لاگ می‌گردد.
        """
        if not prompt or not prompt.strip():
            log.warning("درخواستِ تولید تصویر با prompt خالی نادیده گرفته شد")
            return None

        self._errors_by_provider.clear()
        self._last_error = None

        try:
            from .ai_provider_manager import try_custom_image
            custom_result = await try_custom_image(self.owner_user_id, "generate_image", prompt, width, height)
            if custom_result:
                log.info("تصویر با موفقیت توسط Providerِ سفارشیِ تنظیم‌شده تولید شد (%s بایت)", len(custom_result))
                return custom_result
        except Exception as e:
            log.warning("بررسیِ Providerِ سفارشیِ تصویری شکست خورد، ادامه با زنجیره‌ی پیش‌فرض: %s", e)

        providers = (
            ("pollinations", self._call_pollinations),
            ("deepai", self._call_deepai),
            ("stablehorde", self._call_stablehorde),
        )

        for provider_name, provider_func in providers:
            log.info("تلاش برای تولید تصویر با Provider: %s", provider_name)
            result = await self._run_with_retry(provider_name, provider_func, prompt, width, height)
            if result:
                log.info("تصویر با موفقیت توسط %s تولید شد (%s بایت)", provider_name, len(result))
                return result

        log.error("هیچ‌کدام از سرویس‌های تولید تصویر (Pollinations/DeepAI/Stable Horde) موفق نبودند")
        try:
            from .database import db
            db.add_system_log(
                log_type="IMAGE_GEN",
                event_type="image_gen_failure",
                severity="ERROR",
                message="هر سه Provider تولید تصویر ناموفق بودند",
                details={"prompt": prompt[:500], "errors": self._errors_by_provider},
                status="failed",
            )
        except Exception:
            log.exception("ثبتِ لاگِ شکستِ تولید تصویر در دیتابیس هم ناموفق بود")

        return None

    async def edit_image(
        self,
        image_bytes: bytes,
        instruction: str,
        mime: str = "image/jpeg",
    ) -> Optional[bytes]:
        """
        ویرایش/تغییرِ استایلِ یک تصویرِ موجود (نه تولیدِ تصویرِ کاملاً تازه).
        برخلافِ generate_image، این متد زنجیره‌ی Pollinations/DeepAI/Stable Horde رو
        امتحان نمی‌کنه چون هیچ‌کدوم ورودیِ تصویری نمی‌گیرن؛ فقط Providerِ چندوجهیِ
        تنظیم‌شده در مدیریتِ API (فعلاً Gemini) این کار رو انجام می‌ده.
        اگه هیچ Providerِ مناسبی تنظیم نشده باشه، None برمی‌گرده و caller باید پیامِ
        روشنی (مثلِ «کلیدِ Gemini رو در مدیریتِ API تنظیم کن») به کاربر نشون بده.
        """
        if not image_bytes or not instruction or not instruction.strip():
            return None

        self._last_error = None
        try:
            from .ai_provider_manager import try_custom_image
            result = await try_custom_image(
                self.owner_user_id, "edit_image", instruction.strip(),
                input_image=image_bytes, input_mime=mime,
            )
        except Exception as e:
            log.warning("خطا در ویرایشِ تصویر با هوش مصنوعی: %s", e)
            self._last_error = f"edit_image: {e}"
            return None

        if result:
            log.info("تصویر با موفقیت ویرایش شد (%s بایت)", len(result))
        else:
            self._last_error = (
                "هیچ Providerِ چندوجهی‌ای (Gemini) برای ویرایشِ تصویر تنظیم نشده یا موقتاً در دسترس نیست"
            )
        return result

    async def check_status(self) -> dict:
        """
        تستِ سبکِ در دسترس بودنِ هر سه Provider (برای نمایش در پنل مدیریت).
        هشدار: این متد واقعاً یک تصویر تولید می‌کند (سبک‌ترین سایز ممکن)
        و ممکن است چند ثانیه طول بکشد، مخصوصاً برای Stable Horde.
        """
        results: dict = {}
        test_prompt = "a simple red circle on white background"

        for provider_name, provider_func in (
            ("pollinations", self._call_pollinations),
            ("deepai", self._call_deepai),
            ("stablehorde", self._call_stablehorde),
        ):
            self._last_error = None
            try:
                res = await provider_func(test_prompt, 256, 256)
                ok = bool(res)
            except Exception as e:
                ok = False
                self._last_error = f"{provider_name}: {e}"
            results[provider_name] = {
                "ok": ok,
                "error": None if ok else (self._last_error or "نامشخص"),
            }
        return results

    @property
    def last_errors(self) -> dict:
        """دیکشنریِ آخرین خطای هر Provider (برای دیباگ)"""
        return dict(self._errors_by_provider)

    async def close(self):
        """بستنِ session (باید همیشه در finally صدا زده شود)"""
        await self.session.aclose()
