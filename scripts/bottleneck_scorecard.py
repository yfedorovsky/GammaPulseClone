"""AI-semiconductor bottleneck scorecard — a CONTEXT overlay, not an alert trigger.

Operationalizes the June-20 bottleneck synthesis (docs/research/june20_semis/) as a
structured, filterable map of the US-OPTIONABLE supply-chain names onto the bottleneck
layer each one expresses. This is a fundamental-conviction CONTEXT layer; it is NOT
wired into live alert dispatch (structure detects context, it does not predict — and
the source research is a structurally long-biased corpus from disclosed holders).

What it gives you:
  * the binding-constraint rotation tracker (which layer is the current rate-limiter)
  * each name's layer, conviction, risk, validation phase, near-term catalyst, and the
    single validation signal to watch (Serenity Phase 1->2->3 framework)
  * a coverage cross-check: confirms every name is already in the live scan universe
    (server.tickers) and prints its scan tier — flags any gap to add manually

Run:
  python scripts/bottleneck_scorecard.py                 # full table
  python scripts/bottleneck_scorecard.py --binding       # only current binding-constraint layers
  python scripts/bottleneck_scorecard.py --layer POWER   # one layer
  python scripts/bottleneck_scorecard.py --min-conviction 4
  python scripts/bottleneck_scorecard.py --needs-validation  # Phase 1-2 (asymmetric, pre-consensus)
  python scripts/bottleneck_scorecard.py --json

NOT investment advice. Conviction/phase are analytical reads of the June-20 research,
not recommendations. Verify independently.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Windows cp1252 consoles choke on non-ASCII; force UTF-8 stdout (mirrors run_all_tests.py).
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Binding-constraint rotation tracker (the "which layer is the rate-limiter now")
# Update this call quarterly as the binding constraint rotates.
# ─────────────────────────────────────────────────────────────────────────────
AS_OF = "2026-06-20"
BINDING_CONSTRAINT = {
    # layer: (what it gates, confidence)
    "POWER":     ("binding on NET-NEW greenfield capacity (2,600GW queue, 5-12yr waits, 128wk transformers)", "Very High"),
    "PACKAGING": ("binding on DEPLOYED capacity (CoWoS 95k->130k wafers/mo still short of demand)", "High"),
    "MEMORY":    ("binding on COMPONENTS (HBM sold out '23+, DRAM undersupply 4.9% '26) — but most priced", "Very High"),
    "PASSIVES":  ("tightening into 2H26 (Rubin ~12k MLCC/unit, AI-grade +50-60%, lead times 4-6mo)", "High"),
}
# Layers NOT currently the top rate-limiter (still real, later-dated):
NON_BINDING = {"PHOTONICS", "COMPUTE", "FOUNDRY", "DEMAND"}

# ─────────────────────────────────────────────────────────────────────────────
# The bottleneck universe (US-OPTIONABLE only). conviction 1-5 (5=highest),
# risk = realized-vol / speculation, phase = Serenity validation 1(pre-inst)
# / 2(first validation) / 3(consensus, reduced asymmetry).
# ─────────────────────────────────────────────────────────────────────────────
def _n(ticker, layer, role, conviction, risk, phase, catalyst, watch):
    return dict(ticker=ticker, layer=layer, role=role, conviction=conviction,
                risk=risk, phase=phase, catalyst=catalyst, watch=watch)

UNIVERSE = [
    # MEMORY — only US-liquid pure memory is MU (Samsung/SK Hynix foreign)
    _n("MU", "MEMORY", "pure", 4, "MED", 3, "FQ3 earnings (~late Jun '26)",
       "2027 allocation guidance + HBM4 ramp rate; beware IV-crush/sell-the-news"),

    # ASIC — the cleanest fundamental->liquid-options toll road (Broadcom+Marvell ~95% co-design)
    _n("AVGO", "ASIC", "pure-leader", 5, "MED", 3, "Q3 earnings — XPU/ASIC rev cadence",
       "hyperscaler XPU bookings; ASIC rev growth sustaining"),
    _n("MRVL", "ASIC", "pure-#2", 4, "HIGH", 3, "Q earnings; AVGO-correlated",
       "custom-ASIC design-win retention vs Broadcom; Serenity core"),

    # COMPUTE — demand driver / system-level stress test
    _n("NVDA", "COMPUTE", "demand-driver", 4, "MED", 3, "Rubin H2'26 first shipments",
       "Rubin ship cadence stress-tests CoWoS+HBM4+MLCC at once"),
    _n("AMD", "COMPUTE", "secondary", 3, "MED", 3, "MI450 ramp",
       "MI450 platform traction; MLCC-count spec confirmation"),
    _n("INTC", "COMPUTE", "foundry/cpu", 2, "HIGH", 2, "18A yield progress (~50%)",
       "18A commercialization; Apple production ramp"),
    _n("ARM", "COMPUTE", "cpu-ecosystem", 3, "MED", 3, "agentic-AI CPU demand",
       "CPU-renaissance attach ($223B TAM, Bernstein)"),

    # PACKAGING — TSM the liquid proxy; pure beneficiaries (Ibiden/Ajinomoto) foreign
    _n("TSM", "PACKAGING", "proxy-leader", 4, "MED", 3, "Q2/Q3 — CoWoS util + CoPoS pilot",
       "CoWoS utilization; glass-core validation; CoPoS yield data"),

    # FOUNDRY / EQUIPMENT
    _n("ASML", "FOUNDRY", "equip", 3, "MED", 3, "litho bookings", "AI-tied tool orders"),
    _n("AMAT", "FOUNDRY", "equip", 3, "MED", 3, "packaging/dep tool orders", "advanced-packaging capex"),
    _n("LRCX", "FOUNDRY", "equip", 3, "MED", 3, "etch/HBM tool orders", "HBM/DRAM capex intensity"),
    _n("KLAC", "FOUNDRY", "equip", 3, "MED", 3, "process-control orders", "advanced-node + packaging inspection"),
    _n("AEHR", "FOUNDRY", "equip-inflection", 2, "HIGH", 2, "HVM order announcements",
       "test/burn-in inflection (Serenity); thin, catalyst-binary"),

    # PASSIVES — NO clean US-optionable pure-play (Murata/Yageo/SEMCO/Taiyo foreign).
    # Track as leading indicator via lead-times; expressed only indirectly in US options.
    # (Intentionally no US ticker row — see playbook §2 monitor.)

    # PHOTONICS / CPO — Serenity's asymmetric, later-dated chokepoints
    _n("COHR", "PHOTONICS", "ecosystem", 3, "HIGH", 3, "OFC/CPO demos; earnings",
       "CPO/InP-laser integration traction (200G/lane shown OFC'26)"),
    _n("LITE", "PHOTONICS", "ecosystem", 3, "HIGH", 3, "transceiver/CPO mix",
       "datacom transceiver + CPO ramp (Lumentum)"),
    _n("CIEN", "PHOTONICS", "networking", 3, "MED", 3, "datacenter-interconnect orders",
       "DCI / coherent optics demand"),
    _n("GLW", "PHOTONICS", "proxy-fiber", 3, "MED", 3, "optical-fiber demand",
       "datacenter fiber pull-through (Corning)"),
    _n("AXTI", "PHOTONICS", "pure-chokepoint", 2, "HIGH", 2, "earnings / institutional buying",
       "InP 'Strait of Hormuz'; 15-25% daily swings — accumulate on validation only"),
    _n("AAOI", "PHOTONICS", "pure-transceiver", 2, "HIGH", 2, "earnings (10x rev ramp thesis H2'27)",
       "transceiver-chain volume; 2027-weighted, contrarian"),
    _n("POET", "PHOTONICS", "spec", 1, "HIGH", 1, "partnership/design-win",
       "photonic-integration design wins; pre-consensus"),

    # POWER / GRID / COOLING / NUCLEAR — corpus's biggest blind spot; longest runway
    _n("VRT", "POWER", "cooling-leader", 4, "MED", 3, "earnings; liquid-cooling attach",
       "liquid cooling standard in AI racks '27-28 (most liquid power proxy)"),
    _n("CEG", "POWER", "nuclear", 4, "MED", 3, "FERC large-load rule (Jun'26); PPAs",
       "nuclear PPA / private-grid bypass deals; FERC 180-day rule"),
    _n("VST", "POWER", "nuclear", 4, "MED", 3, "FERC rule; capacity auctions",
       "data-center PPAs; FERC interconnection reform"),

    # DEMAND — hyperscaler capex source (context, not a bottleneck edge itself)
    _n("MSFT", "DEMAND", "hyperscaler", 3, "LOW", 3, "Q capex commentary", "AI capex direction + power access"),
    _n("GOOGL", "DEMAND", "hyperscaler", 3, "LOW", 3, "TPU / capex", "TPU ASIC volume; InP diversification lead"),
    _n("AMZN", "DEMAND", "hyperscaler", 3, "LOW", 3, "Trainium / capex", "Trainium ramp; external-chip plans"),
    _n("META", "DEMAND", "hyperscaler", 3, "LOW", 3, "MTIA / capex", "MTIA ASIC; capex guidance"),
]

LAYER_ORDER = ["POWER", "PACKAGING", "MEMORY", "PASSIVES", "ASIC", "COMPUTE", "PHOTONICS", "FOUNDRY", "DEMAND"]

# Phase 1-2 = the asymmetric, pre-consensus set (best risk-adjusted entry is the
# Phase 1->2 transition). Used by scripts/bottleneck_phase_watch.py (framework #4).
PHASE_WATCH_MAX = 2
_BY_TICKER = {r["ticker"]: r for r in UNIVERSE}


def context_for(ticker: str) -> dict | None:
    """Return the bottleneck-context record for a ticker, or None if not in the
    US-optionable bottleneck universe. The importable hook for framework #4 and any
    future CONTEXT-only alert annotation (never a trigger)."""
    if not ticker:
        return None
    return _BY_TICKER.get(ticker.upper())


def universe_tickers() -> list[str]:
    return [r["ticker"] for r in UNIVERSE]


def _load_universe_membership():
    """Return (all_set, tier_fn) from server.tickers, or (None, None) if unavailable."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from server import tickers as T
        return set(T.all_tickers()), T.tier_of
    except Exception as e:
        print(f"[scorecard] could not import server.tickers ({e!r}); skipping coverage check\n")
        return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description="AI-semi bottleneck scorecard (context overlay)")
    ap.add_argument("--binding", action="store_true", help="only the current binding-constraint layers")
    ap.add_argument("--layer", type=str, default=None, help="filter to one layer (e.g. POWER, PHOTONICS)")
    ap.add_argument("--min-conviction", type=int, default=0, help="minimum conviction 1-5")
    ap.add_argument("--needs-validation", action="store_true", help="only Phase 1-2 (pre-consensus / asymmetric)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    rows = list(UNIVERSE)
    if args.binding:
        rows = [r for r in rows if r["layer"] in BINDING_CONSTRAINT]
    if args.layer:
        rows = [r for r in rows if r["layer"] == args.layer.upper()]
    if args.min_conviction:
        rows = [r for r in rows if r["conviction"] >= args.min_conviction]
    if args.needs_validation:
        rows = [r for r in rows if r["phase"] <= 2]

    rows.sort(key=lambda r: (LAYER_ORDER.index(r["layer"]) if r["layer"] in LAYER_ORDER else 99,
                             -r["conviction"]))

    if args.json:
        print(json.dumps({"as_of": AS_OF, "binding_constraint": BINDING_CONSTRAINT, "rows": rows}, indent=2))
        return 0

    all_set, tier_of = _load_universe_membership()

    print(f"AI-SEMI BOTTLENECK SCORECARD - as of {AS_OF}  (CONTEXT overlay, NOT an alert trigger; NIA)")
    print("=" * 100)
    print("BINDING CONSTRAINT NOW (the current rate-limiters):")
    for layer in ["POWER", "PACKAGING", "MEMORY", "PASSIVES"]:
        what, conf = BINDING_CONSTRAINT[layer]
        print(f"  - {layer:10s} [{conf:9s}] {what}")
    print("  NOTE: PASSIVES has NO clean US-optionable pure-play - track via MLCC lead-times (playbook sec.2).")
    print("=" * 100)

    hdr = f"{'TICK':6s} {'LAYER':10s} {'ROLE':16s} {'CONV':4s} {'RISK':4s} {'PH':2s} {'SCAN':4s}  CATALYST / WATCH-FOR"
    print(hdr)
    print("-" * 100)
    gaps = []
    cur = None
    for r in rows:
        if r["layer"] != cur:
            cur = r["layer"]
        scan = ""
        if all_set is not None:
            if r["ticker"] in all_set:
                scan = f"T{tier_of(r['ticker'])}"
            else:
                scan = "GAP"
                gaps.append(r["ticker"])
        conv = "*" * r["conviction"]
        print(f"{r['ticker']:6s} {r['layer']:10s} {r['role']:16s} {conv:5s} {r['risk']:4s} "
              f"P{r['phase']} {scan:4s}  {r['catalyst']}")
        print(f"{'':51s}      > {r['watch']}")

    print("-" * 100)
    if all_set is not None:
        if gaps:
            print(f"COVERAGE GAPS (not in live scan universe — add manually if wanted): {', '.join(gaps)}")
        else:
            print("COVERAGE: all scorecard names are already in the live scan universe (server.tickers). "
                  "No universe expansion needed.")
    print("\nLegend: CONV *=1..5 (analytical conviction)  RISK=vol/speculation  "
          "PH=Serenity validation phase (1 pre-inst -> 3 consensus)  SCAN=live scan tier")
    print("Asymmetric/pre-consensus (Phase 1-2): run with --needs-validation. NIA — DYODD.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
