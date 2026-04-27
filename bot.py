import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def ask_ai(user_text):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "telegram-bot"
        },
        json={
            "model": "openrouter/auto",
            "messages": [
                {"role": "system", "content": "You are a real human chatting casually."},
                {"role": "user", "content": user_text}
            ]
        }
    )

    data = response.json()
    print("API RESPONSE:", data)  # VERY IMPORTANT

    if "choices" not in data:
        return f"Error from AI: {data}"

    return data["choices"][0]["message"]["content"]

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    ai_reply = ask_ai(user_text)
    await update.message.reply_text(ai_reply)

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

print("Bot running...")
app.run_polling()
