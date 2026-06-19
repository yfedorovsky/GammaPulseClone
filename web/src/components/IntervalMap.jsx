import React, { useEffect, useRef, useState, useMemo } from 'react';
import { useStore } from '../store.js';
import { fmtPrice, fmtStrike } from '../lib/format.js';

/**
 * INTERVAL MAP — time × strike exposure bubbles (Quant-Data-style), built live.
 *
 * Samples the focus ticker's per-strike exposure (GEX/DEX/VEX/CEX) on an interval
 * and accumulates a rolling time series, rendering a bubble grid: x = time,
 * y = strike, bubble size = |exposure|, green = positive / red = negative.
 * "Difference" mode shows the CHANGE per interval (new flow) — the friend's view.
 *
 * HONEST FRAMING (badged in the UI): this is a CONTEXT / monitoring tool. We tested
 * the predictive versions on the real SPX 0DTE tape (docs/research/
 * DEX_INTRADAY_FINDINGS.md): intraday flow does NOT lead price (coincident), and
 * the "fresh bubbles attract price / magnet" claim is FALSIFIED vs a distance-
 * matched control. So: great for seeing WHAT IS HAPPENING, not for forecasting.
 */
const METRICS = [
  { key: 'net_gex', label: 'GEX' }, { key: 'net_delta', label: 'DEX' },
  { key: 'net_vex', label: 'VEX' }, { key: 'net_cex', label: 'CEX' },
];
const SAMPLE_MS = 45000;
const MAX_COLS = 48;
const POS = '#1ca571', NEG = '#d22d3c';

function isRealExp(e) { return typeof e === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(e); }

export default function IntervalMap({ ticker }) {
  const { chains, spotPrices } = useStore();
  const [metric, setMetric] = useState('net_delta');
  const [mode, setMode] = useState('raw');     // 'raw' | 'diff'
  const [snaps, setSnaps] = useState([]);      // [{t, ts, byStrike:{k:{gex,dex,vex,cex}}}]
  const lastTs = useRef(null);

  const data = chains[ticker];
  const spot = spotPrices[ticker] ?? data?.spot ?? null;
  const exp = useMemo(() => {
    const reals = (data?.exps || []).filter(isRealExp).sort();
    return reals[0] || null;   // front / 0DTE for indices
  }, [data]);

  // sample the store's per-strike exposure on an interval (no extra network —
  // HeatmapsTab already refreshes chains[ticker])
  useEffect(() => {
    setSnaps([]); lastTs.current = null;
    const sample = () => {
      const d = useStore.getState().chains[ticker];
      const ed = d?.exp_data?.[exp];
      if (!ed?.strikes?.length) return;
      if (d.timestamp && d.timestamp === lastTs.current) return; // no new data
      lastTs.current = d.timestamp;
      const byStrike = {};
      for (const s of ed.strikes) {
        byStrike[s.strike] = {
          net_gex: s.net_gex || 0, net_delta: s.net_delta || 0,
          net_vex: s.net_vex || 0, net_cex: s.net_cex || 0,
        };
      }
      setSnaps((prev) => [...prev, {
        t: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        byStrike,
      }].slice(-MAX_COLS));
    };
    sample();
    const iv = setInterval(sample, SAMPLE_MS);
    return () => clearInterval(iv);
  }, [ticker, exp]);

  // strike axis: near-spot union across snapshots
  const strikes = useMemo(() => {
    if (!snaps.length || !spot) return [];
    const lo = spot * 0.97, hi = spot * 1.03;
    const all = new Set();
    for (const sn of snaps) for (const k of Object.keys(sn.byStrike)) {
      const kk = +k; if (kk >= lo && kk <= hi) all.add(kk);
    }
    return [...all].sort((a, b) => b - a);
  }, [snaps, spot]);

  // value grid (raw or diff) + max for scaling
  const { grid, maxAbs } = useMemo(() => {
    const g = snaps.map((sn, ci) => {
      const prev = ci > 0 ? snaps[ci - 1].byStrike : null;
      const col = {};
      for (const k of strikes) {
        const cur = sn.byStrike[k]?.[metric] || 0;
        col[k] = mode === 'diff' ? cur - (prev?.[k]?.[metric] || 0) : cur;
      }
      return col;
    });
    let mx = 1;
    for (const col of g) for (const k of strikes) mx = Math.max(mx, Math.abs(col[k]));
    return { grid: g, maxAbs: mx };
  }, [snaps, strikes, metric, mode]);

  if (!data) return <div style={{ padding: 20, color: 'var(--text-3)' }}>Loading {ticker}…</div>;

  const W = 1000, padL = 64, padR = 12, padT = 8, padB = 22;
  const cols = Math.max(snaps.length, 1);
  const cellW = (W - padL - padR) / Math.max(cols, 12);
  const rowH = 16, H = padT + padB + strikes.length * rowH;
  const cx = (ci) => padL + cellW * (ci + 0.5);
  const cy = (ri) => padT + rowH * (ri + 0.5);
  const spotRow = spot == null ? -1 : strikes.findIndex((s) => s < spot);

  return (
    <div style={{ padding: '6px 0', height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 800 }}>{ticker} · INTERVAL MAP</span>
        <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{exp || '—'} · spot ${fmtPrice(spot)}</span>
        <div style={{ display: 'flex', gap: 2, marginLeft: 6 }}>
          {METRICS.map((m) => (
            <button key={m.key} onClick={() => setMetric(m.key)} className="ctrl-btn"
              style={{ fontSize: 9, fontWeight: 700, color: metric === m.key ? '#10dc9a' : 'var(--text-3)',
                background: metric === m.key ? 'rgba(16,220,154,0.12)' : 'transparent' }}>{m.label}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 2 }}>
          {['raw', 'diff'].map((md) => (
            <button key={md} onClick={() => setMode(md)} className="ctrl-btn"
              style={{ fontSize: 9, fontWeight: 700, color: mode === md ? '#f4c430' : 'var(--text-3)',
                background: mode === md ? 'rgba(244,196,48,0.12)' : 'transparent' }}>
              {md === 'raw' ? 'RAW' : 'DIFFERENCE'}</button>
          ))}
        </div>
        <span style={{ fontSize: 8.5, color: 'var(--text-3)', fontStyle: 'italic', marginLeft: 'auto', maxWidth: 320, textAlign: 'right' }}>
          context / monitoring — NOT a predictor (intraday flow tested coincident; "magnet" claim falsified)
        </span>
      </div>
      {snaps.length < 2 ? (
        <div style={{ padding: 24, color: 'var(--text-3)', fontSize: 12 }}>
          Accumulating snapshots… the map fills in live (sample every {SAMPLE_MS / 1000}s). Leave it open during RTH.
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
          {strikes.map((k, ri) => (
            <text key={`y${k}`} x={padL - 6} y={cy(ri) + 3} textAnchor="end"
              fontSize="9" fontFamily="var(--mono)" fill="var(--text-3)">{fmtStrike(k)}</text>
          ))}
          {spotRow >= 0 && (
            <line x1={padL} x2={W - padR} y1={padT + rowH * spotRow} y2={padT + rowH * spotRow}
              stroke="#f4c430" strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
          )}
          {grid.map((col, ci) => strikes.map((k, ri) => {
            const v = col[k] || 0;
            if (!v) return null;
            const r = Math.max(1.2, Math.sqrt(Math.abs(v) / maxAbs) * (rowH / 2 + 1));
            return <circle key={`${ci}-${k}`} cx={cx(ci)} cy={cy(ri)} r={r}
              fill={v >= 0 ? POS : NEG} opacity="0.85" />;
          }))}
          {snaps.map((sn, ci) => (ci % 4 === 0 || ci === snaps.length - 1) && (
            <text key={`x${ci}`} x={cx(ci)} y={H - 6} textAnchor="middle" fontSize="8" fill="var(--text-3)">{sn.t}</text>
          ))}
        </svg>
      )}
    </div>
  );
}
