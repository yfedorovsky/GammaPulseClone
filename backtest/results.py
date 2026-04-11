"""Stats computation and reporting for backtest results."""
from __future__ import annotations

from typing import Any


def compute_stats(results: dict[str, Any]) -> dict[str, Any]:
    """Compute comprehensive stats from BacktestEngine results.

    Returns win rates by grade, ticker, day-of-week, P&L distributions, etc.
    """
    signals = results.get("signals", [])
    traded = [s for s in signals if s.traded and s.outcome]

    if not traded:
        return {"error": "No completed trades to analyze"}

    # Overall
    total = len(traded)
    wins = sum(1 for s in traded if s.outcome == "WIN")
    losses = sum(1 for s in traded if s.outcome in ("LOSS", "EXPIRED"))
    win_rate = (wins / total * 100) if total else 0

    pnls = [s.pnl_pct for s in traded]
    avg_pnl = sum(pnls) / len(pnls)
    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]
    avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 0
    avg_loss = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0

    # By grade
    by_grade: dict[str, dict] = {}
    for grade in ["A+", "A", "B+", "B", "C"]:
        subset = [s for s in traded if s.grade == grade]
        if not subset:
            continue
        g_wins = sum(1 for s in subset if s.outcome == "WIN")
        g_pnls = [s.pnl_pct for s in subset]
        by_grade[grade] = {
            "trades": len(subset),
            "wins": g_wins,
            "losses": len(subset) - g_wins,
            "win_rate": round(g_wins / len(subset) * 100, 1),
            "avg_pnl": round(sum(g_pnls) / len(g_pnls), 1),
            "max_win": round(max(g_pnls), 1),
            "max_loss": round(min(g_pnls), 1),
        }

    # By ticker
    by_ticker: dict[str, dict] = {}
    tickers = set(s.ticker for s in traded)
    for t in sorted(tickers):
        subset = [s for s in traded if s.ticker == t]
        t_wins = sum(1 for s in subset if s.outcome == "WIN")
        t_pnls = [s.pnl_pct for s in subset]
        by_ticker[t] = {
            "trades": len(subset),
            "wins": t_wins,
            "win_rate": round(t_wins / len(subset) * 100, 1),
            "avg_pnl": round(sum(t_pnls) / len(t_pnls), 1),
        }

    # By day of week
    by_dow: dict[str, dict] = {}
    for dow_name, dow_num in [("MON", 0), ("TUE", 1), ("WED", 2), ("THU", 3), ("FRI", 4)]:
        subset = [s for s in traded if s.date.weekday() == dow_num]
        if not subset:
            continue
        d_wins = sum(1 for s in subset if s.outcome == "WIN")
        by_dow[dow_name] = {
            "trades": len(subset),
            "wins": d_wins,
            "win_rate": round(d_wins / len(subset) * 100, 1),
        }

    # By signal type
    by_signal_type: dict[str, dict] = {}
    signal_types = set(s.signal_type for s in traded)
    for st in sorted(signal_types):
        subset = [s for s in traded if s.signal_type == st]
        st_wins = sum(1 for s in subset if s.outcome == "WIN")
        by_signal_type[st] = {
            "trades": len(subset),
            "wins": st_wins,
            "win_rate": round(st_wins / len(subset) * 100, 1),
        }

    # Exit reason breakdown
    by_exit: dict[str, int] = {}
    for s in traded:
        r = s.exit_reason or "UNKNOWN"
        by_exit[r] = by_exit.get(r, 0) + 1

    # Max favorable excursion (how much profit was available but not captured)
    mfe_pnls = [(s.max_favorable, s.pnl_pct) for s in traded if s.max_favorable > 0]
    avg_mfe = (sum(m for m, _ in mfe_pnls) / len(mfe_pnls)) if mfe_pnls else 0
    capture_rate = (
        sum(p / m * 100 for m, p in mfe_pnls if m > 0) / len(mfe_pnls)
    ) if mfe_pnls else 0

    # Drawdown
    equity_curve = [results["starting_value"]]
    for s in sorted(traded, key=lambda x: x.date):
        last = equity_curve[-1]
        pos_value = last * (s.kelly_pct / 100)
        new_equity = last + pos_value * (s.pnl_pct / 100)
        equity_curve.append(new_equity)

    peak = results["starting_value"]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Pnl percentiles
    sorted_pnls = sorted(pnls)
    p10 = sorted_pnls[int(len(sorted_pnls) * 0.1)] if len(sorted_pnls) > 10 else 0
    p25 = sorted_pnls[int(len(sorted_pnls) * 0.25)] if len(sorted_pnls) > 4 else 0
    p50 = sorted_pnls[int(len(sorted_pnls) * 0.5)]
    p75 = sorted_pnls[int(len(sorted_pnls) * 0.75)] if len(sorted_pnls) > 4 else 0
    p90 = sorted_pnls[int(len(sorted_pnls) * 0.9)] if len(sorted_pnls) > 10 else 0

    return {
        "summary": {
            "total_signals": len(signals),
            "signals_traded": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "avg_pnl": round(avg_pnl, 1),
            "avg_win": round(avg_win, 1),
            "avg_loss": round(avg_loss, 1),
            "final_account": round(results.get("account_value", 0), 2),
            "total_return": round(results.get("return_pct", 0), 1),
            "max_drawdown": round(max_dd, 1),
        },
        "pnl_distribution": {
            "p10": round(p10, 1), "p25": round(p25, 1), "median": round(p50, 1),
            "p75": round(p75, 1), "p90": round(p90, 1),
            "min": round(min(pnls), 1), "max": round(max(pnls), 1),
        },
        "by_grade": by_grade,
        "by_ticker": by_ticker,
        "by_day_of_week": by_dow,
        "by_signal_type": by_signal_type,
        "by_exit_reason": by_exit,
        "exit_ladder_stats": {
            "avg_max_favorable_excursion": round(avg_mfe, 1),
            "avg_capture_rate": round(capture_rate, 1),
        },
    }


def print_report(stats: dict[str, Any]) -> None:
    """Print a formatted backtest report to stdout."""
    s = stats.get("summary", {})
    print("\n" + "=" * 70)
    print("  GammaPulse SOE Backtest Report")
    print("=" * 70)
    print(f"  Total signals generated: {s.get('total_signals', 0)}")
    print(f"  Signals traded:          {s.get('signals_traded', 0)}")
    print(f"  Wins: {s.get('wins', 0)}  |  Losses: {s.get('losses', 0)}  |  Win Rate: {s.get('win_rate', 0)}%")
    print(f"  Avg P&L: {s.get('avg_pnl', 0):.1f}%  |  Avg Win: +{s.get('avg_win', 0):.1f}%  |  Avg Loss: {s.get('avg_loss', 0):.1f}%")
    print(f"  Final Account: ${s.get('final_account', 0):,.2f}  |  Return: {s.get('total_return', 0):.1f}%")
    print(f"  Max Drawdown: {s.get('max_drawdown', 0):.1f}%")

    print("\n── Win Rate by Grade ──")
    for grade in ["A+", "A", "B+", "B", "C"]:
        g = stats.get("by_grade", {}).get(grade)
        if g:
            print(f"  {grade:3s}  {g['win_rate']:5.1f}%  ({g['wins']}W / {g['losses']}L / {g['trades']}T)  avg {g['avg_pnl']:+.1f}%")

    print("\n── Win Rate by Ticker (top 10) ──")
    by_t = stats.get("by_ticker", {})
    top = sorted(by_t.items(), key=lambda x: x[1]["trades"], reverse=True)[:10]
    for t, v in top:
        print(f"  {t:6s}  {v['win_rate']:5.1f}%  ({v['wins']}W / {v['trades']}T)  avg {v['avg_pnl']:+.1f}%")

    print("\n── Win Rate by Day ──")
    for dow in ["MON", "TUE", "WED", "THU", "FRI"]:
        d = stats.get("by_day_of_week", {}).get(dow)
        if d:
            print(f"  {dow}  {d['win_rate']:5.1f}%  ({d['wins']}W / {d['trades']}T)")

    print("\n── Win Rate by Signal Type ──")
    for st, v in stats.get("by_signal_type", {}).items():
        print(f"  {st:25s}  {v['win_rate']:5.1f}%  ({v['wins']}W / {v['trades']}T)")

    print("\n── P&L Distribution ──")
    d = stats.get("pnl_distribution", {})
    print(f"  Min: {d.get('min', 0):.1f}%  |  P10: {d.get('p10', 0):.1f}%  |  P25: {d.get('p25', 0):.1f}%  |  Median: {d.get('median', 0):.1f}%  |  P75: {d.get('p75', 0):.1f}%  |  P90: {d.get('p90', 0):.1f}%  |  Max: {d.get('max', 0):.1f}%")

    els = stats.get("exit_ladder_stats", {})
    print(f"\n── Exit Ladder ──")
    print(f"  Avg MFE: {els.get('avg_max_favorable_excursion', 0):.1f}%  |  Capture Rate: {els.get('avg_capture_rate', 0):.1f}%")

    print("\n── Exit Reasons ──")
    for reason, count in sorted(stats.get("by_exit_reason", {}).items(), key=lambda x: x[1], reverse=True):
        print(f"  {reason:20s}  {count}")
    print("=" * 70)
