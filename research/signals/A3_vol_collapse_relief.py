"""A3 (vol-collapse relief rally): when 20d realized vol has fallen out of an
elevated state -- rv20 today is BELOW its trailing 252d median AND rv20 five bars
ago was ABOVE its 252d median -- buy the relief. LONG 5d. Causal: rv20 from
pct_change rolling(20).std()*sqrt(252); the 252d median is a backward-looking
rolling quantile (includes the current bar, which is allowed)."""
import numpy as np

SPEC = dict(id="A3_vol_collapse_relief",
            name="Volatility-collapse relief rally (rv20 falls below its 252d median)",
            category="A1",
            description="rv20<median(rv20,252) today AND rv20[t-5]>its 252d median; LONG 5d.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    med = rv20.rolling(252).median()                 # backward-looking median
    below = (rv20 < med)                             # vol now below its own median
    above5 = (rv20 > med).shift(5)                    # five bars ago it was above
    m = np.asarray((below & above5).to_numpy(), dtype=bool).copy()
    # guard: kill bars where any required input is NaN
    bad = (~np.isfinite(rv20.to_numpy())
           | ~np.isfinite(med.to_numpy())
           | ~np.isfinite(above5.to_numpy().astype(float)))
    m[bad] = False
    return m
