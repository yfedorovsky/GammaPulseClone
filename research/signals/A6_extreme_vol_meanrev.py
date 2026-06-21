"""A6 (extreme-stress mean reversion): when 20d realized vol pushes ABOVE its own
trailing 252d 90th percentile (a causal rolling quantile -- extreme stress for that
instrument), LONG the washout for 10 days. Fully causal: rv20 is trailing, and the
90th-pct threshold is a backward-looking rolling quantile that includes the current
bar (which is fine -- no future bars referenced)."""
import numpy as np

SPEC = dict(id="A6_extreme_vol_meanrev",
            name="Extreme realized-vol washout mean reversion",
            category="A4",
            description="rv20 > trailing-252d 90th pct of rv20 (causal rolling quantile); LONG 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    # Causal trailing 252d 90th percentile of rv20 (includes current bar -- OK).
    rv_q90 = rv20.rolling(252).quantile(0.90)
    m = np.asarray((rv20 > rv_q90).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(rv_q90.to_numpy())] = False
    m[~np.isfinite(rv20.to_numpy())] = False
    return m
