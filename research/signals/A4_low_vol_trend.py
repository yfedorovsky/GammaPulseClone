"""A4 (low-vol melt-up / betting-against-beta flavor): when 20-day realized vol
sits in the bottom causal tercile of its own trailing-252d history AND the
instrument is in a confirmed uptrend (close>200SMA) -> LONG 10d. The premise is
the low-volatility / low-beta anomaly: quiet uptrends keep grinding higher.
The 40-name cross-section is the real test -- a genuine low-vol effect should
show breadth, not just QQQ megacap beta."""
import numpy as np

SPEC = dict(id="A4_low_vol_trend",
            name="Low-vol melt-up (rv20 bottom tercile, uptrend)",
            category="A2",
            description="rv20 < trailing-252d 33.3pct AND close>200SMA; LONG 10d. Cross-section.",
            side="long", horizon=10, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = pd.Series(df["close"].to_numpy())
    r = close.pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)         # 20d realized vol, causal
    thr = rv20.rolling(252).quantile(0.333)             # causal rolling bottom tercile
    sma200 = pd.Series(H.sma(close.to_numpy(), 200))
    m = np.asarray(((rv20 < thr) & (close > sma200)).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(rv20.to_numpy())] = False
    m[~np.isfinite(thr.to_numpy())] = False
    m[~np.isfinite(sma200.to_numpy())] = False
    return m
