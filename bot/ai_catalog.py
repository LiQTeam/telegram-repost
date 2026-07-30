"""
کاتالوگِ ۴ سرویسِ هوش مصنوعی (Mistral، Groq، Gemini، HuggingFace).

هر سرویس یک کلیدِ API واحد داره که هم برایِ متن و هم برایِ تصویر (اگه پشتیبانی
کنه) استفاده می‌شه. دیگه تفکیکِ ۸+۸ نداریم — هر ProviderInfo مشخص می‌کنه چه
قابلیت‌هایی داره (text / image / هر دو).

این فایل فقط «داده» (متادیتا) نگه می‌داره - هیچ فراخوانیِ شبکه‌ای اینجا انجام
نمی‌شه (نگاه کن به ai_provider_manager.py برایِ منطقِ اعتبارسنجی/فراخوانی).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ==================== قابلیت‌ها ====================
CAP_TEXT  = "text"
CAP_IMAGE = "image"

# ==================== برای backward-compat با ai_router.py / image_router.py ====================
CATEGORY_TEXT  = CAP_TEXT
CATEGORY_IMAGE = CAP_IMAGE

# ==================== وضعیت‌های ممکنِ یک سرویس ====================
STATUS_NOT_SET         = "not_set"
STATUS_INVALID         = "invalid"
STATUS_CONNECTION_ERROR= "connection_error"
STATUS_QUOTA_EXCEEDED  = "quota_exceeded"
STATUS_WRONG_SERVICE   = "wrong_service"
STATUS_CHECKING        = "checking"
STATUS_ACTIVE          = "active"
STATUS_FALLBACK        = "fallback"

STATUS_LABELS: dict[str, str] = {
    STATUS_NOT_SET:          "🔴 غیرفعال (API وارد نشده)",
    STATUS_INVALID:          "🔴 غیرفعال (API نامعتبر)",
    STATUS_CONNECTION_ERROR: "🟠 غیرفعال (خطای اتصال)",
    STATUS_QUOTA_EXCEEDED:   "🟠 غیرفعال (Quota تمام شده)",
    STATUS_WRONG_SERVICE:    "🔴 غیرفعال (API مربوط به سرویس دیگری است)",
    STATUS_CHECKING:         "🟡 در حال بررسی",
    STATUS_ACTIVE:           "🟢 فعال (کلیدِ شخصی)",
    STATUS_FALLBACK:         "🟡 فعال (پیش‌فرضِ سیستم/.env — کلیدِ شخصی وارد نشده)",
}


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    capabilities: tuple[str, ...]      # ("text",) | ("image",) | ("text", "image")
    base_url: str
    auth_style: str                    # 'bearer' | 'query' | 'key_header'
    auth_header_name: str = ""
    # ---- مدل‌های متنی ----
    default_text_model: str = ""
    text_models: tuple[str, ...] = field(default_factory=tuple)
    # ---- مدل‌های تصویری ----
    default_image_model: str = ""
    image_models: tuple[str, ...] = field(default_factory=tuple)
    # ---- validation ----
    validate_method: str = "GET"
    validate_path: str = "/models"
    key_prefixes: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    @property
    def has_text(self) -> bool:
        return CAP_TEXT in self.capabilities

    @property
    def has_image(self) -> bool:
        return CAP_IMAGE in self.capabilities

    # backward-compat: قدیماً category داشت؛ primary capability رو برمی‌گردونه
    @property
    def category(self) -> str:
        return self.capabilities[0] if self.capabilities else CAP_TEXT


# ==================== ۴ سرویسِ یکپارچه ====================
PROVIDERS: dict[str, ProviderInfo] = {

    # ---------- Mistral AI ----------
    # فرمتِ OpenAI-compat — فقط متن (Pixtral برای vision هست ولی image-gen نداره)
    "mistral": ProviderInfo(
        id="mistral",
        label="Mistral AI",
        capabilities=(CAP_TEXT,),
        base_url="https://api.mistral.ai/v1",
        auth_style="bearer",
        default_text_model="mistral-small-latest",
        text_models=(
            "mistral-small-latest",        # Small 4 — سریع و مقرون‌به‌صرفه (119B MoE)
            "mistral-large-latest",        # Large 3 — 675B، قدرتمندترین
            "codestral-latest",            # کدنویسی + FIM (تکمیل کد، لتنسی پایین)
            "devstral-small-latest",       # Devstral Small 2 (Dec 2025) — ایجنت کدنویسی، Apache-2.0، ارزان‌ترین ($0.1/$0.3)
            "pixtral-large-latest",        # multimodal vision (ورودیِ تصویر دارد)
        ),
        validate_method="GET",
        validate_path="/models",
    ),

    # ---------- Groq ----------
    # فرمتِ OpenAI-compat — فقط متن
    # مدل‌های llama-3.1-8b-instant و llama-3.3-70b-versatile در ۱۶ آگوست ۲۰۲۶
    # به‌طور کامل خاموش می‌شن (deprecation رسمیِ ۱۷ ژوئن ۲۰۲۶) — عمداً حذف شدن
    "groq": ProviderInfo(
        id="groq",
        label="Groq",
        capabilities=(CAP_TEXT,),
        base_url="https://api.groq.com/openai/v1",
        auth_style="bearer",
        key_prefixes=("gsk_",),
        default_text_model="openai/gpt-oss-120b",
        text_models=(
            "openai/gpt-oss-120b",              # GPT-OSS 120B — Production، توصیه‌شده‌ترین
            "openai/gpt-oss-20b",                # GPT-OSS 20B — Production، سریع‌تر/ارزان‌تر
            "qwen/qwen3.6-27b",                  # Qwen 3.6 27B — Preview، multimodal (متن+تصویر ورودی)
        ),
        # نکته: gemma2-9b-it و moonshotai/kimi-k2-instruct از سرویس حذف شده‌اند
        # (رجوع کن به console.groq.com/docs/deprecations). qwen/qwen3-32b و
        # llama-4-scout هم در ۱۷ ژوئن ۲۰۲۶ deprecated شدن. llama-3.1-8b-instant
        # و llama-3.3-70b-versatile هنوز Production هستن ولی طبق برنامه‌ی رسمیِ
        # Groq در ۱۶ آگوست ۲۰۲۶ (کمتر از ۳ هفته دیگه) خاموش می‌شن — عمداً به
        # کاتالوگ اضافه نکردم چون در بازه‌ی عمرِ این پروژه می‌شکنن.
        validate_method="GET",
        validate_path="/models",
    ),

    # ---------- Google Gemini ----------
    # API اختصاصی (generateContent) — هم متن هم تولید تصویر
    "gemini": ProviderInfo(
        id="gemini",
        label="Google Gemini",
        capabilities=(CAP_TEXT, CAP_IMAGE),
        base_url="https://generativelanguage.googleapis.com/v1beta",
        auth_style="query",          # کلید به‌صورتِ ?key=... یا هدرِ x-goog-api-key
        auth_header_name="key",
        key_prefixes=("AIza",),
        default_text_model="gemini-2.5-flash",
        text_models=(
            "gemini-2.5-flash",       # GA stable — رایگان، توصیه‌شده برای production
            "gemini-3.5-flash",       # جدیدترین GA (می ۲۰۲۶) — frontier + agentic، رایگان
            "gemini-3.1-flash-lite",  # سریع‌ترین/ارزان‌ترین ردهٔ Flash — رایگان، RPM بالاتر
        ),
        # نکته: gemini-2.5-pro و کل خانوادهٔ Pro (gemini-3-pro، gemini-3.1-pro)
        # از ۱ آوریل ۲۰۲۶ به‌طور کامل از free tier خارج و paid-only شدن —
        # عمداً از پیش‌فرض کاتالوگ حذف شدن (اگه کاربر کلید pay-as-you-go داره
        # و صراحتاً Pro می‌خواد، جدا اضافه کن).
        default_image_model="gemini-3.1-flash-image",
        image_models=(
            "gemini-3.1-flash-image",       # Nano Banana 2 — کیفیتِ Pro با سرعتِ Flash (فوریه ۲۰۲۶)
            "gemini-3.1-flash-lite-image",  # Nano Banana 2 Lite — سریع‌ترین/ارزان‌ترین
            "gemini-2.5-flash-image",       # Nano Banana (نسل قبل) — fallback با سازگاریِ بیشتر
        ),
        validate_method="GET",
        validate_path="/models",
    ),

    # ---------- Hugging Face ----------
    # router.huggingface.co — هم متن (OpenAI-compat) هم تصویر (hf-inference endpoint)
    "huggingface": ProviderInfo(
        id="huggingface",
        label="Hugging Face",
        capabilities=(CAP_TEXT, CAP_IMAGE),
        base_url="https://router.huggingface.co/v1",
        auth_style="bearer",
        key_prefixes=("hf_",),
        default_text_model="meta-llama/Llama-3.1-8B-Instruct",
        text_models=(
            "meta-llama/Llama-3.1-8B-Instruct",         # Llama 3.1 8B — سریع و عمومی
            "Qwen/Qwen3-Coder-480B-A35B-Instruct",      # Qwen3 Coder 480B — کدنویسی
            "openai/gpt-oss-120b",                       # GPT-OSS 120B روی HF (چند provider: cerebras/groq/...)
            "deepseek-ai/DeepSeek-V4-Flash",             # DeepSeek V4 Flash — نسلِ جدید، context تا 1M، جایگزینِ R1
        ),
        default_image_model="black-forest-labs/FLUX.1-schnell",
        image_models=(
            "black-forest-labs/FLUX.1-schnell",   # سریع‌ترین و رایگان — تأییدشده روی provider="hf-inference"
            "black-forest-labs/FLUX.1-dev",        # کیفیت بالاتر — تأییدشده روی provider="hf-inference"
        ),
        # نکته: FLUX.2-klein-4B (ژانویه ۲۰۲۶) جدیدتره ولی نتونستم تأیید کنم که
        # روی provider مشخصِ hf-inference هم serve می‌شه یا نه — کدِ فعلی در
        # ai_adapters.py مستقیماً به /hf-inference/models/{model} می‌زنه (نه
        # auto-routing). قبل از سوییچ به FLUX.2 باید با کلید واقعی تست بشه؛
        # فعلاً برای جلوگیری از ۴۰۴ روی FLUX.1 (که رسماً تأیید شده) موندم.
        validate_method="GET",
        validate_path="/models",
    ),
}

# backward-compat
ALL_PROVIDERS: dict[str, ProviderInfo] = PROVIDERS


def get_provider(service_id: str) -> Optional[ProviderInfo]:
    return PROVIDERS.get(service_id)


def all_providers() -> list[ProviderInfo]:
    return list(PROVIDERS.values())


# برای backward-compat با ai_provider_manager.py و ai_router.py
def providers_by_category(category: str) -> list[ProviderInfo]:
    """همه‌ی سرویس‌هایی که این category رو در قابلیت‌هاشون دارن برمی‌گردونه."""
    return [p for p in PROVIDERS.values() if category in p.capabilities]


# ==================== وظایفِ قابل‌مسیریابی ====================
@dataclass(frozen=True)
class TaskInfo:
    id: str
    label: str
    category: str


TEXT_TASKS: dict[str, TaskInfo] = {
    "summarize":         TaskInfo("summarize",         "📝 خلاصه‌سازی",    CAP_TEXT),
    "rewrite":           TaskInfo("rewrite",           "🔄 بازنویسی",      CAP_TEXT),
    "fix_text":          TaskInfo("fix_text",          "🩹 اصلاح املا/گرامر", CAP_TEXT),
    "translate":         TaskInfo("translate",         "🌐 ترجمه",         CAP_TEXT),
    "generate_title":    TaskInfo("generate_title",    "🏷 تولید عنوان",    CAP_TEXT),
    "generate_caption":  TaskInfo("generate_caption",  "💬 تولید کپشن",    CAP_TEXT),
    "generate_hashtags": TaskInfo("generate_hashtags", "#️⃣ تولید هشتگ",   CAP_TEXT),
    "auto_reply":        TaskInfo("auto_reply",        "🤖 پاسخ خودکار",   CAP_TEXT),
    "analyze_text":      TaskInfo("analyze_text",      "🔍 تحلیل متن",     CAP_TEXT),
    "prompt_writer":     TaskInfo("prompt_writer",     "🧠 پرامپت‌نویس",   CAP_TEXT),
}

IMAGE_TASKS: dict[str, TaskInfo] = {
    "generate_image": TaskInfo("generate_image", "🖼 تولید تصویر",    CAP_IMAGE),
    "edit_image":     TaskInfo("edit_image",     "🎨 تغییر استایل عکس", CAP_IMAGE),
    "caption_image":  TaskInfo("caption_image",  "🗒 توضیحِ تصویر",  CAP_IMAGE),
    "vision":         TaskInfo("vision",         "👁 Vision",         CAP_IMAGE),
    "ocr":            TaskInfo("ocr",            "🔤 OCR",            CAP_IMAGE),
}

ALL_TASKS: dict[str, TaskInfo] = {**TEXT_TASKS, **IMAGE_TASKS}


def tasks_by_category(category: str) -> list[TaskInfo]:
    return [t for t in ALL_TASKS.values() if t.category == category]
