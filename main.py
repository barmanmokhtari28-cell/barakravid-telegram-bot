import os
import re
import time
import requests
import feedparser
from deep_translator import GoogleTranslator

# --- Configuration (Loaded from GitHub Repository Secrets) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@secretollah")
TWITTER_TARGET_USER = os.getenv("TWITTER_TARGET_USER", "barakravid")
KEYWORDS_RAW = os.getenv("KEYWORDS", "")
KEYWORDS = [k.strip().lower() for k in KEYWORDS_RAW.split(",") if k.strip()]

NITTER_INSTANCES = [
    f"https://nitter.poast.org/{TWITTER_TARGET_USER}/rss",
    f"https://nitter.privacydev.net/{TWITTER_TARGET_USER}/rss",
    f"https://xcancel.com/{TWITTER_TARGET_USER}/rss"
]

STATE_FILE = "last_tweet_id.txt"

def load_last_tweet_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return None

def save_last_tweet_id(tweet_id):
    with open(STATE_FILE, "w") as f:
        f.write(str(tweet_id))

def escape_html(text: str) -> str:
    """Escapes HTML special characters for Telegram API."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def translate_if_needed(text: str, tweet_lang: str = None) -> tuple[str, bool]:
    """Translates non-English text to English."""
    if tweet_lang and tweet_lang.lower() == 'en':
        return text, False

    try:
        translator = GoogleTranslator(source='auto', target='en')
        translated = translator.translate(text)
        if translated and translated.strip().lower() != text.strip().lower():
            return translated, True
        return text, False
    except Exception as e:
        print(f"Translation error: {e}")
        return text, False

def fetch_recent_tweet_ids(username: str) -> list:
    """Fetches recent tweet IDs using Twitter Official Syndication + Fallback Nitter."""
    tweet_ids = []
    
    # Method 1: Official Twitter Syndication Feed
    syndication_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(syndication_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            found_ids = re.findall(r'/status/(\d+)', resp.text)
            for tid in found_ids:
                if tid not in tweet_ids:
                    tweet_ids.append(tid)
            print(f"Found {len(tweet_ids)} tweet IDs via Twitter Syndication.")
    except Exception as e:
        print(f"Syndication fetch error: {e}")

    # Method 2: Fallback Nitter RSS
    if not tweet_ids:
        for rss_url in NITTER_INSTANCES:
            try:
                feed = feedparser.parse(rss_url)
                if feed.entries:
                    for entry in feed.entries:
                        match = re.search(r'/status/(\d+)', entry.link)
                        if match and match.group(1) not in tweet_ids:
                            tweet_ids.append(match.group(1))
                    if tweet_ids:
                        print(f"Found {len(tweet_ids)} tweet IDs via Nitter RSS.")
                        break
            except Exception:
                continue

    return tweet_ids

def fetch_tweet_details_fxtwitter(tweet_id: str):
    """Fetches full tweet text, media, and language info via FxTwitter API."""
    url = f"https://api.fxtwitter.com/{TWITTER_TARGET_USER}/status/{tweet_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 200 and "tweet" in data:
                return data["tweet"]
    except Exception as e:
        print(f"Error fetching tweet ID {tweet_id} from FxTwitter: {e}")
    return None

def format_telegram_caption(tweet_data: dict) -> str:
    """Formats caption using HTML Expandable Blockquote."""
    original_text = tweet_data.get("text", "")
    author_name = tweet_data.get("author", {}).get("name", TWITTER_TARGET_USER)
    author_handle = tweet_data.get("author", {}).get("screen_name", TWITTER_TARGET_USER)
    tweet_id = tweet_data.get("id")
    tweet_lang = tweet_data.get("lang")
    tweet_url = f"https://x.com/{author_handle}/status/{tweet_id}"

    translated_text, was_translated = translate_if_needed(original_text, tweet_lang)

    caption = f"👤 <b><a href='{tweet_url}'>{escape_html(author_name)} (@{escape_html(author_handle)})</a></b>\n\n"
    
    if was_translated:
        caption += f"🌐 <i>[Translated to English]</i>\n"
        caption += f"<blockquote expandable>{escape_html(translated_text)}\n\n"
        caption += f"<b>Original ({tweet_lang or 'Hebrew'}):</b>\n{escape_html(original_text)}</blockquote>\n\n"
    else:
        caption += f"<blockquote expandable>{escape_html(original_text)}</blockquote>\n\n"

    caption += f"🔗 <a href='{tweet_url}'>View on X</a>"
    return caption

def send_to_telegram(caption: str, media_urls: list):
    """Sends caption and media directly to Telegram channel and logs Telegram response."""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    
    photos = [m['url'] for m in media_urls if m['type'] == 'photo']
    videos = [m['url'] for m in media_urls if m['type'] == 'video']

    if not photos and not videos:
        res = requests.post(api_url + "sendMessage", json={
            "chat_id": TELEGRAM_CHANNEL,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        })
    elif len(photos) == 1 and not videos:
        res = requests.post(api_url + "sendPhoto", json={
            "chat_id": TELEGRAM_CHANNEL,
            "photo": photos[0],
            "caption": caption,
            "parse_mode": "HTML"
        })
    elif len(videos) == 1 and not photos:
        res = requests.post(api_url + "sendVideo", json={
            "chat_id": TELEGRAM_CHANNEL,
            "video": videos[0],
            "caption": caption,
            "parse_mode": "HTML"
        })
    else:
        media_group = []
        all_media = photos + videos
        for index, media_url in enumerate(all_media[:10]):
            item = {
                "type": "video" if media_url in videos else "photo",
                "media": media_url
            }
            if index == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media_group.append(item)

        res = requests.post(api_url + "sendMediaGroup", json={
            "chat_id": TELEGRAM_CHANNEL,
            "media": media_group
        })

    print(f"Telegram API Response Status ({res.status_code}): {res.text}")

def run():
    last_tweet_id = load_last_tweet_id()
    print(f"Checking @{TWITTER_TARGET_USER}... Last processed Tweet ID: {last_tweet_id}")

    tweet_ids = fetch_recent_tweet_ids(TWITTER_TARGET_USER)
    if not tweet_ids:
        print("No tweet IDs found.")
        return

    # Process oldest first
    tweet_ids_to_process = list(reversed(tweet_ids[:10]))
    newest_tweet_id_seen = last_tweet_id

    for tweet_id in tweet_ids_to_process:
        # Skip if already processed
        if last_tweet_id and int(tweet_id) <= int(last_tweet_id):
            continue

        tweet = fetch_tweet_details_fxtwitter(tweet_id)
        if not tweet:
            continue

        text = tweet.get("text", "")

        if not KEYWORDS or any(kw in text.lower() for kw in KEYWORDS):
            print(f"Match found! Processing Tweet ID: {tweet_id}")

            media_list = []
            media_data = tweet.get("media", {})
            if "photos" in media_data and media_data["photos"]:
                for photo in media_data["photos"]:
                    media_list.append({"type": "photo", "url": photo["url"]})
            if "videos" in media_data and media_data["videos"]:
                for video in media_data["videos"]:
                    media_list.append({"type": "video", "url": video["url"]})

            caption = format_telegram_caption(tweet)
            send_to_telegram(caption, media_list)

        newest_tweet_id_seen = tweet_id

    if newest_tweet_id_seen and newest_tweet_id_seen != last_tweet_id:
        save_last_tweet_id(newest_tweet_id_seen)

if __name__ == "__main__":
    run()
