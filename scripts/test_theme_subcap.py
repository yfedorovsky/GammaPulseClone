"""Tests for the per-theme concentration sub-cap (cross-LLM audit rec #1).
Run: python scripts/test_theme_subcap.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import themes  # noqa: E402

_P = _F = 0


def check(name, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1; print(f"  PASS  {name}")
    else:
        _F += 1; print(f"  FAIL  {name}  {detail}")


def test_classify():
    check("MU -> memory", themes.classify("MU") == "memory")
    check("NVDA -> ai_compute", themes.classify("NVDA") == "ai_compute")
    check("VRT -> power_cooling", themes.classify("VRT") == "power_cooling")
    check("LITE -> photonics", themes.classify("LITE") == "photonics")
    check("SOXL -> semis_levered", themes.classify("SOXL") == "semis_levered")
    check("ZZZZ -> other", themes.classify("ZZZZ") == "other")
    check("lowercase mu -> memory", themes.classify("mu") == "memory")


def test_breakdown_subcap():
    # capital 150k, book cap 12% -> theme sub-cap = 0.5*12 = 6%.
    # memory $12k = 8% of 150k -> OVER 6% by 2pp. ai_compute $3k = 2% -> ok.
    pos = [{"ticker": "MU", "premium": 8000}, {"ticker": "WDC", "premium": 4000},
           {"ticker": "NVDA", "premium": 3000}]
    rows = themes.theme_breakdown(pos, capital=150_000, book_cap_pct=12.0)
    by = {r["theme"]: r for r in rows}
    check("memory bucket = 12000", abs(by["memory"]["premium"] - 12000) < 1e-9, str(by))
    check("memory pct = 8%", abs(by["memory"]["pct"] - 8.0) < 0.01, str(by))
    check("theme sub-cap = 6%", abs(by["memory"]["subcap_pct"] - 6.0) < 0.01, str(by))
    check("memory OVER by 2pp", by["memory"]["over"] and abs(by["memory"]["delta_pp"] - 2.0) < 0.01, str(by))
    check("ai_compute under", by["ai_compute"]["over"] is False, str(by))
    check("sorted by premium desc", rows[0]["theme"] == "memory", str(rows))


def test_catalyst_tighten():
    # memory has a catalyst (MU print) -> sub-cap halves to 3%; $12k=8% -> over by 5pp
    pos = [{"ticker": "MU", "premium": 12000}]
    rows = themes.theme_breakdown(pos, 150_000, 12.0, catalysts={"memory"})
    r = rows[0]
    check("catalyst tightens sub-cap to 3%", abs(r["subcap_pct"] - 3.0) < 0.01, str(r))
    check("catalyst flag set", r["has_catalyst"] is True, str(r))


def test_empty_positions_silent():
    check("no positions -> empty list", themes.theme_breakdown(None, 150_000, 12.0) == [])
    check("empty positions -> empty list", themes.theme_breakdown([], 150_000, 12.0) == [])


def test_exposure_parses_positions_and_render():
    tmp = tempfile.mkdtemp()
    fp = os.path.join(tmp, "lotto_exposure.json")
    os.environ["MIR_LOTTO_EXPOSURE_FILE"] = fp
    import importlib
    from server import lotto_exposure
    importlib.reload(lotto_exposure)
    import json
    Path(fp).write_text(json.dumps({
        "premium_at_risk": 15000, "capital": 150000,
        "positions": [{"ticker": "MU", "premium": 9000}, {"ticker": "AVGO", "premium": 6000}],
    }), encoding="utf-8")
    exp = lotto_exposure.get_exposure()
    check("get_exposure parsed 2 positions", exp and len(exp.get("positions") or []) == 2, str(exp))

    from server import mir_tp_window
    lines = mir_tp_window._theme_subcap_lines(exp, 150000, 12.0)
    check("render produces theme lines", any("theme" in ln.lower() or "memory" in ln.lower() for ln in lines), str(lines))
    # single-total feed (no positions) -> silent
    silent = mir_tp_window._theme_subcap_lines({"premium_at_risk": 15000, "capital": 150000, "positions": None}, 150000, 12.0)
    check("no positions -> no lines (no regression)", silent == [], str(silent))
    os.environ.pop("MIR_LOTTO_EXPOSURE_FILE", None)


if __name__ == "__main__":
    print("test_theme_subcap")
    test_classify()
    test_breakdown_subcap()
    test_catalyst_tighten()
    test_empty_positions_silent()
    test_exposure_parses_positions_and_render()
    print(f"\n{_P} passed, {_F} failed")
    sys.exit(1 if _F else 0)
