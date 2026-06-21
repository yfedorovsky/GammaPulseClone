"""I8 (A x E interaction breakdown): vol expanding AND participation breaking ->
SHORT QQQ 5d. Event fires when the instrument's own 20d realized vol today is more
than 1.3x its level twenty bars ago (rv20 expanding) AND the panel breadth_50
(fraction of the 50-name universe above its own 50d SMA) is below 0.40 (breadth
deteriorating). Rising vol with collapsing participation = a distribution/breakdown
regime -> bearish. Breadth read from the PRE-BUILT panel_features.parquet (causal,
1:1 on the QQQ date spine). Fully no-lookahead: rv20 and its 20-bar lag are
backward-only, breadth is pre-built/aligned."""
import numpy as np
import pandas as pd
from pathlib import Path

SPEC = dict(id="I8_vol_expansion_breadth_break_short",
            name="Vol expansion + breadth break (rv20 up >1.3x vs 20d ago & breadth_50<0.40)",
            category="AxE",
            description="rv20 today > 1.3 * rv20 twenty bars ago (vol expanding) AND "
                        "panel breadth_50 < 0.40 (participation breaking) -> SHORT QQQ 5d.",
            side="short", horizon=5, tickers=["QQQ"], cross=False, requires=[])

_PANEL = Path(__file__).resolve().parent.parent.parent / "data" / "panel_features.parquet"


def signal(H, df):
    close = df["close"].to_numpy()
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    rv20_lag20 = rv20.shift(20)  # rv20 twenty bars ago (backward-only)

    vol_expanding = rv20 > 1.3 * rv20_lag20

    pf = pd.read_parquet(_PANEL)
    m = df.merge(pf[["date", "breadth_50"]], on="date", how="left")
    breadth = m["breadth_50"].to_numpy()

    rv20_a = rv20.to_numpy()
    rv20_lag_a = rv20_lag20.to_numpy()

    mask = np.asarray((vol_expanding & (breadth < 0.40)).to_numpy(), dtype=bool).copy()
    mask[~np.isfinite(rv20_a)] = False
    mask[~np.isfinite(rv20_lag_a)] = False
    mask[~np.isfinite(breadth)] = False
    return mask
