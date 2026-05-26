"""Net-flow divergence and stall detection — Price-to-Premium Gap signals.

Consumes the time-series produced by NetFlowAggregator (see
server/net_flow.py) and emits trader-facing signals when:

  FLOW_LEADS_UP:   NCP rising faster than price (bullish flow leads)
  FLOW_LEADS_DOWN: NPP rising faster than price falling (bearish flow leads)
  GAP_CLOSED:      price has caught up to leading premium — stall watch
  DOUBLE_STALL:    both price and dominant premium have flatlined
  BEARISH_DIVERGENCE: price rising but NCP declining (warning: bull losing steam)
  BULLISH_DIVERGENCE: price falling but NPP declining (warning: bear losing steam)

## Methodology

Rate-of-change (ROC) computed over a sliding window (default 10 min).
Premium ROC normalized to $/min; price ROC in %/min. They're on different
units, so divergence is measured by SIGN-COMPARISON and RELATIVE MAGNITUDE
using percentile ranks within the last 4h.

Stall = absolute ROC below 25th percentile of last 60 min for >= 5 consecutive
minutes. This captures "flattening" without needing a hard threshold (which
would vary per-ticker based on typical flow volume).

## API

  detect_signals(bars) -> list[SignalHit]

Callable from the /api/net-flow endpoint or a periodic scan. Stateless —
each call computes fresh over the supplied bars.

Shipped: 2026-04-21 (overnight session, v1 MVP).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Configuration ─────────────────────────────────────────────────

# Window (minutes) for rate-of-change calculation.
ROC_WINDOW_MIN = 10

# How many minutes of "stall" (low ROC) before firing a stall signal.
STALL_CONFIRM_MIN = 5

# Percentile threshold for "low ROC" = stalling.
STALL_PERCENTILE = 0.25

# Lookback window for percentile ranking (baseline comparison).
PERCENTILE_WINDOW_MIN = 60

# Minimum price change (in %) to consider "price moved" for divergence.
MIN_PRICE_MOVE_PCT = 0.1

# Minimum premium change (in $) to consider "premium moved."
# Ticker-specific — for SPY this is ~$1M, for small-caps much less.
# Default to $100K; tune per ticker later.
MIN_PREMIUM_MOVE_DOLLARS = 100_000


# ── Data structures ───────────────────────────────────────────────


@dataclass
class SignalHit:
    """One signal detected at a specific bar."""
    signal: str          # 'FLOW_LEADS_UP', etc.
    bar_t: int           # epoch seconds of the bar where signal fired
    bar_t_iso: str       # ISO timestamp
    price: float | None  # price at signal bar
    ncp: float           # NCP at signal bar
    npp: float           # NPP at signal bar
    # Supporting metrics (for UI display / debugging)
    price_roc_pct: float        # %/window
    ncp_roc_dollars: float      # $/window
    npp_roc_dollars: float      # $/window
    gap_direction: str          # 'bullish' | 'bearish' | 'neutral'
    confidence: str             # 'high' | 'medium' | 'low'
    # Human-readable description
    description: str = ''

    def to_row(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "bar_t": self.bar_t,
            "bar_t_iso": self.bar_t_iso,
            "price": self.price,
            "ncp": round(self.ncp, 2),
            "npp": round(self.npp, 2),
            "price_roc_pct": round(self.price_roc_pct, 3),
            "ncp_roc_dollars": round(self.ncp_roc_dollars, 2),
            "npp_roc_dollars": round(self.npp_roc_dollars, 2),
            "gap_direction": self.gap_direction,
            "confidence": self.confidence,
            "description": self.description,
        }


# ── Core math ─────────────────────────────────────────────────────


def _pct_change(newer: float | None, older: float | None) -> float:
    """Percent change from older → newer. 0.0 if either is None/zero."""
    if newer is None or older is None or older == 0:
        return 0.0
    return (newer - older) / older * 100.0


def _dollar_change(newer: float, older: float) -> float:
    """Absolute change newer - older."""
    return newer - older


def _rolling_roc(bars: list[dict[str, Any]], field_key: str, window: int) -> list[float]:
    """Compute rolling ROC (over `window` bars) for a numeric field.

    For 'price' → pct change, for everything else → dollar change. Output
    has same length as bars with zero-padding for the first `window` entries.
    """
    rocs: list[float] = []
    for i, b in enumerate(bars):
        if i < window:
            rocs.append(0.0)
            continue
        older = bars[i - window].get(field_key)
        newer = b.get(field_key)
        if field_key == "price":
            rocs.append(_pct_change(newer, older))
        else:
            rocs.append(_dollar_change(newer or 0.0, older or 0.0))
    return rocs


def _percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (0-1) of a list of floats. Robust to
    ties and empty lists."""
    vals = sorted(abs(v) for v in values if v is not None)
    if not vals:
        return 0.0
    idx = int(p * (len(vals) - 1))
    return vals[idx]


def _is_stalled(roc_series: list[float], confirm_min: int, percentile_threshold: float) -> bool:
    """True if the last `confirm_min` values are all below the percentile
    threshold (in absolute value)."""
    if len(roc_series) < confirm_min:
        return False
    recent = roc_series[-confirm_min:]
    return all(abs(r) <= percentile_threshold for r in recent)


# ── Signal detectors ──────────────────────────────────────────────


def detect_signals(
    bars: list[dict[str, Any]],
    window: int = ROC_WINDOW_MIN,
) -> list[SignalHit]:
    """Run all signal detectors over the bar series and return hits.

    Only checks the MOST RECENT state — we don't look back and emit
    signals for historical bars. The caller (endpoint or scanner) gets
    the current regime classification.

    Returns empty list if we have insufficient data (need at least
    2 × window bars for reliable ROC + baseline).
    """
    if len(bars) < 2 * window:
        return []

    price_roc = _rolling_roc(bars, "price", window)
    ncp_roc = _rolling_roc(bars, "ncp", window)
    npp_roc = _rolling_roc(bars, "npp", window)

    # Baseline percentiles from last PERCENTILE_WINDOW_MIN minutes
    baseline_start = max(0, len(bars) - PERCENTILE_WINDOW_MIN)
    price_baseline = price_roc[baseline_start:]
    ncp_baseline = ncp_roc[baseline_start:]
    npp_baseline = npp_roc[baseline_start:]

    price_stall_thresh = _percentile(price_baseline, STALL_PERCENTILE)
    ncp_stall_thresh = _percentile(ncp_baseline, STALL_PERCENTILE)
    npp_stall_thresh = _percentile(npp_baseline, STALL_PERCENTILE)

    latest = bars[-1]
    pr = price_roc[-1]
    nr = ncp_roc[-1]
    pnr = npp_roc[-1]

    signals: list[SignalHit] = []

    def mk(
        name: str, desc: str, gap_dir: str, confidence: str
    ) -> SignalHit:
        return SignalHit(
            signal=name,
            bar_t=latest.get("t", 0),
            bar_t_iso=latest.get("t_iso", ""),
            price=latest.get("price"),
            ncp=latest.get("ncp", 0.0),
            npp=latest.get("npp", 0.0),
            price_roc_pct=pr,
            ncp_roc_dollars=nr,
            npp_roc_dollars=pnr,
            gap_direction=gap_dir,
            confidence=confidence,
            description=desc,
        )

    # ── FLOW_LEADS_UP: NCP rising strongly while price flat or slower rising
    # Condition: NCP_ROC significantly positive AND (price flat or rising slower)
    if nr > MIN_PREMIUM_MOVE_DOLLARS and abs(pr) < MIN_PRICE_MOVE_PCT:
        signals.append(mk(
            "FLOW_LEADS_UP",
            f"Net call premium up {nr/1e6:+.2f}M over {window}min while price {'+' if pr >= 0 else ''}{pr:.2f}% — bullish flow leads",
            "bullish",
            "high" if nr > 5 * MIN_PREMIUM_MOVE_DOLLARS else "medium",
        ))

    # ── FLOW_LEADS_DOWN: NPP rising strongly while price flat or slower falling
    if pnr > MIN_PREMIUM_MOVE_DOLLARS and abs(pr) < MIN_PRICE_MOVE_PCT:
        signals.append(mk(
            "FLOW_LEADS_DOWN",
            f"Net put premium up {pnr/1e6:+.2f}M over {window}min while price {'+' if pr >= 0 else ''}{pr:.2f}% — bearish flow leads",
            "bearish",
            "high" if pnr > 5 * MIN_PREMIUM_MOVE_DOLLARS else "medium",
        ))

    # ── GAP_CLOSED: price catching up / caught up to premium
    # Heuristic: premium was rising strongly in recent past but NOW both are
    # aligning. We check that the ROC DIFFERENCE narrowed between now and N/2
    # bars ago.
    half = window // 2
    if len(bars) >= window + half and abs(nr) > MIN_PREMIUM_MOVE_DOLLARS:
        prev_pr = price_roc[-1 - half]
        prev_nr = ncp_roc[-1 - half]
        # Normalize by MIN_PRICE_MOVE_PCT vs MIN_PREMIUM_MOVE_DOLLARS for comparability
        prev_divergence = (prev_nr / MIN_PREMIUM_MOVE_DOLLARS) - (prev_pr / MIN_PRICE_MOVE_PCT)
        now_divergence = (nr / MIN_PREMIUM_MOVE_DOLLARS) - (pr / MIN_PRICE_MOVE_PCT)
        # If prior divergence was significant and now it shrank meaningfully, gap closed
        if abs(prev_divergence) > 3.0 and abs(now_divergence) < 1.5:
            signals.append(mk(
                "GAP_CLOSED",
                f"Price caught up to premium — watch for stall / reversal near current level",
                "neutral",
                "medium",
            ))

    # ── DOUBLE_STALL: both price and dominant premium have flatlined
    dom_premium_roc = ncp_roc if abs(nr) >= abs(pnr) else npp_roc
    dom_stall_thresh = ncp_stall_thresh if abs(nr) >= abs(pnr) else npp_stall_thresh
    if _is_stalled(price_roc, STALL_CONFIRM_MIN, price_stall_thresh) and \
       _is_stalled(dom_premium_roc, STALL_CONFIRM_MIN, dom_stall_thresh):
        signals.append(mk(
            "DOUBLE_STALL",
            f"Price and premium both flatlined for {STALL_CONFIRM_MIN}min — potential support/resistance forming",
            "neutral",
            "medium",
        ))

    # ── BEARISH_DIVERGENCE: price up but NCP down (call selling into strength)
    if pr > MIN_PRICE_MOVE_PCT and nr < -MIN_PREMIUM_MOVE_DOLLARS:
        signals.append(mk(
            "BEARISH_DIVERGENCE",
            f"Price {pr:+.2f}% up but NCP {nr/1e6:+.2f}M down — bulls losing conviction",
            "bearish",
            "medium",
        ))

    # ── BULLISH_DIVERGENCE: price down but NPP down (put selling into weakness)
    if pr < -MIN_PRICE_MOVE_PCT and pnr < -MIN_PREMIUM_MOVE_DOLLARS:
        signals.append(mk(
            "BULLISH_DIVERGENCE",
            f"Price {pr:+.2f}% down but NPP {pnr/1e6:+.2f}M down — bears losing conviction",
            "bullish",
            "medium",
        ))

    return signals


def regime_summary(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a human-readable regime summary for the latest state.

    Useful as a compact header label on the NetFlow chart:
      "FLOW LEADS UP · NCP +$2.4M/10m · price -0.05% · high conf"
    """
    signals = detect_signals(bars)
    if not signals:
        return {
            "regime": "NO_SIGNAL",
            "description": "Insufficient data or no divergence/stall detected",
            "signals": [],
        }

    # Primary signal = first with highest confidence, or first if all equal
    primary = max(signals, key=lambda s: {"high": 3, "medium": 2, "low": 1}.get(s.confidence, 0))
    return {
        "regime": primary.signal,
        "description": primary.description,
        "gap_direction": primary.gap_direction,
        "confidence": primary.confidence,
        "signals": [s.to_row() for s in signals],
    }


# ── Telegram alert loop ───────────────────────────────────────────
#
# Periodically re-evaluates every tracked ticker's regime. When a ticker
# TRANSITIONS into a new regime (different signal from last known AND
# cooldown elapsed), fires a Telegram alert.
#
# Cooldown: 15 min minimum between alerts for the same ticker — prevents
# alert spam when regime flickers between adjacent classifications during
# chop. Same signal re-firing within cooldown is dropped silently.
#
# State lives in this module's singleton (NetFlowAlertState). Resets on
# backend restart, which is acceptable — a stale regime re-alert at
# startup is preferable to missing a real transition.

import asyncio
import json
import sqlite3
import time

from .market_calendar import is_market_holiday
from contextlib import contextmanager


# ── Persistence (added Phase 6 — was fire-and-forget Telegram only) ──

NET_FLOW_ALERTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS net_flow_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  signal TEXT NOT NULL,           -- FLOW_LEADS_UP / FLOW_LEADS_DOWN / etc.
  confidence TEXT NOT NULL,        -- high / medium / low
  gap_direction TEXT NOT NULL,     -- bullish / bearish / neutral
  spot REAL,
  ncp REAL,                        -- net call premium ($)
  npp REAL,                        -- net put premium ($)
  price_roc_pct REAL,              -- price ROC over window
  ncp_roc_dollars REAL,            -- NCP ROC over window
  npp_roc_dollars REAL,            -- NPP ROC over window
  description TEXT
);
CREATE INDEX IF NOT EXISTS idx_nfa_ts ON net_flow_alerts(ts);
CREATE INDEX IF NOT EXISTS idx_nfa_ticker ON net_flow_alerts(ticker, ts);
CREATE INDEX IF NOT EXISTS idx_nfa_signal ON net_flow_alerts(signal, ts);
"""


@contextmanager
def _nfa_conn():
    from .config import get_settings
    s = get_settings()
    c = sqlite3.connect(s.snapshot_db, timeout=30.0)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
    except sqlite3.OperationalError:
        pass
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_net_flow_alerts_db() -> None:
    with _nfa_conn() as c:
        c.executescript(NET_FLOW_ALERTS_SCHEMA)


def persist_net_flow_alert(
    ticker: str, signal: str, confidence: str, gap_direction: str,
    latest: dict[str, Any] | None, regime_info: dict[str, Any],
) -> None:
    """Insert one fire into net_flow_alerts (idempotent enough — no
    natural unique key, dedup is upstream via cooldown)."""
    try:
        l = latest or {}
        with _nfa_conn() as c:
            c.execute(
                """INSERT INTO net_flow_alerts
                    (ts, ticker, signal, confidence, gap_direction, spot,
                     ncp, npp, price_roc_pct, ncp_roc_dollars, npp_roc_dollars,
                     description)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(time.time()), ticker, signal, confidence, gap_direction,
                    l.get("price"),
                    l.get("ncp"),
                    l.get("npp"),
                    regime_info.get("price_roc_pct"),
                    regime_info.get("ncp_roc_dollars"),
                    regime_info.get("npp_roc_dollars"),
                    regime_info.get("description", ""),
                ),
            )
    except Exception as e:
        print(f"[NET_FLOW_ALERT] persist failed for {ticker}: {e}")


# Seconds of cooldown between alerts for the same ticker. Set via env or
# adjust here. 20 min baseline — net-flow signals change slowly, faster
# cooldowns flood chat during chop (documented spam 2026-04-23: 17 alerts
# in 28 min with same tickers flipping bear/bull repeatedly).
ALERT_COOLDOWN_S = 1200

# How often the alert loop scans all tickers (seconds).
ALERT_SCAN_INTERVAL_S = 60

# Minimum confidence required to fire a Telegram alert. Raised from
# 'medium' to 'high' 2026-04-23 — MEDIUM alerts fire on $100k+ 10-min
# premium moves, which is noise for mega-cap tickers (SPY/QQQ/MSFT
# trade $100M+ options daily). HIGH requires 5x the move = real signal.
# MEDIUM/LOW still persist to DB + UI for inspection.
ALERT_MIN_CONFIDENCE = "high"

# Which signals get Telegram pushes. The non-actionable ones (GAP_CLOSED)
# are watch-only (shown in UI but no push).
ALERT_SIGNALS = {
    "FLOW_LEADS_UP",
    "FLOW_LEADS_DOWN",
    "DOUBLE_STALL",
    "BEARISH_DIVERGENCE",
    "BULLISH_DIVERGENCE",
}


class NetFlowAlertState:
    """Tracks last-fired regime per ticker for dedupe + cooldown."""

    def __init__(self):
        # ticker → (regime, last_fired_epoch_seconds)
        self._last: dict[str, tuple[str, float]] = {}
        self.alerts_fired = 0
        self.alerts_suppressed_dedupe = 0
        self.alerts_suppressed_cooldown = 0
        self.alerts_suppressed_confidence = 0

    def should_fire(self, ticker: str, regime: str, confidence: str) -> bool:
        """Return True if this regime-ticker-confidence tuple should alert."""
        if regime not in ALERT_SIGNALS:
            return False
        # Confidence gate
        conf_rank = {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)
        min_rank = {"high": 3, "medium": 2, "low": 1}.get(ALERT_MIN_CONFIDENCE, 2)
        if conf_rank < min_rank:
            self.alerts_suppressed_confidence += 1
            return False

        now = time.time()
        last = self._last.get(ticker)
        if last is None:
            # Never seen — fire
            return True

        last_regime, last_ts = last
        if last_regime == regime:
            # Same regime continuing — check cooldown
            if now - last_ts < ALERT_COOLDOWN_S:
                self.alerts_suppressed_dedupe += 1
                return False
            # Cooldown elapsed, re-fire to remind user regime is still active
            return True

        # Different regime than last — transition. Previously allowed
        # transition alerts at 1/3 cooldown (5 min on 900s), which caused
        # the 2026-04-23 spam: TSLA bear→bull→bear within 17 min because
        # transition gate was lenient. Now require 2/3 cooldown (13 min on
        # 1200s) for transitions too. Flip-flop regimes are usually chop,
        # not real signals.
        if now - last_ts < ALERT_COOLDOWN_S * 2 / 3:
            self.alerts_suppressed_cooldown += 1
            return False
        return True

    def mark_fired(self, ticker: str, regime: str) -> None:
        self._last[ticker] = (regime, time.time())
        self.alerts_fired += 1

    def stats(self) -> dict[str, Any]:
        return {
            "alerts_fired": self.alerts_fired,
            "alerts_suppressed_dedupe": self.alerts_suppressed_dedupe,
            "alerts_suppressed_cooldown": self.alerts_suppressed_cooldown,
            "alerts_suppressed_confidence": self.alerts_suppressed_confidence,
            "tickers_with_state": len(self._last),
            "current_regimes": {
                t: regime for t, (regime, _) in self._last.items()
            },
        }


_alert_state: NetFlowAlertState | None = None


def get_alert_state() -> NetFlowAlertState:
    global _alert_state
    if _alert_state is None:
        _alert_state = NetFlowAlertState()
    return _alert_state


async def _send_regime_telegram(
    ticker: str, regime: str, gap_direction: str, confidence: str,
    description: str, latest: dict[str, Any] | None,
) -> None:
    """Format + send a Telegram alert for a regime transition."""
    try:
        from .telegram import send
    except ImportError:
        return

    # Emoji + color tier by direction
    if gap_direction == "bullish":
        emoji = "🟢"
        dir_tag = "BULLISH"
    elif gap_direction == "bearish":
        emoji = "🔴"
        dir_tag = "BEARISH"
    else:
        emoji = "⚪"
        dir_tag = "NEUTRAL"

    conf_emoji = {"high": "🔥", "medium": "⚡", "low": "·"}.get(confidence, "·")

    # Price + flow numbers for context
    spot_line = ""
    flow_line = ""
    if latest:
        if latest.get("price"):
            spot_line = f"Spot: ${latest['price']:.2f}\n"
        ncp = latest.get("ncp", 0) or 0
        npp = latest.get("npp", 0) or 0
        flow_line = (
            f"NCP: {'+' if ncp >= 0 else ''}${ncp/1e6:.2f}M  ·  "
            f"NPP: {'+' if npp >= 0 else ''}${npp/1e6:.2f}M\n"
        )

    text = (
        f"💹 NET FLOW: {ticker}\n"
        f"{emoji} {regime.replace('_', ' ')}  {conf_emoji} {confidence.upper()} {dir_tag}\n"
        f"\n"
        f"{spot_line}{flow_line}"
        f"\n"
        f"{description}"
    )

    try:
        await send(text, ticker=ticker, force=True)
    except Exception as e:
        print(f"[NET_FLOW_ALERT] telegram send failed: {e}")


def _is_rth_now() -> bool:
    """True only during regular trading hours (Mon–Fri, 9:30–16:00 ET).

    Same gate pattern used by ``flow_alerts._scan_flow_from_cache``. Without
    this, the alert loop fires the SAME stuck-state message every cooldown
    cycle overnight (observed 2026-05-08: TSLA "FLOW LEADS UP" spam every
    20 min from midnight to 4 AM, identical $405.89 spot, +$1.36M NCP). The
    aggregator series doesn't decay after-hours — it just freezes at the
    last RTH bar — so regime_summary keeps returning the same regime, and
    the "cooldown elapsed → re-fire to remind user" branch keeps firing.
    """
    import datetime
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    if is_market_holiday(now.date()):
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return False
    return True


def _bar_is_fresh(latest: dict | None, max_age_seconds: int = 180) -> bool:
    """True if the most recent aggregator bar is recent enough to act on.

    Belt-and-suspenders gate alongside ``_is_rth_now()``: even during RTH,
    if the data feed died and we're operating on stale bars, don't fire.
    Default 3 min — net-flow uses 1-min bars, so 3 min stale = 3 missed
    bars in a row (clear feed problem)."""
    if not latest:
        return False
    ts = latest.get("ts") or latest.get("epoch") or latest.get("timestamp")
    if ts is None:
        return False
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return False
    # Some series store ts in ms; normalize.
    if ts > 1e12:
        ts = ts / 1000.0
    import time as _t
    return (_t.time() - ts) <= max_age_seconds


async def run_net_flow_alert_loop(stop_event: asyncio.Event) -> None:
    """Periodic regime scanner — re-evaluates every TRACKED_TICKERS ticker
    and fires Telegram alerts on qualifying transitions.

    Uses the same aggregator instance as the /api/net-flow endpoint, so
    UI and alerts stay in sync.

    RTH-gated: skips entirely outside 9:30–16:00 ET Mon–Fri, AND requires
    the aggregator's latest bar to be ≤3 min old. Without these gates the
    loop fires identical stuck-state spam overnight (see _is_rth_now docstring).
    """
    # Lazy imports to avoid circular deps at module load
    from .net_flow import get_net_flow_aggregator, TRACKED_TICKERS

    state = get_alert_state()
    agg = get_net_flow_aggregator()

    print(
        f"[net_flow_alerts] loop starting — interval={ALERT_SCAN_INTERVAL_S}s  "
        f"cooldown={ALERT_COOLDOWN_S}s  min_conf={ALERT_MIN_CONFIDENCE}"
    )
    cycles = 0

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=ALERT_SCAN_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

        # ── RTH gate: skip the entire scan outside market hours ──
        # Cheaper than per-ticker gates and identical effect.
        if not _is_rth_now():
            cycles += 1
            if cycles % 30 == 0:  # quiet heartbeat ~ every 15 min when AH
                print("[net_flow_alerts] after-hours — skipping scan")
            continue

        try:
            for ticker in TRACKED_TICKERS:
                bars = agg.series(ticker, minutes=240)
                if len(bars) < 25:
                    # Not enough data yet — skip
                    continue

                regime_info = regime_summary(bars)
                regime = regime_info.get("regime")
                if not regime or regime == "NO_SIGNAL":
                    continue

                confidence = regime_info.get("confidence", "low")
                gap_dir = regime_info.get("gap_direction", "neutral")
                description = regime_info.get("description", "")

                if not state.should_fire(ticker, regime, confidence):
                    continue

                snap = agg.snapshot(ticker)
                latest = snap.get("latest")

                # Belt-and-suspenders staleness check — even inside RTH,
                # don't fire if the latest bar is too old (feed lag, queue
                # stall, etc.). Returns silently so the cooldown clock isn't
                # reset; we'll re-evaluate when fresh data arrives.
                if not _bar_is_fresh(latest):
                    continue

                # Fire telegram asynchronously so scan loop doesn't block
                asyncio.create_task(
                    _send_regime_telegram(
                        ticker, regime, gap_dir, confidence, description, latest
                    )
                )
                state.mark_fired(ticker, regime)

                # Persist to net_flow_alerts table (Phase 6 — was previously
                # fire-and-forget Telegram, no WR data).
                persist_net_flow_alert(
                    ticker, regime, confidence, gap_dir, latest, regime_info
                )

                print(
                    f"[NET_FLOW_ALERT] {ticker} → {regime} ({confidence}, {gap_dir}) — fired"
                )

            cycles += 1
            # Heartbeat every ~5 min
            if cycles % 5 == 0:
                print(f"[net_flow_alerts] heartbeat — {state.stats()}")

        except Exception as e:  # noqa: BLE001
            print(f"[net_flow_alerts] loop error: {e}")

    print(f"[net_flow_alerts] loop stopped — final stats: {state.stats()}")
