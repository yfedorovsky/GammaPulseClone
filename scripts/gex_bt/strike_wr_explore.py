"""Exploratory: 'strikes with highest WR' done HONESTLY.

Puts naive win-rate side-by-side with net-of-spread expectancy (R) and the
underlying's beta, bucketed by |delta| (moneyness) x DTE, on a fixed 1-week
(5 trading-day) buy-and-hold. The point: show that high WR != profit, and that
the 'winning' buckets are riding the 2026 up-market (beta), not an edge.

Buy at ASK, sell at BID 5 trading days later (real spread cost). EOD chains.db.
Run with the autoresearch venv (has polars): .venv-autoresearch python.
"""
import sqlite3
import time
import polars as pl

# SQLite has bid/ask/iv (the trimmed parquet dropped them); read filtered.
DB = "data/chains_ytd_2026.db"
N = 5  # trading-day forward hold (~1 week)

t0 = time.time()
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = ("SELECT date,root,expiration,strike,right,close,bid,ask,delta,spot,oi "
     "FROM option_eod WHERE ask>0.10 AND bid>0 AND oi>=50 AND spot>0 "
     "AND delta IS NOT NULL")
lf = pl.read_database(q, con)
con.close()
print(f"loaded {lf.height:,} tradeable rows in {time.time()-t0:.1f}s")
lf = lf.with_columns([
    pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("d"),
    pl.col("expiration").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("exp"),
])
grp = ["root", "expiration", "strike", "right"]
lf = lf.sort(grp + ["d"]).with_columns([
    pl.col("bid").shift(-N).over(grp).alias("fwd_bid"),
    pl.col("close").shift(-N).over(grp).alias("fwd_close"),
    pl.col("spot").shift(-N).over(grp).alias("fwd_spot5"),
    pl.col("d").shift(-N).over(grp).alias("fwd_d"),
    pl.col("bid").last().over(grp).alias("term_bid"),
    pl.col("close").last().over(grp).alias("term_close"),
    pl.col("spot").last().over(grp).alias("term_spot"),
    pl.col("d").last().over(grp).alias("term_d"),
])
lf = lf.with_columns([
    (pl.col("exp") - pl.col("d")).dt.total_days().alias("dte"),
    pl.col("delta").abs().alias("adelta"),
    # contract ran to ~expiry (truly expired) vs got cut off by the dataset end
    (pl.col("term_d") >= pl.col("exp").dt.offset_by("-3d")).alias("expired"),
])
# SURVIVORSHIP FIX: exit at +5td if the option is still alive; else, if it
# actually expired, exit at its TERMINAL (expiry) value — so worthless OTM is
# booked as the ~-100% it was instead of silently dropped; else (dataset
# boundary, outcome unknowable) drop.
lf = lf.with_columns([
    pl.coalesce([pl.col("fwd_bid"), pl.when(pl.col("expired")).then(pl.col("term_bid"))]).alias("exit_bid"),
    pl.coalesce([pl.col("fwd_close"), pl.when(pl.col("expired")).then(pl.col("term_close"))]).alias("exit_close"),
    pl.coalesce([pl.col("fwd_spot5"), pl.when(pl.col("expired")).then(pl.col("term_spot"))]).alias("fwd_spot"),
    pl.coalesce([pl.col("fwd_d"), pl.when(pl.col("expired")).then(pl.col("term_d"))]).alias("exit_d"),
    (pl.col("fwd_bid").is_null() & pl.col("expired")).alias("held_to_expiry"),
])
lf = lf.filter(
    pl.col("exit_bid").is_not_null() & (pl.col("dte") >= 0)
    & (pl.col("exit_d") > pl.col("d"))  # exit strictly after entry
)
lf = lf.with_columns([
    ((pl.col("exit_bid") - pl.col("ask")) / pl.col("ask")).alias("net_R"),
    (pl.col("exit_bid") > pl.col("ask")).alias("win_net"),
    (pl.col("exit_close") > pl.col("close")).alias("win_naive"),
    ((pl.col("fwd_spot") - pl.col("spot")) / pl.col("spot")).alias("stock_ret"),
])
lf = lf.with_columns([
    pl.when(pl.col("adelta") >= 0.80).then(pl.lit("1.deepITM"))
      .when(pl.col("adelta") >= 0.60).then(pl.lit("2.ITM"))
      .when(pl.col("adelta") >= 0.40).then(pl.lit("3.ATM"))
      .when(pl.col("adelta") >= 0.20).then(pl.lit("4.OTM"))
      .when(pl.col("adelta") >= 0.05).then(pl.lit("5.farOTM"))
      .otherwise(pl.lit("6.lotto")).alias("mbucket"),
    pl.when(pl.col("dte") <= 7).then(pl.lit("0-7"))
      .when(pl.col("dte") <= 30).then(pl.lit("8-30"))
      .when(pl.col("dte") <= 90).then(pl.lit("31-90"))
      .otherwise(pl.lit("91+")).alias("dbucket"),
])

res = lf.group_by(["right", "mbucket", "dbucket"]).agg([
    pl.len().alias("n"),
    (pl.col("win_naive").mean() * 100).round(1).alias("WR_naive%"),
    (pl.col("win_net").mean() * 100).round(1).alias("WR_net%"),
    (pl.col("net_R").mean() * 100).round(1).alias("meanR%"),
    (pl.col("net_R").median() * 100).round(1).alias("medR%"),
    (pl.col("stock_ret").mean() * 100).round(2).alias("stk%"),
]).sort(["right", "mbucket", "dbucket"])

ov = lf.group_by("right").agg([
    pl.len().alias("n"),
    (pl.col("win_naive").mean() * 100).round(1).alias("WR_naive%"),
    (pl.col("win_net").mean() * 100).round(1).alias("WR_net%"),
    (pl.col("net_R").mean() * 100).round(1).alias("meanR%"),
    (pl.col("net_R").median() * 100).round(1).alias("medR%"),
]).sort("right")

with pl.Config(tbl_rows=60, tbl_cols=12, tbl_width_chars=160):
    print("=== buy@ask / sell@bid +5 trading days, by |delta| x DTE ===")
    print(res)
    print("\n=== overall option-buying (net of spread) ===")
    print(ov)
# best by net expectancy (the honest 'best strike')
best = res.filter(pl.col("n") >= 500).sort("meanR%", descending=True).head(8)
with pl.Config(tbl_rows=10, tbl_width_chars=160):
    print("\n=== top 8 buckets by net-of-spread expectancy (n>=500) ===")
    print(best)
print(f"\nrows scanned/joined, elapsed {time.time()-t0:.2f}s")
