# GammaPulse — Project Structure

> Live options-flow / GEX trading system. This document is the map of the repo root so it
> doesn't "feel scattered." Last mapped 2026-06-27.
>
> **GOLDEN RULE:** Anything in *Live Runtime State* below is read/written by the running
> backend. Never move, rename, or delete it while the system can run. Gitignored does NOT
> mean safe-to-move here — most live DBs are gitignored but actively written.

## Top-level docs & config (tracked, stay at root)
| File | Purpose |
|---|---|
| `README.md` | Project overview / setup |
| `STATUS.md` | Operational status (currently stale Apr 11 — refresh, don't move) |
| `STRATEGY.md` | Strategy notes |
| `PROJECT_STRUCTURE.md` | This map |
| `.env` | **Secrets/config (gitignored)** — loaded by config.py + many server modules |
| `.env.example` | Tracked template companion to `.env` |
| `.gitignore` | VCS ignore rules |

## Restart / ops SOP (tracked, stay at root)
| Script | Purpose |
|---|---|
| `start_gammapulse.bat` | Cold start (sets `PYTHONIOENCODING=utf-8`) |
| `restart_gammapulse.bat` / `restart_gammapulse.ps1` | Restart the live stack |

Pre-bell restart SOP (per ops memory): stop → `gc_aggressive` → start → `verify_freshness` → run tests.

## Live runtime state — DO NOT MOVE (all gitignored, all at root)
These are anchored to the repo root by code (relative CWD paths or `ROOT / name`). Moving any
of them breaks the live system or corrupts data.

| Path | Written by | Notes |
|---|---|---|
| `snapshots.db` (+ `-wal`, `-shm`) | `server/config.py` default `./snapshots.db`; main.py + ~20 modules | **5.4GB primary DB, written continuously.** The `-wal`/`-shm` sidecars are SQLite-managed and MUST stay beside it — moving any of the three corrupts the DB. |
| `alert_outcomes.db` | `server/alert_outcomes.py`, flow_alerts.py, informed_cluster.py, signals.py, zero_dte_loop.py, telegram.py | Outcome backfill every 30 min |
| `zero_dte_alerts.db` | `server/zero_dte_loop.py`, alert_annotations.py, structural_turn.py, tradier_executor.py | 0DTE alert store |
| `king_migrations.db` | `server/king_migration.py`, triple_confluence.py | King-strike migration tracker |
| `king_breakouts.db` | `server/king_breakout.py` | King breakout tracker |
| `floor_migrations.db` | `server/floor_migration.py`, structural_turn.py | Floor migration tracker |
| `structural_turns.db` | `server/structural_turn.py`, paired_trades.py, st_near_fire.py, tradier_executor.py | 142MB structural-turn store |
| `paired_trades.db` | `server/paired_trades.py` | The canonical intrinsic-only validation DB |
| `paper_executions.db` | `server/paper_executions.py` (`ROOT / "paper_executions.db"`) | Path hard-anchored to root |
| `setup_cooldown.json` | `server/signals.py` (`./setup_cooldown.json`) | Live cooldown state, read+written |
| `.etrade_tokens.json` | `server.etrade` (on `feature/etrade-paper-execution`) | **Sensitive OAuth cache**, cross-branch |
| `.gex_backfill_checkpoint.json` | `scripts/historical_gex_backfill.py` | Backfill resume checkpoint |

### Offline research DBs (regenerable, but referenced by relative path — keep at root)
`unified_setup_backtest.db`, `realistic_slippage_backtest.db`, `ema_8_9_21_backtest.db`,
`ema_cross_backtest_6mo.db`, `shadow_alerts.db`, `gex_backfill.log`. Gitignored and
regenerable, **but** analysis scripts in `scripts/` open them via relative repo-root paths.
A plain move silently breaks those scripts — only relocate if you edit each script's path
constant in the same commit.

## Source & asset directories (unchanged)
| Dir | What it is |
|---|---|
| `server/` | Live FastAPI backend + all detectors (flow, GEX, king/floor migration, structural turn, whale, informed cluster) |
| `scripts/` | Offline analysis, backtest harnesses, ops scripts (`gc_aggressive.py`, `verify_freshness.py`, `historical_gex_backfill.py`, …) |
| `web/` | Frontend |
| `docs/` | Documentation + research synthesis writeups (audit syntheses, session indexes) |
| `backtest/`, `gex_backtest/`, `research/` | Backtest engines + working dirs (`gex_backtest/`, `research/results/` gitignored) |
| `discord/` | Discord parsers + curated portfolio spreadsheets |
| `mcp_servers/` | MCP server implementations |
| `data/`, `logs/` | Runtime data + logs (gitignored, active) |
| `og_screenshots/`, `telegram_alerts_sample/`, `thread_assets/` | Tracked assets (`thread_assets/*.png` gitignored) |
| `.venv/`, `.claude/`, `.git/` | Tooling/VCS |

## archive/ — orphaned analysis output (2026-06-28 cleanup)
Old ad-hoc dumps and backtest result JSONs (Apr–May) with zero code references live here so the
root stays clean: `archive/backtests/`, `archive/mir_analysis/`, `archive/dumps/`,
`archive/scans/`, `archive/logs/`, `archive/screenshots/`, `archive/db_backups/`. The
git-tracked dumps (grid/walk_forward/spy_intraday/mir/king_compression) were relocated with
`git mv`; the gitignored ones (backtest_*.json, *_dump.json, qqq*/thetav3*, history.txt, *.BAK,
_screenshots/) are plain local moves. Root-anchored `.gitignore` patterns keep future dumps out
of the root without re-flagging the archived copies.

## How to tell if a root file is safe to touch
1. `git check-ignore <file>` — tells you tracked vs ignored (NOT whether it's load-bearing).
2. `grep -rn '<basename>' server/ scripts/` — if it appears in code, it's **load-bearing → leave it.**
3. Live DBs have a current mtime and appear in `server/` grep — never move.
4. When in doubt: archive, don't delete.