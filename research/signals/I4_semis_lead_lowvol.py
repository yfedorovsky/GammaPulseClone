"""I4 (semis leadership in calm tape): INTERACTION of two signals --
semiconductors leading the tape (panel feature ``semis_rs_20`` > 0, i.e. semis
20d return minus QQQ 20d return is positive) AND below-median realized vol
(rv20 < trailing-252d median of its own 20d realized vol). LONG 10d. Distinct
from E3 (which conditions semis leadership on close>200SMA structural uptrend);
here the second leg is a *volatility-regime* condition (calm tape) rather than a
trend condition. Probes whether semis relative-strength leadership is a stronger
forward tailwind for QQQ specifically when the tape is quiet. All inputs are
backward-looking; semis_rs_20 merged 1:1 on the QQQ date spine."""
import numpy as np
import pandas as pd

SPEC = dict(id="I4_semis_lead_lowvol",
            name="Semis leadership (semis_rs_20>0) in calm tape (rv20<median)",
            category="ExA",
            description="semis_rs_20>0 AND rv20<trailing-252d median; LONG 10d. Interaction: semis leadership x low-vol regime.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)          # 20d realized vol, causal
    rv_med = rv20.rolling(252).median()                  # trailing-252d median, causal
    rv20 = rv20.to_numpy()
    rv_med = rv_med.to_numpy()

    pf = pd.read_parquet("data/panel_features.parquet")
    m = df.merge(pf[["date", "semis_rs_20"]], on="date", how="left")
    semis_rs = m["semis_rs_20"].to_numpy()

    mask = np.asarray(((semis_rs > 0) & (rv20 < rv_med)), bool).copy()
    mask[~np.isfinite(semis_rs)] = False
    mask[~np.isfinite(rv20)] = False
    mask[~np.isfinite(rv_med)] = False
    return mask
