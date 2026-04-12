"""Refined ticker universe organized by investment theme.

~45 tickers across 7 themes. Focused on liquid, US-listed names
with strong options markets and thematic relevance.
"""

UNIVERSE = {
    "Mag 7": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    ],
    "Memory + AI Chips": [
        "MU", "AMD", "AVGO", "MRVL", "TSM", "INTC", "LRCX", "AMAT",
    ],
    "Photonics / Optics / Fiber": [
        "LITE", "COHR", "AAOI", "GLW", "CIEN", "TSEM", "AXTI",
    ],
    "Space (SpaceX IPO Sympathy)": [
        "GOOGL", "ASTS", "VOYG", "RKLB", "SATL",
    ],
    "AI / Data Center Infra": [
        "ANET", "PLTR", "SNOW", "NET",
    ],
    "Index ETFs": [
        "SPY", "QQQ", "SMH",
    ],
}

# Deduplicated flat list
def all_tickers() -> list[str]:
    seen = set()
    out = []
    for tickers in UNIVERSE.values():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def download_batches(batch_size: int = 15) -> list[dict]:
    tickers = all_tickers()
    batches = []
    for i in range(0, len(tickers), batch_size):
        chunk = tickers[i:i + batch_size]
        batches.append({
            "batch": len(batches) + 1,
            "tickers": chunk,
            "count": len(chunk),
        })
    return batches


if __name__ == "__main__":
    tickers = all_tickers()
    print(f"Total unique tickers: {len(tickers)}")
    print()
    for sector, syms in UNIVERSE.items():
        print(f"  {sector} ({len(syms)}): {', '.join(syms)}")
    print()
    batches = download_batches()
    print(f"Download batches ({len(batches)}):")
    for b in batches:
        print(f"  Batch {b['batch']}: {','.join(b['tickers'])}")
    print()
    print("Already downloaded: SPY, QQQ, NVDA (partial)")
    remaining = [t for t in tickers if t not in ("SPY", "QQQ")]
    print(f"Remaining to download: {len(remaining)} tickers")
    print(f"Command:")
    print(f"  python -m backtest.download_eodhd --tickers {','.join(remaining)} --start 2024-04-01 --end 2026-04-11 --delay 0.5")
