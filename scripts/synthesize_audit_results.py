"""Read all 8 audit outputs and synthesize a single recommendation.

This is the consumer of the audit chain output. It walks the
V2_DETECTOR_SPEC.md decision tree using the ACTUAL numbers from each
audit and emits docs/research/AUDIT_SYNTHESIS.md — a single document
that says: based on the data, here's what to build (or not build).

Designed to run after `run_databento_audit_chain.py` completes. Reads
the per-audit CSVs and Markdown reports from docs/research/, parses
the key statistics, applies the pre-committed thresholds from the
v2 spec, and outputs the final go/no-go decision per gate.

This is NOT another analysis — it's a deterministic interpretation
of results we already have. Pre-committing this logic before the
data lands prevents the post-hoc threshold tuning Perplexity flagged.

Run:
  python scripts/synthesize_audit_results.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "docs" / "research"
OUT_REPORT = RESEARCH / "AUDIT_SYNTHESIS.md"


def safe_read_csv(name: str) -> pd.DataFrame | None:
    p = RESEARCH / name
    if not p.exists():
        return None
    try:
        return pd.read_csv(p)
    except Exception as e:
        print(f"  [synth] failed to read {name}: {e}")
        return None


def interpret_test1_microstructure() -> dict:
    """Test #1: any feature with |Cohen's d| >= 0.5?"""
    df = safe_read_csv("microstructure_profile_audit.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}

    fire = df[df["row_type"] == "fire"]
    rand = df[df["row_type"] == "random"]
    fire_ok = fire[fire["status"] == "ok"]
    rand_ok = rand[rand["status"] == "ok"]
    if fire_ok.empty or rand_ok.empty:
        return {"status": "incomplete", "verdict": "no usable rows"}

    feature_cols = [
        "cumulative_ofi", "ofi_per_min",
        "mean_mp_minus_mid", "std_mp_minus_mid",
        "mean_spread", "std_spread",
        "aggressor_ratio", "total_volume",
        "mean_trade_size", "n_trades",
    ]
    big_effects = []
    for col in feature_cols:
        if col not in fire_ok.columns:
            continue
        f = fire_ok[col].dropna().values
        r = rand_ok[col].dropna().values
        if len(f) < 2 or len(r) < 2:
            continue
        pooled = np.sqrt((f.var(ddof=1) + r.var(ddof=1)) / 2)
        if pooled == 0:
            continue
        d = (f.mean() - r.mean()) / pooled
        if abs(d) >= 0.5:
            big_effects.append((col, float(d)))

    if big_effects:
        return {
            "status": "PASS",
            "big_effects": big_effects,
            "verdict": "Gates fire at microstructurally distinctive moments. "
                       "Strategy framework has flow-side signal. Continue down v2 spec.",
        }
    else:
        return {
            "status": "FAIL",
            "big_effects": [],
            "verdict": "No feature shows medium-or-larger effect size. "
                       "Gates fire on noise correlated with structural levels. "
                       "RETIRE v1 strategy. Do not build v2.",
        }


def interpret_test2_ofi_predictive() -> dict:
    """Test #2: max R² across (ticker × horizon)?"""
    df = safe_read_csv("ofi_predictive_power.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}
    if df.empty or "r_sq" not in df.columns:
        return {"status": "incomplete", "verdict": "no rows"}

    valid = df.dropna(subset=["r_sq"])
    if valid.empty:
        return {"status": "incomplete", "verdict": "all R² NaN"}
    max_r2 = float(valid["r_sq"].max())
    best = valid.loc[valid["r_sq"].idxmax()]
    out = {"max_r_sq": max_r2,
           "best_ticker": best["ticker"], "best_horizon": int(best["horizon_min"]),
           "best_t_stat": float(best.get("t_stat", np.nan))}
    if max_r2 < 0.02:
        out.update({
            "status": "FAIL",
            "verdict": "OFI does not predict returns. Cont 2014 doesn't transfer. No OFI gate.",
        })
    elif max_r2 < 0.05:
        out.update({
            "status": "BORDERLINE",
            "verdict": "Weakly positive but below literature range. Build OFI as info-only for v2.0.",
        })
    elif max_r2 < 0.20:
        out.update({
            "status": "PASS",
            "verdict": "OFI predictive power confirmed. Build OFI gate for v2.",
        })
    else:
        out.update({
            "status": "SUSPECT",
            "verdict": f"R² {max_r2:.3f} above literature range. Sanity-check before trusting.",
        })
    return out


def interpret_test3_vix_regime() -> dict:
    """Test #3: how many features with K-W p<0.05?"""
    md_path = RESEARCH / "day_regime_audit.md"
    if not md_path.exists():
        return {"status": "missing", "verdict": "no data"}
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Count lines with "✓ significant" — quick parse
    sig_count = text.count("✓ significant")
    if "No significance tests run" in text:
        return {"status": "incomplete", "verdict": "no scipy or insufficient data"}
    if sig_count >= 2:
        return {
            "status": "PASS",
            "n_significant": sig_count,
            "verdict": "VIX1D quartile carries microstructure information. "
                       "Build VIX1D-regime position sizing.",
        }
    else:
        return {
            "status": "FAIL",
            "n_significant": sig_count,
            "verdict": f"Only {sig_count} significant features. VIX1D regime "
                       "is independent of microstructure. IV regime stays retired.",
        }


def interpret_test4_background() -> dict:
    """Test #4: just confirm it ran. No verdict — provides percentile lookups."""
    df = safe_read_csv("background_distributions.csv")
    if df is None:
        return {"status": "missing", "verdict": "not run"}
    if df.empty:
        return {"status": "incomplete", "verdict": "no rows"}
    return {
        "status": "OK",
        "n_features": int(df["feature"].nunique()),
        "n_buckets": int(df.groupby(["ticker", "tod_bucket"]).ngroups),
        "verdict": "Percentile lookup table built. Use these as pre-committed "
                   "thresholds for any v2 gate.",
    }


def interpret_test5_cohorts() -> dict:
    df = safe_read_csv("trade_size_cohort_audit.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}
    md_path = RESEARCH / "trade_size_cohort_audit.md"
    if not md_path.exists():
        return {"status": "incomplete", "verdict": "no md"}
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Pull each cohort's correlation from the md table
    # Format: | small | n | corr | ... |
    cohorts = {}
    import re
    for line in text.splitlines():
        m = re.match(r"\|\s*(small|medium|large)\s*\|\s*\d+\s*\|\s*([+-]?\d+\.\d+)", line)
        if m:
            cohorts[m.group(1)] = float(m.group(2))
    if not cohorts:
        return {"status": "incomplete", "verdict": "couldn't parse correlations"}
    best_cohort = max(cohorts.items(), key=lambda x: abs(x[1]))
    other_max = max((abs(v) for k, v in cohorts.items() if k != best_cohort[0]),
                    default=0)
    if abs(best_cohort[1]) > 0.3 and other_max < 0.15:
        return {
            "status": "PASS", "cohorts": cohorts, "best": best_cohort,
            "verdict": f"{best_cohort[0]}-trade CVD differentiates "
                       f"(corr {best_cohort[1]:+.3f}). Weight that cohort 2× in v2 Gate 8.",
        }
    elif max(abs(v) for v in cohorts.values()) < 0.15:
        return {
            "status": "FAIL", "cohorts": cohorts,
            "verdict": "No cohort shows meaningful correlation. Drop CVD from v2 entirely.",
        }
    else:
        return {
            "status": "MIXED", "cohorts": cohorts,
            "verdict": "Correlations are mid-range. Aggregate CVD only; don't split.",
        }


def interpret_test6_spread() -> dict:
    df = safe_read_csv("spread_regime_audit.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}
    with_pnl = df.dropna(subset=["opt_eod_pnl"])
    if with_pnl.empty:
        return {"status": "incomplete", "verdict": "no outcomes"}
    high = with_pnl[with_pnl["flagged_high_spread"] == 1]
    norm = with_pnl[with_pnl["flagged_high_spread"] == 0]
    if len(high) < 3 or len(norm) < 3:
        return {
            "status": "INSUFFICIENT",
            "n_high": len(high), "n_norm": len(norm),
            "verdict": "Cohort sizes too small for spread-regime verdict.",
        }
    diff = float(norm["opt_eod_pnl"].mean() - high["opt_eod_pnl"].mean())
    if diff > 30:
        return {
            "status": "PASS", "diff_pp": diff,
            "n_high": len(high), "n_norm": len(norm),
            "verdict": f"Normal-spread fires beat HIGH-spread by {diff:.0f}pp. "
                       "Build spread-regime gate for v2 (block when spread > day p90).",
        }
    elif diff < -30:
        return {
            "status": "INVERTED", "diff_pp": diff,
            "verdict": "HIGH-spread fires outperform — counter-intuitive, investigate.",
        }
    else:
        return {
            "status": "FAIL", "diff_pp": diff,
            "verdict": f"Difference only {diff:+.0f}pp. Spread regime doesn't differentiate.",
        }


def interpret_test7_lead_lag() -> dict:
    df = safe_read_csv("lead_lag_audit.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}
    if df.empty:
        return {"status": "incomplete", "verdict": "no rows"}
    # Pool mean correlation per lag
    lag_cols = [c for c in df.columns if c.startswith("corr_lag")]
    lag_means = {c: float(df[c].dropna().mean()) for c in lag_cols
                 if not df[c].dropna().empty}
    if not lag_means:
        return {"status": "incomplete", "verdict": "no lag corrs"}
    peak_col, peak_val = max(lag_means.items(), key=lambda x: x[1])
    peak_lag = int(peak_col.replace("corr_lag", "").replace("+", ""))
    lag0 = lag_means.get("corr_lag+0", 0.0)
    if peak_lag != 0 and abs(peak_val - lag0) > 0.05:
        return {
            "status": "PASS", "peak_lag_min": peak_lag,
            "peak_corr": peak_val, "lag0_corr": lag0,
            "verdict": f"Peak at lag {peak_lag:+d}min ({peak_val:+.3f}) vs "
                       f"lag-0 ({lag0:+.3f}). v2 cross-confirm should use "
                       f"lagged OFI from the leading ticker.",
        }
    else:
        return {
            "status": "FAIL", "peak_lag_min": peak_lag,
            "peak_corr": peak_val, "lag0_corr": lag0,
            "verdict": "No lead-lag asymmetry. Same-second cross-confirm is fine.",
        }


def interpret_gate8() -> dict:
    """Gate 8 audit — does Lee-Ready predict outcomes better than bar proxy?"""
    df = safe_read_csv("gate8_audit.csv")
    if df is None:
        return {"status": "missing", "verdict": "no data"}
    ok = df[df["status"] == "ok"]
    if ok.empty:
        return {"status": "incomplete", "verdict": "no successful audits"}

    sign_flip = ok["direction"].map({"BULLISH": 1, "BEARISH": -1}).astype(float)
    corrs = {}
    for col in ["cvd_lee_ready", "cvd_tick_rule_tick", "cvd_bar_proxy"]:
        if col not in ok.columns:
            continue
        sub = ok.dropna(subset=[col, "opt_eod_pnl"])
        if sub.empty:
            continue
        adj = sub[col] * sign_flip.loc[sub.index]
        corrs[col] = float(sub["opt_eod_pnl"].corr(adj))
    if not corrs:
        return {"status": "incomplete", "verdict": "no outcome correlations computable"}

    lr = corrs.get("cvd_lee_ready", 0)
    bar = corrs.get("cvd_bar_proxy", 0)
    diff = lr - bar
    if abs(lr) > 0.3 and abs(lr) > abs(bar) + 0.1:
        return {
            "status": "PASS", "corrs": corrs, "lr_minus_bar": diff,
            "verdict": f"Lee-Ready CVD beats bar proxy "
                       f"(lr={lr:+.3f} vs bar={bar:+.3f}). Replace Gate 8 with tick LR.",
        }
    elif abs(bar) > abs(lr) + 0.1:
        return {
            "status": "BAR_WINS", "corrs": corrs, "lr_minus_bar": diff,
            "verdict": "Bar proxy outperforms Lee-Ready in this sample. Keep simple.",
        }
    else:
        return {
            "status": "TIE", "corrs": corrs, "lr_minus_bar": diff,
            "verdict": "LR and bar proxy roughly equivalent. No upgrade justified.",
        }


def main() -> int:
    print("Synthesizing audit results...\n", flush=True)
    results = {
        "test1_microstructure": interpret_test1_microstructure(),
        "test2_ofi_predictive": interpret_test2_ofi_predictive(),
        "test3_vix_regime": interpret_test3_vix_regime(),
        "test4_background": interpret_test4_background(),
        "test5_cohorts": interpret_test5_cohorts(),
        "test6_spread": interpret_test6_spread(),
        "test7_lead_lag": interpret_test7_lead_lag(),
        "gate8_lee_ready": interpret_gate8(),
    }
    for name, r in results.items():
        print(f"  {name}: {r.get('status', '?'):<12}  {r.get('verdict', '')[:70]}",
              flush=True)

    # Decision tree per V2_DETECTOR_SPEC
    md = ["# Audit Synthesis — v2 Decision Tree Walk\n"]
    md.append("Generated by `synthesize_audit_results.py`. Walks the "
              "pre-committed decision tree from `V2_DETECTOR_SPEC.md` "
              "using actual numbers from the eight audits.\n")

    # Walk the tree
    md.append("\n## Step 1 — Test #1 (microstructure profile)\n")
    t1 = results["test1_microstructure"]
    md.append(f"**Status: {t1.get('status', 'missing')}**\n")
    md.append(f"Verdict: {t1.get('verdict', '')}\n")
    if t1.get("big_effects"):
        md.append("Features with |Cohen's d| ≥ 0.5:")
        for col, d in t1["big_effects"]:
            md.append(f"  - {col}: d = {d:+.2f}")
    if t1.get("status") == "FAIL":
        md.append("\n**STOP. Strategy framework lacks flow-side signal.** "
                  "Do not build v2. Do not invest more in v1 either — focus "
                  "on understanding why GEX-level structural setups don't "
                  "have microstructure correlates.")
        OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
        print(f"\nReport -> {OUT_REPORT}")
        return 0

    # Continue walking
    for step, key in [
        ("Step 2 — Test #2 (OFI predictive power)", "test2_ofi_predictive"),
        ("Step 3 — Test #3 (VIX1D regime)", "test3_vix_regime"),
        ("Step 4 — Test #4 (background distributions)", "test4_background"),
        ("Step 5 — Test #5 (trade-size cohorts)", "test5_cohorts"),
        ("Step 6 — Test #6 (spread regime)", "test6_spread"),
        ("Step 7 — Test #7 (lead-lag)", "test7_lead_lag"),
        ("Step 8 — Gate 8 (Lee-Ready vs bar proxy)", "gate8_lee_ready"),
    ]:
        r = results[key]
        md.append(f"\n## {step}\n")
        md.append(f"**Status: {r.get('status', 'missing')}**\n")
        md.append(f"Verdict: {r.get('verdict', '')}")
        if r.get("max_r_sq") is not None:
            md.append(f"\nMax R² = {r['max_r_sq']:.4f} "
                      f"({r.get('best_ticker', '?')}, "
                      f"{r.get('best_horizon', '?')}min horizon)")
        if r.get("cohorts"):
            md.append(f"\nCohort correlations: {r['cohorts']}")
        if r.get("diff_pp") is not None:
            md.append(f"\nDifference: {r['diff_pp']:+.1f}pp")
        if r.get("peak_lag_min") is not None:
            md.append(f"\nPeak lag: {r['peak_lag_min']:+d}min "
                      f"(corr {r.get('peak_corr', 0):+.3f})")
        if r.get("corrs"):
            md.append(f"\nCVD correlations with outcomes: {r['corrs']}")

    # Final v2 recommendation
    md.append("\n\n## Final v2 recommendation\n")
    passes = sum(1 for r in results.values()
                 if r.get("status") == "PASS")
    md.append(f"Audits passing their threshold: **{passes}/8**\n")
    md.append("Per V2_DETECTOR_SPEC stop conditions, build v2 if:")
    md.append("- v1 forward falsification (paired bootstrap) shows positive CI, AND")
    md.append("- Test #1 (microstructure profile) PASS, AND")
    md.append("- ≥ 1 of Test #2, #5, #6 PASS\n")
    t1_ok = results["test1_microstructure"].get("status") == "PASS"
    others_ok = sum(1 for k in ["test2_ofi_predictive", "test5_cohorts",
                                 "test6_spread"]
                    if results[k].get("status") == "PASS") >= 1
    if t1_ok and others_ok:
        md.append("**Conditions met (pending v1 forward verdict). Build v2 "
                  "per the gate selections above.** Effort: 16-25h.")
    else:
        md.append("**Conditions not met. Do not build v2.** v1 stays as-is "
                  "through the forward falsification window. After 30+ paired "
                  "observations, re-evaluate.")

    md.append("\n\n## Operational reminders\n")
    md.append("- Do NOT change v1 production code regardless of these results "
              "— the falsification freeze holds until paired bootstrap "
              "delivers a verdict.")
    md.append("- The percentiles from Test #4 are pre-committed thresholds. "
              "Don't re-tune them when implementing v2.")
    md.append("- If audit verdicts disagree with intuition, trust the data. "
              "If they agree with intuition, double-check for "
              "confirmation bias.")

    OUT_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport -> {OUT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
