"""Weekly newsletter scanner — Tier-1 AI/semis equity newsletters.

Tracks the highest-rated AI-equity newsletters (community poll via @chrisbarber).
Each run: pulls every Tier-1 RSS feed, detects posts NEW since the last run
(dedup by guid in newsletters.db), and for each new post produces a 1-sentence
summary, investment implications, and tickers (cross-referenced vs the
GammaPulse universe) via one batched Opus call. Writes a dated digest to
docs/research/newsletters/ and stores everything for weekly tracking.

NOTE: these are PAID Substacks — the free RSS gives title + a preview, not the
full paywalled post. Analysis is from title+preview (flagged when thin). To go
deeper, drop a subscriber RSS token into NEWSLETTER_RSS_TOKENS (env, json).

Usage (intended weekly — cron / Task Scheduler / manual):
    python -m scripts.newsletter_scan              # full run (LLM)
    python -m scripts.newsletter_scan --dry        # fetch only, no LLM, no store
    python -m scripts.newsletter_scan --no-llm      # fetch + store, skip analysis
    python -m scripts.newsletter_scan --telegram    # also push the digest
    python -m scripts.newsletter_scan --since-days 14
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(".env")

MODEL = "claude-opus-4-8"
DB_PATH = "newsletters.db"
OUTPUT_DIR = Path("docs/research/newsletters")
UA = "Mozilla/5.0 (GammaPulse newsletter-scan)"

# (name, feed_url, tier, twitter) — Tier 1 from the @chrisbarber community poll.
NEWSLETTERS = [
    ("SemiAnalysis",         "https://newsletter.semianalysis.com/feed", 1, "@dylan522p"),
    ("FUNDA",                "https://fundaai.substack.com/feed",        1, "@FundaAI"),
    ("Citrini Research",     "https://www.citriniresearch.com/feed",     1, "@citrini"),
    ("Irrational Analysis",  "https://irrationalanalysis.substack.com/feed", 1, "@insane_analyst"),
    ("Vik's Newsletter",     "https://www.viksnewsletter.com/feed",      1, "@vikramskr"),
    ("Fabricated Knowledge", "https://www.fabricatedknowledge.com/feed", 1, "@fabknowledge"),
]

SCHEMA = """CREATE TABLE IF NOT EXISTS posts (
  guid TEXT PRIMARY KEY, newsletter TEXT, tier INTEGER, title TEXT, link TEXT,
  published_ts INTEGER, preview TEXT, summary TEXT, implications TEXT,
  tickers TEXT, seen_at INTEGER
);"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute(SCHEMA)
    return c


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html or "", "html.parser").get_text(" ")).strip()


def fetch_new(since_days: int, limit_per_feed: int) -> list[dict]:
    cutoff = time.time() - since_days * 86400
    con = _conn()
    seen = {r[0] for r in con.execute("SELECT guid FROM posts").fetchall()}
    con.close()
    out: list[dict] = []
    for name, url, tier, tw in NEWSLETTERS:
        try:
            feed = feedparser.parse(url, agent=UA)
        except Exception as e:  # noqa: BLE001
            print(f"  [WARN] {name}: feed error {e!r}", flush=True)
            continue
        cnt = 0
        for e in feed.entries:
            guid = e.get("id") or e.get("link")
            if not guid or guid in seen:
                continue
            pub = e.get("published_parsed") or e.get("updated_parsed")
            pub_ts = time.mktime(pub) if pub else time.time()
            if pub_ts < cutoff:
                continue
            body = e.get("summary") or ""
            if not body and e.get("content"):
                body = e["content"][0].get("value", "")
            out.append({
                "guid": guid, "newsletter": name, "tier": tier, "twitter": tw,
                "title": (e.get("title") or "").strip(), "link": e.get("link", ""),
                "published_ts": int(pub_ts), "preview": _clean(body)[:1200],
            })
            cnt += 1
            if cnt >= limit_per_feed:
                break
    out.sort(key=lambda p: (p["tier"], -p["published_ts"]))
    return out


def analyze(posts: list[dict]) -> dict[int, dict]:
    """One batched Opus call → {index: {summary, implications, tickers, in_universe}}."""
    if not posts:
        return {}
    import anthropic
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from server.tickers import all_tickers
        uni = set(all_tickers())
    except Exception:  # noqa: BLE001
        uni = set()
    blocks = "\n\n".join(
        f"[{i}] {p['newsletter']} — {p['title']}\nPreview: {p['preview'] or '(no preview — paywalled)'}"
        for i, p in enumerate(posts)
    )
    prompt = (
        "You are an AI/semiconductor equity research analyst. For each newsletter post below "
        "(title + free RSS preview — the full post is PAYWALLED, so reason from what's given and "
        "flag when the preview is too thin to be confident), return ONLY a JSON array. Each element:\n"
        '{"i": <index>, "summary": "<exactly one sentence>", '
        '"implications": ["<concise investment takeaway>", ...1-3], '
        '"tickers": ["TSM", "MU", ...]}\n'
        "tickers = US-listed tickers explicitly named or clearly implied. Be precise; empty list if none.\n\n"
        f"POSTS:\n{blocks}"
    )
    resp = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}]
    )
    txt = resp.content[0].text
    m = re.search(r"\[.*\]", txt, re.S)
    arr = json.loads(m.group(0)) if m else []
    res: dict[int, dict] = {}
    for el in arr:
        i = el.get("i")
        tks = [t.strip().upper() for t in (el.get("tickers") or []) if t]
        res[i] = {
            "summary": el.get("summary", ""),
            "implications": el.get("implications", []),
            "tickers": tks,
            "in_universe": [t for t in tks if t in uni],
        }
    return res


def build_digest(posts: list[dict], analysis: dict[int, dict]) -> str:
    today = dt.date.today().isoformat()
    lines = [
        f"# 📰 Newsletter Digest — {today}",
        f"_Tier-1 AI/semis equity newsletters · {len(posts)} new post(s)_  ",
        "_Analysis from title + free RSS preview (full posts are paywalled). Bold tickers = in your universe._\n",
    ]
    cur = None
    for i, p in enumerate(posts):
        if p["newsletter"] != cur:
            cur = p["newsletter"]
            lines.append(f"\n## {p['newsletter']}  ·  {p['twitter']}")
        a = analysis.get(i, {})
        d = dt.datetime.fromtimestamp(p["published_ts"]).strftime("%b %d")
        lines.append(f"\n**[{p['title']}]({p['link']})** · {d}")
        if a.get("summary"):
            lines.append(a["summary"])
        if a.get("implications"):
            lines.append("**Implications:** " + "; ".join(a["implications"]))
        tks = a.get("tickers") or []
        if tks:
            inu = set(a.get("in_universe") or [])
            lines.append("**Tickers:** " + ", ".join(f"**{t}**" if t in inu else t for t in tks))
    return "\n".join(lines)


def store(posts: list[dict], analysis: dict[int, dict]) -> None:
    con = _conn()
    now = int(time.time())
    for i, p in enumerate(posts):
        a = analysis.get(i, {})
        con.execute(
            "INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (p["guid"], p["newsletter"], p["tier"], p["title"], p["link"],
             p["published_ts"], p["preview"], a.get("summary", ""),
             json.dumps(a.get("implications", [])), json.dumps(a.get("tickers", [])), now),
        )
    con.commit()
    con.close()


def push_telegram(digest: str) -> None:
    import urllib.parse
    import urllib.request
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server.config import get_settings
    s = get_settings()
    data = urllib.parse.urlencode({"chat_id": s.telegram_chat_id, "text": digest[:3900]}).encode()
    urllib.request.urlopen(
        urllib.request.Request(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage", data=data),
        timeout=10,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=7)
    ap.add_argument("--limit-per-feed", type=int, default=4)
    ap.add_argument("--dry", action="store_true", help="fetch only — no LLM, no store")
    ap.add_argument("--no-llm", action="store_true", help="fetch + store, skip analysis")
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    posts = fetch_new(args.since_days, args.limit_per_feed)
    print(f"{len(posts)} new post(s) in the last {args.since_days}d:", flush=True)
    for p in posts:
        print(f"  [{p['newsletter']}] {p['title']}", flush=True)
    if not posts:
        print("Nothing new since last run.")
        return 0
    if args.dry:
        return 0

    analysis = {} if args.no_llm else analyze(posts)
    digest = build_digest(posts, analysis)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"weekly_{dt.date.today().isoformat()}.md"
    out_path.write_text(digest, encoding="utf-8")
    store(posts, analysis)
    print(f"\nwrote {out_path}  ·  stored {len(posts)} in {DB_PATH}", flush=True)
    if args.telegram:
        try:
            push_telegram(digest)
            print("dispatched to telegram")
        except Exception as e:  # noqa: BLE001
            print(f"telegram failed: {e!r}")
    print("\n" + digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
