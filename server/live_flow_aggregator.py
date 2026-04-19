"""Live per-contract option-flow aggregator with Golden Flow transition detection.

Complements server/sweep_detector.py:
  - sweep_detector   = ISO-only (condition 95/126/128), 30s time-bucketed
                       rollups, writes to flow_alerts.SWEEP conviction
  - live_flow_aggregator = ALL aggressive flow, per-contract daily accumulator,
                       fires when a contract crosses into GOLDEN FLOW threshold

The two detectors share the same WebSocket stream. sweep_detector keeps its
narrow ISO filter; this aggregator accepts everything except cancellations
and non-ISO auctions, classifies side via the NBBO attached by ThetaStream,
and emits a GOLDEN alert the moment a contract's day-total matches all 5
Golden Flow rules.

That's the UW-style "insider flow fired 15 min before the news" alert —
same latency UW offers (~500ms), same raw data layer, no UW markup.

Why in-memory, not DB-per-trade
-------------------------------
- High frequency: 5k-10k active contracts × up to 100 trades/sec during
  market-open rush = too many DB writes if we persisted every trade
- The Golden Flow check only needs the RUNNING totals, not individual prints
- Periodic flush (30s) persists to option_flow_daily for the UI/backfill
- On server shutdown, final state is flushed

Golden transition semantics
---------------------------
Each (date, ticker, strike, exp, right) aggregate has a `_golden_fired`
boolean. Once a contract transitions False → True, we fire the alert ONCE
per day-contract (not every subsequent trade). A subsequent 30s re-check
that still says True is a no-op.

That means live Golden is a one-shot per contract per day. If the contract
un-crosses (e.g., more sell volume comes in pushing bought% below 65%),
we don't un-fire. The original alert stands as the entry cue.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

from .cache import cache
from .config import get_settings
from .option_flow_daily import (
    DailyFlowAggregate,
    GOLDEN_FLOW_RULES,
    is_golden_flow,
    score_golden_flow,
    upsert_flow_daily_batch,
)
from .thetadata import (
    EXCLUDE_CONDITIONS,
    ISO_SWEEP_CONDITIONS,
    NON_ISO_AUCTION_CONDITIONS,
    ThetaTrade,
)


# How often to re-evaluate aggregates for Golden transitions (seconds).
# Fast enough for real-time feel, slow enough to batch DB writes.
GOLDEN_CHECK_INTERVAL_S = 30

# Notional floor for even CONSIDERING an aggregate. Contracts below this
# can't be Golden anyway (rule 1 = ≥$500K), so we skip the check entirely.
MIN_NOTIONAL_FOR_CHECK = GOLDEN_FLOW_RULES["min_notional"]


class LiveFlowAggregator:
    """In-memory per-contract-day accumulator with Golden Flow transition detection.

    One instance per process. Thread-safe-ish via asyncio single-threaded model.
    """

    def __init__(self):
        # (date, root, strike, exp, right) -> DailyFlowAggregate
        # date is trade_date YYYY-MM-DD (ET), derived at insert time.
        self._aggregates: dict[tuple[str, str, float, str, str], DailyFlowAggregate] = {}
        # Set of keys that have already fired GOLDEN (one-shot per contract-day)
        self._golden_fired: set[tuple[str, str, float, str, str]] = set()
        # Telemetry
        self.trades_seen = 0
        self.trades_skipped_excluded = 0
        self.trades_skipped_auction = 0
        self.golden_alerts_fired = 0

    def _trade_date(self, ts_epoch: float) -> str:
        """Convert trade timestamp to ET date string. Heuristic: server assumed
        in ET, so the local date matches the trade date for RTH trades."""
        return dt.datetime.fromtimestamp(ts_epoch).strftime("%Y-%m-%d")

    def add_trade(self, trade: ThetaTrade) -> None:
        """Feed a single trade into the running aggregate.

        Caller should filter EXCLUDE_CONDITIONS + NON_ISO_AUCTION_CONDITIONS
        upstream, but we double-check here for safety.
        """
        self.trades_seen += 1
        if trade.condition in EXCLUDE_CONDITIONS:
            self.trades_skipped_excluded += 1
            return
        if trade.condition in NON_ISO_AUCTION_CONDITIONS:
            self.trades_skipped_auction += 1
            return

        # trade_date approximation: use "today" in local ET time. For any
        # cross-midnight edge case, the aggregator will start a fresh
        # accumulator for the new date, which is correct.
        trade_date = self._trade_date(time.time())
        key = (trade_date, trade.ticker, trade.strike, trade.expiration, trade.right)

        agg = self._aggregates.get(key)
        if agg is None:
            agg = DailyFlowAggregate(
                date=trade_date,
                ticker=trade.ticker,
                strike=trade.strike,
                expiration=trade.expiration,
                option_type=trade.right,
            )
            self._aggregates[key] = agg

        agg.add(
            size=trade.size, price=trade.price, exchange=trade.exchange,
            condition=trade.condition, side=trade.side,
            is_sweep=trade.is_sweep,
            timestamp=dt.datetime.fromtimestamp(time.time()).isoformat(),
        )

    async def check_golden_transitions(self) -> list[tuple]:
        """Re-evaluate every aggregate ≥$500K notional for Golden status.

        Returns a list of newly-golden aggregate keys that just transitioned
        from not-golden to golden. Caller handles alert dispatch.
        """
        newly_golden: list[tuple] = []

        # Grab worker cache ONCE per cycle for OI/spot lookups
        try:
            snapshot = await cache.snapshot()
        except Exception:
            snapshot = {}

        for key, agg in self._aggregates.items():
            if key in self._golden_fired:
                continue  # one-shot; already alerted
            if agg.total_notional < MIN_NOTIONAL_FOR_CHECK:
                continue  # can't be golden yet, save CPU

            # Enrich with OI + spot from worker cache for the classifier
            state = snapshot.get(agg.ticker) or {}
            spot = state.get("actual_spot") or state.get("_spot") or 0
            oi = self._lookup_oi(state, agg.strike, agg.expiration, agg.option_type)

            # Build a row dict matching option_flow_daily column names
            row = {
                "date": agg.date,
                "ticker": agg.ticker,
                "strike": agg.strike,
                "expiration": agg.expiration,
                "option_type": agg.option_type,
                "total_volume": agg.total_volume,
                "total_notional": agg.total_notional,
                "buy_notional": agg.buy_notional,
                "sell_notional": agg.sell_notional,
                "neutral_notional": agg.neutral_notional,
                "sweep_notional": agg.sweep_notional,
                "oi": oi,
                "spot": spot,
            }
            is_gold, _failed = is_golden_flow(row)
            if is_gold:
                self._golden_fired.add(key)
                newly_golden.append((key, agg, oi, spot))

        return newly_golden

    def _lookup_oi(self, state: dict, strike: float, expiration: str, option_type: str) -> int | None:
        """Pull OI for a contract from the worker's cached raw chain."""
        try:
            raw_by_exp = state.get("_raw_contracts") or {}
            chain = raw_by_exp.get(expiration) or []
            for c in chain:
                if c.get("strike") == strike and (c.get("option_type") or "").lower() == option_type:
                    return c.get("open_interest")
        except Exception:
            pass
        return None

    async def flush_to_db(self) -> int:
        """Persist current aggregates to option_flow_daily. Called periodically
        and at shutdown. Returns number of rows upserted."""
        if not self._aggregates:
            return 0
        # Pull worker cache once to enrich with OI/IV/delta/spot
        try:
            snapshot = await cache.snapshot()
        except Exception:
            snapshot = {}

        batch: list[tuple] = []
        for agg in self._aggregates.values():
            state = snapshot.get(agg.ticker) or {}
            spot = state.get("actual_spot") or state.get("_spot") or 0
            oi = self._lookup_oi(state, agg.strike, agg.expiration, agg.option_type)
            # IV / delta also available from cache chain — best-effort
            iv = None
            delta = None
            try:
                raw_by_exp = state.get("_raw_contracts") or {}
                chain = raw_by_exp.get(agg.expiration) or []
                for c in chain:
                    if c.get("strike") == agg.strike and (c.get("option_type") or "").lower() == agg.option_type:
                        g = c.get("greeks") or {}
                        iv = g.get("mid_iv") or g.get("smv_vol")
                        delta = g.get("delta")
                        break
            except Exception:
                pass
            batch.append(agg.to_db_tuple(oi=oi, iv=iv, delta=delta, spot=spot))

        return upsert_flow_daily_batch(batch)

    def stats(self) -> dict:
        return {
            "active_aggregates": len(self._aggregates),
            "golden_alerts_fired": self.golden_alerts_fired,
            "trades_seen": self.trades_seen,
            "trades_skipped_excluded": self.trades_skipped_excluded,
            "trades_skipped_auction": self.trades_skipped_auction,
        }


# ── Alerting ───────────────────────────────────────────────────────


def _factor_bar(pts: int, width: int = 5) -> str:
    """Render a unicode bar for N/4 points. Used in Telegram messages."""
    filled = "█" * pts
    empty = "░" * (4 - pts)
    return f"{filled}{empty}"


async def send_golden_telegram(
    agg: DailyFlowAggregate, oi: int | None, spot: float,
    cluster_size: int = 1,
) -> None:
    """Telegram push when a contract first crosses the Golden Flow threshold.

    Includes A+/A/B/C/D grade from score_golden_flow() so the user knows at
    a glance whether this is a top-tier alert vs barely-scraping-threshold.
    Hit-rate context (forward returns on similar prior setups) appended when
    available. force=True bypasses rate-limiter — Golden is time-sensitive.
    """
    try:
        from .telegram import send
    except ImportError:
        return

    buy = agg.buy_notional
    sell = agg.sell_notional
    directional = buy + sell
    bought_pct = (buy / directional * 100) if directional else 0
    sold_pct = (sell / directional * 100) if directional else 0
    side = "BUY" if bought_pct >= sold_pct else "SELL"
    side_pct = max(bought_pct, sold_pct)
    otm = abs(agg.strike - spot) / spot * 100 if spot else 0
    vol_oi = (agg.total_volume / oi) if oi else float("inf")
    right_label = "CALL" if agg.option_type == "call" else "PUT"
    emoji = "🟢" if agg.option_type == "call" else "🔴"

    # Trading-day DTE
    try:
        td = dt.date.fromisoformat(agg.date)
        ed = dt.date.fromisoformat(agg.expiration)
        dte = 0
        d = td
        while d < ed:
            d = d + dt.timedelta(days=1)
            if d.weekday() < 5:
                dte += 1
    except Exception:
        dte = "?"

    # Compute grade
    row = {
        "total_notional": agg.total_notional,
        "buy_notional": agg.buy_notional,
        "sell_notional": agg.sell_notional,
        "total_volume": agg.total_volume,
        "oi": oi,
        "sweep_notional": agg.sweep_notional,
    }
    g = score_golden_flow(row, cluster_size=cluster_size)
    factors = g["factors"]

    # Hit-rate context — look up similar historical setups
    hit_rate_line = ""
    try:
        from .signal_outcomes import get_hit_rate
        hr = get_hit_rate(
            source_type="sweep",  # sweeps are our closest historical proxy
            direction=side,
            ticker=agg.ticker,
            min_notional=500_000,
            lookback_days=90,
        )
        if hr["cohort_size"] >= 5:  # only show if meaningful sample
            h1d = hr["horizons"]["1d"]
            h3d = hr["horizons"]["3d"]
            if h1d["rate"] is not None:
                hit_rate_line = (
                    f"\nSimilar setups (n={hr['cohort_size']}): "
                    f"1d {h1d['rate']*100:.0f}% · "
                    f"3d {(h3d['rate'] or 0)*100:.0f}%"
                )
    except Exception:
        pass

    text = (
        f"⚡ GOLDEN {g['grade']}  {agg.ticker}  ({g['score']}/{g['max_score']})\n"
        f"{emoji} ${agg.strike:.0f} {right_label} {agg.expiration} (DTE={dte})\n"
        f"\n"
        f"{side} {side_pct:.0f}%       {_factor_bar(factors['conviction']['pts'])}  {factors['conviction']['pts']}/4\n"
        f"Notional ${agg.total_notional/1e6:.2f}M  {_factor_bar(factors['notional']['pts'])}  {factors['notional']['pts']}/4\n"
        f"V/OI {vol_oi if isinstance(vol_oi, str) else f'{vol_oi:.1f}'}x          {_factor_bar(factors['vol_oi']['pts'])}  {factors['vol_oi']['pts']}/4\n"
        f"Sweep {(agg.sweep_notional / agg.total_notional * 100) if agg.total_notional else 0:.0f}%        {_factor_bar(factors['sweep_share']['pts'])}  {factors['sweep_share']['pts']}/4\n"
        f"Cluster {cluster_size}x        {_factor_bar(factors['cluster']['pts'])}  {factors['cluster']['pts']}/4\n"
        f"\n"
        f"Volume: {agg.total_volume:,} / OI: {oi or '—'}\n"
        f"Largest: {agg.largest_print_size:,} @ ${agg.largest_print_price:.2f}\n"
        f"Spot: ${spot:.2f} | OTM: {otm:.1f}%"
        f"{hit_rate_line}"
    )
    try:
        await send(text, ticker=agg.ticker, force=True)
    except Exception as e:
        print(f"[LIVE_FLOW] telegram send failed: {e}")


# ── Background task entry point ────────────────────────────────────


async def run_golden_transition_loop(
    aggregator: LiveFlowAggregator, stop_event: asyncio.Event,
) -> None:
    """Poll the aggregator every GOLDEN_CHECK_INTERVAL_S seconds for new
    Golden Flow transitions. Fires Telegram + logs to DB on each."""
    while not stop_event.is_set():
        try:
            await asyncio.sleep(GOLDEN_CHECK_INTERVAL_S)
        except asyncio.CancelledError:
            break

        try:
            newly_golden = await aggregator.check_golden_transitions()
        except Exception as e:
            print(f"[LIVE_FLOW] check_golden_transitions error: {e}")
            continue

        if newly_golden:
            # Compute cluster size per (date, ticker) across all golden-fired
            # contracts so we can pass confluence context to the grader. One
            # alert = solo. 2+ on same underlying same session = cluster tell.
            cluster_counter: dict[tuple[str, str], int] = {}
            for key in aggregator._golden_fired:
                dt_, ticker, _strike, _exp, _right = key
                cluster_counter[(dt_, ticker)] = cluster_counter.get((dt_, ticker), 0) + 1

            for key, agg, oi, spot in newly_golden:
                aggregator.golden_alerts_fired += 1
                cluster_size = cluster_counter.get((agg.date, agg.ticker), 1)
                print(
                    f"[GOLDEN] {agg.ticker} ${agg.strike:.0f}{agg.option_type[0].upper()} "
                    f"{agg.expiration} — ${agg.total_notional:,.0f} notional "
                    f"(buy={agg.buy_notional/agg.total_notional*100:.0f}%, "
                    f"sweep={agg.sweep_notional/agg.total_notional*100:.0f}%, "
                    f"OI={oi or '—'}, cluster={cluster_size}x)",
                    flush=True,
                )
                # Fire telegram asynchronously so loop doesn't block
                asyncio.create_task(send_golden_telegram(agg, oi, spot, cluster_size=cluster_size))

        # Also flush to DB on each cycle so the UI sees near-real-time data
        try:
            n = await aggregator.flush_to_db()
            if n and n > 0:
                # only log occasional heartbeat, not every 30s
                if aggregator.trades_seen % 1000 < 50:
                    print(f"[LIVE_FLOW] flushed {n} aggregates to DB  stats={aggregator.stats()}")
        except Exception as e:
            print(f"[LIVE_FLOW] DB flush error: {e}")

    # Final flush on shutdown
    try:
        await aggregator.flush_to_db()
        print(f"[LIVE_FLOW] shutdown flush done  stats={aggregator.stats()}")
    except Exception as e:
        print(f"[LIVE_FLOW] shutdown flush error: {e}")
