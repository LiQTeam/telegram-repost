"""
فیلتر تشخیص محتوای تکراری بین کانال‌های مبدأ
با قابلیت تشخیص تشابه متن، لینک یکسان، یا هش تصویر/ویدئو

علاوه بر تطابقِ دقیق (هش)، یک لایه‌ی تشخیصِ فازی هم داره: وقتی دو کانالِ مبدأ
مثلِ هم به یک مقصد وصل باشن و هر دو خبرِ یکسانی رو با نشانه/ایموجیِ متفاوت،
یا با چند خط اضافه (تبلیغ، امضا، هشتگ) بازنشر کنن، اون‌ها هم «تکراری» شناخته
می‌شن؛ حتی اگه هشِ متنشون یکی نباشه.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from .database import db, _lock as _dup_lock  # noqa: PLC2701

log = logging.getLogger("repost_bot.duplicate_filter")

# قفلِ مشترک با database.py: هر دو ماژول روی یک کانکشنِ SQLite واحد (db._conn)
# کار می‌کنن. قبلاً اینجا یک threading.Lock() جداگانه (_dup_lock) بود که با
# _lock داخلیِ database.py هماهنگ نبود؛ در نتیجه دو ترد می‌تونستن همزمان از
# دو قفلِ مستقل روی یک کانکشن کار کنن ← race condition / "database is locked".
# حالا _dup_lock همون _lock خودِ database.py‌ه، پس همه‌ی دسترسی‌های مستقیم به
# db._conn (هم از database.py هم از اینجا) از یک قفل واحد رد می‌شن.
# ملاحظه: _lock در database.py ری‌اِنترانت نیست؛ مطمئن بشو که هیچ تابعِ
# database.py ای (که _lock می‌گیره) توی بلوکِ with _dup_lock اینجا صدا زده
# نمی‌شه — الان نمی‌شه و باید این ایزولاسیون حفظ بشه.

DUPLICATE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS duplicate_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,
    media_hash TEXT,
    source_channel_id INTEGER NOT NULL,
    source_post_id INTEGER NOT NULL,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_duplicate_hash ON duplicate_log(content_hash);
CREATE INDEX IF NOT EXISTS idx_duplicate_media ON duplicate_log(media_hash);
CREATE INDEX IF NOT EXISTS idx_duplicate_channel ON duplicate_log(source_channel_id);
"""

# ---------- تشخیصِ فازیِ تشابهِ متن ----------

# فقط حروفِ واقعیِ فارسی/عربی، حرفِ لاتین و رقم نگه داشته می‌شن؛ هر چیزِ دیگه
# (ایموجی، بولت، نشانه‌گذاری از جمله «،» و «؛» که اتفاقاً توی همون بازه‌ی
# یونیکدِ حروفِ عربی هستن ولی خودشون حرف نیستن، ZWNJ و...) جداکننده حساب می‌شه.
_PERSIAN_LETTERS = "ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئءآأؤإٱ"
_WORD_SPLIT_RE = re.compile(f"[^{_PERSIAN_LETTERS}a-zA-Z0-9]+", re.UNICODE)

# کلماتِ رایجِ فارسی که وزنِ معنایی ندارن و باعثِ شباهتِ کاذب می‌شن.
_STOPWORDS = {
    "از", "به", "که", "این", "آن", "یک", "و", "در", "را", "با", "هم", "برای",
    "تا", "بر", "شده", "شد", "است", "هست", "بود", "کرده", "کرد", "می", "نیز",
    "اما", "یا", "چون", "روی", "زیر", "بین", "پس", "اگر", "چه", "کجا", "چند",
    "همه", "دیگر", "نمی", "نه", "های", "ها", "او", "ما", "شما", "آنها", "خود",
}

# پسوندهای رایجِ جمع/نسبت که باعث می‌شن دو شکلِ متفاوت از یک کلمه (مثلاً
# «جنوب»/«جنوبی» یا «اختلال»/«اختلالات») به‌عنوانِ دو کلمه‌ی جدا شمرده بشن.
# با حذفِ این پسوندها، هر دو به یک ریشه می‌رسن. ترتیب مهمه: طولانی‌ترین اول.
_SUFFIXES = ("های", "هایی", "انه", "ات", "ها", "یی", "ی")


def _cutoff_str(dt: datetime) -> str:
    """فیکسِ R2: ستون‌های زمانیِ این جدول‌ها با CURRENT_TIMESTAMP یا
    datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') پر می‌شن، یعنی فرمتِ
    «YYYY-MM-DD HH:MM:SS» با *فاصله*. اما قبلاً برای مقایسه از isoformat
    استفاده می‌شد که «YYYY-MM-DDTHH:MM:SS.ffffff» (با حرفِ T و میکروثانیه)
    تولید می‌کنه. چون در مقایسه‌ی رشته‌ای ' ' < 'T'، شرطِ `sent_at > cutoff`
    عملاً همه‌ی رکوردهای همون‌روز رو از پنجره‌ی ۲۴ساعته بیرون می‌نداخت (تشخیصِ
    تکراری ناقص) و در clean_old_logs برعکس، رکوردهای سالم رو زودتر پاک می‌کرد.
    این تابع دقیقاً همون فرمتِ ذخیره‌شده رو می‌سازه تا مقایسه درست باشه."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _stem(word: str) -> str:
    """یک پسوندِ رایجِ فارسی رو (اگه بود) از انتهای کلمه حذف می‌کنه تا شکل‌های
    مختلفِ یک کلمه به ریشه‌ی مشترک برسن. حداقل ۲ حرف از ریشه باقی می‌مونه تا
    کلمه‌ی کوتاه بی‌معنا نشه."""
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            return word[: -len(suf)]
    return word

# حداقلِ تعدادِ کلمه‌ی معنادار برای این‌که مقایسه‌ی فازی اصلاً انجام بشه؛ پایین‌تر
# از این، ریسکِ تشخیصِ اشتباه بین دو پستِ کوتاهِ نامرتبط زیاد می‌شه.
_MIN_WORDS_FOR_FUZZY = 5

# آستانه‌ی شباهت برای «تکراری» شناخته شدن (۰ تا ۱). قابلِ تنظیم با
# db.set_setting("dup_fuzzy_threshold", ...) بدونِ نیاز به تغییرِ کد.
# روی نمونه‌های واقعی تست شده: بازنشرِ عینی با چند خطِ اضافه ~۰.۹۹، پارافریزِ
# فشرده‌ی همون خبر ~۰.۶۰، دو خبرِ هم‌موضوع ولی واقعاً متفاوت ~۰.۱، دو خبرِ
# نامرتبط ۰.۰ - پس ۰.۵۵ فاصله‌ی امنی بینِ «واقعاً همون خبر» و «فقط هم‌موضوع»
# ایجاد می‌کنه.
_DEFAULT_FUZZY_THRESHOLD = 0.55

# تعدادِ کاندیدهای اخیر که برای مقایسه‌ی فازی از دیتابیس خونده می‌شن (برای این‌که
# روی حجمِ زیاد کند نشه).
_FUZZY_CANDIDATE_LIMIT = 300


def _normalize_words(text: str) -> frozenset[str]:
    """متن رو به یک مجموعه از ریشه‌ی کلماتِ معنادار (بدونِ ایموجی/نشانه/کلماتِ
    رایج، و بعدِ حذفِ پسوندهای رایج) تبدیل می‌کنه. برای مقایسه‌ی فازی استفاده
    می‌شه، نه برای نمایش."""
    if not text:
        return frozenset()
    tokens = _WORD_SPLIT_RE.split(text)
    return frozenset(
        _stem(t) for t in tokens if len(t) >= 2 and t not in _STOPWORDS
    )


def _words_to_key(words: frozenset[str]) -> str:
    """برای ذخیره در دیتابیس: رشته‌ای پایدار و قابلِ بازخوانی."""
    return " ".join(sorted(words))


def _key_to_words(key: Optional[str]) -> frozenset[str]:
    if not key:
        return frozenset()
    return frozenset(key.split(" ")) if key else frozenset()


def _fuzzy_threshold() -> float:
    try:
        raw = db.get_setting("dup_fuzzy_threshold", str(_DEFAULT_FUZZY_THRESHOLD))
        return float(raw)
    except Exception:
        return _DEFAULT_FUZZY_THRESHOLD


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """شباهتِ دو مجموعه‌کلمه رو بین ۰ و ۱ برمی‌گردونه.

    ترکیبی از «نسبتِ همپوشانی» (overlap/کوچیک‌ترین مجموعه) و شاخصِ Jaccard:
    نسبتِ همپوشانی وزنِ بیشتری داره چون اگه یک پست فقط چند خطِ تبلیغاتی/هشتگِ
    اضافه داشته باشه، یا پارافریزِ فشرده‌تری از همون خبر باشه، طولش کوتاه‌تر یا
    بلندتر می‌شه ولی محتوای اصلی‌ش هنوز عمدتاً داخلِ پستِ دیگه‌ست؛ Jaccard
    به‌تنهایی این حالت رو دستِ‌کم می‌گیره چون طولِ اتحاد رو هم حساب می‌کنه."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    smallest = min(len(a), len(b))
    containment = inter / smallest
    union = len(a | b)
    jaccard = inter / union if union else 0.0
    return 0.75 * containment + 0.25 * jaccard


class DuplicateFilter:
    """
    فیلتر تشخیص محتوای تکراری با سه حالت:
    - disabled: غیرفعال
    - auto_reject: حذف خودکار
    - send_to_approval: ارسال به تأیید کاربر
    """

    MODE_DISABLED = "disabled"
    MODE_AUTO_REJECT = "auto_reject"
    MODE_SEND_TO_APPROVAL = "send_to_approval"

    @staticmethod
    def get_mode(channel_id: int) -> str:
        """دریافت حالت فیلتر برای کانال مبدأ"""
        return db.get_setting(f"dup_mode_{channel_id}", DuplicateFilter.MODE_DISABLED)

    @staticmethod
    def set_mode(channel_id: int, mode: str):
        """تنظیم حالت فیلتر برای کانال مبدأ"""
        if mode in (DuplicateFilter.MODE_DISABLED, DuplicateFilter.MODE_AUTO_REJECT, DuplicateFilter.MODE_SEND_TO_APPROVAL):
            db.set_setting(f"dup_mode_{channel_id}", mode)

    # ---------- تشخیصِ تکراری در سطحِ مقصد (بینِ چند کانالِ مبدأ) ----------
    # این جدا از get_mode/set_mode بالاست: اون‌ها روی «این کانالِ مبدأ چیزی که
    # خودش قبلاً دیده رو دوباره نفرسته» کار می‌کنن. این بخش رو یِ مقصد کنترل
    # می‌شه: اگه به این مقصد از چند کانالِ مبدأ (۲ تا، ۱۰ تا، فرقی نداره) محتوای
    # مشابه برسه، فقط اولی می‌ره و بقیه برای همین مقصد رد می‌شن.

    @staticmethod
    def get_dest_dedup_enabled(destination_id: int) -> bool:
        """آیا برای این مقصد، جلوگیری از پستِ تکراریِ بینِ‌کانالی روشنه."""
        return db.dest_setting_get_bool(destination_id, "dup_dedup_enabled", False)

    @staticmethod
    def set_dest_dedup_enabled(destination_id: int, enabled: bool) -> None:
        """روشن/خاموش کردنِ جلوگیری از پستِ تکراریِ بینِ‌کانالی برای این مقصد."""
        db.dest_setting_set(destination_id, "dup_dedup_enabled", "1" if enabled else "0")

    @classmethod
    def is_duplicate_for_destination(
        cls,
        text: str,
        media_urls: list[str],
        destination_id: int,
    ) -> tuple[bool, Optional[int]]:
        """بررسی می‌کنه که آیا محتوایی مشابه همین، در بازه‌ی اخیر قبلاً به همین
        مقصد ارسال شده یا نه - فارغ از این‌که از کدوم کانالِ مبدأ اومده باشه.

        بازگشت: (تکراری است؟, id پستِ مبدأیِ مشابهِ قبلی)"""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        text_hash = cls.get_hash_from_text(text) if text else None
        media_hash = cls.get_hash_from_media(media_urls[0]) if media_urls else None

        with _dup_lock:
            if text_hash:
                row = db._conn.execute(
                    """SELECT source_post_id FROM destination_content_log
                       WHERE destination_id=? AND content_hash=? AND sent_at > ?
                       ORDER BY sent_at DESC LIMIT 1""",
                    (destination_id, text_hash, _cutoff_str(cutoff))
                ).fetchone()
                if row:
                    return True, row["source_post_id"]

            if media_hash:
                row = db._conn.execute(
                    """SELECT source_post_id FROM destination_content_log
                       WHERE destination_id=? AND content_hash=? AND sent_at > ?
                       ORDER BY sent_at DESC LIMIT 1""",
                    (destination_id, media_hash, _cutoff_str(cutoff))
                ).fetchone()
                if row:
                    return True, row["source_post_id"]

            words = _normalize_words(text) if text else frozenset()
            if len(words) >= _MIN_WORDS_FOR_FUZZY:
                threshold = _fuzzy_threshold()
                candidates = db._conn.execute(
                    """SELECT source_post_id, dup_words FROM destination_content_log
                       WHERE destination_id=? AND sent_at > ? AND dup_words IS NOT NULL
                       ORDER BY sent_at DESC LIMIT ?""",
                    (destination_id, _cutoff_str(cutoff), _FUZZY_CANDIDATE_LIMIT)
                ).fetchall()
                best_score = 0.0
                best_post_id = None
                for row in candidates:
                    cand_words = _key_to_words(row["dup_words"])
                    score = _similarity(words, cand_words)
                    if score > best_score:
                        best_score = score
                        best_post_id = row["source_post_id"]
                if best_post_id is not None and best_score >= threshold:
                    log.debug(
                        "برای مقصدِ %s پستِ مشابه پیدا شد (پست: %s، شباهت: %.2f)",
                        destination_id, best_post_id, best_score,
                    )
                    return True, best_post_id

        return False, None

    @classmethod
    def log_sent_to_destination(
        cls,
        text: str,
        media_urls: list[str],
        destination_id: int,
        source_channel_id: int,
        source_post_id: int,
    ) -> None:
        """بعدِ ارسالِ موفقِ یک پست به یک مقصد، محتواش رو برای مقایسه‌ی مقصدهای
        بعدی ثبت می‌کنه. فقط وقتی dedup این مقصد روشنه صدا زده می‌شه."""
        text_hash = cls.get_hash_from_text(text) if text else None
        media_hash = cls.get_hash_from_media(media_urls[0]) if media_urls else None
        if text_hash is not None:
            content_hash = text_hash
        elif media_hash is not None:
            content_hash = media_hash
        else:
            content_hash = hashlib.md5(
                f"nomedia:{destination_id}:{source_channel_id}:{source_post_id}".encode("utf-8")
            ).hexdigest()
        dup_words = _words_to_key(_normalize_words(text)) if text else None

        with _dup_lock:
            db._conn.execute(
                """INSERT INTO destination_content_log
                   (destination_id, content_hash, dup_words, source_channel_id, source_post_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (destination_id, content_hash, dup_words, source_channel_id, source_post_id)
            )
            db._conn.commit()

    @staticmethod
    def get_hash_from_text(text: str) -> str:
        """محاسبه هش از متن (نرمال‌سازی شده)"""
        if not text:
            return hashlib.md5(b"").hexdigest()
        # حذف فاصله‌های اضافی و خطوط
        normalized = " ".join(text.strip().split())
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def get_hash_from_media(media_url: str) -> Optional[str]:
        """محاسبه هش از URL مدیا"""
        if not media_url:
            return None
        return hashlib.md5(media_url.encode('utf-8')).hexdigest()

    @classmethod
    def is_duplicate(
        cls,
        text: str,
        media_urls: list[str],
        source_channel_id: int,
        source_post_id: int,
    ) -> tuple[bool, Optional[int]]:
        """
        بررسی تکراری بودن محتوا

        بازگشت: (تکراری است؟, id پست تکراری قبلی)
        """
        # بررسی در ۲۴ ساعت گذشته
        cutoff = datetime.utcnow() - timedelta(hours=24)

        # هش متن
        text_hash = cls.get_hash_from_text(text) if text else None
        with _dup_lock:
            if text_hash:
                row = db._conn.execute(
                    """SELECT id, source_post_id FROM duplicate_log 
                       WHERE content_hash=? AND first_seen > ? 
                       ORDER BY first_seen DESC LIMIT 1""",
                    (text_hash, _cutoff_str(cutoff))
                ).fetchone()
                if row:
                    log.debug("محتوای تکراری بر اساس متن یافت شد (پست: %s)", row["source_post_id"])
                    return True, row["source_post_id"]

            # بررسی هش مدیا (اولین مدیا)
            if media_urls:
                media_hash = cls.get_hash_from_media(media_urls[0])
                if media_hash:
                    row = db._conn.execute(
                        """SELECT id, source_post_id FROM duplicate_log 
                           WHERE media_hash=? AND first_seen > ? 
                           ORDER BY first_seen DESC LIMIT 1""",
                        (media_hash, _cutoff_str(cutoff))
                    ).fetchone()
                    if row:
                        log.debug("محتوای تکراری بر اساس مدیا یافت شد (پست: %s)", row["source_post_id"])
                        return True, row["source_post_id"]

            # بررسیِ فازی: وقتی هشِ دقیق یکی نیست ولی متن تقریباً همون خبره
            # (نشانه/ایموجیِ متفاوت، چند خطِ تبلیغاتی یا هشتگِ اضافه). فقط وقتی
            # متن کلماتِ معنادارِ کافی داشته باشه انجام می‌شه تا پست‌های کوتاه
            # به‌اشتباه به هم شبیه تشخیص داده نشن.
            words = _normalize_words(text) if text else frozenset()
            if len(words) >= _MIN_WORDS_FOR_FUZZY:
                threshold = _fuzzy_threshold()
                candidates = db._conn.execute(
                    """SELECT source_post_id, dup_words FROM duplicate_log
                       WHERE first_seen > ? AND dup_words IS NOT NULL
                       ORDER BY first_seen DESC LIMIT ?""",
                    (_cutoff_str(cutoff), _FUZZY_CANDIDATE_LIMIT)
                ).fetchall()
                best_score = 0.0
                best_post_id = None
                for row in candidates:
                    cand_words = _key_to_words(row["dup_words"])
                    score = _similarity(words, cand_words)
                    if score > best_score:
                        best_score = score
                        best_post_id = row["source_post_id"]
                if best_post_id is not None and best_score >= threshold:
                    log.debug(
                        "محتوای تکراری بر اساسِ تشابهِ فازی یافت شد (پست: %s، شباهت: %.2f)",
                        best_post_id, best_score,
                    )
                    return True, best_post_id

        return False, None

    @classmethod
    def log_post(cls, text: str, media_urls: list[str], source_channel_id: int, source_post_id: int):
        """ثبت پست در لاگ تکراری برای بررسی‌های آینده"""
        text_hash = cls.get_hash_from_text(text) if text else None
        media_hash = cls.get_hash_from_media(media_urls[0]) if media_urls else None

        # ستونِ content_hash در جدول NOT NULL است. اگر پست نه متن دارد و نه مدیایی
        # که URLش استخراج شده باشد (مثلاً ویدیویی که لینکِ مستقیمش از صفحه‌ی
        # پیش‌نمایش به‌دست نیامد و کپشن هم نداشت)، هر دو هش None می‌شدند و درج با
        # خطای «NOT NULL constraint failed: duplicate_log.content_hash» کلِ پردازشِ
        # آن کانال را در هر تیک می‌ترکاند (پست گیر می‌کرد و بی‌نهایت تکرار می‌شد).
        # برای همین اگر متنی نبود، یک هشِ یکتا از هویتِ خودِ پست می‌سازیم تا هم
        # درج معتبر باشد و هم به‌اشتباه با پستِ دیگری «تکراری» تشخیص داده نشود
        # (این هش هیچ‌وقت با هشِ یک متنِ واقعی برخورد نمی‌کند).
        if text_hash is not None:
            content_hash = text_hash
        elif media_hash is not None:
            content_hash = media_hash
        else:
            content_hash = hashlib.md5(
                f"nomedia:{source_channel_id}:{source_post_id}".encode("utf-8")
            ).hexdigest()

        conn = db._conn
        dup_words = _words_to_key(_normalize_words(text)) if text else None

        with _dup_lock:
            # ابتدا بررسی کنیم آیا پست قبلاً ثبت شده است
            existing = conn.execute(
                "SELECT id FROM duplicate_log WHERE source_channel_id=? AND source_post_id=?",
                (source_channel_id, source_post_id)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE duplicate_log SET last_seen=CURRENT_TIMESTAMP, dup_words=? WHERE id=?",
                    (dup_words, existing["id"])
                )
                conn.commit()
                return

            conn.execute(
                """INSERT INTO duplicate_log 
                   (content_hash, media_hash, source_channel_id, source_post_id, dup_words) 
                   VALUES (?, ?, ?, ?, ?)""",
                (content_hash, media_hash, source_channel_id, source_post_id, dup_words)
            )
            conn.commit()
        log.debug("پست در لاگ تکراری ثبت شد: channel=%s, post=%s", source_channel_id, source_post_id)

    @classmethod
    def check_and_log_atomic(
        cls,
        text: str,
        media_urls: list[str],
        source_channel_id: int,
        source_post_id: int,
    ) -> tuple[bool, Optional[int]]:
        """فیکسِ R3 (شرطِ رقابتی): بررسیِ تکراری‌بودن و ثبتِ پست را در *یک* بخشِ
        بحرانیِ واحد (یک بار گرفتنِ _dup_lock) انجام می‌دهد. قبلاً is_duplicate و
        log_post دو قفلِ جدا بودند و بینشان await وجود داشت؛ با چند کانالِ instant
        موازی، دو کانال می‌توانستند هم‌زمان «تکراری نیست» ببینند و هر دو پست را
        بفرستند. حالا بین چک و ثبت هیچ پنجره‌ای نیست.

        فیکسِ R9: آستانه‌ی فازی *قبل* از گرفتنِ قفل خوانده می‌شود، تا فراخوانیِ
        db.get_setting داخلِ قفلِ غیرِری‌اِنترانت نباشد (دِدلاکِ نهفته حذف می‌شود).

        بازگشت: (تکراری بود؟, id پستِ مشابهِ قبلی یا None). اگر تکراری نبود، پست
        همین‌جا ثبت هم می‌شود و دیگر نباید log_post جدا صدا زده شود."""
        cutoff_s = _cutoff_str(datetime.utcnow() - timedelta(hours=24))
        text_hash = cls.get_hash_from_text(text) if text else None
        media_hash = cls.get_hash_from_media(media_urls[0]) if media_urls else None
        words = _normalize_words(text) if text else frozenset()
        do_fuzzy = len(words) >= _MIN_WORDS_FOR_FUZZY
        threshold = _fuzzy_threshold() if do_fuzzy else 1.0  # خارج از قفل (R9)
        dup_words = _words_to_key(words) if text else None
        conn = db._conn

        with _dup_lock:
            # ۱) تطابقِ دقیقِ متن
            if text_hash:
                row = conn.execute(
                    "SELECT source_post_id FROM duplicate_log "
                    "WHERE content_hash=? AND first_seen > ? ORDER BY first_seen DESC LIMIT 1",
                    (text_hash, cutoff_s),
                ).fetchone()
                if row:
                    return True, row["source_post_id"]
            # ۲) تطابقِ دقیقِ مدیا
            if media_hash:
                row = conn.execute(
                    "SELECT source_post_id FROM duplicate_log "
                    "WHERE media_hash=? AND first_seen > ? ORDER BY first_seen DESC LIMIT 1",
                    (media_hash, cutoff_s),
                ).fetchone()
                if row:
                    return True, row["source_post_id"]
            # ۳) تطابقِ فازی
            if do_fuzzy:
                candidates = conn.execute(
                    "SELECT source_post_id, dup_words FROM duplicate_log "
                    "WHERE first_seen > ? AND dup_words IS NOT NULL "
                    "ORDER BY first_seen DESC LIMIT ?",
                    (cutoff_s, _FUZZY_CANDIDATE_LIMIT),
                ).fetchall()
                best_score, best_post_id = 0.0, None
                for row in candidates:
                    score = _similarity(words, _key_to_words(row["dup_words"]))
                    if score > best_score:
                        best_score, best_post_id = score, row["source_post_id"]
                if best_post_id is not None and best_score >= threshold:
                    return True, best_post_id

            # تکراری نبود ← همین‌جا (زیرِ همون قفل) ثبتش می‌کنیم تا پنجره‌ی رقابتی نمونه.
            if text_hash is not None:
                content_hash = text_hash
            elif media_hash is not None:
                content_hash = media_hash
            else:
                content_hash = hashlib.md5(
                    f"nomedia:{source_channel_id}:{source_post_id}".encode("utf-8")
                ).hexdigest()

            existing = conn.execute(
                "SELECT id FROM duplicate_log WHERE source_channel_id=? AND source_post_id=?",
                (source_channel_id, source_post_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE duplicate_log SET last_seen=CURRENT_TIMESTAMP, dup_words=? WHERE id=?",
                    (dup_words, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO duplicate_log "
                    "(content_hash, media_hash, source_channel_id, source_post_id, dup_words) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (content_hash, media_hash, source_channel_id, source_post_id, dup_words),
                )
            conn.commit()
        return False, None

    @classmethod
    def clean_old_logs(cls, days: int = 7):
        """پاکسازی لاگ‌های قدیمی"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with _dup_lock:
            deleted = db._conn.execute(
                "DELETE FROM duplicate_log WHERE first_seen < ?",
                (_cutoff_str(cutoff),)
            ).rowcount
            db._conn.commit()
        if deleted:
            log.info("%s رکورد قدیمی از duplicate_log حذف شد", deleted)