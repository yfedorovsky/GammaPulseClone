"""Pre-registered v0 — does the Finviz "up-5%-from-open" momentum scan continue?

HYPOTHESIS (written BEFORE results): names with a large up-day (close >= +5% vs
prior close — a chains.db-computable PROXY for the scan's intraday "up 5% from
open") continue higher over the next 1-3 days, and an ATM-call expression
captures it net of spread.

PRIOR (Jun-2026 session): it is beta/reversal until proven. Big up-days in a
bull market are mostly sector beta (our universe is AI-capex-tilted); the option
leg dies on the ~14% round-trip spread. Expect: stock leg ~0 or slightly
NEGATIVE after a cross-sectional demean (short-term reversal); option leg
negative net of spread.

PASS-BAR (what makes this real, not beta): the cross-sectionally DEMEANED
forward stock return must be > 0 with |t| > 2, AND the net-of-spread option leg
must be > 0. Anything that only works on the POOLED (un-demeaned) return is
market beta and FAILS. Single regime -> treat any positive as provisional.

LIMITATIONS (v0, stated up front):
  * chains.db has no STOCK volume -> the scan's RVOL>1 and avgvol>2M filters are
    NOT applied. v0 tests the price-momentum core only.
  * "close vs prior close" is a proxy for "up from open" (a different, harder
    signal; the true scan needs intraday opens from Tradier).
  * universe = chains.db's ~116 roots (tech/AI-tilted) -> the demean is the only
    defense against the sector-beta confound; an out-of-tech universe is the
    real fix (separate study).

Buy ATM call at ASK on signal day t, sell at BID t+1 (real spread). EOD chains.db.
Run with the autoresearch venv (polars): .venv-autoresearch python.
"""
import sqlite3
import time
import polars as pl

DB = "data/chains_ytd_2026.db"
UP = 0.05  # signal: closed >= +5% vs prior close

t0 = time.time()
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = ("SELECT date,root,expiration,strike,right,close,bid,ask,delta,spot,oi "
     "FROM option_eod WHERE spot>0")
df = pl.read_database(q, con)
con.close()
print(f"loaded {df.height:,} rows in {time.time()-t0:.1f}s")

df = df.with_columns([
    pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("d"),
    pl.col("expiration").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("exp"),
])

# ── Underlying panel: one spot per (root, day); build momentum + forward rets ──
und = (df.group_by(["root", "d"]).agg(pl.col("spot").first())
         .sort(["root", "d"]))
und = und.with_columns([
    (pl.col("spot") / pl.col("spot").shift(1).over("root") - 1).alias("ret"),
    (pl.col("spot").shift(-1).over("root") / pl.col("spot") - 1).alias("fwd1"),
    (pl.col("spot").shift(-3).over("root") / pl.col("spot") - 1).alias("fwd3"),
])
# Cross-sectional demean per day -> residual forward return (strips market beta)
und = und.with_columns([
    (pl.col("fwd1") - pl.col("fwd1").mean().over("d")).alias("fwd1_resid"),
    (pl.col("fwd3") - pl.col("fwd3").mean().over("d")).alias("fwd3_resid"),
    (pl.col("ret") >= UP).alias("signal"),
])
panel = und.filter(pl.col("ret").is_not_null() & pl.col("fwd1").is_not_null())

def _stats(frame, col):
    s = frame[col].drop_nulls()
    n = s.len()
    if n < 2:
        return (n, None, None, None)
    mean = s.mean(); med = s.median(); sd = s.std()
    t = mean / (sd / (n ** 0.5)) if sd and sd > 0 else None
    return (n, mean * 100, med * 100, t)

print("\n=== STOCK LEG — forward returns, signal (closed >=+5%) vs rest ===")
for label, sub in [("SIGNAL", panel.filter(pl.col("signal"))),
                   ("REST  ", panel.filter(~pl.col("signal")))]:
    for h, raw, res in [("1d", "fwd1", "fwd1_resid"), ("3d", "fwd3", "fwd3_resid")]:
        n, m, md, _ = _stats(sub, raw)
        rn, rm, rmd, rt = _stats(sub, res)
        print(f"  {label} {h}: n={n:5d}  pooled mean={m:+.2f}%  "
              f"DEMEANED mean={rm:+.2f}% med={rmd:+.2f}% t={rt:+.2f}" if m is not None else f"  {label} {h}: n={n}")

# ── OPTIONS LEG: ATM call bought at ASK on signal day, sold at BID t+1 ──
opt = df.filter(
    (pl.col("right") == "C") & (pl.col("ask") > 0.10) & (pl.col("bid") > 0)
    & (pl.col("oi") >= 50) & pl.col("delta").is_not_null()
)
grp = ["root", "expiration", "strike", "right"]
opt = opt.sort(grp + ["d"]).with_columns(
    pl.col("bid").shift(-1).over(grp).alias("fwd_bid"))
opt = opt.with_columns([
    (pl.col("exp") - pl.col("d")).dt.total_days().alias("dte"),
    pl.col("delta").abs().alias("adelta"),
])
# ATM-ish call, 5-45 DTE
opt = opt.filter((pl.col("adelta") >= 0.40) & (pl.col("adelta") <= 0.60)
                 & (pl.col("dte") >= 5) & (pl.col("dte") <= 45)
                 & pl.col("fwd_bid").is_not_null())
# one ATM call per (root, day): the nearest-to-0.5 delta
opt = (opt.with_columns((pl.col("adelta") - 0.50).abs().alias("atm_dist"))
          .sort(["root", "d", "atm_dist"])
          .group_by(["root", "d"]).first())
opt = opt.with_columns(((pl.col("fwd_bid") - pl.col("ask")) / pl.col("ask")).alias("opt_ret"))

# join the signal flag onto the option rows
opt = opt.join(panel.select(["root", "d", "signal", "ret"]), on=["root", "d"], how="inner")
print("\n=== OPTIONS LEG — buy ATM call @ask, sell @bid +1d (net of spread) ===")
for label, sub in [("SIGNAL", opt.filter(pl.col("signal"))),
                   ("REST  ", opt.filter(~pl.col("signal")))]:
    n, m, md, t = _stats(sub, "opt_ret")
    wr = (sub["opt_ret"] > 0).mean() * 100 if sub.height else None
    print(f"  {label}: n={n:5d}  mean={m:+.1f}%  med={md:+.1f}%  win={wr:.1f}%  t={t:+.2f}"
          if m is not None else f"  {label}: n={n}")

print(f"\nelapsed {time.time()-t0:.1f}s")
print("READ: if SIGNAL demeaned stock-t <= REST or option mean < 0 -> beta/spread, NOT edge.")
