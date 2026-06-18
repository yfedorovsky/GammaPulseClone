# Storage / ops benchmark — polars vs SQLite, and why the fetch was slow

A contained measurement prompted by a "polars is a game-changer for storing/
processing" suggestion. The honest split is **wire ≠ store**: polars helps the
*processing* (query layer), but it cannot help the *pull* (the network/terminal
fetch), which was the actual bottleneck in building the chain cache.

## Measured — the query layer (polars/parquet vs SQLite)

WHALE-candidate scan over the **full 25.3M-row chain cache** (`chains.db`),
identical filter (live signature gates: notional ≥ $3M, vol ≥ 500, vol ≥ 0.30·OI,
index/levered ETFs excluded). Reproduce: `scripts/bench_polars_vs_sqlite.py`.

| Path | Time | Result |
|---|---|---|
| SQLite — current per-row `signature_scan` path | **17.65 s** | 60,223 candidates |
| polars — parquet, vectorized lazy scan | **0.17 s** | 60,223 (identical) |

- **104× faster** on the hot scan path, results bit-identical.
- **151 MB parquet vs 5.0 GB SQLite → ~33× smaller on disk** (columnar
  compression; the scan-relevant 10 columns).
- One-time `sqlite → parquet` export: **105 s** (25.3M rows).

This is real and durable: any future algo that backtests off this cache pays the
17.6 s scan today; the parquet path pays 0.17 s. The query-layer win is genuine.

## Wire ≠ store — what polars does NOT fix

The chain cache took three nights to build, and **none of that was storage**. It
was the wire: ThetaData range-latency is superlinear per ROW (~5–8 ms server-
side) on both EOD endpoints, the terminal serializes heavy requests, plus per-
request setup × thousands of requests. Polars writes/reads faster locally, but
the bytes still arrive from the terminal at the same rate — **a faster store
cannot speed up a slower pull.**

The thing that *would* cut the pull is **flat-file bulk download**: ThetaData
Pro's `option_flat_file_eod(date)` returns the entire market's option EOD for one
day in a single request. The 5-day top-off would then be **5 market-wide
requests + a local filter**, versus the chunked path's **thousands** of targeted
per-(root × expiration × week) requests. Collapsing thousands of requests to a
handful directly attacks the measured per-request bottleneck.

**Not measured here, and honestly so.** The flat-file is a separate Pro bulk
service, not the local terminal's v3 REST (every terminal route requires
symbol+expiration). It's reachable only via the MCP flat-file tool, whose result
streams a whole-market day (~1.5M rows / ~150 MB) — too large to ingest and
time cleanly from this position, with no disk-pipe REST route to `curl -o`. So
the flat-file win is **structurally sound but unmeasured**; quoting a wall-clock
for it would be inventing a number. It is a **rebuild** (flat-file → parquet →
polars query layer), not a config flip.

## Wire anchor — and an honest correction (the bottleneck was partly self-inflicted)

The 5-day top-off (06-10 → 06-16) gave the hard wire numbers — and reading the
ThetaData docs to the end exposed that **I built the fetcher the slow way.** Two
in-API levers I wasn't using:

1. **`expiration=*` bulk wildcard** (docs: option history returns bulk data when
   strike/right omitted, and bulk expiration with `expiration=*`). One single-day
   request returns a root's ENTIRE chain (all ~25 expirations); I was looping
   per-expiration. Measured: AMD 5-day top-off = **10 requests** (`expiration=*`,
   both endpoints) vs **~100** per-expiration.
2. **PRO = 8 concurrent requests, NOT rate-limited** (docs). I'd made the fetch
   serial after an early parallel attempt failed — but that was the urllib
   socket-hang (since fixed) + RTH contention, not a real limit. Re-measured at
   6 workers: **36/36 OK, 7.4 req/s**.

| 5-day top-off | requests | wall-clock | result |
|---|---|---|---|
| per-expiration, serial (what I built) | ~thousands | **12+ hr** (never finished unattended) | 75/116 roots after a night |
| **`expiration=*` bulk + 6 concurrent** | **1,480** | **87.6 s** | 149/150 roots, 3.59M rows, 0 fail |

A **~500× wall-clock improvement, all in-API** — no flat-file, no rebuild. The
"wire bottleneck" framing was right that the wire dominates, but wrong to imply
the chunked path was near the API's ceiling: it wasn't using `expiration=*` or
concurrency. Honest version: **most of the slowness was self-inflicted; the
in-API ceiling is minutes, not hours.** Default fetch is now `--bulk`
(`fetch_universe_bulk`).

Flat-file (`option_flat_file_eod`) is still the play for a WHOLE-MARKET scan (all
~1.5M contracts/day in one request) — but for a targeted universe, `expiration=*`
+ concurrency closes nearly all of that gap without leaving the local terminal.

## Bottom line

- **Processing:** polars/parquet is a real 104× / 33×-smaller win for the query
  layer — worth adopting if this cache becomes a general backtest platform.
- **Pull:** the wire dominates, but the fix was mostly **using ThetaData
  properly** (`expiration=*` + PRO's 8 concurrent) — a ~500× in-API speedup, not
  a storage swap and not (for a targeted universe) flat-file. Flat-file remains
  the whole-market play.
- Priority: the next real research cycle (the pre-registered sector/regime-
  neutral whale test) outranks any further plumbing. These benchmarks were the
  cheap, contained measurements — banked and reproducible
  (`scripts/bench_polars_vs_sqlite.py`, `run_historical_replay.py --bulk`).
