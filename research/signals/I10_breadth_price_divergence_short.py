"""I10 (interaction: breadth/price divergence, bearish): price is pressing toward
its own 20-day high (close >= 0.98 * rolling-20d-high) WHILE panel breadth is narrow
(breadth_50 < 0.50, i.e. fewer than half the panel above their 50d SMA). A classic
bearish divergence -- the index makes (near-)new highs on thinning participation, so
the advance is being carried by a shrinking set of leaders. SHORT 5d. The engine
signs the forward return for a short, so lift>0 means the divergence correctly
predicted DOWN."""
import numpy as np
import pandas as pd

SPEC = dict(id="I10_breadth_price_divergence_short",
            name="Breadth/price divergence (near 20d high on narrow breadth)",
            category="ExB",
            description="close >= 0.98*rolling_high(close,20) AND breadth_50 < 0.50; "
                        "SHORT 5d. Near-high on thinning participation = bearish divergence.",
            side="short", horizon=5, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    close = df["close"].to_numpy()
    high20 = H.rolling_high(close, 20)

    pf = pd.read_parquet('data/panel_features.parquet')
    mrg = df.merge(pf[['date', 'breadth_50']], on='date', how='left')
    breadth = mrg['breadth_50'].to_numpy()

    near_high = close >= 0.98 * high20
    narrow = breadth < 0.50

    m = np.asarray((near_high & narrow), dtype=bool).copy()
    # Guard NaNs from the rolling-high warmup and the (pre-2014) breadth panel.
    m[~np.isfinite(high20)] = False
    m[~np.isfinite(breadth)] = False
    return m
