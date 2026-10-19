import asyncio
import csv
import io
import logging
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from flask import Flask
from PIL import Image
import easyocr
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, ChatJoinRequestHandler,
    CommandHandler, ContextTypes, MessageHandler, filters,
)

# ============================================================
# CONFIGURATION
# ============================================================
CAMBODIA_TZ = ZoneInfo("Asia/Phnom_Penh")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8980369344"))
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1004400009713"))

# ⚙️ ព័ត៌មានគណនី ABA របស់អ្នក (សម្រាប់ប្រព័ន្ធ OCR ផ្ទៀងផ្ទាត់)
MERCHANT_NAME = "ROZA YIN"
MERCHANT_USD_ACCOUNT = "019 090 094"
MERCHANT_KHR_ACCOUNT = "500 769 213"

PACKAGES = {
    5: {"price": "2.00", "label": "🛒 ទិញសេវាកម្ម: 5 ថ្ងៃ", "numeric_price": 2.0},
    10: {"price": "3.00", "label": "🛒 ទិញសេវាកម្ម: 10 ថ្ងៃ", "numeric_price": 3.0},
    20: {"price": "5.00", "label": "🛒 ទិញសេវាកម្ម: 20 ថ្ងៃ", "numeric_price": 5.0},
    30: {"price": "6.00", "label": "🛒 ទិញសេវាកម្ម: 30 ថ្ងៃ", "numeric_price": 6.0},
}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("subscription_bot")
DATABASE_URL = os.getenv("DATABASE_URL")

# Initialize EasyOCR Reader (ພາសាអង់គ្លេស)
ocr_reader = easyocr.Reader(['en'], gpu=False)

user_selected_package = {}
user_last_photo_time = {}

# --------------------------- Flask ---------------------------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with OCR Protection is running!"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app_web.run(host="0.0.0.0", port=port, use_reloader=False)

threading.Thread(target=run_web, daemon=True).start()


# ------------------------- Utilities -------------------------
def now_dt():
    return datetime.now(CAMBODIA_TZ)

def get_now():
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")

def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=CAMBODIA_TZ) if value.tzinfo is None else value.astimezone(CAMBODIA_TZ)
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CAMBODIA_TZ)

def fmt_dt(value):
    return value.astimezone(CAMBODIA_TZ).strftime("%Y-%m-%d %H:%M:%S")

def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
    except Exception:
        return None

def db_execute(sql, params=(), fetchone=False, fetchall=False):
    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("Database is unavailable")
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
                return None
    finally:
        conn.close()

def is_admin(user_id):
    return user_id == ADMIN_ID

def target_message(update):
    if update.callback_query:
        return update.callback_query.message
    return update.effective_message

def package_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 ថ្ងៃ - 2.00$", callback_data="pkg_5")],
        [InlineKeyboardButton("10 ថ្ងៃ - 3.00$", callback_data="pkg_10")],
        [InlineKeyboardButton("20 ថ្ងៃ - 5.00$", callback_data="pkg_20")],
        [InlineKeyboardButton("30 ថ្ងៃ - 6.00$", callback_data="pkg_30")],
        [InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")],
    ])

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 គណនីរបស់ខ្ញុំ", callback_data="user_check_status"),
         InlineKeyboardButton("💎 ទិញសេវាកម្ម", callback_data="user_packages")],
        [InlineKeyboardButton("💬 Admin Support", url="https://t.me/Alex_Pree"),
         InlineKeyboardButton("☑️ អំពីពួកយើង", callback_data="user_about")],
        [InlineKeyboardButton("🌐 របៀបបង់ប្រាក់", callback_data="user_payment_help")],
    ])

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        expiry_date TEXT,
                        kicked INTEGER DEFAULT 0,
                        warned INTEGER DEFAULT 0,
                        package_info TEXT DEFAULT 'មិនមាន',
                        referral_code TEXT,
                        referred_by BIGINT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS used_receipts (
                        photo_file_id TEXT PRIMARY KEY,
                        user_id BIGINT,
                        used_at TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payment_requests (
                        id BIGSERIAL PRIMARY KEY,
                        photo_unique_id TEXT UNIQUE NOT NULL,
                        telegram_file_id TEXT NOT NULL,
                        user_id BIGINT NOT NULL,
                        package_days INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL,
                        reviewed_at TEXT,
                        reviewed_by BIGINT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS invite_links (
                        invite_link TEXT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        photo_unique_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active'
                    )
                """)
    finally:
        conn.close()

init_db()


# --------------------------- /start --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    username = user.username or user.first_name or "User"
    
    conn = get_db_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
                    if not cur.fetchone():
                        expired_default = fmt_dt(now_dt() - timedelta(days=1))
                        cur.execute("""
                            INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info, referral_code)
                            VALUES (%s, %s, %s, 0, 0, %s, %s)
                        """, (user_id, username, expired_default, "មិនទាន់ជ្រើសរើសកញ្ចប់", f"ref_{user_id}"))
        finally:
            conn.close()

    await update.effective_message.reply_text(
        f"សួស្តី {user.first_name or 'មិត្ត'}!\n\n"
        "សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសេវាកម្មរបស់យើង។\n"
        "សូមជ្រើសរើសម៉ឺនុយខាងក្រោម៖",
        reply_markup=main_keyboard(),
    )


# ----------------------- User callbacks ----------------------
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "user_packages":
        await query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់សេវាកម្ម៖", reply_markup=package_keyboard())
        return
    if data == "user_check_status":
        await status(update, context)
        return
    if data == "user_payment_help":
        await query.message.reply_text(
            "💳 របៀបបង់ប្រាក់៖\n\n"
            "1. ជ្រើសរើសកញ្ចប់សេវាកម្មដែលអ្នកចង់ទិញ។\n"
            "2. ស្កេន QR Code តាមតម្លៃកញ្ចប់នីមួយៗ។\n"
            "3. ផ្ញើរូបវិក្កយបត្រ (Receipt) មកកាន់ Bot នេះផ្ទាល់។\n"
            "4. ប្រព័ន្ធនឹងពិនិត្យស្វ័យប្រវត្ត និងរង់ចាំ Approve។",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")]]),
        )
        return
    if data == "user_about":
        await query.message.reply_text("☑️ អំពីពួកយើង៖ សេវាកម្មរហ័ស និងមានសុវត្ថិភាព។", reply_markup=main_keyboard())
        return
    if data == "user_main_menu":
        await query.message.reply_text("សូមជ្រើសរើសម៉ឺនុយ៖", reply_markup=main_keyboard())
        return
    if data.startswith("pkg_"):
        try:
            days = int(data.split("_", 1)[1])
        except ValueError:
            return
        if days not in PACKAGES:
            return
        user_selected_package[user_id] = days
        caption = (
            "🧾 Payment\n\n"
            f"{PACKAGES[days]['label']}\n"
            f"💵 តម្លៃ: ${PACKAGES[days]['price']} ដុល្លារ\n\n"
            "សូមស្កែន QR រួចផ្ញើប័ណ្ណមក Bot\n"
            f"លេខសំណើ៖ #{user_id}"
        )
        try:
            qr_row = db_execute("SELECT value FROM bot_settings WHERE key = 'custom_qr_file_id'", fetchone=True)
            qr_id = qr_row[0] if qr_row else None
            if qr_id:
                await query.message.reply_photo(photo=qr_id, caption=caption)
            else:
                with open("qr.jpg", "rb") as qr_file:
                    await query.message.reply_photo(photo=qr_file, caption=caption)
        except Exception:
            await query.message.reply_text(caption + "\n\n⚠️ មិនអាចបង្ហាញ QR Code បានទេ។")


# ------------------------- Receipt flow (WITH OCR AUTO-VALIDATION) ----------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    user_id = user.id
    if user_id not in user_selected_package:
        await update.message.reply_text("⚠️ សូមជ្រើសរើសកញ្ចប់សេវាកម្មជាមុនសិន។", reply_markup=package_keyboard())
        return

    photo = update.message.photo[-1]
    file_id, unique_id = photo.file_id, photo.file_unique_id
    days = user_selected_package[user_id]
    required_price = str(PACKAGES[days]["price"])
    username = user.username or user.first_name or "User"

    # 📥 ទាញយករូបភាពមកធ្វើ OCR Scan
    await update.message.reply_text("🔄 កំពុងពិនិត្យ និងស្កែនវិក្កយបត្ររបស់អ្នកដោយស្វ័យប្រវត្តិ...")
    try:
        photo_file = await photo.get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # ប្រើ EasyOCR អានអក្សរក្នុងរូបភាព
        ocr_results = ocr_reader.readtext(bytes(photo_bytes), detail=0)
        scanned_text = " ".join(ocr_results).upper()
        logger.info(f"OCR Scanned Text for user {user_id}: {scanned_text}")
    except Exception:
        logger.exception("OCR processing failed")
        await update.message.reply_text("❌ មានបញ្ហាក្នុងការអានរូបភាពវិក្កយបត្ររបស់អ្នក។ សូមព្យាយាមផ្ញើរូបភាពច្បាស់ជាងមុន។")
        return

    # 🔍 ផ្ទៀងផ្ទាត់សុវត្ថិភាពស្វ័យប្រវត្ត (Auto-Validation)
    # ១. ពិនិត្យឈ្មោះ និងលេខគណនី
    name_matched = MERCHANT_NAME.upper() in scanned_text
    acc_matched = (MERCHANT_USD_ACCOUNT in scanned_text) or (MERCHANT_KHR_ACCOUNT in scanned_text)

    # ២. ពិនិត្យទឹកប្រាក់ (ត្រូវមានតម្លៃស្មើនឹងកញ្ចប់ដែលបានជ្រើសរើស)
    price_matched = required_price in scanned_text

    # ប្រសិនបើឈ្មោះ ឬលេខគណនី ឬទឹកប្រាក់មិនត្រូវ ❌ បដិសេធភ្លាមៗ (Auto Reject)
    if not (name_matched or acc_matched) or not price_matched:
        await update.message.reply_text(
            "❌ **បដិសេធស្វ័យប្រវត្តិ (Auto-Reject)!**\n\n"
            "ហេតុផលដែលអាចកើតមាន៖\n"
            "• ឈ្មោះអ្នកទទួល ឬលេខគណនីក្នុងវិក្កយបត្រ **មិនមែនជាគណនីរបស់យើងទេ** (អាចជា ACLEDA ឬអ្នកដទៃ)។\n"
            "• ចំនួនទឹកប្រាក់មិនត្រូវនឹងតម្លៃកញ្ចប់សេវាកម្ម ($" + required_price + ")។\n\n"
            "សូមពិនិត្យមើលឡើងវិញ រួចផ្ញើវិក្កយបត្រដែលត្រឹមត្រូវ។"
        )
        return

    # ប្រសិនបើត្រឹមត្រូវ រក្សាទុកក្នុង Database និងផ្ញើទៅ Admin
    conn = get_db_connection()
    if conn is None:
        await update.message.reply_text("❌ Database មានបញ្ហា។")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM payment_requests WHERE photo_unique_id = %s", (unique_id,))
                if cur.fetchone():
                    await update.message.reply_text("❌ រូបវិក្កយបត្រនេះត្រូវបានប្រើប្រាស់រួចហើយ។")
                    return
                cur.execute("""
                    INSERT INTO payment_requests
                    (photo_unique_id, telegram_file_id, user_id, package_days, status, created_at)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                """, (unique_id, file_id, user_id, days, get_now()))
    except Exception:
        await update.message.reply_text("❌ មិនអាចរក្សាទុកទិន្នន័យបានទេ។")
        return
    finally:
        conn.close()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{days}_{unique_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{unique_id}"),
        ]
    ])
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=file_id,
            caption=(
                "✅ **ឆ្លងកាត់ OCR Auto-Check ជោគជ័យ!**\n\n"
                f"👤 ឈ្មោះ Telegram៖ {username}\n"
                f"🆔 User ID៖ `{user_id}`\n"
                f"📦 កញ្ចប់៖ {days} ថ្ងៃ (${required_price})\n"
                f"🧾 Unique ID៖ `{unique_id}`"
            ),
            reply_markup=keyboard,
        )
        await update.message.reply_text("✅ វិក្កយបត្រត្រឹមត្រូវតាមប្រព័ន្ធ! សូមរង់ចាំ Admin អនុម័តបន្តិច។")
    except TelegramError:
        await update.message.reply_text("❌ មិនអាចបញ្ជូនទៅ Admin បានទេ។")


# --------------------- Admin actions & other functions -----------------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ អ្នកមិនមានសិទ្ធិទេ។", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data.startswith("approve_"):
        parts = data.split("_", 3)
        user_id, days, unique_id = int(parts[1]), int(parts[2]), parts[3]
        expiry_date = fmt_dt(now_dt() + timedelta(days=days))
        
        try:
            db_execute("""
                INSERT INTO users (user_id, expiry_date, package_info)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET expiry_date = %s, package_info = %s, kicked = 0
            """, (user_id, expiry_date, f"{days} ថ្ងៃ", expiry_date, f"{days} ថ្ងៃ"))
            db_execute("INSERT INTO used_receipts (photo_file_id, user_id, used_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (unique_id, user_id, get_now()))
            db_execute("UPDATE payment_requests SET status = 'approved' WHERE photo_unique_id = %s", (unique_id,))
            
            await context.bot.send_message(user_id, f"✅ Payment ត្រូវបាន Approve រួចរាល់! សេវាកម្មរបស់អ្នកមានសុពលភាពដល់៖ {expiry_date[:10]}")
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n✅ បាន Approve ជោគជ័យ។")
        except Exception:
            await query.message.reply_text("❌ Approve បរាជ័យ។")

    elif data.startswith("reject_"):
        parts = data.split("_", 2)
        user_id, unique_id = int(parts[1]), parts[2]
        db_execute("UPDATE payment_requests SET status = 'rejected' WHERE photo_unique_id = %s", (unique_id,))
        try:
            await context.bot.send_message(user_id, "❌ វិក្កយបត្ររបស់អ្នកត្រូវបានបដិសេធដោយ Admin។")
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n❌ បាន Reject។")
        except Exception:
            pass


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    row = db_execute("SELECT expiry_date, kicked FROM users WHERE user_id = %s", (user.id,), fetchone=True)
    if not row:
        await target_message(update).reply_text("អ្នកមិនទាន់មានទិន្នន័យសេវាកម្មទេ។ សូមប្រើ /start។")
        return
    expiry = parse_dt(row[0])
    msg = f"👤 គណនីរបស់អ្នក (ID: `{user.id}`)\n"
    if expiry and expiry > now_dt() and not row[1]:
        msg += f"📅 ផុតកំណត់៖ {fmt_dt(expiry)[:10]}\n✨ សកម្មភាពធម្មតា។"
    else:
        msg += "🔴 សេវាកម្មបានផុតកំណត់។"
    await target_message(update).reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 ទិញសេវាកម្មបន្ថែម", callback_data="user_packages")]]))


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set")
    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(approve_|reject_)"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern=r"^(pkg_|user_)"))

    application.run_polling()

if __name__ == "__main__":
    main()
