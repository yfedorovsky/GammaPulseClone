import React from 'react';

export default function GuideTab() {
  return (
    <div className="guide">
      <h1>GammaPulse Guide</h1>
      <p className="text-dim">
        A clone of GammaPulse Pro's documentation panel. Use this as a cheat sheet while viewing
        live heatmaps.
      </p>

      <h2>What is GammaPulse?</h2>
      <p>
        GammaPulse visualizes how market makers are positioned across 300+ tickers in real time.
        It translates Gamma Exposure (GEX) and Vanna Exposure (VEX) into a heatmap showing where
        price is likely to be attracted, repelled, or pinned before the move happens.
      </p>

      <h2>Node types &amp; colors</h2>
      <table>
        <thead>
          <tr>
            <th>Node</th>
            <th>Meaning</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>👑 +GEX King (gold row)</td>
            <td>Highest positive GEX. Price magnetically attracted here. Support / magnet.</td>
          </tr>
          <tr>
            <td>👑 −GEX King (purple row)</td>
            <td>Highest negative GEX. Dealers amplify moves here. Resistance / rejection.</td>
          </tr>
          <tr>
            <td>🚪 Gatekeeper (purple tinted)</td>
            <td>Top GEX intensity strikes. Breaking through one is a structural move.</td>
          </tr>
          <tr>
            <td>▲ Ceiling (red dash)</td>
            <td>Strongest +GEX above spot. Dealers sell here — price resistance.</td>
          </tr>
          <tr>
            <td>▼ Floor (green dash)</td>
            <td>Strongest +GEX below spot. Dealers buy here — price support.</td>
          </tr>
          <tr>
            <td>◀ Spot (white box)</td>
            <td>Live spot price. Flashes on price change.</td>
          </tr>
          <tr>
            <td>ZGL (red dotted)</td>
            <td>Zero Gamma Line. Above = stable. Below = volatile.</td>
          </tr>
        </tbody>
      </table>

      <h2>Signals</h2>
      <table>
        <thead>
          <tr>
            <th>Signal</th>
            <th>Meaning</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>▲ MAGNET UP</td><td>+GEX King above spot. Price pulled upward toward king.</td></tr>
          <tr><td>▼ AIR POCKET</td><td>−GEX King below spot. Breakdown risk elevated.</td></tr>
          <tr><td>◆ PINNING</td><td>Price within 0.3% of +GEX King. Sell premium.</td></tr>
          <tr><td>▼ SUPPORT</td><td>+GEX King below spot. Dips get bought.</td></tr>
          <tr><td>▼ RESISTANCE</td><td>−GEX King above spot. Rips get sold.</td></tr>
          <tr><td>⚠ DANGER</td><td>Price at −GEX King. Volatility expansion imminent.</td></tr>
        </tbody>
      </table>

      <h2>How to read the heatmap</h2>
      <ol>
        <li><strong>Check the king color first.</strong> Gold = support/magnet. Purple = resistance.</li>
        <li><strong>Check the regime.</strong> POS γ = range-bound. NEG γ = trending/volatile.</li>
        <li><strong>Identify floor and ceiling.</strong> Green and red dashed lines define your expected range.</li>
        <li><strong>Look for the strongest green below spot.</strong> That's your support. Brighter = stronger.</li>
        <li><strong>Check the ZGL.</strong> Red dotted. Above = stable. Below = volatile.</li>
        <li><strong>Look for air pockets.</strong> Barely-visible rows. Price accelerates through these.</li>
        <li><strong>Cross-reference MTF.</strong> If weekly and monthly kings disagree, reduce conviction.</li>
      </ol>

      <h2>Tabs reference</h2>
      <ul>
        <li><strong>HEATMAPS</strong> — The main view. MULTI = 3-5 tickers side by side. FOCUS = one ticker across multiple expirations.</li>
        <li><strong>OVERLAY</strong> — Candlestick chart with GEX price lines, orbs, mini heatmap sidebar.</li>
        <li><strong>SCANNER</strong> — 300+ ticker sortable table. Click a row for MTF side panel.</li>
        <li><strong>FLOW</strong> — Unusual volume scanner (vol/OI ≥ 2×) plus per-ticker flow detail.</li>
        <li><strong>HISTORY</strong> — Scrub through past snapshots recorded by the worker every cycle.</li>
        <li><strong>MTF</strong> — Multi-timeframe comparison of king/floor/ceiling across expirations.</li>
        <li><strong>GUIDE</strong> — This page.</li>
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
        This clone uses <strong>Tradier</strong> as the options data provider. The backend worker
        refreshes tier-1 tickers every cycle (~5 minutes), tier-2 every 2 cycles, and tier-3 every 4 cycles.
        Per-strike GEX is computed as <code>gamma × OI × 100 × spot² × 0.01</code>, signed by
        dealer side (long calls / short puts convention). VEX uses <code>vanna × OI × 100 × spot</code>.
      </p>
    </div>
  );
}
