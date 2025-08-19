from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8404658319:AAFxHRR15OS_DrgSUQcQ4GvgG-6gK1IKNFU"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Bot is working.")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.run_polling()