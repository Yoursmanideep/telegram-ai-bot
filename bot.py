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
conn = sqlite3.connect("rithu_last.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS state (
    user_id TEXT PRIMARY KEY,
    interaction INTEGER,
    last_seen TEXT,
    last_gap REAL,
    topic TEXT,
    theme TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS messages (
    user_id TEXT, role TEXT, content TEXT
)""")

conn.commit()

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
            "theme": r[5]
        }

    cur.execute("INSERT INTO state VALUES (?,?,?,?,?,?)",
                (str(uid), 0, datetime.utcnow().isoformat(), 0, "", ""))
    conn.commit()
    return get_state(uid)

def update_state(uid, text):
    s = get_state(uid)

    now = datetime.utcnow()
    last = datetime.fromisoformat(s["last_seen"])
    gap = (now - last).total_seconds()

    interaction = s["interaction"] + 1

    words = text.lower().split()
    topic = s["topic"]
    theme = s["theme"]

    if len(words) > 2:
        topic = " ".join(words[:3])

    # recurring theme capture
    if any(w in text.lower() for w in ["movie", "music", "food", "college", "sleep"]):
        theme = text[:40]

    cur.execute("""UPDATE state SET interaction=?, last_seen=?, last_gap=?, topic=?, theme=? 
                   WHERE user_id=?""",
                (interaction, now.isoformat(), gap, topic, theme, str(uid)))
    conn.commit()

# ===== MEMORY =====
def save_msg(uid, role, text):
    cur.execute("INSERT INTO messages VALUES (?,?,?)", (str(uid), role, text))
    conn.commit()

def get_history(uid):
    cur.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY rowid DESC LIMIT 6", (str(uid),))
    rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

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
    if interaction > 12 and random.random() < 0.04:
        return text + random.choice([" 🙂", " 👀"])
    return text

def current_time_mood():
    hour = datetime.now().hour
    if hour < 12:
        return "morning"
    elif hour < 18:
        return "day"
    else:
        return "night"

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
        return "hmm"

# ===== PROMPT =====
def system_prompt(uid):
    s = get_state(uid)
    time_mood = current_time_mood()

    return {
        "role": "system",
        "content": f"""
You are Rithu.

Time: {time_mood}
Topic: {s['topic']}
Recurring theme: {s['theme']}

Behavior:
- short replies only
- casual texting
- sometimes minimal replies
- sometimes light curiosity
- sometimes just reaction

Time behavior:
- morning → lighter tone
- night → slightly calmer, softer

Conversation:
- sometimes bring back topic naturally
- sometimes refer to recurring theme
- don't force it

Rules:
- no paragraphs
- no overacting
- no fake personality
- just talk normally
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

    # offline reaction
    if s["gap"] > 180:
        ai_reply = "you vanished for a bit lol, " + ai_reply

    ai_reply = shorten(ai_reply)
    ai_reply = maybe_emoji(ai_reply, s["interaction"])

    save_msg(uid, "assistant", ai_reply)

    await asyncio.sleep(typing_delay(s["gap"]))
    await update.message.reply_text(ai_reply)

    # occasional follow-up
    if s["interaction"] > 8 and random.random() < 0.12:
        await asyncio.sleep(random.uniform(1.5, 3))
        await update.message.reply_text(random.choice([
            "hmm",
            "anyway",
            "you there?"
        ]))

# ===== PROACTIVE TEXTING =====
async def proactive_loop(app):
    while True:
        await asyncio.sleep(18000)  # every ~5 hours

        cur.execute("SELECT user_id FROM state ORDER BY interaction DESC LIMIT 3")
        users = [r[0] for r in cur.fetchall()]

        msgs = [
            "random thought… do you overthink at night too?",
            "idk why but felt like texting you",
            "what were you doing today?"
        ]

        for u in users:
            try:
                await app.bot.send_message(chat_id=int(u), text=random.choice(msgs))
            except:
                pass

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    async def start_bg(app):
        asyncio.create_task(proactive_loop(app))

    app.post_init = start_bg

    print("Rithu final human layer running...")

    app.run_polling()

if __name__ == "__main__":
    main()
