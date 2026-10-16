import threading
import sqlite3
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
    return "Advanced Subscription Bot with All Features is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ (សូមកែប្រែត្រង់នេះ) ---
ADMIN_ID = 123456789                      # <--- ដាក់ Telegram User ID របស់អ្នក
GROUP_CHAT_ID = -1001234567890            # <--- លេខ ID គ្រុប Telegram (ចាប់ផ្តើមដោយ -100)
# ---------------------------------------------

user_selected_package = {}

# 2. បង្កើត Database សម្រាប់គ្រប់គ្រងទិន្នន័យទាំងអស់ (បន្ថែម Anti-Cheat & Warning Status)
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
            warned INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            days INTEGER,
            photo_file_id TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    # តារាងសម្រាប់ទប់ស្កាត់ការប្រើប្រាស់វិក្កយបត្រដដែល (Anti-Cheat)
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

# 3. ពាក្យបញ្ជា /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    keyboard = []
    if not result or result[0] == 0:
        keyboard.append([InlineKeyboardButton("🎁 សាកល្បងប្រើប្រាស់ចំនួន ១ ថ្ងៃ (Free Trial)", callback_data="claim_free")])
    
    keyboard.extend([
        [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
        [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
        [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
        [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"សួស្តី {user.first_name}!\n\n"
        f"សូមស្វាគមន៍មកកាន់ប្រព័ន្ធសមាជិកភាពគ្រុបរបស់យើង។ "
        f"សូមជ្រើសរើសកញ្ចប់ ឬសាកល្បងប្រើប្រាស់ฟรีខាងក្រោម៖"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# 4. ដោះស្រាយពេលអតិថិជនចុចយក Free Trial ឬកញ្ចប់
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "claim_free":
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            conn.close()
            await query.message.reply_text("❌ អ្នកបានប្រើប្រាស់សិទ្ធិសាកល្បងฟรี ១ ថ្ងៃរួចរាល់ហើយ!")
            return
            
        expiry = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        
        # មុខងារទី ២៖ បង្កើត Unique Group Invite Link (ប្រើបានតែម្តង ក្នុងរយៈពេល ១ ថ្ងៃ)
        try:
            expire_time = datetime.now() + timedelta(days=1)
            invite_link_obj = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                member_limit=1,
                expire_date=expire_time
            )
            group_link = invite_link_obj.invite_link
        except Exception as e:
            group_link = "មិនអាចបង្កើត Link បានទេ សូមទាក់ទង Admin"
            print(f"Error creating invite link: {e}")

        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed, warned) 
            VALUES (?, ?, ?, ?, 1, 0)
        ''', (user_id, query.from_user.username or query.from_user.first_name, expiry, 0))
        conn.commit()
        conn.close()
        
        success_message = (
            f"🎉 អបអរសាទរ! អ្នកទទួលបានសិទ្ធិសាកល្បងฟรี ១ ថ្ងៃជោគជ័យ។\n\n"
            f"🔗 តំណភ្ជាប់ចូលគ្រុបផ្ទាល់ខ្លួនរបស់អ្នក (ប្រើបានតែម្តង):\n{group_link}\n\n"
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
            f"📸 ២. បន្ទាប់ពីបង់ប្រាក់រួច សូមថតរូបវិក្កយបត្រ (Screenshot) ហើយផ្ញើរូបភាពនោះចូលមកកាន់ Bot នេះផ្ទាល់។"
        )
        
        try:
            await query.message.reply_photo(photo=open('qr.jpg', 'rb'), caption=caption, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(f"{caption}\n\n(⚠️ រកមិនឃើញឯកសារ qr.jpg ក្នុង GitHub ទេ)")

# 5. ទទួលរូបភាពវិក្កយបត្រ (រួមទាំងមុខងារទី ៥: Anti-Cheat Duplicate Receipt Detection)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    photo_file = update.message.photo[-1].file_id
    
    # ពិនិត្យមើលថាតើវិក្កយបត្រនេះធ្លាប់ត្រូវបានប្រើប្រាស់រួចហើយឬនៅ
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM used_receipts WHERE photo_file_id = ?', (photo_file,))
    receipt_check = cursor.fetchone()
    
    if receipt_check:
        conn.close()
        await update.message.reply_text("❌ វិក្កយបត្រ (Screenshot) នេះត្រូវបានប្រើប្រាស់រួចរាល់ហើយ! សូមកុំយកវិក្កយបត្ររបស់អ្នកដទៃមកផ្ញើซ้ำ។")
        return
        
    days = user_selected_package.get(user_id, 30)
    
    cursor.execute('''
        INSERT INTO pending_requests (user_id, username, days, photo_file_id, status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (user_id, username, days, photo_file))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ យល់ព្រម (Approve)", callback_data=f"approve_{request_id}_{user_id}_{days}"),
            InlineKeyboardButton("❌ បដិសេធ (Reject)", callback_data=f"reject_{request_id}_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    admin_caption = (
        f"🔔 **សំណើសមាជិកភាព លេខរៀងទី #{request_id}**\n\n"
        f"👤 ឈ្មោះ: {username}\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📦 កញ្ចប់រើស: **{days} ថ្ងៃ**\n\n"
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
        await update.message.reply_text(f"📥 វិក្កយបត្ររបស់អ្នកត្រូវបានបញ្ជូនជូន Admin ហើយ! (លំដាប់រៀងទី: #{request_id})។ សូមរង់ចាំបន្តិច។")
    except Exception as e:
        await update.message.reply_text("មានបញ្ហាក្នុងการផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")

# 6. Admin អនុម័ត (បង្កើត Unique Invite Link & บันทึก Anti-Cheat)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("approve_"):
        parts = data.split("_")
        request_id = parts[1]
        user_id = int(parts[2])
        days = int(parts[3])
        
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        
        # កត់ត្រាវិក្កយបត្រទុកដើម្បីការពារការយកមកប្រើซ้ำ (Anti-Cheat)
        cursor.execute('SELECT photo_file_id FROM pending_requests WHERE request_id = ?', (request_id,))
        req_row = cursor.fetchone()
        if req_row:
            photo_id = req_row[0]
            cursor.execute('INSERT OR IGNORE INTO used_receipts (photo_file_id, user_id, used_at) VALUES (?, ?, ?)', 
                           (photo_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed, warned) 
            VALUES (?, ?, ?, ?, 1, 0)
        ''', (user_id, "Customer", expiry, 0))
        
        cursor.execute("UPDATE pending_requests SET status = 'approved' WHERE request_id = ?", (request_id,))
        conn.commit()
        conn.close()
        
        # មុខងារទី ២៖ បង្កើប Unique Group Invite Link ដែលប្រើបានតែម្តង
        try:
            expire_time = datetime.now() + timedelta(days=2) # Link មានអាយុ ២ ថ្ងៃ
            invite_link_obj = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                member_limit=1,
                expire_date=expire_time
            )
            group_link = invite_link_obj.invite_link
        except Exception as e:
            group_link = "សូមទាក់ទង Admin ដើម្បីយក Link ចូលគ្រុបផ្ទាល់"
            print(f"Error creating invite link: {e}")
        
        try:
            success_message = (
                f"🎉 អបអរសាទរ! ការទូទាត់របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ។\n\n"
                f"🔗 តំណភ្ជាប់ចូលគ្រុបផ្ទាល់ខ្លួនរបស់អ្នក (ប្រើបានតែម្តង):\n{group_link}\n\n"
                f"📅 សមាជិកភាពមានសុពលភាពចំនួន {days} ថ្ងៃ ដល់ថ្ងៃ៖ {expiry}\n"
                f"ពិនិត្យថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
            )
            await context.bot.send_message(chat_id=user_id, text=success_message)
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ [លេខរៀង #{request_id} - អនុម័តជោគជ័យ {days} ថ្ងៃ]")
        except Exception as e:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ [លេខរៀង #{request_id}] អនុម័តរួច ប៉ុន្តែមានបញ្ហាក្នុងការផ្ញើសារទៅ User")
            
    elif data.startswith("reject_"):
        parts = data.split("_")
        request_id = parts[1]
        user_id = int(parts[2])
        
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ សូមអភ័យទោស វិក្កយបត្ររបស់អ្នកមិនត្រឹមត្រូវ សូមទាក់ទងមក Admin ។")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [លេខរៀង #{request_id} - បានបដិសេធ]")
        except Exception:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [លេខរៀង #{request_id} - បានបដិសេធ]")

# 7. មុខងារទី ៤៖ ពាក្យបញ្ជា /stats សម្រាប់ Admin មើលស្ថិតិ
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ អ្នកមិនមែនជា Admin ទេ!")
        return
        
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date >= datetime('now') AND kicked = 0")
    active_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE expiry_date < datetime('now')")
    expired_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM pending_requests WHERE status = 'pending'")
    pending_count = cursor.fetchone()[0]
    
    conn.close()
    
    stats_text = (
        f"📊 **ស្ថិតិប្រព័ន្ធសមាជិកភាព (Admin Dashboard)**\n\n"
        f"🟢 សមាជិកសកម្ម (Active): **{active_users} នាក់**\n"
        f"🔴 សមាជិកអស់សុពលភាព (Expired): **{expired_users} នាក់**\n"
        f"⏳ សំណើវិក្កយបត្ររង់ចាំពិនិត្យ (Pending): **{pending_count} នាក់**"
    )
    await update.message.reply_text(stats_text, parse_mode="Markdown")

# 8. ពាក្យបញ្ជា /status
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

# 9. មុខងារទី ១ និង ៧៖ Background Worker (ផ្ញើសារເຕືອນមុនផុតកំណត់ និង Auto-Kick)
def auto_kick_checker(application):
    while True:
        try:
            conn = sqlite3.connect('subscriptions.db')
            cursor = conn.cursor()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # ក. មុខងារទី ១៖ ផ្ញើសារເຕືອນមុនផុតកំណត់ ២៤ ម៉ោង (Warning Reminder)
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

            # ខ. មុខងារ Auto-Kick សមាជិកដែលផុតកំណត់
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

if __name__ == "__main__":
    application = ApplicationBuilder().token("8907453817:AAGqGpbWJzbWXFt1Vqcgso9ytQmwFiih0zc").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_)"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|claim_free$)"))
    
    application.add_error_handler(error_handler)
    
    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()
    
    print("Advanced Subscription Bot with All Features is starting...")
    application.run_polling()
