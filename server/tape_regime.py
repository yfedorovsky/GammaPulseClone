"""Tape regime classifier — annotation only.

Classifies the day-so-far microstructure into one of:
  TREND_UP    : strong directional rally, no recent LOD test, making new HODs
  TREND_DOWN  : strong directional fade, no recent HOD test, making new LODs
  RANGE       : tight range bounded by repeated LOD/HOD tests
  MIXED       : doesn't cleanly fit; the most common state
  NOISY       : unusually wide range, likely event-driven

The output is meant to be SURFACED IN TELEGRAM BANNERS, not used as a
hard gate. Per the cross-LLM round 4 freeze-discipline policy:
"only annotation, no production trading-logic changes during the
forward window." The regime tag gives the trader context to mentally
apply different exit rules per regime, but the gates and tier logic
are unchanged.

Origin: BACKLOG.md "Tape Regime Classifier" item, plus the May 2 2026
intrinsic-capture analysis finding that the 0DTE alert win rate is
bimodal by day character (winners cluster on a subset of days; losers
spam quiet drift days like May 1). The metadata of the alerts is
identical between winning and losing days — so the differentiator must
be EXTERNAL day-level context, which this classifier surfaces.

Design constraints:
- Pure function: takes minute bars + a target timestamp, returns regime
- No DB writes, no live-side state
- Deterministic on the same input
- Cheap (~ms per call) so it can run on every alert dispatch
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Regime = Literal["TREND_UP", "TREND_DOWN", "RANGE", "MIXED", "NOISY"]


# ── Pre-committed thresholds (tunable but frozen for the forward window) ──

# Net move from open required for "TREND" classification (40bp)
TREND_NET_MOVE_PCT = 0.004

# Time since last touch of opposite extreme (LOD for trend up, HOD for
# trend down) required for trend conviction (90 minutes)
TREND_NO_OPPOSITE_TEST_MIN = 90

# Number of new session HODs/LODs in last 60 min for trend conviction
TREND_NEW_EXTREMES_60M = 3

# Range classification: tight band around open
RANGE_NET_MOVE_PCT = 0.002       # within 20bp of open
RANGE_DAY_RANGE_PCT = 0.005      # day's full range under 50bp
RANGE_OPP_TEST_RECENT_MIN = 60   # at least one extreme test in last 60min

# Noisy classification: range exceeds this threshold
NOISY_DAY_RANGE_PCT = 0.012      # >1.2% intraday range

# Tolerance for "near LOD/HOD" — used for tracking whether a bar
# touched the extreme (matches FLOOR_PROXIMITY_PCT in structural_turn)
EXTREME_TOUCH_TOL = 0.003


@dataclass
class TapeRegimeResult:
    regime: Regime
    confidence: float           # 0-1, qualitative
    open_to_spot_pct: float
    range_pct: float
    mins_since_lod_touch: int
    mins_since_hod_touch: int
    n_new_hods_60m: int
    n_new_lods_60m: int
    reason: str

    def banner_str(self) -> str:
        """Short tag suitable for Telegram message line."""
        emoji = {
            "TREND_UP":   "🚀",
            "TREND_DOWN": "💀",
            "RANGE":      "↔️",
            "MIXED":      "🔀",
            "NOISY":      "🌪️",
        }[self.regime]
        return (f"{emoji} TAPE: {self.regime}  "
                f"(open{self.open_to_spot_pct*100:+.2f}% / "
                f"range {self.range_pct*100:.2f}%)")


def classify_tape_regime(
    minute_bars: list[dict], ts: int,
) -> TapeRegimeResult:
    """Classify the day's tape character at timestamp `ts`.

    `minute_bars`: list of dicts with at least {ts, open, high, low,
    close} for the trading day. Bars after `ts` are ignored.
    `ts`: target evaluation timestamp (UNIX seconds).
    """
    # Filter to bars in this session up to and including ts
    session = [b for b in minute_bars if b["ts"] <= ts]
    if not session:
        return TapeRegimeResult(
            regime="MIXED", confidence=0.0,
            open_to_spot_pct=0.0, range_pct=0.0,
            mins_since_lod_touch=-1, mins_since_hod_touch=-1,
            n_new_hods_60m=0, n_new_lods_60m=0,
            reason="no session bars yet",
        )

    open_price = float(session[0]["open"])
    spot = float(session[-1]["close"])
    hod = max(float(b["high"]) for b in session)
    lod = min(float(b["low"]) for b in session)

    if open_price <= 0 or lod <= 0:
        return TapeRegimeResult(
            regime="MIXED", confidence=0.0,
            open_to_spot_pct=0.0, range_pct=0.0,
            mins_since_lod_touch=-1, mins_since_hod_touch=-1,
            n_new_hods_60m=0, n_new_lods_60m=0,
            reason="invalid open/LOD",
        )

    open_to_spot_pct = (spot - open_price) / open_price
    range_pct = (hod - lod) / open_price

    # Time since last touch of LOD/HOD (within EXTREME_TOUCH_TOL).
    # Walk back from latest bar.
    lod_tol = lod * EXTREME_TOUCH_TOL
    hod_tol = hod * EXTREME_TOUCH_TOL
    mins_since_lod_touch = -1
    mins_since_hod_touch = -1
    for b in reversed(session):
        if mins_since_lod_touch < 0 and abs(b["low"] - lod) <= lod_tol:
            mins_since_lod_touch = (ts - b["ts"]) // 60
        if mins_since_hod_touch < 0 and abs(b["high"] - hod) <= hod_tol:
            mins_since_hod_touch = (ts - b["ts"]) // 60
        if mins_since_lod_touch >= 0 and mins_since_hod_touch >= 0:
            break

    # New HOD/LOD count in last 60 min.
    cutoff_60m = ts - 60 * 60
    last_60m = [b for b in session if b["ts"] >= cutoff_60m]
    n_new_hods_60m = 0
    n_new_lods_60m = 0
    running_high = -float("inf")
    running_low = float("inf")
    # Re-walk session from start to count when each new extreme was made
    for b in session:
        if b["high"] > running_high:
            running_high = b["high"]
            if b["ts"] >= cutoff_60m:
                n_new_hods_60m += 1
        if b["low"] < running_low:
            running_low = b["low"]
            if b["ts"] >= cutoff_60m:
                n_new_lods_60m += 1

    # ── Decision tree (priority order: NOISY > TREND > RANGE > MIXED) ──

    # NOISY: unusually wide range overrides everything
    if range_pct > NOISY_DAY_RANGE_PCT:
        return TapeRegimeResult(
            regime="NOISY", confidence=0.7,
            open_to_spot_pct=open_to_spot_pct, range_pct=range_pct,
            mins_since_lod_touch=int(mins_since_lod_touch),
            mins_since_hod_touch=int(mins_since_hod_touch),
            n_new_hods_60m=n_new_hods_60m, n_new_lods_60m=n_new_lods_60m,
            reason=f"range {range_pct*100:.2f}% exceeds noisy threshold "
                   f"{NOISY_DAY_RANGE_PCT*100:.1f}%",
        )

    # TREND_UP: net up + no recent LOD test + making new highs
    if (open_to_spot_pct > TREND_NET_MOVE_PCT
            and mins_since_lod_touch > TREND_NO_OPPOSITE_TEST_MIN
            and n_new_hods_60m >= TREND_NEW_EXTREMES_60M):
        return TapeRegimeResult(
            regime="TREND_UP", confidence=0.8,
            open_to_spot_pct=open_to_spot_pct, range_pct=range_pct,
            mins_since_lod_touch=int(mins_since_lod_touch),
            mins_since_hod_touch=int(mins_since_hod_touch),
            n_new_hods_60m=n_new_hods_60m, n_new_lods_60m=n_new_lods_60m,
            reason=f"net +{open_to_spot_pct*100:.2f}% from open, "
                   f"LOD untouched {mins_since_lod_touch}min, "
                   f"{n_new_hods_60m} new HODs in 60m",
        )

    # TREND_DOWN: net down + no recent HOD test + making new lows
    if (open_to_spot_pct < -TREND_NET_MOVE_PCT
            and mins_since_hod_touch > TREND_NO_OPPOSITE_TEST_MIN
            and n_new_lods_60m >= TREND_NEW_EXTREMES_60M):
        return TapeRegimeResult(
            regime="TREND_DOWN", confidence=0.8,
            open_to_spot_pct=open_to_spot_pct, range_pct=range_pct,
            mins_since_lod_touch=int(mins_since_lod_touch),
            mins_since_hod_touch=int(mins_since_hod_touch),
            n_new_hods_60m=n_new_hods_60m, n_new_lods_60m=n_new_lods_60m,
            reason=f"net {open_to_spot_pct*100:.2f}% from open, "
                   f"HOD untouched {mins_since_hod_touch}min, "
                   f"{n_new_lods_60m} new LODs in 60m",
        )

    # RANGE: tight band around open with recent two-sided action
    if (abs(open_to_spot_pct) < RANGE_NET_MOVE_PCT
            and range_pct < RANGE_DAY_RANGE_PCT
            and (mins_since_lod_touch <= RANGE_OPP_TEST_RECENT_MIN
                 or mins_since_hod_touch <= RANGE_OPP_TEST_RECENT_MIN)):
        return TapeRegimeResult(
            regime="RANGE", confidence=0.6,
            open_to_spot_pct=open_to_spot_pct, range_pct=range_pct,
            mins_since_lod_touch=int(mins_since_lod_touch),
            mins_since_hod_touch=int(mins_since_hod_touch),
            n_new_hods_60m=n_new_hods_60m, n_new_lods_60m=n_new_lods_60m,
            reason=f"net {open_to_spot_pct*100:+.2f}%, range {range_pct*100:.2f}%, "
                   f"recent extreme test (LOD {mins_since_lod_touch}m / "
                   f"HOD {mins_since_hod_touch}m ago)",
        )

    # MIXED: anything else (the most common state)
    return TapeRegimeResult(
        regime="MIXED", confidence=0.4,
        open_to_spot_pct=open_to_spot_pct, range_pct=range_pct,
        mins_since_lod_touch=int(mins_since_lod_touch),
        mins_since_hod_touch=int(mins_since_hod_touch),
        n_new_hods_60m=n_new_hods_60m, n_new_lods_60m=n_new_lods_60m,
        reason=f"net {open_to_spot_pct*100:+.2f}%, range {range_pct*100:.2f}%, "
               f"no clean trend or range pattern",
    )


# ── Suggested play guidance per regime (for telegram banner) ──

PLAY_GUIDANCE = {
    "TREND_UP": (
        "TREND day — directional follow-through likely. Bullish 0DTE "
        "alerts have favorable backdrop; bearish 0DTE alerts will fight "
        "the trend. Take TP at +50% on bullish; skip/fade bearish."
    ),
    "TREND_DOWN": (
        "FADE day — directional collapse. Bearish 0DTE alerts have "
        "favorable backdrop; bullish 0DTE alerts are likely catching "
        "knives. Take TP at +50% on bearish; SKIP all bullish without "
        "ST confirmation (May 1 evidence: 11 bullish alerts, 11 wipeouts)."
    ),
    "RANGE": (
        "RANGE day — tight chop, repeated LOD/HOD tests. ST is most "
        "reliable in this regime (LOD-absorption setups). Take ST-confirmed "
        "alerts only; standalone 0DTE alerts likely chase. TP +25% / Stop -30%."
    ),
    "MIXED": (
        "MIXED — no clean tape character. Default workflow: wait for ST "
        "confirmation. If taking standalone 0DTE: TP +50% / Stop -30% / "
        "Time-stop 30min. Do NOT hold to EOD."
    ),
    "NOISY": (
        "NOISY day — unusually wide range, likely event-driven. Reduce "
        "position size. Avoid late-day chasers. ST highly likely to misfire "
        "in this regime."
    ),
}


def regime_play_guidance(regime: Regime) -> str:
    return PLAY_GUIDANCE.get(regime, "")


# ── Convenience wrapper for the live worker ──

def classify_from_yfinance(ticker: str, ts: int | None = None) -> TapeRegimeResult:
    """Live-side helper: pull today's bars from yfinance, classify.

    Returns MIXED with reason='no bars' if yfinance fails — this is
    intentionally fail-soft so a flaky data source can't block the
    annotation pipeline."""
    if ts is None:
        ts = int(datetime.now().timestamp())
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period="1d", interval="1m",
                                        prepost=False)
        if df.empty:
            return TapeRegimeResult(
                regime="MIXED", confidence=0.0,
                open_to_spot_pct=0.0, range_pct=0.0,
                mins_since_lod_touch=-1, mins_since_hod_touch=-1,
                n_new_hods_60m=0, n_new_lods_60m=0,
                reason="yfinance returned no bars",
            )
        df.index = df.index.tz_convert("America/New_York")
        bars = [
            {
                "ts": int(t.timestamp()),
                "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]),
            }
            for t, r in df.iterrows()
        ]
        return classify_tape_regime(bars, ts)
    except Exception as e:
        return TapeRegimeResult(
            regime="MIXED", confidence=0.0,
            open_to_spot_pct=0.0, range_pct=0.0,
            mins_since_lod_touch=-1, mins_since_hod_touch=-1,
            n_new_hods_60m=0, n_new_lods_60m=0,
            reason=f"yfinance failed: {type(e).__name__}: {e}",
        )
