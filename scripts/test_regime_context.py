"""Unit test for server/regime_context.annotate. Run: python scripts/test_regime_context.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.regime_context import annotate  # noqa: E402

_p = _f = 0


def chk(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS  {name}")
    else:
        _f += 1
        print(f"  FAIL  {name}  {detail}")


def ctx(im, br, secs):
    return {"intermarket": {"regime": im}, "breadth": {"posture": br}, "sectors": secs}


# AAPL -> XLK in STOCK_SECTORS
a = annotate(ctx("RISK-ON", "CLEAR", {"XLK": "RISK-ON"}), "AAPL", "BULLISH")
chk("bullish into healthy tape -> ALIGNED", a["aligned"] == "ALIGNED", a["aligned"])
chk("aligned banner uses check", "✅" in a["banner"], a["banner"])
chk("sector mapped (AAPL->XLK)", a["sector_etf"] == "XLK", a["sector_etf"])

a = annotate(ctx("RISK-OFF", "DANGER", {"XLK": "MAX-DEFENSIVE"}), "AAPL", "BULLISH")
chk("bullish into hostile tape -> COUNTER", a["aligned"] == "COUNTER", a["aligned"])
chk("counter banner uses warning", "⚠️" in a["banner"], a["banner"])
chk("backdrop minimal (-3)", a["backdrop"] == -3, a["backdrop"])

a = annotate(ctx("RISK-OFF", "DANGER", {"XLK": "MAX-DEFENSIVE"}), "AAPL", "BEARISH")
chk("bearish into hostile tape -> ALIGNED (shorts want weakness)",
    a["aligned"] == "ALIGNED", a["aligned"])

a = annotate(ctx("NEUTRAL", "WATCH", {"XLK": "NEUTRAL"}), "AAPL", "BULLISH")
chk("neutral backdrop -> MIXED", a["aligned"] == "MIXED", a["aligned"])

a = annotate(ctx("RISK-ON", "CLEAR", {}), "ZZZZ", "BULLISH")
chk("unknown ticker -> no sector etf", a["sector_etf"] is None, a["sector_etf"])
chk("unknown ticker -> sector UNKNOWN", a["sector_regime"] == "UNKNOWN", a["sector_regime"])

a = annotate(ctx("RISK-ON", "CLEAR", {"XLK": "RISK-ON"}), "AAPL", "NEUTRAL")
chk("neutral sentiment -> no alignment", a["aligned"] is None, a["aligned"])

a = annotate(ctx("RISK-ON", "CLEAR", {"XLK": "RISK-ON"}), "AAPL", "BULLISH")
chk("compact stamp parseable (4 fields)", a["compact"].count("|") == 3, a["compact"])

a = annotate({}, "AAPL", "BULLISH")
chk("missing panels -> UNKNOWN, no crash", a["im"] == "UNKNOWN" and a["breadth"] == "UNKNOWN", a)

print(f"\n{'='*44}\n  {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
