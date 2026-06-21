"""A2 / C-proxy (realized-vol term structure): when short-horizon realized vol
spikes well above longer-horizon vol (rv5 >= 1.5x rv20 -- 'backwardation'/acute
stress), fade the panic -> LONG 5d. A causal underlying-only proxy for the
options C-category (no IV-term history on deep data)."""
import numpy as np

SPEC = dict(id="A2_vol_term_backwardation",
            name="Realized-vol backwardation (rv5>>rv20) bounce",
            category="C1",
            description="rv5 >= 1.5*rv20; LONG 5d. Underlying-only proxy for IV-term backwardation.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv5 = r.rolling(5).std() * np.sqrt(252.0)
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    m = np.asarray((rv5 >= 1.5 * rv20).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(rv20.to_numpy())] = False
    return m
