# region imports
from AlgorithmImports import *
from collections import defaultdict
from datetime import timedelta
# endregion


# ══════════════════════════════════════════════════════════════════════
#  GammaPulse SOE Backtest — Self-Contained QuantConnect Algorithm
# ══════════════════════════════════════════════════════════════════════

# ── Portable GEX Engine ───────────────────────────────────────────────

CONTRACT_SIZE = 100
PINNING_THRESHOLD = 0.003
SIGNIFICANCE_PCT = 0.03


def compute_levels(contracts, spot):
    per_strike = defaultdict(lambda: {"net_gex": 0.0, "net_vex": 0.0, "net_delta": 0.0, "iv_sum": 0.0, "iv_count": 0.0, "oi": 0.0})

    for opt in contracts:
        strike = float(opt.get("strike", 0))
        oi = float(opt.get("oi", 0))
        if strike <= 0 or oi <= 0:
            continue
        gamma = float(opt.get("gamma", 0))
        delta = float(opt.get("delta", 0))
        vega = float(opt.get("vega", 0))
        iv = float(opt.get("iv", 0))
        otype = str(opt.get("option_type", "")).lower()
        sign = 1.0 if otype == "call" else -1.0

        vanna = 0.0
        if vega != 0 and spot > 0:
            vanna = vega / spot

        gex = gamma * oi * CONTRACT_SIZE * spot * spot * 0.01 * sign
        vex = vanna * oi * CONTRACT_SIZE * spot * sign
        delta_s = delta * oi * CONTRACT_SIZE * sign

        b = per_strike[strike]
        b["net_gex"] += gex
        b["net_vex"] += vex
        b["net_delta"] += delta_s
        b["oi"] += oi
        if iv > 0:
            b["iv_sum"] += iv
            b["iv_count"] += 1

    if not per_strike:
        return None

    strikes_sorted = sorted(per_strike.keys())
    total_pos = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] > 0)
    total_neg = sum(b["net_gex"] for b in per_strike.values() if b["net_gex"] < 0)
    max_i = max((abs(b["net_gex"]) for b in per_strike.values()), default=1.0) or 1.0

    king_strike = max(per_strike.keys(), key=lambda s: abs(per_strike[s]["net_gex"]))
    king_val = per_strike[king_strike]["net_gex"]
    king_pos = king_val >= 0
    king_abs = abs(king_val) or 1
    sig_thresh = king_abs * SIGNIFICANCE_PCT

    floor_s = None
    ceil_s = None
    best_below = 0.0
    for s in strikes_sorted:
        if s == king_strike: continue
        g = per_strike[s]["net_gex"]
        if g <= 0: continue
        if s < spot and g > best_below:
            best_below = g
            floor_s = s
        elif s > spot and g >= sig_thresh:
            ceil_s = s

    if ceil_s is None:
        for s in strikes_sorted:
            if s > spot and s != king_strike and per_strike[s]["net_gex"] > 0:
                ceil_s = s
                break

    gk = sorted((s for s in strikes_sorted if s != king_strike), key=lambda s: abs(per_strike[s]["net_gex"]), reverse=True)[:6]

    neg_strikes = [(s, abs(per_strike[s]["net_gex"])) for s in strikes_sorted if per_strike[s]["net_gex"] < 0 and s < spot]
    if neg_strikes:
        wt_sum = sum(s * w for s, w in neg_strikes)
        wt_total = sum(w for _, w in neg_strikes)
        zgl = round(wt_sum / wt_total, 1) if wt_total else strikes_sorted[0]
        zgl = min(strikes_sorted, key=lambda s: abs(s - zgl))
    else:
        zgl = strikes_sorted[0]

    iv_cands = [(s, per_strike[s]) for s in strikes_sorted if per_strike[s]["iv_count"] > 0]
    iv_cands.sort(key=lambda p: abs(p[0] - spot))
    closest = iv_cands[:5]
    iv_avg = 0.0
    if closest:
        num = sum(b["iv_sum"] for _, b in closest)
        den = sum(b["iv_count"] for _, b in closest)
        if den > 0:
            iv_avg = num / den

    regime = "POS" if total_pos > abs(total_neg) else "NEG"

    if spot <= 0 or king_strike <= 0:
        signal = "PINNING"
    else:
        dist = abs(spot - king_strike) / spot
        if dist < PINNING_THRESHOLD:
            signal = "PINNING" if king_pos else "DANGER"
        elif king_pos:
            signal = "MAGNET UP" if king_strike > spot else "SUPPORT"
        else:
            signal = "AIR POCKET" if king_strike < spot else "RESISTANCE"

    strikes_out = []
    for s in strikes_sorted:
        b = per_strike[s]
        strikes_out.append({"strike": s, "net_gex": b["net_gex"], "net_vex": b["net_vex"], "ratio": abs(b["net_gex"]) / max_i})

    return {
        "strikes": strikes_out, "king": king_strike, "floor": floor_s or 0, "ceiling": ceil_s or 0,
        "zgl": zgl, "regime": regime, "signal": signal, "king_is_positive": king_pos,
        "iv": iv_avg, "pos_gex": total_pos, "neg_gex": total_neg, "gatekeepers": sorted(gk), "spot": spot,
    }


# ── SOE Scoring ───────────────────────────────────────────────────────

def score_to_grade(score, mx=8.0):
    p = score / mx
    if p >= 0.9: return "A+"
    if p >= 0.75: return "A"
    if p >= 0.625: return "B+"
    if p >= 0.5: return "B"
    return "C"

def determine_direction(state):
    sig = state.get("signal", "")
    if sig in ("MAGNET UP", "SUPPORT", "PINNING"): return "BULL"
    if sig in ("AIR POCKET", "RESISTANCE"): return "BEAR"
    return None

def score_signal(state, direction, confluence=None):
    score = 0.0
    reasons = []
    king = state.get("king", 0)
    floor_v = state.get("floor", 0)
    ceil_v = state.get("ceiling", 0)
    zgl = state.get("zgl", 0)
    spot = state.get("spot", 0)
    regime = state.get("regime", "")
    iv = state.get("iv", 0)
    kp = state.get("king_is_positive", True)
    strikes = state.get("strikes", [])
    if not spot or not king: return 0, "C", []
    kd = abs(king - spot) / spot

    if (direction == "BULL" and regime == "POS") or (direction == "BEAR" and regime == "NEG"):
        score += 1; reasons.append(f"Regime {regime} aligned")
    if direction == "BULL" and kp and king > spot:
        score += 1; reasons.append(f"King ${king} magnet")
    elif direction == "BEAR" and not kp and king < spot:
        score += 1; reasons.append(f"-GEX King ${king}")
    elif (direction == "BULL" and kp) or (direction == "BEAR" and not kp):
        score += 0.5
    if 0.005 <= kd <= 0.03:
        score += 1; reasons.append(f"Dist {kd*100:.1f}%")
    elif kd < 0.003:
        score += 0.5
    if direction == "BULL" and floor_v and floor_v < spot:
        score += 1; reasons.append(f"Floor ${floor_v}")
    elif direction == "BEAR" and ceil_v and ceil_v > spot:
        score += 1; reasons.append(f"Ceil ${ceil_v}")
    if zgl:
        if (direction == "BULL" and spot > zgl) or (direction == "BEAR" and spot < zgl):
            score += 1; reasons.append("ZGL ok")
    if iv:
        if iv < 0.25: score += 1; reasons.append(f"IV {iv*100:.0f}%")
        elif iv < 0.35: score += 0.5
    if confluence:
        bc = sum(1 for t in ["SPY","QQQ","IWM"] if confluence.get(t, {}).get("king_is_positive", True))
        if direction == "BULL" and bc >= 2: score += 1; reasons.append(f"Confl {bc}/3")
        elif direction == "BEAR" and bc <= 1: score += 1; reasons.append(f"Confl {3-bc}/3 bear")
    calls_above = [s for s in strikes if s.get("net_gex", 0) > 0 and s["strike"] > spot]
    puts_below = [s for s in strikes if s.get("net_gex", 0) > 0 and s["strike"] < spot]
    if calls_above:
        cw = max(calls_above, key=lambda s: abs(s.get("net_gex", 0)))["strike"]
        if direction == "BULL" and cw > king: score += 1; reasons.append(f"CW ${cw}")
    if puts_below:
        pw = min(puts_below, key=lambda s: abs(s.get("net_gex", 0)))["strike"]
        if direction == "BEAR" and pw < king: score += 1; reasons.append(f"PW ${pw}")

    return score, score_to_grade(score), reasons


# ══════════════════════════════════════════════════════════════════════
#  ALGORITHM — Start with 3 tickers for validation
# ══════════════════════════════════════════════════════════════════════

TICKERS = ["SPY", "QQQ", "NVDA"]
MIN_SCORE = 3.5


class GammaPulseSOE(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2025, 1, 1)
        self.set_end_date(2025, 4, 1)
        self.set_cash(100_000)

        self.equity_syms = {}
        self.option_syms = {}

        for t in TICKERS:
            eq = self.add_equity(t, Resolution.DAILY)
            eq.set_data_normalization_mode(DataNormalizationMode.RAW)
            self.equity_syms[t] = eq.symbol

            opt = self.add_option(t)
            opt.set_filter(lambda u: u.strikes(-15, 15).expiration(0, 45))
            self.option_syms[t] = opt.symbol

        self.positions = {}
        self.total_signals = 0
        self.total_traded = 0
        self.grade_wins = defaultdict(int)
        self.grade_losses = defaultdict(int)
        self.day_count = 0

    def on_data(self, data):
        self.day_count += 1

        # Only process once per day (skip if already ran today)
        today = self.time.date()

        # Build confluence
        confl = {}
        for idx in ["SPY", "QQQ"]:
            if idx in self.option_syms:
                st = self._get_gex(idx, data)
                if st:
                    confl[idx] = st

        # Process each ticker
        for t in TICKERS:
            st = self._get_gex(t, data)
            if not st:
                continue

            # Check exits first
            self._check_exit(t, today, st)

            # Generate signals
            if t in self.positions or len(self.positions) >= 5:
                continue

            d = determine_direction(st)
            if not d:
                continue

            sc, gr, reasons = score_signal(st, d, confl)
            if sc < MIN_SCORE:
                continue

            self.total_signals += 1
            spot = st["spot"]
            king = st["king"]

            if d == "BULL":
                target = king if king > spot else spot * 1.02
                stop = st.get("floor") or spot * 0.98
                if stop <= 0: stop = spot * 0.98
            else:
                target = king if king < spot else spot * 0.98
                stop = st.get("ceiling") or spot * 1.02
                if stop <= 0: stop = spot * 1.02

            rr = abs(target - spot) / max(abs(stop - spot), 0.01)

            self.positions[t] = {
                "entry_spot": spot, "target": target, "stop": stop,
                "direction": d, "grade": gr, "entry_date": today,
            }
            self.total_traded += 1

            self.log(f"ENTRY {gr} {t} {d} | ${spot:.2f} -> T:${target:.2f} S:${stop:.2f} | R:R {rr:.1f} | Score {sc}/8 | {'; '.join(reasons[:4])}")

    def _get_gex(self, ticker, data):
        if ticker not in self.option_syms:
            return None

        sym = self.option_syms[ticker]
        chains = data.option_chains
        if not chains:
            return None

        chain = chains.get(sym)
        if not chain:
            return None

        eq_sym = self.equity_syms.get(ticker)
        if not eq_sym or eq_sym not in self.securities:
            return None
        price = self.securities[eq_sym].price
        if not price or price <= 0:
            return None

        contracts = []
        for c in chain:
            try:
                g = c.greeks
                contracts.append({
                    "strike": float(c.strike),
                    "oi": float(c.open_interest),
                    "gamma": float(g.gamma) if g else 0,
                    "delta": float(g.delta) if g else 0,
                    "vega": float(g.vega) if g else 0,
                    "iv": float(c.implied_volatility) if c.implied_volatility else 0,
                    "option_type": "call" if c.right == OptionRight.CALL else "put",
                })
            except Exception:
                continue

        if len(contracts) < 5:
            return None

        return compute_levels(contracts, price)

    def _check_exit(self, ticker, today, state):
        if ticker not in self.positions:
            return
        pos = self.positions[ticker]
        spot = state["spot"]
        d = pos["direction"]

        exited = False
        reason = ""
        pnl = 0.0

        if d == "BULL":
            if spot >= pos["target"]:
                exited = True; reason = "TARGET"; pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
            elif spot <= pos["stop"]:
                exited = True; reason = "STOP"; pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
        else:
            if spot <= pos["target"]:
                exited = True; reason = "TARGET"; pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100
            elif spot >= pos["stop"]:
                exited = True; reason = "STOP"; pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100

        # Time-based exit: 14 days max hold
        days_held = (today - pos["entry_date"]).days
        if not exited and days_held >= 14:
            exited = True; reason = "TIME"
            if d == "BULL":
                pnl = ((spot - pos["entry_spot"]) / pos["entry_spot"]) * 100
            else:
                pnl = ((pos["entry_spot"] - spot) / pos["entry_spot"]) * 100

        if exited:
            won = pnl > 0
            gr = pos["grade"]
            if won:
                self.grade_wins[gr] += 1
            else:
                self.grade_losses[gr] += 1
            del self.positions[ticker]
            self.log(f"EXIT {'WIN' if won else 'LOSS'} {ticker} {reason} | P&L {pnl:+.1f}% | Grade {gr} | Held {days_held}d")

    def on_end_of_algorithm(self):
        self.log("")
        self.log("=" * 50)
        self.log("  GammaPulse SOE Backtest Results")
        self.log("=" * 50)
        self.log(f"  Days processed: {self.day_count}")
        self.log(f"  Signals: {self.total_signals} | Traded: {self.total_traded}")

        tw = sum(self.grade_wins.values())
        tl = sum(self.grade_losses.values())
        tt = tw + tl
        wr = (tw / tt * 100) if tt else 0
        self.log(f"  Wins: {tw} | Losses: {tl} | Win Rate: {wr:.1f}%")
        self.log(f"  Final: ${self.portfolio.total_portfolio_value:,.2f}")

        self.log("\n  By Grade:")
        for gr in ["A+", "A", "B+", "B", "C"]:
            w = self.grade_wins.get(gr, 0)
            l = self.grade_losses.get(gr, 0)
            t = w + l
            if t: self.log(f"    {gr:3s}  {w/t*100:5.1f}%  ({w}W/{l}L/{t}T)")
        self.log("=" * 50)
