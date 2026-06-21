"""B3 (buy-the-dip in a confirmed uptrend): structural pullback-continuation.
Event = close above the 200SMA (regime is an uptrend) AND close below the 20SMA
(a short-term dip) AND the 20SMA is still rising (20SMA today > 20SMA five bars
ago, i.e. the intermediate trend has NOT rolled over) -> LONG 5d. This probes
whether shallow dips into a rising short MA, inside a long-term uptrend, resolve
up across the 40-name cross-section rather than being just QQQ-megacap beta."""
import numpy as np

SPEC = dict(id="B3_pullback_in_uptrend",
            name="Pullback in confirmed uptrend (dip < rising 20SMA, > 200SMA)",
            category="B2",
            description="close>200SMA AND close<20SMA AND 20SMA[t]>20SMA[t-5]; LONG 5d. Cross-section.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    sma20 = H.sma(close, 20)
    sma200 = H.sma(close, 200)
    sma20_s = pd.Series(sma20)
    rising20 = (sma20_s > sma20_s.shift(5)).to_numpy()      # 20SMA today > 5 bars ago, causal

    in_uptrend = close > sma200
    below_short = close < sma20
    m = np.asarray((in_uptrend & below_short & rising20), bool).copy()
    m[~np.isfinite(sma20)] = False
    m[~np.isfinite(sma200)] = False
    return m
