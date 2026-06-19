export const meta = {
  name: 'collar-pin-review',
  description: 'Adversarial review of the pre-registered JHEQX collar pin/support backtest',
  phases: [
    { title: 'Load', detail: 'load backtest JSON + pre-reg + engine; faithful digest' },
    { title: 'Challenge', detail: '5 adversarial lenses: placebo, stats, look-ahead, mechanism, effect-size' },
    { title: 'Verdict', detail: 'red-team synthesis -> display_only | context_gated | needs_more_data' },
  ],
}

const DATA = 'data/collar_bt_full.json'
const PREREG = 'docs/research/JPM_COLLAR_PREREG.md'
const ENGINE = 'scripts/gex_bt/collar_backtest.py'

const DIGEST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    n_events: { type: 'integer' },
    n_analyzable: { type: 'integer' },
    pin_hits: { type: 'integer' },
    placebo_hits: { type: 'integer' },
    pin_rate: { type: 'number' },
    placebo_rate: { type: 'number' },
    h2_held: { type: 'integer' },
    h2_rate: { type: 'number' },
    data_quality_notes: { type: 'string' },
    notable_events: { type: 'string' },
  },
  required: ['n_events', 'n_analyzable', 'pin_hits', 'placebo_hits', 'pin_rate',
    'placebo_rate', 'h2_held', 'h2_rate', 'data_quality_notes'],
}

const LENS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    verdict: { type: 'string', enum: ['supports_effect', 'refutes_effect', 'inconclusive'] },
    key_numbers: { type: 'string' },
    reasoning: { type: 'string' },
    caveats: { type: 'string' },
  },
  required: ['lens', 'verdict', 'key_numbers', 'reasoning'],
}

const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['display_only', 'context_gated', 'needs_more_data'] },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    rationale: { type: 'string' },
    what_would_change_it: { type: 'string' },
    findings_doc_written: { type: 'boolean' },
  },
  required: ['verdict', 'confidence', 'rationale', 'what_would_change_it', 'findings_doc_written'],
}

phase('Load')
const digest = await agent(
  `Load a pre-registered backtest for adversarial review. This is the JHEQX (JPMorgan
Hedged Equity Fund) quarterly SPX collar pin/support backtest, 2014-2026.

Read all three:
  - ${DATA}  (the results: per-quarter collar legs, settle, pin/placebo/H2 outcomes + a summary block)
  - ${PREREG}  (the PRE-REGISTRATION: section 4 = hypotheses H1/H2/H3, section 5 = disconfirming criteria)
  - ${ENGINE}  (the deterministic engine that produced the JSON)

Return a FAITHFUL digest: the exact counts and rates straight from the JSON summary, plus any
data-quality issues you find by inspecting the per-event rows (events with errors, leg-detection
failures / nulls, caps that look implausible vs spot, anything that would weaken the sample).
Do NOT judge the hypothesis yet — just load and summarize accurately. notable_events = a few
specific quarters worth flagging (the pin hits, any anomalies).`,
  { schema: DIGEST_SCHEMA, phase: 'Load', label: 'load-digest' })

log(`Loaded: n_analyzable=${digest?.n_analyzable} pin=${digest?.pin_hits}/${digest?.n_analyzable} placebo=${digest?.placebo_hits}`)

phase('Challenge')
const LENSES = [
  {
    key: 'placebo_adequacy',
    prompt: `Challenge the PLACEBO. The backtest's placebo is the nearest round-100 non-leg strike to
the real short-call cap. Is that a fair null, or a weak one a real effect would trivially beat?
Read ${DATA}. Write and run python to recompute the pin statistic (settle within 0.5% of strike)
against ALTERNATE nulls: (a) a deterministic non-leg strike ~5% from the real cap, (b) the
second-largest call-OI strike if present in the rows, (c) a strike exactly at the as-of spot
(ATM). Report whether the real JHEQX short-call cap still beats these stronger nulls. A real pin
must beat a FAIR placebo.`,
  },
  {
    key: 'multiple_testing',
    prompt: `Rigorous significance testing. From ${DATA}: H1 pin is ~8/45 hits vs placebo ~2/45 (use the
EXACT numbers in the JSON). Write and run python (scipy if available, else implement) to compute:
(a) Fisher exact test and a two-proportion z-test for pin-vs-placebo;
(b) Wilson and Clopper-Pearson 95% CIs for the pin rate;
(c) Holm-Bonferroni correction across the family {H1 pin, H2 support} (2 tests).
Does the pin effect survive correction at alpha=0.05? Give exact p-values and corrected thresholds.
State plainly whether this clears significance or is borderline/insignificant.`,
  },
  {
    key: 'lookahead_audit',
    prompt: `Audit for LOOK-AHEAD / leakage. Read ${ENGINE} carefully. Confirm or refute:
(a) collar legs are detected ONLY from OI as-of T-1 (asof = previous business day before expiry),
    never using the settle price;
(b) the cap and placebo use the SAME as-of spot (asof_close), no future info;
(c) leg selection (band-gating) cannot see the run-in/settle path.
Also verify the OI source is genuinely settled historical OI (SPXW bulk as-of T-1), not
snapshot-contaminated. Quote the exact lines that establish (or break) each point. Verdict
'refutes_effect' if you find leakage that would inflate the pin rate.`,
  },
  {
    key: 'mechanism_skeptic',
    prompt: `Is the 'pin' the COLLAR, or just round-number magnetism / low-realized-vol settling that would
happen at ANY salient strike regardless of JHEQX? Read ${DATA}, write and run python:
(a) Compare pin rate at the JHEQX short-call cap vs at the nearest round-100 strike (placebo already
    proxies this — quantify the gap and whether it's just the cap being closer to spot);
(b) Check whether the ~8 pin hits cluster in quarters where SPX barely moved over the run-in (compute
    each event's |settle/asof_close - 1|; if pins only happen when realized move is tiny, ANY near
    strike pins and the collar adds nothing);
(c) Check whether the cap's distance-from-spot explains pinning better than its being the collar leg.
Distinguish collar-SPECIFIC pinning from generic mechanics. This is the most important lens.`,
  },
  {
    key: 'effect_size_prereg',
    prompt: `Apply the PRE-REGISTERED disconfirming criterion verbatim. Read ${PREREG} section 5: H1 pin is
real ONLY if P(pin) >= placebo_baseline + 2 binomial SE across >=20 events AND beats placebo.
From ${DATA} (n analyzable ~45): write and run python to compute placebo_baseline, its binomial SE,
the baseline+2SE threshold, and whether the observed pin rate clears it. Report the exact numbers.
Verdict STRICTLY per the pre-reg floor — do not move the goalposts in either direction.`,
  },
]

const lensResults = await parallel(LENSES.map(L => () =>
  agent(L.prompt, { schema: LENS_SCHEMA, phase: 'Challenge', label: `lens:${L.key}` })
    .then(r => r ? { ...r, key: L.key } : null)
))
const lenses = lensResults.filter(Boolean)
const supports = lenses.filter(l => l.verdict === 'supports_effect').length
const refutes = lenses.filter(l => l.verdict === 'refutes_effect').length
log(`Lenses: ${lenses.length} returned — supports=${supports} refutes=${refutes} inconclusive=${lenses.length - supports - refutes}`)

phase('Verdict')
const lensDigest = lenses.map(l =>
  `### ${l.key} -> ${l.verdict}\nKEY: ${l.key_numbers}\nWHY: ${l.reasoning}\nCAVEATS: ${l.caveats || 'none'}`
).join('\n\n')

const verdict = await agent(
  `You are the RED-TEAM SYNTHESIZER for a pre-registered backtest. Reach a verdict on the JHEQX
collar pin/support effect.

Context — our research history (do not ignore): structure DETECTS but does NOT PREDICT; flow/GEX/
charm have all been falsified as tradeable triggers. A borderline n=45 result must clear a HIGH bar
before earning ANY algo weight. Default to skepticism.

Descriptive result: pin ${digest?.pin_hits}/${digest?.n_analyzable} (${digest?.pin_rate}) vs placebo
${digest?.placebo_hits}/${digest?.n_analyzable} (${digest?.placebo_rate}); H2 held ${digest?.h2_held}/${digest?.n_analyzable}.

The 5 adversarial lens reports:

${lensDigest}

Apply ${PREREG} section 5 disconfirming criteria. Decide ONE verdict:
  - 'display_only'   — collar shown as a context label, ZERO algo weight (the default / null result)
  - 'context_gated'  — collar earns a context FLAG only (still NOT a trigger), if the pin survives
                       fair placebo + multiple-testing + the mechanism lens
  - 'needs_more_data'— genuinely promising but underpowered; specify what sample would settle it

Write docs/research/JPM_COLLAR_BACKTEST_FINDINGS.md containing: the headline numbers, each lens
verdict, the multiple-testing-corrected significance, your final verdict, and EXACTLY what would
change it. Be specific and honest — quote the strongest refuting lens even if you lean supportive.`,
  { schema: VERDICT_SCHEMA, phase: 'Verdict', label: 'red-team-verdict' })

log(`VERDICT: ${verdict?.verdict} (confidence ${verdict?.confidence})`)
return { digest, lenses, verdict }
