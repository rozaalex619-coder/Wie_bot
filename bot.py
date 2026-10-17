import threading
import psycopg2
import time
import os
import io
import csv
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    filters
)
from flask import Flask

# កំណត់ Timezone ឱ្យត្រូវនឹងប្រទេសកម្ពុជា (Asia/Phnom_Penh)
CAMBODIA_TZ = pytz.timezone('Asia/Phnom_Penh')

def get_now():
    return datetime.now(CAMBODIA_TZ).strftime('%Y-%m-%d %H:%M:%S')

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with Safe Cloud PostgreSQL Storage is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ ---
ADMIN_ID = 8980369344                      
GROUP_INVITE_LINK = "https://t.me/+1_JA7CSmMoYxMDg1"  # Link សម្រាប់ Admin ប្រើប្រាស់ផ្ទាល់
GROUP_CHAT_ID = -1004400009713            # ID របស់ Channel / Group របស់បង
# ---------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

# មុខងារតភ្ជាប់ Cloud Database យ៉ាងមានសុវត្ថិភាព
def get_db_connection():
    if not DATABASE_URL:
        print("⚠️ Warning: DATABASE_URL environment variable is missing!")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

user_selected_package = {}
user_last_photo_time = {}

# 2. បង្កើត Database Tables លើ Cloud PostgreSQL (មានសុវត្ថិភាព មិនលុបទិន្នន័យចាស់)
def init_db():
    conn = get_db_connection()
    if conn is None:
        print("⚠️ Skipping init_db because database connection failed.")
        return
    try:
        cursor = conn.cursor()
        cursor.execute('''
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
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS used_receipts (
                photo_file_id TEXT PRIMARY KEY,
                user_id BIGINT,
                used_at TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database initialized & secured successfully!")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

init_db()

# 3. ពាក្យបញ្ជា /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name
        
        args = context.args
        referrer_id = None
        if args and args[0].startswith("ref_"):
            try:
                potential_referrer = int(args[0].split("_")[1])
                if potential_referrer != user_id:
                    referrer_id = potential_referrer
            except Exception:
                pass

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT expiry_date FROM users WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
                
                now_dt = datetime.now(CAMBODIA_TZ)
                if not result:
                    default_expiry = (now_dt - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
                    
                    if referrer_id:
                        cursor.execute('SELECT expiry_date FROM users WHERE user_id = %s', (referrer_id,))
                        ref_res = cursor.fetchone()
                        if ref_res:
                            try:
                                ref_exp = datetime.strptime(ref_res[0], '%Y-%m-%d %H:%M:%S')
                                ref_exp = CAMBODIA_TZ.localize(ref_exp) if ref_exp.tzinfo is None else ref_exp
                                base_time = ref_exp if ref_exp > now_dt else now_dt
                                new_ref_exp = (base_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                                cursor.execute('UPDATE users SET expiry_date = %s WHERE user_id = %s', (new_ref_exp, referrer_id))
                                await context.bot.send_message(chat_id=referrer_id, text="🎁 មានមិត្តភក្តិបានចូលប្រើប្រាស់ Bot តាមរយៈ Link របស់អ្នក! អ្នកទទួលបានការថែមជូន **១ម៉ោង** ដោយស្វ័យប្រវត្តិ។")
                            except Exception as e:
                                print(f"Error giving referral bonus: {e}")

                    cursor.execute('''
                        INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info, referral_code, referred_by)
                        VALUES (%s, %s, %s, 0, 0, 'មិនទាន់ជ្រើសរើសកញ្ចប់', %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
                    ''', (user_id, username, default_expiry, f"ref_{user_id}", referrer_id))
                    conn.commit()
                else:
                    cursor.execute('UPDATE users SET username = %s WHERE user_id = %s', (username, user_id))
                    conn.commit()
                
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error in start query: {e}")
        
        keyboard = [
            [InlineKeyboardButton("🛒 ជ្រើសរើសកញ្ចប់សមាជិកភាព", callback_data="user_packages")],
            [InlineKeyboardButton("📊 ពិនិត្យស្ថានភាពសមាជិកភាព", callback_data="user_check_status")],
            [InlineKeyboardButton("👥 យក Link ណែនាំមិត្តភក្តិ (ថែម ១ម៉ោង)", callback_data="get_referral_link")],
            [InlineKeyboardButton("❓ របៀបទូទាត់ប្រាក់", callback_data="user_payment_help")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_text = (
            f"សួស្តី {user.first_name}!\n\n"
            f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសមាជិកភាពគ្រុបរបស់យើង។\n"
            f"សូមជ្រើសរើសមុខងារដែលអ្នកចង់ប្រើប្រាស់នៅខាងក្រោម៖"
        )
        if update.callback_query:
            await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error in start command: {e}")

# 4. ដោះស្រាយ Package, Status, Referral
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "user_packages":
            keyboard = [
                [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
                [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
                [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
                [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")],
                [InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់សមាជិកភាពដែលអ្នកពេញចិត្ត៖", reply_markup=reply_markup)
            return

        elif data == "user_check_status":
            await status(update, context)
            return

        elif data == "user_payment_help":
            help_text = (
                "💳 **របៀបទូទាត់ប្រាក់៖**\n\n"
                "1. ចុចប៊ូតុង **'🛒 ជ្រើសរើសកញ្ចប់សមាជិកភាព'**\n"
                "2. ជ្រើសរើសកញ្ចប់ចំនួនថ្ងៃដែលចង់បាន\n"
                "3. ស្កែន QR Code ដែលបង្ហាញនៅលើអេក្រង់ដើម្បីបង់ប្រាក់\n"
                "4. ថតរូបវិក្កយបត្រ (Screenshot/Slip) រួចផ្ញើចូលក្នុង Bot នេះ\n"
                "5. Admin នឹងពិនិត្យ និងអនុម័តឱ្យចូលគ្រុបភ្លាមៗ!"
            )
            keyboard = [[InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")]]
            await query.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        elif data == "user_main_menu":
            await start(update, context)
            return

        elif data == "get_referral_link":
            bot_username = context.bot.username
            ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
            await query.message.reply_text(
                f"🔗 **តំណភ្ជាប់ណែនាំមិត្តភក្តិ (Referral Link) របស់អ្នក៖**\n\n"
                f"`{ref_link}`\n\n"
                f"💡 **អត្ថប្រយោជន៍៖** ពេលមានមិត្តភក្តិចុចចូលតាម Link នេះ អ្នកនឹងទទួលបានការថែមជូន **១ម៉ោង** ចូលក្នុងសមាជិកភាពរបស់អ្នកដោយស្វ័យប្រវត្តិ!",
                parse_mode="Markdown"
            )
            return

        if data.startswith("pkg_"):
            days = int(data.split("_")[1])
            user_selected_package[user_id] = days
            
            prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
            price_text = prices.get(days, "")
            
            caption = (
                f"📦 អ្នកបានជ្រើសរើសកញ្ចប់៖ **{days} ថ្ងៃ** (តម្លៃ: **{price_text}**)\n\n"
                f"💳 ១. សូម Scan QR Code ខាងលើដើម្បីទូទាត់ប្រាក់។\n"
                f"📸 ២. បន្ទាប់ពីបង់ប្រាក់រួច សូមថតរូបវិក្កយបត្រ (Screenshot) ហើយផ្ញើរូបភាពនោះចូលមកកាន់ Bot នេះផ្ទាល់។\n\n"
                f"🤖 (វិក្កយបត្ររបស់អ្នកនឹងត្រូវផ្ញើទៅកាន់ Admin ពិនិត្យ និងអនុម័តជូន!)"
            )
            
            conn = get_db_connection()
            custom_qr_file_id = None
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM bot_settings WHERE key = 'custom_qr_file_id'")
                    res = cur.fetchone()
                    if res:
                        custom_qr_file_id = res[0]
                    cur.close()
                    conn.close()
                except Exception:
                    pass

            try:
                if custom_qr_file_id:
                    await query.message.reply_photo(photo=custom_qr_file_id, caption=caption, parse_mode="Markdown")
                else:
                    await query.message.reply_photo(photo=open('qr.jpg', 'rb'), caption=caption, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(f"{caption}\n\n(⚠️ រកមិនឃើញឯកសារ qr.jpg ឬ Custom QR ទេ)")
    except Exception as e:
        print(f"Error in package_callback: {e}")

# 5. ទទួលរូបភាពវិក្កយបត្រ
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name
        
        if user_id not in user_selected_package:
            keyboard = [
                [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
                [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
                [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
                [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "⚠️ **សូមជ្រើសរើសកញ្ចប់សមាជិកភាពជាមុនសិន!**\n\n"
                "អ្នកមិនទាន់បានជ្រើសរើសកញ្ចប់ទេ សូមចុចជ្រើសរើសកញ្ចប់ខាងក្រោម រួចค่อยផ្ញើរូបភាពវិក្កយបត្រ (Slip) មកម្តងទៀត៖",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return

        photo_obj = update.message.photo[-1]
        photo_file = photo_obj.file_id
        photo_unique_id = photo_obj.file_unique_id

        now_ts = time.time()
        if user_id != ADMIN_ID:
            last_time = user_last_photo_time.get(user_id, 0)
            if now_ts - last_time < 10:
                await update.message.reply_text("⚠️ សូមកុំផ្ញើរូបភាពញាប់ពេក! សូមរង់ចាំបន្តិចសិន។")
                return
            user_last_photo_time[user_id] = now_ts
        
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM used_receipts WHERE photo_file_id = %s', (photo_unique_id,))
                receipt_check = cursor.fetchone()
                cursor.close()
                conn.close()
                if receipt_check:
                    await update.message.reply_text("❌ **វិក្កយបត្រ (Slip) នេះត្រូវបានប្រើប្រាស់រួចរាល់ហើយ!**\nប្រព័ន្ធបានរកឃើញថាវិក្កយបត្រនេះធ្លាប់ត្រូវបានបញ្ជូនម្តងរួចមកហើយ សូមកុំយកវិក្កយបត្រចាស់មកផ្ញើសារម្តងទៀត។")
                    return
            except Exception as e:
                print(f"Error checking receipt: {e}")
            
        days = user_selected_package.get(user_id)
        prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
        price_text = prices.get(days, "មិនស្គាល់តម្លៃ")
        package_desc = f"{days} ថ្ងៃ - {price_text}"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ យល់ព្រម (Approve)", callback_data=f"approve_{user_id}_{days}"),
                InlineKeyboardButton("❌ បដិសេធ (Reject)", callback_data=f"reject_{user_id}")
            ],
            [
                InlineKeyboardButton("➕ បន្ថែម ៥ថ្ងៃ", callback_data=f"ext_{user_id}_5"),
                InlineKeyboardButton("➕ បន្ថែម ១០ថ្ងៃ", callback_data=f"ext_{user_id}_10")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        admin_caption = (
            f"🔔 **មានអតិថិជនស្នើសុំចូលសមាជិក! (New Receipt)**\n\n"
            f"👤 ឈ្មោះ: {username}\n"
            f"🆔 User ID: `{user_id}`\n"
            f"ជម្រើសកញ្ចប់: **{package_desc}**\n"
            f"🖼 Photo ID: `{photo_file}`\n\n"
            f"⏳ (ប្រព័ន្ធបានផ្ទៀងផ្ទាត់ថាជា Slip ថ្មី សុវត្ថិភាព ១០០%។ សូម Admin ពិនិត្យ និងចុចសម្រេចចិត្តខាងក្រោម)"
        )
        
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file,
                caption=admin_caption,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await update.message.reply_text("📥 វិក្កយបត្ររបស់អ្នកត្រូវបានបញ្ជូនរួចរាល់ហើយ! សូមរង់ចាំ Admin ពិនិត្យ និងអនុម័តជូនក្នុងពេលបន្តិចទៀតនេះ...")
        except Exception as e:
            await update.message.reply_text("មានបញ្ហាក្នុងការផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")
    except Exception as e:
        print(f"Error in handle_photo: {e}")

# 6. ប្រព័ន្ធ Admin ចុច Approve, Reject ឬ Extend
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ អ្នកមិនមានសិទ្ធិអនុវត្តមុខងារនេះទេ!", show_alert=True)
            return
            
        await query.answer()
        data = query.data
        
        if data.startswith("approve_"):
            parts = data.split("_")
            user_id = int(parts[1])
            days = int(parts[2])
            
            user_display_name = "Customer"
            if query.message.caption:
                for line in query.message.caption.split("\n"):
                    if "👤 ឈ្មោះ:" in line:
                        user_display_name = line.replace("👤 ឈ្មោះ:", "").strip()
                        break

            expiry = (datetime.now(CAMBODIA_TZ) + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
            price_text = prices.get(days, "មិនស្គាល់តម្លៃ")
            package_desc = f"{days} ថ្ងៃ - {price_text}"
            
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    if query.message.photo:
                        photo_obj = query.message.photo[-1] if hasattr(query.message, 'photo') else None
                        if photo_obj:
                            photo_unique_id = photo_obj.file_unique_id
                            cursor.execute('INSERT INTO used_receipts (photo_file_id, user_id, used_at) VALUES (%s, %s, %s) ON CONFLICT (photo_file_id) DO NOTHING', 
                                           (photo_unique_id, user_id, get_now()))
                    
                    cursor.execute('''
                        INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info)
                        VALUES (%s, %s, %s, 0, 0, %s)
                        ON CONFLICT (user_id) DO UPDATE SET 
                            expiry_date = EXCLUDED.expiry_date,
                            kicked = 0,
                            warned = 0,
                            package_info = EXCLUDED.package_info,
                            username = EXCLUDED.username
                    ''', (user_id, user_display_name, expiry, package_desc))
                        
                    conn.commit()
                    cursor.close()
                    conn.close()
                    print(f"✅ User {user_id} saved/updated in DB successfully!")
                except Exception as e:
                    print(f"❌ Error approving user in DB: {e}")
            
            try:
                invite_link = await context.bot.create_chat_invite_link(
                    chat_id=GROUP_CHAT_ID,
                    member_limit=1
                )
                custom_link = invite_link.invite_link
            except Exception:
                custom_link = GROUP_INVITE_LINK
            
            try:
                success_message = (
                    f"🎉 អបអរសាទរ! ការទូទាត់របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ។\n\n"
                    f"🔗 តំណភ្ជាប់ចូលគ្រុប (Group Link):\n{custom_link}\n\n"
                    f"📅 សមាជិកភាពមានសុពលភាពចំនួន {days} ថ្ងៃ ដល់ថ្ងៃ៖ {expiry}\n"
                    f"ពិនិត្យថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
                )
                await context.bot.send_message(chat_id=user_id, text=success_message)
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ [បានអនុម័តជោគជ័យ {days} ថ្ងៃ និងផ្ញើ Auto-Join Link ជូនរួចរាល់]")
            except Exception as e:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ អនុម័តរួច ប៉ុន្តែមានបញ្ហាក្នុងការផ្ញើសារទៅ User")
                
        elif data.startswith("reject_"):
            user_id = int(data.split("_")[1])
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ សូមអភ័យទោស វិក្កយបត្ររបស់អ្នកមិនត្រឹមត្រូវ សូមទាក់ទងមក Admin ។")
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")
            except Exception:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")
                
        elif data.startswith("ext_"):
            parts = data.split("_")
            user_id = int(parts[1])
            ext_days = int(parts[2])
            
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute('SELECT expiry_date, package_info FROM users WHERE user_id = %s', (user_id,))
                    res = cursor.fetchone()
                    
                    now_dt = datetime.now(CAMBODIA_TZ)
                    if res and res[0]:
                        current_expiry = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
                        current_expiry = CAMBODIA_TZ.localize(current_expiry) if current_expiry.tzinfo is None else current_expiry
                        base_time = current_expiry if current_expiry > now_dt else now_dt
                        old_pkg = res[1] if res[1] else "មិនមាន"
                    else:
                        base_time = now_dt
                        old_pkg = "មិនមាន"
                        
                    new_expiry = (base_time + timedelta(days=ext_days)).strftime('%Y-%m-%d %H:%M:%S')
                    new_pkg = f"{old_pkg} + បន្ថែម {ext_days}ថ្ងៃ"
                    
                    cursor.execute('''
                        UPDATE users SET expiry_date = %s, kicked = 0, package_info = %s WHERE user_id = %s
                    ''', (new_expiry, new_pkg, user_id))
                    conn.commit()
                    cursor.close()
                    conn.close()
                except Exception as e:
                    print(f"Error extending days: {e}")
            
            try:
                await context.bot.send_message(chat_id=user_id, text=f"✨ Admin បានបន្ថែមថ្ងៃសមាជិកភាពឱ្យអ្នកចំនួន {ext_days} ថ្ងៃបន្ថែមទៀត! ផុតកំណត់ថ្ងៃ៖ {new_expiry}")
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n➕ [បានបន្ថែមថ្ងៃជោគជ័យ +{ext_days} ថ្ងៃ]")
            except Exception:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n➕ [បានបន្ថែមថ្ងៃជោគជ័យ +{ext_days} ថ្ងៃ ប៉ុន្តែផ្ញើសារមិនទាន់ដល់ User]")
    except Exception as e:
        print(f"Error in button_callback: {e}")

# --- Admin Panel Commands ---
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 ស្ថិតិប្រព័ន្ធ (Stats)", callback_data="admin_stats")],
            [InlineKeyboardButton("📋 បញ្ជីសមាជិកទាំងអស់", callback_data="admin_members_list")],
            [InlineKeyboardButton("📊 Export ទិន្នន័យ (CSV)", callback_data="admin_export_csv")],
            [InlineKeyboardButton("ℹ️ វិធីប្រើប្រាស់ Command ផ្សេងៗ", callback_data="admin_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("👑 **Admin Control Panel**\n\nសូមជ្រើសរើសមុខងារដែលចង់ត្រួតពិនិត្យខាងក្រោម៖", reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in admin_panel_command: {e}")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if query.from_user.id != ADMIN_ID:
            await query.answer("❌ អ្នកមិនមានសិទ្ធិទេ!", show_alert=True)
            return
            
        await query.answer()
        data = query.data
        
        if data == "admin_stats":
            await stats(update, context)
            
        elif data == "admin_members_list":
            await admin_members(update, context)
            
        elif data == "admin_export_csv":
            await export_command(update, context)
            
        elif data == "admin_help":
            help_txt = (
                "ℹ️ **ជំនួយការប្រើប្រាស់ Admin Commands:**\n\n"
                "• `/broadcast <សារ>` : ផ្ញើសារទៅសមាជិកទាំងអស់\n"
                "• `/adddays <user_id> <ថ្ងៃ>` : បន្ថែមថ្ងៃឱ្យ User\n"
                "• `/kickuser <user_id>` : ទាត់ User ចេញពីគ្រុប\n"
                "• `/setqr` : Reply រូបភាព QR ដើម្បីប្តូរ QR ថ្មី"
            )
            await query.message.reply_text(help_txt, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in admin_panel_callback: {e}")

# Broadcast
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        text_to_broadcast = " ".join(context.args)
        if not text_to_broadcast:
            await update.message.reply_text("⚠️ សូមសរសេរសារដែលចង់ Broadcast ផង។ ឧទាហរណ៍៖ `/broadcast សួស្តីសមាជិកទាំងអស់...`", parse_mode="Markdown")
            return

        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ មានបញ្ហា Database។")
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users")
            all_users = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

        success_count = 0
        fail_count = 0
        for row in all_users:
            u_id = row[0]
            try:
                await context.bot.send_message(chat_id=u_id, text=f"📢 **សេចក្តីប្រកាសជូនដំណឹង៖**\n\n{text_to_broadcast}", parse_mode="Markdown")
                success_count += 1
                time.sleep(0.1)
            except Exception:
                fail_count += 1

        await update.message.reply_text(f"✅ Broadcast បានជោគជ័យ!\n- ជោគជ័យ: {success_count} នាក់\n- បរាជ័យ: {fail_count} នាក់")
    except Exception as e:
        print(f"Error in broadcast_command: {e}")

async def adddays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("⚠️ ប្រើប្រាស់៖ `/adddays <user_id> <days>`", parse_mode="Markdown")
            return
        try:
            target_user_id = int(args[0])
            add_d = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ User ID និង Days ត្រូវតែជាតួលេខ។")
            return

        conn = get_db_connection()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT expiry_date, package_info FROM users WHERE user_id = %s", (target_user_id,))
            res = cur.fetchone()
            now_dt = datetime.now(CAMBODIA_TZ)
            if res and res[0]:
                cur_exp = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
                cur_exp = CAMBODIA_TZ.localize(cur_exp) if cur_exp.tzinfo is None else cur_exp
                base = cur_exp if cur_exp > now_dt else now_dt
                old_pkg = res[1] or "Manual"
            else:
                base = now_dt
                old_pkg = "Manual"

            new_exp = (base + timedelta(days=add_d)).strftime('%Y-%m-%d %H:%M:%S')
            new_pkg = f"{old_pkg} + Admin បន្ថែម {add_d}ថ្ងៃ"

            cur.execute("INSERT INTO users (user_id, username, expiry_date, kicked, package_info) VALUES (%s, %s, %s, 0, %s) ON CONFLICT (user_id) DO UPDATE SET expiry_date = %s, kicked = 0, package_info = %s",
                        (target_user_id, "User", new_exp, new_pkg, new_exp, new_pkg))
            conn.commit()
            cur.close()
            conn.close()

            await update.message.reply_text(f"✅ បានបន្ថែមថ្ងៃសមាជិកភាពចំនួន {add_d} ថ្ងៃ ដល់ User ID: `{target_user_id}` ជោគជ័យ!\nផុតកំណត់ថ្ងៃ៖ {new_exp}", parse_mode="Markdown")
            try:
                await context.bot.send_message(chat_id=target_user_id, text=f"✨ Admin បានបន្ថែមថ្ងៃសមាជិកភាពឱ្យអ្នកចំនួន {add_d} ថ្ងៃ! ផុតកំណត់ថ្ងៃ៖ {new_exp}")
            except Exception:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        print(f"Error in adddays_command: {e}")

async def kickuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        args = context.args
        if not args:
            await update.message.reply_text("⚠️ ប្រើប្រាស់៖ `/kickuser <user_id>`", parse_mode="Markdown")
            return
        try:
            target_user_id = int(args[0])
            await context.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=target_user_id)
            await context.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=target_user_id)
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET kicked = 1 WHERE user_id = %s", (target_user_id,))
                conn.commit()
                cur.close()
                conn.close()
            await update.message.reply_text(f"✅ បានទាត់ User ID `{target_user_id}` ចេញពីគ្រុប និង Update DB រួចរាល់។", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        print(f"Error in kickuser_command: {e}")

async def setqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        reply = update.message.reply_to_message
        if not reply or not reply.photo:
            await update.message.reply_text("⚠️ សូម Reply (ឆ្លើយតប) ទៅកាន់រូបភាព QR Code ថ្មី ជាមួយពាក្យ `/setqr`", parse_mode="Markdown")
            return
        
        new_photo_file_id = reply.photo[-1].file_id
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Database error.")
            return
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO bot_settings (key, value) VALUES ('custom_qr_file_id', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_photo_file_id, new_photo_file_id))
            conn.commit()
            cur.close()
            conn.close()
            await update.message.reply_text("✅ បានប្តូរ QR Code ថ្មីសម្រាប់ទូទាត់ប្រាក់ដោយជោគជ័យ!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        print(f"Error in setqr_command: {e}")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Database error.")
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, username, expiry_date, kicked, warned, package_info FROM users")
            rows = cur.fetchall()
            cur.close()
            conn.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["User ID", "Username", "Expiry Date", "Kicked", "Warned", "Package Info"])
        for r in rows:
            writer.writerow(r)
        
        output.seek(0)
        bio = io.BytesIO(output.getvalue().encode('utf-8'))
        bio.name = "members_data.csv"
        
        target_message = update.callback_query.message if update.callback_query else update.message
        await target_message.reply_document(document=bio, caption="📊 បញ្ជីទិន្នន័យសមាជិកទាំងអស់ក្នុងប្រព័ន្ធ (CSV Export)")
    except Exception as e:
        print(f"Error in export_command: {e}")

# 9. stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            return
            
        active_users = 0
        expired_users = 0
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT expiry_date, kicked FROM users")
                rows = cursor.fetchall()
                cursor.close()
                conn.close()
                
                now_dt = datetime.now(CAMBODIA_TZ)
                for row in rows:
                    exp_str, kicked = row[0], row[1]
                    if kicked == 1:
                        expired_users += 1
                    else:
                        try:
                            exp_date = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                            exp_date = CAMBODIA_TZ.localize(exp_date) if exp_date.tzinfo is None else exp_date
                            if now_dt < exp_date:
                                active_users += 1
                            else:
                                expired_users += 1
                        except Exception:
                            expired_users += 1
            except Exception as e:
                print(f"Error fetching stats: {e}")
        
        stats_text = (
            f"📊 **ស្ថិតិប្រព័ន្ធសមាជិកភាព (Admin Dashboard)**\n\n"
            f"🟢 សមាជិកសកម្ម (Active): **{active_users} នាក់**\n"
            f"🔴 សមាជិកអស់សុពលភាព (Expired): **{expired_users} នាក់**"
        )
        target_message = update.callback_query.message if update.callback_query else update.message
        await target_message.reply_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in stats: {e}")

# Admin មើលបញ្ជីសមាជិក
async def admin_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            if update.callback_query:
                await update.callback_query.answer("❌ អ្នកមិនមែនជា Admin ទេ!", show_alert=True)
            return
            
        rows = []
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id, username, expiry_date, kicked, package_info FROM users')
                rows = cursor.fetchall()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error fetching admin_members: {e}")
        
        target_message = update.callback_query.message if update.callback_query else update.message
        
        if not rows:
            await target_message.reply_text("📭 មិនទាន់មានទិន្នន័យសមាជិកនៅក្នុងប្រព័ន្ធទេ។")
            return
            
        msg = "📋 **បញ្ជីឈ្មោះ កញ្ចប់ តម្លៃ និងថ្ងៃផុតកំណត់សមាជិកទាំងអស់៖**\n\n"
        now_dt = datetime.now(CAMBODIA_TZ)
        
        for row in rows:
            u_id, uname, exp_str, kicked, package_info = row
            name = uname if uname else "មិនមានឈ្មោះ"
            badge = "💳 [Paid]"
            pkg_desc = package_info if package_info else "មិនមានទិន្នន័យ"
            
            if kicked == 1:
                status_text = f"🔴 បានទាត់ចេញ | ផុតកំណត់ថ្ងៃ៖ {exp_str}"
            else:
                try:
                    exp_date = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                    exp_date = CAMBODIA_TZ.localize(exp_date) if exp_date.tzinfo is None else exp_date
                    if now_dt < exp_date:
                        rem = exp_date - now_dt
                        days = rem.days
                        hours = rem.seconds // 3600
                        status_text = f"🟢 សកម្ម (សល់ {days} ថ្ងៃ និង {hours} ម៉ោង) | ផុតកំណត់៖ {exp_str}"
                    else:
                        status_text = f"🔴 ផុតកំណត់ហើយ | កាលបរិច្ឆេទ៖ {exp_str}"
                except Exception:
                    status_text = f"📅 ផុតកំណត់ថ្ងៃ៖ {exp_str}"
                    
            msg += f"👤 ឈ្មោះ: **{name}** {badge}\n🆔 ID: `{u_id}`\n📦 កញ្ចប់/តម្លៃ: **{pkg_desc}**\n⏳ ស្ថានភាព: {status_text}\n----------------------------------\n"
            
        if len(msg) > 4000:
            for x in range(0, len(msg), 4000):
                await target_message.reply_text(msg[x:x+4000], parse_mode="Markdown")
        else:
            await target_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in admin_members: {e}")

# 10. status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        result = None
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT expiry_date FROM users WHERE user_id = %s', (user_id,))
                result = cursor.fetchone()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error checking status: {e}")
        
        target_message = update.callback_query.message if update.callback_query else update.message
        
        if result:
            expiry_str = result[0]
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
            expiry_date = CAMBODIA_TZ.localize(expiry_date) if expiry_date.tzinfo is None else expiry_date
            now_dt = datetime.now(CAMBODIA_TZ)

            if now_dt < expiry_date:
                remaining = expiry_date - now_dt
                days = remaining.days
                hours = remaining.seconds // 3600
                
                keyboard = [[InlineKeyboardButton("💳 ต่ออายุ / បន្តសមាជិកភាព (Extend)", callback_data="extend_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await target_message.reply_text(
                    f"ស្ថានភាពសមាជិកភាព៖ ដំណើរការធម្មតា ✅\nសល់ពេល៖ {days} ថ្ងៃ និង {hours} ម៉ោងទៀត\nផុតកំណត់នៅ៖ {expiry_str}",
                    reply_markup=reply_markup
                )
            else:
                keyboard = [[InlineKeyboardButton("💳 ទិញកញ្ចប់សមាជិកភាពថ្មី", callback_data="extend_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await target_message.reply_text(
                    f"សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ ❌\nសូមចុចប៊ូតុងខាងក្រោមដើម្បីបន្តសមាជិកភាព។",
                    reply_markup=reply_markup
                )
        else:
            await target_message.reply_text("អ្នកមិនទាន់ជាសមាជិកទេ។ សូមផ្ញើពាក្យ /start ដើម្បីជ្រើសរើសកញ្ចប់សមាជិកភាព។")
    except Exception as e:
        print(f"Error in status: {e}")

# 11. Extend Menu
async def extend_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
            [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
            [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
            [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់សម្រាប់បន្តសមាជិកភាព (Extend)៖", reply_markup=reply_markup)
    except Exception as e:
        print(f"Error in extend_menu_callback: {e}")

# Auto-Kick
def auto_kick_checker(application):
    while True:
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                now_dt = datetime.now(CAMBODIA_TZ)
                now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
                soon_str = (now_dt + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                
                cursor.execute('SELECT user_id FROM users WHERE expiry_date <= %s AND expiry_date > %s AND warned = 0 AND kicked = 0', (soon_str, now_str))
                warn_users = cursor.fetchall()
                
                for row in warn_users:
                    u_id = row[0]
                    try:
                        keyboard = [[InlineKeyboardButton("💳 បន្តកញ្ចប់ឥឡូវនេះ", callback_data="extend_menu")]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        application.bot.send_message(
                            chat_id=u_id,
                            text="⚠️ **សេចក្តីជូនដំណឹង:** សមាជិកភាពគ្រុបរបស់អ្នកនឹងត្រូវផុតកំណត់ក្នុងរយៈពេល ២៤ ម៉ោងខាងមុខនេះហើយ! សូមបន្តកញ្ចប់សមាជិកភាពរបស់អ្នកជាមុនសិន ដើម្បីកុំឱ្យ Bot ទាត់ចេញពីគ្រុបដោយស្វ័យប្រវត្តិ។",
                            reply_markup=reply_markup
                        )
                        cursor.execute('UPDATE users SET warned = 1 WHERE user_id = %s', (u_id,))
                        conn.commit()
                    except Exception as e:
                        print(f"Error sending warning to {u_id}: {e}")

                cursor.execute('SELECT user_id FROM users WHERE expiry_date < %s AND kicked = 0', (now_str,))
                expired_users = cursor.fetchall()
                
                for row in expired_users:
                    user_id = row[0]
                    try:
                        application.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                        application.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                        
                        keyboard = [[InlineKeyboardButton("💳 ទិញកញ្ចប់ និងចូលគ្រុបវិញ", callback_data="extend_menu")]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        application.bot.send_message(
                            chat_id=user_id, 
                            text="⏰ សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ! Bot បានទាត់អ្នកចេញពីគ្រុបដោយស្វ័យប្រវត្តិ。\n\n👉 សូមចុចប៊ូតុងខាងក្រោមដើម្បីបង់ប្រាក់ទិញកញ្ចប់សមាជិកភាពថ្មី។",
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        print(f"Error kicking user {user_id}: {e}")
                    
                    cursor.execute('UPDATE users SET kicked = 1 WHERE user_id = %s', (user_id,))
                    conn.commit()
                    
                cursor.close()
                conn.close()
        except Exception as e:
            print(f"Database error in auto_kick: {e}")
            
        time.sleep(60)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

if __name__ == "__main__":
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN environment variable is not set!")
        exit(1)
        
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin_members", admin_members))
    
    # Admin Panel Command
    application.add_handler(CommandHandler("admin", admin_panel_command))

    # Extended Commands
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("adddays", adddays_command))
    application.add_handler(CommandHandler("kickuser", kickuser_command))
    application.add_handler(CommandHandler("setqr", setqr_command))
    application.add_handler(CommandHandler("export", export_command))

    # Handlers
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_|ext_)"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|get_referral_link|user_)"))
    application.add_handler(CallbackQueryHandler(extend_menu_callback, pattern="^extend_menu$"))
    
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Subscription Bot with Safe Cloud PostgreSQL & Secure Anti-Fraud is starting...")
    application.run_polling()
