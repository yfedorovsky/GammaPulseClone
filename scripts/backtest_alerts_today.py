"""Backtest the day's Telegram alerts against real ThetaData option quotes.

Parses telegram_alerts_sample/alerts_*.txt, extracts every alert that has
a concrete option contract, pulls intraday quote history from ThetaData,
and reports per-alert + per-type MFE / MAE / end-of-day outcomes.

The point is to validate the Apr 27 changes:
  - Structural risk-factor guard on A-grade SOE (replaces signal_type
    blacklist). Did the surviving A grades perform better than blocked ones?
  - SETUP FORMING alerts now persisted. Did the scoring rubric work today?
  - UPSIDE BET institutional flow — does following these actually work?

Run:
    python scripts/backtest_alerts_today.py [path/to/alerts.txt]
"""
from __future__ import annotations

import io
import re
import sys
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

import pandas as pd
import requests

THETA = "http://127.0.0.1:25503"
DEFAULT_FILE = Path("telegram_alerts_sample/alerts 0427.txt")


# ── Regex patterns for each alert type ──────────────────────────────

ALERT_HEADER_RE = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s+[AP]M)\]")

SOE_RE = re.compile(
    r"SOE\s+([AB]\+?):\s+[▲▼]\s+(\w+)\s*\n"
    r"([A-Z][A-Z _]+)\s*\n"
    r"\$?([\d.]+)\s+(CALL|PUT)\s+(\d{4}-\d{2}-\d{2})\s+(\d+)d\s*\n.*?"
    r"Entry:\s+\$?([\d.]+).*?"
    r"Target:\s+\$?([\d.]+).*?"
    r"Stop:\s+\$?([\d.]+).*?"
    r"R:R:\s+([\d.]+)x\s+\|\s+Score:\s+([\d.]+)/(\d+).*?"
    r"Mid:\s+\$?([\d.]+)",
    re.DOTALL,
)

SETUP_RE = re.compile(
    r"SETUP FORMING:\s+(\w+)\s*\n"
    r"Score:\s+(\d+)/(\d+)\s+\|\s+RTS:\s+(\d+)\s*\n"
    r"Spot:\s+\$?([\d.]+).*?"
    r"Regime:\s+(\w+)\s+\|\s+(\w[\w ]+?)\n.*?"
    r">>\s+(\w+)\s+\$?([\d.]+)\s+(CALL|PUT)\s+(\d{4}-\d{2}-\d{2})\s+\((\d+)DTE\)\s+@\$?([\d.]+)",
    re.DOTALL,
)

UPSIDE_RE = re.compile(
    r"UPSIDE BET:\s+(\w+)\s*\n"
    r"[🟢🔴]\s+\$?([\d.]+)\s+(CALL|PUT)\s+(\d{4}-\d{2}-\d{2})\s+\((\d+)d\)\s*\n.*?"
    r"Notional:\s+\$?([\d,]+)\s+(BOUGHT|SOLD)\s+(\d+)%.*?"
    r"Largest:\s+(\d+)\s+@\s+\$?([\d.]+).*?"
    r"Spot:\s+\$?([\d.]+)",
    re.DOTALL,
)


def parse_alerts(path: Path) -> list[dict]:
    """Parse every alert with a concrete contract. Skips NET FLOW (no contract)
    and 0DTE ALERT (separate DB)."""
    text = path.read_text(encoding="utf-8")
    # Split on the timestamp header so we get one alert per chunk
    chunks = re.split(r"(?=^\[\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\])",
                      text, flags=re.MULTILINE)
    out = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        header_m = ALERT_HEADER_RE.match(chunk)
        if not header_m:
            continue
        date_str, time_str = header_m.group(1), header_m.group(2)
        try:
            ts = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M %p")
        except ValueError:
            continue

        # Try each alert pattern
        m = SOE_RE.search(chunk)
        if m:
            out.append({
                "type": f"SOE {m.group(1)}",
                "ts": ts,
                "ticker": m.group(2),
                "signal_type": m.group(3).strip(),
                "strike": float(m.group(4)),
                "right": m.group(5),
                "expiration": m.group(6),
                "dte": int(m.group(7)),
                "entry_price": float(m.group(8)),
                "target_spot": float(m.group(9)),
                "stop_spot": float(m.group(10)),
                "rr": float(m.group(11)),
                "score": float(m.group(12)),
                "max_score": float(m.group(13)),
                "entry_mid": float(m.group(14)),
            })
            continue

        m = SETUP_RE.search(chunk)
        if m:
            out.append({
                "type": "SETUP FORMING",
                "ts": ts,
                "ticker": m.group(1),
                "score": int(m.group(2)),
                "max_score": int(m.group(3)),
                "rts": int(m.group(4)),
                "spot": float(m.group(5)),
                "regime": m.group(6),
                "signal": m.group(7).strip(),
                "strike": float(m.group(9)),
                "right": m.group(10),
                "expiration": m.group(11),
                "dte": int(m.group(12)),
                "entry_mid": float(m.group(13)),
            })
            continue

        m = UPSIDE_RE.search(chunk)
        if m:
            out.append({
                "type": "UPSIDE BET",
                "ts": ts,
                "ticker": m.group(1),
                "strike": float(m.group(2)),
                "right": m.group(3),
                "expiration": m.group(4),
                "dte": int(m.group(5)),
                "notional": int(m.group(6).replace(",", "")),
                "side": m.group(7),
                "side_pct": int(m.group(8)),
                "largest_size": int(m.group(9)),
                "largest_price": float(m.group(10)),
                "spot": float(m.group(11)),
                "entry_mid": float(m.group(10)),
            })
            continue
    return out


def fetch_quotes(ticker: str, exp: str, strike: float, right: str,
                 date_iso: str) -> pd.DataFrame:
    """Pull 1-min option quote history for a contract on a specific date."""
    if "SPX" in ticker.upper():
        # SPX index options use SPXW or SPX root in OPRA
        symbol_attempts = ["SPXW", "SPX"]
    else:
        symbol_attempts = [ticker]

    for sym in symbol_attempts:
        params = {
            "symbol": sym,
            "expiration": exp,
            "strike": f"{strike:.3f}",
            "right": right[0].upper(),
            "start_date": date_iso,
            "end_date": date_iso,
            "interval": "1m",
        }
        try:
            r = requests.get(f"{THETA}/v3/option/history/quote",
                             params=params, timeout=20)
            if r.status_code != 200:
                continue
            df = pd.read_csv(io.StringIO(r.text))
        except Exception:
            continue
        if not df.empty:
            df["ts"] = pd.to_datetime(df["timestamp"])
            df = df[(df["bid"] > 0) | (df["ask"] > 0)]
            if not df.empty:
                df["mid"] = (df["bid"] + df["ask"]) / 2
                return df
    return pd.DataFrame()


def compute_outcome(alert: dict, df: pd.DataFrame) -> dict | None:
    """Slice df from alert ts to market close (16:00 ET), compute MFE/MAE/end."""
    if df.empty:
        return None
    market_close = alert["ts"].replace(hour=16, minute=0, second=0)
    sub = df[(df["ts"] >= alert["ts"]) & (df["ts"] <= market_close)]
    if sub.empty:
        return None

    entry = alert["entry_mid"]
    if entry <= 0:
        return None

    max_mid = sub["mid"].max()
    min_mid = sub["mid"].min()
    end_mid = sub["mid"].iloc[-1]

    return {
        "ticker": alert["ticker"],
        "type": alert["type"],
        "signal_type": alert.get("signal_type", ""),
        "score": alert.get("score"),
        "rr": alert.get("rr"),
        "entry": entry,
        "max_mid": max_mid,
        "min_mid": min_mid,
        "end_mid": end_mid,
        "mfe_pct": (max_mid / entry - 1) * 100,
        "mae_pct": (min_mid / entry - 1) * 100,
        "end_pct": (end_mid / entry - 1) * 100,
        "hit_50": max_mid >= entry * 1.5,
        "hit_100": max_mid >= entry * 2.0,
        "stopped_50": min_mid <= entry * 0.5,
        "n_quotes": len(sub),
        "minutes_held": int((sub["ts"].iloc[-1] - alert["ts"]).total_seconds() / 60),
    }


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    print(f"Parsing {path}...")
    alerts = parse_alerts(path)
    print(f"  Parsed {len(alerts)} alerts with contract details")
    by_type = {}
    for a in alerts:
        by_type.setdefault(a["type"], 0)
        by_type[a["type"]] += 1
    for t, n in sorted(by_type.items()):
        print(f"    {t}: {n}")

    print("\nPulling ThetaData quotes for each contract...")
    results = []
    skipped = []
    for i, a in enumerate(alerts):
        date_iso = a["ts"].strftime("%Y-%m-%d")
        df = fetch_quotes(a["ticker"], a["expiration"], a["strike"],
                          a["right"], date_iso)
        if df.empty:
            skipped.append(f"{a['ticker']} {a['strike']:.0f}{a['right'][0]} "
                           f"{a['ts'].strftime('%H:%M')} — no quotes")
            continue
        out = compute_outcome(a, df)
        if out is None:
            skipped.append(f"{a['ticker']} {a['strike']:.0f}{a['right'][0]} "
                           f"{a['ts'].strftime('%H:%M')} — no quotes in window")
            continue
        results.append(out)
        if (i + 1) % 10 == 0:
            print(f"  ...{i+1}/{len(alerts)}")

    if not results:
        print("No quotable results.")
        return 1

    df = pd.DataFrame(results)
    print(f"\n{len(df)} alerts with full quote history. {len(skipped)} skipped.")

    # ── Per-alert detail ───────────────────────────────────────────
    print("\n" + "=" * 100)
    print("PER-ALERT DETAIL (sorted by MFE)")
    print("=" * 100)
    print(f"{'Ticker':<8}{'Type':<16}{'SignalType':<22}{'Score':>6}{'Entry':>8}"
          f"{'MFE':>8}{'MAE':>8}{'End':>8}{'50%':>5}{'100%':>5}")
    print("-" * 100)
    for _, r in df.sort_values("mfe_pct", ascending=False).iterrows():
        print(f"{r['ticker']:<8}{r['type']:<16}"
              f"{(r['signal_type'] or '')[:20]:<22}"
              f"{(r['score'] or 0):>6.1f}"
              f"{r['entry']:>8.2f}"
              f"{r['mfe_pct']:>+7.0f}%"
              f"{r['mae_pct']:>+7.0f}%"
              f"{r['end_pct']:>+7.0f}%"
              f"{'Y' if r['hit_50'] else '·':>5}"
              f"{'Y' if r['hit_100'] else '·':>5}")

    # ── By type aggregate ──────────────────────────────────────────
    print("\n" + "=" * 100)
    print("BY ALERT TYPE")
    print("=" * 100)
    print(f"{'Type':<20}{'n':>4}{'AvgMFE':>9}{'AvgMAE':>9}{'AvgEnd':>9}"
          f"{'%End>0':>9}{'%Hit50':>9}{'%Hit100':>10}")
    print("-" * 100)
    for typ, sub in df.groupby("type"):
        print(f"{typ:<20}{len(sub):>4}"
              f"{sub['mfe_pct'].mean():>+8.0f}%"
              f"{sub['mae_pct'].mean():>+8.0f}%"
              f"{sub['end_pct'].mean():>+8.0f}%"
              f"{(sub['end_pct'] > 0).mean()*100:>8.0f}%"
              f"{sub['hit_50'].mean()*100:>8.0f}%"
              f"{sub['hit_100'].mean()*100:>9.0f}%")

    # ── SOE by signal_type breakdown (Phase 6 audit comparison) ────
    soe = df[df["type"].str.startswith("SOE")]
    if not soe.empty:
        print("\n" + "=" * 100)
        print("SOE — by signal_type (compare to Phase 6 baseline)")
        print("=" * 100)
        print(f"{'SignalType':<25}{'Grade':<8}{'n':>4}{'AvgEnd':>9}{'%End>0':>9}{'%Hit50':>9}")
        print("-" * 100)
        for (sig, grade), sub in soe.groupby(["signal_type",
                                              soe["type"].str.split().str[1]]):
            print(f"{sig[:24]:<25}{grade:<8}{len(sub):>4}"
                  f"{sub['end_pct'].mean():>+8.0f}%"
                  f"{(sub['end_pct'] > 0).mean()*100:>8.0f}%"
                  f"{sub['hit_50'].mean()*100:>8.0f}%")

    # ── Save full CSV ─────────────────────────────────────────────
    out_csv = Path("data/backtest_alerts_today.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv}")

    if skipped:
        print(f"\nSkipped {len(skipped)} alerts (no ThetaData coverage):")
        for s in skipped[:10]:
            print(f"  {s}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
