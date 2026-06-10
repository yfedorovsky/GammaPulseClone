"""Signature scan — the LIVE whale/informed classifiers over cached EOD chains.

PORTED, not re-invented, from ``server/flow_alerts.py`` @ main 2026-06-09
(``_classify_whale_signature`` lines ~634-704, ``_classify_insider_signature``
lines ~336-483, ``_is_parity_arb_call`` lines ~599-631, constants lines
~548-590). The backtest must grade the ACTUAL live signature with the live
constants or it isn't testing the real signal.

Adaptations for EOD replay (each documented; none changes a threshold):
  - "today" in every DTE computation is the SCAN DATE, not the wall clock.
  - volume/notional are the day's totals (volume x close x 100) — the same
    cumulative quantities the live scanner sees by EOD.
  - V/OI denominator is the cache row's ``oi`` — ThetaData's morning-settled
    value (= end of prior day), exactly the live snapshot semantics.
  - SIDE is not asserted at scan time. The scan emits candidates that pass
    every side-INDEPENDENT gate and could fire IF the side were ASK; the
    replay pipeline then reads the actual side from the OPRA tape
    (side_confirmation) and finalizes. Replay labels are therefore
    TAPE-clean — strictly better than the live snapshot guess.
  - KNOWN DIVERGENCES (replay is slightly MORE permissive than live):
      1. chop suppression (live gate 7) needs intraday two-way notional
         state — not reconstructable from EOD; omitted.
      2. the INFORMED earnings catalyst-demote needs a historical earnings
         calendar; the live source is API/forward-only — omitted. A live
         5/6-with-catalyst would NOT have fired; replay counts it.
    Both make replay hit-counts an UPPER BOUND on live fires; documented in
    REPLAY_FINDINGS.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Optional

# ── Live constants (server/flow_alerts.py @ 2026-06-09, lines ~548-590) ────
WHALE_MIN_NOTIONAL = 1_000_000        # $1M DB-tag floor.
WHALE_MIN_VOL = 500                   # filter retail.
WHALE_MIN_VOL_OI_RATIO = 0.30         # >= 30% of OI = real accumulation.
WHALE_PARITY_EXTRINSIC_PCT = 0.003    # extrinsic <= 0.3% of spot = parity.
WHALE_PARITY_DEEP_ITM_DELTA = 0.85
WHALE_PARITY_DEEP_ITM_STRIKE_PCT = 0.95
WHALE_EXCLUDED_TICKERS = frozenset({
    "SPY", "SPX", "SPXW", "QQQ", "IWM", "DIA", "VIX", "NDX",
    "SOXL", "TQQQ", "SQQQ", "UPRO", "TSLL", "NVDL",
})
INFORMED_MIN_SCORE = 5                # score >= 5 (of 6) -> is_insider.


@dataclass
class Candidate:
    """A contract-day that passes every side-independent gate of a signature.

    ``needs_ask``: the signature only fires if the tape says the flow was
    buyer-initiated (ASK). For WHALE that is a hard gate; for INFORMED the
    candidate's ``score_if_ask`` already includes the ASK point — the final
    score subtracts it when the tape disagrees.
    """
    signature: str          # 'WHALE' / 'INFORMED'
    date: str
    root: str
    expiration: str
    strike: float
    right: str              # 'C' / 'P'
    volume: int
    oi: int
    vol_oi: float
    close: float
    bid: float
    ask: float
    delta: float
    iv: Optional[float]
    spot: float
    notional: float
    dte: int
    score_if_ask: int = 0   # INFORMED only.
    reasons: str = ""


def _row_val(row, key, default=0.0):
    v = row[key] if key in row.keys() else None
    return default if v is None else v


def is_parity_arb_call(*, right: str, spot: float, strike: float, close: float,
                       delta: float) -> bool:
    """Port of _is_parity_arb_call (dividend-capture suppression, task #49)."""
    if right != "C":
        return False
    if spot <= 0 or close <= 0 or strike <= 0:
        return False
    deep_itm = (abs(delta) >= WHALE_PARITY_DEEP_ITM_DELTA
                or strike <= spot * WHALE_PARITY_DEEP_ITM_STRIKE_PCT)
    if not deep_itm:
        return False
    intrinsic = max(0.0, spot - strike)
    return (close - intrinsic) <= spot * WHALE_PARITY_EXTRINSIC_PCT


def whale_candidate(row) -> Optional[Candidate]:
    """Side-independent gates of _classify_whale_signature on a cache row.

    Live gate order: ticker excl -> notional >= $1M -> side==ASK (DEFERRED to
    tape) -> vol >= 500 -> vol >= oi*0.30 -> sentiment alignment (implied by
    ASK: call+ASK=BULLISH, put+ASK=BEARISH — always consistent once the tape
    confirms ASK) -> parity-arb -> chop (omitted, see module docstring).
    """
    root = (row["root"] or "").upper()
    if not root or root in WHALE_EXCLUDED_TICKERS:
        return None
    vol = int(_row_val(row, "volume", 0))
    close = float(_row_val(row, "close", 0.0))
    notional = vol * close * 100.0
    if notional < WHALE_MIN_NOTIONAL:
        return None
    if vol < WHALE_MIN_VOL:
        return None
    oi = int(_row_val(row, "oi", 0))
    if oi > 0 and vol < oi * WHALE_MIN_VOL_OI_RATIO:
        return None
    spot = float(_row_val(row, "spot", 0.0))
    strike = float(row["strike"])
    delta = float(_row_val(row, "delta", 0.0))
    if is_parity_arb_call(right=row["right"], spot=spot, strike=strike,
                          close=close, delta=delta):
        return None
    dte = _dte(row["expiration"], row["date"])
    return Candidate(
        signature="WHALE", date=row["date"], root=root,
        expiration=row["expiration"], strike=strike, right=row["right"],
        volume=vol, oi=oi, vol_oi=(vol / oi) if oi > 0 else float("inf"),
        close=close, bid=float(_row_val(row, "bid", 0.0)),
        ask=float(_row_val(row, "ask", 0.0)), delta=delta,
        iv=row["iv"] if "iv" in row.keys() else None, spot=spot,
        notional=notional, dte=dte,
        reasons=f"${notional/1e6:.1f}M vol={vol}"
                + (f" vol/oi={vol/oi:.1f}x" if oi > 0 else ""))


def _dte(expiration: str, scan_date: str) -> int:
    try:
        return (_date.fromisoformat(expiration)
                - _date.fromisoformat(scan_date)).days
    except ValueError:
        return -1


def informed_candidate(row) -> Optional[Candidate]:
    """Side-independent port of _classify_insider_signature on a cache row.

    Hard gates (live order): (oi>=100 OR vol>=500) -> notional >= $10K ->
    V/OI >= 10 (REQUIRED, not a vote) -> DTE >= 0 (vs the SCAN date).
    Criteria (1pt each): V/OI>=10 · vol>oi · ASK (from tape later) ·
    cheap (premium<=$5 via ask else last, OR OTM>=3% moneyness) ·
    DTE<=7 · 0<|delta|<=0.40. Fires at score >= 5; here we compute
    ``score_if_ask`` (ASK point included) and emit only candidates that
    COULD fire (score_if_ask >= 5). Earnings demote omitted (see docstring).
    """
    vol = int(_row_val(row, "volume", 0))
    oi = int(_row_val(row, "oi", 0))
    if oi < 100 and vol < 500:
        return None
    close = float(_row_val(row, "close", 0.0))
    notional = vol * close * 100.0
    if notional < 10_000:
        return None
    vol_oi = (vol / oi) if oi > 0 else (float("inf") if vol > 0 else 0.0)
    if vol_oi < 10:
        return None
    dte = _dte(row["expiration"], row["date"])
    if dte < 0:
        return None

    matched = ["V/OI>=10x"]
    if vol > 0 and oi > 0 and vol > oi:
        matched.append("OPEN(vol>oi)")
    matched.append("ASK-side?")          # granted here; tape decides for real.
    ask = float(_row_val(row, "ask", 0.0))
    premium = ask if ask > 0 else close
    spot = float(_row_val(row, "spot", 0.0))
    strike = float(row["strike"])
    moneyness_otm = 0.0
    if spot > 0 and strike > 0:
        moneyness_otm = ((strike - spot) / spot if row["right"] == "C"
                         else (spot - strike) / spot)
    if (0 < premium <= 5.00) or moneyness_otm >= 0.03:
        matched.append("cheap/OTM")
    if 0 <= dte <= 7:
        matched.append(f"{dte}DTE")
    delta = float(_row_val(row, "delta", 0.0))
    if 0 < abs(delta) <= 0.40:
        matched.append(f"D{abs(delta):.2f}")

    score_if_ask = len(matched)
    if score_if_ask < INFORMED_MIN_SCORE:
        return None
    return Candidate(
        signature="INFORMED", date=row["date"], root=(row["root"] or "").upper(),
        expiration=row["expiration"], strike=strike, right=row["right"],
        volume=vol, oi=oi, vol_oi=vol_oi, close=close,
        bid=float(_row_val(row, "bid", 0.0)), ask=ask, delta=delta,
        iv=row["iv"] if "iv" in row.keys() else None, spot=spot,
        notional=notional, dte=dte, score_if_ask=score_if_ask,
        reasons=",".join(matched))


def scan_day(con, date: str, signature: str,
             roots: Optional[list[str]] = None) -> list[Candidate]:
    """Scan one cached trading day for signature candidates."""
    fn = {"WHALE": whale_candidate, "INFORMED": informed_candidate}[signature]
    sql = "SELECT * FROM option_eod WHERE date = ? AND COALESCE(volume,0) > 0"
    params: list = [date]
    if roots:
        sql += f" AND root IN ({','.join('?' * len(roots))})"
        params += [r.upper() for r in roots]
    out = []
    for row in con.execute(sql, params):
        c = fn(row)
        if c is not None:
            out.append(c)
    return out


__all__ = [
    "Candidate", "scan_day", "whale_candidate", "informed_candidate",
    "is_parity_arb_call", "WHALE_EXCLUDED_TICKERS", "INFORMED_MIN_SCORE",
]
