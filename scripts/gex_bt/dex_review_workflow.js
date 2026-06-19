export const meta = {
  name: 'dex-test-review',
  description: 'Adversarial robustness review of the pre-registered DEX predictive-power test',
  phases: [
    { title: 'Load', detail: 'load DEX results + pre-reg + engine; faithful digest' },
    { title: 'Challenge', detail: '5 lenses: break-def, DEX-convention, subgroup, methodology, effect-size' },
    { title: 'Verdict', detail: 'red-team synthesis -> confirm_null | caveat_found | overturned' },
  ],
}

const RESULTS = 'data/dex_bt_results.json'
const PREREG = 'docs/research/DEX_PREREG.md'
const FINDINGS = 'docs/research/DEX_BACKTEST_FINDINGS.md'
const ENGINE = 'scripts/gex_bt/dex_backtest.py'
const DB = 'data/chains_ytd_2026.db'

const DIGEST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    n_name_days: { type: 'integer' }, n_resolved: { type: 'integer' },
    h1_corr: { type: 'number' }, h2_auc: { type: 'number' }, h2_placebo: { type: 'number' },
    h3_lift: { type: 'number' }, h3_floor: { type: 'number' }, h4_corr: { type: 'number' },
    my_verdict: { type: 'string' }, notes: { type: 'string' },
  },
  required: ['n_name_days', 'h2_auc', 'h3_lift', 'my_verdict', 'notes'],
}
const LENS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    verdict: { type: 'string', enum: ['supports_null', 'finds_caveat', 'overturns'] },
    key_numbers: { type: 'string' }, reasoning: { type: 'string' }, ran_code: { type: 'boolean' },
  },
  required: ['lens', 'verdict', 'key_numbers', 'reasoning'],
}
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['confirm_null', 'caveat_found', 'overturned'] },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    rationale: { type: 'string' }, thread_safe_claim: { type: 'string' },
    findings_doc_updated: { type: 'boolean' },
  },
  required: ['verdict', 'confidence', 'rationale', 'thread_safe_claim'],
}

phase('Load')
const digest = await agent(
  `Load a pre-registered backtest for adversarial review. It tests a Discord claim that "DEX
(delta exposure) near GEX levels tells you break vs bounce, and how fast/much." Read:
  - ${RESULTS}  (the computed stats: H1 direction, H2 break/bounce AUC, H3 incremental-over-gamma, H4 magnitude)
  - ${PREREG}   (the pre-registration — hypotheses + disconfirming criteria)
  - ${FINDINGS} (the author's verdict = redundant_with_gamma / not useful)
  - ${ENGINE}   (the deterministic engine — DEX from delta*oi, GEX from BSM gamma, 12k single-name-days)
Return a faithful digest of the actual numbers + note anything that looks off. Do NOT judge yet.`,
  { schema: DIGEST_SCHEMA, phase: 'Load', label: 'load-digest' })

log(`Loaded: H2_auc=${digest?.h2_auc} H3_lift=${digest?.h3_lift} verdict=${digest?.my_verdict}`)

phase('Challenge')
const LENSES = [
  {
    key: 'break_definition_robustness',
    prompt: `Challenge the BREAK/BOUNCE definition. The engine (${ENGINE}) calls a "break" when the
forward close clears the level by >0.5*ATR and a "bounce" when it rejects toward spot, dropping
ambiguous (n 7124 near-level -> 4838 resolved). Is that fair, or does it manufacture/hide the
result? COPY the engine to a scratch file and RE-RUN H2 (DEX break AUC) + H3 (incremental over
gamma) under alternates: BREAK_ATR in {0.25, 0.75, 1.0}; NEAR_LEVEL in {0.02, 0.05}; and a version
that keeps ALL near-level rows (no ambiguous drop, e.g. sign of forward move through level). Use a
smaller bootstrap/placebo (n=200) for speed. Report whether the trivial H2 (~0.526) and sub-floor
H3 (+0.0147) are stable across definitions, or whether ANY definition lifts H3 to >= +0.02. Set
ran_code=true.`,
  },
  {
    key: 'dex_convention',
    prompt: `Challenge the DEX DEFINITION. The engine uses net delta exposure = sum(delta*oi*100),
raw option delta (call +, put −). Maybe the member means something else. RE-RUN H1 (direction) and
H3 (incremental break/bounce over gamma) with alternate DEX constructions: (a) DOLLAR delta
(*spot); (b) dealer-short convention (negate); (c) EXCLUDE deep-ITM |delta|>0.85 (stock-replacement
noise); (d) CALL-only and PUT-only DEX separately; (e) DEX SLOPE = change in net DEX vs prior day
(the member says "near those levels…accelerated" — a CHANGE may matter more than a level). Does ANY
construction produce a real effect (H1 |corr| beating placebo, or H3 lift >= +0.02)? The DEX-slope
/ day-over-day-change variant is the most important to test. Set ran_code=true.`,
  },
  {
    key: 'subgroup_search',
    prompt: `Honestly search for WHERE DEX might work, guarding against data-mining. Maybe DEX
predicts break/bounce in a SUBGROUP even if not on average. RE-RUN H2/H3 within: (a) high-|GEX|
name-days (top tercile — strong dealer positioning); (b) call-wall tests vs put-wall tests
separately; (c) short-DTE-heavy chains; (d) high-IV vs low-IV names. For any subgroup where DEX
looks predictive, RE-RUN the within-subgroup placebo to confirm it is not just multiple-comparison
luck. Report the best honest subgroup and whether it survives its own placebo. Be explicit that
finding 1 lucky subgroup out of many is expected under the null. Set ran_code=true.`,
  },
  {
    key: 'methodology_audit',
    prompt: `Audit the engine ${ENGINE} for errors that could bias toward (or against) the null.
Verify: (1) NO look-ahead — predictors use day-t close only, outcomes strictly t+1/t+3 (check the
fwd1/fwd3 shifts and DEX_z timing); (2) the 7124->4838 ambiguous-drop is not systematically
dropping the cases where DEX WOULD predict (e.g. are dropped rows correlated with DEX?); (3) the
block-bootstrap clusters by DATE correctly and the within-date placebo truly breaks the name-link;
(4) per-name z-scoring uses full-sample mean/std (mild look-ahead in the NORMALIZER — is it
material?); (5) Holm family is honestly specified. Quote the exact lines. Verdict overturns only if
you find a bug that flips the conclusion. Set ran_code accordingly.`,
  },
  {
    key: 'effect_size_steelman',
    prompt: `STEELMAN the member. The author calls H2 (AUC 0.526, p=0.006) "trivial." Is that fair,
or is the author too dismissive of a small-but-real edge? From ${RESULTS}: is 0.526 vs placebo
0.521 a genuine 0.005 AUC effect or noise? Could a 52.6% break/bounce hit rate be tradeable at the
right R:R (compute the breakeven win-rate for plausible payout ratios on a level break vs bounce
trade)? AND counter-steelman: even if 52.6% were real, does H3 (+0.0147 < +0.02 floor) mean DEX
adds nothing a trader doesn't already get from the level itself? Give the honest two-sided read so
the thread cannot be accused of either over- or under-selling.`,
  },
]

const lensResults = await parallel(LENSES.map(L => () =>
  agent(L.prompt, { schema: LENS_SCHEMA, phase: 'Challenge', label: `lens:${L.key}` })
    .then(r => r ? { ...r, key: L.key } : null)))
const lenses = lensResults.filter(Boolean)
const overturns = lenses.filter(l => l.verdict === 'overturns').length
const caveats = lenses.filter(l => l.verdict === 'finds_caveat').length
log(`Lenses: ${lenses.length} returned — overturns=${overturns} caveats=${caveats} supports_null=${lenses.length - overturns - caveats}`)

phase('Verdict')
const lensDigest = lenses.map(l =>
  `### ${l.key} -> ${l.verdict} (ran_code=${l.ran_code})\nKEY: ${l.key_numbers}\nWHY: ${l.reasoning}`).join('\n\n')

const verdict = await agent(
  `Red-team synthesizer for the DEX predictive-power test. Reach a final verdict on whether DEX is
useful as the Discord member claimed ("DEX near GEX levels tells break/bounce + how fast/much").

Author's headline: H1 direction null (corr ~−0.03), H4 magnitude null (corr ~0.05), H2 break AUC
0.526 vs placebo 0.521 (trivial), H3 incremental-over-gamma +0.0147 < +0.02 floor. Verdict:
redundant_with_gamma / not useful (single-name daily; SPX-intraday untested).

The 5 adversarial lenses (several RE-RAN the analysis under alternate definitions):

${lensDigest}

Decide ONE verdict:
  - 'confirm_null'  — robustness checks hold; DEX is not useful as claimed (the expected result)
  - 'caveat_found'  — a specific construction/subgroup (e.g. DEX day-over-day SLOPE, or a subgroup)
                      shows a real effect worth a follow-up; state it precisely and how strong
  - 'overturned'    — a methodology bug or construction flips the conclusion; DEX IS useful

If anything material was found (esp. the DEX-SLOPE variant or a placebo-surviving subgroup), say so
honestly — do not rubber-stamp the null. Update ${FINDINGS} with a "Robustness review" section
capturing what was re-run and the outcome. Provide a single THREAD-SAFE one-sentence claim the user
can publish without being wrong in either direction.`,
  { schema: VERDICT_SCHEMA, phase: 'Verdict', label: 'red-team-verdict' })

log(`VERDICT: ${verdict?.verdict} (confidence ${verdict?.confidence})`)
return { digest, lenses, verdict }
