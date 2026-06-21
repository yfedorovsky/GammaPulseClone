"""E2 (cross-asset breadth): washout bounce. When the panel breadth (fraction of
the 50-name universe above its own 50d SMA) collapses below 0.25 -> deep breadth
washout -> LONG QQQ 10d, betting on mean-reversion off the oversold extreme.
Reads the PRE-BUILT panel_features.parquet (already on the QQQ date spine, 1:1
aligned) so breadth is causal/backward-looking. Fully no-lookahead."""
import numpy as np
import pandas as pd
from pathlib import Path

SPEC = dict(id="E2_breadth_washout_bounce",
            name="Breadth washout bounce (breadth_50 < 0.25)",
            category="E2",
            description="panel breadth_50 < 0.25 (deep breadth washout) -> LONG QQQ 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])

_PANEL = Path(__file__).resolve().parent.parent.parent / "data" / "panel_features.parquet"


def signal(H, df):
    pf = pd.read_parquet(_PANEL)
    m = df.merge(pf[["date", "breadth_50"]], on="date", how="left")
    breadth = m["breadth_50"].to_numpy()
    mask = np.asarray((breadth < 0.25), dtype=bool).copy()
    mask[~np.isfinite(breadth)] = False
    return mask
