"""ThetaData Python-library backend — the Terminal-free path.

The `thetadata` pip package talks gRPC straight to Theta Data's servers, so anything
here works WITHOUT the local Java Terminal running (unlike the REST path in
server/thetadata.py, which proxies through the Terminal at 127.0.0.1:25503). That
makes the option-P&L backfill self-sufficient in cron/workflow/standalone contexts
where a running Terminal was the flaky prerequisite.

Scope: request/response option data only (history + snapshots). The real-time OPRA
trade stream (server/thetadata.py ThetaStream) has NO library equivalent and stays
on the Terminal WebSocket.

Entitlement (verified 2026-06-30 against our account): options history + all-greeks
work; stock and index endpoints return PERMISSION_DENIED (FREE tier) — so this backend
is options-only for us until those subs are added.

Auth: THETADATA_API_KEY (from the process env, or loaded from the repo .env here so
standalone scripts work without pre-loading dotenv). Never hard-fails the import: if
the library is missing or unauthenticated, available() is False and callers fall back
to the REST path.
"""
from __future__ import annotations

import datetime as _dt
import threading
from pathlib import Path
from typing import Any

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_client = None
_client_lock = threading.Lock()
_init_failed = False  # sticky: don't retry a broken client every call


def _get_client():
    """Lazily build a shared authenticated ThetaClient (pandas backend), or None.
    Thread-safe; the backfill loop calls this from asyncio.to_thread workers."""
    global _client, _init_failed
    if _client is not None:
        return _client
    if _init_failed:
        return None
    with _client_lock:
        if _client is not None:
            return _client
        if _init_failed:
            return None
        try:
            from thetadata import ThetaClient
            kwargs: dict[str, Any] = {"dataframe_type": "pandas"}
            # Point at the repo .env so standalone scripts authenticate without
            # pre-loading dotenv; an already-set THETADATA_API_KEY env var still wins.
            if _ENV_PATH.exists():
                kwargs["dotenv_path"] = str(_ENV_PATH)
            _client = ThetaClient(**kwargs)
            return _client
        except Exception as e:  # missing package, no key, bad creds
            print(f"[thetadata_lib] client init failed ({e!r}); REST fallback in use")
            _init_failed = True
            return None


def available() -> bool:
    """True if the library backend is importable AND authenticated."""
    return _get_client() is not None


def _right_word(right: str) -> str:
    return "call" if str(right).upper().startswith("C") else "put"


def fetch_option_nbbo_bars(
    symbol: str, expiration: str, strike: float, right: str,
    start_date: str, end_date: str,
) -> list[dict[str, Any]]:
    """1-min OPRA NBBO bars for one contract over [start_date, end_date] via the
    Python library. Signature + return shape are byte-identical to
    server.alert_outcomes.fetch_option_nbbo_bars (validated to the cent by
    scripts/theta_lib_parity.py), so it is a drop-in fetcher.

    Returns [{ts, date, bid, ask, mid}] sorted ascending; [] on miss/empty/error.
    The library's `timestamp` is already tz-aware ET, so .timestamp() is the correct
    epoch with no localization (the REST path localizes naive ET by hand)."""
    client = _get_client()
    if client is None:
        return []
    try:
        d0 = _dt.date.fromisoformat(start_date)
        d1 = _dt.date.fromisoformat(end_date)
        df = client.option_history_quote(
            symbol=symbol, expiration=expiration, strike=f"{float(strike):.2f}",
            right=_right_word(right), interval="1m", start_date=d0, end_date=d1,
        )
    except Exception as e:
        print(f"[thetadata_lib] option_history_quote failed for "
              f"{symbol} {expiration} {strike}{right}: {e!r}")
        return []
    if df is None or len(df) == 0:
        return []
    try:
        out = []
        for row in df.itertuples(index=False):
            bid, ask = row.bid, row.ask
            if not (bid > 0) or not (ask > 0):  # NaN-safe: NaN>0 is False
                continue
            pdt = row.timestamp.to_pydatetime()  # already tz-aware ET
            out.append({
                "ts": pdt.timestamp(),
                "date": pdt.strftime("%Y-%m-%d"),
                "bid": float(bid), "ask": float(ask),
                "mid": (float(bid) + float(ask)) / 2.0,
            })
        out.sort(key=lambda b: b["ts"])
        return out
    except Exception as e:
        print(f"[thetadata_lib] bar parse failed for {symbol} {expiration}: {e!r}")
        return []
