import os
import sqlite3
import requests
import asyncio
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatAction

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "false").lower() == "true"

# ========= DB (persistent memory) =========
conn = sqlite3.connect("gwen_memory.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS messages (
  user_id TEXT,
  role TEXT,
  content TEXT,
  ts TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS facts (
  user_id TEXT,
  fact TEXT,
  ts TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY,
  summary TEXT
)
""")

conn.commit()


# ========= MEMORY HELPERS =========
def save_message(user_id, role, content):
    cur.execute(
        "INSERT INTO messages VALUES (?,?,?,?)",
        (str(user_id), role, content, datetime.utcnow().isoformat())
    )
    conn.commit()


def get_recent(user_id, limit=10):
    cur.execute("""
        SELECT role, content FROM messages
        WHERE user_id=?
        ORDER BY rowid DESC LIMIT ?
    """, (str(user_id), limit))
    rows = cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def add_fact(user_id, text):
    cur.execute(
        "INSERT INTO facts VALUES (?,?,?)",
        (str(user_id), text, datetime.utcnow().isoformat())
    )
    conn.commit()


def get_facts(user_id, limit=8):
    cur.execute("""
        SELECT fact FROM facts
        WHERE user_id=?
        ORDER BY rowid DESC LIMIT ?
    """, (str(user_id), limit))
    return [r[0] for r in cur.fetchall()]


def get_profile(user_id):
    cur.execute("SELECT summary FROM profile WHERE user_id=?", (str(user_id),))
    r = cur.fetchone()
    return r[0] if r else ""


def update_profile(user_id, text):
    old = get_profile(user_id)
    merged = (old + " " + text)[-600:]
    cur.execute(
        "INSERT OR REPLACE INTO profile (user_id, summary) VALUES (?,?)",
        (str(user_id), merged)
    )
    conn.commit()


# simple heuristic to capture useful facts
def maybe_extract_fact(text: str):
    t = text.lower()
    keys = ["i am", "i'm", "my ", "i like", "i love", "i hate", "i study", "i work"]
    if any(k in t for k in keys) and len(text) < 120:
        return text
    return None


# ========= GWEN PROFILE =========
GWEN_PROFILE = """
Name: Rithu Sharma
Age: 23
Hometown: Pune
Height: 5'4"

Personality:
- playful, curious, slightly chaotic
- emotionally expressive, warm
- a bit flirty (not over the top)
- playful roasts sometimes (never mean)

Habits:
- late-night texting
- overthinking a bit
- loves teasing friends

Likes:
- music, memes, chai, late talks

Dislikes:
- dry replies, being ignored

Family:
- Dad: Rajesh Sharma
- Mom: Meera Sharma

Background:
- School: St. Mary's
- College: BBA
- was the “talkative kid”
"""

# ========= SYSTEM PROMPT =========
def build_system(user_id):
    facts = "\n".join(get_facts(user_id))
    profile = get_profile(user_id)

    return {
        "role": "system",
        "content": f"""
You are Gwen (23). You are NOT an AI.

{GWEN_PROFILE}

Memory about user:
{profile}

Recent known facts about user:
{facts}

Tone:
- short replies only
- match user message length
- natural texting style
- no long paragraphs

Behavior:
- curious, asks questions
- sometimes playful roast
- emotional + expressive
- occasional emojis (not too many)
- more than a bestie, less than a girlfriend

Daily-life feel:
- sometimes mention what you're doing (studying, chilling, bored, etc.)
- feel like a real person living a normal day

Rules:
- never say you are AI
- never write long paragraphs
- never be robotic
"""
    }


# ========= AI =========
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
            },
            timeout=30
        )
        data = r.json()
        print("API:", data)

        if "choices" not in data:
            return "ugh it glitched 😒 try again?"

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("ERR:", e)
        return "umm something broke 😭"


# ========= OPTIONAL VOICE =========
def tts_file(text):
    try:
        from gtts import gTTS
        import uuid
        fn = f"voice_{uuid.uuid4()}.mp3"
        gTTS(text).save(fn)
        return fn
    except Exception as e:
        print("TTS err:", e)
        return None


# ========= HANDLERS =========
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    await update.message.chat.send_action(action=ChatAction.TYPING)

    save_message(user_id, "user", user_text)

    fact = maybe_extract_fact(user_text)
    if fact:
        add_fact(user_id, fact)
        update_profile(user_id, fact)

    history = get_recent(user_id, 10)
    system = build_system(user_id)
    messages = [system] + history

    ai_reply = ask_ai(messages)

    save_message(user_id, "assistant", ai_reply)

    # send text
    await update.message.reply_text(ai_reply)

    # optional voice
    if ENABLE_VOICE:
        fn = tts_file(ai_reply)
        if fn:
            try:
                with open(fn, "rb") as f:
                    await update.message.reply_voice(f)
            except Exception:
                pass


# simple command to simulate “she checks on you”
async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("hey… you went quiet 👀 what you doing?")


# ========= DAILY-LIFE SIMULATION =========
async def daily_ping(app):
    while True:
        try:
            # runs every 6 hours
            await asyncio.sleep(21600)

            # pick last active users (simple approach)
            cur.execute("""
                SELECT DISTINCT user_id FROM messages
                ORDER BY rowid DESC LIMIT 10
            """)
            users = [r[0] for r in cur.fetchall()]

            for uid in users:
                try:
                    await app.bot.send_message(
                        chat_id=int(uid),
                        text="random thought… do you ever overthink at night or is it just me 😭"
                    )
                except Exception:
                    pass
        except Exception as e:
            print("ping err:", e)


# ========= MAIN =========
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_handler(CommandHandler("checkin", checkin))

    print("Gwen is alive…")

    # background task
    app.job_queue.run_once(lambda *_: asyncio.create_task(daily_ping(app)), 1)

    app.run_polling()


if __name__ == "__main__":
    main()
