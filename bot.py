import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def ask_ai(user_text):
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama3-8b-8192",
            "messages": [
                {"role": "system", "content": "You are a real human chatting casually. Keep it short and natural."},
                {"role": "user", "content": user_text}
            ]
        }
    )

    data = response.json()
    print("API RESPONSE:", data)

    if "choices" not in data:
        return f"Error: {data}"

    return data["choices"][0]["message"]["content"]

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    ai_reply = ask_ai(user_text)
    await update.message.reply_text(ai_reply)

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

print("Bot running...")
app.run_polling()
