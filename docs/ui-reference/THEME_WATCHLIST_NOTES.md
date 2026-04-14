# UI Reference: Theme-Based Watchlist + Relative Strength

Screenshots saved April 12, 2026 from discord member's app.

## Features to Implement

### Theme Watchlist View (Scanner tab mode)
- Group tickers by investment theme (not sector ETF)
- Themes: Foundry/Packaging, Chip Equipment, Memory, Photonics/Optical, Bitcoin Miners, AI Compute, AI Networking, Cybersecurity, etc.
- Each theme shows: alpha badge (aggregate %), X/Y outperforming count, avg RS percentile + direction arrow
- Expandable: click theme to see individual tickers

### Per-Ticker Relative Strength (RS 0-100)
- RS score based on price performance vs SPY (or sector)
- Color coding: green (80+), neutral (40-79), red (0-39)
- Inline: ticker, daily %, 5d %, RS score

### Inline Performance
- 5d and 20d performance shown inline
- SPY benchmark at top: "SPY +3.6% (5d) +2.3% (20d)"

### Mode Toggles
- Longs / Shorts / All / Themes
- Briefing button (could trigger MirBot briefing)
- Ticker detail search (strengths/weaknesses)

### Example Themes from Screenshots
1. Foundry/Packaging — 4/4 outperforming, RS 99
2. Chip Equipment — AMAT, LRCX, KLAC, FORM, ENTG, ASML — all RS 98-100
3. Memory — 2/3 outperforming, RS 98
4. Photonics/Optical — 3/4 outperforming, RS 75
5. Bitcoin Miners — 2/4 outperforming, RS 54
6. AI Compute — 4/5 outperforming, RS 83
7. AI Networking — 1/3 outperforming, RS 60
8. Cybersecurity (bearish) — PANW RS 4, FTNT RS 3, CRWD RS 2, ZS RS 0, S RS 0
