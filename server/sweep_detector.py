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
    run_upside_bet_transition_loop,
)
from .tick_side_tracker import get_tracker as get_tick_side_tracker
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
TELEGRAM_NOTIONAL = 500_000    # $ — default alert threshold for Telegram push

# Mag7 tier: Telegram push fires at a lower threshold for AAPL/AMZN/GOOGL/etc.
# because (a) these names have deep-enough books that $200K in a 30s window is
# still institutional footprint, and (b) the AMZN-Anthropic precedent (2026-04-20)
# showed $168K single prints meaningfully predicted overnight catalysts.
TELEGRAM_NOTIONAL_MAG7 = 200_000


def _telegram_threshold(ticker: str) -> float:
    """Per-ticker Telegram push threshold for ISO sweeps. Mag7 tier is lower."""
    # Import here to avoid a hard circular dep at module load time.
    from .option_flow_daily import MAG7_ROOTS
    if ticker.upper() in MAG7_ROOTS:
        return TELEGRAM_NOTIONAL_MAG7
    return TELEGRAM_NOTIONAL


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
    """Return the next N expiration dates as YYYYMMDD ints.

    Expanded 2026-04-22 to include Tuesday + Thursday so SPX/SPXW daily
    expirations are captured on those days too (SPY/QQQ also have daily
    expirations now as of ~2022, and index products have them daily).

    Theta will silently ignore subscriptions to expirations that don't
    exist for a given root, so over-subscribing weekdays is safe — the
    benefit is never missing a 0DTE day on any product.

    We still skip weekends because no US options trade Sat/Sun.
    """
    import datetime
    today = datetime.date.today()
    dates: list[datetime.date] = []

    # Cover all weekdays in the next 14 calendar days. Daily-expiry index
    # products (SPX, SPXW, QQQ, SPY) expire every weekday; M/W/F-only
    # equities silently ignore T/Th subscriptions.
    for d in range(0, 14):
        candidate = today + datetime.timedelta(days=d)
        if candidate.weekday() < 5:  # Mon-Fri
            dates.append(candidate)
            if len(dates) >= n:
                break
    return [int(d.strftime("%Y%m%d")) for d in dates]


def _monthly_opex_expirations(n_monthlies: int = 2) -> list[int]:
    """Return the next N monthly opex dates (3rd Friday of each month).

    Added 2026-04-22 after missing Mir's SMH 15MAY 490C call at 11:28 AM.
    Root cause: the live Theta subscription only covered the next 3 daily
    expirations (via _next_expirations(n=3)) — never any monthly contracts.
    That blinded us to TAIL_FLOW activity which by rule is 3-45 DTE, much
    of which concentrates in monthlies on single-name equities.

    Theta silently ignores non-existent expirations, so subscribing to the
    3rd Friday of the next N months is safe — only real listings get data.
    """
    import datetime
    today = datetime.date.today()
    monthlies: list[datetime.date] = []
    year, month = today.year, today.month
    # Walk forward up to 6 months; collect up to n_monthlies opex dates
    for _ in range(6):
        # 3rd Friday = 1st of month + days-to-Friday + 14
        first = datetime.date(year, month, 1)
        days_to_fri = (4 - first.weekday()) % 7
        third_fri = first + datetime.timedelta(days=days_to_fri + 14)
        if third_fri > today:
            monthlies.append(third_fri)
            if len(monthlies) >= n_monthlies:
                break
        month += 1
        if month > 12:
            month = 1
            year += 1
    return [int(d.strftime("%Y%m%d")) for d in monthlies]


# Hardcoded MVP watchlist. Expansion: dynamically read from worker's Tier 1
# watchlist once worker has populated the cache (follow-up work).
#
# SPX/SPXW added 2026-04-18: SPX = monthly AM-settled, SPXW = weekly + 0DTE
# PM-settled. Both trade OPRA and support ISO sweeps. 0DTE SPXW is where
# most insider flow lives (UW's best-performing alert category).
MVP_WATCHLIST_ROOTS = [
    "SPY", "QQQ", "IWM", "DIA",                       # ETF indices (DIA added Apr 22)
    "SPX", "SPXW", "NDX", "RUT", "VIX",               # Cash-settled + vol (VIX added)
    "AAPL", "NVDA", "MSFT", "TSLA", "META", "AMZN", "GOOGL", "GOOG",  # mega-cap
    "AMD", "AVGO", "NFLX", "CRM", "ORCL",
    # Sector ETFs with active OPRA flow. SMH added 2026-04-22 after missing
    # Mir's SMH 15MAY 490C ~$2M tape print at 11:28 AM — it wasn't in any
    # subscription tier, so the Theta aggregator never saw the trade.
    "SMH",                                            # semi ETF
    # Universe-audit adds (2026-04-22) — tickers with ≥$100M weekly flow
    # that were invisible to the live Theta stream. Prioritized by catalyst
    # proximity (BA/INTC reporting this week) and flow notional.
    "UNH",    # healthcare mega-cap ($724M weekly flow)
    "INTC",   # Thursday AMC earnings ($596M flow, 12.8% implied)
    "BA",     # Wednesday BMO earnings ($141M flow)
    "LLY",    # healthcare mega-cap
    "XOM",    # energy mega-cap (Iran-sensitive)
    "GLD",    # gold ETF ($955M weekly — biggest non-index miss)
    "SLV",    # silver ETF ($346M weekly)
    "USO",    # oil ETF ($417M weekly)
    "IBIT",   # BTC ETF ($117M weekly)
    # Financials + consumer + China (added 2026-04-22 round 2)
    "JPM",    # financial mega-cap
    "GS",     # financial
    "MS",     # financial
    "BRK.B",  # Berkshire — ultra-liquid, news-sensitive
    "WMT",    # consumer staple mega-cap
    "BABA",   # China ADR — active options, news-driven
]

# Added 2026-04-20 after missing MRVL 165C 5/8 and FSLR 192.5C 4/24 signals:
# these Tier-3 thematic names have active institutional flow that the REST
# scanner catches too slowly. Streaming them lets GOLDEN / TAIL / UPSIDE_BET
# fire within 500ms instead of waiting for next chain-cache refresh.
#
# Tighter strike radius (±12 vs mega-cap ±40) keeps budget impact ~1,800
# contracts, fitting in the 15K-cap headroom.
#
# Selection criteria:
#   - Active options volume (≥100K avg daily)
#   - In current thematic baskets (AI silicon, power, fiber, neocloud, crypto, clean energy)
#   - Validated flow activity today or in past week (MRVL +5%, FSLR $1M print, etc.)
TIER2_THEMATIC_ROOTS = [
    # AI silicon / networking (missed MRVL 165C today)
    "MRVL", "ANET",
    # AI data center power (GEV/VRT rotation winners)
    "GEV", "VRT",
    # AI software / data (PLTR confluence + DELL A-grade today)
    "PLTR", "DELL", "PANW",
    # Data storage (SNDK NDX-100 inclusion, MU memory cycle)
    "SNDK", "WDC", "STX", "MU",
    # Semi equipment (added 2026-04-22 after missing ASML -5% news crash).
    # These are news-sensitive mega-caps with heavy option flow — the kind
    # of crashes the live Theta stream SHOULD catch via put sweep detection.
    "ASML", "LRCX", "KLAC", "AMAT", "TSM",
    # AI silicon momentum leaders (added 2026-04-22)
    "ALAB", "CRDO", "AEHR", "ARM",
    # Clean energy / solar (missed FSLR 192.5C today)
    "FSLR",
    # Crypto infrastructure (MSTR/COIN/HOOD momentum cohort)
    "MSTR", "COIN", "HOOD",
    # Neocloud (NVDA-reference customers, real flow activity)
    "NBIS",
    # ─── Universe-audit adds (2026-04-22) ─────────────────────────────
    # Tickers with $30M+ weekly flow that weren't in any sweep tier.
    # Prioritized for active options + thematic fit.
    # Semi equipment / analog peers
    "AMKR", "TXN",
    # AI connectivity / photonics (AAOI/GLW/COHR fiber optics layer).
    # LITE added 2026-04-22 from HeidingOut AI-ecosystem thesis — CPO lasers
    # and NVDA commitments. Pairs directly with AAOI/COHR in the photonics
    # leg of the Rubin/Groq LPX disaggregation thesis.
    "AAOI", "COHR", "GLW", "LITE",
    # AI power delivery (rack-density / 48V conversion — VRT already covers
    # cooling; VICR covers the power-module layer). Added 2026-04-22.
    "VICR",
    # Software mega-caps (sector mover signals)
    "NOW", "SNOW", "DDOG",
    # Space / defense satellites (pairs with BKSY already in Tier3)
    "RKLB", "ASTS",
    # Defense prime (missed today's -3.2% bear move)
    "LMT",
    # Alt-energy / fuel cells
    "BE",
    # Thematic momentum single-names (heavy retail + institutional interest)
    "OKLO",   # nuclear SMR (500% rip today on 75C weekly)
    "IONQ",   # quantum pure-play
    "HIMS",   # pharma momentum
    "AXTI",   # $227M/7d extreme concentration — smart money signal
]

# Strike coverage target for Tier-2 thematic names — percentage-based so
# $1-step stocks (MRVL, FSLR) get enough coverage for 15% OTM (UPSIDE_BET max).
# Fixed-count radius (12) was too tight: MRVL ±$12 = 8% OTM → missed 165C @ 11.6% OTM.
TIER2_OTM_COVERAGE_PCT = 0.15  # ±15% of spot
# Cap to prevent runaway strike counts on very high-priced tickers
TIER2_MAX_RADIUS = 30


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
    from .root_config import get_strike_step, is_index_root

    snapshot = await cache.snapshot()
    specs: list[SubscribeSpec] = []
    # Daily expirations (0DTE + 1-2 DTE index coverage) + monthly opex
    # (catches TAIL flow 3-45 DTE on single names). Combined list ~5-7 dates;
    # Theta silently ignores any that aren't listed for a given root.
    expirations = _next_expirations(n=3) + _monthly_opex_expirations(n_monthlies=2)

    # Per-root strike radius. Equities get ±40 (covers ±6% at $1 step for SPY-sized
    # names). Index products need wider radius in STRIKE count to cover same OTM %
    # because their step is 5-25x larger. SPX/SPXW at ±200 × $5 = ±$1000 = ±14% at
    # $7100 spot, which covers the full TAIL-FLOW OTM range (4-25%).
    #
    # Budget check:
    #   Equities:  15 tickers × 80 strikes × 2 rights × 3 exps ≈ 7,200
    #   SPX/SPXW:  2 roots × 400 strikes × 2 rights × 3 exps ≈ 4,800
    #   NDX/RUT:   2 roots × 80 strikes × 2 rights × 3 exps ≈ 960
    #   Total ≈ 12,960 / 15,000 cap
    RADIUS_EQUITY = 40
    RADIUS_INDEX = 200  # wider strike count for $5+ step index products

    # Count subscriptions per tier for logging + budget enforcement
    tier_counts: dict[str, int] = {"mvp": 0, "tier2": 0}

    def _subscribe_root(root: str, radius: int, tier_label: str) -> None:
        state = snapshot.get(root) or {}
        spot = state.get("actual_spot") or state.get("_spot") or 0
        if not spot:
            return
        step = get_strike_step(root, spot)
        atm = round(spot / step) * step
        strikes = [atm + i * step for i in range(-radius, radius + 1)]
        added = 0
        for exp in expirations:
            for k in strikes:
                for right in ("C", "P"):
                    specs.append(SubscribeSpec(
                        root=root,
                        expiration=exp,
                        strike_1000ths=int(k * 1000),
                        right=right,
                    ))
                    added += 1
        tier_counts[tier_label] = tier_counts.get(tier_label, 0) + added

    # MVP tier: indexes + mega-caps (wide strike radius)
    for root in MVP_WATCHLIST_ROOTS:
        radius = RADIUS_INDEX if root in ("SPX", "SPXW") else RADIUS_EQUITY
        _subscribe_root(root, radius, "mvp")

    # Tier-2 thematic: percentage-based radius so $1-step names (MRVL, FSLR)
    # get real 15% OTM coverage instead of just 8%. Capped to prevent runaway.
    for root in TIER2_THEMATIC_ROOTS:
        state = snapshot.get(root) or {}
        spot_t2 = state.get("actual_spot") or state.get("_spot") or 0
        if not spot_t2:
            continue
        step_t2 = get_strike_step(root, spot_t2)
        # How many steps does 15% of spot represent?
        radius_t2 = min(
            TIER2_MAX_RADIUS,
            max(12, int((spot_t2 * TIER2_OTM_COVERAGE_PCT) / step_t2) + 1),
        )
        _subscribe_root(root, radius_t2, "tier2")

    # Safety check — warn if we're approaching the 15K Standard-tier cap
    total = len(specs)
    print(
        f"[SWEEP] subscription plan: {total} contracts "
        f"(MVP={tier_counts['mvp']}, Tier2={tier_counts['tier2']}) "
        f"— budget 15,000, {15000 - total} headroom",
        flush=True,
    )
    if total > 14_500:
        print(
            f"[SWEEP] ⚠️ subscription count {total} near 15K cap — "
            f"consider reducing RADIUS_TIER2 or pruning TIER2_THEMATIC_ROOTS",
            flush=True,
        )

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
        # Tick-level side tracker — module singleton so flow_alerts can read it
        # without lifespan plumbing. Fed from the trade consume loop below.
        self.tick_side_tracker = get_tick_side_tracker()
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
        from .live_flow_aggregator import _fmt_strike
        print(
            f"[SWEEP] {rollup.ticker} {_fmt_strike(rollup.strike)}{rollup.option_type[0].upper()} "
            f"{rollup.expiration} "
            f"notional=${rollup.total_notional:,.0f} "
            f"contracts={rollup.total_contracts} venues={rollup.venue_count} "
            f"prints={rollup.print_count} avg=${rollup.avg_price:.2f}",
            flush=True,
        )

        if rollup.total_notional >= _telegram_threshold(rollup.ticker):
            asyncio.create_task(self._send_telegram(rollup))

    async def _send_telegram(self, rollup: SweepRollup) -> None:
        """Telegram push for high-notional sweeps. Uses the existing
        rate-limited sender; SWEEP is its own category. Gated on market
        hours + contract tradeable (2026-04-23) — ThetaData sometimes
        delivers late OPRA closing prints after hours; those are not
        actionable for the user."""
        from .alert_gates import should_send_alert
        ok, reason = should_send_alert(expiration=rollup.expiration)
        if not ok:
            print(f"[SWEEP] telegram gated ({reason}) — {rollup.ticker} {rollup.strike}{rollup.option_type[0].upper()}")
            return
        try:
            from .telegram import send
        except ImportError:
            return
        from .live_flow_aggregator import _fmt_strike
        right_emoji = "🟢" if rollup.option_type == "call" else "🔴"
        text = (
            f"⚡ ISO SWEEP: {rollup.ticker}\n"
            f"{right_emoji} {_fmt_strike(rollup.strike)} {rollup.option_type.upper()} {rollup.expiration}\n"
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

        # Diagnostic heartbeat (2026-04-22) — every 30s print trades_seen so
        # we can distinguish "stream alive but consumer stuck" from "no
        # trades arriving at all". Paired with ThetaStream msg_mix log.
        async def diag_heartbeat():
            last_trades = 0
            while not stop_event.is_set():
                await asyncio.sleep(30.0)
                delta = self.trades_seen - last_trades
                last_trades = self.trades_seen
                print(
                    f"[SWEEP] heartbeat — trades_seen={self.trades_seen} "
                    f"(+{delta}/30s)  stream_queue_size="
                    f"{self.stream._out_queue.qsize() if hasattr(self.stream, '_out_queue') else '?'}",
                    flush=True,
                )
                # Keep tick-side tracker bounded + log audit-ready stats.
                # fallback_rate is the dual-running signal we'll review weekly:
                # high rate = many strikes have <50c/60s tick coverage.
                try:
                    self.tick_side_tracker.prune_all()
                    ts = self.tick_side_tracker.stats()
                    print(
                        f"[TICK_SIDE] tracked={ts['tracked_contracts']} "
                        f"trades={ts['trades_seen']} lookups={ts['lookups']} "
                        f"fallback_rate={ts['fallback_rate']} "
                        f"top_active={ts['top_active']}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[TICK_SIDE] heartbeat error: {e}")

        diag_task = asyncio.create_task(diag_heartbeat())

        # Drain stale trades that accumulated in the queue BEFORE consume
        # started. Without this, the fast 10s-bar aggregator ingests 5-15
        # min of stale market data as if it were live, producing bogus
        # FLOW_LEADS_UP/DOWN signals for several minutes. 2026-04-22:
        # saw queue=7659 before fix; drains in ~100ms at startup.
        if hasattr(self.stream, "_out_queue"):
            drained = 0
            while not self.stream._out_queue.empty():
                try:
                    self.stream._out_queue.get_nowait()
                    drained += 1
                except asyncio.QueueEmpty:
                    break
            if drained > 0:
                print(f"[SWEEP] drained {drained} stale trades from queue pre-consume", flush=True)

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

                # FORK 0: feed the tick-side tracker. Cheap O(1) per trade.
                # Provides flow_alerts.py with a 60s rolling ASK/BID/MID side
                # so the snapshot-based _detect_side stops mislabeling strikes
                # after big institutional prints (INTC 5/15 $120C, 2026-05-08).
                try:
                    self.tick_side_tracker.add_trade(trade)
                except Exception as e:
                    print(f"[SWEEP] tick_side_tracker error: {e}")

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
            diag_task.cancel()
            for t in (flush_task, diag_task):
                try:
                    await t
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

    # Subscription lifecycle:
    #   Phase 1 (now): subscribe all roots currently in cache (indexes + any
    #                  Tier 1/2 already populated by warmup_indexes).
    #   Phase 2 (background, every 60s): re-build plan and subscribe any
    #                  new roots that are now cached but weren't before.
    #
    # This fixes the Tier2=0 race where _build_subscription_plan runs before
    # the worker's first full cycle has populated Tier 2 GEX state for names
    # like ARM/AEHR/CRDO. On 2026-04-23 this gap caused us to miss Mir's live
    # ARM 220C trade — ARM wasn't in the sweep subscription at all.
    subscribed_roots: set[str] = set()

    async def _subscribe_new_roots(label: str) -> tuple[int, int]:
        """Build plan + subscribe any roots not yet subscribed. Idempotent.
        Returns (specs_sent, roots_added)."""
        specs = await _build_subscription_plan()
        new_specs = [s for s in specs if s.root not in subscribed_roots]
        new_roots = {s.root for s in new_specs}
        if not new_roots:
            return 0, 0
        sent = 0
        failed = 0
        for spec in new_specs:
            if stop_event.is_set():
                break
            try:
                await stream.subscribe(spec)
                sent += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"[SWEEP] {label} subscribe failed: {e}")
            await asyncio.sleep(0.005)
        subscribed_roots.update(new_roots)
        print(
            f"[SWEEP] {label}: added {len(new_roots)} roots ({sorted(new_roots)[:8]}"
            f"{'...' if len(new_roots)>8 else ''}) — {sent} specs sent, {failed} failed"
        )
        return sent, len(new_roots)

    async def _subscribe_trickle() -> None:
        # Phase 1: immediate subscription for what's already cached
        await _subscribe_new_roots("phase1")
        # Phase 2: periodic catch-up for Tier 2 roots as they populate.
        # Also periodically clean up expired subscriptions to free budget
        # (critical at date-rollover — yesterday's 0DTE specs occupy slots
        # that block new tickers from being added).
        last_cleanup_date = None
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=60.0)
                break
            except asyncio.TimeoutError:
                pass
            try:
                # Run expired-subscription cleanup once per calendar day
                import datetime as _dt
                today = _dt.date.today().isoformat()
                if today != last_cleanup_date:
                    try:
                        removed = await stream.cleanup_expired_subscriptions()
                        last_cleanup_date = today
                        # Also forget those roots from subscribed_roots so
                        # phase2 re-adds them with fresh expirations
                        if removed > 0:
                            subscribed_roots.clear()
                    except Exception as e:
                        print(f"[SWEEP] expired-cleanup error: {e}")

                sent, added = await _subscribe_new_roots("phase2")
                if added == 0 and len(subscribed_roots) >= 50:
                    # Stable state — increase interval to reduce overhead
                    await asyncio.sleep(300)
            except Exception as e:
                print(f"[SWEEP] phase2 resubscribe error: {e}")

    subscribe_task = asyncio.create_task(_subscribe_trickle())

    # Launch the Golden Flow + UPSIDE_BET transition loops as sibling tasks.
    # Both run in parallel with the trade consumer, re-evaluating the shared
    # aggregator state every 30s. Independent one-shot dedupe per classifier.
    golden_task = asyncio.create_task(
        run_golden_transition_loop(flow_aggregator, stop_event)
    )
    upside_bet_task = asyncio.create_task(
        run_upside_bet_transition_loop(flow_aggregator, stop_event)
    )

    # Consume loop — runs NOW (parallel with subscribe). Trades flow from
    # whatever subscriptions have landed so far. Queue drains as it fills.
    try:
        await detector.consume(stop_event)
    finally:
        for t in (golden_task, upside_bet_task, subscribe_task):
            t.cancel()
        for t in (golden_task, upside_bet_task, subscribe_task):
            try:
                await asyncio.wait_for(t, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        await stream.stop()
        print(
            f"[SWEEP] shutdown — sweep: seen={detector.trades_seen} "
            f"iso={detector.sweeps_seen} rollups={detector.alerts_fired} | "
            f"flow: {flow_aggregator.stats()}"
        )
