import React, { useMemo } from 'react';
import { useStore } from '../store.js';
import { fmtBig, fmtPrice, fmtStrike } from '../lib/format.js';

const MACRO_KEY = 'MACRO (ALL 200D)';

function isRealExpiration(e) {
  return typeof e === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(e);
}

// Short column label, e.g. "2026-06-17" -> "Jun17", MACRO sentinel -> "MACRO".
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function shortExpLabel(e) {
  if (!isRealExpiration(e)) return 'MACRO';
  const [, m, d] = e.split('-');
  return `${MONTHS[(+m) - 1]}${String(+d).padStart(2, '0')}`;
}

/**
 * Per-expiration GEX matrix — a 2D heatmap modeled on GammaPulse Pro.
 *
 * ROWS  = strikes (descending), centered on spot ±3%.
 * COLS  = expirations (near-dated first; optional MACRO aggregate last).
 * CELL  = that (strike, exp)'s net_gex, green (+) / red (-), intensity by |GEX|.
 *
 * Each column's KING strike (dominant +GEX) gets a gold border/glow, and a
 * per-column header shows that king + value (e.g. "740 Jun17 +381M").
 *
 * Color convention matches the existing heatmap: green = +GEX, red = -GEX.
 * Reuses the same fmtBig / fmtStrike / fmtPrice formatters as HeatmapPanel.
 */
export default function GexMatrix({ ticker, includeMacro = false }) {
  const { chains, spotPrices } = useStore();
  const data = chains[ticker];
  const spot = spotPrices[ticker] ?? data?.spot ?? null;

  // --- Columns: near-dated real expirations first, optional MACRO last. ---
  const columns = useMemo(() => {
    const expList = data?.exps || [];
    const real = expList.filter(isRealExpiration).sort(); // chronological asc
    const cols = [...real];
    if (includeMacro) {
      const macro = expList.find((e) => !isRealExpiration(e) && String(e).startsWith('MACRO')) || MACRO_KEY;
      if (data?.exp_data?.[macro]) cols.push(macro);
    }
    return cols;
  }, [data, includeMacro]);

  // --- Per-column derived facts: king strike, king value, strike->net_gex map. ---
  const colInfo = useMemo(() => {
    const ed = data?.exp_data || {};
    return columns.map((exp) => {
      const block = ed[exp] || {};
      const strikes = block.strikes || [];
      const byStrike = new Map();
      let maxAbs = 1;
      for (const s of strikes) {
        // #76: the matrix renders settled-OI GEX (net_gex_raw) for cross-
        // expiration comparability + GammaPulse Pro / OG parity — effective
        // (volume-adjusted) OI inflates 0DTE columns ~2.7x. Remap net_gex ->
        // net_gex_raw at the source so every downstream consumer (cells, king
        // value, scaling) uses settled OI. Falls back to net_gex pre-restart.
        const sr = { ...s, net_gex: (s.net_gex_raw ?? s.net_gex ?? 0) };
        byStrike.set(s.strike, sr);
        const a = Math.abs(sr.net_gex || 0);
        if (a > maxAbs) maxAbs = a;
      }
      // King = settled-OI (raw) dominant +GEX strike → matches OG. Falls back to
      // the effective-OI king if king_raw isn't present (pre-restart data).
      const king = block.king_raw || block.king || 0;
      const kingRow = byStrike.get(king);
      return {
        exp,
        king,
        kingVal: kingRow ? kingRow.net_gex : null,
        byStrike,
        maxAbs,
      };
    });
  }, [columns, data]);

  // --- Rows: union of strikes within spot ±3%, descending. ---
  const rows = useMemo(() => {
    if (!spot) {
      // No spot yet — fall back to the union of every column's strikes.
      const all = new Set();
      for (const ci of colInfo) for (const k of ci.byStrike.keys()) all.add(k);
      return [...all].sort((a, b) => b - a);
    }
    const lo = spot * 0.97;
    const hi = spot * 1.03;
    const all = new Set();
    for (const ci of colInfo) {
      for (const k of ci.byStrike.keys()) {
        if (k >= lo && k <= hi) all.add(k);
      }
    }
    return [...all].sort((a, b) => b - a); // descending (ladder style)
  }, [colInfo, spot]);

  // Where to drop the spot marker row (above the first strike < spot).
  const spotIdx = useMemo(() => {
    if (spot == null) return -1;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i] < spot) return i;
    }
    return rows.length;
  }, [rows, spot]);

  if (!data || !columns.length) {
    return (
      <div className="gex-matrix-empty">
        {data ? 'No dated expirations available for this ticker.' : `Loading ${ticker} chain…`}
      </div>
    );
  }

  // Grid template: a fixed strike-label gutter + one equal column per expiration.
  const gridTemplate = `72px repeat(${columns.length}, minmax(0, 1fr))`;

  // Cell background: same green=+ / red=- convention as the existing heatmap,
  // intensity scaled to the column's own max so each expiration is readable
  // even when a near-dated week dwarfs a far one in absolute dollars.
  const cellBg = (s, maxAbs) => {
    if (!s || !s.net_gex) return 'transparent';
    const r = Math.max(0, Math.min(1, Math.abs(s.net_gex) / (maxAbs || 1)));
    if (s.net_gex >= 0) {
      const alpha = 0.10 + r * 0.70;
      return `rgba(28, 165, 113, ${alpha.toFixed(3)})`;
    }
    const alpha = 0.10 + r * 0.65;
    return `rgba(210, 45, 60, ${alpha.toFixed(3)})`;
  };

  return (
    <div className="gex-matrix">
      {/* Title + legend */}
      <div className="gex-matrix-bar">
        <span className="gex-matrix-title">{ticker} · GEX MATRIX</span>
        <span className="gex-matrix-spot">
          spot ${fmtPrice(spot)}
        </span>
        <span className="gex-matrix-legend">
          <span style={{ color: '#1ca571' }}>■ +GEX</span>
          <span style={{ color: '#d22d3c' }}>■ −GEX</span>
          <span style={{ color: 'var(--king-pos)' }}>▣ column KING</span>
          <span style={{ color: 'var(--text-3)' }}>strikes ±3% · {columns.length} expirations</span>
        </span>
      </div>

      <div className="gex-matrix-scroll">
        {/* Header row: per-column king + value */}
        <div className="gex-matrix-grid gex-matrix-header" style={{ gridTemplateColumns: gridTemplate }}>
          <div className="gmx-corner">STRIKE</div>
          {colInfo.map((ci) => (
            <div key={ci.exp} className="gmx-colhead" title={`${ci.exp} — King ${ci.king ? fmtStrike(ci.king) : '—'} ${ci.kingVal != null ? fmtBig(ci.kingVal) : ''}`}>
              <div className="gmx-colhead-exp">{shortExpLabel(ci.exp)}</div>
              <div className="gmx-colhead-king">
                {ci.king ? (
                  <>
                    <span className="gmx-king-strike">{fmtStrike(ci.king)}</span>
                    {ci.kingVal != null && (
                      <span className={`gmx-king-val ${ci.kingVal >= 0 ? 'pos' : 'neg'}`}>
                        {fmtBig(ci.kingVal)}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="gmx-king-strike" style={{ color: 'var(--text-dim)' }}>—</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Body: one row per strike, with a spot marker inserted at spotIdx. */}
        {rows.map((strike, idx) => {
          const showSpotAbove = idx === spotIdx;
          return (
            <React.Fragment key={strike}>
              {showSpotAbove && (
                <div className="gex-matrix-grid gmx-spot-row" style={{ gridTemplateColumns: gridTemplate }}>
                  <div className="gmx-strike gmx-spot-label">${fmtPrice(spot)} ◀</div>
                  {columns.map((c) => <div key={c} className="gmx-cell gmx-spot-cell" />)}
                </div>
              )}
              <div className="gex-matrix-grid" style={{ gridTemplateColumns: gridTemplate }}>
                <div className="gmx-strike">{fmtStrike(strike)}</div>
                {colInfo.map((ci) => {
                  const s = ci.byStrike.get(strike);
                  const isKing = ci.king && Math.abs(ci.king - strike) < 0.01;
                  return (
                    <div
                      key={ci.exp}
                      className={`gmx-cell${isKing ? ' gmx-king-cell' : ''}`}
                      style={{ background: cellBg(s, ci.maxAbs) }}
                      title={s ? `${ticker} ${shortExpLabel(ci.exp)} ${fmtStrike(strike)} — ${fmtBig(s.net_gex)}${isKing ? ' · KING' : ''}` : `${fmtStrike(strike)} — no OI`}
                    >
                      {s && Math.abs(s.net_gex || 0) >= 1 ? (
                        <span className="gmx-cell-val">{fmtBig(s.net_gex)}</span>
                      ) : (
                        <span className="gmx-cell-empty">·</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </React.Fragment>
          );
        })}
        {/* Spot marker at the very bottom if spot is below every visible strike */}
        {spotIdx === rows.length && (
          <div className="gex-matrix-grid gmx-spot-row" style={{ gridTemplateColumns: gridTemplate }}>
            <div className="gmx-strike gmx-spot-label">${fmtPrice(spot)} ◀</div>
            {columns.map((c) => <div key={c} className="gmx-cell gmx-spot-cell" />)}
          </div>
        )}
      </div>
    </div>
  );
}
