"""Intrinsic-capture analysis for historical 0DTE telegram alerts.

The core question: given the strikes the system actually picks, how
often does the strike print intrinsic value during the trade window,
and what's the maximum capturable P&L before theta destroys it?

We use Databento SPY+QQQ tick data (the 21 alerts that fall within our
2025-10-30 → 2026-05-01 cache window). For each alert we compute the
intrinsic path minute-by-minute, find peak intrinsic, time-to-peak,
how long it stayed profitable, and EOD intrinsic.

Key metrics per alert:
  - reached_itm        : did strike ever go in-the-money?
  - peak_intrinsic     : max intrinsic over the trade window
  - peak_pnl_pct       : (peak_intrinsic - entry_paid) / entry_paid * 100
  - peak_hhmm          : when did the peak happen?
  - mins_to_peak       : minutes from fire time to peak
  - mins_above_entry   : how long was intrinsic > entry_paid?
  - mins_2x_entry      : how long was intrinsic >= 2x entry_paid?
  - eod_intrinsic      : intrinsic at 15:59 ET
  - tp50_outcome       : would TP-at-+50% have caught a profit?
  - tp100_outcome      : would TP-at-+100% have caught a profit?

Then aggregate across all 21 alerts and report capture rates by
exit-policy variant.

Run:
  python scripts/intrinsic_capture_analysis.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import load_window  # noqa: E402

ALERT_DB = "zero_dte_alerts.db"
DB_START = int(datetime(2025, 10, 30).timestamp())
DB_END = int(datetime(2026, 5, 1, 23, 59).timestamp())

# Exit-policy thresholds (% gain on entry premium)
TP_THRESHOLDS = [25, 50, 75, 100, 150, 200]


def fetch_alerts() -> list[dict]:
    """All SPY/QQQ alerts in Databento cache window."""
    conn = sqlite3.connect(ALERT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """SELECT alert_id, ticker, fired_at, direction, grade,
                  spot, strike, right, expiration, est_entry_price,
                  target_mid, target_r, time_stop_minutes, strike_quality
           FROM zero_dte_alerts
           WHERE fired_at BETWEEN ? AND ? AND ticker IN ('SPY', 'QQQ')
           ORDER BY fired_at""",
        (DB_START, DB_END),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def session_minute_bars(ticker: str, day: str) -> pd.DataFrame:
    """Aggregate Databento trades to per-minute OHLC bars (RTH only)."""
    df = load_window(ticker, day, start_hhmm="09:30", end_hhmm="16:00",
                     actions=["T"])
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["ts_event"], utc=True) \
              .dt.tz_convert("America/New_York")
    df["minute"] = df["t"].dt.floor("min")
    g = df.groupby("minute").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
    ).reset_index()
    g["hhmm"] = g["minute"].dt.strftime("%H:%M")
    return g


def analyze_alert(alert: dict) -> dict:
    """Compute intrinsic path + all metrics for one alert."""
    fire_dt = datetime.fromtimestamp(alert["fired_at"])
    fire_hhmm = fire_dt.strftime("%H:%M")
    day = fire_dt.strftime("%Y-%m-%d")
    ticker = alert["ticker"]
    strike = float(alert["strike"])
    entry = float(alert["est_entry_price"])
    right = alert["right"].upper()

    bars = session_minute_bars(ticker, day)
    if bars.empty:
        return {**alert, "fire_hhmm": fire_hhmm, "day": day,
                "error": "no Databento bars"}

    # Trade window: from fire minute to 15:59
    sub = bars[bars["hhmm"] >= fire_hhmm].copy()
    if sub.empty:
        return {**alert, "fire_hhmm": fire_hhmm, "day": day,
                "error": "no bars in trade window"}

    # Compute intrinsic path. For calls: max(0, high - strike) is the
    # high-water-mark intrinsic the bar reached. For puts: max(0, strike - low).
    # We use HIGH (calls) / LOW (puts) per bar to capture peak intrinsic
    # an attentive trader could have hit during the minute.
    if right in ("C", "CALL"):
        sub["intrinsic_max"] = (sub["high"] - strike).clip(lower=0)
        sub["intrinsic_close"] = (sub["close"] - strike).clip(lower=0)
    else:
        sub["intrinsic_max"] = (strike - sub["low"]).clip(lower=0)
        sub["intrinsic_close"] = (strike - sub["close"]).clip(lower=0)

    # Peak intrinsic across window (using the wick-touched max)
    peak_intrinsic = float(sub["intrinsic_max"].max())
    peak_idx = sub["intrinsic_max"].idxmax()
    peak_row = sub.loc[peak_idx]
    peak_hhmm = peak_row["hhmm"]
    mins_to_peak = (peak_row["minute"] - sub.iloc[0]["minute"]).total_seconds() / 60

    # EOD intrinsic (close of last bar in session, NOT the wick)
    eod_intrinsic = float(sub.iloc[-1]["intrinsic_close"])

    # Reached ITM at any point?
    reached_itm = peak_intrinsic > 0

    # Time spent above various intrinsic thresholds
    target_above_entry = entry
    target_2x = entry * 2
    target_3x = entry * 3
    mins_above_entry = int((sub["intrinsic_max"] > target_above_entry).sum())
    mins_2x = int((sub["intrinsic_max"] >= target_2x).sum())
    mins_3x = int((sub["intrinsic_max"] >= target_3x).sum())

    # P&L percentages
    peak_pnl_pct = (peak_intrinsic - entry) / entry * 100 if entry > 0 else None
    eod_pnl_pct = (eod_intrinsic - entry) / entry * 100 if entry > 0 else None

    # TP exit simulation: would price have HIT each TP threshold?
    # If yes, exit at that minute at the threshold value (assumes a
    # limit order at the TP fills when intrinsic touches it; for 0DTE
    # this is approximately when the option mid hits target).
    tp_outcomes = {}
    for tp in TP_THRESHOLDS:
        target_intrinsic = entry * (1 + tp / 100)
        hit = sub[sub["intrinsic_max"] >= target_intrinsic]
        if not hit.empty:
            tp_outcomes[f"tp{tp}_hit"] = True
            tp_outcomes[f"tp{tp}_hhmm"] = hit.iloc[0]["hhmm"]
            tp_outcomes[f"tp{tp}_mins"] = int(
                (hit.iloc[0]["minute"] - sub.iloc[0]["minute"]).total_seconds() / 60
            )
            tp_outcomes[f"tp{tp}_pnl"] = tp  # captured exactly tp%
        else:
            tp_outcomes[f"tp{tp}_hit"] = False
            tp_outcomes[f"tp{tp}_hhmm"] = None
            tp_outcomes[f"tp{tp}_mins"] = None
            # Without TP hit, P&L = EOD intrinsic
            tp_outcomes[f"tp{tp}_pnl"] = eod_pnl_pct

    return {
        "alert_id": alert["alert_id"],
        "day": day, "fire_hhmm": fire_hhmm, "ticker": ticker,
        "strike": strike, "right": right[0],
        "fire_spot": float(alert["spot"]),
        "fire_dist_pct": (strike - float(alert["spot"])) / float(alert["spot"]) * 100,
        "entry": entry,
        "reached_itm": reached_itm,
        "peak_intrinsic": peak_intrinsic,
        "peak_hhmm": peak_hhmm,
        "mins_to_peak": int(mins_to_peak),
        "peak_pnl_pct": peak_pnl_pct,
        "eod_intrinsic": eod_intrinsic,
        "eod_pnl_pct": eod_pnl_pct,
        "mins_above_entry": mins_above_entry,
        "mins_2x_entry": mins_2x,
        "mins_3x_entry": mins_3x,
        **tp_outcomes,
    }


def report(results: list[dict]) -> str:
    df = pd.DataFrame([r for r in results if "error" not in r])
    if df.empty:
        return "No usable results."

    lines = []
    lines.append("# 0DTE Engine Alerts — Intrinsic Capture Analysis")
    lines.append("")
    lines.append(f"**Sample**: {len(df)} SPY/QQQ alerts, "
                 f"{df['day'].nunique()} trading days "
                 f"({df['day'].min()} to {df['day'].max()}).")
    lines.append("")
    lines.append("All alerts are bullish B+ grade (the only kind the system "
                 "fired during this window). Analysis uses Databento minute-bar "
                 "intrinsic value as proxy for what an attentive trader could "
                 "have captured. **Does NOT model option theta or spread cost** "
                 "— peak intrinsic is the upper bound of capturable P&L; actual "
                 "captured P&L would be lower by the option's time premium "
                 "decay between fire-time and exit-time. For 0DTE held >30 min, "
                 "expect time decay of ~$0.05-0.20 per minute on near-ATM strikes.")
    lines.append("")

    # ── Section 1: did the strike ever go ITM? ─────────────────────
    lines.append("## 1. Did the strike ever reach intrinsic value?")
    lines.append("")
    n_itm = df["reached_itm"].sum()
    lines.append(f"**{n_itm}/{len(df)} alerts ({n_itm/len(df)*100:.0f}%) "
                 f"saw their strike go in-the-money at some point in the "
                 f"trade window.**")
    lines.append("")
    lines.append(f"Of the {n_itm} that reached ITM:")
    if n_itm > 0:
        itm = df[df["reached_itm"]]
        lines.append(f"- Mean peak intrinsic: ${itm['peak_intrinsic'].mean():.2f} "
                     f"(median ${itm['peak_intrinsic'].median():.2f})")
        lines.append(f"- Mean entry paid: ${itm['entry'].mean():.2f}")
        lines.append(f"- Mean peak P&L: {itm['peak_pnl_pct'].mean():+.0f}% "
                     f"(median {itm['peak_pnl_pct'].median():+.0f}%)")
        lines.append(f"- Mean time-to-peak: {itm['mins_to_peak'].mean():.0f} min "
                     f"(median {int(itm['mins_to_peak'].median())} min)")
        lines.append(f"- Strike distance at fire (% from spot): "
                     f"mean {itm['fire_dist_pct'].mean():+.2f}%, "
                     f"median {itm['fire_dist_pct'].median():+.2f}%")
    lines.append("")

    # ── Section 2: peak P&L distribution ───────────────────────────
    lines.append("## 2. Peak P&L distribution")
    lines.append("")
    lines.append("Bucket | Count | %")
    lines.append("---|---|---")
    buckets = [
        ("Peak P&L >= +200% (huge win)", df["peak_pnl_pct"] >= 200),
        ("Peak P&L +100% to +200% (big win)",
         (df["peak_pnl_pct"] >= 100) & (df["peak_pnl_pct"] < 200)),
        ("Peak P&L +50% to +100% (clean win)",
         (df["peak_pnl_pct"] >= 50) & (df["peak_pnl_pct"] < 100)),
        ("Peak P&L 0% to +50% (marginal)",
         (df["peak_pnl_pct"] >= 0) & (df["peak_pnl_pct"] < 50)),
        ("Peak P&L -50% to 0% (loss-with-bounce)",
         (df["peak_pnl_pct"] >= -50) & (df["peak_pnl_pct"] < 0)),
        ("Peak P&L < -50% (full wipeout, never recovered)",
         df["peak_pnl_pct"] < -50),
    ]
    for label, mask in buckets:
        n = mask.sum()
        pct = n / len(df) * 100
        lines.append(f"{label} | {n} | {pct:.0f}%")
    lines.append("")

    # ── Section 3: time-window endurance ───────────────────────────
    lines.append("## 3. How long did the alert stay profitable?")
    lines.append("")
    lines.append("This is the theta-vs-capture tradeoff. The longer the alert "
                 "stayed above an intrinsic threshold, the more 'forgiving' "
                 "the exit window — you don't need to time the exact peak.")
    lines.append("")
    lines.append("Threshold | Mean min above | Median min above | n alerts that ever exceeded")
    lines.append("---|---|---|---")
    for col, label in [("mins_above_entry", "intrinsic > entry"),
                       ("mins_2x_entry", "intrinsic >= 2× entry"),
                       ("mins_3x_entry", "intrinsic >= 3× entry")]:
        sub = df[df[col] > 0]
        lines.append(f"{label} | "
                     f"{sub[col].mean():.0f} | "
                     f"{int(sub[col].median()) if not sub.empty else 0} | "
                     f"{len(sub)}/{len(df)}")
    lines.append("")

    # ── Section 4: TP-exit simulation ──────────────────────────────
    lines.append("## 4. TP-exit policy simulation")
    lines.append("")
    lines.append("'TP-at-X%' = if intrinsic ever touched (entry × (1+X/100)) "
                 "during the window, exit at that level (capturing X% gain). "
                 "Otherwise exit at EOD intrinsic.")
    lines.append("")
    lines.append("Policy | Hit rate | Mean P&L (alerts) | Mean P&L (hits only) | Median time-to-hit")
    lines.append("---|---|---|---|---")
    # Baseline: hold to EOD
    eod_mean = df["eod_pnl_pct"].mean()
    lines.append(f"Hold to EOD (current default) | n/a | {eod_mean:+.0f}% | n/a | n/a")
    for tp in TP_THRESHOLDS:
        col_hit = f"tp{tp}_hit"
        col_pnl = f"tp{tp}_pnl"
        col_mins = f"tp{tp}_mins"
        n_hit = df[col_hit].sum()
        hit_rate = n_hit / len(df) * 100
        mean_pnl = df[col_pnl].mean()
        hits_pnl = df[df[col_hit]][col_pnl].mean() if n_hit > 0 else None
        median_mins = int(df[df[col_hit]][col_mins].median()) if n_hit > 0 else None
        lines.append(f"TP at +{tp}% | "
                     f"{n_hit}/{len(df)} ({hit_rate:.0f}%) | "
                     f"{mean_pnl:+.0f}% | "
                     f"{hits_pnl:+.0f}% | "
                     f"{median_mins} min" if median_mins is not None
                     else f"TP at +{tp}% | {n_hit}/{len(df)} ({hit_rate:.0f}%) | "
                          f"{mean_pnl:+.0f}% | n/a | n/a")
    lines.append("")

    # ── Section 5: per-alert table ─────────────────────────────────
    lines.append("## 5. Per-alert detail")
    lines.append("")
    cols = ["day", "fire_hhmm", "ticker", "strike", "fire_spot",
            "fire_dist_pct", "entry", "peak_intrinsic", "peak_pnl_pct",
            "peak_hhmm", "mins_to_peak", "mins_above_entry", "mins_2x_entry",
            "eod_pnl_pct"]
    short = df[cols].copy()
    short.columns = ["day", "fire", "tkr", "K", "spot", "dist%",
                     "entry", "peak_int", "peak%", "peak_t",
                     "min2pk", "min>entry", "min>=2x", "EOD%"]
    lines.append(short.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    lines.append("")

    # ── Section 6: time-of-day pattern ─────────────────────────────
    lines.append("## 6. Time-of-day pattern")
    lines.append("")
    df_tod = df.copy()
    df_tod["hour"] = df_tod["fire_hhmm"].str[:2].astype(int)
    df_tod["tod"] = pd.cut(df_tod["hour"],
                           bins=[0, 10, 12, 14, 24],
                           labels=["09:30-09:59", "10:00-11:59",
                                   "12:00-13:59", "14:00-16:00"])
    lines.append("TOD bucket | n | reached ITM | mean peak P&L | mean EOD P&L")
    lines.append("---|---|---|---|---")
    for tod in df_tod["tod"].cat.categories:
        sub = df_tod[df_tod["tod"] == tod]
        if sub.empty:
            continue
        n_itm = sub["reached_itm"].sum()
        lines.append(f"{tod} | {len(sub)} | {n_itm}/{len(sub)} | "
                     f"{sub['peak_pnl_pct'].mean():+.0f}% | "
                     f"{sub['eod_pnl_pct'].mean():+.0f}%")
    lines.append("")

    # ── Section 7: distance-from-strike pattern ────────────────────
    lines.append("## 7. Strike-distance pattern (% OTM at fire)")
    lines.append("")
    df_d = df.copy()
    df_d["dist_bucket"] = pd.cut(df_d["fire_dist_pct"],
                                 bins=[-1, 0, 0.1, 0.2, 0.5, 99],
                                 labels=["ITM", "0-0.1% OTM", "0.1-0.2% OTM",
                                         "0.2-0.5% OTM", ">0.5% OTM"])
    lines.append("Strike distance | n | reached ITM | mean peak P&L | mean EOD P&L")
    lines.append("---|---|---|---|---")
    for db in df_d["dist_bucket"].cat.categories:
        sub = df_d[df_d["dist_bucket"] == db]
        if sub.empty:
            continue
        n_itm = sub["reached_itm"].sum()
        lines.append(f"{db} | {len(sub)} | {n_itm}/{len(sub)} | "
                     f"{sub['peak_pnl_pct'].mean():+.0f}% | "
                     f"{sub['eod_pnl_pct'].mean():+.0f}%")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    alerts = fetch_alerts()
    print(f"Analyzing {len(alerts)} historical alerts...", flush=True)
    results = []
    for a in alerts:
        try:
            r = analyze_alert(a)
            results.append(r)
            err = r.get("error")
            if err:
                print(f"  {a['alert_id']}: skip ({err})")
            else:
                marker = "ITM" if r.get("reached_itm") else "OTM"
                print(f"  {a['alert_id'][:30]:<30} {r['day']} {r['fire_hhmm']} "
                      f"{r['ticker']} {r['strike']:.0f}{r['right']} "
                      f"entry=${r['entry']:.2f}  peak={r['peak_intrinsic']:.2f} "
                      f"({r['peak_pnl_pct']:+.0f}%)  EOD%={r['eod_pnl_pct']:+.0f}%  [{marker}]",
                      flush=True)
        except Exception as e:
            print(f"  {a['alert_id']}: ERROR {type(e).__name__}: {e}")

    print()
    out = report(results)
    out_path = ROOT / "docs" / "research" / "INTRINSIC_CAPTURE_ANALYSIS.md"
    out_path.write_text(out, encoding="utf-8")
    print(f"\nWrote {out_path}")

    # Also save the raw per-alert table
    df = pd.DataFrame([r for r in results if "error" not in r])
    csv_path = ROOT / "docs" / "research" / "intrinsic_capture_per_alert.csv"
    df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
