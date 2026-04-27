"""Hysteresis state filter — eliminates signal flickering.

Phase 6A.2 (Apr 26 night). User feedback from OG GammaPulse Discord:
"danger sign was switching with bullish reversal" — classic flicker
when continuous variable hovers near a binary threshold.

Cross-LLM convergence: ChatGPT, Perplexity, Gemini all recommend
hysteresis or 3-cycle persistence over multi-timeframe bucketing.
Gemini gave the specific math (dual-threshold dead-band).

This module provides two filter modes:

  1. **N-cycle persistence:** require state to hold N cycles before display
     state changes. Simple, no thresholds needed.

  2. **Dual-threshold dead-band:** for continuous variables, define an
     activation threshold and a (separate, distant) deactivation threshold.
     Once a state is established, it requires meaningful directional change
     to flip. Eliminates flicker on noisy continuous variables (NYMO around
     zero, IV-rank around 0.66, etc.).

Both modes are **per-signal** stateful — caller passes a `signal_id` to
keep separate states for different signals.

Usage:

    from server.hysteresis import HysteresisFilter

    flt = HysteresisFilter()
    # N-cycle mode for discrete states
    label = flt.persistence("breadth_regime", "FULL_BULL", n_cycles=3)
    # Dual-threshold for continuous
    state = flt.dual_threshold("nymo", current_value=27,
                                bull_activate=25, bear_activate=-25,
                                bull_deactivate=-15, bear_deactivate=15)
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any


class HysteresisFilter:
    """Per-signal stateful filter for both modes."""

    def __init__(self) -> None:
        # N-cycle persistence: signal_id -> {observed_history: deque, displayed_state, last_seen}
        self._persistence: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"observed": deque(maxlen=10), "displayed": None,
                     "last_change_ts": 0.0}
        )
        # Dual-threshold: signal_id -> current_state ("BULL"/"BEAR"/"NEUTRAL")
        self._threshold: dict[str, str] = {}

    def persistence(self, signal_id: str, observed_state: str,
                    n_cycles: int = 3) -> dict[str, Any]:
        """N-cycle persistence: require state to repeat N times before display flips.

        Args:
            signal_id: unique identifier per signal (e.g., "breadth_regime")
            observed_state: current cycle's raw observation
            n_cycles: how many consecutive cycles of new state to display

        Returns:
            {
                "displayed_state": str,        # filtered output
                "observed_state": str,         # raw current observation
                "is_changing": bool,           # state in transition
                "cycles_in_new_state": int,    # progress toward flip
            }
        """
        s = self._persistence[signal_id]
        s["observed"].append(observed_state)

        if s["displayed"] is None:
            # First observation — accept immediately
            s["displayed"] = observed_state
            s["last_change_ts"] = time.time()
            return {
                "displayed_state": observed_state,
                "observed_state": observed_state,
                "is_changing": False,
                "cycles_in_new_state": 1,
            }

        # Count consecutive trailing cycles of any new state
        recent = list(s["observed"])
        if recent[-1] == s["displayed"]:
            # Reverted to displayed state — reset
            return {
                "displayed_state": s["displayed"],
                "observed_state": observed_state,
                "is_changing": False,
                "cycles_in_new_state": 0,
            }

        # Count consecutive trailing observations of new state
        new_state = recent[-1]
        cycles_in_new = 0
        for obs in reversed(recent):
            if obs == new_state:
                cycles_in_new += 1
            else:
                break

        if cycles_in_new >= n_cycles:
            # Flip the displayed state
            s["displayed"] = new_state
            s["last_change_ts"] = time.time()
            return {
                "displayed_state": new_state,
                "observed_state": observed_state,
                "is_changing": False,
                "cycles_in_new_state": cycles_in_new,
            }
        return {
            "displayed_state": s["displayed"],
            "observed_state": observed_state,
            "is_changing": True,
            "cycles_in_new_state": cycles_in_new,
        }

    def dual_threshold(self, signal_id: str, current_value: float,
                       bull_activate: float, bear_activate: float,
                       bull_deactivate: float | None = None,
                       bear_deactivate: float | None = None) -> dict[str, Any]:
        """Dual-threshold dead-band for continuous variables.

        Args:
            signal_id: unique identifier
            current_value: current numeric value
            bull_activate: threshold above which BULL state activates
            bear_activate: threshold below which BEAR state activates
            bull_deactivate: BULL state holds until value falls below this
                (default: midpoint between bull_activate and bear_activate)
            bear_deactivate: BEAR state holds until value rises above this
                (default: midpoint)

        Returns:
            {
                "state": "BULL" | "BEAR" | "NEUTRAL",
                "value": float,
                "thresholds": {...},
                "transitioned": bool,
            }
        """
        if bull_deactivate is None:
            bull_deactivate = (bull_activate + bear_activate) / 2
        if bear_deactivate is None:
            bear_deactivate = (bull_activate + bear_activate) / 2

        # Sanity: bull_deactivate must be below bull_activate; bear_deactivate above bear_activate
        if bull_deactivate >= bull_activate:
            bull_deactivate = bull_activate * 0.5  # fallback
        if bear_deactivate <= bear_activate:
            bear_deactivate = bear_activate * 0.5

        prev_state = self._threshold.get(signal_id, "NEUTRAL")
        new_state = prev_state  # default: maintain

        if prev_state == "BULL":
            if current_value < bull_deactivate:
                # Drop out of BULL — reassess
                new_state = "BEAR" if current_value <= bear_activate else "NEUTRAL"
        elif prev_state == "BEAR":
            if current_value > bear_deactivate:
                new_state = "BULL" if current_value >= bull_activate else "NEUTRAL"
        else:  # NEUTRAL
            if current_value >= bull_activate:
                new_state = "BULL"
            elif current_value <= bear_activate:
                new_state = "BEAR"

        transitioned = new_state != prev_state
        self._threshold[signal_id] = new_state

        return {
            "state": new_state,
            "value": current_value,
            "thresholds": {
                "bull_activate": bull_activate, "bear_activate": bear_activate,
                "bull_deactivate": bull_deactivate, "bear_deactivate": bear_deactivate,
            },
            "transitioned": transitioned,
            "previous_state": prev_state,
        }

    def reset(self, signal_id: str | None = None) -> None:
        """Reset state. If signal_id is None, reset all."""
        if signal_id is None:
            self._persistence.clear()
            self._threshold.clear()
        else:
            self._persistence.pop(signal_id, None)
            self._threshold.pop(signal_id, None)


# Module-level singleton for convenience
_FILTER = HysteresisFilter()


def persistence(signal_id: str, observed_state: str, n_cycles: int = 3) -> dict[str, Any]:
    return _FILTER.persistence(signal_id, observed_state, n_cycles)


def dual_threshold(signal_id: str, current_value: float,
                   bull_activate: float, bear_activate: float,
                   bull_deactivate: float | None = None,
                   bear_deactivate: float | None = None) -> dict[str, Any]:
    return _FILTER.dual_threshold(signal_id, current_value,
                                    bull_activate, bear_activate,
                                    bull_deactivate, bear_deactivate)


def reset(signal_id: str | None = None) -> None:
    _FILTER.reset(signal_id)


if __name__ == "__main__":
    # Smoke test scenarios
    flt = HysteresisFilter()

    print("Test 1: N-cycle persistence (n=3) on flickering NYMO label")
    print("-" * 60)
    sequence = ["BULL", "BULL", "BEAR", "BULL", "BEAR", "BEAR", "BEAR", "BEAR", "BULL"]
    for i, obs in enumerate(sequence):
        r = flt.persistence("nymo_label", obs, n_cycles=3)
        marker = "→" if r["displayed_state"] == obs else " "
        print(f"  cycle {i}: observed={obs:<5} → displayed={r['displayed_state']:<5} {marker} "
              f"(cycles_in_new={r['cycles_in_new_state']})")

    print("\nTest 2: Dual-threshold dead-band on NYMO value")
    print("-" * 60)
    nymo_values = [10, 28, 30, 22, 18, 12, -5, -20, -28, -10, 5, 18, 26, 22]
    for v in nymo_values:
        r = flt.dual_threshold("nymo_value", v,
                                bull_activate=25, bear_activate=-25,
                                bull_deactivate=15, bear_deactivate=-15)
        trans = " 🔄" if r["transitioned"] else ""
        print(f"  NYMO={v:>4} → state={r['state']:<8}{trans}")
