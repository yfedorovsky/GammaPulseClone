"""SPY/QQQ Scalp Alert System — Structure-based intraday alerts.

Separate from SOE signal engine. Runs every 30 seconds and fires
Telegram alerts when price interacts with GEX structural levels.

4-LLM consensus (ChatGPT + Perplexity + Gemini + Grok, April 14 2026):
  - 1DTE default for PM entries (1:30-3:00), 0DTE only Power Hour (3:00+)
  - VIX filter: >30 skip all, 25-30 1DTE only, <25 normal
  - +25% partial exit (tracked in paper_trading.py)
  - 2 total daily cap across SPY+QQQ combined
  - ZGL_CROSS demoted to context/bias tag (no daily cap charge)
  - Macro skip time-windowed (not all-day)

Trigger conditions:
  - BUY_DIP: bounce off Floor (BUY CALLS)
  - BREAKOUT: cross above King (BUY CALLS)
  - RETEST: pullback to King from above (BUY CALLS)
  - SELL_POP: rejection off Ceiling (BUY PUTS) — normal mode only
  - FLOOR_BREAK: breakdown below Floor (BUY PUTS)
  - ZGL_CROSS_UP/DOWN: regime context tag (no cap charge)
  - EMA_PULLBACK: 15-min 8 EMA bounce (Mir's #1 trigger)
  - TREND_CONTINUATION: gap-and-go day, above 8 EMA
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .cache import cache
from .config import get_settings

# Which tickers get scalp alerts
SCALP_TICKERS = {"SPY", "QQQ"}

# Cooldowns: prevent alert spam
_last_alert: dict[str, float] = {}  # "ticker:alert_type" -> timestamp
ALERT_COOLDOWN = 900  # 15 minutes per ticker per alert type

# Track previous state for cross detection
_prev_state: dict[str, dict[str, Any]] = {}

# Daily alert cap: 2 TOTAL across SPY+QQQ combined (not per-ticker)
# 4-LLM consensus: 2 per-ticker allowed 4 total which is too generous
_daily_alert_count: dict[str, int] = {}  # "date" -> count (combined)
MAX_DAILY_ALERTS = 2

# ZGL_CROSS types are context/bias tags — they don't count toward the daily cap
_CONTEXT_ONLY_ALERTS = {"ZGL_CROSS_UP", "ZGL_CROSS_DOWN"}

# ── 15-min 8 EMA tracking ───────────────────────────────────────────
# Mir's actual entry trigger from RAG: "pullback to the 8 EMA on 15-min"
# Cached to avoid hammering Tradier — refresh every 5 minutes.

_bar_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}  # ticker -> (ts, bars)
_BAR_CACHE_TTL = 120  # 2 minutes (matches GEX refresh cycle)

_ema8_state: dict[str, dict[str, Any]] = {}
# {ticker: {prev_close, prev_ema, prev_relation ("ABOVE"/"BELOW"/"TOUCHING")}}

_tradier_client = None  # lazy-init

# VIX state — refreshed at the top of each scalp scan cycle
# {level: float, structure: str, regime: "NORMAL"|"ELEVATED"|"SKIP"}
_current_vix: dict[str, Any] = {}
_VIX_CACHE_TS: float = 0
_VIX_CACHE_TTL = 300  # 5 minutes


def _compute_ema8(closes: list[float]) -> float:
    """Compute 8-period EMA from a list of closing prices."""
    period = 8
    if len(closes) < period:
        return sum(closes) / len(closes)
    multiplier = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for val in closes[period:]:
        ema = val * multiplier + ema * (1 - multiplier)
    return ema


async def _refresh_bars(ticker: str) -> list[dict[str, Any]] | None:
    """Fetch 15-min bars from Tradier with caching (5-min TTL)."""
    global _tradier_client

    cached = _bar_cache.get(ticker)
    if cached and (time.time() - cached[0]) < _BAR_CACHE_TTL:
        return cached[1]

    try:
        if _tradier_client is None:
            from .tradier import TradierClient
            _tradier_client = TradierClient()

        # 4-LLM consensus: 5-min bars nearly double returns vs 15-min (options.cafe study)
        # SPY 4/15 lesson: 15-min smoothed away two obvious pullback entries visible on 5-min
        bars = await _tradier_client.history(ticker, interval="5min")
        if bars:
            _bar_cache[ticker] = (time.time(), bars)
            return bars
    except Exception as e:
        print(f"[SCALP] 15-min bars fetch failed for {ticker}: {e}")

    # Return stale cache if available
    return cached[1] if cached else None


async def _detect_ema_pullback(ticker: str, state: dict[str, Any]) -> dict[str, Any] | None:
    """Detect 15-min 8 EMA pullback/bounce entry (Mir's trigger).

    Returns an alert dict or None.
    """
    bars = await _refresh_bars(ticker)
    if not bars or len(bars) < 10:
        return None

    closes = [b["close"] for b in bars]
    ema_val = _compute_ema8(closes)
    current_close = closes[-1]
    spot = state.get("actual_spot") or state.get("_spot") or current_close

    # Determine current relation to EMA
    ema_dist_pct = (spot - ema_val) / ema_val if ema_val else 0
    if abs(ema_dist_pct) < 0.001:
        relation = "TOUCHING"
    elif spot > ema_val:
        relation = "ABOVE"
    else:
        relation = "BELOW"

    prev = _ema8_state.get(ticker, {})
    prev_relation = prev.get("prev_relation")

    # Update state for next cycle
    _ema8_state[ticker] = {
        "prev_close": spot,
        "prev_ema": ema_val,
        "prev_relation": relation,
    }

    if prev_relation is None:
        return None  # First cycle — need history

    king = state.get("king", 0)
    floor_val = state.get("floor", 0)
    regime = state.get("regime", "")

    # ── Trend day check ──
    trend_day = state.get("_trend_day") or {}
    trend_mode = trend_day.get("trend_mode", "NORMAL")
    gap_dir = trend_day.get("gap_direction", "")

    # TREND CONTINUATION: gap-and-go day, price above EMA with momentum
    if (
        trend_mode in ("TREND_DAY", "EXTREME_TREND")
        and gap_dir == "UP"
        and relation == "ABOVE"
        and ema_dist_pct > 0.001
    ):
        contract = _suggest_contract(ticker, spot, "CALLS", king)
        king_dist = ((king - spot) / spot * 100) if king > spot else 0
        return {
            "ticker": ticker,
            "type": "TREND_CONTINUATION",
            "emoji": "🔥",
            "headline": f"TREND DAY — Gap +{trend_day.get('gap_pct', 0):.1f}%, above 8 EMA",
            "detail": (
                f"Spot ${spot:.2f} | 8 EMA ${ema_val:.2f} (+{ema_dist_pct*100:.2f}%)\n"
                f"Gap-and-go — no pullback wait, ride the trend\n"
                f"King: ${king} ({king_dist:+.1f}%) | Regime: {regime}"
            ),
            "contract": contract,
            "direction": "CALLS",
            "spot": spot,
            "target": king if king > spot else spot * 1.01,
            "stop": ema_val,
        }

    # EMA PULLBACK: previous bar was at/below EMA, now bouncing above
    if prev_relation in ("BELOW", "TOUCHING") and relation == "ABOVE" and ema_dist_pct > 0.001:
        contract = _suggest_contract(ticker, spot, "CALLS", king)
        king_dist = ((king - spot) / spot * 100) if king > spot else 0
        return {
            "ticker": ticker,
            "type": "EMA_PULLBACK",
            "emoji": "📈",
            "headline": "8 EMA PULLBACK — Bounce confirmed",
            "detail": (
                f"Spot ${spot:.2f} bounced off 5-min 8 EMA ${ema_val:.2f}\n"
                f"Mir's #1 entry trigger — pullback to trend support\n"
                f"King magnet: ${king} ({king_dist:+.1f}%) | Regime: {regime}"
            ),
            "contract": contract,
            "direction": "CALLS",
            "spot": spot,
            "target": king if king > spot else spot * 1.01,
            "stop": ema_val * 0.998,  # Just below EMA
        }

    # EMA REJECTION: previous bar was at/above EMA, now breaking below
    if prev_relation in ("ABOVE", "TOUCHING") and relation == "BELOW" and ema_dist_pct < -0.001:
        contract = _suggest_contract(ticker, spot, "PUTS")
        return {
            "ticker": ticker,
            "type": "EMA_REJECTION",
            "emoji": "📉",
            "headline": "8 EMA REJECTION — Breaking below trend",
            "detail": (
                f"Spot ${spot:.2f} broke below 5-min 8 EMA ${ema_val:.2f}\n"
                f"Trend support lost — momentum reversal\n"
                f"Floor: ${floor_val} | Regime: {regime}"
            ),
            "contract": contract,
            "direction": "PUTS",
            "spot": spot,
            "target": floor_val if floor_val and floor_val < spot else spot * 0.99,
            "stop": ema_val * 1.002,  # Just above EMA
        }

    return None


def _can_alert(ticker: str, alert_type: str) -> bool:
    key = f"{ticker}:{alert_type}"
    last = _last_alert.get(key, 0)
    return (time.time() - last) > ALERT_COOLDOWN


def _record_alert(ticker: str, alert_type: str) -> None:
    _last_alert[f"{ticker}:{alert_type}"] = time.time()


def _get_dte_preference() -> tuple[int, str]:
    """Determine 0DTE vs 1DTE based on time window.

    4-LLM consensus:
      - 1:30-3:00 PM: 1DTE only (theta is $0.80-1.20/hr on 0DTE)
      - 3:00-4:00 PM: 0DTE allowed (Power Hour — gamma leverage peaks)

    Returns (dte_days, label) where dte_days is 0 or 1.
    """
    import datetime
    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute

    if mins >= 900:  # 3:00 PM+ = Power Hour
        return 0, "0DTE"
    else:
        return 1, "1DTE"


def _suggest_contract(ticker: str, spot: float, direction: str, king: float = 0) -> str:
    """Suggest a contract with 1DTE/0DTE based on time window + VIX."""
    import datetime

    dte_days, dte_label = _get_dte_preference()

    # VIX override: 25-30 forces 1DTE regardless of window
    vix_level = _current_vix.get("level", 0)
    if vix_level >= 25:
        dte_days = 1
        dte_label = "1DTE"

    if dte_days == 0:
        exp_date = datetime.date.today()
    else:
        # 1DTE = next trading day
        exp_date = datetime.date.today() + datetime.timedelta(days=1)
        # Skip weekend
        if exp_date.weekday() == 5:  # Saturday
            exp_date += datetime.timedelta(days=2)
        elif exp_date.weekday() == 6:  # Sunday
            exp_date += datetime.timedelta(days=1)

    exp_str = exp_date.isoformat()

    if direction == "CALLS":
        strike = round(spot / 1) if spot < 50 else round(spot / 5) * 5
        return f"{ticker} ${strike}C {exp_str} ({dte_label})"
    else:
        strike = round(spot / 1) if spot < 50 else round(spot / 5) * 5
        return f"{ticker} ${strike}P {exp_str} ({dte_label})"


async def _check_scalp_alerts() -> list[dict[str, Any]]:
    """Check all scalp tickers for structure alerts. Returns list of alerts."""
    import datetime

    now = datetime.datetime.now()
    # Only during market hours
    if now.weekday() >= 5:
        return []
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return []
    if now.hour > 16 or (now.hour == 16 and now.minute > 15):
        return []

    # ── VIX regime filter (4-LLM consensus) ────────────────────────
    # >30: skip ALL scalp alerts
    # 25-30: 1DTE only (handled in _suggest_contract)
    # <25: normal
    global _VIX_CACHE_TS
    if time.time() - _VIX_CACHE_TS > _VIX_CACHE_TTL:
        try:
            from .breadth import get_vix_term_structure, get_vix_intraday_regime
            vix_ts = await get_vix_term_structure()
            vix_regime_data = await get_vix_intraday_regime()
            vix_level = vix_ts.get("vix", 0)
            _current_vix.update({
                "level": vix_level,
                "structure": vix_ts.get("structure", ""),
                "regime": vix_regime_data.get("regime", "UNKNOWN"),
                "bull_bias": vix_regime_data.get("bull_bias", False),
            })
            _VIX_CACHE_TS = time.time()
        except Exception:
            pass  # Keep stale VIX if refresh fails

    vix_level = _current_vix.get("level", 0)
    if vix_level > 30:
        return []  # 4-LLM consensus: VIX > 30 = skip all scalps

    # ── Macro event time-window skip (upgraded from all-day ban) ──
    # Block 90 min before through 60 min after high-impact events,
    # not the entire day. FOMC at 2PM → block 12:30-3:00.
    try:
        import httpx
        s = get_settings()
        if s.finnhub_api_key:
            today_str = now.strftime("%Y-%m-%d")
            r = httpx.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"token": s.finnhub_api_key, "from": today_str, "to": today_str},
                timeout=5,
            )
            if r.status_code == 200:
                events = r.json().get("economicCalendar", [])
                major = [e for e in events if e.get("impact", "") == "high"]
                for ev in major:
                    ev_time = ev.get("time", "")
                    if ev_time:
                        # Parse HH:MM format from Finnhub
                        try:
                            parts = ev_time.split(":")
                            ev_mins = int(parts[0]) * 60 + int(parts[1])
                            block_start = ev_mins - 90
                            block_end = ev_mins + 60
                            if block_start <= mins <= block_end:
                                return []  # Inside macro danger window
                        except (ValueError, IndexError):
                            pass
                    else:
                        # No time given — event affects whole day, skip entirely
                        if major:
                            return []
    except Exception:
        pass  # If check fails, continue with alerts

    # Reset daily counter at midnight
    today_key_prefix = now.strftime("%Y%m%d")

    # Time gates moved per-ticker to allow trend-day exceptions.
    # Normal mode: PM momentum + power hour only (1:30 PM+)
    # Trend day: allow from 10:00 AM (after first-hour settle)
    mins = now.hour * 60 + now.minute
    if mins < 600:  # Before 10:00 AM absolute minimum
        return []

    alerts: list[dict[str, Any]] = []

    for ticker in SCALP_TICKERS:
        state = await cache.get(ticker)
        if not state:
            continue

        # Per-ticker time gate: trend days allow earlier scanning
        trend_day = state.get("_trend_day") or {}
        trend_mode = trend_day.get("trend_mode", "NORMAL")
        if trend_mode == "NORMAL" and mins < 810:
            continue  # Normal mode: skip until 1:30 PM

        spot = state.get("actual_spot") or state.get("_spot") or 0
        king = state.get("king") or 0
        floor_val = state.get("floor") or 0
        ceiling = state.get("ceiling") or 0
        zgl = state.get("zgl") or 0
        signal = state.get("signal", "")
        regime = state.get("regime", "")
        king_pos = state.get("king_pos", True)

        if not spot or not king:
            continue

        prev = _prev_state.get(ticker, {})
        prev_spot = prev.get("spot", spot)

        # Volume confirmation: skip transitions without participation
        ed = state.get("exp_data", {}).get("MACRO (ALL 200D)", {})
        # Gate 1: GEX magnitude (options activity)
        gex_magnitude = abs(ed.get("pos_gex", 0)) + abs(ed.get("neg_gex", 0))
        if gex_magnitude < 1_000_000:  # Less than $1M total GEX = dead tape
            continue

        # Gate 2: Price volume context on the 15-min bar
        # Volume confirms but does NOT veto — gamma squeezes can start on normal volume
        # (dealer hedging flows don't need retail volume expansion to kick off)
        vol_confirmed = True  # default
        cached_bars = _bar_cache.get(ticker)
        if cached_bars and cached_bars[1] and len(cached_bars[1]) >= 10:
            bars = cached_bars[1]
            volumes = [b.get("volume", 0) for b in bars if b.get("volume")]
            if len(volumes) >= 5:
                avg_vol = sum(volumes[-20:]) / min(len(volumes), 20)
                current_vol = volumes[-1] if volumes else 0
                vol_confirmed = current_vol > avg_vol * 0.8

        # Only fire on STATE TRANSITIONS — not proximity persistence.
        # "Cream of the crop" = the moment price CROSSES a level or
        # BOUNCES off it with confirmation, not while it sits near it.

        prev_floor = prev.get("floor", floor_val)
        prev_king = prev.get("king", king)

        # ── BUY THE DIP: price dipped to floor and is now bouncing ─
        # Trigger: prev was within 0.3% of floor (or below), now moving away up
        if floor_val and spot > floor_val:
            was_at_floor = prev_spot and prev_spot <= floor_val * 1.003
            now_bouncing = spot > floor_val * 1.003
            if was_at_floor and now_bouncing and _can_alert(ticker, "BUY_DIP"):
                contract = _suggest_contract(ticker, spot, "CALLS", king)
                king_dist = ((king - spot) / spot * 100) if king > spot else 0
                alerts.append({
                    "ticker": ticker,
                    "type": "BUY_DIP",
                    "emoji": "🟢",
                    "headline": "BUY THE DIP — Floor held, bouncing",
                    "detail": (
                        f"Spot ${spot:.2f} bounced off Floor ${floor_val}\n"
                        f"King magnet: ${king} ({king_dist:+.1f}%)\n"
                        f"Regime: {regime} | Signal: {signal}\n"
                        f"Stop below floor, target king"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": king,
                    "stop": floor_val * 0.997,  # Just below floor
                })
                _record_alert(ticker, "BUY_DIP")

        # ── BREAKOUT: price crosses above king ────────────────────
        # Trigger: prev was below king, now above — breakout above magnet
        if king and king_pos and prev_spot and prev_spot < king and spot >= king:
            if _can_alert(ticker, "BREAKOUT"):
                # Target: next gatekeeper or ceiling
                target = ceiling if ceiling and ceiling > king else king * 1.01
                contract = _suggest_contract(ticker, spot, "CALLS", target)
                alerts.append({
                    "ticker": ticker,
                    "type": "BREAKOUT",
                    "emoji": "🚀",
                    "headline": "BREAKOUT — Price cleared King",
                    "detail": (
                        f"Spot ${spot:.2f} broke above King ${king}\n"
                        f"Dealers now chasing — momentum accelerating\n"
                        f"Next target: ${target:.2f}\n"
                        f"Stop: King retest ${king}"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": target,
                    "stop": king,
                })
                _record_alert(ticker, "BREAKOUT")

        # ── RETEST: price pulled back to king from above (buy the retest)
        if king and king_pos and prev_spot and prev_spot > king * 1.003 and spot <= king * 1.003 and spot >= king * 0.997:
            if _can_alert(ticker, "RETEST"):
                contract = _suggest_contract(ticker, spot, "CALLS", ceiling or king * 1.02)
                alerts.append({
                    "ticker": ticker,
                    "type": "RETEST",
                    "emoji": "🔄",
                    "headline": "RETEST — King pullback entry",
                    "detail": (
                        f"Spot ${spot:.2f} retesting King ${king} from above\n"
                        f"King is +GEX — dealers support at this level\n"
                        f"Classic breakout-retest entry\n"
                        f"Stop below king, target ceiling"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": ceiling or king * 1.02,
                    "stop": king * 0.995,
                })
                _record_alert(ticker, "RETEST")

        # ── SELL THE POP: price hit ceiling and rejecting ──────────
        # 4-LLM consensus: only fire when trend_mode == NORMAL
        # "Selling pop into a trend day is how 0DTE traders donate money"
        # VIX regime gate (added Apr 16): skip on bull compress days —
        # the backtest shows these are 80%+ bull tape, fading is suicide.
        _vix_regime = _current_vix.get("regime", "UNKNOWN")
        _skip_sell_pop_regime = _vix_regime in ("VIX_BULL_COMPRESS", "VIX_ELEVATED_COMP")
        if (ceiling and ceiling > spot and prev_spot
            and prev_spot >= ceiling * 0.997 and spot < ceiling * 0.997
            and trend_mode == "NORMAL"
            and not _skip_sell_pop_regime):
            if _can_alert(ticker, "SELL_POP"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "SELL_POP",
                    "emoji": "🔴",
                    "headline": "SELL THE POP — Ceiling rejection",
                    "detail": (
                        f"Spot ${spot:.2f} rejected at Ceiling ${ceiling}\n"
                        f"GEX resistance confirmed — dealers selling\n"
                        f"Target: King ${king} | Stop: above ceiling"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": king,
                    "stop": ceiling * 1.003,
                })
                _record_alert(ticker, "SELL_POP")

        # ── FLOOR BREAK: breakdown below support ──────────────────
        if floor_val and spot < floor_val and prev_spot and prev_spot >= floor_val:
            if _can_alert(ticker, "FLOOR_BREAK"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "FLOOR_BREAK",
                    "emoji": "💥",
                    "headline": "FLOOR BREAK — Air pocket below",
                    "detail": (
                        f"Spot ${spot:.2f} broke Floor ${floor_val}\n"
                        f"Entering negative gamma — dealers amplifying\n"
                        f"Next support: ZGL ${zgl}\n"
                        f"Let runners ride, stop above floor"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": zgl,
                    "stop": floor_val * 1.003,
                })
                _record_alert(ticker, "FLOOR_BREAK")

        # ── ZGL CROSS: regime change ──────────────────────────────
        if zgl and spot > zgl and prev_spot and prev_spot <= zgl:
            if _can_alert(ticker, "ZGL_CROSS_UP"):
                contract = _suggest_contract(ticker, spot, "CALLS", king)
                alerts.append({
                    "ticker": ticker,
                    "type": "ZGL_CROSS_UP",
                    "emoji": "⚡",
                    "headline": "REGIME CHANGE — Positive gamma zone",
                    "detail": (
                        f"Spot ${spot:.2f} crossed above ZGL ${zgl}\n"
                        f"Dealers now stabilizing — buy dips supported\n"
                        f"King target: ${king}"
                    ),
                    "contract": contract,
                    "direction": "CALLS",
                    "spot": spot,
                    "target": king,
                    "stop": zgl * 0.997,
                })
                _record_alert(ticker, "ZGL_CROSS_UP")

        if zgl and spot < zgl and prev_spot and prev_spot >= zgl:
            if _can_alert(ticker, "ZGL_CROSS_DOWN"):
                contract = _suggest_contract(ticker, spot, "PUTS")
                alerts.append({
                    "ticker": ticker,
                    "type": "ZGL_CROSS_DOWN",
                    "emoji": "⚡",
                    "headline": "REGIME CHANGE — Negative gamma zone",
                    "detail": (
                        f"Spot ${spot:.2f} crossed below ZGL ${zgl}\n"
                        f"Dealers amplifying moves — momentum trades\n"
                        f"Floor: ${floor_val}"
                    ),
                    "contract": contract,
                    "direction": "PUTS",
                    "spot": spot,
                    "target": floor_val,
                    "stop": zgl * 1.003,
                })
                _record_alert(ticker, "ZGL_CROSS_DOWN")

        # ── 8 EMA PULLBACK: Mir's #1 intraday entry trigger ─────────
        ema_alert = await _detect_ema_pullback(ticker, state)
        if ema_alert and _can_alert(ticker, ema_alert["type"]):
            # Add trend day context to headline
            if trend_mode == "TREND_DAY":
                ema_alert["headline"] += " (TREND DAY)"
            elif trend_mode == "EXTREME_TREND":
                ema_alert["headline"] += " (EXTREME GAP — reduced size)"
            alerts.append(ema_alert)
            _record_alert(ticker, ema_alert["type"])

        # Tag alerts with volume context + VIX/DTE metadata
        for a in alerts:
            if a.get("ticker") == ticker:
                a["_vol_confirmed"] = vol_confirmed
                a["_vix_level"] = vix_level
                dte_days, dte_label = _get_dte_preference()
                if vix_level >= 25:
                    dte_label = "1DTE"
                a["_dte_label"] = dte_label

        # Store state for next cycle
        _prev_state[ticker] = {"spot": spot, "king": king, "floor": floor_val, "zgl": zgl}

    # ── Combined daily cap: 2 total across SPY+QQQ ───────────────
    # ZGL_CROSS context tags pass through without counting
    daily_key = today_key_prefix
    day_count = _daily_alert_count.get(daily_key, 0)
    kept: list[dict[str, Any]] = []
    for a in alerts:
        if a["type"] in _CONTEXT_ONLY_ALERTS:
            a["_context_only"] = True
            kept.append(a)  # Context tags always pass, don't count
        elif day_count >= MAX_DAILY_ALERTS:
            print(f"[SCALP] Daily cap hit ({MAX_DAILY_ALERTS}), dropping {a['ticker']} {a['type']}")
        else:
            day_count += 1
            kept.append(a)
    _daily_alert_count[daily_key] = day_count

    return kept


def _get_window() -> tuple[str, str]:
    """Get current time window and quality label."""
    import datetime
    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute

    if mins < 630:
        return "AVOID", "First hour — Mir: 'wait an hour after the bell'"
    if 630 <= mins < 690:
        return "AM_SETTLED", "Post-open settled"
    if 690 <= mins < 810:
        return "CHOP", "Midday chop — low probability"
    if 810 <= mins < 900:
        return "PM_MOMENTUM", "Afternoon momentum"
    if 900 <= mins < 960:
        return "POWER_HOUR", "Mir's top window — 'biggest plays in final minutes'"
    return "CLOSED", "Market closed"


def format_scalp_alert(alert: dict[str, Any]) -> str:
    """Format a scalp alert for Telegram."""
    window, window_note = _get_window()

    lines = [
        f"{alert['emoji']} <b>{alert['ticker']} {alert['headline']}</b>",
        f"",
        alert['detail'],
    ]
    if alert.get('contract'):
        lines.append(f"")
        lines.append(f">> <b>{alert['contract']}</b>")
    if alert.get('target') and alert.get('stop'):
        lines.append(f"Target: ${alert['target']:.2f} | Stop: ${alert['stop']:.2f}")

    # Window quality from Mir + backtest
    lines.append(f"")
    if window == "POWER_HOUR":
        lines.append(f"⏰ POWER HOUR — highest EV window (backtest: +0.43%/trade)")
    elif window == "PM_MOMENTUM":
        lines.append(f"⏰ PM momentum — good window (backtest: +0.15%/trade)")
    elif window == "AM_SETTLED":
        lines.append(f"⏰ Morning — lower EV, be selective")
    elif window == "CHOP":
        lines.append(f"⚠️ Midday chop — Mir avoids this window")

    # Volume confirmation tag
    if alert.get("_vol_confirmed") is False:
        lines.append(f"⚠️ LOW VOLUME — no participation confirmation")
    elif alert.get("_vol_confirmed") is True:
        lines.append(f"✅ Volume confirmed")

    # VIX context
    vix_level = alert.get("_vix_level", 0)
    if vix_level >= 25:
        lines.append(f"⚠️ VIX {vix_level:.1f} — ELEVATED, 1DTE forced")
    elif vix_level > 0:
        lines.append(f"VIX: {vix_level:.1f}")

    # DTE label (1DTE vs 0DTE)
    dte_label = alert.get("_dte_label", "0DTE")
    if dte_label == "0DTE":
        lines.append(f"🔥 0DTE POWER HOUR | aggressive theta, tight stops")
    else:
        lines.append(f"📋 1DTE — theta buffer, let the trade develop")

    # Context-only tag for ZGL alerts
    if alert.get("_context_only"):
        lines.append(f"ℹ️ CONTEXT ONLY — regime bias, not a trade trigger")

    return "\n".join(lines)


async def _auto_paper_scalp(alert: dict[str, Any]) -> None:
    """Auto-open a paper position for a scalp alert.

    Inserts into soe_signals first (so paper_trading can reference it),
    then opens the paper position at the ask (Grok rule).
    Context-only alerts (ZGL_CROSS) are skipped.
    """
    if alert.get("_context_only"):
        return

    try:
        import sqlite3
        from .config import get_settings
        s = get_settings()
        conn = sqlite3.connect(s.snapshot_db)
        conn.row_factory = sqlite3.Row

        ticker = alert["ticker"]
        direction = alert.get("direction", "CALLS")
        spot = alert.get("spot", 0)
        target = alert.get("target", 0)
        stop = alert.get("stop", 0)
        dte_days, dte_label = _get_dte_preference()
        vix_level = _current_vix.get("level", 0)
        if vix_level >= 25:
            dte_days = 1

        # Parse contract suggestion for strike/exp
        contract_str = alert.get("contract", "")
        # Format: "SPY $697C 2026-04-16 (1DTE)"
        strike = 0
        expiration = ""
        option_type = "call" if direction == "CALLS" else "put"
        import re
        m = re.search(r'\$(\d+(?:\.\d+)?)[CP]?\s+(\d{4}-\d{2}-\d{2})', contract_str)
        if m:
            strike = float(m.group(1))
            expiration = m.group(2)

        # Get bid/ask from cached chain
        bid, ask, mid, delta = 0, 0, 0, 0.5
        state = await cache.get(ticker)

        if state:
            raw = state.get("_raw_contracts", {})
            for exp_contracts in raw.values():
                for c in exp_contracts:
                    if (abs(c.get("strike", 0) - strike) < 0.01 and
                        (c.get("option_type") or "").lower() == option_type and
                        c.get("expiration_date") == expiration):
                        bid = c.get("bid", 0) or 0
                        ask = c.get("ask", 0) or 0
                        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
                        g = c.get("greeks") or {}
                        delta = abs(g.get("delta", 0) or 0.5)
                        break

        if not ask or ask <= 0:
            print(f"[SCALP] Skip paper trade for {ticker} — no ask price")
            return

        # Insert as signal so paper_trading can reference it
        import time as _time
        conn.execute(
            """INSERT INTO soe_signals
            (ts, ticker, direction, signal_type, grade, score, max_score,
             strike, expiration, option_type, target, target_label, stop, stop_label,
             rr_ratio, spot, king, reasoning, status,
             entry_price, mid_price, bid, ask)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(_time.time()), ticker,
                "BULL" if direction == "CALLS" else "BEAR",
                f"SCALP_{alert['type']}", "SCALP", 0, 0,
                strike, expiration, option_type,
                target, alert.get("type", ""), stop, "level break",
                round(abs(target - spot) / abs(spot - stop), 1) if abs(spot - stop) > 0 else 0,
                spot, state.get("king", 0) if state else 0,
                alert.get("headline", ""), "PENDING",
                ask, mid, bid, ask,
            ),
        )
        signal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        # Open paper position
        from .paper_trading import open_position
        result = open_position(signal_id, contracts=1)  # Always 1 contract for scalps
        if result.get("error"):
            print(f"[SCALP] Paper open failed for {ticker}: {result['error']}")
        else:
            print(f"[SCALP] Paper auto-opened: {ticker} {alert['type']} x1 @ ask ${ask:.2f} ({dte_label})")

    except Exception as e:
        print(f"[SCALP] Paper trade error for {alert.get('ticker', '?')}: {e}")


async def run_scalp_scanner(stop_event: asyncio.Event) -> None:
    """Background loop: check structure alerts every 30 seconds."""
    await asyncio.sleep(90)  # Wait for first GEX cycle to populate cache

    while not stop_event.is_set():
        try:
            alerts = await _check_scalp_alerts()
            if alerts:
                from .telegram import send
                for a in alerts:
                    msg = format_scalp_alert(a)
                    await send(msg, ticker=a["ticker"], force=True)
                    print(f"[SCALP] {a['ticker']} {a['type']}: {a['headline']}")
                    # Auto-open paper position for real trade alerts
                    await _auto_paper_scalp(a)
        except Exception as e:
            print(f"[SCALP] error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
