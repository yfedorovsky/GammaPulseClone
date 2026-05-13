"""Intraday spike detector — flags abnormal flow concentration windows.

P0.6 (2026-05-12). Fidget surfaces "1239x spike at 3:13 PM ET" / "14x spike
midday" / "18x surge" labels — relative-baseline alerts that catch the
INSTANT a single 5-min window's flow notional dwarfs the day's average.
This is how the operator notices "something just happened on TGT" without
staring at the tape.

Detector logic:
  1. Bucket flow_alerts rows into 5-min windows per ticker.
  2. For each ticker, compute the rolling baseline = average per-bucket
     notional from market open to the most-recent COMPLETED bucket.
  3. Compare the most-recent COMPLETED bucket to baseline.
  4. Fire when: bucket_notional >= 10x baseline AND >= $5M absolute
     (avoids 10x-of-$50K = $500K false positives).

Why 5-min buckets:
  - Smaller than 1-min = each bucket has enough samples to be stable
  - Larger than 1-min = catches the actual institutional execution
    burst (3-7 min typical for a multi-venue sweep)

Dedup:
  - Once per (ticker, bucket_id) — the bucket ID is the floor-divided
    UTC epoch, so each 5-min slot can fire at most once globally.
  - In-memory set; resets on worker restart (acceptable — spikes are
    intraday-only signal, not preserved across days).

Database read-only — does not write new rows. Works off flow_alerts
already populated by the chain scanner cycle.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import time
from contextlib import contextmanager

from .config import get_settings


BUCKET_SIZE_SECONDS = 300       # 5 min
MIN_BUCKETS_FOR_BASELINE = 3    # need 3+ completed buckets before fire
SPIKE_MULTIPLIER = 10.0         # >=10x baseline
SPIKE_MIN_ABS_NOTIONAL = 5_000_000  # $5M absolute floor
TICKER_BLOCKLIST = {"SPX", "SPXW", "SPY", "QQQ", "NDX", "RUT", "IWM"}
# Index products always have huge flow — spike ratio is meaningless there.
# Blocked from spike detection but still surface via flow_alerts directly.

_fired: set[tuple[str, int]] = set()  # (ticker, bucket_id)


@contextmanager
def _conn():
    db = get_settings().snapshot_db
    c = sqlite3.connect(db)
    try:
        yield c
    finally:
        c.close()


def _today_unix_bounds(now: _dt.datetime | None = None) -> tuple[int, int]:
    """Return (start_of_today_ts, current_ts) in unix epoch seconds.

    Uses the server's local clock (ET, matches rest of codebase).
    """
    now = now or _dt.datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start_of_day.timestamp()), int(now.timestamp())


def detect_spikes(now: _dt.datetime | None = None) -> list[dict]:
    """Scan flow_alerts for 5-min buckets that are >=10x today's baseline.

    Returns a list of spike dicts. Each spike represents ONE bucket that
    fired today, deduped so re-runs return only freshly-fired spikes.
    """
    now = now or _dt.datetime.now()
    # Gate: only run during RTH so we don't fire on overnight noise
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 35):
        return []  # 5 min grace after 9:30 to seed baseline
    if now.hour > 16:
        return []

    start_today, now_ts = _today_unix_bounds(now)

    # Current bucket boundary (exclusive — we only look at COMPLETED buckets)
    current_bucket = now_ts // BUCKET_SIZE_SECONDS
    last_completed_bucket = current_bucket - 1
    if last_completed_bucket < (start_today // BUCKET_SIZE_SECONDS):
        return []

    # Compute the NEW notional in each 5-min bucket per contract. The raw
    # `notional` column is cumulative day-volume × price (monotonically
    # increasing through the day), so a naive bucket sum gives the running
    # total, not the burst. We diff: per (ticker, strike, exp, type),
    # the per-bucket new-notional = MAX(notional) in that bucket minus
    # MAX(notional) in all prior buckets that day. The window-function
    # version (LAG over partition) is cleanest:
    sql = """
      WITH per_contract_per_bucket AS (
        SELECT ticker, strike, expiration, option_type,
               (ts / ?) AS bucket_id,
               MAX(notional) AS cum_notional
        FROM flow_alerts
        WHERE ts >= ? AND ts < ?
        GROUP BY ticker, strike, expiration, option_type, bucket_id
      ),
      with_lag AS (
        SELECT
          ticker, strike, expiration, option_type, bucket_id, cum_notional,
          COALESCE(
            LAG(cum_notional) OVER (
              PARTITION BY ticker, strike, expiration, option_type
              ORDER BY bucket_id
            ),
            0
          ) AS prior_cum
        FROM per_contract_per_bucket
      )
      SELECT ticker, bucket_id,
             SUM(CASE WHEN cum_notional > prior_cum
                      THEN cum_notional - prior_cum ELSE 0 END)
                 AS bucket_notional,
             COUNT(*) AS contract_count
      FROM with_lag
      GROUP BY ticker, bucket_id
    """
    end_ts = (last_completed_bucket + 1) * BUCKET_SIZE_SECONDS

    with _conn() as c:
        cur = c.execute(sql, (BUCKET_SIZE_SECONDS, start_today, end_ts))
        rows = cur.fetchall()

    # Build per-ticker bucket maps
    per_ticker: dict[str, dict[int, tuple[float, int]]] = {}
    for ticker, bucket_id, bucket_notional, contract_count in rows:
        if ticker in TICKER_BLOCKLIST:
            continue
        per_ticker.setdefault(ticker, {})[int(bucket_id)] = (
            float(bucket_notional or 0.0),
            int(contract_count or 0),
        )

    spikes: list[dict] = []
    for ticker, buckets in per_ticker.items():
        last_bucket = buckets.get(int(last_completed_bucket))
        if not last_bucket:
            continue
        # Dedup: skip if already fired this bucket
        if (ticker, int(last_completed_bucket)) in _fired:
            continue

        # Baseline = mean of all PRIOR buckets (excluding the current one).
        prior = [n for bid, (n, _) in buckets.items()
                 if bid < last_completed_bucket]
        if len(prior) < MIN_BUCKETS_FOR_BASELINE:
            continue
        baseline = sum(prior) / len(prior)
        if baseline <= 0:
            continue

        bucket_notional, contract_count = last_bucket
        if bucket_notional < SPIKE_MIN_ABS_NOTIONAL:
            continue
        ratio = bucket_notional / baseline
        if ratio < SPIKE_MULTIPLIER:
            continue

        # Format bucket time as ET HH:MM
        bucket_start_ts = last_completed_bucket * BUCKET_SIZE_SECONDS
        bucket_dt = _dt.datetime.fromtimestamp(bucket_start_ts)
        spikes.append({
            "ticker": ticker,
            "bucket_id": int(last_completed_bucket),
            "bucket_time": bucket_dt.strftime("%H:%M"),
            "bucket_notional": bucket_notional,
            "contract_count": contract_count,
            "baseline": baseline,
            "ratio": ratio,
        })
        _fired.add((ticker, int(last_completed_bucket)))

    # Sort by ratio descending so the biggest spikes hit Telegram first
    spikes.sort(key=lambda s: -s["ratio"])
    return spikes


def format_spike_alert(spike: dict) -> str:
    """Format a spike for Telegram."""
    ticker = spike["ticker"]
    bucket_time = spike["bucket_time"]
    notional = spike["bucket_notional"]
    baseline = spike["baseline"]
    ratio = spike["ratio"]
    contracts = spike["contract_count"]
    return (
        f"⚡ <b>SPIKE</b> — {ticker} @ {bucket_time} ET\n"
        f"<b>{ratio:.0f}× day baseline</b>\n"
        f"Bucket: ${notional/1_000_000:.1f}M premium, {contracts} contracts\n"
        f"Baseline: ${baseline/1_000_000:.2f}M / 5min\n"
        f"<i>Check the ticker — institutional concentration just hit</i>"
    )


def reset_dedup_state() -> None:
    """Clear in-memory dedup. Worker restart clears it automatically;
    this is for tests."""
    _fired.clear()
