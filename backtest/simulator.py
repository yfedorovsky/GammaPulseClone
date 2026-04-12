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
    date: datetime.date
    ticker: str
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
        self._spot_history: dict[str, list[float]] = {}  # ticker -> last 30 closes for parabolic detection

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

        # 2. Check existing positions for exit signals
        self._check_exits(ticker, date, spot, daily_high, daily_low, state)

        # Track spot history for parabolic detection
        if ticker not in self._spot_history:
            self._spot_history[ticker] = []
        self._spot_history[ticker].append(spot)
        if len(self._spot_history[ticker]) > 30:
            self._spot_history[ticker] = self._spot_history[ticker][-30:]

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
        score, grade, reasons = score_signal(state, direction, self._confluence_cache, self._spot_history.get(ticker))

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

        # Kelly sizing -- use actual BSM payoff ratio from ticker history
        ts = self.ticker_stats.get(ticker, TickerStats())
        win_pnls = [p for p in ts.pnls if p > 0]
        loss_pnls = [p for p in ts.pnls if p <= 0]
        actual_avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 46.3  # BSM default
        actual_avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 78.7  # BSM default
        ks = kelly_size(
            ts.win_rate, ts.tier,
            is_0dte=(contract["dte"] == 0),
            cb_level=self.circuit_breaker.level,
            avg_win=actual_avg_win,
            avg_loss=actual_avg_loss,
        )

        # Per-ticker EV gate: block tickers with negative expectancy (5+ trades)
        ticker_ev_blocked = False
        if ts.trades >= 5:
            ticker_ev = (ts.win_rate / 100 * actual_avg_win) - ((1 - ts.win_rate / 100) * actual_avg_loss)
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
            pos = Position(
                signal_id=self._signal_id,
                ticker=ticker,
                direction=direction,
                entry_date=date,
                entry_spot=spot,
                strike=contract["strike"],
                expiration=contract["expiration"],
                option_type=contract["option_type"],
                dte=contract["dte"],
                grade=grade,
                score=score,
                gate_label=gate["label"],
                kelly_pct=ks["size_pct"],
                target=contract["target"],
                stop=contract["stop"],
                rr_ratio=contract["rr_ratio"],
                signal_type=signal_type,
                reasons=reasons,
            )
            self.positions.append(pos)

        self.signals.append(record)
        self._daily_signals_count[day_key] = self._daily_signals_count.get(day_key, 0) + 1
        day_signals.append(record)

        return day_signals

    def _calc_option_pnl(
        self, pos: "Position", exit_spot: float, days_held: int,
    ) -> float:
        """Calculate option P&L using Black-Scholes repricing.

        Uses BSM to compute entry and exit option prices from the position's
        strike, DTE, IV, and spot movement. Far more accurate than the
        leverage approximation, especially on high-vol names.
        """
        iv = 0.25  # default
        # Try to get IV from the position's entry state
        for sr in self.signals:
            if sr.date == pos.entry_date and sr.ticker == pos.ticker and sr.traded:
                iv = sr.iv or 0.25
                break

        return estimate_option_pnl(
            entry_spot=pos.entry_spot,
            exit_spot=exit_spot,
            strike=pos.strike,
            entry_dte=pos.dte,
            days_held=days_held,
            iv=iv,
            option_type=pos.option_type,
        )

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

            # Track max favorable excursion (in option terms)
            fav_exit = high if pos.direction == "BULL" else low
            fav_opt = self._calc_option_pnl(pos, fav_exit, days_held)
            pos.max_favorable = max(pos.max_favorable, fav_opt)

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

            # Update the signal record
            for sr in self.signals:
                if sr.date == pos.entry_date and sr.ticker == pos.ticker and sr.traded:
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
        """Close all open positions at given spots (end of backtest)."""
        for pos in list(self.positions):
            spot = spots.get(pos.ticker, pos.entry_spot)
            if pos.direction == "BULL":
                pos.pnl_pct = ((spot - pos.entry_spot) / pos.entry_spot) * 100
            else:
                pos.pnl_pct = ((pos.entry_spot - spot) / pos.entry_spot) * 100
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
        }
