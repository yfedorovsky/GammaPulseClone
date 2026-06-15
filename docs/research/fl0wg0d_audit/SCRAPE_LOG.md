# FL0WG0D Scrape Log — 2026-05-13

## Scrape attempt sequence

1. **Claude in Chrome MCP** (primary) — connected to user's "Personal Chrome" device (deviceId 99a33913-406c-443f-85ba-ceadf93b4d5e). User was already logged into x.com/FL0WG0D. **Success.**

2. **JS DOM harvest pattern:**
   ```javascript
   window.__fl0w_posts = window.__fl0w_posts || {};
   function harvest() {
     document.querySelectorAll('article').forEach(a => {
       const time = a.querySelector('time');
       const link = a.querySelector('a[href*="/status/"]');
       const href = link?.getAttribute('href');
       if (!href || window.__fl0w_posts[href]) return;
       window.__fl0w_posts[href] = {
         datetime: time?.getAttribute('datetime'),
         text: a.innerText,
         img_count: a.querySelectorAll('img[alt="Image"]').length
       };
     });
   }
   ```

3. **Scroll mechanism:** X virtualizes the timeline, so `window.scrollBy()` does NOT trigger lazy-load. **Only real mouse-wheel events (via `mcp__Claude_in_Chrome__computer` scroll action) trigger new content loading.** This forced a manual scroll-harvest loop instead of a one-shot autoscroll.

4. **Display truncation:** JS exec output truncates around 1000 chars per `javascript_tool` call, regardless of returned string length. Worked around by paginating Object.entries() in chunks of 4.

5. **Subscribe gate:** ~1/3 of posts are paywalled ("Subscribe to unlock") — these are his SPY/SPX heatmap commentary, not contract-level flow. We do NOT need these for the audit (different product surface).

6. **Bullflow chart text not in DOM:** the per-contract chart (TICKER STRIKE TYPE / Exp / Ask/Bid/Mid sizes / Premium / OTM%) is canvas-rendered, not HTML text. Strike/expiry/premium had to be read off live screenshots manually during the scroll. A future industrialized version would use Claude vision (anthropic SDK) per image. The pattern from `scripts/substack_to_md.py` applies directly.

## Posts captured

67 status hrefs, of which:
- 41 contract-level alerts (audited)
- 18 commentary/heatmap/SPY context (subscribe-locked, not auditable)
- 1 repost (Vest Exchange MU $4500 overnight)
- 1 pinned (April 2 "Exclusive sh*t" subscription pitch)
- 6 misc (replies, QTs without contract content)

## Time window covered

Oldest post: 2026-05-11T14:55:57Z (AVGO 447.5C 5/15 — $646K Weekly call buyer)
Newest post: 2026-05-13T19:05:49Z (FCEL $370K Call buyer)

**52.2 hours = 2.2 trading days** out of the 7-day target.

## Trade-off rationale

7-day coverage would have required ~200+ status posts and likely 90+ minutes of pure scroll/harvest time. With a 4-6 hour audit budget total (per brief), spending more than ~1.5 hours on scrape and leaving < 3 hours for analysis was not the right shape. The 2.2-day window contains his entire 5/12 + 5/13 sessions — the same period our flow_alerts DB has freshest, most-relevant data for. Audit conclusions remain valid for "would today's scanner catch this kind of flow."
