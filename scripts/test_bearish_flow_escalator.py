"""Unit tests for server/bearish_flow_escalator.py (#122-C).

Run:  python scripts/test_bearish_flow_escalator.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from server import bearish_flow_escalator as B  # noqa: E402

_p = _f = 0


def check(name, got, want):
    global _p, _f
    if got == want:
        _p += 1; print(f"  PASS  {name}")
    else:
        _f += 1; print(f"  FAIL  {name}: got {got!r} want {want!r}")


def ev(ts, ot, side, notl, tkr="MU", spot=1200.0):
    return B.record_and_check({"ticker": tkr, "ts": ts, "option_type": ot,
                               "side": side, "notional": notl, "spot": spot})


T = 1_000_000  # base epoch

# 1. fires when 3 ASK puts out-total call-ASK above the floor
B.reset()
check("put1 no fire", ev(T + 0, "put", "ASK", 6_000_000) is None, True)
check("put2 no fire", ev(T + 10, "put", "ASK", 6_000_000) is None, True)
r = ev(T + 20, "put", "ASK", 6_000_000)  # 18M put-ASK, 0 call-ASK, 3 prints
check("put3 fires", r is not None and r["direction"] == "BEAR", True)

# 2. below floor never fires
B.reset()
ev(T, "put", "ASK", 4_000_000)
ev(T + 5, "put", "ASK", 4_000_000)
check("below floor no fire", ev(T + 10, "put", "ASK", 4_000_000) is None, True)  # 12M < 15M

# 3. call-ASK >= put-ASK never fires
B.reset()
ev(T, "put", "ASK", 6_000_000)
ev(T + 5, "put", "ASK", 6_000_000)
ev(T + 8, "put", "ASK", 6_000_000)         # 18M put-ASK
check("call dominates no fire", ev(T + 10, "call", "ASK", 30_000_000) is None, True)

# 4. BID / MID puts ignored (only ASK aggression counts)
B.reset()
ev(T, "put", "BID", 50_000_000)
ev(T + 5, "put", "MID", 50_000_000)
check("bid/mid puts ignored", ev(T + 10, "put", "ASK", 6_000_000) is None, True)  # only 6M ASK

# 5. dedup within 30 min
B.reset()
ev(T, "put", "ASK", 8_000_000); ev(T + 5, "put", "ASK", 8_000_000)
first = ev(T + 10, "put", "ASK", 8_000_000)
ev(T + 60, "put", "ASK", 8_000_000); ev(T + 65, "put", "ASK", 8_000_000)
dup = ev(T + 70, "put", "ASK", 8_000_000)
check("first fires", first is not None, True)
check("dedup suppresses within 30m", dup is None, True)

# 6. window eviction — prints older than 10 min drop out
B.reset()
ev(T, "put", "ASK", 8_000_000)
ev(T + 5, "put", "ASK", 8_000_000)
# 11 minutes later the first two are evicted; one fresh print can't reach floor/prints
check("evicted window no fire", ev(T + 660, "put", "ASK", 8_000_000) is None, True)

print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
