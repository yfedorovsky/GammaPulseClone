"""Generate a side-by-side HTML+SVG visual of MSFT vs TSLA runner patterns.

Fetches real Tradier daily OHLCV, builds candlestick + volume charts with
annotations for Day 1/2/3 runner state transitions. Saves to
`scripts/msft_vs_tsla_runners.html` — open in any browser.

Run: python -m scripts.plot_runner_comparison
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.tradier import TradierClient


# ── Tuning ──────────────────────────────────────────────────────────
WINDOW_START = "2026-03-20"
WINDOW_END = "2026-04-15"
# Candlestick colors
UP_COLOR = "#10dc9a"   # green
DOWN_COLOR = "#ff5656" # red
BG = "#0b0d12"
GRID = "#1e222b"
AXIS = "#4a5568"
TEXT = "#e4e9f2"
TEXT_DIM = "#8a93a8"
ACCENT = "#f4c430"  # gold
MEASURED_CLR = "#6ec6ff"  # blue
SQUEEZE_CLR = "#ff5656"   # red

OUT_PATH = Path(__file__).parent / "msft_vs_tsla_runners.html"


async def fetch(symbol: str) -> list[dict]:
    tc = TradierClient()
    bars = await tc.history(symbol, interval="daily", start=WINDOW_START, end=WINDOW_END)
    await tc.close()
    return bars


def sma(values: list[float], period: int, at_idx: int) -> float | None:
    if at_idx + 1 < period:
        return None
    window = values[at_idx - period + 1 : at_idx + 1]
    return sum(window) / len(window)


def ema(values: list[float], period: int, at_idx: int) -> float | None:
    if at_idx + 1 < period:
        return None
    m = 2.0 / (period + 1)
    window = values[: at_idx + 1]
    e = sum(window[:period]) / period
    for v in window[period:]:
        e = v * m + e * (1 - m)
    return e


def build_panel_svg(
    title: str,
    subtitle: str,
    bars: list[dict],
    x_off: int,
    width: int,
    panel_h: int,
    annotations: list[dict],
    shape: str,
    score: str,
    total_gain: str,
) -> str:
    """Return SVG markup for one ticker panel (candlesticks + volume + notes)."""
    # Layout within panel
    pad_l, pad_r, pad_t, pad_b = 60, 25, 60, 30
    gap_price_vol = 10
    price_h = int(panel_h * 0.62)
    vol_h = panel_h - price_h - gap_price_vol - pad_t - pad_b - 40  # 40 for shape/score box

    plot_w = width - pad_l - pad_r
    price_plot_top = pad_t
    price_plot_bot = pad_t + price_h
    vol_plot_top = price_plot_bot + gap_price_vol
    vol_plot_bot = vol_plot_top + vol_h

    # Price scale
    lo = min(b["low"] for b in bars) * 0.998
    hi = max(b["high"] for b in bars) * 1.002
    rng = hi - lo

    # Volume scale
    vmax = max(b["volume"] for b in bars) * 1.05
    avg_vol = sum(b["volume"] for b in bars[:10]) / 10 if len(bars) >= 10 else sum(b["volume"] for b in bars) / len(bars)

    n = len(bars)
    bar_w = plot_w / n * 0.75
    step = plot_w / n

    def y_price(p: float) -> float:
        return price_plot_top + (hi - p) / rng * price_h

    def y_vol(v: float) -> float:
        return vol_plot_bot - (v / vmax) * vol_h

    parts = [f'<g transform="translate({x_off}, 0)">']

    # Panel border + title
    parts.append(f'<rect x="10" y="10" width="{width - 20}" height="{panel_h - 20}" rx="8" fill="none" stroke="{GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{width // 2}" y="35" text-anchor="middle" fill="{TEXT}" font-family="monospace" font-size="18" font-weight="700">{title}</text>')
    parts.append(f'<text x="{width // 2}" y="53" text-anchor="middle" fill="{TEXT_DIM}" font-family="monospace" font-size="11">{subtitle}</text>')

    # Y-axis price labels
    for i in range(5):
        p = lo + (rng * i / 4)
        y = y_price(p)
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{pad_l + plot_w}" y2="{y}" stroke="{GRID}" stroke-width="0.5" stroke-dasharray="2,4"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{y + 3}" text-anchor="end" fill="{TEXT_DIM}" font-family="monospace" font-size="9">${p:.0f}</text>')

    # EMA 21 line
    closes = [b["close"] for b in bars]
    ema_pts = []
    for i in range(len(bars)):
        e = ema(closes, 21, i)
        if e is not None:
            x = pad_l + step * (i + 0.5)
            ema_pts.append(f"{x},{y_price(e)}")
    if len(ema_pts) > 1:
        parts.append(f'<polyline points="{" ".join(ema_pts)}" fill="none" stroke="{ACCENT}" stroke-width="1.5" opacity="0.7"/>')
        parts.append(f'<text x="{pad_l + plot_w - 4}" y="{y_price(ema(closes, 21, len(bars)-1)) - 4}" text-anchor="end" fill="{ACCENT}" font-family="monospace" font-size="9" opacity="0.9">EMA21</text>')

    # Candlesticks
    for i, b in enumerate(bars):
        x_center = pad_l + step * (i + 0.5)
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        is_up = c >= o
        color = UP_COLOR if is_up else DOWN_COLOR
        # Wick
        parts.append(f'<line x1="{x_center}" y1="{y_price(h)}" x2="{x_center}" y2="{y_price(l)}" stroke="{color}" stroke-width="1"/>')
        # Body
        y_top = y_price(max(o, c))
        y_bot = y_price(min(o, c))
        body_h = max(1, y_bot - y_top)
        parts.append(f'<rect x="{x_center - bar_w / 2}" y="{y_top}" width="{bar_w}" height="{body_h}" fill="{color}" stroke="{color}" stroke-width="0.5"/>')

    # X axis (date labels)
    for i, b in enumerate(bars):
        if i % max(1, n // 8) == 0 or i == n - 1:
            x_center = pad_l + step * (i + 0.5)
            date_short = b["time"][5:]  # MM-DD
            parts.append(f'<text x="{x_center}" y="{price_plot_bot + 14}" text-anchor="middle" fill="{TEXT_DIM}" font-family="monospace" font-size="9">{date_short}</text>')

    # Volume bars
    for i, b in enumerate(bars):
        x_center = pad_l + step * (i + 0.5)
        v = b["volume"]
        is_up = b["close"] >= b["open"]
        color = UP_COLOR if is_up else DOWN_COLOR
        y_top = y_vol(v)
        parts.append(f'<rect x="{x_center - bar_w / 2}" y="{y_top}" width="{bar_w}" height="{vol_plot_bot - y_top}" fill="{color}" opacity="0.55"/>')

    # Avg volume line
    y_avg = y_vol(avg_vol)
    parts.append(f'<line x1="{pad_l}" y1="{y_avg}" x2="{pad_l + plot_w}" y2="{y_avg}" stroke="{TEXT_DIM}" stroke-width="0.8" stroke-dasharray="3,3"/>')
    parts.append(f'<text x="{pad_l + 4}" y="{y_avg - 3}" fill="{TEXT_DIM}" font-family="monospace" font-size="8">avg vol</text>')

    # Volume label
    parts.append(f'<text x="{pad_l - 6}" y="{vol_plot_top + 10}" text-anchor="end" fill="{TEXT_DIM}" font-family="monospace" font-size="9">VOL</text>')

    # Annotations (arrows + labels above/below specific candles)
    for ann in annotations:
        date = ann["date"]
        label = ann["label"]
        color = ann.get("color", ACCENT)
        try:
            i = next(idx for idx, b in enumerate(bars) if b["time"] == date)
        except StopIteration:
            continue
        x_center = pad_l + step * (i + 0.5)
        bar = bars[i]
        y_high = y_price(bar["high"])
        # Arrow + label above the candle
        parts.append(f'<circle cx="{x_center}" cy="{y_high - 8}" r="3" fill="{color}"/>')
        parts.append(f'<line x1="{x_center}" y1="{y_high - 8}" x2="{x_center}" y2="{y_high - 4}" stroke="{color}" stroke-width="1.5"/>')
        parts.append(f'<text x="{x_center}" y="{y_high - 15}" text-anchor="middle" fill="{color}" font-family="monospace" font-size="10" font-weight="700">{label}</text>')

    # Bottom info box (shape + score + gain)
    box_y = panel_h - pad_b - 35
    shape_color = SQUEEZE_CLR if shape == "SQUEEZE" else MEASURED_CLR
    parts.append(f'<rect x="{pad_l}" y="{box_y}" width="{plot_w}" height="28" rx="4" fill="{shape_color}11" stroke="{shape_color}44" stroke-width="1"/>')
    parts.append(f'<text x="{pad_l + 10}" y="{box_y + 18}" fill="{shape_color}" font-family="monospace" font-size="11" font-weight="700">{shape}</text>')
    parts.append(f'<text x="{pad_l + plot_w / 2}" y="{box_y + 18}" text-anchor="middle" fill="{TEXT}" font-family="monospace" font-size="11">Total: {total_gain}</text>')
    parts.append(f'<text x="{pad_l + plot_w - 10}" y="{box_y + 18}" text-anchor="end" fill="{TEXT}" font-family="monospace" font-size="11">Score: {score}</text>')

    parts.append('</g>')
    return "\n".join(parts)


async def main():
    msft = await fetch("MSFT")
    tsla = await fetch("TSLA")

    # Trim to display window (we have more for EMA calc, but show last ~20 bars)
    display_n = 20
    msft_disp = msft[-display_n:]
    tsla_disp = tsla[-display_n:]

    # Annotations
    msft_ann = [
        {"date": "2026-04-13", "label": "DAY 1", "color": MEASURED_CLR},
        {"date": "2026-04-14", "label": "DAY 2", "color": MEASURED_CLR},
        {"date": "2026-04-15", "label": "DAY 3", "color": ACCENT},
    ]
    tsla_ann = [
        {"date": "2026-04-13", "label": "accum.", "color": TEXT_DIM},
        {"date": "2026-04-14", "label": "accum.", "color": TEXT_DIM},
        {"date": "2026-04-15", "label": "SQUEEZE!", "color": SQUEEZE_CLR},
    ]

    # MSFT gain
    msft_entry = msft[-5]["close"]  # Apr 10 (5 bars back from Apr 15)
    msft_exit = msft[-1]["close"]
    msft_gain = (msft_exit - msft_entry) / msft_entry * 100

    # TSLA: Day 1 gain (single-day squeeze)
    tsla_prev = tsla[-2]["close"]
    tsla_exit = tsla[-1]["close"]
    tsla_gain = (tsla_exit - tsla_prev) / tsla_prev * 100

    # Canvas
    panel_w, panel_h = 600, 520
    total_w = panel_w * 2
    total_h = panel_h + 90  # extra for header

    # Header
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" width="{total_w}" height="{total_h}">',
        f'<rect width="{total_w}" height="{total_h}" fill="{BG}"/>',
        # Title
        f'<text x="{total_w / 2}" y="35" text-anchor="middle" fill="{TEXT}" font-family="monospace" font-size="22" font-weight="800">MSFT vs TSLA — April 2026 Multi-Day Runners</text>',
        f'<text x="{total_w / 2}" y="58" text-anchor="middle" fill="{TEXT_DIM}" font-family="monospace" font-size="12">Same outcome, different geometry. Runner Tracker caught both.</text>',
    ]

    # MSFT panel
    parts.append(f'<g transform="translate(0, 80)">')
    parts.append(build_panel_svg(
        title="MSFT — MEASURED 3-Day Stair-Step",
        subtitle="Day 1: +3.64% · Day 2: +2.27% · Day 3: +4.61% · RVOL: 1.1x → 1.2x → 1.4x",
        bars=msft_disp,
        x_off=0, width=panel_w, panel_h=panel_h,
        annotations=msft_ann,
        shape="MEASURED",
        score="13/20",
        total_gain=f"+{msft_gain:.2f}%",
    ))
    parts.append('</g>')

    # TSLA panel
    parts.append(f'<g transform="translate(0, 80)">')
    parts.append(build_panel_svg(
        title="TSLA — SQUEEZE Single-Day Detonation",
        subtitle="Accumulation... Accumulation... +7.62% on 1.74x RVOL · Range: 2x ATR",
        bars=tsla_disp,
        x_off=panel_w, width=panel_w, panel_h=panel_h,
        annotations=tsla_ann,
        shape="SQUEEZE",
        score="12/20",
        total_gain=f"+{tsla_gain:.2f}% (D1 only)",
    ))
    parts.append('</g>')

    parts.append('</svg>')
    svg = "\n".join(parts)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>MSFT vs TSLA — Runner Tracker Comparison</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: {BG};
      color: {TEXT};
      font-family: -apple-system, system-ui, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
    }}
    .legend {{
      display: flex;
      gap: 24px;
      margin-top: 16px;
      font-family: monospace;
      font-size: 11px;
      color: {TEXT_DIM};
    }}
    .legend span {{
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 2px;
      margin-right: 4px;
      vertical-align: middle;
    }}
    footer {{
      margin-top: 24px;
      font-family: monospace;
      font-size: 10px;
      color: {TEXT_DIM};
    }}
  </style>
</head>
<body>
  {svg}
  <div class="legend">
    <div><span style="background:{UP_COLOR}"></span>Up candle</div>
    <div><span style="background:{DOWN_COLOR}"></span>Down candle</div>
    <div><span style="background:{ACCENT}"></span>EMA21</div>
    <div><span style="background:{MEASURED_CLR}"></span>MEASURED shape</div>
    <div><span style="background:{SQUEEZE_CLR}"></span>SQUEEZE shape</div>
  </div>
  <footer>Data: Tradier daily bars · Generated by scripts/plot_runner_comparison.py</footer>
</body>
</html>
"""
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(f"MSFT: {msft_disp[0]['time']} to {msft_disp[-1]['time']}, {len(msft_disp)} bars, gain {msft_gain:+.2f}%")
    print(f"TSLA: {tsla_disp[0]['time']} to {tsla_disp[-1]['time']}, {len(tsla_disp)} bars, Day 1 gain {tsla_gain:+.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
