"""B2 (momentum/mean-rev at extremes): close within 3% of its trailing 252d low
AND today is an up day (reclaim attempt) -> LONG 5d. The deliberate opposite of
the already-tested 52wk-HIGH continuation; this probes capitulation reversal."""
import numpy as np

SPEC = dict(id="B2_52wk_low_reclaim", name="Within 3% of 52wk low + up-day reclaim",
            category="B3",
            description="close <= 1.03*rolling-252d-low AND close>prev_close; LONG 5d.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    close = df["close"].to_numpy()
    low252 = H.rolling_low(close, 252)
    up_day = pd.Series(close).pct_change().to_numpy() > 0
    near_low = close <= 1.03 * low252
    m = near_low & up_day & np.isfinite(low252)
    return m
