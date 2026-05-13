"""Flow alert filter chain — reduces Telegram spam without losing signal.

Background (May 6 2026): 1,267 flow_alerts fired in a single session, 91%
LOW or MEDIUM conviction, with multi-leg trades exploding into 18+ alerts
within a single minute (AMD 9:39, IWM 11:07 risk-reversal). The DB-side
filter alone (HIGH-only + ≥$5M + OTM≥1%) wasn't enough because OPRA sweeps
and whale-overrides bypassed those gates and clustered.

This module sits BETWEEN `insert_alert` (which always writes to DB so we
keep the data) and `_send_telegram` (which only fires if the filter says
yes). Same wiring works for `insert_sweep_alert` flow.

Filter levels (env var FLOW_ALERT_FILTER_LEVEL):
  OFF   — no filtering, current behavior
  LIGHT — rules 2 + 4 only (drop LOW unless sweep/$5M, drop NEUTRAL+HARD)
  FULL  — all 4 rules (LIGHT + cluster collapser + hourly throttle)

Rule 1 (cluster collapser): ≥3 same-ticker alerts within 60s -> 1 unified
alert summarizing total notional + dominant sentiment. Holds the first N-1
alerts back, emits a synthetic summary once the window closes.

Rule 2 (LOW conviction floor): drop conviction='LOW' unless is_sweep=1 OR
notional > $5M. Real institutional flow either hits a hard size threshold
or carries an OPRA sweep tag.

Rule 3 (per-ticker hourly throttle): cap 5 alerts/ticker/hour. Excess gets
queued into a "HOT FLOW" summary that fires once at hour-end.

Rule 4 (NEUTRAL in HARD regime): drop alerts with sentiment='NEUTRAL' AND
macro_regime_tag='HARD'. NEUTRAL flow during high-uncertainty regimes is
just noise; we want directional bets.

Decision contract:
  decide(alert) -> ('FIRE', alert)              # send the original alert
                | ('FIRE_SUMMARY', summary_dict) # send a collapsed cluster
                | ('DROP', reason: str)         # don't send anything
                | ('DEFER', None)               # held in cluster window

Caller MUST also call `flush()` periodically (e.g. once every 30s after a
scan cycle) to drain any clusters whose 60s window has expired and any
hour-end HOT FLOW summaries.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Any, Literal

Decision = Literal["FIRE", "FIRE_SUMMARY", "DROP", "DEFER"]

# ---- Config ----------------------------------------------------------------

CLUSTER_WINDOW_SEC = 60
CLUSTER_MIN_LEGS = 5            # was 3 — only orchestrated clusters fire
CLUSTER_MIN_NOTIONAL = 10_000_000  # 2026-05-13: $10M aggregate floor
CLUSTER_DIRECTIONAL_BIAS = True    # 2026-05-13: drop MIXED clusters
LOW_NOTIONAL_FLOOR = 5_000_000
HOURLY_CAP = 5


def _level() -> str:
    """Read filter level fresh each call so .env updates take effect at the
    next scan cycle without restart. Caches in a function-local; if you
    really need a hot-toggle, call `set_level()` instead."""
    return (os.environ.get("FLOW_ALERT_FILTER_LEVEL") or "LIGHT").upper()


_override_level: str | None = None


def set_level(level: str | None) -> None:
    """Programmatic override (used by backtest harness)."""
    global _override_level
    _override_level = level.upper() if level else None


def _active_level() -> str:
    return _override_level or _level()


# ---- Cluster collapser -----------------------------------------------------


class ClusterCollapser:
    """Holds same-ticker alerts arriving within CLUSTER_WINDOW_SEC and emits
    one summary if ≥CLUSTER_MIN_LEGS pile up. If only 1-2 land in a window,
    they fire individually once the window closes.

    Window starts on the FIRST alert for a ticker; subsequent alerts within
    the window are buffered. Calling `flush(now)` returns alerts whose
    windows have expired (either as singles or summaries).
    """

    def __init__(
        self,
        window_sec: int = CLUSTER_WINDOW_SEC,
        min_legs: int = CLUSTER_MIN_LEGS,
    ) -> None:
        self.window_sec = window_sec
        self.min_legs = min_legs
        # ticker -> list[(ts, alert)]
        self._buf: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)

    def add(self, alert: dict[str, Any], now: int | None = None) -> Decision:
        """Buffer this alert. Always returns DEFER — caller relies on
        flush() to actually emit. Simpler than trying to fire mid-stream."""
        ts = now if now is not None else int(alert.get("ts") or time.time())
        ticker = alert.get("ticker", "")
        self._buf[ticker].append((ts, alert))
        return "DEFER"

    def flush(self, now: int | None = None) -> list[tuple[Decision, Any]]:
        """Emit any clusters whose window has fully elapsed. Returns a list
        of (decision, payload) tuples to feed into the throttle stage."""
        now = now if now is not None else int(time.time())
        out: list[tuple[Decision, Any]] = []
        for ticker, items in list(self._buf.items()):
            if not items:
                self._buf.pop(ticker, None)
                continue
            window_start = items[0][0]
            if now - window_start < self.window_sec:
                continue  # window still open

            if len(items) >= self.min_legs:
                summary = self._build_summary(ticker, items)
                if self._cluster_passes_gates(summary):
                    out.append(("FIRE_SUMMARY", summary))
                # else: silently drop — cluster was directionally mixed
                # or below notional floor, not signal-worthy
            else:
                for _, a in items:
                    out.append(("FIRE", a))
            self._buf.pop(ticker, None)
        return out

    def force_flush_all(self) -> list[tuple[Decision, Any]]:
        """Drain everything (test/shutdown hook). Same logic as flush() but
        ignores the window-elapsed gate."""
        out: list[tuple[Decision, Any]] = []
        for ticker, items in list(self._buf.items()):
            if not items:
                continue
            if len(items) >= self.min_legs:
                summary = self._build_summary(ticker, items)
                if self._cluster_passes_gates(summary):
                    out.append(("FIRE_SUMMARY", summary))
            else:
                for _, a in items:
                    out.append(("FIRE", a))
        self._buf.clear()
        return out

    @staticmethod
    def _cluster_passes_gates(summary: dict[str, Any]) -> bool:
        """Post-build gates added 2026-05-13 to suppress noise clusters.

        Two filters:
          1. Notional floor — cluster's aggregate notional must be
             institutional-grade. Sub-$10M clusters are usually MM activity
             plus retail piggybacking, not orchestrated flow.
          2. Directional clarity — drop pure-MIXED clusters (bull == bear).
             A cluster that's directionally split provides no actionable
             read; it's just an active 0DTE day. MIXED-BULL/MIXED-BEAR
             (bull > bear or vice versa, but not 2x) still pass because
             the lean is informative.
        """
        if (summary.get("total_notional") or 0) < CLUSTER_MIN_NOTIONAL:
            return False
        if CLUSTER_DIRECTIONAL_BIAS and summary.get("bias") == "MIXED":
            return False
        return True

    @staticmethod
    def _build_summary(
        ticker: str, items: list[tuple[int, dict[str, Any]]]
    ) -> dict[str, Any]:
        legs = len(items)
        total_notional = sum((a.get("notional") or 0) for _, a in items)
        senti = [a.get("sentiment") or "NEUTRAL" for _, a in items]
        bull = sum(1 for s in senti if s == "BULLISH")
        bear = sum(1 for s in senti if s == "BEARISH")
        if bull > bear * 2:
            bias = "BULLISH"
        elif bear > bull * 2:
            bias = "BEARISH"
        elif bull > bear:
            bias = "MIXED-BULL"
        elif bear > bull:
            bias = "MIXED-BEAR"
        else:
            bias = "MIXED"
        # Pick the "best" representative leg (highest notional) for spot/regime
        rep = max(items, key=lambda kv: (kv[1].get("notional") or 0))[1]
        # Strike spread
        strikes = [a.get("strike") for _, a in items if a.get("strike") is not None]
        sweep_legs = sum(1 for _, a in items if a.get("is_sweep"))
        return {
            "kind": "CLUSTER",
            "ticker": ticker,
            "legs": legs,
            "total_notional": total_notional,
            "bias": bias,
            "bullish_legs": bull,
            "bearish_legs": bear,
            "sweep_legs": sweep_legs,
            "strike_low": min(strikes) if strikes else None,
            "strike_high": max(strikes) if strikes else None,
            "spot": rep.get("spot"),
            "macro_regime_tag": rep.get("macro_regime_tag"),
            "first_ts": items[0][0],
            "last_ts": items[-1][0],
        }


# ---- Hourly throttle -------------------------------------------------------


class HourlyThrottle:
    """Caps alerts per ticker per clock-hour. Excess alerts get queued for
    the end-of-hour HOT FLOW summary."""

    def __init__(self, cap: int = HOURLY_CAP) -> None:
        self.cap = cap
        # (ticker, hour_bucket) -> count of fired alerts
        self._fired: dict[tuple[str, int], int] = defaultdict(int)
        # (ticker, hour_bucket) -> list of suppressed alerts
        self._suppressed: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        # Track which hour buckets we've already drained into HOT FLOW summaries
        self._drained: set[tuple[str, int]] = set()

    @staticmethod
    def _hour_bucket(ts: int) -> int:
        return ts // 3600

    def admit(self, alert: dict[str, Any], now: int | None = None) -> Decision:
        ticker = alert.get("ticker", "")
        ts = now if now is not None else int(alert.get("ts") or time.time())
        key = (ticker, self._hour_bucket(ts))
        if self._fired[key] < self.cap:
            self._fired[key] += 1
            return "FIRE"
        self._suppressed[key].append(alert)
        return "DEFER"

    def flush(self, now: int | None = None) -> list[dict[str, Any]]:
        """Emit HOT FLOW summaries for any expired hour buckets that
        accumulated suppressed alerts."""
        now = now if now is not None else int(time.time())
        current_bucket = self._hour_bucket(now)
        out: list[dict[str, Any]] = []
        for key, alerts in list(self._suppressed.items()):
            ticker, bucket = key
            if bucket >= current_bucket:
                continue  # current hour still open
            if key in self._drained:
                continue
            if not alerts:
                continue
            out.append(self._build_hot_flow(ticker, bucket, alerts))
            self._drained.add(key)
        return out

    @staticmethod
    def _build_hot_flow(
        ticker: str, hour_bucket: int, alerts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        n = len(alerts)
        total_notional = sum((a.get("notional") or 0) for a in alerts)
        senti = [a.get("sentiment") or "NEUTRAL" for a in alerts]
        bull = sum(1 for s in senti if s == "BULLISH")
        bear = sum(1 for s in senti if s == "BEARISH")
        return {
            "kind": "HOT_FLOW",
            "ticker": ticker,
            "hour_start": hour_bucket * 3600,
            "suppressed_count": n,
            "total_notional": total_notional,
            "bullish_legs": bull,
            "bearish_legs": bear,
        }


# ---- Filter chain ----------------------------------------------------------


class FlowAlertFilter:
    """The full pipeline. Use one instance per process (singleton in worker).

    Usage:
        f = FlowAlertFilter()
        decisions = f.process(alert)     # returns 0..1 things to fire
        ...
        # call once per scan cycle (e.g. every 30s):
        decisions += f.flush()
    """

    def __init__(self) -> None:
        self._cluster = ClusterCollapser()
        self._throttle = HourlyThrottle()
        # Stats for diagnostics
        self.stats = defaultdict(int)

    # ---- Pre-filter (rules 2 + 4): synchronous drop --------------------

    def _prefilter(self, alert: dict[str, Any]) -> tuple[bool, str]:
        """Returns (keep?, reason_if_dropped)."""
        level = _active_level()
        if level == "OFF":
            return True, ""

        # Rule 4: NEUTRAL in HARD regime
        if level in ("LIGHT", "FULL"):
            if (
                (alert.get("sentiment") or "").upper() == "NEUTRAL"
                and (alert.get("macro_regime_tag") or "").upper() == "HARD"
            ):
                return False, "neutral_in_hard"

        # Rule 2: LOW conviction unless sweep or notional ≥ $5M
        if level in ("LIGHT", "FULL"):
            if (alert.get("conviction") or "").upper() == "LOW":
                is_sweep = bool(alert.get("is_sweep"))
                notional = alert.get("notional") or 0
                if not is_sweep and notional < LOW_NOTIONAL_FLOOR:
                    return False, "low_conviction"

        return True, ""

    # ---- Public API -----------------------------------------------------

    def process(
        self, alert: dict[str, Any], now: int | None = None
    ) -> list[tuple[Decision, Any]]:
        """Run an incoming alert through the chain. Returns immediate
        decisions (may be empty if alert was deferred or dropped)."""
        self.stats["seen"] += 1
        keep, reason = self._prefilter(alert)
        if not keep:
            self.stats[f"drop_{reason}"] += 1
            return [("DROP", reason)]

        level = _active_level()
        if level == "OFF" or level == "LIGHT":
            # Skip cluster (rule 1 only in FULL); apply throttle for LIGHT/FULL
            if level == "OFF":
                self.stats["fired"] += 1
                return [("FIRE", alert)]
            decision = self._throttle.admit(alert, now=now)
            if decision == "FIRE":
                self.stats["fired"] += 1
                return [("FIRE", alert)]
            self.stats["throttled"] += 1
            return []

        # FULL: cluster first
        self._cluster.add(alert, now=now)
        self.stats["clustered_pending"] += 1
        return []

    def flush(self, now: int | None = None) -> list[tuple[Decision, Any]]:
        """Drain expired cluster windows and hour buckets, push them through
        the throttle, and return final FIRE decisions."""
        now = now if now is not None else int(time.time())
        results: list[tuple[Decision, Any]] = []

        for decision, payload in self._cluster.flush(now=now):
            if decision == "FIRE":
                # Single alert from a small window — still throttle-gate it
                d2 = self._throttle.admit(payload, now=now)
                if d2 == "FIRE":
                    self.stats["fired"] += 1
                    results.append(("FIRE", payload))
                else:
                    self.stats["throttled"] += 1
            elif decision == "FIRE_SUMMARY":
                # Cluster summaries bypass throttle (already a roll-up)
                self.stats["fired_summary"] += 1
                results.append(("FIRE_SUMMARY", payload))

        for hot in self._throttle.flush(now=now):
            self.stats["fired_hot_flow"] += 1
            results.append(("FIRE_SUMMARY", hot))

        return results

    def reset(self) -> None:
        """For tests / backtests."""
        self._cluster = ClusterCollapser()
        self._throttle = HourlyThrottle()
        self.stats = defaultdict(int)


# ---- Module-level singleton ------------------------------------------------

_global_filter: FlowAlertFilter | None = None


def get_filter() -> FlowAlertFilter:
    global _global_filter
    if _global_filter is None:
        _global_filter = FlowAlertFilter()
    return _global_filter


# ---- Telegram formatters for the synthetic alerts --------------------------


def format_cluster_summary(c: dict[str, Any]) -> str:
    bias_emoji = {
        "BULLISH": "🟢",
        "BEARISH": "🔴",
        "MIXED-BULL": "🟢🟡",
        "MIXED-BEAR": "🔴🟡",
        "MIXED": "🟡",
    }.get(c.get("bias") or "MIXED", "🟡")
    span = ""
    sl, sh = c.get("strike_low"), c.get("strike_high")
    if sl is not None and sh is not None:
        if sl == sh:
            span = f" @ ${sl:g}"
        else:
            span = f" ${sl:g}–${sh:g}"
    sweep_note = ""
    if c.get("sweep_legs"):
        sweep_note = f" ⚡{c['sweep_legs']}sw"
    return (
        f"{bias_emoji} CLUSTER FLOW: {c['ticker']} ({c['bias']})\n"
        f"{c['legs']} legs in 60s{span}{sweep_note}\n"
        f"Bull: {c['bullish_legs']}  Bear: {c['bearish_legs']}\n"
        f"Total notional: ${c['total_notional']:,.0f}\n"
        f"Spot: ${(c.get('spot') or 0):.2f}"
    )


def format_hot_flow_summary(h: dict[str, Any]) -> str:
    import datetime as dt
    hr = dt.datetime.fromtimestamp(h["hour_start"]).strftime("%I%p").lstrip("0")
    return (
        f"🔥 HOT FLOW [{hr}]: {h['ticker']}\n"
        f"{h['suppressed_count']} additional alerts suppressed\n"
        f"Total notional: ${h['total_notional']:,.0f}\n"
        f"Bull: {h['bullish_legs']}  Bear: {h['bearish_legs']}"
    )
