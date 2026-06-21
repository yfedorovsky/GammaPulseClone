"""A5 (vol-expansion continuation in a downtrend): when short-horizon realized
vol spikes well above its longer-horizon baseline (rv5 >= 1.5x rv20 -- an acute
vol expansion) AND price is below its 200-day SMA (established downtrend), expect
the breakdown to CONTINUE -> SHORT 5d. The downtrend filter is what distinguishes
this from A2 (which fades the same rv5/rv20 spike to the long side regardless of
trend): here the spike is treated as continuation, not capitulation/bounce."""
import numpy as np


SPEC = dict(id="A5_vol_expansion_downtrend_short",
            name="Vol-expansion continuation in a downtrend (rv5>>rv20 & close<200SMA)",
            category="A3",
            description="rv5 >= 1.5*rv20 AND close < 200SMA; SHORT 5d. Acute vol "
                        "spike below the 200-day trend filter = breakdown continuation.",
            side="short", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv5 = r.rolling(5).std() * np.sqrt(252.0)
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    sma200 = H.sma(close, 200)

    rv5_a = rv5.to_numpy()
    rv20_a = rv20.to_numpy()
    m = np.asarray(((rv5 >= 1.5 * rv20) & (close < sma200)).to_numpy(), dtype=bool).copy()
    # Guard NaNs from the rolling windows and the 200-SMA warmup.
    m[~np.isfinite(rv5_a)] = False
    m[~np.isfinite(rv20_a)] = False
    m[~np.isfinite(sma200)] = False
    return m
