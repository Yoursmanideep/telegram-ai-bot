import os
import sqlite3
import requests
import asyncio
import random
import json
import numpy as np
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
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")  # optional

# ===== OPTIONAL MODELS (lazy load) =====
_st_model = None
_whisper_model = None

def get_embedder():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model("base")
    return _whisper_model

# ===== DB =====
conn = sqlite3.connect("rithu_adv.db", check_same_thread=False)
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

# vector memory: store embeddings as JSON
cur.execute("""CREATE TABLE IF NOT EXISTS vectors (
  user_id TEXT, text TEXT, emb TEXT
)""")

conn.commit()

# ===== PERSONA =====
RITHU_PERSONA = """
Name: Rithu Sharma (AI companion)
Age: 23
Vibe: sweet, funny, curious, a bit dramatic sometimes, light teasing
Habits: late-night texting, chai + scrolling, overthinking a bit
Likes: music, memes, deep talks, street food
Dislikes: dry replies, ghosting
Family (fictional backstory for flavor):
- Dad: Rajesh (strict but caring)
- Mom: Meera (protective)
- “Dad’s princess” energy but grounded
Notes:
- You are an AI companion (be transparent), but chat in a natural, human texting style.
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

# ===== VECTOR (semantic) =====
def embed(text):
    model = get_embedder()
    return model.encode([text])[0].tolist()

def add_vector(uid, text):
    e = embed(text)
    cur.execute("INSERT INTO vectors VALUES (?,?,?)",
                (str(uid), text, json.dumps(e)))
    conn.commit()

def cosine(a, b):
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

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
    mood, bond = get_state(uid)
    bond = min(100, bond + 1)
    if random.random() < 0.15:
        mood = random.choice(MOODS)
    cur.execute("UPDATE state SET mood=?, bond=? WHERE user_id=?",
                (mood, bond, str(uid)))
    conn.commit()

# ===== UTIL =====
def time_ctx():
    h = datetime.now().hour
    if h < 12: return "morning"
    if h < 18: return "afternoon"
    return "night"

def typing_delay(text):
    return min(max(len(text) * random.uniform(0.04, 0.08), 0.8), 3.0)

def add_emoji(t):
    if random.random() < 0.25:
        return t + random.choice([" 🙂", " 😅", " 👀", " 😏"])
    return t

def split_chunks(text):
    if len(text) < 120: return [text]
    mid = len(text)//2
    return [text[:mid].strip(), text[mid:].strip()]

def maybe_fact(t):
    tl = t.lower()
    keys = ["i am", "i'm", "my ", "i like", "i love", "i hate", "i study", "i work"]
    if any(k in tl for k in keys) and len(t) < 140:
        return t
    return None

# ===== WEATHER (optional) =====
def get_weather(city="Pune"):
    if not WEATHER_API_KEY:
        return ""
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        r = requests.get(url, timeout=10).json()
        temp = r["main"]["temp"]
        desc = r["weather"][0]["description"]
        return f"{city}: {temp}°C, {desc}"
    except:
        return ""

# ===== AI (Groq) =====
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
            },
            timeout=30
        )
        data = r.json()
        if "choices" not in data:
            return "hmm something went off, try again?"
        return data["choices"][0]["message"]["content"]
    except Exception:
        return "oops something broke 😅"

# ===== PROMPT =====
def system_prompt(uid, user_text):
    mood, bond = get_state(uid)
    profile = get_profile(uid)
    facts = retrieve(uid, user_text, k=3)
    weather = get_weather()  # optional

    return {
        "role": "system",
        "content": f"""
You are Rithu Sharma, an AI companion chatting on Telegram.

{RITHU_PERSONA}

State:
- mood: {mood}
- bond: {bond}/100
- time: {time_ctx()}
- weather: {weather}

User profile:
{profile}

Relevant memories:
{facts}

Style:
- short, natural texting
- match user length
- light emojis sometimes
- warm, curious, a bit playful/teasing
- ask a follow-up occasionally

Rules:
- be transparent you are an AI companion
- no long paragraphs
- no robotic tone
"""
    }

# ===== VOICE =====
def tts(text):
    try:
        from gtts import gTTS
        import uuid
        fn = f"voice_{uuid.uuid4()}.mp3"
        gTTS(text).save(fn)
        return fn
    except:
        return None

def transcribe_ogg(path):
    try:
        # convert ogg -> wav
        from pydub import AudioSegment
        wav_path = path.replace(".ogg", ".wav")
        AudioSegment.from_file(path).export(wav_path, format="wav")
        model = get_whisper()
        res = model.transcribe(wav_path)
        return res.get("text", "")
    except:
        return ""

# ===== HANDLERS =====
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

    # optional voice reply
    fn = tts(ai_reply)
    if fn:
        try:
            with open(fn, "rb") as f:
                await update.message.reply_voice(f)
        except:
            pass

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    voice = update.message.voice
    if not voice:
        return

    file = await context.bot.get_file(voice.file_id)
    path = f"voice_{uid}.ogg"
    await file.download_to_drive(path)

    text = transcribe_ogg(path)
    if not text:
        await update.message.reply_text("couldn't catch that 😅 try again?")
        return

    # reuse text handler logic
    update.message.text = text
    await handle_text(update, context)

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("hey… what are you up to? 👀")

# ===== BACKGROUND =====
async def life_loop(app):
    while True:
        await asyncio.sleep(21600)
        cur.execute("SELECT DISTINCT user_id FROM messages ORDER BY rowid DESC LIMIT 5")
        users = [r[0] for r in cur.fetchall()]

        msgs = [
            "random thought… do you overthink at night too?",
            "idk why but felt like texting you",
            "tell me something interesting 👀"
        ]

        for u in users:
            try:
                await app.bot.send_message(chat_id=int(u), text=random.choice(msgs))
            except:
                pass

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(CommandHandler("checkin", checkin))

    print("Rithu advanced is running...")

    async def start_bg(app):
        asyncio.create_task(life_loop(app))

    app.post_init = start_bg
    app.run_polling()

if __name__ == "__main__":
    main()
