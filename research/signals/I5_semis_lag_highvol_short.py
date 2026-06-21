"""I5 (semis-lag risk-off interaction short): a two-condition risk-off INTERACTION.
Event = semis_rs_20 < 0 (the semis basket is LAGGING QQQ over 20d -- a leadership
deterioration signal) AND rv20 in the top tercile of its own causal trailing
distribution (rv20 > trailing-252d 0.667 quantile -- a high-volatility regime).
When chip leadership rolls over WHILE volatility is already elevated, expect QQQ to
keep falling -> SHORT 5d. side="short", so the engine signs the forward return:
lift>0 means QQQ fell over the next 5 days.

Fully causal: semis_rs_20 is a backward-looking 20d relative-strength feature read
1:1 off the pre-built panel on the QQQ date spine; rv20 is trailing realized vol and
rv_hi is a trailing 252d rolling quantile (includes the current bar only -- no future
bars referenced)."""
import numpy as np
import pandas as pd

SPEC = dict(id="I5_semis_lag_highvol_short",
            name="Semis lagging AND high-vol tercile (risk-off interaction) short",
            category="ExA",
            description="semis_rs_20<0 (semis lagging) AND rv20>trailing-252d 0.667 "
                        "quantile (top vol tercile); SHORT 5d. Leadership rollover in "
                        "an elevated-vol regime = breakdown continuation.",
            side="short", horizon=5, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    close = df["close"].to_numpy()

    # Causal realized-vol terciles of the instrument's own 20d vol.
    r = pd.Series(close).pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)
    rv_hi = rv20.rolling(252).quantile(0.667)  # trailing top-tercile threshold

    # Pre-built panel feature: semis 20d relative strength vs QQQ (1:1 on date spine).
    pf = pd.read_parquet("data/panel_features.parquet")
    m = df.merge(pf[["date", "semis_rs_20"]], on="date", how="left")
    semis_rs = m["semis_rs_20"].to_numpy()

    rv20_a = rv20.to_numpy()
    rv_hi_a = rv_hi.to_numpy()

    mask = np.asarray(((semis_rs < 0) & (rv20 > rv_hi).to_numpy()), bool).copy()
    # Guard NaNs from the rolling-vol warmup, the trailing quantile, and the
    # pre-2014 panel-feature NaNs (expected/fine).
    mask[~np.isfinite(semis_rs)] = False
    mask[~np.isfinite(rv20_a)] = False
    mask[~np.isfinite(rv_hi_a)] = False
    return mask
