#!/usr/bin/env python3
"""
نقطه‌ی ورود ربات ری‌پست هوشمند MR LiQ.
اجرا: python3 main.py
"""
from __future__ import annotations

import logging
import os
import signal
import time

# ⚠️ سقفِ زمانیِ *مطلقِ* واچ‌داگِ shutdown - باید واضحاً کمتر از TimeoutStopSecِ
# یونیتِ systemd (۲۰ ثانیه، در install.sh) باشه. چرا لازمه با اینکه هم
# validate_provider() (بالای ai_provider_manager.py، سقفِ ۱۲ ثانیه) و هم
# ThreadPoolExecutorِ concurrency.py (پایین همین فایل، سقفِ ۱۰ ثانیه) خودشون
# سقفِ زمانی دارن: این دو سقف روی مسیرِ shutdown پشتِ‌سرِ‌هم اجرا می‌شن (اول
# PTB منتظرِ اتمامِ هندلرِ در‌حال‌اجرا می‌مونه [تا ۱۲ ثانیه]، بعد _post_shutdown
# صدا زده می‌شه [تا ۱۰ ثانیه‌یِ دیگه]) - جمعشون (۱۲+۱۰=۲۲ ثانیه) از سقفِ
# ۲۰ثانیه‌ایِ TimeoutStopSec رد می‌شه. این واچ‌داگ یک سقفِ مطلق و مستقل از کلِ
# فرآیندِ shutdown - صرف‌نظر از این‌که چند زیرسیستم پشتِ سرِ هم گیر کنن یا حتی
# یک hangِ کاملاً پیش‌بینی‌نشده‌یِ دیگه - تضمین می‌کنه.
_WATCHDOG_GRACE_SECONDS = 16.0


def _spawn_shutdown_watchdog() -> None:
    """
    یک پروسه‌ی بچه‌یِ مستقل (واچ‌داگ) فورک می‌کنه که هیچ کاری با منطقِ ربات
    نداره؛ فقط منتظرِ SIGTERM/SIGINT می‌مونه و اگه پروسه‌ی اصلی (parent - همون
    MainPIDِ که systemd می‌شناسه، چون fork خودِ parent's PID رو عوض نمی‌کنه)
    ظرفِ _WATCHDOG_GRACE_SECONDS بعد از دریافتِ سیگنال خودش تمیز نمرده باشه،
    مستقیماً با SIGKILL پروسه‌ی اصلی رو می‌کشه - قبل از این‌که systemd با
    TimeoutStopSec (۲۰ ثانیه) این کار رو با روشِ خشن‌ترِ control-group انجام
    بده (که «State 'stop-sigterm' timed out. Killing.» رو توی journalctl
    می‌ندازه).

    ⚠️ باید همین‌جا، در همون ابتدایِ فایل و قبل از هر importِ سنگین (`bot`،
    `telegram`) و قبل از هر threadی فورک بشه. فورک بعد از بالا اومدنِ
    threadها/event loop/سوکت‌ها stateِ ناقص کپی می‌کنه و می‌تونه قفل/کرش بده.

    فیکسِ باگِ fd inheritance: fork تمامِ فایل‌دیسکریپتورهای بازِ parent
    (stdin/stdout/stderr) رو عیناً کپی می‌کنه. اگه اینا رو تویِ بچه نبندیم،
    واچ‌داگ pipeِ journald رو دستش نگه می‌داره؛ حتی بعد از مردنِ parent،
    journald/systemd این pipe رو هنوز به یه پروسه‌ی دیگه (واچ‌داگ) متصل
    می‌بینه که می‌تونه بستنِ تمیزِ لاگ/سرویس رو معوق نگه داره. واچ‌داگ اصلاً
    کاری با stdin/stdout/stderr نداره، پس بلافاصله بعدِ fork همه رو می‌بندیم
    و به /dev/null وصل می‌کنیم.
    """
    main_pid = os.getpid()
    try:
        pid = os.fork()
    except OSError:
        # فورک روی بعضی محیط‌های محدودشده (مثلاً کانتینرهای بدونِ اجازه‌ی
        # فورک) ممکنه fail بشه؛ نبودِ واچ‌داگ نباید جلویِ بالا اومدنِ ربات رو
        # بگیره - فقط این لایه‌یِ محافظتیِ اضافه از دست می‌ره.
        logging.getLogger(__name__).warning(
            "فورکِ واچ‌داگِ shutdown ناموفق بود - ربات بدونِ این لایه‌یِ محافظتی ادامه می‌ده."
        )
        return

    if pid != 0:
        # پروسه‌ی اصلی (parent) - همون ربات - بدونِ هیچ تغییری ادامه می‌ده.
        return

    # ⚠️ از این خط به بعد فقط توی پروسه‌ی بچه (واچ‌داگ) هستیم. این پروسه هرگز
    # نباید به بقیه‌ی main.py برسه یا هیچ کدی از خودِ ربات رو اجرا کنه.
    try:
        devnull_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull_fd, 0)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        if devnull_fd > 2:
            os.close(devnull_fd)
    except OSError:
        pass

    state: dict[str, float | None] = {"deadline": None}

    def _on_signal(signum, frame):  # noqa: ANN001, ARG001 - امضایِ اجباریِ signal.signal
        if state["deadline"] is None:
            state["deadline"] = time.monotonic() + _WATCHDOG_GRACE_SECONDS

    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except Exception:
        pass

    while True:
        time.sleep(0.5)
        try:
            os.kill(main_pid, 0)
        except (ProcessLookupError, PermissionError):
            os._exit(0)  # پروسه‌ی اصلی مرده - کارِ واچ‌داگ تمومه

        deadline = state["deadline"]
        if deadline is not None and time.monotonic() >= deadline:
            try:
                os.kill(main_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os._exit(0)


if __name__ == "__main__":
    _spawn_shutdown_watchdog()

# ⚠️ این بلوک باید همین‌جا، قبل از هر importِ دیگه (خصوصاً `from bot import
# config`) بمونه. چرا: `bot/__init__.py` به‌محضِ importِ پکیجِ bot، ماژول‌های
# sr_model.py و lama_model.py رو eagerly import می‌کنه که خودشون numpy رو
# module-level import می‌کنن؛ بعداً موقعِ پردازشِ واقعیِ عکس (واترمارک/بهبودِ
# کیفیت)، torch هم لود می‌شه. اگه envِ زیر *بعد* از این importها ست بشه، دیگه
# روی تعدادِ تردهای داخلیِ این کتابخونه‌ها اثر نداره (چون موقعِ اولین
# importشون خونده می‌شه، نه بعدش).
#
# چرا اصلاً لازمه: بدونِ این محدودیت، PyTorch/OpenBLAS به‌محضِ اولین
# inference یه استخرِ تردِ داخلی به‌اندازه‌ی تعدادِ هسته‌های CPU می‌سازن که
# بعضی‌وقت‌ها موقعِ SIGTERM تمیز بسته نمی‌شن و توی cgroupِ systemd زنده
# می‌مونن. چون KillMode پیش‌فرضِ systemd "control-group"ه، سرویس تا وقتی این
# تردها/پردازه‌ها زنده‌ن "stopped" حساب نمی‌شه و بعد از تایم‌اوتِ ۹۰ثانیه‌ای
# با SIGKILL به‌زور بسته می‌شه - دقیقاً همون چیزی که توی journalctl می‌دیدیم:
# "State 'stop-sigterm' timed out. Killing." + کشته‌شدنِ ده‌ها پردازه‌ی
# اضافی (از جمله چندتا با نامِ "pt_main_thread" که torch به خودش می‌ده).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import sys

# سقفِ زمانیِ امن برای منتظرِ تمام‌شدنِ کارهای سنگینِ در حالِ اجرا (واترمارک/
# بهبودِ کیفیت با AI) موقعِ خاموش‌شدن - نگاه کن به توضیحِ کاملش توی
# _post_shutdown. باید واضحاً کمتر از TimeoutStopSecِ یونیتِ systemd
# (پیش‌فرض ۲۰ ثانیه، توی install.sh) باشه تا فرصتِ کافی برایِ خروجِ کنترل‌شده
# قبل از این‌که خودِ systemd با SIGKILL پروسه رو بکشه باقی بمونه.
_HEAVY_SHUTDOWN_GRACE_SECONDS = 10.0

from telegram import BotCommand, MenuButtonCommands, Update
from telegram.ext import Application, ContextTypes
from telegram.request import HTTPXRequest

from bot import config
from bot.handlers import register_handlers
from bot.scheduler import schedule_jobs


async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هندلرِ سراسریِ خطا. بدونِ این، هر exceptionِ کنترل‌نشده‌ی داخلِ هندلرها
    (مثلاً fail شدنِ ارسالِ پیامِ خصوصی به کاربری که هنوز /start نزده) فقط
    توی لاگ می‌افتاد و از دیدِ کاربر هیچ اتفاقی نمی‌افتاد - نه خطا، نه نتیجه.
    حالا حداقل لاگ می‌شه و در صورتِ امکان به خودِ کاربر هم خبر داده می‌شه.
    """
    import logging
    logging.getLogger(__name__).exception("خطای کنترل‌نشده در پردازشِ آپدیت: %s", context.error)

    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ یه خطای غیرمنتظره پیش اومد. دوباره امتحان کن یا لاگ رو چک کن.",
            )
    except Exception:
        pass


_COMMANDS = [
    BotCommand("start", "شروع / نمایش منوی اصلی"),
    BotCommand("menu", "نمایش دوبارهٔ منوی اصلی"),
    BotCommand("stats", "آمار ربات"),
    BotCommand("sources", "کانال‌های مبدأ"),
    BotCommand("extsources", "منابع اکستنشن (گروه‌های خصوصی)"),
    BotCommand("destinations", "کانال‌های مقصد"),
    BotCommand("watermark", "واترمارک تصویر"),
    BotCommand("footer", "امضای پایان پست"),
    BotCommand("format", "قالب‌بندی متن"),
    BotCommand("adfilter", "فیلتر پست‌های تبلیغاتی"),
    BotCommand("help", "راهنما"),
]


async def _post_init(application: Application) -> None:
    """
    فعال‌سازیِ دکمه‌ی Menu (آیکونِ سه‌خط) کنارِ نوارِ متن برای دسترسیِ سریع به
    دستورات، به‌جای نوعِ پیش‌فرض/بدونِ آیکون.

    همچنین سرویس‌های پس‌زمینه (مانیتورینگ منابع سرور، بکاپ خودکار روزانه،
    تبلیغات، ارسالِ دستیِ زمان‌بندی‌شده، سرورِ API اکستنشن) زمان‌بندی می‌شن تا
    حلقه‌ی اصلیِ ربات را قفل نکنن - نگاه کن به توضیحِ _start_background_tasks
    برای این‌که چرا مستقیم این‌جا create_task نمی‌شن.
    """
    from bot.resource_monitor import ResourceMonitor
    from bot.backup_manager import BackupManager

    await application.bot.set_my_commands(_COMMANDS)
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    resource_monitor = ResourceMonitor(application.bot)
    backup_manager = BackupManager(application.bot)
    application.bot_data["resource_monitor"] = resource_monitor
    application.bot_data["backup_manager"] = backup_manager

    # ⚠️ باگِ مهم: قبلاً همین‌جا (تویِ post_init) مستقیماً application.create_task(...)
    # برای این تسک‌ها صدا زده می‌شد. طبقِ خودِ python-telegram-bot، post_init دقیقاً
    # همون لحظه‌ای اجرا می‌شه که application هنوز واقعاً «running» نیست (این حالت
    # چند خط بعدتر، توسطِ run_polling، ست می‌شه) - برای همین create_task هر بار با
    # PTBUserWarning («won't be automatically awaited») هشدار می‌داد و این تسک‌ها
    # اصلاً توسطِ خودِ PTB ردیابی نمی‌شدن. نتیجه: سرِ هر ری‌استارت/توقفِ سرویس، این
    # تسک‌ها به‌جای cancel/awaitِ تمیزِ PTB، وسطِ کار (pending) نابود می‌شدن و یه
    # مشتی «asyncio - ERROR - Task was destroyed but it is pending!» توی لاگ
    # می‌ریخت. راهِ حل: زمان‌بندیِ ساختِ این تسک‌ها با یک jobِ یک‌بارِ JobQueue
    # (when=0) که تضمین می‌کنه فقط *بعدِ* این‌که application واقعاً start شد اجرا
    # بشه - اون‌جا create_task دیگه هم بدونِ هشدار کار می‌کنه هم توسطِ PTB برای
    # shutdownِ تمیز ردیابی می‌شه.
    application.job_queue.run_once(_start_background_tasks, when=0)


async def _start_background_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """ساختِ واقعیِ تسک‌های پس‌زمینه - نگاه کن به توضیحِ باگ توی _post_init."""
    application = context.application
    resource_monitor = application.bot_data["resource_monitor"]
    backup_manager = application.bot_data["backup_manager"]
    application.create_task(resource_monitor.run_loop())
    application.create_task(backup_manager.run_daily_backup())

    # ماژولِ ایزوله‌ی «تبلیغات» — دیتابیس/حلقه‌ی خودش را در یک تسکِ
    # asyncio جدا راه‌اندازی می‌کند؛ هیچ تاثیری روی حلقه‌ی اصلیِ ری‌پست ندارد.
    from bot import auto_poster as _auto_poster
    _auto_poster.setup(application)

    # ماژولِ ایزوله‌ی «ارسالِ دستی + زمان‌بندی» — حلقه‌ی چکِ پست‌های زمان‌بندی‌شده
    # در یک تسکِ asyncio جدا (مستقل از حلقه‌ی اصلیِ ری‌پست و از حلقه‌ی تبلیغات).
    from bot.manual_poster import run_manual_scheduler_loop as _manual_scheduler_loop
    application.create_task(_manual_scheduler_loop(application.bot))

    # API اکستنشنِ مرورگر (گروه‌های خصوصیِ تلگرام‌وب) - تسکِ جداگانه، فقط اگه
    # توی .env فعال شده باشه (EXTENSION_API_ENABLED=true)، وگرنه بی‌اثره.
    from bot.extension_api import run_ext_api_server as _run_ext_api_server
    application.create_task(_run_ext_api_server(application.bot))


async def _post_shutdown(application: Application) -> None:
    """
    موقعِ خاموش‌شدنِ ربات (Ctrl+C یا systemctl stop) صدا زده می‌شه.
    """
    from bot import auto_poster as _auto_poster
    try:
        await _auto_poster.shutdown()
    except Exception:
        pass

    # ⚠️ فیکسِ اصلیِ باگِ «systemd تایم‌اوت می‌خوره و پروسه رو SIGKILL می‌کنه»:
    # bot/concurrency.py یک ThreadPoolExecutor برای اجرای کارهای سنگین
    # (واترمارک/بهبودِ کیفیت با AI) داره که تردهاش non-daemonن. تا حالا هیچ‌
    # جا شات‌داون نمی‌شد، پس بعد از هر پردازشِ عکس این تردها idle می‌موندن و
    # جلوی exitِ واقعیِ خودِ پروسه‌ی پایتون رو می‌گرفتن - حتی بعد از این‌که
    # Application/scheduler به‌درستی و سریع (چند ثانیه‌ای) shutdown می‌شدن.
    # نتیجه: systemd پروسه رو هنوز "زنده" می‌دید و تا TimeoutStopSec صبر
    # می‌کرد و بعد مجبور می‌شد با SIGKILL به‌زور ببندتش.
    import asyncio
    import logging
    import os
    log = logging.getLogger(__name__)
    try:
        from bot import concurrency as _concurrency
        log.info("در حالِ بستنِ ThreadPoolExecutorِ پردازش‌های سنگین...")
        # ⚠️ فیکسِ جدید (روی همون باگ): _concurrency.shutdown() عمداً از
        # wait=True استفاده می‌کنه تا تردهای idle برای همیشه نمونن - این
        # درسته. ولی اگه دقیقاً لحظه‌ی systemctl stop یک پردازشِ سنگین
        # (مثلاً بهبودِ کیفیتِ تصویر با torch روی CPU) واقعاً درحالِ اجرا
        # باشه، از بیرون هیچ راهی برای لغوِ اون ترد نیست؛ wait=True تا
        # وقتی اون کار *واقعاً* تموم بشه صبر می‌کنه - که می‌تونه از
        # TimeoutStopSecِ یونیتِ systemd (۲۰ ثانیه) بیشتر طول بکشه و دقیقاً
        # همون خطای «Failed with result 'timeout'» رو دوباره بده (systemd
        # پروسه رو بی‌رحمانه SIGKILL می‌کنه، بدونِ این‌که کدِ ما بتونه
        # جلوشو بگیره). راهِ حل: یک سقفِ زمانیِ امن (کمتر از TimeoutStopSec)
        # روی این انتظار می‌ذاریم؛ اگه رد شد، به‌جایِ این‌که بذاریم دیر یا
        # زود systemd با SIGKILL بکشتش، خودمون با os._exit یه خروجِ فوریِ
        # کنترل‌شده انجام می‌دیم. کارِ سنگینِ نیمه‌کاره از دست می‌ره (پستِ
        # بعدی دوباره امتحان می‌شه)، ولی سرویس سریع و تمیز (زیرِ سقفِ
        # systemd) خاموش می‌شه و Restart=on-failure بلافاصله دوباره
        # بالاش می‌آره - به‌جایِ ده‌ها ثانیه معطلی + SIGKILLِ زشتِ سراسری.
        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _concurrency.shutdown),
            timeout=_HEAVY_SHUTDOWN_GRACE_SECONDS,
        )
        log.info("ThreadPoolExecutor با موفقیت بسته شد.")
    except asyncio.TimeoutError:
        log.warning(
            "بستنِ ThreadPoolExecutor بعد از %.0f ثانیه هنوز کامل نشده (احتمالاً یک "
            "پردازشِ سنگین/AI در حالِ اجراست) - برای جلوگیریِ از SIGKILLِ سراسریِ "
            "systemd، همین‌جا با خروجِ کنترل‌شده پروسه رو می‌بندیم؛ Restart=on-failure "
            "طبقِ تنظیماتِ سرویس دوباره بالاش می‌آره.",
            _HEAVY_SHUTDOWN_GRACE_SECONDS,
        )
        os._exit(0)
    except Exception:
        logging.getLogger(__name__).exception("بستنِ ThreadPoolExecutor ناموفق بود")


def main() -> None:
    log = config.setup_logging()

    errors = config.validate()
    if errors:
        for e in errors:
            log.error(e)
        log.error("فایل .env رو کامل کن (از .env.example کپی بگیر) و دوباره اجرا کن.")
        sys.exit(1)

    # concurrent_updates=True: چند تا آپدیت (پیام/کلیکِ دکمه) می‌تونن هم‌زمان
    # پردازش بشن، نه یکی‌یکی توی صف. این دقیقاً همون چیزیه که باعث می‌شه ربات
    # موقعی که یک پردازشِ سنگین (مثلا واترمارک/AI روی یک عکس) در حال اجراست،
    # هنوز به کلیک‌های دیگه (مثلا باز کردنِ لیستِ کانال‌های مبدأ) فوراً جواب بده -
    # رفعِ همون باگِ «باید چند بار کلیک کنم تا جواب بده».
    # تنظیماتِ پیش‌فرضِ python-telegram-bot برای تایم‌اوتِ آپلود/دانلود (چندین
    # ثانیه) برای ویدیوهای حجیم اصلاً کافی نیست و باعثِ شکستِ ارسال با خطای
    # «Timed out» می‌شد - حتی وقتی خودِ فایل کاملاً دانلود شده بود. اینجا
    # تایم‌اوت‌ها رو به‌طورِ قابل‌توجهی زیاد می‌کنیم (به‌خصوص media_write_timeout
    # که مخصوصِ آپلودِ فایل/عکس/ویدیوعه) تا حتی ویدیوهای سنگین هم فرصتِ کافی
    # برای رسیدن به تلگرام داشته باشن.
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=90.0,
        write_timeout=90.0,
        pool_timeout=60.0,
        media_write_timeout=300.0,
    )

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(request)
        .concurrent_updates(config.MAX_CONCURRENT_HEAVY_JOBS + 5)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    register_handlers(application)
    application.add_error_handler(_global_error_handler)
    schedule_jobs(application)

    log.info(
        "ربات با موفقیت بالا اومد و در حال گوش‌دادن به پیام‌هاست... "
        "(پردازش هم‌زمانِ آپدیت‌ها فعاله)"
    )
    # "channel_post" هم اضافه شد: بدونش، وقتی ادمین بعد از زدنِ «ویرایش کپشن/
    # تغییر عکس/تغییر ویدیو» مستقیماً توی کانالِ تایید (نه توی چتِ خصوصی) عکس/
    # متن/ویدیویِ جدید رو پست می‌کرد، ربات اصلاً اون آپدیت رو دریافت نمی‌کرد.
    application.run_polling(allowed_updates=["message", "callback_query", "channel_post"], drop_pending_updates=True)


if __name__ == "__main__":
    main()