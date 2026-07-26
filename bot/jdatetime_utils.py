"""
توابع کمکی برای تاریخ و زمان شمسی با فرمت‌های مختلف
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

import jdatetime

# منطقه‌ی زمانیِ تهران - صریحاً مشخص شده تا مستقل از تنظیماتِ سیستم‌عاملِ سرور
# باشه. اکثرِ سرورهای ابری (VPS) روی UTC ست شدن؛ قبلاً این‌جا از
# jdatetime.datetime.now() استفاده می‌شد که ساعتِ محلیِ سرور رو می‌گرفت - یعنی
# اگه سرور UTC بود، همه‌ی زمان‌ها (بکاپ، لاگ‌ها، زمان‌بندیِ ارسال و...) ۳ ساعت و
# ۳۰ دقیقه با وقتِ واقعیِ تهران فرق داشتن.
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# نگاشت نام ماه‌های شمسی به انگلیسی
PERSIAN_MONTHS = {
    1: "فروردین", 2: "اردیبهشت", 3: "خرداد", 4: "تیر",
    5: "مرداد", 6: "شهریور", 7: "مهر", 8: "آبان",
    9: "آذر", 10: "دی", 11: "بهمن", 12: "اسفند"
}

PERSIAN_DAYS = {
    0: "شنبه", 1: "یکشنبه", 2: "دوشنبه", 3: "سه‌شنبه",
    4: "چهارشنبه", 5: "پنجشنبه", 6: "جمعه"
}


def now_jalali() -> jdatetime.datetime:
    """دریافت زمانِ فعلی به وقتِ تهران (نه ساعتِ سیستمِ سرور)، به شمسی"""
    return jdatetime.datetime.fromgregorian(datetime=datetime.now(TEHRAN_TZ))


def to_jalali(dt: Union[datetime, jdatetime.datetime, None] = None) -> jdatetime.datetime:
    """تبدیل زمان میلادی به شمسی"""
    if dt is None:
        return now_jalali()
    if isinstance(dt, jdatetime.datetime):
        return dt
    if isinstance(dt, datetime):
        # اگه دیتیایمِ ورودی timezone-aware باشه، اول به وقتِ تهران تبدیل میشه؛
        # اگه naive باشه (مثلاً از قبلاً توی دیتابیس ذخیره شده)، همون‌طور که
        # هست فرض می‌شه از قبل وقتِ تهرانه (رفتارِ قبلی حفظ شد تا داده‌های
        # قدیمی جابه‌جا نشن).
        if dt.tzinfo is not None:
            dt = dt.astimezone(TEHRAN_TZ)
        return jdatetime.datetime.fromgregorian(datetime=dt)
    return now_jalali()


def format_jalali_datetime(dt: Union[datetime, jdatetime.datetime, None] = None, show_weekday: bool = False) -> str:
    """فرمت کردن تاریخ شمسی به صورت خوانا"""
    jal = to_jalali(dt)
    result = jal.strftime("%Y/%m/%d - %H:%M:%S")
    if show_weekday:
        weekday = PERSIAN_DAYS.get(jal.weekday(), "")
        result = f"{weekday} {result}"
    return result


def format_jalali_date(dt: Union[datetime, jdatetime.datetime, None] = None, show_weekday: bool = False) -> str:
    """فرمت فقط تاریخ شمسی"""
    jal = to_jalali(dt)
    result = jal.strftime("%Y/%m/%d")
    if show_weekday:
        weekday = PERSIAN_DAYS.get(jal.weekday(), "")
        result = f"{weekday} {result}"
    return result


def format_jalali_time(dt: Union[datetime, jdatetime.datetime, None] = None) -> str:
    """فرمت فقط ساعت شمسی"""
    jal = to_jalali(dt)
    return jal.strftime("%H:%M:%S")


def format_jalali_persian(dt: Union[datetime, jdatetime.datetime, None] = None) -> str:
    """
    فرمت کامل فارسی: "شنبه ۱۵ مهر ۱۴۰۲ - ۱۴:۳۰:۲۵"
    """
    jal = to_jalali(dt)
    weekday = PERSIAN_DAYS.get(jal.weekday(), "")
    month = PERSIAN_MONTHS.get(jal.month, "")
    return f"{weekday} {jal.day} {month} {jal.year} - {jal.strftime('%H:%M:%S')}"


def parse_gregorian_from_jalali(jalali_str: str) -> Optional[datetime]:
    """
    تبدیل رشته شمسی به میلادی
    فرمت‌های پشتیبانی‌شده:
    - 1402/12/01 - 12:30:00
    - 1402/12/01 12:30:00
    - 1402/12/01
    """
    jalali_str = jalali_str.strip()
    if not jalali_str:
        return None

    # جداسازی تاریخ و زمان
    # باگ: الگویِ قبلی فقط روی فاصله و خط‌تیره اسپلیت می‌کرد، پس برای
    # "1402/12/01 - 12:30:00" مقدارِ parts[0] برابرِ "1402/12/01" می‌شد و
    # int() روش ValueError می‌داد → تابع همیشه None برمی‌گردوند.
    parts = [p for p in re.split(r'[/:\s\-]+', jalali_str) if p]

    if len(parts) < 3:
        return None

    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2])

        hour = int(parts[3]) if len(parts) > 3 else 0
        minute = int(parts[4]) if len(parts) > 4 else 0
        second = int(parts[5]) if len(parts) > 5 else 0

        jd = jdatetime.datetime(year, month, day, hour, minute, second)
        return jd.togregorian()

    except (ValueError, TypeError):
        return None


def jalali_timedelta(days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> jdatetime.timedelta:
    """ایجاد timedelta شمسی"""
    return jdatetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def get_jalali_weekday(dt: Union[datetime, jdatetime.datetime, None] = None) -> str:
    """دریافت نام روز هفته به فارسی"""
    jal = to_jalali(dt)
    return PERSIAN_DAYS.get(jal.weekday(), "")


def get_jalali_month_name(dt: Union[datetime, jdatetime.datetime, None] = None) -> str:
    """دریافت نام ماه به فارسی"""
    jal = to_jalali(dt)
    return PERSIAN_MONTHS.get(jal.month, "")