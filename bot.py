import threading
import psycopg2
import time
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with Cloud PostgreSQL & Free Trial is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ ---
ADMIN_ID = 8980369344                      
GROUP_INVITE_LINK = "https://t.me/+2JquQ2gZnQE4OGU1"  
GROUP_CHAT_ID = -1001234567890            
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
                free_claimed INTEGER DEFAULT 0,
                warned INTEGER DEFAULT 0,
                package_info TEXT DEFAULT 'មិនមាន'
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
    
    conn = get_db_connection()
    result = None
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT free_claimed, expiry_date FROM users WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                default_expiry = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('''
                    INSERT INTO users (user_id, username, expiry_date, kicked, free_claimed, warned, package_info)
                    VALUES (%s, %s, %s, 0, 0, 0, 'មិនទាន់ជ្រើសរើសកញ្ចប់')
                ''', (user_id, username, default_expiry))
                conn.commit()
            
            cursor.execute('SELECT free_claimed FROM users WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error in start query: {e}")
    
    keyboard = []
    if not result or result[0] == 0:
        keyboard.append([InlineKeyboardButton("🎁 សាកល្បងប្រើប្រាស់បានចំនួន១ ថ្ងៃ (Free Trial)", callback_data="claim_free")])
    
    keyboard.extend([
        [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
        [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
        [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
        [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"សួស្តី {user.first_name}!\n\n"
        f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធទិញសមាជិកភាពគ្រុបរបស់យើង។ "
        f"អ្នកអាចជ្រើសរើសកញ្ចប់សមាជិកភាព ឬសាកល្បងប្រើប្រាស់នៅខាងក្រោម៖"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# 4. ដោះស្រាយពេលអតិថិជនចុចយក Free Trial ឬកញ្ចប់បង់ប្រាក់
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "claim_free":
        conn = get_db_connection()
        if not conn:
            await query.message.reply_text("⚠️ មានបញ្ហាក្នុងការតភ្ជាប់ Database សូមព្យាយាមម្តងទៀត។")
            return
            
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT free_claimed FROM users WHERE user_id = %s', (user_id,))
            result = cursor.fetchone()
            
            if result and result[0] == 1:
                cursor.close()
                conn.close()
                await query.message.reply_text("❌ អ្នកបានប្រើប្រាស់សិទ្ធិសាកល្បងអស់ចំនួន ១ ថ្ងៃរួចរាល់ហើយ! (មិនអាចយកម្តងទៀតបានទេ)")
                return
                
            expiry = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
            username = query.from_user.username or query.from_user.first_name
            package_desc = "១ ថ្ងៃ - 0 ដុល្លារ (Free Trial)"
            
            cursor.execute('''
                UPDATE users SET username = %s, expiry_date = %s, kicked = 0, free_claimed = 1, warned = 0, package_info = %s WHERE user_id = %s
            ''', (username, expiry, package_desc, user_id))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error in claim_free: {e}")
            await query.message.reply_text("⚠️ មានបញ្ហាក្នុងការរក្សាទុកទិន្នន័យ។")
            return
        
        success_message = (
            f"🎉 អបអរសាទរ! អ្នកទទួលបានសិទ្ធិសាកល្បងចំនួន ១ ថ្ងៃជោគជ័យ។\n\n"
            f"🔗 តំណភ្ជាប់ចូលគ្រុប (Group Link):\n{GROUP_INVITE_LINK}\n\n"
            f"📅 មានសុពលភាពដល់ថ្ងៃ៖ {expiry}\n"
            f"ពិនិត្យថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
        )
        await query.message.reply_text(success_message)
        
    elif data.startswith("pkg_"):
        days = int(data.split("_")[1])
        user_selected_package[user_id] = days
        
        prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
        price_text = prices.get(days, "")
        
        caption = (
            f"📦 អ្នកបានជ្រើសរើសកញ្ចប់៖ **{days} ថ្ងៃ** (តម្លៃ: **{price_text}**)\n\n"
            f"💳 ១. សូម Scan QR Code ខាងលើដើម្បីទូទាត់ប្រាក់។\n"
            f"📸 ២. បន្ទាប់ពីបង់ប្រាក់រួច សូមថតរូបវិក្កយបត្រ (Screenshot) ហើយផ្ញើរូបភាពនោះចូលមកកាន់ Bot នេះផ្ទាល់។\n\n"
            f"Admin នឹងពិនិត្យ និងផ្ញើ Link ជូនភ្លាមៗ!"
        )
        
        try:
            await query.message.reply_photo(photo=open('qr.jpg', 'rb'), caption=caption, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(f"{caption}\n\n(⚠️ រកមិនឃើញឯកសារ qr.jpg ក្នុង GitHub ទេ)")

# 5. ទទួលរូបភាពវិក្កយបត្រ (Anti-Cheat)
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
        f"សូមពិនិត្យវិក្កយបត្រខាងក្រោម រួចចុចសម្រេចចិត្ត៖"
    )
    
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file,
            caption=admin_caption,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        await update.message.reply_text("📥 វិក្កយបត្ររបស់អ្នកត្រូវបានផ្ញើជូន Admin ហើយ! សូមរង់ចាំបន្តិច។")
    except Exception as e:
        await update.message.reply_text("មានបញ្ហាក្នុងការផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")

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
                        INSERT INTO users (user_id, username, expiry_date, kicked, free_claimed, warned, package_info) 
                        VALUES (%s, %s, %s, %s, %s, 0, %s)
                    ''', (user_id, "Customer", expiry, 0, 1, package_desc))
                    
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error approving user: {e}")
        
        try:
            success_message = (
                f"🎉 អបអរសាទរ! ការទូទាត់របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ។\n\n"
                f"🔗 តំណភ្ជាប់ចូលគ្រុប (Group Link):\n{GROUP_INVITE_LINK}\n\n"
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

# 7. ពាក្យបញ្ជា /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text(f"❌ អ្នកមិនមែនជា Admin ទេ! (User ID របស់អ្នកគឺ: `{user_id}`)", parse_mode="Markdown")
        return
        
    active_users = expired_users = free_users = 0
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date >= TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS') AND kicked = 0")
            active_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date < TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS')")
            expired_users = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM users WHERE free_claimed = 1")
            free_users = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error fetching stats: {e}")
    
    stats_text = (
        f"📊 **ស្ថិតិប្រព័ន្ធសមាជិកភាព (Admin Dashboard)**\n\n"
        f"🟢 សមាជិកសកម្ម (Active): **{active_users} នាក់**\n"
        f"🔴 សមាជិកអស់សុពលភាព (Expired): **{expired_users} នាក់**\n"
        f"🎁 អ្នកប្រើប្រាស់សាកល្បងฟรี (Free Trial): **{free_users} នាក់**"
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
            cursor.execute('SELECT user_id, username, expiry_date, kicked, free_claimed, package_info FROM users')
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
        u_id, uname, exp_str, kicked, free_claimed, package_info = row
        name = uname if uname else "មិនមានឈ្មោះ"
        badge = "🎁 [Free Trial]" if free_claimed == 1 else "💳 [Paid]"
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

# ពាក្យបញ្ជា /status
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
            await update.message.reply_text(f"ស្ថានភាពសមាជិកភាព៖ ដំណើរការធម្មតា ✅\nសល់ពេល៖ {days} ថ្ងៃ និង {hours} ម៉ោងទៀត\nផុតកំណត់នៅ៖ {expiry_str}")
        else:
            await update.message.reply_text(f"សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ ❌\nសូមចុច /start ដើម្បីទិញកញ្ចប់បន្តសមាជិកភាព។")
    else:
        await update.message.reply_text("អ្នកមិនទាន់ជាសមាជិកទេ។ សូមផ្ញើពាក្យ /start ដើម្បីជ្រើសរើសកញ្ចប់សមាជិកភាព។")

# Auto-Kick Worker
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
                        application.bot.send_message(
                            chat_id=u_id,
                            text="⚠️ **សេចក្តីជូនដំណឹង:** សមាជិកភាពគ្រុបរបស់អ្នកនឹងត្រូវផុតកំណត់ក្នុងរយៈពេល ២៤ ម៉ោងខាងមុខនេះហើយ! សូមបន្តកញ្ចប់សមាជិកភាពរបស់អ្នកជាមុនសិន ដើម្បីកុំឱ្យ Bot ទាត់ចេញពីគ្រុបដោយស្វ័យប្រវត្តិ។ (ចុច /start)"
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
                        
                        application.bot.send_message(
                            chat_id=user_id, 
                            text="⏰ សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ! Bot បានទាត់អ្នកចេញពីគ្រុបដោយស្វ័យប្រវត្តិ។\n\n👉 សូមចុច /start ដើម្បីបង់ប្រាក់ទិញកញ្ចប់សមាជិកភាពថ្មី និងចូលគ្រុបវិញ។"
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
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|claim_free$)"))
    
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Subscription Bot with Cloud PostgreSQL is starting...")
    application.run_polling()
