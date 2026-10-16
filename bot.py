import threading
import sqlite3
import time
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render (ប្រើ os.environ.get("PORT"))
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Subscription Bot with Free Trial & Auto-Kick is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ (សូមដាក់ Link គ្រុប Telegram ពិតប្រាកដរបស់អ្នកនៅទីនេះ) ---
ADMIN_ID = 8980369344                      # <--- ដាក់ Telegram User ID របស់អ្នក
GROUP_INVITE_LINK = "https://t.me/+2JquQ2gZnQE4OGU1"  # <--- បានកែដាក់ Link គ្រុបពិតប្រាកដរបស់អ្នករួចរាល់
GROUP_CHAT_ID = -1001234567890            # <--- លេខ ID គ្រុប Telegram (ចាប់ផ្តើមដោយ -100)
# ---------------------------------------------

# រក្សាទុកកញ្ចប់ដែល User បានជ្រើសរើសបណ្តោះអាសន្ន
user_selected_package = {}

# 2. បង្កើត Database សម្រាប់គ្រប់គ្រងសមាជិកភាព (បន្ថែម package_info សម្រាប់កត់ត្រាកញ្ចប់ និងតម្លៃ)
def init_db():
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expiry_date TEXT,
            kicked INTEGER DEFAULT 0,
            free_claimed INTEGER DEFAULT 0,
            warned INTEGER DEFAULT 0,
            package_info TEXT DEFAULT 'មិនមាន'
        )
    ''')
    # តារាងសម្រាប់ទប់ស្កាត់ការប្រើប្រាស់វិក្កយបត្រដដែល (Anti-Cheat មុខងារទី ៥)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS used_receipts (
            photo_file_id TEXT PRIMARY KEY,
            user_id INTEGER,
            used_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 3. ពាក្យបញ្ជា /start (បង្ហាញប៊ូតុង Free Trial ១ថ្ងៃសម្រាប់អ្នកថ្មី និងកញ្ចប់ទូទាត់)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # ពិនិត្យមើលថាតើ User ធ្លាប់បានយក Free Trial រួចហើយឬยัง
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    keyboard = []
    
    # បើមិនទាន់មានក្នុង Database ឬមិនទាន់បាន Claim Free Trial ទេ បង្ហាញប៊ូតុង Free Trial
    if not result or result[0] == 0:
        keyboard.append([InlineKeyboardButton("🎁 សាកល្បងប្រើប្រាស់បានចំនួន១ ថ្ងៃ (Free Trial)", callback_data="claim_free")])
    
    # បន្ថែមបញ្ជីកញ្ចប់តម្លៃធម្មតា
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
    
    # បើ User ចុចយក Free Trial ១ ថ្ងៃ
    if data == "claim_free":
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            conn.close()
            await query.message.reply_text("❌ អ្នកបានប្រើប្រាស់សិទ្ធិសាកល្បងអស់ចំនួន ១ ថ្ងៃរួចរាល់ហើយ!")
            return
            
        # កំណត់ថ្ងៃផុតកំណត់ ១ ថ្ងៃក្រោយ
        expiry = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        username = query.from_user.username or query.from_user.first_name
        package_desc = "១ ថ្ងៃ - 0 ដុល្លារ (Free Trial)"
        
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed, warned, package_info) 
            VALUES (?, ?, ?, ?, ?, 0, ?)
        ''', (user_id, username, expiry, 0, 1, package_desc))
        conn.commit()
        conn.close()
        
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

# 5. ទទួលរូបភាពវិក្កយបត្រពីអតិថិជន និងបញ្ជូនទៅ Admin (រួមបញ្ចូលមុខងារទី ៥: Anti-Cheat)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    photo_file = update.message.photo[-1].file_id
    
    # មុខងារទី ៥៖ ពិនិត្យមើលថាតើវិក្កយបត្រនេះធ្លាប់ត្រូវបានប្រើប្រាស់រួចហើយឬยัง (Anti-Cheat)
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM used_receipts WHERE photo_file_id = ?', (photo_file,))
    receipt_check = cursor.fetchone()
    conn.close()
    
    if receipt_check:
        await update.message.reply_text("❌ វិក្កយបត្រ (Screenshot) នេះត្រូវបានប្រើប្រាស់រួចរាល់ហើយ! សូមកុំយកវិក្កយបត្ររបស់អ្នកដទៃមកផ្ញើម្តងទៀត។")
        return
        
    days = user_selected_package.get(user_id, 30)
    prices = {5: "២ ដុល្លារ", 10: "៣ ដុល្លារ", 20: "៥ ដុល្លារ", 30: "៦ ដុល្លារ"}
    price_text = prices.get(days, "មិនស្គាល់តម្លៃ")
    package_desc = f"{days} ថ្ងៃ - {price_text}"
    
    # មុខងារទី ៣៖ បន្ថែមប៊ូតុងកែសម្រួលថ្ងៃបន្ថែម (+5d, +10d) ឱ្យ Admin ងាយស្រួលគ្រប់គ្រងរហ័ស
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

# 6. ប្រព័ន្ធ Admin ចុច Approve, Reject ឬ Extend Days (មុខងារទី ៣ និង ៥)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
        
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        
        # កត់ត្រាវិក្កយបត្រទុកដើម្បីការពារការយកមកប្រើซ้ำ (Anti-Cheat មុខងារទី ៥)
        if query.message.photo:
            photo_file = query.message.photo[-1].file_id if hasattr(query.message, 'photo') else None
            if photo_file:
                cursor.execute('INSERT OR IGNORE INTO used_receipts (photo_file_id, user_id, used_at) VALUES (?, ?, ?)', 
                               (photo_file, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        cursor.execute('''
            UPDATE users SET expiry_date = ?, kicked = 0, warned = 0, package_info = ? WHERE user_id = ?
        ''', (expiry, package_desc, user_id))
        
        if cursor.rowcount == 0:
            cursor.execute('''
                INSERT INTO users (user_id, username, expiry_date, kicked, free_claimed, warned, package_info) 
                VALUES (?, ?, ?, ?, ?, 0, ?)
            ''', (user_id, "Customer", expiry, 0, 1, package_desc))
            
        conn.commit()
        conn.close()
        
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
            
    elif data.startswith("ext_"): # មុខងារទី ៣៖ Admin Panel បន្ថែមថ្ងៃឱ្យអតិថិជនរហ័ស
        parts = data.split("_")
        user_id = int(parts[1])
        ext_days = int(parts[2])
        
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT expiry_date, package_info FROM users WHERE user_id = ?', (user_id,))
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
            INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed, warned, package_info) 
            VALUES (?, ?, ?, 0, 1, 0, ?)
        ''', (user_id, "Customer", new_expiry, new_pkg))
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(chat_id=user_id, text=f"✨ Admin បានបន្ថែមថ្ងៃសមាជិកភាពឱ្យអ្នកចំនួន {ext_days} ថ្ងៃបន្ថែមទៀត! ផុតកំណត់ថ្ងៃ៖ {new_expiry}")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n➕ [បានបន្ថែមថ្ងៃជោគជ័យ +{ext_days} ថ្ងៃ]")
        except Exception:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n➕ [បានបន្ថែមថ្ងៃជោគជ័យ +{ext_days} ថ្ងៃ ប៉ុន្តែផ្ញើសារមិនទាន់ដល់ User]")

# 7. មុខងារទី ៤៖ ពាក្យបញ្ជា /stats សម្រាប់ Admin មើលស្ថិតិសមាជិក (រួមបញ្ចូលការរាប់ចំនួន Free Trial)
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text(f"❌ អ្នកមិនមែនជា Admin ទេ! (User ID របស់អ្នកគឺ: `{user_id}`)", parse_mode="Markdown")
        return
        
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date >= datetime('now') AND kicked = 0")
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date < datetime('now')")
    expired_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE free_claimed = 1")
    free_users = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 **ស្ថិតិប្រព័ន្ធសមាជិកភាព (Admin Dashboard)**\n\n"
        f"🟢 សមាជិកសកម្ម (Active): **{active_users} នាក់**\n"
        f"🔴 សមាជិកអស់សុពលភាព (Expired): **{expired_users} នាក់**\n"
        f"🎁 អ្នកប្រើប្រាស់សាកល្បងฟรี (Free Trial): **{free_users} នាក់**"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown")

# 🆕 មុខងារថ្មីសម្រាប់ Admin៖ មើលបញ្ជីសមាជិកទាំងអស់ ឈ្មោះ វិន័យកញ្ចប់ និងចំនួនថ្ងៃដែលនៅសល់
async def admin_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text(f"❌ អ្នកមិនមែនជា Admin ទេ! (User ID របស់អ្នកគឺ: `{user_id}`)", parse_mode="Markdown")
        return
        
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, expiry_date, kicked, free_claimed, package_info FROM users')
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("📭 មិនទាន់មានទិន្នន័យសមាជិកនៅក្នុងប្រព័ន្ធទេ។")
        return
        
    msg = "📋 **បញ្ជីឈ្មោះ វិន័យកញ្ចប់ និងស្ថានភាពសមាជិកទាំងអស់៖**\n\n"
    now = datetime.now()
    
    for row in rows:
        u_id, uname, exp_str, kicked, free_claimed, package_info = row
        name = uname if uname else "មិនមានឈ្មោះ"
        badge = "🎁 [Free Trial]" if free_claimed == 1 else "💳 [Paid]"
        pkg_desc = package_info if package_info else "មិនមានទិន្នន័យ"
        
        if kicked == 1:
            status_text = "🔴 បានទាត់ចេញ (Expired/Kicked)"
        else:
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d %H:%M:%S')
                if now < exp_date:
                    rem = exp_date - now
                    days = rem.days
                    hours = rem.seconds // 3600
                    status_text = f"🟢 សកម្ម (សល់ {days} ថ្ងៃ និង {hours} ម៉ោង)"
                else:
                    status_text = "🔴 ផុតកំណត់ហើយ"
            except Exception:
                status_text = f"📅 ផុតកំណត់ថ្ងៃ៖ {exp_str}"
                
        msg += f"👤 ឈ្មោះ: **{name}** {badge}\n🆔 ID: `{u_id}`\n📦 កញ្ចប់: **{pkg_desc}**\n⏳ ស្ថានភាព: {status_text}\n----------------------------------\n"
        
    if len(msg) > 4000:
        for x in range(0, len(msg), 4000):
            await update.message.reply_text(msg[x:x+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

# 7. ពាក្យបញ្ជា /status ពិនិត្យថ្ងៃខែសល់
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT expiry_date FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
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

# 8. ប្រព័ន្ធស្វ័យប្រវត្តិពិនិត្យ ផ្ញើសារជូនដំណឹងមុនផុតកំណត់ (មុខងារទី ១) និង Auto-Kick Worker
def auto_kick_checker(application):
    while True:
        try:
            conn = sqlite3.connect('subscriptions.db')
            cursor = conn.cursor()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # មុខងារទី ១៖ ផ្ញើសារជូនដំណឹងមុនពេលផុតកំណត់ ២៤ ម៉ោង (Expiry Warning Reminder)
            soon_str = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('SELECT user_id FROM users WHERE expiry_date <= ? AND expiry_date > ? AND warned = 0 AND kicked = 0', (soon_str, now_str))
            warn_users = cursor.fetchall()
            
            for row in warn_users:
                u_id = row[0]
                try:
                    application.bot.send_message(
                        chat_id=u_id,
                        text="⚠️ **សេចក្តីជូនដំណឹង:** សមាជិកភាពគ្រុបរបស់អ្នកនឹងត្រូវផុតកំណត់ក្នុងរយៈពេល ២៤ ម៉ោងខាងមុខនេះហើយ! សូមបន្តកញ្ចប់សមាជិកភាពរបស់អ្នកជាមុនសិន ដើម្បីកុំឱ្យ Bot ទាត់ចេញពីគ្រុបដោយស្វ័យប្រវត្តិ។ (ចុច /start)"
                    )
                    cursor.execute('UPDATE users SET warned = 1 WHERE user_id = ?', (u_id,))
                    conn.commit()
                except Exception as e:
                    print(f"Error sending warning to {u_id}: {e}")

            # Auto-Kick សមាជិកដែលផុតកំណត់
            cursor.execute('SELECT user_id FROM users WHERE expiry_date < ? AND kicked = 0', (now_str,))
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
                
                cursor.execute('UPDATE users SET kicked = 1 WHERE user_id = ?', (user_id,))
                conn.commit()
                
            conn.close()
        except Exception as e:
            print(f"Database error in auto_kick: {e}")
            
        time.sleep(60)

# 9. Error Handler ការពារកុំឱ្យ Bot គាំងពេលមានបញ្ហាអនឡាញ
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

if __name__ == "__main__":
    application = ApplicationBuilder().token("8907453817:AAGqGpbWJzbWXFt1Vqcgso9ytQmwFiih0zc").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin_members", admin_members))  # <--- បន្ថែម Handler សម្រាប់ Admin មើលសមាជិក
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_|ext_)"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|claim_free$)"))
    
    # ចុះឈ្មោះ Error Handler
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Subscription Bot with Free Trial, Warning, Anti-Cheat & Auto-Kick is starting...")
    application.run_polling()
