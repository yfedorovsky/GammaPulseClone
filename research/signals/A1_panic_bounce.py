"""A1 (vol-regime): capitulation bounce. A 1-day drop of >=2x the instrument's
own trailing 20d daily vol, WHILE in a high realized-vol regime (rv20 above its
trailing 252d median) -> LONG 3d. Distinct from the dead uptrend-RSI2: this is
panic mean-reversion in stress, no trend filter. Fully causal (trailing-only)."""
import numpy as np

SPEC = dict(id="A1_panic_bounce", name="Capitulation 1d drop in high-vol regime",
            category="A1",
            description="ret_1d <= -2*sigma20 AND rv20 > trailing-252d median(rv20); LONG 3d.",
            side="long", horizon=3, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    sigma20 = r.rolling(20).std()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    rv_med = rv20.rolling(252).median()
    drop = r <= (-2.0 * sigma20)
    high_vol = rv20 > rv_med
    m = np.asarray((drop & high_vol).to_numpy(), dtype=bool).copy()
    m[~np.isfinite(rv_med.to_numpy())] = False
    return m
