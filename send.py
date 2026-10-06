"""Daily Telegram poster: motivating quote (4 AM IST) and bedtime story (9:30 PM IST).

Usage: python send.py quote | story
Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, (optional) GEMINI_MODEL
Only uses the Python standard library.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL", "").strip()  # optional override
# Newest-first; the script skips any that Google has retired or that aren't on your free tier.
FALLBACK_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).strftime("%A, %d %B %Y")


def http_json(url, payload=None, headers=None, timeout=90):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def gemini(prompt, temperature=1.0):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    # Try models in order; if one is retired (404) or rate-limited, move to the next.
    # GEMINI_MODEL (if set) is tried first.
    models = ([MODEL] if MODEL else []) + [
        m for m in FALLBACK_MODELS if m != MODEL
    ]
    errors = []
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                res = http_json(url, body, {"x-goog-api-key": GEMINI_KEY})
                print("Used model:", model)
                return res["candidates"][0]["content"]["parts"][0]["text"].strip()
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="ignore")[:300]
                errors.append(f"{model} -> HTTP {e.code}: {detail}")
                print(errors[-1])
                if e.code in (404, 400, 403):
                    break  # retrying the same model won't help
                time.sleep(5)
            except Exception as e:  # noqa
                errors.append(f"{model} -> {e}")
                print(errors[-1])
                time.sleep(5)
    raise RuntimeError("Gemini failed on all models:\n" + "\n".join(errors))


def get_quote():
    try:
        return gemini(
            f"Today is {TODAY}. Give ONE short, genuinely motivating quote to start the day. "
            "Prefer a real, well-known quote with its author; if unsure of the author, write an "
            "original line instead. Vary themes across days (discipline, courage, kindness, "
            "focus, resilience, gratitude). Output format exactly:\n"
            "☀️ Good morning!\n\n“<quote>”\n— <author>\n\nNo extra commentary."
        )
    except Exception:
        # Fallback: free ZenQuotes API (attribution: zenquotes.io)
        q = http_json("https://zenquotes.io/api/today")[0]
        return f"☀️ Good morning!\n\n“{q['q']}”\n— {q['a']}\n\nQuotes by ZenQuotes.io"


def get_story():
    return gemini(
        f"Today is {TODAY}. Write a calm, original bedtime story for children aged 4-8, "
        "about 1000 words (between 950 and 1050). Requirements: gentle tone, a fresh setting and "
        "characters (animals, nature, kind magic), a small problem solved through kindness or "
        "courage, a soothing ending that leads to sleep, and a one-line moral at the end. "
        "Start with a title on its own line prefixed by 🌙. Use short paragraphs separated by "
        "blank lines. No markdown symbols like ** or #. Plain text only.",
        temperature=1.1,
    )


def split_message(text, limit=3800):
    """Telegram caps messages at 4096 chars; split on paragraph boundaries."""
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > limit and cur:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = split_message(text)
    # TELEGRAM_CHAT_ID can be one ID or several, comma-separated
    # e.g. "@myfamilychannel,123456789,987654321"
    for chat in [c.strip() for c in CHAT_ID.split(",") if c.strip()]:
        try:
            for chunk in chunks:
                res = http_json(url, {"chat_id": chat, "text": chunk, "disable_web_page_preview": True})
                if not res.get("ok"):
                    print("Failed for", chat, res)
        except Exception as e:  # one person failing shouldn't block the others
            print("Failed for", chat, e)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "quote":
        send(get_quote())
    elif mode == "story":
        send(get_story())
    else:
        sys.exit("Usage: python send.py quote|story")
    print("Sent:", mode)
