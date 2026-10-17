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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, ChatJoinRequestHandler,
    CommandHandler, ContextTypes, MessageHandler, filters,
)

# ============================================================
# CONFIGURATION
# Set BOT_TOKEN, DATABASE_URL, ADMIN_ID and GROUP_CHAT_ID
# in Render Environment Variables. Never publish your bot token.
# ============================================================
CAMBODIA_TZ = ZoneInfo("Asia/Phnom_Penh")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8980369344"))
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1004400009713"))

PACKAGES = {
    5: {"price": "២ ដុល្លារ", "label": "៥ ថ្ងៃ - ២ ដុល្លារ"},
    10: {"price": "៣ ដុល្លារ", "label": "១០ ថ្ងៃ - ៣ ដុល្លារ"},
    20: {"price": "៥ ដុល្លារ", "label": "២០ ថ្ងៃ - ៥ ដុល្លារ"},
    30: {"price": "៦ ដុល្លារ", "label": "៣០ ថ្ងៃ - ៦ ដុល្លារ"},
}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("subscription_bot")
DATABASE_URL = os.getenv("DATABASE_URL")

# Lightweight throttling / package selection. These reset on restart.
user_selected_package = {}
user_last_photo_time = {}

# --------------------------- Flask ---------------------------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with PostgreSQL is running!"

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
        logger.error("DATABASE_URL environment variable is missing")
        return None
    try:
        return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
    except Exception:
        logger.exception("Database connection failed")
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
        [InlineKeyboardButton(PACKAGES[5]["label"], callback_data="pkg_5")],
        [InlineKeyboardButton(PACKAGES[10]["label"], callback_data="pkg_10")],
        [InlineKeyboardButton(PACKAGES[20]["label"], callback_data="pkg_20")],
        [InlineKeyboardButton(PACKAGES[30]["label"], callback_data="pkg_30")],
        [InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")],
    ])

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 ជ្រើសរើសកញ្ចប់សមាជិកភាព", callback_data="user_packages")],
        [InlineKeyboardButton("📊 ពិនិត្យស្ថានភាពសមាជិកភាព", callback_data="user_check_status")],
        [InlineKeyboardButton("👥 Link ណែនាំមិត្តភក្តិ (ថែម ១ ម៉ោង)", callback_data="get_referral_link")],
        [InlineKeyboardButton("❓ របៀបទូទាត់ប្រាក់", callback_data="user_payment_help")],
    ])

def init_db():
    conn = get_db_connection()
    if conn is None:
        logger.error("Skipping database initialization; no database connection")
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
        http://logger.info("Database initialized")
    except Exception:
        logger.exception("Database initialization failed")
    finally:
        conn.close()

init_db()

# --------------------------- /start --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = http://user.id
    username = user.username or user.first_name or "User"
    referrer_id = None

    if context.args and context.args[0].startswith("ref_"):
        try:
            candidate = int(context.args[0][4:])
            if candidate != user_id:
                referrer_id = candidate
        except ValueError:
            pass

    conn = get_db_connection()
    if conn:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
                    exists = cur.fetchone()
                    if not exists:
                        expired_default = fmt_dt(now_dt() - timedelta(days=1))
                        if referrer_id:
                            cur.execute(
                                "SELECT expiry_date FROM users WHERE user_id = %s FOR UPDATE",
                                (referrer_id,),
                            )
                            ref = cur.fetchone()
                            if ref:
                                ref_exp = parse_dt(ref[0])
                                base = ref_exp if ref_exp and ref_exp > now_dt() else now_dt()
                                cur.execute(
                                    "UPDATE users SET expiry_date = %s, warned = 0 WHERE user_id = %s",
                                    (fmt_dt(base + timedelta(hours=1)), referrer_id),
                                )
                                # Notify after DB transaction is committed below.
                                context.application.create_task(notify_referrer(context, referrer_id))
                        cur.execute("""
                            INSERT INTO users
                            (user_id, username, expiry_date, kicked, warned, package_info,
                             referral_code, referred_by)
                            VALUES (%s, %s, %s, 0, 0, %s, %s, %s)
                        """, (
                            user_id, username, expired_default,
                            "មិនទាន់ជ្រើសរើសកញ្ចប់", f"ref_{user_id}", referrer_id
                        ))
                    else:
                        cur.execute("UPDATE users SET username = %s WHERE user_id = %s",
                                    (username, user_id))
        except Exception:
            logger.exception("Could not update user on /start")
        finally:
            conn.close()

    await update.effective_message.reply_text(
        f"សួស្តី {user.first_name or 'មិត្ត'}!\n\n"
        "សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសមាជិកភាពគ្រុប។\n"
        "សូមជ្រើសរើសមុខងារខាងក្រោម៖",
        reply_markup=main_keyboard(),
    )

async def notify_referrer(context, referrer_id):
    try:
        await context.bot.send_message(
            chat_id=referrer_id,
            text="🎁 មិត្តភក្តិថ្មីបានចូលតាម Link របស់អ្នក! អ្នកទទួលបានបន្ថែម ១ ម៉ោង។",
        )
    except TelegramError:
        http://logger.info("Could not notify referrer %s", referrer_id)

# ----------------------- User callbacks ----------------------
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = http://query.from_user.id

    if data == "user_packages":
        await query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់សមាជិកភាព៖", reply_markup=package_keyboard())
        return
    if data == "user_check_status":
        await status(update, context)
        return
    if data == "user_payment_help":
        await query.message.reply_text(
            "💳 របៀបទូទាត់ប្រាក់៖\n\n"
            "1. ជ្រើសរើសកញ្ចប់សមាជិកភាព។\n"
            "2. ស្កេន QR Code ដើម្បីបង់ប្រាក់។\n"
            "3. ផ្ញើរូបវិក្កយបត្រមក Bot នេះ។\n"
            "4. រង់ចាំ Admin ពិនិត្យ និងអនុម័ត។",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")
            ]]),
        )
        return
    if data == "user_main_menu":
        await query.message.reply_text("សូមជ្រើសរើសមុខងារ៖", reply_markup=main_keyboard())
        return
    if data == "get_referral_link":
        bot = await context.bot.get_me()
        link = f"https://t.me/%7Bbot.username%7D?start=ref_%7Buser_id%7D"
        await query.message.reply_text(
            f"🔗 Link ណែនាំមិត្តភក្តិ៖\n{link}\n\n"
            "មិត្តភក្តិថ្មីដែលចូលប្រើ Bot ជាលើកដំបូងតាម Link នេះ នឹងផ្តល់រង្វាន់ ១ ម៉ោង។"
        )
        return
    if data.startswith("pkg_"):
        try:
            days = int(data.split("_", 1)[1])
        except ValueError:
            return
        if days not in PACKAGES:
            await query.message.reply_text("❌ កញ្ចប់នេះមិនត្រឹមត្រូវទេ។")
            return
        user_selected_package[user_id] = days
        qr_id = None
        try:
            qr_row = db_execute("SELECT value FROM bot_settings WHERE key = 'custom_qr_file_id'", fetchone=True)
            if qr_row:
                qr_id = qr_row[0]
        except Exception:
            logger.exception("Could not load custom QR")
        caption = (
            f"📦 កញ្ចប់៖ {days} ថ្ងៃ ({PACKAGES[days]['price']})\n\n"
            "💳 សូមស្កេន QR Code ដើម្បីទូទាត់ប្រាក់។\n"
            "📸 បន្ទាប់ពីបង់ប្រាក់ សូមផ្ញើរូបវិក្កយបត្រមក Bot នេះ។\n"
            "Admin នឹងពិនិត្យមុនពេលអនុម័ត។"
        )
        try:
            if qr_id:
                await query.message.reply_photo(photo=qr_id, caption=caption)
            else:
                with open("qr.jpg", "rb") as qr_file:
                    await query.message.reply_photo(photo=qr_file, caption=caption)
        except (OSError, TelegramError):
            logger.exception("Could not send QR code")
            await query.message.reply_text(caption + "\n\n⚠️ មិនអាចបង្ហាញ QR Code បានទេ។ សូមទាក់ទង Admin។")

# ------------------------- Receipt flow ----------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    user_id = http://user.id
    if user_id not in user_selected_package:
        await update.message.reply_text("⚠️ សូមជ្រើសរើសកញ្ចប់សមាជិកភាពជាមុនសិន។", reply_markup=package_keyboard())
        return

    current_time = asyncio.get_running_loop().time()
    if not is_admin(user_id):
        last = user_last_photo_time.get(user_id, 0)
        if current_time - last < 10:
            await update.message.reply_text("⚠️ សូមរង់ចាំ ១០ វិនាទី មុនពេលផ្ញើរូបម្ដងទៀត។")
            return
        user_last_photo_time[user_id] = current_time

    photo = update.message.photo[-1]
    file_id, unique_id = photo.file_id, photo.file_unique_id
    days = user_selected_package[user_id]
    username = user.username or user.first_name or "User"

    conn = get_db_connection()
    if conn is None:
        await update.message.reply_text("❌ Database មានបញ្ហា។ សូមសាកល្បងម្ដងទៀតពេលក្រោយ។")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM payment_requests WHERE photo_unique_id = %s", (unique_id,))
                if cur.fetchone():
                    await update.message.reply_text("❌ រូបវិក្កយបត្រនេះត្រូវបានផ្ញើរួចហើយ។")
                    return
                cur.execute("""
                    INSERT INTO payment_requests
                    (photo_unique_id, telegram_file_id, user_id, package_days, status, created_at)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                """, (unique_id, file_id, user_id, days, get_now()))
    except Exception:
        logger.exception("Could not register payment request")
        await update.message.reply_text("❌ មិនអាចរក្សាទុកវិក្កយបត្របានទេ។")
        return
    finally:
        conn.close()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{days}_{unique_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{unique_id}"),
        ],
        [
            InlineKeyboardButton("➕ បន្ថែម ៥ថ្ងៃ", callback_data=f"ext_{user_id}_5"),
            InlineKeyboardButton("➕ បន្ថែម ១០ថ្ងៃ", callback_data=f"ext_{user_id}_10"),
        ],
    ])
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=file_id,
            caption=(
                "🔔 សំណើទូទាត់ថ្មី\n\n"
                f"👤 ឈ្មោះ៖ {username}\n🆔 User ID៖ {user_id}\n"
                f"📦 កញ្ចប់៖ {PACKAGES[days]['label']}\n🧾 Receipt key៖ {unique_id}\n\n"
                "⚠️ សូមពិនិត្យប្រាក់ចូល ABA ពិតប្រាកដ មុនចុច Approve។"
            ),
            reply_markup=keyboard,
        )
        await update.message.reply_text("📥 បានបញ្ជូនវិក្កយបត្រទៅ Admin រួចរាល់។ សូមរង់ចាំការពិនិត្យ។")
    except TelegramError:
        logger.exception("Could not send receipt to admin")
        await update.message.reply_text("❌ មិនអាចផ្ញើវិក្កយបត្រទៅ Admin បានទេ។")

# ------------------ Secure private invite --------------------
async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if not req or http://req.chat.id != GROUP_CHAT_ID:
        return
    joining_user_id = http://req.from_user.id
    invite_url = req.invite_link.invite_link if req.invite_link else None

    if not invite_url:
        try:
            await context.bot.decline_chat_join_request(GROUP_CHAT_ID, joining_user_id)
        except TelegramError:
            logger.exception("Could not decline join request without invite link")
        return

    conn = get_db_connection()
    if conn is None:
        logger.error("Cannot validate join request: database unavailable")
        return
    row = None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, status, expires_at FROM invite_links WHERE invite_link = %s",
                    (invite_url,),
                )
                row = cur.fetchone()
    except Exception:
        logger.exception("Could not validate invite link")
        return
    finally:
        conn.close()

    if not row:
        await decline_request(context, joining_user_id, "❌ Link នេះមិនត្រូវបានទទួលស្គាល់ទេ។")
        return

    assigned_user_id, status_value, expires_text = row
    expires_at = parse_dt(expires_text)
    if assigned_user_id != joining_user_id or status_value != "active" or not expires_at or expires_at <= now_dt():
        await decline_request(
            context, joining_user_id,
            "❌ សំណើចូលក្រុមមិនត្រូវបានអនុម័តទេ។ Link នេះភ្ជាប់ជាមួយគណនីអ្នកទិញម្នាក់ប៉ុណ្ណោះ ឬបានផុតកំណត់។"
        )
        return

    # Claim the link atomically to avoid approving duplicate requests.
    conn = get_db_connection()
    if conn is None:
        return
    claimed = False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE invite_links SET status = 'processing'
                    WHERE invite_link = %s AND user_id = %s AND status = 'active'
                """, (invite_url, joining_user_id))
                claimed = cur.rowcount == 1
    except Exception:
        logger.exception("Could not claim invite")
        return
    finally:
        conn.close()

    if not claimed:
        await decline_request(context, joining_user_id, "❌ Link នេះត្រូវបានប្រើ ឬកំពុងដំណើរការរួចហើយ។")
        return

    try:
        member = db_execute("SELECT expiry_date, kicked FROM users WHERE user_id = %s", (joining_user_id,), fetchone=True)
        member_expiry = parse_dt(member[0]) if member and member[0] else None
        if not member_expiry or member_expiry <= now_dt() or member[1]:
            db_execute("UPDATE invite_links SET status = 'expired' WHERE invite_link = %s", (invite_url,))
            await decline_request(context, joining_user_id, "❌ សមាជិកភាពផុតកំណត់ ឬមិនសកម្មទេ។ សូមបន្តទិញសេវាកម្ម។")
            return

        await context.bot.approve_chat_join_request(chat_id=GROUP_CHAT_ID, user_id=joining_user_id)
        db_execute("UPDATE invite_links SET status = 'used' WHERE invite_link = %s", (invite_url,))
        try:
            await context.bot.revoke_chat_invite_link(chat_id=GROUP_CHAT_ID, invite_link=invite_url)
        except TelegramError:
            logger.warning("Could not revoke used invite for %s", joining_user_id)
        try:
            await context.bot.send_message(joining_user_id, "✅ សំណើចូលក្រុមរបស់អ្នកត្រូវបានអនុម័តហើយ។ សូមស្វាគមន៍!")
        except TelegramError:
            pass
    except Exception:
        logger.exception("Join request processing failed for %s", joining_user_id)
        try:
            db_execute(
                "UPDATE invite_links SET status = 'active' WHERE invite_link = %s AND status = 'processing'",
                (invite_url,),
            )
        except Exception:
            logger.exception("Could not reset invite status")

async def decline_request(context, user_id, message):
    try:
        await context.bot.decline_chat_join_request(chat_id=GROUP_CHAT_ID, user_id=user_id)
    except TelegramError:
        logger.exception("Could not decline join request for %s", user_id)
    try:
        await context.bot.send_message(chat_id=user_id, text=message)
    except TelegramError:
        pass

# --------------------- Membership helper ---------------------
async def add_membership_days(user_id, days, note):
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT expiry_date, package_info FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
                row = cur.fetchone()
                now = now_dt()
                old_exp = parse_dt(row[0]) if row and row[0] else None
                base = old_exp if old_exp and old_exp > now else now
                expiry = fmt_dt(base + timedelta(days=days))
                old_package = row[1] if row and row[1] else "មិនមាន"
                package = f"{old_package} + {note}"
                cur.execute("""
                    INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info)
                    VALUES (%s, %s, %s, 0, 0, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        expiry_date = EXCLUDED.expiry_date, kicked = 0,
                        warned = 0, package_info = EXCLUDED.package_info
                """, (user_id, str(user_id), expiry, package))
        return expiry
    except Exception:
        logger.exception("Could not add membership days")
        return None
    finally:
        conn.close()

# --------------------- Admin receipt actions -----------------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(http://query.from_user.id):
        await query.answer("❌ អ្នកមិនមានសិទ្ធិប្រើមុខងារនេះទេ។", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data.startswith("approve_"):
        parts = data.split("_", 3)
        if len(parts) != 4:
            await query.message.reply_text("❌ ទិន្នន័យ Approve មិនត្រឹមត្រូវ។")
            return
        try:
            user_id, days, unique_id = int(parts[1]), int(parts[2]), parts[3]
        except ValueError:
            return
        if days not in PACKAGES:
            return

        # Create/store invite first. If creation fails, payment remains pending,
        # allowing Admin to retry safely without extending membership twice.
        invite_expiry = now_dt() + timedelta(hours=24)
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                creates_join_request=True,
                expire_date=invite_expiry,
                name=f"paid-{user_id}-{unique_id[:12]}",
            )
        except TelegramError:
            logger.exception("Could not create invite link")
            await query.message.reply_text("❌ បង្កើត Link មិនបានទេ។ សូមពិនិត្យ Bot permissions ហើយចុច Approve ម្តងទៀត។")
            return

        conn = get_db_connection()
        if conn is None:
            try:
                await context.bot.revoke_chat_invite_link(GROUP_CHAT_ID, invite.invite_link)
            except TelegramError:
                pass
            await query.message.reply_text("❌ Database មិនអាចភ្ជាប់បានទេ។")
            return

        expiry_text = None
        approved = False
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT user_id, package_days, status
                        FROM payment_requests
                        WHERE photo_unique_id = %s FOR UPDATE
                    """, (unique_id,))
                    req = cur.fetchone()
                    if not req or req[0] != user_id or req[1] != days:
                        raise ValueError("Payment request mismatch")
                    if req[2] != "pending":
                        await query.message.reply_text("⚠️ សំណើនេះត្រូវបានពិនិត្យរួចហើយ។")
                        return

                    cur.execute("SELECT expiry_date FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
                    old = cur.fetchone()
                    current = now_dt()
                    old_exp = parse_dt(old[0]) if old and old[0] else None
                    base = old_exp if old_exp and old_exp > current else current
                    expiry_text = fmt_dt(base + timedelta(days=days))

                    cur.execute("""
                        INSERT INTO users
                        (user_id, username, expiry_date, kicked, warned, package_info)
                        VALUES (%s, %s, %s, 0, 0, %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            expiry_date = EXCLUDED.expiry_date, kicked = 0,
                            warned = 0, package_info = EXCLUDED.package_info
                    """, (user_id, str(user_id), expiry_text, PACKAGES[days]["label"]))
                    cur.execute("""
                        INSERT INTO used_receipts (photo_file_id, user_id, used_at)
                        VALUES (%s, %s, %s) ON CONFLICT (photo_file_id) DO NOTHING
                    """, (unique_id, user_id, get_now()))
                    cur.execute("""
                        UPDATE payment_requests SET status = 'approved',
                            reviewed_at = %s, reviewed_by = %s
                        WHERE photo_unique_id = %s AND status = 'pending'
                    """, (get_now(), ADMIN_ID, unique_id))
                    if cur.rowcount != 1:
                        raise ValueError("Payment request already reviewed")
                    cur.execute("""
                        INSERT INTO invite_links
                        (invite_link, user_id, photo_unique_id, created_at, expires_at, status)
                        VALUES (%s, %s, %s, %s, %s, 'active')
                    """, (invite.invite_link, user_id, unique_id, get_now(), fmt_dt(invite_expiry)))
                    approved = True
        except ValueError as exc:
            logger.warning("Approval rejected: %s", exc)
            try:
                await context.bot.revoke_chat_invite_link(GROUP_CHAT_ID, invite.invite_link)
            except TelegramError:
                pass
            await query.message.reply_text("⚠️ សំណើនេះមិនត្រឹមត្រូវ ឬត្រូវបានពិនិត្យរួចហើយ។")
            return
        except Exception:
            logger.exception("Approval transaction failed")
            try:
                await context.bot.revoke_chat_invite_link(GROUP_CHAT_ID, invite.invite_link)
            except TelegramError:
                pass
            await query.message.reply_text("❌ ការអនុម័តបរាជ័យ។ សូមពិនិត្យ Database Log មុនសាកល្បងម្ដងទៀត។")
            return
        finally:
            conn.close()

        if not approved:
            return
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 ការទូទាត់របស់អ្នកត្រូវបានអនុម័តហើយ!\n\n"
                    f"🔗 Link ស្នើសុំចូលគ្រុប (សុពលភាព ២៤ ម៉ោង)៖ {invite.invite_link}\n\n"
                    "🔐 Link នេះភ្ជាប់ជាមួយ Telegram User ID របស់អ្នក។ Bot នឹងពិនិត្យមុនអនុម័តសំណើចូល។\n"
                    f"📅 សមាជិកភាពមានសុពលភាពដល់៖ {expiry_text}\n"
                    "ប្រើ /status ដើម្បីពិនិត្យស្ថានភាព។"
                ),
            )
        except TelegramError:
            logger.exception("Could not notify approved user %s", user_id)
            await query.message.reply_text("⚠️ បាន Approve ហើយ ប៉ុន្តែមិនអាចផ្ញើសារទៅអតិថិជនបានទេ។ អតិថិជនត្រូវចុច /start ជាមួយ Bot ជាមុន។")
        try:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n✅ បានអនុម័តរួចរាល់។")
        except TelegramError:
            pass
        return

    if data.startswith("reject_"):
        parts = data.split("_", 2)
        if len(parts) != 3:
            return
        try:
            user_id = int(parts[1])
        except ValueError:
            return
        unique_id = parts[2]
        conn = get_db_connection()
        if conn is None:
            await query.message.reply_text("❌ Database មិនអាចភ្ជាប់បានទេ។")
            return
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE payment_requests SET status = 'rejected',
                            reviewed_at = %s, reviewed_by = %s
                        WHERE photo_unique_id = %s AND user_id = %s AND status = 'pending'
                    """, (get_now(), ADMIN_ID, unique_id, user_id))
                    changed = cur.rowcount
            if changed == 0:
                await query.message.reply_text("⚠️ សំណើនេះត្រូវបានពិនិត្យរួច ឬមិនមានទេ។")
                return
        except Exception:
            logger.exception("Reject failed")
            await query.message.reply_text("❌ មិនអាចបដិសេធសំណើនេះបានទេ។")
            return
        finally:
            conn.close()
        try:
            await context.bot.send_message(user_id, "❌ វិក្កយបត្រមិនត្រូវបានអនុម័តទេ។ សូមទាក់ទង Admin ប្រសិនបើមានកំហុស។")
        except TelegramError:
            pass
        try:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n❌ បានបដិសេធ។")
        except TelegramError:
            pass
        return

    if data.startswith("ext_"):
        parts = data.split("_")
        if len(parts) != 3:
            return
        try:
            user_id, days = int(parts[1]), int(parts[2])
        except ValueError:
            return
        if days <= 0 or days > 365:
            return
        expiry_text = await add_membership_days(user_id, days, f"Admin បន្ថែម {days}ថ្ងៃ")
        if not expiry_text:
            await query.message.reply_text("❌ មិនអាចបន្ថែមថ្ងៃបានទេ។")
            return
        try:
            await context.bot.send_message(user_id, f"✨ Admin បានបន្ថែមសមាជិកភាព {days} ថ្ងៃ។ ផុតកំណត់៖ {expiry_text}")
        except TelegramError:
            pass
        try:
            await query.edit_message_caption(caption=(query.message.caption or "") + f"\n\n➕ បានបន្ថែម {days} ថ្ងៃ។")
        except TelegramError:
            pass

# -------------------------- Status ---------------------------
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    try:
        row = db_execute("SELECT expiry_date, kicked FROM users WHERE user_id = %s", (http://user.id,), fetchone=True)
    except Exception:
        logger.exception("Status query failed")
        await target_message(update).reply_text("❌ មិនអាចពិនិត្យស្ថានភាពបានទេ។")
        return
    if not row:
        await target_message(update).reply_text("អ្នកមិនទាន់មានទិន្នន័យសមាជិកទេ។ សូមប្រើ /start។")
        return
    expiry = parse_dt(row[0])
    if expiry and expiry > now_dt() and not row[1]:
        remaining = expiry - now_dt()
        text = f"ស្ថានភាព៖ សកម្ម ✅\nសល់ពេល៖ {remaining.days} ថ្ងៃ និង {remaining.seconds // 3600} ម៉ោង\nផុតកំណត់៖ {fmt_dt(expiry)}"
    else:
        text = "សមាជិកភាពរបស់អ្នកបានផុតកំណត់ ឬត្រូវបានដកចេញហើយ។ សូមជ្រើសរើសកញ្ចប់ដើម្បីបន្ត។"
    await target_message(update).reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 បន្ត / ទិញសមាជិកភាព", callback_data="extend_menu")
        ]]),
    )

async def extend_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់៖", reply_markup=package_keyboard())

# ----------------------- Admin panel -------------------------
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 ស្ថិតិប្រព័ន្ធ", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 បញ្ជីសមាជិក", callback_data="admin_members_list")],
        [InlineKeyboardButton("📤 Export CSV", callback_data="admin_export_csv")],
        [InlineKeyboardButton("ℹ️ ជំនួយ", callback_data="admin_help")],
    ])
    await update.message.reply_text("👑 Admin Control Panel", reply_markup=keyboard)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(http://query.from_user.id):
        await query.answer("❌ អ្នកមិនមានសិទ្ធិទេ។", show_alert=True)
        return
    await query.answer()
    if query.data == "admin_stats":
        await stats(update, context)
    elif query.data == "admin_members_list":
        await admin_members(update, context)
    elif query.data == "admin_export_csv":
        await export_command(update, context)
    elif query.data == "admin_help":
        await query.message.reply_text(
            "Commands:\n/broadcast សារ\n/adddays USER_ID DAYS\n/kickuser USER_ID\n"
            "/setqr (reply ទៅ QR រូបថ្មី)\n/export"
        )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    message_text = " ".join(context.args).strip()
    if not message_text:
        await update.message.reply_text("ប្រើ៖ /broadcast សារដែលចង់ផ្ញើ")
        return
    try:
        rows = db_execute("SELECT user_id FROM users", fetchall=True)
    except Exception:
        await update.message.reply_text("❌ Database មានបញ្ហា។")
        return
    ok = failed = 0
    for (uid,) in rows:
        try:
            await context.bot.send_message(uid, f"📢 សេចក្តីជូនដំណឹង៖\n\n{message_text}")
            ok += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            failed += 1
    await update.message.reply_text(f"Broadcast រួចរាល់\nជោគជ័យ៖ {ok}\nបរាជ័យ៖ {failed}")

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("ប្រើ៖ /adddays USER_ID DAYS")
        return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        if days <= 0 or days > 3650:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ USER_ID និង DAYS មិនត្រឹមត្រូវទេ។")
        return
    expiry = await add_membership_days(uid, days, f"Admin បន្ថែម {days}ថ្ងៃ")
    if not expiry:
        await update.message.reply_text("❌ មិនអាចបន្ថែមថ្ងៃបានទេ។")
        return
    await update.message.reply_text(f"✅ បានបន្ថែម {days} ថ្ងៃដល់ {uid}។ ផុតកំណត់៖ {expiry}")
    try:
        await context.bot.send_message(uid, f"✨ Admin បានបន្ថែម {days} ថ្ងៃ។ ផុតកំណត់៖ {expiry}")
    except TelegramError:
        pass

async def kickuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("ប្រើ៖ /kickuser USER_ID")
        return
    try:
        uid = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
        await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
        db_execute("UPDATE users SET kicked = 1 WHERE user_id = %s", (uid,))
        await update.message.reply_text(f"✅ បានដក User {uid} ចេញពីគ្រុប។")
    except Exception:
        logger.exception("kickuser failed")
        await update.message.reply_text("❌ មិនអាចដក User ចេញបានទេ។ ពិនិត្យ Bot permissions និង User ID។")

async def setqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    reply = update.message.reply_to_message
    if not reply or not reply.photo:
        await update.message.reply_text("សូម Reply ទៅរូប QR Code ថ្មី រួចវាយ /setqr")
        return
    conn = get_db_connection()
    if conn is None:
        await update.message.reply_text("❌ Database មានបញ្ហា។")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_settings (key, value) VALUES ('custom_qr_file_id', %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """, (reply.photo[-1].file_id,))
        await update.message.reply_text("✅ បានប្តូរ QR Code ជោគជ័យ។")
    except Exception:
        logger.exception("setqr failed")
        await update.message.reply_text("❌ មិនអាចប្តូរ QR Code បានទេ។")
    finally:
        conn.close()

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        return
    try:
        rows = db_execute(
            "SELECT user_id, username, expiry_date, kicked, warned, package_info FROM users ORDER BY user_id",
            fetchall=True,
        )
    except Exception:
        await target_message(update).reply_text("❌ Database មានបញ្ហា។")
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User ID", "Username", "Expiry Date", "Kicked", "Warned", "Package Info"])
    writer.writerows(rows)
    file_obj = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8"))
    file_obj.name = "members_data.csv"
    await target_message(update).reply_document(document=file_obj, caption="📊 ទិន្នន័យសមាជិក (CSV)")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("❌ អ្នកមិនមែនជា Admin ទេ។", show_alert=True)
        return
    try:
        rows = db_execute("SELECT expiry_date, kicked FROM users", fetchall=True)
    except Exception:
        await target_message(update).reply_text("❌ Database មានបញ្ហា។")
        return
    active = expired = 0
    now = now_dt()
    for exp_text, kicked in rows:
        exp = parse_dt(exp_text)
        if kicked or not exp or exp <= now:
            expired += 1
        else:
            active += 1
    await target_message(update).reply_text(f"📊 ស្ថិតិប្រព័ន្ធ\n\n🟢 សកម្ម៖ {active}\n🔴 ផុតកំណត់/ត្រូវបានដក៖ {expired}")

async def admin_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(http://update.effective_user.id):
        if update.callback_query:
            await update.callback_query.answer("❌ អ្នកមិនមែនជា Admin ទេ។", show_alert=True)
        return
    try:
        rows = db_execute(
            "SELECT user_id, username, expiry_date, kicked, package_info FROM users ORDER BY user_id",
            fetchall=True,
        )
    except Exception:
        await target_message(update).reply_text("❌ Database មានបញ្ហា។")
        return
    if not rows:
        await target_message(update).reply_text("មិនទាន់មានសមាជិកទេ។")
        return
    now = now_dt()
    lines = ["📋 បញ្ជីសមាជិក៖"]
    for uid, username, exp_text, kicked, package in rows:
        exp = parse_dt(exp_text)
        if kicked:
            state = "🔴 ត្រូវបានដកចេញ"
        elif exp and exp > now:
            state = f"🟢 សកម្ម (សល់ {(exp - now).days} ថ្ងៃ)"
        else:
            state = "🔴 ផុតកំណត់"
        lines.append(f"\n👤 {username or 'មិនមានឈ្មោះ'}\n🆔 {uid}\n📦 {package or 'មិនមាន'}\n⏳ {state} | {exp_text or 'មិនមានថ្ងៃ'}")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) > 3500:
            await target_message(update).reply_text(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await target_message(update).reply_text(chunk)

# --------------------- Expiry background job -----------------
async def expiry_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        if conn is None:
            return
        try:
            with conn:
                with conn.cursor() as cur:
                    now = now_dt()
                    now_text = fmt_dt(now)
                    soon_text = fmt_dt(now + timedelta(hours=24))
                    cur.execute("""
                        SELECT user_id FROM users
                        WHERE expiry_date <= %s AND expiry_date > %s
                          AND warned = 0 AND kicked = 0
                    """, (soon_text, now_text))
                    warn_ids = [r[0] for r in cur.fetchall()]
                    cur.execute("""
                        SELECT user_id FROM users
                        WHERE expiry_date <= %s AND kicked = 0
                    """, (now_text,))
                    expired_ids = [r[0] for r in cur.fetchall()]
            for uid in warn_ids:
                try:
                    await context.bot.send_message(
                        uid,
                        "⚠️ សមាជិកភាពរបស់អ្នកនឹងផុតកំណត់ក្នុង ២៤ ម៉ោង។ សូមបន្តកញ្ចប់ជាមុន។",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("💳 បន្តសមាជិកភាព", callback_data="extend_menu")
                        ]]),
                    )
                    db_execute("UPDATE users SET warned = 1 WHERE user_id = %s AND kicked = 0", (uid,))
                except Exception:
                    logger.exception("Could not warn user %s", uid)
            for uid in expired_ids:
                try:
                    await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
                    await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
                except TelegramError:
                    logger.exception("Could not remove expired user %s", uid)
                    continue
                try:
                    await context.bot.send_message(
                        uid,
                        "⏰ សមាជិកភាពរបស់អ្នកបានផុតកំណត់ ហើយត្រូវបានដកចេញពីគ្រុប។ សូមទិញកញ្ចប់ថ្មីដើម្បីចូលវិញ។",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("💳 ទិញកញ្ចប់ថ្មី", callback_data="extend_menu")
                        ]]),
                    )
                except TelegramError:
                    pass
                db_execute("UPDATE users SET kicked = 1 WHERE user_id = %s", (uid,))
        finally:
            conn.close()
    except Exception:
        logger.exception("Expiry job failed")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled Telegram update error", exc_info=context.error)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set")
    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin_members", admin_members))
    application.add_handler(CommandHandler("admin", admin_panel_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("adddays", adddays_command))
    application.add_handler(CommandHandler("kickuser", kickuser_command))
    application.add_handler(CommandHandler("setqr", setqr_command))
    application.add_handler(CommandHandler("export", export_command))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(ChatJoinRequestHandler(handle_chat_join_request))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(approve_|reject_|ext_)"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern=r"^(pkg_|get_referral_link|user_)"))
    application.add_handler(CallbackQueryHandler(extend_menu_callback, pattern=r"^extend_menu$"))
    application.add_error_handler(error_handler)

    if application.job_queue:
        application.job_queue.run_repeating(expiry_job, interval=60, first=15)
    else:
        logger.warning("JobQueue unavailable. Install python-telegram-bot[job-queue].")

    http://logger.info("Subscription bot starting")
    application.run_polling()

if __name__ == "__main__":
    main()
