"""External backend watchdog (task #91).

WHY THIS EXISTS
---------------
The whole GammaPulse backend is ONE uvicorn process (`server.main:app`) running
~20 asyncio tasks; flow_alerts rows land in snapshots.db every ~30s during RTH.
There is no supervisor — the process is started by hand (start_gammapulse.bat,
optionally wired to Task Scheduler). On **2026-06-17** (a normal NYSE Wednesday)
the operator simply did not re-launch it after the prior session, and the system
sat producing ZERO flow_alerts all day with no crash and no alert. (2026-06-13 was
a benign Saturday.) The in-process server/snapshot_watchdog.py cannot catch this:
it lives *inside* the process it would need to watch.

This script is the EXTERNAL watcher. It is deliberately dependency-light and does
NOT import the heavy server package at its core (the failure it guards against can
itself be "the server package won't import"), so it keeps working when the backend
is broken. It reads the live DB read-only, checks the process is up, and posts an
infra alarm to Telegram DIRECTLY — bypassing send() and every category gate, so a
WATCHDOG alert can never be rate-limited or demoted.

WHAT IT CHECKS each cycle (only during RTH on real trading days; weekends/holidays
are skipped via the market calendar so 6/13-Sat and 6/19-Juneteenth zeros are not
treated as failures):
  1. PROCESS UP   — TCP 8000 listening. Down for FAIL_CONFIRM cycles -> "PROCESS DOWN"
                    (the 6/17 mode). With --auto-restart, relaunches start_gammapulse.bat.
  2. FLOW SILENT  — process up but <FLOW_FLOOR flow_alerts rows in the last 5 min
                    during RTH for FAIL_CONFIRM cycles -> "FLOW SILENT" (scanner stalled).
                    Alert-only (no auto-restart — a silent-but-up backend still serves
                    the UI; a mid-session restart is disruptive, so it's the operator's call).
A SNAPSHOT-age diagnostic is attached so you can tell "whole worker dead" from
"only the flow scanner dead".

DEPLOYMENT (recommended): Windows Task Scheduler, separate task from the backend
(so it outlives a crashed backend), every 2 min, "run whether user is logged on or
not", action:
    C:\\Dev\\GammaPulse\\.venv\\Scripts\\python.exe C:\\Dev\\GammaPulse\\scripts\\backend_watchdog.py --once
Or run a single long-lived watcher window:
    python scripts/backend_watchdog.py --loop
Add --auto-restart to opt into relaunch-on-process-down. State (arm/cooldown/streak)
persists to logs/watchdog_state.json so --once invocations share a failure streak.

Read-only on all DBs. Never runs the gc_* mutators (they require a STOPPED backend
and race the writer). NEVER mutates anything except its own state + log files.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

# ─────────────────────────────────────────────────────────────────────────────
# Paths / config
# ─────────────────────────────────────────────────────────────────────────────

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO, "snapshots.db")
STATE_PATH = os.path.join(REPO, "logs", "watchdog_state.json")
START_BAT = os.path.join(REPO, "start_gammapulse.bat")

BACKEND_PORT = 8000
CHECK_INTERVAL_S = 120          # --loop poll cadence / expected --once cadence
FAIL_CONFIRM = 2                # consecutive failing cycles before alarming
FLOW_FLOOR = 10                 # <this many flow_alerts in 5min during RTH = silent (healthy ~390)
FLOW_WINDOW_S = 300             # "recent" flow window (5 min)
STARTUP_GRACE_MIN = 5           # don't evaluate in the first N min after 09:30 (open auction)
ALARM_COOLDOWN_S = 1800         # 30 min between repeat alarms of the same type
RESTART_COOLDOWN_S = 600        # 10 min between auto-restart attempts
SNAPSHOT_STALE_S = 600          # worker-liveness diagnostic threshold


# ─────────────────────────────────────────────────────────────────────────────
# Market calendar — load the canonical module by file path (no server/__init__
# import, so it works even if the server package is broken). Inline fallback if
# even that fails, so the watchdog never dies on a calendar import.
# ─────────────────────────────────────────────────────────────────────────────

def _load_market_calendar():
    try:
        path = os.path.join(REPO, "server", "market_calendar.py")
        spec = importlib.util.spec_from_file_location("gp_market_calendar", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception as e:
        print(f"[watchdog] market_calendar load failed ({e!r}); using inline fallback", flush=True)
        return None


_MC = _load_market_calendar()

# Minimal inline fallback holiday set (mirror of server/market_calendar.py, 2026-27).
_FALLBACK_HOLIDAYS = {
    _dt.date(2026, 1, 1), _dt.date(2026, 1, 19), _dt.date(2026, 2, 16),
    _dt.date(2026, 4, 3), _dt.date(2026, 5, 25), _dt.date(2026, 6, 19),
    _dt.date(2026, 7, 3), _dt.date(2026, 9, 7), _dt.date(2026, 11, 26),
    _dt.date(2026, 12, 25),
    _dt.date(2027, 1, 1), _dt.date(2027, 1, 18), _dt.date(2027, 2, 15),
    _dt.date(2027, 3, 26), _dt.date(2027, 5, 31), _dt.date(2027, 6, 18),
    _dt.date(2027, 7, 5), _dt.date(2027, 9, 6), _dt.date(2027, 11, 25),
    _dt.date(2027, 12, 24),
}


def is_market_open() -> bool:
    if _MC is not None:
        try:
            return bool(_MC.is_market_open())
        except Exception:
            pass
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date() in _FALLBACK_HOLIDAYS:
        return False
    hm = (now.hour, now.minute)
    return (9, 30) <= hm and now.hour < 16


def minutes_since_open() -> float:
    """Minutes since 09:30 ET today (assumes server clock is ET, like the backend)."""
    now = _dt.datetime.now()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return (now - open_dt).total_seconds() / 60.0


# ─────────────────────────────────────────────────────────────────────────────
# Health probes (all read-only)
# ─────────────────────────────────────────────────────────────────────────────

def is_port_listening(port: int = BACKEND_PORT, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _ro_conn(db_path: str) -> sqlite3.Connection:
    """Open a strictly read-only connection (mode=ro), so the watchdog can never
    write or hold a writer lock against the live backend."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)


def count_recent_flow(db_path: str = DB_PATH, seconds: int = FLOW_WINDOW_S) -> int:
    """flow_alerts rows in the last N seconds. -1 on read error."""
    try:
        conn = _ro_conn(db_path)
        cutoff = time.time() - seconds
        n = conn.execute("SELECT COUNT(*) FROM flow_alerts WHERE ts >= ?", (cutoff,)).fetchone()[0]
        conn.close()
        return int(n or 0)
    except Exception as e:
        print(f"[watchdog] flow_alerts read error: {e!r}", flush=True)
        return -1


def snapshot_age_s(db_path: str = DB_PATH) -> float | None:
    """Seconds since the most recent snapshots row (worker-liveness). None on error."""
    try:
        conn = _ro_conn(db_path)
        row = conn.execute("SELECT MAX(ts) FROM snapshots").fetchone()
        conn.close()
        if not row or row[0] is None:
            return None
        return time.time() - float(row[0])
    except Exception as e:
        print(f"[watchdog] snapshots read error: {e!r}", flush=True)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Telegram (direct post — bypasses send() and ALL category/rate gates so an infra
# alarm is always delivered)
# ─────────────────────────────────────────────────────────────────────────────

def _telegram_creds() -> tuple[str, str]:
    """Return (bot_token, chat_id). Canonical source is server.config; falls back
    to a direct .env / os.environ parse if the server package can't be imported."""
    # 1) canonical
    try:
        sys.path.insert(0, REPO)
        from server.config import get_settings  # type: ignore
        s = get_settings()
        if s.telegram_bot_token and s.telegram_chat_id:
            return s.telegram_bot_token, s.telegram_chat_id
    except Exception:
        pass
    # 2) os.environ / .env fallback
    env: dict[str, str] = {}
    try:
        with open(os.path.join(REPO, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip().upper()] = v.strip().strip('"').strip("'")
    except Exception:
        pass

    def pick(key: str) -> str:
        return os.environ.get(key, "") or env.get(key, "")

    return pick("TELEGRAM_BOT_TOKEN"), pick("TELEGRAM_CHAT_ID")


def telegram_send(text: str) -> bool:
    token, chat_id = _telegram_creds()
    if not token or not chat_id:
        print("[watchdog] no telegram creds — cannot alert; message follows:\n" + text, flush=True)
        return False
    try:
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"[watchdog] telegram send failed: {e!r}", flush=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# State (persisted so --once invocations share a failure streak / cooldown)
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_STATE = {
    "process": {"fail_streak": 0, "armed": True, "last_alarm_ts": 0.0, "last_restart_ts": 0.0},
    "flow": {"fail_streak": 0, "armed": True, "last_alarm_ts": 0.0},
}


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
        for k, v in _DEFAULT_STATE.items():
            st.setdefault(k, dict(v))
            for kk, vv in v.items():
                st[k].setdefault(kk, vv)
        return st
    except Exception:
        return json.loads(json.dumps(_DEFAULT_STATE))  # deep copy


def save_state(st: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        print(f"[watchdog] state save failed: {e!r}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# One evaluation cycle
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(st: dict, auto_restart: bool = False) -> dict:
    """Evaluate health once, mutate `st`, fire alarms. Returns a small status dict."""
    now = time.time()
    proc = st["process"]
    flow = st["flow"]

    # Off-hours / open-auction grace: never alarm; reset streaks + re-arm for a
    # clean start at the next session. (This is exactly why Sat 6/20 and Juneteenth
    # 6/19 — both zero-flow — must not trip the watchdog.)
    if not is_market_open() or minutes_since_open() < STARTUP_GRACE_MIN:
        proc["fail_streak"] = 0
        flow["fail_streak"] = 0
        proc["armed"] = True
        flow["armed"] = True
        return {"status": "idle", "rth": is_market_open()}

    port_up = is_port_listening()

    # ── PROCESS DOWN branch (the 6/17 mode) ──────────────────────────────────
    if not port_up:
        flow["fail_streak"] = 0  # can't assess flow with the process down
        proc["fail_streak"] += 1
        fired = restarted = False
        if (proc["fail_streak"] >= FAIL_CONFIRM and proc["armed"]
                and now - proc["last_alarm_ts"] >= ALARM_COOLDOWN_S):
            extra = ""
            if auto_restart and now - proc["last_restart_ts"] >= RESTART_COOLDOWN_S:
                restarted = _trigger_restart()
                proc["last_restart_ts"] = now
                extra = ("\n\n♻️ Auto-restart triggered (start_gammapulse.bat)."
                         if restarted else "\n\n⚠️ Auto-restart FAILED — start it by hand.")
            telegram_send(
                f"🚨 <b>BACKEND WATCHDOG — PROCESS DOWN</b>\n\n"
                f"Port {BACKEND_PORT} is not listening during RTH after "
                f"{proc['fail_streak']} checks (~{proc['fail_streak']*CHECK_INTERVAL_S//60} min).\n"
                f"The backend is not running — this is the 6/17 silent-zero-flow failure.\n"
                f"Start it: <code>start_gammapulse.bat</code>{extra}"
            )
            proc["last_alarm_ts"] = now
            proc["armed"] = False
            fired = True
        return {"status": "process_down", "fail_streak": proc["fail_streak"],
                "alarmed": fired, "restarted": restarted}

    # ── Process is UP — re-arm process alarm + announce recovery if it had fired ─
    if not proc["armed"]:
        telegram_send(f"✅ <b>BACKEND WATCHDOG — backend back up</b>\n"
                      f"Port {BACKEND_PORT} is listening again.")
    proc["fail_streak"] = 0
    proc["armed"] = True

    # ── FLOW SILENT branch (process up but scanner stalled) ──────────────────
    flow_n = count_recent_flow()
    age = snapshot_age_s()
    age_str = f"{age/60:.1f} min" if age is not None else "unknown"

    if flow_n < 0:  # DB read error — don't alarm on our own failure, just log
        return {"status": "db_error", "flow_n": flow_n}

    if flow_n < FLOW_FLOOR:
        flow["fail_streak"] += 1
        fired = False
        if (flow["fail_streak"] >= FAIL_CONFIRM and flow["armed"]
                and now - flow["last_alarm_ts"] >= ALARM_COOLDOWN_S):
            worker_note = ("the whole worker loop looks dead"
                           if (age is not None and age > SNAPSHOT_STALE_S)
                           else "the worker is still writing snapshots, so only the flow scanner stalled")
            telegram_send(
                f"🚨 <b>BACKEND WATCHDOG — FLOW SILENT</b>\n\n"
                f"Backend is UP (port {BACKEND_PORT}) but only <b>{flow_n}</b> flow_alerts "
                f"in the last {FLOW_WINDOW_S//60} min during RTH "
                f"(healthy ≈ hundreds).\n"
                f"Last snapshot: {age_str} ago → {worker_note}.\n"
                f"The flow scanner has stalled — a restart is recommended."
            )
            flow["last_alarm_ts"] = now
            flow["armed"] = False
            fired = True
        return {"status": "flow_silent", "flow_n": flow_n, "snap_age_s": age,
                "fail_streak": flow["fail_streak"], "alarmed": fired}

    # ── Healthy ──────────────────────────────────────────────────────────────
    if not flow["armed"]:
        telegram_send(f"✅ <b>BACKEND WATCHDOG — flow restored</b>\n"
                      f"{flow_n} flow_alerts in the last {FLOW_WINDOW_S//60} min.")
    flow["fail_streak"] = 0
    flow["armed"] = True
    return {"status": "healthy", "flow_n": flow_n, "snap_age_s": age}


def _trigger_restart() -> bool:
    """Relaunch start_gammapulse.bat (only ever called on confirmed PROCESS DOWN, so
    there is no live writer to race — and we never invoke the gc_* mutators)."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "", START_BAT], cwd=REPO,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        print("[watchdog] auto-restart: launched start_gammapulse.bat", flush=True)
        return True
    except Exception as e:
        print(f"[watchdog] auto-restart failed: {e!r}", flush=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="GammaPulse external backend watchdog (#91)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="single check then exit (Task Scheduler)")
    mode.add_argument("--loop", action="store_true", help="long-lived poll loop (default)")
    ap.add_argument("--auto-restart", action="store_true",
                    help="on confirmed PROCESS DOWN, relaunch start_gammapulse.bat")
    ap.add_argument("--interval", type=int, default=CHECK_INTERVAL_S,
                    help=f"loop poll seconds (default {CHECK_INTERVAL_S})")
    ap.add_argument("--check", action="store_true",
                    help="print a one-shot health snapshot and exit (no alarms, no state)")
    args = ap.parse_args()

    if args.check:
        rth = is_market_open()
        up = is_port_listening()
        fn = count_recent_flow()
        age = snapshot_age_s()
        print(json.dumps({
            "rth": rth, "minutes_since_open": round(minutes_since_open(), 1),
            "port_8000_up": up, "flow_alerts_5min": fn,
            "snapshot_age_s": round(age, 1) if age is not None else None,
            "db": DB_PATH,
        }, indent=2))
        return 0

    if args.once:
        st = load_state()
        result = run_cycle(st, auto_restart=args.auto_restart)
        save_state(st)
        print(f"[watchdog] {time.strftime('%Y-%m-%d %H:%M:%S')} {result}", flush=True)
        return 0

    # default: loop
    interval = args.interval
    print(f"[watchdog] loop starting — interval={interval}s db={DB_PATH} "
          f"auto_restart={args.auto_restart}", flush=True)
    st = load_state()
    while True:
        try:
            result = run_cycle(st, auto_restart=args.auto_restart)
            save_state(st)
            print(f"[watchdog] {time.strftime('%H:%M:%S')} {result}", flush=True)
        except KeyboardInterrupt:
            print("[watchdog] stopped", flush=True)
            return 0
        except Exception as e:
            print(f"[watchdog] cycle error: {e!r}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
