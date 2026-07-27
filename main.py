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

STATE_FILE = "last_tweet_id.txt"

def load_last_tweet_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            val = f.read().strip()
            return val if val else None
    return None

def save_last_tweet_id(tweet_id):
    with open(STATE_FILE, "w") as f:
        f.write(str(tweet_id))
    print(f"Saved state file '{STATE_FILE}' with Tweet ID: {tweet_id}")

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

def fetch_tweet_details_fxtwitter(tweet_id: str):
    """Fetches full tweet metadata and media via FxTwitter/VxTwitter API."""
    for domain in ["api.fxtwitter.com", "api.vxtwitter.com"]:
        url = f"https://{domain}/{TWITTER_TARGET_USER}/status/{tweet_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "tweet" in data:
                    return data["tweet"]
                elif "text" in data:
                    return data
        except Exception as e:
            print(f"Error fetching tweet ID {tweet_id} from {domain}: {e}")
    return None

def fetch_recent_tweets():
    """Fetches recent tweet objects using multiple reliable sources."""
    tweets = []
    
    # Source 1: FxTwitter / VxTwitter Profile APIs
    for domain in ["api.fxtwitter.com", "api.vxtwitter.com"]:
        try:
            print(f"Fetching timeline from https://{domain}/{TWITTER_TARGET_USER}...")
            url = f"https://{domain}/{TWITTER_TARGET_USER}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                fetched = []
                if "tweets" in data and isinstance(data["tweets"], list):
                    fetched = data["tweets"]
                elif "user" in data and "tweets" in data["user"]:
                    fetched = data["user"]["tweets"]
                
                if fetched:
                    print(f"Successfully retrieved {len(fetched)} tweets from {domain}!")
                    return fetched
        except Exception as e:
            print(f"Source {domain} error: {e}")

    # Source 2: Twitter Syndication Feed
    try:
        print("Fetching timeline from Twitter Syndication...")
        syndication_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TWITTER_TARGET_USER}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(syndication_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            found_ids = re.findall(r'/status/(\d+)', resp.text)
            found_ids = list(dict.fromkeys(found_ids))
            print(f"Found {len(found_ids)} Tweet IDs via Syndication.")
            for tid in found_ids[:10]:
                td = fetch_tweet_details_fxtwitter(tid)
                if td:
                    tweets.append(td)
            if tweets:
                return tweets
    except Exception as e:
        print(f"Syndication error: {e}")

    # Source 3: Public RSS Feed Fallbacks
    rss_sources = [
        f"https://rsshub.app/twitter/user/{TWITTER_TARGET_USER}",
        f"https://nitter.poast.org/{TWITTER_TARGET_USER}/rss",
        f"https://xcancel.com/{TWITTER_TARGET_USER}/rss"
    ]
    for rss_url in rss_sources:
        try:
            print(f"Trying RSS feed: {rss_url}")
            feed = feedparser.parse(rss_url)
            if feed.entries:
                print(f"Found {len(feed.entries)} entries in RSS feed!")
                for entry in feed.entries[:10]:
                    match = re.search(r'/status/(\d+)', entry.link)
                    if match:
                        tid = match.group(1)
                        td = fetch_tweet_details_fxtwitter(tid)
                        if td:
                            tweets.append(td)
                if tweets:
                    return tweets
        except Exception as e:
            print(f"RSS error on {rss_url}: {e}")

    return tweets

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
    print(f"=== Starting Twitter Monitor for @{TWITTER_TARGET_USER} ===")
    print(f"Configured Channel: {TELEGRAM_CHANNEL}")
    print(f"Configured Keywords: {KEYWORDS if KEYWORDS else 'None (All tweets match)'}")
    
    last_tweet_id = load_last_tweet_id()
    print(f"Last processed Tweet ID from state: {last_tweet_id}")

    tweets = fetch_recent_tweets()
    if not tweets:
        print("ERROR: Could not fetch any tweets from any source!")
        return

    print(f"Fetched {len(tweets)} tweets. Processing...")

    # Sort tweets from oldest to newest
    tweets_sorted = sorted(tweets, key=lambda x: int(x.get("id", 0)))
    newest_tweet_id_seen = last_tweet_id

    for tweet in tweets_sorted:
        tweet_id = str(tweet.get("id"))
        
        # Skip tweets already processed
        if last_tweet_id and int(tweet_id) <= int(last_tweet_id):
            print(f"Skipping Tweet ID {tweet_id} (already processed in earlier run).")
            continue

        text = tweet.get("text", "")
        print(f"Evaluating Tweet ID {tweet_id}: '{text[:60]}...'")

        # Check keyword filter
        if not KEYWORDS or any(kw in text.lower() for kw in KEYWORDS):
            print(f"-> MATCH FOUND for Tweet ID {tweet_id}!")

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
        else:
            print(f"-> Skipped Tweet ID {tweet_id}: Did not match keywords {KEYWORDS}")

        newest_tweet_id_seen = tweet_id

    if newest_tweet_id_seen and newest_tweet_id_seen != last_tweet_id:
        save_last_tweet_id(newest_tweet_id_seen)

if __name__ == "__main__":
    run()
