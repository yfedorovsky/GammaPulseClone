"""Outbound Discord posting via channel webhooks.

The Discord integration was inbound-only (discord_listener reads Mir's signals);
this adds the OUTBOUND path so detectors can post to a Discord channel. Best-effort,
never raises. The webhook URL lives in an env var (e.g. DISCORD_SPX_WEBHOOK) — never
hard-code it; a webhook URL is a secret (anyone with it can post to your channel).

Create one in Discord: channel → Edit Channel → Integrations → Webhooks → New
Webhook → Copy URL → put it in .env as DISCORD_SPX_WEBHOOK=...
"""
from __future__ import annotations

import os

_MAX = 1990  # Discord hard limit is 2000 chars/message


def post(content: str, env_var: str = "DISCORD_SPX_WEBHOOK", timeout: float = 8.0) -> bool:
    """POST `content` to the Discord webhook named by `env_var`. Returns True on a
    2xx, False if no webhook is configured or the post fails. Never raises."""
    url = os.getenv(env_var)
    if not url:
        return False  # not configured → silently no-op (fail-safe)
    try:
        import requests
        r = requests.post(url, json={"content": content[:_MAX]}, timeout=timeout)
        ok = r.status_code in (200, 204)
        if not ok:
            print(f"[discord_out] {env_var} HTTP {r.status_code}", flush=True)
        return ok
    except Exception as e:
        print(f"[discord_out] post failed: {e!r}", flush=True)
        return False
