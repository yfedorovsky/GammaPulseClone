"""GammaPulse AutoResearch — OFFLINE research loop over our own outcome data.

This package is deliberately OUTSIDE ``server/`` so the live trading app can
never import it. Nothing here may:
  - be wired into real-time scoring or dispatch (it would kill the OPRA latency edge),
  - auto-ship anything to live scoring (a human gate stays in front of production),
  - write to the live ``alert_outcomes.db`` (read-only, by absolute path).

Phase 0 is the decay/retirement monitor (``autoresearch.decay_monitor``). See
``docs/research/autoresearch/PROJECT.md`` for the charter and phased plan.
"""

__all__ = ["decay_monitor"]
