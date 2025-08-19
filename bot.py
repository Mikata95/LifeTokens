from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Google Sheets Setup ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("LifeTokens").sheet1

# --- Telegram Bot Setup ---
TOKEN = "8404658319:AAFxHRR15OS_DrgSUQcQ4GvgG-6gK1IKNFU"

activities = ["💪", "💻", "📚", "🧘", "🗣️", "🍲", "🏡"]

# Dictionary to store user scores temporarily
user_scores = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_scores[user_id] = {activity: 0 for activity in activities}
    keyboard = []
    for activity in activities:
        keyboard.append([InlineKeyboardButton(f"{activity} 0", callback_data=activity + "_0")])
    # Added Reset button alongside Submit
    keyboard.append([
        InlineKeyboardButton("Reset", callback_data="reset"),
        InlineKeyboardButton("Submit", callback_data="submit")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Hello! I will help you track your daily tokens 🌟\n"
        "Click the buttons to increase your tokens for each activity.\n"
        "When done, press Submit.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in user_scores:
        user_scores[user_id] = {activity: 0 for activity in activities}

    data = query.data

    if data == "submit":
        today = datetime.now().strftime("%Y-%m-%d")
        values = [user_scores[user_id].get(activity, 0) for activity in activities]
        sheet.append_row([today] + values)
        await query.edit_message_text("✅ Tokens saved for today! Use /start to enter new data.")
        user_scores.pop(user_id, None)
        return

    # New feature: Reset tokens button resets all counts to 0
    if data == "reset":
        user_scores[user_id] = {activity: 0 for activity in activities}
        # Rebuild keyboard with zeros
        keyboard = []
        for act in activities:
            keyboard.append([InlineKeyboardButton(f"{act} 0", callback_data=f"{act}_0")])
        keyboard.append([
            InlineKeyboardButton("Reset", callback_data="reset"),
            InlineKeyboardButton("Submit", callback_data="submit")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return

    # data format: activity + "_" + count
    activity, count_str = data.split("_")
    count = int(count_str) + 1
    user_scores[user_id][activity] = count

    # Rebuild keyboard with updated counts
    keyboard = []
    for act in activities:
        keyboard.append([InlineKeyboardButton(f"{act} {user_scores[user_id][act]}", callback_data=f"{act}_{user_scores[user_id][act]}")])
    keyboard.append([
        InlineKeyboardButton("Reset", callback_data="reset"),
        InlineKeyboardButton("Submit", callback_data="submit")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_reply_markup(reply_markup=reply_markup)

# New feature: /average command to retrieve averages over last 7 rows
async def average(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get all values from sheet
    all_values = sheet.get_all_values()
    # Exclude header if present, assume first row is header or date row
    data_rows = all_values[1:] if len(all_values) > 1 else []
    # Take last 7 rows or fewer if not enough data
    last_rows = data_rows[-7:] if len(data_rows) >= 1 else []

    if not last_rows:
        await update.message.reply_text("No data available to calculate averages.")
        return

    # Initialize sums for each activity
    sums = {activity: 0 for activity in activities}
    count_rows = len(last_rows)

    for row in last_rows:
        # row format: [date, val1, val2, ...]
        # values start from index 1
        for i, activity in enumerate(activities):
            try:
                val = int(row[i+1])
            except (IndexError, ValueError):
                val = 0
            sums[activity] += val

    averages = {activity: round(sums[activity]/count_rows, 2) for activity in activities}

    # Build response message
    msg_lines = ["📊 Average tokens for last 7 entries:"]
    for activity in activities:
        msg_lines.append(f"{activity}: {averages[activity]}")

    await update.message.reply_text("\n".join(msg_lines))

# New feature: Daily reminder at 22:00 to send /start prompt automatically
async def send_daily_reminder(app):
    # This function should send a message to all users who have interacted before
    # Since we only store scores for active users, we can send to all users in user_scores
    # Alternatively, if you want to send to a fixed chat or group, adjust accordingly
    for user_id in list(user_scores.keys()):
        try:
            await app.bot.send_message(chat_id=user_id, text="It's 22:00! Time to log your daily tokens. Use /start to begin.")
        except Exception:
            # If user blocked bot or other error, remove from user_scores
            user_scores.pop(user_id, None)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("average", average))

    # Setup scheduler for daily reminder at 22:00
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: send_daily_reminder(app), 'cron', hour=22, minute=0)
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()