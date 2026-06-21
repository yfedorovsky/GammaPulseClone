"""D2 (calendar): monthly OPEX week. Enter at the close of the Monday of the week
that contains the 3rd Friday of the month, hold 5 trading days (through the OPEX
Friday). Causal: the 3rd-Friday date is known in advance. LONG."""
import numpy as np

SPEC = dict(id="D2_opex_week", name="OPEX-week Monday long through Friday",
            category="D2",
            description="bar = Monday of the week containing the monthly 3rd Friday; LONG 5d.",
            side="long", horizon=5, tickers=["QQQ"], cross=True, requires=[])


def signal(H, df):
    import pandas as pd
    dt = pd.DatetimeIndex(df["date"])
    # 3rd Friday of each (year,month): the OPEX Friday.
    is_fri = dt.weekday == 4
    # rank of Fridays within each month
    s = pd.Series(np.where(is_fri, 1, 0), index=range(len(dt)))
    ym = dt.year.to_numpy() * 100 + dt.month.to_numpy()
    df2 = pd.DataFrame({"ym": ym, "is_fri": is_fri.astype(int),
                        "wd": dt.weekday.to_numpy(),
                        "day": dt.day.to_numpy()})
    df2["fri_rank"] = df2.groupby("ym")["is_fri"].cumsum() * df2["is_fri"]
    # The OPEX Monday: a Monday (wd==0) in the same calendar week as that 3rd Friday.
    # 3rd Friday always falls on day 15..21 -> its Monday is day 11..17.
    opex_mon = (df2["wd"] == 0) & (df2["day"] >= 11) & (df2["day"] <= 17)
    return opex_mon.to_numpy()
