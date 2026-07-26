# Contributing / راهنمای مشارکت

از مشارکتِ شما استقبال می‌کنیم! 🙌 — Contributions are welcome!

## English

1. **Fork** the repository and create a feature branch:
   `git checkout -b feature/my-change`
2. Set up a local environment:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Make your changes. Keep the existing code style (the codebase uses short
   Persian comments next to non-obvious logic — match that where it helps).
4. **Run the tests** before opening a PR:
   ```bash
   python3 tests/run_all.py
   ```
5. Never commit secrets. `.env`, the SQLite database, and downloaded model
   weights are git-ignored — keep them out of commits.
6. Open a **Pull Request** with a clear description of *what* changed and
   *why*. Reference any related Issue.

For bug reports and feature requests, please open an **Issue** with steps to
reproduce (and `data/bot.log` excerpts when relevant).

## فارسی

۱. مخزن را **fork** کن و یک شاخه‌ی جدید بساز:
   `git checkout -b feature/my-change`
۲. محیطِ محلی را آماده کن:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
۳. تغییراتت را اعمال کن و سبکِ کدِ موجود را حفظ کن (کامنت‌های کوتاهِ فارسی کنارِ
   منطقِ غیربدیهی).
۴. پیش از باز کردنِ PR، **تست‌ها را اجرا کن**:
   ```bash
   python3 tests/run_all.py
   ```
۵. هیچ‌وقت اطلاعاتِ محرمانه را commit نکن. فایلِ `.env`، دیتابیسِ SQLite و
   وزنِ مدل‌های دانلودشده در `.gitignore` هستند.
۶. یک **Pull Request** با توضیحِ واضحِ «چه چیزی» و «چرا» باز کن و به Issueِ
   مرتبط (در صورت وجود) اشاره کن.

برای گزارشِ باگ یا پیشنهاد، لطفاً یک **Issue** با مراحلِ بازتولید (و در صورتِ
نیاز بخشی از `data/bot.log`) باز کن.
