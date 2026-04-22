import React from 'react';

// Icon-grid reference cards (OG-style). Each entry renders as a compact
// card: color-accented icon on the left, name + one-line meaning on the
// right. Faster to scan than a long two-column table, and each card
// visually ties to the color you actually see in the heatmap rows.

const NODE_TYPES = [
  {
    icon: '★',
    accent: '#f4c430',
    accentBg: 'rgba(244, 196, 48, 0.14)',
    name: '+GEX King',
    aka: 'gold row',
    desc: 'Largest positive gamma cluster. Dealers pull price toward this strike — acts as magnet / support.',
  },
  {
    icon: '◄',
    accent: '#ff69b4',
    accentBg: 'rgba(255, 105, 180, 0.14)',
    name: '−GEX King',
    aka: 'pink row',
    desc: 'Largest negative gamma cluster. Dealers amplify moves here — whipsaw / acceleration zone.',
  },
  {
    icon: '◆',
    accent: '#bb7cff',
    accentBg: 'rgba(162, 77, 255, 0.14)',
    name: 'Gatekeeper',
    aka: 'violet row',
    desc: 'Top GEX-intensity strikes after the king. Breaking through one signals a structural move.',
  },
  {
    icon: '▲',
    accent: '#ff5656',
    accentBg: 'rgba(255, 86, 86, 0.12)',
    name: 'Ceiling',
    aka: 'red dash above',
    desc: 'Strongest +GEX above spot. Dealers sell here — price resistance on the way up.',
  },
  {
    icon: '▼',
    accent: '#10dc9a',
    accentBg: 'rgba(16, 220, 154, 0.12)',
    name: 'Floor',
    aka: 'green dash below',
    desc: 'Strongest +GEX below spot. Dealers buy here — price support on the way down.',
  },
  {
    icon: '◀',
    accent: '#ffffff',
    accentBg: 'rgba(255, 255, 255, 0.08)',
    name: 'Spot',
    aka: 'white marker',
    desc: 'Live spot price. Flashes briefly on change. Position on the strike ladder tells you the setup.',
  },
  {
    icon: '⚡',
    accent: '#ffd84d',
    accentBg: 'rgba(255, 216, 77, 0.12)',
    name: 'Confluence Bolt',
    aka: 'on king row',
    desc: 'High-conviction strike where GEX + VEX + OI agree on direction. Highest-signal node.',
  },
  {
    icon: '⌁',
    accent: '#ff3e3e',
    accentBg: 'rgba(255, 62, 62, 0.12)',
    name: 'ZGL',
    aka: 'red dotted line',
    desc: 'Zero Gamma Line. Above = dealers long gamma / stable. Below = short gamma / volatile.',
  },
];

const SIGNALS = [
  { icon: '▲', accent: '#10dc9a', name: 'MAGNET UP',   desc: '+GEX King above spot. Price pulled upward toward the king.' },
  { icon: '▼', accent: '#bb7cff', name: 'AIR POCKET',  desc: '−GEX King below spot. Breakdown risk elevated.' },
  { icon: '◆', accent: '#f4c430', name: 'PINNING',     desc: 'Price within 0.3% of +GEX King. Sell premium.' },
  { icon: '▼', accent: '#10dc9a', name: 'SUPPORT',     desc: '+GEX King below spot. Dips get bought.' },
  { icon: '▼', accent: '#ff9090', name: 'RESISTANCE',  desc: '−GEX King above spot. Rips get sold.' },
  { icon: '⚠', accent: '#ff5656', name: 'DANGER',      desc: 'Price at −GEX King. Volatility expansion imminent.' },
];

function RefCard({ item }) {
  return (
    <div className="ref-card">
      <div
        className="ref-card-icon"
        style={{ color: item.accent, background: item.accentBg, boxShadow: `inset 0 0 0 1px ${item.accent}33` }}
      >
        {item.icon}
      </div>
      <div className="ref-card-body">
        <div className="ref-card-name">
          {item.name}
          {item.aka && <span className="ref-card-aka"> · {item.aka}</span>}
        </div>
        <div className="ref-card-desc">{item.desc}</div>
      </div>
    </div>
  );
}

export default function GuideTab() {
  return (
    <div className="guide">
      <h1>GammaPulse Guide</h1>
      <p className="text-dim">
        Cheat sheet for reading the heatmap. Scan the cards below while watching live levels.
      </p>

      <h2>Node types &amp; colors</h2>
      <div className="ref-grid">
        {NODE_TYPES.map((n) => <RefCard key={n.name} item={n} />)}
      </div>

      <h2>Signals</h2>
      <div className="ref-grid">
        {SIGNALS.map((s) => <RefCard key={s.name} item={s} />)}
      </div>

      <h2>How to read the heatmap</h2>
      <ol>
        <li><strong>Check the king color first.</strong> Gold = positive magnet. Pink = negative acceleration zone.</li>
        <li><strong>Check the regime.</strong> POS γ = range-bound. NEG γ = trending / volatile.</li>
        <li><strong>Identify floor and ceiling.</strong> Green and red dashed lines define the expected range.</li>
        <li><strong>Look for the strongest green below spot.</strong> That's your support. Brighter = stronger.</li>
        <li><strong>Check the ZGL.</strong> Red dotted. Above = stable. Below = volatile.</li>
        <li><strong>Look for air pockets.</strong> Barely-visible rows. Price accelerates through these.</li>
        <li><strong>Cross-reference MTF.</strong> If weekly and monthly kings disagree, reduce conviction.</li>
      </ol>

      <h2>Tabs reference</h2>
      <ul>
        <li><strong>HEATMAPS</strong> — The main view. MULTI = 3-5 tickers side by side. FOCUS = one ticker across multiple expirations.</li>
        <li><strong>OVERLAY</strong> — Candlestick chart with GEX price lines, orbs, mini heatmap sidebar.</li>
        <li><strong>SCANNER</strong> — 300+ ticker sortable table. Click a row for the big-price side panel.</li>
        <li><strong>FLOW</strong> — Unusual volume scanner (vol/OI ≥ 2×) plus per-ticker flow detail.</li>
        <li><strong>BIG FLOW</strong> — UW-style per-contract daily aggregator with GOLDEN / TAIL grading.</li>
        <li><strong>SECTORS</strong> — SPDR treemap + Relative Rotation Graph.</li>
        <li><strong>CALENDAR</strong> — Earnings + macro events for the current week (today column highlighted).</li>
        <li><strong>SIGNALS</strong> — SOE 5-factor engine with discipline layer.</li>
        <li><strong>SWEEPS / SWINGS / HISTORY / MTF / NEWS</strong> — specialized drills.</li>
      </ul>

      <h2>Controls</h2>
      <ul>
        <li><strong>MULTI / FOCUS</strong> — Toggle between multi-ticker and multi-expiration mode.</li>
        <li><strong>Strike window (20/30/40/60/80)</strong> — How many nearest strikes to render.</li>
        <li><strong>BARS / PROFILE</strong> — Colored row heatmap vs horizontal bar profile view.</li>
        <li><strong>Watchlist tabs</strong> — Click to switch groups. Double-click to rename. ✎ Edit to reorder/remove.</li>
        <li><strong>− 100% +</strong> — Font zoom.</li>
      </ul>

      <h2>Backend &amp; data</h2>
      <p>
        Options data from <strong>Tradier</strong> (chain + OI) and <strong>ThetaData</strong> (live
        greeks + NBBO). Per-strike GEX is computed as{' '}
        <code>γ × activity-weighted OI × 100 × S² × 0.01</code>, signed by dealer side
        (long calls / short puts convention). v4 methodology bifurcates KING into positive magnet
        and negative acceleration zones (see the <code>ⓘ</code> tooltip on any heatmap panel).
      </p>
    </div>
  );
}
