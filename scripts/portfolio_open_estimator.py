"""Estimate tomorrow's open value for each option position based on AH prices.

Uses Black-Scholes with post-earnings-IV estimates for tickers that reported,
elevated IV for tickers reporting tomorrow, normal IV for everything else.
"""
from __future__ import annotations

import re
from datetime import datetime
from math import exp, log, sqrt

from scipy.stats import norm

CSV = r"C:\Users\yfedo\Downloads\Portfolio_Positions_May-05-2026.csv"

AH_PRICES = {
    'AAPL': {'rth': 284.18, 'ah_high': 290.46, 'ah_last': 282.40},
    'AMD': {'rth': 355.26, 'ah_high': 414.45, 'ah_last': 414.00},
    'AMZN': {'rth': 273.55, 'ah_high': 273.80, 'ah_last': 272.65},
    'ARM': {'rth': 208.84, 'ah_high': 229.35, 'ah_last': 226.23},
    'ASTS': {'rth': 63.87, 'ah_high': 64.38, 'ah_last': 63.90},
    'AVGO': {'rth': 427.36, 'ah_high': 439.50, 'ah_last': 432.00},
    'BKSY': {'rth': 35.96, 'ah_high': 36.12, 'ah_last': 36.00},
    'C': {'rth': 128.01, 'ah_high': 128.50, 'ah_last': 128.45},
    'CAT': {'rth': 904.59, 'ah_high': 913.09, 'ah_last': 910.88},
    'FCX': {'rth': 57.68, 'ah_high': 58.10, 'ah_last': 58.10},
    'FLY': {'rth': 31.52, 'ah_high': 32.04, 'ah_last': 31.22},
    'GME': {'rth': 24.23, 'ah_high': 24.27, 'ah_last': 24.12},
    'GOOGL': {'rth': 388.43, 'ah_high': 399.40, 'ah_last': 394.73},
    'INTC': {'rth': 108.15, 'ah_high': 114.59, 'ah_last': 113.35},
    'IREN': {'rth': 54.74, 'ah_last': 54.45},
    'JPM': {'rth': 309.40, 'ah_high': 310.20, 'ah_last': 309.85},
    'LLY': {'rth': 988.87, 'ah_high': 990.35, 'ah_last': 984.48},
    'LULU': {'rth': 130.21, 'ah_high': 130.70, 'ah_last': 130.45},
    'META': {'rth': 604.96, 'ah_high': 645.38, 'ah_last': 602.95},
    'MSFT': {'rth': 411.38, 'ah_high': 439.38, 'ah_last': 409.68},
    'NBIS': {'rth': 175.92, 'ah_high': 176.95, 'ah_last': 176.00},
    'NVDA': {'rth': 196.50, 'ah_high': 201.38, 'ah_last': 197.42},
    'ORCL': {'rth': 185.35, 'ah_high': 190.44, 'ah_last': 186.40},
    'PLTR': {'rth': 135.91, 'ah_high': 136.20, 'ah_last': 135.28},
    'QCOM': {'rth': 186.55, 'ah_high': 193.27, 'ah_last': 191.10},
    'QQQ': {'rth': 681.61, 'ah_high': 688.30, 'ah_last': 687.24},
    'RDDT': {'rth': 171.63, 'ah_high': 172.00, 'ah_last': 170.45},
    'SNDQ': {'rth': 10.51, 'ah_high': 10.60, 'ah_last': 9.60},
    'SPY': {'rth': 723.77, 'ah_high': 727.07, 'ah_last': 726.42},
    'TSLA': {'rth': 389.37, 'ah_high': 400.75, 'ah_last': 387.26},
    'UNH': {'rth': 363.87, 'ah_high': 374.57, 'ah_last': 362.20},
    'ZM': {'rth': 109.10, 'ah_high': 109.95, 'ah_last': 109.10},
    'SPXW': {'rth': 7245, 'ah_last': 7280},  # SPY * 10 proxy
}

# Post-earnings IV (collapsed) for tickers that reported AC tonight
POST_EARNINGS = {'AMD'}
# Tickers reporting tomorrow (Wed AC) — IV stays elevated
PRE_EARNINGS_TMW = {'ARM', 'COHR', 'IONQ', 'AXON', 'APP', 'SNAP', 'FSLY', 'MELI', 'BYND'}

BASE_IV = {
    'AMD': 0.55, 'ARM': 1.10, 'NBIS': 0.85, 'TSLA': 0.55,
    'NVDA': 0.45, 'AVGO': 0.40, 'AMZN': 0.28, 'AAPL': 0.22,
    'GOOGL': 0.28, 'META': 0.35, 'MSFT': 0.22, 'PLTR': 0.65,
    'QCOM': 0.50, 'INTC': 0.55, 'CAT': 0.28, 'JPM': 0.22,
    'C': 0.28, 'LLY': 0.28, 'LULU': 0.40, 'ORCL': 0.28,
    'GME': 1.20, 'BKSY': 0.85, 'ASTS': 0.85, 'FLY': 0.80,
    'IREN': 0.85, 'FCX': 0.38, 'UNH': 0.35, 'ZM': 0.40,
    'SNDQ': 0.65, 'RDDT': 0.55, 'QQQ': 0.18, 'SPY': 0.16,
    'SPXW': 0.18,
}


def parse_position(desc: str, sym: str):
    # e.g. "AAPL MAY 06 2026 $285 CALL"
    m = re.match(r"(\w+) (\w+) (\d+) (\d+) \$([\d.,]+) (CALL|PUT)", desc)
    if not m:
        return None
    ticker, mon, day, year, strike, right = m.groups()
    strike = float(strike.replace(',', ''))
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,
              'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    expiry = datetime(int(year), months[mon], int(day))
    return ticker, strike, right[0], expiry


def bs_price(S, K, T_years, vol, right, r=0.045):
    if T_years <= 0 or vol <= 0:
        return max(S - K, 0) if right == 'C' else max(K - S, 0)
    d1 = (log(S/K) + (r + vol*vol/2) * T_years) / (vol * sqrt(T_years))
    d2 = d1 - vol * sqrt(T_years)
    if right == 'C':
        return S * norm.cdf(d1) - K * exp(-r*T_years) * norm.cdf(d2)
    return K * exp(-r*T_years) * norm.cdf(-d2) - S * norm.cdf(-d1)


def estimate_iv(ticker, dte, moneyness):
    base = BASE_IV.get(ticker, 0.40)
    # Post-earnings: crush
    if ticker in POST_EARNINGS:
        base = base * 0.55  # significant crush
    # Pre-earnings tomorrow: elevated
    if ticker in PRE_EARNINGS_TMW:
        base = base * 1.4
    # Vol smile for OTM
    if abs(moneyness) > 0.10:
        base *= 1.20
    elif abs(moneyness) > 0.05:
        base *= 1.10
    # Short DTE pump
    if dte <= 1:
        base *= 1.30
    elif dte <= 3:
        base *= 1.15
    return base


def main():
    import csv as csvmod
    today = datetime(2026, 5, 6)  # Tomorrow (open)
    rows = []
    with open(CSV, 'r', newline='') as f:
        reader = csvmod.reader(f)
        for parts in reader:
            if len(parts) < 16: continue
            sym = parts[2].strip().lstrip('-').strip()
            desc = parts[3]
            qty = parts[4]
            last_price = parts[5]
            current_value = parts[7]
            cost_basis = parts[13]
            if not sym or sym == 'Symbol' or sym.startswith('FDRXX'):
                continue
            # Stock?
            if not desc.startswith(' ') and 'CALL' not in desc and 'PUT' not in desc:
                # IREN stock
                t = sym.strip()
                if t in AH_PRICES:
                    px = AH_PRICES[t].get('ah_last', AH_PRICES[t]['rth'])
                    rth = AH_PRICES[t]['rth']
                    qty_n = int(qty) if qty else 0
                    open_value = px * qty_n
                    cb = float(cost_basis.replace('$','').replace(',',''))
                    cur = float(current_value.replace('$','').replace(',',''))
                    rows.append({
                        'symbol': t, 'qty': qty_n, 'type': 'stock',
                        'cost_basis': cb, 'current': cur, 'est_open': open_value,
                        'profit_at_open': open_value - cb,
                        'pct_at_open': (open_value - cb) / cb * 100,
                        'pnl_change_from_close': open_value - cur,
                    })
                continue
            # Option
            parsed = parse_position(desc.strip(), sym)
            if not parsed: continue
            ticker, strike, right, expiry = parsed
            if ticker not in AH_PRICES:
                continue
            S = AH_PRICES[ticker].get('ah_last', AH_PRICES[ticker]['rth'])
            S_high = AH_PRICES[ticker].get('ah_high', S)
            qty_n = int(qty)
            cb = float(cost_basis.replace('$','').replace(',',''))
            cur = float(current_value.replace('$','').replace(',',''))
            dte = max((expiry - today).days, 0)
            T_years = dte / 365.0
            moneyness = (S - strike) / S * (1 if right == 'C' else -1)
            iv = estimate_iv(ticker, dte, moneyness)
            # Price at AH last
            est_per_contract = bs_price(S, strike, T_years, iv, right) * 100
            est_open_total = est_per_contract * qty_n
            # Price at AH high (best case)
            est_per_high = bs_price(S_high, strike, T_years, iv, right) * 100
            est_high_total = est_per_high * qty_n
            rows.append({
                'symbol': sym, 'desc_short': f"{ticker} {expiry.strftime('%m/%d')} {int(strike) if strike==int(strike) else strike}{right}",
                'qty': qty_n, 'type': 'option', 'dte': dte,
                'cost_basis': cb, 'current': cur,
                'spot_ah_last': S, 'spot_ah_high': S_high,
                'iv_est': round(iv*100, 0),
                'est_open': round(est_open_total, 0),
                'est_high': round(est_high_total, 0),
                'profit_at_open': round(est_open_total - cb, 0),
                'pct_at_open': round((est_open_total - cb) / cb * 100, 1) if cb else 0,
                'pnl_change_from_close': round(est_open_total - cur, 0),
            })

    # Print table sorted by profit_at_open descending
    rows.sort(key=lambda r: -r['profit_at_open'])
    print(f"{'symbol':<28} {'qty':<4} {'cb':<10} {'cur':<10} {'est_open':<10} "
          f"{'est_high':<10} {'chg':<10} {'profit':<11} {'pct':<8}")
    print('-' * 120)
    total_cb = total_cur = total_open = total_high = 0
    for r in rows:
        change = r['pnl_change_from_close']
        sym_display = r.get('desc_short', r['symbol'])[:27]
        est_high = r.get('est_high', r['est_open'])
        print(f"{sym_display:<28} {r['qty']:<4} "
              f"${r['cost_basis']:>7,.0f}  ${r['current']:>7,.0f}  "
              f"${r['est_open']:>8,.0f}  ${est_high:>8,.0f}  "
              f"${change:>+7,.0f}   "
              f"${r['profit_at_open']:>+8,.0f}  "
              f"{r['pct_at_open']:+.0f}%")
        total_cb += r['cost_basis']
        total_cur += r['current']
        total_open += r['est_open']
        total_high += est_high
    print('-' * 120)
    print(f"{'TOTAL':<28} {'':<4} ${total_cb:>7,.0f}  ${total_cur:>7,.0f}  "
          f"${total_open:>8,.0f}  ${total_high:>8,.0f}  "
          f"${(total_open - total_cur):+,.0f}   ${(total_open - total_cb):+,.0f}")
    print()
    print(f'Cost basis total: ${total_cb:,.0f}')
    print(f'Current value:    ${total_cur:,.0f}')
    print(f'Est at AH-last:   ${total_open:,.0f}  '
          f'(change vs close: ${total_open - total_cur:+,.0f})')
    print(f'Est at AH-high:   ${total_high:,.0f}  '
          f'(change vs close: ${total_high - total_cur:+,.0f})')
    print(f'Total profit at AH-last open: ${total_open - total_cb:+,.0f} '
          f'({(total_open - total_cb)/total_cb*100:+.0f}%)')


if __name__ == '__main__':
    main()
