"""Set the current lotto premium-at-risk for the Mir TP exposure monitor (Phase 2a).

  python scripts/set_lotto_exposure.py 18500
  python scripts/set_lotto_exposure.py 18500 --capital 150000 --note "5 names, AI basket"
  python scripts/set_lotto_exposure.py --show

  # Per-position (enables the per-theme concentration sub-cap; total auto-sums):
  python scripts/set_lotto_exposure.py --capital 150000 \
      --position MU:9000 --position AVGO:6000 --position VRT:4000

The monitor compares this to today's regime-scaled cap (risk-on 12 / chop 6 /
downtrend 3 %) and flags if you're over. Update it once a day or when your open
lotto book changes meaningfully — a stale figure gets flagged in the alert.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.lotto_exposure import get_exposure, set_exposure, staleness_hours, age_str


def _parse_positions(items):
    """['MU:9000', 'AVGO:6000'] -> [{'ticker':'MU','premium':9000.0}, ...]"""
    out = []
    for it in items or []:
        if ":" not in it:
            raise SystemExit(f"bad --position '{it}' (use TICKER:PREMIUM, e.g. MU:9000)")
        tk, prem = it.rsplit(":", 1)
        out.append({"ticker": tk.strip().upper(), "premium": float(prem.replace(",", "").replace("$", ""))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("premium", nargs="?", type=float,
                    help="total concurrent lotto premium-at-risk, in $ (optional if --position given)")
    ap.add_argument("--capital", type=float, default=None, help="capital base, $ (to show as percent)")
    ap.add_argument("--note", default="", help="optional note")
    ap.add_argument("--position", action="append", default=[], metavar="TICKER:PREM",
                    help="per-name premium (repeatable) — enables the per-theme sub-cap")
    ap.add_argument("--show", action="store_true", help="show current state and exit")
    a = ap.parse_args()

    positions = _parse_positions(a.position)

    if a.show or (a.premium is None and not positions):
        st = get_exposure()
        if not st:
            print("lotto exposure: NOT SET  (run: python scripts/set_lotto_exposure.py <premium> [--capital N])")
            return
        cap = st.get("capital")
        pct = f" = {st['premium_at_risk'] / cap * 100:.1f}% of ${cap:,.0f}" if cap else ""
        npos = len(st.get("positions") or [])
        pos_str = f"  [{npos} positions → theme sub-cap on]" if npos else ""
        print(f"lotto exposure: ${st['premium_at_risk']:,.0f}{pct}  "
              f"({age_str(staleness_hours(st))})"
              f"{('  note: ' + st['note']) if st['note'] else ''}{pos_str}")
        return

    d = set_exposure(a.premium, a.capital, a.note, positions=positions or None)
    cap = d.get("capital")
    pct = f" = {d['premium_at_risk'] / cap * 100:.1f}% of ${cap:,.0f}" if cap else ""
    pos_str = f"  [{len(d.get('positions') or [])} positions]" if d.get("positions") else ""
    print(f"set lotto exposure: ${d['premium_at_risk']:,.0f}{pct}"
          f"{('  note: ' + d['note']) if d['note'] else ''}{pos_str}")


if __name__ == "__main__":
    main()
