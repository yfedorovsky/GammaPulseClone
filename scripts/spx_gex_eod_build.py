"""Build a daily SPX GEX structure table from the pulled EOD greeks + OI.

The v1/v2 backtests couldn't reconstruct the scanner's two hardest gates (+gamma REGIME and
AT-SUPPORT/king) because gex_struct_eod has no index data and the OHLC pull had no gamma/OI.
This builds that missing structure for SPXW directly, per trading day, from
kind=greeks_eod (gamma, underlying_price, bid/ask) joined to kind=oi (open_interest):

  * gamma-exposure per strike = gamma * open_interest, summed across ALL expirations on the day
  * KING   = strike with the max TOTAL gamma-exposure (peak gamma concentration ~ the pin /
             support the scanner rests its limit at). Convention-free.
  * net_gex = sum(call gxoi) - sum(put gxoi); REGIME = POS if net>0 else NEG. (A convention:
             call-gamma-dominant = the pinning/stable side the scanner wants. Noted, not gospel.)
  * atm_spread_pct = the ATM call's (ask-bid)/mid  -> the spread gate input.

Writes data/spx_gex_eod.parquet: date, spot, king, dist_king_pct, net_gex, regime, atm_spread_pct.
This is the SPX analogue of gex_backtest/work.db::gex_struct_eod, built by us because Theta's
index feed is gated but the OPTION greeks (which carry the underlying) are entitled.

    python scripts/spx_gex_eod_build.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from scripts.theta_bulk_pull import scan  # noqa: E402

STORE = "C:/Dev/GammaPulse/data/theta_hist"
OUT = ROOT / "data" / "spx_gex_eod.parquet"


def build(store=STORE):
    gk = (scan(store, "greeks_eod")
          .with_columns(pl.col("timestamp").dt.date().alias("d"))
          .filter(pl.col("gamma").is_not_nan() & pl.col("gamma").is_not_null())
          .select("d", "expiration", "strike", "right", "gamma", "underlying_price", "bid", "ask"))
    oi = (scan(store, "oi")
          .with_columns(pl.col("timestamp").dt.date().alias("d"))
          .select("d", "expiration", "strike", "right", "open_interest"))
    j = (gk.join(oi, on=["d", "expiration", "strike", "right"], how="inner")
         .with_columns((pl.col("gamma") * pl.col("open_interest")).alias("gxoi"))
         .collect(engine="streaming"))
    if j.height == 0:
        raise SystemExit("no joined greeks+oi rows — pull kind=greeks_eod and kind=oi first")

    spot = j.group_by("d").agg(pl.col("underlying_price").median().alias("spot"))

    # per (day, strike): total (unsigned) and net signed gamma-exposure, summed over expirations
    strike_lvl = (j.with_columns(pl.when(pl.col("right") == "CALL")
                                 .then(pl.col("gxoi")).otherwise(-pl.col("gxoi")).alias("signed"))
                  .group_by("d", "strike")
                  .agg(pl.col("gxoi").sum().alias("total_gxoi"),
                       pl.col("signed").sum().alias("signed_gxoi")))
    king = (strike_lvl.sort(["d", "total_gxoi"], descending=[False, True])
            .group_by("d").agg(pl.col("strike").first().alias("king"),
                               pl.col("total_gxoi").first().alias("king_gamma_oi")))
    net = strike_lvl.group_by("d").agg(pl.col("signed_gxoi").sum().alias("net_gex"))

    # ATM spread: the call at the strike nearest that day's spot
    calls = (j.filter(pl.col("right") == "CALL").join(spot, on="d")
             .with_columns((pl.col("strike") - pl.col("spot")).abs().alias("dist")))
    atm = (calls.sort(["d", "dist"]).group_by("d")
           .agg(pl.col("bid").first().alias("abid"), pl.col("ask").first().alias("aask")))
    atm = atm.with_columns(pl.when((pl.col("aask") + pl.col("abid")) > 0)
                           .then((pl.col("aask") - pl.col("abid")) / ((pl.col("aask") + pl.col("abid")) / 2))
                           .otherwise(None).alias("atm_spread_pct"))

    daily = (spot.join(king, on="d").join(net, on="d").join(atm.select("d", "atm_spread_pct"), on="d")
             .with_columns(pl.when(pl.col("net_gex") > 0).then(pl.lit("POS")).otherwise(pl.lit("NEG")).alias("regime"),
                           ((pl.col("spot") - pl.col("king")).abs() / pl.col("spot") * 100).alias("dist_king_pct"))
             .sort("d")
             .select("d", "spot", "king", "king_gamma_oi", "dist_king_pct", "net_gex",
                     "regime", "atm_spread_pct"))
    return daily


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=STORE)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    daily = build(a.store)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    daily.write_parquet(out)
    print(f"wrote {out}  ({daily.height} trading days, "
          f"{daily['d'].min()} .. {daily['d'].max()})")
    reg = daily.group_by("regime").len().sort("regime")
    print("regime split:", {r["regime"]: r["len"] for r in reg.iter_rows(named=True)})
    print("median dist_king:", round(daily["dist_king_pct"].median(), 2), "%  |  median atm_spread:",
          round(daily["atm_spread_pct"].median() * 100, 2), "%")
    print(daily.head(3))
    print(daily.tail(3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
