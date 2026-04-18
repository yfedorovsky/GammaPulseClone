import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

/**
 * HitRateStrip — shows forward-return hit rates for a cohort of alerts.
 *
 * Pattern borrowed from the systematic-timing tool (Saturday morning
 * screenshot):  `Day 50 · 28 prior SELLs · 1mo 46% · 3mo 77% · 6mo 92%`
 *
 * Fetches /api/stats/hit-rate with the filter you pass via the `cohort`
 * prop, renders a compact strip showing cohort size + n/hit% per horizon.
 *
 * Usage:
 *   <HitRateStrip
 *     label="BUY Sweeps ≥3 venues"
 *     cohort={{ sourceType: 'sweep', direction: 'BUY', minSweepVenues: 3 }}
 *   />
 *
 * Null-safe: when a horizon's forward date hasn't arrived yet (n=0), it
 * shows '—' instead of 0%. Auto-refreshes every 60s.
 */

const HORIZONS = ['1d', '3d', '1w', '2w', '1mo'];

function colorFor(rate) {
  if (rate == null) return 'var(--text-3)';
  if (rate >= 0.65) return '#10dc9a';  // green — strong edge
  if (rate >= 0.55) return '#7cf0c3';  // light green — positive
  if (rate >= 0.45) return 'var(--text-2)';  // gray — near coin-flip
  return '#ff9c9c';                     // red — inverse/weak
}

function fmtRate(rate, n) {
  if (rate == null || n === 0) return '—';
  return `${(rate * 100).toFixed(0)}%`;
}


export default function HitRateStrip({ label, cohort = {}, compact = false }) {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const resp = await api.hitRate(cohort);
        if (alive) { setStats(resp); setError(null); }
      } catch (e) {
        if (alive) setError(e.message || 'Hit-rate load failed');
      }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(id); };
  }, [JSON.stringify(cohort)]);

  if (error) {
    return (
      <div style={{
        padding: '6px 10px', fontSize: 10, fontFamily: 'var(--mono)',
        color: '#ff5656', background: 'rgba(255,86,86,0.06)',
        border: '1px solid rgba(255,86,86,0.2)', borderRadius: 3,
      }}>
        {label ? `${label}: ` : ''}hit-rate unavailable
      </div>
    );
  }

  if (!stats) {
    return (
      <div style={{
        padding: '6px 10px', fontSize: 10, fontFamily: 'var(--mono)',
        color: 'var(--text-3)',
      }}>
        {label ? `${label}: ` : ''}loading…
      </div>
    );
  }

  const { cohort_size, horizons, lookback_days } = stats;
  if (!cohort_size) {
    return (
      <div style={{
        padding: '6px 10px', fontSize: 10, fontFamily: 'var(--mono)',
        color: 'var(--text-3)', fontStyle: 'italic',
      }}>
        {label ? `${label}: ` : ''}no prior setups match this filter ({lookback_days}d window)
      </div>
    );
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: compact ? 10 : 16,
      padding: compact ? '4px 8px' : '6px 12px',
      fontSize: compact ? 10 : 11, fontFamily: 'var(--mono)',
      background: 'var(--bg-1)',
      border: '1px solid var(--border-faint)', borderRadius: 3,
      flexWrap: 'wrap',
    }}>
      {label && (
        <span style={{ color: 'var(--text-2)', fontWeight: 600 }}>{label}</span>
      )}
      <span style={{ color: 'var(--text-3)' }}>
        n=<b style={{ color: 'var(--text-1)' }}>{cohort_size}</b>
      </span>
      <span style={{ color: 'var(--text-3)' }}>|</span>
      {HORIZONS.map((h) => {
        const row = horizons[h] || {};
        const rate = row.rate;
        const n = row.n || 0;
        const color = colorFor(rate);
        return (
          <span key={h} style={{ color: 'var(--text-3)' }}>
            {h}: <b style={{ color, fontWeight: 700 }}>{fmtRate(rate, n)}</b>
            {n > 0 && <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 2 }}>({n})</span>}
          </span>
        );
      })}
      <span style={{ color: 'var(--text-3)', marginLeft: 'auto', fontSize: 9 }}>
        {lookback_days}d lookback
      </span>
    </div>
  );
}
