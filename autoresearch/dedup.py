"""Hypothesis-card novelty / de-duplication (Phase-2 precondition).

Replaces the gate's token-Jaccard placeholder (which misses paraphrases and is
blind to structure) with an AlphaAgent-style novelty check adapted to our
TestCards (which are natural-language, not factor expressions):

  - LEXICAL similarity of the claim, robust to wording: max of
      * token Jaccard (content words, stopwords dropped), and
      * character tri-gram (shingle) Jaccard — catches reordering / typos /
        paraphrase that pure token overlap misses.
  - STRUCTURAL duplication: two cards testing the SAME (target_cohort,
    expected_sign) with a similar claim+mechanism are the same experiment even if
    worded differently — caught at a lower threshold than raw lexical identity.

Pure-stdlib, deterministic, no embedding model. A card is a duplicate if EITHER a
lexical threshold OR the structural rule fires. Used by the gate's Stage 0 (cheap
rejection, never records a trial) and available to a future internal miner so it
doesn't re-propose what's already been tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

# Small, domain-light stopword set — enough to stop function words dominating the
# token overlap without scrubbing the actual hypothesis content.
_STOPWORDS = frozenset("""
a an the of to in on for and or but with without is are be been being this that
these those it its as at by from into over under than then when while which who
whom whose we i you they he she them our your their has have had do does did will
would should could may might can card claim signal when whether if more less
""".split())

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    """Content tokens: lowercase alphanumerics, stopwords + <=2-char dropped."""
    return {w for w in _WORD_RE.findall((text or "").lower())
            if len(w) > 2 and w not in _STOPWORDS}


def char_ngrams(text: str, n: int = 3) -> set[str]:
    """Character n-gram (shingle) set over whitespace-collapsed lowercase text."""
    s = re.sub(r"\s+", " ", (text or "").lower().strip())
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def claim_similarity(a: str, b: str) -> tuple[float, float]:
    """Return (token_jaccard, char_trigram_jaccard) between two claim strings."""
    return jaccard(tokens(a), tokens(b)), jaccard(char_ngrams(a), char_ngrams(b))


@dataclass
class _CardView:
    """Minimal view over anything dedup compares (a TestCard or a bare claim)."""
    claim: str
    target_cohort: Optional[str] = None
    expected_sign: Optional[str] = None
    mechanism: str = ""
    card_id: Optional[str] = None


def _view(item) -> _CardView:
    if isinstance(item, str):
        return _CardView(claim=item)
    return _CardView(
        claim=getattr(item, "claim", "") or "",
        target_cohort=getattr(item, "target_cohort", None),
        expected_sign=getattr(item, "expected_sign", None),
        mechanism=getattr(item, "mechanism", "") or "",
        card_id=getattr(item, "card_id", None),
    )


def _structural_key(v: _CardView) -> Optional[tuple]:
    """(cohort, sign) identity — None when either is missing (no structural match)."""
    if not v.target_cohort or not v.expected_sign:
        return None
    return (v.target_cohort.strip().lower(), v.expected_sign.strip().lower())


@dataclass
class DupResult:
    is_dup: bool
    kind: str = ""          # "" | "lexical" | "structural"
    score: float = 0.0      # the similarity that triggered it (or the best seen)
    match_id: Optional[str] = None
    reason: str = ""


def is_duplicate(
    card,
    corpus: Sequence,
    *,
    token_max: float = 0.9,
    charngram_max: float = 0.85,
    structural_min: float = 0.6,
) -> DupResult:
    """Is ``card`` a duplicate of anything in ``corpus``?

    ``card`` / ``corpus`` items may be TestCards (preferred — enables the
    structural rule) or bare claim strings (lexical only). Returns the first /
    strongest hit. Thresholds live in GateConfig.
    """
    v = _view(card)
    v_struct = _structural_key(v)
    v_content = tokens(v.claim) | tokens(v.mechanism)

    best = DupResult(is_dup=False)
    for item in corpus:
        p = _view(item)
        tj, cj = claim_similarity(v.claim, p.claim)

        # Lexical: either signal independently is enough.
        if tj >= token_max or cj >= charngram_max:
            return DupResult(True, "lexical", max(tj, cj), p.card_id,
                             f"lexical duplicate (token={tj:.2f}, char3={cj:.2f})")

        # Structural: same cohort+sign AND similar claim+mechanism content.
        if v_struct is not None and _structural_key(p) == v_struct:
            sj = jaccard(v_content, tokens(p.claim) | tokens(p.mechanism))
            if sj >= structural_min:
                return DupResult(True, "structural", sj, p.card_id,
                                 f"same cohort+sign with similar rationale "
                                 f"(content Jaccard {sj:.2f})")

        if max(tj, cj) > best.score:
            best = DupResult(False, "", max(tj, cj), p.card_id)
    return best


__all__ = [
    "tokens", "char_ngrams", "jaccard", "claim_similarity",
    "is_duplicate", "DupResult",
]
