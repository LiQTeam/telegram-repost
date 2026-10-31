# -*- coding: utf-8 -*-
"""Load bot.poster with heavy/DB deps stubbed, so send_post logic is testable."""
import _harness  # noqa: F401 - بسته‌ی سبکِ bot را می‌سازد (اثرِ جانبی)
import sys, types

def _mod(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

# ---- stub heavy image/AI modules poster imports at top ----
aiw = _mod("bot.ai_watermark")
aiw.process_image_sync = lambda raw, remove_enabled=False: raw
srm = _mod("bot.sr_model")
srm.enhance_photo_sync = lambda raw: raw
wm = _mod("bot.watermark")
wm.add_watermark = lambda raw, settings: raw
cwm = _mod("bot.custom_watermark")
async def _apply_named(bot, raw, wms): return raw
cwm.apply_named_watermarks = _apply_named

# public_report_channel / notification_manager are lazy-imported inside funcs
prc = _mod("bot.public_report_channel")
class PublicReportChannel:
    @staticmethod
    def is_enabled(): return False
prc.PublicReportChannel = PublicReportChannel
nm = _mod("bot.notification_manager")
class NotificationManager:
    @staticmethod
    async def send_admin_notification(*a, **k): return None
nm.NotificationManager = NotificationManager

# button_style (needs db/jdatetime); stub to no button
bs = _mod("bot.button_style")
bs.build_repost_markup = lambda chat_id, post_text: None

# ---- fake DB ----
class FakeDB:
    def __init__(self):
        self.settings = {}
        self.mapped = {}  # (channel_id, post_id, dest_id) -> message_id
        self.max_caption_length = 1024
    # effective/bool getters -> return provided default
    def get_effective_bool(self, channel_id, key, default=False, owner_user_id=None): return default
    def get_bool(self, key, default=False): return self.settings.get(key, default)
    def setting_get(self, key, default="", owner_user_id=None): return self.settings.get(key, default)
    def setting_get_int(self, key, default=0, owner_user_id=None):
        if key == "max_caption_length": return self.max_caption_length
        return self.settings.get(key, default)
    def setting_get_bool(self, key, default=False, owner_user_id=None): return self.settings.get(key, default)
    def get_channel(self, channel_id): return None
    def get_user(self, uid): return None
    def get_watermarks_for_destination(self, dest_id): return []
    def dest_setting_get(self, dest_id, key, default=""): return default
    def dest_setting_get_bool(self, dest_id, key, default=False): return default
    def dest_setting_get_int(self, dest_id, key, default=0): return default
    def get_mapped_message_id(self, channel_id, post_id, dest_id):
        return self.mapped.get((channel_id, post_id, dest_id))
    def set_mapped_message_id(self, channel_id, post_id, dest_id, mid):
        self.mapped[(channel_id, post_id, dest_id)] = mid
    def has_open_destination_warning(self, dest_id): return False
    def mark_destination_sent(self, dest_id, post_link=""): pass
    def log_sent(self, *a, **k): pass
    def increment_ad_filtered(self): pass
    def add_system_log(self, **k): pass

fake_db = FakeDB()
dbmod = _mod("bot.database")
dbmod.db = fake_db

# Now import poster (real formatter/scraper/utils/ad_filter/cache/concurrency/config).
# این‌ها عمداً اینجا وارد می‌شن تا فایل‌های تست بعد از importِ همین ماژول،
# `from bot import poster` و `from bot.scraper import Post, MediaItem` رو روی
# نسخه‌ی استاب‌شده بگیرن (اثرِ جانبیِ گرم‌کردنِ sys.modules، نه استفاده‌ی مستقیم).
from bot import poster  # noqa: F401
from bot.scraper import Post, MediaItem  # noqa: F401
