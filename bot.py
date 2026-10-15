import threading
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask

# 1. ផ្នែក Flask សម្រាប់រក្សាឱ្យ Bot រត់បានយូរលើ Render
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is running with Subscription System!"

def run_web():
    app_web.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web, daemon=True).start()

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

# 3. ពាក្យបញ្ជា /start (ចុះឈ្មោះ និងផ្ដល់សាកល្បង ៣ថ្ងៃ)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT expiry_date FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if not result:
        expiry = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT OR REPLACE INTO users (user_id, username, expiry_date) VALUES (?, ?, ?)', 
                       (user_id, username, expiry))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"សួស្តី {username}!\nអ្នកបានចុះឈ្មោះជោគជ័យ និងទទួលបានពេលសាកល្បង ៣ថ្ងៃ។\nសូមប្រើពាក្យបញ្ជា /status ដើម្បីឆែកមើលថ្ងៃផុតកំណត់។")
    else:
        conn.close()
        await update.message.reply_text(f"សួស្តី {username}!\nអ្នកមានគណនីក្នុងប្រព័ន្ធរួចហើយ។ ប្រើពាក្យបញ្ជា /status ដើម្បីពិនិត្យថ្ងៃផុតកំណត់។")

# 4. ពាក្យបញ្ជា /status (ពិនិត្យថ្ងៃផុតកំណត់)
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
            await update.message.reply_text(f"សមាជិកភាពរបស់អ្នកបានផុតកំណត់ហើយ ❌\nកាលបរិច្ឆេទផុតកំណត់៖ {expiry_str}\nសូមទាក់ទង Admin ដើម្បីបន្តសមាជិកភាព។")
    else:
        await update.message.reply_text("អ្នកមិនទាន់បានចុះឈ្មោះក្នុងប្រព័ន្ធទេ។ សូមផ្ញើពាក្យ /start ដើម្បីចាប់ផ្តើម។")

# 5. ពាក្យបញ្ជាសម្រាប់ Admin បន្ថែមថ្ងៃសមាជិកភាព (/addsub <user_id> <ចំនួនថ្ងៃ>)
async def add_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("របៀបប្រើប្រាស់៖ /addsub <user_id> <ចំនួនថ្ងៃ>")
        return
    
    try:
        target_user_id = int(context.args[0])
        days_to_add = int(context.args[1])
    except ValueError:
        await update.message.reply_text("User ID និង ចំនួនថ្ងៃ ត្រូវតែជាតួលេខ។")
        return
    
    expiry = (datetime.now() + timedelta(days=days_to_add)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect('subscriptions.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, expiry_date) VALUES (?, ?, ?)', 
                   (target_user_id, "User", expiry))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"បានបន្ថែមសមាជិកភាពជោគជ័យសម្រាប់ User ID: {target_user_id} រយៈពេល {days_to_add} ថ្ងៃ។")

if __name__ == "__main__":
    application = ApplicationBuilder().token("8907453817:AAGqGpbWJzbWXFt1Vqcgso9ytQmwFiih0zc").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("addsub", add_sub))
    
    print("Bot with Subscription System is starting...")
    application.run_polling()
