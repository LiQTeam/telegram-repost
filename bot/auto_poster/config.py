"""
تنظیمات و ثابت‌های ماژول «تبلیغات» (auto_poster).

این ماژول کاملاً ایزوله از هسته‌ی ربات ری‌پسته:
- دیتابیس مجزا: data/auto_poster.db
- کدها همگی زیرِ bot/auto_poster/
- هیچ وابستگی‌ای به bot/database.py یا کش/دیتابیسِ اصلی نداره

⚠️ نکته: این ماژول قبلاً شاملِ زیرسیستمِ «قیمت‌ها» (اسکرِیپِ tgju.org + رندرِ
عکسِ گرافیکی) هم بود؛ طبقِ درخواستِ کاربر، اون بخش (کد، HTML/CSS/فونت/آیکون‌ها،
جدول‌های دیتابیس) کاملاً حذف شد و فقط زیرسیستمِ تبلیغات باقی مونده.
"""
from __future__ import annotations

from pathlib import Path

from .. import config as _core_config

# ==================== مسیرها ====================
PKG_DIR = Path(__file__).resolve().parent

DATA_DIR = _core_config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "auto_poster.db"

# ==================== پیش‌فرض‌های تبلیغات ====================
DEFAULT_ADS_CAPTION = (
    "🔥 <b>کانال‌های پیشنهادی</b>\n"
    "این کانال‌ها رو حتماً چک کن، محتوای باکیفیت و به‌روز 👇"
)
