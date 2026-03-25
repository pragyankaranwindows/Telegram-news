import feedparser
import yt_dlp
import os
import asyncio
import json
import re
import requests
from datetime import datetime
from telegram.ext import Application
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

QUEUE_FILE = "queue.json"
POSTED_FILE = "posted.json"
CHANNELS_FILE = "channels.json"

last_post_date = None

# ================= COOKIE SETUP =================
def setup_cookies():
    data = os.getenv("COOKIE_DATA")
    if data:
        with open("cookies.txt", "w") as f:
            f.write(data)
        print("✅ Cookies loaded")

setup_cookies()

# ================= STORAGE =================
def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return []

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

def load_channels():
    return load_json(CHANNELS_FILE)

# ================= CLEAN =================
def clean_caption(text):
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"@\w+", "", text)
    return text.strip()

def format_caption(title, source):
    return f"{clean_caption(title)}\n\n📢 {source}\n🍃 Picka Pi"

# ================= CLASSIFY =================
def classify_content(link, title):
    t = title.lower()

    if any(x in t for x in ["buy", "sale", "offer", "discount", "subscribe"]):
        return "skip"

    if "/post/" in link:
        return "post"

    if "shorts/" in link:
        return "short"

    if "watch?v=" in link:
        return "video"

    return "skip"

# ================= FETCH =================
def get_content():
    items = []
    for cid in load_channels():
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")

        for entry in feed.entries[:3]:
            link = entry.link
            title = entry.title
            source = feed.feed.title if "title" in feed.feed else "YouTube"

            ctype = classify_content(link, title)
            if ctype == "skip":
                continue

            if "watch?v=" in link:
                vid = link.split("watch?v=")[-1]
                link = f"https://www.youtube.com/watch?v={vid}"

            items.append({
                "type": ctype,
                "url": link,
                "title": title,
                "source": source,
                "retry": 0
            })

    return items

# ================= DOWNLOAD =================
def download_video(url, fallback=False):
    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best' if fallback else 'bestvideo+bestaudio/best',
            'outtmpl': 'video.%(ext)s',
            'cookiefile': 'cookies.txt',
            'quiet': True,
            'merge_output_format': 'mp4',
            'sleep_interval': 3,
            'max_sleep_interval': 6
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return "video.mp4"

    except Exception as e:
        print("❌ Download error:", e)
        return None

# ================= COMMUNITY FETCH =================
def fetch_post(url):
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text

        text_match = re.search(r'"contentText":\{"runs":\[\{"text":"(.*?)"\}', html)
        text = text_match.group(1) if text_match else ""

        img_match = re.search(r'"url":"(https://i.ytimg.com/.*?)"', html)
        img = img_match.group(1).replace("\\u0026", "&") if img_match else None

        return text, img

    except:
        return None, None

# ================= QUEUE =================
def add_to_queue(item):
    q = load_json(QUEUE_FILE)
    if item["url"] not in [x["url"] for x in q]:
        q.append(item)
        save_json(QUEUE_FILE, q)
        print("📥 Added")

def get_next():
    q = load_json(QUEUE_FILE)
    if q:
        item = q.pop(0)
        save_json(QUEUE_FILE, q)
        return item
    return None

# ================= WORKER =================
async def worker(app):
    global last_post_date
    bot = app.bot
    posted = set(load_json(POSTED_FILE))

    while True:
        try:
            today = datetime.now().date()
            if last_post_date != today:
                await bot.send_message(chat_id=CHANNEL_ID, text="🍃Picka Pi")
                last_post_date = today

            for item in get_content():
                if item["url"] not in posted:
                    add_to_queue(item)
                    posted.add(item["url"])
                    save_json(POSTED_FILE, list(posted))

            item = get_next()

            if item:
                await asyncio.sleep(5)

                # ===== VIDEO / SHORT =====
                if item["type"] in ["video", "short"]:
                    path = download_video(item["url"])

                    if not path:
                        path = download_video(item["url"], fallback=True)

                    if path and os.path.exists(path):
                        with open(path, "rb") as v:
                            await bot.send_video(
                                chat_id=CHANNEL_ID,
                                video=v,
                                caption=format_caption(item["title"], item["source"])
                            )
                        os.remove(path)
                        print("🧹 Deleted file")

                    else:
                        if item["retry"] < 2:
                            item["retry"] += 1
                            await asyncio.sleep(30)
                            add_to_queue(item)
                        else:
                            print("❌ Skipped video")

                # ===== COMMUNITY =====
                elif item["type"] == "post":
                    text, img = fetch_post(item["url"])

                    caption = format_caption(text or item["title"], item["source"])

                    if img:
                        await bot.send_photo(chat_id=CHANNEL_ID, photo=img, caption=caption)
                    else:
                        await bot.send_message(chat_id=CHANNEL_ID, text=caption)

        except Exception as e:
            print("🔥 ERROR:", e)

        await asyncio.sleep(240)

# ================= START =================
async def post_init(app):
    asyncio.create_task(worker(app))

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    print("🚀 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
