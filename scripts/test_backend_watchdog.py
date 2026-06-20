"""State-machine tests for scripts/backend_watchdog.py (task #91).

Drives run_cycle() with the health probes + telegram monkeypatched, so every
transition is exercised without touching the live DB, the state file, or Telegram.
Run: python scripts/test_backend_watchdog.py
"""
import importlib.util
import os
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "backend_watchdog.py"
_spec = importlib.util.spec_from_file_location("backend_watchdog", _PATH)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)

SENT: list[str] = []


def _reset(rth=True, mins=30.0, port_up=True, flow=400, snap_age=60.0):
    """Install probe stubs and a fresh state dict. Returns the state dict."""
    SENT.clear()
    wd.is_market_open = lambda: rth
    wd.minutes_since_open = lambda: mins
    wd.is_port_listening = lambda *a, **k: port_up
    wd.count_recent_flow = lambda *a, **k: flow
    wd.snapshot_age_s = lambda *a, **k: snap_age
    wd.telegram_send = lambda text: (SENT.append(text), True)[1]
    wd._trigger_restart = lambda: True
    # zero cooldowns out via a state with last_alarm_ts far in the past
    return {
        "process": {"fail_streak": 0, "armed": True, "last_alarm_ts": 0.0, "last_restart_ts": 0.0},
        "flow": {"fail_streak": 0, "armed": True, "last_alarm_ts": 0.0},
    }


def check(cond, desc):
    print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")
    return 0 if cond else 1


def main() -> int:
    fails = 0

    # 1) Off-hours: never alarm, even with zero flow (the 6/13-Sat / 6/19-Juneteenth case)
    st = _reset(rth=False, flow=0)
    r = wd.run_cycle(st)
    fails += check(r["status"] == "idle" and not SENT, "off-hours -> idle, no alarm")

    # 2) Open-auction grace window: open but <5 min in -> idle
    st = _reset(rth=True, mins=2.0, port_up=False, flow=0)
    r = wd.run_cycle(st)
    fails += check(r["status"] == "idle" and not SENT, "open-auction grace -> idle, no alarm")

    # 3) Process down, first cycle: streak=1, NOT yet alarmed (needs FAIL_CONFIRM)
    st = _reset(rth=True, port_up=False)
    r = wd.run_cycle(st)
    fails += check(r["status"] == "process_down" and r["fail_streak"] == 1 and not SENT,
                   "process down cycle 1 -> streak 1, no alarm")

    # 4) Process down, second cycle: alarm fires once
    r = wd.run_cycle(st)
    fails += check(r["status"] == "process_down" and r["alarmed"] and len(SENT) == 1
                   and "PROCESS DOWN" in SENT[0], "process down cycle 2 -> PROCESS DOWN alarm")

    # 5) Process down, third cycle: cooldown -> no second alarm
    r = wd.run_cycle(st)
    fails += check(not r["alarmed"] and len(SENT) == 1, "process down cycle 3 -> cooled down, no repeat")

    # 6) Process recovers: 'back up' notice, then evaluates flow (healthy)
    wd.is_port_listening = lambda *a, **k: True
    wd.count_recent_flow = lambda *a, **k: 400
    r = wd.run_cycle(st)
    fails += check(r["status"] == "healthy" and any("back up" in m for m in SENT)
                   and st["process"]["armed"], "process recovery -> back-up notice + healthy")

    # 7) Flow silent (process up, ~0 flow) for FAIL_CONFIRM cycles -> FLOW SILENT alarm
    st = _reset(rth=True, port_up=True, flow=0, snap_age=60.0)
    r1 = wd.run_cycle(st)
    r2 = wd.run_cycle(st)
    fails += check(r1["status"] == "flow_silent" and not r1["alarmed"]
                   and r2["alarmed"] and any("FLOW SILENT" in m for m in SENT),
                   "flow silent 2 cycles -> FLOW SILENT alarm")
    fails += check(any("only the flow scanner stalled" in m for m in SENT),
                   "flow-silent msg distinguishes scanner-vs-worker (fresh snapshots)")

    # 8) Flow silent WITH stale snapshots -> 'whole worker looks dead' wording
    st = _reset(rth=True, port_up=True, flow=0, snap_age=1200.0)
    wd.run_cycle(st); wd.run_cycle(st)
    fails += check(any("whole worker loop looks dead" in m for m in SENT),
                   "flow-silent + stale snapshots -> worker-dead wording")

    # 9) Flow restored after a silent alarm -> 'flow restored' notice + rearm
    st = _reset(rth=True, port_up=True, flow=0)
    wd.run_cycle(st); wd.run_cycle(st)   # arm + alarm
    SENT.clear()
    wd.count_recent_flow = lambda *a, **k: 350
    r = wd.run_cycle(st)
    fails += check(r["status"] == "healthy" and any("flow restored" in m for m in SENT)
                   and st["flow"]["armed"], "flow restored -> restored notice + rearm")

    # 10) Auto-restart on confirmed process-down -> restart triggered + noted in msg
    st = _reset(rth=True, port_up=False)
    restarts = {"n": 0}
    wd._trigger_restart = lambda: (restarts.__setitem__("n", restarts["n"] + 1), True)[1]
    wd.run_cycle(st, auto_restart=True)
    r = wd.run_cycle(st, auto_restart=True)
    fails += check(restarts["n"] == 1 and r.get("restarted")
                   and any("Auto-restart triggered" in m for m in SENT),
                   "auto-restart -> relaunch fired + noted")

    # 11) DB read error (flow=-1) must NOT alarm on our own failure
    st = _reset(rth=True, port_up=True, flow=-1)
    r = wd.run_cycle(st)
    fails += check(r["status"] == "db_error" and not SENT, "db read error -> no alarm")

    print("ALL TESTS PASSED" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
