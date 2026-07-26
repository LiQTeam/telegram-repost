"""
تنظیمات اصلی ربات از فایل .env
با تمام متغیرهای محیطی و مقادیر پیش‌فرض
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ==================== مسیرهای اصلی ====================
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== تنظیمات ربات ====================
# نکته: اینجا عمداً exception پرتاب نمی‌کنیم. اگر مقادیر خالی باشند، تابعِ
# validate() (که در main.py صدا زده می‌شود) خطای خوانا چاپ می‌کند و برنامه با
# پیامِ راهنما (اشاره به .env.example) به‌صورتِ تمیز خارج می‌شود. اگر اینجا
# raise می‌کردیم، همون لحظه‌ی import کل برنامه با یک traceback خام کرش می‌کرد و
# مسیرِ گراسفولِ validate() هیچ‌وقت اجرا نمی‌شد (و cli.py هم بدونِ .env قابلِ
# import نمی‌بود).
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMIN_IDS: list[int] = []
for _x in os.getenv("ADMIN_IDS", "").split(","):
    _x = _x.strip()
    if not _x:
        continue
    try:
        ADMIN_IDS.append(int(_x))
    except ValueError:
        # مقدارِ نامعتبر (غیرعددی) در ADMIN_IDS نادیده گرفته می‌شود؛ در صورتِ
        # خالی‌ماندنِ کاملِ لیست، validate() خطا می‌دهد.
        logging.getLogger("repost_bot.config").warning(
            "مقدارِ نامعتبر در ADMIN_IDS نادیده گرفته شد: %r", _x
        )

TARGET_CHAT_ID_ENV = os.getenv("TARGET_CHAT_ID", "")

# ==================== تنظیمات دیتابیس ====================
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "bot.sqlite"))

# ==================== تنظیمات زمانی ====================
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tehran")

# ==================== تنظیمات همزمانی ====================
# ---------------- API اکستنشنِ مرورگر (دریافتِ پست از گروه‌های خصوصیِ تلگرام‌وب) ----------------
EXTENSION_API_ENABLED = os.getenv("EXTENSION_API_ENABLED", "false").strip().lower() in ("1", "true", "yes")
EXTENSION_API_HOST = os.getenv("EXTENSION_API_HOST", "0.0.0.0")
EXTENSION_API_PORT = int(os.getenv("EXTENSION_API_PORT", "8843"))
# توکنِ اشتراکی بینِ ربات و اکستنشن؛ چون سرور فقط IP داره (بدونِ SSL)، این توکن
# به‌صورتِ متنِ ساده روی شبکه رد و بدل میشه - این API رو فقط پشتِ فایروال/روی
# یک شبکه‌ی قابلِ‌اعتماد اجرا کن، نه رویِ اینترنتِ باز.
EXTENSION_API_TOKEN = os.getenv("EXTENSION_API_TOKEN", "")

MAX_CONCURRENT_HEAVY_JOBS = int(os.getenv("MAX_CONCURRENT_HEAVY_JOBS", "3"))

# ==================== تنظیمات کش ====================
DOWNLOAD_CACHE_MAX_ITEMS = int(os.getenv("DOWNLOAD_CACHE_MAX_ITEMS", "200"))
DOWNLOAD_CACHE_TTL_SECONDS = int(os.getenv("DOWNLOAD_CACHE_TTL_SECONDS", "1800"))
# فیکسِ C3: سقفِ بایتیِ کلِ کشِ دانلود (علاوه بر سقفِ تعداد). بدونِ این، ۲۰۰ آیتمِ
# تا ۸ مگابایتی می‌تونست تا ۱.۶ گیگابایت رم بگیره و روی VPSهای کوچیک OOM بشه.
# پیش‌فرضِ محافظه‌کارانه: ۱۵۰ مگابایت.
DOWNLOAD_CACHE_MAX_BYTES = int(os.getenv("DOWNLOAD_CACHE_MAX_BYTES", str(150 * 1024 * 1024)))
# فیکسِ C4: سقفِ سختِ حجمِ هر فایلِ دانلودی (استریمی). فایلِ بزرگ‌تر رد می‌شه تا
# رمِ پروسه با یک ویدیوی چندصد مگابایتی پر و OOM نشه.
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(60 * 1024 * 1024)))

# کشِ نتیجه‌ی داوریِ AI برای فیلترِ تبلیغات: متن‌های عیناً یکسان (که در تبلیغاتِ
# کپی‌پیستی خیلی رایجه) دیگه دوباره به Mistral/Groq فرستاده نمی‌شن - هم در
# هزینه/تاخیر صرفه‌جویی می‌شه، هم از تناقض (یه بار AD یه بار SAFE برای دقیقاً
# همون متن) جلوگیری می‌کنه. صفر یعنی کش غیرفعاله.
AD_FILTER_CACHE_MAX_ITEMS = int(os.getenv("AD_FILTER_CACHE_MAX_ITEMS", "2000"))
AD_FILTER_CACHE_TTL_SECONDS = int(os.getenv("AD_FILTER_CACHE_TTL_SECONDS", "21600"))

# ==================== تنظیمات تشخیص واترمارک ====================
TEMPLATE_MATCH_THRESHOLD = float(os.getenv("TEMPLATE_MATCH_THRESHOLD", "0.75"))
MAX_WATERMARK_AREA_RATIO = float(os.getenv("MAX_WATERMARK_AREA_RATIO", "0.3"))

# ==================== API Keys برای AI ====================
# امنیت: کلیدها فقط از متغیرِ محیطی/‏.env خوانده می‌شوند و هیچ مقدارِ پیش‌فرضِ
# واقعی در سورس هاردکد نمی‌شود. اگر خالی باشند، ماژول‌های AI به‌صورتِ graceful
# غیرفعال می‌شوند (نگاه کن به ai_router.py / image_router.py: fallback رفتار).
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ==================== API Keys برای تولید تصویر (Image Generation) ====================
# ترتیب اولویت: Pollinations -> DeepAI -> Stable Horde
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
DEEPAI_API_KEY = os.getenv("DEEPAI_API_KEY", "")
STABLEHORDE_API_KEY = os.getenv("STABLEHORDE_API_KEY", "")

# تنظیمات مربوط به تولید تصویر
IMAGE_GEN_TIMEOUT = float(os.getenv("IMAGE_GEN_TIMEOUT", "30"))
IMAGE_GEN_MAX_RETRIES = int(os.getenv("IMAGE_GEN_MAX_RETRIES", "2"))
STABLEHORDE_POLL_TIMEOUT = float(os.getenv("STABLEHORDE_POLL_TIMEOUT", "180"))
STABLEHORDE_POLL_INTERVAL = float(os.getenv("STABLEHORDE_POLL_INTERVAL", "5"))

# ==================== دایرکتوری‌ها ====================
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

WATERMARK_TEMPLATES_DIR = DATA_DIR / "watermark_templates"
WATERMARK_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

FONTS_DIR = BASE_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# دایرکتوریِ تصاویرِ نشان (Badge) واترمارک — تلگرام و اینستاگرام
BADGES_DIR = BASE_DIR / "assets" / "badges"
BADGES_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = DATA_DIR
LOG_FILE = LOG_DIR / "bot.log"

MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ==================== فایل‌های مدل ====================
SR_MODEL_PATH = MODELS_DIR / "realesr-general-x4v3.pth"
LAMA_MODEL_PATH = MODELS_DIR / "big-lama.pt"


def setup_logging() -> logging.Logger:
    """تنظیمات لاگینگ با لاگ‌فایل و خروجی کنسول"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("repost_bot")


def validate() -> list[str]:
    """بررسی تنظیمات ضروری و برگرداندن لیست خطاها"""
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN در .env تنظیم نشده است.")
    if not ADMIN_IDS:
        errors.append("ADMIN_IDS در .env تنظیم نشده است.")
    return errors