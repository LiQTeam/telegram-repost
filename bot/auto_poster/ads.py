"""
ماژولِ «تبلیغات و تبادلات».

ساختارِ پیام: یک کپشنِ قابلِ‌ویرایش در بالا + دکمه‌های شیشه‌ای (۲ تا در هر
ردیف) که هرکدوم به یک کانال/لینکِ دلخواه وصلن. این پیام به همه‌ی کانال‌های
مقصدِ ثبت‌شده (جدولِ ads_targets) به‌صورتِ هم‌زمان فرستاده می‌شه.
"""
from __future__ import annotations

import logging

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from . import config, db

log = logging.getLogger("repost_bot.auto_poster.ads")


def build_markup() -> InlineKeyboardMarkup | None:
    buttons = db.list_ads_buttons()
    if not buttons:
        return None
    # ساختِ کیبورد با رنگ (طبقِ button_config.ADS_DEFAULT_COLOR یا رنگِ ذخیره‌شده‌ی
    # هر دکمه اگه داشته باشه). ۲ دکمه در هر ردیف.
    from ..button_style import build_ads_markup
    return build_ads_markup(buttons)


async def publish_now(bot: Bot, chat_id: int | str | None = None) -> bool:
    """
    ارسالِ فوریِ پیامِ تبلیغاتی به همه‌ی کانال‌های مقصدِ ثبت‌شده (ads_targets).
    اگه chat_id صراحتاً پاس داده بشه، فقط همون یکی هدف قرار می‌گیره؛ در غیرِ
    این صورت به‌صورتِ پیش‌فرض به همه‌ی کانال‌های ثبت‌شده می‌فرسته. خطای هر کانال
    جداگانه لاگ می‌شه و باعثِ توقفِ ارسال به بقیه‌ی کانال‌ها نمی‌شه.

    خروجی: True فقط اگه ارسال به *همه‌ی* مقصدها موفق باشه.
    """
    caption = db.get_setting("ads_caption_text", config.DEFAULT_ADS_CAPTION)
    markup = build_markup()
    if markup is None:
        db.add_log("WARNING", "انتشارِ تبلیغ لغو شد: هیچ دکمه‌ای ثبت نشده.")
        return False

    if chat_id is not None:
        targets = [{"chat_id": str(chat_id), "name": None}]
    else:
        targets = db.list_ads_targets()

    if not targets:
        db.add_log("WARNING", "انتشارِ تبلیغ لغو شد: هیچ کانالِ مقصدی ثبت نشده.")
        return False

    all_ok = True
    for target in targets:
        target_chat_id = target["chat_id"]
        label = target.get("name") or target_chat_id
        try:
            await bot.send_message(
                chat_id=target_chat_id, text=caption, parse_mode=ParseMode.HTML,
                reply_markup=markup, disable_web_page_preview=True,
            )
            db.add_log("INFO", f"پیامِ تبلیغاتی با موفقیت به «{label}» ارسال شد.")
        except TelegramError as e:
            log.exception("خطای تلگرام هنگامِ ارسالِ تبلیغ به %s: %s", label, e)
            db.add_log("ERROR", f"خطای ارسالِ تبلیغ به «{label}»: {e}")
            all_ok = False
        except Exception as e:  # noqa: BLE001
            log.exception("خطای غیرمنتظره هنگامِ ارسالِ تبلیغ به %s: %s", label, e)
            db.add_log("ERROR", f"خطای غیرمنتظره در ارسالِ تبلیغ به «{label}»: {e}")
            all_ok = False

    return all_ok
