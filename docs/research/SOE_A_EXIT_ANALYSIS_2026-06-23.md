# SOE_A exit-policy analysis (#121) — 783 alerts, 25 days (2026-05-14->2026-06-22)
_Day-clustered realized OPTION expectancy, ask-in/bid-out. Take-profit/stop are exact from opt_mfe/mae; brackets (TP+SL order) need the path and are omitted._

## Exit-policy sweep (day-clustered realized option return)
- hold-to-EOD (baseline)          -11.7%  (25d)
- scale-1/3-at-+100 (shipped)     -11.7%  (25d)
- take-profit @ +5%               -12.2%  (25d)
- take-profit @ +10%              -12.7%  (25d)
- take-profit @ +15%              -12.4%  (25d)
- take-profit @ +25%              -12.5%  (25d)
- take-profit @ +50%              -12.0%  (25d)
- take-profit @ +100%             -11.6%  (25d)
- stop @ -25%                     -10.2%  (25d)
- stop @ -50%                     -11.5%  (25d)
- stop @ -75%                     -12.0%  (25d)

- **best single policy: stop @ -25% = -10.2%**

## Bracket bounds (take-profit @ +25% AND stop @ -50%, order-ambiguous)
- optimistic (target-first): -12.3%   pessimistic (stop-first): -12.7%

## SPOT diagnosis — is the signal directionally right (entry-latency) or just weak?
- spot EOD win rate (excl FLAT): 37.7%  (W214/L353/F216)
- median spot MFE +0.27%  /  median spot MAE -0.65%  (in thesis direction)
- day-clustered mean spot MFE: +0.50%

## How often the option peak reaches +X% (why a low take-profit can help)
- reach +5%: 318/783 = 40.6%
- reach +10%: 249/783 = 31.8%
- reach +25%: 129/783 = 16.5%
- reach +50%: 46/783 = 5.9%
- reach +100%: 13/783 = 1.7%

## Verdict & recommendation
- **DEMOTE/CUT JUSTIFIED — SOE_A is a directionally WEAK signal, not an exit problem.** No take-profit/stop policy flips it (best stop @ -25% -10.2% vs hold -11.7%), and the SPOT EOD win rate is only 37.7% — the underlying goes AGAINST the thesis more often than with it. The 57.6% option touch-green WR was a CONVEXITY ARTIFACT (a volatile option ticks green briefly), not directional skill. This SUPERSEDES the interim 'don't cut, it's an exit problem' call: after running the exit analysis the audit asked for, the demote is justified with evidence. Recommend: demote SOE_A to UI-only (like WHALE #94) via the env category cut, pending multi-regime confirmation.
- CAVEAT: single regime (25 days, all VIX 15-25, bull). Confirm across a vol-spike/bear before a permanent cut; demote (env-reversible) is the safe interim.
- Next (path-dependent, needs re-fetch): time-stops (exit at min N) + true brackets via scripts/backfill_alert_outcomes_nbbo.py-style minute bars.