"""ChatGPT's 10 recommended tests — the 6 remaining ones."""
import sys, io, json, csv, math
from collections import defaultdict
from pathlib import Path
from datetime import datetime, date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from backtest.runner import load_per_ticker_csvs
from backtest.mir_backtest import run_mir_backtest, CONFIGS

chains, spots = load_per_ticker_csvs(Path('./data'))

# Load spot lookup for entry timing tests
spot_lookup = defaultdict(dict)
with open('data/spots.csv') as f:
    for row in csv.DictReader(f):
        spot_lookup[row['ticker']][row['date']] = {
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
        }

# Run base case
CONFIGS['swing']['dte_range'] = (7, 14)
results = run_mir_backtest(chains, spots, 'swing', False, 100_000)
trades = results['trades']
filtered = [t for t in trades if t['ticker'] not in ('SPY', 'QQQ')]

print("\n" + "=" * 70)
print("  ChatGPT TESTS 5-10 (remaining)")
print("=" * 70)

# ============================================================
# TEST 5: Entry Timing Sensitivity
# ============================================================
print("\n\n--- TEST 5: ENTRY TIMING SENSITIVITY ---")
print("  Does the edge survive different entry assumptions?")

# Check gap-up filter: skip if stock gaps up > 2% at open
gap_filtered = []
no_gap = []
for t in filtered:
    ticker = t['ticker']
    d = str(t['date'])[:10]
    sd = spot_lookup.get(ticker, {}).get(d, {})
    if not sd or not sd['open'] or not sd['close']:
        no_gap.append(t)
        continue
    # Previous day close
    dates = sorted(spot_lookup.get(ticker, {}).keys())
    if d not in dates:
        no_gap.append(t)
        continue
    idx = dates.index(d)
    if idx == 0:
        no_gap.append(t)
        continue
    prev_close = spot_lookup[ticker][dates[idx-1]]['close']
    gap_pct = (sd['open'] - prev_close) / prev_close * 100

    if gap_pct > 2.0:
        gap_filtered.append(t)
    else:
        no_gap.append(t)

def quick_stats(subset, label):
    if not subset:
        print(f"  {label}: no trades")
        return
    w = sum(1 for t in subset if t['outcome'] == 'WIN')
    p = [t['pnl_pct'] for t in subset]
    print(f"  {label}: {len(subset)} trades, {w/len(subset)*100:.1f}% WR, avg {sum(p)/len(p):+.1f}%")

quick_stats(filtered, "All trades (baseline)")
quick_stats(no_gap, "Skip gap-up > 2%")
quick_stats(gap_filtered, "Gap-up > 2% trades (removed)")

# Open vs close entry comparison
open_trades = []
close_trades = []
for t in filtered:
    ticker = t['ticker']
    d = str(t['date'])[:10]
    sd = spot_lookup.get(ticker, {}).get(d, {})
    if sd and sd['open'] > 0 and sd['close'] > 0:
        # If entered at open instead of close
        open_entry = sd['open']
        close_entry = sd['close']
        # Approximate: how different would P&L be?
        gap = (open_entry - close_entry) / close_entry * 100
        if gap > 0:  # open was higher = worse entry for calls
            open_trades.append(t['pnl_pct'] - gap * 3)  # rough leverage adj
        else:
            open_trades.append(t['pnl_pct'] + abs(gap) * 3)

if open_trades:
    print(f"  If entered at OPEN instead of CLOSE: avg {sum(open_trades)/len(open_trades):+.1f}% (vs {sum(t['pnl_pct'] for t in filtered)/len(filtered):+.1f}% at close)")

# ============================================================
# TEST 6: DTE x Hold Interaction
# ============================================================
print("\n\n--- TEST 6: DTE x HOLD INTERACTION ---")
print("  Do fast holds (1-2d) or slow holds (5+d) drive the edge?")

hold_buckets = {
    '1 day': (0, 1),
    '2 days': (2, 2),
    '3-4 days': (3, 4),
    '5-7 days': (5, 7),
    '8+ days': (8, 100),
}

print(f"\n  {'Hold':<12} {'Trades':>6} {'WR':>6} {'Avg P&L':>8} {'Avg Win':>8} {'Avg Loss':>9} {'% of Total P&L':>14}")
total_pnl = sum(t['pnl_pct'] for t in filtered)
for label, (lo, hi) in hold_buckets.items():
    subset = [t for t in filtered if lo <= t['days_held'] <= hi]
    if not subset:
        continue
    w = sum(1 for t in subset if t['outcome'] == 'WIN')
    p = [t['pnl_pct'] for t in subset]
    wp = [x for x in p if x > 0]
    lp = [x for x in p if x <= 0]
    bucket_pnl = sum(p)
    pct_of_total = bucket_pnl / total_pnl * 100 if total_pnl else 0
    print(f"  {label:<12} {len(subset):>6} {w/len(subset)*100:>5.1f}% {sum(p)/len(p):>+7.1f}% {sum(wp)/max(len(wp),1):>+7.1f}% {sum(lp)/max(len(lp),1):>8.1f}% {pct_of_total:>13.0f}%")

# ============================================================
# TEST 7: Moneyness Test (ATM vs 1st OTM vs 2nd OTM)
# ============================================================
print("\n\n--- TEST 7: MONEYNESS TEST ---")
print("  ATM vs 1st OTM vs 2nd OTM (via grid search configs)")

for so_label, so_val in [("ATM", 0), ("1st OTM", 1), ("2nd OTM", 2)]:
    # Re-run with different strike offset
    from backtest.mir_backtest import CONFIGS as CFG2
    # We can approximate by adjusting the existing trades' P&L
    # ATM = higher delta, more P&L per move but more expensive
    # 2nd OTM = lower delta, less P&L per move but cheaper
    leverage_adj = {0: 1.3, 1: 1.0, 2: 0.7}[so_val]
    adj_pnls = [t['pnl_pct'] * leverage_adj for t in filtered]
    w = sum(1 for p in adj_pnls if p > 0)
    avg = sum(adj_pnls) / len(adj_pnls)
    print(f"  {so_label:<10} est avg {avg:+.1f}%, WR {w/len(adj_pnls)*100:.1f}%  (leverage adj {leverage_adj}x)")

print("  NOTE: Approximate. Full test needs separate backtest runs per strike offset.")

# ============================================================
# TEST 8: Remove Bull-Market Crutch
# ============================================================
print("\n\n--- TEST 8: REMOVE BULL-MARKET CRUTCH ---")
print("  What happens with NO regime filter (SPY 20d check removed)?")

# Re-run without regime filter
# We can approximate: include trades from months that were filtered out
# Check which months had negative SPY 20d
spy_closes = []
for d in sorted(spot_lookup.get('SPY', {}).keys()):
    spy_closes.append((d, spot_lookup['SPY'][d]['close']))

neg_regime_months = set()
for i in range(20, len(spy_closes)):
    ret_20d = (spy_closes[i][1] - spy_closes[i-20][1]) / spy_closes[i-20][1] * 100
    if ret_20d < 0:
        neg_regime_months.add(spy_closes[i][0][:7])

print(f"  Negative regime months: {sorted(neg_regime_months)}")
print(f"  ({len(neg_regime_months)} months with SPY 20d < 0)")

# Split current trades by whether they were in positive or negative regime
pos_regime = []
neg_regime = []
for t in filtered:
    m = str(t['date'])[:7]
    d = str(t['date'])[:10]
    # Check if this specific date was negative regime
    spy_dates = [s[0] for s in spy_closes]
    if d in spy_dates:
        idx = spy_dates.index(d)
        if idx >= 20:
            ret = (spy_closes[idx][1] - spy_closes[idx-20][1]) / spy_closes[idx-20][1] * 100
            if ret < 0:
                neg_regime.append(t)
            else:
                pos_regime.append(t)
        else:
            pos_regime.append(t)
    else:
        pos_regime.append(t)

quick_stats(pos_regime, "Positive regime trades")
quick_stats(neg_regime, "Negative regime trades (would be filtered)")
quick_stats(filtered, "All trades (current, with filter)")

# ============================================================
# TEST 9: Stock Replacement (already partially done, expand)
# ============================================================
print("\n\n--- TEST 9: STOCK vs CALL vs STOP-PROTECTED STOCK ---")

stock_returns = []
for t in filtered:
    ticker = t['ticker']
    entry_date = str(t['date'])[:10]
    days_held = t['days_held']
    dates = sorted(spot_lookup.get(ticker, {}).keys())
    if entry_date not in dates:
        continue
    entry_idx = dates.index(entry_date)
    exit_idx = min(entry_idx + max(days_held, 1), len(dates) - 1)
    entry_p = spot_lookup[ticker][dates[entry_idx]]['close']
    exit_p = spot_lookup[ticker][dates[exit_idx]]['close']
    if entry_p > 0:
        stock_ret = (exit_p - entry_p) / entry_p * 100
        # Stop-protected stock: cap loss at -3%
        stopped_ret = max(stock_ret, -3.0)
        stock_returns.append({
            'stock': stock_ret,
            'option': t['pnl_pct'],
            'stopped_stock': stopped_ret,
            'ticker': ticker,
        })

if stock_returns:
    s = [r['stock'] for r in stock_returns]
    o = [r['option'] for r in stock_returns]
    ss = [r['stopped_stock'] for r in stock_returns]

    print(f"\n  {'Strategy':<25} {'Avg':>8} {'Median':>8} {'Total':>10} {'Max Loss':>9}")
    print(f"  {'-'*60}")
    print(f"  {'Long stock':<25} {sum(s)/len(s):>+7.2f}% {sorted(s)[len(s)//2]:>+7.2f}% {sum(s):>+9.1f}% {min(s):>+8.2f}%")
    print(f"  {'Stock + 3% stop':<25} {sum(ss)/len(ss):>+7.2f}% {sorted(ss)[len(ss)//2]:>+7.2f}% {sum(ss):>+9.1f}% {min(ss):>+8.2f}%")
    print(f"  {'Long call (current)':<25} {sum(o)/len(o):>+7.1f}% {sorted(o)[len(o)//2]:>+7.1f}% {sum(o):>+9.1f}% {min(o):>+8.1f}%")

    # Capital efficiency: option uses ~5% of stock capital
    print(f"\n  Capital efficiency (same $10K deployed):")
    print(f"  Stock: $10K -> {sum(s)/len(s) * len(s) / 100 * 10000:+,.0f} total P&L")
    print(f"  Options ($500/trade x {len(o)} trades): {sum(o)/len(o) * len(o) / 100 * 500:+,.0f} total P&L")

# ============================================================
# TEST 10: Time-to-Resolution / Path Dependency
# ============================================================
print("\n\n--- TEST 10: TIME-TO-RESOLUTION / PATH DEPENDENCY ---")

# Winners that first went negative
winners = [t for t in filtered if t['outcome'] == 'WIN']
losers = [t for t in filtered if t['outcome'] == 'LOSS']

# We don't have intrabar MFE/MAE, but we can check if winners had any adverse excursion
# Using max_favorable as a proxy for path
print(f"\n  Winners: {len(winners)} trades")
win_mfe = [t['max_favorable'] for t in winners]
print(f"  Avg MFE: {sum(win_mfe)/len(win_mfe):+.1f}%")
print(f"  % that hit +100% target: {sum(1 for t in winners if t['pnl_pct'] >= 100)/len(winners)*100:.0f}%")
print(f"  % that hit +25% ladder: {sum(1 for t in winners if t['max_favorable'] >= 25)/len(winners)*100:.0f}%")

# Winners by speed
fast_w = [t for t in winners if t['days_held'] <= 2]
slow_w = [t for t in winners if t['days_held'] > 2]
print(f"\n  Fast winners (<=2d): {len(fast_w)} trades, avg {sum(t['pnl_pct'] for t in fast_w)/max(len(fast_w),1):+.1f}%")
print(f"  Slow winners (>2d):  {len(slow_w)} trades, avg {sum(t['pnl_pct'] for t in slow_w)/max(len(slow_w),1):+.1f}%")

print(f"\n  Losers: {len(losers)} trades")
# Losers that were once profitable
losers_once_profitable = [t for t in losers if t['max_favorable'] > 0]
losers_never_positive = [t for t in losers if t['max_favorable'] <= 0]
print(f"  Once profitable (MFE > 0): {len(losers_once_profitable)} ({len(losers_once_profitable)/len(losers)*100:.0f}%)")
print(f"  Never positive: {len(losers_never_positive)} ({len(losers_never_positive)/len(losers)*100:.0f}%)")

losers_had_25 = [t for t in losers if t['max_favorable'] >= 25]
print(f"  Had +25% MFE before dying: {len(losers_had_25)} ({len(losers_had_25)/len(losers)*100:.0f}%)")
if losers_had_25:
    print(f"  These traded avg exit: {sum(t['pnl_pct'] for t in losers_had_25)/len(losers_had_25):+.1f}% (should have been +12.5%)")

# Exit reason by hold time
print(f"\n  Exit reason by hold time:")
for hold_label, (lo, hi) in [("Day 1", (0,1)), ("Day 2", (2,2)), ("Day 3-4", (3,4)), ("Day 5+", (5,100))]:
    subset = [t for t in filtered if lo <= t['days_held'] <= hi]
    if not subset:
        continue
    exits = defaultdict(int)
    for t in subset:
        exits[t['exit_reason']] += 1
    parts = ", ".join(f"{k}: {v}" for k, v in sorted(exits.items(), key=lambda x: x[1], reverse=True))
    print(f"  {hold_label:<10} {parts}")

print("\n" + "=" * 70)
CONFIGS['swing']['dte_range'] = (14, 21)
