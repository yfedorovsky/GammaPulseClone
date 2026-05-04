"""Verify Telegram bot can send messages.

Sends a single test message confirming the alert pipeline is alive.
Doesn't burn rate limit (one message per run).

Usage:
  python scripts/telegram_healthcheck.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    try:
        from server.telegram import send
    except Exception as e:
        print(f"FAIL: telegram module import — {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    msg = (
        f"🟢 GammaPulse pre-market healthcheck\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (local)\n"
        f"\n"
        f"If you see this, telegram alerts are working for today's session."
    )

    try:
        result = await send(msg, ticker="HEALTHCHECK", force=True)
    except Exception as e:
        print(f"FAIL: telegram send raised — {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    if result:
        print("PASS: telegram healthcheck sent (check your chat)")
        return 0
    print("WARN: telegram send returned False — check TELEGRAM_BOT_TOKEN + "
          "TELEGRAM_CHAT_ID in .env")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
