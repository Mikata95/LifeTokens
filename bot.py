import os
import json
from datetime import datetime
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# =========================
# Configuration via ENV VARS
# =========================
# REQUIRED:
#   TELEGRAM_BOT_TOKEN          -> your BotFather token
#   GOOGLE_SERVICE_ACCOUNT_JSON -> full JSON content of your Google service account
#   SPREADSHEET_ID              -> the ID part from your Google Sheet URL
# OPTIONAL:
#   REMINDER_TZ                 -> timezone string (default "Europe/Rome")
#   REMINDER_HOUR               -> hour in 24h format (default 22)
#   REMINDER_MINUTE             -> minute (default 0)


# Activities (emoji order must match sheet columns)
ACTIVITIES = ["💪", "💻", "📚", "🧘", "🗣️", "🍲", "🏡"]

# In-memory scores per user (only for current session)
user_scores = {}

# =========================
# Google Sheets setup
# =========================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Users sheet to store chat_ids for daily reminders
def get_or_create_users_ws(spreadsheet):
    try:
        return spreadsheet.worksheet("Users")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="Users", rows=1000, cols=2)
        ws.update("A1:B1", [["chat_id", "first_seen"]])
        return ws

def ensure_user_in_users_ws(users_ws, chat_id: int):
    """Add chat_id to Users sheet if not present."""
    values = users_ws.get_all_values()
    existing_ids = {row[0] for row in values[1:]} if len(values) > 1 else set()
    if str(chat_id) not in existing_ids:
        users_ws.append_row([str(chat_id), datetime.utcnow().isoformat() + "Z"])

def get_all_chat_ids(users_ws):
    values = users_ws.get_all_values()
    if len(values) <= 1:
        return []
    return [int(row[0]) for row in values[1:] if row and row[0].strip().isdigit()]

# =========================
# UI helpers
# =========================
def build_keyboard(scores_for_user: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for act in ACTIVITIES:
        val = scores_for_user.get(act, 0)
        keyboard.append([
            InlineKeyboardButton(f"{act} {val}", callback_data=f"{act}_{val}")
        ])
    keyboard.append([
        InlineKeyboardButton("Reset", callback_data="reset"),
        InlineKeyboardButton("Submit", callback_data="submit"),
    ])
    return InlineKeyboardMarkup(keyboard)

# =========================
# Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    users_ws = context.bot_data["users_ws"]
    ensure_user_in_users_ws(users_ws, chat_id)

    # Initialize scores for this user for the current session
    user_scores[chat_id] = {act: 0 for act in ACTIVITIES}
    await update.message.reply_text(
        "Hello! I will help you track your daily tokens 🌟\n"
        "Tap the buttons to set tokens for each area, then Submit.",
        reply_markup=build_keyboard(user_scores[chat_id]),
    )

async def average(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sheet = context.bot_data["sheet"]
    # Compute averages for the last 7 entries (rows) in the main sheet
    all_values = sheet.get_all_values()
    data_rows = all_values[1:] if len(all_values) > 1 else []
    last_rows = data_rows[-7:] if data_rows else []

    if not last_rows:
        await update.message.reply_text("No data available to calculate averages yet.")
        return

    sums = {act: 0 for act in ACTIVITIES}
    count_rows = len(last_rows)

    for row in last_rows:
        # Expected row: [date, 💪, 💻, 📚, 🧘, 🗣️, 🍲, 🏡]
        for i, act in enumerate(ACTIVITIES):
            try:
                sums[act] += int(row[i + 1])
            except Exception:
                pass

    averages = {act: round(sums[act] / count_rows, 2) for act in ACTIVITIES}
    lines = ["📊 Average tokens for last 7 entries:"]
    for act in ACTIVITIES:
        lines.append(f"{act}: {averages[act]}")
    await update.message.reply_text("\n".join(lines))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    REMINDER_TZ = context.bot_data["reminder_tz"]
    sheet = context.bot_data["sheet"]

    # Ensure a session exists for this chat
    if chat_id not in user_scores:
        user_scores[chat_id] = {act: 0 for act in ACTIVITIES}

    data = query.data

    if data == "submit":
        # Append today's row to sheet
        today = datetime.now(pytz.timezone(REMINDER_TZ)).strftime("%Y-%m-%d")
        values = [user_scores[chat_id].get(act, 0) for act in ACTIVITIES]
        sheet.append_row([today] + values)
        await query.edit_message_text("✅ Tokens saved for today! Use /start to log again.")
        user_scores.pop(chat_id, None)
        return

    if data == "reset":
        user_scores[chat_id] = {act: 0 for act in ACTIVITIES}
        await query.edit_message_reply_markup(reply_markup=build_keyboard(user_scores[chat_id]))
        return

    # data format: "<emoji>_<current_val>"
    try:
        act, count_str = data.split("_", 1)
        current = int(count_str)
    except Exception:
        return

    user_scores[chat_id][act] = current + 1
    await query.edit_message_reply_markup(reply_markup=build_keyboard(user_scores[chat_id]))

# =========================
# Daily reminder job
# =========================
async def send_daily_reminders(app: Application):
    users_ws = app.bot_data["users_ws"]
    reminder_tz = app.bot_data["reminder_tz"]
    # Send the inline keyboard directly so you can log without typing /start
    for chat_id in get_all_chat_ids(users_ws):
        if chat_id not in user_scores:
            user_scores[chat_id] = {act: 0 for act in ACTIVITIES}
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ It's {22 if reminder_tz == 'Europe/Rome' else ''}:00! Time to log your daily tokens.",
                reply_markup=build_keyboard(user_scores[chat_id]),
            )
        except Exception:
            # If bot cannot send (blocked, etc.), just skip
            pass

# =========================
# Main entry
# =========================
def main():
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    SERVICE_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    REMINDER_TZ = os.getenv("REMINDER_TZ", "Europe/Rome")
    REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "22"))
    REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
    print("ENV VARS:", list(os.environ.keys()))
    if not TELEGRAM_BOT_TOKEN or not SERVICE_JSON or not SPREADSHEET_ID:
        print("ERROR: Missing environment variables!")
        return
    
    # Load JSON credentials from environment variable
    creds_info = json.loads(SERVICE_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, SCOPE)
    client = gspread.authorize(creds)

    # Open the sheet by ID from environment variable
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # Main data sheet (first worksheet) 
    sheet = spreadsheet.sheet1

    users_ws = get_or_create_users_ws(spreadsheet)

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Store references in bot_data for access in handlers
    app.bot_data["sheet"] = sheet
    app.bot_data["users_ws"] = users_ws
    app.bot_data["reminder_tz"] = REMINDER_TZ

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("average", average))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Scheduler with timezone
    scheduler = AsyncIOScheduler(timezone=pytz.timezone(REMINDER_TZ))
    scheduler.add_job(send_daily_reminders, "cron", hour=REMINDER_HOUR, minute=REMINDER_MINUTE, args=[app])
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()