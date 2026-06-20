"""Triple Confluence detector — INFORMED FLOW + king migration + SOE A/A+.

When three independent signal types converge on the same ticker in the same
direction within a rolling window, that's a much louder buy/sell signal than
any single signal alone. The MRVL 5/28 case study motivated this module:

  5/28 PM (4-hour window) — MRVL signal stack we missed surfacing loudly:
    1. INFORMED FLOW: 4× MRVL 320C 7/17 BULLISH ASK (score 5/6)
       — first fire at 1:17 PM, 3 minutes before PETROAI Twitter tweet
    2. SOE: 4× A/A+ SUPPORT BOUNCE targeting $220 (held)
    3. King migration: holding $200, set up to migrate to $220 by 6/1

  The MRVL 320C 7/17 went $3.60 → $16.65 by 6/2 (+362%). PETROAI bought
  the cheaper 6/18 expression at $0.82 → $16.65 (+1,930%). Our system
  saw the institutional flow; it just looked like "another INFORMED FLOW
  alert" rather than the loudest setup of the week.

How this fires:

  For each ticker active in the last 4 hours:
    A) Count INFORMED FLOW fires (is_insider=1) — need ≥2 same-direction
    B) Check for QUALIFIED king migration — same direction
    C) Count SOE A/A+ signals — same direction
  If A+B+C present in same direction → TRIPLE CONFLUENCE fires.

  Direction normalization handles three formats present in our DB:
    - flow_alerts: maps (option_type, sentiment) → BULL/BEAR
    - soe_signals: ▲ (BULL) / ▼ (BEAR) / literal "BULL"/"BEAR"
    - king_migrations: migration_type "UP"/"DOWN"

Dedup:
  Once per (ticker, direction, ET calendar day). In-memory state resets
  on backend restart. A direction flip on the same ticker SAME day would
  fire — that's the right behavior (means a major reversal is happening).

Worker integration:
  Called once per scan cycle from worker.py. Cheap query — touches
  flow_alerts, king_migrations.db, soe_signals all with indexed reads
  over a 4-hour window. Typical: <50ms.
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Any


# Rolling window: how far back we look for confluence signals
CONFLUENCE_WINDOW_SEC = 4 * 3600  # 4 hours

# Index ETFs excluded entirely — these trip all three signals constantly
# from routine MM activity (same rationale as the flow_alerts.py:1095
# tracker exclusion). Add INFORMED FLOW + king migration + SOE A/A+
# noise to that and the composite fires on SPY hourly. Carve them out.
_EXCLUDED_TICKERS = {
    "SPY", "SPX", "SPXW", "QQQ", "IWM", "DIA", "VIX", "NDX",
    "SOXL", "TQQQ", "SQQQ", "UPRO", "TSLL", "NVDL",
}

# INFORMED FLOW: minimum count of UNIQUE (strike, expiration) combos in
# direction. Counts unique contracts, not raw fire-events — a single
# alert re-firing every 5-min scan cycle should count as 1, not 5.
MIN_INFORMED_FLOW_UNIQUE_STRIKES = 2

# SOE: require at least 1 A+ signal in direction. A alone is too noisy —
# large-cap names hit A-grade SOE 5-15× per day on routine momentum.
# A+ requires extra confluence in the SOE scorer (king alignment + IV
# regime + breadth) so it's the tighter quality gate. Backtest on 5/28
# showed A-fallback admitted 87 daily fires; requiring A+ drops to ~12.
MIN_SOE_APLUS = 1

# King migration: at least one QUALIFIED migration AND the cumulative
# delta_pts movement must be ≥ 1.5% of spot. A king migrating $200 → $201
# on a $200 stock is noise; $200 → $220 is the signal.
MIN_KMIG_DELTA_PCT = 1.5

# Once-per-ticker-per-direction-per-day dedup (in-memory; resets on restart)
_fired_today: set[tuple[str, str, str]] = set()
_last_fired_date: date | None = None


def _today_et() -> date:
    """ET calendar day (server clock assumed ET)."""
    return datetime.now().date()


def _reset_dedup_if_new_day() -> None:
    """Clear in-memory dedup state at midnight ET."""
    global _fired_today, _last_fired_date
    today = _today_et()
    if _last_fired_date != today:
        _fired_today = set()
        _last_fired_date = today


def _flow_direction(option_type: str | None, sentiment: str | None) -> str:
    """Map (option_type, sentiment) → BULL/BEAR."""
    ot = (option_type or "").lower()
    sent = (sentiment or "").upper()
    if ot == "call":
        return "BULL" if sent == "BULLISH" else "BEAR"
    if ot == "put":
        return "BEAR" if sent == "BULLISH" else "BULL"
    return "NEUTRAL"


def _soe_direction(direction_raw: str | None) -> str:
    """Map SOE direction column to BULL/BEAR.

    SOE uses three formats:
      - "▲" → BULL  (the common case, 99%+ of legacy signals)
      - "▼" → BEAR
      - "BULL" / "BEAR" → as-is (newer SCALP variants)
    """
    d = (direction_raw or "").strip().upper()
    if d in ("BULL", "▲") or d.startswith("BULL"):
        return "BULL"
    if d in ("BEAR", "▼") or d.startswith("BEAR"):
        return "BEAR"
    return "NEUTRAL"


def _kingmig_direction(migration_type: str | None) -> str:
    """Map king migration_type → BULL/BEAR.

    UP migrations = king price climbing = bullish gamma flow
    DOWN migrations = king price dropping = bearish gamma flow
    """
    m = (migration_type or "").strip().upper()
    if m == "UP":
        return "BULL"
    if m == "DOWN":
        return "BEAR"
    return "NEUTRAL"


def _query_signals(now_ts: int) -> dict[str, dict[str, Any]]:
    """Scan all three signal sources in the rolling window. Returns:

      {
        ticker: {
          "BULL": {
              "flow_strikes": set of (strike, exp),
              "soe_aplus": int,
              "soe_a": int,
              "kingmig": [event_dicts],
          },
          "BEAR": {...},
          "flow_examples": {"BULL": [alert_dict], "BEAR": [alert_dict]},
          "soe_examples": {"BULL": [signal_dict], "BEAR": [signal_dict]},
        }
      }

    flow_strikes is a SET so re-fires of the same (strike, exp) collapse.
    """
    cutoff_ts = now_ts - CONFLUENCE_WINDOW_SEC
    by_ticker: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "BULL": {
                "flow_strikes": set(),
                "soe_aplus": 0,
                "soe_a": 0,
                "kingmig": [],
            },
            "BEAR": {
                "flow_strikes": set(),
                "soe_aplus": 0,
                "soe_a": 0,
                "kingmig": [],
            },
            "flow_examples": {"BULL": [], "BEAR": []},
            "soe_examples": {"BULL": [], "BEAR": []},
        }
    )

    # 1. INFORMED FLOW fires (is_insider=1) in window
    try:
        conn = sqlite3.connect("snapshots.db", timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ticker, strike, option_type, expiration, sentiment,
                      side, vol_oi, notional, last_price, insider_score, ts
               FROM flow_alerts
               WHERE ts >= ? AND is_insider = 1""",
            (cutoff_ts,),
        ).fetchall()
        for r in rows:
            tk = r["ticker"]
            if tk in _EXCLUDED_TICKERS:
                continue
            direction = _flow_direction(r["option_type"], r["sentiment"])
            if direction == "NEUTRAL":
                continue
            # Dedup by (strike, exp, option_type) — multiple fires on same
            # contract count as one unique strike signal.
            key = (r["strike"], r["expiration"], r["option_type"])
            by_ticker[tk][direction]["flow_strikes"].add(key)
            if len(by_ticker[tk]["flow_examples"][direction]) < 3:
                by_ticker[tk]["flow_examples"][direction].append(dict(r))
        conn.close()
    except Exception as e:
        print(f"[TRIPLE] flow query failed: {e!r}", flush=True)

    # 2. SOE signals — split A vs A+ buckets
    try:
        conn = sqlite3.connect("snapshots.db", timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ticker, direction, signal_type, grade, spot, target, ts
               FROM soe_signals
               WHERE ts >= ? AND grade IN ('A','A+')""",
            (cutoff_ts,),
        ).fetchall()
        for r in rows:
            tk = r["ticker"]
            if tk in _EXCLUDED_TICKERS:
                continue
            dir_norm = _soe_direction(r["direction"])
            if dir_norm == "NEUTRAL":
                continue
            grade = (r["grade"] or "").strip()
            if grade == "A+":
                by_ticker[tk][dir_norm]["soe_aplus"] += 1
            elif grade == "A":
                by_ticker[tk][dir_norm]["soe_a"] += 1
            if len(by_ticker[tk]["soe_examples"][dir_norm]) < 3:
                by_ticker[tk]["soe_examples"][dir_norm].append(dict(r))
        conn.close()
    except Exception as e:
        print(f"[TRIPLE] soe query failed: {e!r}", flush=True)

    # 3. QUALIFIED king migrations in window, with delta_pct floor
    kingmig_path = os.environ.get(
        "KING_MIGRATION_DB_PATH", "./king_migrations.db"
    )
    if os.path.exists(kingmig_path):
        try:
            conn = sqlite3.connect(kingmig_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, migration_ts, old_king, new_king,
                          delta_pts, spot, migration_type, qualified_reasons
                   FROM king_migrations
                   WHERE migration_ts >= ? AND qualified = 1""",
                (cutoff_ts,),
            ).fetchall()
            for r in rows:
                tk = r["ticker"]
                if tk in _EXCLUDED_TICKERS:
                    continue
                dir_norm = _kingmig_direction(r["migration_type"])
                if dir_norm == "NEUTRAL":
                    continue
                # Filter out small migrations: |delta| must be ≥1.5% of spot
                spot = float(r["spot"] or 0)
                delta = abs(float(r["delta_pts"] or 0))
                if spot > 0 and (delta / spot * 100) < MIN_KMIG_DELTA_PCT:
                    continue
                by_ticker[tk][dir_norm]["kingmig"].append(dict(r))
            conn.close()
        except Exception as e:
            print(f"[TRIPLE] kingmig query failed: {e!r}", flush=True)

    return dict(by_ticker)


def detect_confluences(now_ts: int | None = None) -> list[dict[str, Any]]:
    """Return list of triple-confluence dicts for tickers meeting criteria.

    Each result is a dict with everything needed for Telegram formatting:
      {
        "ticker": str,
        "direction": "BULL" | "BEAR",
        "flow_count": int,
        "soe_count": int,
        "kingmig_events": [event_dict, ...],
        "flow_examples": [alert_dict, ...],
        "soe_examples": [signal_dict, ...],
      }
    """
    if now_ts is None:
        now_ts = int(time.time())

    by_ticker = _query_signals(now_ts)
    results = []
    for ticker, data in by_ticker.items():
        for direction in ("BULL", "BEAR"):
            d = data[direction]
            n_flow_strikes = len(d["flow_strikes"])
            n_aplus = d["soe_aplus"]
            n_a = d["soe_a"]
            n_kmig = len(d["kingmig"])

            # Three-gate convergence check:
            #   (1) Multiple unique INFORMED FLOW strikes (institutional)
            #   (2) At least 1 A+ SOE signal (no A-only fallback)
            #   (3) At least one meaningful king migration in direction
            flow_ok = n_flow_strikes >= MIN_INFORMED_FLOW_UNIQUE_STRIKES
            soe_ok = n_aplus >= MIN_SOE_APLUS
            kmig_ok = n_kmig > 0

            if flow_ok and soe_ok and kmig_ok:
                results.append({
                    "ticker": ticker,
                    "direction": direction,
                    "flow_strike_count": n_flow_strikes,
                    "soe_aplus_count": n_aplus,
                    "soe_a_count": n_a,
                    "kingmig_events": d["kingmig"],
                    "flow_examples": data["flow_examples"][direction],
                    "soe_examples": data["soe_examples"][direction],
                })
    return results


def _format_telegram(confluence: dict[str, Any]) -> str:
    """Build the Telegram alert body."""
    tk = confluence["ticker"]
    direction = confluence["direction"]
    arrow = "🟢🟢🟢" if direction == "BULL" else "🔴🔴🔴"
    arrow_word = "BULLISH" if direction == "BULL" else "BEARISH"

    lines: list[str] = []
    lines.append(f"{arrow} <b>TRIPLE CONFLUENCE</b> {arrow} <b>{tk}</b> {arrow_word}")
    lines.append(
        f"<i>INFORMED FLOW + king migration + SOE A/A+ converging "
        f"in 4hr window</i>"
    )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    # 1. INFORMED FLOW summary
    n_flow = confluence["flow_strike_count"]
    lines.append(f"<b>1) INFORMED FLOW</b> ({n_flow} unique strikes)")
    for ex in confluence["flow_examples"][:2]:
        otype = (ex.get("option_type") or "")[:1].upper()
        sent = (ex.get("sentiment") or "")[:5]
        ntl = (ex.get("notional") or 0) / 1000
        lines.append(
            f"   ${ex.get('strike', 0):g}{otype} {ex.get('expiration', '')}"
            f"  V/OI={ex.get('vol_oi', 0):.1f}x  ${ntl:.0f}K  "
            f"<i>{sent}</i>"
        )

    # 2. SOE summary — A+ first, then A
    n_aplus = confluence["soe_aplus_count"]
    n_a = confluence["soe_a_count"]
    soe_label = (
        f"A+={n_aplus}, A={n_a}" if n_aplus else f"A={n_a}"
    )
    lines.append(f"<b>2) SOE quality signals</b> ({soe_label})")
    for ex in confluence["soe_examples"][:2]:
        sig = ex.get("signal_type", "")
        grade = ex.get("grade", "")
        spot = ex.get("spot", 0)
        target = ex.get("target", 0)
        lines.append(
            f"   {grade} {sig}  spot ${spot:.2f} → ${target:.2f}"
        )

    # 3. King migration summary
    kmevents = confluence["kingmig_events"]
    lines.append(f"<b>3) KING MIGRATION</b> ({len(kmevents)} qualified)")
    for ev in kmevents[:2]:
        old_k = ev.get("old_king", 0)
        new_k = ev.get("new_king", 0)
        spot = ev.get("spot", 0)
        m_type = ev.get("migration_type", "")
        lines.append(
            f"   {m_type}  ${old_k:.0f} → ${new_k:.0f}  (spot ${spot:.2f})"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"<i>3-signal convergence is rare. Historical MRVL 5/28 setup "
        f"caught +362% to +1,930% within 5 days.</i>"
    )
    return "\n".join(lines)


async def maybe_fire_triple_confluence() -> int:
    """Scan for triple confluences and fire Telegram alerts for new ones.
    Returns count of confluences fired this cycle.

    Idempotent within a day: each (ticker, direction) only fires once per
    ET calendar day. Cheap no-op when no confluences exist (typical case).
    Worker should call this every scan cycle.
    """
    _reset_dedup_if_new_day()

    try:
        confluences = detect_confluences()
    except Exception as e:
        print(f"[TRIPLE] detect failed: {e!r}", flush=True)
        return 0

    if not confluences:
        return 0

    fired = 0
    today = _today_et()
    today_iso = today.isoformat()

    for conf in confluences:
        key = (conf["ticker"], conf["direction"], today_iso)
        if key in _fired_today:
            continue

        try:
            msg = _format_telegram(conf)
            # TRIPLE → suppressed (task #94 follow-up). The composite triple-
            # confluence alert tested ANTI-PREDICTIVE in the Jun-20 audit (lowest
            # WR 36.4%, the only category with a NEGATIVE mean move -0.73%, loses
            # train AND test). Suppress the Telegram push; dedup + console log are
            # untouched so it stays visible. Reversible: env TRIPLE_TELEGRAM=1.
            from .telegram import send, triple_telegram_on
            if not triple_telegram_on():
                try:
                    from . import telegram_audit
                    telegram_audit.record_drop(text=msg, ticker=conf["ticker"],
                                               drop_reason="triple_demoted")
                except Exception:
                    pass
                _fired_today.add(key)   # dedup so it isn't re-evaluated all session
                print(f"[TRIPLE] suppressed {conf['ticker']} {conf['direction']} "
                      f"(TRIPLE_TELEGRAM off — anti-predictive in audit)", flush=True)
                continue
            ok = await send(msg, ticker=conf["ticker"], priority=True, force=True)
            if ok:
                _fired_today.add(key)
                fired += 1
                print(
                    f"[TRIPLE] fired {conf['ticker']} {conf['direction']} "
                    f"(flow_strikes={conf['flow_strike_count']} "
                    f"soe_aplus={conf['soe_aplus_count']} "
                    f"soe_a={conf['soe_a_count']} "
                    f"kmig={len(conf['kingmig_events'])})",
                    flush=True,
                )
        except Exception as e:
            print(
                f"[TRIPLE] send failed {conf['ticker']}: {e!r}",
                flush=True,
            )

    return fired
