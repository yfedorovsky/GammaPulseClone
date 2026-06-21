"""E4 (cross-asset RS leadership): tech relative-strength leadership. Read the
pre-built panel feature qqq_spy_rs_20 (QQQ 20d return minus SPY 20d return). Event
= qqq_spy_rs_20 in its top causal tercile (rolling 252d 66.7th pct, backward-looking,
includes current bar). LONG 10d. Probes whether QQQ leadership over SPY persists."""
import numpy as np
import pandas as pd

SPEC = dict(id="E4_qqq_spy_rs_top", name="QQQ-SPY RS in top causal tercile",
            category="E4",
            description="qqq_spy_rs_20 >= rolling-252d 66.7th pct of itself; LONG 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    pf = pd.read_parquet('data/panel_features.parquet')
    m = df.merge(pf[['date', 'qqq_spy_rs_20']], on='date', how='left')
    rs = m['qqq_spy_rs_20']
    # causal top-tercile threshold: rolling 252d 66.7th pct (backward, incl current bar)
    thr = rs.rolling(252).quantile(0.667)
    rs_np = rs.to_numpy()
    thr_np = thr.to_numpy()
    mask = np.asarray((rs_np >= thr_np), dtype=bool).copy()
    mask[~np.isfinite(rs_np)] = False
    mask[~np.isfinite(thr_np)] = False
    return mask
