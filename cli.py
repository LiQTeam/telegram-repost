#!/usr/bin/env python3
"""
ابزار خط فرمان برای مدیریت ربات از طریق سرور

استفاده:
    python cli.py add-destination <chat_id> [title]
    python cli.py add-source <username> [title] [--instant] [--link=<chat_id>]
    python cli.py list-sources [--active]
    python cli.py list-destinations [--active]
    python cli.py stats
    python cli.py backup [--create] [--restore <file>]
"""
import argparse
import asyncio
import os

from bot.database import db
from bot.scraper import fetch_latest_post_id
from bot.backup_manager import BackupManager
from bot.jdatetime_utils import now_jalali


def add_destination(chat_id: str, title: str = ""):
    """افزودن کانال مقصد"""
    ok = db.add_destination(chat_id, title)
    if ok:
        print(f"✅ کانال مقصد {chat_id} اضافه شد.")
    else:
        print(f"⚠️ کانال مقصد {chat_id} قبلا وجود دارد.")


def add_source(username: str, title: str = "", instant: bool = False, link: str = None):
    """افزودن کانال مبدأ"""
    ok = db.add_channel(username, title)
    if not ok:
        print(f"⚠️ کانال مبدأ @{username} قبلا وجود دارد.")
        return

    ch = next((c for c in db.list_channels() if c["username"] == username.lower()), None)
    if not ch:
        print(f"❌ کانال @{username} پیدا نشد.")
        return

    cid = ch["id"]

    # تنظیم حالت ارسال
    if instant:
        db.set_channel_send_mode(cid, "instant")
        try:
            baseline_id = asyncio.run(fetch_latest_post_id(username))
            if baseline_id:
                db.update_last_post(cid, baseline_id)
                print(f"   آخرین پست: {baseline_id}")
        except Exception as e:
            print(f"   ⚠️ پایه‌گذاری last_post_id ناموفق: {e}")

    # اتصال به مقصد
    if link:
        dest = next((d for d in db.list_destinations() if d["chat_id"] == link), None)
        if dest:
            db.toggle_link(cid, dest["id"])
            print(f"   🔗 متصل به مقصد: {link}")
        else:
            print(f"   ⚠️ مقصد {link} پیدا نشد.")

    print(f"✅ کانال مبدأ @{username} اضافه شد.")


def add_user(name: str, approval_chat_id: str, telegram_id: str = ""):
    """افزودن کاربر با کانال تایید اختصاصی"""
    existing = next(
        (u for u in db.list_users() if str(u["approval_chat_id"]) == str(approval_chat_id)),
        None,
    )
    if existing:
        print(f"⚠️ کاربری با کانال تایید {approval_chat_id} از قبل وجود دارد ({existing['name']}).")
        return

    tid = int(telegram_id) if telegram_id else None
    uid = db.add_user(name, tid, int(approval_chat_id))
    print(f"✅ کاربر «{name}» اضافه شد (id={uid}, approval_chat_id={approval_chat_id}).")


def list_sources(active_only: bool = False):

    """لیست کانال‌های مبدأ"""
    channels = db.list_channels(active_only)
    if not channels:
        print("📡 هیچ کانال مبدأیی وجود ندارد.")
        return

    print(f"📡 کانال‌های مبدأ ({'فعال' if active_only else 'همه'}):")
    print("-" * 60)
    for ch in channels:
        status = "🟢" if ch["active"] else "⚪️"
        mode = ch["send_mode"] or "schedule"
        dest_count = len(db.linked_destination_ids(ch["id"]))
        title = ch["title"] or "بدون اسم"
        print(f"{status} @{ch['username']:<20} - {title:<20} - {mode:<10} - 🎯{dest_count}")


def list_destinations(active_only: bool = False):
    """لیست کانال‌های مقصد"""
    destinations = db.list_destinations(active_only)
    if not destinations:
        print("🎯 هیچ کانال مقصدی وجود ندارد.")
        return

    print(f"🎯 کانال‌های مقصد ({'فعال' if active_only else 'همه'}):")
    print("-" * 60)
    for d in destinations:
        status = "🟢" if d["active"] else "⚪️"
        src_count = len(db.linked_channels_for_destination(d["id"]))
        title = d["title"] or "بدون اسم"
        print(f"{status} {d['chat_id']:<25} - {title:<20} - 📡{src_count}")


def show_stats():
    """نمایش آمار کلی"""
    stats = db.stats()
    print("📊 آمار ربات")
    print(f"{'─' * 40}")
    print(f"📡 کانال‌های مبدأ: {stats['total_channels']} (فعال: {stats['active_channels']})")
    print(f"🎯 کانال‌های مقصد: {stats['total_destinations']} (فعال: {stats['active_destinations']})")
    print(f"📨 پست امروز: {stats['sent_today']}")
    print(f"🗂 مجموع پست‌ها: {stats['sent_total']}")
    print(f"🚫 پست‌های فیلترشده: {stats['ad_filtered_total']}")


def create_backup():
    """ایجاد بکاپ فوری"""
    print("⏳ در حال ایجاد بکاپ...")
    encrypted = BackupManager.create_backup()
    filename = f"backup_{now_jalali().strftime('%Y%m%d_%H%M')}.backup"
    with open(filename, "wb") as f:
        f.write(encrypted)
    print(f"✅ بکاپ در {filename} ذخیره شد (حجم: {len(encrypted) // 1024} کیلوبایت)")


def restore_backup(file_path: str):
    """بازیابی از فایل بکاپ"""
    if not os.path.exists(file_path):
        print(f"❌ فایل {file_path} وجود ندارد.")
        return

    print(f"⏳ در حال بازیابی از {file_path}...")
    with open(file_path, "rb") as f:
        encrypted = f.read()

    ok, msg = BackupManager.restore_backup(encrypted)
    if ok:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")


def main():
    parser = argparse.ArgumentParser(
        description="ابزار مدیریت ربات MR LiQ از خط فرمان",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
مثال‌ها:
  python cli.py add-destination -1001234567890 "کانال اصلی"
  python cli.py add-source mychannel "کانال خبری" --instant --link=-1001234567890
  python cli.py list-sources
  python cli.py list-destinations --active
  python cli.py stats
  python cli.py backup --create
  python cli.py backup --restore backup_20240101_0300.backup
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="دستورات")

    # add-destination
    dest_parser = subparsers.add_parser("add-destination", help="افزودن کانال مقصد")
    dest_parser.add_argument("chat_id", help="آیدی عددی یا یوزرنیم کانال مقصد")
    dest_parser.add_argument("title", nargs="?", default="", help="اسم دلخواه")

    # add-user
    user_parser = subparsers.add_parser("add-user", help="افزودن کاربر با کانال تایید اختصاصی")
    user_parser.add_argument("name", help="اسم کاربر")
    user_parser.add_argument("approval_chat_id", help="آیدی عددی کانال/گروه تایید اختصاصی کاربر")
    user_parser.add_argument("telegram_id", nargs="?", default="", help="آیدی عددی تلگرام کاربر (اختیاری)")

    # add-source
    src_parser = subparsers.add_parser("add-source", help="افزودن کانال مبدأ")

    src_parser.add_argument("username", help="یوزرنیم کانال مبدأ (بدون @)")
    src_parser.add_argument("title", nargs="?", default="", help="اسم دلخواه")
    src_parser.add_argument("--instant", action="store_true", help="فعال کردن حالت ارسال لحظه‌ای")
    src_parser.add_argument("--link", help="اتصال به کانال مقصد با آیدی")

    # list-sources
    src_list_parser = subparsers.add_parser("list-sources", help="لیست کانال‌های مبدأ")
    src_list_parser.add_argument("--active", action="store_true", help="فقط کانال‌های فعال")

    # list-destinations
    dest_list_parser = subparsers.add_parser("list-destinations", help="لیست کانال‌های مقصد")
    dest_list_parser.add_argument("--active", action="store_true", help="فقط کانال‌های فعال")

    # stats
    subparsers.add_parser("stats", help="نمایش آمار کلی")

    # backup
    backup_parser = subparsers.add_parser("backup", help="مدیریت بکاپ")
    backup_group = backup_parser.add_mutually_exclusive_group(required=True)
    backup_group.add_argument("--create", action="store_true", help="ایجاد بکاپ فوری")
    backup_group.add_argument("--restore", metavar="FILE", help="بازیابی از فایل بکاپ")

    args = parser.parse_args()

    if args.command == "add-destination":
        add_destination(args.chat_id, args.title)
    elif args.command == "add-source":
        add_source(args.username, args.title, args.instant, args.link)
    elif args.command == "add-user":
        add_user(args.name, args.approval_chat_id, args.telegram_id)

    elif args.command == "list-sources":
        list_sources(args.active)
    elif args.command == "list-destinations":
        list_destinations(args.active)
    elif args.command == "stats":
        show_stats()
    elif args.command == "backup":
        if args.create:
            create_backup()
        elif args.restore:
            restore_backup(args.restore)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()