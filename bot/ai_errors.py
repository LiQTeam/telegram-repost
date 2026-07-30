"""
سلسله‌مراتبِ خطاهایِ مشترکِ همه‌ی Adapterهایِ سرویس‌هایِ هوش مصنوعی.

هدف: هر Adapter (هرچقدر هم فرمتِ خطایِ سرویسِ مبدأش متفاوت باشه) باید یکی از
این خطاهایِ استاندارد رو raise کنه؛ لایه‌یِ بالاتر (manager.py) فقط با همین
چند نوع سروکار داره و لازم نیست فرمتِ خامِ خطایِ هر سرویس رو بشناسه.
"""
from __future__ import annotations


class ProviderError(Exception):
    """پایه‌یِ همه‌یِ خطاهایِ Adapter."""


class AuthError(ProviderError):
    """کلید رد شد (HTTP 401/403). می‌تونه به‌خاطرِ کلیدِ نامعتبر یا کلیدِ
    متعلق‌به‌سرویسِ‌دیگر باشه؛ manager.py با هیوریستیکِ پیشوند این دو حالت رو
    قبل از حتی رسیدن به اینجا تفکیک می‌کنه (نگاه کن به catalog.py)."""


class RateLimitError(ProviderError):
    """HTTP 429 - سرویس موقتاً محدودیتِ نرخ داره؛ ارزشِ Retry با تأخیر داره."""


class ProviderTimeoutError(ProviderError):
    """Timeout در سطحِ HTTP (نه منطقِ داخلیِ ما)."""


class ServerError(ProviderError):
    """خطایِ سمتِ سرویس (HTTP 5xx) - موقتیه، ارزشِ Retry/Failover داره."""


class InvalidResponseError(ProviderError):
    """پاسخِ ۲xx گرفتیم ولی فرمتش قابلِ‌پارس نبود یا خالی بود."""


class OtherProviderError(ProviderError):
    """هر خطایِ دیگه (۴xx غیرِ ۴۰۱/۴۰۳/۴۲۹، خطایِ شبکه‌یِ غیرِ Timeout و ...)."""
