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

# ================= DATABASE =================
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
    new = (old + " " + text)[-500:]
    cur.execute("INSERT OR REPLACE INTO profile VALUES (?,?)", (str(uid), new))
    conn.commit()

# ================= STATE =================
def get_state(uid):
    cur.execute("SELECT mood, bond FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    if r:
        return r
    mood = random.choice(["happy", "playful", "low", "flirty"])
    bond = 1
    cur.execute("INSERT INTO state VALUES (?,?,?)", (str(uid), mood, bond))
    conn.commit()
    return mood, bond

def update_bond(uid, text):
    cur.execute("SELECT bond FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    if r:
        bond = min(100, r[1] + 1)
        cur.execute("UPDATE state SET bond=? WHERE user_id=?", (bond, str(uid)))
        conn.commit()

# ================= TIME =================
def get_time_context():
    h = datetime.now().hour
    if h < 12:
        return "morning"
    elif h < 18:
        return "afternoon"
    return "night"

# ================= AI =================
def ask_ai(messages):
    try:
        res = requests.post(
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

        data = res.json()
        if "choices" not in data:
            return "ugh something broke 😒"

        return data["choices"][0]["message"]["content"]

    except:
        return "umm something went wrong 😭"

# ================= SYSTEM PROMPT =================
def system_prompt(uid):
    mood, bond = get_state(uid)
    profile = get_profile(uid)
    time_ctx = get_time_context()

    return {
        "role": "system",
        "content": f"""
You are Rithu Sharma, 23.

Personality:
- playful, emotional, curious
- slightly flirty
- sometimes savage (fun way)

Mood: {mood}
Bond: {bond}/100
Time: {time_ctx}

User memory:
{profile}

Rules:
- short replies only
- natural texting style
- no paragraphs
- sometimes ask questions
"""
    }

# ================= HANDLER =================
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    await asyncio.sleep(random.uniform(1, 3))

    save_msg(uid, "user", text)
    update_profile(uid, text)
    update_bond(uid, text)

    history = get_history(uid)
    messages = [system_prompt(uid)] + history

    ai_reply = ask_ai(messages)

    save_msg(uid, "assistant", ai_reply)

    await update.message.reply_text(ai_reply)

# ================= COMMAND =================
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("hey… what are you doing rn 👀")

# ================= LIFE LOOP =================
async def life_loop(app):
    while True:
        await asyncio.sleep(21600)

        cur.execute("SELECT DISTINCT user_id FROM messages ORDER BY rowid DESC LIMIT 5")
        users = [r[0] for r in cur.fetchall()]

        for u in users:
            try:
                await app.bot.send_message(
                    chat_id=int(u),
                    text="random thought… do you overthink at night too? 😭"
                )
            except:
                pass

# ================= MAIN =================
async def start():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_handler(CommandHandler("checkin", checkin))

    print("Rithu is alive...")

    asyncio.create_task(life_loop(app))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(start())
