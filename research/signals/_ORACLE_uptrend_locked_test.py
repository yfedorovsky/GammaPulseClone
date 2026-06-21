"""TEST FIXTURE — NOT A STRATEGY. DELIBERATE LOOKAHEAD + regime lock.

Like _ORACLE_lookahead_test but ALSO requires close>200SMA, forcing ~100%
trend_up. Purpose: probe the Type-II cost of the mono-regime hard PASS-block on a
KNOWN POSITIVE that is genuinely regime-specific. Expected: both CIs strongly
positive (real injected edge) yet verdict REJECT via the mono_regime pass_blocker —
quantifying exactly what the block costs, and motivating regime-conditioned controls.
NEVER use as a research signal — it cheats by construction.
"""
import numpy as np

SPEC = dict(id="_ORACLE_uptrend_locked_test",
            name="ORACLE lookahead +3% fwd, LOCKED to uptrend — mono-regime Type-II fixture",
            category="TEST",
            description="LOOKAHEAD fwd>+3% AND close>200SMA (~100% trend_up). Tests mono-regime block Type-II.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])

THRESH = 0.03


def signal(H, df):
    close = df["close"].to_numpy()
    h = int(SPEC["horizon"])
    fwd = np.full(len(close), np.nan)
    fwd[:-h] = close[h:] / close[:-h] - 1.0    # LOOKAHEAD by construction
    sma200 = H.sma(close, 200)
    m = (np.nan_to_num(fwd, nan=-1.0) > THRESH) & np.isfinite(sma200) & (close > sma200)
    return m
