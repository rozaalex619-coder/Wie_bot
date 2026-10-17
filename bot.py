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
    return "Tourism & Subscription Bot with Safe Cloud PostgreSQL is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ ---
ADMIN_ID = 8980369344                      
GROUP_INVITE_LINK = "https://t.me/+1_JA7CSmMoYxMDg1"  
GROUP_CHAT_ID = -1004400009713            
# ---------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

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
user_tour_route = {}
user_last_photo_time = {}

# 2. បង្កើត Database Tables លើ Cloud PostgreSQL
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
            [InlineKeyboardButton("🗺 ជ្រើសរើសផ្លូវ និងកញ្ចប់ទេសចរណ៍", callback_data="tour_routes_menu")],
            [InlineKeyboardButton("📊 ពិនិត្យស្ថានភាពកាលវិភាគទេសចរណ៍", callback_data="user_check_status")],
            [InlineKeyboardButton("❓ របៀបទូទាត់ប្រាក់", callback_data="user_payment_help")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_text = (
            f"សួស្តី {user.first_name}!\n\n"
            f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធគ្រប់គ្រងកាលវិភាគ និងកញ្ចប់សេវាកម្មទេសចរណ៍។\n"
            f"សូមជ្រើសរើសមុខងារខាងក្រោម៖"
        )
        if update.callback_query:
            await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error in start command: {e}")

# 4. ម៉ឺនុយជ្រើសរើសផ្លូវ និងកញ្ចប់ទេសចរណ៍
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "tour_routes_menu":
            keyboard = [
                [InlineKeyboardButton("🛤 ផ្លូវទី ១ (កញ្ចប់ ៥ ថ្ងៃ)", callback_data="route_1_days_5")],
                [InlineKeyboardButton("🛤 ផ្លូវទី ២ (កញ្ចប់ ១០ ថ្ងៃ)", callback_data="route_2_days_10")],
                [InlineKeyboardButton("🛤 ផ្លូវទី ៣ (កញ្ចប់ ៣០ ថ្ងៃ)", callback_data="route_3_days_30")],
                [InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("🗺 **សូមជ្រើសរើសផ្លូវ និងកញ្ចប់ទេសចរណ៍របស់អ្នក៖**", reply_markup=reply_markup, parse_mode="Markdown")
            return

        elif data == "user_check_status":
            await status(update, context)
            return

        elif data == "user_payment_help":
            help_text = (
                "💳 **របៀបទូទាត់ប្រាក់សម្រាប់កញ្ចប់ទេសចរណ៍៖**\n\n"
                "1. ជ្រើសរើសផ្លូវ និងកញ្ចប់ចំនួនថ្ងៃដែលចង់បាន\n"
                "2. ស្កែន QR Code ដើម្បីទូទាត់ប្រាក់តាមតម្លៃកញ្ចប់\n"
                "3. ថតរូបវិក្កយបត្រ (Slip) ផ្ញើចូលមកកាន់ Bot នេះ\n"
                "4. Admin នឹងផ្ទៀងផ្ទាត់ និងចាប់ផ្តើមកាលវិភាគដំណើរការជូនភ្លាមៗ!"
            )
            keyboard = [[InlineKeyboardButton("⬅️ ត្រឡប់ទៅម៉ឺនុយដើម", callback_data="user_main_menu")]]
            await query.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        elif data == "user_main_menu":
            await start(update, context)
            return

        if data.startswith("route_"):
            parts = data.split("_")
            route_num = parts[1]
            days = int(parts[3])
            
            user_tour_route[user_id] = f"ផ្លូវទី {route_num}"
            user_selected_package[user_id] = days
            
            prices = {5: "១០ ដុល្លារ", 10: "១៨ ដុល្លារ", 30: "៤៥ ដុល្លារ"}
            price_text = prices.get(days, "ទាក់ទង Admin")
            
            caption = (
                f"🗺 អ្នកបានជ្រើសរើស៖ **ផ្លូវទី {route_num}** (រយៈពេល: **{days} ថ្ងៃ**)\n"
                f"💵 តម្លៃសេវាកម្ម៖ **{price_text}**\n\n"
                f"💳 ១. សូម Scan QR Code ខាងលើដើម្បីទូទាត់ប្រាក់។\n"
                f"📸 ២. បន្ទាប់ពីបង់ប្រាក់រួច សូមថតរូបវិក្កយបត្រ (Screenshot/Slip) ហើយផ្ញើរូបភាពនោះចូលមកកាន់ Bot នេះផ្ទាល់។\n\n"
                f"🤖 (ប្រព័ន្ធនឹងចាប់ផ្តើមកាលវិភាគថ្ងៃ និងម៉ោងដំណើរការជូនបន្ទាប់ពី Admin អនុម័ត!)"
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

# 5. ទទួលរូបភាពវិក្កយបត្រទេសចរណ៍
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name
        
        if user_id not in user_selected_package or user_id not in user_tour_route:
            keyboard = [[InlineKeyboardButton("🗺 ជ្រើសរើសផ្លូវ និងកញ្ចប់ទេសចរណ៍", callback_data="tour_routes_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "⚠️ **សូមជ្រើសរើសផ្លូវ និងកញ្ចប់សេវាកម្មជាមុនសិន!**",
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
                    await update.message.reply_text("❌ **វិក្កយបត្រ (Slip) នេះត្រូវបានប្រើប្រាស់រួចរាល់ហើយ!**")
                    return
            except Exception as e:
                print(f"Error checking receipt: {e}")
            
        days = user_selected_package.get(user_id)
        route_name = user_tour_route.get(user_id)
        package_desc = f"{route_name} - {days} ថ្ងៃ"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ យល់ព្រម (Approve)", callback_data=f"approve_{user_id}_{days}"),
                InlineKeyboardButton("❌ បដិសេធ (Reject)", callback_data=f"reject_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        admin_caption = (
            f"🗺 **មានការស្នើសុំកញ្ចប់ទេសចរណ៍ថ្មី!**\n\n"
            f"👤 ឈ្មោះ: {username}\n"
            f"🆔 User ID: `{user_id}`\n"
            f"📍 ផ្លូវ និងកញ្ចប់: **{package_desc}**\n"
            f"🖼 Photo ID: `{photo_file}`\n\n"
            f"⏳ (សូម Admin ពិនិត្យ និងចុចអនុម័ត ដើម្បីចាប់ផ្តើមកាលវិភាគថ្ងៃ/ម៉ោងជូនទេសចរ)"
        )
        
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file,
                caption=admin_caption,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await update.message.reply_text("📥 វិក្កយបត្ររបស់អ្នកត្រូវបានបញ្ជូនជូន Admin រួចរាល់ហើយ! សូមរង់ចាំការផ្ទៀងផ្ទាត់កាលវិភាគដំណើរ...")
        except Exception as e:
            await update.message.reply_text("មានបញ្ហាក្នុងការផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")
    except Exception as e:
        print(f"Error in handle_photo: {e}")

# 6. ប្រព័ន្ធ Admin អនុម័ត និងចាប់ផ្តើមកាលវិភាគថ្ងៃ/ម៉ោង
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
            
            user_display_name = "Tourist"
            route_info = "ផ្លូវទេសចរណ៍"
            if query.message.caption:
                for line in query.message.caption.split("\n"):
                    if "👤 ឈ្មោះ:" in line:
                        user_display_name = line.replace("👤 ឈ្មោះ:", "").strip()
                    if "📍 ផ្លូវ និងកញ្ចប់:" in line:
                        route_info = line.replace("📍 ផ្លូវ និងកញ្ចប់:", "").strip()

            start_dt = datetime.now(CAMBODIA_TZ)
            expiry_dt = start_dt + timedelta(days=days)
            
            start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
            expiry_str = expiry_dt.strftime('%Y-%m-%d %H:%M:%S')
            package_desc = f"{route_info} ({days}ថ្ងៃ ចាប់ផ្តើម៖ {start_str})"
            
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
                    ''', (user_id, user_display_name, expiry_str, package_desc))
                        
                    conn.commit()
                    cursor.close()
                    conn.close()
                except Exception as e:
                    print(f"Error approving tourist in DB: {e}")
            
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
                    f"🎉 អបអរសាទរ! កាលវិភាគដំណើរទេសចរណ៍របស់អ្នកត្រូវបានចាប់ផ្តើមដោយជោគជ័យ។\n\n"
                    f"🗺 កញ្ចប់៖ **{route_info}**\n"
                    f"🕒 ពេលចាប់ផ្តើម៖ **{start_str}**\n"
                    f"📅 ពេលបញ្ចប់៖ **{expiry_str}**\n\n"
                    f"🔗 តំណភ្ជាប់ចូលគ្រុបទេសចរណ៍:\n{custom_link}\n\n"
                    f"ពិនិត្យម៉ោង និងថ្ងៃនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
                )
                await context.bot.send_message(chat_id=user_id, text=success_message)
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ [បានអនុម័តកាលវិភាគទេសចរណ៍ {days} ថ្ងៃ និងផ្ញើ Link ជូនរួចរាល់]")
            except Exception as e:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ អនុម័តរួច ប៉ុន្តែមានបញ្ហាក្នុងការផ្ញើសារទៅ User")
                
        elif data.startswith("reject_"):
            user_id = int(data.split("_")[1])
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ សូមអភ័យទោស វិក្កយបត្រសេវាកម្មទេសចរណ៍របស់អ្នកមិនត្រឹមត្រូវទេ។")
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")
            except Exception:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")
    except Exception as e:
        print(f"Error in button_callback: {e}")

# --- Admin Panel Commands ---
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 ស្ថិតិទេសចរ (Stats)", callback_data="admin_stats")],
            [InlineKeyboardButton("📋 បញ្ជីទេសចរទាំងអស់", callback_data="admin_members_list")],
            [InlineKeyboardButton("📊 Export ទិន្នន័យ (CSV)", callback_data="admin_export_csv")],
            [InlineKeyboardButton("ℹ️ វិធីប្រើប្រាស់ Command", callback_data="admin_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("👑 **Tourism Admin Control Panel**\n\nសូមជ្រើសរើសមុខងារខាងក្រោម៖", reply_markup=reply_markup, parse_mode="Markdown")
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
                "• `/broadcast <សារ>` : ផ្ញើសារទៅទេសចរទាំងអស់\n"
                "• `/adddays <user_id> <ថ្ងៃ>` : បន្ថែមថ្ងៃទេសចរណ៍\n"
                "• `/kickuser <user_id>` : ដកសិទ្ធិទេសចរចេញពីគ្រុប\n"
                "• `/setqr` : Reply រូបភាព QR ដើម្បីប្តូរ QR ថ្មី"
            )
            await query.message.reply_text(help_txt, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in admin_panel_callback: {e}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        text_to_broadcast = " ".join(context.args)
        if not text_to_broadcast:
            await update.message.reply_text("⚠️ សូមសរសេរសារដែលចង់ Broadcast ផង។", parse_mode="Markdown")
            return

        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        all_users = cur.fetchall()
        cur.close()
        conn.close()

        success_count = 0
        for row in all_users:
            try:
                await context.bot.send_message(chat_id=row[0], text=f"📢 **សេចក្តីប្រកាសជូនដំណឹងដល់ទេសចរ៖**\n\n{text_to_broadcast}", parse_mode="Markdown")
                success_count += 1
                time.sleep(0.1)
            except Exception:
                pass

        await update.message.reply_text(f"✅ Broadcast បានជោគជ័យដល់ទេសចរចំនួន {success_count} នាក់!")
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
        target_user_id, add_d = int(args[0]), int(args[1])

        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT expiry_date, package_info FROM users WHERE user_id = %s", (target_user_id,))
        res = cur.fetchone()
        now_dt = datetime.now(CAMBODIA_TZ)
        if res and res[0]:
            cur_exp = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
            cur_exp = CAMBODIA_TZ.localize(cur_exp) if cur_exp.tzinfo is None else cur_exp
            base = cur_exp if cur_exp > now_dt else now_dt
            old_pkg = res[1] or "Tour"
        else:
            base = now_dt
            old_pkg = "Tour"

        new_exp = (base + timedelta(days=add_d)).strftime('%Y-%m-%d %H:%M:%S')
        new_pkg = f"{old_pkg} + បន្ថែម {add_d}ថ្ងៃ"

        cur.execute("INSERT INTO users (user_id, username, expiry_date, kicked, package_info) VALUES (%s, %s, %s, 0, %s) ON CONFLICT (user_id) DO UPDATE SET expiry_date = %s, kicked = 0, package_info = %s",
                    (target_user_id, "Tourist", new_exp, new_pkg, new_exp, new_pkg))
        conn.commit()
        cur.close()
        conn.close()

        await update.message.reply_text(f"✅ បានបន្ថែមរយៈពេលទេសចរណ៍ចំនួន {add_d} ថ្ងៃ ដល់ ID: `{target_user_id}` ជោគជ័យ!", parse_mode="Markdown")
    except Exception as e:
        print(f"Error in adddays_command: {e}")

async def kickuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        args = context.args
        if not args:
            return
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
        await update.message.reply_text(f"✅ បានដកសិទ្ធិទេសចរ ID `{target_user_id}` ចេញពីគ្រុប។", parse_mode="Markdown")
    except Exception as e:
        print(f"Error in kickuser_command: {e}")

async def setqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        reply = update.message.reply_to_message
        if not reply or not reply.photo:
            await update.message.reply_text("⚠️ សូម Reply រូបភាព QR Code ជាមួយពាក្យ `/setqr`", parse_mode="Markdown")
            return
        new_photo_file_id = reply.photo[-1].file_id
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO bot_settings (key, value) VALUES ('custom_qr_file_id', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_photo_file_id, new_photo_file_id))
            conn.commit()
            cur.close()
            conn.close()
            await update.message.reply_text("✅ បានប្តូរ QR Code ថ្មីសម្រាប់ទូទាត់ប្រាក់ទេសចរណ៍!")
    except Exception as e:
        print(f"Error in setqr_command: {e}")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, expiry_date, kicked, warned, package_info FROM users")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["User ID", "Username", "Expiry Date", "Kicked", "Warned", "Package Info"])
        for r in rows:
            writer.writerow(r)
        
        output.seek(0)
        bio = io.BytesIO(output.getvalue().encode('utf-8'))
        bio.name = "tourists_data.csv"
        
        target_message = update.callback_query.message if update.callback_query else update.message
        await target_message.reply_document(document=bio, caption="📊 បញ្ជីទិន្នន័យទេសចរទាំងអស់ (CSV Export)")
    except Exception as e:
        print(f"Error in export_command: {e}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id != ADMIN_ID:
            return
        active_tourists = 0
        expired_tourists = 0
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT expiry_date, kicked FROM users")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            
            now_dt = datetime.now(CAMBODIA_TZ)
            for row in rows:
                exp_str, kicked = row[0], row[1]
                if kicked == 1:
                    expired_tourists += 1
                else:
                    try:
                        exp_date = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                        exp_date = CAMBODIA_TZ.localize(exp_date) if exp_date.tzinfo is None else exp_date
                        if now_dt < exp_date:
                            active_tourists += 1
                        else:
                            expired_tourists += 1
                    except Exception:
                        expired_tourists += 1
        
        stats_text = (
            f"📊 **ស្ថិតិកាលវិភាគទេសចរណ៍ (Admin Dashboard)**\n\n"
            f"🟢 ទេសចរណ៍សកម្ម (Active): **{active_tourists} នាក់**\n"
            f"🔴 ទេសចរណ៍ផុតកាលវិភាគ (Expired): **{expired_tourists} នាក់**"
        )
        target_message = update.callback_query.message if update.callback_query else update.message
        await target_message.reply_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in stats: {e}")

# Admin មើលបញ្ជីទេសចរលម្អិតថ្ងៃ ម៉ោង
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
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, username, expiry_date, kicked, package_info FROM users')
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        
        target_message = update.callback_query.message if update.callback_query else update.message
        if not rows:
            await target_message.reply_text("📭 មិនទាន់មានទិន្នន័យទេសចរក្នុងប្រព័ន្ធទេ។")
            return
            
        msg = "📋 **បញ្ជីឈ្មោះ កាលវិភាគ ថ្ងៃខែ និងម៉ោងនៅសល់របស់ទេសចរ៖**\n\n"
        now_dt = datetime.now(CAMBODIA_TZ)
        
        for row in rows:
            u_id, uname, exp_str, kicked, package_info = row
            name = uname if uname else "មិនមានឈ្មោះ"
            pkg_desc = package_info if package_info else "មិនមានកញ្ចប់"
            
            if kicked == 1:
                status_text = f"🔴 បានបញ្ចប់កាលវិភាគ | កាលពី៖ {exp_str}"
            else:
                try:
                    exp_date = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                    exp_date = CAMBODIA_TZ.localize(exp_date) if exp_date.tzinfo is None else exp_date
                    if now_dt < exp_date:
                        rem = exp_date - now_dt
                        days = rem.days
                        hours = rem.seconds // 3600
                        minutes = (rem.seconds % 3600) // 60
                        status_text = (
                            f"🟢 **ដំណើរការសកម្ម**\n"
                            f"⏳ **នៅសល់៖** `{days}` ថ្ងៃ `{hours}` ម៉ោង `{minutes}` នាទី\n"
                            f"📅 **ផុតកំណត់ម៉ោង៖** `{exp_str}`"
                        )
                    else:
                        status_text = f"🔴 **ផុតកាលវិភាគហើយ**\n📅 **កាលបរិច្ឆេទផុត៖** `{exp_str}`"
                except Exception:
                    status_text = f"📅 **ផុតកំណត់ថ្ងៃ៖** `{exp_str}`"
                    
            msg += (
                f"👤 **ឈ្មោះ:** {name}\n"
                f"🆔 **User ID:** `{u_id}`\n"
                f"🗺 **កញ្ចប់/ផ្លូវ:** {pkg_desc}\n"
                f"{status_text}\n"
                f"----------------------------------\n"
            )
            
        if len(msg) > 4000:
            for x in range(0, len(msg), 4000):
                await target_message.reply_text(msg[x:x+4000], parse_mode="Markdown")
        else:
            await target_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in admin_members: {e}")

# 10. status សម្រាប់ទេសចរពិនិត្យកាលវិភាគខ្លួនឯង
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        result = None
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute('SELECT expiry_date, package_info FROM users WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
        
        target_message = update.callback_query.message if update.callback_query else update.message
        
        if result:
            expiry_str = result[0]
            pkg_info = result[1]
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
            expiry_date = CAMBODIA_TZ.localize(expiry_date) if expiry_date.tzinfo is None else expiry_date
            now_dt = datetime.now(CAMBODIA_TZ)

            if now_dt < expiry_date:
                remaining = expiry_date - now_dt
                days = remaining.days
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                
                keyboard = [[InlineKeyboardButton("🗺 បន្តកញ្ចប់ផ្លូវទេសចរណ៍", callback_data="tour_routes_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await target_message.reply_text(
                    f"🗺 **កាលវិភាគដំណើរទេសចរណ៍របស់អ្នក៖**\n"
                    f"📦 កញ្ចប់៖ {pkg_info}\n"
                    f"✅ ស្ថានភាព៖ កំពុងដំណើរការធម្មតា\n"
                    f"⏳ នៅសល់ពេល៖ {days} ថ្ងៃ {hours} ម៉ោង {minutes} នាទីទៀត\n"
                    f"📅 កាលបរិច្ឆេទបញ្ចប់៖ {expiry_str}",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                keyboard = [[InlineKeyboardButton("🗺 កក់កញ្ចប់ផ្លូវទេសចរណ៍ថ្មី", callback_data="tour_routes_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await target_message.reply_text(
                    f"❌ **កាលវិភាគទេសចរណ៍របស់អ្នកបានផុតកំណត់ហើយ!**\nសូមជ្រើសរើសផ្លូវថ្មីនៅខាងក្រោម៖",
                    reply_markup=reply_markup
                )
        else:
            await target_message.reply_text("អ្នកមិនទាន់មានកាលវិភាគទេសចរណ៍ទេ។ សូមប្រើពាក្យបញ្ជា /start ដើម្បីជ្រើសរើស។")
    except Exception as e:
        print(f"Error in status: {e}")

async def extend_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("🛤 ផ្លូវទី ១ (៥ ថ្ងៃ)", callback_data="route_1_days_5")],
            [InlineKeyboardButton("🛤 ផ្លូវទី ២ (១០ ថ្ងៃ)", callback_data="route_2_days_10")],
            [InlineKeyboardButton("🛤 ផ្លូវទី ៣ (៣០ ថ្ងៃ)", callback_data="route_3_days_30")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🗺 សូមជ្រើសរើសផ្លូវទេសចរណ៍បន្ថែម៖", reply_markup=reply_markup)
    except Exception as e:
        print(f"Error in extend_menu_callback: {e}")

# Auto-Kick / Auto-Expire Worker
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
                        application.bot.send_message(
                            chat_id=u_id,
                            text="⚠️ **សេចក្តីជូនដំណឹង:** កាលវិភាគដំណើរទេសចរណ៍របស់អ្នកនឹងត្រូវផុតកំណត់ក្នុងរយៈពេល ២៤ ម៉ោងខាងមុខនេះហើយ!"
                        )
                        cursor.execute('UPDATE users SET warned = 1 WHERE user_id = %s', (u_id,))
                        conn.commit()
                    except Exception as e:
                        print(f"Error warning tourist {u_id}: {e}")

                cursor.execute('SELECT user_id FROM users WHERE expiry_date < %s AND kicked = 0', (now_str,))
                expired_users = cursor.fetchall()
                for row in expired_users:
                    user_id = row[0]
                    try:
                        application.bot.ban_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                        application.bot.unban_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                        application.bot.send_message(
                            chat_id=user_id, 
                            text="⏰ កាលវិភាគទេសចរណ៍របស់អ្នកបានផុតកំណត់ហើយ! ប្រព័ន្ធបានដកសិទ្ធិចេញពីគ្រុបដោយស្វ័យប្រវត្តិ។"
                        )
                    except Exception as e:
                        print(f"Error kicking tourist {user_id}: {e}")
                    
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
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_)"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(route_|user_|pkg_)"))
    application.add_handler(CallbackQueryHandler(extend_menu_callback, pattern="^extend_menu$"))
    
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Tourism & Subscription Bot is starting...")
    application.run_polling()
