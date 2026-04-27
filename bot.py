import os
import sqlite3
import requests
import asyncio
import random
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ===== DB =====
conn = sqlite3.connect("rithu_final_real.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS state (
    user_id TEXT PRIMARY KEY,
    interaction INTEGER,
    last_seen TEXT,
    last_gap REAL
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS messages (
    user_id TEXT, role TEXT, content TEXT
)""")

conn.commit()

# ===== MEMORY =====
def save_msg(uid, role, text):
    cur.execute("INSERT INTO messages VALUES (?,?,?)", (str(uid), role, text))
    conn.commit()

def get_history(uid):
    cur.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY rowid DESC LIMIT 6", (str(uid),))
    rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

# ===== STATE =====
def get_state(uid):
    cur.execute("SELECT * FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()

    if r:
        return {
            "interaction": r[1],
            "last_seen": r[2],
            "gap": r[3]
        }

    cur.execute("INSERT INTO state VALUES (?,?,?,?)",
                (str(uid), 0, datetime.utcnow().isoformat(), 0))
    conn.commit()
    return get_state(uid)

def update_state(uid):
    s = get_state(uid)

    now = datetime.utcnow()
    last = datetime.fromisoformat(s["last_seen"])
    gap = (now - last).total_seconds()

    interaction = s["interaction"] + 1

    cur.execute("UPDATE state SET interaction=?, last_seen=?, last_gap=? WHERE user_id=?",
                (interaction, now.isoformat(), gap, str(uid)))
    conn.commit()

# ===== HUMAN TOUCH =====
def typing_delay(gap):
    base = random.uniform(0.8, 1.6)

    if gap < 5:
        base *= 0.7  # fast reply → faster response
    elif gap > 60:
        base += random.uniform(1.5, 3)

    return base

def shorten(text):
    return text.split(".")[0][:100]

def maybe_emoji(text, interaction):
    if interaction > 10 and random.random() < 0.05:
        return text + random.choice([" 🙂", " 👀"])
    return text

# ===== CONVERSATION IMPROVEMENT =====
def improve_reply(text):
    # avoid dead replies
    if len(text.split()) < 3:
        text += " lol"

    # sometimes continue convo
    if random.random() < 0.4:
        text += random.choice([
            " what about you",
            " you into that",
            " btw what do you usually do",
            " idk why that sounds interesting",
            " or is it just me"
        ])

    return text

# ===== AI =====
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
                "temperature": 0.85
            }
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return "hmm idk what happened"

# ===== PROMPT =====
def system_prompt(uid):
    s = get_state(uid)
    i = s["interaction"]

    if i < 4:
        stage = "stranger"
    elif i < 8:
        stage = "warming"
    else:
        stage = "comfortable"

    return {
        "role": "system",
        "content": f"""
You are Rithu.

Stage: {stage}

Personality:
- friendly, kind
- slightly funny sometimes
- curious but not clingy

Conversation:
- short replies (1–2 lines)
- never one-word replies
- sometimes ask back
- sometimes add small new topic
- sometimes just react

Style:
- casual texting
- not over-explaining
- not acting like a character

Behavior:
- stranger → simple replies
- warming → a bit curious
- comfortable → relaxed, natural, slightly playful

Important:
- don’t be dry
- don’t force questions every time
- don’t overtalk
- keep conversation flowing naturally
"""
    }

# ===== HANDLER =====
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    s = get_state(uid)

    save_msg(uid, "user", text)
    update_state(uid)

    history = get_history(uid)
    messages = [system_prompt(uid)] + history

    ai_reply = ask_ai(messages)

    ai_reply = shorten(ai_reply)
    ai_reply = improve_reply(ai_reply)
    ai_reply = maybe_emoji(ai_reply, s["interaction"])

    save_msg(uid, "assistant", ai_reply)

    await asyncio.sleep(typing_delay(s["gap"]))
    await update.message.reply_text(ai_reply)

    # ===== DOUBLE TEXT (human behavior) =====
    if s["interaction"] > 6 and random.random() < 0.12:
        await asyncio.sleep(random.uniform(1.5, 3))
        await update.message.reply_text(random.choice([
            "hmm",
            "anyway",
            "you there?"
        ]))

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Rithu (real convo mode) running...")

    app.run_polling()

if __name__ == "__main__":
    main()
