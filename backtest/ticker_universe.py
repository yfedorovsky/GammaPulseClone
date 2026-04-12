"""Refined ticker universe organized by investment theme.

34 tickers across 6 themes. Focused on liquid, US-listed names
with strong options markets and thematic relevance.

Date ranges per theme:
  - Mag 7 + Index ETFs: 2 years (deep history, regime changes)
  - Everything else: 12-15 months (AI regime only, pre-2024 is noise)
"""

UNIVERSE = {
    "Mag 7": {
        "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
        "start": "2024-04-01",
    },
    "Index ETFs": {
        "tickers": ["SPY", "QQQ", "SMH"],
        "start": "2024-04-01",
    },
    "Memory + AI Chips": {
        "tickers": ["MU", "AMD", "AVGO", "MRVL", "TSM", "INTC", "LRCX", "AMAT"],
        "start": "2025-01-01",
    },
    "Photonics / Optics / Fiber": {
        "tickers": ["LITE", "COHR", "AAOI", "GLW", "CIEN", "TSEM", "AXTI"],
        "start": "2025-01-01",
    },
    "Space (SpaceX IPO Sympathy)": {
        "tickers": ["GOOGL", "ASTS", "VOYG", "RKLB", "SATL"],
        "start": "2025-01-01",
    },
    "AI / Data Center Infra": {
        "tickers": ["ANET", "VRT", "NET", "SNOW", "PLTR"],
        "start": "2025-01-01",
    },
}

END_DATE = "2026-04-11"

# Deduplicated flat list
def all_tickers() -> list[str]:
    seen = set()
    out = []
    for theme in UNIVERSE.values():
        for t in theme["tickers"]:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def ticker_date_range(ticker: str) -> tuple[str, str]:
    """Get the start/end date range for a ticker based on its theme."""
    for theme in UNIVERSE.values():
        if ticker in theme["tickers"]:
            return theme["start"], END_DATE
    return "2025-01-01", END_DATE  # default


def download_commands() -> list[dict]:
    """Generate download commands grouped by start date to minimize API calls."""
    by_start: dict[str, list[str]] = {}
    seen = set()
    for name, theme in UNIVERSE.items():
        for t in theme["tickers"]:
            if t not in seen:
                seen.add(t)
                start = theme["start"]
                if start not in by_start:
                    by_start[start] = []
                by_start[start].append(t)

    commands = []
    for start, tickers in sorted(by_start.items()):
        commands.append({
            "start": start,
            "end": END_DATE,
            "tickers": tickers,
            "count": len(tickers),
        })
    return commands


if __name__ == "__main__":
    tickers = all_tickers()
    print(f"Total unique tickers: {len(tickers)}")
    print()
    for name, theme in UNIVERSE.items():
        print(f"  {name} ({len(theme['tickers'])}): {', '.join(theme['tickers'])}  [{theme['start']} -> {END_DATE}]")
    print()
    cmds = download_commands()
    print(f"Download commands ({len(cmds)}):")
    for c in cmds:
        print(f"\n  {c['start']} -> {c['end']} ({c['count']} tickers):")
        print(f"  python -m backtest.download_eodhd --tickers {','.join(c['tickers'])} --start {c['start']} --end {c['end']} --delay 0.5")
    print()
    print("Already downloaded: SPY (full), QQQ (full)")
