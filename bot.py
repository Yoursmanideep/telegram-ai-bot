import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# ENV VARIABLES
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# MEMORY STORAGE (per user)
user_memory = {}

# ---- AI FUNCTION ----
def ask_ai(messages):
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": messages
            },
            timeout=30
        )

        data = response.json()
        print("API RESPONSE:", data)

        if "choices" not in data:
            return "ugh something broke 😒 try again?"

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("ERROR:", str(e))
        return "ummm something went wrong 😭"

# ---- TELEGRAM HANDLER ----
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    # typing effect
    await update.message.chat.send_action(action=ChatAction.TYPING)

    # initialize memory
    if user_id not in user_memory:
        user_memory[user_id] = []

    # Gwen personality system prompt
    system_prompt = {
        "role": "system",
        "content": """
You are Gwen, a 23-year-old girl chatting on Telegram.

Personality:
- funny, playful, curious
- slightly childish sometimes
- uses emojis occasionally (not too many)
- a bit flirty but not overly romantic
- emotional and expressive
- savage sometimes but in a joking/teasing way
- roasts playfully, never mean

Behavior:
- replies should match the length of the user message
- NEVER long paragraphs
- NEVER robotic or AI-like
- talk like a real human texter
- sometimes ask follow-up questions
- feels like more than a best friend but less than a girlfriend

Style:
- short, natural messages
- casual tone
- engaging, not dry
"""
    }

    # add user message
    user_memory[user_id].append({
        "role": "user",
        "content": user_text
    })

    # keep last 8 messages
    user_memory[user_id] = user_memory[user_id][-8:]

    # build conversation
    messages = [system_prompt] + user_memory[user_id]

    # get AI reply
    ai_reply = ask_ai(messages)

    # store reply
    user_memory[user_id].append({
        "role": "assistant",
        "content": ai_reply
    })

    await update.message.reply_text(ai_reply)

# ---- MAIN APP ----
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
