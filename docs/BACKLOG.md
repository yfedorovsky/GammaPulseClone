# Backlog — Build Ideas Not Yet Started

Active to-do items that survived being mentioned during a session but
weren't built. Add to the top, mark `[done]` (don't delete) when shipped
so we have a record.

---

## Tape Regime Classifier

**Why**: The Apr 29 workflow rule (0DTE Engine alert → wait for Structural
Turn confirmation) is regime-dependent.
- **Range/chop day** (LOD test late morning, spot within 0.3% of LOD):
  rule works perfectly — wait for ST.
- **Trend day** (LOD made at open, spot keeps climbing): ST will never
  fire because there's no LOD retest to absorb. Following the rule means
  missing the entire move.

Currently the trader has to mentally classify the regime. We should
automate it.

**What to build**: A classifier that runs every ~15 min during cash
session and tags the day as `RANGE` / `TREND` / `MIXED`. Output goes
into the 0DTE Engine telegram banner instead of the generic "trend day
caveat" line we have now.

**Inputs** (all already available):
- Distance from open price
- Distance from session LOD (and HOD)
- Time since last LOD test (within 0.3%)
- ATR / range expansion vs prior 5 days
- Number of new highs/lows made today

**Heuristic v1**:
```
TREND if:
  - Spot > open + 0.4% AND
  - Last LOD test (within 0.3%) was > 90 min ago AND
  - Made 3+ new session highs in last hour

RANGE if:
  - Spot within 0.3% of LOD
  - Or LOD has been re-tested 2+ times in last 60 min

MIXED otherwise
```

**Telegram integration**:
- 0DTE Engine alert on RANGE day → `👁 WATCHING — wait for ST (RANGE day)`
- 0DTE Engine alert on TREND day → `⚡ TAKE IT — TREND day, ST won't fire`
- 0DTE Engine alert on MIXED day → keep current generic text

**Effort**: ~50 lines for classifier + 10 lines wiring into telegram.

**Source**: Apr 29 audit conversation — Q1 of "how would the workflow
rule have helped?" exposed this gap.

---

## Old / lower-priority ideas

(Add as they come up. Date-stamp them so we know what's stale.)
