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
conn = sqlite3.connect("rithu_human.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS memory (
    user_id TEXT,
    content TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS state (
    user_id TEXT PRIMARY KEY,
    mood TEXT,
    bond INTEGER,
    last_seen TEXT,
    emotion INTEGER
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

# IMPORTANT: store meaningful things only
def store_memory(uid, text):
    if len(text) < 6:
        return

    keywords = ["like", "love", "hate", "feel", "sad", "happy", "my", "i am"]
    if any(k in text.lower() for k in keywords):
        cur.execute("INSERT INTO memory VALUES (?,?)", (str(uid), text))
        conn.commit()

def recall_memory(uid):
    cur.execute("SELECT content FROM memory WHERE user_id=? ORDER BY rowid DESC LIMIT 5", (str(uid),))
    return [r[0] for r in cur.fetchall()]

# ===== STATE =====
def get_state(uid):
    cur.execute("SELECT * FROM state WHERE user_id=?", (str(uid),))
    r = cur.fetchone()

    if r:
        return {
            "mood": r[1],
            "bond": r[2],
            "last_seen": r[3],
            "emotion": r[4]
        }

    cur.execute("INSERT INTO state VALUES (?,?,?,?,?)",
                (str(uid), "neutral", 1, datetime.utcnow().isoformat(), 0))
    conn.commit()
    return get_state(uid)

def update_state(uid, text):
    s = get_state(uid)

    now = datetime.utcnow()
    last = datetime.fromisoformat(s["last_seen"])
    gap = (now - last).total_seconds()

    t = text.lower()

    # emotional learning
    if any(w in t for w in ["sad", "tired", "bad", "hurt"]):
        s["emotion"] -= 1
    elif any(w in t for w in ["happy", "good", "love"]):
        s["emotion"] += 1

    # mood
    if s["emotion"] < -2:
        mood = "soft"
    elif s["emotion"] > 2:
        mood = "warm"
    elif "lol" in t or "haha" in t:
        mood = "playful"
    elif len(t) < 4:
        mood = "dry"
    else:
        mood = "neutral"

    # distance
    if gap > 28800:
        mood = "distant"
        s["bond"] = max(1, s["bond"] - 2)

    s["bond"] = min(100, s["bond"] + 1)

    cur.execute("UPDATE state SET mood=?, bond=?, last_seen=?, emotion=? WHERE user_id=?",
                (mood, s["bond"], now.isoformat(), s["emotion"], str(uid)))
    conn.commit()

# ===== HUMAN BEHAVIOR =====
def typing_delay(mood, bond):
    base = random.uniform(0.8, 2.0)

    if mood == "distant":
        base += random.uniform(2, 5)

    if random.random() < 0.2:
        base += random.uniform(2, 6)

    if bond > 60:
        base *= 0.8

    return base

def maybe_emoji(text, mood):
    if mood in ["warm", "playful"] and random.random() < 0.1:
        return text + random.choice([" 🙂", " 👀"])
    return text

def shorten(text):
    if random.random() < 0.25:
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
        return r.json()["choices"][0]["message"]["content"]
    except:
        return "hmm something broke"

# ===== PROMPT =====
def system_prompt(uid, user_text):
    s = get_state(uid)
    memories = recall_memory(uid)

    return {
        "role": "system",
        "content": f"""
You are Rithu.

Relationship:
- close friend (more than bestie, less than girlfriend)

Mood: {s['mood']}
Bond: {s['bond']}

Memories about user:
{memories}

Behavior:
- talk naturally like a human
- short replies
- express emotion when needed (not always)
- be warm when user is emotional
- be normal when nothing special

Important:
- sometimes refer to past conversations naturally
- don't list memories, just weave them casually
- don't overreact
- be real, not dramatic
"""
    }

# ===== HANDLER =====
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    save_msg(uid, "user", text)
    store_memory(uid, text)

    update_state(uid, text)
    s = get_state(uid)

    history = get_history(uid)
    messages = [system_prompt(uid, text)] + history

    ai_reply = ask_ai(messages)
    ai_reply = shorten(ai_reply)
    ai_reply = maybe_emoji(ai_reply, s["mood"])

    save_msg(uid, "assistant", ai_reply)

    await asyncio.sleep(typing_delay(s["mood"], s["bond"]))
    await update.message.reply_text(ai_reply)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Rithu (human memory) running...")

    app.run_polling()

if __name__ == "__main__":
    main()
