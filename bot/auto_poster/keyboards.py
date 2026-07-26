from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import db


_VALID_BTN_STYLES = {"primary", "success", "danger"}


def _btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    api_kwargs = {"style": style} if style in _VALID_BTN_STYLES else None
    return InlineKeyboardButton(text, callback_data=data, api_kwargs=api_kwargs)


# ==================== تبلیغات ====================
def ads_root_menu() -> InlineKeyboardMarkup:
    enabled = db.get_bool("ads_module_enabled", False)
    status_label = "🟢 روشن (برای خاموش‌کردن بزن)" if enabled else "🔴 خاموش (برای روشن‌کردن بزن)"
    status_style = "success" if enabled else "danger"
    return InlineKeyboardMarkup([
        [_btn(status_label, "npz:ads:toggle", style=status_style)],
        [_btn("➕ افزودن دکمه کانال جدید", "npz:ads:addbtn", style="primary")],
        [_btn("🗑 حذف/ویرایش دکمه‌ها", "npz:ads:list")],
        [_btn("✍️ ویرایش متن کپشن", "npz:ads:caption")],
        [_btn("⏱ تنظیم زمان‌بندی", "npz:ads:schedule")],
        [_btn("📡 کانال‌های مقصد", "npz:ads:targets", style="primary")],
        [_btn("▶️ انتشار دستی الآن", "npz:ads:publishnow", style="success")],
    ])


def ads_buttons_list_menu(buttons: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for b in buttons:
        rows.append([
            _btn(f"✏️ {b['name']}", f"npz:ads:editbtn:{b['id']}"),
            _btn("🗑", f"npz:ads:delbtn:{b['id']}"),
        ])
    rows.append([_btn("🔙 بازگشت", "npz:ads:root")])
    return InlineKeyboardMarkup(rows)


def ads_schedule_menu() -> InlineKeyboardMarkup:
    times = db.list_ads_schedule()
    rows = [[_btn(f"🗑 {t}", f"npz:ads:schedule:del:{t}")] for t in times]
    rows.append([_btn("➕ افزودن زمانِ جدید", "npz:ads:schedule:add")])
    rows.append([_btn("🔙 بازگشت", "npz:ads:root")])
    return InlineKeyboardMarkup(rows)


def ads_targets_menu() -> InlineKeyboardMarkup:
    targets = db.list_ads_targets()
    rows = []
    for t in targets:
        label = t.get("name") or t["chat_id"]
        rows.append([_btn(f"🗑 {label} ({t['chat_id']})", f"npz:ads:targets:del:{t['id']}")])
    rows.append([_btn("➕ افزودن کانالِ مقصدِ جدید", "npz:ads:targets:add")])
    rows.append([_btn("🔙 بازگشت", "npz:ads:root")])
    return InlineKeyboardMarkup(rows)


def back_only(data: str = "npz:ads:root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("🔙 بازگشت", data)]])
