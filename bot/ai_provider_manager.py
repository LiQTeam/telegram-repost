"""
مدیریتِ کاملِ سرویس‌هایِ هوش مصنوعی (Mistral، Groq، Gemini، HuggingFace) با
پشتیبانیِ چندکلیدی: اعتبارسنجیِ واقعیِ کلید، مسیریابیِ وظایف با Fallback،
آمار، فراخوانیِ متن/تصویر.

هر Provider حالا می‌تونه تا ۵ کلیدِ API داشته باشه (مثلاً ۵ اکانتِ جداگانه‌ی
Gemini). فراخوانی‌ها به‌طورِ چرخشی (round-robin) بینِ کلیدهایِ فعال پخش
می‌شن؛ وقتی یک کلید به Quota می‌خوره، همون لحظه (بدونِ برگردوندنِ خطا به
کاربر) به کلیدِ بعدی سوییچ می‌شه، و اون کلید تا مدتی (KEY_COOLDOWN_SECONDS)
از چرخه کنار گذاشته می‌شه تا خودش برگرده. این منطق در یک نقطه‌ی مرکزی
(call_text / call_image) پیاده شده و همه‌ی وظایف (فیلترِ هوشمند، خلاصه‌سازی،
بازنویسی، ترجمه، تولیدِ تصویر، چت و ...) که از طریقِ ai_router.py /
image_router.py می‌رن، خودکار از این چرخش بهره‌مند می‌شن.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from . import ai_adapters as adapters
from . import ai_catalog as cat
from . import ai_crypto as crypto
from . import config as cfg
from .ai_errors import (
    AuthError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)
from .database import db

log = logging.getLogger("repost_bot.ai_provider_manager")

# بعدِ خوردن به Quota (429)، کلید به مدتِ ۱۵ دقیقه از چرخه کنار گذاشته می‌شه و
# بعدش خودکار دوباره امتحان می‌شه (خیلی از سرویس‌ها rate-limit رو دقیقه‌ای/
# ساعتی ریست می‌کنن، نه فقط روزانه).
KEY_COOLDOWN_SECONDS = 15 * 60
MAX_KEYS_PER_SERVICE = db.MAX_AI_KEYS_PER_SERVICE


class ProviderCallError(Exception):
    """خطای طبقه‌بندی‌شده هنگامِ فراخوانیِ یک Provider."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # 'invalid' | 'quota' | 'connection' | 'other'


def _map_provider_error(e: ProviderError) -> ProviderCallError:
    if isinstance(e, AuthError):
        return ProviderCallError("invalid", str(e))
    if isinstance(e, RateLimitError):
        return ProviderCallError("quota", str(e))
    if isinstance(e, (ProviderTimeoutError, ServerError)):
        return ProviderCallError("connection", str(e))
    return ProviderCallError("other", str(e))


def _status_from_error(e: ProviderError) -> tuple[str, str]:
    if isinstance(e, AuthError):
        return cat.STATUS_INVALID, str(e)
    if isinstance(e, RateLimitError):
        return cat.STATUS_QUOTA_EXCEEDED, str(e)
    if isinstance(e, ProviderTimeoutError):
        return cat.STATUS_CONNECTION_ERROR, "Timeout در اتصال به سرویس"
    if isinstance(e, ServerError):
        return cat.STATUS_CONNECTION_ERROR, str(e)
    return cat.STATUS_CONNECTION_ERROR, str(e)


# ────────────────────────────────────────────────────────────────────────────
# تشخیصِ سریعِ «کلیدِ سرویسِ اشتباه» (بدونِ round-trip)
# ────────────────────────────────────────────────────────────────────────────

def _detect_wrong_service(service_id: str, raw_key: str) -> bool:
    raw = (raw_key or "").strip()
    if not raw:
        return False
    best_len = -1
    matched_ids: set[str] = set()
    for provider in cat.PROVIDERS.values():
        for prefix in provider.key_prefixes:
            if raw.startswith(prefix):
                if len(prefix) > best_len:
                    best_len = len(prefix)
                    matched_ids = {provider.id}
                elif len(prefix) == best_len:
                    matched_ids.add(provider.id)
    if best_len == -1:
        return False
    return service_id not in matched_ids


# ────────────────────────────────────────────────────────────────────────────
# اعتبارسنجیِ واقعی
# ────────────────────────────────────────────────────────────────────────────

async def validate_provider(service_id: str, raw_key: str) -> tuple[str, str]:
    """خروجی: (status, status_detail)"""
    info = cat.get_provider(service_id)
    if not info:
        return cat.STATUS_INVALID, "سرویسِ ناشناخته"

    raw_key = (raw_key or "").strip()
    if not raw_key:
        return cat.STATUS_NOT_SET, ""

    if raw_key and _detect_wrong_service(service_id, raw_key):
        return cat.STATUS_WRONG_SERVICE, f"فرمتِ این کلید متعلق به سرویسِ دیگری‌ست، نه {info.label}"

    # برایِ validate همیشه از text adapter استفاده می‌کنیم
    # (image adapter همان کلید رو چک می‌کنه؛ جداگانه نیاز نیست)
    adapter = adapters.get_text_adapter(service_id)
    if adapter is None:
        return cat.STATUS_INVALID, "آداپترِ این سرویس یافت نشد"

    VALIDATE_TIMEOUT = 12.0
    try:
        await asyncio.wait_for(adapter.validate(raw_key), timeout=VALIDATE_TIMEOUT)
        return cat.STATUS_ACTIVE, ""
    except asyncio.TimeoutError:
        return cat.STATUS_CONNECTION_ERROR, f"اعتبارسنجی بعد از {VALIDATE_TIMEOUT:.0f} ثانیه پاسخ نداد"
    except ProviderError as e:
        return _status_from_error(e)
    except Exception as e:
        log.warning("validate_provider(%s) خطایِ غیرمنتظره: %s", service_id, e)
        return cat.STATUS_CONNECTION_ERROR, f"{e.__class__.__name__}: {e}"


# ────────────────────────────────────────────────────────────────────────────
# CRUD چندکلیدی
# ────────────────────────────────────────────────────────────────────────────

def list_keys(owner_user_id: Optional[int], service_id: str) -> list:
    """لیستِ همه‌ی کلیدهایِ ثبت‌شده برایِ این سرویس (بر اساسِ slot، صعودی)."""
    return db.ai_list_keys(owner_user_id, service_id)


def key_count(owner_user_id: Optional[int], service_id: str) -> int:
    return len(db.ai_list_keys(owner_user_id, service_id))


async def add_key(owner_user_id: Optional[int], service_id: str, raw_key: str) -> tuple[Optional[int], str, str]:
    """کلیدِ جدید رو اعتبارسنجی و در اولین slotِ خالی ثبت می‌کنه.
    خروجی: (slot یا None اگه پر بود, status, detail)"""
    if key_count(owner_user_id, service_id) >= MAX_KEYS_PER_SERVICE:
        return None, cat.STATUS_INVALID, f"حداکثر {MAX_KEYS_PER_SERVICE} کلید به‌ازایِ هر سرویس قابلِ ثبته."
    status, detail = await validate_provider(service_id, raw_key)
    slot = db.ai_add_key(owner_user_id, service_id, crypto.encrypt_text(raw_key), status, detail)
    if slot is None:
        return None, cat.STATUS_INVALID, f"حداکثر {MAX_KEYS_PER_SERVICE} کلید به‌ازایِ هر سرویس قابلِ ثبته."
    return slot, status, detail


async def retest_key(owner_user_id: Optional[int], service_id: str, slot: int) -> tuple[str, str]:
    row = db.ai_get_key(owner_user_id, service_id, slot)
    if not row or not row["api_key_encrypted"]:
        return cat.STATUS_NOT_SET, ""
    raw_key = crypto.decrypt_text(row["api_key_encrypted"])
    if not raw_key:
        db.ai_update_key_status(owner_user_id, service_id, slot, cat.STATUS_INVALID, "رمزگشاییِ کلیدِ ذخیره‌شده ناموفق بود")
        return cat.STATUS_INVALID, "رمزگشاییِ کلیدِ ذخیره‌شده ناموفق بود"
    db.ai_update_key_status(owner_user_id, service_id, slot, cat.STATUS_CHECKING)
    status, detail = await validate_provider(service_id, raw_key)
    # retestِ دستی یعنی کاربر صراحتاً می‌خواد این کلید دوباره امتحان بشه؛
    # cooldown هم پاک می‌شه (حتی اگه هنوز quota_exceeded باشه، cooldown_until خالی می‌شه).
    db.ai_update_key_status(owner_user_id, service_id, slot, status, detail, cooldown_until="")
    return status, detail


async def retest_all_keys(owner_user_id: Optional[int], service_id: str) -> list[tuple[int, str, str]]:
    rows = db.ai_list_keys(owner_user_id, service_id)
    out = []
    for row in rows:
        status, detail = await retest_key(owner_user_id, service_id, row["slot"])
        out.append((row["slot"], status, detail))
    return out


# ────────────────────────────────────────────────────────────────────────────
# وضعیتِ زنده‌ی همه‌ی موتورها (تستِ واقعیِ هر کلیدِ هر سرویس)
# ────────────────────────────────────────────────────────────────────────────
# ⚠️ چرا اینجا و نه در ai_router: نسخه‌های قبلی «وضعیتِ زنده» فقط Groq و
# Mistralِ .env را تست می‌کرد، یعنی Gemini و HuggingFace و کلاً کلیدهایِ
# شخصی‌ای که از منویِ «مدیریتِ API» ثبت شده بودند اصلاً دیده نمی‌شدند و
# آیکونِ صفحه‌ی مدیریت با نتیجه‌ی تستِ زنده هم‌خوان نبود. حالا این تابع
# تک‌منبعِ حقیقتِ «وضعیت» است: همه‌ی سرویس‌هایِ کاتالوگ × همه‌ی کلیدهاشون.

# سقفِ زمانیِ کلِ گزارش. هر کلید خودش تا ۱۲ ثانیه (VALIDATE_TIMEOUT) وقت دارد
# و همه موازی تست می‌شوند، پس این سقف فقط برایِ حالتِ فاجعه (شبکه‌ی کاملاً
# قفل) است تا کاربر پشتِ یک پیامِ «در حال تست…» گیر نکند.
LIVE_STATUS_TOTAL_TIMEOUT = 25.0

# کلیدِ .env هر سرویس (اگر داشته باشد). Gemini/HuggingFace کلیدِ .env ندارند و
# فقط از طریقِ منویِ «مدیریتِ API» تنظیم می‌شوند.
_ENV_RAW_KEY_GETTERS = {
    "mistral": lambda: getattr(cfg, "MISTRAL_API_KEY", "") or "",
    "groq": lambda: getattr(cfg, "GROQ_API_KEY", "") or "",
}


async def _live_check_one(
    owner_user_id: Optional[int], service_id: str, slot: Optional[int], raw_key: str, source: str,
) -> dict:
    """یک کلید را واقعاً تست می‌کند و (برایِ کلیدهایِ ذخیره‌شده) وضعیتِ جدید را
    در دیتابیس هم می‌نویسد تا آیکونِ صفحه‌ی «مدیریتِ API» با همین نتیجه یکی شود."""
    status, detail = await validate_provider(service_id, raw_key)
    if source == "key" and slot is not None:
        try:
            # اگر همین الان به Quota خورده، مثلِ مسیرِ عادیِ فراخوانی یک
            # cooldown واقعی می‌گذاریم؛ وگرنه cooldownِ قبلی پاک می‌شود چون
            # این یک تستِ زنده و صریح است و کلیدی که دوباره جواب می‌دهد نباید
            # تا پایانِ کولداونِ قدیمی کنار بماند.
            # ⚠️ بدونِ این تفکیک، _aggregate_status کلیدِ quota-خورده‌ای که
            # cooldownش خالی شده را «فعال» حساب می‌کرد و آیکونِ صفحه‌ی مدیریت
            # 🟢 می‌شد، درست برخلافِ چیزی که همین گزارش تازه نشان داده بود.
            cooldown = (
                str(time.time() + KEY_COOLDOWN_SECONDS)
                if status == cat.STATUS_QUOTA_EXCEEDED else ""
            )
            db.ai_update_key_status(owner_user_id, service_id, slot, status, detail, cooldown_until=cooldown)
        except Exception as e:  # noqa: BLE001 - نوشتنِ وضعیت نباید کلِ گزارش را بترکاند
            log.warning("ثبتِ وضعیتِ زنده‌ی %s/slot%s ناموفق بود: %s", service_id, slot, e)
    return {"slot": slot, "source": source, "status": status, "detail": detail}


async def live_status_report(owner_user_id: Optional[int]) -> list[dict]:
    """تستِ زنده‌ی **همه‌ی** سرویس‌هایِ کاتالوگ و **همه‌ی** کلیدهایشان، به‌صورتِ موازی.

    خروجی، به ترتیبِ کاتالوگ، برایِ هر سرویس یک dict:
        {
          "info":    ProviderInfo,
          "checks":  [{"slot", "source", "status", "detail"}, ...],
          "overall": یکی از cat.STATUS_*,
        }
    اگر سرویسی نه کلیدِ ذخیره‌شده داشته باشد و نه کلیدِ .env، هیچ تستی برایش
    زده نمی‌شود و overall برابرِ STATUS_NOT_SET است (نه «خطا» — نبودِ کلید
    خرابی نیست).
    """
    providers = cat.all_providers()

    # ۱) فهرستِ همه‌ی تست‌هایِ لازم را جمع می‌کنیم (بدونِ هیچ فراخوانیِ شبکه‌ای)
    plan: list[tuple[str, Optional[int], str, str]] = []  # (service_id, slot, raw_key, source)
    empty_slots: dict[str, list[dict]] = {}
    for info in providers:
        empty_slots.setdefault(info.id, [])
        rows = db.ai_list_keys(owner_user_id, info.id)
        for row in rows:
            enc = row["api_key_encrypted"]
            raw = crypto.decrypt_text(enc) if enc else ""
            if raw:
                plan.append((info.id, row["slot"], raw, "key"))
            else:
                # کلیدی ثبت شده ولی رمزگشایی نشد (فایلِ سکرت عوض شده) — این
                # خودش یک وضعیتِ واقعی است و باید در گزارش دیده شود.
                empty_slots[info.id].append({
                    "slot": row["slot"], "source": "key",
                    "status": cat.STATUS_INVALID,
                    "detail": "رمزگشاییِ کلیدِ ذخیره‌شده ناموفق بود",
                })
        if not rows:
            env_key = (_ENV_RAW_KEY_GETTERS.get(info.id) or (lambda: ""))()
            if env_key:
                plan.append((info.id, None, env_key, "env"))

    # ۲) همه‌ی تست‌ها با هم (نه پشتِ سرِ هم) — ۴ سرویس × تا ۵ کلید سریالی
    #    می‌توانست چند دقیقه طول بکشد.
    async def _guarded(service_id, slot, raw, source):
        try:
            return await _live_check_one(owner_user_id, service_id, slot, raw, source)
        except Exception as e:  # noqa: BLE001
            log.warning("تستِ زنده‌ی %s/slot%s خطا داد: %s", service_id, slot, e)
            return {"slot": slot, "source": source,
                    "status": cat.STATUS_CONNECTION_ERROR, "detail": f"{e.__class__.__name__}: {e}"}

    results: list[dict] = []
    if plan:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*(_guarded(*item) for item in plan)),
                timeout=LIVE_STATUS_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning("گزارشِ وضعیتِ زنده از سقفِ %.0f ثانیه رد شد.", LIVE_STATUS_TOTAL_TIMEOUT)
            results = [{"slot": slot, "source": source,
                        "status": cat.STATUS_CONNECTION_ERROR, "detail": "پاسخ در زمانِ مقرر نرسید"}
                       for _sid, slot, _raw, source in plan]

    # ۳) نتیجه‌ها را به سرویسِ خودشان برمی‌گردانیم
    by_service: dict[str, list[dict]] = {info.id: list(empty_slots[info.id]) for info in providers}
    for (service_id, _slot, _raw, _source), res in zip(plan, results):
        by_service[service_id].append(res)

    report = []
    for info in providers:
        checks = sorted(by_service[info.id], key=lambda c: (c["slot"] is None, c["slot"] or 0))
        if checks:
            overall = next(
                (s for s in _STATUS_PRIORITY if any(c["status"] == s for c in checks)),
                cat.STATUS_NOT_SET,
            )
        else:
            overall = cat.STATUS_NOT_SET
        report.append({"info": info, "checks": checks, "overall": overall})
    return report


def delete_key(owner_user_id: Optional[int], service_id: str, slot: int) -> None:
    db.ai_delete_key(owner_user_id, service_id, slot)


def delete_all_keys(owner_user_id: Optional[int], service_id: str) -> None:
    for row in db.ai_list_keys(owner_user_id, service_id):
        db.ai_delete_key(owner_user_id, service_id, row["slot"])


# ────────────────────────────────────────────────────────────────────────────
# Fallbackِ سراسریِ .env
# ────────────────────────────────────────────────────────────────────────────

_ENV_FALLBACK_CHECKS = {
    "mistral": lambda: bool(cfg.MISTRAL_API_KEY),
    "groq":    lambda: bool(cfg.GROQ_API_KEY),
}


def _has_env_fallback(service_id: str) -> bool:
    check = _ENV_FALLBACK_CHECKS.get(service_id)
    return bool(check and check())


def _resolve_unset_status(service_id: str) -> str:
    return cat.STATUS_FALLBACK if _has_env_fallback(service_id) else cat.STATUS_NOT_SET


# ترتیبِ اولویت برایِ تجمیعِ وضعیتِ چند کلید در یک وضعیتِ کلی برایِ سرویس
_STATUS_PRIORITY = [
    cat.STATUS_ACTIVE,
    cat.STATUS_CHECKING,
    cat.STATUS_QUOTA_EXCEEDED,
    cat.STATUS_CONNECTION_ERROR,
    cat.STATUS_WRONG_SERVICE,
    cat.STATUS_INVALID,
    cat.STATUS_NOT_SET,
]


def _cooldown_active(row) -> bool:
    cd = row["cooldown_until"] if row and "cooldown_until" in row.keys() else ""
    if not cd:
        return False
    try:
        return time.time() < float(cd)
    except (TypeError, ValueError):
        return False


def _aggregate_status(rows: list) -> str:
    if not rows:
        return cat.STATUS_NOT_SET
    present = set()
    for r in rows:
        st = r["status"]
        if st == cat.STATUS_QUOTA_EXCEEDED and not _cooldown_active(r):
            # کولداون تموم شده؛ برایِ نمایش به‌عنوانِ «فعال منتظرِ retry» در نظر می‌گیریم
            st = cat.STATUS_ACTIVE
        present.add(st)
    for candidate in _STATUS_PRIORITY:
        if candidate in present:
            return candidate
    return cat.STATUS_NOT_SET


def get_status(owner_user_id: Optional[int], service_id: str) -> str:
    rows = db.ai_list_keys(owner_user_id, service_id)
    if not rows:
        return _resolve_unset_status(service_id)
    return _aggregate_status(rows)


def list_status(owner_user_id: Optional[int], category: str | None = None) -> list[tuple[cat.ProviderInfo, str]]:
    """
    لیستِ تمامِ Providerها (یا فیلترشده بر اساسِ capability) با وضعیتِ کلیشون
    (تجمیع‌شده از رویِ همه‌ی کلیدهایِ ثبت‌شده‌ی هر سرویس).
    """
    providers = (
        cat.providers_by_category(category) if category
        else cat.all_providers()
    )
    return [(info, get_status(owner_user_id, info.id)) for info in providers]


def get_stats_text(owner_user_id: Optional[int], service_id: str) -> str:
    """آمارِ تجمیعیِ همه‌ی کلیدهایِ این سرویس."""
    rows = db.ai_list_keys(owner_user_id, service_id)
    info = cat.get_provider(service_id)
    label = info.label if info else service_id
    if not rows:
        return f"📊 {label}: هنوز هیچ کلیدی ثبت نشده."
    total  = sum(r["total_requests"] or 0 for r in rows)
    errors = sum(r["total_errors"] or 0 for r in rows)
    resp_ms = sum(r["total_response_ms"] or 0 for r in rows)
    avg_ms = int(resp_ms / total) if total else 0
    ok = total - errors
    last_used = max((r["last_used_at"] or "" for r in rows), default="") or "—"
    return (
        f"📊 <b>{label}</b>  ({len(rows)} کلید)\n"
        f"• تعداد درخواست‌ها: {total}\n"
        f"• موفق: {ok} | خطا: {errors}\n"
        f"• میانگین زمانِ پاسخ: {avg_ms} ms\n"
        f"• آخرین استفاده: {last_used}"
    )


def get_key_stats_text(owner_user_id: Optional[int], service_id: str, slot: int) -> str:
    row = db.ai_get_key(owner_user_id, service_id, slot)
    info = cat.get_provider(service_id)
    label = info.label if info else service_id
    if not row:
        return f"📊 {label} — کلیدِ #{slot}: یافت نشد."
    total  = row["total_requests"] or 0
    errors = row["total_errors"]   or 0
    avg_ms = int(row["total_response_ms"] / total) if total else 0
    ok = total - errors
    return (
        f"📊 <b>{label} — کلیدِ #{slot}</b>\n"
        f"• وضعیت: {cat.STATUS_LABELS.get(row['status'], row['status'])}\n"
        f"• تعداد درخواست‌ها: {total}\n"
        f"• موفق: {ok} | خطا: {errors}\n"
        f"• میانگین زمانِ پاسخ: {avg_ms} ms\n"
        f"• آخرین استفاده: {row['last_used_at'] or '—'}\n"
        f"• آخرین بررسیِ اتصال: {row['last_checked_at'] or '—'}"
    )


# backward-compat: کدهایِ قدیمی‌تر ممکنه این نام‌ها رو صدا بزنن
async def set_and_validate_key(owner_user_id: Optional[int], service_id: str, raw_key: str) -> tuple[str, str]:
    """Alias برای add_key (سازگاریِ عقب‌رو) — همیشه به‌عنوانِ کلیدِ جدید اضافه می‌کنه."""
    slot, status, detail = await add_key(owner_user_id, service_id, raw_key)
    return status, detail


async def retest_provider(owner_user_id: Optional[int], service_id: str) -> tuple[str, str]:
    """بررسیِ اتصالِ همه‌ی کلیدهایِ این سرویس؛ وضعیتِ تجمیعی رو برمی‌گردونه."""
    await retest_all_keys(owner_user_id, service_id)
    return get_status(owner_user_id, service_id), ""


# ────────────────────────────────────────────────────────────────────────────
# مسیریابیِ وظایف
# ────────────────────────────────────────────────────────────────────────────

def get_task_route(owner_user_id: Optional[int], task_id: str) -> tuple[str, str]:
    row = db.ai_get_task_route(owner_user_id, task_id)
    if not row:
        return "", ""
    return row["provider_service_id"] or "", row["fallback_service_id"] or ""


def set_task_route(owner_user_id: Optional[int], task_id: str, provider_id: str = "", fallback_id: str = "") -> None:
    db.ai_set_task_route(owner_user_id, task_id, provider_id, fallback_id)


def resolve_provider_for_task(owner_user_id: Optional[int], task_id: str) -> Optional[str]:
    provider_id, fallback_id = get_task_route(owner_user_id, task_id)
    for sid in (provider_id, fallback_id):
        if not sid:
            continue
        status = get_status(owner_user_id, sid)
        if status in (cat.STATUS_ACTIVE, cat.STATUS_QUOTA_EXCEEDED):
            # حتی اگه aggregate روی quota_exceeded باشه بازم امتحانش می‌کنیم؛
            # ممکنه یکی از چند کلید هنوز قابلِ‌استفاده باشه یا cooldownش تموم
            # شده باشه - انتخابِ دقیقِ کلید در call_text/call_image انجام می‌شه.
            return sid
    return None


# ────────────────────────────────────────────────────────────────────────────
# انتخابِ چرخشیِ کلیدِ قابلِ‌استفاده
# ────────────────────────────────────────────────────────────────────────────

def _usable_key_rows(rows: list) -> list:
    out = []
    for r in rows:
        if not r["api_key_encrypted"]:
            continue
        if r["status"] in (cat.STATUS_INVALID, cat.STATUS_WRONG_SERVICE, cat.STATUS_NOT_SET):
            continue
        if r["status"] == cat.STATUS_QUOTA_EXCEEDED and _cooldown_active(r):
            continue
        out.append(r)
    return out


def _rotated(rows: list, cursor: int) -> list:
    if not rows:
        return []
    start = 0
    for i, r in enumerate(rows):
        if r["slot"] >= cursor:
            start = i
            break
    else:
        start = 0
    return rows[start:] + rows[:start]


# ────────────────────────────────────────────────────────────────────────────
# فراخوانیِ مستقیم (با چرخشِ خودکارِ بینِ چند کلید)
# ────────────────────────────────────────────────────────────────────────────

async def call_text(
    owner_user_id: Optional[int], service_id: str, prompt: str,
    system_prompt: str = "", temperature: float = 0.7,
    model: str = "",
) -> str:
    info = cat.get_provider(service_id)
    if not info or not info.has_text:
        raise ProviderCallError("other", f"سرویسِ {service_id} پشتیبانیِ متن ندارد")
    adapter = adapters.get_text_adapter(service_id)
    if adapter is None:
        raise ProviderCallError("other", f"آداپترِ متنیِ {service_id} یافت نشد")

    all_rows = db.ai_list_keys(owner_user_id, service_id)
    if not all_rows:
        raise ProviderCallError("invalid", "کلیدی برای این سرویس ثبت نشده")
    usable = _usable_key_rows(all_rows)
    if not usable:
        raise ProviderCallError("quota", "همه‌ی کلیدهایِ ثبت‌شده برایِ این سرویس Quota تمام کرده یا نامعتبرن")

    cursor = db.ai_get_rotation_cursor(owner_user_id, service_id)
    ordered = _rotated(usable, cursor)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    call_kwargs: dict = {}
    if model:
        call_kwargs["model"] = model

    last_err: Optional[ProviderCallError] = None
    for row in ordered:
        slot = row["slot"]
        raw_key = crypto.decrypt_text(row["api_key_encrypted"])
        if not raw_key:
            continue
        start = time.monotonic()
        try:
            text = await adapter.call(raw_key, messages, temperature=temperature, **call_kwargs)
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, True, elapsed)
            db.ai_record_usage(owner_user_id, service_id, True, elapsed)
            # چرخشِ round-robin: دفعه‌ی بعد از کلیدِ بعدی شروع کن
            db.ai_set_rotation_cursor(owner_user_id, service_id, slot + 1)
            return text
        except ProviderError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, False, elapsed)
            db.ai_record_usage(owner_user_id, service_id, False, elapsed)
            status, detail = _status_from_error(e)
            cooldown = str(time.time() + KEY_COOLDOWN_SECONDS) if isinstance(e, RateLimitError) else ""
            db.ai_update_key_status(owner_user_id, service_id, slot, status, detail, cooldown)
            if isinstance(e, RateLimitError):
                log.info("کلیدِ #%s سرویسِ %s Quota تمام کرد؛ چرخش به کلیدِ بعدی...", slot, service_id)
            last_err = _map_provider_error(e)
            continue
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, False, elapsed)
            last_err = ProviderCallError("other", str(e))
            continue

    raise last_err or ProviderCallError("other", "همه‌ی کلیدهایِ این سرویس شکست خوردن")


async def call_image(
    owner_user_id: Optional[int], service_id: str, prompt: str,
    width: int = 1024, height: int = 1024,
    model: str = "",
    input_image: bytes | None = None,
    input_mime: str = "image/jpeg",
) -> bytes:
    info = cat.get_provider(service_id)
    if not info or not info.has_image:
        raise ProviderCallError("other", f"سرویسِ {service_id} پشتیبانیِ تصویر ندارد")
    adapter = adapters.get_image_adapter(service_id)
    if adapter is None:
        raise ProviderCallError("other", f"آداپترِ تصویریِ {service_id} یافت نشد")

    all_rows = db.ai_list_keys(owner_user_id, service_id)
    if not all_rows:
        raise ProviderCallError("invalid", "کلیدی برای این سرویس ثبت نشده")
    usable = _usable_key_rows(all_rows)
    if not usable:
        raise ProviderCallError("quota", "همه‌ی کلیدهایِ ثبت‌شده برایِ این سرویس Quota تمام کرده یا نامعتبرن")

    cursor = db.ai_get_rotation_cursor(owner_user_id, service_id)
    ordered = _rotated(usable, cursor)

    call_kwargs: dict = {"width": width, "height": height}
    if model:
        call_kwargs["model"] = model
    if input_image:
        call_kwargs["input_image"] = input_image
        call_kwargs["input_mime"] = input_mime

    last_err: Optional[ProviderCallError] = None
    for row in ordered:
        slot = row["slot"]
        raw_key = crypto.decrypt_text(row["api_key_encrypted"])
        if not raw_key:
            continue
        start = time.monotonic()
        try:
            data = await adapter.call(raw_key, prompt, **call_kwargs)
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, True, elapsed)
            db.ai_record_usage(owner_user_id, service_id, True, elapsed)
            db.ai_set_rotation_cursor(owner_user_id, service_id, slot + 1)
            return data
        except ProviderError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, False, elapsed)
            db.ai_record_usage(owner_user_id, service_id, False, elapsed)
            status, detail = _status_from_error(e)
            cooldown = str(time.time() + KEY_COOLDOWN_SECONDS) if isinstance(e, RateLimitError) else ""
            db.ai_update_key_status(owner_user_id, service_id, slot, status, detail, cooldown)
            if isinstance(e, RateLimitError):
                log.info("کلیدِ #%s سرویسِ %s Quota تمام کرد؛ چرخش به کلیدِ بعدی...", slot, service_id)
            last_err = _map_provider_error(e)
            continue
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            db.ai_record_key_usage(owner_user_id, service_id, slot, False, elapsed)
            last_err = ProviderCallError("other", str(e))
            continue

    raise last_err or ProviderCallError("other", "همه‌ی کلیدهایِ این سرویس شکست خوردن")


# ────────────────────────────────────────────────────────────────────────────
# نقطه‌ی ورودیِ سطحِ بالا برای ai_router.py / image_router.py
# ────────────────────────────────────────────────────────────────────────────

async def try_custom_text(
    owner_user_id: Optional[int], task_id: str, prompt: str,
    system_prompt: str = "", temperature: float = 0.7,
) -> Optional[str]:
    sid = resolve_provider_for_task(owner_user_id, task_id)
    if not sid:
        return None
    try:
        return await call_text(owner_user_id, sid, prompt, system_prompt, temperature)
    except ProviderCallError as e:
        log.warning("Providerِ سفارشیِ متنی (%s) برایِ وظیفه‌ی %s شکست خورد: %s", sid, task_id, e)
        return None


async def try_custom_image(
    owner_user_id: Optional[int], task_id: str, prompt: str,
    width: int = 1024, height: int = 1024,
    input_image: bytes | None = None,
    input_mime: str = "image/jpeg",
) -> Optional[bytes]:
    sid = resolve_provider_for_task(owner_user_id, task_id)
    if not sid:
        return None
    if input_image and sid != "gemini":
        # فعلاً فقط Gemini از ویرایشِ تصویرِ ورودی (چندوجهی) پشتیبانی می‌کنه.
        # اگه Providerِ انتخاب‌شده برایِ این وظیفه چیزِ دیگه‌ایه، به‌جایِ خطایِ
        # گنگ، صریحاً None برمی‌گردونیم تا لایه‌ی بالاتر پیامِ روشن بده.
        log.info("Providerِ %s از ویرایشِ تصویرِ ورودی پشتیبانی نمی‌کنه (فقط Gemini)", sid)
        return None
    try:
        return await call_image(
            owner_user_id, sid, prompt, width, height,
            input_image=input_image, input_mime=input_mime,
        )
    except ProviderCallError as e:
        log.warning("Providerِ سفارشیِ تصویری (%s) برایِ وظیفه‌ی %s شکست خورد: %s", sid, task_id, e)
        return None
