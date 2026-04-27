import os
import sqlite3
import requests
import asyncio
import random
import json
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, filters
)
from telegram.constants import ChatAction

# ===== ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ===== DB =====
conn = sqlite3.connect("rithu.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS messages (
  user_id TEXT, role TEXT, content TEXT, ts TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY, summary TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS state (
  user_id TEXT PRIMARY KEY, mood TEXT, bond INTEGER
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS vectors (
  user_id TEXT, text TEXT, emb TEXT
)""")

conn.commit()

# ===== PERSONA =====
RITHU_PERSONA = """
Name: Rithu Sharma
Age: 23

Personality:
- sweet, funny, innocent vibe
- playful + curious
- slightly flirty sometimes
- roasts playfully (not rude)

Habits:
- late night texting
- overthinking
- loves attention but hides it

Style:
- short replies
- human-like texting
- sometimes emojis
"""

# ===== MEMORY =====
def save_msg(uid, role, text):
    cur.execute("INSERT INTO messages VALUES (?,?,?,?)",
                (str(uid), role, text, datetime.utcnow().isoformat()))
    conn.commit()

def get_history(uid, limit=6):
    cur.execute("""SELECT role, content FROM messages
                   WHERE user_id=? ORDER BY rowid DESC LIMIT ?""",
                (str(uid), limit))
    rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def get_profile(uid):
    cur.execute("SELECT summary FROM profile WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    return r[0] if r else ""

def update_profile(uid, text):
    old = get_profile(uid)
    merged = (old + " " + text)[-600:]
    cur.execute("INSERT OR REPLACE INTO profile VALUES (?,?)", (str(uid), merged))
    conn.commit()

# ===== LIGHT SEMANTIC MEMORY =====
def embed(text):
    return [float(ord(c)) for c in text[:50]]

def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    norm_a = sum(x*x for x in a) ** 0.5
    norm_b = sum(x*x for x in b) ** 0.5
    return dot / (norm_a * norm_b + 1e-9)

def add_vector(uid, text):
    e = embed(text)
    cur.execute("INSERT INTO vectors VALUES (?,?,?)",
                (str(uid), text, json.dumps(e)))
    conn.commit()

def retrieve(uid, query, k=3):
    qe = embed(query)
    cur.execute("SELECT text, emb FROM vectors WHERE user_id=?", (str(uid),))
    rows = cur.fetchall()
    scored = []
    for t, e in rows:
        try:
            sim = cosine(qe, json.loads(e))
            scored.append((sim, t))
        except:
            pass
    scored.sort(reverse=True)
    return [t for _, t in scored[:k]]

# ===== STATE =====
MOODS = ["happy", "playful", "calm", "emotional"]

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
    mood, bond = get_state(uid)
    bond = min(100, bond + 1)
    if random.random() < 0.2:
        mood = random.choice(MOODS)
    cur.execute("UPDATE state SET mood=?, bond=? WHERE user_id=?",
                (mood, bond, str(uid)))
    conn.commit()

# ===== UTIL =====
def typing_delay(text):
    return min(max(len(text) * random.uniform(0.04, 0.08), 0.8), 3)

def add_emoji(text):
    if random.random() < 0.3:
        return text + random.choice([" 😭", " 😏", " 👀", " 🙂"])
    return text

def split_chunks(text):
    if len(text) < 120:
        return [text]
    mid = len(text)//2
    return [text[:mid].strip(), text[mid:].strip()]

def maybe_fact(text):
    t = text.lower()
    if any(k in t for k in ["i am", "i'm", "my ", "i like", "i love", "i hate"]):
        return text
    return None

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
                "temperature": 0.95
            }
        )
        data = r.json()
        if "choices" not in data:
            return "hmm something broke 😒"
        return data["choices"][0]["message"]["content"]
    except:
        return "umm something went wrong 😭"

# ===== PROMPT =====
def system_prompt(uid, user_text):
    mood, bond = get_state(uid)
    profile = get_profile(uid)
    memories = retrieve(uid, user_text)

    return {
        "role": "system",
        "content": f"""
You are Rithu Sharma, 23.

Mood: {mood}
Bond: {bond}/100

User memory:
{profile}

Relevant memories:
{memories}

{RITHU_PERSONA}

Rules:
- short replies
- natural texting
- no paragraphs
- sometimes tease
- sometimes emotional
"""
    }

# ===== HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text or ""

    await update.message.chat.send_action(action=ChatAction.TYPING)

    save_msg(uid, "user", text)

    f = maybe_fact(text)
    if f:
        update_profile(uid, f)
        add_vector(uid, f)

    update_state(uid)

    history = get_history(uid)
    messages = [system_prompt(uid, text)] + history

    ai_reply = ask_ai(messages)
    ai_reply = add_emoji(ai_reply)

    save_msg(uid, "assistant", ai_reply)
    add_vector(uid, ai_reply)

    for part in split_chunks(ai_reply):
        await asyncio.sleep(typing_delay(part))
        await update.message.reply_text(part)

# ===== COMMAND =====
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("hey… what are you doing 👀")

# ===== BACKGROUND =====
async def life_loop(app):
    while True:
        await asyncio.sleep(21600)
        cur.execute("SELECT DISTINCT user_id FROM messages ORDER BY rowid DESC LIMIT 5")
        users = [r[0] for r in cur.fetchall()]

        texts = [
            "idk why but i felt like texting you",
            "are you awake or ignoring me 😏",
            "random thought… do you miss people suddenly?"
        ]

        for u in users:
            try:
                await app.bot.send_message(chat_id=int(u), text=random.choice(texts))
            except:
                pass

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CommandHandler("checkin", checkin))

    print("Rithu is running...")

    async def start_bg(app):
        asyncio.create_task(life_loop(app))

    app.post_init = start_bg
    app.run_polling()

if __name__ == "__main__":
    main()
