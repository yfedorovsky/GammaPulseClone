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

## Pending anchor — one hard wire number

The chunked 5-day top-off (06-10 → 06-16) runs after the 16:05 ET close (it
yields the terminal to the live system during RTH). Its real wall-clock + exact
request count land here when it completes — the concrete half of the wire
comparison, against which the flat-file's 5-requests-vs-thousands is the
structural argument.

> _chunked 5-day top-off: <pending post-close run>_

## Bottom line

- **Processing:** polars/parquet is a real 104× / 33×-smaller win for the query
  layer — worth adopting if this cache becomes a general backtest platform.
- **Pull:** the fetch bottleneck is the wire, and the fix is flat-file bulk
  download (a Pro-service rebuild), not a storage swap.
- Priority: the rebuild waits on the platform decision; the next real research
  cycle (the pre-registered sector/regime-neutral whale test) outranks parquet
  plumbing. This benchmark was the cheap, contained measurement — banked and
  reproducible.
