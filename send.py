"""Daily Telegram poster.

  python send.py quote    -> 4:00 AM IST   "Good Morning warrior" + motivational quote
  python send.py proverb  -> 12:30 PM IST  English proverb/idiom + meaning + example sentence
  python send.py story    -> 9:00 PM IST   calm bedtime story (<= 4000 chars) + closing message

Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (one or more, comma-separated),
          GEMINI_API_KEY, optional GEMINI_MODEL.
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

# ---- Easy-to-edit texts ----
GREETING = "Good Morning warrior 🌅"
STORY_END_MESSAGE = "Story over, keep out your mobile and sleep 😴🌙"
STORY_MAX_CHARS = 4000

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
TODAY = NOW.strftime("%A, %d %B %Y")


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
    models = ([MODEL] if MODEL else []) + [m for m in FALLBACK_MODELS if m != MODEL]
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


# ---------- 1. Morning quote ----------
def get_quote():
    try:
        quote = gemini(
            f"Today is {TODAY}. Give ONE short, genuinely motivating and inspirational quote. "
            "Prefer a real, well-known quote with its author; if unsure of the author, write an "
            "original line instead. Vary the theme from day to day (discipline, courage, grit, "
            "focus, resilience, self-belief, perseverance). Output format exactly:\n"
            "“<quote>”\n— <author>\n\nNo greeting, no extra commentary."
        )
    except Exception as e:
        print("Gemini failed, using ZenQuotes fallback:", e)
        q = http_json("https://zenquotes.io/api/today")[0]  # attribution: zenquotes.io
        quote = f"“{q['q']}”\n— {q['a']}"
    return [f"{GREETING}\n\n{quote}"]


# ---------- 2. Proverb / idiom ----------
def get_proverb():
    day = NOW.timetuple().tm_yday
    text = gemini(
        f"Today is {TODAY} (day {day} of the year). Pick ONE English proverb or idiom (alternate "
        "between the two across days and avoid the most overused ones, so choose something "
        "fresh). Output EXACTLY in this format, plain text, no markdown symbols:\n\n"
        "📖 Proverb of the Day\n\n"
        "“<the proverb or idiom>”\n\n"
        "💡 Meaning: <clear one or two sentence meaning>\n\n"
        "✍️ Usage: <one well-articulated, natural sentence using it correctly>\n\n"
        "No extra commentary.",
        temperature=1.1,
    )
    return [text]


# ---------- 3. Bedtime story ----------
def trim_to_limit(text, limit):
    """Last-resort safety: cut at a sentence/paragraph boundary under the limit."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind("\n\n"), cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > limit * 0.6 else cut).strip()


def get_story():
    prompt = (
        f"Today is {TODAY}. Write a calm, original bedtime story for children aged 4-8. "
        "HARD LIMIT: the whole output, including the title, must be under 3500 characters "
        "(roughly 550 words). Requirements: soothing, gentle tone; a fresh setting and "
        "characters (animals, nature, kind magic); a tiny problem solved through kindness; "
        "an ending where everyone gets sleepy and drifts off to sleep; finish with a "
        "one-line moral. Start with a title on its own line prefixed by 🌙. Use short "
        "paragraphs separated by blank lines. Plain text only, no ** or # symbols."
    )
    story = gemini(prompt, temperature=1.1)
    if len(story) > STORY_MAX_CHARS:  # ask once more, then trim as a last resort
        story = gemini(prompt + " It MUST be shorter than 3000 characters.", temperature=1.0)
    story = trim_to_limit(story, STORY_MAX_CHARS)
    return [story, STORY_END_MESSAGE]


# ---------- Telegram ----------
def split_message(text, limit=3800):
    """Telegram caps messages at 4096 chars; split on paragraph boundaries if needed."""
    if len(text) <= 4096:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > limit and cur:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def send(messages):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [c for m in messages for c in split_message(m)]
    # TELEGRAM_CHAT_ID can be one ID or several, comma-separated
    # e.g. "@myfamilychannel,123456789,987654321"
    failed = 0
    for chat in [c.strip() for c in CHAT_ID.split(",") if c.strip()]:
        try:
            for i, chunk in enumerate(chunks):
                res = http_json(url, {"chat_id": chat, "text": chunk, "disable_web_page_preview": True})
                if not res.get("ok"):
                    raise RuntimeError(res)
                if i < len(chunks) - 1:
                    time.sleep(1)  # keep message order
        except Exception as e:  # one person failing shouldn't block the others
            failed += 1
            print("Failed for", chat, e)
    if failed:
        sys.exit(f"{failed} recipient(s) failed - see log above")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    jobs = {"quote": get_quote, "proverb": get_proverb, "story": get_story}
    if mode not in jobs:
        sys.exit("Usage: python send.py quote|proverb|story")
    send(jobs[mode]())
    print("Sent:", mode)
