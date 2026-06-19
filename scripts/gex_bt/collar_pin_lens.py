"""
Lens: Is the JHEQX 'pin' COLLAR-specific, or generic round-number / low-vol settling
that would happen at ANY salient strike near spot?

Three sub-analyses:
 (a) Pin rate at cap vs nearest round-100 placebo; quantify the gap and whether it is
     explained by the cap simply being closer to spot.
 (b) Do pin hits cluster in quarters where SPX barely moved over the run-in?
 (c) Does cap distance-from-spot explain pinning better than its being the collar leg?
"""
import json, math, statistics as st

PIN_THRESH = 0.005  # 0.5% settle-within-strike (inferred: max hit |dist|=0.378%, min miss=0.52%)

d = json.load(open('data/collar_bt_full.json'))
ev = [e for e in d['events'] if 'error' not in e]

def absdist(strike, spot):
    return abs(strike / spot - 1.0)

# Recompute pin flags from raw settle/strike to be threshold-explicit and consistent
for e in ev:
    cap = e['short_call']['strike']
    pl  = e['h1_placebo_strike']
    settle = e['settle']
    spot = e['asof_close']
    e['_cap_pin']     = absdist(cap, settle) <= PIN_THRESH
    e['_placebo_pin'] = absdist(pl, settle) <= PIN_THRESH
    e['_cap_d0']      = absdist(cap, spot)   # cap distance from spot at as-of
    e['_pl_d0']       = absdist(pl, spot)
    e['_runin_move']  = absdist(settle, spot)  # |settle/asof_close - 1|, realized run-in move
    e['_cap_closer']  = e['_cap_d0'] < e['_pl_d0']

n = len(ev)
cap_hits = [e for e in ev if e['_cap_pin']]
pl_hits  = [e for e in ev if e['_placebo_pin']]

print("="*78)
print(f"N analyzable events = {n}   PIN_THRESH = {PIN_THRESH*100:.2f}% settle-within-strike")
print("="*78)

# ---------- (a) Cap vs placebo pin rate + confound check ----------
print("\n(a) PIN RATE: cap vs nearest round-100 placebo")
print(f"  cap pins     : {len(cap_hits):2d}/{n}  = {len(cap_hits)/n*100:5.1f}%")
print(f"  placebo pins : {len(pl_hits):2d}/{n}  = {len(pl_hits)/n*100:5.1f}%")
print(f"  RAW gap      : {(len(cap_hits)-len(pl_hits))/n*100:+.1f} pp")

# Is the placebo systematically farther from spot? (the confound)
cap_closer_n = sum(1 for e in ev if e['_cap_closer'])
print(f"\n  Confound: cap is closer to spot than placebo in {cap_closer_n}/{n} events ({cap_closer_n/n*100:.0f}%)")
print(f"  mean cap_dist0     = {st.mean(e['_cap_d0'] for e in ev)*100:.2f}%")
print(f"  mean placebo_dist0 = {st.mean(e['_pl_d0'] for e in ev)*100:.2f}%")

# Distance-matched test: for each event, the cap and placebo each get a pin chance.
# If pinning were pure proximity, the CLOSER strike should pin more regardless of identity.
# Compare: pin rate of "closer strike" vs "farther strike" pooling cap+placebo.
closer_pins = sum(1 for e in ev if (e['_cap_pin'] if e['_cap_closer'] else e['_placebo_pin']))
farther_pins= sum(1 for e in ev if (e['_placebo_pin'] if e['_cap_closer'] else e['_cap_pin']))
print(f"\n  Proximity test (pool both strikes, label by who is closer to spot):")
print(f"    CLOSER strike pins  : {closer_pins}/{n} = {closer_pins/n*100:.1f}%")
print(f"    FARTHER strike pins : {farther_pins}/{n} = {farther_pins/n*100:.1f}%")

# Within events where placebo is the CLOSER one, does it out-pin the cap?
pl_closer = [e for e in ev if not e['_cap_closer']]
if pl_closer:
    pcc = sum(1 for e in pl_closer if e['_placebo_pin'])
    ccc = sum(1 for e in pl_closer if e['_cap_pin'])
    print(f"\n  Subset where PLACEBO is closer to spot (n={len(pl_closer)}):")
    print(f"    placebo pins {pcc}, cap pins {ccc}  "
          f"-> if proximity ruled, placebo should win here")

# ---------- (b) Do pins cluster in tiny-realized-move quarters? ----------
print("\n" + "="*78)
print("(b) Do the ~8 cap pins cluster in quarters where SPX barely moved (run-in)?")
moves = sorted(e['_runin_move'] for e in ev)
med_move = st.median(moves)
print(f"  median run-in |settle/asof-1| over all events = {med_move*100:.2f}%")
print(f"\n  {'expiry':>11} {'runin_move%':>11} {'cap_d0%':>8} {'cap_pin':>7} {'pl_pin':>6}")
for e in sorted(ev, key=lambda x: x['_runin_move']):
    if e['_cap_pin'] or e['_runin_move'] <= med_move:
        print(f"  {e['expiry']:>11} {e['_runin_move']*100:11.2f} {e['_cap_d0']*100:8.2f} "
              f"{'YES' if e['_cap_pin'] else '.':>7} {'yes' if e['_placebo_pin'] else '.':>6}")

cap_pin_moves = [e['_runin_move'] for e in cap_hits]
nonpin_moves  = [e['_runin_move'] for e in ev if not e['_cap_pin']]
print(f"\n  mean run-in move | CAP PIN events  = {st.mean(cap_pin_moves)*100:.2f}%  (n={len(cap_pin_moves)})")
print(f"  mean run-in move | non-pin events  = {st.mean(nonpin_moves)*100:.2f}%  (n={len(nonpin_moves)})")
# How many cap pins are in the low-move half?
low_half = [e for e in cap_hits if e['_runin_move'] <= med_move]
print(f"  cap pins in the LOW-move half: {len(low_half)}/{len(cap_hits)}")

# Critical question: in those low-move quarters, was the cap also the closest strike?
# If move tiny AND cap closest -> indistinguishable from generic nearest-strike settling.
print(f"\n  Among cap pins: cap_dist0 and whether cap was the closest strike:")
for e in cap_hits:
    print(f"    {e['expiry']}  cap_d0={e['_cap_d0']*100:.2f}%  "
          f"runin_move={e['_runin_move']*100:.2f}%  "
          f"{'cap_closest' if e['_cap_closer'] else 'placebo_closer'}")

# ---------- (c) Distance vs collar-leg-identity as predictor ----------
print("\n" + "="*78)
print("(c) Does cap distance-from-spot explain pinning better than collar-leg identity?")

# Logistic-free: bucket cap by distance, show pin rate per bucket.
buckets = [(0,0.005),(0.005,0.01),(0.01,0.02),(0.02,1.0)]
print(f"\n  Pin rate of the CAP, bucketed by cap distance-from-spot at as-of:")
print(f"  {'cap_d0 bucket':>16} {'n':>4} {'cap_pins':>9} {'rate':>7}")
for lo,hi in buckets:
    sub=[e for e in ev if lo<=e['_cap_d0']<hi]
    if not sub: continue
    p=sum(1 for e in sub if e['_cap_pin'])
    print(f"  {lo*100:5.1f}-{hi*100:5.1f}%      {len(sub):4d} {p:9d} {p/max(len(sub),1)*100:6.1f}%")

# Does a generic 'closest round-25/round-100 strike' pin at the same rate as the cap
# WHEN matched on distance? Build a placebo that is itself near spot and compare.
# Use: among events where cap_d0 <= 1%, cap pin rate vs placebo pin rate.
near = [e for e in ev if e['_cap_d0']<=0.01]
if near:
    cp=sum(1 for e in near if e['_cap_pin']); pp=sum(1 for e in near if e['_placebo_pin'])
    print(f"\n  Distance-matched (cap within 1% of spot, n={len(near)}):")
    print(f"    cap pins {cp}/{len(near)} = {cp/len(near)*100:.0f}%   "
          f"placebo pins {pp}/{len(near)} = {pp/len(near)*100:.0f}%")
    print(f"    mean cap_d0={st.mean(e['_cap_d0'] for e in near)*100:.2f}%  "
          f"mean pl_d0={st.mean(e['_pl_d0'] for e in near)*100:.2f}%")

# Point-biserial-ish: correlation between cap being close and pinning, vs the
# fact that ALL pins occur when cap is already near spot.
_d0list = ', '.join('%.2f%%' % (e['_cap_d0']*100) for e in cap_hits)
print("\n  All 8 cap pins had cap_d0 = [%s]" % _d0list)
print(f"  Max cap_d0 among pins = {max(e['_cap_d0'] for e in cap_hits)*100:.2f}%")
print(f"  -> every pin required the cap to be < this far from spot already.")

# Counterfactual: how often is the cap within that same distance but does NOT pin?
maxpin_d0 = max(e['_cap_d0'] for e in cap_hits)
near_cap = [e for e in ev if e['_cap_d0']<=maxpin_d0]
np_pins = sum(1 for e in near_cap if e['_cap_pin'])
print(f"  When cap_d0 <= {maxpin_d0*100:.2f}% (n={len(near_cap)}): "
      f"{np_pins} pin, {len(near_cap)-np_pins} do NOT -> "
      f"conditional pin rate {np_pins/len(near_cap)*100:.0f}%")
