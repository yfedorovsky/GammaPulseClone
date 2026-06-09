"""Tests for autoresearch/dedup.py (hypothesis-card novelty / de-dup).

Pure-stdlib, deterministic. Covers token + char-trigram lexical similarity, the
structural (same cohort+sign + similar rationale) rule, and the string back-compat
corpus path.

Run:  python scripts/test_dedup.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoresearch.dedup import (  # noqa: E402
    char_ngrams, claim_similarity, is_duplicate, jaccard, tokens,
)

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


@dataclass
class Card:
    claim: str
    target_cohort: str = ""
    expected_sign: str = ""
    mechanism: str = ""
    card_id: str = ""


# ── unit ───────────────────────────────────────────────────────────────────
def test_primitives():
    check("char_ngrams basic", char_ngrams("abcd", 3) == {"abc", "bcd"})
    check("tokens drop stopwords/short", tokens("the SPY gamma is on a tape") ==
          {"spy", "gamma", "tape"}, tokens("the SPY gamma is on a tape"))
    check("jaccard identical = 1", jaccard({"a", "b"}, {"a", "b"}) == 1.0)
    check("jaccard disjoint = 0", jaccard({"a"}, {"b"}) == 0.0)
    tj, cj = claim_similarity("negative gamma sells", "negative gamma sells")
    check("identical claim sim = (1,1)", tj == 1.0 and cj == 1.0)


# ── lexical ──────────────────────────────────────────────────────────────────
def test_lexical_token_duplicate():
    prior = Card(claim="negative gamma amplifies SPY downside into the close",
                 target_cohort="SPY", expected_sign="negative")
    near = Card(claim="negative gamma amplifies SPY downside into the close today",
                target_cohort="SPY", expected_sign="negative")
    d = is_duplicate(near, [prior])
    check("near-identical claim -> lexical dup", d.is_dup and d.kind == "lexical",
          f"{d.kind} {d.score:.2f}")


def test_distinct_not_duplicate():
    prior = Card(claim="negative gamma amplifies SPY downside",
                 target_cohort="SPY", expected_sign="negative")
    other = Card(claim="earnings drift lifts single names the week after a beat",
                 target_cohort="AAPL", expected_sign="positive")
    d = is_duplicate(other, [prior])
    check("genuinely distinct -> not dup", not d.is_dup, f"{d.kind} {d.score:.2f}")


# ── structural ───────────────────────────────────────────────────────────────
def test_structural_duplicate_reworded():
    """Same cohort+sign, claim REWORDED below lexical thresholds, but identical
    mechanism -> structural duplicate (the test the old token-Jaccard missed)."""
    mech = "dealers short gamma must sell futures as price drops amplifying downside"
    prior = Card(claim="SPY downside accelerates into the close",
                 target_cohort="SPY", expected_sign="negative", mechanism=mech)
    reworded = Card(claim="SPY downside grows late in the session",
                    target_cohort="SPY", expected_sign="negative", mechanism=mech)
    # confirm lexical alone would NOT catch it
    tj, cj = claim_similarity(prior.claim, reworded.claim)
    check("reworded claim escapes lexical (token<0.9, char<0.85)",
          tj < 0.9 and cj < 0.85, f"token={tj:.2f} char={cj:.2f}")
    d = is_duplicate(reworded, [prior])
    check("reworded same-cohort/sign -> STRUCTURAL dup",
          d.is_dup and d.kind == "structural", f"{d.kind} {d.score:.2f}")


def test_same_cohort_different_hypothesis_not_dup():
    prior = Card(claim="negative gamma amplifies SPY downside into the close",
                 target_cohort="SPY", expected_sign="negative",
                 mechanism="dealer short gamma hedging sells into weakness")
    different = Card(claim="overnight gap fills by lunch on calm tape",
                     target_cohort="SPY", expected_sign="negative",
                     mechanism="mean reversion after a quiet globex session")
    d = is_duplicate(different, [prior])
    check("same cohort+sign but different hypothesis -> not dup", not d.is_dup,
          f"{d.kind} {d.score:.2f}")


# ── string corpus (back-compat) ──────────────────────────────────────────────
def test_string_corpus_backcompat():
    corpus = ["negative gamma amplifies SPY downside into the close"]
    dup = Card(claim="negative gamma amplifies SPY downside into the close")
    new = Card(claim="put skew steepens before scheduled macro prints")
    check("string corpus catches exact lexical dup", is_duplicate(dup, corpus).is_dup)
    check("string corpus passes a distinct claim", not is_duplicate(new, corpus).is_dup)


def main() -> int:
    print("=== dedup tests ===")
    for fn in (test_primitives, test_lexical_token_duplicate, test_distinct_not_duplicate,
               test_structural_duplicate_reworded,
               test_same_cohort_different_hypothesis_not_dup, test_string_corpus_backcompat):
        print(f"\n{fn.__name__}:")
        fn()
    print(f"\n{'='*40}\n  {_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
