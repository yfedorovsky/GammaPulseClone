"""Monday morning pre-flight healthcheck.

Runs ~10 checks in ~30 seconds covering:
  - .env credentials present
  - E-Trade OAuth token cached + valid (sandbox connectivity)
  - Tradier auth working (existing strategy stack)
  - DB files exist + writable
  - Live spread tracker can construct
  - Tape regime classifier importable
  - Alert annotation pipeline importable
  - Last live activity timestamps (when did worker last write?)

Output: PASS / FAIL / WARN per check, with concrete remediation hints
if anything's amiss.

Usage:
  python scripts/monday_healthcheck.py
  python scripts/monday_healthcheck.py --account-id YOUR_KEY
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


CHECKS_PASSED = 0
CHECKS_FAILED = 0
CHECKS_WARNED = 0


def _print(level: str, name: str, msg: str) -> None:
    global CHECKS_PASSED, CHECKS_FAILED, CHECKS_WARNED
    sym = {"PASS": "[+]", "FAIL": "[X]", "WARN": "[!]", "INFO": "[ ]"}[level]
    print(f"  {sym} {name:<35} {msg}", flush=True)
    if level == "PASS":
        CHECKS_PASSED += 1
    elif level == "FAIL":
        CHECKS_FAILED += 1
    elif level == "WARN":
        CHECKS_WARNED += 1


def section(name: str) -> None:
    print(f"\n--- {name} ---", flush=True)


# ── Check 1: env credentials ─────────────────────────────────────


def check_env_credentials() -> None:
    section("Environment credentials")
    required = {
        "TRADIER_TOKEN": "Tradier (existing strategy)",
        "TELEGRAM_BOT_TOKEN": "Telegram alerts",
        "TELEGRAM_CHAT_ID": "Telegram alerts",
        "ETRADE_SANDBOX_KEY": "E-Trade paper",
        "ETRADE_SANDBOX_SECRET": "E-Trade paper",
    }
    for var, label in required.items():
        if os.getenv(var):
            _print("PASS", var, f"set ({label})")
        else:
            _print("FAIL", var, f"missing — needed for {label}")

    sandbox_flag = os.getenv("ETRADE_USE_SANDBOX", "1")
    if sandbox_flag == "1":
        _print("PASS", "ETRADE_USE_SANDBOX", "= 1 (sandbox — paper trading)")
    else:
        _print("WARN", "ETRADE_USE_SANDBOX",
               f"= {sandbox_flag} — PRODUCTION mode active!")


# ── Check 2: E-Trade OAuth + connectivity ────────────────────────


async def check_etrade(account_id_key: str | None) -> None:
    section("E-Trade integration")
    # Branch-aware: server.etrade only exists on feature/etrade-paper-execution.
    # On main, skip the entire check with a SKIP marker so it doesn't show as
    # a hard FAIL — the branch warning at the top already explains why.
    import subprocess
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        ).stdout.strip()
    except Exception:
        branch = ""
    if branch != "feature/etrade-paper-execution":
        _print("INFO", "etrade module import",
               f"skipped — not on feature/etrade-paper-execution (current: {branch or 'unknown'})")
        return

    try:
        from server.etrade import (
            ETradeClient, get_cached_token, _is_sandbox, _base_url,
        )
    except Exception as e:
        _print("FAIL", "etrade module import", f"{type(e).__name__}: {e}")
        return

    _print("PASS", "etrade module import",
           f"sandbox={_is_sandbox()} base={_base_url()}")

    token = get_cached_token()
    if token is None:
        _print("FAIL", "OAuth token cached",
               "no token — run scripts/etrade_oauth_setup.py")
        return
    age_min = int((time.time() - token.granted_at) / 60)
    _print("PASS", "OAuth token cached", f"age={age_min}min")

    # Try a lightweight call: list accounts
    try:
        client = ETradeClient(token=token)
        accts = await client.list_accounts()
        await client.close()
    except Exception as e:
        _print("FAIL", "list_accounts call",
               f"{type(e).__name__}: {str(e)[:120]} — token may be expired; "
               f"re-run scripts/etrade_oauth_setup.py")
        return
    _print("PASS", "list_accounts call",
           f"returned {len(accts)} accounts")

    if account_id_key:
        match = next((a for a in accts
                      if a.get("accountIdKey") == account_id_key), None)
        if match:
            _print("PASS", "account_id_key match",
                   f"type={match.get('accountType')} status={match.get('accountStatus')}")
        else:
            _print("FAIL", "account_id_key match",
                   f"id_key '{account_id_key}' not in account list — "
                   f"check the value")
    else:
        _print("INFO", "account_id_key match",
               "(no --account-id passed; skipping)")


# ── Check 3: Tradier connectivity ────────────────────────────────


async def check_tradier() -> None:
    section("Tradier integration (existing strategy)")
    try:
        from server.tradier import TradierClient
    except Exception as e:
        _print("FAIL", "tradier module import", f"{type(e).__name__}: {e}")
        return
    _print("PASS", "tradier module import", "ok")

    try:
        client = TradierClient()
        quotes = await client.quotes(["SPY"])
        await client.close()
    except Exception as e:
        _print("FAIL", "tradier quotes call",
               f"{type(e).__name__}: {str(e)[:120]}")
        return
    spy = quotes.get("SPY")
    if spy:
        _print("PASS", "tradier quotes call", f"SPY=${spy:.2f}")
    else:
        _print("WARN", "tradier quotes call",
               "returned empty (market may be closed)")


# ── Check 4: Spread tracker ──────────────────────────────────────


async def check_spread_tracker() -> None:
    section("Spread tracker (Tier-1 shadow gate)")
    try:
        from server.spread_tracker import SpreadTracker, get_spread_30m_mean
    except Exception as e:
        _print("FAIL", "spread_tracker import",
               f"{type(e).__name__}: {e}")
        return
    _print("PASS", "spread_tracker import", "ok")

    # Try one poll iteration
    try:
        t = SpreadTracker(["SPY", "QQQ"])
        n = await t._poll_once()
        _print("PASS", "spread_tracker poll",
               f"added {n} samples in one cycle")
    except Exception as e:
        _print("WARN", "spread_tracker poll",
               f"{type(e).__name__}: {str(e)[:120]}")


# ── Check 5: Tape regime classifier ──────────────────────────────


def check_tape_regime() -> None:
    section("Tape regime classifier")
    try:
        from server.tape_regime import (
            classify_tape_regime, classify_from_yfinance, regime_play_guidance,
        )
    except Exception as e:
        _print("FAIL", "tape_regime import", f"{type(e).__name__}: {e}")
        return
    _print("PASS", "tape_regime import", "ok")

    # Test with synthetic bars
    bars = [{"ts": i*60 + 1000000, "open": 720, "high": 720.1,
             "low": 719.9, "close": 720} for i in range(60)]
    try:
        r = classify_tape_regime(bars, 1000000 + 60*60)
        _print("PASS", "tape_regime classify",
               f"synthetic test -> {r.regime}")
    except Exception as e:
        _print("FAIL", "tape_regime classify",
               f"{type(e).__name__}: {e}")


# ── Check 6: Alert annotation pipeline ───────────────────────────


def check_annotation_pipeline() -> None:
    section("Alert annotation pipeline")
    try:
        from server.alert_annotations import (
            annotate_alert, apply_migrations, macro_event_at,
        )
    except Exception as e:
        _print("FAIL", "alert_annotations import",
               f"{type(e).__name__}: {e}")
        return
    _print("PASS", "alert_annotations import", "ok")

    # Verify migrations apply cleanly
    try:
        n = apply_migrations()
        _print("PASS", "alert_annotations migrations",
               f"applied {n} new columns (others already exist)")
    except Exception as e:
        _print("FAIL", "alert_annotations migrations",
               f"{type(e).__name__}: {e}")


# ── Check 7: ST near-fire annotation ─────────────────────────────


def check_st_near_fire() -> None:
    section("ST near-fire annotation")
    try:
        from server.st_near_fire import (
            apply_migrations, compute_near_fire_features,
            SLOW_GATES, FAST_GATES,
        )
    except Exception as e:
        _print("FAIL", "st_near_fire import", f"{type(e).__name__}: {e}")
        return
    _print("PASS", "st_near_fire import",
           f"slow={SLOW_GATES} fast={FAST_GATES}")

    try:
        n = apply_migrations()
        _print("PASS", "st_near_fire migrations",
               f"applied {n} new columns (others already exist)")
    except Exception as e:
        _print("FAIL", "st_near_fire migrations",
               f"{type(e).__name__}: {e}")


# ── Check 8: paper_executions DB ─────────────────────────────────


def check_paper_executions() -> None:
    section("paper_executions DB (E-Trade tracking)")
    try:
        from server import paper_executions as pe
    except Exception as e:
        _print("FAIL", "paper_executions import",
               f"{type(e).__name__}: {e}")
        return
    _print("PASS", "paper_executions import", "ok")

    try:
        pe.init_db()
        _print("PASS", "paper_executions schema",
               f"DB at {Path(pe.PAPER_EXECUTIONS_DB).name}")
    except Exception as e:
        _print("FAIL", "paper_executions schema",
               f"{type(e).__name__}: {e}")
        return

    # Show today's count
    today = pe.get_today()
    _print("INFO", "paper_executions today",
           f"{len(today)} rows so far today")


# ── Check 9: Production DB freshness ─────────────────────────────


def check_db_freshness() -> None:
    section("Production DB freshness (last writes)")
    # flow_alerts lives INSIDE snapshots.db (see server/flow_alerts.py using
    # settings.snapshot_db) — a standalone flow_alerts.db file in the repo
    # is a 0-byte phantom from an old auto-create. Use ::table syntax to
    # check a non-default table inside a shared DB.
    dbs = {
        "snapshots.db": "snapshots",
        "structural_turns.db": "structural_turns",
        "zero_dte_alerts.db": "zero_dte_alerts",
        "snapshots.db::flow_alerts": "flow_alerts",
    }
    for db_file, table in dbs.items():
        # Allow "<file>::<override_table>" so multiple tables in one DB can
        # be freshness-checked independently. Falls back to the {file: table}
        # mapping for the simple case.
        if "::" in db_file:
            file_part, _ = db_file.split("::", 1)
            path = ROOT / file_part
            label = f"{file_part}::{table}"
        else:
            path = ROOT / db_file
            label = db_file
        if not path.exists():
            _print("WARN", label, "not present")
            continue
        try:
            conn = sqlite3.connect(str(path))
            try:
                # Find a timestamp column in that table
                cur = conn.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                ts_col = next((c for c in ("ts", "fired_at", "created_at", "ts_event")
                               if c in cols), None)
                if ts_col is None:
                    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    n = cur.fetchone()[0]
                    _print("INFO", label, f"{n} rows (no timestamp col)")
                    continue
                cur = conn.execute(f"SELECT MAX({ts_col}), COUNT(*) FROM {table}")
                row = cur.fetchone()
                max_ts = row[0] or 0
                count = row[1] or 0
                if max_ts > 0:
                    last_dt = datetime.fromtimestamp(int(max_ts))
                    age_hr = (datetime.now() - last_dt).total_seconds() / 3600
                    age_str = (f"{age_hr:.1f}h ago" if age_hr < 72
                               else f"{age_hr/24:.0f}d ago")
                    if age_hr > 72:
                        _print("WARN", label,
                               f"last write: {last_dt.strftime('%m-%d %H:%M')} "
                               f"({age_str}, {count} rows)")
                    else:
                        _print("PASS", label,
                               f"last write: {last_dt.strftime('%m-%d %H:%M')} "
                               f"({age_str}, {count} rows)")
                else:
                    _print("WARN", label, f"{count} rows but no max ts")
            finally:
                conn.close()
        except Exception as e:
            _print("WARN", label, f"{type(e).__name__}: {str(e)[:80]}")


# ── Check 10: Branch + git status ────────────────────────────────


def check_git_branch() -> None:
    section("Git branch")
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        branch = result.stdout.strip()
        if branch == "feature/etrade-paper-execution":
            _print("PASS", "current branch",
                   f"{branch} (E-Trade executor available)")
        elif branch == "main":
            _print("WARN", "current branch",
                   f"{branch} — E-Trade executor NOT available; "
                   "switch to feature/etrade-paper-execution if you want paper exec")
        else:
            _print("INFO", "current branch", branch)
    except Exception as e:
        _print("WARN", "current branch", f"{type(e).__name__}: {e}")


# ── Main ─────────────────────────────────────────────────────────


async def main_async(account_id_key: str | None) -> int:
    print("=" * 70)
    print("  GammaPulse Monday Pre-flight Healthcheck")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (local)")
    print("=" * 70)

    check_git_branch()
    check_env_credentials()
    await check_etrade(account_id_key)
    await check_tradier()
    await check_spread_tracker()
    check_tape_regime()
    check_annotation_pipeline()
    check_st_near_fire()
    check_paper_executions()
    check_db_freshness()

    print()
    print("=" * 70)
    total = CHECKS_PASSED + CHECKS_FAILED + CHECKS_WARNED
    print(f"  RESULT: {CHECKS_PASSED} pass, {CHECKS_FAILED} fail, "
          f"{CHECKS_WARNED} warn  (of {total})")
    if CHECKS_FAILED == 0:
        print("  STATUS: ready to launch live worker + E-Trade executor")
    else:
        print(f"  STATUS: {CHECKS_FAILED} blocker(s) — fix before launching")
    print("=" * 70)
    return 1 if CHECKS_FAILED > 0 else 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--account-id", default=None,
                   help="E-Trade account_id_key (verifies it exists)")
    args = p.parse_args()
    return asyncio.run(main_async(args.account_id))


if __name__ == "__main__":
    sys.exit(main())
