"""I1 (AxE interaction: calm + broad continuation). Combines the instrument's own
realized-vol regime with cross-asset breadth: event fires when 20-day realized vol
sits in the bottom causal tercile of its trailing-252d history (calm) AND the
panel breadth_50 feature exceeds 0.65 (broad participation). The premise is a
healthy-uptrend continuation -- quiet tape with broad underlying participation
keeps grinding higher. Distinct from A4 (vol + 200SMA trend filter, no breadth)
and E1 (breadth alone, no vol regime); the interaction is the test. LONG 10d."""
import numpy as np
import pandas as pd

SPEC = dict(id="I1_lowvol_highbreadth_cont",
            name="Calm + broad continuation (rv20 bottom tercile AND breadth>0.65)",
            category="AxE",
            description="rv20 < trailing-252d 33.3pct AND panel breadth_50 > 0.65; LONG 10d.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])


def signal(H, df):
    close = pd.Series(df["close"].to_numpy())
    r = close.pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(252.0)          # 20d realized vol, causal
    rv_lo = rv20.rolling(252).quantile(0.333)            # causal rolling bottom tercile

    pf = pd.read_parquet('data/panel_features.parquet')
    m = df.merge(pf[['date', 'breadth_50']], on='date', how='left')
    breadth = m['breadth_50'].to_numpy()

    rv20_np = rv20.to_numpy()
    rv_lo_np = rv_lo.to_numpy()

    mask = np.asarray(((rv20_np < rv_lo_np) & (breadth > 0.65)), dtype=bool).copy()
    mask[~np.isfinite(rv20_np)] = False
    mask[~np.isfinite(rv_lo_np)] = False
    mask[~np.isfinite(breadth)] = False
    return mask
