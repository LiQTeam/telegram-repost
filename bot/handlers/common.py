from __future__ import annotations

import functools
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import config

log = logging.getLogger("repost_bot.handlers")

# نشونه‌های متنیِ خطای معروفِ تلگرام برایِ callback_query: هم وقتی کوئری
# واقعاً منقضی شده (کاربر/شبکه دیر جواب داده)، هم وقتی همون کوئری قبلاً یک‌بار
# answer شده، دقیقاً همین یک پیام رو برمی‌گردونه - گمراه‌کننده‌ست ولی رفتارِ
# مستندِ خودِ تلگرامه. توی هر دو حالت، تنها اثرِ عملی اینه که پاپ‌آپِ تاییدِ
# کلیک نشون داده نمی‌شه؛ خودِ عملیاتِ اصلی (اگه قبلش/بعدش اجرا شده باشه) کاملاً
# سالم می‌مونه. پس امنه که این خطای خاص رو نادیده بگیریم، به‌جایِ این‌که کلِ
# پردازشِ آپدیت کرش کنه و به هندلرِ سراسریِ خطا برسه (که باعثِ لاگ‌شدنِ
# ترسناک + اسپمِ پیامِ «یه خطای غیرمنتظره پیش اومد» به کاربر/کانال می‌شد).
_EXPIRED_QUERY_MARKERS = (
    "query is too old",
    "query id is invalid",
    "response timeout expired",
)


def is_expired_callback_query_error(err: BaseException) -> bool:
    """تشخیصِ خطای «Query is too old and response timeout expired or query id
    is invalid» (و واریانت‌های مشابهش)."""
    msg = str(err).lower()
    return any(marker in msg for marker in _EXPIRED_QUERY_MARKERS)


async def safe_answer(query, *args, **kwargs) -> bool:
    """آنسر کردنِ امنِ callback_query. اگه کوئری منقضی شده باشه یا قبلاً یک‌بار
    answer شده باشه (تلگرام هر callback_query رو فقط یک‌بار قابلِ answer
    می‌دونه)، به‌جایِ raise کردنِ استثنا فقط لاگِ سبک می‌کنه و False برمی‌گردونه.
    خطاهای دیگه (غیرِ این موردِ خاص) دست‌نخورده raise می‌شن."""
    try:
        await query.answer(*args, **kwargs)
        return True
    except BadRequest as e:
        if is_expired_callback_query_error(e):
            log.info("کالبک‌کوئری منقضی/تکراری بود، answer نادیده گرفته شد: %s", e)
            return False
        raise


def is_admin(user_id: int | None) -> bool:
    return bool(user_id) and user_id in config.ADMIN_IDS


def is_owner(user_id: int | None) -> bool:
    if not user_id:
        return False
    from ..database import db
    return db.get_user_by_telegram_id(user_id) is not None


def is_authorized(user_id: int | None) -> bool:
    return is_admin(user_id) or is_owner(user_id)


def has_perm(user_id: int | None, key: str) -> bool:
    if not user_id:
        return False
    if is_admin(user_id):
        return True
    from ..database import db
    return db.get_permissions_by_telegram_id(user_id).get(key, False)


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user = update.effective_user
        if not is_admin(user.id if user else None):
            if update.callback_query:
                await safe_answer(
                    update.callback_query,
                    "⛔️ دسترسی نداری، این ربات فقط برای ادمین‌هاست.", show_alert=True
                )
            elif update.message:
                await update.message.reply_text("⛔️ دسترسی نداری، این ربات فقط برای ادمین‌هاست.")
            return
        return await func(update, context, *a, **kw)
    return wrapper


def authorized_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        user = update.effective_user
        if not is_authorized(user.id if user else None):
            if update.callback_query:
                await safe_answer(
                    update.callback_query,
                    "⛔️ دسترسی نداری.", show_alert=True
                )
            elif update.message:
                await update.message.reply_text("⛔️ دسترسی نداری.")
            return
        return await func(update, context, *a, **kw)
    return wrapper


def scope_owner(user_id: int | None) -> int | None:
    """برای تنظیماتِ مختصِ کاربر (واترمارک/امضا/قالب‌بندی): آیدیِ داخلیِ کاربر
    (owner_user_id) رو برمی‌گردونه تا هرکس فقط تنظیماتِ خودش رو ببینه/تغییر بده.
    برای ادمین (که تنظیماتش سراسری/بخشِ ادمینه) None برمی‌گردونه."""
    if not user_id or is_admin(user_id):
        return None
    from ..database import db
    u = db.get_user_by_telegram_id(user_id)
    return u["id"] if u else None


async def safe_edit(query, text: str, reply_markup=None, parse_mode=None):
    """ویرایشِ امنِ پیام: اگه پیام عکس/ویدیو/فایل باشه (کپشن داره، نه متن)،
    باید edit_message_caption صدا زده بشه وگرنه تلگرام ارورِ
    «There is no text in the message to edit» می‌ده."""
    msg = query.message
    is_media = bool(msg) and bool(
        msg.photo or msg.video or msg.document or msg.animation or msg.audio or msg.voice
    )
    try:
        if is_media:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        if "There is no text in the message to edit" in err:
            try:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                return
            except BadRequest as e2:
                if "Message is not modified" in str(e2):
                    return
                raise
        if "There is no caption in the message to edit" in err:
            try:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
                return
            except BadRequest as e2:
                if "Message is not modified" in str(e2):
                    return
                raise
        raise