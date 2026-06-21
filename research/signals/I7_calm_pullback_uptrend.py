"""I7 (calm dip in an uptrend): an A x B INTERACTION that refines the beta-y B3
pullback with a volatility filter. The premise is that not all dips below the
20SMA inside a 200SMA uptrend are equal -- the ones worth buying are the *calm*
ones (orderly profit-taking), not the *anxious* ones (vol expanding as the tape
breaks). So we gate B3's structural pullback on realized vol being BELOW its own
long-run median.

Event (all causal / backward-looking) =
    close > 200SMA               (regime: long-term uptrend)
  AND close < 20SMA              (a short-term dip)
  AND rv20 < rv_med              (calm: 20d realized vol below its 252d median)
-> LONG, 5-day horizon, run across the 40-name cross-section (cross=True, generic,
no panel features). Because the uptrend gate makes this near mono-trend, it should
exercise the engine's regime-conditioned Layer-2 path."""
import numpy as np
import pandas as pd

SPEC = dict(id="I7_calm_pullback_uptrend",
            name="Calm pullback in uptrend (dip<20SMA, >200SMA, rv20<rv_med)",
            category="AxB",
            description="close>200SMA AND close<20SMA AND rv20<rv_med (calm); LONG 5d. Cross-section.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    close = df["close"].to_numpy()
    sma20 = H.sma(close, 20)
    sma200 = H.sma(close, 200)

    # Causal realized-vol terciles of the instrument's OWN 20d vol.
    r = pd.Series(close).pct_change()
    rv20 = (r.rolling(20).std() * np.sqrt(252.0))
    rv_med = rv20.rolling(252).median()          # all backward-looking, OK
    rv20_np = rv20.to_numpy()
    rv_med_np = rv_med.to_numpy()

    in_uptrend = close > sma200
    below_short = close < sma20
    calm = rv20_np < rv_med_np

    m = np.asarray((in_uptrend & below_short & calm), bool).copy()
    m[~np.isfinite(sma20)] = False
    m[~np.isfinite(sma200)] = False
    m[~np.isfinite(rv20_np)] = False
    m[~np.isfinite(rv_med_np)] = False
    return m
