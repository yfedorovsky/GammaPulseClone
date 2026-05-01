"""Master runner — chains all five Databento-data audits in dependency order.

Order:
  0. (precondition) databento cache must be built; checks status first
  1. gate8_audit.py             — Lee-Ready vs tick-rule Gate 8 audit
  2. microstructure_profile_audit.py
                                — fires vs same-day random-minute baseline
  3. ofi_predictive_power.py    — Cont 2014 replication on raw tape
  4. day_regime_audit.py        — VIX1D quartile vs microstructure
  5. background_distributions.py
                                — percentile thresholds for v2 gates

Each script writes its own outputs to docs/research/. This master script
runs them sequentially with timing + status. If any script fails, it
logs the failure and continues to the next (no hard stops — we want all
the data we can get).

Run:
  python scripts/run_databento_audit_chain.py
  python scripts/run_databento_audit_chain.py --skip gate8 --skip ofi
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPTS = [
    ("gate8",          "gate8_audit.py"),
    ("microstructure", "microstructure_profile_audit.py"),
    ("ofi",            "ofi_predictive_power.py"),
    ("day_regime",     "day_regime_audit.py"),
    ("background",     "background_distributions.py"),
]


def run_one(name: str, script: str, env: dict | None = None) -> dict:
    path = ROOT / "scripts" / script
    if not path.exists():
        return {"name": name, "status": "missing", "duration_s": 0,
                "exit_code": -1}
    print(f"\n{'='*70}\n[{name}] running {script}\n{'='*70}", flush=True)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ROOT), env=env, check=False,
            stdout=sys.stdout, stderr=sys.stderr,
        )
        exit_code = result.returncode
        status = "ok" if exit_code == 0 else "failed"
    except Exception as e:
        exit_code = -2
        status = f"error: {e}"
    dur = time.time() - t0
    print(f"\n[{name}] {status} in {dur:.1f}s (exit={exit_code})", flush=True)
    return {"name": name, "status": status, "duration_s": dur,
            "exit_code": exit_code}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", action="append", default=[],
                    help="Audit names to skip (e.g., --skip ofi)")
    ap.add_argument("--only", action="append", default=[],
                    help="If set, run ONLY these audits")
    args = ap.parse_args()

    # Verify cache is built
    print("Checking Databento cache status...", flush=True)
    cache_check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "databento_loader.py"),
         "--status"],
        cwd=str(ROOT), check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    if "cache is empty" in cache_check.stdout.lower():
        print("Cache is empty. Run `python scripts/databento_loader.py "
              "--build-cache` first.")
        return 1
    print(cache_check.stdout, flush=True)

    # Set unbuffered stdout for child processes
    import os
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # Filter scripts per --skip / --only
    to_run = SCRIPTS
    if args.only:
        to_run = [(n, s) for (n, s) in SCRIPTS if n in args.only]
    else:
        to_run = [(n, s) for (n, s) in SCRIPTS if n not in args.skip]

    print(f"\nWill run {len(to_run)} audits: {[n for n, _ in to_run]}\n",
          flush=True)

    results = []
    chain_t0 = time.time()
    for name, script in to_run:
        results.append(run_one(name, script, env=env))

    chain_dur = time.time() - chain_t0
    print(f"\n{'='*70}\nCHAIN COMPLETE in {chain_dur:.1f}s "
          f"({chain_dur/60:.1f}min)\n{'='*70}")
    print(f"\n{'name':<20} {'status':<12} {'duration':>10} {'exit':>6}")
    for r in results:
        print(f"{r['name']:<20} {r['status']:<12} {r['duration_s']:>9.1f}s "
              f"{r['exit_code']:>6}")

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_total = len(results)
    print(f"\n{n_ok}/{n_total} audits succeeded")
    print("\nReports written to docs/research/:")
    print("  gate8_audit.md")
    print("  microstructure_profile_audit.md")
    print("  ofi_predictive_power.md")
    print("  day_regime_audit.md")
    print("  background_distributions.md")
    return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
