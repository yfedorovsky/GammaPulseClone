"""PML/PMH ±0.05% touch strategy — backtest with realistic option P&L.

## Strategy spec

ENTRY (5-min timeframe):
  CALL:  first cash-session bar whose LOW comes within ±0.05% of pre-market low
  PUT:   first cash-session bar whose HIGH comes within ±0.05% of pre-market high

ADD (optional, controlled by --use-ema-add):
  After entry, if price crosses the 8-period EMA in trade direction within 60 min,
  add 50% of original size at the crossing bar's close.

POSITION SIZING (per trade, normalized to 100 units of premium):
  Entry:        100 units
  EMA add:      +50 units (optional)

EXITS (in priority order, evaluated each minute after entry):
  Stop:    -50% on weighted-avg cost basis  → close ALL
  TP1:     option mark = 2× cost basis      → sell 50% (of original 100 units)
  TP2:     option mark = 3× cost basis      → sell 25% (of original 100 units)
  Trail:   after TP1 hits, tracking peak; if mark drops by entry_premium from
           peak OR by 50% from peak (whichever is tighter)         → close remainder
  EOD:     15:55 ET                                                → close remainder

P&L is realized in % of cost basis, weighted by what fraction of the position
was active at each exit point.

## Usage

  python scripts/pml_strategy_backtest.py --tickers SPY,QQQ --days 30
  python scripts/pml_strategy_backtest.py --tickers SPY --days 14 --use-ema-add
"""
from __future__ import annotations

import argparse
import io
import os
import sys
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

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

THETA = "http://127.0.0.1:25503"
TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN", "")
TRADIER_BASE = os.environ.get("TRADIER_BASE_URL", "https://api.tradier.com/v1").rstrip("/")

OUT_REPORT = Path("docs/research/pml_strategy_backtest.md")
OUT_CSV = Path("docs/research/pml_strategy_fires.csv")

# Strategy parameters
TOUCH_TOLERANCE_PCT = 0.0005   # ±0.05% from PML/PMH
EMA_PERIOD = 8                  # 8-period EMA on 5-min closes
EMA_LONG_PERIOD = 21            # 21-period EMA for trend filter
EMA_ADD_WINDOW_MIN = 60         # Add only if EMA cross happens within 60 min of entry
EMA_ADD_SIZE = 0.5              # Adds 50% of original size
TP1_MULT = 2.0                  # Option doubles → sell 50%
TP1_FRAC = 0.5
TP2_MULT = 3.0                  # Option triples → sell 25%
TP2_FRAC = 0.25
EOD_HHMM = "15:55"              # Force-close remaining


# ── Data fetchers ─────────────────────────────────────────────────


_yf_cache: dict[tuple[str, str], pd.DataFrame] = {}


def _fetch_yf_day(ticker: str, day: datetime) -> pd.DataFrame:
    """Pull full-session 1-min bars (pre + cash + post) via yfinance.
    Cached per (ticker, day) since both PML and cash queries hit the same data."""
    key = (ticker, day.strftime("%Y-%m-%d"))
    if key in _yf_cache:
        return _yf_cache[key]
    try:
        df = yf.Ticker(ticker).history(
            start=day.strftime("%Y-%m-%d"),
            end=(day + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1m", prepost=True,
        )
    except Exception as e:
        print(f"  yfinance {ticker} {day:%Y-%m-%d}: {e}")
        df = pd.DataFrame()
    if not df.empty:
        df.index = df.index.tz_convert("America/New_York")
    _yf_cache[key] = df
    return df


def _df_to_bars(df: pd.DataFrame) -> list[dict]:
    out = []
    for t, r in df.iterrows():
        out.append({
            "ts": int(t.timestamp()),
            "hhmm": t.strftime("%H:%M"),
            "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"]),
            "volume": int(r["Volume"]),
        })
    return out


def fetch_premarket_bars(ticker: str, day: datetime) -> list[dict]:
    """Pre-market bars 04:00-09:30 ET via yfinance prepost."""
    df = _fetch_yf_day(ticker, day)
    if df.empty:
        return []
    pre = df.between_time("04:00", "09:29")
    return _df_to_bars(pre)


def fetch_cash_bars(ticker: str, day: datetime) -> list[dict]:
    """Cash-session 1-min bars 09:30-16:00 ET via yfinance."""
    df = _fetch_yf_day(ticker, day)
    if df.empty:
        return []
    cash = df.between_time("09:30", "15:59")
    return _df_to_bars(cash)


def fetch_option_quotes(symbol: str, expiration: str, strike: float,
                        right: str, date: str) -> pd.DataFrame:
    params = {"symbol": symbol, "expiration": expiration,
              "strike": f"{strike:.3f}", "right": right,
              "start_date": date, "end_date": date, "interval": "1m"}
    try:
        r = requests.get(f"{THETA}/v3/option/history/quote",
                         params=params, timeout=30)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["timestamp"])
    df["hhmm"] = df["t"].dt.strftime("%H:%M")
    df = df[(df["bid"] > 0) | (df["ask"] > 0)]
    df["mid"] = (df["bid"] + df["ask"]) / 2
    return df


# ── Bar utilities ─────────────────────────────────────────────────


def aggregate_5min(bars_1min: list[dict]) -> list[dict]:
    """Aggregate 1-min bars to 5-min bars (anchored to :00, :05, :10...)."""
    if not bars_1min:
        return []
    df = pd.DataFrame(bars_1min)
    df["t"] = pd.to_datetime(df["ts"], unit="s")
    df = df.set_index("t")
    agg = df.resample("5min", label="left").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    out = []
    for t, r in agg.iterrows():
        out.append({
            "ts": int(t.timestamp()),
            "hhmm": t.strftime("%H:%M"),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": int(r["volume"]),
        })
    return out


def compute_ema(bars: list[dict], period: int = 8, key: str = "close") -> list[float]:
    """Standard EMA on the given key. Returns list aligned with bars."""
    if not bars:
        return []
    alpha = 2 / (period + 1)
    out = [bars[0][key]]
    for i in range(1, len(bars)):
        out.append(alpha * bars[i][key] + (1 - alpha) * out[-1])
    return out


def compute_vwap(bars: list[dict]) -> list[float]:
    """Session VWAP starting from the first bar (cash session)."""
    if not bars:
        return []
    cum_pv = 0.0
    cum_v = 0
    out = []
    for b in bars:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += typical * b["volume"]
        cum_v += b["volume"]
        out.append(cum_pv / cum_v if cum_v > 0 else typical)
    return out


# ── Trade simulation ─────────────────────────────────────────────


def simulate_trade(
    entry_ts: int, entry_spot: float, direction: str,
    ticker: str, day: datetime,
    bars_5min: list[dict], bars_1min: list[dict],
    use_ema_add: bool = False,
    stop_pct: float = -0.50,
) -> dict:
    """Run one trade end-to-end. Returns dict with all outcome fields."""
    strike = round(entry_spot)
    expiry = day.strftime("%Y-%m-%d")
    sym = "SPXW" if ticker == "SPX" else ticker
    right = "C" if direction == "BULLISH" else "P"
    df = fetch_option_quotes(sym, expiry, float(strike), right,
                              day.strftime("%Y-%m-%d"))
    out = {
        "ticker": ticker, "day": day.strftime("%Y-%m-%d"),
        "direction": direction, "entry_ts": entry_ts,
        "entry_hhmm": datetime.fromtimestamp(entry_ts).strftime("%H:%M"),
        "entry_spot": entry_spot, "strike": strike, "right": right,
        "entry_ask": None, "entry_mid": None,
        "tp1_hit": False, "tp1_t": None, "tp1_price": None,
        "tp2_hit": False, "tp2_t": None, "tp2_price": None,
        "ema_add_hit": False, "ema_add_t": None, "ema_add_ask": None,
        "stopped_out": False, "stop_t": None,
        "exit_kind": None, "exit_t": None, "exit_price": None,
        "realized_pct": None, "mfe_pct": None,
    }
    if df.empty:
        out["error"] = "no option data"
        return out

    # Find entry bar
    entry_dt = datetime.fromtimestamp(entry_ts)
    entry_hhmm = entry_dt.strftime("%H:%M")
    entry_sub = df[df["hhmm"] >= entry_hhmm]
    if entry_sub.empty:
        out["error"] = "no option quote at entry time"
        return out
    entry_row = entry_sub.iloc[0]
    entry_ask = float(entry_row["ask"])
    entry_mid = float(entry_row["mid"])
    if entry_ask <= 0:
        out["error"] = "entry ask zero"
        return out

    out["entry_ask"] = entry_ask
    out["entry_mid"] = entry_mid

    # Compute 5-min EMA + the entry-bar EMA value (for add-leg detection)
    ema_5 = compute_ema(bars_5min, EMA_PERIOD)
    # Snap entry to a 5-min bar (the one whose interval contains entry_ts)
    entry_5min_idx = None
    for i, b in enumerate(bars_5min):
        if b["ts"] <= entry_ts < b["ts"] + 300:
            entry_5min_idx = i
            break
    if entry_5min_idx is None:
        # fall back: closest prior 5-min bar
        for i, b in enumerate(bars_5min):
            if b["ts"] <= entry_ts:
                entry_5min_idx = i

    # Position state — fractions of original 1.0 unit
    pos_remaining = 1.0
    cost_basis = entry_ask  # weighted-avg ask paid
    units_held = 1.0
    realized = 0.0  # cumulative realized P&L in option-$ per original unit
    peak_mid = entry_mid

    # Optional EMA-add scan: walk forward from entry, look for cross within
    # EMA_ADD_WINDOW_MIN. If found, add 0.5 units at the crossing 5-min close.
    add_done = False
    if use_ema_add and entry_5min_idx is not None:
        end_idx = min(len(bars_5min) - 1,
                      entry_5min_idx + EMA_ADD_WINDOW_MIN // 5)
        for i in range(entry_5min_idx + 1, end_idx + 1):
            prev_close = bars_5min[i - 1]["close"]
            cur_close = bars_5min[i]["close"]
            prev_ema = ema_5[i - 1]
            cur_ema = ema_5[i]
            if direction == "BULLISH":
                crossed = prev_close <= prev_ema and cur_close > cur_ema
            else:
                crossed = prev_close >= prev_ema and cur_close < cur_ema
            if crossed:
                # Add at the bar-close time
                add_t = bars_5min[i]["ts"] + 300  # 5-min bar end
                add_hhmm = datetime.fromtimestamp(add_t).strftime("%H:%M")
                add_sub = df[df["hhmm"] >= add_hhmm]
                if not add_sub.empty:
                    add_ask = float(add_sub.iloc[0]["ask"])
                    if add_ask > 0:
                        # Weighted-avg cost basis: 1.0 unit at entry_ask + 0.5 at add_ask
                        cost_basis = (cost_basis * 1.0 + add_ask * EMA_ADD_SIZE) / (1.0 + EMA_ADD_SIZE)
                        units_held += EMA_ADD_SIZE
                        pos_remaining = units_held  # tracks total position relative to base 1.0
                        out["ema_add_hit"] = True
                        out["ema_add_t"] = add_hhmm
                        out["ema_add_ask"] = add_ask
                        add_done = True
                break  # only one add-leg

    # Walk forward minute-by-minute to manage exits
    # Use option-quote frame; iterate post-entry rows
    held_after = df[df["hhmm"] >= entry_hhmm].copy().reset_index(drop=True)
    if held_after.empty:
        return out

    # Track which TPs we've hit
    tp1_done = tp2_done = False

    for _, row in held_after.iterrows():
        hhmm = row["hhmm"]
        bid = float(row["bid"])
        mid = float(row["mid"])

        # Update peak (used for trail)
        if mid > peak_mid:
            peak_mid = mid

        # Stop loss — check on bid
        if not tp1_done:
            stop_level = cost_basis * (1 + stop_pct)
            if bid <= stop_level and bid > 0:
                # Exit ALL at bid
                exit_pnl = (bid - cost_basis) * pos_remaining
                realized += exit_pnl
                pos_remaining = 0
                out["stopped_out"] = True
                out["stop_t"] = hhmm
                out["exit_kind"] = "STOP"
                out["exit_t"] = hhmm
                out["exit_price"] = bid
                break

        # TP1
        if not tp1_done and mid >= cost_basis * TP1_MULT:
            # Sell 50% of original units (= 0.5 of base 1.0)
            sell_units = min(TP1_FRAC, pos_remaining)
            tp1_pnl = (mid - cost_basis) * sell_units
            realized += tp1_pnl
            pos_remaining -= sell_units
            tp1_done = True
            out["tp1_hit"] = True
            out["tp1_t"] = hhmm
            out["tp1_price"] = mid
            # Move stop to breakeven on remainder (cost basis); set tighter trail
            continue

        # TP2
        if tp1_done and not tp2_done and mid >= cost_basis * TP2_MULT:
            sell_units = min(TP2_FRAC, pos_remaining)
            tp2_pnl = (mid - cost_basis) * sell_units
            realized += tp2_pnl
            pos_remaining -= sell_units
            tp2_done = True
            out["tp2_hit"] = True
            out["tp2_t"] = hhmm
            out["tp2_price"] = mid
            continue

        # Post-TP1 management — breakeven stop + trail
        if tp1_done and pos_remaining > 0:
            # Breakeven stop on cost basis
            be_stop = cost_basis
            # Trail = entry_ask (original entry premium) from peak, or 50% of peak
            trail_dollar_stop = peak_mid - entry_ask
            trail_50pct_stop = peak_mid * 0.5
            trail_stop = max(be_stop, trail_dollar_stop, trail_50pct_stop)
            if bid <= trail_stop and bid > 0:
                exit_pnl = (bid - cost_basis) * pos_remaining
                realized += exit_pnl
                out["exit_kind"] = "TRAIL" if trail_stop > be_stop else "BREAKEVEN"
                out["exit_t"] = hhmm
                out["exit_price"] = bid
                pos_remaining = 0
                break

        # EOD force close
        if hhmm >= EOD_HHMM and pos_remaining > 0:
            exit_pnl = (bid - cost_basis) * pos_remaining
            realized += exit_pnl
            out["exit_kind"] = "EOD"
            out["exit_t"] = hhmm
            out["exit_price"] = bid
            pos_remaining = 0
            break

    # If still holding at end of frame, force-close at last available bid
    if pos_remaining > 0 and not held_after.empty:
        last = held_after.iloc[-1]
        bid = float(last["bid"])
        exit_pnl = (bid - cost_basis) * pos_remaining
        realized += exit_pnl
        out["exit_kind"] = out["exit_kind"] or "FRAME_END"
        out["exit_t"] = last["hhmm"]
        out["exit_price"] = bid

    # MFE on mid
    out["mfe_pct"] = (peak_mid / cost_basis - 1) * 100 if cost_basis > 0 else None

    # Realized % of cost basis (per unit). Total contracts purchased = units_held.
    # realized is in option-$ per unit summed across exits — divide by cost_basis * 1
    # to get %.
    # Actually: realized was computed as (price - cost) × fraction — so it already
    # represents the dollar P&L per ORIGINAL unit (sum of fractional pieces × their
    # individual P&L per piece). Divide by entry_ask to get % of original cost.
    # But if EMA add fired, we paid more than entry_ask total. Use cost_basis × units_held.
    total_invested = cost_basis * units_held
    if total_invested > 0:
        # realized is sum of (exit_price - cost_basis) × fraction. For % of invested:
        # We want realized / total_invested expressed as %.
        # Each fraction f sold at price P contributed (P - cost_basis) * f.
        # If we held 1.5 units (entry 1.0 + add 0.5), total_invested = cost_basis * 1.5.
        # The realized variable is dollars per "original unit" — multiply by units_held
        # to get total realized dollars. Then / total_invested.
        total_realized_dollars = realized * units_held
        out["realized_pct"] = (total_realized_dollars / total_invested) * 100

    return out


# ── Day driver ───────────────────────────────────────────────────


def find_qualified_entry(bars_5min: list[dict], level: float,
                         direction: str, ema_8: list[float] | None = None,
                         ema_21: list[float] | None = None,
                         tol_pct: float = TOUCH_TOLERANCE_PCT,
                         require_confirm: bool = False,
                         require_trend: bool = False,
                         ) -> tuple[int, float, dict] | None:
    """Find the first qualified entry.
    direction='LOW' = PML test (CALL); direction='HIGH' = PMH test (PUT).

    Touch: bar's low (or high) within tol_pct of level.
    Confirm (if require_confirm): the NEXT bar must close back through level
        (above for CALL / below for PUT) — entry happens at the next bar's close.
    Trend (if require_trend): EMA8 vs EMA21 must align with direction
        (8>21 for CALL, 8<21 for PUT) at the entry bar.
    """
    for i, b in enumerate(bars_5min):
        # Step 1: touch test
        if direction == "LOW":
            touched = b["low"] <= level * (1 + tol_pct)
        else:
            touched = b["high"] >= level * (1 - tol_pct)
        if not touched:
            continue

        # Step 2: confirmation (if required)
        if require_confirm:
            if i + 1 >= len(bars_5min):
                return None  # touched on last bar, can't confirm
            next_b = bars_5min[i + 1]
            if direction == "LOW":
                # Need next close ABOVE level (and ideally above touch bar's high)
                confirmed = next_b["close"] > level and next_b["close"] > b["close"]
            else:
                confirmed = next_b["close"] < level and next_b["close"] < b["close"]
            if not confirmed:
                continue
            entry_bar_idx = i + 1
        else:
            entry_bar_idx = i
        entry_bar = bars_5min[entry_bar_idx]

        # Step 3: trend filter
        trend_ok = True
        trend_info: dict = {}
        if require_trend and ema_8 is not None and ema_21 is not None:
            if entry_bar_idx >= len(ema_8):
                trend_ok = False
            else:
                e8 = ema_8[entry_bar_idx]
                e21 = ema_21[entry_bar_idx]
                if direction == "LOW":
                    trend_ok = e8 > e21  # uptrend for calls
                else:
                    trend_ok = e8 < e21  # downtrend for puts
                trend_info = {"ema8": e8, "ema21": e21, "trend_ok": trend_ok}
        if not trend_ok:
            continue

        # Use entry-bar close as fill price (5-min bar)
        # Add the bar end time as entry_ts (we'd be filling at the close)
        entry_ts = entry_bar["ts"] + 300  # end of 5-min bar
        return entry_ts, entry_bar["close"], {
            "touch_bar_hhmm": b["hhmm"],
            "touch_bar_low_or_high": b["low"] if direction == "LOW" else b["high"],
            "confirmed": require_confirm,
            **trend_info,
        }
    return None


def run_day(ticker: str, day: datetime,
            use_ema_add: bool,
            stop_pct: float,
            require_confirm: bool,
            require_trend: bool) -> list[dict]:
    """Find PML/PMH, simulate CALL and PUT trades for the day."""
    fires = []
    pre_bars = fetch_premarket_bars(ticker, day)
    if not pre_bars or len(pre_bars) < 30:
        return fires
    pml = min(b["low"] for b in pre_bars)
    pmh = max(b["high"] for b in pre_bars)

    cash_1min = fetch_cash_bars(ticker, day)
    if not cash_1min:
        return fires
    bars_5min = aggregate_5min(cash_1min)
    if not bars_5min:
        return fires

    # Pre-compute EMAs for trend filter
    ema_8 = compute_ema(bars_5min, EMA_PERIOD)
    ema_21 = compute_ema(bars_5min, EMA_LONG_PERIOD)

    # CALL — PML touch
    pml_entry = find_qualified_entry(bars_5min, pml, "LOW", ema_8, ema_21,
                                     require_confirm=require_confirm,
                                     require_trend=require_trend)
    if pml_entry is not None:
        ts, spot, meta = pml_entry
        trade = simulate_trade(ts, spot, "BULLISH", ticker, day,
                               bars_5min, cash_1min, use_ema_add,
                               stop_pct=stop_pct)
        trade["pml"] = pml
        trade["pmh"] = pmh
        trade.update({"trigger_meta": meta})
        fires.append(trade)

    # PUT — PMH touch
    pmh_entry = find_qualified_entry(bars_5min, pmh, "HIGH", ema_8, ema_21,
                                     require_confirm=require_confirm,
                                     require_trend=require_trend)
    if pmh_entry is not None:
        ts, spot, meta = pmh_entry
        trade = simulate_trade(ts, spot, "BEARISH", ticker, day,
                               bars_5min, cash_1min, use_ema_add,
                               stop_pct=stop_pct)
        trade["pml"] = pml
        trade["pmh"] = pmh
        trade.update({"trigger_meta": meta})
        fires.append(trade)

    return fires


# ── Report ───────────────────────────────────────────────────────


def render_report(fires: pd.DataFrame, days_scanned: int,
                  tickers: list[str], use_ema_add: bool) -> str:
    L: list[str] = []
    L.append("# PML/PMH Touch Strategy — Backtest")
    L.append("")
    L.append(f"- Scan window: **{days_scanned} trading days**")
    L.append(f"- Tickers: {', '.join(tickers)}")
    L.append(f"- 8EMA add-leg: **{'enabled' if use_ema_add else 'disabled'}**")
    L.append(f"- Total trades: **{len(fires)}**")
    L.append(f"- TP1 hit: {(fires['tp1_hit']==True).sum()}  "
             f"TP2 hit: {(fires['tp2_hit']==True).sum()}  "
             f"Stopped out: {(fires['stopped_out']==True).sum()}")
    L.append("")
    L.append("**Strategy spec**: enter ATM 0DTE CALL on first 5-min bar within ±0.05% "
             "of pre-market low (PML), or ATM 0DTE PUT on first 5-min bar within "
             "±0.05% of pre-market high (PMH). Stop -50% on cost basis. TP1 sells 50% "
             "at +100%; TP2 sells 25% at +200%; remainder rides trailing stop or EOD.")
    L.append("")

    if fires.empty:
        return "\n".join(L)

    # Aggregate stats
    L.append("## Headline P&L")
    L.append("")
    valid = fires[fires["realized_pct"].notna()]
    if not valid.empty:
        avg = valid["realized_pct"].mean()
        median = valid["realized_pct"].median()
        wins = (valid["realized_pct"] > 0).sum()
        losses = (valid["realized_pct"] <= 0).sum()
        hit_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        L.append(f"- Trades evaluated: {len(valid)}")
        L.append(f"- Hit rate: **{hit_rate:.1f}%** ({wins}W / {losses}L)")
        L.append(f"- Avg realized: **{avg:+.1f}%**")
        L.append(f"- Median realized: **{median:+.1f}%**")
        L.append(f"- Best trade: {valid['realized_pct'].max():+.1f}%")
        L.append(f"- Worst trade: {valid['realized_pct'].min():+.1f}%")
        mfe_avg = valid["mfe_pct"].mean()
        L.append(f"- Avg MFE: {mfe_avg:+.1f}%  (peak unrealized — "
                 f"compare to avg realized to gauge exit discipline)")
    L.append("")

    # By direction
    L.append("## By direction")
    L.append("")
    L.append("| Dir | n | Hit% | Avg | Median | TP1% | TP2% | Stop% |")
    L.append("|---|---|---|---|---|---|---|---|")
    for d, sub in fires.groupby("direction"):
        v = sub[sub["realized_pct"].notna()]
        if v.empty:
            continue
        wins = (v["realized_pct"] > 0).sum()
        hit = wins / len(v) * 100
        tp1 = sub["tp1_hit"].sum() / len(sub) * 100
        tp2 = sub["tp2_hit"].sum() / len(sub) * 100
        stop = sub["stopped_out"].sum() / len(sub) * 100
        L.append(f"| {d} | {len(sub)} | {hit:.0f}% | {v['realized_pct'].mean():+.1f}% | "
                 f"{v['realized_pct'].median():+.1f}% | {tp1:.0f}% | {tp2:.0f}% | {stop:.0f}% |")
    L.append("")

    # By ticker
    L.append("## By ticker")
    L.append("")
    L.append("| Ticker | n | Hit% | Avg | TP1% | TP2% | Stop% |")
    L.append("|---|---|---|---|---|---|---|")
    for t, sub in fires.groupby("ticker"):
        v = sub[sub["realized_pct"].notna()]
        if v.empty:
            continue
        wins = (v["realized_pct"] > 0).sum()
        hit = wins / len(v) * 100
        tp1 = sub["tp1_hit"].sum() / len(sub) * 100
        tp2 = sub["tp2_hit"].sum() / len(sub) * 100
        stop = sub["stopped_out"].sum() / len(sub) * 100
        L.append(f"| {t} | {len(sub)} | {hit:.0f}% | {v['realized_pct'].mean():+.1f}% | "
                 f"{tp1:.0f}% | {tp2:.0f}% | {stop:.0f}% |")
    L.append("")

    # All trades
    L.append("## All trades (chronological)")
    L.append("")
    L.append("| Day | Tkr | Dir | Entry | Spot | Strike | Entry$ | TP1 | TP2 | Exit | "
             "**Realized** | MFE |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in fires.sort_values(["day", "entry_ts"]).iterrows():
        def fmt_pct(x):
            return f"{x:+.0f}%" if pd.notna(x) else "—"
        d = r.get("direction", "")
        d_emoji = "🟢" if d == "BULLISH" else "🔴"
        strike = f"{int(r['strike'])}{r['right']}"
        entry_ask = f"${r['entry_ask']:.2f}" if pd.notna(r.get("entry_ask")) else "—"
        tp1 = f"{r['tp1_t']}" if r["tp1_hit"] else "—"
        tp2 = f"{r['tp2_t']}" if r["tp2_hit"] else "—"
        exit_kind = r.get("exit_kind") or "—"
        L.append(f"| {r['day']} | {r['ticker']} | {d_emoji} | {r['entry_hhmm']} | "
                 f"${r['entry_spot']:.2f} | {strike} | {entry_ask} | "
                 f"{tp1} | {tp2} | {exit_kind} | "
                 f"**{fmt_pct(r.get('realized_pct'))}** | "
                 f"{fmt_pct(r.get('mfe_pct'))} |")
    L.append("")

    return "\n".join(L)


def trading_days(end_date: datetime, days_back: int) -> list[datetime]:
    out = []
    d = end_date - timedelta(days=days_back)
    while d <= end_date:
        if d.weekday() < 5:
            out.append(d.replace(hour=0, minute=0, second=0, microsecond=0))
        d += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ")
    ap.add_argument("--days", type=int, default=22)
    ap.add_argument("--use-ema-add", action="store_true",
                    help="Enable 8EMA cross add-leg (50%% size add within 60 min)")
    ap.add_argument("--stop-pct", type=float, default=-0.50,
                    help="Stop loss as fraction of cost basis (default -0.50)")
    ap.add_argument("--confirm", action="store_true",
                    help="Require next-bar close-back confirmation through PML/PMH")
    ap.add_argument("--trend-filter", action="store_true",
                    help="Require EMA8/EMA21 trend alignment (8>21 for calls)")
    ap.add_argument("--label", default="",
                    help="Tag this run for the report filename (e.g. 'v2_filtered')")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    end_date = datetime(2026, 4, 28)
    days = trading_days(end_date, args.days)
    print(f"Tickers: {tickers}")
    print(f"Days: {len(days)} trading days back to {days[0]:%Y-%m-%d}")
    print(f"EMA add-leg: {args.use_ema_add}")
    print(f"Stop: {args.stop_pct*100:+.0f}%   Confirm: {args.confirm}   "
          f"Trend filter: {args.trend_filter}")
    print()

    all_fires = []
    for d in days:
        for t in tickers:
            fires = run_day(t, d, args.use_ema_add,
                           stop_pct=args.stop_pct,
                           require_confirm=args.confirm,
                           require_trend=args.trend_filter)
            for f in fires:
                if f.get("realized_pct") is not None:
                    pnl = f["realized_pct"]
                    arrow = "🟢" if f["direction"] == "BULLISH" else "🔴"
                    tags = []
                    if f["tp1_hit"]: tags.append("TP1")
                    if f["tp2_hit"]: tags.append("TP2")
                    if f["stopped_out"]: tags.append("STOP")
                    if f["ema_add_hit"]: tags.append("EMA+")
                    tag_str = "/".join(tags) if tags else "-"
                    print(f"  {d:%Y-%m-%d} {t} {arrow} {f['direction']} "
                          f"@ {f['entry_hhmm']}  [{tag_str}]  realized={pnl:+.0f}%")
                else:
                    print(f"  {d:%Y-%m-%d} {t} {f['direction']} "
                          f"@ {f.get('entry_hhmm','?')}  ERROR: {f.get('error','?')}")
                all_fires.append(f)

    if not all_fires:
        print("\nNo trades found.")
        return 0

    df = pd.DataFrame(all_fires)
    suffix = f"_{args.label}" if args.label else ""
    out_csv = OUT_CSV.parent / f"pml_strategy_fires{suffix}.csv"
    out_report = OUT_REPORT.parent / f"pml_strategy_backtest{suffix}.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\nCSV → {out_csv} ({len(df)} rows)")

    md = render_report(df, len(days), tickers, args.use_ema_add)
    out_report.write_text(md, encoding="utf-8")
    print(f"Report → {out_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
