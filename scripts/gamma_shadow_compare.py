"""Phase 3 shadow: real gamma (ThetaData library greeks_all) vs the production
BSM-synthesized gamma (server.thetadata.synth_gamma).

Production feeds GEX with gamma it BSM-synthesizes from first-order IV (the Standard-tier
habit that never got switched off after the June Pro upgrade). The library returns REAL
gamma directly. Before flipping the live GEX inputs, this harness answers two questions
on a real chain:

  1. Per-strike, how far does synth gamma sit from real gamma? (ratio distribution)
  2. Does the *pin* — the peak OI-weighted gamma strike, ~ the GEX king — move if we
     swap the gamma source? That's the thing that would change alerts.

Same IV + same spot feed both, so any gap is model (r/q assumptions, 0DTE T-floor,
BSM vs the vendor's engine), not a data mismatch. Read-only; no writes, no live path.

    python scripts/gamma_shadow_compare.py

Market-closed is fine: the snapshot is the last (close) chain, which is a representative
gamma profile for a source comparison. ASCII-only output.
"""
from __future__ import annotations

import datetime as _dt
import statistics as _stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.thetadata import _days_to_exp, synth_gamma  # noqa: E402

_ENV = str(ROOT / ".env")
_TICKERS = ["SPY", "QQQ"]
_N_EXPS = 2  # nearest N future expirations (0-2 DTE region is where it matters most)


def _client():
    from thetadata import ThetaClient
    return ThetaClient(dotenv_path=_ENV, dataframe_type="pandas")


def _col(df, *names):
    for n in names:
        for c in df.columns:
            if n == str(c).lower():
                return c
    for n in names:
        for c in df.columns:
            if n in str(c).lower():
                return c
    return None


def _future_exps(client, ticker, n):
    df = client.option_list_expirations(symbol=ticker)
    col = _col(df, "expiration")
    today = _dt.date.today()
    out = []
    for v in df[col].tolist():
        s = str(v)
        try:
            d = _dt.date.fromisoformat(s[:10])
        except ValueError:
            continue
        if d >= today:
            out.append(d.isoformat())
    return sorted(set(out))[:n]


def _greeks(client, ticker, exp, right):
    """Return {strike: (real_gamma, iv, spot)} for liquid rows (iv>0, gamma present)."""
    df = client.option_snapshot_greeks_all(symbol=ticker, expiration=exp, right=right)
    if df is None or len(df) == 0:
        return {}
    cs, cg = _col(df, "strike"), _col(df, "gamma")
    civ = _col(df, "implied_vol", "iv")
    cu = _col(df, "underlying_price", "underlying")
    out = {}
    for row in df.itertuples(index=False):
        d = row._asdict()
        try:
            strike = float(d[cs]); g = float(d[cg])
            iv = float(d[civ]); spot = float(d[cu])
        except (TypeError, ValueError):
            continue
        if iv <= 0 or spot <= 0:  # stale/illiquid — mirrors prod skip
            continue
        out[strike] = (g, iv, spot)
    return out


def _oi(client, ticker, exp):
    df = client.option_snapshot_open_interest(symbol=ticker, expiration=exp)
    if df is None or len(df) == 0:
        return {}
    cs, cr = _col(df, "strike"), _col(df, "right")
    coi = _col(df, "open_interest", "oi")
    out = {}
    for row in df.itertuples(index=False):
        d = row._asdict()
        try:
            out[(float(d[cs]), str(d[cr]).upper()[0])] = float(d[coi])
        except (TypeError, ValueError):
            continue
    return out


def _pin(gamma_by_strike_right, oi):
    """Peak OI-weighted total gamma strike (~ GEX king/pin). gamma_by_strike_right:
    {(strike,'C'|'P'): gamma}. Weight |gamma|*OI, sum call+put per strike."""
    tot: dict[float, float] = {}
    for (strike, r), g in gamma_by_strike_right.items():
        w = oi.get((strike, r), 0.0)
        tot[strike] = tot.get(strike, 0.0) + abs(g) * w
    if not tot:
        return None, {}
    return max(tot, key=tot.get), tot


def main():
    print("=" * 74)
    print("PHASE 3 SHADOW — real gamma (library) vs BSM-synth gamma (production)")
    print("=" * 74)
    client = _client()
    any_pin_moves = False
    for ticker in _TICKERS:
        exps = _future_exps(client, ticker, _N_EXPS)
        for exp in exps:
            dte = _days_to_exp(exp)
            calls = _greeks(client, ticker, exp, "call")
            puts = _greeks(client, ticker, exp, "put")
            oi = _oi(client, ticker, exp)
            if not calls and not puts:
                print(f"\n{ticker} {exp} (DTE {dte:.1f}): no liquid greeks rows")
                continue
            spot = next(iter(calls.values()))[2] if calls else next(iter(puts.values()))[2]

            ratios, atm_rows = [], []
            real_map, synth_map = {}, {}
            for right_word, book, rc in (("C", calls, "call"), ("P", puts, "put")):
                for strike, (rg, iv, sp) in book.items():
                    sg = synth_gamma(spot=sp, strike=strike, iv=iv,
                                     days_to_exp=dte, root=ticker)
                    real_map[(strike, right_word)] = rg
                    synth_map[(strike, right_word)] = sg
                    if rg > 0:
                        ratios.append(sg / rg)
                    if abs(strike - spot) / spot <= 0.01:  # ATM +/-1%
                        atm_rows.append((strike, right_word, rg, sg))

            real_pin, _ = _pin(real_map, oi)
            synth_pin, _ = _pin(synth_map, oi)
            moved = real_pin != synth_pin
            any_pin_moves = any_pin_moves or moved

            print(f"\n{ticker} {exp}  (DTE {dte:.1f}, spot {spot:.2f}, "
                  f"{len(calls)+len(puts)} liquid strikes)")
            if ratios:
                rs = sorted(ratios)
                print(f"  synth/real gamma ratio:  median={_stats.median(rs):.3f}  "
                      f"p10={rs[len(rs)//10]:.3f}  p90={rs[min(len(rs)-1, 9*len(rs)//10)]:.3f}  "
                      f"(1.000 = identical)")
            print("  ATM +/-1% (strike right real_gamma synth_gamma  ratio):")
            for (strike, rw, rg, sg) in sorted(atm_rows)[:8]:
                rr = f"{sg/rg:.3f}" if rg > 0 else "n/a"
                print(f"    {strike:>8.1f} {rw}   real={rg:.6f}  synth={sg:.6f}  x{rr}")
            print(f"  PIN (peak OI-weighted gamma strike):  real={real_pin}  "
                  f"synth={synth_pin}  {'>>> MOVED' if moved else 'same'}")

    print("\n" + "=" * 74)
    if any_pin_moves:
        print("RESULT: pin MOVES for >=1 chain when swapping gamma source -> real gamma")
        print("        would change GEX king/alerts. Wire it SHADOW (log both, don't flip).")
    else:
        print("RESULT: pin STABLE across all chains -> GEX structure robust to the gamma")
        print("        source. Safe to flip to real gamma (still stage it behind a flag).")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
