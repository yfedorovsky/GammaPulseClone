"""B1 (momentum): classic Jegadeesh-Titman 12-1 momentum. Trailing 12-month
return excluding the most recent month, in the top causal tercile of its own
252d history, AND close>200SMA -> LONG 10d. The 40-name cross-section is the
point: real momentum should show breadth, not just QQQ-megacap beta."""
import numpy as np

SPEC = dict(id="B1_mom_12_1", name="12-1 month momentum (top tercile, uptrend)",
            category="B1",
            description="ret[t-252..t-21] > rolling-252d 66.7pct AND close>200SMA; LONG 10d. Cross-section.",
            side="long", horizon=10, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = pd.Series(df["close"].to_numpy())
    mom = close.shift(21) / close.shift(252) - 1.0      # 12m ex last 1m, causal
    thr = mom.rolling(252).quantile(0.667)              # causal rolling tercile
    sma200 = pd.Series(H.sma(close.to_numpy(), 200))
    m = np.asarray(((mom > thr) & (close > sma200)).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(thr.to_numpy())] = False
    m[~np.isfinite(sma200.to_numpy())] = False
    return m
