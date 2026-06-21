"""E1 (cross-asset breadth): broad-participation continuation. Read the pre-built
panel feature breadth_50 (fraction of the 40-name panel trading above its 50d SMA,
already aligned 1:1 to the QQQ date spine). Event = breadth_50 > 0.70 (broad
participation). LONG 10d. Probes whether broad breadth begets continuation rather
than mean-reverting froth."""
import numpy as np
import pandas as pd

SPEC = dict(id="E1_breadth_high", name="Breadth high (>70% above 50d SMA)",
            category="E1",
            description="panel breadth_50 > 0.70 (broad participation); LONG 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    pf = pd.read_parquet('data/panel_features.parquet')
    m = df.merge(pf[['date', 'breadth_50']], on='date', how='left')
    breadth = m['breadth_50'].to_numpy()
    mask = np.asarray((breadth > 0.70), dtype=bool).copy()
    mask[~np.isfinite(breadth)] = False
    return mask
