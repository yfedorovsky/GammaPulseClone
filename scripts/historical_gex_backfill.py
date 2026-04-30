"""Historical GEX backfill — reconstructs daily snapshots from ThetaData.

The Apr 28 audit revealed n=4 fires across 22 days because GEX snapshot
data only goes back ~10 days. This script backfills synthetic daily
snapshots so we can validate the Structural Turn detector across months
of historical data.

## What it does

For each (ticker, day) pair in [SPY, QQQ, IWM, SPX] × past N trading days:
  1. Determine front-week expiry to use (next Friday from that date)
  2. List option strikes for that expiry
  3. Filter to strikes within ±5% of session spot
  4. Pull EOD greeks + OI per strike (calls — gamma is symmetric per Black-Scholes)
  5. Compute per-strike dealer net gamma assuming standard SpotGamma framing
     (dealers short calls, long puts):
       dealer_gamma = -OI_call × gamma + OI_put × gamma
                   = gamma × (OI_put − OI_call)
  6. Aggregate to king/floor/ceiling/zgl/regime/pos_gex/neg_gex
  7. Insert ONE synthetic snapshot at 09:30 ET that day into snapshots.db

## Limitations

- Only EOD greeks available on ThetaData Standard sub (intraday requires
  Professional). So we get 1 snapshot per day instead of the usual 6-12.
- Gate 2 (floor reclaim) requires intraday snapshot history — backfilled
  days will rely on the floor-hold proxy not the migration event. This
  reduces fire count somewhat.
- The greeks pulled are EOD (16:14 ET roughly). Used as proxy for
  morning-session structure — typically valid since GEX is stable
  intraday for index ETFs.

## Usage

  python scripts/historical_gex_backfill.py --tickers SPY,QQQ,IWM,SPX --days 90
  python scripts/historical_gex_backfill.py --resume   # picks up from checkpoint

Checkpointing: tracks completed (ticker, day) pairs in a JSON file so the
script is restartable mid-run.

Rate limit: throttles to 50 req/sec to stay well below ThetaData Standard's
limit. ~70 strikes × 3 calls (greeks + OI_call + OI_put) per (ticker, day)
× 4 tickers × 90 days = ~75K calls, ~25 min runtime at 50/sec.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

load_dotenv(Path(__file__).parent.parent / ".env")

THETA = "http://127.0.0.1:25503"
TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN", "")
TRADIER_BASE = os.environ.get("TRADIER_BASE_URL",
                              "https://api.tradier.com/v1").rstrip("/")

SNAPSHOTS_DB = "./snapshots.db"
CHECKPOINT_PATH = Path("./.gex_backfill_checkpoint.json")
LOG_PATH = Path("./gex_backfill.log")

# Strike filter: ±5% of spot covers >95% of relevant gamma
STRIKE_RANGE_PCT = 0.05

# Throttle: ThetaData Standard caps around 100 req/sec; we run at 50 to be safe
RATE_LIMIT_PER_SEC = 50
SLEEP_PER_REQ = 1.0 / RATE_LIMIT_PER_SEC

# Contract multiplier (standard for equity options)
MULTIPLIER = 100


def log(msg: str) -> None:
    """Persistent + stdout logging."""
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_checkpoint() -> set[str]:
    if not CHECKPOINT_PATH.exists():
        return set()
    try:
        return set(json.loads(CHECKPOINT_PATH.read_text()))
    except Exception:
        return set()


def save_checkpoint(done: set[str]) -> None:
    try:
        CHECKPOINT_PATH.write_text(json.dumps(sorted(done)))
    except Exception:
        pass


def trading_days_back(end: datetime, days: int) -> list[datetime]:
    """Walk BACKWARD from end, collecting weekdays. Returns chronological order."""
    out = []
    d = end
    while len(out) < days:
        if d.weekday() < 5:
            out.append(d.replace(hour=0, minute=0, second=0, microsecond=0))
        d -= timedelta(days=1)
    return list(reversed(out))


def front_week_expiry(day: datetime) -> str:
    """Pick the front-week Friday expiry for backfill purposes.
    For SPY/QQQ/IWM/SPX, the front weekly captures most of the dominant
    gamma. We use 'next Friday' from the target day; if day IS Friday,
    use that day's expiry."""
    days_to_friday = (4 - day.weekday()) % 7
    if days_to_friday == 0 and day.weekday() == 4:
        # Friday itself
        target = day
    else:
        target = day + timedelta(days=days_to_friday or 7)
    return target.strftime("%Y-%m-%d")


def get_spot(ticker: str, day: datetime) -> float | None:
    """Get the day's open price from Tradier (preferred) or yfinance fallback."""
    if TRADIER_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_BASE}/markets/history",
                params={"symbol": ticker, "interval": "daily",
                        "start": day.strftime("%Y-%m-%d"),
                        "end": day.strftime("%Y-%m-%d")},
                headers={"Authorization": f"Bearer {TRADIER_TOKEN}",
                         "Accept": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get("history") or {}
                bars = data.get("day") or []
                if isinstance(bars, dict):
                    bars = [bars]
                if bars:
                    return float(bars[0]["open"])
        except Exception:
            pass
    # Fallback: yfinance daily
    try:
        df = yf.Ticker(ticker).history(
            start=day.strftime("%Y-%m-%d"),
            end=(day + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d", prepost=False,
        )
        if not df.empty:
            return float(df.iloc[0]["Open"])
    except Exception:
        pass
    return None


def list_strikes(symbol: str, expiration: str) -> list[float]:
    try:
        r = requests.get(
            f"{THETA}/v3/option/list/strikes",
            params={"symbol": symbol, "expiration": expiration},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or "strike" not in df.columns:
            return []
        return sorted(df["strike"].astype(float).unique().tolist())
    except Exception:
        return []


def fetch_greeks_eod(symbol: str, expiration: str, strike: float,
                    right: str, day_str: str) -> dict | None:
    """Pull EOD greeks for one (strike, right) on one day."""
    try:
        r = requests.get(
            f"{THETA}/v3/option/history/greeks/eod",
            params={"symbol": symbol, "expiration": expiration,
                    "strike": f"{strike:.3f}", "right": right,
                    "start_date": day_str, "end_date": day_str},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty:
            return None
        row = df.iloc[0]
        gamma = row.get("gamma")
        underlying = row.get("underlying_price")
        if gamma is None or pd.isna(gamma):
            return None
        return {"gamma": float(gamma),
                "spot": float(underlying) if underlying else None}
    except Exception:
        return None


def fetch_oi(symbol: str, expiration: str, strike: float,
             right: str, day_str: str) -> int | None:
    """Pull EOD OI for one (strike, right)."""
    try:
        r = requests.get(
            f"{THETA}/v3/option/history/open_interest",
            params={"symbol": symbol, "expiration": expiration,
                    "strike": f"{strike:.3f}", "right": right,
                    "start_date": day_str, "end_date": day_str},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty:
            return None
        return int(df.iloc[-1]["open_interest"])
    except Exception:
        return None


def compute_gex_state(strikes_data: list[dict], spot: float) -> dict:
    """Aggregate per-strike dealer gamma into king/floor/ceiling/zgl/regime."""
    # Sort by strike
    rows = [r for r in strikes_data if r.get("net_gamma") is not None]
    if not rows:
        return {}
    rows.sort(key=lambda r: r["strike"])

    # King = strike with most positive net gamma
    pos_rows = [r for r in rows if r["net_gamma"] > 0]
    king = max(pos_rows, key=lambda r: r["net_gamma"])["strike"] if pos_rows else None

    # Floor = strike with most negative net gamma BELOW spot
    neg_below = [r for r in rows if r["net_gamma"] < 0 and r["strike"] < spot]
    floor = (min(neg_below, key=lambda r: r["net_gamma"])["strike"]
             if neg_below else None)

    # Ceiling = strike with most negative net gamma ABOVE spot
    neg_above = [r for r in rows if r["net_gamma"] < 0 and r["strike"] > spot]
    ceiling = (min(neg_above, key=lambda r: r["net_gamma"])["strike"]
               if neg_above else None)

    # Pos/Neg GEX in dollars: gamma × OI × multiplier × spot²/100
    # (Standard SpotGamma scaling — gamma units → dollar gamma per 1% spot move)
    pos_gex = sum(r["net_gamma"] for r in rows if r["net_gamma"] > 0) * spot * MULTIPLIER * spot / 100
    neg_gex = sum(r["net_gamma"] for r in rows if r["net_gamma"] < 0) * spot * MULTIPLIER * spot / 100

    # ZGL = strike where cumulative net gamma crosses zero (walk low to high)
    cum = 0.0
    zgl = None
    for r in rows:
        new_cum = cum + r["net_gamma"]
        if cum >= 0 and new_cum < 0:
            zgl = r["strike"]
            break
        if cum <= 0 and new_cum > 0:
            zgl = r["strike"]
            break
        cum = new_cum
    if zgl is None:
        # Fallback: midpoint between most positive and most negative
        if pos_rows and (neg_below or neg_above):
            all_neg = neg_below + neg_above
            most_neg = min(all_neg, key=lambda r: r["net_gamma"])["strike"]
            most_pos = max(pos_rows, key=lambda r: r["net_gamma"])["strike"]
            zgl = (most_pos + most_neg) / 2

    regime = "POS" if abs(pos_gex) > abs(neg_gex) else "NEG"
    signal = "MAGNET UP" if regime == "POS" else "MAGNET FADE"

    return {
        "king": king, "floor": floor, "ceiling": ceiling, "zgl": zgl,
        "pos_gex": pos_gex, "neg_gex": neg_gex,
        "regime": regime, "signal": signal,
    }


def insert_synthetic_snapshot(ticker: str, day: datetime,
                               spot: float, gex: dict) -> None:
    """Insert a synthetic snapshot at 09:30 ET on the given day."""
    ts = int(day.replace(hour=9, minute=30, second=0).timestamp())
    conn = sqlite3.connect(SNAPSHOTS_DB, timeout=30)
    try:
        conn.execute(
            """INSERT INTO snapshots (
                 ticker, ts, spot, king, floor, ceiling, zgl,
                 signal, regime, pos_gex, neg_gex, net_delta, net_vanna, iv
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, ts, spot,
             gex.get("king"), gex.get("floor"), gex.get("ceiling"),
             gex.get("zgl"), gex.get("signal"), gex.get("regime"),
             gex.get("pos_gex"), gex.get("neg_gex"),
             None, None, None),
        )
        conn.commit()
    finally:
        conn.close()


def process_ticker_day(ticker: str, day: datetime) -> tuple[bool, str]:
    """Returns (success, message)."""
    sym = "SPXW" if ticker == "SPX" else ticker
    day_str = day.strftime("%Y-%m-%d")
    expiration = front_week_expiry(day)

    spot = get_spot(ticker, day)
    if spot is None:
        return False, f"no spot for {ticker} {day_str}"

    strikes = list_strikes(sym, expiration)
    if not strikes:
        return False, f"no strikes for {sym} exp {expiration}"

    # Filter to ±5% of spot
    lo = spot * (1 - STRIKE_RANGE_PCT)
    hi = spot * (1 + STRIKE_RANGE_PCT)
    strikes = [s for s in strikes if lo <= s <= hi]
    if not strikes:
        return False, f"no strikes in ±5% range for {sym}"

    strikes_data = []
    for k in strikes:
        # Pull greeks (call) + OI for both sides
        time.sleep(SLEEP_PER_REQ)
        greeks = fetch_greeks_eod(sym, expiration, k, "C", day_str)
        if greeks is None or greeks.get("gamma") is None:
            continue
        gamma = greeks["gamma"]

        time.sleep(SLEEP_PER_REQ)
        oi_call = fetch_oi(sym, expiration, k, "C", day_str)
        time.sleep(SLEEP_PER_REQ)
        oi_put = fetch_oi(sym, expiration, k, "P", day_str)
        if oi_call is None and oi_put is None:
            continue
        oi_call = oi_call or 0
        oi_put = oi_put or 0
        # SpotGamma convention used by the live worker:
        #   net_gamma_per_strike = gamma × (OI_call − OI_put)
        # Above spot, calls dominate → positive net gamma → king (call wall)
        # Below spot, puts dominate → negative net gamma → floor (put wall)
        # (Earlier sign convention was inverted — fixed Apr 29 morning.)
        net_gamma = gamma * (oi_call - oi_put)
        strikes_data.append({
            "strike": k, "gamma": gamma,
            "oi_call": oi_call, "oi_put": oi_put,
            "net_gamma": net_gamma,
        })

    if not strikes_data:
        return False, f"no greek data for any strike of {sym} {day_str}"

    gex = compute_gex_state(strikes_data, spot)
    if not gex:
        return False, "compute_gex_state returned empty"

    insert_synthetic_snapshot(ticker, day, spot, gex)
    return True, (f"{ticker} {day_str}: spot=${spot:.2f}  "
                  f"king=${gex.get('king') or 0:.0f}  floor=${gex.get('floor') or 0:.0f}  "
                  f"zgl=${gex.get('zgl') or 0:.0f}  regime={gex['regime']}  "
                  f"({len(strikes_data)} strikes)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM,SPX")
    ap.add_argument("--days", type=int, default=90,
                    help="Trading days back to backfill")
    ap.add_argument("--resume", action="store_true",
                    help="Skip (ticker, day) pairs already in checkpoint")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    end_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = trading_days_back(end_day, args.days)
    log(f"Tickers: {tickers}")
    log(f"Days: {len(days)} trading days from {days[0]:%Y-%m-%d} to {days[-1]:%Y-%m-%d}")

    done = load_checkpoint() if args.resume else set()
    if args.resume:
        log(f"Resuming from checkpoint: {len(done)} pairs already done")

    total = len(tickers) * len(days)
    processed = 0
    success = 0
    failed = 0

    for d in days:
        for t in tickers:
            key = f"{t}|{d:%Y-%m-%d}"
            if key in done:
                processed += 1
                continue
            try:
                ok, msg = process_ticker_day(t, d)
                if ok:
                    success += 1
                    log(f"  ✓ {msg}")
                else:
                    failed += 1
                    log(f"  ✗ {msg}")
            except Exception as e:
                failed += 1
                log(f"  ✗ {t} {d:%Y-%m-%d} error: {e}")
            done.add(key)
            processed += 1
            if processed % 10 == 0:
                save_checkpoint(done)
                log(f"Progress: {processed}/{total}  "
                    f"({success} ok, {failed} failed)")

    save_checkpoint(done)
    log(f"\nFINAL: {processed}/{total} processed, "
        f"{success} succeeded, {failed} failed")
    log(f"Checkpoint saved to {CHECKPOINT_PATH}")
    log(f"Run: python scripts/structural_turn_backtest_30d.py --days {args.days} --bars-source tradier")
    return 0


if __name__ == "__main__":
    sys.exit(main())
