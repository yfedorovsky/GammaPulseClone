"""Robustness tests per ChatGPT recommendations."""
import sys, io, json, csv, math
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backtest.runner import load_per_ticker_csvs
from backtest.mir_backtest import run_mir_backtest, CONFIGS

chains, spots = load_per_ticker_csvs(Path('./data'))
CONFIGS['swing']['dte_range'] = (7, 14)
results = run_mir_backtest(chains, spots, 'swing', False, 100_000)
trades = results['trades']

# Filter sector leaders only
filtered = [t for t in trades if t['ticker'] not in ('SPY', 'QQQ')]
pnls = [t['pnl_pct'] for t in filtered]
wins = sum(1 for t in filtered if t['outcome'] == 'WIN')

print("=" * 70)
print("  ROBUSTNESS TESTS (ChatGPT Recommended)")
print("=" * 70)

# ============================================================
# TEST 1: Outlier Robustness
# ============================================================
print("\n--- TEST 1: OUTLIER ROBUSTNESS ---")

# Full sample
print(f"\n  Full sample: {len(filtered)} trades, {wins/len(filtered)*100:.1f}% WR, avg {sum(pnls)/len(pnls):+.1f}%")
print(f"  Median P&L: {sorted(pnls)[len(pnls)//2]:+.1f}%")

# Without AXTI
no_axti = [t for t in filtered if t['ticker'] != 'AXTI']
na_pnls = [t['pnl_pct'] for t in no_axti]
na_wins = sum(1 for t in no_axti if t['outcome'] == 'WIN')
print(f"\n  Without AXTI: {len(no_axti)} trades, {na_wins/len(no_axti)*100:.1f}% WR, avg {sum(na_pnls)/len(na_pnls):+.1f}%")
print(f"  Median P&L: {sorted(na_pnls)[len(na_pnls)//2]:+.1f}%")

# Exclude top trade per ticker
trimmed = []
by_ticker = defaultdict(list)
for t in filtered:
    by_ticker[t['ticker']].append(t)
for ticker, tt in by_ticker.items():
    sorted_tt = sorted(tt, key=lambda x: x['pnl_pct'], reverse=True)
    trimmed.extend(sorted_tt[1:])  # skip the single biggest winner
tr_pnls = [t['pnl_pct'] for t in trimmed]
tr_wins = sum(1 for t in trimmed if t['outcome'] == 'WIN')
print(f"\n  Exclude top winner per ticker: {len(trimmed)} trades, {tr_wins/len(trimmed)*100:.1f}% WR, avg {sum(tr_pnls)/len(tr_pnls):+.1f}%")

# Winsorize at 95th percentile
p95 = sorted(pnls)[int(len(pnls) * 0.95)]
p5 = sorted(pnls)[int(len(pnls) * 0.05)]
winsorized = [max(min(p, p95), p5) for p in pnls]
print(f"\n  Winsorized (5th-95th): avg {sum(winsorized)/len(winsorized):+.1f}% (cap at {p5:.0f}% to {p95:.0f}%)")

# ============================================================
# TEST 2: Distribution Analysis
# ============================================================
print("\n\n--- TEST 2: P&L DISTRIBUTION ---")
sorted_pnls = sorted(pnls)
print(f"  P10: {sorted_pnls[int(len(pnls)*0.1)]:+.1f}%")
print(f"  P25: {sorted_pnls[int(len(pnls)*0.25)]:+.1f}%")
print(f"  Median: {sorted_pnls[len(pnls)//2]:+.1f}%")
print(f"  P75: {sorted_pnls[int(len(pnls)*0.75)]:+.1f}%")
print(f"  P90: {sorted_pnls[int(len(pnls)*0.90)]:+.1f}%")
print(f"  P95: {sorted_pnls[int(len(pnls)*0.95)]:+.1f}%")
print(f"  Min: {min(pnls):+.1f}%  Max: {max(pnls):+.1f}%")

# % of P&L from top 10 trades
top_10 = sorted(pnls, reverse=True)[:10]
total_pnl = sum(pnls)
top_10_pnl = sum(top_10)
print(f"\n  Total P&L: {total_pnl:+.1f}%")
print(f"  Top 10 trades contribute: {top_10_pnl:+.1f}% ({top_10_pnl/total_pnl*100:.0f}% of total)")
print(f"  Top 10 trades: {[f'+{p:.0f}%' for p in top_10]}")

# Hit rates
hit_25 = sum(1 for t in filtered if t['max_favorable'] >= 25) / len(filtered) * 100
hit_100 = sum(1 for t in filtered if t['pnl_pct'] >= 100) / len(filtered) * 100
hit_stop = sum(1 for t in filtered if t['pnl_pct'] <= -50) / len(filtered) * 100
print(f"\n  Hit +25% MFE: {hit_25:.0f}% of trades")
print(f"  Hit +100% target: {hit_100:.0f}% of trades")
print(f"  Hit -50% stop: {hit_stop:.0f}% of trades")

# ============================================================
# TEST 3: Stock vs Options (same signals)
# ============================================================
print("\n\n--- TEST 3: STOCK vs OPTIONS (same signals) ---")
print("  Using same entry/exit dates, comparing underlying return vs option return")

stock_pnls = []
for t in filtered:
    entry = t.get('entry_spot', 0)
    # Approximate exit spot from option P&L direction
    if t['exit_reason'] == 'TARGET_HIT':
        # Stock moved enough to double the option
        stock_move = 2.0  # rough: +2% underlying for +100% option
    elif t['exit_reason'] == 'STOP_HIT':
        stock_move = -1.0  # rough: -1% underlying for -50% option
    elif t['exit_reason'] == 'BREAKEVEN_STOP':
        stock_move = 0.5  # small positive
    else:
        stock_move = 0

    stock_pnls.append(stock_move)

# Better approach: use actual spot data
stock_returns = []
with open('data/spots.csv') as f:
    spot_lookup = defaultdict(dict)
    for row in csv.DictReader(f):
        spot_lookup[row['ticker']][row['date']] = {
            'open': float(row['open']),
            'close': float(row['close']),
        }

for t in filtered:
    ticker = t['ticker']
    entry_date = str(t['date'])[:10]
    days_held = t['days_held']

    # Find entry and exit spots
    dates = sorted(spot_lookup.get(ticker, {}).keys())
    if entry_date not in dates:
        continue

    entry_idx = dates.index(entry_date)
    exit_idx = min(entry_idx + max(days_held, 1), len(dates) - 1)

    entry_price = spot_lookup[ticker][dates[entry_idx]]['close']
    exit_price = spot_lookup[ticker][dates[exit_idx]]['close']

    if entry_price > 0:
        stock_ret = (exit_price - entry_price) / entry_price * 100
        stock_returns.append({
            'ticker': ticker,
            'stock_pnl': stock_ret,
            'option_pnl': t['pnl_pct'],
            'date': entry_date,
            'days': days_held,
            'outcome': t['outcome'],
        })

if stock_returns:
    s_pnls = [r['stock_pnl'] for r in stock_returns]
    o_pnls = [r['option_pnl'] for r in stock_returns]
    s_wins = sum(1 for p in s_pnls if p > 0)
    o_wins = sum(1 for p in o_pnls if p > 0)

    print(f"\n  Matched trades: {len(stock_returns)}")
    print(f"  {'Metric':<25} {'Stock':>10} {'Options':>10}")
    print(f"  {'-'*45}")
    print(f"  {'Win Rate':<25} {s_wins/len(s_pnls)*100:>9.1f}% {o_wins/len(o_pnls)*100:>9.1f}%")
    print(f"  {'Avg P&L':<25} {sum(s_pnls)/len(s_pnls):>+9.2f}% {sum(o_pnls)/len(o_pnls):>+9.1f}%")
    print(f"  {'Median P&L':<25} {sorted(s_pnls)[len(s_pnls)//2]:>+9.2f}% {sorted(o_pnls)[len(o_pnls)//2]:>+9.1f}%")
    print(f"  {'Total P&L':<25} {sum(s_pnls):>+9.1f}% {sum(o_pnls):>+9.1f}%")
    print(f"  {'Max Win':<25} {max(s_pnls):>+9.2f}% {max(o_pnls):>+9.1f}%")
    print(f"  {'Max Loss':<25} {min(s_pnls):>+9.2f}% {min(o_pnls):>+9.1f}%")

    # Per-ticker stock vs options
    print(f"\n  Per Ticker:")
    by_t = defaultdict(lambda: {'stock': [], 'option': []})
    for r in stock_returns:
        by_t[r['ticker']]['stock'].append(r['stock_pnl'])
        by_t[r['ticker']]['option'].append(r['option_pnl'])

    print(f"  {'Ticker':<8} {'Trades':>6} {'Stock Avg':>10} {'Option Avg':>11} {'Winner'}")
    for tk in sorted(by_t.keys(), key=lambda x: sum(by_t[x]['option'])/len(by_t[x]['option']), reverse=True):
        v = by_t[tk]
        sa = sum(v['stock'])/len(v['stock'])
        oa = sum(v['option'])/len(v['option'])
        winner = 'OPTIONS' if oa > sa else 'STOCK'
        print(f"  {tk:<8} {len(v['stock']):>6} {sa:>+9.2f}% {oa:>+10.1f}% {winner}")

# ============================================================
# TEST 4: Time Split (first half vs second half)
# ============================================================
print("\n\n--- TEST 4: TIME SPLIT ---")
sorted_trades = sorted(filtered, key=lambda t: str(t['date']))
mid = len(sorted_trades) // 2
first_half = sorted_trades[:mid]
second_half = sorted_trades[mid:]

for label, subset in [("First half", first_half), ("Second half", second_half)]:
    w = sum(1 for t in subset if t['outcome'] == 'WIN')
    p = [t['pnl_pct'] for t in subset]
    dates = [str(t['date'])[:10] for t in subset]
    print(f"\n  {label} ({dates[0]} to {dates[-1]}):")
    print(f"    {len(subset)} trades, {w/len(subset)*100:.1f}% WR, avg {sum(p)/len(p):+.1f}%, median {sorted(p)[len(p)//2]:+.1f}%")

print("\n" + "=" * 70)

CONFIGS['swing']['dte_range'] = (14, 21)
