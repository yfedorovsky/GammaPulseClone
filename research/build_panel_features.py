"""Pre-build causal panel-derived features on the QQQ date spine, so Layer-1
cross-asset (E) signals can read aligned columns without each re-deriving (and
risking alignment/lookahead bugs). All features use trailing-only info.

Outputs data/panel_features.parquet:
  date
  breadth_50    : fraction of the 40-name panel with close>50SMA that day
  semis_rs_20   : mean(20d return of semis basket) - QQQ 20d return
  qqq_spy_rs_20 : QQQ 20d return - SPY 20d return
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEMIS = ["NVDA", "AVGO", "AMD", "MU", "LRCX", "AMAT", "QCOM", "ARM", "MRVL", "TXN"]


def _close(t):
    p = DATA / f"daily_long_{t}.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)[["date", "close"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date")["close"].sort_index()


def main():
    qqq = pd.read_parquet(DATA / "qqq_daily.parquet")[["date", "close"]].copy()
    qqq["date"] = pd.to_datetime(qqq["date"])
    qqq = qqq.set_index("date")["close"].sort_index()
    spine = qqq.index

    # breadth: frac of panel names above their own 50SMA on each spine date
    names = sorted(p.name.replace("daily_long_", "").replace(".parquet", "")
                   for p in DATA.glob("daily_long_*.parquet"))
    above = pd.DataFrame(index=spine)
    for t in names:
        c = _close(t)
        if c is None or len(c) < 60:
            continue
        sma50 = c.rolling(50).mean()
        flag = (c > sma50).reindex(spine)          # NaN where no data that date
        above[t] = flag
    breadth = above.mean(axis=1, skipna=True)       # frac of AVAILABLE names

    def ret20(c):
        return (c / c.shift(20) - 1.0)

    qqq_r20 = ret20(qqq)
    # semis basket mean 20d return on spine
    semis_r = pd.DataFrame(index=spine)
    for t in SEMIS:
        c = _close(t)
        if c is None:
            continue
        semis_r[t] = ret20(c).reindex(spine)
    semis_rs = semis_r.mean(axis=1, skipna=True) - qqq_r20

    spy = _close("SPY")
    qqq_spy_rs = (qqq_r20 - ret20(spy).reindex(spine)) if spy is not None else pd.Series(index=spine, dtype=float)

    out = pd.DataFrame({"date": spine, "breadth_50": breadth.to_numpy(),
                        "semis_rs_20": semis_rs.to_numpy(),
                        "qqq_spy_rs_20": qqq_spy_rs.to_numpy()})
    out.to_parquet(DATA / "panel_features.parquet", index=False)
    nn = out.dropna()
    print(f"wrote {DATA/'panel_features.parquet'} rows={len(out)} "
          f"first_full={str(nn['date'].iloc[0])[:10]} "
          f"breadth[last]={out['breadth_50'].iloc[-1]:.2f} "
          f"semis_rs[last]={out['semis_rs_20'].iloc[-1]:.4f} "
          f"qqq_spy_rs[last]={out['qqq_spy_rs_20'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
