export const meta = {
  name: 'dex-intraday-review',
  description: 'Adversarial review of the DEX intraday-flow + magnet (Quant Data) test',
  phases: [
    { title: 'Load', detail: 'load results + pre-reg + cache + scripts' },
    { title: 'Challenge', detail: '5 lenses: bubble-def, aggressor, placebo, subgroup, methodology' },
    { title: 'Verdict', detail: 'confirm_null | caveat | overturned' },
  ],
}

const CACHE = 'data/dex_tape_cache.csv'          // 322k per-strike-buckets, 32 days SPXW 0DTE
const DIRR = 'data/dex_directional_results.json'
const MAGR = 'data/dex_magnet_results.json'
const PRE = 'docs/research/DEX_INTRADAY_PREREG.md'
const FIND = 'docs/research/DEX_INTRADAY_FINDINGS.md'
const SD = 'scripts/gex_bt/dex_directional_stats.py'
const SM = 'scripts/gex_bt/dex_magnet_stats.py'

const DIGEST = { type: 'object', additionalProperties: false,
  properties: { dir_lead: { type: 'string' }, magnet_p: { type: 'string' },
    n_buckets: { type: 'integer' }, n_bubbles: { type: 'integer' }, notes: { type: 'string' } },
  required: ['dir_lead', 'magnet_p', 'notes'] }
const LENS = { type: 'object', additionalProperties: false,
  properties: { lens: { type: 'string' }, verdict: { type: 'string', enum: ['supports_null', 'finds_caveat', 'overturns'] },
    key_numbers: { type: 'string' }, reasoning: { type: 'string' }, ran_code: { type: 'boolean' } },
  required: ['lens', 'verdict', 'key_numbers', 'reasoning'] }
const VERD = { type: 'object', additionalProperties: false,
  properties: { verdict: { type: 'string', enum: ['confirm_null', 'caveat_found', 'overturned'] },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] }, rationale: { type: 'string' },
    thread_safe_claim: { type: 'string' }, findings_updated: { type: 'boolean' } },
  required: ['verdict', 'confidence', 'rationale', 'thread_safe_claim'] }

phase('Load')
const digest = await agent(
  `Load a pre-registered test for adversarial review. It tests two claims on the REAL SPXW 0DTE tape
(32 days): (A) does intraday 3-min net signed delta/notional FLOW lead the next 5/15/30-min SPX move,
and (B) Quant Data's stated claim that "sudden large fresh bubbles attract price / are magnets."
Read ${DIRR}, ${MAGR}, ${PRE}, ${FIND}, and the per-strike cache header + the two stat scripts
${SD} ${SM}. The cache ${CACHE} has columns day_idx,date,sec_end,spot,strike,dflow,nflow,gross
(dflow=net signed delta flow, nflow=net signed premium, gross=total premium activity = bubble size).
Return a faithful digest (the actual directional corr/sign-acc and the magnet bubble-vs-placebo p).
Do NOT judge yet.`,
  { schema: DIGEST, phase: 'Load', label: 'load' })
log(`Loaded: dir=${digest?.dir_lead} magnet_p=${digest?.magnet_p}`)

phase('Challenge')
const LENSES = [
  { key: 'bubble_definition', prompt: `Challenge the MAGNET bubble definition. The magnet test (${SM}) defines a bubble as top-decile
GROSS premium, 0.2-2.0% from spot, spiking vs the strike's trailing mean. Re-run the magnet test from
${CACHE} under alternates and report whether the null (bubble <= distance-matched placebo) holds:
(a) bubble metric = NET notional (nflow) or net |dflow| instead of gross; (b) TOP_PCT in {80,95};
(c) DIST bands {0.001-0.01, 0.005-0.03}; (d) SPIKE_X in {1.5, 3}; (e) drop the spike requirement.
Write+run python on the cache (it's local, fast — no ThetaData). Does ANY definition make bubbles
beat the distance-matched placebo (one-sided p<0.05)? ran_code=true.` },
  { key: 'aggressor_classification', prompt: `Challenge the AGGRESSOR proxy. The flow sign uses trade>=ask -> buy, <=bid -> sell, mid excluded
(in dex_tape_collect.py, baked into the cache's dflow/nflow signs). This can misclassify. From the
cache you CANNOT re-classify (signs are baked), so instead: (a) assess how sensitive the DIRECTIONAL
result could be — what fraction of premium is 'gross' (all trades) vs net (signed)? If net flow is a
small fraction of gross, classification noise dominates and the ~−0.05 corr is unsurprising. (b) Re-run
the directional test using |dflow|/gross ratio as a 'conviction' filter (only buckets where net is a
large fraction of gross) — does a cleaner-signed subset show any lead? Report. ran_code=true.` },
  { key: 'placebo_control', prompt: `Challenge the MAGNET placebo. The magnet test matches each bubble to ONE same-distance non-bubble
strike. Is that control fair/robust? Re-run from ${CACHE} with alternates: (a) average over MULTIPLE
distance-matched placebos per bubble; (b) opposite-side placebo; (c) a no-control raw test (does
price migrate toward bubbles at all, ignoring placebo — to see the absolute toward-rate). Confirm the
distance-matched control isn't hiding a real effect, and that the raw absolute migration is also
non-magnetic. ran_code=true.` },
  { key: 'regime_subgroup', prompt: `Honest subgroup hunt (guard against mining). Does flow LEAD or do bubbles ATTRACT in any subgroup,
even if not on average? From ${CACHE}: split by (a) trend days vs range days (by the day's open-to-close
|return|), (b) time of day (open 9:30-11, midday, power-hour 15-16), (c) high vs low realized vol.
Re-run directional corr + magnet bubble-minus-placebo within each. For any 'positive' subgroup, re-run
its OWN within-subgroup placebo/bootstrap. Be explicit that 1 lucky subgroup of many is expected under
the null. ran_code=true.` },
  { key: 'methodology_audit', prompt: `Audit ${SD} and ${SM} for errors that bias toward/against the null. Verify: (1) NO look-ahead — the
forward spot is strictly AFTER the bucket's sec_end (check fwd/fwd_spot); (2) day-clustered bootstrap
is correct (resamples whole days); (3) the magnet 'migration' metric sign is right (positive = toward
K); (4) the n (4162 buckets / 2248 bubbles) is real not inflated by duplicates; (5) Holm family honest.
Quote exact lines. Overturn only on a verdict-flipping bug. ran_code as appropriate.` },
]
const lenses = (await parallel(LENSES.map(L => () =>
  agent(L.prompt, { schema: LENS, phase: 'Challenge', label: `lens:${L.key}` }).then(r => r ? { ...r, key: L.key } : null)))).filter(Boolean)
const overturns = lenses.filter(l => l.verdict === 'overturns').length
log(`Lenses: ${lenses.length} — overturns=${overturns} caveats=${lenses.filter(l => l.verdict === 'finds_caveat').length}`)

phase('Verdict')
const dg = lenses.map(l => `### ${l.key} -> ${l.verdict} (ran_code=${l.ran_code})\nKEY: ${l.key_numbers}\nWHY: ${l.reasoning}`).join('\n\n')
const verdict = await agent(
  `Red-team synthesizer. Final verdict on the DEX intraday tests. Headline: directional flow does NOT
lead (corr ~−0.05, sign-acc <0.50, Holm all fail) -> flow_coincident; MAGNET (Quant Data's "bubbles
attract price") FALSIFIED (bubble migration <= distance-matched placebo, one-sided p 0.85-0.996).

The 5 adversarial lenses (most re-ran code off the local cache):

${dg}

Decide ONE: 'confirm_null' (robustness holds — both claims fail as reported), 'caveat_found' (a
specific subgroup/definition shows something worth a follow-up — state it), or 'overturned' (a bug
flips it). Default to skepticism but report honestly if a lens found real signal. Update ${FIND} with a
"Robustness review" section. Give a single THREAD-SAFE one-sentence claim that names Quant Data's
magnet framing fairly (their docs assert it without validation; we tested 2,248 events) and cannot be
called a strawman.`,
  { schema: VERD, phase: 'Verdict', label: 'verdict' })
log(`VERDICT: ${verdict?.verdict} (${verdict?.confidence})`)
return { digest, lenses, verdict }
