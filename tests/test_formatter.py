# -*- coding: utf-8 -*-
import _harness
from bot import formatter as f

RLM = "‏"; RLE = "‫"; PDF = "‬"
fails = []
def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra if not cond else "")
    if not cond: fails.append(name)

# ب-0: باگِ راست‌چینی (اسکرین‌شات‌های کاربر): نشانگر باید RLM (bidi=R) باشد، نه
# RLE (bidi=RLE). تلگرام RLE را به‌عنوانِ نشانه‌ی راست‌چینی نمی‌شناسد و خط چپ می‌افتد.
import unicodedata as _ud
for _txt, _lbl in [("👑 کانفیگ فیلترشکن", "emoji_start"),
                   ("📍 موقعیت سرور :", "pin_start"),
                   ("پرامپت کاپلی:", "letter_start"),
                   ("از غذات ساده عکس نگیر:", "letter_start2")]:
    _o = f.ensure_rtl_lines(_txt)
    check(f"rtl.marker_is_RLM.{_lbl}", _o.startswith(RLM), repr(_o))
    check(f"rtl.no_RLE.{_lbl}", RLE not in _o and PDF not in _o, repr(_o))
    # اولین نویسه باید کلاسِ bidi=R داشته باشد (که تلگرام راست‌چینش می‌کند)
    check(f"rtl.first_char_bidi_R.{_lbl}", _ud.bidirectional(_o[0]) == "R", f"got {_ud.bidirectional(_o[0])}")

# ب-0b: بینِ متنِ کپشن و بلاک‌کوت باید یک خطِ خالی باشد (وگرنه آخرین خطِ متن که به
# نقل‌قول چسبیده در تلگرام راست‌چین نمی‌شود — کشفِ کاربر با تستِ واقعی).
_bq_in = "🔌 وضعیت : متصل تا زمان فیلتر\n<blockquote>ss://abc@1.2.3.4:443#n</blockquote>"
_bq_out = f.ensure_rtl_lines(_bq_in)
check("rtl.blank_before_blockquote", "\n\n<blockquote" in _bq_out, repr(_bq_out))
# آخرین خطِ متن باید RLM بگیرد
check("rtl.last_line_marked", (RLM + "🔌") in _bq_out, repr(_bq_out))
# idempotency: اجرای دوباره نباید خطِ خالیِ دوم بسازد
_bq_out2 = f.ensure_rtl_lines(_bq_out)
check("rtl.blank_before_bq_idempotent", _bq_out == _bq_out2 and "\n\n\n" not in _bq_out2, repr(_bq_out2))
# دو بلاک‌کوتِ پشتِ‌سرهم باید با یک \n بمانند (نه خطِ خالی)
_two = f.ensure_rtl_lines("<blockquote>الف</blockquote><blockquote>ب</blockquote>")
check("rtl.adjacent_bq_no_blank", "</blockquote>\n<blockquote" in _two and "</blockquote>\n\n<blockquote" not in _two, repr(_two))

# ب-0c: خطِ پرچم‌دار (پرچم = چپ‌به‌راست) باید پرچمش به آخر برود تا راست‌چین شود.
import unicodedata as _ud2
_flag_in = "🇵🇱🇩🇪🇺🇸 موقعیت سرور :\n<blockquote>vless://x</blockquote>"
_flag_out = f.ensure_rtl_lines(_flag_in)
_flag_line = [l for l in _flag_out.split("\n") if "موقعیت" in l][0]
# اولین نویسه‌ی «قویِ» خط باید RTL باشد (پرچم رفته آخر)
_fc = next((c for c in _flag_line if c != RLM), "")
check("rtl.flag_line_starts_rtl", _ud2.bidirectional(_fc) in ("R", "AL"), repr(_flag_line))
check("rtl.flag_moved_to_end", _flag_line.rstrip().endswith("🇵🇱🇩🇪🇺🇸"), repr(_flag_line))
# ایموجیِ خنثی (👑) نباید جابه‌جا شود
_crown = f.ensure_rtl_lines("👑 کانفیگ فیلترشکن")
check("rtl.neutral_emoji_kept", "👑" in _crown[:3], repr(_crown))
# idempotency
check("rtl.flag_idempotent", f.ensure_rtl_lines(_flag_out) == _flag_out, "")
# خطِ فقط‌پرچم (بدونِ فارسی) نباید تغییر کند
check("rtl.pure_flags_untouched", f.ensure_rtl_lines("🇩🇪🇫🇷") == "🇩🇪🇫🇷", "")

# ب-0d: پرچمِ داخلِ <tg-emoji> (ایموجیِ پرمیوم) که قبل از متنِ فارسی است باید
# به‌عنوانِ یک تگِ کامل و سالم (نه فقط نویسه‌ی پرچم) به آخرِ خط منتقل شود؛ تگِ
# خالیِ <tg-emoji></tg-emoji> نباید جا بماند و emoji-id نباید گم شود.
_tge_in = '<tg-emoji emoji-id="555">🇫🇷</tg-emoji> ویدیو جدید فرانسوی'
_tge_out = f.ensure_rtl_lines(_tge_in)
check("rtl.tg_emoji_flag_no_empty_tag", "<tg-emoji emoji-id=\"555\"></tg-emoji>" not in _tge_out, repr(_tge_out))
check("rtl.tg_emoji_flag_id_preserved", 'emoji-id="555"' in _tge_out, repr(_tge_out))
check("rtl.tg_emoji_flag_moved_intact", _tge_out.rstrip().endswith('<tg-emoji emoji-id="555">🇫🇷</tg-emoji>'), repr(_tge_out))
_tge_fc = next((c for c in _tge_out if c != RLM), "")
check("rtl.tg_emoji_flag_line_starts_rtl", _ud2.bidirectional(_tge_fc) in ("R", "AL"), repr(_tge_out))
# idempotency برای پرچمِ داخلِ tg-emoji
check("rtl.tg_emoji_flag_idempotent", f.ensure_rtl_lines(_tge_out) == _tge_out, "")
# ترکیبِ پرچمِ ساده + پرچمِ داخلِ tg-emoji قبل از متنِ فارسی: هر دو باید سالم منتقل شوند
_mix_out = f.ensure_rtl_lines('🇩🇪<tg-emoji emoji-id="777">🇺🇸</tg-emoji> موقعیت سرور :')
check("rtl.tg_emoji_flag_mixed_both_moved", _mix_out.rstrip().endswith('🇩🇪<tg-emoji emoji-id="777">🇺🇸</tg-emoji>'), repr(_mix_out))
check("rtl.tg_emoji_flag_mixed_id_preserved", 'emoji-id="777"' in _mix_out, repr(_mix_out))

# ب-0e: خطِ خالیِ بینِ کپشن و نقل‌قول باید صرف‌نظر از این‌که خطِ ماقبلِ نقل‌قول
# (خطِ دوم، سوم، یا هر خطی) با چه ایموجی/تگ/متنی شروع یا تموم شده باشد حفظ شود.
# باگِ کشف‌شده: html.parser (داخلِ _balance_html) وقتی آن خط به یک تگِ بسته ختم
# می‌شد (مثلاً بعدِ جابه‌جاییِ پرچمِ tg-emoji به آخرِ خط) خطِ خالی را در سریالایزِ
# دوباره به یک \n تنها فشرده می‌کرد.
_bq_cases = [
    ("3line_tgemoji_flag_end", 'کانفیگ فیلترشکن\nوضعیت : متصل\n<tg-emoji emoji-id="9">🇫🇷</tg-emoji> موقعیت سرور\n<blockquote>vless://x</blockquote>'),
    ("2line_bold_tag_end", 'کانفیگ جدید\nوضعیت <b>متصل</b>\n<blockquote>vless://x</blockquote>'),
    ("2line_neutral_tgemoji_end", 'کانفیگ جدید\nوضعیت متصل <tg-emoji emoji-id="1">😀</tg-emoji>\n<blockquote>vless://x</blockquote>'),
    ("2line_plain_emoji_end", 'کانفیگ جدید\nوضعیت متصل 🔥\n<blockquote>vless://x</blockquote>'),
    ("3line_plain_text_end", 'خط یک\nخط دو\nخط سه بدونِ تگ\n<blockquote>vless://x</blockquote>'),
]
for _lbl, _in in _bq_cases:
    _out = f.ensure_rtl_lines(_in)
    check(f"rtl.blank_before_bq_preserved.{_lbl}", "\n\n<blockquote" in _out, repr(_out))
    check(f"rtl.blank_before_bq_preserved_idempotent.{_lbl}", f.ensure_rtl_lines(_out) == _out, repr(_out))

# ب-1: راست‌چینی: خط فارسی نشانگر بگیرد؛ خط فقط‌عددی/لاتین نه
out = f.ensure_rtl_lines("سلام دنیا")
check("rtl.persian_marked", RLE in out or RLM in out, repr(out))
out2 = f.ensure_rtl_lines("17:22   1405/04/26")
check("rtl.numeric_untouched", RLE not in out2 and RLM not in out2, repr(out2))
out3 = f.ensure_rtl_lines("Hello World")
check("rtl.latin_untouched", RLE not in out3 and RLM not in out3, repr(out3))
# داخل code/pre نباید دست بخورد
out4 = f.ensure_rtl_lines("<pre>vless://abc</pre>")
check("rtl.pre_untouched", RLE not in out4 and RLM not in out4, repr(out4))
outc = f.ensure_rtl_lines("<code>سلام</code>")
check("rtl.code_untouched", RLE not in outc and RLM not in outc, repr(outc))

# ب-2: Idempotency — اجرای دوباره نباید نشانگر تکراری بسازد
once = f.ensure_rtl_lines("سلام دنیا")
twice = f.ensure_rtl_lines(once)
check("rtl.idempotent_simple", once == twice, f"\n once={once!r}\n twice={twice!r}")
# روی blockquote
bq = "<blockquote>سلام این نقل‌قول است</blockquote>"
o1 = f.ensure_rtl_lines(bq)
o2 = f.ensure_rtl_lines(o1)
check("rtl.idempotent_blockquote", o1 == o2, f"\n o1={o1!r}\n o2={o2!r}")
# شمارش نشانگرها روی blockquote نباید دو برابر شود
check("rtl.blockquote_single_marker", o1.count(RLE) <= 1, f"count={o1.count(RLE)} o1={o1!r}")

# ب-3: محتوا نباید تغییر کند بعد از حذف نویسه‌های نامرئی (idempotency روی متن ساده چندخطی)
multi = "خط اول\nخط دوم\nخط سوم"
om1 = f.ensure_rtl_lines(multi)
om2 = f.ensure_rtl_lines(om1)
check("rtl.multiline_idempotent", om1 == om2, f"\n om1={om1!r}\n om2={om2!r}")

# ب-4: بین متن و فوتر همیشه دقیقاً یک خط خالی.
# نکته: append_footer عمداً خطِ خالیِ عمدی را با نشانه‌ی _GAP_MARK علامت می‌زند تا
# از _collapse_blankish_runs جانِ سالم به‌در ببرد (وگرنه blank_lines=2 همیشه یک
# خط می‌شد)؛ خودِ نشانه در آخرین مرحله (ensure_rtl_lines) پاک می‌شود. پس ثابتِ
# واقعی روی *خروجیِ نهایی* است، نه روی خروجیِ خامِ append_footer.
footer = '<a href="https://t.me/x">@x</a>'
for body, label in [
    ("متن پست", "zero_blank"),
    ("متن پست\n", "one_nl"),
    ("متن پست\n\n\n\n\n", "five_nl"),
    ("متن پست\n" + RLM + "\n‌", "invisible"),
]:
    raw = f.append_footer(body, footer)
    res = f.ensure_rtl_lines(raw)
    # دقیقاً یک خطِ خالی بین بدنه و فوتر، و هیچ نشانه‌ی داخلی‌ای باقی نمانده
    ok = res.endswith(f"متن پست\n\n{footer}") and f._GAP_MARK not in res
    check(f"footer.one_blank.{label}", ok, repr(res))

# ب-4-ب: blank_lines=2 (امضای فایل‌های .nm/.npvt) واقعاً دو خطِ خالی می‌دهد —
# همون باگی که _GAP_MARK برای رفعش اضافه شد.
res2 = f.ensure_rtl_lines(f.append_footer("متن پست", footer, blank_lines=2))
check("footer.two_blank_lines_kept", res2.endswith(f"متن پست\n\n\n{footer}"), repr(res2))

# ب-5: تگ‌های خاص سالم بمانند
# blockquote expandable (نه expandable="")
be = f.ensure_rtl_lines("<blockquote expandable>متن گسترده</blockquote>")
check("tags.blockquote_expandable", 'expandable="' not in be and "expandable" in be, repr(be))
# tg-emoji emoji-id حفظ شود وقتی premium روشن است (strip نشود در ensure_rtl)
te = f.ensure_rtl_lines('<tg-emoji emoji-id="123">😀</tg-emoji> سلام')
check("tags.tg_emoji_preserved", 'emoji-id="123"' in te, repr(te))
# tg-spoiler
ts = f.ensure_rtl_lines("<tg-spoiler>راز</tg-spoiler> متن")
check("tags.tg_spoiler", "<tg-spoiler>" in ts and "</tg-spoiler>" in ts, repr(ts))
# دو نقل‌قول پشت‌سرهم
two_bq = "<blockquote>اول</blockquote><blockquote>دوم</blockquote>"
tb = f.ensure_rtl_lines(two_bq)
check("tags.two_blockquotes", tb.count("<blockquote>") == 2, repr(tb))

# ب-6: توازن تگ — حذف خط منشن که </b> رویش است
# body با بولد چندخطی که بستنش روی خط منشن است
raw = "<b>عنوان مهم\nاطلاعات بیشتر @SourceChannel</b>"
# clean_post_html با self_username=SourceChannel خط منشن را حذف می‌کند
from bs4 import BeautifulSoup
node = BeautifulSoup(f"<div>{raw}</div>", "html.parser").div
cleaned = f.clean_post_html(node, "SourceChannel")
# باید متوازن باشد: تعداد <b> == </b>
nb_open = cleaned.count("<b>"); nb_close = cleaned.count("</b>")
check("balance.bold_closed", nb_open == nb_close, f"open={nb_open} close={nb_close} cleaned={cleaned!r}")

# ب-7: رشته‌های کانفیگ هرگز تغییر نکنند
for cfg in ["vless://uuid@host:443?type=tcp", "trojan://pass@h:1", "ss://abc@d:2", "tg://proxy?server=x"]:
    body = f"کانفیگ:\n<code>{cfg}</code>"
    node = BeautifulSoup(f"<div>{body}</div>", "html.parser").div
    cleaned = f.clean_post_html(node, "SomeChannel")
    check(f"config.untouched.{cfg[:8]}", cfg in cleaned, f"cleaned={cleaned!r}")

# ب-8: تغییرِ نامِ لینک‌هایی که متنِ نمایشی‌شون دقیقاً «آواکادوپروکسی» است
_h1 = '<a href="https://t.me/proxy?server=x">آواکادوپروکسی</a>'
_o1 = f.rename_avocado_proxy_links_in_html(_h1)
check("avocado.single_no_number", "پروکسی</a>" in _o1 and "پروکسی 1" not in _o1, _o1)
check("avocado.single_word_gone", "آواکادوپروکسی" not in _o1, _o1)

_h2 = "\n".join(f'<a href="https://t.me/proxy?server={i}">آواکادوپروکسی</a>' for i in range(1, 4))
_o2 = f.rename_avocado_proxy_links_in_html(_h2)
check("avocado.multi_numbered", all(f"پروکسی {i}</a>" in _o2 for i in (1, 2, 3)), _o2)
check("avocado.multi_word_gone", "آواکادوپروکسی" not in _o2, _o2)
_o2b = f.rename_avocado_proxy_links_in_html(_o2)
check("avocado.idempotent", _o2b == _o2, f"{_o2b!r} != {_o2!r}")

_h3 = ('<a href="https://t.me/proxy?a">آواکادوپروکسی</a>\n'
       '<a href="https://t.me/proxy?b">پروکسی</a>\n'
       '<a href="https://example.com">یک لینکِ دیگه</a>')
_o3 = f.rename_avocado_proxy_links_in_html(_h3)
check("avocado.existing_proxy_untouched", 'href="https://t.me/proxy?b">پروکسی</a>' in _o3, _o3)
check("avocado.other_link_untouched", 'href="https://example.com">یک لینکِ دیگه</a>' in _o3, _o3)

_h4 = '<a href="https://t.me/proxy?z">آواکادوپروکسی ویژه</a>'
_o4 = f.rename_avocado_proxy_links_in_html(_h4)
check("avocado.partial_phrase_untouched", _o4 == _h4, _o4)

_h5 = '<a href="https://t.me/proxy?y">پروکسی</a>'
_o5 = f.rename_avocado_proxy_links_in_html(_h5)
check("avocado.no_avocado_word_noop", _o5 == _h5, _o5)

# ب-9: کپشنِ پویا بسته به کانفیگ/پروکسیِ نگه‌داشته‌شده در نقل‌قول‌ها
_mixed = ('<blockquote>https://t.me/proxy?server=x&amp;secret=abc</blockquote>'
          '<blockquote>vless://uuid@host:443?security=reality</blockquote>')
_out_mixed = f.apply_fixed_config_caption(_mixed)
check("caption.mixed_both", _out_mixed.startswith(f.FIXED_CONFIG_AND_PROXY_CAPTION), _out_mixed)

_cfg_only = '<blockquote>vless://uuid@host:443?type=tcp</blockquote>'
_out_cfg = f.apply_fixed_config_caption(_cfg_only)
check("caption.config_only", _out_cfg.startswith(f.FIXED_CONFIG_CAPTION), _out_cfg)

_proxy_only = '<blockquote>tg://proxy?server=1.2.3.4&amp;port=443</blockquote>'
_out_proxy = f.apply_fixed_config_caption(_proxy_only)
check("caption.proxy_only", _out_proxy.startswith(f.FIXED_PROXY_CAPTION), _out_proxy)

_no_bq = "یک متنِ ساده بدونِ نقل‌قول"
check("caption.no_blockquote_untouched", f.apply_fixed_config_caption(_no_bq) == _no_bq)

_out_mixed2 = f.apply_fixed_config_caption(_out_mixed)
check("caption.idempotent", _out_mixed2 == _out_mixed, f"{_out_mixed2!r} != {_out_mixed!r}")

print("\n=== FORMATTER:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
