"""Set the current lotto premium-at-risk for the Mir TP exposure monitor (Phase 2a).

  python scripts/set_lotto_exposure.py 18500
  python scripts/set_lotto_exposure.py 18500 --capital 150000 --note "5 names, AI basket"
  python scripts/set_lotto_exposure.py --show

The monitor compares this to today's regime-scaled cap (risk-on 12 / chop 6 /
downtrend 3 %) and flags if you're over. Update it once a day or when your open
lotto book changes meaningfully — a stale figure gets flagged in the alert.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.lotto_exposure import get_exposure, set_exposure, staleness_hours, age_str


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("premium", nargs="?", type=float,
                    help="total concurrent lotto premium-at-risk, in $")
    ap.add_argument("--capital", type=float, default=None, help="capital base, $ (to show as percent)")
    ap.add_argument("--note", default="", help="optional note")
    ap.add_argument("--show", action="store_true", help="show current state and exit")
    a = ap.parse_args()

    if a.show or a.premium is None:
        st = get_exposure()
        if not st:
            print("lotto exposure: NOT SET  (run: python scripts/set_lotto_exposure.py <premium> [--capital N])")
            return
        cap = st.get("capital")
        pct = f" = {st['premium_at_risk'] / cap * 100:.1f}% of ${cap:,.0f}" if cap else ""
        print(f"lotto exposure: ${st['premium_at_risk']:,.0f}{pct}  "
              f"({age_str(staleness_hours(st))})"
              f"{('  note: ' + st['note']) if st['note'] else ''}")
        return

    d = set_exposure(a.premium, a.capital, a.note)
    cap = d.get("capital")
    pct = f" = {d['premium_at_risk'] / cap * 100:.1f}% of ${cap:,.0f}" if cap else ""
    print(f"set lotto exposure: ${d['premium_at_risk']:,.0f}{pct}"
          f"{('  note: ' + d['note']) if d['note'] else ''}")


if __name__ == "__main__":
    main()
