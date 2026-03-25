import feedparser
import yt_dlp
import os
import asyncio
import json
import re
import requests
import threading
from datetime import datetime
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

bot = Bot(token=BOT_TOKEN)

QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"
CHANNELS_FILE = "channels.json"

# ================= DAILY TRACK =================
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

# ================= CHANNEL STORAGE =================
def load_channels():
    return load_json(CHANNELS_FILE)

def save_channels(channels):
    save_json(CHANNELS_FILE, channels)

# ================= CAPTION CLEANER =================
def clean_caption(text):
    if not text:
        return ""
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ================= FORMAT =================
def format_caption(title, source):
    clean = clean_caption(title)
    return f"""🔥 {clean}

📺 {source}
🍃 Picka Pi"""

# ================= FETCH YT =================
def get_all_latest_videos():
    channels = load_channels()
    videos = []

    for channel_id in channels:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:1]:
                link = entry.link

                # Skip live videos
                if "live" in link.lower():
                    continue

                if "watch?v=" in link:
                    video_id = link.split("watch?v=")[-1]
                    shorts_url = f"https://www.youtube.com/shorts/{video_id}"
                else:
                    shorts_url = link

                if "shorts" in shorts_url:
                    videos.append({
                        "url": shorts_url,
                        "title": entry.title,
                        "source": feed.feed.title if "title" in feed.feed else "YouTube"
                    })

        except Exception as e:
            print(f"⚠️ Channel error: {channel_id} → {e}")

    import random
    random.shuffle(videos)

    return videos

# ================= DOWNLOAD =================
def download_video(url):
    try:
        ydl_opts = {
            'format': 'best[height<=720][filesize<50M]',
            'outtmpl': 'video.%(ext)s',
            'quiet': True
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
        print("📥 Added to queue")

def get_next_from_queue():
    queue = load_json(QUEUE_FILE)
    if queue:
        item = queue.pop(0)
        save_json(QUEUE_FILE, queue)
        return item
    return None

# ================= SEND =================
async def send_video(file_path, caption):
    try:
        with open(file_path, 'rb') as video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=video,
                caption=caption,
                timeout=120
            )
        print("✅ Sent")
        return True
    except Exception as e:
        print("❌ Send error:", e)
        return False

# ================= COMMANDS =================

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("❌ Use: /weather city")
            return

        city = " ".join(context.args)
        res = requests.get(f"https://wttr.in/{city}?format=3").text
        await update.message.reply_text(f"{res}\n🍃 Picka Pi")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("❌ Use: /add <links>")
            return

        input_text = " ".join(context.args)
        links = re.split(r"[,\s]+", input_text)

        channels = load_channels()
        added = []

        for link in links:
            try:
                html = requests.get(link).text
                match = re.search(r'"channelId":"(UC[\w-]+)"', html)

                if match:
                    channel_id = match.group(1)
                    if channel_id not in channels:
                        channels.append(channel_id)
                        added.append(channel_id)
            except:
                continue

        save_channels(channels)

        await update.message.reply_text("✅ Added:\n" + "\n".join(added) if added else "Nothing added")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = load_channels()

    if not channels:
        await update.message.reply_text("📭 No channels")
        return

    if context.args:
        try:
            index = int(context.args[0]) - 1
            removed = channels.pop(index)
            save_channels(channels)
            await update.message.reply_text(f"✅ Removed:\n{removed}")
            return
        except:
            await update.message.reply_text("❌ Use: /remove 1")
            return

    msg = "🗑 Select:\n\n"
    for i, ch in enumerate(channels, start=1):
        msg += f"{i}. {ch}\n"

    await update.message.reply_text(msg)

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = load_channels()

    if not channels:
        await update.message.reply_text("📭 No channels")
        return

    msg = "📺 Channels:\n\n"
    for i, ch in enumerate(channels, start=1):
        msg += f"{i}. {ch}\n"

    await update.message.reply_text(msg)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = load_channels()
    queue = load_json(QUEUE_FILE)

    await update.message.reply_text(
        f"📊 Status\n\nChannels: {len(channels)}\nQueue: {len(queue)}\n🍃 Picka Pi"
    )

# ================= TELEGRAM BOT =================
def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_channels))
    app.add_handler(CommandHandler("status", status))

    print("🤖 Command bot running...")
    app.run_polling()

# ================= MAIN LOOP =================
async def main():
    global last_post_date

    print("🚀 YT Bot Running...")

    posted = set(load_json(POSTED_FILE))

    while True:
        try:
            today = datetime.now().date()

            if last_post_date != today:
                await bot.send_message(chat_id=CHANNEL_ID, text="🍃Picka Pi")
                last_post_date = today

            videos = get_all_latest_videos()

            for item in videos:
                if item["url"] not in posted:
                    add_to_queue(item)
                    posted.add(item["url"])
                    save_json(POSTED_FILE, list(posted))

            item = get_next_from_queue()

            if item:
                file_path = download_video(item["url"])

                if file_path:
                    await send_video(file_path, format_caption(item["title"], item["source"]))
                    await asyncio.sleep(2)

                    if os.path.exists(file_path):
                        os.remove(file_path)

        except Exception as e:
            print("🔥 ERROR:", e)

        await asyncio.sleep(300)

# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    asyncio.run(main())