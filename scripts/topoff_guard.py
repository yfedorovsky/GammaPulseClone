"""Self-healing top-off guard — run by a Windows Scheduled Task every 15 min.

The chain top-off has died repeatedly (silent kills, a process death ~26 min in,
RTH contention). Rather than trust one long-lived process, this wrapper + a
15-min scheduled trigger gives auto-resume: the fetch resumes from the ledger on
each launch, so any death is recovered within 15 min, and a full CLEAN pass
(subprocess returncode 0) writes a sentinel that makes all further ticks no-ops.

Idempotent and safe to run concurrently-but-it-won't-be: the scheduled task is
registered IgnoreNew, so a tick while a fetch is already running just exits.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = ROOT / "autoresearch" / "_artifacts" / "topoff_done.flag"
PY = ROOT / ".venv-autoresearch" / "Scripts" / "python.exe"
LOG = ROOT / "autoresearch" / "_artifacts" / "topoff_guard.log"


def log(msg: str):
    import time
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.time():.0f} {msg}\n")


def main() -> int:
    if SENTINEL.exists():
        return 0  # already complete — no-op.
    # Don't double-run if a fetch is already alive (belt; the task is IgnoreNew).
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'run_historical_replay' } | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=30)
        if (out.stdout or "").strip() not in ("0", ""):
            log("fetch already running — tick no-op")
            return 0
    except Exception:
        pass

    log("launching fetch (resume from ledger)")
    rc = subprocess.run(
        [str(PY), "scripts/run_historical_replay.py", "--fetch-only",
         "--no-rth-pause", "--start", "2026-01-02", "--end", "2026-06-16",
         "--universe", "top150"],
        cwd=str(ROOT)).returncode
    log(f"fetch exited rc={rc}")
    if rc == 0:
        SENTINEL.write_text("done", encoding="utf-8")
        log("CLEAN PASS — sentinel written, top-off complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
