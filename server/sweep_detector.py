"""ISO sweep detector — consumes Theta WebSocket trade stream and rolls
OPRA-tagged intermarket sweep prints into contract-level alerts.

Why this exists:
  Regular flow alerts (server/flow_alerts.py) infer unusual activity from
  aggregate volume/OI ratios every 30s. This detector watches the live
  OPRA tape and fires INSTANTLY when the OPRA feed itself tags a print
  as condition=95 (INTERMARKET_SWEEP) — no inference needed.

  Sweeps have a documented edge in flow-tracking literature: unlike block
  trades they signal URGENCY (an order routed across 4+ venues within
  100ms to chase fills). UW's highest-hit-rate category.

Pipeline:
  ThetaStream.trades() -> [filter: condition 95/126/128]
                       -> [drop cancellations (40-44) + non-ISO auctions (125/127)]
                       -> [rollup: per-contract 30s window, sum size/notional,
                           count distinct exchanges, count prints]
                       -> [on window close: insert_sweep_alert() to DB]
                       -> [Telegram push if notional > threshold]

Subscription strategy (MVP, hardcoded Apr 17 2026):
  SPY ATM ±10 × next 3 expirations  = ~120 subs
  QQQ ATM ±10 × next 3 expirations  = ~120 subs
  Tier 1 momentum ATM ±5 × near exp = ~200 subs
  Total well under the 15K Standard-tier cap

Side classification is NEUTRAL in MVP — full ask/bid-relative classification
requires a parallel QUOTE stream subscription (follow-up). We store enough
raw data (price, venues, size distribution) that we can reclassify later
by re-querying Theta's snapshot quote history.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .cache import cache
from .config import get_settings
from .flow_alerts import insert_sweep_alert
from .live_flow_aggregator import (
    LiveFlowAggregator,
    run_golden_transition_loop,
)
from .thetadata import (
    EXCLUDE_CONDITIONS,
    NON_ISO_AUCTION_CONDITIONS,
    SubscribeSpec,
    ThetaStream,
    ThetaTrade,
    get_stream,
)


# ── Rollup window ─────────────────────────────────────────────────────

ROLLUP_SECONDS = 30
MIN_SWEEP_NOTIONAL = 50_000    # $ — below this, ignore (noise; single contract ISO)
TELEGRAM_NOTIONAL = 500_000    # $ — alert threshold for Telegram push


@dataclass
class SweepRollup:
    """Per-contract aggregation window. One instance per (ticker, strike, exp, right)
    active in the current 30s bucket."""
    ticker: str
    strike: float
    expiration: str
    option_type: str            # 'call' | 'put'
    window_start: float         # epoch seconds when this rollup was opened

    total_contracts: int = 0
    total_notional: float = 0.0
    print_count: int = 0
    exchanges: set[int] = field(default_factory=set)
    prices: list[float] = field(default_factory=list)
    first_price: float = 0.0
    last_price: float = 0.0
    max_print_size: int = 0

    def add(self, trade: ThetaTrade) -> None:
        if not self.print_count:
            self.first_price = trade.price
        self.print_count += 1
        self.total_contracts += trade.size
        self.total_notional += trade.notional
        self.exchanges.add(trade.exchange)
        self.prices.append(trade.price)
        self.last_price = trade.price
        if trade.size > self.max_print_size:
            self.max_print_size = trade.size

    @property
    def venue_count(self) -> int:
        return len(self.exchanges)

    @property
    def avg_price(self) -> float:
        return sum(self.prices) / len(self.prices) if self.prices else 0.0

    def to_alert_payload(self) -> dict[str, Any]:
        """Shape the rollup into the dict expected by insert_sweep_alert."""
        return {
            "ticker": self.ticker,
            "strike": self.strike,
            "expiration": self.expiration,
            "option_type": self.option_type,
            "sweep_notional": round(self.total_notional, 2),
            "sweep_contracts": self.total_contracts,
            "sweep_venues": self.venue_count,
            "sweep_prints": self.print_count,
            "sweep_side": "NEUTRAL",  # MVP — classification requires NBBO stream
            "sweep_window_s": ROLLUP_SECONDS,
            "last": self.last_price,
            "bid": None,
            "ask": None,
            "iv": None,
            "delta": None,
            "oi": None,
            "spot": None,
        }


# ── Subscription planning ─────────────────────────────────────────────


def _next_expirations(n: int = 3) -> list[int]:
    """Return the next N weekly expiration dates (Friday-anchored) as YYYYMMDD ints.

    Theta expects YYYYMMDD ints on the wire. We target Fridays going forward
    plus Wednesday/Monday for SPY/QQQ daily expirations.
    """
    import datetime
    today = datetime.date.today()
    dates: list[datetime.date] = []

    # SPY/QQQ have M/W/F expirations. Pull all upcoming M/W/F in next 14 days.
    for d in range(0, 14):
        candidate = today + datetime.timedelta(days=d)
        if candidate.weekday() in (0, 2, 4):  # Mon, Wed, Fri
            dates.append(candidate)
            if len(dates) >= n:
                break
    return [int(d.strftime("%Y%m%d")) for d in dates]


# Hardcoded MVP watchlist. Expansion: dynamically read from worker's Tier 1
# watchlist once worker has populated the cache (follow-up work).
#
# SPX/SPXW added 2026-04-18: SPX = monthly AM-settled, SPXW = weekly + 0DTE
# PM-settled. Both trade OPRA and support ISO sweeps. 0DTE SPXW is where
# most insider flow lives (UW's best-performing alert category).
MVP_WATCHLIST_ROOTS = [
    "SPY", "QQQ", "IWM",                              # ETF indices
    "SPX", "SPXW", "NDX", "RUT",                      # Cash-settled index options
    "AAPL", "NVDA", "MSFT", "TSLA", "META", "AMZN", "GOOGL",  # mega-cap momentum
    "AMD", "AVGO", "NFLX", "CRM", "ORCL",
]


async def _build_subscription_plan(
    rest_client: Any = None,
) -> list[SubscribeSpec]:
    """Plan which contracts to subscribe to on startup.

    Strike grid per root uses server.root_config.get_strike_step() so SPY
    gets $1 steps (every strike) and SPX gets $5 steps (index-appropriate).
    Radius widened to 40 strikes each side so the 2.5% OTM Golden-Flow rule
    has headroom — on SPY at $660, radius 40 × $1 = $620-$700 (±6%), which
    comfortably encloses the whole 2.5% zone where insider-pattern trades
    cluster.

    Budget check (all MVP roots at radius 40):
      19 tickers × ~80 strikes × 2 rights × 3 exps ≈ 9,120 subs
    Under the Standard-tier 15K-trade-stream cap with headroom.
    """
    from .root_config import get_strike_step

    snapshot = await cache.snapshot()
    specs: list[SubscribeSpec] = []
    expirations = _next_expirations(n=3)

    RADIUS = 40  # strikes each side of ATM

    for root in MVP_WATCHLIST_ROOTS:
        state = snapshot.get(root) or {}
        spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot:
            continue

        # Per-root strike step (SPY=$1, SPX=$5, NDX=$25, etc.) via root_config
        step = get_strike_step(root, spot)
        atm = round(spot / step) * step
        strikes = [atm + i * step for i in range(-RADIUS, RADIUS + 1)]

        for exp in expirations:
            for k in strikes:
                for right in ("C", "P"):
                    specs.append(SubscribeSpec(
                        root=root,
                        expiration=exp,
                        strike_1000ths=int(k * 1000),
                        right=right,
                    ))

    return specs


# ── Detector ──────────────────────────────────────────────────────────


class SweepDetector:
    """Owns the rollup state and the consumer loop.

    Also forwards every non-filtered trade to an attached LiveFlowAggregator
    so broader Golden Flow detection runs in parallel with narrow ISO sweep
    rollups. Both detectors share the same stream subscription budget.
    """

    def __init__(
        self, stream: ThetaStream | None = None,
        flow_aggregator: LiveFlowAggregator | None = None,
    ):
        self.stream = stream or get_stream()
        self.flow_aggregator = flow_aggregator  # optional — None = sweep-only mode
        # Rollup bucket: key = (ticker, strike, exp_str, otype), value = SweepRollup
        self._buckets: dict[tuple[str, float, str, str], SweepRollup] = {}
        # Stats counters
        self.trades_seen = 0
        self.sweeps_seen = 0
        self.alerts_fired = 0

    def _bucket_key(self, trade: ThetaTrade) -> tuple[str, float, str, str]:
        return (trade.ticker, trade.strike, trade.expiration, trade.right)

    def _expire_windows(self) -> list[SweepRollup]:
        """Move all rollups older than ROLLUP_SECONDS into a flush list.

        Called periodically (every few seconds) and on shutdown. Returns the
        rollups that should be written to DB.
        """
        now = time.time()
        to_flush: list[SweepRollup] = []
        still_open: dict[tuple[str, float, str, str], SweepRollup] = {}
        for key, rollup in self._buckets.items():
            if now - rollup.window_start >= ROLLUP_SECONDS:
                to_flush.append(rollup)
            else:
                still_open[key] = rollup
        self._buckets = still_open
        return to_flush

    def _flush_rollup(self, rollup: SweepRollup, snapshot: dict | None = None) -> None:
        """Filter + persist a completed rollup. snapshot is the worker's cache
        snapshot passed in by the async flush loop so this method stays sync."""
        if rollup.total_notional < MIN_SWEEP_NOTIONAL:
            return
        if rollup.print_count < 1:
            return

        payload = rollup.to_alert_payload()

        # Pull GEX context + per-contract enrichment (OI, bid/ask, delta, IV)
        # from the async-fetched cache snapshot, if available.
        gex_info = None
        if snapshot:
            state = snapshot.get(rollup.ticker) or {}
            gex_info = {
                "king": state.get("king"),
                "floor": state.get("floor"),
                "ceiling": state.get("ceiling"),
                "signal": state.get("signal"),
                "regime": state.get("regime"),
            }
            payload["spot"] = state.get("actual_spot") or state.get("_spot")

            # Find the matching contract in the cached raw chain to pull
            # OI, bid, ask, delta, IV. Enables OI-based UI filtering.
            raw_by_exp = state.get("_raw_contracts") or {}
            chain = raw_by_exp.get(rollup.expiration) or []
            for c in chain:
                if (
                    c.get("strike") == rollup.strike
                    and (c.get("option_type") or "").lower() == rollup.option_type
                ):
                    greeks = c.get("greeks") or {}
                    payload["oi"] = c.get("open_interest")
                    payload["bid"] = c.get("bid")
                    payload["ask"] = c.get("ask")
                    payload["delta"] = greeks.get("delta")
                    payload["iv"] = greeks.get("mid_iv") or greeks.get("smv_vol")
                    break

        try:
            insert_sweep_alert(payload, gex_info)
            self.alerts_fired += 1
        except Exception as e:
            print(f"[SWEEP] insert failed: {e}")
            return

        # Log + Telegram
        print(
            f"[SWEEP] {rollup.ticker} ${rollup.strike:.0f}{rollup.option_type[0].upper()} "
            f"{rollup.expiration} "
            f"notional=${rollup.total_notional:,.0f} "
            f"contracts={rollup.total_contracts} venues={rollup.venue_count} "
            f"prints={rollup.print_count} avg=${rollup.avg_price:.2f}",
            flush=True,
        )

        if rollup.total_notional >= TELEGRAM_NOTIONAL:
            asyncio.create_task(self._send_telegram(rollup))

    async def _send_telegram(self, rollup: SweepRollup) -> None:
        """Telegram push for high-notional sweeps. Uses the existing
        rate-limited sender; SWEEP is its own category."""
        try:
            from .telegram import send
        except ImportError:
            return
        right_emoji = "🟢" if rollup.option_type == "call" else "🔴"
        text = (
            f"⚡ ISO SWEEP: {rollup.ticker}\n"
            f"{right_emoji} ${rollup.strike:.0f} {rollup.option_type.upper()} {rollup.expiration}\n"
            f"Notional: ${rollup.total_notional:,.0f}\n"
            f"Contracts: {rollup.total_contracts:,}\n"
            f"Venues: {rollup.venue_count} (multi-exchange = real sweep)\n"
            f"Prints: {rollup.print_count} in {ROLLUP_SECONDS}s window\n"
            f"Avg: ${rollup.avg_price:.2f}"
        )
        try:
            await send(text, ticker=rollup.ticker)
        except Exception as e:
            print(f"[SWEEP] telegram send failed: {e}")

    async def consume(self, stop_event: asyncio.Event) -> None:
        """Main consumer loop. Read trades off the stream, rollup, flush."""
        # Flush timer runs alongside the consumer so windows close on time.
        # Pulls one cache snapshot per flush cycle so all rollups in that
        # batch see consistent GEX context without blocking the consumer.
        async def flush_loop():
            while not stop_event.is_set():
                await asyncio.sleep(5.0)
                expired = self._expire_windows()
                if expired:
                    try:
                        snap = await cache.snapshot()
                    except Exception:
                        snap = None
                    for rollup in expired:
                        self._flush_rollup(rollup, snapshot=snap)
            # Final flush on shutdown — drain remaining windows
            remaining = list(self._buckets.values())
            self._buckets.clear()
            try:
                snap = await cache.snapshot()
            except Exception:
                snap = None
            for r in remaining:
                self._flush_rollup(r, snapshot=snap)

        flush_task = asyncio.create_task(flush_loop())

        try:
            async for trade in self.stream.trades():
                if stop_event.is_set():
                    break
                self.trades_seen += 1

                # Drop cancellations & non-ISO auctions at ingest — these don't
                # belong in EITHER detector (canceled = voided; non-ISO auctions
                # are crossed trades with no directional signal).
                if trade.is_excluded:
                    continue
                if trade.condition in NON_ISO_AUCTION_CONDITIONS:
                    continue

                # FORK 1: every qualifying trade feeds the live flow aggregator
                # (broader Golden Flow detection — catches non-ISO at-ask prints
                # that UW's "Bought" total also includes).
                if self.flow_aggregator is not None:
                    try:
                        self.flow_aggregator.add_trade(trade)
                    except Exception as e:
                        print(f"[SWEEP] flow_aggregator error: {e}")

                # FORK 2: ISO-only sweep rollup (existing narrow path, produces
                # flow_alerts.SWEEP conviction rows with 30s time-bucketing).
                if not trade.is_sweep:
                    continue

                self.sweeps_seen += 1
                key = self._bucket_key(trade)
                rollup = self._buckets.get(key)
                if rollup is None:
                    rollup = SweepRollup(
                        ticker=trade.ticker,
                        strike=trade.strike,
                        expiration=trade.expiration,
                        option_type=trade.right,
                        window_start=time.time(),
                    )
                    self._buckets[key] = rollup
                rollup.add(trade)
        finally:
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass


# ── Background task entry point (called from main.py lifespan) ──────────


async def run_sweep_detector(stop_event: asyncio.Event) -> None:
    """Top-level background task: start stream, subscribe, consume.

    Launches TWO detectors that share one stream subscription:
      - SweepDetector: narrow ISO-only rollups -> flow_alerts.SWEEP
      - LiveFlowAggregator: broader all-flow aggregation + Golden Flow
        transitions (fires Telegram + upserts to option_flow_daily)
    """
    settings = get_settings()
    if not settings.thetadata_sweep_enabled:
        print("[SWEEP] disabled via thetadata_sweep_enabled=False")
        return

    stream = get_stream()
    flow_aggregator = LiveFlowAggregator()
    detector = SweepDetector(stream=stream, flow_aggregator=flow_aggregator)

    # Start the WebSocket connection loop in its own task
    await stream.start()
    await asyncio.sleep(2.0)  # Give the connection time to come up

    # Wait for the worker to populate the ticker cache (subscription plan
    # needs spot prices to compute ATM strikes)
    for _ in range(24):  # up to 2 min
        snapshot = await cache.snapshot()
        if any(snapshot.get(t, {}).get("actual_spot") for t in ("SPY", "QQQ")):
            break
        await asyncio.sleep(5.0)

    # Build + send subscription plan
    specs = await _build_subscription_plan()
    print(f"[SWEEP] subscribing to {len(specs)} contracts via Theta stream")
    for spec in specs:
        await stream.subscribe(spec)
        # Trickle the sub requests so we don't overwhelm the Terminal
        await asyncio.sleep(0.005)

    # Launch the Golden Flow transition loop as a sibling task — runs in
    # parallel with the trade consumer, re-evaluates aggregates every 30s.
    golden_task = asyncio.create_task(
        run_golden_transition_loop(flow_aggregator, stop_event)
    )

    # Consume loop — runs until stop_event
    try:
        await detector.consume(stop_event)
    finally:
        golden_task.cancel()
        try:
            await asyncio.wait_for(golden_task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        await stream.stop()
        print(
            f"[SWEEP] shutdown — sweep: seen={detector.trades_seen} "
            f"iso={detector.sweeps_seen} rollups={detector.alerts_fired} | "
            f"flow: {flow_aggregator.stats()}"
        )
