"""QuantConnect Algorithm — GammaPulse SOE Backtest.

Deploy this to QuantConnect's cloud to backtest against their historical
options chain data (OI + Greeks, back to 2012+).

Usage in QuantConnect:
  1. Create a new algorithm (Python)
  2. Paste this file's contents
  3. Upload gex_engine.py, soe_scorer.py, discipline.py as library files
  4. Set start/end dates in the Initialize method
  5. Run backtest

This runs in LOGGING MODE by default — generates signals and tracks outcomes
without placing actual orders. Set PAPER_TRADE = True to simulate fills.
"""

# ── QuantConnect Algorithm ─────────────────────────────────────────────
# Uncomment the QCAlgorithm imports when running in QuantConnect's cloud.
# Locally, this file serves as a reference/template.

PAPER_TRADE = False  # Set True to simulate order fills

# When running locally, these imports won't resolve — that's expected.
# QuantConnect provides them in their cloud environment.
try:
    from AlgorithmImports import *
except ImportError:
    pass  # Running locally for reference

# These are our portable modules — upload them as library files in QC
from backtest.gex_engine import compute_levels
from backtest.soe_scorer import (
    determine_direction,
    determine_signal_type,
    score_signal,
    select_contract,
    MIN_SCORE_THRESHOLD,
    score_to_grade,
)
from backtest.discipline import (
    CircuitBreaker,
    TickerStats,
    five_factor_gate,
    kelly_size,
)


# Ticker universe
TICKERS = [
    "SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL",
    "AMD", "AVGO", "CRM", "NFLX", "COIN", "PLTR", "UBER", "SQ", "SHOP",
    "BA", "JPM",
]


class GammaPulseSOE(QCAlgorithm):
    """GammaPulse SOE signal backtester for QuantConnect."""

    def Initialize(self):
        # ── Backtest window ──
        self.SetStartDate(2024, 4, 1)
        self.SetEndDate(2026, 4, 1)
        self.SetCash(100_000)

        # ── Universe ──
        self.symbols = {}
        self.option_symbols = {}
        for ticker in TICKERS:
            equity = self.AddEquity(ticker, Resolution.Daily)
            equity.SetDataNormalizationMode(DataNormalizationMode.Raw)
            self.symbols[ticker] = equity.Symbol

            # Add options universe for each equity
            option = self.AddOption(ticker, Resolution.Daily)
            option.SetFilter(-20, 20, 0, 60)  # ±20 strikes, 0-60 DTE
            self.option_symbols[ticker] = option.Symbol

        # ── State ──
        self.ticker_stats: dict[str, TickerStats] = {}
        self.circuit_breaker = CircuitBreaker()
        self.open_positions: dict[str, dict] = {}  # ticker → position info
        self.signal_log: list[dict] = []
        self.daily_processed: set[str] = set()

        # ── Schedule ──
        # Process at 3:30 PM to have full day's chain data
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.At(15, 30),
            self.ProcessSignals,
        )

    def ProcessSignals(self):
        """Main daily processing — called at 3:30 PM each trading day."""
        today = self.Time.date()
        date_key = today.isoformat()

        # Build confluence from index tickers
        confluence = {}
        for idx in ["SPY", "QQQ", "IWM"]:
            if idx in self.symbols:
                state = self._get_gex_state(idx)
                if state:
                    confluence[idx] = state

        # Process each ticker
        for ticker in TICKERS:
            day_key = f"{date_key}:{ticker}"
            if day_key in self.daily_processed:
                continue

            state = self._get_gex_state(ticker)
            if not state:
                continue

            self._check_exits(ticker, today, state)
            self._generate_signal(ticker, today, state, confluence)
            self.daily_processed.add(day_key)

    def _get_gex_state(self, ticker: str) -> dict | None:
        """Extract option chain data and compute GEX levels."""
        if ticker not in self.option_symbols:
            return None

        chain = self.CurrentSlice.OptionChains.get(self.option_symbols[ticker])
        if not chain:
            return None

        equity_price = self.Securities[self.symbols[ticker]].Price
        if not equity_price or equity_price <= 0:
            return None

        # Convert QC chain to our contract format
        contracts = []
        for contract in chain:
            contracts.append({
                "strike": float(contract.Strike),
                "oi": float(contract.OpenInterest),
                "gamma": float(contract.Greeks.Gamma) if contract.Greeks else 0,
                "delta": float(contract.Greeks.Delta) if contract.Greeks else 0,
                "vega": float(contract.Greeks.Vega) if contract.Greeks else 0,
                "iv": float(contract.ImpliedVolatility) if contract.ImpliedVolatility else 0,
                "option_type": "call" if contract.Right == OptionRight.Call else "put",
                "volume": float(contract.Volume),
                "bid": float(contract.BidPrice),
                "ask": float(contract.AskPrice),
                "last": float(contract.LastPrice),
                "expiration": contract.Expiry.strftime("%Y-%m-%d"),
            })

        if not contracts:
            return None

        state = compute_levels(contracts, equity_price)
        state["spot"] = equity_price
        return state

    def _generate_signal(self, ticker: str, today, state: dict, confluence: dict):
        """Score and potentially trade a signal."""
        if self.circuit_breaker.is_blocked():
            return

        direction = determine_direction(state)
        if not direction:
            return

        score, grade, reasons = score_signal(state, direction, confluence)
        if score < MIN_SCORE_THRESHOLD:
            return

        # Available expirations
        exps = sorted(set(c.get("expiration", "") for c in state.get("_raw_contracts", [])))
        if not exps:
            # Fallback: generate some reasonable expirations
            import datetime
            exps = [(today + datetime.timedelta(days=d)).isoformat() for d in [7, 14, 21, 28]]

        contract = select_contract(state, direction, exps, trade_date=today)
        if not contract:
            return

        signal_type = determine_signal_type(state, direction)

        sig = {
            "ticker": ticker,
            "grade": grade,
            "score": score,
            "direction": direction,
            "dte": contract["dte"],
            "expiration": contract["expiration"],
        }

        gate = five_factor_gate(sig, flow_confirmed=None, trade_date=today)
        ts = self.ticker_stats.get(ticker, TickerStats())
        ks = kelly_size(ts.win_rate, ts.tier, is_0dte=(contract["dte"] == 0), cb_level=self.circuit_breaker.level)

        traded = gate["label"] != "INVALID" and not gate["earnings_blocked"]
        traded = traded and ticker not in self.open_positions
        traded = traded and len(self.open_positions) < 10

        log_entry = {
            "date": today.isoformat(),
            "ticker": ticker,
            "direction": direction,
            "signal_type": signal_type,
            "grade": grade,
            "score": score,
            "gate": gate["label"],
            "gate_score": gate["score"],
            "kelly_pct": ks["size_pct"],
            "spot": state["spot"],
            "king": state.get("king", 0),
            "target": contract["target"],
            "stop": contract["stop"],
            "rr": contract["rr_ratio"],
            "strike": contract["strike"],
            "expiration": contract["expiration"],
            "option_type": contract["option_type"],
            "traded": traded,
            "reasons": reasons,
        }
        self.signal_log.append(log_entry)

        if traded:
            self.open_positions[ticker] = {
                "entry_date": today,
                "entry_spot": state["spot"],
                "target": contract["target"],
                "stop": contract["stop"],
                "direction": direction,
                "grade": grade,
                "kelly_pct": ks["size_pct"],
                "expiration": contract["expiration"],
            }
            self.Log(f"SIGNAL: {grade} {ticker} {direction} {signal_type} | Score: {score}/8 | Gate: {gate['label']} | Size: {ks['size_pct']}%")

    def _check_exits(self, ticker: str, today, state: dict):
        """Check open positions for exit conditions."""
        if ticker not in self.open_positions:
            return

        pos = self.open_positions[ticker]
        spot = state["spot"]

        exited = False
        reason = ""
        pnl = 0.0

        # Target hit
        if pos["direction"] == "BULL" and spot >= pos["target"]:
            exited = True
            reason = "TARGET"
            pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
        elif pos["direction"] == "BEAR" and spot <= pos["target"]:
            exited = True
            reason = "TARGET"
            pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100

        # Stop hit
        if not exited:
            if pos["direction"] == "BULL" and spot <= pos["stop"]:
                exited = True
                reason = "STOP"
                pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
            elif pos["direction"] == "BEAR" and spot >= pos["stop"]:
                exited = True
                reason = "STOP"
                pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100

        # Expiration
        if not exited:
            import datetime
            try:
                exp = datetime.date.fromisoformat(pos["expiration"])
                if today >= exp:
                    exited = True
                    reason = "EXPIRED"
                    if pos["direction"] == "BULL":
                        pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
                    else:
                        pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100
            except ValueError:
                pass

        if exited:
            outcome = "WIN" if pnl > 0 else "LOSS"
            self.Log(f"EXIT: {ticker} {reason} | P&L: {pnl:+.1f}% | Grade: {pos['grade']}")

            del self.open_positions[ticker]

            if ticker not in self.ticker_stats:
                self.ticker_stats[ticker] = TickerStats()
            self.ticker_stats[ticker].record(pnl, outcome == "WIN")
            self.circuit_breaker.record_outcome(outcome == "WIN")

    def OnEndOfAlgorithm(self):
        """Print final stats at end of backtest."""
        total = len(self.signal_log)
        traded = [s for s in self.signal_log if s["traded"]]
        self.Log(f"\n{'='*60}")
        self.Log(f"GammaPulse SOE Backtest Complete")
        self.Log(f"Total signals: {total} | Traded: {len(traded)}")
        self.Log(f"{'='*60}")

        # Win rate by grade
        for grade in ["A+", "A", "B+", "B", "C"]:
            subset = [s for s in traded if s["grade"] == grade]
            if not subset:
                continue
            # We'd need exit data here — log it for now
            self.Log(f"  {grade}: {len(subset)} signals traded")

        # Ticker stats
        for ticker, stats in sorted(self.ticker_stats.items(), key=lambda x: x[1].trades, reverse=True)[:10]:
            self.Log(f"  {ticker}: {stats.trades}T / {stats.wins}W / {stats.win_rate:.1f}% WR / {stats.tier}")

        self.Log(f"Circuit Breaker: {self.circuit_breaker.consecutive_losses} consecutive losses, level {self.circuit_breaker.level}")
