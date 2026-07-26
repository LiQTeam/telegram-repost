"""
سازنده‌های دکمه‌ی رنگی (وابسته به تلگرام).

رنگِ دکمه (style) از Bot API 9.4 اضافه شده و کتابخونه‌ی فعلی
(python-telegram-bot 21.6) اون رو مدل نکرده؛ برای همین رنگ رو از راهِ api_kwargs
مستقیم به تلگرام تزریق می‌کنیم. to_dict() محتوای api_kwargs رو داخلِ خروجی merge
می‌کنه، پس بدونِ آپدیتِ کتابخونه هم کار می‌کنه و هیچ نصبِ جدیدی لازم نیست.
"""
from __future__ import annotations

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import button_config as bc
from .jdatetime_utils import TEHRAN_TZ

log = logging.getLogger("repost_bot.button_style")

# غیرفعال‌سازیِ موقتِ رنگِ دکمه‌ها: وقتی False باشه، هیچ دکمه‌ای (نه در ریپست، نه
# تبلیغات، نه منوها) رنگی نمی‌شه؛ خودِ دکمه‌ها (متن/لینک/کال‌بک) دست‌نخورده کار
# می‌کنن. برای غیرفعال کردنِ موقت (مثلاً برای دیباگ)، فقط این مقدار رو False کن.
COLORED_BUTTONS_ENABLED = True

# غیرفعال‌سازیِ کلِ دکمه‌های زیرِ پستِ ریپست: وقتی False باشه، هیچ دکمه‌ای زیرِ
# پست‌های ریپست‌شده گذاشته نمی‌شه (نه از button_config، نه رنگی). تبلیغات و منوها
# تحتِ تأثیر قرار نمی‌گیرن. برای فعال کردنِ دوباره، فقط این مقدار رو True کن.
REPOST_BUTTONS_ENABLED = False


def colored_button(
    text: str,
    *,
    url: str | None = None,
    callback_data: str | None = None,
    color: str | None = None,
    web_app=None,
    login_url=None,
    switch_inline_query: str | None = None,
    switch_inline_query_current_chat: str | None = None,
) -> InlineKeyboardButton:
    """یک دکمه‌ی اینلاین با رنگِ دلخواه می‌سازه. color یکی از
    primary/danger/success یا None. رنگ از راهِ api_kwargs تزریق می‌شه.
    اگه COLORED_BUTTONS_ENABLED غیرفعال باشه، رنگ نادیده گرفته می‌شه.

    پارامترهای web_app/login_url/switch_inline_query(_current_chat) اختیاری‌ان
    و فقط برای آماده‌بودنِ آینده اضافه شدن (امروز جایی از پروژه استفاده‌شون
    نمی‌کنه)؛ هیچ‌کدوم روی رفتارِ فعلیِ callback_data/url اثر نمی‌ذارن."""
    if not COLORED_BUTTONS_ENABLED:
        color = None
    api_kwargs = {"style": color} if color in bc.VALID_COLORS else None
    return InlineKeyboardButton(
        text=text,
        url=url,
        callback_data=callback_data,
        web_app=web_app,
        login_url=login_url,
        switch_inline_query=switch_inline_query,
        switch_inline_query_current_chat=switch_inline_query_current_chat,
        api_kwargs=api_kwargs,
    )


def colored_reply_button(text: str, color: str | None = None):
    """یک KeyboardButton (دکمه‌ی کیبوردِ رِپلای، همون کیبوردِ ثابتِ پایینِ صفحه)
    با رنگِ دلخواه می‌سازه. مثلِ colored_button بالا، ولی برای دکمه‌های رِپلای —
    از Bot API 9.4 به بعد این دکمه‌ها هم فیلدِ style رو می‌پذیرن. اگه
    COLORED_BUTTONS_ENABLED غیرفعال باشه، رنگ نادیده گرفته می‌شه."""
    from telegram import KeyboardButton
    if not COLORED_BUTTONS_ENABLED:
        color = None
    api_kwargs = {"style": color} if color in bc.VALID_COLORS else None
    return KeyboardButton(text, api_kwargs=api_kwargs)


def _current_tehran_hour() -> int:
    return datetime.now(TEHRAN_TZ).hour


def build_repost_markup(chat_id, post_text: str | None) -> InlineKeyboardMarkup | None:
    """کیبوردِ دکمه‌های زیرِ یک پستِ مقصد رو بر اساسِ تنظیماتِ button_config می‌سازه.
    اگه این مقصد غیرفعاله، یا الان خارجِ بازه‌ی ساعتیه، یا پست نشانه‌ی «دکمه نذار»
    داره، یا هیچ دکمه‌ی معتبری تعریف نشده، یا REPOST_BUTTONS_ENABLED خاموش باشه
    → None برمی‌گردونه (یعنی دکمه نذار)."""
    if not REPOST_BUTTONS_ENABLED:
        return None
    cfg = bc.resolve_repost_config(chat_id)
    if not cfg or not cfg.get("enabled", True):
        return None
    if bc.has_no_button_marker(post_text):
        return None
    if not bc.within_time_window(cfg.get("time_window"), _current_tehran_hour()):
        return None

    buttons = bc.sanitized_repost_buttons(cfg)
    if not buttons:
        return None

    per_row = max(1, min(4, int(getattr(bc, "REPOST_BUTTONS_PER_ROW", 1) or 1)))
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        row.append(colored_button(b["text"], url=b["url"], color=b["color"]))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def build_ads_markup(buttons: list[dict]) -> InlineKeyboardMarkup | None:
    """کیبوردِ تبلیغات رو با رنگ می‌سازه. هر دکمه {"name","url"} و اختیاری "color".
    اگه دکمه‌ای رنگِ خودش رو نداشته باشه، ADS_DEFAULT_COLOR روش می‌شینه. ۲ دکمه در
    هر ردیف (مثلِ قبل)."""
    if not buttons:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        name = b.get("name") or b.get("text") or ""
        url = b.get("url") or ""
        if not name or not url:
            continue
        color = b.get("color") or bc.ADS_DEFAULT_COLOR
        row.append(colored_button(name, url=url, color=color))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None


def _recolor_button(btn: InlineKeyboardButton, color: str) -> InlineKeyboardButton:
    """یک نسخه‌ی رنگیِ تازه از یک دکمه‌ی منو می‌سازه. فقط دکمه‌های ساده
    (callback_data یا url) بازسازی می‌شن؛ بقیه (web_app، login_url و...) دست‌نخورده
    برمی‌گردن تا چیزی خراب نشه."""
    if btn.callback_data is not None:
        return colored_button(btn.text, callback_data=btn.callback_data, color=color)
    if btn.url is not None:
        return colored_button(btn.text, url=btn.url, color=color)
    return btn


def apply_menu_colors(markup):
    """رنگِ دکمه‌های یک منو رو طبقِ MENU_BUTTON_COLORS اعمال می‌کنه و یک markup تازه
    برمی‌گردونه. اگه رنگی تعریف نشده یا markup اینلاین نیست، همون ورودی برمی‌گرده.
    هیچ‌وقت استثنا پرت نمی‌کنه (منو نباید به‌خاطرِ رنگ خراب شه)."""
    try:
        if markup is None or not isinstance(markup, InlineKeyboardMarkup):
            return markup
        if not bc.MENU_BUTTON_COLORS:
            return markup
        changed = False
        new_rows = []
        for row in markup.inline_keyboard:
            new_row = []
            for btn in row:
                color = bc.style_for_callback(btn.callback_data, btn.text)
                if color and (btn.callback_data is not None or btn.url is not None):
                    new_btn = _recolor_button(btn, color)
                    new_row.append(new_btn)
                    if new_btn is not btn:
                        changed = True
                else:
                    new_row.append(btn)
            new_rows.append(new_row)
        return InlineKeyboardMarkup(new_rows) if changed else markup
    except Exception as e:  # noqa: BLE001
        log.debug("اعمالِ رنگِ منو ناموفق بود (نادیده گرفته شد): %s", e)
        return markup


def install_menu_colors(module) -> None:
    """همه‌ی توابعِ یک ماژولِ کیبورد رو طوری wrap می‌کنه که اگه خروجی‌شون
    InlineKeyboardMarkup بود، از فیلترِ رنگ رد بشه. این‌طوری بدونِ دست‌زدن به تک‌تکِ
    توابع، رنگِ منوها به‌صورتِ مرکزی اعمال می‌شه."""
    import functools
    import inspect

    for name, obj in list(vars(module).items()):
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue  # فقط توابعِ خودِ همین ماژول، نه import‌شده‌ها

        def _make_wrapper(func):
            @functools.wraps(func)
            def _wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                if isinstance(result, InlineKeyboardMarkup):
                    return apply_menu_colors(result)
                return result
            return _wrapper

        setattr(module, name, _make_wrapper(obj))
