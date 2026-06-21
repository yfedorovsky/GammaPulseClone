"""I6 (RS acceleration, not level): tech leadership AND strengthening. Read the
pre-built panel feature qqq_spy_rs_20 (QQQ 20d return minus SPY 20d return). Event =
qqq_spy_rs_20 > 0 (QQQ currently leading SPY) AND qqq_spy_rs_20 today > qqq_spy_rs_20
five bars ago (the leadership is *accelerating*, second-derivative positive). LONG 10d.
Distinct from E4, which tests the *level* (top tercile); this tests the *change*."""
import numpy as np
import pandas as pd

SPEC = dict(id="I6_qqq_spy_rs_accel", name="QQQ-SPY RS positive AND accelerating",
            category="E",
            description="qqq_spy_rs_20>0 AND qqq_spy_rs_20 > its value 5 bars ago; LONG 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    pf = pd.read_parquet('data/panel_features.parquet')
    m = df.merge(pf[['date', 'qqq_spy_rs_20']], on='date', how='left')
    rs = m['qqq_spy_rs_20']
    rs_5ago = rs.shift(5)                      # value 5 bars ago (backward only)
    rs_np = rs.to_numpy()
    rs5_np = rs_5ago.to_numpy()
    mask = np.asarray(((rs_np > 0.0) & (rs_np > rs5_np)), dtype=bool).copy()
    mask[~np.isfinite(rs_np)] = False
    mask[~np.isfinite(rs5_np)] = False
    return mask
