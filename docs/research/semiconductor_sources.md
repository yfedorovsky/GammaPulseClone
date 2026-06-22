---
title: "Semiconductor research source registry"
updated: "2026-06-22"
purpose: "Vetted sources for repeatable semis research — which are auto-fetchable (wired into weekend_research.py) vs Perplexity/manual-only."
---

# Semiconductor research sources

Built from the 2026-06-22 source audit (Grok + Perplexity intel passes) — see
`docs/research/semiconductor_intel_2026-06-22.md`. RSS status verified 2026-06-22.

## Auto-fetchable (wired into `scripts/weekend_research.py` SOURCES)

| Source | Region / type | RSS | Why |
|---|---|---|---|
| **DigiTimes** | Taiwan supply-chain primary | `digitimes.com/rss/daily.xml` | CoWoS/CoPoS, foundry, OSAT — best Taiwan primary that exposes RSS |
| **SK Hynix Newsroom** | Korea memory primary | `news.skhynix.com/feed/` | Official HBM4/HBM4E, NVIDIA deals — straight from the source |
| **KED Global** | Korea Economic Daily (EN) | `kedglobal.com/rss/news.xml` | Samsung/SK foundry + memory (broad biz feed — some noise) |
| **TrendForce** | Taiwan research | `trendforce.com/news/feed` | Memory spot/contract pricing, packaging, foundry |
| **SemiAnalysis** | Analysis (Patel) | `semianalysis.com/feed` | High-signal AI-infra / datacenter / packaging deep-dives |
| **EE Times** | Trade press | `eetimes.com/feed/` | Roadmaps, equipment, design |
| **SemiWiki** | Niche industry | `semiwiki.com/feed/` | EDA, IP, design ecosystem |
| **Tom's Hardware (semis tag)** | Tech press | `tomshardware.com/feeds/tag/semiconductors` | Roadmap/product reporting |
| **Global Semi Research** | Substack | `globalsemiresearch.substack.com/feed` | Memory/HBM, CPO, custom silicon takes |
| **The Diligence Stack** | Substack | `thediligencestack.com/feed` | AI-server market structure (hyperscaler/neocloud/sovereign) |

## NOT auto-fetchable — pull via Perplexity / manual

| Source | Region | Why not RSS |
|---|---|---|
| **ETNews** (en.etnews.com) | Korea | No working English RSS (404 / invalid XML) — but high-signal HBM4E/process detail |
| **ChosunBiz / Chosun Daily** | Korea | RSS returns malformed XML |
| **Seoul Economic Daily** (en.sedaily.com) | Korea | RSS endpoint returns HTML — but best **Korean ETF/flow** color (single-stock leverage) |
| **Nikkei Asia** | Japan | Paywalled; RSS is headlines-only + broad |
| **Bloomberg** | US | Paywalled; no usable free RSS (export-control, ASML, strategist takes) |
| **Sell-side (GS/MS/Citi/UBS/Bernstein/RJ)** | — | Not syndicated; reach via Yahoo/Investing/Barchart aggregation or Perplexity |

## The reusable Perplexity prompt
The 7-topic foreign-media prompt (memory/packaging/foundry/power/equipment/China/positioning,
"give me the bear takes too") lives in the chat history for 2026-06-22; re-run it weekly in
Deep Research mode to cover the manual-only sources the RSS feeds can't reach.

## Known gaps / TODO
- **Finnhub economic calendar returns 403** (premium endpoint) → no FOMC/CPI auto-flagging;
  earnings calendar works. Consider a free macro-calendar source.
- KED Global + Tom's feeds are broad (some non-semi noise); the LLM synthesis filters, but a
  per-feed keyword pre-filter could be added if noise becomes a problem.
