import os
import re
import requests
from curl_cffi import requests as cf_requests
from deep_translator import GoogleTranslator

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@secretollah")
TWITTER_TARGET_USER = os.getenv("TWITTER_TARGET_USER", "barakravid")

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
    print(f"💾 Updated state file '{STATE_FILE}' with Tweet ID: {tweet_id}")

def escape_html(text: str) -> str:
    """Escapes HTML special characters for Telegram API."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def translate_if_needed(text: str, tweet_lang: str = None) -> tuple[str, bool]:
    """Translates non-Persian text into Persian (Farsi)."""
    if tweet_lang and tweet_lang.lower() == 'fa':
        return text, False

    try:
        translator = GoogleTranslator(source='auto', target='fa')
        translated = translator.translate(text)
        if translated and translated.strip() != text.strip():
            return translated, True
        return text, False
    except Exception as e:
        print(f"Translation notice: {e}")
        return text, False

def extract_tweet_ids(text: str) -> list[str]:
    """Pulls tweet IDs out of HTML, RSS XML, or JSON response bodies."""
    ids = []
    patterns = [
        r'status\\?/(\d+)',
        r'"id_str"\s*:\s*"(\d+)"',
        r'statuses/(\d+)',
    ]
    for pattern in patterns:
        for tid in re.findall(pattern, text):
            if tid not in ids:
                ids.append(tid)
    return ids

def fetch_tweet_details_fxtwitter(tweet_id: str):
    """Fetches full tweet metadata and media via FxTwitter / VxTwitter API."""
    for domain in ["api.fxtwitter.com", "api.vxtwitter.com"]:
        url = f"https://{domain}/{TWITTER_TARGET_USER}/status/{tweet_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "tweet" in data:
                    return data["tweet"]
        except Exception as e:
            print(f"FxTwitter API notice for ID {tweet_id} on {domain}: {e}")
    return None

def fetch_recent_tweet_ids():
    """Multi-tiered fetch strategy to overcome Twitter / GitHub Actions IP blocks."""
    tweet_ids = []

    # --------------------------------------------------------------------------
    # Method 1: Nitter Public RSS Feeds
    # --------------------------------------------------------------------------
    # Nitter instances bypass Twitter's web bot-detection and deliver standard RSS feeds.
    nitter_instances = [
        f"https://nitter.poast.org/{TWITTER_TARGET_USER}/rss",
        f"https://nitter.privacydev.net/{TWITTER_TARGET_USER}/rss",
        f"https://nitter.lucabased.xyz/{TWITTER_TARGET_USER}/rss",
        f"https://nitter.spaceint.fr/{TWITTER_TARGET_USER}/rss",
        f"https://nitter.x86-64-gmbh.sc/{TWITTER_TARGET_USER}/rss",
    ]
    print("📡 Method 1: Fetching via Nitter RSS feeds...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for nitter_url in nitter_instances:
        try:
            resp = requests.get(nitter_url, headers=headers, timeout=8)
            if resp.status_code == 200 and resp.text.strip():
                found = extract_tweet_ids(resp.text)
                if found:
                    print(f"✅ Success via Nitter ({nitter_url.split('/')[2]})! Found {len(found)} Tweet IDs.")
                    return found
        except Exception:
            continue

    # --------------------------------------------------------------------------
    # Method 2: Twitter Syndication via Public Proxy Relays
    # --------------------------------------------------------------------------
    # Twitter returns empty bodies (200) or 429 errors directly to GitHub Actions IP ranges.
    # Routing the syndication request through a public proxy bridge routes it from a non-datacenter IP.
    target_syndication = f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={TWITTER_TARGET_USER}&dnt=true"
    proxy_urls = [
        f"https://api.allorigins.win/raw?url={target_syndication}",
        f"https://corsproxy.io/?{target_syndication}",
    ]
    print("📡 Method 2: Fetching Syndication via Proxy Bridges...")
    for p_url in proxy_urls:
        try:
            resp = requests.get(p_url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.text.strip():
                found = extract_tweet_ids(resp.text)
                if found:
                    print(f"✅ Success via Proxy Bridge ({p_url.split('/')[2]})! Found {len(found)} Tweet IDs.")
                    return found
        except Exception:
            continue

    # --------------------------------------------------------------------------
    # Method 3: Jina AI Web Reader
    # --------------------------------------------------------------------------
    jina_url = f"https://r.jina.ai/https://x.com/{TWITTER_TARGET_USER}"
    try:
        print(f"📡 Method 3: Fetching via Jina AI Reader ({jina_url})...")
        resp = requests.get(jina_url, headers=headers, timeout=25)
        if resp.status_code == 200:
            found = extract_tweet_ids(resp.text)
            if found:
                print(f"✅ Success via Jina AI Reader! Found {len(found)} Tweet IDs.")
                return found
    except Exception as e:
        print(f"Jina AI Reader notice: {e}")

    # --------------------------------------------------------------------------
    # Method 4: Direct Twitter Syndication with TLS Spoofing (curl_cffi)
    # --------------------------------------------------------------------------
    widget_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Referer": "https://platform.twitter.com/",
        "Accept": "application/json",
    }
    syndication_urls = [
        f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={TWITTER_TARGET_USER}&dnt=true",
        f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TWITTER_TARGET_USER}",
    ]
    print("📡 Method 4: Trying Direct Twitter Syndication Endpoints...")
    for s_url in syndication_urls:
        try:
            resp = cf_requests.get(s_url, headers=widget_headers, impersonate="chrome124", timeout=12)
            if resp.status_code == 200 and resp.text.strip():
                found = extract_tweet_ids(resp.text)
                if found:
                    print(f"✅ Success via direct syndication! Found {len(found)} Tweet IDs.")
                    return found
        except Exception as e:
            print(f"Direct syndication notice: {e}")

    return tweet_ids

def format_telegram_caption(tweet_data: dict) -> str:
    """Formats caption using modern Telegram Rich Text HTML tags."""
    original_text = tweet_data.get("text", "")
    author_name = tweet_data.get("author", {}).get("name", TWITTER_TARGET_USER)
    author_handle = tweet_data.get("author", {}).get("screen_name", TWITTER_TARGET_USER)
    tweet_id = tweet_data.get("id")
    tweet_lang = tweet_data.get("lang")
    tweet_url = f"https://x.com/{author_handle}/status/{tweet_id}"

    translated_text, was_translated = translate_if_needed(original_text, tweet_lang)

    # 1. Author Header
    caption = f"👤 <b><a href='{tweet_url}'>{escape_html(author_name)} (@{escape_html(author_handle)})</a></b>\n\n"
    
    # 2. Body Text (Expandable Blockquote)
    if was_translated:
        caption += f"🌐 <b>ترجمه ماشینی به فارسی:</b>\n"
        caption += f"<blockquote expandable>{escape_html(translated_text)}\n\n"
        caption += f"<b>متن اصلی:</b>\n{escape_html(original_text)}</blockquote>\n\n"
    else:
        caption += f"<blockquote expandable>{escape_html(original_text)}</blockquote>\n\n"

    # 3. Custom Source Link
    caption += f"🔗 <a href='{tweet_url}'>لیـنــک زر این کون‌نشـور</a>\n\n"

    # 4. Custom Footer & Hashtags
    caption += f"🤖 @secretollah\n#راوید\n#اکسیوس"

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

    if res.status_code == 200:
        print(f"✅ SUCCESS: Posted to Telegram channel {TELEGRAM_CHANNEL}!")
    else:
        print(f"❌ TELEGRAM ERROR ({res.status_code}): {res.text}")

def run():
    print("=" * 50)
    print(f"=== Starting Twitter Monitor for @{TWITTER_TARGET_USER} ===")
    print("=" * 50)
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ CRITICAL ERROR: TELEGRAM_BOT_TOKEN secret is empty or missing in GitHub Repository Secrets!")
        return
    if not TELEGRAM_CHANNEL:
        print("❌ CRITICAL ERROR: TELEGRAM_CHANNEL environment variable is missing!")
        return

    print(f"Target Channel: {TELEGRAM_CHANNEL}")
    
    last_tweet_id = load_last_tweet_id()
    print(f"Last processed Tweet ID: {last_tweet_id}")

    tweet_ids = fetch_recent_tweet_ids()
    if not tweet_ids:
        print("❌ ERROR: Could not retrieve any tweet IDs!")
        return

    print(f"Found {len(tweet_ids)} tweet IDs: {tweet_ids[:5]}...")

    # Process oldest first
    tweet_ids_to_process = list(reversed(tweet_ids[:10]))
    newest_tweet_id_seen = last_tweet_id

    for tweet_id in tweet_ids_to_process:
        # Skip if already processed in earlier run
        if last_tweet_id and int(tweet_id) <= int(last_tweet_id):
            print(f"Skipping Tweet ID {tweet_id} (already posted previously).")
            continue

        tweet = fetch_tweet_details_fxtwitter(tweet_id)
        if not tweet:
            print(f"Could not load details for Tweet ID {tweet_id}, skipping.")
            continue

        text = tweet.get("text", "")
        print(f"\nProcessing Tweet ID {tweet_id}: '{text[:60]}...'")
        print(f"-> Sending Tweet ID {tweet_id} to Telegram...")

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
