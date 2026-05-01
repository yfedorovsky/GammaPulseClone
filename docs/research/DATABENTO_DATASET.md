# Databento US Equities Mini — research dataset

**Acquired Apr 30 2026 via Databento's $125 new-account credit. This is
a high-value research asset; treat as such.**

## What we have

| | |
|---|---|
| **Dataset** | Databento US Equities Mini (`EQUS.MINI`) |
| **Schema** | MBP-1 (every trade + every BBO update at top of book) |
| **Symbols** | SPY, QQQ |
| **Time window** | 2025-10-30 → 2026-04-30 (6 months, ~125 trading days) |
| **Encoding** | DBN (zero-copy binary) + zstd compression |
| **Splits** | One file per day; both tickers interleaved |
| **Total size** | ~106 GB compressed (128 files × avg ~150 MB) |
| **Cost** | $118.90 (covered in full by free credit) |

## Why this matters

Multi-venue aggregated NBBO at tick-level resolution is the single
biggest data gap retail options traders normally face. Three things this
unlocks that we previously could not do:

1. **Lee-Ready (1991) trade classification** — quote-based vs the
   tick-rule proxy currently used in Gate 5 (NCP) and Gate 8 (CVD
   divergence). Perplexity flagged tick-rule contamination as a major
   source of noise in our gates.

2. **OFI (Cont/Kukanov/Stoikov 2014)** — order flow imbalance from
   per-event BBO size changes. A leading indicator of short-horizon
   returns (literature R² 0.05–0.15 on liquid index ETFs).

3. **Microprice (Bonart 2017)** — opposite-side-weighted NBBO mean.
   Predicts next-mid drift via stack-asymmetry signal.

All three are inputs for any future **v2 detector** that wants to
upgrade from minute-bar / tick-rule gates to quote-based ones.

## Replacement cost if this dataset is lost

To put a dollar number on what's sitting on the local disk:

- **Databento US Equities Mini MBP-1 SPY+QQQ 6 months** → $118.90 raw
  download cost (we paid $0 with the credit)
- Equivalent options data is *materially* more expensive on Databento.
  Per the user's cross-check: ~$150 for 1 month of SPY OHLCV-1m on
  options data. Tick-level options data (analogue of MBP-1) is
  multiples of that.
- The closest commercial equivalents (CQS/UTP feeds, Polygon advanced,
  IEX paid tiers) for 6 months of multi-venue tick data on two ETFs
  are typically in the **low thousands of dollars** range when
  purchased standalone.

In other words: the local disk holds a research-grade dataset that
would cost $1k–$5k to replace if it were lost. **Back up off-machine
before doing anything destructive in the data directory.**

## Layout on disk

```
data/databento_equs_mini/                  ← raw downloads (gitignored)
  condition.json                             (Databento metadata)
  equs-mini-20251030.mbp-1.dbn.zst           (one file per trading day)
  equs-mini-20251031.mbp-1.dbn.zst
  ...
  equs-mini-20260430.mbp-1.dbn.zst

data/databento_cache/                      ← built parquet cache (gitignored)
  SPY/
    2025-10-30.parquet                       (~50 MB compressed each)
    2025-10-31.parquet
    ...
  QQQ/
    2025-10-30.parquet
    ...
```

`data/` is in `.gitignore`. The dataset never enters git. Only the
analysis OUTPUTS (scripts and markdown reports) are tracked.

## How to use it

Three tracked Python modules wrap the dataset:

| Module | Purpose |
|---|---|
| `scripts/databento_loader.py` | Reads `*.dbn.zst`, splits by (ticker, date), writes parquet cache. Provides `load_window()`, `get_trades()`, `get_quotes()` query helpers. |
| `scripts/lee_ready_classifier.py` | Lee-Ready (1991) + tick-rule classifier. `cumulative_volume_delta(trades, classifier='lee_ready')`. Compare-mode utilities. |
| `scripts/microstructure_features.py` | OFI (Cont 2014) + microprice (Bonart 2017). Vectorized. `cumulative_ofi()`, `add_microprice_columns()`, window aggregates. |

### Building the cache (one-time)

```bash
python scripts/databento_loader.py --build-cache
python scripts/databento_loader.py --status
```

Idempotent — re-runs skip already-cached (ticker, date) pairs unless
`--force` is passed.

### Querying a window

```python
from scripts.databento_loader import get_trades, get_quotes

# All SPY trades between 10:00 and 10:30 ET on 2026-04-21
trades = get_trades("SPY", "2026-04-21", "10:00", "10:30")

# All quote updates over the same window
quotes = get_quotes("SPY", "2026-04-21", "10:00", "10:30")
```

### Computing features

```python
from scripts.lee_ready_classifier import cumulative_volume_delta
from scripts.microstructure_features import cumulative_ofi, add_microprice_columns

cvd_lr = cumulative_volume_delta(trades, classifier="lee_ready")
ofi    = cumulative_ofi(quotes)
mp_df  = add_microprice_columns(quotes)   # adds mid, microprice, mp_minus_mid
```

## Audits and analyses this enables

### Stage 1 — already wired (`scripts/gate8_audit.py`)

For each of the 27 existing fires (filtered to SPY/QQQ), compares three
CVD computations: minute-bar proxy (current production), tick-level
tick-rule, tick-level Lee-Ready. Tests whether quote-based classification
predicts gated outcomes better than the proxy currently in Gate 8.

Run after cache build: `python scripts/gate8_audit.py`

### Stage 2 — paper-trade forward-test enrichment

Per `FALSIFICATION_PROTOCOL.md`, log raw stock ticks per future fire as
*passive observation only* during the 4–6 week forward experiment. After
the bootstrap delivers a verdict, regress (gated_pnl − naive_pnl) on
microstructure features to identify conditioning variables for v2.

### Stage 3 — pre-Apr-28 out-of-sample baseline (post-validation)

The structural-turn gates were first introduced on Apr 28 2026 (commit
`3a78e3a`). The Oct 30 2025 → Apr 27 2026 window is therefore *truly*
out-of-sample with respect to the gate construction process. ~125
trading days of unfit-on data is a real research asset for v2 gate
calibration **once Stages 1 and 2 validate the strategy framework**.

### Possible future research

- Microprice deviation z-score percentile distributions per ticker (for
  pre-committed thresholds in any v2 OFI/microprice gate)
- Cross-ETF microstructure correlation (does SPY OFI lead QQQ?)
- Regime-conditional OFI behavior (high-vol vs low-vol days)
- Vol-surface event-day signature in tick patterns (relates to the IV
  regime work that didn't externally validate; tick data may surface
  the same regime signal more cleanly)

## What this dataset does NOT solve

Important to keep separate from the strategy-validation question:

- **Intraday options OI history** does not exist at retail. The GEX
  backfill bias (look-ahead OI in `historical_gex_backfill.py`) is not
  fixed by having tick data on the underlying. Walk-forward backtest of
  the v1 detector remains blocked.
- **Per-venue order book reconstruction** — Mini is aggregated; we have
  the consolidated NBBO and pooled trade prints, not per-venue book
  state. Not a problem for our use case (ETF microstructure on the
  consolidated tape) but worth knowing.
- **Real-time live data** — this is historical only. Forward-testing
  during the falsification experiment will pull live ticks via either
  pay-as-you-go Databento Live or an alternative. Decide closer to the
  time.

## Operational notes

- **Backup**: not included in the GitHub repo (gitignored). If the
  local machine fails, the data is gone unless backed up. Recommended:
  copy `data/databento_equs_mini/` to an external drive or cloud
  storage at least once.
- **Don't accidentally `git add data/`** — would attempt to push 106 GB.
  The gitignore protects this, but be careful with `git add -A` style
  commands.
- **Memory profile**: each ~150 MB compressed file expands to 1–3 GB
  in pandas. The loader processes one at a time and releases each
  before the next; close memory-hungry apps during cache builds.
- **Cache build runtime**: ~1 file/min on a typical dev machine
  (single-threaded). Full 125-file build is ~2 hours.
