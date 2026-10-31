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
GROQ_MODEL = "openai/gpt-oss-120b"

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


_MODULE_TASK_MAP = {
    "translate": "translate",
    "rewrite": "rewrite",
    "summarize": "summarize",
    "ad_classify": "analyze_text",
    "general": "generate_caption",
    "fix_text": "fix_text",
    "generate_hashtags": "generate_hashtags",
    "prompt_writer": "prompt_writer",
    # وظایفِ تعامليِ صفحه‌ی اصلی که مستقیماً با نامِ خودشون route می‌شن؛ این‌جا مپ
    # می‌شن تا اگر کاربر Providerِ سفارشی برای همین وظیفه تنظیم کرده باشه، اعمال بشه.
    "generate_caption": "generate_caption",
    "generate_title": "generate_title",
    "auto_reply": "auto_reply",
    "analyze_text": "analyze_text",
}

# زبان‌هایِ قابل‌انتخاب برایِ ترجمه‌ی هوشمند (کد -> نامِ نمایشی)
TRANSLATE_LANGS: dict[str, str] = {
    "fa": "فارسی",
    "en": "انگلیسی",
    "ar": "عربی",
    "auto": "خودکار (برعکسِ زبانِ متن)",
}

# سطح‌هایِ خلاصه‌سازی (کد -> (برچسبِ نمایشی، نسبتِ تقریبیِ طول خروجی، توضیحِ اضافه برایِ پرامپت))
SUMMARY_LEVELS: dict[str, tuple[str, str, str]] = {
    "short": (
        "⚡️ فوق‌کوتاه",
        "۱۰ تا ۱۵ درصد",
        "فقط در حدِ یک یا دو جمله‌ی تیتروار، فقط مهم‌ترین نکته را بگو؛ مثلِ تیترِ خبری.",
    ),
    "medium": (
        "📄 متوسط",
        "۲۰ تا ۳۰ درصد",
        "خلاصه‌ای استاندارد و متعادل که نکاتِ کلیدی را در چند جمله‌ی روان پوشش می‌دهد.",
    ),
    "detailed": (
        "📚 مفصل",
        "۴۰ تا ۵۰ درصد",
        "خلاصه‌ای کامل‌تر و ساختاریافته؛ در صورتِ نیاز از نکته‌های بولت‌وار (هرکدام با یک ایموجیِ مرتبط در ابتدا) "
        "برایِ جدا کردنِ محورهایِ اصلی استفاده کن، ولی باز هم چیزی جز خلاصه ننویس.",
    ),
}


class AIRouter:
    """مسیریاب هوشمند برای انتخاب بهترین مدل AI"""

    def __init__(self, owner_user_id: "int | None" = None):
        # owner_user_id: اگه ست بشه، قبل از منطقِ پیش‌فرضِ Mistral/Groq (که از
        # کلیدهای .env استفاده می‌کنه)، اول بررسی می‌شه که آیا این کاربر/ادمین
        # برایِ این وظیفه یک Providerِ سفارشی (از سیستمِ مدیریتِ API هوش
        # مصنوعی) و فعال تنظیم کرده یا نه. اگه نه، دقیقاً رفتارِ قبلی ادامه
        # پیدا می‌کنه (سازگاریِ کامل با معماریِ موجود).
        self.owner_user_id = owner_user_id
        self.session = httpx.AsyncClient(timeout=TIMEOUT)
        self._last_error = None

    async def _try_custom(self, task_type: str, text: str, system_prompt: str, temperature: float) -> Optional[str]:
        mapped = _MODULE_TASK_MAP.get(task_type)
        if not mapped:
            return None
        try:
            from .ai_provider_manager import try_custom_text
            return await try_custom_text(self.owner_user_id, mapped, text, system_prompt, temperature)
        except Exception as e:
            log.warning("بررسیِ Providerِ سفارشی برایِ وظیفه‌ی %s شکست خورد: %s", task_type, e)
            return None

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
        # ⚠️ فیکس: بدونِ این گارد، وقتی کلید تنظیم نشده باشه هدرِ
        # «Authorization: Bearer » ساخته می‌شد و httpx همون‌جا (قبل از هر
        # درخواستِ شبکه‌ای) با `Illegal header value` استثنا می‌داد؛ نتیجه یک
        # لاگِ گمراه‌کننده‌ی «خطا در فراخوانی Mistral» بود که مثلِ خرابیِ سرویس
        # به‌نظر می‌رسید، در حالی‌که فقط کلید ست نشده بود.
        if not MISTRAL_API_KEY:
            log.debug("کلیدِ Mistral تنظیم نشده؛ این Provider رد شد.")
            self._last_error = "Mistral: کلید تنظیم نشده"
            return None
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
        # همون گاردِ _call_mistral_messages — نگاه کن به توضیحش.
        if not GROQ_API_KEY:
            log.debug("کلیدِ Groq تنظیم نشده؛ این Provider رد شد.")
            self._last_error = "Groq: کلید تنظیم نشده"
            return None
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
        custom_result = await self._try_custom(task_type, text, system_prompt, temperature)
        if custom_result is not None:
            return custom_result

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

    async def summarize(self, text: str, level: str = "medium") -> str:
        """
        خلاصه‌سازی هوشمند و چندسطحیِ متن با حفظ نکات کلیدی.
        level: یکی از "short" / "medium" / "detailed" (نگاه کن به SUMMARY_LEVELS)
        """
        _label, ratio, extra_rule = SUMMARY_LEVELS.get(level, SUMMARY_LEVELS["medium"])
        system = (
            "تو یک خلاصه‌ساز حرفه‌ای و دقیق هستی. "
            "متن ورودی را به‌صورت مختصر، مفید و روان خلاصه کن. "
            "نکات کلیدی و اصلی را به‌طور کامل حفظ کن. "
            "خلاصه باید خوانا، منسجم و بدون جملات اضافی باشد. "
            f"طول خلاصه باید حدود {ratio} متن اصلی باشد. {extra_rule}\n\n"
            + _EMOJI_RULES
            + "\n\nتنها متن خلاصه‌شده را برگردان، بدون توضیح اضافی، بدون گفتنِ این‌که چه سطحی انتخاب شده."
        )
        return await self.route(text, task_type="summarize", system_prompt=system, temperature=0.5)

    async def translate_smart(self, text: str, target: str = "fa") -> str:
        """
        ترجمه‌ی هوشمند با تشخیصِ خودکارِ زبانِ مبدأ.
        target: "fa" | "en" | "ar" | "auto" (auto یعنی برعکسِ زبانِ تشخیص‌داده‌شده:
        اگر متن فارسی بود -> انگلیسی، در غیرِ این صورت -> فارسی)
        خروجی همیشه با یک خطِ اول به‌شکلِ دقیقاً:
            LANG: <نامِ زبانِ تشخیص‌داده‌شده به فارسی>
        و از خطِ دوم به بعد، فقط متنِ ترجمه‌شده است — تا لایه‌ی نمایش بتونه این دو رو جدا کنه.
        """
        target_name = TRANSLATE_LANGS.get(target, "فارسی")
        if target == "auto":
            target_rule = (
                "ابتدا زبانِ متنِ ورودی رو خودکار تشخیص بده. اگر زبانِ متن فارسی بود، آن را به انگلیسیِ روان "
                "ترجمه کن؛ در غیرِ این صورت (هر زبانِ دیگری) آن را به فارسیِ روان ترجمه کن."
            )
        else:
            target_rule = f"ابتدا زبانِ متنِ ورودی رو خودکار تشخیص بده، سپس آن را به {target_name} ترجمه کن."
        system = (
            "تو یک مترجمِ حرفه‌ای، چندزبانه و فوق‌العاده ماهر هستی که همیشه اول زبانِ متنِ ورودی رو دقیق تشخیص "
            "می‌دهی و بعد ترجمه می‌کنی.\n"
            + target_rule + "\n"
            "ترجمه باید روان، طبیعی، با رعایتِ کاملِ دستورِ زبان و نگارشِ زبانِ مقصد باشد؛ هرگز خشک و "
            "تحت‌اللفظی ترجمه نکن. لحنِ متنِ اصلی (رسمی، خبری، طنز، تبلیغاتی) را در ترجمه هم حفظ کن.\n\n"
            "فرمتِ خروجی حیاتی است و باید دقیقاً همین ساختار را رعایت کنی:\n"
            "خطِ اول -> دقیقاً به‌شکلِ: LANG: <نامِ زبانِ تشخیص‌داده‌شده، به فارسی، مثلِ «انگلیسی» یا «عربی» یا «فارسی»>\n"
            "خطِ دوم -> خالی\n"
            "از خطِ سوم به بعد -> فقط و فقط متنِ ترجمه‌شده، بدون هیچ توضیحِ اضافه‌ای."
        )
        return await self.route(text, task_type="translate", system_prompt=system, temperature=0.4)

    async def fix_text(self, text: str) -> str:
        """
        فقط اصلاحِ املا، گرامر، نقطه‌گذاری و نیم‌فاصله — بدونِ بازنویسیِ خلاقانه.
        سبک، لحن، طولِ جمله‌ها و انتخابِ کلماتِ نویسنده دست‌نخورده می‌مونه.
        """
        system = (
            "تو یک ویراستارِ حرفه‌ایِ فارسی هستی که فقط و فقط غلط‌های نگارشی رو اصلاح می‌کنی؛ "
            "تو ویراستارِ ادبی یا بازنویس‌کننده نیستی.\n\n"
            "قوانینِ دقیق:\n"
            "۱. فقط این موارد رو اصلاح کن: غلط‌های املایی، غلط‌های دستورِ زبان (فعل/فاعل، مطابقتِ جمع/مفرد)، "
            "نقطه‌گذاری (نقطه، ویرگول، علامتِ سؤال/تعجب)، نیم‌فاصله‌های غلط یا جاافتاده، فاصله‌های اضافیِ بینِ کلمات.\n"
            "۲. کلمات، لحن، سبکِ نویسنده، طولِ جمله‌ها و ترتیبِ اطلاعات رو عیناً حفظ کن؛ هیچ جمله‌ای رو "
            "بازنویسی، خلاصه یا زیباتر نکن — این کارِ ابزارِ «بازنویسی» است نه این ابزار.\n"
            "۳. ایموجی‌های موجود در متن رو دقیقاً همون‌جوری که هستن نگه‌دار؛ ایموجیِ جدید اضافه نکن و حذفشون نکن.\n"
            "۴. اگر متن از قبل کاملاً درست بود، همون متن رو بدونِ هیچ تغییری برگردون.\n\n"
            "تنها متنِ اصلاح‌شده رو برگردون، بدونِ توضیح، بدونِ فهرستِ غلط‌های پیداشده، بدونِ مقدمه."
        )
        return await self.route(text, task_type="fix_text", system_prompt=system, temperature=0.2)

    async def generate_hashtags(self, text: str, count: int = 8) -> str:
        """
        تولیدِ هوشمندِ هشتگ‌هایِ مرتبط با متن (ترکیبِ فارسی/انگلیسی بر حسبِ مناسب‌بودن).
        """
        system = (
            "تو یک متخصصِ سئو و رشدِ محتوایِ شبکه‌هایِ اجتماعی (به‌خصوص تلگرام و اینستاگرام) هستی. "
            f"بر اساسِ موضوع، کلیدواژه‌ها و حال‌وهوایِ متنِ ورودی، دقیقاً {count} هشتگِ مرتبط، پرکاربرد و "
            "هوشمندانه تولید کن.\n\n"
            "قوانین:\n"
            "۱. ترکیبی از هشتگ‌هایِ فارسی و انگلیسی بساز؛ فقط وقتی از انگلیسی استفاده کن که آن هشتگِ "
            "خاص در انگلیسی رایج‌تر و پرجست‌وجوتر باشه (مثلِ نامِ برند/تکنولوژی/فیلم).\n"
            "۲. از هشتگ‌هایِ خیلی کلی و بی‌فایده (مثلِ #پست یا #عکس) خودداری کن؛ هشتگ‌ها باید دقیقاً به "
            "موضوعِ همین متن مربوط باشن، نه فقط کلیِ حوزه.\n"
            "۳. هیچ فاصله یا نویسه‌ی غیرمجاز (مثلِ نیم‌فاصله یا -) داخلِ خودِ هشتگ نذار؛ کلماتِ چندبخشی رو "
            "بدونِ فاصله بچسبون (مثلِ #هوش_مصنوعی یا #هوش‌مصنوعی با آندرلاین یا بدونِ فاصله بنویس).\n"
            "۴. فقط لیستِ هشتگ‌ها رو، همه در یک خط و با یک فاصله از هم جدا، برگردون؛ هیچ توضیح، شماره یا "
            "متنِ اضافه‌ای ننویس."
        )
        return await self.route(text, task_type="generate_hashtags", system_prompt=system, temperature=0.6)

    async def prompt_writer(self, idea: str) -> str:
        """
        تبدیلِ یک ایده‌ی کوتاهِ فارسی به یک پرامپتِ فوق‌حرفه‌ایِ انگلیسی برایِ تولیدِ تصویر با هوش مصنوعی،
        با رعایتِ کاملِ اصولِ Prompt Engineering (Subject / Style / Lighting / Composition / Mood / Details / Negative).
        خروجی عمداً کاملاً انگلیسی است چون مدل‌هایِ تولیدِ تصویر با پرامپتِ انگلیسی نتیجه‌یِ به‌مراتب بهتری می‌دهند.
        """
        system = (
            "You are a world-class AI image-generation prompt engineer. Given a short idea (possibly in Persian), "
            "write ONE professional, highly-detailed English prompt following best prompt-engineering practice.\n\n"
            "Structure your output as labeled lines, in this exact order, each on its own line:\n"
            "Subject: <the main subject, described precisely and vividly>\n"
            "Style: <art/photo style, e.g. cinematic photography, oil painting, 3D render, anime, cyberpunk...>\n"
            "Lighting: <lighting setup, e.g. golden hour, studio softbox, neon rim light...>\n"
            "Composition: <camera angle, framing, lens, depth of field>\n"
            "Color palette: <dominant colors / mood colors>\n"
            "Mood: <the emotional atmosphere>\n"
            "Details: <extra fine details that add realism/richness>\n"
            "Quality tags: <e.g. 8k, ultra-detailed, sharp focus, award-winning, trending on artstation>\n"
            "Negative prompt: <what to avoid, e.g. blurry, extra limbs, watermark, low quality, deformed>\n"
            "Aspect ratio: <a sensible suggestion, e.g. 16:9 or 1:1 or 9:16, based on the subject>\n\n"
            "Rules:\n"
            "- Every value must be concrete and specific, never vague placeholders.\n"
            "- Do not add any heading, explanation, or translation before or after the structured lines.\n"
            "- Do not wrap the output in code fences yourself; return plain labeled lines only."
        )
        return await self.route(idea, task_type="prompt_writer", system_prompt=system, temperature=0.8)

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
        last_user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_text = m.get("content", "")
                break
        try:
            from .ai_provider_manager import try_custom_text
            custom_result = await try_custom_text(self.owner_user_id, "auto_reply", last_user_text, system_prompt)
            if custom_result is not None:
                return custom_result
        except Exception as e:
            log.warning("بررسیِ Providerِ سفارشی برایِ چت شکست خورد: %s", e)

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