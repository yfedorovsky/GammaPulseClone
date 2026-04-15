"""Trade-by-trade analysis for chip/semi tickers."""
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

CHIP_TICKERS = ['NVDA', 'MU', 'AMD', 'SMH', 'LRCX', 'AMAT', 'AVGO', 'MRVL', 'TSM', 'INTC']

for ticker in CHIP_TICKERS:
    tt = [t for t in trades if t['ticker'] == ticker]
    if not tt:
        print(f"\n{ticker}: no trades")
        continue

    wins = [t for t in tt if t['outcome'] == 'WIN']
    losses = [t for t in tt if t['outcome'] == 'LOSS']
    holds = [t['days_held'] for t in tt if t['days_held'] > 0]

    print(f"\n{'='*70}")
    print(f"  {ticker}: {len(tt)} trades, {len(wins)}/{len(tt)} WR ({len(wins)/len(tt)*100:.0f}%)")
    print(f"  Avg P&L: {sum(t['pnl_pct'] for t in tt)/len(tt):+.1f}%  |  Total: {sum(t['pnl_pct'] for t in tt):+.1f}%")
    if wins:
        print(f"  Avg Win: {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}%  |  Avg Loss: {sum(t['pnl_pct'] for t in losses)/max(len(losses),1):.1f}%")
    print(f"  Avg Hold: {sum(holds)/max(len(holds),1):.1f}d")

    # Exit reasons
    exits = defaultdict(int)
    for t in tt: exits[t['exit_reason']] += 1
    print(f"  Exits: {dict(exits)}")

    # Every trade
    print(f"  {'#':>3} {'Date':<12} {'Spot':>8} {'P&L':>8} {'Days':>4} {'Exit':<18} {'MFE':>6} {'Result'}")
    print(f"  {'-'*72}")
    for i, t in enumerate(sorted(tt, key=lambda x: str(x['date'])), 1):
        d = str(t['date'])[:10]
        result = 'WIN' if t['outcome'] == 'WIN' else 'LOSS'
        spot = t.get('entry_spot', 0)
        mfe = t.get('max_favorable', 0)
        print(f"  {i:>3} {d:<12} ${spot:>7.2f} {t['pnl_pct']:>+7.1f}% {t['days_held']:>4}d {t['exit_reason']:<18} {mfe:>+5.1f}% {result}")

    # Monthly
    by_month = defaultdict(list)
    for t in tt: by_month[str(t['date'])[:7]].append(t)
    cumul = 0
    print(f"\n  Monthly:")
    for m in sorted(by_month.keys()):
        mt = by_month[m]
        w = sum(1 for t in mt if t['outcome'] == 'WIN')
        s = sum(t['pnl_pct'] for t in mt)
        cumul += s
        print(f"    {m}: {w}/{len(mt)} trades  month {s:+7.1f}%  cumul {cumul:+8.1f}%")

# B&H comparison
print(f"\n{'='*70}")
print(f"  BUY & HOLD COMPARISON")
print(f"{'='*70}")
with open('data/spots.csv') as f:
    spot_data = defaultdict(list)
    for r in csv.DictReader(f):
        if r['ticker'] in CHIP_TICKERS:
            spot_data[r['ticker']].append((r['date'], float(r['close'])))

for ticker in CHIP_TICKERS:
    sd = sorted(spot_data.get(ticker, []))
    jan = [s for s in sd if s[0] >= '2025-01-01']
    if not jan: continue
    bh = (jan[-1][1] - jan[0][1]) / jan[0][1] * 100

    tt = [t for t in trades if t['ticker'] == ticker]
    mir_total = sum(t['pnl_pct'] for t in tt) if tt else 0

    verdict = 'MIR WINS' if mir_total > bh else 'B&H WINS'
    print(f"  {ticker:<6} B&H: {bh:+7.1f}%  Mir: {mir_total:+8.1f}%  {verdict}")

CONFIGS['swing']['dte_range'] = (14, 21)
