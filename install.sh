#!/usr/bin/env bash
# ============================================================
#  نصب کاملاً خودکارِ ربات ری‌پست هوشمند MR LiQ
#  اجرا: sudo bash install.sh
#  هیچ سوالی پرسیده نمی‌شه؛ همه‌چیز از قبل تنظیم شده.
# ============================================================
set -euo pipefail

C_RESET="\033[0m"
C_GREEN="\033[1;32m"
C_RED="\033[1;31m"
C_CYAN="\033[1;36m"
C_YEL="\033[1;33m"
C_MAG="\033[1;35m"

info()  { echo -e "${C_CYAN}[i]${C_RESET} $1"; }
ok()    { echo -e "${C_GREEN}[✓]${C_RESET} $1"; }
warn()  { echo -e "${C_YEL}[!]${C_RESET} $1"; }
err()   { echo -e "${C_RED}[x]${C_RESET} $1"; }
title() { echo -e "${C_MAG}$1${C_RESET}"; }

if [[ $EUID -ne 0 ]]; then
   err "این اسکریپت باید با دسترسی root/sudo اجرا بشه. مثال: sudo bash install.sh"
   exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
#  تنظیمات نصب — این مقادیر رو موقعِ اجرا از خودت می‌پرسه
#
#  ⚠️ هیچ توکن/کلید/آیدیِ واقعی نباید توی این فایل ذخیره بشه. این فایل داخلِ
#  مخزنِ گیت است؛ هر مقداری که اینجا هاردکد بشه عملاً منتشر شده و باید فوراً
#  باطل/جایگزین بشه. برای نصبِ بدونِ تعامل (اسکریپتی/CI) همین متغیرها رو
#  به‌عنوانِ متغیرِ محیطی پاس بده، مثلاً:
#      BOT_TOKEN=... ADMIN_IDS=... ./install.sh
# ============================================================
TZ_VALUE="Asia/Tehran"
SERVICE_NAME="mrliq-bot"
PANEL_CMD="mrliq"

echo ""
title "=== تنظیمات اولیه‌ی ربات ==="
# هر کدام که از قبل به‌صورتِ متغیرِ محیطی داده شده باشه، پرسیده نمی‌شه.
[[ -n "${BOT_TOKEN:-}" ]]       || read -rp "توکن ربات تلگرام (از @BotFather): " BOT_TOKEN
[[ -n "${ADMIN_IDS:-}" ]]      || read -rp "آیدی عددیِ ادمین(ها) (با کاما جدا کن اگه چندتان): " ADMIN_IDS
[[ -n "${DEFAULT_DEST_ID:-}" ]] || read -rp "آیدی عددیِ کانال مقصدِ پیش‌فرض (مثلاً -1001234567890) [اختیاری، Enter=رد شو]: " DEFAULT_DEST_ID
[[ -n "${MISTRAL_API_KEY:-}" ]] || read -rp "Mistral API Key [اختیاری، Enter=رد شو]: " MISTRAL_API_KEY
[[ -n "${GROQ_API_KEY:-}" ]]   || read -rp "Groq API Key [اختیاری، Enter=رد شو]: " GROQ_API_KEY
echo ""

if [[ -z "${BOT_TOKEN// }" ]]; then
  err "توکن ربات نمی‌تونه خالی باشه."
  exit 1
fi

# کاربرانی که می‌خوای موقعِ نصب با کانالِ تاییدِ اختصاصی اضافه بشن.
# فرمتِ هر آیتم: "اسم|آیدی کانال تایید|آیدی تلگرام کاربر (اختیاری)"
# مثال: DEFAULT_USERS=("علی|-1001111111111|123456789")
DEFAULT_USERS=()

# کانال‌های مبدأیی که می‌خوای موقعِ نصب خودکار اضافه بشن (یوزرنیم بدونِ @).
# مثال: DEFAULT_SOURCE_CHANNELS=(somechannel anotherchannel)
DEFAULT_SOURCE_CHANNELS=()

# ============================================================
#  هدر
# ============================================================
clear
title "============================================================"
title "   نصب‌کننده‌ی کاملاً خودکارِ ربات ری‌پست هوشمند MR LiQ"
title "============================================================"
echo ""

# ============================================================
#  پیش‌نیازهای سیستمی
# ============================================================
info "در حال بررسی و نصب پیش‌نیازهای سیستمی..."

if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null
    apt-get install -y \
        python3 \
        python3-venv \
        python3-pip \
        curl \
        wget \
        git \
        gnupg \
        lsb-release \
        fonts-dejavu-core \
        build-essential \
        >/dev/null
    ok "پکیج‌های سیستمی (apt) نصب شدند."
elif command -v yum >/dev/null 2>&1; then
    yum install -y \
        python3 \
        python3-pip \
        curl \
        wget \
        git \
        >/dev/null
    ok "پکیج‌های سیستمی (yum) نصب شدند."
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y \
        python3 \
        python3-pip \
        curl \
        wget \
        git \
        >/dev/null
    ok "پکیج‌های سیستمی (dnf) نصب شدند."
else
    warn "پکیج‌منیجر سیستم شناسایی نشد؛ فرض می‌کنیم پیش‌نیازها از قبل نصب‌اند."
fi

if ! command -v python3 >/dev/null 2>&1; then
    err "python3 پیدا نشد. اول اونو نصب کن و دوباره اجرا کن."
    exit 1
fi

if ! command -v pip3 >/dev/null 2>&1; then
    warn "pip3 پیدا نشد، در حال نصب..."
    python3 -m ensurepip --upgrade >/dev/null || true
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "پایتون نسخه $PY_VERSION نصب است."
ok "پیش‌نیازهای سیستمی آماده‌ست."

# ============================================================
#  پروکسی Cloudflare WARP برای Gemini (کاملاً خودکار)
# ============================================================
#  روی بعضی سرورها (مخصوصاً سرورهای ایران یا هر آی‌پی‌ای که گوگل بلاکش
#  کرده) تماسِ مستقیم به Gemini API با خطای ۴۰۳ (User location is not
#  supported) مواجه می‌شه و ماژول‌های AI که از Gemini استفاده می‌کنن کار
#  نمی‌کنن. این بخش یک تونل WARP در «حالت پروکسی» می‌سازه (فقط پورتِ
#  لوکالِ ${WARP_PROXY_PORT:-40000} رو پروکسی می‌کنه، نه کل شبکه‌ی سرور -
#  پس SSH و بقیه‌ی سرویس‌ها هیچ تأثیری نمی‌بینن) و در صورتِ موفقیت،
#  GEMINI_PROXY_URL رو خودش توی .env می‌ذاره تا bot/ai_adapters.py (که
#  از GEMINI_PROXY_URL در bot/config.py می‌خونه) خودکار ازش استفاده کنه.
#  اگه نصبِ WARP به هر دلیلی شکست بخوره، این بخش فقط هشدار می‌ده و
#  نصبِ بات رو متوقف نمی‌کنه - GEMINI_PROXY_URL خالی می‌مونه و ربات
#  بدونِ پروکسی (مستقیم) کار می‌کند.
# ============================================================
GEMINI_PROXY_URL_VALUE=""
WARP_PROXY_PORT=40000

# اجرای یک زیردستورِ warp-cli بدونِ اینکه با «set -e» کلِ اسکریپت رو
# در صورتِ شکست بترکونه (چون این مرحله باید «best effort» بمونه).
warp_run() { "$@" >/dev/null 2>&1; }

setup_cloudflare_warp_proxy() {
    echo ""
    title "------------------------------------------------------------"
    info "بررسی و راه‌اندازی خودکارِ پروکسیِ Cloudflare WARP برای Gemini..."
    title "------------------------------------------------------------"

    if ! command -v apt-get >/dev/null 2>&1; then
        warn "این مرحله فقط روی سیستم‌های مبتنی بر apt (اوبونتو/دبیان) خودکاره؛ رد شد."
        return 0
    fi

    # ------------------------------------------------------------
    # نصبِ کلاینتِ WARP (اگه از قبل نصب نباشه)
    # ------------------------------------------------------------
    if ! command -v warp-cli >/dev/null 2>&1; then
        info "در حال نصب کلاینت Cloudflare WARP..."
        mkdir -p /usr/share/keyrings
        if curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg 2>/dev/null; then
            echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs 2>/dev/null || echo stable) main" \
                > /etc/apt/sources.list.d/cloudflare-client.list
            if apt-get update -y >/dev/null 2>&1 && apt-get install -y cloudflare-warp >/dev/null 2>&1; then
                ok "کلاینت Cloudflare WARP نصب شد."
            else
                warn "نصب کلاینت WARP ناموفق بود؛ Gemini بدونِ پروکسی (مستقیم) کار خواهد کرد."
                return 0
            fi
        else
            warn "دریافتِ کلید امنیتیِ WARP ناموفق بود؛ Gemini بدونِ پروکسی (مستقیم) کار خواهد کرد."
            return 0
        fi
    else
        ok "کلاینت Cloudflare WARP از قبل نصب است."
    fi

    if ! command -v warp-cli >/dev/null 2>&1; then
        warn "warp-cli بعد از نصب پیدا نشد؛ این مرحله رد شد."
        return 0
    fi

    # ------------------------------------------------------------
    # اطمینان از بالا بودنِ سرویسِ warp-svc
    # ------------------------------------------------------------
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable --now warp-svc >/dev/null 2>&1 || true
        local i
        for i in $(seq 1 10); do
            warp_run warp-cli status && break
            sleep 1
        done
    fi

    # ------------------------------------------------------------
    # ثبت‌نام (فقط اگه از قبل ثبت‌نام نشده باشه - جلوگیری از ساختِ
    # ثبت‌نامِ تکراری روی سرورهایی که install.sh دوباره اجرا می‌شه)
    # ------------------------------------------------------------
    if ! warp_run warp-cli account; then
        info "در حال ثبت‌نامِ دستگاه در Cloudflare WARP..."
        (yes | warp-cli --accept-tos registration new >/dev/null 2>&1) || \
        (yes | warp-cli registration new >/dev/null 2>&1) || true
    else
        ok "دستگاه از قبل در Cloudflare WARP ثبت‌نام شده است."
    fi

    # ------------------------------------------------------------
    # تنظیمِ حالتِ پروکسی (SOCKS5) + پورتِ اختصاصی
    # ------------------------------------------------------------
    info "تنظیمِ WARP روی حالتِ پروکسی (SOCKS5, پورتِ ${WARP_PROXY_PORT})..."
    warp_run warp-cli mode proxy || warp_run warp-cli set-mode proxy
    warp_run warp-cli proxy port "${WARP_PROXY_PORT}" || warp_run warp-cli set-proxy-port "${WARP_PROXY_PORT}"

    # ------------------------------------------------------------
    # اتصال
    # ------------------------------------------------------------
    warp_run warp-cli connect
    sleep 3

    # ------------------------------------------------------------
    # تستِ واقعیِ عملکردِ پروکسی روی خودِ دامنه‌ی Gemini (نه فقط بالا
    # بودنِ سرویس) - هر کدِ HTTP معتبر یعنی درخواست واقعاً از پروکسی
    # تا سرورِ گوگل رفته و برگشته (۴۰۴/۴۰۳ روی مسیرِ ریشه طبیعیه).
    # ------------------------------------------------------------
    info "تستِ عملکردِ پروکسی روی سرورِ Gemini..."
    local HTTP_CODE
    HTTP_CODE=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
        -x "socks5h://127.0.0.1:${WARP_PROXY_PORT}" \
        "https://generativelanguage.googleapis.com/" 2>/dev/null || echo "000")

    if [[ "$HTTP_CODE" =~ ^[2-4][0-9][0-9]$ ]]; then
        ok "پروکسیِ WARP فعال و سالم است (کدِ پاسخِ گوگل: ${HTTP_CODE})."
        GEMINI_PROXY_URL_VALUE="socks5://127.0.0.1:${WARP_PROXY_PORT}"
        ok "GEMINI_PROXY_URL به‌صورت خودکار در .env تنظیم می‌شود."
    else
        warn "پروکسیِ WARP پاسخِ معتبر نداد (کدِ خام: ${HTTP_CODE})."
        warn "GEMINI_PROXY_URL خالی می‌ماند؛ اگه بعداً Gemini کار نکرد، با دستور"
        warn "  sudo systemctl status warp-svc  و  warp-cli status  بررسی کن."
    fi
}

setup_cloudflare_warp_proxy

# ============================================================
#  حذف محیط مجازی قبلی و ساخت جدید
# ============================================================
info "ساخت محیط مجازی پایتون (venv)..."

rm -rf venv
python3 -m venv venv

if [ ! -f "venv/bin/activate" ]; then
    err "ساخت venv ناموفق بود."
    exit 1
fi

source venv/bin/activate

# ارتقای pip
pip install --upgrade pip -q
ok "محیط مجازی ساخته شد."

# ============================================================
#  نصب کتابخانه‌های پایتون از requirements.txt
# ============================================================
info "در حال نصب کتابخانه‌های پایتون (این مرحله ۲-۵ دقیقه طول می‌کشد)..."

if [ ! -f "requirements.txt" ]; then
    err "فایل requirements.txt پیدا نشد."
    exit 1
fi

# نصب با --extra-index-url برای torch
# فیکسِ R10: با `set -e` فعال، اگه pip شکست بخوره اسکریپت بلافاصله خارج می‌شد و
# خطِ `if [ $? -ne 0 ]` هیچ‌وقت اجرا نمی‌شد (کدِ مرده). حالا خودِ دستور در شرطِ
# if قرار گرفته تا set -e موقتاً برای همین دستور کنار بره و fallback واقعاً کار کنه.
if pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu -q; then
    ok "همه کتابخانه‌های پایتون نصب شدند."
else
    warn "نصب با --extra-index-url ناموفق بود، تلاش مجدد بدون آن..."
    pip install -r requirements.txt -q
    ok "همه کتابخانه‌های پایتون نصب شدند (تلاشِ دوم)."
fi

# ============================================================
#  ایجاد پوشه‌های مورد نیاز
# ============================================================
info "ایجاد پوشه‌های پروژه..."

mkdir -p models data fonts
mkdir -p data/watermark_templates
mkdir -p logs

ok "پوشه‌های پروژه ایجاد شدند."

# ============================================================
#  دانلود مدل بهبود کیفیت تصویر (Real-ESRGAN)
# ============================================================
# ============================================================
#  دانلود مدل بهبود کیفیت تصویر (Real-ESRGAN)
# ============================================================
SR_MODEL_FILE="models/realesr-general-x4v3.pth"
SR_MODEL_URL="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth"
SR_DL_LOG="/tmp/sr_model_download.log"

if [[ -f "$SR_MODEL_FILE" ]]; then
    ok "مدل بهبود کیفیت از قبل موجود است (${SR_MODEL_FILE})"
else
    info "در حال دانلود مدل بهبود کیفیت تصویر (~۴.۷ مگابایت)..."
    rm -f "$SR_DL_LOG"
    if curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 -o "$SR_MODEL_FILE" "$SR_MODEL_URL" >"$SR_DL_LOG" 2>&1 || \
       wget -q --tries=3 --timeout=30 -O "$SR_MODEL_FILE" "$SR_MODEL_URL" >>"$SR_DL_LOG" 2>&1; then
        ACTUAL_SIZE=$(stat -c%s "$SR_MODEL_FILE" 2>/dev/null || echo 0)
        # آستانه‌ی واقعی: خود مدل حدود ۴.۷ مگابایت است؛ هر چیزی زیر ۱ مگابایت
        # قطعاً صفحه‌ی خطا/HTML است، نه فایل مدل واقعی.
        if [ -f "$SR_MODEL_FILE" ] && [ "$ACTUAL_SIZE" -gt 1000000 ]; then
            ok "مدل بهبود کیفیت دانلود شد (حجم: $(du -h "$SR_MODEL_FILE" | cut -f1))"
        else
            rm -f "$SR_MODEL_FILE"
            warn "فایل دانلودشده ناقص است (حجم: ${ACTUAL_SIZE} بایت)، حذف شد. جزئیات خطا: $(tail -3 "$SR_DL_LOG" 2>/dev/null)"
        fi
    else
        rm -f "$SR_MODEL_FILE"
        warn "دانلود مدل بهبود کیفیت شکست خورد (ربات بدون آن هم کار می‌کند). جزئیات خطا: $(tail -3 "$SR_DL_LOG" 2>/dev/null)"
    fi
fi

# ============================================================
#  دانلود مدل LaMa (حذف واترمارک با کیفیت بالا)
# ============================================================
LAMA_MODEL_FILE="models/big-lama.pt"
LAMA_MODEL_URL="https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"
LAMA_MODEL_MD5="e3aa4aaa15225a33ec84f9f4bc47e500"

if [[ -f "$LAMA_MODEL_FILE" ]]; then
    ok "مدل LaMa از قبل موجود است (${LAMA_MODEL_FILE})"
else
    info "در حال دانلود مدل LaMa (~۲۰۰ مگابایت، ممکن است ۵-۱۰ دقیقه طول بکشد)..."
    if curl -fL --retry 3 --retry-delay 5 --connect-timeout 60 -o "$LAMA_MODEL_FILE" "$LAMA_MODEL_URL" 2>/dev/null || \
       wget -q --tries=3 --timeout=60 -O "$LAMA_MODEL_FILE" "$LAMA_MODEL_URL" 2>/dev/null; then
        if [ -f "$LAMA_MODEL_FILE" ] && [ $(stat -c%s "$LAMA_MODEL_FILE" 2>/dev/null || echo 0) -gt 100000000 ]; then
            ok "مدل LaMa دانلود شد (حجم: $(du -h "$LAMA_MODEL_FILE" | cut -f1))"
        else
            rm -f "$LAMA_MODEL_FILE"
            warn "فایل دانلودشده ناقص است، حذف شد."
        fi
    else
        rm -f "$LAMA_MODEL_FILE"
        warn "دانلود مدل LaMa شکست خورد (ربات بدون آن هم کار می‌کند)."
    fi
fi

# ============================================================
#  نصب فونت فارسی (Vazirmatn)
# ============================================================
info "بررسی فونت فارسی..."

if [ ! -f "fonts/Vazirmatn-Bold.ttf" ]; then
    info "دانلود فونت Vazirmatn..."
    curl -fL -o fonts/Vazirmatn-Bold.ttf \
        "https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/Vazirmatn-Bold.ttf" 2>/dev/null || \
    wget -q -O fonts/Vazirmatn-Bold.ttf \
        "https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/Vazirmatn-Bold.ttf" 2>/dev/null || true
fi

if [ -f "fonts/Vazirmatn-Bold.ttf" ]; then
    ok "فونت Vazirmatn نصب است."
else
    warn "فونت Vazirmatn دانلود نشد (واترمارک فارسی ممکن است درست نمایش داده نشود)."
fi

# ============================================================
#  ساخت فایل .env
# ============================================================
info "ساخت فایل .env با مقادیر از پیش تنظیم‌شده..."

cat > .env <<EOF
# ============================================================
#  تنظیمات اصلی ربات
# ============================================================
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
TARGET_CHAT_ID=${DEFAULT_DEST_ID}

# ============================================================
#  تنظیمات دیتابیس و زمان
# ============================================================
DB_PATH=data/bot.sqlite
TIMEZONE=${TZ_VALUE}

# ============================================================
#  تنظیمات همزمانی و کش
# ============================================================
MAX_CONCURRENT_HEAVY_JOBS=3
DOWNLOAD_CACHE_MAX_ITEMS=200
DOWNLOAD_CACHE_TTL_SECONDS=1800

# ============================================================
#  API Keys هوش مصنوعی (Mistral و Groq)
# ============================================================
MISTRAL_API_KEY=${MISTRAL_API_KEY}
GROQ_API_KEY=${GROQ_API_KEY}

# ============================================================
#  پروکسیِ Gemini (اگه سرور مستقیم به گوگل دسترسی نداشته باشه)
#  این مقدار به‌صورت خودکار توسطِ install.sh و تونلِ Cloudflare WARP
#  (حالتِ پروکسی، پورتِ محلیِ ${WARP_PROXY_PORT}) تنظیم شده. اگه خالیه
#  یعنی پروکسی نساخته شده/کار نکرده و ربات مستقیم به Gemini وصل می‌شه.
# ============================================================
GEMINI_PROXY_URL=${GEMINI_PROXY_URL_VALUE}

# ============================================================
#  تنظیمات تشخیص واترمارک
# ============================================================
TEMPLATE_MATCH_THRESHOLD=0.75
MAX_WATERMARK_AREA_RATIO=0.3
EOF

ok "فایل .env ساخته شد."

# ============================================================
#  آماده‌سازی دیتابیس (کانال مقصد پیش‌فرض + کانال‌های مبدأ)
# ============================================================
info "آماده‌سازی دیتابیس..."

# بررسی وجود cli.py
if [ ! -f "cli.py" ]; then
    warn "فایل cli.py پیدا نشد، دیتابیس به‌صورت دستی تنظیم نمی‌شود."
else
    # افزودن کانال مقصد پیش‌فرض (فقط اگه کاربر واقعاً آیدی داده باشه؛ وگرنه
    # یک مقصدِ با آیدیِ خالی توی دیتابیس ساخته می‌شد که بعداً باید دستی پاک شه)
    if [[ -n "${DEFAULT_DEST_ID// }" ]]; then
        python3 cli.py add-destination "${DEFAULT_DEST_ID}" "مقصد پیش‌فرض" 2>/dev/null || true
        ok "کانال مقصد پیش‌فرض (${DEFAULT_DEST_ID}) اضافه شد."
    else
        info "کانال مقصدِ پیش‌فرض وارد نشد؛ از داخلِ خودِ ربات اضافه‌اش کن."
    fi

    # افزودن کانال‌های مبدأ (${...[@]+"${...[@]}"} یعنی روی آرایه‌ی خالی، زیرِ
    # set -u، اصلاً بسط داده نشه)
    for CH in ${DEFAULT_SOURCE_CHANNELS[@]+"${DEFAULT_SOURCE_CHANNELS[@]}"}; do
        info "  افزودن کانال مبدأ @${CH}..."
        python3 cli.py add-source "${CH}" "" --instant "--link=${DEFAULT_DEST_ID}" 2>/dev/null || true
    done

    ok "${#DEFAULT_SOURCE_CHANNELS[@]} کانال مبدأ اولیه اضافه شدند."

    # افزودن کاربران پیش‌فرض (هرکدام با کانال تایید و آیدی تلگرام اختصاصی خودشان)
    for U in ${DEFAULT_USERS[@]+"${DEFAULT_USERS[@]}"}; do
        U_NAME="${U%%|*}"
        U_REST="${U#*|}"
        U_APPROVAL="${U_REST%%|*}"
        U_TID="${U_REST##*|}"
        info "  افزودن کاربر ${U_NAME} (کانال تایید: ${U_APPROVAL}, تلگرام: ${U_TID:-ندارد})..."
        python3 cli.py add-user "${U_NAME}" "${U_APPROVAL}" "${U_TID}" 2>/dev/null || true
    done
    ok "${#DEFAULT_USERS[@]} کاربر پیش‌فرض اضافه شدند."
fi


# ============================================================
#  نصب سرویس systemd
# ============================================================
if command -v systemctl >/dev/null 2>&1; then
    info "نصب سرویس systemd..."

    SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

    cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=MR LiQ Telegram Repost Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/venv/bin/python3 ${SCRIPT_DIR}/main.py
Restart=on-failure
RestartSec=10
# شات‌داونِ نرمالِ برنامه (Application.stop + scheduler shutdown) معمولاً زیرِ
# ۵ ثانیه طول می‌کشه؛ ۲۰ ثانیه فضای کافی می‌ذاره ولی اگه به هر دلیلی (نه فقط
# باگِ تردهای torch که جداگانه فیکس شده) چیزی گیر کنه، دیگه سرویس ۹۰ثانیه‌ی
# پیش‌فرضِ systemd رو آفلاین نمی‌مونه.
TimeoutStopSec=20
KillSignal=SIGTERM
User=${SUDO_USER:-root}
Group=${SUDO_USER:-root}
Environment=PYTHONUNBUFFERED=1
# محدودسازیِ تعدادِ تردهای داخلیِ torch/numpy/OpenBLAS در سطحِ سرویس هم (علاوه
# بر envِ خودِ main.py) - جلوگیری از استخرِ تردِ بزرگی که موقعِ SIGTERM ممکنه
# تمیز بسته نشه و systemd رو مجبور به SIGKILLِ اجباری کنه.
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
EnvironmentFile=${SCRIPT_DIR}/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

    # بارگذاری مجدد systemd
    systemctl daemon-reload

    # فعال‌سازی سرویس (روشن شدن خودکار در boot)
    systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true

    # راه‌اندازی سرویس
    systemctl restart "${SERVICE_NAME}"

    sleep 3

    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        ok "ربات با موفقیت به‌عنوان سرویس '${SERVICE_NAME}' اجرا شد."
        ok "سرویس با ری‌بوت سرور خودکار روشن می‌شود."
    else
        err "سرویس بالا نیامد. خطاها را با دستور زیر ببین:"
        echo "   journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
        echo ""
        warn "می‌توانید ربات را به‌صورت دستی اجرا کنید:"
        echo "   cd ${SCRIPT_DIR} && source venv/bin/activate && python3 main.py"
    fi
else
    warn "systemctl پیدا نشد (احتمالاً محیط کانتینر یا سیستم بدون systemd)."
    warn "ربات را به‌صورت دستی با دستور زیر اجرا کنید:"
    echo "   cd ${SCRIPT_DIR} && source venv/bin/activate && python3 main.py"
fi

# ============================================================
#  ساخت پنل مدیریت (دستور سراسری)
# ============================================================
info "ساخت پنل مدیریت سرور (دستور: ${PANEL_CMD})..."

PANEL_PATH="/usr/local/bin/${PANEL_CMD}"

cat > "$PANEL_PATH" << 'PANELEOF'
#!/usr/bin/env bash
SERVICE_NAME="mrliq-bot"
PANEL_CMD="mrliq"

# ---------------------------------------------------------------------------
# Read the install directory straight from the systemd unit instead of a
# hardcoded path, so this file works no matter where it's dropped or where
# the bot actually lives.
# ---------------------------------------------------------------------------
INSTALL_DIR="$(systemctl show -p WorkingDirectory --value "$SERVICE_NAME" 2>/dev/null)"
if [[ -z "$INSTALL_DIR" ]]; then
  echo "Couldn't find the $SERVICE_NAME systemd service — is the bot installed?"
  exit 1
fi

# `-u` catches typos in variable names; we no longer rely on it to hard-crash
# mid-menu, because every read now has an explicit default. `pipefail` still
# applies so piped log filters correctly report failures.
set -uo pipefail

# Force a UTF-8 locale for this script. Without it, bash measures the
# box-drawing header art and the • / emoji by raw byte count instead of
# character count whenever the SSH client's session doesn't already hand
# over a UTF-8 locale — which silently breaks all the centering math.
# C.UTF-8 ships with glibc on virtually every Linux box, no locale-gen needed.
export LC_ALL=C.UTF-8 2>/dev/null || export LC_ALL=en_US.UTF-8 2>/dev/null || true

ENV_FILE="$INSTALL_DIR/.env"
PY="$INSTALL_DIR/venv/bin/python3"
CLI="$INSTALL_DIR/cli.py"

# ---------------------------------------------------------------
#  Colors — hacker/matrix palette
#
#  IMPORTANT: these are defined with $'...' (ANSI-C quoting) so each
#  variable holds the *real* ESC byte (0x1B), not the literal 4-character
#  text "\033". Previously they held literal text and relied on every
#  single `echo -e` call along the way to re-interpret that text back
#  into an escape code. That worked almost everywhere, but the matrix
#  intro's random character pool could occasionally draw a literal "\"
#  glyph right before a color code — echo -e would then consume that
#  stray backslash together with the *next* code's leading backslash as
#  a single literal "\" (per the `\\` escape rule), which stripped the
#  escape marker off "\033[0m" and printed it as plain readable text —
#  exactly the "033[0m" garbage seen on screen. Storing the real ESC
#  byte up front makes every code self-contained: it prints correctly
#  with plain `printf '%s'`/`echo` even with no escape re-interpretation
#  at all, so no downstream text can ever corrupt it again.
# ---------------------------------------------------------------
C_RESET=$'\033[0m'
C_BOLD=$'\033[1m'
C_DIM=$'\033[2m'
C_BLINK=$'\033[5m'  # blink attribute — degrades gracefully to a static
                     # bright color on terminals that ignore blinking
C_G=$'\033[1;32m'   # green    - safe actions / online
C_R=$'\033[1;31m'   # red      - danger / errors / offline
C_C=$'\033[1;36m'   # cyan     - borders / accents
C_Y=$'\033[1;33m'   # yellow   - warnings
C_M=$'\033[1;35m'   # magenta  - rarely used accent
C_B=$'\033[1;34m'   # blue     - section titles / matrix rain accent
C_W=$'\033[1;37m'   # white    - primary text
C_MG=$'\033[1;32m'  # matrix bright green - logo glow
C_MG2=$'\033[0;32m' # matrix mid green
C_MG3=$'\033[2;32m' # matrix dim green
C_DRIP=$'\033[1;36m'   # bright "water" cyan - fresh drop
C_DRIP2=$'\033[0;36m'  # mid water cyan
C_DRIP3=$'\033[2;34m'  # dim trailing drop / fading tail

BOX_W=60

# Skip the animated intro entirely for non-interactive shells (piped output,
# cron, CI) or if the user opts out — never let cosmetics break automation.
NO_INTRO="${MRLIQ_NO_INTRO:-0}"

need_root() {
  if [[ $EUID -ne 0 ]]; then
    echo -e "${C_R}This action requires sudo. Run: sudo ${PANEL_CMD}${C_RESET}"
    return 1
  fi
  return 0
}

pause() { read -rp $'\n\xe2\x8f\x8e  Press Enter to return to the menu...' _ || true; }

# Restart the bot only if it's running; otherwise start it.
restart_bot() {
  if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl restart "$SERVICE_NAME" 2>/dev/null && echo -e "${C_G}✔ Restarted successfully.${C_RESET}" || echo -e "${C_R}✘ Restart failed.${C_RESET}"
  else
    systemctl start "$SERVICE_NAME" 2>/dev/null && echo -e "${C_G}✔ Started (was not running).${C_RESET}" || echo -e "${C_R}✘ Start failed.${C_RESET}"
  fi
}

rule()  { echo -e "${C_C}$(printf '═%.0s' $(seq 1 "$BOX_W"))${C_RESET}"; }
srule() { echo -e "${C_C}$(printf '─%.0s' $(seq 1 "$BOX_W"))${C_RESET}"; }

center() {
  local text="$1" width="$2" len pad_l pad_r
  len=${#text}
  if (( len >= width )); then printf "%s" "$text"; return; fi
  pad_l=$(( (width - len) / 2 ))
  pad_r=$(( width - len - pad_l ))
  printf "%*s%s%*s" "$pad_l" "" "$text" "$pad_r" ""
}

# Hard terminal reset — plain `clear` relies on the terminfo entry the
# client reports, and a lot of mobile SSH apps either send no TERM or one
# that `clear` can't resolve, so it silently no-ops and every redraw just
# gets appended below the last one. \033c is the DEC "full reset" every
# terminal emulator honors; the second sequence is a normal xterm
# clear+scrollback-wipe as a belt-and-suspenders fallback.
#
# Several Android SSH/terminal apps keep their own client-side scrollback
# buffer and simply ignore \033[3J (the scrollback-clear sequence), so the
# previous menu is still there the moment the user scrolls up even though
# the visible viewport looks clean. There's no universal escape code that
# forces those apps to drop their buffer, but most keep only a fixed
# number of lines: printing enough blank lines pushes the old content
# past that limit so it's discarded rather than merely scrolled away.
clear_screen() {
  printf '\033c'
  printf '\033[H\033[2J\033[3J'
  printf '%.0s\n' {1..1000}
  printf '\033[H\033[2J'
}

# ---------------------------------------------------------------------------
#  MATRIX / HACKER INTRO — shown once when the panel launches, never again
#  during the same session (menu redraws stay instant and clean).
# ---------------------------------------------------------------------------
# True columnar matrix rain: each column tracks its own falling head
# (cursor-addressed with tput/ANSI, not a full-width reprint every
# frame) so drops actually stream top-to-bottom for `duration` seconds
# instead of flickering as random static. Pure "01" digits per the
# requested look; green dominant with a blue accent, occasional white
# spark at the head of a drop.
matrix_rain() {
  local duration="${1:-5}"
  [[ -t 1 ]] || return 0
  local cols rows
  cols=$(tput cols 2>/dev/null); cols=${cols:-70}
  rows=$(tput lines 2>/dev/null); rows=${rows:-24}
  # tput can hand back "0" (or something non-numeric) on an odd terminal;
  # guard the floor so `RANDOM % rows` below can never divide by zero.
  [[ "$cols" =~ ^[0-9]+$ ]] || cols=70
  [[ "$rows" =~ ^[0-9]+$ ]] || rows=24
  (( cols < 20 )) && cols=20
  (( rows < 10 )) && rows=10
  # No upper cap on either dimension: the rain must cover the entire
  # detected terminal, whatever its size — a small phone screen, a huge
  # desktop window, anything in between. Frame cost scales with cols
  # (rows only affects column drop-lengths), and since this only runs
  # for a few seconds at intro, even a very wide/tall terminal is cheap
  # for that short a time.

  local -a col_y col_speed col_len
  local i
  for (( i = 0; i < cols; i++ )); do
    col_y[i]=$(( -(RANDOM % rows) ))
    col_speed[i]=1
    (( RANDOM % 3 == 0 )) && col_speed[i]=2
    col_len[i]=$(( (RANDOM % 6) + 4 ))
  done

  clear_screen
  tput civis 2>/dev/null

  local start_s
  start_s=$(date +%s)
  local out y ty ey ch color now_s
  while true; do
    now_s=$(date +%s)
    (( now_s - start_s >= duration )) && break
    out=""
    for (( i = 0; i < cols; i++ )); do
      y=${col_y[i]}
      if (( y >= 0 && y < rows )); then
        ch=$(( RANDOM % 2 ))
        if (( RANDOM % 10 == 0 )); then
          color="$C_W"          # bright spark at the falling head
        elif (( RANDOM % 4 == 0 )); then
          color="$C_B"          # occasional blue accent
        else
          color="$C_MG"         # matrix green
        fi
        out+="${C_RESET}"$'\033['"$((y+1));$((i+1))H${color}${ch}"
      fi
      ty=$(( y - col_len[i] ))
      if (( ty >= 0 && ty < rows )); then
        out+="${C_RESET}"$'\033['"$((ty+1));$((i+1))H${C_MG3}$(( RANDOM % 2 ))"
      fi
      ey=$(( ty - 1 ))
      if (( ey >= 0 && ey < rows )); then
        out+=$'\033['"$((ey+1));$((i+1))H "
      fi
      col_y[i]=$(( y + col_speed[i] ))
      if (( col_y[i] - col_len[i] > rows )); then
        col_y[i]=$(( -(RANDOM % 10) ))
      fi
    done
    printf '%s%s' "$out" "$C_RESET"
    sleep 0.06
  done

  tput cnorm 2>/dev/null
  clear_screen
}

boot_sequence() {
  local lines=(
    "[ OK ] initializing secure channel..."
    "[ OK ] mounting encrypted vault..."
    "[ OK ] linking telegram bot API..."
    "[ OK ] loading MR-LiQ core modules..."
    "[DONE] handshake complete."
  )
  local l
  for l in "${lines[@]}"; do
    echo -e "  ${C_MG3}${l}${C_RESET}"
    sleep 0.12
  done
  sleep 0.15
}

intro() {
  [[ "$NO_INTRO" == "1" ]] && return 0
  [[ -t 1 ]] || return 0   # not a real terminal (piped/redirected) — skip
  matrix_rain 5            # matrix_rain clears the screen itself, start & end
  boot_sequence
  sleep 0.2
}

# Renders `width` characters for one side-margin of the logo box. Instead
# of leaving it blank, a couple of fixed columns "drip" a 0/1 digit down
# through the rows they're active on (bright at the top of the drop,
# fading through mid to dim as it falls) so the box reads as if binary
# droplets are running down beside the logo rather than just padding.
_drip_margin() {
  local width="$1" row="$2"
  local -n drips="$3"
  local i out="" j active bit
  for (( i = 0; i < width; i++ )); do
    active=-1
    for j in 0 1; do
      local dcol="${drips[$((j*3))]}" dstart="${drips[$((j*3+1))]}" dlen="${drips[$((j*3+2))]}"
      if (( i == dcol && row >= dstart && row < dstart + dlen )); then
        active=$(( row - dstart ))
      fi
    done
    if (( active >= 0 )); then
      bit=$(( RANDOM % 2 ))
      if (( active == 0 )); then out+="${C_W}${bit}${C_RESET}"
      elif (( active <= 1 )); then out+="${C_DRIP}${bit}${C_RESET}"
      elif (( active <= 2 )); then out+="${C_DRIP2}${bit}${C_RESET}"
      else out+="${C_DRIP3}${bit}${C_RESET}"
      fi
    else
      out+=" "
    fi
  done
  printf '%s' "$out"
}

# Same falling-digit look, standalone, for the couple of lines left
# hanging under the box so the drips visibly run off the bottom edge.
_drip_line() {
  local width="$1" i out=""
  for (( i = 0; i < width; i++ )); do
    if (( RANDOM % 16 == 0 )); then
      out+="${C_DRIP3}$(( RANDOM % 2 ))${C_RESET}"
    else
      out+=" "
    fi
  done
  printf '%s' "$out"
}

# Colors each non-space character of $1 from a bright palette and wraps
# it in the blink attribute — reads as a "chasing lights" credit line on
# terminals that honor blink, and simply as a lively multi-color line on
# the (many) terminals that ignore blinking, so it stays legible either way.
_rainbow_blink() {
  local text="$1" out="" i ch
  local palette=("$C_R" "$C_Y" "$C_G" "$C_C" "$C_B" "$C_M")
  local n=${#palette[@]}
  for (( i = 0; i < ${#text}; i++ )); do
    ch="${text:i:1}"
    if [[ "$ch" == " " ]]; then out+=" "
    else out+="${C_BLINK}${palette[i % n]}${ch}${C_RESET}"
    fi
  done
  printf '%s' "$out"
}

banner() {
  local logo=(
    "███╗   ███╗██████╗    ██╗     ██╗ ██████╗ "
    "████╗ ████║██╔══██╗   ██║     ██║██╔═══██╗"
    "██╔████╔██║██████╔╝   ██║     ██║██║   ██║"
    "██║╚██╔╝██║██╔══██╗   ██║     ██║██║▄▄ ██║"
    "██║ ╚═╝ ██║██║  ██║   ███████╗██║╚██████╔╝"
    "╚═╝     ╚═╝╚═╝  ╚═╝   ╚══════╝╚═╝ ╚═▀▀═╝  "
  )
  # Subtle top-to-bottom matrix gradient across the ASCII-art lines instead
  # of a single flat color, so the header actually reads as "matrix glow"
  # rather than just green text.
  local shades=("$C_W" "$C_MG" "$C_MG" "$C_MG2" "$C_MG2" "$C_MG3")
  local inner=$(( BOX_W - 2 ))
  local logo_len=42
  local pad_l=$(( (inner - logo_len) / 2 ))
  local pad_r=$(( inner - logo_len - pad_l ))
  local rows=${#logo[@]}

  # Two independent drip streaks per side: (column, start-row, length),
  # randomized fresh on every render so the box never looks static.
  local -a Ldrip=() Rdrip=()
  local j lcol rcol
  for j in 0 1; do
    lcol=$(( pad_l > 1 ? RANDOM % (pad_l - 1) + 1 : 0 ))
    rcol=$(( pad_r > 1 ? RANDOM % (pad_r - 1) + 1 : 0 ))
    Ldrip+=("$lcol" "$(( RANDOM % 3 ))" "$(( (RANDOM % 3) + 3 ))")
    Rdrip+=("$rcol" "$(( RANDOM % 3 ))" "$(( (RANDOM % 3) + 3 ))")
  done

  echo -e "${C_BOLD}"
  local i
  for i in "${!logo[@]}"; do
    printf "  %*s%s%s%s%*s\n" "$pad_l" "" "${shades[$i]:-$C_MG3}" "${logo[$i]}" "$C_RESET" "$pad_r" ""
  done
  echo -e "${C_RESET}"
  echo -e "${C_C}$(center "◤ TELEGRAM REPOST BOT — CONTROL DECK ◢" "$BOX_W")${C_RESET}"
  rule
}

header() {
  clear_screen
  banner
  local status_txt status_color status_icon uptime_txt pid_txt
  if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    status_txt="Running"; status_color="$C_G"; status_icon="🟢"
    uptime_txt="$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE_NAME" 2>/dev/null)"
    pid_txt="$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null)"
  else
    status_txt="Stopped"; status_color="$C_R"; status_icon="🔴"
    uptime_txt=""; pid_txt=""
  fi
  echo -e "   ${status_color}Status: ${status_icon} ${status_txt}${C_RESET}  |  Service: ${C_W}${SERVICE_NAME}${C_RESET}$( [[ -n "$pid_txt" && "$pid_txt" != "0" ]] && echo -e "  |  PID: ${C_W}${pid_txt}${C_RESET}")"
  if [[ -n "$uptime_txt" ]]; then
    echo -e "   ${C_DIM}Since: ${uptime_txt}${C_RESET}  ${C_R}⌁ GitHub: LiQTeam ⌁${C_RESET}"
  else
    echo -e "   ${C_R}⌁ GitHub: LiQTeam ⌁${C_RESET}"
  fi
  srule
  echo ""
}

section() { echo -e "  ${C_B}▸ $1${C_RESET}"; }

item() {
  # $1=number $2=emoji $3=label $4=color(optional)
  local num="$1" emoji="$2" label="$3" color="${4:-$C_G}"
  printf "   ${color}%2s)${C_RESET}  %s  %s\n" "$num" "$emoji" "$label"
}

# Guard used by menu options that touch root-owned files (.env, systemd,
# the sqlite DB under INSTALL_DIR). Centralizing this avoids the previous
# bug where a permission failure printed a misleading "invalid input"
# message instead of the real "needs sudo" message.
require_python_stack() {
  if [[ ! -f "$CLI" || ! -x "$PY" ]]; then
    echo -e "${C_R}cli.py or the bot's venv python3 was not found under:${C_RESET}"
    echo -e "${C_DIM}  ${INSTALL_DIR}${C_RESET}"
    return 1
  fi
  return 0
}

# Every option below reads or writes the sqlite DB, .env, or files under
# INSTALL_DIR — all owned by the deploying (root) user. Without this guard,
# running the panel as a normal user didn't fail cleanly: it let cli.py
# start, then sqlite/python threw a raw "permission denied" instead of the
# friendly sudo prompt every other write action already showed.
require_admin_python() {
  need_root || return 1
  require_python_stack || return 1
  return 0
}

show_menu() {
  header
  section "SERVICE CONTROL"
  item  1 "🟢" "Start Bot"
  item  2 "🔁" "Restart Bot"
  item  3 "🔴" "Stop Bot (temporary)"
  item  4 "📴" "Disable Completely (won't start on reboot)"
  item  5 "✅" "Re-enable & Start"
  echo
  section "LOGS & DIAGNOSTICS"
  item  6 "📊" "Full Service Status"
  item  7 "📜" "Live Log — everything (exit: Ctrl+C)"
  item  8 "🛑" "Live Log — ERRORS ONLY (exit: Ctrl+C)" "$C_R"
  echo
  section "DATA & STATISTICS"
  item  9 "📈" "Bot Statistics"
  item 10 "📡" "List Source Channels"
  item 11 "🎯" "List Destination Channels"
  item 12 "💾" "Create Instant Backup"
  echo
  section "USER & CHANNEL MANAGEMENT"
  item 13 "🔑" "Change Bot Token"
  item 14 "👤" "Add New Admin"
  item 15 "🙋" "Add New Bot User (dedicated approval channel)"
  item 16 "🎯" "Add Destination Channel"
  item 17 "📡" "Add Source Channel"
  echo
  section "CONFIGURATION"
  item 18 "🌐" "Show Current Settings (.env, secrets masked)"
  echo
  section "DANGER ZONE"
  item 19 "❌" "Delete Bot Completely (irreversible)" "$C_R"
  echo
  item  0 "🚪" "Exit" "$C_Y"
  echo
  srule
  local CH
  read -rp "$(echo -e "  ${C_W}Select an option:${C_RESET} ")" CH
  # If read failed (Ctrl+D / closed stdin) or nothing was typed, land safely
  # on a no-op option instead of an unset-variable error under `set -u`.
  CH="${CH:-}"
  [[ -z "$CH" ]] && CH="__none__"
  handle "$CH"
}

# ----------------------------------------------------------------------
# Helper: safely update a KEY=value line in .env.
#
# The previous implementation split every line on "=" with awk's FS/OFS,
# which silently corrupted any value that itself contained an "=" (for
# example a base64-ish token or a URL with query params): everything
# after the *second* "=" got dropped from the reconstructed line. This
# version matches the key with a regex and replaces the whole line as a
# single string, so the value is never re-split.
# ----------------------------------------------------------------------
update_env() {
  local key="$1" value="$2"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${C_R}.env file not found.${C_RESET}"
    return 1
  fi
  if grep -q "^${key}=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" '
      index($0, k"=") == 1 { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

handle() {
  case "$1" in
    1) if need_root; then systemctl start "$SERVICE_NAME" 2>/dev/null && echo -e "${C_G}✔ Started.${C_RESET}" || echo -e "${C_R}✘ Failed.${C_RESET}"; fi; pause ;;
    2) need_root && restart_bot; pause ;;
    3) if need_root; then systemctl stop "$SERVICE_NAME" 2>/dev/null && echo -e "${C_Y}⏹ Stopped.${C_RESET}" || echo -e "${C_R}✘ Failed.${C_RESET}"; fi; pause ;;
    4) if need_root; then systemctl disable --now "$SERVICE_NAME" 2>/dev/null && echo -e "${C_Y}📴 Disabled.${C_RESET}" || echo -e "${C_R}✘ Failed.${C_RESET}"; fi; pause ;;
    5) if need_root; then systemctl enable --now "$SERVICE_NAME" 2>/dev/null && echo -e "${C_G}✔ Enabled and started.${C_RESET}" || echo -e "${C_R}✘ Failed.${C_RESET}"; fi; pause ;;
    6) systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null || echo "Service not found."; pause ;;
    7)
      echo -e "${C_C}Streaming full live log... (exit: Ctrl+C)${C_RESET}"
      # Ignore SIGINT in THIS shell while journalctl runs in the foreground.
      # Without this trap, Ctrl+C was delivered to the whole process group
      # — including the panel script itself — and silently killed the
      # entire panel instead of just stopping the log stream. journalctl
      # still receives and honors the same Ctrl+C normally, so it stops
      # right on cue; only the parent script now survives it.
      trap '' INT
      journalctl -u "$SERVICE_NAME" -f -n 50 2>/dev/null || echo "Could not display log."
      trap - INT
      pause ;;
    8)
      echo -e "${C_R}Streaming ERRORS ONLY... (exit: Ctrl+C)${C_RESET}"
      echo -e "${C_DIM}Filtering for: error, exception, traceback, critical, failed${C_RESET}"
      srule
      trap '' INT
      # فیکس: خط‌های وسطِ traceback (مثلِ File "bot/xxx.py", line 145, in func)
      # هیچ‌کدوم از کلمه‌های کلیدی رو ندارن، پس با grep ساده حذف می‌شدن و
      # دقیقاً همون فایل/خطی که برای دیباگ لازمه گم می‌شد. با -A 15 بعد از هر
      # خطِ Match‌شده (مثلاً «Traceback (most recent call last):»)، ۱۵ خطِ
      # بعدی هم چاپ می‌شه تا کلِ traceback (با فایل/خط دقیق) کامل بمونه.
      journalctl -u "$SERVICE_NAME" -f -n 500 2>/dev/null \
        | grep --line-buffered -A 15 -iE 'error|exception|traceback|critical|failed|refused' \
        | while IFS= read -r line; do echo -e "${C_R}${line}${C_RESET}"; done
      trap - INT
      pause ;;
    9)
      if require_admin_python; then
        "$PY" "$CLI" stats
      fi
      pause ;;
    10)
      if require_admin_python; then
        read -rp "Show only active sources? [y/N]: " ONLY_ACTIVE
        ONLY_ACTIVE="${ONLY_ACTIVE:-n}"
        if [[ "${ONLY_ACTIVE,,}" == "y" ]]; then
          "$PY" "$CLI" list-sources --active
        else
          "$PY" "$CLI" list-sources
        fi
      fi
      pause ;;
    11)
      if require_admin_python; then
        read -rp "Show only active destinations? [y/N]: " ONLY_ACTIVE
        ONLY_ACTIVE="${ONLY_ACTIVE:-n}"
        if [[ "${ONLY_ACTIVE,,}" == "y" ]]; then
          "$PY" "$CLI" list-destinations --active
        else
          "$PY" "$CLI" list-destinations
        fi
      fi
      pause ;;
    12)
      if require_admin_python; then
        echo -e "${C_C}Creating an encrypted backup in the current directory...${C_RESET}"
        (cd "$INSTALL_DIR" && "$PY" "$CLI" backup --create)
      fi
      pause ;;
    13)
      read -rp "New token: " NEWTOKEN
      NEWTOKEN="${NEWTOKEN:-}"
      if [[ -z "${NEWTOKEN// }" ]]; then
        echo -e "${C_R}Token cannot be empty.${C_RESET}"
      elif need_root; then
        if update_env "BOT_TOKEN" "$NEWTOKEN"; then
          restart_bot
          echo -e "${C_G}✔ Token updated and bot restarted.${C_RESET}"
        fi
      fi
      pause ;;
    14)
      read -rp "New admin numeric ID: " NEWADMIN
      NEWADMIN="${NEWADMIN:-}"
      if [[ ! "$NEWADMIN" =~ ^-?[0-9]+$ ]]; then
        echo -e "${C_R}Invalid ID (numbers only).${C_RESET}"
      elif need_root; then
        if [[ -f "$ENV_FILE" ]]; then
          CURRENT=$(grep '^ADMIN_IDS=' "$ENV_FILE" | cut -d'=' -f2-)
          if [[ -z "$CURRENT" ]]; then
            NEW_LIST="$NEWADMIN"
          elif [[ ",${CURRENT}," == *",${NEWADMIN},"* ]]; then
            echo -e "${C_Y}This ID is already an admin.${C_RESET}"
            pause
            return
          else
            NEW_LIST="${CURRENT},${NEWADMIN}"
          fi
          update_env "ADMIN_IDS" "$NEW_LIST"
          restart_bot
          echo -e "${C_G}✔ Added and bot restarted.${C_RESET}"
        else
          echo -e "${C_R}.env file not found.${C_RESET}"
        fi
      fi
      pause ;;
    15)
      if require_admin_python; then
        read -rp "User's display name: " U_NAME
        read -rp "Approval channel/group numeric ID: " U_APPROVAL
        read -rp "User's Telegram numeric ID (optional): " U_TID
        if [[ -z "${U_NAME// }" || ! "$U_APPROVAL" =~ ^-?[0-9]+$ ]]; then
          echo -e "${C_R}Name and a numeric approval-channel ID are required.${C_RESET}"
        else
          ARGS=(add-user "$U_NAME" "$U_APPROVAL")
          [[ -n "${U_TID// }" ]] && ARGS+=("$U_TID")
          "$PY" "$CLI" "${ARGS[@]}"
        fi
      fi
      pause ;;
    16)
      if require_admin_python; then
        read -rp "Destination chat ID or @username: " DEST_ID
        read -rp "Custom name (optional): " DEST_TITLE
        if [[ -z "${DEST_ID// }" ]]; then
          echo -e "${C_R}Destination ID cannot be empty.${C_RESET}"
        else
          "$PY" "$CLI" add-destination "$DEST_ID" "$DEST_TITLE"
        fi
      fi
      pause ;;
    17)
      if require_admin_python; then
        read -rp "Source channel username (without @): " SRC_USER
        read -rp "Custom name (optional): " SRC_TITLE
        read -rp "Instant posting mode? [y/N]: " INSTANT
        read -rp "Link to a destination chat ID now? (leave blank to skip): " LINK_ID
        INSTANT="${INSTANT:-n}"
        LINK_ID="${LINK_ID:-}"
        if [[ -z "${SRC_USER// }" ]]; then
          echo -e "${C_R}Source username cannot be empty.${C_RESET}"
        else
          ARGS=(add-source "$SRC_USER" "$SRC_TITLE")
          [[ "${INSTANT,,}" == "y" ]] && ARGS+=(--instant)
          [[ -n "${LINK_ID// }" ]] && ARGS+=(--link "$LINK_ID")
          "$PY" "$CLI" "${ARGS[@]}"
        fi
      fi
      pause ;;
    18)
      echo
      if [[ ! -f "$ENV_FILE" ]]; then
        echo -e "${C_R}.env file not found.${C_RESET}"
      elif need_root; then
        # Mask anything that looks like a token/secret so it isn't left in
        # plaintext on screen or in terminal scrollback/screen-recordings.
        awk -F= '
          /^(BOT_TOKEN|.*(SECRET|KEY|PASSWORD).*)=/ {
            v=$2
            if (length(v) > 8) print $1 "=" substr(v,1,4) "••••••••" substr(v,length(v)-3,4)
            else print $1 "=••••••••"
            next
          }
          { print }
        ' "$ENV_FILE"
      fi
      pause ;;
    19)
      echo -e "${C_R}⚠️  This will permanently delete the service, files, and database.${C_RESET}"
      read -rp "Type DELETE to confirm: " CONFIRM
      CONFIRM="${CONFIRM:-}"
      if [[ "$CONFIRM" != "DELETE" ]]; then
        echo -e "${C_Y}Cancelled.${C_RESET}"
      elif need_root; then
        systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        systemctl daemon-reload 2>/dev/null || true
        rm -f "/usr/local/bin/${PANEL_CMD}"
        rm -rf "$INSTALL_DIR"
        echo -e "${C_G}✔ Bot completely removed from the server.${C_RESET}"
        exit 0
      fi
      pause ;;
    0|__none__) clear_screen; exit 0 ;;
    *) echo -e "${C_R}Invalid option.${C_RESET}"; pause ;;
  esac
}

# A plain top-level SIGINT (e.g. Ctrl+C sitting at the main "Select an
# option" prompt) now exits cleanly with a message instead of dumping a
# raw shell prompt or a stray "^C".
trap 'clear_screen; echo -e "\n${C_Y}Goodbye.${C_RESET}"; exit 0' INT

intro
while true; do show_menu; done
PANELEOF

chmod +x "$PANEL_PATH"

if [ -f "$PANEL_PATH" ]; then
    ok "پنل مدیریت ساخته شد (دستور: sudo ${PANEL_CMD})"
else
    warn "ساخت پنل مدیریت ناموفق بود."
fi

# ============================================================
#  تنظیم مجوزهای فایل‌ها
# ============================================================
info "تنظیم مجوزهای فایل‌ها..."

chown -R ${SUDO_USER:-root}:${SUDO_USER:-root} . 2>/dev/null || true
chmod -R 755 . 2>/dev/null || true
chmod +x main.py cli.py 2>/dev/null || true

# فیکسِ R10 (امنیت): chmod -R 755 بالا فایلِ .env (شاملِ BOT_TOKEN و کلیدهای API)
# و دیتابیس رو world-readable می‌کرد (هر کاربرِ دیگه روی همون سرور می‌تونست
# بخوندشون). این‌ها به 600 محدود می‌شن تا فقط صاحبِ سرویس دسترسی داشته باشه.
chmod 600 .env 2>/dev/null || true
[ -f data/bot.sqlite ] && chmod 600 data/bot.sqlite 2>/dev/null || true
# پوشه‌ی بکاپ‌ها (شاملِ کلِ دیتابیسِ رمزنگاری‌شده) هم فقط برای صاحبِ سرویس
[ -d data/backups ] && chmod -R 700 data/backups 2>/dev/null || true

ok "مجوزهای فایل‌ها تنظیم شد."

# ============================================================
#  پیام نهایی
# ============================================================
echo
echo -e "${C_CYAN}═════════════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_GREEN}✅  نصب کاملاً با موفقیت انجام شد!${C_RESET}"
echo -e "${C_CYAN}═════════════════════════════════════════════════════════════${C_RESET}"
echo ""
echo -e "📌 ${C_MAG}دستور مدیریت ربات:${C_RESET}"
echo "    sudo ${PANEL_CMD}"
echo ""
echo -e "📌 ${C_MAG}دستورات مفید:${C_RESET}"
echo "    وضعیت سرویس:      systemctl status ${SERVICE_NAME}"
echo "    لاگ زنده:         journalctl -u ${SERVICE_NAME} -f"
echo "    ری‌استارت:        systemctl restart ${SERVICE_NAME}"
echo "    توقف:             systemctl stop ${SERVICE_NAME}"
echo "    روشن‌کردن:        systemctl start ${SERVICE_NAME}"
echo ""
echo -e "📌 ${C_MAG}مسیرهای مهم:${C_RESET}"
echo "    دیتابیس:          ${SCRIPT_DIR}/data/bot.sqlite"
echo "    فایل تنظیمات:     ${SCRIPT_DIR}/.env"
echo "    لاگ ربات:         ${SCRIPT_DIR}/logs/bot.log"
echo "    مدل‌های AI:       ${SCRIPT_DIR}/models/"
echo ""
echo -e "${C_CYAN}═════════════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_GREEN}🤖  حالا برو توی تلگرام و به ربات /start بزن.${C_RESET}"
echo -e "${C_CYAN}═════════════════════════════════════════════════════════════${C_RESET}"
echo ""

# ============================================================
#  بررسی نهایی سرویس
# ============================================================
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        ok "سرویس ${SERVICE_NAME} در حال اجرا است."
    else
        warn "سرویس ${SERVICE_NAME} در حال اجرا نیست."
        info "برای اجرا: sudo systemctl start ${SERVICE_NAME}"
    fi
fi

ok "نصب کامل شد. موفق باشی 🚀"
exit 0