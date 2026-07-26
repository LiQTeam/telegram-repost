"""
مسیریاب هوشمند بین Mistral و Groq برای عملیات‌های AI
با قابلیت انتخاب خودکار مدل بر اساس طول متن و نوع درخواست
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import MISTRAL_API_KEY, GROQ_API_KEY

log = logging.getLogger("repost_bot.ai_router")

# URLهای API
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# مدل‌ها
MISTRAL_MODEL = "mistral-small-latest"
GROQ_MODEL = "llama-3.1-8b-instant"

# زمان تایم‌اوت (ثانیه)
TIMEOUT = 30

# آستانه‌های طول متن برای انتخاب مدل
SHORT_TEXT_THRESHOLD = 1500
LONG_TEXT_THRESHOLD = 6000

# قانونِ مشترکِ «مدیریتِ هوشمندِ ایموجی» که هم در خلاصه‌نویسی و هم در بازنویسی
# استفاده می‌شه: اگر متن ایموجی نداشت، هوشمندانه و به‌اندازه ایموجی اضافه شه.
_EMOJI_RULES = (
    "مدیریت هوشمند ایموجی‌ها:\n"
    "- اگر متن اصلاً ایموجی نداشت، خودت به‌اندازه‌ای که لازمه (نه زیاد و نه شلوغ) "
    "ایموجی‌های مرتبط و طبیعی بهش اضافه کن؛ چیدمانِ هوشمند این‌طوریه: یک ایموجیِ "
    "مناسب در ابتدای متن، یک ایموجیِ مناسب در انتهای متن، و در صورتِ نیاز چند "
    "ایموجیِ مرتبط در وسط‌های متن کنارِ کلمات یا جمله‌های کلیدی.\n"
    "- تعداد و شدتِ ایموجی‌ها باید متناسب با طولِ متن باشه؛ برای متنِ کوتاه کم و "
    "برای متنِ بلندتر کمی بیشتر، ولی هیچ‌وقت شلوغ و آزاردهنده نشه.\n"
    "- ایموجی‌ها باید کاملاً با موضوع، کلمات و لحنِ متن (رسمی، خبری، طنز، تبلیغاتی) "
    "همخوان باشن و دقیقاً سرِ جای درست بشینن (نه وسطِ کلمه یا جای بی‌ربط).\n"
    "- اگر متن از قبل ایموجی داشت، ایموجی‌های خوب رو نگه‌دار و فقط ایموجی‌های "
    "نامرتبط یا زشت رو اصلاح یا حذف کن؛ الکی ایموجی اضافه نکن.\n"
    "- خوانایی مهم‌تر از تزئینه؛ ایموجی باید به فهمِ متن کمک کنه نه این‌که حواس رو پرت کنه."
)


class AIRouter:
    """مسیریاب هوشمند برای انتخاب بهترین مدل AI"""

    def __init__(self):
        self.session = httpx.AsyncClient(timeout=TIMEOUT)
        self._last_error = None

    async def _call_mistral(self, prompt: str, system_prompt: str = "", temperature: float = 0.7) -> Optional[str]:
        """
        فراخوانی Mistral API (تک‌پیامی)
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self._call_mistral_messages(messages, temperature)

    async def _call_mistral_messages(self, messages: list, temperature: float = 0.7) -> Optional[str]:
        """
        فراخوانی Mistral API با تاریخچه‌ی کامل پیام‌ها (برای چت چندمرحله‌ای)
        """
        try:
            response = await self.session.post(
                MISTRAL_URL,
                headers={
                    "Authorization": f"Bearer {MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MISTRAL_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 4096,
                }
            )
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"]["content"].strip()
            log.debug("Mistral پاسخ داد: %s کاراکتر", len(result))
            return result

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else 0
            error_msg = f"HTTP {status}"
            try:
                error_data = e.response.json()
                if "error" in error_data:
                    error_msg = error_data["error"].get("message", error_msg)
            except Exception:
                pass
            log.warning("خطا در فراخوانی Mistral (%s): %s", status, error_msg)
            self._last_error = f"Mistral: {error_msg}"
            return None

        except httpx.TimeoutException:
            log.warning("Mistral Timeout (بیش از %s ثانیه)", TIMEOUT)
            self._last_error = "Mistral: Timeout"
            return None

        except Exception as e:
            log.warning("خطا در فراخوانی Mistral: %s", e)
            self._last_error = f"Mistral: {e}"
            return None

    async def _call_groq(self, prompt: str, system_prompt: str = "", temperature: float = 0.7) -> Optional[str]:
        """
        فراخوانی Groq API (تک‌پیامی)
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self._call_groq_messages(messages, temperature)

    async def _call_groq_messages(self, messages: list, temperature: float = 0.7) -> Optional[str]:
        """
        فراخوانی Groq API با تاریخچه‌ی کامل پیام‌ها (برای چت چندمرحله‌ای)
        """
        try:
            response = await self.session.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 4096,
                }
            )
            response.raise_for_status()
            data = response.json()
            result = data["choices"][0]["message"]["content"].strip()
            log.debug("Groq پاسخ داد: %s کاراکتر", len(result))
            return result

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else 0
            error_msg = f"HTTP {status}"
            try:
                error_data = e.response.json()
                if "error" in error_data:
                    error_msg = error_data["error"].get("message", error_msg)
            except Exception:
                pass
            log.warning("خطا در فراخوانی Groq (%s): %s", status, error_msg)
            self._last_error = f"Groq: {error_msg}"
            return None

        except httpx.TimeoutException:
            log.warning("Groq Timeout (بیش از %s ثانیه)", TIMEOUT)
            self._last_error = "Groq: Timeout"
            return None

        except Exception as e:
            log.warning("خطا در فراخوانی Groq: %s", e)
            self._last_error = f"Groq: {e}"
            return None

    async def route(
        self,
        text: str,
        task_type: str = "translate",
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """
        انتخاب Provider مناسب و اجرای درخواست با fallback خودکار

        قوانین انتخاب:
        - متن کمتر از 1500 کاراکتر: Mistral (دقت بالاتر)
        - متن بین 1500 تا 6000 کاراکتر: Groq (سرعت بالاتر)
        - متن بیشتر از 6000 کاراکتر: ابتدا Groq، در صورت خطا Mistral
        - ترجمه و بازنویسی خلاقانه: Mistral ترجیح داده می‌شود
        - اصلاح نگارشی یا ترجمه ساده: Groq ترجیح داده می‌شود
        """
        text_len = len(text)

        # انتخاب اولیه بر اساس نوع و طول
        if task_type == "ad_classify":
            # تشخیصِ تبلیغ/پستِ عادی -> همیشه Mistral در اولویته (برای این
            # وظیفه، دقت/استدلالِ درست‌تر مهم‌تر از سرعته؛ متنِ ورودی هم از قبل
            # کوتاه/بریده‌شده‌ست، پس نیازی به سوییچِ Groq بر اساسِ طول نیست).
            preferred = "mistral"
        elif task_type in ("translate", "rewrite"):
            # ترجمه و بازنویسی خلاقانه -> Mistral
            preferred = "mistral"
        elif task_type == "summarize":
            # خلاصه‌سازی -> اگر کوتاه باشه Mistral وگرنه Groq
            preferred = "mistral" if text_len < SHORT_TEXT_THRESHOLD else "groq"
        else:
            # سایر موارد -> Groq
            preferred = "groq"

        # بازنویسی بر اساس طول (تشخیصِ تبلیغ از این قاعده مستثناست؛ نگاه کن به بالا)
        if text_len > LONG_TEXT_THRESHOLD and task_type != "ad_classify":
            # متن خیلی بلند -> Groq (ظرفیت بالاتر)
            preferred = "groq"

        log.info("انتخاب Provider: %s (طول: %s, نوع: %s)", preferred, text_len, task_type)

        # تلاش اول
        result = None
        if preferred == "mistral":
            result = await self._call_mistral(text, system_prompt, temperature)
            if result is None:
                log.warning("Mistral ناموفق بود، سوییچ به Groq")
                result = await self._call_groq(text, system_prompt, temperature)
        else:
            result = await self._call_groq(text, system_prompt, temperature)
            if result is None:
                log.warning("Groq ناموفق بود، سوییچ به Mistral")
                result = await self._call_mistral(text, system_prompt, temperature)

        if result is None:
            log.error("هر دو Provider در دسترس نبودند، متن اصلی برگردانده شد.")
            # ثبت خطا در لاگ سیستم
            from .database import db
            db.add_system_log(
                log_type="AI",
                event_type="ai_failure",
                severity="ERROR",
                message="هر دو Provider AI در دسترس نبودند، متن اصلی برگردانده شد",
                details={"task_type": task_type, "text_length": text_len, "last_error": self._last_error},
                status="failed"
            )
            return text

        return result

    async def translate_to_persian(self, text: str) -> str:
        """
        ترجمه متن به فارسی با لحن کاملاً انسانی
        """
        system = (
            "تو یک مترجم حرفه‌ای و فوق‌العاده ماهر فارسی هستی. "
            "متن ورودی را به فارسی روان، طبیعی و با رعایت کامل دستور زبان و نگارش ترجمه کن. "
            "از معادل‌های دقیق و زیبای فارسی برای کلمات استفاده کن. "
            "ترجمه نباید خشک و تحت‌اللفظی باشد. "
            "به ساختار جملات، نیم‌فاصله‌ها، ویرگول‌ها و نقطه‌گذاری صحیح توجه کامل داشته باش. "
            "لحن ترجمه باید متناسب با محتوای اصلی (رسمی، خبری، طنز، تبلیغاتی) باشد. "
            "تنها متن ترجمه‌شده را برگردان، بدون توضیح اضافی."
        )
        return await self.route(text, task_type="translate", system_prompt=system, temperature=0.5)

    async def summarize(self, text: str) -> str:
        """
        خلاصه‌سازی هوشمند متن با حفظ نکات کلیدی
        """
        system = (
            "تو یک خلاصه‌ساز حرفه‌ای و دقیق هستی. "
            "متن ورودی را به‌صورت مختصر، مفید و روان خلاصه کن. "
            "نکات کلیدی و اصلی را به‌طور کامل حفظ کن. "
            "خلاصه باید خوانا، منسجم و بدون جملات اضافی باشد. "
            "طول خلاصه باید حدود ۲۰ تا ۳۰ درصد متن اصلی باشد.\n\n"
            + _EMOJI_RULES
            + "\n\nتنها متن خلاصه‌شده را برگردان، بدون توضیح اضافی."
        )
        return await self.route(text, task_type="summarize", system_prompt=system, temperature=0.5)

    async def rewrite(self, text: str) -> str:
        """
        بازنویسی خلاقانه با حفظ محتوا و مدیریت هوشمند ایموجی‌ها
        """
        system = (
            "تو یک نویسنده‌ی حرفه‌ای، خلاق و بسیار باتجربه در تولید محتوای کانال‌های تلگرامی فارسی هستی. "
            "وظیفه‌ات بازنویسیِ کامل و عمیقِ متن ورودی است، به‌گونه‌ای که هیچ ردی از سبک نگارشیِ متن اصلی باقی نماند.\n\n"
            "قوانین بازنویسی:\n"
            "۱. فقط جایگزینیِ کلمات با مترادف کافی نیست؛ ساختار جمله‌ها را کاملاً بازچینی کن: جمله‌های بلند را بشکن، "
            "جمله‌های کوتاه را در صورت لازم ترکیب کن، ترتیب اطلاعات را تغییر بده و لحن را از نو بساز.\n"
            "۲. طول و ریتم جمله‌ها را متنوع کن (کوتاه، متوسط، بلند) تا متن یکنواخت و قابل‌شناسایی نباشد.\n"
            "۳. موضوع، محتوا، اطلاعات و پیام اصلی باید دقیقاً و کامل حفظ شود؛ هیچ واقعیتی حذف، اضافه یا تحریف نشود.\n"
            "۴. هدف نهایی: شباهت ظاهری، ساختاری و سبکی با متنِ کانال مبدأ کاملاً از بین برود (ضدِ تشخیصِ کپی/ری‌پست)، "
            "بدون این‌که مفهوم عوض شود.\n"
            "۵. اگر متن لحنِ تبلیغاتی، خبری، طنز یا رسمی دارد، همان لحن را با کلماتِ متفاوت و جذاب‌تر بازسازی کن؛ "
            "می‌توانی از عبارات جذاب‌تر، هوک ابتدایی قوی‌تر یا جمله‌ی پایانیِ گیراتر استفاده کنی، تا وقتی مفهوم دست‌نخورده بماند.\n"
            "۶. از تکرار عینیِ عبارات کلیدیِ متن اصلی خودداری کن؛ برایشان معادل طبیعی و روان فارسی بساز.\n\n"
            + _EMOJI_RULES
            + "\n\nتنها متن بازنویسی‌شده را برگردان، بدون توضیح اضافی، بدون مقدمه، بدون گفتنِ این‌که چه کاری انجام دادی."
        )
        return await self.route(text, task_type="rewrite", system_prompt=system, temperature=0.9)

    async def chat(self, messages: list, temperature: float = 0.85) -> str:
        """
        چتِ پیوسته و چندمرحله‌ای با هوش مصنوعی (مثل یک مکالمه‌ی واقعی).
        `messages` لیستی از دیکشنری‌های {"role": "user"/"assistant", "content": "..."} است
        که کل تاریخچه‌ی مکالمه را در بر می‌گیرد.
        """
        system_prompt = (
            "تو یک دستیار هوشمند، دوستانه و فارسی‌زبان هستی که دقیقاً مثل یک انسان واقعی و طبیعی گفت‌وگو می‌کنی. "
            "این یک مکالمه‌ی پیوسته و چندمرحله‌ای است؛ حتماً به کل تاریخچه‌ی پیام‌های قبلی توجه کن و مکالمه را "
            "منسجم، مرتبط و با به‌خاطر سپردنِ جزئیاتی که کاربر قبلاً گفته ادامه بده. "
            "پاسخ‌هایت طبیعی، مفید، مستقیم و بدون مقدمه‌چینیِ اضافه باشد؛ کوتاه و خلاصه بنویس مگر این‌که موضوع "
            "واقعاً نیاز به توضیح کامل‌تر داشته باشد."
        )
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        text_len = sum(len(m.get("content", "")) for m in messages)

        preferred = "mistral" if text_len < SHORT_TEXT_THRESHOLD else "groq"
        if text_len > LONG_TEXT_THRESHOLD:
            preferred = "groq"

        log.info("چت هوش مصنوعی؛ انتخاب Provider: %s (طول تاریخچه: %s)", preferred, text_len)

        result = None
        if preferred == "mistral":
            result = await self._call_mistral_messages(full_messages, temperature)
            if result is None:
                log.warning("Mistral ناموفق بود، سوییچ به Groq")
                result = await self._call_groq_messages(full_messages, temperature)
        else:
            result = await self._call_groq_messages(full_messages, temperature)
            if result is None:
                log.warning("Groq ناموفق بود، سوییچ به Mistral")
                result = await self._call_mistral_messages(full_messages, temperature)

        if result is None:
            log.error("هر دو Provider برای چت در دسترس نبودند.")
            from .database import db
            db.add_system_log(
                log_type="AI",
                event_type="ai_chat_failure",
                severity="ERROR",
                message="هر دو Provider AI برای چت در دسترس نبودند",
                details={"text_length": text_len, "last_error": self._last_error},
                status="failed",
            )
            return "❌ در حال حاضر هیچ‌کدوم از موتورهای هوش مصنوعی در دسترس نیستن. کمی بعد دوباره امتحان کن."

        return result

    async def generate(self, prompt: str) -> str:
        """
        اجرای یک درخواست آزاد و دلخواه کاربر (مثلاً نوشتن کپشن یا متن درباره‌ی هر موضوعی).
        هر کدام از دو موتور Groq یا Mistral که در دسترس باشد پاسخ می‌دهد.
        """
        system = (
            "تو یک دستیار خلاق و فارسی‌زبان هستی که هر نوع محتوای متنی (کپشن، متن، ایده، توضیح) "
            "را دقیقاً بر اساس درخواست کاربر می‌نویسی. مستقیم سراغ اصل مطلب برو، "
            "بدون مقدمه‌چینی یا توضیح اضافی درباره‌ی خودت یا این‌که چه کاری انجام می‌دی."
        )
        return await self.route(prompt, task_type="general", system_prompt=system, temperature=0.8)

    async def check_status(self) -> dict:
        """
        تست زنده‌ی در دسترس بودنِ هر یک از Mistral و Groq با یک درخواست سبک.
        این وضعیت فقط مربوط به خدمات متنی (ترجمه/خلاصه‌سازی/بازنویسی) است
        و هیچ ارتباطی به موتورهای پردازش تصویر بخش واترمارک ندارد.
        """
        results: dict = {}
        for name, func in (("groq", self._call_groq), ("mistral", self._call_mistral)):
            self._last_error = None
            try:
                res = await func("سلام", system_prompt="فقط دقیقاً بنویس: OK", temperature=0)
            except Exception as e:
                res = None
                self._last_error = f"{name}: {e}"
            results[name] = {
                "ok": res is not None,
                "error": None if res is not None else (self._last_error or "نامشخص"),
            }
        return results

    async def close(self):
        """بستن session"""
        await self.session.aclose()