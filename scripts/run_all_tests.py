"""Master test runner — runs every test_*.py in scripts/.

Adds a summary line so CI / pre-restart checks can grep one number.

Usage:
    python scripts/run_all_tests.py
    # Exit code: 0 if all pass, 1 if any fail
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Force UTF-8 on Windows so emoji in child stdout doesn't crash the
# parent's cp1252 console. Without this, test_side_detection_p0.py
# (which prints 🟢/🔴 in its assertions) crashes the runner with
# UnicodeEncodeError. Set BEFORE any print() in this script.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    test_files = sorted(scripts_dir.glob("test_*.py"))
    if not test_files:
        print("No test_*.py files found.")
        return 0

    print("=" * 70)
    print(f"RUNNING ALL TESTS — {len(test_files)} files")
    print("=" * 70)
    print()

    results = []
    for tf in test_files:
        print(f"  >>> {tf.name}")
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(tf)],
            capture_output=True, text=True, encoding="utf-8",
        )
        # Indent the captured stdout so each test file's results group
        indented = "\n".join(f"      {ln}" for ln in proc.stdout.splitlines())
        print(indented)
        if proc.stderr.strip():
            print("      [stderr]")
            print("\n".join(f"      {ln}" for ln in proc.stderr.splitlines()))
        results.append((tf.name, proc.returncode))
        print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    n_pass = sum(1 for _, rc in results if rc == 0)
    n_fail = sum(1 for _, rc in results if rc != 0)
    for name, rc in results:
        status = "PASS" if rc == 0 else "FAIL"
        print(f"  [{status}] {name}")
    print()
    print(f"OVERALL: {n_pass}/{len(results)} suites passed, {n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
