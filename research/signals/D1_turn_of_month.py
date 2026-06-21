"""D1 (calendar): turn-of-month effect. Enter at the close of the FIRST trading
day of each month (causal: known because the prior bar was a different month),
hold 4 trading days -> captures the canonical ToM strength window. LONG."""
import numpy as np

SPEC = dict(id="D1_turn_of_month", name="Turn-of-month (first trading day) long 4d",
            category="D1",
            description="bar = first trading day of its month; LONG 4d.",
            side="long", horizon=4, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    dt = pd.DatetimeIndex(df["date"])
    mon = dt.month.to_numpy()
    prev_mon = np.roll(mon, 1); prev_mon[0] = mon[0]
    first_td = (mon != prev_mon)
    first_td[0] = False
    return first_td
