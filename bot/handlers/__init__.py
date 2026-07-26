"""
ثبت تمام هندلرهای ربات
شامل دستورات، منوی اصلی، ورودی‌های متنی، عکس‌ها، فایل‌ها و دکمه‌های اینلاین
"""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from .menu import (
    start_command,
    main_menu_text_router,
    section_command,
    callback_router,
)
from .. import keyboards as _kb
from ..auto_poster.menu import handle_text_input as _npz_text_input
from ..manual_poster import handle_incoming_message as _manual_incoming_message
from ..manual_poster import handle_text_input as _manual_text_input
from .inputs import (
    text_input_router,
    photo_input_router,
    video_input_router,
    document_input_router,
    channel_edit_input_router,
)

log = logging.getLogger("repost_bot.handlers")


def register_handlers(application: Application) -> None:
    """
    ثبت تمام هندلرهای ربات

    شامل:
    - دستورات (/start, /menu, /stats, /sources, /destinations, /watermark,
      /footer, /format, /adfilter, /help)
    - منوی اصلی (Reply Keyboard با ۱۴ گزینه)
    - ورودی‌های متنی (تنظیمات، اعداد، متن‌ها)
    - عکس‌ها (برای تغییر عکس پست در صف تایید)
    - ویدیوها (برای تغییر کامل ویدیوی پست در صف تایید)
    - فایل‌ها (برای بازیابی بکاپ)
    - تأیید بازیابی بکاپ (کلمه "تایید")
    - دکمه‌های اینلاین (همه callback_data ها)
    """
    # ===== دستورات =====
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", section_command))
    application.add_handler(CommandHandler("stats", section_command))
    application.add_handler(CommandHandler("sources", section_command))
    application.add_handler(CommandHandler("extsources", section_command))
    application.add_handler(CommandHandler("destinations", section_command))
    application.add_handler(CommandHandler("watermark", section_command))
    application.add_handler(CommandHandler("footer", section_command))
    application.add_handler(CommandHandler("format", section_command))
    application.add_handler(CommandHandler("adfilter", section_command))
    application.add_handler(CommandHandler("help", section_command))

    # ===== منوی اصلی (Reply Keyboard) =====
    # از رجیستریِ واحدِ دکمه‌ها (kb.MAIN_MENU_REGEX) استفاده می‌شه تا هر دکمه‌ی
    # جدیدی که به MAIN_BUTTONS اضافه بشه (مثلِ «📢 تبلیغات») خودکار اینجا
    # هم شناخته بشه، بدونِ نیاز به دو جا نگه‌داشتنِ لیستِ برچسب‌ها.
    application.add_handler(MessageHandler(filters.Regex(_kb.MAIN_MENU_REGEX), main_menu_text_router))

    # ===== ورودیِ ماژول‌هایِ ایزوله‌یِ «تبلیغات» و «ارسالِ دستی» =====
    # ⚠️ نکته‌ی مهم: این دو مسیر باید در یک هندلرِ واحد ادغام بشن، نه دو
    # MessageHandlerِ جدا با فیلترِ هم‌پوشان در یک group. چرا؟ چون در
    # python-telegram-bot، داخلِ یک group فقط اولین هندلری که فیلترش match
    # بشه اجرا می‌شه (نه همه‌ی هندلرهای اون group)؛ اگه این دو تا جدا و هر دو
    # با فیلترِ TEXT & PRIVATE در group=-1 ثبت بشن، هندلرِ اولی (npz) همیشه
    # match می‌شه و جلوی چک‌شدنِ هندلرِ دومی (manual) رو می‌گیره - حتی وقتی
    # npz خودش تشخیص بده که این پیام برایِ اون نیست و False برگردونه. نتیجه:
    # وقتی ربات منتظرِ ورودیِ متنیِ ماژولِ «ارسالِ دستی» (مثلاً تاریخ/ساعتِ
    # زمان‌بندی) بود، اون ورودی هیچ‌وقت به دستِ _manual_text_input نمی‌رسید.
    # فیکس: هر دو مسیر رو به‌ترتیب داخلِ یک تابع/هندلرِ واحد امتحان می‌کنیم.
    async def _isolated_modules_gate(update, context):
        handled = False
        if update.message and update.message.text:
            handled = await _npz_text_input(update, context)
        if not handled:
            from ..custom_watermark import handle_text_input as _wmc_text_input
            from ..custom_watermark import handle_photo_input as _wmc_photo_input
            handled = await _wmc_photo_input(update, context)
            if not handled and update.message and update.message.text:
                handled = await _wmc_text_input(update, context)
        if not handled:
            handled = await _manual_incoming_message(update, context)
        if not handled and update.message and update.message.text:
            handled = await _manual_text_input(update, context)
        if handled:
            from telegram.ext import ApplicationHandlerStop
            raise ApplicationHandlerStop
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.ANIMATION |
             filters.VOICE | filters.Document.ALL) & ~filters.COMMAND & filters.ChatType.PRIVATE,
            _isolated_modules_gate,
        ),
        group=-1,
    )

    # ===== ورودی‌های متنی (فقط توی چتِ خصوصیِ ادمین/کاربر با ربات) =====
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        text_input_router
    ))

    # ===== عکس‌ها (فقط توی چتِ خصوصی) =====
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        photo_input_router
    ))

    # ===== ویدیوها (برای تغییرِ کاملِ ویدیوی پست در صف تایید، فقط توی چتِ خصوصی) =====
    application.add_handler(MessageHandler(
        filters.VIDEO & filters.ChatType.PRIVATE,
        video_input_router
    ))

    # ===== فایل‌ها (برای بازیابی بکاپ) =====
    # ⚠️ فیلترِ ChatType.PRIVATE الزامیه: بدونش این هندلر پست‌های داکیومنتِ داخلِ
    # کانال (channel_post) رو هم می‌گرفت، در حالی که برای پستِ کانال کاربری وجود
    # نداره و context.user_data برابرِ None می‌شه → کرشِ AttributeError روی
    # user_data.get("awaiting").
    application.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE,
        document_input_router
    ))

    # ===== ویرایشِ مستقیمِ کپشن/عکس/ویدیوِ پستِ در صفِ تایید، وقتی خودِ ادمین
    # مستقیماً توی کانالِ تایید (نه توی چتِ خصوصی) عکس/متن/ویدیویِ جدید رو
    # پست می‌کنه =====
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | (filters.TEXT & ~filters.COMMAND)) & filters.ChatType.CHANNEL,
        channel_edit_input_router
    ))

    # ===== دکمه‌های اینلاین (همه) =====
    application.add_handler(CallbackQueryHandler(callback_router))

    log.info("تمام هندلرها با موفقیت ثبت شدند.")