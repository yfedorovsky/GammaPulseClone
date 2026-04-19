"""Weekend research synthesis via Claude Opus 4.7.

Pulls market intelligence from public feeds (TrendForce, JPM, substack
feeds), passes it to Claude for synthesis, writes a dated report to
`docs/research/weekend_YYYY-MM-DD.md`, and cross-references any mentioned
tickers against the GammaPulse universe + IBD layer.

Runs end-to-end with no manual input. Intended for weekend cron:

    python -m scripts.weekend_research          # full run
    python -m scripts.weekend_research --dry    # fetch only, skip LLM call
    python -m scripts.weekend_research --stale  # use cached fetches if fresh

Refactored from the Gemini proposal — fixes model ID (claude-3-opus-20240229
→ claude-opus-4-7), content access bug (response.content.text → content[0].text),
empty list init, prompt caching, streaming for long outputs, typed exceptions,
and adds IBD integration + date-stamped output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import anthropic
import feedparser
import httpx
from bs4 import BeautifulSoup


# ── Configuration ─────────────────────────────────────────────────────

MODEL = "claude-opus-4-7"          # Per claude-api skill — adaptive thinking supported
MAX_TOKENS = 16000                 # Plenty for a weekend synthesis; streaming handles latency
CACHE_DIR = Path("data/weekend_research_cache")
OUTPUT_DIR = Path("docs/research")
CACHE_TTL_SECONDS = 3600 * 6       # Re-fetch sources older than 6h
REQUEST_TIMEOUT = 20.0             # Per-source fetch timeout
MAX_RSS_ENTRIES = 8                # Per feed — keeps context bounded
MAX_HTML_CHARS = 6000              # Per page — token bloat guard


# Source list — favor RSS (structured, reliable) over HTML scraping.
# Gemini's original included JSP/JS-rendered pages that return mostly nav
# markup; we've dropped those or replaced with working equivalents.
SOURCES: dict[str, dict[str, str]] = {
    "TrendForce News": {
        "type": "rss",
        "url": "https://www.trendforce.com/news/feed",
    },
    "Global Semi Research": {
        "type": "rss",
        "url": "https://globalsemiresearch.substack.com/feed",
    },
    "The Diligence Stack": {
        "type": "rss",
        "url": "https://thediligencestack.com/feed",
    },
    "JPM Market Insights": {
        "type": "html",
        "url": "https://am.jpmorgan.com/us/en/asset-management/adv/insights/market-insights/market-updates/weekly-market-recap/",
    },
    # Mirae Asset removed — JS-rendered page returned only navbar in tests.
    # User can add Substack / Kakao / specific research PDFs manually.
}


# Known-good ticker pattern: 1-5 uppercase letters. We post-filter against
# the GammaPulse universe to avoid picking up stray acronyms (like "AI", "CEO").
TICKER_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")


SYSTEM_PROMPT = """You are a senior financial and technology market analyst specializing in semiconductors, AI infrastructure, and macro positioning.

Synthesize the provided unstructured market intelligence into a professional weekly report with the following structure:

## Executive Summary
2-3 sentence summary of the week's dominant narratives.

## Key Themes
Three to five numbered themes. Each with:
- A short bold headline
- 2-4 supporting sentences integrating specific metrics/companies/prices
- The source(s) that corroborate the theme

## Actionable Tickers
A markdown table: | Ticker | Catalyst | Source | Direction (Long/Short/Watch) |
Only include tickers with a CONCRETE near-term catalyst from the source material. Do not speculate beyond the sources.

## Risks to Monitor
Bulleted list of 3-5 downside scenarios from the source material.

## What Changed This Week
1-2 sentences on how the picture shifted vs prior weeks (call out if sources agree or diverge).

Requirements:
- Output pure Markdown. No conversational filler ("Here's the report...").
- Never invent data points, company names, or price moves not in the source material.
- Prefer numbers, specific dollar figures, and dated events over generalities.
- If the source material is thin or contradictory, say so explicitly."""


# ── Cache helpers ─────────────────────────────────────────────────────

def _cache_path(source_name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", source_name)
    return CACHE_DIR / f"{safe}.txt"


def _cache_fresh(path: Path, ttl: int = CACHE_TTL_SECONDS) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl


# ── Fetchers ──────────────────────────────────────────────────────────

def fetch_rss(url: str, max_entries: int = MAX_RSS_ENTRIES) -> str:
    """Parse an RSS feed and return joined title+summary text for the latest entries."""
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        return f"[RSS parse error: {feed.bozo_exception}]"
    chunks: list[str] = []
    for entry in feed.entries[:max_entries]:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        # Summaries often contain HTML — strip it.
        summary_text = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        published = entry.get("published", entry.get("updated", ""))
        chunk = f"[{published}] {title}\n{summary_text[:800]}".strip()
        chunks.append(chunk)
    return "\n\n".join(chunks) if chunks else "[no entries]"


def fetch_html(url: str, max_chars: int = MAX_HTML_CHARS) -> str:
    """Fetch an HTML page and return the concatenated <p> text (DOM-stripped)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GammaPulseResearchBot/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # Drop scripts/styles/navs entirely before extracting text
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = " ".join(p for p in paragraphs if len(p) > 40)
    if len(text) < 200:
        return f"[HTML too thin ({len(text)} chars) — page may be JS-rendered]"
    return text[:max_chars]


def fetch_source(name: str, spec: dict[str, str], use_cache: bool = True) -> str:
    """Fetch one source with caching. Returns text, never raises."""
    cache_path = _cache_path(name)
    if use_cache and _cache_fresh(cache_path):
        return cache_path.read_text(encoding="utf-8")
    try:
        if spec["type"] == "rss":
            body = fetch_rss(spec["url"])
        elif spec["type"] == "html":
            body = fetch_html(spec["url"])
        else:
            body = f"[unknown source type: {spec['type']}]"
    except httpx.HTTPError as e:
        body = f"[fetch error: {e}]"
    except Exception as e:
        body = f"[unexpected error: {e}]"
    cache_path.write_text(body, encoding="utf-8")
    return body


def aggregate_corpus(use_cache: bool = True) -> tuple[str, dict[str, int]]:
    """Fetch all sources, join into one corpus with source delimiters.
    Returns (corpus, stats) where stats maps source name → byte count."""
    parts: list[str] = []
    stats: dict[str, int] = {}
    for name, spec in SOURCES.items():
        print(f"[fetch] {name} ({spec['type']}: {spec['url'][:60]}...)", flush=True)
        body = fetch_source(name, spec, use_cache=use_cache)
        stats[name] = len(body)
        parts.append(f"=== SOURCE: {name} ({spec['url']}) ===\n{body}")
    corpus = "\n\n".join(parts)
    return corpus, stats


# ── LLM synthesis ─────────────────────────────────────────────────────

def synthesize(client: anthropic.Anthropic, corpus: str) -> str:
    """Stream a synthesis from Claude. Uses prompt caching on the system
    prompt (stable across runs) so repeated iterations are cheaper.

    Streaming with `.get_final_message()` avoids the 10-min HTTP timeout
    that a non-streaming Opus call can hit with max_tokens=16000."""
    # cache_control on the system prompt; the corpus is the volatile tail.
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    print(f"[llm] sending {len(corpus)} chars of corpus to {MODEL}", flush=True)
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{
            "role": "user",
            "content": (
                "Synthesize the following aggregated market intelligence into the "
                "structured report described in the system prompt. Today is "
                f"{dt.date.today().isoformat()}.\n\n{corpus}"
            ),
        }],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        final = stream.get_final_message()

    print()  # newline after stream
    # Report cache behavior
    usage = final.usage
    print(
        f"[llm] usage: input={usage.input_tokens} "
        f"output={usage.output_tokens} "
        f"cache_read={usage.cache_read_input_tokens} "
        f"cache_write={usage.cache_creation_input_tokens}",
        flush=True,
    )
    # Extract the first text block
    return next(b.text for b in final.content if b.type == "text")


# ── Ticker extraction + IBD cross-reference ──────────────────────────

def _gammapulse_universe() -> set[str]:
    try:
        # Import lazily so the script runs even outside the full repo context
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from server.tickers import all_tickers  # type: ignore
        return set(all_tickers())
    except Exception as e:
        print(f"[ibd] could not load GammaPulse universe: {e}", flush=True)
        return set()


def _ibd_info(ticker: str) -> dict[str, Any]:
    """Return {group_rank, group_name, is_sector_leader} or empty dict."""
    try:
        from server.ibd_groups import get_ibd_group_info  # type: ignore
        from server.ibd_sector_leaders import is_sector_leader  # type: ignore
        grp = get_ibd_group_info(ticker) or {}
        return {
            "group_rank": grp.get("rank"),
            "group_name": grp.get("name"),
            "ytd_pct": grp.get("ytd_pct"),
            "is_sector_leader": is_sector_leader(ticker),
        }
    except Exception:
        return {}


def extract_tickers(report: str, universe: set[str]) -> list[dict[str, Any]]:
    """Find every ALLCAPS token in the report that matches the GammaPulse
    universe, sorted by first appearance. Returns one row per ticker with
    IBD context."""
    seen: dict[str, int] = {}
    for m in TICKER_PATTERN.finditer(report):
        t = m.group(1)
        if t in universe and t not in seen:
            seen[t] = m.start()
    rows: list[dict[str, Any]] = []
    for ticker in sorted(seen, key=seen.get):  # type: ignore[arg-type]
        info = _ibd_info(ticker)
        rows.append({"ticker": ticker, **info})
    return rows


def format_ibd_appendix(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "## GammaPulse Ticker Context\n\nNo universe tickers mentioned in the report.\n"
    lines = [
        "## GammaPulse Ticker Context",
        "",
        "Tickers mentioned in the report that overlap the GammaPulse universe, "
        "with current IBD group and Sector Leader status.",
        "",
        "| Ticker | IBD Group | YTD% | Sector Leader |",
        "|---|---|---:|:---:|",
    ]
    for r in rows:
        grp = f"#{r['group_rank']} {r['group_name']}" if r.get("group_rank") else "—"
        ytd = f"{r['ytd_pct']}%" if r.get("ytd_pct") is not None else "—"
        lead = "★★" if r.get("is_sector_leader") else ""
        lines.append(f"| {r['ticker']} | {grp} | {ytd} | {lead} |")
    lines.append("")
    return "\n".join(lines)


# ── Output ────────────────────────────────────────────────────────────

def write_report(report: str, ibd_appendix: str, stats: dict[str, int]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = OUTPUT_DIR / f"weekend_{today}.md"
    stats_block = "\n".join(f"- `{k}`: {v:,} chars" for k, v in stats.items())
    full = (
        f"# Weekend Research — {today}\n\n"
        f"_Generated by `scripts/weekend_research.py` using {MODEL}._\n\n"
        f"{report}\n\n"
        f"{ibd_appendix}\n\n"
        f"## Source Telemetry\n\n"
        f"{stats_block}\n"
    )
    path.write_text(full, encoding="utf-8")
    return path


# ── Main ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true",
                    help="Fetch sources only, skip LLM call + report write.")
    ap.add_argument("--no-cache", action="store_true",
                    help="Bypass the 6h source cache (always re-fetch).")
    args = ap.parse_args()

    # Fetch sources first so we can abort cheaply if all sources are dead.
    corpus, stats = aggregate_corpus(use_cache=not args.no_cache)
    print()
    for name, n in stats.items():
        print(f"  {name}: {n:,} chars", flush=True)

    if args.dry:
        print("\n[dry] skipping LLM call. Corpus cached.")
        print(f"[dry] preview:\n{corpus[:600]}...")
        return

    # Initialize client — SDK reads ANTHROPIC_API_KEY from env
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[error] ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(1)
    client = anthropic.Anthropic()

    # LLM synthesis with typed exception handling
    try:
        report = synthesize(client, corpus)
    except anthropic.RateLimitError as e:
        print(f"[error] rate limited: {e}", file=sys.stderr)
        sys.exit(2)
    except anthropic.APIStatusError as e:
        print(f"[error] API status {e.status_code}: {e.message}", file=sys.stderr)
        sys.exit(3)
    except anthropic.APIConnectionError as e:
        print(f"[error] network: {e}", file=sys.stderr)
        sys.exit(4)

    # Post-process: find universe tickers + build IBD appendix
    universe = _gammapulse_universe()
    ticker_rows = extract_tickers(report, universe)
    ibd_appendix = format_ibd_appendix(ticker_rows)

    out_path = write_report(report, ibd_appendix, stats)
    print(f"\n[done] wrote {out_path}")
    print(f"[done] {len(ticker_rows)} universe tickers mentioned:",
          [r["ticker"] for r in ticker_rows])


if __name__ == "__main__":
    main()
