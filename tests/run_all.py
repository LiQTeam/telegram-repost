# -*- coding: utf-8 -*-
"""Run the whole regression suite. Exit non-zero if any invariant fails.

Usage:  python3 tests/run_all.py   (or from inside tests/:  python3 run_all.py)

Dependencies (lightweight subset — no torch/cv2/Pillow needed):
    pip install beautifulsoup4 lxml httpx python-telegram-bot python-dotenv jdatetime
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = [
    "test_formatter.py",
    "test_adfilter.py",
    "test_ad_feedback_stats.py",
    "test_scraper.py",
    "test_poster.py",
    "test_e2e.py",
    "test_button_colors.py",
    "test_v240_modules.py",
    "test_database.py",
    "test_dedup_cache_backup.py",
    "test_menu_smoke.py",
]

def main() -> int:
    failed = []
    for m in MODULES:
        print("\n" + "#" * 72)
        print("# RUNNING", m)
        print("#" * 72)
        # ⚠️ فیکس: قبلاً فقط کدِ خروج چک می‌شد، ولی چند فایلِ تست (مثلِ
        # test_formatter.py و test_poster.py) خطاهاشون رو فقط با چاپِ خطِ
        # «FAIL ...» اعلام می‌کنن و بازهم با کدِ ۰ خارج می‌شن — یعنی یک
        # رگرسیونِ واقعی می‌تونست بی‌سروصدا از کلِ سوییت رد بشه (و شد).
        # حالا خروجی هم گرفته و دنبالِ نشانه‌ی FAIL می‌گردیم.
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, m)],
            cwd=HERE, capture_output=True, text=True,
        )
        out = (r.stdout or "") + (r.stderr or "")
        print(out, end="" if out.endswith("\n") else "\n")
        has_fail_marker = any(
            line.startswith("FAIL ") or " FAIL:" in line
            for line in out.splitlines()
        )
        if r.returncode != 0 or has_fail_marker:
            failed.append(m)
    print("\n" + "=" * 72)
    if failed:
        print("SUITE RESULT: FAILURES in", failed)
        return 1
    print(f"SUITE RESULT: ALL PASS ({len(MODULES)} modules)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
