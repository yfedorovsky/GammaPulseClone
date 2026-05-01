"""Microstructure features from Databento MBP-1: OFI and microprice.

Implements two well-known microstructure signals that the literature
treats as more informative than tick-rule for short-term price prediction:

  - Order Flow Imbalance (OFI), Cont/Kukanov/Stoikov (2014):
      "The price impact of order book events"
    Tracks net liquidity demand at the BBO. Positive OFI = buying
    pressure, negative = selling pressure. Aggregated over a window,
    it has been shown to predict short-horizon returns with R² of
    ~0.05-0.15 on liquid index ETFs.

  - Microprice, Bonart (2017):
      "What is the optimal weighted bid/ask price?"
    A weighted mid-price using OPPOSITE-side liquidity:
        microprice = (bid_sz × ask_px + ask_sz × bid_px) / (bid_sz + ask_sz)
    A heavy bid stack (bid_sz >> ask_sz) pushes microprice toward the
    ask, predicting upward drift; vice versa. Microprice deviation
    from mid (microprice − mid) is a leading indicator of next mid move.

These features become inputs for any future v2 detector that wants to
upgrade from tick-rule based gates. This module just provides the
computations — it does not modify any production gate. Audit consumers
(e.g., gate8_audit.py extension) join these features to fire events
and test whether they predict gated outcomes.

The functions are vectorized via numpy and run in O(N) over millions
of events without Python loops.

Self-test: `python scripts/microstructure_features.py`
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd


# ── Order Flow Imbalance (Cont, Kukanov, Stoikov 2014) ────────────


def compute_ofi_per_event(quotes: pd.DataFrame) -> pd.Series:
    """Compute the per-event order flow imbalance contribution e_n.

    For each quote event n with prior n-1:
      bid contribution:
        if bid_px ↑           : +bid_sz[n]            (new bid price level set with size)
        if bid_px ↓           : -bid_sz[n-1]          (prior bid level wiped)
        if bid_px unchanged   : bid_sz[n] - bid_sz[n-1]   (size change at same price)
      ask contribution (sign flipped — ask buying = sell pressure):
        if ask_px ↓           : -ask_sz[n]
        if ask_px ↑           : +ask_sz[n-1]
        if ask_px unchanged   : ask_sz[n-1] - ask_sz[n]

    e_n = e_bid + e_ask. Cumulative sum over a window is the OFI.

    Args:
      quotes: DataFrame sorted by time with columns
        bid_px_00, bid_sz_00, ask_px_00, ask_sz_00

    Returns:
      Series of per-event OFI contributions (NOT cumulative; same index).
      The first row's contribution is 0 (no prior to diff against).
    """
    if quotes.empty or len(quotes) < 2:
        return pd.Series([0.0] * len(quotes), index=quotes.index, dtype=float)

    bid_px = quotes["bid_px_00"].to_numpy(dtype=float)
    bid_sz = quotes["bid_sz_00"].to_numpy(dtype=float)
    ask_px = quotes["ask_px_00"].to_numpy(dtype=float)
    ask_sz = quotes["ask_sz_00"].to_numpy(dtype=float)

    # Prior values (shift by 1)
    prior_bid_px = np.roll(bid_px, 1)
    prior_bid_sz = np.roll(bid_sz, 1)
    prior_ask_px = np.roll(ask_px, 1)
    prior_ask_sz = np.roll(ask_sz, 1)

    # Bid-side contribution
    bid_px_up = bid_px > prior_bid_px
    bid_px_dn = bid_px < prior_bid_px
    e_bid = np.where(
        bid_px_up, bid_sz,
        np.where(bid_px_dn, -prior_bid_sz, bid_sz - prior_bid_sz),
    )

    # Ask-side contribution (sign-flipped per Cont 2014)
    ask_px_up = ask_px > prior_ask_px
    ask_px_dn = ask_px < prior_ask_px
    e_ask = np.where(
        ask_px_dn, -ask_sz,
        np.where(ask_px_up, prior_ask_sz, prior_ask_sz - ask_sz),
    )

    e = e_bid + e_ask

    # First row has no prior — zero it out
    e[0] = 0.0

    # NaN handling: any row with NaN in any of the four BBO fields
    # contributes 0. Without this, a single NaN spreads through cumsum.
    nan_mask = (np.isnan(bid_px) | np.isnan(ask_px)
                | np.isnan(bid_sz) | np.isnan(ask_sz)
                | np.isnan(prior_bid_px) | np.isnan(prior_ask_px)
                | np.isnan(prior_bid_sz) | np.isnan(prior_ask_sz))
    e[nan_mask] = 0.0

    return pd.Series(e, index=quotes.index, dtype=float)


def cumulative_ofi(quotes: pd.DataFrame) -> pd.Series:
    """Cumulative OFI over the entire quote series."""
    return compute_ofi_per_event(quotes).cumsum()


# ── Microprice (Bonart 2017) ──────────────────────────────────────


def compute_microprice(
    bid_px: np.ndarray, ask_px: np.ndarray,
    bid_sz: np.ndarray, ask_sz: np.ndarray,
) -> np.ndarray:
    """Vectorized microprice computation.

    microprice = (bid_sz × ask_px + ask_sz × bid_px) / (bid_sz + ask_sz)

    Note the weights: the OPPOSITE side's size weights each price. Heavy
    bid stack → microprice leans toward ask (upward bias).
    """
    total = bid_sz + ask_sz
    with np.errstate(divide="ignore", invalid="ignore"):
        mp = np.where(
            total > 0,
            (bid_sz * ask_px + ask_sz * bid_px) / total,
            np.nan,
        )
    return mp


def add_microprice_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return df with two new columns added:
      - mid:        (bid_px_00 + ask_px_00) / 2
      - microprice: opposite-size-weighted mean
      - mp_minus_mid: signed deviation (positive = bid stack heavy → bullish bias)
    """
    out = df.copy()
    bid_px = out["bid_px_00"].to_numpy(dtype=float)
    ask_px = out["ask_px_00"].to_numpy(dtype=float)
    bid_sz = out["bid_sz_00"].to_numpy(dtype=float)
    ask_sz = out["ask_sz_00"].to_numpy(dtype=float)
    out["mid"] = (bid_px + ask_px) / 2
    out["microprice"] = compute_microprice(bid_px, ask_px, bid_sz, ask_sz)
    out["mp_minus_mid"] = out["microprice"] - out["mid"]
    return out


# ── Window-level aggregates for fire-time analysis ───────────────


def window_ofi(
    quotes: pd.DataFrame,
    start_ns: int | None = None, end_ns: int | None = None,
) -> float:
    """Sum of per-event OFI within [start_ns, end_ns]. None means no bound."""
    sub = quotes
    if start_ns is not None:
        sub = sub[sub["ts_event_ns"] >= start_ns]
    if end_ns is not None:
        sub = sub[sub["ts_event_ns"] <= end_ns]
    if sub.empty:
        return 0.0
    return float(compute_ofi_per_event(sub).sum())


def window_microprice_stats(
    quotes: pd.DataFrame,
    start_ns: int | None = None, end_ns: int | None = None,
) -> dict:
    """Aggregate microprice deviation stats over a window.

    Returns dict with mean_mp_minus_mid, std_mp_minus_mid, last_mp_minus_mid,
    n_events, last_mid, last_microprice.
    """
    sub = quotes
    if start_ns is not None:
        sub = sub[sub["ts_event_ns"] >= start_ns]
    if end_ns is not None:
        sub = sub[sub["ts_event_ns"] <= end_ns]
    if sub.empty:
        return {
            "n_events": 0, "mean_mp_minus_mid": None,
            "std_mp_minus_mid": None, "last_mp_minus_mid": None,
            "last_mid": None, "last_microprice": None,
        }
    sub = add_microprice_columns(sub)
    last = sub.iloc[-1]
    return {
        "n_events": int(len(sub)),
        "mean_mp_minus_mid": float(sub["mp_minus_mid"].mean()),
        "std_mp_minus_mid": float(sub["mp_minus_mid"].std()),
        "last_mp_minus_mid": float(last["mp_minus_mid"]),
        "last_mid": float(last["mid"]),
        "last_microprice": float(last["microprice"]),
    }


# ── Self-test ─────────────────────────────────────────────────────


def _self_test() -> None:
    """Synthetic test of OFI and microprice on a tiny event sequence."""
    import io
    csv = """ts_event_ns,bid_px_00,bid_sz_00,ask_px_00,ask_sz_00
1,99.99,1000,100.01,1000
2,99.99,1500,100.01,1000
3,100.00,500,100.01,1000
4,100.00,500,100.02,500
5,99.99,1000,100.02,500
"""
    df = pd.read_csv(io.StringIO(csv))
    print("Quotes:")
    print(df.to_string(index=False))

    print("\nPer-event OFI:")
    print(compute_ofi_per_event(df).to_list())
    # Walk through:
    #  Event 1: first → 0
    #  Event 2: bid_px unchanged, bid_sz +500 → +500. ask unchanged → 0. Total = +500
    #  Event 3: bid_px UP (99.99→100.00) → +bid_sz[3]=+500. ask unchanged → 0. Total = +500
    #  Event 4: bid unchanged → 0. ask_px UP (100.01→100.02) → +prior_ask_sz=+1000. Total = +1000
    #            (ask price moving UP = sellers backing off → bullish → +OFI ✓)
    #  Event 5: bid_px DN (100.00→99.99) → -prior_bid_sz=-500. ask unchanged → 0. Total = -500
    print("\nCumulative OFI:")
    print(cumulative_ofi(df).to_list())

    print("\nMicroprice:")
    print(add_microprice_columns(df)[["mid", "microprice", "mp_minus_mid"]]
          .to_string(index=False))

    print("\nWindow OFI (whole sample):", window_ofi(df))
    print("Window microprice stats:", window_microprice_stats(df))


if __name__ == "__main__":
    _self_test()
    sys.exit(0)
