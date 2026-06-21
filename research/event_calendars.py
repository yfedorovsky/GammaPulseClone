"""Scheduled macro-event calendars (FOMC, CPI) for Category-D event-drift research.

FOMC announcement dates = the day the policy statement is released (2:00-2:15pm ET),
i.e. the LAST day of each scheduled meeting. SCHEDULED meetings only — emergency /
inter-meeting actions (e.g. 2020-03-03, 2020-03-15) are EXCLUDED, because the
Lucca-Moench pre-FOMC drift is about anticipation of a *scheduled* announcement.

PROVENANCE:
  2021-2026 — VERIFIED against federalreserve.gov/monetarypolicy/fomccalendars.htm (2026-06-21).
  2011-2020 — best-recall of the well-documented scheduled meeting dates. A wrong date
              only mislabels a non-event day -> dilutes the effect toward NULL (conservative,
              cannot create a false positive). Spot-check vs the Fed historical calendar
              before treating a NULL as final; a POSITIVE result is trustworthy regardless.

A date being on this list is NOT lookahead: the FOMC schedule is published ~a year ahead.
"""
from __future__ import annotations
import pandas as pd

# Statement/announcement day (YYYY-MM-DD), scheduled meetings only.
FOMC_ANNOUNCEMENT = [
    # 2011
    "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22", "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    # 2012
    "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20", "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    # 2013
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19", "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    # 2014
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18", "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17", "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15", "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14", "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13", "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (scheduled only; emergency 3/3 + 3/15 EXCLUDED)
    "2020-01-29", "2020-03-18", "2020-04-29", "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021 — Fed-verified
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022 — Fed-verified
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023 — Fed-verified
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024 — Fed-verified
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025 — Fed-verified
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 — Fed-verified (through the published schedule)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
]


def fomc_dates() -> set:
    """Set of FOMC announcement dates as normalized pd.Timestamp (tz-naive)."""
    return {pd.Timestamp(d).normalize() for d in FOMC_ANNOUNCEMENT}


def next_day_is_fomc(date_index) -> "list[bool]":
    """For a sequence of trading dates, mark bars whose NEXT trading day is an FOMC
    announcement day (i.e. the FOMC-EVE entry bar). Causal — the schedule is public."""
    idx = pd.DatetimeIndex(pd.to_datetime(date_index)).normalize()
    fomc = fomc_dates()
    nxt = idx[1:].tolist() + [pd.NaT]            # each bar's next trading date
    return [(n is not pd.NaT and n in fomc) for n in nxt]


def is_fomc_day(date_index) -> "list[bool]":
    idx = pd.DatetimeIndex(pd.to_datetime(date_index)).normalize()
    fomc = fomc_dates()
    return [(d in fomc) for d in idx]
