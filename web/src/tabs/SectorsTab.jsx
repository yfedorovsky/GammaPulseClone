import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api.js';

// ---------------------------------------------------------------------------
// Treemap layout — squarified algorithm
// ---------------------------------------------------------------------------

function squarify(items, x, y, w, h) {
  // items: [{value, ...}]  returns [{...item, x, y, w, h}]
  if (!items.length) return [];
  const total = items.reduce((s, it) => s + it.value, 0);
  if (total === 0) return items.map((it) => ({ ...it, x, y, w: 0, h: 0 }));

  const result = [];
  _squarify(items.slice().sort((a, b) => b.value - a.value), x, y, w, h, total, result);
  return result;
}

function _squarify(items, x, y, w, h, total, result) {
  if (!items.length) return;
  if (items.length === 1) {
    result.push({ ...items[0], x, y, w, h });
    return;
  }

  const isWide = w >= h;
  const shortSide = isWide ? h : w;

  // Build a row along the short side
  let row = [];
  let rowSum = 0;
  let bestRatio = Infinity;

  for (let i = 0; i < items.length; i++) {
    row.push(items[i]);
    rowSum += items[i].value;
    const ratio = _worstRatio(row, rowSum, shortSide, total, w * h);
    if (i > 0 && ratio > bestRatio) {
      // Last item made it worse — pop it
      row.pop();
      rowSum -= items[i].value;
      break;
    }
    bestRatio = ratio;
  }

  // Place the row
  const rowFraction = rowSum / total;
  const rowThick = isWide ? w * rowFraction : h * rowFraction;
  let cursor = isWide ? y : x;

  for (const it of row) {
    const frac = it.value / rowSum;
    const cellLen = (isWide ? h : w) * frac;
    if (isWide) {
      result.push({ ...it, x, y: cursor, w: rowThick, h: cellLen });
      cursor += cellLen;
    } else {
      result.push({ ...it, x: cursor, y, w: cellLen, h: rowThick });
      cursor += cellLen;
    }
  }

  // Recurse on remaining items
  const remaining = items.slice(row.length);
  if (!remaining.length) return;
  const newTotal = total - rowSum;
  if (isWide) {
    _squarify(remaining, x + rowThick, y, w - rowThick, h, newTotal, result);
  } else {
    _squarify(remaining, x, y + rowThick, w, h - rowThick, newTotal, result);
  }
}

function _worstRatio(row, rowSum, shortSide, total, area) {
  const rowThick = (rowSum / total) * (area / shortSide);
  let worst = 0;
  for (const it of row) {
    const cellLen = (it.value / rowSum) * shortSide;
    const r = Math.max(rowThick / cellLen, cellLen / rowThick);
    if (r > worst) worst = r;
  }
  return worst;
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

function pctColor(pct) {
  if (pct === undefined || pct === null) return 'rgba(30,40,60,0.9)';
  const abs = Math.abs(pct);
  const intensity = Math.min(abs / 3, 1); // saturates at ±3%
  if (pct >= 0) {
    const g = Math.round(80 + 120 * intensity);
    return `rgba(0,${g},60,0.85)`;
  } else {
    const r = Math.round(100 + 120 * intensity);
    return `rgba(${r},20,20,0.85)`;
  }
}

function signalColor(signal) {
  if (!signal || signal === '–') return 'var(--text-3)';
  const s = signal.toUpperCase();
  if (s.includes('BULL') || s === 'LONG') return 'var(--accent)';
  if (s.includes('BEAR') || s === 'SHORT') return 'var(--danger)';
  return 'var(--warn)';
}

// ---------------------------------------------------------------------------
// Treemap panel
// ---------------------------------------------------------------------------

function SectorTreemap({ sectors, selectedSector, onSelect }) {
  const [dims, setDims] = useState({ w: 600, h: 300 });
  const ref = React.useRef(null);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setDims({ w: Math.max(width, 1), h: Math.max(height, 1) });
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const items = sectors.map((s) => ({ ...s, value: s.weight }));
  const cells = squarify(items, 0, 0, dims.w, dims.h);

  return (
    <div ref={ref} className="sectors-panel" style={{ position: 'relative', overflow: 'hidden' }}>
      {cells.map((cell) => {
        const isSelected = cell.ticker === selectedSector;
        return (
          <div
            key={cell.ticker}
            onClick={() => onSelect(cell.ticker)}
            style={{
              position: 'absolute',
              left: cell.x,
              top: cell.y,
              width: Math.max(cell.w - 2, 0),
              height: Math.max(cell.h - 2, 0),
              background: pctColor(cell.pct_change),
              border: isSelected
                ? '2px solid var(--accent)'
                : '1px solid rgba(0,0,0,0.5)',
              borderRadius: 4,
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
              transition: 'filter 120ms',
              filter: isSelected ? 'brightness(1.2)' : undefined,
            }}
          >
            {cell.w > 36 && cell.h > 22 && (
              <>
                <span
                  style={{
                    fontSize: Math.min(Math.max(cell.w / 8, 9), 15),
                    fontWeight: 800,
                    color: '#fff',
                    lineHeight: 1.1,
                    textShadow: '0 1px 3px rgba(0,0,0,0.8)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {cell.ticker}
                </span>
                {cell.h > 36 && (
                  <span
                    style={{
                      fontSize: Math.min(Math.max(cell.w / 10, 8), 12),
                      color: 'rgba(255,255,255,0.85)',
                      fontFamily: 'var(--mono)',
                      textShadow: '0 1px 2px rgba(0,0,0,0.9)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {cell.pct_change >= 0 ? '+' : ''}
                    {cell.pct_change?.toFixed(2) ?? '0.00'}%
                  </span>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RRG Chart
// ---------------------------------------------------------------------------

const RRG_QUAD_LABELS = [
  { text: 'Improving', qx: 0, qy: 0, color: '#3b82f6' },
  { text: 'Leading',   qx: 1, qy: 0, color: 'var(--accent)' },
  { text: 'Lagging',   qx: 0, qy: 1, color: 'var(--danger)' },
  { text: 'Weakening', qx: 1, qy: 1, color: 'var(--warn)' },
];

function RRGChart({ sectors, selectedSector, onSelect, history }) {
  // history: { [ticker]: [{rs_ratio, rs_momentum}, ...] } — last 8 points per sector
  const SVG_W = 420;
  const SVG_H = 380;
  const PAD = 40;
  const CX = PAD + (SVG_W - 2 * PAD) / 2;
  const CY = PAD + (SVG_H - 2 * PAD) / 2;
  const INNER_W = SVG_W - 2 * PAD;
  const INNER_H = SVG_H - 2 * PAD;

  // Compute axis range from data
  const allRatios = sectors.map((s) => s.rs_ratio).filter(Boolean);
  const allMoms = sectors.map((s) => s.rs_momentum).filter(Boolean);
  const ratioMin = Math.min(95, ...allRatios) - 2;
  const ratioMax = Math.max(105, ...allRatios) + 2;
  const momMin = Math.min(95, ...allMoms) - 2;
  const momMax = Math.max(105, ...allMoms) + 2;

  function toSvgX(r) {
    return PAD + ((r - ratioMin) / (ratioMax - ratioMin)) * INNER_W;
  }
  function toSvgY(m) {
    // Y is inverted: higher momentum = higher on chart
    return PAD + ((momMax - m) / (momMax - momMin)) * INNER_H;
  }

  const centerX = toSvgX(100);
  const centerY = toSvgY(100);

  return (
    <div className="sectors-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <svg width="100%" height="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ maxWidth: SVG_W, maxHeight: SVG_H }}>
        {/* Quadrant fills */}
        <rect x={PAD} y={PAD} width={centerX - PAD} height={centerY - PAD} fill="rgba(59,130,246,0.06)" />
        <rect x={centerX} y={PAD} width={PAD + INNER_W - centerX} height={centerY - PAD} fill="rgba(16,220,154,0.06)" />
        <rect x={PAD} y={centerY} width={centerX - PAD} height={PAD + INNER_H - centerY} fill="rgba(255,86,86,0.06)" />
        <rect x={centerX} y={centerY} width={PAD + INNER_W - centerX} height={PAD + INNER_H - centerY} fill="rgba(255,204,77,0.06)" />

        {/* Quadrant labels */}
        {RRG_QUAD_LABELS.map((q) => (
          <text
            key={q.text}
            x={q.qx === 0 ? PAD + 6 : PAD + INNER_W - 6}
            y={q.qy === 0 ? PAD + 14 : PAD + INNER_H - 6}
            fontSize={10}
            fill={q.color}
            fontWeight={700}
            fontFamily="var(--sans)"
            textAnchor={q.qx === 0 ? 'start' : 'end'}
            opacity={0.7}
          >
            {q.text}
          </text>
        ))}

        {/* Center crosshairs */}
        <line x1={centerX} y1={PAD} x2={centerX} y2={PAD + INNER_H} stroke="rgba(255,255,255,0.12)" strokeWidth={1} strokeDasharray="4 3" />
        <line x1={PAD} y1={centerY} x2={PAD + INNER_W} y2={centerY} stroke="rgba(255,255,255,0.12)" strokeWidth={1} strokeDasharray="4 3" />

        {/* Axis labels */}
        <text x={CX} y={SVG_H - 4} fontSize={9} fill="var(--text-3)" textAnchor="middle" fontFamily="var(--mono)">RS-Ratio (Relative Strength)</text>
        <text x={8} y={CY} fontSize={9} fill="var(--text-3)" textAnchor="middle" fontFamily="var(--mono)" transform={`rotate(-90,8,${CY})`}>RS-Momentum</text>

        {/* Sector dots + tails */}
        {sectors.map((s) => {
          const tail = (history[s.ticker] || []).slice(-8);
          const sx = toSvgX(s.rs_ratio ?? 100);
          const sy = toSvgY(s.rs_momentum ?? 100);
          const isSelected = s.ticker === selectedSector;

          // Determine quadrant color
          const inLeading = s.rs_ratio >= 100 && s.rs_momentum >= 100;
          const inImproving = s.rs_ratio < 100 && s.rs_momentum >= 100;
          const inWeakening = s.rs_ratio >= 100 && s.rs_momentum < 100;
          const dotColor = inLeading ? '#10dc9a' : inImproving ? '#3b82f6' : inWeakening ? '#ffcc4d' : '#ff5656';

          return (
            <g key={s.ticker} onClick={() => onSelect(s.ticker)} style={{ cursor: 'pointer' }}>
              {/* Tail path */}
              {tail.length >= 2 && (
                <polyline
                  points={tail.map((pt) => `${toSvgX(pt.rs_ratio ?? 100)},${toSvgY(pt.rs_momentum ?? 100)}`).join(' ')}
                  fill="none"
                  stroke={dotColor}
                  strokeWidth={1}
                  strokeOpacity={0.35}
                  strokeDasharray="none"
                />
              )}
              {/* Tail dots */}
              {tail.map((pt, ti) => (
                <circle
                  key={ti}
                  cx={toSvgX(pt.rs_ratio ?? 100)}
                  cy={toSvgY(pt.rs_momentum ?? 100)}
                  r={1.5}
                  fill={dotColor}
                  opacity={0.2 + (ti / tail.length) * 0.4}
                />
              ))}
              {/* Main dot */}
              <circle
                cx={sx}
                cy={sy}
                r={isSelected ? 8 : 6}
                fill={dotColor}
                fillOpacity={isSelected ? 0.9 : 0.7}
                stroke={isSelected ? '#fff' : dotColor}
                strokeWidth={isSelected ? 2 : 1}
              />
              {/* Label */}
              <text
                x={sx}
                y={sy - 9}
                fontSize={isSelected ? 10 : 8}
                fill="#fff"
                textAnchor="middle"
                fontWeight={isSelected ? 800 : 600}
                fontFamily="var(--sans)"
                style={{ pointerEvents: 'none' }}
              >
                {s.ticker}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Holdings Table
// ---------------------------------------------------------------------------

function HoldingsTable({ sectorDetail, loading }) {
  if (loading) {
    return (
      <div className="sectors-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
        Loading holdings...
      </div>
    );
  }
  if (!sectorDetail) {
    return (
      <div className="sectors-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
        Click a sector to view holdings
      </div>
    );
  }

  const { holdings = [], name } = sectorDetail;

  return (
    <div className="sectors-panel" style={{ overflow: 'auto' }}>
      <div className="sectors-panel-title">{name} — Top 10 Holdings</div>
      <table className="data-table" style={{ width: '100%' }}>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Spot</th>
            <th>King</th>
            <th>Signal</th>
            <th>Regime</th>
            <th>King Dist</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => (
            <tr key={h.ticker}>
              <td style={{ fontWeight: 800, color: 'var(--accent)' }}>{h.ticker}</td>
              <td style={{ fontFamily: 'var(--mono)' }}>
                {h.spot != null ? `$${h.spot.toFixed(2)}` : '–'}
              </td>
              <td style={{ fontFamily: 'var(--mono)', color: 'var(--king-pos)' }}>
                {h.king != null ? `$${Number(h.king).toFixed(2)}` : '–'}
              </td>
              <td>
                <span style={{ color: signalColor(h.signal), fontWeight: 700, fontSize: 11 }}>
                  {h.signal || '–'}
                </span>
              </td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{h.regime ?? '–'} γ</td>
              <td
                style={{
                  fontFamily: 'var(--mono)',
                  fontWeight: 700,
                  color:
                    h.king_dist == null
                      ? 'var(--text-3)'
                      : h.king_dist >= 0
                      ? 'var(--accent)'
                      : 'var(--danger)',
                }}
              >
                {h.king_dist != null
                  ? `${h.king_dist >= 0 ? '+' : ''}${h.king_dist.toFixed(2)}%`
                  : '–'}
              </td>
            </tr>
          ))}
          {!holdings.length && (
            <tr>
              <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-3)', padding: 20 }}>
                No data available
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GEX Walls panel
// ---------------------------------------------------------------------------

function GexWallsPanel({ sectorDetail, loading }) {
  if (loading) {
    return (
      <div className="sectors-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
        Loading GEX data...
      </div>
    );
  }
  if (!sectorDetail) {
    return (
      <div className="sectors-panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)' }}>
        Select a sector to view aggregate GEX
      </div>
    );
  }

  const { holdings = [], aggregate = {}, name } = sectorDetail;
  const { regime: aggRegime, king_dist: aggKingDist } = aggregate;

  const withKing = holdings.filter((h) => h.king_dist != null);
  const bulls = withKing.filter((h) => h.king_dist >= 0).length;
  const bears = withKing.filter((h) => h.king_dist < 0).length;

  const regimeColor =
    aggRegime && aggRegime !== '–'
      ? aggKingDist != null && aggKingDist >= 0
        ? 'var(--accent)'
        : 'var(--danger)'
      : 'var(--text-3)';

  return (
    <div className="sectors-panel" style={{ overflow: 'auto' }}>
      <div className="sectors-panel-title">{name} — Aggregate GEX</div>

      {/* Aggregate summary cards */}
      <div className="sectors-gex-cards">
        <div className="sectors-gex-card">
          <div
            className="sectors-gex-val"
            style={{ color: regimeColor }}
          >
            {aggRegime || '–'}
          </div>
          <div className="sectors-gex-label">AGG REGIME</div>
        </div>
        <div className="sectors-gex-card">
          <div
            className="sectors-gex-val"
            style={{
              color:
                aggKingDist == null
                  ? 'var(--text-3)'
                  : aggKingDist >= 0
                  ? 'var(--accent)'
                  : 'var(--danger)',
            }}
          >
            {aggKingDist != null
              ? `${aggKingDist >= 0 ? '+' : ''}${aggKingDist.toFixed(2)}%`
              : '–'}
          </div>
          <div className="sectors-gex-label">WTD KING DIST</div>
        </div>
        <div className="sectors-gex-card">
          <div className="sectors-gex-val" style={{ color: 'var(--accent)' }}>{bulls}</div>
          <div className="sectors-gex-label">ABOVE KING</div>
        </div>
        <div className="sectors-gex-card">
          <div className="sectors-gex-val" style={{ color: 'var(--danger)' }}>{bears}</div>
          <div className="sectors-gex-label">BELOW KING</div>
        </div>
      </div>

      {/* Horizontal bar chart: king distance per holding */}
      <div style={{ padding: '8px 14px' }}>
        <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 6, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          King Distance per Holding
        </div>
        {holdings.map((h) => {
          const dist = h.king_dist;
          const barW = dist != null ? Math.min(Math.abs(dist) * 8, 100) : 0;
          const barColor = dist == null ? 'var(--text-dim)' : dist >= 0 ? 'rgba(16,220,154,0.6)' : 'rgba(255,86,86,0.6)';
          return (
            <div key={h.ticker} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ width: 46, fontSize: 10, fontWeight: 700, color: 'var(--text-2)', fontFamily: 'var(--mono)', textAlign: 'right', flexShrink: 0 }}>
                {h.ticker}
              </span>
              <div style={{ flex: 1, height: 12, background: 'rgba(255,255,255,0.04)', borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
                {dist != null && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 0,
                      [dist >= 0 ? 'left' : 'right']: '50%',
                      width: `${barW / 2}%`,
                      height: '100%',
                      background: barColor,
                      borderRadius: 2,
                    }}
                  />
                )}
                <div style={{ position: 'absolute', left: '50%', top: 0, width: 1, height: '100%', background: 'rgba(255,255,255,0.15)' }} />
              </div>
              <span
                style={{
                  width: 52,
                  fontSize: 10,
                  fontFamily: 'var(--mono)',
                  fontWeight: 700,
                  color: dist == null ? 'var(--text-3)' : dist >= 0 ? 'var(--accent)' : 'var(--danger)',
                  textAlign: 'right',
                  flexShrink: 0,
                }}
              >
                {dist != null ? `${dist >= 0 ? '+' : ''}${dist.toFixed(1)}%` : '–'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main SectorsTab
// ---------------------------------------------------------------------------

export default function SectorsTab() {
  const [sectors, setSectors] = useState([]);
  const [selectedSector, setSelectedSector] = useState(null);
  const [sectorDetail, setSectorDetail] = useState(null);
  const [loadingSectors, setLoadingSectors] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  // RRG history: {[ticker]: [{rs_ratio, rs_momentum}]} built from successive fetches
  const [rrgHistory, setRrgHistory] = useState({});

  const loadSectors = useCallback(async () => {
    setLoadingSectors(true);
    try {
      const d = await api.sectors();
      const secs = d.sectors || [];
      setSectors(secs);
      // Append to RRG history for tails
      setRrgHistory((prev) => {
        const next = { ...prev };
        for (const s of secs) {
          const tail = prev[s.ticker] || [];
          const last = tail[tail.length - 1];
          if (!last || last.rs_ratio !== s.rs_ratio || last.rs_momentum !== s.rs_momentum) {
            next[s.ticker] = [...tail, { rs_ratio: s.rs_ratio, rs_momentum: s.rs_momentum }].slice(-8);
          }
        }
        return next;
      });
    } catch (e) {
      console.warn('sectors load error', e);
    } finally {
      setLoadingSectors(false);
    }
  }, []);

  const loadDetail = useCallback(async (sector) => {
    if (!sector) return;
    setLoadingDetail(true);
    try {
      const d = await api.sectorDetail(sector);
      setSectorDetail(d);
    } catch (e) {
      console.warn('sector detail error', e);
      setSectorDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  // Initial load + 5-min refresh
  useEffect(() => {
    loadSectors();
    const iv = setInterval(loadSectors, 300_000);
    return () => clearInterval(iv);
  }, [loadSectors]);

  // Load detail when selection changes
  useEffect(() => {
    if (selectedSector) {
      loadDetail(selectedSector);
      const iv = setInterval(() => loadDetail(selectedSector), 300_000);
      return () => clearInterval(iv);
    }
  }, [selectedSector, loadDetail]);

  const handleSelectSector = useCallback((ticker) => {
    setSelectedSector((prev) => (prev === ticker ? null : ticker));
  }, []);

  return (
    <div className="sectors-root">
      {/* Control bar */}
      <div className="ctrl-bar" style={{ gap: 14 }}>
        <strong style={{ fontSize: 15, marginRight: 6 }}>Sector Rotation</strong>
        <div style={{ flex: 1 }} />
        {selectedSector && (
          <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 700 }}>
            {selectedSector} selected
          </span>
        )}
        <button className="header-btn" onClick={loadSectors} disabled={loadingSectors}>
          {loadingSectors ? 'Loading...' : '⟳ Refresh'}
        </button>
      </div>

      {/* 2×2 grid */}
      <div className="sectors-grid">
        {/* Top-left: Treemap */}
        <div className="sectors-cell">
          <div className="sectors-cell-header">
            <span className="sectors-cell-title">S&amp;P 500 Sector Weights</span>
            <span className="sectors-cell-hint">Size = weight · Color = 1-day %chg · Click to select</span>
          </div>
          <SectorTreemap
            sectors={sectors}
            selectedSector={selectedSector}
            onSelect={handleSelectSector}
          />
        </div>

        {/* Top-right: RRG */}
        <div className="sectors-cell">
          <div className="sectors-cell-header">
            <span className="sectors-cell-title">Relative Rotation Graph</span>
            <span className="sectors-cell-hint">X = RS-Ratio · Y = RS-Momentum · 8-pt tail</span>
          </div>
          <RRGChart
            sectors={sectors}
            selectedSector={selectedSector}
            onSelect={handleSelectSector}
            history={rrgHistory}
          />
        </div>

        {/* Bottom-left: Holdings table */}
        <div className="sectors-cell">
          <div className="sectors-cell-header">
            <span className="sectors-cell-title">
              {sectorDetail ? `${sectorDetail.name} Holdings` : 'Holdings'}
            </span>
            <span className="sectors-cell-hint">Top 10 · GEX from cache</span>
          </div>
          <HoldingsTable sectorDetail={sectorDetail} loading={loadingDetail} />
        </div>

        {/* Bottom-right: GEX walls */}
        <div className="sectors-cell">
          <div className="sectors-cell-header">
            <span className="sectors-cell-title">
              {sectorDetail ? `${sectorDetail.name} GEX Walls` : 'GEX Walls'}
            </span>
            <span className="sectors-cell-hint">Weighted aggregate · King distance</span>
          </div>
          <GexWallsPanel sectorDetail={sectorDetail} loading={loadingDetail} />
        </div>
      </div>
    </div>
  );
}
