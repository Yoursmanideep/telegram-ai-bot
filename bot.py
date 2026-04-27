import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# ENV VARIABLES (set in Railway)
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ---- AI FUNCTION ----
def ask_ai(user_text):
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a real human chatting casually on Telegram. Keep replies short, natural, and human-like."
                    },
                    {
                        "role": "user",
                        "content": user_text
                    }
                ]
            },
            timeout=30
        )

        data = response.json()
        print("API RESPONSE:", data)

        # Handle errors safely
        if "choices" not in data:
            return f"Error: {data.get('error', data)}"

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("ERROR:", str(e))
        return "Something went wrong. Try again."

# ---- TELEGRAM HANDLER ----
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    ai_reply = ask_ai(user_text)
    await update.message.reply_text(ai_reply)

# ---- MAIN APP ----
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
