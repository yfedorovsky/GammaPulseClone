"""One-time builder for 5-min OHLC cache from Databento."""
import sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databento_loader import cache_status
from server.alert_annotations import get_minute_bars

OUT = ROOT / "data" / "theta_cache"
OUT.mkdir(exist_ok=True, parents=True)

for sym in ["SPY", "QQQ"]:
    cache_path = OUT / f"{sym}_5min.parquet"
    if cache_path.exists():
        print(f"{sym}: already cached", flush=True)
        continue
    days = sorted(cache_status().query("ticker == @sym")["date"].unique())
    print(f"{sym}: building 5-min cache for {len(days)} days...", flush=True)
    chunks = []
    t0 = time.time()
    for i, d in enumerate(days):
        try:
            mb = get_minute_bars(sym, d)
        except Exception as e:
            print(f"  {sym} {d}: FAIL {e}", flush=True)
            continue
        if mb.empty:
            continue
        mb = mb.copy()
        for c in ("open", "high", "low", "close", "volume"):
            mb[c] = pd.to_numeric(mb[c], errors="coerce")
        mb["dt"] = pd.to_datetime(mb["minute"])
        b5 = mb.set_index("dt").resample(
            "5min", closed="right", label="right"
        ).agg({"open": "first", "high": "max", "low": "min",
               "close": "last", "volume": "sum"}).dropna().reset_index()
        b5["day"] = d
        b5["hhmm"] = b5["dt"].dt.strftime("%H:%M")
        b5 = b5[(b5["hhmm"] >= "09:30") & (b5["hhmm"] <= "16:00")]
        chunks.append(b5)
        if (i + 1) % 10 == 0:
            print(f"  {sym} {i+1}/{len(days)} ({time.time()-t0:.0f}s elapsed)",
                  flush=True)
    out = pd.concat(chunks, ignore_index=True).sort_values("dt").reset_index(drop=True)
    out.to_parquet(cache_path)
    print(f"{sym}: {len(out)} 5-min bars cached -> {cache_path} ({time.time()-t0:.0f}s)",
          flush=True)

print("DONE", flush=True)
