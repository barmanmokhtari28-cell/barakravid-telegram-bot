import os
import re
import requests
from urllib.parse import quote
from curl_cffi import requests as cf_requests
from deep_translator import GoogleTranslator

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@secretollah")
TWITTER_TARGET_USER = os.getenv("TWITTER_TARGET_USER", "barakravid")
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY")

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
    """Pulls tweet IDs out of an HTML or JSON response body.

    Handles three shapes we've seen in practice:
    - plain HTML links: /status/1234567890
    - JSON with escaped slashes: status\\/1234567890 (common with older/internal
      Twitter backends, which escape "/" as "\\/" inside JSON strings)
    - JSON fields with the ID as a plain value: "id_str":"1234567890"
    A single regex tuned for HTML silently finds nothing against a JSON body,
    which looks identical to "no tweets" — this checks all three so a 200
    response isn't wasted just because of how the ID happened to be encoded.
    """
    ids = []
    patterns = [
        r'status\\?/(\d+)',
        r'"id_str"\s*:\s*"(\d+)"',
    ]
    for pattern in patterns:
        for tid in re.findall(pattern, text):
            if tid not in ids:
                ids.append(tid)
    return ids

def fetch_tweet_details_fxtwitter(tweet_id: str):
    """Fetches full tweet metadata and media via FxTwitter API."""
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
    """Fetches recent Tweet IDs via Jina AI Reader, falling back to Twitter's embed-widget
    syndication endpoints called directly, then falling back again to the same syndication
    endpoint routed through ScraperAPI (a paid proxy pool) when the direct GitHub Actions IP
    is blocked or rate-limited."""
    tweet_ids = []
    
    # Method 1: Jina AI Web Reader (Renders X.com using headless browser proxies)
    # NOTE: r.jina.ai caches page renders for up to 3600s (1 hour) by default.
    # Since a 45-60 min delivery delay is acceptable, we deliberately do NOT set
    # x-no-cache or x-cache-tolerance here — letting Jina serve its own cached
    # copy whenever it has one. This matters because a cached copy is served
    # WITHOUT re-scraping x.com, so it can't trigger X's anti-bot block. Forcing
    # freshness on every run was exactly what caused the 403s, since every run
    # then had to survive X's live bot-detection instead of just reading a cache.
    jina_url = f"https://r.jina.ai/https://x.com/{TWITTER_TARGET_USER}"
    try:
        print(f"📡 Method 1: Fetching via Jina AI Reader ({jina_url})...", flush=True)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(jina_url, headers=headers, timeout=25)
        print(f"Jina AI Status: {resp.status_code} | body length: {len(resp.text)}", flush=True)
        if resp.status_code == 200:
            found = extract_tweet_ids(resp.text)
            for tid in found:
                if tid not in tweet_ids:
                    tweet_ids.append(tid)
            if tweet_ids:
                print(f"✅ Success via Jina AI Reader! Found {len(tweet_ids)} Tweet IDs.", flush=True)
                return tweet_ids
            else:
                print(f"Jina AI Reader returned 200 but no Tweet IDs were parsed out of the body.", flush=True)
                print(f"Raw response snippet for debugging: {resp.text[:300]!r}", flush=True)
        elif resp.status_code == 403:
            print("Jina AI Reader was blocked (403) - even the cached copy was unavailable. Falling back...", flush=True)
        else:
            print(f"Jina AI Reader returned an unexpected status. Body snippet: {resp.text[:300]!r}", flush=True)
    except Exception as e:
        print(f"Jina AI Reader notice: {e}", flush=True)

    # Method 2: Twitter's embed-widget syndication endpoints, called directly.
    # NOTE: CORS proxies (allorigins/corsproxy.io) exist to work around a BROWSER
    # restriction — they're irrelevant here since this is a server-side Python
    # script, not JS running in a browser. Routing through them was adding two
    # more unreliable free services on top of Twitter's own blocking, for no
    # benefit. These endpoints are what Twitter's own embed widgets (the ones
    # websites use to show a live timeline) call, so they respond to a request
    # that "looks like" a widget: a normal browser User-Agent plus a Referer of
    # platform.twitter.com. We try both the current CDN host and the legacy host,
    # since either may be the one still serving traffic in a given window.
    # No cache-busting param here on purpose: since some delay is acceptable,
    # letting any caching layer in front of these endpoints serve the request
    # is strictly better than forcing a fresh hit (and a fresh shot at a block)
    # every single run.
    # We use curl_cffi (not plain requests) here specifically: a 200 status with
    # an EMPTY body is a classic sign of TLS-fingerprint-based bot detection —
    # Cloudflare-class defenses inspect the TLS handshake itself (cipher order,
    # extensions, etc), which plain Python `requests` can't disguise no matter
    # what headers you set. curl_cffi replicates a real Chrome TLS handshake at
    # that lower layer, which header spoofing alone cannot do.
    widget_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Referer": "https://platform.twitter.com/",
        "Accept": "application/json",
    }
    syndication_urls = [
        f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={TWITTER_TARGET_USER}&dnt=true",
        f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TWITTER_TARGET_USER}",
    ]
    for s_url in syndication_urls:
        try:
            print(f"📡 Method 2: Trying syndication endpoint ({s_url[:60]}...)...", flush=True)
            resp = cf_requests.get(s_url, headers=widget_headers, impersonate="chrome124", timeout=12)
            print(f"Syndication status: {resp.status_code} | body length: {len(resp.text)}", flush=True)
            if resp.status_code == 200:
                found = extract_tweet_ids(resp.text)
                for tid in found:
                    if tid not in tweet_ids:
                        tweet_ids.append(tid)
                if tweet_ids:
                    print(f"✅ Success via syndication endpoint! Found {len(tweet_ids)} Tweet IDs.", flush=True)
                    return tweet_ids
                elif not resp.text.strip():
                    print("Syndication endpoint returned 200 with an EMPTY body — this usually means a soft block is still in place, not that the account has no tweets.", flush=True)
                else:
                    print("Syndication endpoint returned 200 but no tweet IDs were found in the content.", flush=True)
                    print(f"Raw response snippet for debugging: {resp.text[:300]!r}", flush=True)
            else:
                print(f"Syndication notice: got HTTP {resp.status_code}. Body snippet: {resp.text[:300]!r}", flush=True)
        except Exception as e:
            print(f"Syndication notice: {e}", flush=True)

    # Method 3: Same syndication endpoint, routed through ScraperAPI so the
    # request comes from ScraperAPI's proxy pool instead of GitHub Actions'
    # shared (and evidently blocked/rate-limited) IP range. This targets the
    # raw JSON endpoint directly (no JS rendering flag) since the endpoint
    # already returns JSON on its own - that keeps each call to a single
    # credit on ScraperAPI's free tier instead of the much pricier
    # JS-rendering multiplier.
    if not SCRAPERAPI_KEY:
        print("Method 3 skipped: SCRAPERAPI_KEY is not set.", flush=True)
    else:
        target_url = f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={TWITTER_TARGET_USER}&dnt=true"
        proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={quote(target_url, safe='')}"
        try:
            print("📡 Method 3: Trying syndication endpoint via ScraperAPI...", flush=True)
            resp = requests.get(proxy_url, timeout=60)
            print(f"ScraperAPI status: {resp.status_code} | body length: {len(resp.text)}", flush=True)
            if resp.status_code == 200:
                found = extract_tweet_ids(resp.text)
                for tid in found:
                    if tid not in tweet_ids:
                        tweet_ids.append(tid)
                if tweet_ids:
                    print(f"✅ Success via ScraperAPI! Found {len(tweet_ids)} Tweet IDs.", flush=True)
                    return tweet_ids
                else:
                    print("ScraperAPI returned 200 but no Tweet IDs were found in the content.", flush=True)
                    print(f"Raw response snippet for debugging: {resp.text[:300]!r}", flush=True)
            elif resp.status_code in (403, 429):
                print(f"ScraperAPI notice: got HTTP {resp.status_code}. This usually means the ScraperAPI free-tier credit limit was hit for the month, or its own proxy got blocked. Body: {resp.text[:300]!r}", flush=True)
            else:
                print(f"ScraperAPI notice: got HTTP {resp.status_code}. Body snippet: {resp.text[:300]!r}", flush=True)
        except Exception as e:
            print(f"ScraperAPI notice: {e}", flush=True)

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
