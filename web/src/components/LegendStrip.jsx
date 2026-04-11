import React from 'react';

/**
 * Top legend strip showing color keys. Mirrors the live app:
 *   🟨 King Node  🟩 +GEX (absorbs)  🟪 -GEX (amplifies)  🟥 Ceiling  🟩 Floor  ⬛ Air Pocket
 *   GEX$ left | VEX$ right   ⚡ Confluence   hover any row for tooltip
 */
export default function LegendStrip() {
  return (
    <div className="legend-strip">
      <span className="leg">
        <span className="dot" style={{ background: 'var(--king-pos)' }} /> King Node
      </span>
      <span className="leg">
        <span className="dot" style={{ background: 'var(--gex-pos-strong)' }} /> +GEX (absorbs)
      </span>
      <span className="leg">
        <span className="dot" style={{ background: 'var(--king-neg)' }} /> -GEX (amplifies)
      </span>
      <span className="leg">
        <span className="dot" style={{ background: 'var(--ceiling)' }} /> Ceiling
      </span>
      <span className="leg">
        <span className="dot" style={{ background: 'var(--floor)' }} /> Floor
      </span>
      <span className="leg">
        <span className="dot" style={{ background: 'rgba(255,255,255,0.1)' }} /> Air Pocket
      </span>
      <span className="leg-sep">GEX$ left | VEX$ right</span>
      <span className="leg-sep">⚡ Confluence</span>
      <span className="leg-sep">hover any row for tooltip</span>
    </div>
  );
}
