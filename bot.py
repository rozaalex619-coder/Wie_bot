import asyncio import csv import io import logging import os import threading from datetime import datetime, timedelta from zoneinfo import ZoneInfo
import psycopg2 from flask import Flask from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.error import TelegramError from telegram.ext import ( ApplicationBuilder, CallbackQueryHandler, ChatJoinRequestHandler, CommandHandler, ContextTypes, MessageHandler, filters, )
============================================================
CONFIGURATION
============================================================
CAMBODIA_TZ = ZoneInfo("Asia/Phnom_Penh") ADMIN_ID = int(os.getenv("ADMIN_ID", "8980369344")) GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1004400009713"))
PACKAGES = { 5: {"price": "២ ដុល្លារ", "label": "៥ ថ្ងៃ - ២ ដុល្លារ", "en": "5 Days - $2"}, 10: {"price": "៣ ដុល្លារ", "label": "១០ ថ្ងៃ - ៣ ដុល្លារ", "en": "10 Days - $3"}, 20: {"price": "៥ ដុល្លារ", "label": "២០ ថ្ងៃ - ៥ ដុល្លារ", "en": "20 Days - $5"}, 30: {"price": "៦ ដុល្លារ", "label": "៣០ ថ្ងៃ - ៦ ដុល្លារ", "en": "30 Days - $6"}, }
logging.basicConfig( format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=os.getenv("LOG_LEVEL", "INFO"), ) logger = logging.getLogger("subscription_bot") DATABASE_URL = os.getenv("DATABASE_URL")
user_selected_package = {} user_last_photo_time = {} admin_states = {}
--------------------------- Flask ---------------------------
app_web = Flask(name)
@app_web.route("/") def home(): return "Smart Auto-Verify Subscription Bot is running!"
def run_web(): port = int(os.getenv("PORT", "10000")) app_web.run(host="0.0.0.0", port=port, use_reloader=False)
threading.Thread(target=run_web, daemon=True).start()
------------------------- Utilities -------------------------
def now_dt(): return datetime.now(CAMBODIA_TZ)
def get_now(): return now_dt().strftime("%Y-%m-%d %H:%M:%S")
def parse_dt(value): if not value: return None if isinstance(value, datetime): return value.replace(tzinfo=CAMBODIA_TZ) if value.tzinfo is None else value.astimezone(CAMBODIA_TZ) return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CAMBODIA_TZ)
def fmt_dt(value): return value.astimezone(CAMBODIA_TZ).strftime("%Y-%m-%d %H:%M:%S")
def get_db_connection(): if not DATABASE_URL: logger.error("DATABASE_URL environment variable is missing") return None try: return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10) except Exception: logger.exception("Database connection failed") return None
def db_execute(sql, params=(), fetchone=False, fetchall=False): conn = get_db_connection() if conn is None: raise RuntimeError("Database is unavailable") try: with conn: with conn.cursor() as cur: cur.execute(sql, params) if fetchone: return cur.fetchone() if fetchall: return cur.fetchall() return None finally: conn.close()
def log_admin_action(admin_id, action_type, details): try: db_execute( "INSERT INTO admin_logs (admin_id, action_type, details, created_at) VALUES (%s, %s, %s, %s)", (admin_id, action_type, details, get_now()) ) except Exception: logger.exception("Failed to log admin action")
def is_admin(user_id): return user_id == ADMIN_ID
def target_message(update): if update.callback_query: return update.callback_query.message return update.effective_message
def get_user_lang(user_id): row = db_execute("SELECT language FROM users WHERE user_id = %s", (user_id,), fetchone=True) return row[0] if row and row[0] else "km"
def package_keyboard(lang="km"): if lang == "en": return InlineKeyboardMarkup([ [InlineKeyboardButton(PACKAGES[5]["en"], callback_data="pkg_5")], [InlineKeyboardButton(PACKAGES[10]["en"], callback_data="pkg_10")], [InlineKeyboardButton(PACKAGES[20]["en"], callback_data="pkg_20")], [InlineKeyboardButton(PACKAGES[30]["en"], callback_data="pkg_30")], [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="user_main_menu")], ]) return InlineKeyboardMarkup([ [InlineKeyboardButton(PACKAGES[5]["label"], callback_data="pkg_5")], [InlineKeyboardButton(PACKAGES[10]["label"], callback_data="pkg_10")], [InlineKeyboardButton(PACKAGES[20]["label"], callback_data="pkg_20")], [InlineKeyboardButton(PACKAGES[30]["label"], callback_data="pkg_30")], [InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")], ])
def main_keyboard(lang="km"): if lang == "en": return InlineKeyboardMarkup([ [InlineKeyboardButton("🛒 Select Membership Package", callback_data="user_packages")], [InlineKeyboardButton("📊 Check Membership Status", callback_data="user_check_status")], [InlineKeyboardButton("👥 Referral Link (+1 Hour)", callback_data="get_referral_link")], [InlineKeyboardButton("🎁 Referral Dashboard", callback_data="referral_dashboard")], [InlineKeyboardButton("❓ Payment Guide", callback_data="user_payment_help")], [InlineKeyboardButton("🇰🇭/🇬🇧 Switch Language", callback_data="switch_lang")], ]) return InlineKeyboardMarkup([ [InlineKeyboardButton("🛒 ជ្រើសរើសកញ្ចប់សមាជិកភាព", callback_data="user_packages")], [InlineKeyboardButton("📊 ពិនិត្យស្ថានភាពសមាជិកភាព", callback_data="user_check_status")], [InlineKeyboardButton("👥 Link ណែនាំមិត្តភក្តិ (ថែម ១ ម៉ោង)", callback_data="get_referral_link")], [InlineKeyboardButton("🎁 ស្ថិតិការណែនាំមិត្តភក្តិ (Referral)", callback_data="referral_dashboard")], [InlineKeyboardButton("❓ របៀបទូទាត់ប្រាក់", callback_data="user_payment_help")], [InlineKeyboardButton("🇰🇭/🇬🇧 Switch Language", callback_data="switch_lang")], ])
def admin_main_keyboard(): return InlineKeyboardMarkup([ [InlineKeyboardButton("📊 ស្ថិតិប្រព័ន្ធ", callback_data="adm_stats"), InlineKeyboardButton("📋 បញ្ជីសមាជិក", callback_data="adm_members")], [InlineKeyboardButton("📜 Admin Audit Logs", callback_data="adm_logs"), InlineKeyboardButton("📤 Export CSV", callback_data="adm_export")], [InlineKeyboardButton("📢 ផ្ញើសារ Broadcast", callback_data="adm_broadcast_prompt"), InlineKeyboardButton("➕ បន្ថែមថ្ងៃ User", callback_data="adm_adddays_prompt")], [InlineKeyboardButton("👢 ដក User ចេញគ្រុប", callback_data="adm_kick_prompt"), InlineKeyboardButton("📸 ប្តូរ QR Code", callback_data="adm_qr_prompt")], [InlineKeyboardButton("🔄 ធ្វើឱ្យស្រស់ (Refresh)", callback_data="adm_panel")] ])
def init_db(): conn = get_db_connection() if conn is None: logger.error("Skipping database initialization; no database connection") return try: with conn: with conn.cursor() as cur: cur.execute(""" CREATE TABLE IF NOT EXISTS users ( user_id BIGINT PRIMARY KEY, username TEXT, expiry_date TEXT, kicked INTEGER DEFAULT 0, warned INTEGER DEFAULT 0, package_info TEXT DEFAULT 'មិនមាន', referral_code TEXT, referred_by BIGINT, language TEXT DEFAULT 'km' ) """) cur.execute(""" CREATE TABLE IF NOT EXISTS used_receipts ( photo_file_id TEXT PRIMARY KEY, user_id BIGINT, used_at TEXT ) """) cur.execute(""" CREATE TABLE IF NOT EXISTS bot_settings ( key TEXT PRIMARY KEY, value TEXT ) """) cur.execute(""" CREATE TABLE IF NOT EXISTS payment_requests ( id BIGSERIAL PRIMARY KEY, photo_unique_id TEXT UNIQUE NOT NULL, telegram_file_id TEXT NOT NULL, user_id BIGINT NOT NULL, package_days INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by BIGINT ) """) cur.execute(""" CREATE TABLE IF NOT EXISTS invite_links ( invite_link TEXT PRIMARY KEY, user_id BIGINT NOT NULL, photo_unique_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active' ) """) cur.execute(""" CREATE TABLE IF NOT EXISTS admin_logs ( id BIGSERIAL PRIMARY KEY, admin_id BIGINT NOT NULL, action_type TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL ) """) logger.info("Database initialized successfully with Smart Auto-Verify Receipt Protection") except Exception: logger.exception("Database initialization failed") finally: conn.close()
init_db()
--------------------------- /start --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user if not user: return user_id = user.id username = user.username or user.first_name or "User" referrer_id = None
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
                            context.application.create_task(notify_referrer(context, referrer_id))
                    cur.execute("""
                        INSERT INTO users
                        (user_id, username, expiry_date, kicked, warned, package_info,
                         referral_code, referred_by, language)
                        VALUES (%s, %s, %s, 0, 0, %s, %s, %s, 'km')
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

lang = get_user_lang(user_id)
text = (
    f"សួស្តី {user.first_name or 'មិត្ត'}!\n\n"
    "សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសមាជិកភាពគ្រុប។\n"
    "សូមជ្រើសរើសមុខងារខាងក្រោម៖"
    if lang == "km" else
    f"Hello {user.first_name or 'Friend'}!\n\n"
    "Welcome to the group subscription system.\n"
    "Please choose an option below:"
)
await update.effective_message.reply_text(text, reply_markup=main_keyboard(lang))
async def notify_referrer(context, referrer_id): try: lang = get_user_lang(referrer_id) msg = ( "🎁 មិត្តភក្តិថ្មីបានចូលតាម Link របស់អ្នក! អ្នកទទួលបានបន្ថែម ១ ម៉ោង។" if lang == "km" else "🎁 A new friend joined via your link! You received an extra 1 hour." ) await context.bot.send_message(chat_id=referrer_id, text=msg) except TelegramError: logger.info("Could not notify referrer %s", referrer_id)
----------------------- User callbacks ----------------------
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() data = query.data user_id = query.from_user.id lang = get_user_lang(user_id)
if data == "switch_lang":
    new_lang = "en" if lang == "km" else "km"
    db_execute("UPDATE users SET language = %s WHERE user_id = %s", (new_lang, user_id))
    await query.message.edit_text(
        "Language changed to English." if new_lang == "en" else "ភាសាត្រូវបានប្ដូរជាភាសាខ្មែរ។",
        reply_markup=main_keyboard(new_lang)
    )
    return
if data == "referral_dashboard":
    rows = db_execute("SELECT COUNT(*) FROM users WHERE referred_by = %s", (user_id,), fetchone=True)
    invited_count = rows[0] if rows else 0
    text = (
        f"🎁 **Referral Dashboard**\n\n"
        f"👥 មិត្តភក្តិបានអញ្ជើញសរុប៖ {invited_count} នាក់\n"
        f"⏱ រង្វាន់សរុប៖ បានបន្ថែមម៉ោងដោយស្វ័យប្រវត្តិទៅលើ Expiry Date របស់អ្នក។"
        if lang == "km" else
        f"🎁 **Referral Dashboard**\n\n"
        f"👥 Total Friends Invited: {invited_count}\n"
        f"⏱ Reward: Automatically added to your expiry date."
    )
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Back" if lang == "en" else "⬅️ ត្រឡប់ក្រោយ", callback_data="user_main_menu")
    ]]))
    return
if data == "user_packages":
    await query.message.reply_text(
        "📦 សូមជ្រើសរើសកញ្ចប់សមាជិកភាព៖" if lang == "km" else "📦 Please select a membership package:",
        reply_markup=package_keyboard(lang)
    )
    return
if data == "user_check_status":
    await status(update, context)
    return
if data == "user_payment_help":
    help_text = (
        "💳 របៀបទូទាត់ប្រាក់៖\n\n1. ជ្រើសរើសកញ្ចប់សមាជិកភាព។\n2. ស្កេន QR Code ដើម្បីបង់ប្រាក់។\n3. ផ្ញើរូបវិក្កយបត្រមក Bot នេះ (ប្រព័ន្ធ Auto-Verify នឹងពិនិត្យលេខកូដវិក្កយបត្រដោយស្វ័យប្រវត្តិ)។\n4. រង់ចាំ Admin អនុម័ត។"
        if lang == "km" else
        "💳 Payment Guide:\n\n1. Select a package.\n2. Scan QR Code to pay.\n3. Send your receipt photo to this bot.\n4. Wait for Admin approval."
    )
    await query.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back" if lang == "en" else "⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")
        ]]),
    )
    return
if data == "user_main_menu":
    await query.message.reply_text(
        "សូមជ្រើសរើសមុខងារ៖" if lang == "km" else "Please select an option:",
        reply_markup=main_keyboard(lang)
    )
    return
if data == "get_referral_link":
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    ref_text = (
        f"🔗 Link ណែនាំមិត្តភក្តិ៖\n{link}\n\nមិត្តភក្តិថ្មីដែលចូលប្រើ Bot តាម Link នេះ នឹងផ្តល់រង្វាន់ ១ ម៉ោងដល់អ្នក។"
        if lang == "km" else
        f"🔗 Referral Link:\n{link}\n\nFriends joining via this link grant you an extra 1 hour."
    )
    await query.message.reply_text(ref_text)
    return
if data.startswith("pkg_"):
    try:
        days = int(data.split("_", 1)[1])
    except ValueError:
        return
    if days not in PACKAGES:
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
        "📸 បន្ទាប់ពីបង់ប្រាក់ សូមផ្ញើរូបវិក្កយបត្រមក Bot (ប្រព័ន្ធ Auto-Verify នឹងចាប់លេខកូដវិក្កយបត្រដោយស្វ័យប្រវត្តិ)។"
        if lang == "km" else
        f"📦 Package: {days} Days ({PACKAGES[days]['price']})\n\n"
        "💳 Please scan QR Code to pay.\n"
        "📸 Send your payment receipt to this bot."
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
------------------------- Receipt flow (Smart Auto-Verify) ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user if not user or not update.message or not update.message.photo: return user_id = user.id
# Check if admin is sending QR code update
if is_admin(user_id) and admin_states.get(user_id) == "waiting_qr":
    db_execute("""
        INSERT INTO bot_settings (key, value) VALUES ('custom_qr_file_id', %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
    """, (update.message.photo[-1].file_id,))
    admin_states.pop(user_id, None)
    log_admin_action(user_id, "SET_QR", "Updated custom QR code via photo")
    await update.message.reply_text("✅ បានប្តូរ QR Code ថ្មីជោគជ័យ!", reply_markup=admin_main_keyboard())
    return

lang = get_user_lang(user_id)
if user_id not in user_selected_package:
    await update.message.reply_text(
        "⚠️ សូមជ្រើសរើសកញ្ចប់សមាជិកភាពជាមុនសិន។" if lang == "km" else "⚠️ Please select a membership package first.",
        reply_markup=package_keyboard(lang)
    )
    return

current_time = asyncio.get_running_loop().time()
if not is_admin(user_id):
    last = user_last_photo_time.get(user_id, 0)
    if current_time - last < 5:
        await update.message.reply_text(
            "⚠️ សូមរង់ចាំបន្តិច មុនពេលផ្ញើរូបម្ដងទៀត។" if lang == "km" else "⚠️ Please wait before sending another photo."
        )
        return
    user_last_photo_time[user_id] = current_time

photo = update.message.photo[-1]
file_id, unique_id = photo.file_id, photo.file_unique_id
days = user_selected_package[user_id]
username = user.username or user.first_name or "User"

conn = get_db_connection()
if conn is None:
    await update.message.reply_text("❌ Database error.")
    return

try:
    with conn:
        with conn.cursor() as cur:
            # 1. ពិនិត្យមើលថាតើ Receipt Unique ID ឬ File ID នេះធ្លាប់ត្រូវបានប្រើប្រាស់រួចហើយឬនៅ (Duplicate Check)
            cur.execute("SELECT user_id, status FROM used_receipts WHERE photo_file_id = %s", (unique_id,))
            used_check = cur.fetchone()
            
            cur.execute("SELECT status FROM payment_requests WHERE photo_unique_id = %s", (unique_id,))
            req_check = cur.fetchone()

            if used_check or req_check:
                # ប្រសិនបើធ្លាប់ប្រើហើយ Bot ធ្វើការទប់ស្កាត់ និងបដិសេធភ្លាមៗ (Auto-Reject Duplicate)
                logger.warning(f"Duplicate receipt detected! User {user_id} tried to reuse receipt unique_id: {unique_id}")
                await update.message.reply_text(
                    "❌ **កំហុស៖ វិក្កយបត្រនេះត្រូវបានប្រើប្រាស់ក្នុងប្រព័ន្ធរួចហើយ!**\n"
                    "ប្រព័ន្ធ Auto-Verify បានចាប់យកលេខសម្គាល់វិក្កយបត្រនេះ ហើយปฏิเสธការស្នើសុំซ้ำដោយស្វ័យប្រវត្តិ។ សូមប្រើវិក្កយបត្រថ្មីដែលត្រឹមត្រូវ។"
                    if lang == "km" else
                    "❌ **Error: This receipt has already been used in the system!** Auto-rejected."
                )
                return

            # 2. ប្រសិនបារូបភាពថ្មីសុទ្ធសាធ ធ្វើការកត់ត្រាទុកក្នុង Database ជា Pending Request
            cur.execute("""
                INSERT INTO payment_requests
                (photo_unique_id, telegram_file_id, user_id, package_days, status, created_at)
                VALUES (%s, %s, %s, %s, 'pending', %s)
            """, (unique_id, file_id, user_id, days, get_now()))
except Exception:
    logger.exception("Could not register payment request")
    await update.message.reply_text("❌ Could not save receipt.")
    return
finally:
    conn.close()

# បង្កើតប៊ូតុងសម្រាប់ Admin ពិនិត្យเฉพาะករណីមានវិក្កយបត្រថ្មីចូលមកប៉ុណ្ណោះ
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
            "🔔 **សំណើទូទាត់ថ្មី (New Valid Receipt)**\n\n"
            f"👤 ឈ្មោះ៖ {username}\n"
            f"🆔 User ID៖ `{user_id}`\n"
            f"📦 កញ្ចប់៖ {PACKAGES[days]['label']}\n"
            f"🧾 Receipt Unique Hash: `{unique_id}`\n\n"
            "💡 *ប្រព័ន្ធ Auto-Verify បានចាប់យកលេខកូដវិក្កយបត្រនេះរួចរាល់ និងរក្សាទុកក្នុងទិន្នន័យដើម្បីការពារការយកមកប្រើซ้ำ។*"
        ),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "📥 បានផ្ញើវិក្កយបត្រទៅប្រព័ន្ធ Auto-Verify និង Admin រួចរាល់។ ប្រព័ន្ធបានចាប់យកលេខកូដវិក្កយបត្ររបស់អ្នករួចរាល់ហើយ។ សូមរង់ចាំការពិនិត្យ។"
        if lang == "km" else
        "📥 Receipt submitted successfully. Hash saved. Please wait."
    )
except TelegramError:
    logger.exception("Could not send receipt to admin")
    await update.message.reply_text("❌ Could not send receipt to admin.")
------------------ Text Message Handler (Admin prompts) -----
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user if not user or not is_admin(user.id): return
admin_id = user.id
state = admin_states.get(admin_id)
text = update.message.text.strip()

if state == "waiting_broadcast":
    admin_states.pop(admin_id, None)
    rows = db_execute("SELECT user_id FROM users", fetchall=True)
    ok = failed = 0
    for (uid,) in rows:
        try:
            await context.bot.send_message(uid, f"📢 សេចក្តីជូនដំណឹង៖\n\n{text}")
            ok += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            failed += 1
    log_admin_action(admin_id, "BROADCAST", f"Success: {ok}, Failed: {failed}")
    await update.message.reply_text(f"✅ Broadcast រួចរាល់!\nជោគជ័យ៖ {ok}\nបរាជ័យ៖ {failed}", reply_markup=admin_main_keyboard())

elif state == "waiting_adddays":
    admin_states.pop(admin_id, None)
    parts = text.split()
    if len(parts) != 2:
        await update.message.reply_text("❌ ទម្រង់មិនត្រឹមត្រូវ។ សូមវាយជាឧទាហរណ៍៖ `123456789 10`", parse_mode="Markdown", reply_markup=admin_main_keyboard())
        return
    try:
        uid, days = int(parts[0]), int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ User ID និង Days ត្រូវតែជាលេខ។", reply_markup=admin_main_keyboard())
        return
    expiry = await add_membership_days(uid, days, f"Admin បន្ថែម {days}ថ្ងៃ")
    log_admin_action(admin_id, "ADD_DAYS_PROMPT", f"User: {uid}, Days: {days}")
    await update.message.reply_text(f"✅ បានបន្ថែម {days} ថ្ងៃដល់ User `{uid}`។ ផុតកំណត់៖ {expiry}", parse_mode="Markdown", reply_markup=admin_main_keyboard())
    try:
        await context.bot.send_message(uid, f"✨ Admin បានបន្ថែម {days} ថ្ងៃ។ ផុតកំណត់៖ {expiry}")
    except TelegramError:
        pass

elif state == "waiting_kick":
    admin_states.pop(admin_id, None)
    try:
        uid = int(text)
        await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
        await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
        db_execute("UPDATE users SET kicked = 1 WHERE user_id = %s", (uid,))
        log_admin_action(admin_id, "KICK_USER_PROMPT", f"User: {uid}")
        await update.message.reply_text(f"✅ បានដក User `{uid}` ចេញពីគ្រុបជោគជ័យ។", parse_mode="Markdown", reply_markup=admin_main_keyboard())
    except Exception:
        await update.message.reply_text("❌ កំហុស៖ មិនអាចដក User នេះបានទេ។ សូមពិនិត្យ User ID ម្តងទៀត។", reply_markup=admin_main_keyboard())
------------------ Secure private invite --------------------
async def handle_chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE): req = update.chat_join_request if not req or req.chat.id != GROUP_CHAT_ID: return joining_user_id = req.from_user.id invite_url = req.invite_link.invite_link if req.invite_link else None
if not invite_url:
    try:
        await context.bot.decline_chat_join_request(GROUP_CHAT_ID, joining_user_id)
    except TelegramError:
        pass
    return

conn = get_db_connection()
if conn is None:
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
    return
finally:
    conn.close()

if not row:
    await decline_request(context, joining_user_id, "❌ Link មិនត្រឹមត្រូវ។")
    return

assigned_user_id, status_value, expires_text = row
expires_at = parse_dt(expires_text)
if assigned_user_id != joining_user_id or status_value != "active" or not expires_at or expires_at <= now_dt():
    await decline_request(context, joining_user_id, "❌ Link បានផុតកំណត់ ឬមិនមែនរបស់អ្នក។")
    return

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
    return
finally:
    conn.close()

if not claimed:
    await decline_request(context, joining_user_id, "❌ Link ត្រូវបានប្រើរួចហើយ។")
    return

try:
    member = db_execute("SELECT expiry_date, kicked FROM users WHERE user_id = %s", (joining_user_id,), fetchone=True)
    member_expiry = parse_dt(member[0]) if member and member[0] else None
    if not member_expiry or member_expiry <= now_dt() or member[1]:
        db_execute("UPDATE invite_links SET status = 'expired' WHERE invite_link = %s", (invite_url,))
        await decline_request(context, joining_user_id, "❌ សមាជិកភាពផុតកំណត់។")
        return

    await context.bot.approve_chat_join_request(chat_id=GROUP_CHAT_ID, user_id=joining_user_id)
    db_execute("UPDATE invite_links SET status = 'used' WHERE invite_link = %s", (invite_url,))
    try:
        await context.bot.revoke_chat_invite_link(chat_id=GROUP_CHAT_ID, invite_link=invite_url)
    except TelegramError:
        pass
    try:
        await context.bot.send_message(joining_user_id, "✅ សំណើចូលក្រុមត្រូវបានអនុម័ត! សូមស្វាគមន៍!")
    except TelegramError:
        pass
except Exception:
    logger.exception("Join request processing failed")
async def decline_request(context, user_id, message): try: await context.bot.decline_chat_join_request(chat_id=GROUP_CHAT_ID, user_id=user_id) except TelegramError: pass try: await context.bot.send_message(chat_id=user_id, text=message) except TelegramError: pass
--------------------- Membership helper ---------------------
async def add_membership_days(user_id, days, note): conn = get_db_connection() if conn is None: return None try: with conn: with conn.cursor() as cur: cur.execute("SELECT expiry_date, package_info FROM users WHERE user_id = %s FOR UPDATE", (user_id,)) row = cur.fetchone() now = now_dt() old_exp = parse_dt(row[0]) if row and row[0] else None base = old_exp if old_exp and old_exp > now else now expiry = fmt_dt(base + timedelta(days=days)) old_package = row[1] if row and row[1] else "មិនមាន" package = f"{old_package} + {note}" cur.execute(""" INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info) VALUES (%s, %s, %s, 0, 0, %s) ON CONFLICT (user_id) DO UPDATE SET expiry_date = EXCLUDED.expiry_date, kicked = 0, warned = 0, package_info = EXCLUDED.package_info """, (user_id, str(user_id), expiry, package)) return expiry except Exception: logger.exception("Could not add membership days") return None finally: conn.close()
--------------------- Admin receipt & panel actions ---------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query if not is_admin(query.from_user.id): await query.answer("❌ Unauthorized.", show_alert=True) return await query.answer() data = query.data
if data == "adm_panel":
    await query.message.edit_text("👑 **Admin Control Panel**\n\nសូមជ្រើសរើសមុខងារខាងក្រោម៖", reply_markup=admin_main_keyboard(), parse_mode="Markdown")
    return
elif data == "adm_stats":
    await stats_action(query)
    return
elif data == "adm_members":
    await admin_members_action(query)
    return
elif data == "adm_logs":
    logs = db_execute("SELECT admin_id, action_type, details, created_at FROM admin_logs ORDER BY id DESC LIMIT 15", fetchall=True)
    if not logs:
        await query.message.reply_text("គ្មានទិន្នន័យ Audit Logs ទេ។", reply_markup=admin_main_keyboard())
        return
    msg = ["📜 **Recent Admin Audit Logs:**"]
    for aid, action, details, time in logs:
        msg.append(f"• [{time}] Admin `{aid}`: **{action}** ({details})")
    await query.message.reply_text("\n".join(msg), parse_mode="Markdown", reply_markup=admin_main_keyboard())
    return
elif data == "adm_export":
    await export_action(query, context)
    return
elif data == "adm_broadcast_prompt":
    admin_states[query.from_user.id] = "waiting_broadcast"
    await query.message.reply_text("📢 **Broadcast Mode**\n\nសូមផ្ញើសារដែលអ្នកចង់ Broadcast ទៅកាន់សមាជិកទាំងអស់៖", parse_mode="Markdown")
    return
elif data == "adm_adddays_prompt":
    admin_states[query.from_user.id] = "waiting_adddays"
    await query.message.reply_text("➕ **Add Days Mode**\n\nសូមផ្ញើ User ID និងចំនួនថ្ងៃមក (ឧទាហរណ៍៖ `123456789 15`)៖", parse_mode="Markdown")
    return
elif data == "adm_kick_prompt":
    admin_states[query.from_user.id] = "waiting_kick"
    await query.message.reply_text("👢 **Kick User Mode**\n\nសូមផ្ញើ Telegram User ID ដែលត្រូវដកចេញពីគ្រុប៖", parse_mode="Markdown")
    return
elif data == "adm_qr_prompt":
    admin_states[query.from_user.id] = "waiting_qr"
    await query.message.reply_text("📸 **Change QR Code Mode**\n\nសូមផ្ញើរូបភាព QR Code ថ្មីមកកាន់ Chat នេះ៖")
    return

# Receipt Approvals & Extensions
if data.startswith("approve_"):
    parts = data.split("_", 3)
    if len(parts) != 4:
        return
    try:
        user_id, days, unique_id = int(parts[1]), int(parts[2]), parts[3]
    except ValueError:
        return
    if days not in PACKAGES:
        return

    invite_expiry = now_dt() + timedelta(hours=24)
    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=GROUP_CHAT_ID,
            creates_join_request=True,
            expire_date=invite_expiry,
            name=f"paid-{user_id}-{unique_id[:12]}",
        )
    except TelegramError:
        await query.message.reply_text("❌ Could not create invite link.")
        return

    conn = get_db_connection()
    if conn is None:
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
                if not req or req[0] != user_id or req[1] != days or req[2] != "pending":
                    raise ValueError("Invalid request")

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
                
                # บันทឹกลงตาราง Used Receipts เพื่อป้องกันการนำกลับมาใช้อีกอย่างถาวร
                cur.execute("""
                    INSERT INTO used_receipts (photo_file_id, user_id, used_at)
                    VALUES (%s, %s, %s) ON CONFLICT (photo_file_id) DO NOTHING
                """, (unique_id, user_id, get_now()))
                
                cur.execute("""
                    UPDATE payment_requests SET status = 'approved',
                        reviewed_at = %s, reviewed_by = %s
                    WHERE photo_unique_id = %s AND status = 'pending'
                """, (get_now(), ADMIN_ID, unique_id))
                cur.execute("""
                    INSERT INTO invite_links
                    (invite_link, user_id, photo_unique_id, created_at, expires_at, status)
                    VALUES (%s, %s, %s, %s, %s, 'active')
                """, (invite.invite_link, user_id, unique_id, get_now(), fmt_dt(invite_expiry)))
                approved = True
    except Exception:
        logger.exception("Approval failed")
        return
    finally:
        conn.close()

    if approved:
        log_admin_action(query.from_user.id, "APPROVE_PAYMENT", f"User: {user_id}, Days: {days}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 ការទូទាត់ត្រូវបានអនុម័ត!\n\n"
                    f"🔗 Link ចូលគ្រុប (២៤ម៉ោង)៖ {invite.invite_link}\n"
                    f"📅 ផុតកំណត់៖ {expiry_text}"
                ),
            )
        except TelegramError:
            pass
        try:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n✅ Approved.")
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
    db_execute("""
        UPDATE payment_requests SET status = 'rejected',
            reviewed_at = %s, reviewed_by = %s
        WHERE photo_unique_id = %s AND status = 'pending'
    """, (get_now(), ADMIN_ID, unique_id))
    log_admin_action(query.from_user.id, "REJECT_PAYMENT", f"User: {user_id}, Receipt: {unique_id}")
    try:
        await context.bot.send_message(user_id, "❌ វិក្កយបត្ររបស់អ្នកមិនត្រូវបានអនុម័តទេ។")
    except TelegramError:
        pass
    try:
        await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n❌ Rejected.")
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
    expiry_text = await add_membership_days(user_id, days, f"Admin បន្ថែម {days}ថ្ងៃ")
    log_admin_action(query.from_user.id, "EXTEND_DAYS", f"User: {user_id}, Days: {days}")
    try:
        await context.bot.send_message(user_id, f"✨ Admin បានបន្ថែម {days} ថ្ងៃ។ ផុតកំណត់៖ {expiry_text}")
    except TelegramError:
        pass
    try:
        await query.edit_message_caption(caption=(query.message.caption or "") + f"\n\n➕ Added {days} days.")
    except TelegramError:
        pass
-------------------------- Status & Panel Actions -----------
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user if not user: return try: row = db_execute("SELECT expiry_date, kicked FROM users WHERE user_id = %s", (user.id,), fetchone=True) except Exception: await target_message(update).reply_text("❌ Database error.") return lang = get_user_lang(user.id) if not row: await target_message(update).reply_text("សូមប្រើ /start ជាមុនសិន។" if lang == "km" else "Please use /start first.") return expiry = parse_dt(row[0]) if expiry and expiry > now_dt() and not row[1]: remaining = expiry - now_dt() text = ( f"ស្ថានភាព៖ សកម្ម ✅\nសល់ពេល៖ {remaining.days} ថ្ងៃ និង {remaining.seconds // 3600} ម៉ោង\nផុតកំណត់៖ {fmt_dt(expiry)}" if lang == "km" else f"Status: Active ✅\nRemaining: {remaining.days} days and {remaining.seconds // 3600} hours\nExpires: {fmt_dt(expiry)}" ) else: text = "សមាជិកភាពផុតកំណត់។" if lang == "km" else "Membership expired." await target_message(update).reply_text( text, reply_markup=InlineKeyboardMarkup([[ InlineKeyboardButton("💳 ទិញសមាជិកភាព" if lang == "km" else "💳 Extend/Buy", callback_data="extend_menu") ]]), )
async def extend_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.answer() lang = get_user_lang(update.callback_query.from_user.id) await update.callback_query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់៖", reply_markup=package_keyboard(lang))
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): return await update.message.reply_text("👑 Admin Control Panel\n\nសូមជ្រើសរើសមុខងារខាងក្រោម៖", reply_markup=admin_main_keyboard(), parse_mode="Markdown")
async def stats_action(query): rows = db_execute("SELECT expiry_date, kicked FROM users", fetchall=True) active = expired = 0 now = now_dt() for exp_text, kicked in rows: exp = parse_dt(exp_text) if kicked or not exp or exp <= now: expired += 1 else: active += 1 await query.message.reply_text(f"📊 ស្ថិតិប្រព័ន្ធ\n\n🟢 សកម្ម៖ {active}\n🔴 ផុតកំណត់៖ {expired}", reply_markup=admin_main_keyboard())
async def admin_members_action(query): rows = db_execute("SELECT user_id, username, expiry_date, kicked, package_info FROM users ORDER BY user_id", fetchall=True) if not rows: await query.message.reply_text("មិនទាន់មានសមាជិកទេ។", reply_markup=admin_main_keyboard()) return now = now_dt() lines = ["📋 បញ្ជីសមាជិក៖"] for uid, username, exp_text, kicked, package in rows: exp = parse_dt(exp_text) state = "🔴 ត្រូវបានដក" if kicked else (f"🟢 សកម្ម" if exp and exp > now else "🔴 ផុតកំណត់") lines.append(f"\n👤 {username or 'User'}\n🆔 {uid}\n📦 {package}\n⏳ {state} | {exp_text}") chunk = "" for line in lines: if len(chunk) + len(line) > 3500: await query.message.reply_text(chunk) chunk = "" chunk += line + "\n" if chunk: await query.message.reply_text(chunk, reply_markup=admin_main_keyboard())
async def export_action(query, context): rows = db_execute("SELECT user_id, username, expiry_date, kicked, warned, package_info FROM users ORDER BY user_id", fetchall=True) output = io.StringIO() writer = csv.writer(output) writer.writerow(["User ID", "Username", "Expiry Date", "Kicked", "Warned", "Package Info"]) writer.writerows(rows) file_obj = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8")) file_obj.name = "members_data.csv" await context.bot.send_document(chat_id=query.from_user.id, document=file_obj, caption="📊 ទិន្នន័យសមាជិក (CSV)")
--------------------- Expiry background job -----------------
async def expiry_job(context: ContextTypes.DEFAULT_TYPE): try: conn = get_db_connection() if conn is None: return try: with conn: with conn.cursor() as cur: now = now_dt() now_text = fmt_dt(now) soon_text = fmt_dt(now + timedelta(hours=24)) cur.execute(""" SELECT user_id FROM users WHERE expiry_date <= %s AND expiry_date > %s AND warned = 0 AND kicked = 0 """, (soon_text, now_text)) warn_ids = [r[0] for r in cur.fetchall()] cur.execute(""" SELECT user_id FROM users WHERE expiry_date <= %s AND kicked = 0 """, (now_text,)) expired_ids = [r[0] for r in cur.fetchall()] for uid in warn_ids: try: lang = get_user_lang(uid) msg = ( "⚠️ សមាជិកភាពរបស់អ្នកនឹងផុតកំណត់ក្នុង ២៤ ម៉ោង។" if lang == "km" else "⚠️ Your membership expires in 24 hours." ) await context.bot.send_message( uid, msg, reply_markup=InlineKeyboardMarkup([[ InlineKeyboardButton("💳 បន្តសមាជិកភាព" if lang == "km" else "💳 Extend", callback_data="extend_menu") ]]), ) db_execute("UPDATE users SET warned = 1 WHERE user_id = %s AND kicked = 0", (uid,)) except Exception: pass for uid in expired_ids: try: await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid) await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid) except TelegramError: continue try: lang = get_user_lang(uid) msg = ( "⏰ សមាជិកភាពផុតកំណត់ និងត្រូវបានដកចេញពីគ្រុប។" if lang == "km" else "⏰ Membership expired and removed from group." ) await context.bot.send_message(uid, msg) except TelegramError: pass db_execute("UPDATE users SET kicked = 1 WHERE user_id = %s", (uid,)) finally: conn.close() except Exception: logger.exception("Expiry job failed")
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE): logger.error("Unhandled Telegram update error", exc_info=context.error)
def main(): token = os.getenv("BOT_TOKEN") if not token: raise RuntimeError("BOT_TOKEN environment variable is not set") application = ApplicationBuilder().token(token).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("status", status))
application.add_handler(CommandHandler("admin", admin_panel_command))

application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
application.add_handler(ChatJoinRequestHandler(handle_chat_join_request))

application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(approve_|reject_|ext_|adm_)"))
application.add_handler(CallbackQueryHandler(package_callback, pattern=r"^(pkg_|get_referral_link|user_|switch_lang|referral_dashboard)"))
application.add_handler(CallbackQueryHandler(extend_menu_callback, pattern=r"^extend_menu$"))

application.add_error_handler(error_handler)

if application.job_queue:
    application.job_queue.run_repeating(expiry_job, interval=60, first=15)
else:
    logger.warning("JobQueue unavailable.")

logger.info("Smart Auto-Verify Bot starting")
application.run_polling()
if name == "main": main()
