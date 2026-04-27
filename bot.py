import os
import sqlite3
import requests
import asyncio
import random
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ================= DB =================
conn = sqlite3.connect("rithu.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS messages (user_id TEXT, role TEXT, content TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS profile (user_id TEXT PRIMARY KEY, summary TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS state (user_id TEXT PRIMARY KEY, mood TEXT, bond INTEGER)")
conn.commit()

# ================= MEMORY =================
def save_msg(uid, role, text):
    cur.execute("INSERT INTO messages VALUES (?,?,?)", (str(uid), role, text))
    conn.commit()

def get_history(uid):
    cur.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY rowid DESC LIMIT 6", (str(uid),))
    rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def get_profile(uid):
    cur.execute("SELECT summary FROM profile WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    return r[0] if r else ""

def update_profile(uid, text):
    old = get_profile(uid)
    new = (old + " " + text)[-400:]
    cur.execute("INSERT OR REPLACE INTO profile VALUES (?,?)", (str(uid), new))
    conn.commit()

# ================= STATE =================
MOODS = ["happy", "playful", "calm", "thoughtful"]

def get_state(uid):
    cur.execute("SELECT mood, bond FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    if r:
        return r
    mood = random.choice(MOODS)
    bond = 1
    cur.execute("INSERT INTO state VALUES (?,?,?)", (str(uid), mood, bond))
    conn.commit()
    return mood, bond

def update_state(uid):
    cur.execute("SELECT mood, bond FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    if not r:
        return
    mood, bond = r
    bond = min(100, bond + 1)

    if random.random() < 0.15:
        mood = random.choice(MOODS)

    cur.execute("UPDATE state SET mood=?, bond=? WHERE user_id=?", (mood, bond, str(uid)))
    conn.commit()

# ================= HUMAN TOUCH =================
def typing_delay(text):
    return min(max(len(text) * random.uniform(0.03, 0.07), 0.8), 2.5)

def add_emoji(text):
    if random.random() < 0.25:
        return text + random.choice([" 🙂", " 😅", " 👀", " 😄"])
    return text

# ================= AI =================
def ask_ai(messages):
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": messages,
                "temperature": 0.9
            }
        )
        data = r.json()
        if "choices" not in data:
            return "hmm something went off, try again?"
        return data["choices"][0]["message"]["content"]
    except:
        return "oops something broke 😅"

# ================= PROMPT =================
def system_prompt(uid):
    mood, bond = get_state(uid)
    profile = get_profile(uid)

    return {
        "role": "system",
        "content": f"""
You are Rithu Sharma, 23, chatting casually.

Mood: {mood}
Bond: {bond}/100

User info:
{profile}

Style:
- short replies
- natural texting
- slightly playful
- emotionally aware
- no long paragraphs
"""
    }

# ================= HANDLER =================
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    save_msg(uid, "user", text)
    update_profile(uid, text)
    update_state(uid)

    history = get_history(uid)
    messages = [system_prompt(uid)] + history

    ai_reply = ask_ai(messages)
    ai_reply = add_emoji(ai_reply)

    save_msg(uid, "assistant", ai_reply)

    await asyncio.sleep(typing_delay(ai_reply))
    await update.message.reply_text(ai_reply)

# ================= COMMAND =================
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("hey, what's up?")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_handler(CommandHandler("checkin", checkin))

    print("Rithu is running...")

    app.run_polling()

if __name__ == "__main__":
    main()
