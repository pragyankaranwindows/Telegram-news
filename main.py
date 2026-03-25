import feedparser
import yt_dlp
import os
import asyncio
import json
import re
import requests
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"
CHANNELS_FILE = "channels.json"

last_post_date = None

# ================= STORAGE =================
def load_json(file):
    try:
        if os.path.exists(file):
            with open(file, "r") as f:
                return json.load(f)
    except:
        return []
    return []

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

def load_channels():
    return load_json(CHANNELS_FILE)

def save_channels(channels):
    save_json(CHANNELS_FILE, channels)

# ================= CLEAN =================
def clean_caption(text):
    if not text:
        return ""
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def format_caption(title, source):
    return f"""🔥 {clean_caption(title)}

📺 {source}
🍃 Picka Pi"""

# ================= FETCH =================
def get_all_latest_videos():
    channels = load_channels()
    videos = []

    for channel_id in channels:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:1]:
                link = entry.link

                if "live" in link.lower():
                    continue

                if "watch?v=" in link:
                    vid = link.split("watch?v=")[-1]
                    url = f"https://www.youtube.com/shorts/{vid}"
                else:
                    url = link

                if "shorts" in url:
                    videos.append({
                        "url": url,
                        "title": entry.title,
                        "source": feed.feed.title if "title" in feed.feed else "YouTube"
                    })

        except Exception as e:
            print("⚠️ Feed error:", e)

    import random
    random.shuffle(videos)
    return videos

# ================= DOWNLOAD =================
def download_video(url):
    try:
        ydl_opts = {
            'format': 'best[height<=720][filesize<50M]',
            'outtmpl': 'video.%(ext)s',
            'quiet': True,
            'noplaylist': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return "video.mp4"

    except Exception as e:
        print("❌ Download error:", e)
        return None

# ================= QUEUE =================
def add_to_queue(item):
    queue = load_json(QUEUE_FILE)

    if item["url"] not in [q["url"] for q in queue]:
        queue.append(item)
        save_json(QUEUE_FILE, queue)
        print("📥 Added")

def get_next_from_queue():
    queue = load_json(QUEUE_FILE)
    if queue:
        item = queue.pop(0)
        save_json(QUEUE_FILE, queue)
        return item
    return None

# ================= SEND =================
async def send_video(file_path, caption, bot):
    try:
        with open(file_path, 'rb') as video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=video,
                caption=caption,
                timeout=120
            )
        print("✅ Sent")
    except Exception as e:
        print("❌ Send error:", e)

# ================= COMMANDS =================
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = " ".join(context.args)
    res = requests.get(f"https://wttr.in/{city}?format=3").text
    await update.message.reply_text(res + "\n🍃 Picka Pi")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    links = re.split(r"[,\s]+", " ".join(context.args))
    channels = load_channels()
    added = []

    for link in links:
        try:
            html = requests.get(link).text
            match = re.search(r'"channelId":"(UC[\w-]+)"', html)
            if match:
                cid = match.group(1)
                if cid not in channels:
                    channels.append(cid)
                    added.append(cid)
        except:
            continue

    save_channels(channels)
    await update.message.reply_text("✅ Added:\n" + "\n".join(added) if added else "Nothing added")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = load_channels()

    if context.args:
        idx = int(context.args[0]) - 1
        removed = channels.pop(idx)
        save_channels(channels)
        await update.message.reply_text(f"Removed:\n{removed}")
        return

    msg = "\n".join([f"{i+1}. {c}" for i, c in enumerate(channels)])
    await update.message.reply_text(msg or "No channels")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = load_channels()
    msg = "\n".join([f"{i+1}. {c}" for i, c in enumerate(channels)])
    await update.message.reply_text(msg or "No channels")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Channels: {len(load_channels())}\nQueue: {len(load_json(QUEUE_FILE))}\n🍃 Picka Pi"
    )

# ================= BACKGROUND TASK =================
async def background_loop(app):
    global last_post_date

    bot = app.bot
    posted = set(load_json(POSTED_FILE))

    while True:
        try:
            today = datetime.now().date()

            if last_post_date != today:
                await bot.send_message(chat_id=CHANNEL_ID, text="🍃Picka Pi")
                last_post_date = today

            videos = get_all_latest_videos()

            for v in videos:
                if v["url"] not in posted:
                    add_to_queue(v)
                    posted.add(v["url"])
                    save_json(POSTED_FILE, list(posted))

            item = get_next_from_queue()

            if item:
                path = download_video(item["url"])

                if path:
                    await send_video(path, format_caption(item["title"], item["source"]), bot)

                    if os.path.exists(path):
                        os.remove(path)
                else:
                    print("⏭ Skipped blocked video")

        except Exception as e:
            print("🔥 ERROR:", e)

        await asyncio.sleep(300)

# ================= RUN =================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_channels))
    app.add_handler(CommandHandler("status", status))

    print("🚀 Bot running...")

    # start background task
    asyncio.create_task(background_loop(app))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
