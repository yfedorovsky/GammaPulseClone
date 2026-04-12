"""Trade simulation engine — replay historical data through the SOE scoring pipeline.

For each trading day:
  1. Load option chain snapshot → compute GEX levels
  2. Score signals → filter by threshold
  3. Run 5-factor gate → filter INVALID
  4. Track open positions → check exit ladder vs daily price action
  5. Log outcomes

All state is in-memory. No database, no server.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from .gex_engine import compute_levels
from .soe_scorer import (
    determine_direction,
    determine_signal_type,
    is_parabolic,
    score_signal,
    select_contract,
    MIN_SCORE_THRESHOLD,
)
from .discipline import (
    CircuitBreaker,
    TickerStats,
    check_exit_ladder,
    five_factor_gate,
    kelly_size,
)
from .pricing import estimate_option_pnl


@dataclass
class Position:
    """An open tracked position."""
    signal_id: int
    ticker: str
    direction: str  # "BULL" or "BEAR"
    entry_date: datetime.date
    entry_spot: float
    strike: float
    expiration: str
    option_type: str
    dte: int
    grade: str
    score: float
    gate_label: str
    kelly_pct: float
    target: float
    stop: float
    rr_ratio: float
    signal_type: str
    signal_date: datetime.date | None = None  # day signal was computed (T)
    entry_iv: float = 0.25  # IV at signal time for BSM repricing
    reasons: list[str] = field(default_factory=list)

    # Tracking
    max_favorable: float = 0.0  # best gain seen
    exit_date: datetime.date | None = None
    exit_spot: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0
    outcome: str = ""  # WIN | LOSS | EXPIRED


@dataclass
class SignalRecord:
    """A logged signal (whether traded or not)."""
    signal_id: int = 0
    date: datetime.date = None
    ticker: str = ""
    direction: str
    signal_type: str
    grade: str
    score: float
    gate_label: str
    gate_score: float
    kelly_pct: float
    strike: float
    expiration: str
    option_type: str
    dte: int
    target: float
    stop: float
    rr_ratio: float
    spot: float
    king: float
    floor: float
    ceiling: float
    regime: str
    iv: float
    reasons: list[str]
    traded: bool  # whether we actually opened a position
    is_parabolic: bool = False  # ticker was in parabolic mode at signal time
    outcome: str = ""
    pnl_pct: float = 0.0
    exit_reason: str = ""
    exit_date: str = ""
    max_favorable: float = 0.0


class BacktestEngine:
    """Run the SOE + discipline pipeline over historical data.

    Usage:
        engine = BacktestEngine()
        for date, ticker, chain_data, spot, daily_ohlc in data_iterator:
            engine.process_day(date, ticker, chain_data, spot, daily_ohlc)
        results = engine.get_results()
    """

    def __init__(
        self,
        account_value: float = 100_000,
        max_positions: int = 10,
        max_per_ticker: int = 2,
    ):
        self.account_value = account_value
        self.starting_value = account_value
        self.max_positions = max_positions
        self.max_per_ticker = max_per_ticker

        self.positions: list[Position] = []
        self.closed: list[Position] = []
        self.signals: list[SignalRecord] = []

        self.ticker_stats: dict[str, TickerStats] = {}
        self.circuit_breaker = CircuitBreaker()

        self._signal_id = 0
        self._confluence_cache: dict[str, dict] = {}
        self._daily_signals_count: dict[str, int] = {}
        self._spot_history: dict[str, list[float]] = {}
        # Pending signals: computed on day T, executed on day T+1
        # This prevents data leakage (using same-day chain + same-day price)
        self._pending_entries: list[dict] = []
        # Full spot history per ticker: {ticker: [(date, open, high, low, close), ...]}
        # Used for honest benchmark computation in results.py
        self._spot_series: dict[str, list[tuple]] = {}
        self._prev_gex_state: dict[str, dict] = {}  # ticker -> yesterday's GEX state

    def set_confluence(self, spy_state: dict, qqq_state: dict, iwm_state: dict) -> None:
        """Set the confluence data for the current day."""
        self._confluence_cache = {
            "SPY": spy_state,
            "QQQ": qqq_state,
            "IWM": iwm_state,
        }

    def process_day(
        self,
        date: datetime.date,
        ticker: str,
        chain_contracts: list[dict[str, Any]],
        spot: float,
        daily_high: float | None = None,
        daily_low: float | None = None,
        daily_open: float | None = None,
        available_expirations: list[str] | None = None,
        earnings_dates: dict[str, list[str]] | None = None,
    ) -> list[SignalRecord]:
        """Process one ticker for one day.

        Args:
            date: trading date
            ticker: symbol
            chain_contracts: list of option contracts with {strike, oi, gamma, delta, vega, option_type, ...}
            spot: closing spot price
            daily_high: intraday high (for exit ladder check)
            daily_low: intraday low (for exit ladder check)
            available_expirations: list of "YYYY-MM-DD" expiration dates
            earnings_dates: {ticker: [date_str, ...]} for toxic list check

        Returns: list of signals generated this day for this ticker
        """
        if not chain_contracts or not spot:
            return []

        # 1. Compute GEX levels
        state = compute_levels(chain_contracts, spot)
        state["spot"] = spot

        # 2. Execute pending entries from YESTERDAY's signal (T+1 entry)
        # Uses TODAY'S OPEN price, not close, for realistic fill
        entry_price = daily_open if daily_open and daily_open > 0 else spot
        self._execute_pending_entries(ticker, date, entry_price)

        # 3. Check existing positions for exit signals
        self._check_exits(ticker, date, spot, daily_high, daily_low, state)

        # Track spot history for parabolic detection
        if ticker not in self._spot_history:
            self._spot_history[ticker] = []
        self._spot_history[ticker].append(spot)
        if len(self._spot_history[ticker]) > 30:
            self._spot_history[ticker] = self._spot_history[ticker][-30:]

        # Record full spot series for benchmark computation
        if ticker not in self._spot_series:
            self._spot_series[ticker] = []
        self._spot_series[ticker].append((
            date.isoformat(),
            daily_open or 0,
            daily_high or spot,
            daily_low or spot,
            spot,  # close
        ))

        # 3. Generate new signals
        day_signals = []

        # Skip if circuit breaker blocks
        if self.circuit_breaker.is_blocked():
            return day_signals

        # Dedup: max 1 signal per ticker per day
        day_key = f"{date.isoformat()}:{ticker}"
        if self._daily_signals_count.get(day_key, 0) >= 1:
            return day_signals

        direction = determine_direction(state)
        if direction is None:
            return day_signals

        # Score (with spot history for parabolic detection)
        # Score with full context: confluence, spot history, previous GEX state
        score, grade, reasons = score_signal(
            state, direction,
            confluence=self._confluence_cache,
            spot_history=self._spot_history.get(ticker),
            prev_state=self._prev_gex_state.get(ticker),
        )

        # Save current GEX state for tomorrow's dGEX comparison
        self._prev_gex_state[ticker] = {
            "king": state.get("king", 0),
            "neg_gex": state.get("neg_gex", 0),
            "pos_gex": state.get("pos_gex", 0),
            "iv": state.get("iv", 0),
            "regime": state.get("regime", ""),
        }

        if score < MIN_SCORE_THRESHOLD:
            return day_signals

        # Contract selection
        exps = available_expirations or []
        contract = select_contract(state, direction, exps, trade_date=date)
        if not contract:
            return day_signals

        signal_type = determine_signal_type(state, direction)

        # Build signal dict for gate
        sig_dict = {
            "ticker": ticker,
            "grade": grade,
            "score": score,
            "direction": direction,
            "dte": contract["dte"],
            "expiration": contract["expiration"],
        }

        # 5-factor gate
        gate = five_factor_gate(sig_dict, flow_confirmed=None, earnings_dates=earnings_dates, trade_date=date)

        # FIXED SIZING: 1.5% of account per trade (validation phase)
        # Kelly suspended per ChatGPT/Perplexity review:
        # - inputs too noisy for Kelly to be meaningful
        # - payoff ratio b<1 makes Kelly output unstable
        # - 1.5% = ~$1,500 on $100K, enough for real execution feedback
        ts = self.ticker_stats.get(ticker, TickerStats())
        FIXED_SIZE_PCT = 1.5
        ks = {"size_pct": FIXED_SIZE_PCT, "capped_by": "FIXED_VALIDATION", "kelly_raw": 0, "quarter_kelly": 0}

        # Per-ticker EV gate: block tickers with negative expectancy (5+ trades)
        ticker_ev_blocked = False
        if ts.trades >= 5:
            t_win_pnls = [p for p in ts.pnls if p > 0]
            t_loss_pnls = [p for p in ts.pnls if p <= 0]
            t_avg_win = (sum(t_win_pnls) / len(t_win_pnls)) if t_win_pnls else 0
            t_avg_loss = abs(sum(t_loss_pnls) / len(t_loss_pnls)) if t_loss_pnls else 100
            ticker_ev = (ts.win_rate / 100 * t_avg_win) - ((1 - ts.win_rate / 100) * t_avg_loss)
            if ticker_ev < 0:
                ticker_ev_blocked = True

        # Determine if we trade
        traded = False
        if ticker_ev_blocked:
            pass  # skip -- negative expectancy on this ticker
        elif gate["label"] != "INVALID" and not gate["earnings_blocked"]:
            if len(self.positions) < self.max_positions:
                ticker_positions = sum(1 for p in self.positions if p.ticker == ticker)
                if ticker_positions < self.max_per_ticker:
                    traded = True

        self._signal_id += 1

        record = SignalRecord(
            signal_id=self._signal_id,
            date=date,
            ticker=ticker,
            direction=direction,
            signal_type=signal_type,
            grade=grade,
            score=score,
            gate_label=gate["label"],
            gate_score=gate["score"],
            kelly_pct=ks["size_pct"],
            strike=contract["strike"],
            expiration=contract["expiration"],
            option_type=contract["option_type"],
            dte=contract["dte"],
            target=contract["target"],
            stop=contract["stop"],
            rr_ratio=contract["rr_ratio"],
            spot=spot,
            king=state.get("king", 0),
            floor=state.get("floor", 0),
            ceiling=state.get("ceiling", 0),
            regime=state.get("regime", ""),
            iv=state.get("iv", 0),
            reasons=reasons,
            traded=traded,
            is_parabolic=is_parabolic(self._spot_history.get(ticker)),
        )

        if traded:
            # Queue for T+1 entry (prevents data leakage)
            # Signal computed from today's EOD chain, entry at tomorrow's open
            self._pending_entries.append({
                "signal_id": self._signal_id,
                "ticker": ticker,
                "direction": direction,
                "signal_date": date,  # day signal was generated
                "entry_spot": spot,  # will be updated to T+1 open price
                "strike": contract["strike"],
                "expiration": contract["expiration"],
                "option_type": contract["option_type"],
                "dte": contract["dte"],
                "grade": grade,
                "score": score,
                "gate_label": gate["label"],
                "kelly_pct": ks["size_pct"],
                "target": contract["target"],
                "stop": contract["stop"],
                "rr_ratio": contract["rr_ratio"],
                "signal_type": signal_type,
                "reasons": reasons,
                "iv": state.get("iv", 0),
            })

        self.signals.append(record)
        self._daily_signals_count[day_key] = self._daily_signals_count.get(day_key, 0) + 1
        day_signals.append(record)

        return day_signals

    def _calc_option_pnl(
        self, pos: "Position", exit_spot: float, days_held: int,
    ) -> float:
        """Calculate option P&L using Black-Scholes repricing.

        Uses pos.entry_iv directly (stored at signal time) instead of
        trying to match by date which was broken (signal_date != entry_date).
        """
        iv = pos.entry_iv or 0.25

        return estimate_option_pnl(
            entry_spot=pos.entry_spot,
            exit_spot=exit_spot,
            strike=pos.strike,
            entry_dte=pos.dte,
            days_held=days_held,
            iv=iv,
            option_type=pos.option_type,
        )

    def _execute_pending_entries(self, ticker: str, date: datetime.date, spot: float) -> None:
        """Execute pending entries from yesterday's signals at today's open price.

        This enforces strict T+1 execution: signal from day T chain data,
        entry at day T+1 open. Prevents data leakage.
        """
        remaining = []
        for pending in self._pending_entries:
            if pending["ticker"] != ticker:
                remaining.append(pending)
                continue

            # Enter at today's open (approximated by today's spot for daily data)
            # In production, this would be the actual open price
            pos = Position(
                signal_id=pending["signal_id"],
                ticker=ticker,
                direction=pending["direction"],
                entry_date=date,  # T+1 (today), not signal date
                entry_spot=spot,  # today's open, not yesterday's close
                strike=pending["strike"],
                expiration=pending["expiration"],
                option_type=pending["option_type"],
                dte=max(pending["dte"] - 1, 0),  # one day less DTE
                grade=pending["grade"],
                score=pending["score"],
                signal_date=pending["signal_date"],  # day T (when signal was computed)
                entry_iv=pending.get("iv", 0.25),    # IV from signal day chain
                gate_label=pending["gate_label"],
                kelly_pct=pending["kelly_pct"],
                target=pending["target"],
                stop=pending["stop"],
                rr_ratio=pending["rr_ratio"],
                signal_type=pending["signal_type"],
                reasons=pending["reasons"],
            )
            self.positions.append(pos)

            # Update the signal record with actual entry price
            for sr in self.signals:
                if sr.signal_id == pending["signal_id"]:
                    sr.spot = spot  # update to actual entry price
                    break

        self._pending_entries = remaining

    def _check_exits(
        self,
        ticker: str,
        date: datetime.date,
        spot: float,
        daily_high: float | None,
        daily_low: float | None,
        state: dict[str, Any],
    ) -> None:
        """Check all open positions in this ticker for exit conditions."""
        high = daily_high or spot
        low = daily_low or spot

        to_close = []
        for pos in self.positions:
            if pos.ticker != ticker:
                continue

            is_0dte = False
            days_held = (date - pos.entry_date).days
            remaining_dte = max(0, pos.dte - days_held)

            try:
                exp_date = datetime.date.fromisoformat(pos.expiration)
                is_0dte = exp_date == date
                if date > exp_date:
                    pos.exit_date = date
                    pos.exit_spot = spot
                    pos.exit_reason = "EXPIRED"
                    pos.outcome = "LOSS"
                    pos.pnl_pct = -100  # option expires worthless
                    to_close.append(pos)
                    continue
            except ValueError:
                pass

            # TIME STOP: close at 40% of DTE if not profitable
            # Long options bleed theta -- don't hold losers hoping for reversal
            if pos.dte > 0 and days_held >= pos.dte * 0.4:
                current_pnl = self._calc_option_pnl(pos, spot, days_held)
                if current_pnl <= 0:
                    pos.exit_date = date
                    pos.exit_spot = spot
                    pos.exit_reason = "TIME_STOP"
                    pos.pnl_pct = current_pnl
                    pos.outcome = "LOSS"
                    to_close.append(pos)
                    continue

            # Track max favorable excursion (in option terms)
            fav_exit = high if pos.direction == "BULL" else low
            fav_opt = self._calc_option_pnl(pos, fav_exit, days_held)
            pos.max_favorable = max(pos.max_favorable, fav_opt)

            # PESSIMISTIC SAME-BAR RULE (Gemini/ChatGPT):
            # If both stop and target could be hit in the same bar,
            # assume STOP FIRST (worst case). This prevents fake edge.
            both_hit_bull = pos.direction == "BULL" and high >= pos.target and low <= pos.stop
            both_hit_bear = pos.direction == "BEAR" and low <= pos.target and high >= pos.stop
            if both_hit_bull or both_hit_bear:
                pos.exit_date = date
                pos.exit_spot = pos.stop
                pos.exit_reason = "STOP_HIT_PESSIMISTIC"
                pos.outcome = "LOSS"
                pos.pnl_pct = self._calc_option_pnl(pos, pos.stop, days_held)
                to_close.append(pos)
                continue

            # Check target hit (spot reaches target price)
            if pos.direction == "BULL" and high >= pos.target:
                pos.exit_date = date
                pos.exit_spot = pos.target
                pos.exit_reason = "TARGET_HIT"
                pos.outcome = "WIN"
                pos.pnl_pct = self._calc_option_pnl(pos, pos.target, days_held)
                to_close.append(pos)
                continue

            if pos.direction == "BEAR" and low <= pos.target:
                pos.exit_date = date
                pos.exit_spot = pos.target
                pos.exit_reason = "TARGET_HIT"
                pos.outcome = "WIN"
                pos.pnl_pct = self._calc_option_pnl(pos, pos.target, days_held)
                to_close.append(pos)
                continue

            # Check stop hit
            if pos.direction == "BULL" and low <= pos.stop:
                pos.exit_date = date
                pos.exit_spot = pos.stop
                pos.exit_reason = "STOP_HIT"
                pos.outcome = "LOSS"
                pos.pnl_pct = self._calc_option_pnl(pos, pos.stop, days_held)
                to_close.append(pos)
                continue

            if pos.direction == "BEAR" and high >= pos.stop:
                pos.exit_date = date
                pos.exit_spot = pos.stop
                pos.exit_reason = "STOP_HIT"
                pos.outcome = "LOSS"
                pos.pnl_pct = self._calc_option_pnl(pos, pos.stop, days_held)
                to_close.append(pos)
                continue

            # 0DTE force exit at close
            if is_0dte:
                pos.exit_date = date
                pos.exit_spot = spot
                pos.pnl_pct = self._calc_option_pnl(pos, spot, days_held)
                pos.exit_reason = "0DTE_CLOSE"
                pos.outcome = "WIN" if pos.pnl_pct > 0 else "LOSS"
                to_close.append(pos)

        for pos in to_close:
            self.positions.remove(pos)
            self.closed.append(pos)

            # Update stats
            if pos.ticker not in self.ticker_stats:
                self.ticker_stats[pos.ticker] = TickerStats()
            self.ticker_stats[pos.ticker].record(pos.pnl_pct, pos.outcome == "WIN")
            self.circuit_breaker.record_outcome(pos.outcome == "WIN")

            # Update the signal record by signal_id (not date -- dates differ T vs T+1)
            for sr in self.signals:
                if sr.signal_id == pos.signal_id:
                    sr.outcome = pos.outcome
                    sr.pnl_pct = pos.pnl_pct
                    sr.exit_reason = pos.exit_reason
                    sr.exit_date = pos.exit_date.isoformat() if pos.exit_date else ""
                    sr.max_favorable = pos.max_favorable
                    break

            # Account update
            position_value = self.account_value * (pos.kelly_pct / 100)
            self.account_value += position_value * (pos.pnl_pct / 100)

    def force_close_all(self, date: datetime.date, spots: dict[str, float]) -> None:
        """Close all open positions at given spots (end of backtest).
        Uses BSM repricing consistent with all other exits."""
        for pos in list(self.positions):
            spot = spots.get(pos.ticker, pos.entry_spot)
            days_held = (date - pos.entry_date).days
            pos.pnl_pct = self._calc_option_pnl(pos, spot, days_held)
            pos.exit_date = date
            pos.exit_spot = spot
            pos.exit_reason = "BACKTEST_END"
            pos.outcome = "WIN" if pos.pnl_pct > 0 else "LOSS"
            self.positions.remove(pos)
            self.closed.append(pos)

    def get_results(self) -> dict[str, Any]:
        """Return all data for analysis."""
        return {
            "signals": self.signals,
            "closed_positions": self.closed,
            "open_positions": self.positions,
            "ticker_stats": {k: {"trades": v.trades, "wins": v.wins, "win_rate": v.win_rate, "tier": v.tier} for k, v in self.ticker_stats.items()},
            "account_value": self.account_value,
            "starting_value": self.starting_value,
            "return_pct": ((self.account_value - self.starting_value) / self.starting_value) * 100,
            "circuit_breaker": {"losses": self.circuit_breaker.consecutive_losses, "level": self.circuit_breaker.level},
            "spots_data": self._spot_series,  # full price history for honest benchmarks
        }
