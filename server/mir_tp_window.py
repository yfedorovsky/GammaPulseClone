"""Mir TP Window — daily Telegram alert at 1:00 PM ET.

TraderMir 5/28 PM observation: "if you take profits regardless of target
in the window from 10am to 10:45 pacific time you will likely sell the
high for the day of your options contracts."

Validated against today's 396 INFORMED FLOW fires:
  - 9.8% peaked exactly in Mir's 1:00-1:45 PM ET window
  - 24% peaked between 13:00-14:00
  - 58% peaked in the 13:45-15:00 PM window
  - Only 9% peaked in power hour (15:00-16:00)
  - 0% peaked at/after close

The rule is directionally right: take profits in early afternoon,
not at close. Specific 1:00 PM trigger captures micro-caps (DPRO,
ONDS, SOXX peaked at 13:00 today); large-caps run an hour later.

This module fires a daily Telegram ping at 13:00 ET listing every
INFORMED FLOW + SOE A/A+ alert from today that's still tradeable
(neither TP'd nor stopped) with current P/L vs entry.

Dedup: fires once per calendar day (ET). Resets at midnight.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

# Data-backed exit/sizing discipline (2026-06-21 research, cross-regime confirmed
# Jan-Jun 2026): on far-OTM "lotto" single-name calls, flat profit-targets were
# NEGATIVE-EV; scaling 1/3 at +100% and running the rest kept ~75% of expectancy +
# the full right tail while halving the median loss. And these lottos LOSE in
# down/chop tape (Feb -37%, Jun -18%) — hence the downtrend caution. This is
# DISCIPLINE guidance, never an auto-trade rule. Reversible: env MIR_TP_DISCIPLINE=0.
# See docs/research/EXIT_POLICY_FINDINGS.md.
SPY_DOWNTREND_PCT = -1.5   # SPY <= this over ~1wk -> down/chop caution

# Phase-1 sizing MONITOR (2026-06-21 cap backtest — docs/research/SIZING_CAP_BACKTEST_FINDINGS.md):
# an uncapped 100%-deployed lotto book BANKRUPTED in Q1 2026 (−138% mark-to-market drawdown,
# crossed −100% in March); a regime-scaled CONCURRENT-EXPOSURE cap kept max DD ~26% and
# survived. This block displays the cap that applies RIGHT NOW so the user can self-check
# their open book against it. MONITOR ONLY — it never gates an alert. Reversible: env
# MIR_LOTTO_MONITOR=0. Showing the user's ACTUAL premium-at-risk needs a live broker position
# feed (future phase); here we surface the binding NUMBER (the regime-scaled cap) + a prompt.
SPY_RISK_ON_PCT = 1.0      # SPY >= this over ~1wk -> risk-on (full cap); between = chop
LOTTO_CAP_RISK_ON = 12.0   # % of capital — concurrent far-OTM single-name call premium
LOTTO_CAP_CHOP = 6.0
LOTTO_CAP_DOWN = 3.0


def _discipline_on() -> bool:
    return os.getenv("MIR_TP_DISCIPLINE", "1").strip().lower() in ("1", "true", "yes", "on")


def _lotto_monitor_on() -> bool:
    return os.getenv("MIR_LOTTO_MONITOR", "1").strip().lower() in ("1", "true", "yes", "on")


def _theme_subcap_on() -> bool:
    # Default ON, but the block renders NOTHING unless per-position data is
    # present in the exposure feed — so it's a no-op for single-total users.
    return os.getenv("MIR_THEME_SUBCAP", "1").strip().lower() in ("1", "true", "yes", "on")


def _lotto_capital() -> float | None:
    """Optional capital base (env MIR_LOTTO_CAPITAL) to render the cap in $ as well as %."""
    raw = os.getenv("MIR_LOTTO_CAPITAL", "").strip().replace(",", "").replace("$", "")
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


# Once-per-day dedup state (in-memory; resets on restart)
_last_fired_date: date | None = None


def _today_et() -> date:
    """ET calendar day (server clock assumed ET)."""
    return datetime.now().date()


def _is_mir_window_now() -> bool:
    """True between 13:00 and 13:30 ET (gives 30-min firing window).

    Mir's window is 13:00-13:45, but we want to fire EARLY in the
    window (13:00-13:15 ideally) so the user has time to actually
    place orders before the peak rolls past.
    """
    now = datetime.now()
    if now.weekday() >= 5:  # weekend
        return False
    minute_of_day = now.hour * 60 + now.minute
    # 13:00 = 780, 13:30 = 810
    return 780 <= minute_of_day <= 810


def _spot_at(conn, ticker: str, target_ts: int, window: int = 900) -> float | None:
    """Closest snapshot to target_ts within ±window seconds."""
    r = conn.execute(
        """SELECT spot FROM snapshots
           WHERE ticker = ? AND ABS(ts - ?) <= ?
           ORDER BY ABS(ts - ?) LIMIT 1""",
        (ticker, target_ts, window, target_ts),
    ).fetchone()
    return float(r[0]) if r and r[0] else None


def _spy_week_change(conn) -> float | None:
    """SPY ~1-week % change from snapshots. None on any missing data / error (fail-open)."""
    try:
        now_ts = int(time.time())
        spy_now = _spot_at(conn, "SPY", now_ts, window=1800)
        spy_past = _spot_at(conn, "SPY", now_ts - 6 * 86400, window=2 * 86400)
        if spy_now and spy_past:
            return (spy_now / spy_past - 1) * 100
    except Exception:
        pass
    return None


def _tape_caution(conn) -> tuple[bool, str]:
    """True if the broad tape looks like a down/chop regime — where the lotto-call
    payoff bled (Feb -37% / Jun -18% in the 2026 study). Uses SPY's ~1-week trend.
    Fail-open: missing data -> (False, '') so a flaky read never adds a false caution."""
    chg = _spy_week_change(conn)
    if chg is not None and chg <= SPY_DOWNTREND_PCT:
        return True, f"SPY {chg:+.1f}% / ~1wk"
    return False, ""


def _lotto_regime(conn) -> dict[str, Any]:
    """3-state regime + the regime-scaled concurrent-exposure cap (% of capital) for the
    lotto book. Display-only (Phase-1 monitor). Regime read unavailable -> cap_pct None
    (the caller shows the full ladder instead of a single number)."""
    chg = _spy_week_change(conn)
    if chg is None:
        return {"regime": "unknown", "reason": "SPY read unavailable", "cap_pct": None}
    if chg <= SPY_DOWNTREND_PCT:
        reg, cap = "downtrend", LOTTO_CAP_DOWN
    elif chg >= SPY_RISK_ON_PCT:
        reg, cap = "risk-on", LOTTO_CAP_RISK_ON
    else:
        reg, cap = "chop", LOTTO_CAP_CHOP
    return {"regime": reg, "reason": f"SPY {chg:+.1f}% / ~1wk", "cap_pct": cap}


def _direction(opt_type: str | None, sentiment: str | None) -> str:
    """Map (option_type, sentiment) -> BULL/BEAR."""
    ot = (opt_type or "").lower()
    sent = (sentiment or "").upper()
    if ot == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if ot == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "BULL"


def _compute_pl_pct(entry: float, current: float, direction: str) -> float:
    if entry <= 0:
        return 0.0
    sign = 1 if direction == "BULL" else -1
    return (current - entry) / entry * 100 * sign


def _collect_open_alerts() -> dict[str, list[dict[str, Any]]]:
    """Gather today's INFORMED FLOW + SOE A/A+ alerts that are still tradeable
    (neither TP'd nor stopped). Returns dict with 'flow' and 'soe' lists."""
    today_start = int(datetime.combine(_today_et(), datetime.min.time()).timestamp())
    now_ts = int(time.time())

    conn = sqlite3.connect("snapshots.db")
    conn.row_factory = sqlite3.Row

    # INFORMED FLOW — per-contract dedup, only one per contract per day
    flow_rows = conn.execute(
        """SELECT MIN(ts) AS fire_ts, ticker, strike, option_type, expiration,
                  sentiment, MIN(spot) AS entry_spot, MAX(notional) AS notional,
                  MAX(vol_oi) AS vol_oi, MAX(insider_score) AS score
           FROM flow_alerts
           WHERE is_insider = 1 AND ts >= ?
           GROUP BY ticker, strike, expiration, option_type, sentiment
           ORDER BY fire_ts""",
        (today_start,),
    ).fetchall()

    flow_open: list[dict] = []
    for r in flow_rows:
        if not r["entry_spot"]:
            continue
        ticker = r["ticker"]
        direction = _direction(r["option_type"], r["sentiment"])
        entry = float(r["entry_spot"])
        cur = _spot_at(conn, ticker, now_ts) or entry
        pl_pct = _compute_pl_pct(entry, cur, direction)

        # Only ping on meaningful winners — Mir's rule is about CAPTURING
        # peak P/L, not nudging on every open position. Skip trades that
        # haven't moved at least +3% spot in our direction yet.
        if pl_pct < 3.0:
            continue

        flow_open.append({
            "ticker": ticker,
            "strike": r["strike"],
            "option_type": (r["option_type"] or "").upper(),
            "expiration": r["expiration"],
            "direction": direction,
            "entry": entry,
            "current": cur,
            "pl_pct": pl_pct,
            "vol_oi": r["vol_oi"],
            "notional": r["notional"] or 0,
        })

    # SOE A/A+ — open if neither target nor stop hit yet AND signal
    # actually reached Telegram. 2026-06-02 PM: previously included
    # signals blocked by is_broken_a_combo IV gate — the user got Mir TP
    # "take profits on open winners" messages for trades they were never
    # alerted to. Filter to telegram_sent = 1 so what we surface as "open
    # winners" matches what we actually sent.
    soe_rows = conn.execute(
        """SELECT ts, ticker, signal_type, grade, spot, target, stop, direction
           FROM soe_signals
           WHERE ts >= ? AND grade IN ('A', 'A+') AND status = 'PENDING'
             AND telegram_sent = 1
           ORDER BY ts""",
        (today_start,),
    ).fetchall()

    soe_open: list[dict] = []
    for r in soe_rows:
        ticker = r["ticker"]
        entry = float(r["spot"] or 0)
        if entry <= 0:
            continue
        target = float(r["target"] or 0)
        stop = float(r["stop"] or 0)
        cur = _spot_at(conn, ticker, now_ts) or entry

        # Direction inference
        direction = "BULL"
        if "▼" in (r["direction"] or "") or "BEAR" in (r["direction"] or "").upper():
            direction = "BEAR"

        # Has it hit target or stop already? skip if yes
        if direction == "BULL":
            if target > 0 and cur >= target:
                continue
            if stop > 0 and cur <= stop:
                continue
        else:
            if target > 0 and cur <= target:
                continue
            if stop > 0 and cur >= stop:
                continue

        pl_pct = _compute_pl_pct(entry, cur, direction)
        # Same +3% winner threshold as flow path
        if pl_pct < 3.0:
            continue

        soe_open.append({
            "ticker": ticker,
            "signal": r["signal_type"],
            "grade": r["grade"],
            "direction": direction,
            "entry": entry,
            "current": cur,
            "target": target,
            "stop": stop,
            "pl_pct": pl_pct,
        })

    # SOE dedup by ticker — keep best P/L per ticker (avoids QCOM ×4)
    soe_by_ticker: dict[str, dict] = {}
    for s in soe_open:
        existing = soe_by_ticker.get(s["ticker"])
        if not existing or s["pl_pct"] > existing["pl_pct"]:
            soe_by_ticker[s["ticker"]] = s
    soe_open = list(soe_by_ticker.values())

    # FLOW dedup by (ticker, direction) — keep best P/L
    # (User generally rolls multiple strike alerts on same ticker into one
    # net thesis trade.)
    flow_by_key: dict[tuple, dict] = {}
    for f in flow_open:
        key = (f["ticker"], f["direction"])
        existing = flow_by_key.get(key)
        if not existing or f["pl_pct"] > existing["pl_pct"]:
            flow_by_key[key] = f
    flow_open = list(flow_by_key.values())

    tape_caution = _tape_caution(conn)
    lotto_cap = _lotto_regime(conn)
    conn.close()
    return {"flow": flow_open, "soe": soe_open, "tape_caution": tape_caution,
            "lotto_cap": lotto_cap}


def _discipline_footer(open_alerts: dict[str, Any]) -> list[str]:
    """Exit-discipline + Phase-1 sizing-cap MONITOR footer. Both are flag-gated guidance
    (never auto-trade / never gate an alert) and render on every Mir TP fire incl no-alert
    days. See docs/research/EXIT_POLICY_FINDINGS.md + SIZING_CAP_BACKTEST_FINDINGS.md."""
    out: list[str] = []

    # Data-backed exit discipline for OTM/lotto single-name calls (env MIR_TP_DISCIPLINE=0).
    if _discipline_on():
        out.append("")
        out.append("📊 <b>DATA-BACKED DISCIPLINE</b> <i>(far-OTM / lotto single-name calls)</i>")
        out.append(
            "<i>Scale ⅓ at +100%, run the rest. Flat profit-targets tested NEGATIVE-EV; "
            "letting winners run kept ~75% of expectancy + the full right tail "
            "(cross-regime confirmed, Jan–Jun '26). Size each as a lotto.</i>"
        )
        caution, reason = open_alerts.get("tape_caution", (False, ""))
        if caution:
            out.append(
                f"⚠️ <b>Down/chop tape</b> ({reason}) — lotto calls LOST in down months "
                f"(Feb −37%, Jun −18%). Trim size / be quicker to cut. "
                f"<i>Discipline, not a signal.</i>"
            )

    # Phase-1/2a sizing MONITOR — regime-scaled cap + (Phase 2a) manual exposure compare.
    # env MIR_LOTTO_MONITOR=0 to disable.
    if _lotto_monitor_on():
        lc = open_alerts.get("lotto_cap") or {}
        exp = None
        try:
            from .lotto_exposure import get_exposure
            exp = get_exposure()
        except Exception:
            exp = None
        capital = _lotto_capital() or (exp.get("capital") if exp else None)
        out.append("")
        out.append("💰 <b>LOTTO EXPOSURE CAP</b> <i>(size the book, not the trade)</i>")
        cap = lc.get("cap_pct")
        if cap is not None:
            dollar = f" (~${cap / 100 * capital:,.0f})" if capital else ""
            out.append(
                f"Tape <b>{lc.get('regime')}</b> ({lc.get('reason')}) → keep total concurrent "
                f"far-OTM single-name call premium under <b>~{cap:g}% of capital</b>{dollar}."
            )
        else:
            out.append(
                f"<i>{lc.get('reason', 'regime read unavailable')}</i> — ladder: risk-on "
                f"{LOTTO_CAP_RISK_ON:g}% / chop {LOTTO_CAP_CHOP:g}% / downtrend "
                f"{LOTTO_CAP_DOWN:g}% of capital."
            )
        out.extend(_lotto_exposure_lines(exp, capital, cap))
        if _theme_subcap_on():
            out.extend(_theme_subcap_lines(exp, capital, cap))
        out.append(
            "<i>Backtest: an uncapped book bankrupted in Q1 '26 (−138% MTM drawdown); this cap "
            "held max DD ~26%. Check your open lotto premium vs this number.</i>"
        )
    return out


def _theme_subcap_lines(exp: dict[str, Any] | None, capital: float | None,
                        cap_pct: float | None) -> list[str]:
    """Per-theme concentration sub-cap (cross-LLM audit rec #1). Renders only when
    the exposure feed carries per-position data — otherwise silent (no regression).
    Display-only: the single-name cap and book cap don't catch 20 semis names
    collapsing into one bet into the MU print; this surfaces that."""
    if not exp:
        return []
    positions = exp.get("positions")
    if not positions:
        return []  # single-total feed → stay silent
    try:
        from .themes import theme_breakdown
    except Exception:
        return []
    rows = theme_breakdown(positions, capital, cap_pct)
    if not rows:
        return []
    lines = ["<i>Per-theme concentration (N_eff≈1 within a theme — the real ruin path):</i>"]
    shown = 0
    for r in rows:
        if shown >= 5:
            break
        theme = r["theme"].replace("_", " ")
        prem = r["premium"]
        if r.get("pct") is not None and r.get("subcap_pct") is not None:
            if r.get("over"):
                tag = f"⚠️ <b>OVER by {r['delta_pp']:.1f} pp</b>"
            else:
                tag = f"✅ ok ({abs(r['delta_pp']):.1f} pp room)"
            if r.get("has_catalyst"):
                tag += " <i>·catalyst-tightened</i>"
            lines.append(f"• <b>{theme}</b> ${prem:,.0f} = {r['pct']:.1f}% "
                         f"(sub-cap ~{r['subcap_pct']:.1f}%) → {tag}")
        else:
            lines.append(f"• <b>{theme}</b> ${prem:,.0f}")
        shown += 1
    lines.append("<i>Sub-cap = 0.5× the book cap (a theme is ~2× as concentrated). "
                 "Prior, not backtested — tune MIR_THEME_SUBCAP_FRACTION.</i>")
    return lines


def _lotto_exposure_lines(exp: dict[str, Any] | None, capital: float | None,
                          cap_pct: float | None) -> list[str]:
    """Phase-2a manual-exposure compare: your current lotto premium vs the regime cap,
    with a staleness warning (a stale figure misleads). `exp` is the get_exposure() dict."""
    if not exp:
        return ["<i>Your book: not set — "
                "<code>python scripts/set_lotto_exposure.py &lt;premium&gt; --capital N</code></i>"]
    try:
        from .lotto_exposure import staleness_hours, age_str
    except Exception:
        return []
    prem = exp["premium_at_risk"]
    lines: list[str] = []
    if capital and cap_pct is not None:
        pct = prem / capital * 100.0
        delta = pct - cap_pct
        status = (f"⚠️ <b>OVER by {delta:.1f} pp</b> — trim" if delta > 0
                  else f"✅ under (<b>{-delta:.1f} pp</b> room)")
        lines.append(f"Your book: <b>${prem:,.0f}</b> = <b>{pct:.1f}%</b> of capital "
                     f"vs ~{cap_pct:g}% cap → {status}")
    else:
        lines.append(f"Your book: <b>${prem:,.0f}</b> "
                     f"<i>(set --capital or MIR_LOTTO_CAPITAL for %)</i>")
    hrs = staleness_hours(exp)
    if hrs is not None and hrs > 24:
        lines.append(f"<i>⏳ figure set {age_str(hrs)} — update it if your book changed</i>")
    return lines


def _format_telegram(open_alerts: dict[str, list[dict]]) -> str:
    """Build the Telegram message body."""
    flow = open_alerts["flow"]
    soe = open_alerts["soe"]
    lines: list[str] = []

    lines.append("⏰ <b>MIR TP WINDOW</b> (1:00–1:45 PM ET)")
    lines.append("<i>Take partial profits on open winners — peak window today</i>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    if not flow and not soe:
        lines.append("No open INFORMED FLOW or SOE A/A+ alerts to ping.")
        lines.append("")
        lines.append(
            "<i>Reminder: this window historically captures the day's peak. "
            "If you have broker positions open, consider taking partial profits.</i>"
        )
        lines.extend(_discipline_footer(open_alerts))
        return "\n".join(lines)

    # INFORMED FLOW winners sorted by P/L descending
    if flow:
        lines.append(f"<b>INFORMED FLOW</b> ({len(flow)} open)")
        # Sort: winners first, biggest gains on top
        flow.sort(key=lambda x: -x["pl_pct"])
        for f in flow[:10]:  # top 10 to keep msg short
            emoji = "🟢" if f["direction"] == "BULL" else "🔴"
            pl_str = (
                f"+{f['pl_pct']:.2f}%" if f["pl_pct"] >= 0
                else f"{f['pl_pct']:.2f}%"
            )
            lines.append(
                f"{emoji} <b>{f['ticker']}</b> ${f['strike']:g}{f['option_type'][0]}"
                f" {f['expiration']}  "
                f"<i>{pl_str}</i>"
            )
            lines.append(
                f"   entry ${f['entry']:.2f} → ${f['current']:.2f}"
            )
        if len(flow) > 10:
            lines.append(f"   <i>+ {len(flow) - 10} more</i>")
        lines.append("")

    # SOE A/A+ winners
    if soe:
        lines.append(f"<b>SOE A/A+</b> ({len(soe)} open)")
        soe.sort(key=lambda x: -x["pl_pct"])
        for s in soe[:8]:
            emoji = "🟢" if s["direction"] == "BULL" else "🔴"
            pl_str = (
                f"+{s['pl_pct']:.2f}%" if s["pl_pct"] >= 0
                else f"{s['pl_pct']:.2f}%"
            )
            lines.append(
                f"{emoji} <b>{s['ticker']}</b> {s['grade']} {s['signal']}  "
                f"<i>{pl_str}</i>"
            )
            lines.append(
                f"   entry ${s['entry']:.2f} → ${s['current']:.2f}  "
                f"target ${s['target']:.2f}"
            )
        if len(soe) > 8:
            lines.append(f"   <i>+ {len(soe) - 8} more</i>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "<i>Mir's rule: take partial profits regardless of target. "
        "Re-enter at power hour (3-4 PM ET) or tomorrow morning if setup intact.</i>"
    )

    lines.extend(_discipline_footer(open_alerts))
    return "\n".join(lines)


async def maybe_fire_mir_tp_alert() -> bool:
    """Check if it's time to fire the Mir TP window alert. Returns True if fired.

    Idempotent: only fires once per ET calendar day. Call from worker loop
    every cycle — cheap no-op when not in window or already fired today.
    """
    global _last_fired_date

    today = _today_et()
    if _last_fired_date == today:
        return False  # already fired today

    if not _is_mir_window_now():
        return False

    # Collect data
    try:
        open_alerts = _collect_open_alerts()
        msg = _format_telegram(open_alerts)
    except Exception as e:
        print(f"[MIR_TP] collect failed: {e!r}", flush=True)
        return False

    # Send via Telegram (force=True so it bypasses rate limits)
    try:
        from .telegram import send
        ok = await send(msg, priority=True, force=True)
        if ok:
            _last_fired_date = today
            n_total = len(open_alerts["flow"]) + len(open_alerts["soe"])
            print(
                f"[MIR_TP] fired Mir TP window alert: "
                f"{n_total} open positions tagged",
                flush=True,
            )
        return ok
    except Exception as e:
        print(f"[MIR_TP] send failed: {e!r}", flush=True)
        return False
