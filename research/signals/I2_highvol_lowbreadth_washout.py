"""I2 (AxE interaction -- capitulation washout): the broad-market washout cell where
BOTH stress dimensions fire together -- high realized vol AND collapsing breadth.

Event = rv20 in the TOP vol tercile (rv20 > rv_hi, the causal trailing-252d 0.667
quantile of the instrument's own 20d realized vol) AND panel breadth_50 < 0.35
(fewer than 35% of the 50-name universe above its 50d SMA). LONG QQQ 10d.

This is the INTERACTION of A6 (vol alone) and E2 (breadth alone): neither stress
signal alone, but their co-occurrence -- a genuine broad capitulation. breadth_50 is
read from the PRE-BUILT panel_features.parquet (already on the QQQ date spine, 1:1
aligned, fully causal). rv20 + its terciles are trailing/backward-looking. No
lookahead anywhere; panel breadth is NaN before ~2014 (guarded -> dropped)."""
import numpy as np
import pandas as pd
from pathlib import Path

SPEC = dict(id="I2_highvol_lowbreadth_washout",
            name="High-vol + low-breadth capitulation washout (AxE)",
            category="AxE",
            description=("rv20 > top-tercile (causal 252d 0.667 quantile) AND "
                         "breadth_50 < 0.35 -> broad washout; LONG QQQ 10d."),
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])

_PANEL = Path(__file__).resolve().parent.parent.parent / "data" / "panel_features.parquet"


def signal(H, df):
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    # Causal trailing-252d top-tercile threshold (0.667 quantile, includes current
    # bar only -- no future bars referenced).
    rv_hi = rv20.rolling(252).quantile(0.667)

    pf = pd.read_parquet(_PANEL)
    mm = df.merge(pf[["date", "breadth_50"]], on="date", how="left")
    breadth = mm["breadth_50"].to_numpy()

    rv20_v = rv20.to_numpy()
    rv_hi_v = rv_hi.to_numpy()
    m = np.asarray((rv20_v > rv_hi_v) & (breadth < 0.35), dtype=bool).copy()
    m[~np.isfinite(rv20_v)] = False
    m[~np.isfinite(rv_hi_v)] = False
    m[~np.isfinite(breadth)] = False
    return m
