"""TEST FIXTURE — NOT A STRATEGY. DELIBERATE LOOKAHEAD.

Fires when the underlying's OWN next-`horizon`-day return exceeds a threshold
(uses future bars on purpose). Its only job is to stress-test the Layer-2 guard
against a KNOWN POSITIVE: an oracle that buys calls exactly when the underlying is
about to rise should produce strongly positive option P&L that beats random, so a
correctly-built guard must be able to return LAYER2_PASS (not just REJECT
everything). Confirms the acceptance path + checks the mono-regime block's Type-II
behavior. NEVER use this as a research signal — it cheats by construction.
"""
import numpy as np

SPEC = dict(id="_ORACLE_lookahead_test",
            name="ORACLE lookahead (+3% fwd) — Layer-2 guard Type-II fixture",
            category="TEST",
            description="LOOKAHEAD: fires when fwd-horizon return > +3%. Known-positive guard test.",
            side="long", horizon=10, tickers=["QQQ"], cross=False, requires=[])

THRESH = 0.03  # next-horizon-day underlying return that triggers the oracle


def signal(H, df):
    close = df["close"].to_numpy()
    h = int(SPEC["horizon"])
    fwd = np.full(len(close), np.nan)
    fwd[:-h] = close[h:] / close[:-h] - 1.0    # LOOKAHEAD by construction
    return np.nan_to_num(fwd, nan=-1.0) > THRESH
