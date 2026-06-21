"""D (event drift): pre-FOMC announcement drift (Lucca-Moench 2015).

Fires on bar t iff t+1 is a SCHEDULED FOMC announcement day -> enter at close[t]
(the FOMC-eve), exit at close[t+1] (the announcement day's close). LONG, 1-day.
Causal: the FOMC schedule is published ~a year ahead, so knowing tomorrow is FOMC
is NOT lookahead. Dates from research/event_calendars.py (2021-26 Fed-verified)."""
import numpy as np
import event_calendars as EC

SPEC = dict(id="D_pre_fomc_drift",
            name="Pre-FOMC drift (enter FOMC-eve close, hold to announcement close)",
            category="D1",
            description="t+1 is a scheduled FOMC announcement day -> LONG 1d (Lucca-Moench).",
            side="long", horizon=1, tickers=["SPY"], cross=True, requires=[])


def signal(H, df):
    return np.asarray(EC.next_day_is_fomc(df["date"]), bool)
