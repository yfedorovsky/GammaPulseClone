"""Real-time unusual flow alert system — ZERO additional API calls.

Piggybacks on the GEX worker's chain cache to scan ALL cached tickers
(300+ across mega/large/mid cap) for unusual options volume every 30 seconds.

Coverage:
  - Tier 1: mega caps (SPY, QQQ, AAPL, NVDA, TSLA, etc.)
  - Tier 2: large caps (META, CRM, SHOP, UBER, etc.)
  - Tier 3: mid caps (DOCN, SOFI, RIVN, MARA, etc.)
  All tickers in the scanner universe are covered for flow alerts.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from typing import Any

import httpx

from .cache import cache
from .config import get_settings
from .market_calendar import is_rth_or_extended
from .tick_side_tracker import get_tracker as _get_tick_side_tracker


ALERT_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  expiration TEXT NOT NULL,
  option_type TEXT NOT NULL,
  volume INTEGER,
  oi INTEGER,
  vol_oi REAL,
  last_price REAL,
  bid REAL,
  ask REAL,
  side TEXT,
  sentiment TEXT,
  iv REAL,
  delta REAL,
  notional REAL,
  spot REAL,
  conviction TEXT DEFAULT 'LOW',
  status TEXT DEFAULT 'OPEN',
  king REAL,
  floor_level REAL,
  ceiling_level REAL,
  signal TEXT,
  regime TEXT,
  -- ThetaData sweep columns (added Apr 17, 2026).
  -- is_sweep = TRUE when OPRA tags trade(s) with condition 95/126/128.
  -- Populated by server/sweep_detector.py from the WebSocket stream.
  -- Existing flow alerts (vol/OI-based) leave these NULL.
  is_sweep INTEGER DEFAULT 0,
  sweep_side TEXT,              -- 'BUY' (above ask) | 'SELL' (below bid) | 'NEUTRAL'
  sweep_notional REAL,          -- total $ across all ISO prints in the rollup window
  sweep_contracts INTEGER,      -- total size summed across prints
  sweep_venues INTEGER,         -- count of distinct exchange codes (real sweep = >1)
  sweep_prints INTEGER,         -- number of ISO prints in the cluster
  sweep_window_s INTEGER        -- rollup window (seconds) that produced this alert
);
CREATE INDEX IF NOT EXISTS idx_flow_ts ON flow_alerts(ts);
CREATE INDEX IF NOT EXISTS idx_flow_ticker ON flow_alerts(ticker, ts);
-- NOTE: idx_flow_sweep is created in _SWEEP_MIGRATIONS after ALTER TABLE
-- (can't live in the base schema since existing DBs lack the is_sweep column
--  at the time this CREATE TABLE IF NOT EXISTS is a no-op).
"""


# Migration for existing DBs (run on startup, idempotent).
# sqlite ALTER TABLE ADD COLUMN errors if column already exists — we ignore.
_SWEEP_MIGRATIONS = [
    "ALTER TABLE flow_alerts ADD COLUMN is_sweep INTEGER DEFAULT 0",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_side TEXT",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_notional REAL",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_contracts INTEGER",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_venues INTEGER",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_prints INTEGER",
    "ALTER TABLE flow_alerts ADD COLUMN sweep_window_s INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_flow_sweep ON flow_alerts(is_sweep, ts) WHERE is_sweep = 1",
    # Apr 27: macro regime tag (Perplexity feedback). Cross-family
    # consistency — tag flow_alerts the same way as soe_signals so
    # we can ask "did sweep-followed trades degrade in HARD regime?"
    # alongside SOE WR. Uses 60s cache (cached_macro_regime_tag).
    "ALTER TABLE flow_alerts ADD COLUMN macro_regime_tag TEXT DEFAULT 'NONE'",
    # 2026-05-27: insider-pattern score (0-6). When >= 5 → INSIDER tag,
    # force-through Telegram + UI pin. See _classify_insider_signature.
    "ALTER TABLE flow_alerts ADD COLUMN insider_score INTEGER DEFAULT 0",
    "ALTER TABLE flow_alerts ADD COLUMN is_insider INTEGER DEFAULT 0",
    "ALTER TABLE flow_alerts ADD COLUMN insider_reasons TEXT",
    "CREATE INDEX IF NOT EXISTS idx_flow_insider ON flow_alerts(is_insider, ts) WHERE is_insider = 1",
]


def _safe_regime_tag() -> str:
    """Cached regime fetch for high-frequency flow_alerts inserts.
    Fail-open returns NONE on any error."""
    try:
        from .macro_regime import cached_macro_regime_tag
        return cached_macro_regime_tag()
    except Exception:
        return "NONE"

# ── Dedup state ─────────────────────────────────────────────────────────
# Pre-2026-05-08: Set was {ticker:strike:exp:type} — fired exactly ONCE per
# strike per process lifetime. Catastrophic on flip days: INTC 5/15 120C
# fired BEARISH at 10:16 AM (call sellers); when the AAPL-deal insider
# flow flipped it BULLISH at 11:30 AM with $5M+ ASK sweeps, we silently
# skipped because the strike was already in `_seen`. Two hours of insider
# positioning never reached Telegram.
#
# Now: dict keyed by {ticker:strike:exp:type:sentiment_bucket} → last
# fire timestamp. We re-fire when:
#   (a) The same key exhausted its TTL (default 5 min), OR
#   (b) The sentiment_bucket flipped (BULL/BEAR/NEUT) — which happens
#       when smart-money rotates direction on a contract.
# The bucket is derived from `sentiment` so a BEARISH-tagged strike
# becoming BULLISH-tagged refires regardless of TTL.
_DEDUP_TTL_SECONDS = 300
_seen: dict[str, float] = {}


def _dedup_key(ticker: str, strike: float, exp: str, otype: str, sentiment: str) -> str:
    bucket = (sentiment or "NEUT")[:4].upper()  # BULL / BEAR / NEUT / MID
    return f"{ticker}:{strike}:{exp}:{otype}:{bucket}"


def _should_skip_dedup(key: str, now: float) -> bool:
    """Returns True if we recently emitted this exact (strike, sentiment)
    bucket — don't re-fire. Aged-out entries are pruned in place."""
    last = _seen.get(key)
    if last is None:
        return False
    if now - last >= _DEDUP_TTL_SECONDS:
        # TTL expired — let it re-fire
        return False
    return True


@contextmanager
def _conn():
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_alert_db() -> None:
    with _conn() as c:
        c.executescript(ALERT_SCHEMA)
        # Run idempotent migrations for existing DBs that predate the sweep columns
        for stmt in _SWEEP_MIGRATIONS:
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                # Column already exists or index already exists — expected
                pass


def insert_sweep_alert(rollup: dict[str, Any], gex_info: dict[str, Any] | None = None) -> None:
    """Insert an ISO-sweep-flagged flow alert.

    rollup contains the aggregated sweep data produced by sweep_detector.py
    across one rollup window for one contract:
      ticker, strike, expiration, option_type,
      sweep_notional, sweep_contracts, sweep_venues, sweep_prints,
      sweep_side ('BUY'/'SELL'/'NEUTRAL'), sweep_window_s,
      spot, bid, ask, last, iv, delta, oi
    """
    conviction = "SWEEP"  # Highest tier — OPRA-tagged, not inferred
    with _conn() as c:
        c.execute(
            """INSERT INTO flow_alerts
            (ts, ticker, strike, expiration, option_type, volume, oi, vol_oi,
             last_price, bid, ask, side, sentiment, iv, delta, notional, spot,
             conviction, status, king, floor_level, ceiling_level, signal, regime,
             is_sweep, sweep_side, sweep_notional, sweep_contracts, sweep_venues,
             sweep_prints, sweep_window_s, macro_regime_tag)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()),
                rollup["ticker"],
                rollup["strike"],
                rollup["expiration"],
                rollup["option_type"],
                rollup.get("sweep_contracts"),  # use sweep contract count for volume field
                rollup.get("oi"),
                None,  # vol_oi — not meaningful for sweep rollup
                rollup.get("last"),
                rollup.get("bid"),
                rollup.get("ask"),
                rollup.get("sweep_side"),  # 'BUY' / 'SELL' / 'NEUTRAL'
                rollup.get("sweep_side"),  # sentiment mirrors side for sweeps
                rollup.get("iv"),
                rollup.get("delta"),
                rollup.get("sweep_notional"),
                rollup.get("spot"),
                conviction,
                "OPEN",
                gex_info.get("king") if gex_info else None,
                gex_info.get("floor") if gex_info else None,
                gex_info.get("ceiling") if gex_info else None,
                gex_info.get("signal") if gex_info else None,
                gex_info.get("regime") if gex_info else None,
                1,  # is_sweep
                rollup.get("sweep_side"),
                rollup.get("sweep_notional"),
                rollup.get("sweep_contracts"),
                rollup.get("sweep_venues"),
                rollup.get("sweep_prints"),
                rollup.get("sweep_window_s"),
                _safe_regime_tag(),
            ),
        )


def get_sweep_alerts(
    since_ts: int = 0, limit: int = 100, ticker: str | None = None,
    min_notional: float = 0,
) -> list[dict[str, Any]]:
    """Return ISO-sweep-flagged alerts only (is_sweep=1)."""
    with _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE is_sweep = 1 AND ts > ? AND ticker = ? "
                "AND COALESCE(sweep_notional, 0) >= ? ORDER BY ts DESC LIMIT ?",
                (since_ts, ticker.upper(), min_notional, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE is_sweep = 1 AND ts > ? "
                "AND COALESCE(sweep_notional, 0) >= ? ORDER BY ts DESC LIMIT ?",
                (since_ts, min_notional, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def _compute_conviction(alert: dict[str, Any], gex_info: dict[str, Any] | None = None) -> str:
    """Score conviction: HIGH / MEDIUM / LOW based on volume, notional, and GEX alignment.

    Includes CHEAP 0DTE WHALE override (2026-04-23): notional-based scoring
    systematically under-grades cheap-option lotto whales. Example caught:
    QQQ 649P 0DTE today — UW flagged $0.09 → $4.33 (+4700%). We saw 55k vol
    at $0.10 ($550k notional = MEDIUM under old rules) but that's 55,000
    contracts = delta-equivalent of ~2,000 ATM puts = actual whale positioning.
    Override catches this pattern.
    """
    import datetime

    score = 0
    vol = alert.get("volume", 0) or 0
    notional = alert.get("notional", 0) or 0
    vol_oi = alert.get("vol_oi", 0) or 0
    # Cache-scan alerts store the price under "last"; sweep alerts under "last_price".
    # Read both so Tier A/B whale overrides actually fire on cache-scan flow.
    last_price = alert.get("last_price") or alert.get("last") or 0
    expiration = alert.get("expiration", "") or ""

    # ── CHEAP-OPTION WHALE OVERRIDE (checked first, bypasses notional) ──
    # Position size over premium size. When someone dumps $500k into 50k
    # contracts of a 10¢ 0/1DTE option, that's a gamma-squeeze lotto bet.
    # Sets alert['_whale_override'] so the Telegram formatter can flag
    # these visually distinct from standard HIGH alerts.
    try:
        today_str = datetime.date.today().isoformat()
        tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        is_0_1_dte = expiration in (today_str, tomorrow_str)
        # Tier A: cheap <= $0.50, 20k+ vol, 10x+ v/oi, 0/1 DTE -> HIGH (WHALE)
        if is_0_1_dte and 0 < last_price <= 0.50 and vol >= 20_000 and vol_oi >= 10:
            alert["_whale_override"] = "A"
            return "HIGH"
        # Tier B: ultra-cheap <= $0.25 lottos with extreme v/oi -> HIGH (WHALE)
        if is_0_1_dte and 0 < last_price <= 0.25 and vol >= 10_000 and vol_oi >= 15:
            alert["_whale_override"] = "B"
            return "HIGH"
        # Tier C: absurd volume regardless of price (50k+ contracts single strike) -> HIGH (WHALE)
        if vol >= 50_000 and vol_oi >= 5:
            alert["_whale_override"] = "C"
            return "HIGH"
    except Exception:
        pass

    # ── Standard score-based logic (existing) ──

    # Volume tier
    if vol >= 5000: score += 2
    elif vol >= 2000: score += 1

    # Notional tier
    if notional >= 5_000_000: score += 2
    elif notional >= 1_000_000: score += 1

    # V/OI ratio
    if vol_oi >= 10: score += 1

    # GEX alignment: does the flow direction match the GEX signal?
    if gex_info:
        signal = gex_info.get("signal", "")
        sentiment = alert.get("sentiment", "")
        otype = alert.get("option_type", "")
        if sentiment == "BULLISH" and otype == "call" and signal in ("MAGNET UP", "SUPPORT"):
            score += 2
        elif sentiment == "BEARISH" and otype == "put" and signal in ("AIR POCKET", "RESISTANCE"):
            score += 2
        elif signal == "PINNING":
            score += 1

    if score >= 5: return "HIGH"
    if score >= 3: return "MEDIUM"
    return "LOW"


def _classify_insider_signature(
    alert: dict[str, Any], spot_for_moneyness: float | None = None,
) -> tuple[int, list[str]]:
    """6-criteria INFORMED FLOW scorer (renamed from INSIDER PATTERN 2026-05-27 PM).

    Built from the pattern documented across our top catches:
      MU 3/31 whale ($111M → $1.5B intrinsic over 6 weeks)
      INTC 5/8 $120C ($5M+ ASK sweep ahead of AAPL deal news)
      META 5/27 0DTE 615C/617.5C/620C ladder (paid-subs announcement)

    Returns (score 0..6, list of matched-criteria labels).
    Score >= 5 → flag as is_insider=1 (force-through Telegram + UI pin).
    Note: the underlying tag is INFORMED FLOW; the `is_insider` DB column
    name is retained for backward compat — see telegram.py for the new
    user-facing label.

    Criteria (each = 1 point):
      1. V/OI ≥ 10x        — abnormal new positioning (paired with #2)
      2. vol > oi          — clearly opening, not roll/close
      3. ASK side          — buyer-initiated (post-P0 side fix reliable)
      4. Cheap leverage    — 2/4 vote: (a) ask ≤ $5.00 OR (b) OTM ≥ 3%
                             [moneyness ratio replaces absolute dollar
                             threshold per Gemini/ChatGPT critique —
                             $5 means 25% notional on $20 stock vs 0.5%
                             on $1,000 stock]
      5. Short-dated ≤ 7 DTE — time-sensitive catalyst priced in
      6. OTM |delta| ≤ 0.40  — leverage zone, insider sweet spot

    Hard sanity gates (apply BEFORE scoring):
      - oi ≥ 100 OR vol ≥ 500  (denominator-vulnerability guard per ChatGPT/Gemini —
        25-contract retail trade vs OI=2 producing V/OI=12.5x is meaningless)
      - notional ≥ $10,000  (filter retail micro-spam per Gemini)
    """
    import datetime as _dt
    matched: list[str] = []
    vol = alert.get("volume", 0) or 0
    oi = alert.get("oi", 0) or 0
    vol_oi = alert.get("vol_oi", 0) or 0
    side = (alert.get("side") or "").upper()
    ask = alert.get("ask", 0) or 0
    last = alert.get("last") or alert.get("last_price") or 0
    delta = alert.get("delta", 0) or 0
    exp = alert.get("expiration") or ""
    strike = alert.get("strike", 0) or 0
    spot = spot_for_moneyness if spot_for_moneyness else (alert.get("spot", 0) or 0)
    notional = alert.get("notional", 0) or 0

    # ── Hard sanity gates (return 0 score, classifier cannot fire) ──
    if oi < 100 and vol < 500:
        # Denominator vulnerability: insufficient liquidity for V/OI ratio
        # to be meaningful. 12.5x on OI=2 is noise. Score=0, won't fire.
        return 0, []
    if notional < 10_000:
        # Retail micro-flow: even 6/6 score is meaningless at $200 trade size.
        # Insiders deploy real capital; this gate cuts the spam without
        # touching legitimate informed flow.
        return 0, []

    # Hard gate: V/OI >= 10x is REQUIRED (not just a vote).
    # Discovered during 2026-05-27 PM backtest: SPX/SPY 0DTE liquidity at
    # V/OI 2-3x was firing 5/6 because OPEN+ASK+cheap+0DTE+OTM = 5 even
    # without abnormal volume. That's exactly the criteria-collapse problem
    # ChatGPT flagged (6 criteria → ~3 latent dimensions). V/OI≥10x is the
    # abnormality signal; without it, we're flagging normal opening flow
    # with leverage, not informed accumulation.
    if vol_oi < 10:
        return 0, []

    # Hard gate: expired contracts (DTE < 0) — should never fire INFORMED
    # FLOW. SPY $749P 2026-05-26 was firing today (5/27) at V/OI 495.9x on
    # ask $0.03 — stale-OI artifact from yesterday's expiration.
    try:
        if exp:
            exp_date = _dt.date.fromisoformat(exp)
            if (exp_date - _dt.date.today()).days < 0:
                return 0, []
    except (ValueError, TypeError):
        pass

    # ── 6-criteria scorer ──
    if vol_oi >= 10:
        matched.append("V/OI≥10x")
    if vol > 0 and oi > 0 and vol > oi:
        matched.append("OPEN(vol>oi)")
    if side == "ASK":
        matched.append("ASK-side")

    # Cheap-leverage criterion (replaces ask ≤ $5 absolute threshold).
    # Either path satisfies: (a) very cheap absolute premium, OR
    # (b) meaningfully OTM by moneyness ratio. Gemini called the absolute
    # threshold "mathematically illiterate" — $5 on a $20 stock vs $1000 stock
    # are completely different instruments.
    premium = ask if ask > 0 else last
    moneyness_otm = 0.0
    if spot > 0 and strike > 0:
        otype = (alert.get("option_type") or "").lower()
        if otype == "call":
            moneyness_otm = (strike - spot) / spot
        else:
            moneyness_otm = (spot - strike) / spot
    if (0 < premium <= 5.00) or moneyness_otm >= 0.03:
        if moneyness_otm >= 0.03:
            matched.append(f"OTM+{moneyness_otm*100:.1f}%")
        else:
            matched.append("cheap≤$5")

    # DTE from expiration string YYYY-MM-DD
    try:
        if exp:
            exp_date = _dt.date.fromisoformat(exp)
            dte = (exp_date - _dt.date.today()).days
            if 0 <= dte <= 7:
                matched.append(f"{dte}DTE")
    except (ValueError, TypeError):
        pass

    if 0 < abs(delta) <= 0.40:
        matched.append(f"Δ{abs(delta):.2f}")

    # Scheduled-catalyst demote (Batch 3a, 2026-05-27 PM, ChatGPT/Perplexity).
    # 3/4 LLMs flagged this as a top precision booster. Reasoning: retail
    # traders pre-position into KNOWN earnings/FDA/announcement dates and
    # the resulting flow mirrors the informed-trade signature exactly —
    # cheap OTM short-dated calls/puts. Without this gate, the classifier
    # cannot distinguish "insider front-running an unscheduled catalyst"
    # from "retail YOLOing a known catalyst." The META 5/27 catch was on
    # an UNSCHEDULED catalyst (no earnings in window) so this rule doesn't
    # affect it; it cuts the event-day false-positive population.
    #
    # Implementation: demote score by 1 point when ticker has earnings
    # within the contract's DTE window. 6/6 with catalyst stays at 5 (still
    # fires); 5/6 with catalyst drops to 4 (no fire). Surgical effect.
    try:
        from .earnings_calendar import er_in_window_sync
        if exp:
            exp_date = _dt.date.fromisoformat(exp)
            dte = (exp_date - _dt.date.today()).days
            if 0 <= dte <= 14:
                ticker = alert.get("ticker", "")
                in_window, _days = er_in_window_sync(ticker, dte)
                if in_window:
                    # Demote one point and tag the alert for audit
                    matched.append("[catalyst-demote]")
                    return max(len(matched) - 2, 0), matched
                    # -2 because we appended one tag — net effect is -1
    except Exception:
        pass

    return len(matched), matched


# Per-contract dedup TTL (2026-05-27 PM, ChatGPT P0).
# Without this, hot contracts re-fire INFORMED FLOW on every snapshot tick —
# the META 620C 0DTE today fired 312 times, all the same insider position.
# Key on (ticker, strike, expiration, option_type, sentiment); 30-min TTL.
_INFORMED_FLOW_DEDUP: dict[tuple[str, float, str, str, str], float] = {}
INFORMED_FLOW_DEDUP_TTL_SEC = 30 * 60  # 30 min


def _is_informed_flow_duplicate(alert: dict[str, Any]) -> bool:
    """Check if this alert is a duplicate of one fired recently for the same
    contract. Returns True if dedup'd (drop), False if fresh (fire).
    """
    key = (
        alert.get("ticker", ""),
        alert.get("strike", 0),
        alert.get("expiration", ""),
        (alert.get("option_type") or "").lower(),
        (alert.get("sentiment") or "").upper(),
    )
    now = time.time()
    last_fire = _INFORMED_FLOW_DEDUP.get(key, 0.0)
    if now - last_fire < INFORMED_FLOW_DEDUP_TTL_SEC:
        return True
    _INFORMED_FLOW_DEDUP[key] = now
    # GC: purge entries older than 2× TTL
    cutoff = now - 2 * INFORMED_FLOW_DEDUP_TTL_SEC
    stale = [k for k, ts in _INFORMED_FLOW_DEDUP.items() if ts < cutoff]
    for k in stale:
        _INFORMED_FLOW_DEDUP.pop(k, None)
    return False


def insert_alert(alert: dict[str, Any], gex_info: dict[str, Any] | None = None) -> None:
    conviction = _compute_conviction(alert, gex_info)
    alert["conviction"] = conviction

    # 2026-06-02 PM: noise filter gate. Drops LOW conviction, small-dollar
    # MID side, and repeat-fire dedup. See server/flow_noise_filter.py
    # for the full rule list. Audit showed 327K alerts/day from only 7K
    # unique contracts (46x repeat). Filter reduces stored noise ~95%
    # while preserving every meaningful state change.
    try:
        from .flow_noise_filter import should_insert
        keep, reason = should_insert(alert)
        if not keep:
            # Silent drop — too noisy to log every dropped row. Sampling
            # can be added if we want visibility on what's being filtered.
            return
    except Exception as _filter_err:
        # Fail-open: if the filter errors, fall through to insert. Don't
        # silently lose alerts due to a filter bug.
        print(f"[FLOW_FILTER] error (fail-open): {_filter_err!r}", flush=True)

    # INFORMED FLOW score (0..6). >= 5 → is_insider=1 for force-Telegram + UI.
    # (Renamed from "INSIDER PATTERN" 2026-05-27 PM per ChatGPT validation —
    # the actual signal is "informed-looking flow ahead of catalysts" rather
    # than provably illegal insider trading. is_insider column name kept for
    # backward DB compat; user-facing label is now "INFORMED FLOW".)
    insider_score, insider_reasons = _classify_insider_signature(alert)
    alert["insider_score"] = insider_score
    alert["insider_reasons"] = insider_reasons

    # Hot-contract dedup: even when 5+/6, suppress is_insider for repeat
    # fires on the same (ticker, strike, exp, type, sentiment) within 30
    # min. The META 620C 0DTE today fired 312 times — same position, same
    # contract, getting re-tagged on every snapshot cycle. Dedup gate
    # collapses that to one fire per 30-min window. The underlying alert
    # still persists to flow_alerts table; only the is_insider tag (and
    # therefore Telegram + UI pin) is suppressed for duplicates.
    #
    # 2026-06-02 PM: chop-ticker gate. When today's bull-buy/bear-buy
    # notional balance is within ±10% on the dominant expiration, the
    # ticker is in textbook chop (TSLA 6/5 today: $9.2B / $9.2B = 0.1%
    # bias). INFORMED FLOW dispatch is suppressed for chop tickers
    # until the balance breaks. Audit trail preserved — the alert
    # still inserts with insider_score on it, just is_insider=0.
    _ticker = alert.get("ticker", "")
    _in_chop = False
    try:
        from .flow_noise_filter import is_ticker_in_chop
        _in_chop = is_ticker_in_chop(_ticker)
    except Exception:
        pass
    if insider_score >= 5 and _in_chop:
        alert["is_insider"] = 0
        alert["_informed_flow_chop_suppressed"] = 1
    elif insider_score >= 5 and not _is_informed_flow_duplicate(alert):
        alert["is_insider"] = 1
        # INFORMED FLOW trades override conviction to HIGH so trade_tracker
        # auto-tracks for exit signals (currently filtered to HIGH/SWEEP
        # only — see line ~850 auto-track gate). Without this, INFORMED
        # FLOW alerts at LOW/MEDIUM conviction would fire Telegram but
        # not show up in tracked_trades for the runner.
        if conviction != "HIGH":
            alert["_pre_insider_conviction"] = conviction
            conviction = "HIGH"
            alert["conviction"] = "HIGH"
    else:
        alert["is_insider"] = 0
        if insider_score >= 5:
            # Was qualifying but dedup'd. Mark so backtest / audit tooling
            # can distinguish "score too low" from "dedup'd repeat fire."
            alert["_informed_flow_dedup"] = 1
    with _conn() as c:
        c.execute(
            """INSERT INTO flow_alerts
            (ts, ticker, strike, expiration, option_type, volume, oi, vol_oi,
             last_price, bid, ask, side, sentiment, iv, delta, notional, spot,
             conviction, status, king, floor_level, ceiling_level, signal, regime,
             macro_regime_tag, insider_score, is_insider, insider_reasons)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(time.time()),
                alert["ticker"],
                alert["strike"],
                alert["expiration"],
                alert["option_type"],
                alert.get("volume"),
                alert.get("oi"),
                alert.get("vol_oi"),
                alert.get("last"),
                alert.get("bid"),
                alert.get("ask"),
                alert.get("side"),
                alert.get("sentiment"),
                alert.get("iv"),
                alert.get("delta"),
                alert.get("notional"),
                alert.get("spot"),
                conviction,
                "OPEN",
                gex_info.get("king") if gex_info else None,
                gex_info.get("floor") if gex_info else None,
                gex_info.get("ceiling") if gex_info else None,
                gex_info.get("signal") if gex_info else None,
                gex_info.get("regime") if gex_info else None,
                _safe_regime_tag(),
                insider_score,
                alert["is_insider"],
                ",".join(insider_reasons) if insider_reasons else None,
            ),
        )


def get_alerts(
    since_ts: int = 0, limit: int = 100, ticker: str | None = None
) -> list[dict[str, Any]]:
    with _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE ts > ? AND ticker = ? ORDER BY ts DESC LIMIT ?",
                (since_ts, ticker.upper(), limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM flow_alerts WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                (since_ts, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get_recent_flow(ticker: str, minutes: int = 30) -> dict[str, Any] | None:
    """Get most recent HIGH-conviction flow alert for a ticker within N minutes."""
    cutoff = int(time.time()) - minutes * 60
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM flow_alerts WHERE ticker = ? AND ts > ? AND conviction = 'HIGH' ORDER BY ts DESC LIMIT 1",
            (ticker.upper(), cutoff),
        ).fetchone()
    return dict(row) if row else None


def _detect_side(
    bid: float,
    ask: float,
    last: float,
    *,
    delta: float = 0.0,
    vol: int = 0,
    oi: int = 0,
    notional: float = 0.0,
) -> str:
    """Snapshot-based side classifier — fallback when tick tracker is thin.

    Returns 'ASK' | 'BID' | 'MID'. The optional kwargs (delta/vol/oi/notional)
    let callers nudge the decision when `last` is stale.

    Improvements (Bug #2 layered fix, 2026-05-12):
      1. Tightened mid threshold 0.2 -> 0.15 — late-day prints settling
         "near mid" were over-classified as MID.
      2. ITM bias: deep-ITM contracts (|delta| > 0.70) on a fresh-OI day
         (vol >= oi, i.e. opening accumulation) get ASK by default — the
         GLD 6/18 $380C / QCOM 6/18 $270C / MU 5/15 $760C class of trade.
      3. Cheap-far-OTM bias: small-premium far-OTM (delta < 0.15) with
         exploding V/OI (vol/oi >= 5) gets ASK — insider lotto signature.
      4. STALE-LAST DETECTION (2026-05-12 evening): when `last` is strictly
         outside the [bid, ask] band, the snapshot is provably stale (a
         fresh trade can't print below bid or above ask). The default
         logic would mis-classify (last < bid -> BID even though the
         active institutional trade likely lifted offers). When this
         happens on a high-notional deep-ITM contract, default to ASK
         (institutional buying is the dominant case). The GLD 6/18 $380C
         on 5/12 was the prototype: bid=$54.20, ask=$54.90, last=$54.05,
         FL0WG0D confirmed bullish call buying, our scanner read BEARISH.
    """
    if bid <= 0 and ask <= 0:
        return "MID"
    mid = (bid + ask) / 2
    spread = ask - bid if ask > bid else 0.01

    # Stale-last detection — gate (4) above
    if (last > 0 and bid > 0 and ask > 0
            and (last < bid or last > ask)):
        # Snapshot is provably stale. Apply directional bias by
        # underlying-likely-intent if the contract is institutionally-
        # sized + directional-by-structure; else return MID rather than
        # confidently mis-classify.
        adel = abs(delta or 0.0)
        if notional >= 5_000_000 and adel >= 0.70:
            # Deep-ITM heavy notional with stale last: institutional buy
            # is the dominant pattern (small offsetting prints below the
            # bid are the residual that staled the `last`).
            return "ASK"
        return "MID"

    dist = abs(last - mid) / spread
    if dist < 0.15:
        # Last sits near mid — apply directional bias for contracts where
        # mid-price prints are statistically rare (deep ITM, cheap far OTM
        # with V/OI shock). Otherwise return MID.
        adel = abs(delta or 0.0)
        if adel >= 0.70 and oi > 0 and vol >= oi:
            # Deep ITM with opening accumulation — institutional buy bias.
            return "ASK"
        if adel <= 0.15 and oi > 0 and (vol / max(oi, 1)) >= 5.0:
            # Cheap far-OTM with V/OI shock — insider lotto bias.
            return "ASK"
        # P0 fix (Bug #12 part 1, 2026-05-13 PM): near-mid + V/OI shock
        # falls through to mid-distance directional read. HPE 5/15 $30.5C
        # today had vol=3,029 / oi=18 = 168x V/OI with last sitting at mid.
        # Pre-fix returned MID (no signal). Post-fix uses tiny directional
        # tiebreak based on bid/ask proximity since institutional V/OI
        # shock at mid almost never prints randomly — it's the snapshot
        # catching a moment between buy waves.
        vol_oi_now = vol / max(oi, 1) if oi > 0 else 999.0

        # P0 fix Bug #12 part 2 (2026-05-27, META 0DTE 620C):
        # opening accumulation (vol > oi) at V/OI >= 10x is virtually
        # always buyer-initiated regardless of where `last` sits in the
        # spread. Override the last-vs-mid coin flip with the opening
        # signal — closing rolls don't need 10x volume on stale OI.
        # Without this, META 620C 0DTE 14:11 with last=$1.69 in
        # [$1.61, $1.81] (just below mid $1.71) returned BID/BEARISH on
        # what was the textbook insider call buy (151× peak the same hour).
        if vol_oi_now >= 10.0 and vol > oi:
            return "ASK"

        if vol_oi_now >= 5.0 and last > 0:
            # Use micro-distance from mid as direction proxy
            if last >= mid:
                return "ASK"
            return "BID"
        return "MID"

    # P0 fix (Bug #12, 2026-05-13 PM): MID-of-spread aggression bias.
    # When `last` sits between mid and one extreme of the spread AND
    # V/OI shows accumulation shock (>=1.5x), lean toward that extreme
    # rather than the existing "ASK if last>=mid else BID" coin-flip.
    #
    # The FL0WG0D audit (39% hit rate) flagged this as the single biggest
    # source of wrong-side classifications. Concrete miss today:
    # HPE 5/15 $30.5C — vol=3,029 on oi=18 = 168x V/OI shock, last=$0.95.
    # Theta tape confirms 1,497 contracts ISO-swept at $0.80 across 3
    # exchanges in 1ms = clearly ASK side. Pre-fix returned MID/BID/BEARISH
    # because last drifted slightly below mid. With V/OI=168x and notional
    # crossing the high-conviction floor, this fix returns ASK confidently.
    #
    # Two-sided so the symmetric BID-side aggression is also captured
    # (institutional put-buying / call-selling on the bid side).
    vol_oi = vol / max(oi, 1) if oi > 0 else 999.0

    # Extreme V/OI shock layer (2026-05-20 PM): the 1.5x quarter-spread tier
    # still coin-flips when last sits in the middle 50% of the spread. ABNB
    # 137C 6/12 today: vol_oi=552.8 (!!), 2,211 contracts, but last drifted
    # slightly below mid -> tagged BID/BEARISH via line 487 fallback. Bullflow
    # and Flowseeker both read this as 95% ASK/BULLISH. At 25x+ V/OI the
    # accumulation is so aggressive that mid-of-spread prints are statistical
    # noise — institutional buyers are actively lifting offers across the
    # tape, not patient-resting at mid. Tighten the aggression bands from
    # 0.25*spread to 0.10*spread for this regime.
    if spread > 0 and vol_oi >= 25.0 and last > 0:
        if last >= mid + spread * 0.10:
            return "ASK"
        if last <= mid - spread * 0.10:
            return "BID"
        # last is within ±10% of mid AND V/OI >= 25x. Historical base rate:
        # extreme V/OI shocks with no clear bid/ask preference are 70%+
        # aggressive opens (institutional accumulation). Lean ASK rather
        # than coin-flip via line 491 fallback. _detect_sentiment then
        # interprets call+ASK = bullish, put+ASK = bearish — both correct
        # priors for V/OI shock signature.
        return "ASK"

    # OPENING-ACCUMULATION ASK bias (2026-05-27 P0 fix — META 0DTE 620C bug).
    #
    # 3rd confirmation today of the mid-of-spread coin-flip: META 620C 0DTE
    # at 14:11:08 — vol=39,435 oi=3,096 (V/OI 12.7x) with bid=$1.61 ask=$1.81.
    # Last drifted to ~$1.69 (slightly below mid $1.71), so the line ~511
    # `last >= mid else BID` fallback tagged BID -> BEARISH on a CALL. The
    # 25x extreme-layer threshold above didn't trigger (V/OI only 12.7).
    # META then ran +3% on the paid-subscriptions news 5 min later and the
    # 615C 0DTE went $0.14 -> $21.15 (151x). Mis-classifying that as BEARISH
    # is exactly the insider catch we're paying ThetaData for.
    #
    # Rule: when V/OI >= 10x AND vol > oi (clear opening, not roll), the
    # statistical prior is OVERWHELMINGLY buyer-initiated. Closers don't
    # need to flood 10x daily volume; openers (insiders, institutionals
    # front-running a catalyst) do. Set ASK as default unless last is
    # convincingly below bid (stale-last path already handled it earlier).
    #
    # Prior fixes covered V/OI >= 25 + last-vs-spread heuristics. This
    # widens the V/OI floor to 10 AND adds the opening-confirmation gate
    # (vol > oi) so we don't false-positive on closing flow.
    if vol_oi >= 10.0 and vol > oi and last > 0:
        # Even with last slightly below mid, opening accumulation at 10x+
        # V/OI is virtually always buyer-initiated. Only override when
        # last is materially below bid (stale handled earlier) — at this
        # point in the function `last` is within [bid, ask] by construction.
        # Hold the ASK bias unless last is in the bottom 25% of the spread,
        # which would indicate seller-initiated even on opening (rare —
        # would require a large institution OPENING shorts at the bid).
        if spread > 0 and last <= bid + spread * 0.25:
            # Bottom quartile of spread on opening accumulation. Rare but
            # real (call writes ahead of resistance). Defer to the existing
            # last-vs-mid fallback below.
            pass
        else:
            return "ASK"

    if spread > 0 and vol_oi >= 1.5:
        # Quarter-spread aggression line: above mid + spread*0.25 is "lean ask"
        if last >= mid + spread * 0.25:
            return "ASK"
        if last <= mid - spread * 0.25:
            return "BID"

    return "ASK" if last >= mid else "BID"


def _detect_sentiment(option_type: str, side: str) -> str:
    if side == "MID":
        return "NEUTRAL"
    if option_type == "call":
        return "BULLISH" if side == "ASK" else "BEARISH"
    return "BEARISH" if side == "ASK" else "BULLISH"


async def _send_telegram(alert: dict[str, Any]) -> None:
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return
    # P0.7: hydrate the earnings cache for this ticker before formatting so
    # the badge can append synchronously inside format_flow_alert. The
    # earnings_calendar module caches for 24h so this is a no-op most of
    # the time.
    try:
        from .earnings_calendar import get_next_er
        await get_next_er(alert.get("ticker", ""))
    except Exception:
        pass
    emoji = (
        "🟢" if alert["sentiment"] == "BULLISH"
        else "🔴" if alert["sentiment"] == "BEARISH"
        else "🟡"
    )
    otype = alert["option_type"].upper()

    # Whale-override alerts get a distinct header so you can spot them
    # at a glance vs. standard HIGH (notional-driven) flow. Tier letter
    # (A/B/C) corresponds to which override rule fired — see
    # _compute_conviction for the rule definitions.
    whale_tier = alert.get("_whale_override")
    if whale_tier:
        header = f"🐋 {emoji} WHALE FLOW [{whale_tier}]: {alert['ticker']}\n"
    else:
        header = f"{emoji} FLOW ALERT: {alert['ticker']}\n"

    text = (
        header
        + f"${alert['strike']} {otype} {alert['expiration']}\n"
        + f"Vol: {alert['volume']:,} | OI: {alert['oi']:,} | {alert['vol_oi']}x\n"
        + f"Side: {alert['side']} | {alert['sentiment']}\n"
        + f"Last: ${alert['last']:.2f} | Notional: ${alert['notional']:,.0f}\n"
        + f"IV: {alert['iv']}% | Delta: {alert['delta']} | Spot: ${alert['spot']:.2f}"
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                json={"chat_id": s.telegram_chat_id, "text": text},
                timeout=10,
            )
    except Exception as e:
        print(f"[TELEGRAM] send failed: {e}")


async def _scan_flow_from_cache(vol_oi_threshold: float = 3.0) -> list[dict[str, Any]]:
    """Scan ALL cached tickers for unusual flow using data the GEX worker
    already fetched. ZERO additional API calls.

    Covers 300+ tickers across mega/large/mid cap — including names like
    DOCN, SOFI, RIVN, MARA that wouldn't be caught by a tier-1-only scan.
    """
    import datetime

    # 2026-05-25: holiday-aware gate. Memorial Day produced 93K stale
    # alerts because the prior weekend-only gate let Monday-holiday scans
    # re-fire Friday-close V/OI data. Module-level import (see top of file).
    if not is_rth_or_extended():
        return []

    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Read the worker's chain cache — this has raw per-option data
    from .worker import _chain_cache

    snapshot = await cache.snapshot()
    new_alerts: list[dict[str, Any]] = []

    for cache_key, (ts, contracts) in list(_chain_cache.items()):
        ticker = cache_key.split(":")[0]
        exp_date = cache_key.split(":", 1)[1] if ":" in cache_key else ""

        # 0DTE alerts stay ON all day — tradeable until market close on most brokers

        spot = 0
        state = snapshot.get(ticker)
        if state:
            spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot:
            continue

        # P2 (5/13): if this ticker is currently hot (had a $1M+ alert in
        # the last 30 min), lower the gates so adjacent strikes riding the
        # same whale wave clear the threshold. Reads from hot_chain module
        # once per ticker, not per contract.
        try:
            from .hot_chain import (
                is_hot,
                HOT_VOL_FLOOR,
                HOT_NOTIONAL_FLOOR_LOW,
                HOT_NOTIONAL_FLOOR_HIGH,
            )
            _ticker_hot = is_hot(ticker)
        except Exception:
            _ticker_hot = False
            HOT_VOL_FLOOR = 100
            HOT_NOTIONAL_FLOOR_LOW = 500_000
            HOT_NOTIONAL_FLOOR_HIGH = 1_000_000

        # Default gates (post-5/12 Bug #5 fix): vol>=200, vol<500 needs
        # est_notional >= $1M, V/OI fallback path needs >= $2M.
        # Hot-ticker gates: vol>=100, vol<500 needs >=$500K, V/OI fallback
        # path needs >=$1M.
        vol_floor = HOT_VOL_FLOOR if _ticker_hot else 200
        notional_floor_low = HOT_NOTIONAL_FLOOR_LOW if _ticker_hot else 1_000_000
        notional_floor_high = HOT_NOTIONAL_FLOOR_HIGH if _ticker_hot else 2_000_000
        # Fix C (5/19): lower V/OI threshold for hot tickers from 3.0 -> 2.0.
        # Matches the existing "V/OI >= 2.0 + $1M" side-channel — consistent
        # whale-signature floor. Catches ARM 280C-style trades (V/OI 1.77
        # with $545K premium) that UW flagged today but we missed.
        effective_vol_oi_threshold = 2.0 if _ticker_hot else vol_oi_threshold

        for opt in contracts:
            vol = int(opt.get("volume") or 0)
            oi = int(opt.get("open_interest") or 0)
            est_notional_pre = vol * (float(opt.get("last") or 0)) * 100

            # Fix B (5/19): LOW-VOL WHALE BYPASS. Two patterns:
            #   1. OI=0 fresh-strike whale: insider opens a strike no one
            #      has touched (SNDK 1375P 6/18 today: vol=14, OI=0, $155K)
            #   2. OI<=5 ratio-extreme whale: insider enters on a stale,
            #      barely-positioned strike (STX 755C: vol=40, OI=3, $174K;
            #      MU 727.5C: vol=77, OI=2, $460K — both today)
            # Both bypass the vol_floor + notional_floor_low gates ONLY;
            # downstream IV, delta, dedup, and sentiment checks still apply.
            # Bar: notional >= $150K to ensure it's not penny-options noise.
            fresh_strike_whale = (
                (oi == 0 and vol >= 10 and est_notional_pre >= 150_000)
                or
                (0 < oi <= 5 and vol >= 10 and est_notional_pre >= 150_000)
            )

            # Volume floor: 500 contracts for normal contracts, 200 for
            # high-notional/V-O-I-rich ones. Bumped 2026-05-12 after missing
            # MU 9/18 $1030C ($2.5M notional, vol=307) — the trade had real
            # institutional fingerprints (sweep, V/OI 2.6) but was under the
            # 500-vol floor. Two-stage check preserves noise filter for
            # cheap-name nonsense while opening the door to small-vol whale
            # prints on expensive contracts. Hot-ticker mode lowers further.
            if not fresh_strike_whale:
                if vol < vol_floor:
                    continue
                if vol < 500 and est_notional_pre < notional_floor_low:
                    continue
            # OI=0 is legitimate for strikes that carried over with no settled
            # OI from the prior session — and is precisely where insider plays
            # often appear (fresh strike, no public position, then a single
            # whale prints). Treat OI=0 with meaningful vol as effectively
            # infinite V/OI so it can clear the threshold check below.
            # (Missed SPY 727P 5/7/26 +350% trade: vol=70,903 / oi=0 was
            # silently skipped here all day.)
            vol_oi = round(vol / oi, 1) if oi >= 1 else 999.0
            # Three paths to qualify:
            # 1. High V/OI ratio (unusual relative to open interest)
            # 2. Big notional ($2M+) — bumped down 5/12 from $5M to catch
            #    MU 9/18 $1030C-class trades ($2.5M / V/OI 2.6 / vol 307)
            # 3. Mid-V/OI ($1M+) — V/OI >=2.0 with $1M+ notional captures
            #    real whale prints that don't quite reach the strict gate
            est_notional = vol * (float(opt.get("last") or 0)) * 100
            # notional_floor_high: $2M default, $1M when hot (P2 5/13).
            # The V/OI >= 2.0 + $1M side-channel is unchanged — it's already
            # the most generous path for whale prints with mid-vol.
            # effective_vol_oi_threshold: 3.0 default, 2.0 when hot (Fix C 5/19).
            # Fresh-strike whales (OI=0) auto-pass this gate because
            # vol_oi=999 always clears any threshold.
            if (vol_oi < effective_vol_oi_threshold
                    and est_notional < notional_floor_high
                    and not (vol_oi >= 2.0 and est_notional >= 1_000_000)):
                continue

            strike = opt.get("strike", 0)
            otype = (opt.get("option_type") or "").lower()
            opt_exp = opt.get("expiration_date") or exp_date

            bid = float(opt.get("bid") or 0)
            ask = float(opt.get("ask") or 0)
            last = float(opt.get("last") or 0)
            greeks = opt.get("greeks") or {}
            iv = float(greeks.get("mid_iv") or greeks.get("smv_vol") or 0)
            delta = float(greeks.get("delta") or 0)

            # Prefer the tick-level 60s rolling ASK/BID tracker (fed by the
            # OPRA stream in sweep_detector). Returns None when the contract
            # has <50 contracts in the window — fall back to the snapshot
            # detector so illiquid strikes don't lose alerts during rollout.
            # Plan: audit fallback_rate after one week of dual-running.
            side = _get_tick_side_tracker().latest_side(
                ticker, strike, opt_exp, otype,
            )
            if side is None:
                # Pass delta/vol/oi/notional so the snapshot fallback can
                # apply directional bias on deep-ITM, V/OI-shock, and
                # stale-last contracts (Bug #2 layered fix 2026-05-12).
                est_notional = vol * last * 100 if last > 0 else 0
                side = _detect_side(
                    bid, ask, last,
                    delta=delta, vol=vol, oi=oi, notional=est_notional,
                )
            sentiment = _detect_sentiment(otype, side)
            notional = vol * last * 100

            # Dedup AFTER sentiment computed so the bucket is part of the
            # key — catches the flip-day case (BEARISH on 5/15 120C at
            # 10:16 AM, then BULLISH at 11:30 AM = re-fire).
            now = time.time()
            dkey = _dedup_key(ticker, strike, opt_exp, otype, sentiment)
            if _should_skip_dedup(dkey, now):
                continue
            _seen[dkey] = now

            # Noise filters
            if notional < 250_000:
                continue
            # Deep-ITM exception (P0.5 / Bug #7 fix, 2026-05-12).
            # Pre-fix: `abs(delta) > 0.95` always continued — assuming deep
            # ITM = wide-spread noise. But TGT 5/15 $45C ($75 ITM on $120
            # spot) printed 100 trades at $2.77M each in 7 seconds today =
            # synthetic-stock accumulation. Fidget flagged it as the day's
            # #1 TGT signal; we filtered it out. Allow ITM-equity-substitute
            # trades through IF notional and vol both meet institutional
            # thresholds (>= $1M and >= 100 vol). Otherwise still cull as
            # the original wide-spread noise.
            if abs(delta) > 0.95:
                if not (notional >= 1_000_000 and vol >= 100):
                    continue
            if iv > 2.0:
                continue

            alert = {
                "ticker": ticker,
                "strike": strike,
                "expiration": opt_exp,
                "option_type": otype,
                "volume": vol,
                "oi": oi,
                "vol_oi": round(vol_oi, 1),
                "last": last,
                "bid": bid,
                "ask": ask,
                "side": side,
                "sentiment": sentiment,
                "iv": round(iv * 100, 1),
                "delta": round(delta, 3),
                "notional": round(notional),
                "spot": spot,
            }
            gex_info = {
                "king": state.get("king") if state else None,
                "floor": state.get("floor") if state else None,
                "ceiling": state.get("ceiling") if state else None,
                "regime": state.get("regime") if state else None,
                "signal": state.get("signal") if state else None,
            }
            insert_alert(alert, gex_info)
            new_alerts.append(alert)

            # P2 (5/13): mark ticker hot if this alert's notional clears
            # $1M. Lowers gates + bumps max_exp on this ticker's next scan
            # cycle. Defense-in-depth for adjacent strikes riding the
            # same whale wave.
            try:
                from .hot_chain import mark_hot
                mark_hot(ticker, notional)
            except Exception:
                pass

            # Auto-track for exit signals — HIGH conviction tier only.
            # Prior behavior auto-tracked every alert (~2,000/cycle) which
            # blew up tracked_trades to 448,575 active rows on 2026-05-26,
            # freezing the asyncio event loop in the 30s tracker scan
            # (root cause of the post-Memorial-Day backend freezes).
            # Filter: only SWEEP and HIGH tiers get auto-tracked. LOW/MEDIUM
            # alerts are still inserted to flow_alerts table (insert_alert
            # above), just not added to the active exit-tracking queue.
            #
            # 2026-06-02: Index ETFs (SPY/SPX/QQQ/IWM/NDX/DIA/VIX) were
            # dominating HIGH conviction because their base volume + notional
            # auto-clears the score >= 5 threshold even on routine MM
            # hedging. ~1,200/day of these were polluting tracker — only ~7%
            # were genuine INFORMED FLOW. Exclude them from tracker creation
            # unless explicitly insider-tagged.
            _INDEX_TICKERS = {
                "SPY", "SPX", "SPXW", "QQQ", "IWM", "DIA", "VIX", "NDX",
            }
            conviction = (alert.get("conviction") or "").upper()
            if conviction in ("HIGH", "SWEEP"):
                is_index = ticker in _INDEX_TICKERS
                is_insider = bool(alert.get("is_insider"))
                if is_index and not is_insider:
                    pass  # skip routine index MM flow
                else:
                    try:
                        from .trade_tracker import create_trade
                        create_trade(alert, gex_info)
                    except Exception:
                        pass

    return new_alerts


async def run_flow_scanner(stop_event: asyncio.Event) -> None:
    """Background loop scanning cached data every 30 seconds.
    Zero API calls — uses the GEX worker's chain cache.

    Telegram emission is gated through ``flow_alert_filter`` (env-var
    ``FLOW_ALERT_FILTER_LEVEL`` = OFF | LIGHT | FULL). The legacy hard-coded
    gates (HIGH-only, $5M, OTM≥1%, max 2 per cycle) only run when level=OFF
    so the old behavior remains available as a fallback.
    """
    # Wait a bit for the first GEX cycle to populate the cache
    await asyncio.sleep(30)
    from .flow_alert_filter import (
        get_filter, _active_level,
        format_cluster_summary, format_hot_flow_summary,
    )
    while not stop_event.is_set():
        try:
            alerts = await _scan_flow_from_cache()
            level = _active_level()
            if alerts:
                tickers_hit = list(set(a["ticker"] for a in alerts))
                print(
                    f"[FLOW] {len(alerts)} new alerts: "
                    f"{', '.join(tickers_hit[:10])}"
                )
                from .telegram import send, format_flow_alert

                if level == "OFF":
                    # Legacy gate: HIGH/$5M/OTM/max 2 per cycle
                    for a in alerts[:2]:
                        if a.get("conviction") != "HIGH":
                            continue
                        if a.get("side") == "MID":
                            continue
                        if (a.get("notional", 0) or 0) < 5_000_000:
                            continue
                        strike = a.get("strike", 0) or 0
                        spot = a.get("spot", 0) or 0
                        if strike and spot:
                            is_call = (a.get("option_type") or "").lower() == "call"
                            otm_pct = (
                                ((strike - spot) / spot * 100)
                                if is_call
                                else ((spot - strike) / spot * 100)
                            )
                            if otm_pct < 1.0:
                                continue
                        await send(
                            format_flow_alert(a),
                            ticker=a.get("ticker", ""),
                            priority=bool(a.get("is_insider")),
                            force=bool(a.get("is_insider")),
                        )
                        # Cluster check on the OFF/legacy path too
                        if a.get("is_insider"):
                            try:
                                from .informed_cluster import (
                                    record_and_check, format_cluster_telegram,
                                    MIN_CLUSTER_TELEGRAM_STRIKES,
                                )
                                cluster = record_and_check(a)
                                if cluster and cluster["n_strikes"] >= MIN_CLUSTER_TELEGRAM_STRIKES:
                                    await send(
                                        format_cluster_telegram(cluster),
                                        ticker=cluster["ticker"],
                                        priority=True, force=True,
                                    )
                            except Exception as ce:
                                print(f"[INFORMED_CLUSTER] error: {ce!r}", flush=True)
                else:
                    # New 4-rule filter (LIGHT or FULL)
                    f = get_filter()
                    fired_singles = 0
                    fired_summaries = 0
                    for a in alerts:
                        for decision, payload in f.process(a):
                            if decision == "FIRE":
                                # Weak-signal mute (added 2026-05-20).
                                # 5/19 backtest showed FLOW [MEDIUM] alerts
                                # with V/OI < 1.0 AND notional < $10M (the
                                # "existing OI dominates" tier) were 1/3
                                # directionally right — the format itself
                                # tags them "weak signal", so don't ping
                                # Telegram for what we've already labeled
                                # weak. Fresh strikes (OI=0, V/OI=999) and
                                # whale prints ($10M+) still go through.
                                _vol_oi = payload.get("vol_oi", 0) or 0
                                _notional = payload.get("notional", 0) or 0
                                _is_weak = _vol_oi < 1.0 and _notional < 10_000_000
                                if _is_weak and not payload.get("is_insider"):
                                    # weak alerts dropped — UNLESS INSIDER flag
                                    # is set, in which case the 6-criteria
                                    # match overrides the V/OI < 1 mute.
                                    continue
                                await send(
                                    format_flow_alert(payload),
                                    ticker=payload.get("ticker", ""),
                                    priority=bool(payload.get("is_insider")),
                                    force=bool(payload.get("is_insider")),
                                )
                                fired_singles += 1
                                # INFORMED CLUSTER detector (Batch 2, 2026-05-27).
                                # When 2+ strikes on same (ticker, exp, direction)
                                # have fired INFORMED FLOW within 30 min, emit a
                                # CLUSTER summary alert at higher priority. This
                                # is the unanimous 4/4 LLM recommendation — pattern
                                # matches Panuwat (3 strikes 70-84% of daily vol)
                                # + META 5/27 ladder (615/617.5/620C 0DTE).
                                if payload.get("is_insider"):
                                    try:
                                        from .informed_cluster import (
                                            record_and_check,
                                            format_cluster_telegram,
                                            MIN_CLUSTER_TELEGRAM_STRIKES,
                                        )
                                        cluster = record_and_check(payload)
                                        # Backtest finding 2026-05-27 PM:
                                        # 2-strike clusters are coin-flip
                                        # (49.5% WR); 3+ are the signal tier
                                        # (4-strike: 89%, 5-strike: 80%).
                                        # Persist 2-strike for audit but
                                        # only fire Telegram for 3+.
                                        if cluster and cluster["n_strikes"] >= MIN_CLUSTER_TELEGRAM_STRIKES:
                                            await send(
                                                format_cluster_telegram(cluster),
                                                ticker=cluster["ticker"],
                                                priority=True,
                                                force=True,
                                            )
                                    except Exception as ce:
                                        print(f"[INFORMED_CLUSTER] error: {ce!r}", flush=True)
                                # Performance database log (2026-05-20)
                                try:
                                    from .alert_outcomes import log_alert
                                    _side = payload.get("side", "")
                                    _otype = (payload.get("option_type") or "").lower()
                                    _is_bull_flow = (
                                        (_side == "ASK" and _otype == "call")
                                        or (_side == "BID" and _otype == "put")
                                    )
                                    log_alert(
                                        alert_type="FLOW_MEDIUM",
                                        ticker=payload.get("ticker", ""),
                                        direction="BULL" if _is_bull_flow else "BEAR",
                                        score=_vol_oi,
                                        strike=payload.get("strike"),
                                        expiration=payload.get("expiration"),
                                        option_type=_otype,
                                        spot_at_alert=payload.get("spot"),
                                        entry_price=payload.get("last"),
                                        gex_regime=None,  # not in flow alert payload
                                        raw_alert=payload,
                                    )
                                except Exception:
                                    pass
                            elif decision == "FIRE_SUMMARY":
                                if payload.get("kind") == "CLUSTER":
                                    text = format_cluster_summary(payload)
                                elif payload.get("kind") == "CLUSTER_RESOLUTION":
                                    from .cluster_resolution import format_resolution_telegram
                                    text = format_resolution_telegram(payload)
                                else:
                                    text = format_hot_flow_summary(payload)
                                await send(text, ticker=payload.get("ticker", ""))
                                fired_summaries += 1
                                # Performance database log (2026-05-20)
                                try:
                                    from .alert_outcomes import log_alert
                                    bias = payload.get("bias", "")
                                    log_alert(
                                        alert_type=(f"CLUSTER_{bias.replace('-','_')}"
                                                    if payload.get("kind") == "CLUSTER"
                                                    else "HOT_FLOW"),
                                        ticker=payload.get("ticker", ""),
                                        direction=("BULL" if "BULL" in bias
                                                  else "BEAR" if "BEAR" in bias
                                                  else "NEUTRAL"),
                                        spot_at_alert=payload.get("spot"),
                                        raw_alert={"bias": bias,
                                                   "notional": payload.get("total_notional"),
                                                   "legs": payload.get("legs")},
                                    )
                                except Exception:
                                    pass
                    if fired_singles or fired_summaries:
                        print(
                            f"[FLOW][{level}] fired {fired_singles} single + "
                            f"{fired_summaries} summary"
                        )

            # Always flush expired cluster windows + hour buckets every cycle
            if level != "OFF":
                f = get_filter()
                for decision, payload in f.flush():
                    if decision == "FIRE":
                        # Same weak-signal mute as the process loop above.
                        _vol_oi = payload.get("vol_oi", 0) or 0
                        _notional = payload.get("notional", 0) or 0
                        _is_weak = _vol_oi < 1.0 and _notional < 10_000_000
                        if _is_weak and not payload.get("is_insider"):
                            continue
                        await send(
                            format_flow_alert(payload),
                            ticker=payload.get("ticker", ""),
                            priority=bool(payload.get("is_insider")),
                            force=bool(payload.get("is_insider")),
                        )
                        # Cluster check on flush path
                        if payload.get("is_insider"):
                            try:
                                from .informed_cluster import (
                                    record_and_check, format_cluster_telegram,
                                    MIN_CLUSTER_TELEGRAM_STRIKES,
                                )
                                cluster = record_and_check(payload)
                                if cluster and cluster["n_strikes"] >= MIN_CLUSTER_TELEGRAM_STRIKES:
                                    await send(
                                        format_cluster_telegram(cluster),
                                        ticker=cluster["ticker"],
                                        priority=True, force=True,
                                    )
                            except Exception as ce:
                                print(f"[INFORMED_CLUSTER] error: {ce!r}", flush=True)
                    elif decision == "FIRE_SUMMARY":
                        if payload.get("kind") == "CLUSTER":
                            text = format_cluster_summary(payload)
                        elif payload.get("kind") == "CLUSTER_RESOLUTION":
                            # CLUSTER_RESOLUTION lacks `hour_start`; route to
                            # its own formatter. Missing branch here caused
                            # `[FLOW] scan error: 'hour_start'` KeyError
                            # observed 2026-05-26.
                            from .cluster_resolution import format_resolution_telegram
                            text = format_resolution_telegram(payload)
                        else:
                            text = format_hot_flow_summary(payload)
                        await send(text, ticker=payload.get("ticker", ""))
        except Exception as e:
            print(f"[FLOW] scan error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
