"""Lee-Ready trade classification + tick-rule reference implementation.

Per Perplexity's critique (Apr 30): the existing Gate 5 (NCP corroboration)
and Gate 8 (CVD divergence) rely on tick-rule trade classification, which
the literature says is materially less accurate for options than for
equities. This module provides:

  - tick_rule_classify(): the "current" baseline used in our gate logic,
    purely price-vs-prior-price.
  - lee_ready_classify(): Lee-Ready (1991), uses NBBO mid at trade time:
      trade > mid → BUY
      trade < mid → SELL
      trade == mid → fall back to tick rule

Both produce a BUY/SELL/UNKNOWN label per trade. Unknown is rare for
Lee-Ready on liquid names like SPY/QQQ — usually only when the trade
arrives between two same-priced quotes and the tick-rule fallback also
ties.

The audit consumer (gate8_audit.py) compares cumulative volume delta
under both schemes around fire times to test whether quote-based
classification predicts gated outcomes better than tick-rule.

References:
  Lee, C.M.C. & Ready, M.J. (1991). "Inferring Trade Direction from
  Intraday Data." Journal of Finance.
  Easley, López de Prado, O'Hara (2016) discusses LR bias on modern
  high-speed markets but it remains the standard equity reference.

This module is dependency-free except pandas/numpy. The trade DataFrame
is expected to have columns:
  ts_event_ns (int64), price (float), size (int),
  bid_px_00 (float), ask_px_00 (float)

For Databento MBP-1 schema, the BBO columns are populated at every event
(including trade events), so the NBBO at trade time is directly available
without a separate quote-merge step.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


Side = Literal["BUY", "SELL", "UNKNOWN"]


def tick_rule_classify(trades: pd.DataFrame) -> pd.Series:
    """Tick rule: compare each trade price to the previous DIFFERENT price.

      uptick   → BUY
      downtick → SELL
      same     → carry forward last non-tie direction
      first    → UNKNOWN until first price change

    Args:
      trades: DataFrame sorted by ts_event_ns with a 'price' column.

    Returns:
      Series of {'BUY', 'SELL', 'UNKNOWN'} with same index as trades.
    """
    if trades.empty:
        return pd.Series([], dtype="object")
    prices = trades["price"].to_numpy()
    out = np.array(["UNKNOWN"] * len(prices), dtype=object)
    last_diff_price = None
    last_label = "UNKNOWN"
    for i, p in enumerate(prices):
        if last_diff_price is None:
            out[i] = "UNKNOWN"
            last_diff_price = p
            continue
        if p > last_diff_price:
            out[i] = "BUY"
            last_label = "BUY"
            last_diff_price = p
        elif p < last_diff_price:
            out[i] = "SELL"
            last_label = "SELL"
            last_diff_price = p
        else:
            out[i] = last_label  # carry forward
    return pd.Series(out, index=trades.index)


def lee_ready_classify(trades: pd.DataFrame) -> pd.Series:
    """Lee-Ready: classify each trade by comparison to the NBBO mid at
    trade time, with tick-rule fallback when price equals mid.

    Args:
      trades: DataFrame sorted by ts_event_ns with columns
        'price', 'bid_px_00', 'ask_px_00'.

    Returns:
      Series of {'BUY', 'SELL', 'UNKNOWN'} with same index as trades.
    """
    if trades.empty:
        return pd.Series([], dtype="object")
    prices = trades["price"].to_numpy()
    bids = trades["bid_px_00"].to_numpy()
    asks = trades["ask_px_00"].to_numpy()
    mids = (bids + asks) / 2

    # Quote-mid comparison
    out = np.full(len(prices), "UNKNOWN", dtype=object)
    above = prices > mids
    below = prices < mids
    out[above] = "BUY"
    out[below] = "SELL"

    # For ties (price == mid OR missing quote), fall back to tick rule.
    tie_mask = (~above) & (~below)
    if tie_mask.any():
        # Run tick-rule once and use only the tie positions
        tr = tick_rule_classify(trades).to_numpy()
        out[tie_mask] = tr[tie_mask]
    return pd.Series(out, index=trades.index)


def cumulative_volume_delta(
    trades: pd.DataFrame, classifier: str = "lee_ready",
) -> pd.Series:
    """Compute cumulative signed volume (CVD) for the trade series.

    BUY trades add +size, SELL trades subtract -size, UNKNOWN are 0.

    Args:
      trades: DataFrame with 'size' column and the necessary classifier
        inputs ('price' for tick_rule; 'price' + 'bid_px_00' + 'ask_px_00'
        for lee_ready).
      classifier: 'lee_ready' or 'tick_rule'.

    Returns:
      Series of cumulative signed volume, same index as trades.
    """
    if trades.empty:
        return pd.Series([], dtype=float)
    if classifier == "lee_ready":
        labels = lee_ready_classify(trades)
    elif classifier == "tick_rule":
        labels = tick_rule_classify(trades)
    else:
        raise ValueError(f"unknown classifier: {classifier}")

    sign = pd.Series(np.where(
        labels == "BUY", 1.0,
        np.where(labels == "SELL", -1.0, 0.0),
    ), index=trades.index)
    signed_size = sign * trades["size"]
    return signed_size.cumsum()


def cvd_divergence(
    trades: pd.DataFrame,
) -> dict:
    """For one trade window, return summary stats comparing the two
    classifiers' end-of-window CVD.

    Useful for the Gate 8 audit: was the tick-rule CVD that the live
    detector saw materially different from the Lee-Ready CVD that quote-
    based classification would have produced?
    """
    if trades.empty:
        return {"n_trades": 0, "cvd_lr": 0.0, "cvd_tr": 0.0,
                "diff_pct_of_volume": 0.0,
                "agreement_pct": None}
    cvd_lr_series = cumulative_volume_delta(trades, "lee_ready")
    cvd_tr_series = cumulative_volume_delta(trades, "tick_rule")
    cvd_lr = float(cvd_lr_series.iloc[-1])
    cvd_tr = float(cvd_tr_series.iloc[-1])
    total_vol = float(trades["size"].sum())

    # Per-trade agreement rate
    lr = lee_ready_classify(trades)
    tr = tick_rule_classify(trades)
    agree = (lr == tr).sum()
    agreement_pct = float(agree) / len(trades) * 100 if len(trades) else None

    return {
        "n_trades": int(len(trades)),
        "total_volume": total_vol,
        "cvd_lr": cvd_lr,
        "cvd_tr": cvd_tr,
        "diff_abs": cvd_lr - cvd_tr,
        "diff_pct_of_volume": (cvd_lr - cvd_tr) / total_vol * 100
                              if total_vol > 0 else 0.0,
        "agreement_pct": agreement_pct,
        "lr_bull_pct": (lr == "BUY").sum() / len(lr) * 100,
        "tr_bull_pct": (tr == "BUY").sum() / len(tr) * 100,
    }


# ── Self-test (run module directly) ─────────────────────────────────


if __name__ == "__main__":
    # Tiny synthetic test
    import io
    csv = """ts_event_ns,price,size,bid_px_00,ask_px_00
1,100.00,100,99.99,100.01
2,100.01,200,99.99,100.01
3,100.00,150,99.99,100.01
4,100.00,50,99.99,100.01
5,99.99,100,99.99,100.01
6,100.02,300,100.00,100.02
"""
    df = pd.read_csv(io.StringIO(csv))
    print("Trades:")
    print(df)
    print("\nLee-Ready:", lee_ready_classify(df).tolist())
    print("Tick-rule:", tick_rule_classify(df).tolist())
    print("\nDivergence stats:")
    for k, v in cvd_divergence(df).items():
        print(f"  {k}: {v}")
