import threading
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from flask import Flask

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot with Payment Approval System is running!"

def run_web():
    app_web.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web, daemon=True).start()

# --- ការកំណត់សំខាន់ៗ (សូមកែប្រែត្រង់នេះ) ---
ADMIN_ID = 8980369344             # <--- ដាក់ Telegram User ID របស់អ្នកនៅទីនេះ
GROUP_INVITE_LINK = "https://t.me/+1oRgTCiY4RM1MjNl"  # <--- ដាក់ Link គ្រុប Telegram របស់អ្នកនៅទីនេះ
# ---------------------------------------------

# 2. បង្កើត Database សម្រាប់គ្រប់គ្រងសមាជិកភាព
def init_db():
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expiry_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 3. ពាក្យបញ្ជា /start (បង្ហាញ QR Code)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    caption = (
        f"សួស្តី {user.first_name}!\n\n"
        f"💳 ដើម្បីចូលជាសមាជិក និងទទួលបាន Link ចូលគ្រុប៖\n"
        f"១. សូម Scan QR Code ខាងលើដើម្បីទូទាត់ប្រាក់។\n"
        f"២. បន្ទាប់ពីបង់ប្រាក់រួច សូម **ថតរូបវិក្កយបត្រ (Screenshot)** ហើយផ្ញើរូបភាពនោះចូលមកកាន់ Bot នេះផ្ទាល់។\n\n"
        f"Admin នឹងពិនិត្យ និងផ្ញើ Link ជូនភ្លាមៗបន្ទាប់ពីទទួលបានការយល់ព្រម!"
    )
    
    try:
        await update.message.reply_photo(photo=open('qr.jpg', 'rb'), caption=caption)
    except Exception:
        await update.message.reply_text(
            f"{caption}\n\n(⚠️ រកមិនឃើញឯកសារ qr.jpg ក្នុង GitHub ទេ សូម Admin ដាក់បញ្ចូលជាមុនសិន)"
        )

# 4. ទទួលរូបភាពវិក្កយបត្រពីអតិថិជន និងបញ្ជូនទៅ Admin
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    keyboard = [
        [
            InlineKeyboardButton("✅ យល់ព្រម (Approve)", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ បដិសេធ (Reject)", callback_data=f"reject_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    admin_caption = (
        f"🔔 **មានអតិថិជនស្នើសុំចូលសមាជិក!**\n\n"
        f"👤 ឈ្មោះ: {username}\n"
        f"🆔 User ID: `{user_id}`\n\n"
        f"សូមពិនិត្យវិក្កយបត្រខាងក្រោម រួចចុចប៊ូតុងសម្រេចចិត្ត៖"
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
        await update.message.reply_text("📥 វិក្កយបត្ររបស់អ្នកត្រូវបានផ្ញើជូន Admin ហើយ! សូមរង់ចាំការពិនិត្យបន្តិច។")
    except Exception as e:
        await update.message.reply_text("មានបញ្ហាក្នុងការផ្ញើរូបភាព សូមព្យាយាមម្តងទៀត។")

# 5. ប្រព័ន្ធដោះស្រាយការចុចប៊ូតុងរបស់ Admin (Callback Query)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("approve_"):
        user_id = int(data.split("_")[1])
        
        # កំណត់ពេលសមាជិកភាព ៣០ថ្ងៃ ចូល Database
        expiry = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect('subscriptions.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO users (user_id, username, expiry_date) VALUES (?, ?, ?)', 
                       (user_id, "Customer", expiry))
        conn.commit()
        conn.close()
        
        try:
            success_message = (
                f"🎉 អបអរសាទរ! ការទូទាត់របស់អ្នកត្រូវបាន Admin យល់ព្រមហើយ។\n\n"
                f"🔗 តំណភ្ជាប់ចូលគ្រុប (Group Link):\n{GROUP_INVITE_LINK}\n\n"
                f"📅 សមាជិកភាពមានសុពលភាពដល់៖ {expiry}\n"
                f"អ្នកអាចពិនិត្យមើលថ្ងៃខែនៅសល់ដោយប្រើពាក្យបញ្ជា /status"
            )
            await context.bot.send_message(chat_id=user_id, text=success_message)
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ [បានអនុម័តជោគជ័យ និងផ្ញើ Link ជូនអតិថិជនរួចរាល់]")
        except Exception as e:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ អនុម័តរួច ប៉ុន្តែមានបញ្ហាក្នុងការផ្ញើសារទៅកាន់ User")
            
    elif data.startswith("reject_"):
        user_id = int(data.split("_")[1])
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ សូមអភ័យទោស វិក្កយបត្រទូទាត់ប្រាក់របស់អ្នកមិនត្រឹមត្រូវ ឬមិនទាន់ទទួលបានប្រាក់ សូមទាក់ទងមក Admin ផ្ទាល់។")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")
        except Exception:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ [បានបដិសេធ]")

# 6. ពាក្យបញ្ជា /status
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
            await update.message.reply_text(f"សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ ❌\nកាលបរិច្ឆេទផុតកំណត់៖ {expiry_str}\nសូមផ្ញើវិក្កយបត្រថ្មីដើម្បីបន្ត។")
    else:
        await update.message.reply_text("អ្នកមិនទាន់ជាសមាជិកទេ។ សូមផ្ញើពាក្យ /start ដើម្បីមើល QR Code ទូទាត់ប្រាក់។")

if __name__ == "__main__":
    application = ApplicationBuilder().token("8907453817:AAGqGpbWJzbWXFt1Vqcgso9ytQmwFiih0zc").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Bot with Payment & Approval System is starting...")
    application.run_polling()
