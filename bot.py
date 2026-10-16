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

--- ការកំណត់សំខាន់ៗ (សូមកែប្រែត្រង់នេះ) ---
ADMIN_ID = 123456789                      # <--- ដាក់ Telegram User ID របស់អ្នក
GROUP_CHAT_ID = -1001234567890            # <--- លេខ ID គ្រុប Telegram (ចាប់ផ្តើមដោយ -100)
---------------------------------------------

# រក្សាទុកកញ្ចប់ដែល User បានជ្រើសរើសបណ្តោះអាសន្ន
user_selected_package = {}

# 2. បង្កើត Database សម្រាប់គ្រប់គ្រងសមាជិកភាព (បន្ថែម free_claimed)
def init_db():
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expiry_date TEXT,
            kicked INTEGER DEFAULT 0,
            free_claimed INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 3. ពាក្យបញ្ជា /start (បង្ហាញជម្រើសកញ្ចប់សមាជិកភាព និង Free Trial)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()

    keyboard = []
    # បើមិនទាន់ធ្លាប់ប្រើ Free Trial ទេ បង្ហាញប៊ូតុងសាកល្បង
    if not result or result[0] == 0:
        keyboard.append([InlineKeyboardButton("🎁 សាកល្បងប្រើប្រាស់ฟรี ១ ថ្ងៃ (Free Trial)", callback_data="claim_free")])

    keyboard.extend([
        [InlineKeyboardButton("៥ ថ្ងៃ - ២ ដុល្លារ", callback_data="pkg_5")],
        [InlineKeyboardButton("១០ ថ្ងៃ - ៣ ដុល្លារ", callback_data="pkg_10")],
        [InlineKeyboardButton("២០ ថ្ងៃ - ៥ ដុល្លារ", callback_data="pkg_20")],
        [InlineKeyboardButton("៣០ ថ្ងៃ - ៦ ដុល្លារ", callback_data="pkg_30")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"សួស្តី {user.first_name}!\n\n"
        f"សូមជ្រើសរើសកញ្ចប់សមាជិកភាព ឬសាកល្បងប្រើប្រាស់ฟรีខាងក្រោម៖"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# 4. ដោះស្រាយពេលអតិថិជនចុចយក Free Trial ឬកញ្ចប់ផ្សេងៗ
async def package_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    user = query.from_user
    username = user.username or user.first_name

    if data == "claim_free":
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT free_claimed FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            conn.close()
            await query.message.reply_text("❌ អ្នកបានប្រើប្រាស់សិទ្ធិសាកល្បងប្រើប្រាស់ฟรี ១ ថ្ងៃរួចរាល់ហើយ!")
            return
            
        expiry = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        
        # បង្កើត Unique Group Invite Link ( member_limit=1 ប្រើបានតែ ១ ដងគត់ និងផុតកំណត់ក្នុង ១ ថ្ងៃ )
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
            INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, expiry, 0, 1))
        conn.commit()
        conn.close()
        
        success_text = (
            f"🎁 អបអរសាទរ! អ្នកបានទទួលបានសិទ្ធិសាកល្បងប្រើប្រាស់ฟรี ១ ថ្ងៃជោគជ័យ។\n\n"
            f"👤 ឈ្មោះ Telegram: {username}\n"
            f"🔗 តំណភ្ជាប់ចូលគ្រុបរបស់អ្នក (ប្រើបានតែម្តងគត់):\n{group_link}\n\n"
            f"📅 មានសុពលភាពដល់ថ្ងៃ៖ {expiry}\n"
            f"ពិនិត្យថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
        )
        await query.message.reply_text(success_text)

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

# 5. ទទួលរូបភាពវិក្កយបត្រពីអតិថិជន និងបញ្ជូនទៅ Admin
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    days = user_selected_package.get(user_id, 30)

    keyboard = [
        [
            InlineKeyboardButton("✅ យល់ព្រម (Approve)", callback_data=f"approve_{user_id}_{days}"),
            InlineKeyboardButton("❌ បដិសេធ (Reject)", callback_data=f"reject_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_caption = (
        f"🔔 **មានអតិថិជនស្នើសុំចូលសមាជិក!**\n\n"
        f"👤 ឈ្មោះ: {username}\n"
        f"🆔 User ID: `{user_id}`\n"
        f"ជម្រើសកញ្ចប់: **{days} ថ្ងៃ**\n\n"
        f"សូមពិនិត្យវិក្កយបត្រខាងក្រោម រួចចុចសម្រេចចិត្ត៖"
    )

    try:
        photo_file = update.message.photo[-1].file_id
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

# 6. ប្រព័ន្ធ Admin ចុច Approve ឬ Reject
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("approve_"):
        parts = data.split("_")
        user_id = int(parts[1])
        days = int(parts[2])
        
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        
        # បង្កើត Unique Group Invite Link ពេល Approve សម្រាប់កញ្ចប់បង់ប្រាក់
        try:
            expire_time = datetime.now() + timedelta(days=days)
            invite_link_obj = await context.bot.create_chat_invite_link(
                chat_id=GROUP_CHAT_ID,
                member_limit=1,
                expire_date=expire_time
            )
            group_link = invite_link_obj.invite_link
        except Exception as e:
            group_link = "មិនអាចបង្កើត Link បានទេ សូមទាក់ទង Admin"
            print(f"Error creating invite link: {e}")

        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO users (user_id, username, expiry_date, kicked, free_claimed) VALUES (?, ?, ?, ?, (SELECT free_claimed FROM users WHERE user_id = ?))', 
                       (user_id, "Customer", expiry, 0, user_id))
        conn.commit()
        conn.close()
        
        try:
            success_message = (
                f"🎉 អបអរសាទរ! ការទូទាត់របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ។\n\n"
                f"🔗 តំណភ្ជាប់ចូលគ្រុបរបស់អ្នក (ប្រើបានតែម្តងគត់):\n{group_link}\n\n"
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

# 8. ប្រព័ន្ធស្វ័យប្រវត្តិពិនិត្យ និងទាត់ចេញ (Auto-Kick Worker)
def auto_kick_checker(application):
    while True:
        try:
            conn = sqlite3.connect('subscriptions.db')
            cursor = conn.cursor()
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
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
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(approve_|reject_)"))
    application.add_handler(CallbackQueryHandler(package_callback, pattern="^(pkg_|claim_free)"))

    # ចុះឈ្មោះ Error Handler
    application.add_error_handler(error_handler)

    threading.Thread(target=auto_kick_checker, args=(application,), daemon=True).start()

    print("Subscription Bot with Free Trial & Auto-Kick is starting...")
    application.run_polling()
