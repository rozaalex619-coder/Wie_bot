import threading
import psycopg2
import time
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ChatJoinRequestHandler, 
    ContextTypes, 
    filters
)
from flask import Flask

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with Cloud PostgreSQL & Join Request Handler is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ ---
ADMIN_ID = 8980369344                      
GROUP_INVITE_LINK = "https://t.me/+2JquQ2gZnQE4OGU1"  # Link សម្រាប់ Admin ប្រើប្រាស់ផ្ទាល់
GROUP_CHAT_ID = -1004404523665            # ID របស់ Channel / Group របស់បង
# ---------------------------------------------

# ទាញយក Database URL ពី Render Environment Variable
DATABASE_URL = os.environ.get("DATABASE_URL")

# មុខងារតភ្ជាប់ Cloud Database (PostgreSQL) ជាមួយ Error Handling
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

# រក្សាទុកកញ្ចប់ដែល User បានជ្រើសរើសបណ្តោះអាសន្ន
user_selected_package = {}

# 2. បង្កើត Database Tables លើ Cloud PostgreSQL
def init_db():
    conn = get_db_connection()
    if conn is None:
        print("⚠️ Skipping init_db because database connection failed. Bot will retry on request.")
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
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

init_db()

# 3. ពាក្យបញ្ជា /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            
            if not result:
                default_expiry = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
                
                if referrer_id:
                    cursor.execute('SELECT expiry_date FROM users WHERE user_id = %s', (referrer_id,))
                    ref_res = cursor.fetchone()
                    if ref_res:
                        try:
                            ref_exp = datetime.strptime(ref_res[0], '%Y-%m-%d %H:%M:%S')
                            now = datetime.now()
                            base_time = ref_exp if ref_exp > now else now
                            new_ref_exp = (base_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                            cursor.execute('UPDATE users SET expiry_date = %s WHERE user_id = %s', (new_ref_exp, referrer_id))
                            await context.bot.send_message(chat_id=referrer_id, text="🎁 មានមិត្តភក្តិបានចូលប្រើប្រាស់ Bot តាមរយៈ Link របស់អ្នក! អ្នកទទួលបានការថែមជូន **១ម៉ោង** ដោយស្វ័យប្រវត្តិ។")
                        except Exception as e:
                            print(f"Error giving referral bonus: {e}")

                cursor.execute('''
                    INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info, referral_code, referred_by)
                    VALUES (%s, %s, %s, 0, 0, 'មិនទាន់ជ្រើសរើសកញ្ចប់', %s, %s)
                ''', (user_id, username, default_expiry, f"ref_{user_id}", referrer_id))
                conn.commit()
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error in start query: {e}")
    
    keyboard = [
        [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
        [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
        [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
        [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")],
        [InlineKeyboardButton("👥 យក Link ណែនាំមិត្តភក្តិ (ថែម ១ម៉ោង)", callback_data="get_referral_link")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"សួស្តី {user.first_name}!\n\n"
        f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសមាជិកភាពគ្រុបរបស់យើង។ "
        f"សូមជ្រើសរើសកញ្ចប់សមាជិកភាពនៅខាងក្រោម៖"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# 4. ដោះស្រាយពេលអតិថិជនចុច Package ឬ Referral Link
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "get_referral_link":
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
            f"🤖 (ប្រព័ន្ធនឹងត្រួតពិនិត្យវិក្កយបត្រដោយស្វ័យប្រវត្តិក្នុងរយៈពេល ២-៣ នាទី ឬ Admin នឹងអនុម័តផ្ទាល់!)"
        )
        
        try:
            await query.message.reply_photo(photo=open('qr.jpg', 'rb'), caption=caption, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(f"{caption}\n\n(⚠️ រកមិនឃើញឯកសារ qr.jpg ក្នុង GitHub ទេ)")

# 5. ទទួលរូបភាពវិក្កយបត្រ និង Background Auto-Verify Task
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    photo_file = update.message.photo[-1].file_id
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM used_receipts WHERE photo_file_id = %s', (photo_file,))
            receipt_check = cursor.fetchone()
            cursor.close()
            conn.close()
            if receipt_check:
                await update.message.reply_text("❌ វិក្កយបត្រ (Screenshot) នេះត្រូវបានប្រើប្រាស់រួចរាល់ហើយ! សូមកុំយកវិក្កយបត្ររបស់អ្នកដទៃមកផ្ញើម្តងទៀត។")
                return
        except Exception as e:
            print(f"Error checking receipt: {e}")
        
    days = user_selected_package.get(user_id, 30)
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
        f"🔔 **មានអតិថិជនស្នើសុំចូលសមាជិក!**\n\n"
        f"👤 ឈ្មោះ: {username}\n"
        f"🆔 User ID: `{user_id}`\n"
        f"ជម្រើសកញ្ចប់: **{package_desc}**\n"
        f"🖼 Photo ID: `{photo_file}`\n\n"
        f"⏳ (Bot កំពុងរង់ចាំ Admin ពិនិត្យ ២ នាទី បើមិនទាន់ឆ្លើយតប Bot នឹង Auto-Approve ឱ្យដោយស្វ័យប្រវត្តិ)"
    )
    
    sent_message = None
    try:
        sent_message = await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file,
            caption=admin_caption,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        await update.message.reply_text("📥 វិក្កយបត្ររបស់អ្នកត្រូវបានបញ្ជូនហើយ! Bot កំពុងផ្ទៀងផ្ទាត់ដោយស្វ័យប្រវត្តិក្នុងរយៈពេលបន្តិចទៀតនេះ...")
    except Exception as e:
        await update.message.reply_text("មានបញ្ហាក្នុងការផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")
        return

    def auto_verify_worker(app_context, target_user_id, target_days, target_package_desc, msg_chat_id, msg_id, photo_id):
        time.sleep(150)
        try:
            c = get_db_connection()
            if not c:
                return
            cur = c.cursor()
            cur.execute('SELECT user_id FROM used_receipts WHERE photo_file_id = %s', (photo_id,))
            if cur.fetchone():
                cur.close()
                c.close()
                return
            
            expiry = (datetime.now() + timedelta(days=target_days)).strftime('%Y-%m-%d %H:%M:%S')
            cur.execute('INSERT INTO used_receipts (photo_file_id, user_id, used_at) VALUES (%s, %s, %s) ON CONFLICT (photo_file_id) DO NOTHING', 
                           (photo_id, target_user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            cur.execute('''
                UPDATE users SET expiry_date = %s, kicked = 0, warned = 0, package_info = %s WHERE user_id = %s
            ''', (expiry, target_package_desc, target_user_id))
            c.commit()
            cur.close()
            c.close()

            # បង្កើត Single-Use Join Request Link ផ្ញើជូនអតិថិជនពេល Auto-Verify
            async def send_auto_link():
                try:
                    invite_link = await app_context.bot.create_chat_invite_link(
                        chat_id=GROUP_CHAT_ID,
                        creates_join_request=True,
                        member_limit=1
                    )
                    custom_link = invite_link.invite_link
                except Exception:
                    custom_link = GROUP_INVITE_LINK

                success_message = (
                    f"🎉 អបអរសាទរ! វិក្កយបត្ររបស់អ្នកត្រូវបានផ្ទៀងផ្ទាត់ជោគជ័យដោយស្វ័យប្រវត្តិ (Auto-Verified)។\n\n"
                    f"🔗 តំណភ្ជាប់ចូលគ្រុប (Group Link):\n{custom_link}\n\n"
                    f"📅 សមាជិកភាពមានសុពលភាព {target_days} ថ្ងៃ ដល់ថ្ងៃ៖ {expiry}\n"
                    f"ពិនិត្យថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
                )
                await app_context.bot.send_message(chat_id=target_user_id, text=success_message)

            import asyncio
            asyncio.run_coroutine_threadsafe(send_auto_link(), app_context.bot.loop)
            
            try:
                app_context.bot.edit_message_caption(
                    chat_id=msg_chat_id,
                    message_id=msg_id,
                    caption=f"🔔 [Auto-Approved ស្វ័យប្រវត្តិដោយ Bot ក្រោយ ២នាទី]\n\n📅 កញ្ចប់: {target_package_desc}"
                )
            except Exception:
                pass
        except Exception as e:
            print(f"Error in auto_verify_worker: {e}")

    threading.Thread(target=auto_verify_worker, args=(context, user_id, days, package_desc, ADMIN_ID, sent_message.message_id, photo_file), daemon=True).start()

# 6. ប្រព័ន្ធ Admin ចុច Approve, Reject ឬ Extend Days
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
        price_text = prices.get(days, "មិនស្គាល់តម្លៃ")
        package_desc = f"{days} ថ្ងៃ - {price_text}"
        
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                if query.message.photo:
                    photo_file = query.message.photo[-1].file_id if hasattr(query.message, 'photo') else None
                    if photo_file:
                        cursor.execute('INSERT INTO used_receipts (photo_file_id, user_id, used_at) VALUES (%s, %s, %s) ON CONFLICT (photo_file_id) DO NOTHING', 
                                       (photo_file, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                cursor.execute('''
                    UPDATE users SET expiry_date = %s, kicked = 0, warned = 0, package_info = %s WHERE user_id = %s
                ''', (expiry, package_desc, user_id))
                
                if cursor.rowcount == 0:
                    cursor.execute('''
                        INSERT INTO users (user_id, username, expiry_date, kicked, warned, package_info) 
                        VALUES (%s, %s, %s, %s, 0, %s)
                    ''', (user_id, "Customer", expiry, 0, package_desc))
                    
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error approving user: {e}")
        
        # បង្កើត Single-Use Join Request Link ផ្ញើជូនអតិថិជនពេល Admin ចុច Approve
        try:
            invite_link = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                creates_join_request=True,
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
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ [បានអនុម័តជោគជ័យ {days} ថ្ងៃ និងផ្ញើ Link ជូនរួចរាល់]")
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
        new_expiry = (datetime.now() + timedelta(days=ext_days)).strftime('%Y-%m-%d %H:%M:%S')
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute('SELECT expiry_date, package_info FROM users WHERE user_id = %s', (user_id,))
                res = cursor.fetchone()
                
                now = datetime.now()
                if res and res[0]:
                    current_expiry = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
                    base_time = current_expiry if current_expiry > now else now
                    old_pkg = res[1] if res[1] else "មិនមាន"
                else:
                    base_time = now
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

# 7. មុខងារទទួល Join Request ពេលអតិថិជនចុច Link (លោតមក Admin ផ្ទាល់)
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    user = req.from_user
    chat = req.chat
    
    # បង្កើតប៊ូតុង Approve / Decline ឱ្យ Admin ចុចផ្ទាល់
    keyboard = [
        [
            InlineKeyboardButton("✅ យល់ព្រមចូល (Approve)", callback_data=f"accept_req_{chat.id}_{user.id}"),
            InlineKeyboardButton("❌ បដិសេធ (Decline)", callback_data=f"decline_req_{chat.id}_{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = (
        f"📩 **មានអតិថិជនស្នើសុំចូល Channel/Group!**\n\n"
        f"👤 ឈ្មោះ: {user.first_name} (@{user.username or 'ไม่มี username'})\n"
        f"🆔 User ID: `{user.id}`\n"
        f"📍 គ្រុប/ឆានែល: {chat.title}\n\n"
        f"សូមចុចសម្រេចចិត្តខាងក្រោម៖"
    )
    
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending join request to admin: {e}")

# 8. ដោះស្រាយពេល Admin ចុច Approve/Decline លើ Join Request តាមប៊ូតុង
async def join_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ អ្នកមិនមានសិទ្ធិទេ!", show_alert=True)
        return
        
    await query.answer()
    data = query.data
    parts = data.split("_")
    action = parts[0] # accept ឬ decline
    chat_id = int(parts[2])
    target_user_id = int(parts[3])
    
    try:
        if action == "accept":
            await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=target_user_id)
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ [បានយល់ព្រមឱ្យចូល Channel ជោគជ័យ]")
            await context.bot.send_message(chat_id=target_user_id, text="🎉 សំណើសុំចូល Channel របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ! សូមរីករាយកម្សាន្ត។")
        else:
            await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=target_user_id)
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ [បានបដិសេធសំណើ]")
            await context.bot.send_message(chat_id=target_user_id, text="❌ សំណើសុំចូល Channel របស់អ្នកត្រូវបានបដិសេធ។")
    except Exception as e:
        await query.edit_message_text(text=f"{query.message.text}\n\n⚠️ មានបញ្ហាក្នុងការដំណើរការសំណើ៖ {e}")

# 9. ពាក្យបញ្ជា /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text(f"❌ អ្នកមិនមែនជា Admin ទេ! (User ID របស់អ្នកគឺ: `{user_id}`)", parse_mode="Markdown")
        return
        
    active_users = expired_users = 0
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date >= TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS') AND kicked = 0")
            active_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date < TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS')")
            expired_users = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error fetching stats: {e}")
    
    stats_text = (
        f"📊 **ស្ថិតិប្រព័ន្ធសមាជិកភាព (Admin Dashboard)**\n\n"
        f"🟢 សមាជិកសកម្ម (Active): **{active_users} នាក់**\n"
        f"🔴 សមាជិកអស់សុពលភាព (Expired): **{expired_users} នាក់**"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown")

# Admin មើលបញ្ជីសមាជិក
async def admin_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text(f"❌ អ្នកមិនមែនជា Admin ទេ! (User ID របស់អ្នកគឺ: `{user_id}`)", parse_mode="Markdown")
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
    
    if not rows:
        await update.message.reply_text("📭 មិនទាន់មានទិន្នន័យសមាជិកនៅក្នុងប្រព័ន្ធទេ។")
        return
        
    msg = "📋 **បញ្ជីឈ្មោះ កញ្ចប់ តម្លៃ និងថ្ងៃផុតកំណត់សមាជិកទាំងអស់៖**\n\n"
    now = datetime.now()
    
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
                if now < exp_date:
                    rem = exp_date - now
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
            await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

# 10. ពាក្យបញ្ជា /status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    if result:
        expiry_str = result[0]
        expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
        if datetime.now() < expiry_date:
            remaining = expiry_date - datetime.now()
            days = remaining.days
            hours = remaining.seconds // 3600
            
            keyboard = [[InlineKeyboardButton("💳 បន្ត / បន្តសមាជិកភាព (Extend)", callback_data="extend_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"ស្ថានភាពសមាជិកភាព៖ ដំណើរការធម្មតា ✅\nសល់ពេល៖ {days} ថ្ងៃ និង {hours} ម៉ោងទៀត\nផុតកំណត់នៅ៖ {expiry_str}",
                reply_markup=reply_markup
            )
        else:
            keyboard = [[InlineKeyboardButton("💳 ទិញកញ្ចប់សមាជិកភាពใหม่", callback_data="extend_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ ❌\nសូមចុចប៊ូតុងខាងក្រោមដើម្បីបន្តសមាជិកភាព។",
                reply_markup=reply_markup
            )
    else:
        await update.message.reply_text("អ្នកមិនទាន់ជាសមាជិកទេ។ សូមផ្ញើពាក្យ /start ដើម្បីជ្រើសរើសកញ្ចប់សមាជិកភាព។")

# 11. ដោះស្រាយពេល User ចុចប៊ូតុងបន្ត (Extend Menu)
async def extend_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
        [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
        [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
        [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("📦 សូមជ្រើសរើសកញ្ចប់សម្រាប់សេវាកម្ម (Extend)៖", reply_markup=reply_markup)

# Auto-Kick Worker & Warning Check
def auto_kick_checker(application):
    while True:
        try:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                soon_str = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('SELECT user_id FROM users WHERE expiry_date <= %s AND expiry_date > %s AND warned = 0 AND kicked = 0', (soon_str, now_str))
                warn_users = cursor.fetchall()
                
                for row in warn_users:
                    u_id = row[0]
                    try:
                        keyboard = [[InlineKeyboardButton("💳 បន្ត / បន្តកញ្ចប់ឥឡូវនេះ", callback_data="extend_menu")]]
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
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin_members", admin_members))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_|ext_)"))
    application.add_handler(CallbackQueryHandler(join_request_callback, pattern="^(accept_req_|decline_req_)"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|get_referral_link)"))
    application.add_handler(CallbackQueryHandler(extend_menu_callback, pattern="^extend_menu$"))
    
    # Handler សម្រាប់ចាប់យករាល់ពេលមានអតិថិជនចុច Request ចូល Channel
    application.add_handler(ChatJoinRequestHandler(join_request_handler))
    
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Subscription Bot with Cloud PostgreSQL is starting...")
    application.run_polling()
