"""One-off LRCX trade analysis."""
import sys, io, csv
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backtest.runner import load_per_ticker_csvs
from backtest.mir_backtest import run_mir_backtest, CONFIGS

chains, spots = load_per_ticker_csvs(Path('./data'))
CONFIGS['swing']['dte_range'] = (7, 14)
results = run_mir_backtest(chains, spots, 'swing', False, 100_000)
trades = results['trades']

lrcx = [t for t in trades if t['ticker'] == 'LRCX']
wins = [t for t in lrcx if t['outcome'] == 'WIN']
losses = [t for t in lrcx if t['outcome'] == 'LOSS']

print(f"LRCX: {len(lrcx)} trades, {len(wins)}/{len(lrcx)} WR ({len(wins)/len(lrcx)*100:.0f}%)")
print(f"Avg P&L: {sum(t['pnl_pct'] for t in lrcx)/len(lrcx):+.1f}%")
print(f"Total P&L: {sum(t['pnl_pct'] for t in lrcx):+.1f}%")
print(f"Avg Win: {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}%")
print(f"Avg Loss: {sum(t['pnl_pct'] for t in losses)/len(losses):.1f}%")
print(f"Avg Hold: {sum(t['days_held'] for t in lrcx)/len(lrcx):.1f}d")
print()

# Every trade
print(f"{'#':>2} {'Date':<12} {'Spot':>8} {'P&L':>8} {'Days':>4} {'Exit':<18} {'MFE':>6} {'Result'}")
print("-" * 75)
for i, t in enumerate(sorted(lrcx, key=lambda x: x['date']), 1):
    result = "WIN" if t['outcome'] == 'WIN' else "LOSS"
    spot = t.get('entry_spot', 0)
    mfe = t.get('max_favorable', 0)
    d = str(t['date'])[:10]
    print(f"{i:>2} {d:<12} ${spot:>7.2f} {t['pnl_pct']:>+7.1f}% {t['days_held']:>4}d {t['exit_reason']:<18} {mfe:>+5.1f}% {result}")

# Spot price context
print()
with open('data/spots.csv') as f:
    lrcx_spots = [(r['date'], float(r['close'])) for r in csv.DictReader(f) if r['ticker'] == 'LRCX']
lrcx_spots.sort()
if lrcx_spots:
    first = [s for s in lrcx_spots if s[0] >= '2025-01-01']
    if first:
        print(f"LRCX price: ${first[0][1]:.2f} ({first[0][0]}) -> ${lrcx_spots[-1][1]:.2f} ({lrcx_spots[-1][0]})")
        print(f"B&H return: {(lrcx_spots[-1][1] - first[0][1])/first[0][1]*100:+.1f}%")

# Monthly
by_month = defaultdict(list)
for t in lrcx:
    by_month[str(t['date'])[:7]].append(t)
print(f"\nMonthly:")
cumul = 0
for m in sorted(by_month.keys()):
    tt = by_month[m]
    w = sum(1 for t in tt if t['outcome'] == 'WIN')
    s = sum(t['pnl_pct'] for t in tt)
    cumul += s
    print(f"  {m}: {w}/{len(tt)} trades  month {s:+7.1f}%  cumul {cumul:+8.1f}%")

CONFIGS['swing']['dte_range'] = (14, 21)
