"""B4 (momentum acceleration): the recent 10-day pace is exceeding the 20-day pace
while both are positive, and price is above its 50SMA. ret10 = close/close.shift(10)-1;
ret20 = close/close.shift(20)-1. Event = ret10 > ret20 AND ret20 > 0 AND close>50SMA
-> LONG 5d. Probes whether *accelerating* momentum (second-derivative positive) beats
the already-tested level-momentum signals; cross-section tests breadth across 40 names."""
import numpy as np

SPEC = dict(id="B4_momentum_accel", name="Momentum acceleration (10d pace > 20d pace, uptrend)",
            category="B4",
            description="ret10>ret20 AND ret20>0 AND close>50SMA; LONG 5d. Cross-section.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = pd.Series(df["close"].to_numpy())
    ret10 = close / close.shift(10) - 1.0      # causal 10d return
    ret20 = close / close.shift(20) - 1.0      # causal 20d return
    sma50 = pd.Series(H.sma(close.to_numpy(), 50))
    m = np.asarray(((ret10 > ret20) & (ret20 > 0) & (close > sma50)).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(ret10.to_numpy())] = False
    m[~np.isfinite(ret20.to_numpy())] = False
    m[~np.isfinite(sma50.to_numpy())] = False
    return m
