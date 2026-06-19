"""Track I, step 1 — pin the STABLE-LOGIC WINDOW and copy windowed snapshot
rows into the gitignored work DB.

Stable-logic window rationale (binding per docs/research/GEX_BACKTEST_PREREG.md):
  The pre-reg restricts Track I to "post the last king-selection change".
  `git log -- server/gex.py` shows the last KING-SELECTION-logic change is
  commit c0549e3 "king-selection-v3" at 2026-05-27 16:58:42 ET (KING_TIGHT_PCT
  5% / KING_WIDE_PCT 10% progressive cascade + king_far + king_is_intraday).
  Later gex.py commits do NOT change king selection in the recorded-snapshot
  path:
    - a9000d7 (2026-05-28) 0DTE synth-gamma fallback: numeric gamma fill only
      when provider gamma==0 on 0DTE; not a king-selection rule. Lands the same
      day the window opens, so it is effectively inside the stable regime.
    - e0d2dbe (2026-06-08) additive CEX / structure_regime / oi_mode param whose
      default stays "effective" (historical) — king/floor/ceiling selection
      untouched for the snapshot path.
    - 1db72a9 (2026-06-15) relaxes the 15% FLOOR fallback to run when king>spot
      too (a floor-selection edge case) + serializes no-floor as null. This is a
      genuine but narrow floor change made 1 day before this run, so it yields
      no usable post-commit data; we therefore keep 2026-05-27 as the binding
      boundary and FLAG the floor-fallback caveat for floor-setup interpretation.

  Window = snapshots with ts STRICTLY AFTER the commit instant. Because the
  commit landed after RTH close on 2026-05-27, the first full session under v3
  logic is 2026-05-28.

Copies (ticker, ts, spot, king, floor, ceiling, regime) where is_stale=0 AND
king>0 into work.db::snap_window. READ-ONLY on snapshots.db (immutable URI).
"""
import sqlite3
import datetime
import os
from zoneinfo import ZoneInfo

SRC = "file:///C:/Dev/GammaPulse/snapshots.db?mode=ro&immutable=1"
WORK = r"C:\Dev\GammaPulse\gex_backtest\work.db"
ET = ZoneInfo("America/New_York")

# c0549e3 king-selection-v3 commit instant (2026-05-27 16:58:42 ET).
BOUNDARY_TS = int(
    datetime.datetime(2026, 5, 27, 20, 58, 42, tzinfo=datetime.timezone.utc).timestamp()
)


def main() -> None:
    os.makedirs(os.path.dirname(WORK), exist_ok=True)
    src = sqlite3.connect(SRC, uri=True)
    work = sqlite3.connect(WORK)
    wc = work.cursor()
    wc.execute("DROP TABLE IF EXISTS snap_window")
    wc.execute(
        """
        CREATE TABLE snap_window (
            ticker   TEXT NOT NULL,
            ts       INTEGER NOT NULL,
            et_date  TEXT NOT NULL,   -- ET trading date (YYYY-MM-DD)
            et_hms   TEXT NOT NULL,   -- ET HH:MM:SS
            spot     REAL,
            king     REAL,
            floor    REAL,
            ceiling  REAL,
            regime   TEXT
        )
        """
    )

    sc = src.cursor()
    sc.execute(
        """
        SELECT ticker, ts, spot, king, floor, ceiling, regime
        FROM snapshots
        WHERE ts > ? AND is_stale = 0 AND king IS NOT NULL AND king > 0
        """,
        (BOUNDARY_TS,),
    )

    rows = []
    n = 0
    for ticker, ts, spot, king, floor, ceiling, regime in sc:
        dt = datetime.datetime.fromtimestamp(ts, ET)
        rows.append(
            (ticker, ts, dt.date().isoformat(), dt.strftime("%H:%M:%S"),
             spot, king, floor, ceiling, regime)
        )
        n += 1
        if len(rows) >= 50000:
            wc.executemany(
                "INSERT INTO snap_window VALUES (?,?,?,?,?,?,?,?,?)", rows
            )
            rows = []
    if rows:
        wc.executemany(
            "INSERT INTO snap_window VALUES (?,?,?,?,?,?,?,?,?)", rows
        )

    wc.execute("CREATE INDEX ix_snap_tk_ts ON snap_window(ticker, ts)")
    wc.execute("CREATE INDEX ix_snap_date ON snap_window(et_date)")
    work.commit()

    wc.execute("SELECT COUNT(*), COUNT(DISTINCT ticker), COUNT(DISTINCT et_date) FROM snap_window")
    cnt, ntk, nday = wc.fetchone()
    wc.execute("SELECT MIN(et_date), MAX(et_date) FROM snap_window")
    d0, d1 = wc.fetchone()
    print(f"copied rows       : {cnt:,}  (read {n:,})")
    print(f"distinct tickers  : {ntk}")
    print(f"distinct ET dates : {nday}  ({d0} .. {d1})")
    print(f"boundary ts       : {BOUNDARY_TS}  (c0549e3 king-selection-v3, 2026-05-27 16:58:42 ET)")
    work.close()
    src.close()


if __name__ == "__main__":
    main()
