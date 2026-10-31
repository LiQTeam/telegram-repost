"""
Adapterهایِ ۴ سرویسِ هوش مصنوعی (Mistral، Groq، Gemini، HuggingFace).

هر Provider می‌تونه TextAdapter، ImageAdapter، یا هر دو رو داشته باشه.
یک کلیدِ API واحد برایِ هر Provider استفاده می‌شه (هم متن هم تصویر).

ساختار:
  TEXT_ADAPTERS["mistral"]   → TextAdapter
  TEXT_ADAPTERS["groq"]      → TextAdapter
  TEXT_ADAPTERS["gemini"]    → TextAdapter
  TEXT_ADAPTERS["huggingface"] → TextAdapter
  IMAGE_ADAPTERS["gemini"]     → ImageAdapter
  IMAGE_ADAPTERS["huggingface"] → ImageAdapter

همه‌ی توابع فقط خطاهایِ استانداردِ ai_errors.py رو raise می‌کنن.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .ai_errors import (
    AuthError,
    InvalidResponseError,
    OtherProviderError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
)
from .config import GEMINI_PROXY_URL

log = logging.getLogger("repost_bot.ai_providers.adapters")

DEFAULT_TIMEOUT = 30.0
IMAGE_TIMEOUT   = 60.0


# ─── خطا-نگاشت مشترک ────────────────────────────────────────────────────────

def _clean_detail(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("<"):
        return "پاسخِ سرور HTML/XML بود، نه JSON (احتمالاً خطایِ Gateway یا endpoint اشتباه)"
    return " ".join(text.split())[:300]


def _map_error(exc: Exception, provider: str) -> ProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        detail = ""
        try:
            body = exc.response.json()
            detail = _clean_detail(str(body.get("error") or body.get("message") or body))
        except Exception:
            detail = _clean_detail(exc.response.text) if exc.response is not None else ""
        if status in (401, 403):
            return AuthError(f"{provider}: HTTP {status} - {detail or 'کلید رد شد'}")
        if status == 429:
            return RateLimitError(f"{provider}: HTTP 429 - {detail or 'Rate limit'}")
        if status >= 500:
            return ServerError(f"{provider}: HTTP {status} - {detail or 'خطایِ سرور'}")
        return OtherProviderError(f"{provider}: HTTP {status} - {detail or 'خطایِ نامشخص'}")
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(f"{provider}: Timeout")
    if isinstance(exc, (KeyError, IndexError, ValueError, TypeError)):
        return InvalidResponseError(f"{provider}: پاسخِ غیرِمنتظره - {exc}")
    return OtherProviderError(f"{provider}: {exc}")


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class TextAdapter:
    call: Callable[..., Awaitable[str]]
    validate: Callable[[str], Awaitable[None]]


@dataclass
class ImageAdapter:
    call: Callable[..., Awaitable[bytes]]
    validate: Callable[[str], Awaitable[None]]


# ─── کمک‌تابعِ OpenAI-style Chat (Mistral، Groq، HuggingFace همه این فرمتن) ──

async def _openai_style_chat(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    extra_headers: dict | None = None,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, provider) from e


async def _openai_style_validate(provider: str, models_url: str, api_key: str) -> None:
    """GET /models — اعتبارسنجیِ سبک بدونِ هزینه."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(models_url, headers=headers)
            resp.raise_for_status()
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, provider) from e


# ════════════════════════════════════════════════════════════════════════════
# ۱. MISTRAL  (فقط متن — OpenAI-compat)
# مدل‌های ۲۰۲۶: mistral-small-latest، mistral-large-latest، codestral-latest،
#              pixtral-large-latest
# ════════════════════════════════════════════════════════════════════════════
MISTRAL_BASE   = "https://api.mistral.ai/v1"
MISTRAL_MODEL  = "mistral-small-latest"


async def _mistral_call(
    api_key: str, messages: list[dict],
    temperature: float = 0.7, max_tokens: int = 4096,
    model: str = MISTRAL_MODEL, **_kw,
) -> str:
    return await _openai_style_chat("mistral", MISTRAL_BASE, api_key, model, messages, temperature, max_tokens)


async def _mistral_validate(api_key: str) -> None:
    await _openai_style_validate("mistral", f"{MISTRAL_BASE}/models", api_key)


# ════════════════════════════════════════════════════════════════════════════
# ۲. GROQ  (فقط متن — OpenAI-compat)
# مدل‌های ۲۰۲۶: openai/gpt-oss-120b، openai/gpt-oss-20b، qwen/qwen3.6-27b
# (gemma2-9b-it و moonshotai/kimi-k2-instruct از سرویس حذف شدن)
# ════════════════════════════════════════════════════════════════════════════
GROQ_BASE  = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"


async def _groq_call(
    api_key: str, messages: list[dict],
    temperature: float = 0.7, max_tokens: int = 4096,
    model: str = GROQ_MODEL, **_kw,
) -> str:
    return await _openai_style_chat("groq", GROQ_BASE, api_key, model, messages, temperature, max_tokens)


async def _groq_validate(api_key: str) -> None:
    await _openai_style_validate("groq", f"{GROQ_BASE}/models", api_key)


# ════════════════════════════════════════════════════════════════════════════
# ۳. GEMINI  (متن + تصویر — API اختصاصیِ Google)
# متن (رایگان): gemini-2.5-flash، gemini-3.5-flash، gemini-3.1-flash-lite
# (gemini-2.5-pro و کل خانواده‌ی Pro از ۱ آوریل ۲۰۲۶ paid-only شدن — دیگه پیش‌فرض نیست)
# تصویر: gemini-3.1-flash-image (Nano Banana 2)
# ════════════════════════════════════════════════════════════════════════════
GEMINI_BASE        = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TEXT_MODEL  = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"


def _gemini_content_url(model: str) -> str:
    return f"{GEMINI_BASE}/models/{model}:generateContent"


def _gemini_client_kwargs(timeout: float) -> dict[str, Any]:
    """
    kwargs برایِ httpx.AsyncClient مخصوصِ Gemini.
    generativelanguage.googleapis.com از خیلی رنج‌آی‌پی‌ها (ازجمله ایران) با
    ۴۰۳ بلاک می‌شه؛ اگه GEMINI_PROXY_URL در .env ست شده باشه، همه‌ی
    درخواست‌های Gemini (متن + تصویر + validate) از اون پروکسی رد می‌شن.
    فقط Gemini — Mistral/Groq/HuggingFace نیازی به این ندارن.
    نکته: httpx==0.27.2 از پارامترِ singular «proxy=» پشتیبانی می‌کنه (نه
    «proxies=» جمع که در httpx 0.28 حذف شده)؛ برایِ socks5:// پکیجِ socksio
    لازمه (توی requirements.txt اضافه شده).
    """
    kwargs: dict[str, Any] = {"timeout": timeout}
    if GEMINI_PROXY_URL:
        kwargs["proxy"] = GEMINI_PROXY_URL
    return kwargs


async def _gemini_call(
    api_key: str, messages: list[dict],
    temperature: float = 0.7, max_tokens: int = 4096,
    model: str = GEMINI_TEXT_MODEL, **_kw,
) -> str:
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    contents = [
        {"role": ("model" if m["role"] == "assistant" else "user"),
         "parts": [{"text": m["content"]}]}
        for m in messages if m.get("role") != "system"
    ]
    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(**_gemini_client_kwargs(DEFAULT_TIMEOUT)) as client:
            resp = await client.post(_gemini_content_url(model), headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, "gemini") from e


async def _gemini_validate(api_key: str) -> None:
    """GET /models — فقط چکِ احراز هویت، بدونِ هزینه."""
    headers = {"x-goog-api-key": api_key}
    try:
        async with httpx.AsyncClient(**_gemini_client_kwargs(DEFAULT_TIMEOUT)) as client:
            resp = await client.get(f"{GEMINI_BASE}/models", headers=headers)
            resp.raise_for_status()
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, "gemini") from e


async def _gemini_image_call(
    api_key: str, prompt: str,
    model: str = GEMINI_IMAGE_MODEL,
    input_image: bytes | None = None,
    input_mime: str = "image/jpeg",
    **_kw,
) -> bytes:
    """
    تولید یا ویرایشِ تصویر با Gemini (Nano Banana).
    اگر input_image داده بشه، این یک درخواستِ چندوجهیِ ویرایش/تغییرِ استایل روی همون
    تصویرِ ورودیه (نه تولیدِ تصویرِ کاملاً تازه)؛ Gemini از ترکیبِ inlineData + text
    توی همون parts پشتیبانی می‌کنه.
    خروجی: inlineData.data → base64 decode → bytes
    """
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    parts: list[dict] = []
    if input_image:
        parts.append({
            "inlineData": {
                "mimeType": input_mime,
                "data": base64.b64encode(input_image).decode("ascii"),
            }
        })
    parts.append({"text": prompt})
    body = {"contents": [{"parts": parts}]}
    try:
        async with httpx.AsyncClient(**_gemini_client_kwargs(IMAGE_TIMEOUT)) as client:
            resp = await client.post(_gemini_content_url(model), headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            for p in parts:
                inline = p.get("inlineData") or p.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
            raise InvalidResponseError("gemini_image: پاسخ حاویِ تصویر نبود")
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, "gemini_image") from e


async def _gemini_image_validate(api_key: str) -> None:
    await _gemini_validate(api_key)


# ════════════════════════════════════════════════════════════════════════════
# ۴. HUGGING FACE  (متن + تصویر)
# متن: router.huggingface.co/v1/chat/completions (OpenAI-compat)
# تصویر: router.huggingface.co/hf-inference/models/{model}
# ════════════════════════════════════════════════════════════════════════════
HF_BASE             = "https://router.huggingface.co"
HF_CHAT_BASE        = f"{HF_BASE}/v1"
HF_TEXT_MODEL       = "meta-llama/Llama-3.1-8B-Instruct"
HF_IMAGE_MODEL      = "black-forest-labs/FLUX.1-schnell"
HF_WHOAMI_URL       = "https://huggingface.co/api/whoami-v2"


async def _huggingface_call(
    api_key: str, messages: list[dict],
    temperature: float = 0.7, max_tokens: int = 4096,
    model: str = HF_TEXT_MODEL, **_kw,
) -> str:
    """
    Chat completions روی router.huggingface.co — OpenAI-compat endpoint.
    مدل: org/repo-name (مثلاً meta-llama/Llama-3.1-8B-Instruct)
    """
    return await _openai_style_chat(
        "huggingface", HF_CHAT_BASE, api_key, model, messages, temperature, max_tokens
    )


async def _huggingface_validate(api_key: str) -> None:
    """GET whoami — بدونِ هزینه."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(HF_WHOAMI_URL, headers=headers)
            resp.raise_for_status()
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, "huggingface") from e


async def _huggingface_image_call(
    api_key: str, prompt: str,
    model: str = HF_IMAGE_MODEL, **_kw,
) -> bytes:
    """
    تولید تصویر از طریقِ hf-inference router.
    endpoint: https://router.huggingface.co/hf-inference/models/{model}
    payload: {"inputs": "prompt"}
    response: bytes (image/png یا image/jpeg)
    """
    url = f"{HF_BASE}/hf-inference/models/{model}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json={"inputs": prompt})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                # مدل هنوز در حالِ لود / خطا
                raise InvalidResponseError(f"huggingface_image: {data}")
            return resp.content
    except ProviderError:
        raise
    except Exception as e:
        raise _map_error(e, "huggingface_image") from e


async def _huggingface_image_validate(api_key: str) -> None:
    await _huggingface_validate(api_key)


# ════════════════════════════════════════════════════════════════════════════
# رجیستری نهایی
# ════════════════════════════════════════════════════════════════════════════

TEXT_ADAPTERS: dict[str, TextAdapter] = {
    "mistral":     TextAdapter(_mistral_call,     _mistral_validate),
    "groq":        TextAdapter(_groq_call,         _groq_validate),
    "gemini":      TextAdapter(_gemini_call,       _gemini_validate),
    "huggingface": TextAdapter(_huggingface_call,  _huggingface_validate),
}

IMAGE_ADAPTERS: dict[str, ImageAdapter] = {
    "gemini":      ImageAdapter(_gemini_image_call,     _gemini_image_validate),
    "huggingface": ImageAdapter(_huggingface_image_call, _huggingface_image_validate),
}


def get_text_adapter(provider: str) -> TextAdapter | None:
    return TEXT_ADAPTERS.get(provider)


def get_image_adapter(provider: str) -> ImageAdapter | None:
    return IMAGE_ADAPTERS.get(provider)
