from __future__ import annotations

import functools
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .. import config

log = logging.getLogger("repost_bot.handlers")


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
                await update.callback_query.answer(
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
                await update.callback_query.answer(
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