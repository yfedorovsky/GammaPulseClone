"""Unit tests for server/sector_rotation_alert.py (#123).

Run:  python scripts/test_sector_rotation_alert.py
Pure-core tests with injected returns (no DB).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server import sector_rotation_alert as R  # noqa: E402
from server.industry import INDUSTRY_GROUPS  # noqa: E402

_p = _f = 0


def check(name, got, want):
    global _p, _f
    if got == want:
        _p += 1; print(f"  PASS  {name}")
    else:
        _f += 1; print(f"  FAIL  {name}: got {got!r} want {want!r}")


# Real 6/26 day-over-day returns (semis dumped, healthcare decoupled up).
SEMIS = {"MU": -6.69, "NVDA": -1.64, "AVGO": -3.67, "AMD": -2.06, "MRVL": -5.15,
         "QCOM": -7.57, "TSM": -0.61, "INTC": -3.42}
HEALTH = {"LLY": 7.13, "UNH": 2.97, "PFE": 1.10, "MRK": 1.80, "ABBV": 1.50, "MRNA": 1.20}
SPY_626 = -0.72


def scene(extra=None):
    r = {}
    r.update(SEMIS); r.update(HEALTH)
    r["SPY"] = SPY_626
    if extra:
        r.update(extra)
    return r


# 1. The 6/26 rotation fires with the right winner/loser/leader
R.reset()
ev = R.find_rotation(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
check("6/26 fires", ev is not None, True)
check("winner = Biotech/Health", ev and ev["green"], "Biotech / Health")
check("loser = Semis/Chips", ev and ev["red"], "Semis / Chips")
check("gap >= 5pts", ev and ev["gap"] >= 5.0, True)
check("leader = LLY", ev and ev.get("leader", {}).get("ticker"), "LLY")
check("LLY leads group by >3pts", ev and ev["leader"]["spread"] >= 3.0, True)

# 2. Narrow divergence (semis only mildly red, health mildly green) -> no fire
mild = {**{k: -1.0 for k in SEMIS}, **{k: 1.0 for k in HEALTH}, "SPY": 0.0}
mild["LLY"] = 1.2
ev2 = R.find_rotation(R.sector_table(mild, INDUSTRY_GROUPS), 0.0)
check("narrow gap -> no fire", ev2, None)

# 3. Market beta (sectors move WITH SPY) -> no fire (SPY-separation gate)
beta = scene({"SPY": 2.0})  # SPY +2; health mean ~+2.6 is only ~0.6 from SPY
ev3 = R.find_rotation(R.sector_table(beta, INDUSTRY_GROUPS), 2.0)
check("market-beta -> no fire (SPY sep)", ev3, None)

# 4. No broadly-green sector -> no fire
flat_health = {**SEMIS, **{k: 0.4 for k in HEALTH}, "SPY": -0.72}
ev4 = R.find_rotation(R.sector_table(flat_health, INDUSTRY_GROUPS), -0.72)
check("no green sector -> no fire", ev4, None)

# 5. Breadth gate: health mean green but driven by one name (most members red)
narrow_breadth = {**SEMIS, "LLY": 20.0, "UNH": -1.0, "PFE": -1.0, "MRK": -1.0,
                  "ABBV": -1.0, "MRNA": -1.0, "SPY": -0.72}  # mean +2.5 but 1/6 green
ev5 = R.find_rotation(R.sector_table(narrow_breadth, INDUSTRY_GROUPS), -0.72)
check("breadth gate -> no fire (1 name carrying)", ev5, None)

# 6. Leaderboard: sectors ranked by mean desc, health on top, semis last
lb = R.leaderboard(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
check("leaderboard health is #1", lb[0]["sector"], "Biotech / Health")
check("leaderboard semis is last", lb[-1]["sector"], "Semis / Chips")
check("leaderboard RS vs SPY computed", lb[0]["rs_vs_spy"] is not None, True)

# 7. dedup: same pair same day re-fires only on a materially wider gap
R.reset()
e = R.find_rotation(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
check("dedup: first is new", R._is_new(e, "2026-06-26"), True)
check("dedup: same gap suppressed", R._is_new(e, "2026-06-26"), False)
e2 = dict(e); e2["gap"] = e["gap"] + 4.0
check("dedup: wider gap re-fires", R._is_new(e2, "2026-06-26"), True)

# 8. format produces banner + leaderboard + leader (smoke)
ev_fmt = R.find_rotation(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
ev_fmt["leaderboard"] = R.leaderboard(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
txt = R.format_rotation(ev_fmt)
check("format has ROTATION banner", "SECTOR ROTATION" in txt, True)
check("format has leaderboard", "RS leaderboard" in txt, True)
check("format names LLY leader", "LLY" in txt, True)

# 9. ETF RS anchor: leaderboard attaches the cap-weighted sector-ETF return + RS
lb_etf = R.leaderboard(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626,
                       etf_ret={"XLV": 3.0, "SMH": -4.0, "XLE": 0.2})
health = next(r for r in lb_etf if r["sector"] == "Biotech / Health")
semis = next(r for r in lb_etf if r["sector"] == "Semis / Chips")
mag7 = next(r for r in lb_etf if r["sector"] == "Mag 7")
check("ETF anchor: XLV return on Health", health["etf_ret"], 3.0)
check("ETF anchor: XLV RS vs SPY", round(health["etf_rs"], 2), round(3.0 - SPY_626, 2))
check("ETF anchor: SMH return on Semis", semis["etf_ret"], -4.0)
check("ETF anchor: unmapped group (Mag 7) has no ETF", mag7["etf_ret"], None)
check("ETF anchor: basket RS unaffected", health["rs_vs_spy"] is not None, True)

# 10. format renders the ETF anchor in the leaderboard line
ev_etf = R.find_rotation(R.sector_table(scene(), INDUSTRY_GROUPS), SPY_626)
ev_etf["leaderboard"] = lb_etf
check("format shows XLV ETF anchor", "[XLV" in R.format_rotation(ev_etf), True)

print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
