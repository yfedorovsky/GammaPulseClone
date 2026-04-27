"""Bayesian shrinkage helpers for per-ticker win-rate / payoff estimates.

Phase 1 #2 from the cross-LLM synthesis. All three LLMs (ChatGPT, Grok,
Perplexity) independently identified per-ticker selection bias as the single
most dangerous flaw in the scoring system, and proposed the same fix:
empirical-Bayes shrinkage toward the pooled mean.

    p_adjusted = (n × p_ticker + k × p_pooled) / (n + k)

Where:
    n         = ticker's historical trigger count
    p_ticker  = ticker's raw observed hit rate
    p_pooled  = pooled hit rate across the cohort
    k         = prior strength (consensus k=20)

If n < 10, fall back to 100% pooled. Below 10 samples a per-ticker rate is
indistinguishable from noise.

Item #3 from the same synthesis (Grok-unique): cap the inputs to Kelly so a
single freak rate cannot blow up sizing.

    win_rate clipped to [45%, 65%]
    payoff ratio clipped to [0.8, 2.5]

Both protections apply *after* shrinkage, before Kelly.
"""
from __future__ import annotations

# Consensus parameters (cross-LLM synthesis Apr 25 2026)
SHRINKAGE_K = 20            # prior strength
MIN_SAMPLES_FOR_TICKER = 10  # below this, use 100% pooled
WIN_RATE_FLOOR = 45.0
WIN_RATE_CEIL = 65.0
PAYOFF_FLOOR = 0.8
PAYOFF_CEIL = 2.5


def shrunk_win_rate(
    ticker_wins: int,
    ticker_trades: int,
    pooled_win_rate: float,
    k: int = SHRINKAGE_K,
) -> float:
    """Empirical-Bayes shrinkage of a per-ticker win rate toward the pool.

    Args:
        ticker_wins: number of historical wins for this ticker
        ticker_trades: total historical trades for this ticker
        pooled_win_rate: pooled hit rate across the cohort, in PERCENT
        k: prior strength (default 20 per cross-LLM consensus). Pass
            dynamic_k(p, sigma_prior_sq) for the data-driven version.

    Returns: adjusted win rate in PERCENT.
    """
    if ticker_trades < MIN_SAMPLES_FOR_TICKER:
        return pooled_win_rate
    raw_p = 100.0 * ticker_wins / ticker_trades
    n = ticker_trades
    return (n * raw_p + k * pooled_win_rate) / (n + k)


def dynamic_k(p_ticker_pct: float, sigma_prior_sq: float) -> float:
    """Compute the dynamic shrinkage parameter k per Gemini's formula.

    Phase 6A.2 (Apr 26 night) — replaces the hardcoded k=20 with a
    data-driven value derived from the actual cohort's cross-sectional
    variance.

    Per Gemini Apr 26 follow-up:
        k_dynamic = p(1-p) / sigma_prior_sq

    Where:
        p = ticker's hit rate (decimal, 0-1)
        sigma_prior_sq = sample variance of all cohort ticker hit rates

    Behavior:
        - High ticker variance OR low cohort dispersion → large k
          (shrink heavily toward pooled mean)
        - Low ticker variance AND high cohort dispersion → small k
          (trust the individual ticker)
        - Tightly clustered cohort (sigma_prior_sq → 0) → k → infinity
          (pulls everything to the mean — correct when cohort is uniform)
        - Highly disparate cohort (sigma_prior_sq large) → k → 0
          (trust each ticker as its own draw)

    Args:
        p_ticker_pct: ticker's hit rate in PERCENT (0-100)
        sigma_prior_sq: cross-sectional VARIANCE of cohort hit rates,
            computed in DECIMAL units (e.g. 0.01 for std=0.10)

    Returns: dynamic k value (clamped to [1, 200] for stability)
    """
    p = max(0.01, min(0.99, p_ticker_pct / 100.0))
    binomial_var = p * (1 - p)
    if sigma_prior_sq <= 1e-6:
        # Effectively zero cohort dispersion — shrink hard
        return 200.0
    k = binomial_var / sigma_prior_sq
    return max(1.0, min(200.0, k))


def cohort_prior_variance(ticker_hit_rates_pct: list[float]) -> float:
    """Compute sigma_prior_sq from a list of per-ticker hit rates.

    Use this once per refresh cycle to derive the variance, then pass
    to dynamic_k() per ticker.

    Args:
        ticker_hit_rates_pct: list of hit rates in PERCENT (0-100)

    Returns: sample variance in DECIMAL units (matches dynamic_k input)
    """
    if not ticker_hit_rates_pct or len(ticker_hit_rates_pct) < 2:
        return 0.0
    decimals = [r / 100.0 for r in ticker_hit_rates_pct]
    n = len(decimals)
    mean = sum(decimals) / n
    return sum((x - mean) ** 2 for x in decimals) / (n - 1)


def shrunk_win_rate_dynamic(
    ticker_wins: int,
    ticker_trades: int,
    pooled_win_rate: float,
    cohort_hit_rates_pct: list[float] | None = None,
    sigma_prior_sq: float | None = None,
) -> dict:
    """Shrunk win rate using DATA-DRIVEN k (per Gemini Apr 26).

    Either pass `cohort_hit_rates_pct` (list of all cohort ticker rates,
    will compute variance internally) OR `sigma_prior_sq` (precomputed).

    Returns:
        {
            "shrunk_pct": float,
            "k_used": float,
            "raw_pct": float,
            "n": int,
            "fell_back_to_pooled": bool,
        }
    """
    if ticker_trades < MIN_SAMPLES_FOR_TICKER:
        return {
            "shrunk_pct": pooled_win_rate,
            "k_used": float("inf"),
            "raw_pct": 0.0 if ticker_trades == 0 else 100.0 * ticker_wins / ticker_trades,
            "n": ticker_trades,
            "fell_back_to_pooled": True,
        }
    raw_p = 100.0 * ticker_wins / ticker_trades

    if sigma_prior_sq is None:
        if not cohort_hit_rates_pct:
            # No cohort data → fallback to legacy k=20
            k = float(SHRINKAGE_K)
        else:
            sigma_prior_sq = cohort_prior_variance(cohort_hit_rates_pct)
            k = dynamic_k(raw_p, sigma_prior_sq)
    else:
        k = dynamic_k(raw_p, sigma_prior_sq)

    n = ticker_trades
    adj = (n * raw_p + k * pooled_win_rate) / (n + k)
    return {
        "shrunk_pct": adj,
        "k_used": k,
        "raw_pct": raw_p,
        "n": n,
        "fell_back_to_pooled": False,
    }


def shrunk_payoff(
    ticker_avg_win: float,
    ticker_avg_loss: float,
    ticker_trades: int,
    pooled_payoff: float,
    k: int = SHRINKAGE_K,
) -> float:
    """Empirical-Bayes shrinkage of per-ticker avg-win / avg-loss ratio.

    Args:
        ticker_avg_win, ticker_avg_loss: positive numbers, percent of premium
        ticker_trades: sample size
        pooled_payoff: pooled b = avg_win / avg_loss across cohort
        k: prior strength

    Returns: adjusted payoff ratio (b).
    """
    if ticker_trades < MIN_SAMPLES_FOR_TICKER or ticker_avg_loss <= 0:
        return pooled_payoff
    raw_b = ticker_avg_win / ticker_avg_loss
    n = ticker_trades
    return (n * raw_b + k * pooled_payoff) / (n + k)


def clip_kelly_inputs(win_rate_pct: float, payoff: float) -> tuple[float, float, str]:
    """Cap win-rate and payoff inputs before they hit Kelly.

    Prevents a single freak observation (110% win or 7x payoff) from blowing up
    the Kelly fraction. Especially important for thin-sample per-ticker stats.

    Returns: (clipped_win_rate_pct, clipped_payoff, reason_str)
        reason_str describes which clip(s) bound (or 'OK' if neither did).
    """
    reasons = []
    wr = win_rate_pct
    if wr < WIN_RATE_FLOOR:
        wr = WIN_RATE_FLOOR
        reasons.append(f"WR_FLOOR({WIN_RATE_FLOOR})")
    elif wr > WIN_RATE_CEIL:
        wr = WIN_RATE_CEIL
        reasons.append(f"WR_CEIL({WIN_RATE_CEIL})")

    b = payoff
    if b < PAYOFF_FLOOR:
        b = PAYOFF_FLOOR
        reasons.append(f"PAYOFF_FLOOR({PAYOFF_FLOOR})")
    elif b > PAYOFF_CEIL:
        b = PAYOFF_CEIL
        reasons.append(f"PAYOFF_CEIL({PAYOFF_CEIL})")

    reason = ",".join(reasons) if reasons else "OK"
    return wr, b, reason


if __name__ == "__main__":
    # Smoke tests
    print("Static shrinkage (k=20) examples:")
    pooled = 60.0
    for n, w in [(5, 5), (10, 8), (20, 16), (50, 40), (100, 80)]:
        p = shrunk_win_rate(w, n, pooled)
        raw = 100.0 * w / n if n else 0
        print(f"  n={n:>3} wins={w:>3} raw={raw:>5.1f}% shrunk={p:>5.1f}%")

    print("\nClipping examples:")
    for wr, b in [(80, 5.0), (35, 0.5), (55, 1.5), (65, 2.5)]:
        c_wr, c_b, reason = clip_kelly_inputs(wr, b)
        print(f"  in: wr={wr} b={b}  -->  wr={c_wr} b={c_b}  ({reason})")

    print("\n=== DYNAMIC shrinkage (Gemini formula) ===")
    print("Cohort like ours: AAOI 75%, AESI 40%, MU 65%, SNDK 70%, GLW 60%, "
          "CIEN 67%, ...")
    cohort = [75, 40, 65, 70, 60, 67, 55, 50, 73, 62, 58, 64, 71, 45, 52, 68, 60]
    sigma_sq = cohort_prior_variance(cohort)
    print(f"sigma_prior_sq = {sigma_sq:.4f} (std = {sigma_sq**0.5:.3f})")

    print("\nDynamic k for various raw p values (with cohort variance above):")
    for p in [40, 50, 60, 70, 75, 80]:
        k = dynamic_k(p, sigma_sq)
        print(f"  raw_p={p}%  →  k_dynamic={k:.1f}  (vs static k=20)")

    print("\nFull dynamic shrinkage examples (with cohort context):")
    for n, w in [(5, 5), (10, 8), (20, 16), (50, 40), (100, 80)]:
        r = shrunk_win_rate_dynamic(w, n, pooled_win_rate=60.0,
                                     cohort_hit_rates_pct=cohort)
        fb = " (FELL BACK to pooled — n<10)" if r["fell_back_to_pooled"] else ""
        print(f"  n={n:>3} wins={w:>3} raw={r['raw_pct']:>5.1f}% "
              f"k={r['k_used']:>5.1f} shrunk={r['shrunk_pct']:>5.1f}%{fb}")

    print("\nComparison: static k=20 vs dynamic k for n=20, raw 80%:")
    static = shrunk_win_rate(16, 20, 60.0)
    dynamic = shrunk_win_rate_dynamic(16, 20, 60.0, cohort_hit_rates_pct=cohort)
    print(f"  static k=20:    {static:.1f}%")
    print(f"  dynamic k={dynamic['k_used']:.1f}: {dynamic['shrunk_pct']:.1f}%")
