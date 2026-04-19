"""Monday preflight — exercises every code path shipped this weekend.

Run this before market open to catch any import error, missing dep,
misconfigured env var, or broken DB state that would silently wedge
the live system. Sends ONE test Telegram at the end if enabled.

Exit codes:
  0 = all green, safe to start the server
  1 = warnings (yellow — review output), mostly safe
  2 = errors (red — fix before starting)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3
import sys
import traceback
from pathlib import Path

# Make server imports work no matter where script is invoked
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Tracker:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []  # (status, name, detail)
        self.errors = 0
        self.warnings = 0

    def ok(self, name: str, detail: str = ""):
        self.rows.append(("✅", name, detail))

    def warn(self, name: str, detail: str = ""):
        self.rows.append(("⚠️ ", name, detail))
        self.warnings += 1

    def err(self, name: str, detail: str = ""):
        self.rows.append(("❌", name, detail))
        self.errors += 1

    def report(self) -> int:
        print()
        print("=" * 72)
        print(f"PREFLIGHT REPORT — {dt.datetime.now().isoformat(timespec='seconds')}")
        print("=" * 72)
        for status, name, detail in self.rows:
            detail_str = f" — {detail}" if detail else ""
            print(f"{status} {name}{detail_str}")
        print("-" * 72)
        print(f"  {sum(1 for r in self.rows if r[0] == '✅')} passed  "
              f"{self.warnings} warnings  {self.errors} errors")
        print("=" * 72)
        if self.errors:
            print("\n❌ DO NOT START THE SERVER — fix errors first.")
            return 2
        if self.warnings:
            print("\n⚠️  Review warnings before starting. System is probably OK.")
            return 1
        print("\n✅ All green. Safe to start the server.")
        return 0


t = Tracker()


# ── 1. Imports ────────────────────────────────────────────────────────

def check_imports():
    modules = [
        "server.tickers", "server.signals", "server.paper_trading",
        "server.price_watch", "server.telegram", "server.signal_parser",
        "server.discord_listener", "server.worker", "server.main",
        "server.ibd_groups", "server.ibd_sector_leaders",
        "server.swing_scanner", "server.backfill_closes",
    ]
    for mod in modules:
        try:
            __import__(mod)
            t.ok(f"import {mod}")
        except Exception as e:
            t.err(f"import {mod}", f"{type(e).__name__}: {e}")


# ── 2. IBD layer ──────────────────────────────────────────────────────

def check_ibd():
    try:
        from server.ibd_groups import get_ibd_group_info, summary as groups_summary
        s = groups_summary()
        t.ok("ibd_groups.summary()",
             f"{s['n_groups']} groups, {s['n_tickers_mapped']} tickers mapped, as of {s['table_as_of']}")

        # Spot checks
        checks = {"NVDA": 7, "AVGO": 7, "TSM": 7, "MU": 2, "AAOI": 1, "AEHR": 3, "AXTI": 9}
        for ticker, expected_rank in checks.items():
            info = get_ibd_group_info(ticker)
            if info and info["rank"] == expected_rank:
                t.ok(f"ibd_groups[{ticker}]", f"#{info['rank']} {info['name']}")
            else:
                t.err(f"ibd_groups[{ticker}]", f"expected rank {expected_rank}, got {info}")
    except Exception as e:
        t.err("ibd_groups", f"{type(e).__name__}: {e}")

    try:
        from server.ibd_sector_leaders import (
            is_sector_leader, leaders_count, leaders_regime, summary as ldr_summary,
        )
        s = ldr_summary()
        regime = leaders_regime()
        t.ok("ibd_sector_leaders.summary()",
             f"{leaders_count()}/16 leaders ({regime['label']}, {regime['pct_full']:.0f}%)")

        # Spot checks
        for ticker in ["NVDA", "AVGO", "TSM", "VRT", "APH"]:
            if is_sector_leader(ticker):
                t.ok(f"sector_leader[{ticker}]", "★★")
            else:
                t.err(f"sector_leader[{ticker}]", "should be leader, got False")

        for ticker in ["AAPL", "MSFT", "GOOGL", "GFS"]:
            if not is_sector_leader(ticker):
                t.ok(f"non-leader[{ticker}]", "correctly not flagged")
            else:
                t.err(f"non-leader[{ticker}]", "should NOT be leader, got True")
    except Exception as e:
        t.err("ibd_sector_leaders", f"{type(e).__name__}: {e}")


# ── 3. Discipline rules ───────────────────────────────────────────────

def check_rules():
    # Rule #4: max_pay gate
    try:
        from server.price_watch import get_max_pay_for_contract, _WATCHES
        active = [w for w in _WATCHES
                  if w.get("active_date") == dt.date.today().isoformat()
                  or (w.get("active_until") and w["active_until"] >= dt.date.today().isoformat())]
        t.ok("price_watch._WATCHES", f"{len(_WATCHES)} total, {len(active)} active today")

        # Test helper returns None for random contract (shouldn't match any watch)
        cap = get_max_pay_for_contract("NVDA", 200, "call", "2026-06-18")
        if cap is None:
            t.ok("get_max_pay_for_contract", "returns None for non-watch contract")
        else:
            t.warn("get_max_pay_for_contract",
                   f"unexpected cap ${cap} for NVDA 200C — check _WATCHES")
    except Exception as e:
        t.err("max_pay gate", f"{type(e).__name__}: {e}")

    # Rule #2: paper_trading DTE gate — verify the code path exists
    try:
        import inspect
        from server import paper_trading
        src = inspect.getsource(paper_trading.open_position)
        if "DTE_TOO_SHORT" in src and "dte < 3" in src:
            t.ok("rule #2 (DTE >= 3)", "gate wired in paper_trading.open_position")
        else:
            t.err("rule #2 (DTE >= 3)", "gate not found in open_position source")
    except Exception as e:
        t.err("rule #2 gate", f"{type(e).__name__}: {e}")

    # Rule #1: puts block in signals.py
    try:
        import inspect
        from server import signals
        src = inspect.getsource(signals.generate_signals)
        if "_block_puts" in src and "_spy_20d" in src:
            t.ok("rule #1 (block puts non-bear)", "gate wired in generate_signals")
        else:
            t.err("rule #1", "gate not found in generate_signals source")
    except Exception as e:
        t.err("rule #1", f"{type(e).__name__}: {e}")

    # Rule #3b: B+ drift warning in telegram
    try:
        import inspect
        from server import telegram
        src = inspect.getsource(telegram.format_soe_signal)
        if "drift_warning" in src and "TRADE THIS EXACT CONTRACT" in src:
            t.ok("rule #3b (B+ drift warning)", "wired in format_soe_signal")
        else:
            t.err("rule #3b", "drift warning not found in format_soe_signal")
    except Exception as e:
        t.err("rule #3b", f"{type(e).__name__}: {e}")


# ── 4. Market-hours gates ────────────────────────────────────────────

def check_gates():
    try:
        import inspect
        from server import signals, price_watch

        sig_src = inspect.getsource(signals.generate_signals)
        if "mins > 975" in sig_src:  # 4:15 outer cutoff
            t.ok("signals.py 4:15 outer cutoff", "wired")
        else:
            t.err("signals.py 4:15 gate", "not found")
        if "cutoff_mins > 960" in sig_src:  # 4:00 per-ticker
            t.ok("signals.py 4:00 per-ticker filter", "wired")
        else:
            t.err("signals.py 4:00 filter", "not found")

        pw_src = inspect.getsource(price_watch.check_watches)
        if "mins < 570 or mins > 960" in pw_src:
            t.ok("price_watch market-hours gate", "9:30-4:00 wired")
        else:
            t.err("price_watch gate", "not found")
    except Exception as e:
        t.err("gates", f"{type(e).__name__}: {e}")


# ── 5. CHAT_RELAY parser ─────────────────────────────────────────────

def check_chat_relay():
    try:
        import inspect
        from server import signal_parser, discord_listener
        parser_src = inspect.getsource(signal_parser)
        if "CHAT_RELAY" in parser_src:
            t.ok("signal_parser CHAT_RELAY", "type defined")
        else:
            t.err("signal_parser CHAT_RELAY", "type not found")
        listener_src = inspect.getsource(discord_listener.MirDiscordClient)
        if "_handle_chat_relay" in listener_src:
            t.ok("discord_listener._handle_chat_relay", "method wired")
        else:
            t.err("discord_listener CHAT_RELAY", "handler not found")
    except Exception as e:
        t.err("CHAT_RELAY", f"{type(e).__name__}: {e}")


# ── 6. Database state ────────────────────────────────────────────────

def check_db():
    try:
        con = sqlite3.connect("snapshots.db")
        con.row_factory = sqlite3.Row

        # Ticker universe sanity
        from server.tickers import all_tickers
        uni = set(all_tickers())
        t.ok("ticker universe", f"{len(uni)} tickers in tickers.py")

        # Backfilled closes — snapshots table takes both live scans (full row)
        # and backfill inserts (ticker/ts/spot only, other columns NULL). Any
        # row presence = ticker has historical data.
        n_tickers_in_db = con.execute(
            "SELECT COUNT(DISTINCT ticker) FROM snapshots"
        ).fetchone()[0]
        t.ok("snapshots table", f"{n_tickers_in_db} distinct tickers have rows")

        new_adds = {"GEV", "CRWV", "GFS", "AMBA", "PAAS", "SLV",
                    "USO", "GLD", "APH", "WDC", "STX", "VIAV",
                    "AGI", "GFI", "KGC", "TFPM", "WPM",
                    "ICHR", "UCTT", "FORM", "MKSI", "KLIC",
                    "ONTO", "NVMI", "ENTG", "PLAB",
                    "FIX", "ROAD", "FUTU", "MRX"}
        backfilled_new = con.execute(
            f"SELECT COUNT(DISTINCT ticker) FROM snapshots "
            f"WHERE ticker IN ({','.join('?'*len(new_adds))})",
            list(new_adds),
        ).fetchone()[0]
        if backfilled_new == len(new_adds):
            t.ok("new-ticker backfill", f"all {len(new_adds)} new adds have closes")
        else:
            missing = [tk for tk in new_adds if con.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=?", (tk,)
            ).fetchone()[0] == 0]
            t.warn("new-ticker backfill",
                   f"{backfilled_new}/{len(new_adds)} backfilled. Missing: {missing}")

        # Critical tables exist
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        required = {"soe_signals", "paper_positions", "paper_trade_events",
                    "flow_alerts", "mir_signal_cache", "broker_roundtrips",
                    "signal_outcomes", "option_flow_daily"}
        missing = required - tables
        if not missing:
            t.ok("DB tables", f"all {len(required)} required tables present")
        else:
            t.err("DB tables", f"missing: {missing}")

        # Recent signals count (sanity)
        r = con.execute(
            "SELECT COUNT(*) FROM soe_signals WHERE ts >= strftime('%s','2026-04-13')"
        ).fetchone()[0]
        t.ok("soe_signals this week", f"{r} signals logged")

        con.close()
    except Exception as e:
        t.err("database", f"{type(e).__name__}: {e}")
        traceback.print_exc()


# ── 7. External services ─────────────────────────────────────────────

def check_env():
    for key, required in [
        ("ANTHROPIC_API_KEY", True),
        ("TELEGRAM_BOT_TOKEN", True),
        ("TELEGRAM_CHAT_ID", True),
        ("TRADIER_TOKEN", True),
        ("DISCORD_ENABLED", False),
        ("FINNHUB_API_KEY", False),
    ]:
        val = os.environ.get(key)
        if val:
            t.ok(f"env {key}", f"<set, {len(val)} chars>")
        elif required:
            t.err(f"env {key}", "MISSING — required for core functionality")
        else:
            t.warn(f"env {key}", "not set (optional feature disabled)")

    # ThetaData is a local REST+WS daemon, not an env var — TCP-probe the REST
    # port. Any HTTP response (including 404/472 rate-limit) means the daemon
    # is up; only a ConnectionRefusedError means it's not running.
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", 25503), timeout=3)
        sock.close()
        t.ok("ThetaData daemon", "REST port 25503 open")
    except (ConnectionRefusedError, OSError) as e:
        t.warn("ThetaData daemon",
               f"port 25503 closed ({e}) — daemon not running, Greeks will fallback to Tradier")


async def check_telegram():
    try:
        from server.telegram import send
        msg = (
            f"🚀 <b>GammaPulse preflight — {dt.date.today().isoformat()}</b>\n"
            f"\n"
            f"System check before Monday open.\n"
            f"If you're seeing this, Telegram is wired ✅"
        )
        ok = await send(msg, ticker="__preflight__", force=True)
        if ok:
            t.ok("Telegram test alert", "delivered")
        else:
            t.err("Telegram test alert", "send() returned False (rate limit or config issue)")
    except Exception as e:
        t.err("Telegram test alert", f"{type(e).__name__}: {e}")


# ── 8. Weekend research dependencies ─────────────────────────────────

def check_weekend_deps():
    try:
        import feedparser, bs4, httpx, anthropic  # noqa: F401
        t.ok("weekend_research deps", f"anthropic {anthropic.__version__}, feedparser, bs4, httpx")
    except ImportError as e:
        t.warn("weekend_research deps", f"missing: {e}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("Running Monday preflight...")
    check_imports()
    check_ibd()
    check_rules()
    check_gates()
    check_chat_relay()
    check_db()
    check_env()
    check_weekend_deps()
    asyncio.run(check_telegram())
    sys.exit(t.report())


if __name__ == "__main__":
    main()
