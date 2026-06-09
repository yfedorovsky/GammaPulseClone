"""Gate-stage tests for the side-label-confidence axis (LABEL_CONF).

Verifies the quarantine semantics: a side-label-dependent cohort (WHALE/
INFORMED/FLOW_*) is capped at SHADOW when its labels are UNVERIFIED or
low-confidence, REJECTed when the confirmed-only subset contradicts the claimed
edge (labeling artifact), and unaffected when labels verify HIGH or the cohort
is exempt. Also covers the backtest_adapter wiring (tape_source -> Candidate).

MUST run under the autoresearch venv:
    .venv-autoresearch/Scripts/python scripts/test_label_conf_gate.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np  # noqa: E402

from autoresearch.trials_ledger import TrialLedger  # noqa: E402
from autoresearch.gate import (  # noqa: E402
    TestCard, Candidate, GateConfig, ValidationGate, SHIP, SHADOW, REJECT,
)
from autoresearch.label_confidence import (  # noqa: E402
    LabelConfidenceConfig, check_cohort_side_labels,
)
from autoresearch.side_confirmation import TapePrint  # noqa: E402
from autoresearch.backtest_adapter import build_candidate  # noqa: E402

_passed = 0
_failed = 0
NOW = 1_780_929_000.0  # 2026-06-08 14:30 UTC = 10:30 ET (inside the fake NBBO session).


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def _tmp_ledger_path() -> str:
    fd = tempfile.NamedTemporaryFile(prefix="lbl_ledger_", suffix=".json", delete=False)
    fd.close()
    p = Path(fd.name)
    p.unlink()
    return str(p)


def _card(cid) -> TestCard:
    return TestCard(
        card_id=cid, provenance="internal cohort slice",
        claim=f"{cid} cohort beats baseline net of slippage",
        expected_sign="positive",
        mechanism="informed flow precedes the move so premium expands",
        target_cohort=cid, kill_criteria="rolling lower bound < breakeven",
    )


def _prints(ask=0, bid=0, mid=0, b=0.95, a=1.05):
    out = []
    if ask:
        out.append(TapePrint(size=ask, price=a, bid=b, ask=a))
    if bid:
        out.append(TapePrint(size=bid, price=b, bid=b, ask=a))
    if mid:
        out.append(TapePrint(size=mid, price=(b + a) / 2, bid=b, ask=a))
    return out


class _StubTape:
    def __init__(self, mapping, default=None):
        self.mapping = mapping
        self.default = default if default is not None else []

    def prints(self, ticker, expiration, strike, right, date, start, end):
        return self.mapping.get(ticker, self.default)


def _clusters(n, ret=0.5, prefix="T"):
    return [{"ticker": f"{prefix}{i}", "day": "2026-06-05", "direction": "BULL",
             "option_type": "call", "strike": 100.0, "expiration": "20260620",
             "fired_at": NOW + i * 60.0, "ret": ret} for i in range(n)]


def _gate():
    led = TrialLedger(_tmp_ledger_path())
    return ValidationGate(led, GateConfig(spa_reps=200))


def _eval(cand) -> tuple:
    rep = _gate().evaluate(cand)
    lc = next(s for s in rep.stages if s.name == "LABEL_CONF")
    return rep, lc


def _base_candidate(cid, *, dependent, label_conf=None, T=64):
    rng = np.random.default_rng(7)
    ret = rng.normal(0.1, 0.2, T)
    return Candidate(card=_card(cid), returns=ret,
                     baseline_returns=rng.normal(0.0, 0.2, T),
                     side_label_dependent=dependent,
                     label_confidence=label_conf)


# ── stage semantics ─────────────────────────────────────────────────────────
def test_exempt_cohort_passes():
    rep, lc = _eval(_base_candidate("SOE-LIKE", dependent=False))
    check("exempt -> stage PASS/SHIP", lc.status == "PASS" and lc.tier == SHIP,
          f"{lc.status}/{lc.tier}")
    check("LABEL_CONF not a driver", "LABEL_CONF" not in rep.drivers, str(rep.drivers))


def test_unverified_dependent_quarantined():
    rep, lc = _eval(_base_candidate("WHALE-UNVERIFIED", dependent=True,
                                    label_conf=None))
    check("unverified -> SHADOW tier", lc.tier == SHADOW, f"{lc.status}/{lc.tier}")
    check("outcome capped at SHADOW or worse", rep.outcome in (SHADOW, REJECT),
          rep.outcome)
    check("message says unverified", "UNVERIFIED" in lc.message.upper(), lc.message)


def test_low_confidence_quarantined_distinct_from_mintrl():
    tape = _StubTape({}, default=_prints(mid=100))   # all guesses.
    lc_res = check_cohort_side_labels("WHALE", _clusters(20), tape)
    rep, lc = _eval(_base_candidate("WHALE-LOW", dependent=True, label_conf=lc_res))
    check("LOW band -> FAIL/SHADOW", lc.status == "FAIL" and lc.tier == SHADOW,
          f"{lc.status}/{lc.tier}")
    check("quarantine message names label axis", "label" in lc.message.lower(),
          lc.message)
    # Distinctness: if SHADOW is the outcome, LABEL_CONF must be among drivers
    # on its own merits (not merely riding MIN_LENGTH).
    if rep.outcome == SHADOW:
        check("LABEL_CONF is its own driver", "LABEL_CONF" in rep.drivers,
              str(rep.drivers))


def test_artifact_rejects():
    # REJECT grade: confirmed-only edge SIGN-FLIPS on >= artifact_reject_min_n
    # (30) confirmed clusters.
    mapping = {f"C{i}": _prints(ask=95, bid=5) for i in range(35)}
    mapping.update({f"A{i}": _prints(mid=100) for i in range(20)})
    tape = _StubTape(mapping)
    clusters = ([{**c, "ret": -0.1} for c in _clusters(35, prefix="C")]
                + [{**c, "ret": 1.0} for c in _clusters(20, prefix="A")])
    lc_res = check_cohort_side_labels("WHALE", clusters, tape)
    rep, lc = _eval(_base_candidate("WHALE-ARTIFACT", dependent=True,
                                    label_conf=lc_res))
    check("artifact -> FAIL/REJECT", lc.status == "FAIL" and lc.tier == REJECT,
          f"{lc.status}/{lc.tier}")
    check("gate outcome REJECT", rep.outcome == REJECT, rep.outcome)
    check("LABEL_CONF among reject drivers", "LABEL_CONF" in rep.drivers,
          str(rep.drivers))
    check("message notes the graded data span", "data thru" in lc.message,
          lc.message)


def test_suspected_artifact_shadows_not_rejects():
    # Confirmed subset negative but SMALL (12 < 30) -> SHADOW, not REJECT
    # (live-ops review: hard reject off a 10-row subset is noise).
    mapping = {f"C{i}": _prints(ask=95, bid=5) for i in range(12)}
    mapping.update({f"A{i}": _prints(mid=100) for i in range(18)})
    tape = _StubTape(mapping)
    clusters = ([{**c, "ret": -0.1} for c in _clusters(12, prefix="C")]
                + [{**c, "ret": 1.0} for c in _clusters(18, prefix="A")])
    lc_res = check_cohort_side_labels("WHALE", clusters, tape)
    check("result is SUSPECTED grade",
          lc_res.artifact_suspected and not lc_res.edge_is_artifact, lc_res.reason)
    rep, lc = _eval(_base_candidate("WHALE-SUSPECT", dependent=True,
                                    label_conf=lc_res))
    check("suspected -> FAIL/SHADOW (not REJECT)",
          lc.status == "FAIL" and lc.tier == SHADOW, f"{lc.status}/{lc.tier}")
    check("LABEL_CONF does not REJECT the gate",
          "LABEL_CONF" not in (rep.drivers if rep.outcome == REJECT else []),
          f"{rep.outcome} {rep.drivers}")


def test_high_confidence_does_not_cap():
    tape = _StubTape({}, default=_prints(ask=95, bid=5))
    lc_res = check_cohort_side_labels("WHALE", _clusters(20), tape)
    _, lc = _eval(_base_candidate("WHALE-HIGH", dependent=True, label_conf=lc_res))
    check("HIGH band -> PASS/SHIP", lc.status == "PASS" and lc.tier == SHIP,
          f"{lc.status}/{lc.tier}")


# ── adapter wiring ──────────────────────────────────────────────────────────
_DB_COLS = ("fired_at", "alert_type", "ticker", "direction", "score",
            "strike", "expiration", "option_type", "spot_at_alert",
            "outcome_resolution_spot", "verdict_eod", "outcome_status")


def _make_db(rows) -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="lbl_adapter_")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE alert_outcomes ({', '.join(_DB_COLS)})")
    con.executemany(
        f"INSERT INTO alert_outcomes ({', '.join(_DB_COLS)}) "
        f"VALUES ({', '.join('?' * len(_DB_COLS))})", rows)
    con.commit()
    con.close()
    return path


def _alert_row(i, alert_type="FLOW_MEDIUM", ticker=None):
    return (NOW + i * 86400.0, alert_type, ticker or f"T{i}", "BULL", 5.0,
            100.0, "20270115", "call", 100.0, 101.0, "WIN", "resolved")


class _FakeNBBO:
    def bars(self, ticker, expiration, strike, right, date):
        from autoresearch.option_pnl import Bar
        return [Bar(hhmm=f"{9 + h:02d}:{m:02d}", bid=1.0, ask=1.1)
                for h in range(1, 7) for m in (0, 30)]


def test_adapter_attaches_label_confidence():
    rows = [_alert_row(i) for i in range(15)] + \
           [_alert_row(i, alert_type="SOE_A", ticker=f"B{i}") for i in range(10)]
    db = _make_db(rows)
    try:
        tape = _StubTape({}, default=_prints(ask=95, bid=5))
        cand, diag = build_candidate(
            _card("FLOW-WIRED"), "FLOW_MEDIUM", db_path=db,
            baseline_alert_type="SOE_A", source=_FakeNBBO(),
            tape_source=tape,
            label_config=LabelConfidenceConfig(min_checked=5))
        check("flow cohort flagged dependent", cand.side_label_dependent,
              str(diag.get("side_label_dependent")))
        check("label confidence attached", cand.label_confidence is not None)
        check("diag carries band", (diag.get("label_confidence") or {}).get("band")
              in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"), str(diag.get("label_confidence")))

        cand2, diag2 = build_candidate(
            _card("SOE-WIRED"), "SOE_A", db_path=db,
            baseline_alert_type="FLOW_MEDIUM", source=_FakeNBBO(),
            tape_source=tape)
        check("SOE cohort exempt", not cand2.side_label_dependent)
        check("no label check for exempt", cand2.label_confidence is None)

        cand3, _ = build_candidate(
            _card("FLOW-NO-TAPE"), "FLOW_MEDIUM", db_path=db,
            baseline_alert_type="SOE_A", source=_FakeNBBO())
        check("dependent w/o tape source -> unverified (None)",
              cand3.side_label_dependent and cand3.label_confidence is None)
    finally:
        os.unlink(db)


def main() -> int:
    print("=== label-confidence gate tests ===")
    for fn in (test_exempt_cohort_passes, test_unverified_dependent_quarantined,
               test_low_confidence_quarantined_distinct_from_mintrl,
               test_artifact_rejects, test_suspected_artifact_shadows_not_rejects,
               test_high_confidence_does_not_cap,
               test_adapter_attaches_label_confidence):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*46}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
