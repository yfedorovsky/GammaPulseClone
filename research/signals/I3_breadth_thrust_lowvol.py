"""I3 (interaction: breadth thrust confirmed by low-vol regime). Event = the panel
breadth_50 (fraction of the 50-name universe above its own 50d SMA, pre-built on the
QQQ date spine) crosses UP through 0.50 -- breadth_50 today > 0.50 AND breadth_50 five
bars ago < 0.50 -- AND the instrument's own 20d realized vol is NOT in the high tercile
(rv20 <= causal trailing-252d 66.7pct). The interaction premise: a breadth thrust is
only a durable LONG signal when it fires from a calm tape, not a high-vol panic spike.
LONG QQQ 10d. Breadth is causal (pre-built panel); rv20/threshold are backward-rolling.
Fully no-lookahead."""
import numpy as np
import pandas as pd
from pathlib import Path

SPEC = dict(id="I3_breadth_thrust_lowvol",
            name="Breadth thrust (cross >0.50) in non-high-vol regime",
            category="ExA",
            description="breadth_50 crosses UP through 0.50 (today>0.50 AND 5 bars ago<0.50) "
                        "AND rv20 <= trailing-252d 66.7pct; LONG QQQ 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])

_PANEL = Path(__file__).resolve().parent.parent.parent / "data" / "panel_features.parquet"


def signal(H, df):
    # --- panel breadth (causal, pre-built on QQQ date spine) ---
    pf = pd.read_parquet(_PANEL)
    m = df.merge(pf[["date", "breadth_50"]], on="date", how="left")
    breadth = m["breadth_50"].to_numpy()
    b_ser = pd.Series(breadth)
    b_lag5 = b_ser.shift(5).to_numpy()                    # breadth five bars ago
    cross_up = (breadth > 0.50) & (b_lag5 < 0.50)         # crossed UP through 0.50

    # --- own 20d realized vol, NOT high tercile (causal) ---
    close = pd.Series(df["close"].to_numpy())
    r = close.pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)           # 20d realized vol, causal
    rv_hi = rv20.rolling(252).quantile(0.667)             # causal high-tercile threshold
    not_high_vol = rv20 <= rv_hi

    mask = np.asarray((cross_up & not_high_vol.to_numpy()), dtype=bool).copy()
    mask[~np.isfinite(breadth)] = False
    mask[~np.isfinite(b_lag5)] = False
    mask[~np.isfinite(rv20.to_numpy())] = False
    mask[~np.isfinite(rv_hi.to_numpy())] = False
    return mask
