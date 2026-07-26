"""
چرخه‌ی خودکار ارسال: هر چند ثانیه یک‌بار اجرا میشه و بسته به «حالت ارسال»ِ هر
کانال مبدأ، یکی از این سه مسیر رو طی می‌کنه (این سه همیشه دقیقا با هم انحصاری‌ان،
چون send_mode هر کانال فقط یکی از این سه مقدار رو داره):

  ۱. schedule (پیش‌فرض/رفتار قبلی ربات): هفت اسلاتِ زمانیِ ساعتی (به وقت تهران).
     هر اسلاتِ فعال که زمانش رسیده و امروز هنوز اجرا نشده، «یک» پستِ جدید می‌گیره.
  ۲. instant (ارسال لحظه‌ای): سرِ هر تیک چک میشه؛ هر پستِ تازه‌ای که پیدا بشه
     همون لحظه پردازش میشه. اگه «تاییدِ قبل از ارسال» فعال باشه، پست اول به
     کانالِ تایید می‌ره و بعد از تاییدِ ادمین به مقصد می‌رسه.
  ۳. interval (ارسال بازه‌ای): هر «interval_minutes» دقیقه یک‌بار، آخرین پستِ
     تازه رو می‌گیره؛ اگه اپشنِ تاییدِ ادمین برای این کانال فعال باشه، اول میره
     توی صفِ تایید.

در هر سه حالت، اگه «تاییدِ ادمین قبل از ارسال» (approval_required) برای کانال
فعال باشه، پست قبل از رفتن به مقصد ابتدا به کانالِ تایید ارسال می‌شه.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from . import ad_filter, config
from .database import db
from .poster import process_new_post, PostResult
from .scraper import fetch_new_posts, ScraperError

log = logging.getLogger("repost_bot.scheduler")

TICK_SECONDS = 30
DEST_CHECK_INTERVAL_SECONDS = 1800
DEST_INACTIVITY_THRESHOLD = timedelta(hours=48)

# حداکثر تعدادِ فراخوانیِ هم‌زمانِ LLM هنگامِ پیش‌گرمِ کشِ فیلترِ تبلیغات (پایین‌تر:
# _prewarm_ad_filter_cache). زیاد نبودنش عمدیه: هدف اینه که تاخیرِ N پستِ سریالی
# (که دقیقاً همون چیزیه که باعثِ زمان‌بندیِ نامنظمِ حالتِ لحظه‌ای می‌شه) با هم موازی
# بشه، نه اینکه با ده‌ها فراخوانیِ هم‌زمان به rate-limit ارائه‌دهنده‌ی AI بخوریم
# (که خودش باعثِ کندترشدن/شکستِ بیشتر می‌شه - دقیقاً نقطه‌ی مقابلِ هدف).
_AD_FILTER_PREWARM_CONCURRENCY = 4

_DEST_WARNING_TEXT_TEMPLATE = (
    "🔴🚨⚠️ <b>هشدار: کانال مقصد غیرفعال شده</b> ⚠️🚨🔴\n\n"
    "کانال مقصدِ زیر ۲ روزِ کامل هست هیچ پستی توش ارسال نشده:\n\n"
    "📛 نام: <b>{title}</b>\n"
    "🆔 آیدی: <code>{chat_id}</code>\n\n"
    "لطفاً هرچه زودتر یک پستِ جدید توی این کانال قرار بده تا کانال فعال بمونه؛ "
    "وگرنه ممکنه به‌عنوانِ کانالِ غیرفعال در نظر گرفته بشه.\n\n"
    "🔴🚨⚠️⚠️🚨🔴"
)

_DEST_THANKS_TEXT_TEMPLATE = (
    "✅🎉 <b>ممنون بابتِ به‌روزرسانی!</b> 🎉✅\n\n"
    "توی کانالِ «{title}» (<code>{chat_id}</code>) پستِ جدید دیده شد؛ "
    "کانال فعال موند 👌"
)

_DEST_THANKS_LINK_LINE = "\n\n🔗 <a href='{link}'>مشاهده پست</a>"

try:
    TEHRAN_TZ = ZoneInfo(config.TIMEZONE)
except (ZoneInfoNotFoundError, ValueError):
    log.warning("منطقه‌ی زمانیِ %s شناخته نشد؛ از Asia/Tehran استفاده می‌شه.", config.TIMEZONE)
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")

_running_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# سقفِ تلاش برای یک پستِ خراب
# ---------------------------------------------------------------------------
# برای حفظِ ترتیب، وقتی پستی با خطای فنی شکست می‌خورد، پست‌های جدیدتر صبر می‌کنن
# تا همون پست موفق بشه. مشکل: اگه خطا *دائمی* باشه (مثلاً تلگرام برای اون ویدیو
# لینکِ مستقیم نمی‌ده، یا فایل خیلی سنگینه)، اون پست هیچ‌وقت موفق نمی‌شه و صف
# «برای همیشه» بسته می‌مونه؛ یعنی هیچ پستِ جدیدی دیگه ری‌پست نمی‌شه. برای همین
# بعد از این تعداد تلاشِ ناموفق، از اون پست عبور می‌کنیم (last_post_id جلو می‌ره)
# تا صف باز شه و بقیه‌ی پست‌ها به‌موقع برسن. خطاهای گذرا (شبکه/تایم‌اوت) معمولاً
# در همین چند تلاش برطرف می‌شن، پس چیزی بی‌دلیل رد نمی‌شه.
_MAX_POST_ATTEMPTS = 3
_post_fail_counts: dict[tuple[int, int], int] = {}

# چند کانالِ مبدأ هم‌زمان اسکن/پردازش بشن. اگه خواستی رفتار کاملاً پشتِ‌سرِ‌هم و
# محافظه‌کارانه‌ی قبلی برگرده، این عدد رو ۱ بذار.
_MAX_PARALLEL_CHANNELS = 4

# سمافورِ هم‌زمانیِ کانال‌های instant. باید در سطحِ ماژول (persistent) باشه نه
# داخلِ run_tick، چون - برخلافِ قبل - دیگه تیک‌ها منتظرِ تمومِ‌شدنِ کانال‌های
# instant نمی‌مونن (پایین‌تر توضیح داده شده) و ممکنه چند تیک هم‌زمان تسکِ
# instant داشته باشن؛ این سمافور باید بینِ همه‌شون مشترک باشه تا سقفِ هم‌زمانی
# واقعاً رعایت بشه.
_instant_semaphore = asyncio.Semaphore(_MAX_PARALLEL_CHANNELS)

# قفلِ اختصاصیِ هر کانالِ instant: تضمین می‌کنه اگه یه کانال هنوز از تیکِ قبلی
# مشغولِ خالی‌کردنِ بک‌لاگشه، تیکِ جدید دوباره همون کانال رو هم‌زمان پردازش
# نکنه (که می‌تونست ترتیبِ پست‌ها رو به‌هم بریزه یا باعثِ ارسالِ تکراری بشه).
_instant_channel_locks: dict[int, asyncio.Lock] = {}

# رفرنسِ تسک‌های پس‌زمینه‌ی instant تا تمومِ‌شدنشون؛ بدونِ نگه‌داشتنِ این رفرنس،
# پایتون ممکنه تسک رو زودتر از موعد garbage-collect کنه (این یه گیرِ شناخته‌شده‌ی
# asyncio.create_task هست).
_background_tasks: set[asyncio.Task] = set()


async def _prewarm_ad_filter_cache(posts: list) -> None:
    """پیشگرمِ *موازیِ* کشِ داوریِ AIِ فیلترِ تبلیغات برای یک دسته پست، قبل از
    اینکه حلقه‌ی سریالیِ ارسال (که باید سریالی بمونه تا ترتیبِ پست‌ها حفظ بشه -
    نگاه کن به کامنتِ _handle_instant_channel) شروع بشه.

    چرا این کار امنه: ad_filter.llm_classify یک کشِ سراسری داره (نگاه کن به
    ad_filter._llm_verdict_cache) که کلیدش فقط «هشِ متنِ نرمال‌شده + نامِ داور»
    است - نه تنظیماتِ کلیدواژه/آستانه/مقصد. یعنی هرچی الان این‌جا پیش‌گرم بشه،
    بعداً دقیقاً همون خط‌لوله‌ی واقعی (_run_ad_filter → classify_async →
    llm_classify، داخلِ process_new_post) از همون کش می‌خونه - این تابع هیچ
    تصمیمی نمی‌گیره و نتیجه‌اش مستقیماً جایی استفاده نمی‌شه، فقط کش رو زودتر پر
    می‌کنه. اگه AI اصلاً کانفیگ نشده باشه، خودِ llm_classify فوراً و بدونِ
    فراخوانیِ شبکه‌ای None برمی‌گردونه، پس این تابع در اون حالت عملاً بی‌هزینه‌ست.

    چرا لازمه: بدونِ این پیش‌گرم، اگه ۵ پستِ جدید باهم پیدا بشن و هرکدوم به یک
    فراخوانیِ LLM نیاز داشته باشه، این ۵ فراخوانی *سریالی* (یکی پسِ دیگری، داخلِ
    حلقه‌ی اصلیِ ارسال) اتفاق می‌افتادن و مجموعِ تاخیرشون جمع می‌شد - همون چیزی
    که باعثِ حسِ «گاهی دیر، گاهی چند تا باهم» می‌شد. الان همه‌شون موازی (با سقفِ
    _AD_FILTER_PREWARM_CONCURRENCY تا هم‌زمان، تا rate-limit ارائه‌دهنده نخوریم)
    اجرا می‌شن و مجموع‌شون فقط به‌اندازه‌ی کندترینشون طول می‌کشه.

    best-effort و کاملاً بی‌خطر: هر خطایی (شبکه، rate-limit، هرچی) این‌جا کاملاً
    نادیده گرفته می‌شه؛ ارسالِ واقعی همیشه طبقِ روالِ سریالیِ خودش - با retry و
    حفظِ ترتیب - جلو می‌ره، چه این پیش‌گرم موفق بشه چه نه.
    """
    texts = []
    for p in posts:
        t = (getattr(p, "raw_text", "") or getattr(p, "html_text", "") or "").strip()
        if t:
            texts.append(t)
    if not texts:
        return

    sem = asyncio.Semaphore(_AD_FILTER_PREWARM_CONCURRENCY)

    async def _one(text: str) -> None:
        async with sem:
            try:
                await ad_filter.llm_classify(text, hint_keywords=None)
            except Exception:  # noqa: BLE001 - صرفاً پیش‌گرمِ کش است؛ هیچ‌وقت نباید چیزی رو بترکونه
                pass

    try:
        await asyncio.gather(*(_one(t) for t in texts))
    except Exception:  # noqa: BLE001 - محضِ اطمینانِ اضافه؛ _one خودش هم استثنا نمی‌ده
        log.debug("پیش‌گرمِ کشِ فیلترِ تبلیغات با خطا مواجه شد (نادیده گرفته شد).", exc_info=True)


def _note_post_failure(channel_id: int, post_id: int) -> int:
    """یک شکست برای این پست ثبت می‌کنه و تعدادِ کلِ تلاش‌های ناموفقش رو برمی‌گردونه."""
    if len(_post_fail_counts) > 2000:  # جلوگیری از رشدِ بی‌پایانِ حافظه
        _post_fail_counts.clear()
    key = (channel_id, post_id)
    n = _post_fail_counts.get(key, 0) + 1
    _post_fail_counts[key] = n
    return n


def _clear_post_failure(channel_id: int, post_id: int) -> None:
    _post_fail_counts.pop((channel_id, post_id), None)


def _log_post_given_up(channel_id: int, username: str, post_id: int) -> None:
    log.error(
        "پست %s از @%s بعد از %s تلاشِ ناموفق رد شد تا صفِ ارسال باز بشه و پست‌های "
        "جدیدتر معطل نمونن.",
        post_id, username, _MAX_POST_ATTEMPTS,
    )
    try:
        db.add_system_log(
            log_type="POST",
            event_type="post_given_up",
            severity="ERROR",
            message=(
                f"پست {post_id} از @{username} بعد از {_MAX_POST_ATTEMPTS} تلاش ارسال نشد "
                "و رد شد تا ترتیبِ بقیه‌ی پست‌ها قفل نشه."
            ),
            channel_id=channel_id,
            post_id=post_id,
            status="failed",
        )
    except Exception:  # noqa: BLE001 - لاگ نباید جلوی ادامه‌ی کار رو بگیره
        pass


def _now_local() -> datetime:
    return datetime.now(TEHRAN_TZ)


def _get_instant_lock(channel_id: int) -> asyncio.Lock:
    lock = _instant_channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _instant_channel_locks[channel_id] = lock
    return lock


async def _run_instant_guarded(context: ContextTypes.DEFAULT_TYPE, ch) -> None:
    """پردازشِ یک کانالِ instant به‌صورتِ تسکِ پس‌زمینه (نه چیزی که run_tick
    منتظرش بمونه). قفلِ اختصاصیِ کانال تضمین می‌کنه اگه تیکِ قبلی هنوز داره
    بک‌لاگِ همین کانال رو خالی می‌کنه، این تیک دوباره هم‌زمان سراغش نره."""
    channel_id = ch["id"]
    lock = _get_instant_lock(channel_id)
    if lock.locked():
        # این کانال هنوز از تیکِ قبلی مشغولِ ارساله؛ همین‌جا رد می‌شیم و تیکِ
        # بعدی دوباره امتحان می‌کنه - به‌جایِ این‌که منتظرش بمونیم و کلِ تیکِ
        # فعلی رو معطل کنیم.
        return
    async with lock:
        async with _instant_semaphore:
            try:
                await _handle_instant_channel(context, ch)
            except Exception:
                log.exception(
                    "خطای غیرمنتظره در ارسال لحظه‌ای کانال @%s؛ رد شد و ادامه داده میشه.",
                    ch["username"],
                )


async def _handle_slot(context: ContextTypes.DEFAULT_TYPE, slot_row, today: str) -> None:
    channel_id = slot_row["channel_id"]
    slot_index = slot_row["slot_index"]
    username = slot_row["username"]

    db.mark_slot_run(channel_id, slot_index, today)

    channel = db.get_channel(channel_id)
    if not channel:
        return

    last_post_id = channel["last_post_id"]

    remove_links = db.get_effective_bool(channel_id, "remove_source_links", True, owner_user_id=(channel["owner_user_id"] if channel and channel["owner_user_id"] else None))
    try:
        posts = await fetch_new_posts(username, last_post_id, remove_self_links=remove_links, limit=1)
    except ScraperError as e:
        log.warning("خطا در گرفتن پست‌های @%s: %s", username, e)
        return

    if not posts:
        log.info("برای کانال @%s (اسلات %s) پستِ جدیدی پیدا نشد.", username, slot_index)
        return

    post = posts[0]
    result = await process_new_post(context.bot, channel, post)
    if result == PostResult.FAILED:
        # شکستِ فنی (نه رد-شدنِ قانونی): last_post_id عمداً جلو نمی‌ره تا سرِ
        # اسلاتِ بعدی، دوباره همین پست امتحان بشه - وگرنه این پست گم می‌شد.
        # ولی بعد از سقفِ تلاش، ازش عبور می‌کنیم تا این اسلات برای همیشه گیر نکنه.
        attempts = _note_post_failure(channel_id, post.id)
        if attempts < _MAX_POST_ATTEMPTS:
            log.warning(
                "ارسالِ پست %s از @%s (اسلات %s) به‌دلیلِ خطای فنی ناموفق بود (تلاشِ %s از %s)؛ "
                "همین پست دوباره امتحان می‌شه.",
                post.id, username, slot_index, attempts, _MAX_POST_ATTEMPTS,
            )
            return
        _log_post_given_up(channel_id, username, post.id)
        _clear_post_failure(channel_id, post.id)
        db.update_last_post(channel_id, post.id)
        return
    _clear_post_failure(channel_id, post.id)
    db.update_last_post(channel_id, post.id)
    if result == PostResult.SENT:
        log.info("پست %s از @%s (اسلات %s) ارسال شد.", post.id, username, slot_index)


async def _handle_instant_channel(context: ContextTypes.DEFAULT_TYPE, channel) -> None:
    """حالت ارسال لحظه‌ای: هر پستِ تازه‌ای که پیدا بشه همون لحظه پردازش میشه.
    اگه approval_required فعال باشه، پست اول به کانالِ تایید می‌ره (مثل بقیه‌ی حالت‌ها)؛
    وگرنه مستقیم به مقصد می‌رسه."""
    channel_id = channel["id"]
    username = channel["username"]
    last_post_id = channel["last_post_id"]
    remove_links = db.get_effective_bool(channel_id, "remove_source_links", True, owner_user_id=(channel["owner_user_id"] if channel and channel["owner_user_id"] else None))

    try:
        posts = await fetch_new_posts(username, last_post_id, remove_self_links=remove_links, limit=10)
    except ScraperError as e:
        log.warning("خطا در گرفتن پست‌های @%s (لحظه‌ای): %s", username, e)
        return

    if not posts:
        return

    # نکته‌ی مهم برای حفظِ ترتیب: posts از قدیم به جدید مرتبه (مثلاً ۳۰۰، ۳۰۱،
    # ۳۰۲...). اگه پستی (مثلاً ۳۰۰) با یک خطای فنیِ موقتی (دانلود/آپلود) شکست
    # بخوره، دیگه سراغِ پستِ بعدی (۳۰۱) نمی‌ریم - همون‌جا متوقف می‌شیم و
    # last_post_id رو هم جلو نمی‌بریم، تا سرِ تیکِ بعدی (۳۰ ثانیه‌ی دیگه) اول
    # دوباره ۳۰۰ امتحان بشه و کامل با موفقیت بره، بعد نوبتِ ۳۰۱ برسه. این‌طوری
    # نه پستی گم میشه، نه ترتیبش به‌هم می‌ریزه.
    # اگه approval_required فعال باشه، bypass نمیشه — پست اول به کانالِ تایید می‌ره.
    #
    # پیش‌گرمِ موازیِ کشِ فیلترِ تبلیغات برایِ کلِ این دسته پست، *قبل* از حلقه‌ی
    # سریالیِ زیر (نگاه کن به docstringِ _prewarm_ad_filter_cache برای این‌که چرا
    # این کار امن و بی‌خطره و چرا اصلاً لازمه). جای این خط قبلِ محاسبه‌ی bypass
    # مهم نیست - این تابع فقط کش رو پر می‌کنه، خودش جایی decide نمی‌کنه.
    await _prewarm_ad_filter_cache(posts)

    bypass = not bool(channel["approval_required"])

    for post in posts:
        result = await process_new_post(context.bot, channel, post, bypass_approval=bypass)
        if result == PostResult.FAILED:
            attempts = _note_post_failure(channel_id, post.id)
            if attempts < _MAX_POST_ATTEMPTS:
                log.warning(
                    "ارسالِ لحظه‌ایِ پست %s از @%s به‌دلیلِ خطای فنی ناموفق بود (تلاشِ %s از %s)؛ "
                    "پست‌های بعدی (اگه باشن) صبر می‌کنن تا همین پست سرِ تیکِ بعدی کامل با "
                    "موفقیت ارسال بشه (حفظِ ترتیب).",
                    post.id, username, attempts, _MAX_POST_ATTEMPTS,
                )
                break
            # خطا دائمیه: از این پست عبور کن تا صف باز شه و بقیه عقب نیفتن.
            _log_post_given_up(channel_id, username, post.id)
            _clear_post_failure(channel_id, post.id)
            db.update_last_post(channel_id, post.id)
            continue
        _clear_post_failure(channel_id, post.id)
        db.update_last_post(channel_id, post.id)
        if result == PostResult.SENT:
            log.info("پست %s از @%s به‌صورت لحظه‌ای ارسال شد.", post.id, username)
        elif result == PostResult.QUEUED:
            log.info(
                "پست %s از @%s (لحظه‌ای) به کانالِ تایید فرستاده شد — منتظرِ تاییدِ ادمین.",
                post.id, username,
            )
        await asyncio.sleep(1.0)


async def _handle_interval_channel(context: ContextTypes.DEFAULT_TYPE, channel, now: datetime) -> None:
    """حالت ارسال بازه‌ای: هر interval_minutes دقیقه، آخرین پستِ تازه رو می‌فرسته."""
    channel_id = channel["id"]
    username = channel["username"]
    last_post_id = channel["last_post_id"]
    interval_minutes = max(1, int(channel["interval_minutes"] or 30))

    last_run_raw = channel["last_interval_run"] or ""
    if last_run_raw:
        try:
            last_run = datetime.fromisoformat(last_run_raw)
        except ValueError:
            last_run = None
    else:
        last_run = None

    if last_run is not None and (now - last_run) < timedelta(minutes=interval_minutes):
        return

    db.set_channel_last_interval_run(channel_id, now.isoformat())

    remove_links = db.get_effective_bool(channel_id, "remove_source_links", True, owner_user_id=(channel["owner_user_id"] if channel and channel["owner_user_id"] else None))
    try:
        posts = await fetch_new_posts(username, last_post_id, remove_self_links=remove_links, limit=1)
    except ScraperError as e:
        log.warning("خطا در گرفتن پست‌های @%s (بازه‌ای): %s", username, e)
        return

    if not posts:
        log.info("برای کانال @%s (بازه‌ای) پستِ جدیدی پیدا نشد.", username)
        return

    post = posts[0]
    result = await process_new_post(context.bot, channel, post)
    if result == PostResult.FAILED:
        attempts = _note_post_failure(channel_id, post.id)
        if attempts < _MAX_POST_ATTEMPTS:
            log.warning(
                "ارسالِ بازه‌ایِ پست %s از @%s به‌دلیلِ خطای فنی ناموفق بود (تلاشِ %s از %s)؛ "
                "همین پست دوباره امتحان می‌شه.",
                post.id, username, attempts, _MAX_POST_ATTEMPTS,
            )
            return
        _log_post_given_up(channel_id, username, post.id)
        _clear_post_failure(channel_id, post.id)
        db.update_last_post(channel_id, post.id)
        return
    _clear_post_failure(channel_id, post.id)
    db.update_last_post(channel_id, post.id)
    if result == PostResult.SENT:
        log.info("پست %s از @%s (بازه‌ای، هر %s دقیقه) ارسال شد.", post.id, username, interval_minutes)


async def run_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.get_bool("scheduler_active", True):
        return
    if _running_lock.locked():
        log.info("تیک قبلی هنوز در حال اجراست؛ این تیک رد شد.")
        return

    async with _running_lock:
        now = _now_local()
        now_hhmm = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")

        # ---------- حالت ۱: زمان‌بندیِ هفت‌گانه ----------
        due = db.due_slots(now_hhmm, today)
        for slot_row in due:
            try:
                await _handle_slot(context, slot_row, today)
            except Exception:
                log.exception(
                    "خطای غیرمنتظره هنگام پردازشِ اسلات %s از کانال @%s؛ رد شد و ادامه داده میشه.",
                    slot_row["slot_index"], slot_row["username"],
                )

        # ---------- حالت ۲: ارسال لحظه‌ای ----------
        # نکته‌ی مهم: اینجا دیگه await نمی‌کنیم تا کانال‌های instant تمومِ کارشون
        # رو بکنن. قبلاً (با asyncio.gather زیرِ _running_lock) اگه یک کانال
        # بک‌لاگِ زیادی داشت (مثلاً چند پستِ انباشته که هر کدوم ۱ ثانیه فاصله
        # دارن)، کلِ تیک - و در نتیجه *همه‌ی* تیک‌های بعدی، چون _running_lock
        # هنوز قفل بود - دقیقه‌ها معطل می‌موند (لاگِ پشتِ‌سرِ‌همِ «maximum number
        # of running instances reached» دقیقاً همین بود). الان هر کانال به‌صورتِ
        # تسکِ پس‌زمینه راه می‌افته و run_tick سریع برمی‌گرده؛ خودِ _running_lock
        # فقط رویِ اسکنِ اسلات‌ها/بازه‌ای می‌مونه که همیشه سریعن. سمافور و قفلِ
        # هر-کانالِ persistent (تعریف‌شده در بالای فایل) هم سقفِ هم‌زمانی و هم
        # ترتیبِ داخلِ هر کانال رو تضمین می‌کنن.
        for ch in db.channels_by_send_mode("instant", active_only=True):
            task = asyncio.create_task(_run_instant_guarded(context, ch))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        # ---------- حالت ۳: ارسال بازه‌ای ----------
        for channel in db.channels_by_send_mode("interval", active_only=True):
            try:
                await _handle_interval_channel(context, channel, now)
            except Exception:
                log.exception(
                    "خطای غیرمنتظره در ارسال بازه‌ایِ کانال @%s؛ رد شد و ادامه داده میشه.",
                    channel["username"],
                )


def _warning_targets(owner_key: int) -> list[int]:
    if owner_key:
        user = db.get_user(owner_key)
        if user and user["active"]:
            # فیکسِ M2: قبلاً فقط [user["approval_chat_id"]] برمی‌گشت؛ ولی کاربر
            # می‌تونه بدونِ کانالِ تاییدِ اختصاصی (approval_chat_id تهی) و فقط با
            # telegram_id اضافه شده باشه (هم install.sh و هم CLIِ add-user این
            # حالت رو مجاز می‌دونن). اون‌وقت این تابع [None] برمی‌گردوند و بعداً
            # bot.send_message(chat_id=None, ...) می‌ترکید. حالا مثلِ
            # poster._approval_targets به telegram_id fallback می‌کنه و اگه هیچ‌کدوم
            # نبود، به ادمین‌های سراسری برمی‌گرده تا هشدار گم نشه.
            target = user["approval_chat_id"] or user["telegram_id"]
            if target:
                return [int(target)]
    return list(config.ADMIN_IDS)


async def _send_destination_warning(
    bot, dest_row, owner_key: int, hours_inactive: float, total_warnings: int,
) -> None:
    from html import escape as _esc
    title = dest_row["title"] or str(dest_row["chat_id"])
    text = _DEST_WARNING_TEXT_TEMPLATE.format(title=_esc(title), chat_id=_esc(str(dest_row["chat_id"])))

    # اول کارتِ گرافیکیِ اخطار توی کانالِ عمومی (با تگ‌کردنِ مسئول)، اگه فعال باشه.
    # پیامش رو نگه می‌داریم تا وقتی جبران شد، پیامِ تشکر دقیقاً ریپلایِ همین پیام بشه.
    public_chat_id = None
    public_message_id = None
    try:
        from .public_report_channel import PublicReportChannel
        pub_msg = await PublicReportChannel.send_destination_warning_card(
            bot, dest_row, owner_key, hours_inactive, total_warnings,
        )
        if pub_msg:
            public_chat_id = pub_msg.chat_id
            public_message_id = pub_msg.message_id
    except Exception as e:
        log.warning("ارسالِ کارتِ اخطارِ عمومی برایِ مقصدِ %s ناموفق بود: %s", dest_row["id"], e)

    sent_any = False
    for chat_id in _warning_targets(owner_key):
        try:
            msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            sent_any = True
            try:
                await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=False)
            except TelegramError as e:
                log.warning("پین‌کردنِ پیامِ هشدارِ مقصدِ %s در چتِ %s ناموفق بود: %s", dest_row["id"], chat_id, e)
            db.set_destination_warning(
                dest_row["id"], owner_key, chat_id, msg.message_id,
                public_chat_id=public_chat_id, public_message_id=public_message_id,
            )
        except TelegramError as e:
            log.warning("ارسالِ هشدارِ عدم‌فعالیتِ مقصدِ %s به چتِ %s ناموفق بود: %s", dest_row["id"], chat_id, e)

    if not sent_any and public_message_id:
        # حتی اگه ارسال به همه‌ی چت‌هایِ خصوصی ناموفق بود (مثلاً کاربر ربات رو
        # بلاک کرده)، رکوردِ پیامِ عمومی رو ذخیره کن تا موقعِ جبران بشه بهش ریپلای زد.
        db.set_destination_warning(
            dest_row["id"], owner_key, None, None,
            public_chat_id=public_chat_id, public_message_id=public_message_id,
        )


async def _send_destination_thanks(bot, dest_row, owner_key: int, warning_row) -> None:
    from html import escape as _esc
    title = dest_row["title"] or str(dest_row["chat_id"])
    text = _DEST_THANKS_TEXT_TEMPLATE.format(title=_esc(title), chat_id=_esc(str(dest_row["chat_id"])))
    # اگه لینکِ آخرین پستی که توی این مقصد فرستاده شده (همون پستی که باعثِ
    # جبرانِ اخطار شده) در دسترس باشه، به هر دو پیام (خصوصی + کارتِ عمومی) اضافه‌ش کن.
    post_link = ""
    try:
        post_link = dest_row["last_post_link"] if "last_post_link" in dest_row.keys() else ""
    except Exception:
        post_link = ""
    if post_link:
        text += _DEST_THANKS_LINK_LINE.format(link=_esc(post_link))
    chat_id = warning_row["chat_id"]
    message_id = warning_row["message_id"]

    # مدتی که طول کشید تا بعدِ اخطار، پستِ تازه گذاشته بشه (برایِ نمایش در کارتِ تشکر)
    response_seconds = 0.0
    warned_at_raw = (warning_row["warned_at"] or "").strip()
    if warned_at_raw:
        try:
            warned_dt = datetime.strptime(warned_at_raw[:19], "%Y-%m-%d %H:%M:%S")
            response_seconds = (datetime.utcnow() - warned_dt).total_seconds()
        except ValueError:
            pass

    if chat_id and message_id:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        except TelegramError as e:
            log.warning("آنپین‌کردنِ پیامِ هشدارِ مقصدِ %s در چتِ %s ناموفق بود: %s", dest_row["id"], chat_id, e)
    if chat_id:
        try:
            # باگِ قبلی: این پیامِ تشکر یک پیامِ کاملاً جدا و بی‌ربط فرستاده می‌شد؛
            # حالا مستقیماً «ریپلایِ» همون پیامِ اخطارِ اصلیه، تا کاملاً مشخص باشه
            # این تشکر دقیقاً برایِ کدوم اخطار بوده.
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML",
                reply_to_message_id=message_id, allow_sending_without_reply=True,
            )
        except TelegramError as e:
            log.warning("ارسالِ پیامِ تشکرِ مقصدِ %s به چتِ %s ناموفق بود: %s", dest_row["id"], chat_id, e)

    try:
        from .public_report_channel import PublicReportChannel
        public_message_id = warning_row["public_message_id"] if "public_message_id" in warning_row.keys() else None
        await PublicReportChannel.send_destination_thanks_card(
            bot, dest_row, owner_key, response_seconds,
            reply_to_message_id=public_message_id,
            post_link=post_link,
        )
    except Exception as e:
        log.warning("ارسالِ کارتِ تشکرِ عمومی برایِ مقصدِ %s ناموفق بود: %s", dest_row["id"], e)

    db.clear_destination_warning(dest_row["id"], owner_key)


async def check_destination_inactivity(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not db.get_bool("scheduler_active", True):
        return
    now = datetime.utcnow()
    for dest in db.list_destinations(active_only=True):
        owners = db.owners_of_destination(dest["id"])
        if not owners:
            continue

        last_raw = (dest["last_sent_at"] or dest["created_at"] or "").strip()
        if not last_raw:
            continue
        try:
            last_dt = datetime.strptime(last_raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        is_inactive = (now - last_dt) >= DEST_INACTIVITY_THRESHOLD
        hours_inactive = (now - last_dt).total_seconds() / 3600

        # اگه هیچ‌کدوم از مالک‌ها الان اخطارِ باز ندارن، یعنی این یک اپیزودِ کاملاً
        # تازه‌ی بی‌فعالیته - شمارنده‌ی دائمی فقط همین‌جا (یک‌بار برایِ کلِ مقصد،
        # نه به‌ازایِ هر مالک) بالا میره تا با چند-مالکی‌بودنِ یک مقصد هم درست کار کنه.
        is_fresh_episode = is_inactive and not db.has_open_destination_warning(dest["id"])
        total_warnings: int | None = None

        for owner_key in owners:
            try:
                warning_row = db.get_destination_warning(dest["id"], owner_key)
                if is_inactive and not warning_row:
                    if total_warnings is None:
                        total_warnings = (
                            db.bump_destination_warning_count(dest["id"])
                            if is_fresh_episode else dest["total_warnings"]
                        )
                    await _send_destination_warning(
                        context.bot, dest, owner_key, hours_inactive, total_warnings,
                    )
                elif not is_inactive and warning_row:
                    await _send_destination_thanks(context.bot, dest, owner_key, warning_row)
            except Exception:
                log.exception(
                    "خطای غیرمنتظره در بررسیِ هشدارِ عدم‌فعالیتِ مقصدِ %s (مالک %s)؛ رد شد و ادامه داده میشه.",
                    dest["id"], owner_key,
                )


async def _send_daily_scoreboard_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from .public_report_channel import PublicReportChannel
        await PublicReportChannel.send_daily_scoreboard(context.bot)
    except Exception:
        log.exception("ارسالِ کارنامه‌ی روزانه‌ی مقصدها ناموفق بود.")


async def _cache_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """فیکسِ C3(ب): پاکسازیِ دوره‌ایِ آیتم‌های منقضیِ کشِ دانلود. قبلاً
    cache.cleanup_expired() هیچ‌جا صدا زده نمی‌شد، پس آیتم‌های منقضی تا رسیدنِ
    فشارِ LRU در حافظه می‌موندن و رم بی‌دلیل اشغال می‌شد."""
    try:
        from . import cache
        n = await cache.cleanup_expired()
        if n:
            log.debug("کشِ دانلود: %s آیتمِ منقضی پاک شد.", n)
    except Exception:
        log.debug("پاکسازیِ دوره‌ایِ کشِ دانلود با خطا مواجه شد (نادیده گرفته شد).", exc_info=True)


def schedule_jobs(application) -> None:
    application.job_queue.run_repeating(
        run_tick, interval=TICK_SECONDS, first=10, name="repost_tick"
    )
    application.job_queue.run_repeating(
        _cache_cleanup_job, interval=300, first=120, name="cache_cleanup"
    )
    application.job_queue.run_repeating(
        check_destination_inactivity, interval=DEST_CHECK_INTERVAL_SECONDS, first=60,
        name="dest_inactivity_check",
    )
    application.job_queue.run_daily(
        _send_daily_scoreboard_job,
        time=dtime(hour=9, minute=0, tzinfo=TEHRAN_TZ),
        name="daily_scoreboard",
    )
    log.info("زمان‌بند فعال شد: هر %s ثانیه اسلات‌های زمانی (به وقت %s) چک می‌شن.",
              TICK_SECONDS, config.TIMEZONE)
    log.info("بررسیِ عدم‌فعالیتِ کانال‌های مقصد هر %s ثانیه انجام می‌شه.", DEST_CHECK_INTERVAL_SECONDS)
    log.info("کارنامه‌ی روزانه‌ی مقصدها هر روز ساعت ۹:۰۰ (به وقت %s) ارسال می‌شه.", config.TIMEZONE)