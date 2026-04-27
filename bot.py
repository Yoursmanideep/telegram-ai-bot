import os
import sqlite3
import requests
import asyncio
import random
import json
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ===== DB =====
conn = sqlite3.connect("rithu_real.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS messages (user_id TEXT, role TEXT, content TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS profile (user_id TEXT PRIMARY KEY, summary TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS vectors (user_id TEXT, text TEXT, emb TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS state (user_id TEXT PRIMARY KEY, mood TEXT, bond INTEGER)")
conn.commit()

# ===== MEMORY =====
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

# ===== LIGHT MEMORY =====
def embed(text):
    return [float(ord(c)) for c in text[:40]]

def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = sum(x*x for x in a) ** 0.5
    nb = sum(x*x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)

def add_vector(uid, text):
    cur.execute("INSERT INTO vectors VALUES (?,?,?)", (str(uid), text, json.dumps(embed(text))))
    conn.commit()

def retrieve(uid, query):
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
    return [t for _, t in scored[:3]]

# ===== STATE =====
def get_state(uid):
    cur.execute("SELECT mood, bond FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()
    if r:
        return r

    mood = "neutral"
    bond = 1
    cur.execute("INSERT INTO state VALUES (?,?,?)", (str(uid), mood, bond))
    conn.commit()
    return mood, bond

def update_state(uid, user_text):
    mood, bond = get_state(uid)

    text = user_text.lower()

    # mood based on user message
    if any(w in text for w in ["sad", "tired", "bad", "hurt"]):
        mood = "soft"
    elif any(w in text for w in ["love", "miss", "cute"]):
        mood = "warm"
    elif any(w in text for w in ["lol", "haha"]):
        mood = "playful"
    elif len(text) < 4:
        mood = "dry"
    else:
        mood = "neutral"

    bond = min(100, bond + 1)

    cur.execute("UPDATE state SET mood=?, bond=? WHERE user_id=?", (mood, bond, str(uid)))
    conn.commit()

# ===== HUMAN BEHAVIOR =====
def typing_delay():
    return random.uniform(0.8, 2.2)

def maybe_emoji(text):
    if random.random() < 0.08:
        return text + random.choice([" 🙂", " 👀"])
    return text

def shorten(text):
    if random.random() < 0.2:
        return text.split(".")[0]
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
                "temperature": 0.9
            }
        )
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except:
        return "something broke, try again"

# ===== PROMPT =====
def system_prompt(uid, user_text):
    mood, bond = get_state(uid)
    profile = get_profile(uid)
    memories = retrieve(uid, user_text)

    return {
        "role": "system",
        "content": f"""
You are Rithu.

Not overly expressive. Not a character.

Relationship:
- more than a bestie
- less than a girlfriend

Mood: {mood}
Bond: {bond}/100

Behavior:
- keep replies short
- sometimes dry
- sometimes warm
- sometimes playful
- no forced flirting
- minimal emojis
- talk like a normal person texting

If mood is:
- soft → gentle, caring
- warm → slightly affectionate
- playful → teasing
- dry → short replies

User memory:
{profile}

Relevant:
{memories}
"""
    }

# ===== HANDLER =====
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    save_msg(uid, "user", text)
    update_profile(uid, text)
    update_state(uid, text)

    history = get_history(uid)
    messages = [system_prompt(uid, text)] + history

    ai_reply = ask_ai(messages)
    ai_reply = shorten(ai_reply)
    ai_reply = maybe_emoji(ai_reply)

    save_msg(uid, "assistant", ai_reply)
    add_vector(uid, ai_reply)

    await asyncio.sleep(typing_delay())
    await update.message.reply_text(ai_reply)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Rithu is running...")

    app.run_polling()

if __name__ == "__main__":
    main()
