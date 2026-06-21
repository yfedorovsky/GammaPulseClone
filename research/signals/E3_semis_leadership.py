"""E3 (semis leadership): semiconductors leading the tape AND QQQ in an uptrend.
Read the pre-built panel feature ``semis_rs_20`` (semis-basket 20d return minus
QQQ 20d return). Event = semis_rs_20 > 0 (semis outperforming) AND close > 200SMA
(structural uptrend) -> LONG 10d. Probes whether semis relative-strength leadership
is a forward tailwind for QQQ. All inputs are backward-looking; merged 1:1 on the
QQQ date spine from data/panel_features.parquet."""
import numpy as np
import pandas as pd

SPEC = dict(id="E3_semis_leadership",
            name="Semis leadership (semis_rs_20>0) in uptrend",
            category="E3",
            description="semis_rs_20>0 AND close>200SMA; LONG 10d. Semis relative-strength leadership tailwind.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    close = df["close"].to_numpy()
    sma200 = H.sma(close, 200)

    pf = pd.read_parquet("data/panel_features.parquet")
    m = df.merge(pf[["date", "semis_rs_20"]], on="date", how="left")
    semis_rs = m["semis_rs_20"].to_numpy()

    mask = np.asarray(((semis_rs > 0) & np.isfinite(sma200) & (close > sma200)), bool).copy()
    mask[~np.isfinite(semis_rs)] = False
    return mask
