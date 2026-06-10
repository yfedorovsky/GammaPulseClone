"""Tests for the historical-replay stack (autoresearch/replay/*).

Deterministic: temp chain store + scripted tape/NBBO. Covers the cache schema
and upsert merge, expiration scoping, the PORTED classifier gates (live
constants), tape fire-time semantics (no look-ahead, side dominance, the
WHALE-needs-ASK and INFORMED 5-vs-6 score rules), cluster collapse, and the
known-whale fixtures (MSTR 125C 8/21 and NBIS 350C 9/18 EOD rows as recorded
from the real cache on 2026-06-09).

MUST run under the autoresearch venv:
    .venv-autoresearch/Scripts/python scripts/test_replay.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from autoresearch.replay import chain_fetcher as cf  # noqa: E402
from autoresearch.replay.signature_scan import (  # noqa: E402
    Candidate, informed_candidate, is_parity_arb_call, scan_day, whale_candidate,
)
from autoresearch.replay.replay_cohorts import (  # noqa: E402
    build_replay_clusters, find_fire,
)
from autoresearch.option_pnl import Bar  # noqa: E402
from autoresearch.side_confirmation import TapePrint  # noqa: E402

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


# ── chain store ─────────────────────────────────────────────────────────────
def _store():
    fd = tempfile.NamedTemporaryFile(suffix=".db", prefix="replay_", delete=False)
    fd.close()
    return cf.open_store(fd.name), fd.name


def _ins(con, **kw):
    row = {"date": "2026-06-08", "root": "MSTR", "expiration": "2026-08-21",
           "strike": 125.0, "right": "C", "volume": 0, "trade_count": 0,
           "close": 0.0, "bid": 0.0, "ask": 0.0, "delta": 0.0, "iv": None,
           "spot": 0.0, "oi": 0}
    row.update(kw)
    con.execute(
        "INSERT OR REPLACE INTO option_eod (date, root, expiration, strike,"
        " right, volume, trade_count, close, bid, ask, delta, iv, spot, oi)"
        " VALUES (:date,:root,:expiration,:strike,:right,:volume,:trade_count,"
        ":close,:bid,:ask,:delta,:iv,:spot,:oi)", row)
    con.commit()
    return row


# The real cached EOD rows for the two known live whales (verified 2026-06-09).
MSTR_ROW = dict(date="2026-06-08", root="MSTR", expiration="2026-08-21",
                strike=125.0, right="C", volume=51847, trade_count=105,
                close=20.1, bid=19.5, ask=20.55, delta=0.5994, iv=0.8208,
                spot=127.2, oi=644)
NBIS_ROW = dict(date="2026-06-04", root="NBIS", expiration="2026-09-18",
                strike=350.0, right="C", volume=1158, trade_count=278,
                close=36.5, bid=35.8, ask=37.15, delta=0.4314, iv=1.1239,
                spot=259.67, oi=113)


def test_store_and_scan_known_whales():
    con, path = _store()
    _ins(con, **MSTR_ROW)
    _ins(con, **NBIS_ROW)
    cands = scan_day(con, "2026-06-08", "WHALE", roots=["MSTR"])
    check("MSTR 125C 8/21 detected", len(cands) == 1
          and cands[0].strike == 125.0, str(cands))
    c = cands[0]
    check("notional = vol*close*100",
          abs(c.notional - 51847 * 20.1 * 100) < 1e-6, str(c.notional))
    check("vol/oi from morning-settled OI",
          abs(c.vol_oi - 51847 / 644) < 1e-6, str(c.vol_oi))
    check("DTE vs SCAN date (not today)", c.dte == 74, str(c.dte))
    cands2 = scan_day(con, "2026-06-04", "WHALE", roots=["NBIS"])
    check("NBIS 350C 9/18 detected", len(cands2) == 1
          and cands2[0].strike == 350.0, str(cands2))
    con.close()
    Path(path).unlink()


def test_whale_gates():
    con, path = _store()
    # Below $1M notional -> no candidate.
    _ins(con, root="AAA", volume=600, close=10.0, spot=100.0, strike=110.0, oi=100)
    # Below 500 vol.
    _ins(con, root="BBB", volume=400, close=30.0, spot=100.0, strike=110.0, oi=100)
    # vol < oi*0.30 (roll churn).
    _ins(con, root="CCC", volume=600, close=30.0, spot=100.0, strike=110.0, oi=5000)
    # Excluded ticker.
    _ins(con, root="SPY", volume=5000, close=30.0, spot=100.0, strike=110.0, oi=100)
    # Parity-arb deep ITM call at sub-intrinsic (NEE class).
    _ins(con, root="DDD", volume=5000, close=45.62, spot=85.65, strike=40.0,
         oi=100, delta=1.0)
    # Clean qualifier.
    _ins(con, root="EEE", volume=900, close=20.0, spot=100.0, strike=110.0, oi=200)
    got = {c.root for c in scan_day(con, "2026-06-08", "WHALE")}
    check("only the clean qualifier passes", got == {"EEE"}, str(got))
    con.close()
    Path(path).unlink()


def test_parity_arb_port():
    check("NEE-class sub-intrinsic call -> arb",
          is_parity_arb_call(right="C", spot=85.65, strike=40.0,
                             close=45.62, delta=1.0))
    check("positive-extrinsic call -> not arb",
          not is_parity_arb_call(right="C", spot=100.0, strike=95.0,
                                 close=7.0, delta=0.9))
    check("puts never arb", not is_parity_arb_call(
        right="P", spot=85.65, strike=120.0, close=35.0, delta=-1.0))
    check("strike proxy works without delta",
          is_parity_arb_call(right="C", spot=100.0, strike=50.0,
                             close=50.1, delta=0.0))


def test_informed_gates_and_score():
    con, path = _store()
    # 6-if-ask: V/OI 20x, vol>oi, cheap ($2 ask), 3 DTE, delta .30.
    _ins(con, root="FFF", date="2026-06-08", expiration="2026-06-11",
         volume=2000, close=2.0, bid=1.9, ask=2.0, oi=100, delta=0.30,
         spot=100.0, strike=104.0)
    # 5-if-ask: same but 30 DTE + delta .60 strips two points... build a 5:
    # V/OI + vol>oi + ASK? + cheap + delta -> 5 (not short-dated).
    _ins(con, root="GGG", date="2026-06-08", expiration="2026-07-17",
         volume=2000, close=2.0, bid=1.9, ask=2.0, oi=100, delta=0.30,
         spot=100.0, strike=104.0)
    # Hard-gate failures: V/OI < 10; liquidity; notional; expired.
    _ins(con, root="HHH", volume=500, close=2.0, ask=2.0, oi=100, delta=0.30)   # voi 5x
    _ins(con, root="III", volume=400, close=2.0, ask=2.0, oi=50, delta=0.30)    # illiquid
    _ins(con, root="JJJ", volume=600, close=0.05, ask=0.05, oi=10, delta=0.30)  # $3K notional
    _ins(con, root="KKK", date="2026-06-08", expiration="2026-06-05",
         volume=2000, close=2.0, ask=2.0, oi=100, delta=0.30)                   # DTE<0
    cands = {c.root: c for c in scan_day(con, "2026-06-08", "INFORMED")}
    check("qualifiers only", set(cands) == {"FFF", "GGG"}, str(set(cands)))
    check("FFF scores 6-if-ask", cands["FFF"].score_if_ask == 6,
          str(cands["FFF"].score_if_ask))
    check("GGG scores 5-if-ask", cands["GGG"].score_if_ask == 5,
          str(cands["GGG"].score_if_ask))
    con.close()
    Path(path).unlink()


def test_scope_expirations():
    cfg = cf.FetchConfig()
    exps = ["2025-12-19",            # expired before window -> out
            "2026-03-20",            # in-window monthly -> in (near)
            "2026-06-12",            # weekly just past end -> in (near)
            "2026-09-08",            # non-monthly far weekly -> out
            "2026-09-18",            # monthly within LEAP tenor -> in
            "2027-06-17",            # holiday-shifted monthly LEAP -> in
            "2029-01-19"]            # past LEAP tenor -> out
    got = cf.scope_expirations(exps, "2026-01-02", "2026-06-09", cfg)
    check("scoping keeps near + monthly LEAPs",
          got == ["2026-03-20", "2026-06-12", "2026-09-18", "2027-06-17"],
          str(got))


def test_oi_merge_and_prune():
    con, path = _store()
    _ins(con, root="MMM", volume=100, close=1.0, oi=0)
    con.execute("UPDATE option_eod SET oi=250 WHERE root='MMM'")
    con.commit()
    row = con.execute("SELECT oi FROM option_eod WHERE root='MMM'").fetchone()
    check("oi update merges into greeks row", row["oi"] == 250)
    _ins(con, root="NNN", volume=0, close=0.0, oi=0)   # dead strike
    n = cf.prune_dead_rows(con)
    check("dead strikes pruned", n == 1, str(n))
    check("live rows survive prune", con.execute(
        "SELECT COUNT(*) c FROM option_eod").fetchone()["c"] == 1)
    con.close()
    Path(path).unlink()


# ── tape fire semantics ─────────────────────────────────────────────────────
def _p(ts, size, at="ask"):
    px = {"ask": 1.05, "bid": 0.95, "mid": 1.00}[at]
    return TapePrint(size=size, price=px, bid=0.95, ask=1.05, ts=ts)


def _whale_sig(**kw):
    base = dict(signature="WHALE", date="2026-06-08", root="MSTR",
                expiration="2026-08-21", strike=125.0, right="C",
                volume=51847, oi=644, vol_oi=80.5, close=20.1, bid=19.5,
                ask=20.55, delta=0.6, iv=0.82, spot=127.2,
                notional=104e6, dte=74)
    base.update(kw)
    return Candidate(**base)


def test_find_fire_whale():
    sig = _whale_sig(oi=100)
    # Gates: cum_notional>=1M & cum_vol>=500 & cum_vol>=30. $1.05*100sh:
    # 500 contracts at ~$1.05 = $52.5K... need big sizes for $1M.
    prints = [_p("10:00:00", 4000, "ask"),     # cum $420K — not yet
              _p("10:30:00", 6000, "ask"),     # cum $1.05M, vol 10000 -> FIRE
              _p("11:00:00", 50000, "bid")]    # later selling — irrelevant
    f = find_fire(sig, prints)
    check("whale fires at gate crossing", f is not None and f.hhmm == "10:30",
          str(f))
    check("side from prints <= fire only (no look-ahead)",
          f.side == "ASK" and f.ask_frac == 1.0, str(f))
    # Bid-dominant tape: gates cross but side never ASK -> no fire.
    prints2 = [_p("10:00:00", 4000, "bid"), _p("10:30:00", 9000, "bid")]
    check("whale never fires on bid tape", find_fire(sig, prints2) is None)
    # MSTR-like: early ask trickle, then the giant bid block -> the trickle
    # never crosses $1M, the block flips side to BID -> NO whale fire.
    prints3 = [_p("10:00:00", 800, "ask"), _p("14:00:00", 51000, "bid")]
    check("MSTR-class bid block never fires whale",
          find_fire(sig, prints3) is None)


def test_find_fire_informed_score_rules():
    sig5 = Candidate(signature="INFORMED", date="2026-06-08", root="GGG",
                     expiration="2026-07-17", strike=104.0, right="C",
                     volume=2000, oi=100, vol_oi=20.0, close=2.0, bid=1.9,
                     ask=2.0, delta=0.30, iv=None, spot=100.0,
                     notional=400_000, dte=39, score_if_ask=5)
    # V/OI>=10 needs cum_vol >= 1000.
    ask_tape = [_p("10:00:00", 600, "ask"), _p("10:10:00", 600, "ask")]
    bid_tape = [_p("10:00:00", 600, "bid"), _p("10:10:00", 600, "bid")]
    f = find_fire(sig5, ask_tape)
    check("informed 5-if-ask fires on ask tape",
          f is not None and f.hhmm == "10:10", str(f))
    check("informed 5-if-ask does NOT fire on bid tape",
          find_fire(sig5, bid_tape) is None)
    sig6 = Candidate(**{**sig5.__dict__, "score_if_ask": 6})
    f2 = find_fire(sig6, bid_tape)
    check("informed 6-if-ask fires even on bid tape (score 5 w/o ASK)",
          f2 is not None and f2.side == "BID", str(f2))


# ── cluster build ───────────────────────────────────────────────────────────
class _Tape:
    def __init__(self, prints):
        self.p = prints

    def prints(self, *a):
        return self.p


class _NBBO:
    def bars(self, ticker, expiration, strike, right, date):
        return [Bar(hhmm=f"{10 + h:02d}:{m:02d}", bid=1.0, ask=1.1)
                for h in range(0, 6) for m in (0, 30)]


def test_build_replay_clusters():
    sigs = [_whale_sig(root="AAA", oi=100),
            _whale_sig(root="AAA", oi=100, strike=130.0),   # same root/day/dir
            _whale_sig(root="BBB", oi=100)]
    tape = _Tape([_p("10:00:00", 12000, "ask")])
    clusters, cov = build_replay_clusters(sigs, tape, _NBBO(), hold_days=0)
    check("two clusters (AAA collapsed)", len(clusters) == 2,
          str([(c['ticker'], c['n_alerts']) for c in clusters]))
    aaa = next(c for c in clusters if c["ticker"] == "AAA")
    check("collapse counts alerts", aaa["n_alerts"] == 2, str(aaa["n_alerts"]))
    check("direction BULL from ASK call", aaa["direction"] == "BULL")
    check("side_source tagged tape", aaa["side_source"] == "tape")
    check("outcome attached", isinstance(aaa["ret"], float))
    check("coverage accounting", cov["n_fired"] == 3 and cov["n_clusters"] == 2,
          str(cov))
    # Censoring: NBBO data ends on the fire day -> a 5-day hold can't be
    # covered -> unresolved, excluded.
    class _FireDayOnlyNBBO(_NBBO):
        def bars(self, ticker, expiration, strike, right, date):
            return super().bars(ticker, expiration, strike, right, date) \
                if date == "2026-06-08" else []

    clusters2, cov2 = build_replay_clusters(sigs, tape, _FireDayOnlyNBBO(),
                                            hold_days=5)
    check("censoring rule applies in replay",
          len(clusters2) == 0 and cov2["n_clusters_unresolved"] == 2, str(cov2))


def main() -> int:
    print("=== historical replay tests ===")
    for fn in (test_store_and_scan_known_whales, test_whale_gates,
               test_parity_arb_port, test_informed_gates_and_score,
               test_scope_expirations, test_oi_merge_and_prune,
               test_find_fire_whale, test_find_fire_informed_score_rules,
               test_build_replay_clusters):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
