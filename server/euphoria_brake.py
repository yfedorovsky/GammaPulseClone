"""Euphoria / exhaustion brake + shared exhaustion primitives (#122-B/D).

Mechanizes the pre-registered MU note: when a name is stretched far above its
mean AND inside a binary-catalyst window AND the tape has actually rolled over,
suppress (or invert) bullish breakout/bounce signals. On 6/25 the SOE engine
fired a grade-A 1240C at MU's +18% blow-off open and two 1280C at the 1:43pm
lower high — all into collapsing event vol — and they were the biggest losers.

Design-review (verifier) corrections folded in:
  * The clean-continuation guard is NOT "IV not crushing" (that would brake
    post-earnings runners like ARM 5/26, which crushed IV at 4.16 ATR right
    before +25%). Instead the brake requires **the tape to have ROLLED** — a
    lower high, or below prior close, or below the session open. An
    up-continuing tape is NEVER braked, regardless of IV.
  * The pre-catalyst window is bounded (min(dte, CATALYST_PRE_DAYS_MAX)) so a
    30-45 DTE bull signal isn't braked a month before earnings.
  * Extension uses pct-above-MA20 as the primary metric (MA20 is available live
    via the RTS cache; clean ATR is not — worker.py passes closes-only). +18%
    ~= 2 ATR for these high-ATR names. ATR is used when supplied.

This module exposes BOTH the brake (bull suppression) and the exhaustion
primitives that the bear-enablement (#122-D) reuses to decide a blow-off short.

Shadow by default. Env EUPHORIA_BRAKE_ACTIVE=1 to enforce bull suppression.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

# ── thresholds (calibrated 6/25-6/26; verified) ─────────────────────────────
EUPH_PCT_SUPPRESS = 0.18    # >=+18% over MA20 (~2 ATR) -> suppress long
EUPH_PCT_INVERT = 0.25      # >=+25% over MA20 (~2.8 ATR) -> blow-off extreme
EUPH_ATR_SUPPRESS = 2.0     # used instead of pct when ATR supplied
EUPH_ATR_INVERT = 2.8
CATALYST_PRE_DAYS_MAX = 7   # don't arm pre-catalyst more than a week out
IVCRUSH_DROP_PCT = 0.06     # >=6% relative IV drop vs prior session = post-print crush

SNAPSHOTS_DB = os.environ.get("SNAPSHOTS_DB_PATH", "snapshots.db")


def _active() -> bool:
    return os.environ.get("EUPHORIA_BRAKE_ACTIVE", "").lower() in ("1", "true", "yes")


class _ActiveProxy:
    def __bool__(self) -> bool:
        return _active()


BRAKE_ACTIVE = _ActiveProxy()


# ── exhaustion primitives (shared with #122-D bear-enablement) ──────────────
def extension(spot: float, ma20: float | None, atr: float | None = None) -> dict:
    """How stretched is spot above its 20d mean. Returns metrics + flags."""
    out = {"pct_above_ma20": None, "atr_dist": None, "suppress": False, "invert": False}
    if not spot or not ma20 or ma20 <= 0:
        return out
    pct = (spot - ma20) / ma20
    out["pct_above_ma20"] = round(pct, 4)
    if atr and atr > 0:
        out["atr_dist"] = round((spot - ma20) / atr, 2)
        out["suppress"] = out["atr_dist"] >= EUPH_ATR_SUPPRESS
        out["invert"] = out["atr_dist"] >= EUPH_ATR_INVERT
    else:
        out["suppress"] = pct >= EUPH_PCT_SUPPRESS
        out["invert"] = pct >= EUPH_PCT_INVERT
    return out


def tape_rolled(intraday: dict | None) -> bool:
    """True when the tape has actually turned over (the verifier-mandated axis).

    `intraday` is the _intraday_momentum_stats dict: vs_open_pct, vs_high_pct,
    vs_low_pct. Rolled = decisively off the high (vs_high <= -0.5%) OR red vs
    open (vs_open <= -0.2%). An up-continuing tape returns False -> never braked.
    """
    if not intraday:
        return False
    vs_high = intraday.get("vs_high_pct")
    vs_open = intraday.get("vs_open_pct")
    if vs_high is not None and vs_high <= -0.5:
        return True
    if vs_open is not None and vs_open <= -0.2:
        return True
    return False


def snapshot_iv(ticker: str, *, db: str | None = None) -> float | None:
    """Most recent IV for a ticker from snapshots (None on any error)."""
    return _iv_query(ticker, 0, db)


def iv_n_days_ago(ticker: str, n: int, *, db: str | None = None) -> float | None:
    """IV from ~n calendar days ago (latest row before that cutoff)."""
    return _iv_query(ticker, n, db)


def _iv_query(ticker: str, days_back: int, db: str | None) -> float | None:
    try:
        con = sqlite3.connect(f"file:{db or SNAPSHOTS_DB}?mode=ro", uri=True, timeout=5)
        try:
            if days_back <= 0:
                row = con.execute(
                    "SELECT iv FROM snapshots WHERE ticker=? AND iv>0 "
                    "ORDER BY ts DESC LIMIT 1", (ticker,)).fetchone()
            else:
                cutoff = f"-{days_back} days"
                row = con.execute(
                    "SELECT iv FROM snapshots WHERE ticker=? AND iv>0 "
                    "AND ts <= strftime('%s','now', ?) ORDER BY ts DESC LIMIT 1",
                    (ticker, cutoff)).fetchone()
            return float(row[0]) if row and row[0] else None
        finally:
            con.close()
    except Exception:
        return None


def iv_crush(ticker: str, *, iv_now: float | None = None,
             iv_prior: float | None = None, db: str | None = None) -> bool:
    """True when event vol has collapsed (>=6% relative drop vs ~2 sessions ago).

    Marks the post-print regime that a forward-ER calendar (er_in_window) can't
    see. Inputs injectable for tests; otherwise read from snapshots.
    """
    now = iv_now if iv_now is not None else snapshot_iv(ticker, db=db)
    prior = iv_prior if iv_prior is not None else iv_n_days_ago(ticker, 2, db=db)
    if not now or not prior or prior <= 0:
        return False
    return (prior - now) / prior >= IVCRUSH_DROP_PCT


# ── the brake ───────────────────────────────────────────────────────────────
def euphoria_state(
    ticker: str,
    spot: float,
    *,
    ma20: float | None,
    dte: int | None = None,
    er_in_window_days: int | None = None,
    atr: float | None = None,
    intraday: dict | None = None,
    iv_now: float | None = None,
    iv_prior: float | None = None,
    db: str | None = None,
) -> dict:
    """Decide whether a BULL breakout/bounce should be braked.

    verdict: "PASS" | "SUPPRESS" | "INVERT".
      SUPPRESS -> demote the long to UI/DB-only (no Telegram/auto-trade).
      INVERT   -> blow-off extreme; suppress AND flag as a fade-watch.
    Brakes ONLY when extended AND catalyst-in-window AND tape-rolled. An
    up-continuing tape (tape_rolled False) always PASSes -> ARM-runner guard.
    """
    ext = extension(spot, ma20, atr)
    rolled = tape_rolled(intraday)

    # catalyst axis: forward ER within a bounded pre-window OR post-print crush.
    pre_window = None
    if er_in_window_days is not None and dte is not None:
        pre_window = er_in_window_days <= min(dte, CATALYST_PRE_DAYS_MAX)
    elif er_in_window_days is not None:
        pre_window = er_in_window_days <= CATALYST_PRE_DAYS_MAX
    crush = iv_crush(ticker, iv_now=iv_now, iv_prior=iv_prior, db=db)
    catalyst = bool(pre_window) or crush

    verdict = "PASS"
    reason = None
    if ext["suppress"] and catalyst and rolled:
        verdict = "INVERT" if ext["invert"] else "SUPPRESS"
        pctd = ext["pct_above_ma20"]
        cat = "ER<=window" if pre_window else "IV-crush"
        reason = (f"euphoria: +{pctd*100:.0f}% over MA20"
                  f"{f' ({ext['atr_dist']} ATR)' if ext['atr_dist'] else ''}, "
                  f"{cat}, tape rolled")
    return {
        "verdict": verdict,
        "reason": reason,
        "extended": ext["suppress"],
        "pct_above_ma20": ext["pct_above_ma20"],
        "atr_dist": ext["atr_dist"],
        "catalyst": catalyst,
        "iv_crush": crush,
        "tape_rolled": rolled,
    }
