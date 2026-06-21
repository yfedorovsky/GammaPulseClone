"""I9 (double risk-off leadership, interaction): both the semis basket AND tech
are lagging the broad tape simultaneously. Reads two pre-built panel features:
``semis_rs_20`` (semis-basket 20d return minus QQQ 20d return) and
``qqq_spy_rs_20`` (QQQ 20d return minus SPY 20d return). Event = semis_rs_20 < 0
AND qqq_spy_rs_20 < 0 -- semis are not leading QQQ, AND QQQ is not leading SPY,
i.e. risk-off leadership at two levels at once. Bearish -> SHORT 5d. The engine
signs the forward return, so lift>0 means the signal correctly predicted DOWN.
Both inputs are backward-looking; merged 1:1 on the QQQ date spine from
data/panel_features.parquet (NaN before ~2014, guarded with isfinite)."""
import numpy as np
import pandas as pd

SPEC = dict(id="I9_double_rs_lag_short",
            name="Double RS lag (semis_rs_20<0 AND qqq_spy_rs_20<0) short",
            category="E",
            description="semis_rs_20<0 AND qqq_spy_rs_20<0 (both semis and tech "
                        "lagging the broad tape); SHORT 5d. Double risk-off "
                        "leadership interaction.",
            side="short", horizon=5, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    pf = pd.read_parquet("data/panel_features.parquet")
    m = df.merge(pf[["date", "semis_rs_20", "qqq_spy_rs_20"]], on="date", how="left")
    semis_rs = m["semis_rs_20"].to_numpy()
    tech_rs = m["qqq_spy_rs_20"].to_numpy()

    mask = np.asarray(((semis_rs < 0) & (tech_rs < 0)), dtype=bool).copy()
    mask[~np.isfinite(semis_rs)] = False
    mask[~np.isfinite(tech_rs)] = False
    return mask
