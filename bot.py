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
conn = sqlite3.connect("rithu_final_layer.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS state (
    user_id TEXT PRIMARY KEY,
    interaction INTEGER,
    last_seen TEXT,
    last_gap REAL,
    last_topic TEXT,
    inside_joke TEXT
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
            "gap": r[3],
            "topic": r[4],
            "joke": r[5]
        }

    cur.execute("INSERT INTO state VALUES (?,?,?,?,?,?)",
                (str(uid), 0, datetime.utcnow().isoformat(), 0, "", ""))
    conn.commit()
    return get_state(uid)

def update_state(uid, user_text):
    s = get_state(uid)

    now = datetime.utcnow()
    last = datetime.fromisoformat(s["last_seen"])
    gap = (now - last).total_seconds()

    interaction = s["interaction"] + 1

    # ===== TOPIC TRACKING =====
    topic = s["topic"]
    words = user_text.lower().split()

    if len(words) > 2:
        topic = " ".join(words[:3])  # simple topic capture

    # ===== INSIDE JOKE =====
    joke = s["joke"]
    if "lol" in user_text.lower() or "haha" in user_text.lower():
        joke = user_text[:40]

    cur.execute("""UPDATE state SET interaction=?, last_seen=?, last_gap=?, last_topic=?, inside_joke=? 
                   WHERE user_id=?""",
                (interaction, now.isoformat(), gap, topic, joke, str(uid)))
    conn.commit()

# ===== HUMAN BEHAVIOR =====
def typing_delay(gap):
    base = random.uniform(0.8, 1.8)

    if gap < 5:
        base *= 0.7
    elif gap > 60:
        base += random.uniform(2, 4)

    return base

def shorten(text):
    return text.split(".")[0][:80]

def maybe_emoji(text, interaction):
    if interaction > 10 and random.random() < 0.05:
        return text + random.choice([" 🙂", " 👀"])
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
        return "hmm something broke"

# ===== PROMPT =====
def system_prompt(uid):
    s = get_state(uid)
    i = s["interaction"]

    if i < 4:
        stage = "stranger"
    elif i < 8:
        stage = "warming"
    elif i < 15:
        stage = "comfortable"
    else:
        stage = "friendly"

    return {
        "role": "system",
        "content": f"""
You are Rithu.

Stage: {stage}
Recent topic: {s['topic']}
Inside joke: {s['joke']}

Behavior:
- short replies only (1 line)
- casual texting
- not trying too hard
- sometimes refer to topic casually
- sometimes bring up joke lightly

Offline behavior:
- if user was gone long → slightly acknowledge it casually

Rules:
- no paragraphs
- no dramatic tone
- no forced personality
"""
    }

# ===== HANDLER =====
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    s = get_state(uid)

    save_msg(uid, "user", text)
    update_state(uid, text)

    history = get_history(uid)
    messages = [system_prompt(uid)] + history

    ai_reply = ask_ai(messages)

    # ===== OFFLINE REACTION =====
    if s["gap"] > 120:
        ai_reply = "you disappeared for a bit lol, anyway " + ai_reply

    ai_reply = shorten(ai_reply)
    ai_reply = maybe_emoji(ai_reply, s["interaction"])

    save_msg(uid, "assistant", ai_reply)

    await asyncio.sleep(typing_delay(s["gap"]))
    await update.message.reply_text(ai_reply)

    # ===== DOUBLE TEXT =====
    if s["interaction"] > 6 and random.random() < 0.15:
        await asyncio.sleep(random.uniform(1.5, 3))
        followups = ["hmm", "anyway", "you there?"]
        await update.message.reply_text(random.choice(followups))

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Rithu final realism layer running...")

    app.run_polling()

if __name__ == "__main__":
    main()
