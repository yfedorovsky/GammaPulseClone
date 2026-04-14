import React, { useEffect, useState } from 'react';
import { useStore } from '../store.js';
import { computeConfluenceBanner } from '../lib/gex.js';
import { fmtPrice } from '../lib/format.js';
import { api } from '../api.js';

const REGIME_STYLE = {
  EXTREME_OVERSOLD: { color: '#10dc9a', label: 'EXTREME OVERSOLD', emoji: '🟢' },
  OVERSOLD: { color: '#10dc9a', label: 'OVERSOLD', emoji: '🟢' },
  NEUTRAL: { color: '#8a93a8', label: 'NEUTRAL', emoji: '🟡' },
  OVERBOUGHT: { color: '#ff5656', label: 'OVERBOUGHT', emoji: '🔴' },
  EXTREME_OVERBOUGHT: { color: '#ff5656', label: 'EXTREME OB', emoji: '🔴' },
  INSUFFICIENT_DATA: { color: '#555', label: 'LOADING', emoji: '⏳' },
  NO_DATA: { color: '#555', label: 'N/A', emoji: '--' },
};

export default function ConfluenceBanner() {
  const { confluence } = useStore();
  const banner = computeConfluenceBanner(confluence);
  const pins = ['SPY', 'QQQ', 'IWM'];

  // Breadth data (NYMO/NAMO)
  const [breadth, setBreadth] = useState(null);
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await api.get('/api/breadth');
        if (alive) setBreadth(data);
      } catch {}
    }
    load();
    const iv = setInterval(load, 300_000); // Refresh every 5 min (daily indicator)
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const nymo = breadth?.nymo || {};
  const namo = breadth?.namo || {};
  const nymoStyle = REGIME_STYLE[nymo.regime] || REGIME_STYLE.NO_DATA;
  const namoStyle = REGIME_STYLE[namo.regime] || REGIME_STYLE.NO_DATA;

  return (
    <div className="confluence-banner">
      <span className={`conf-pill ${banner.cls}`}>
        {banner.label} ({banner.alignment})
      </span>

      {/* NYMO/NAMO breadth indicators */}
      {breadth && (
        <span className="breadth-indicators">
          <span className="breadth-chip" style={{ borderColor: nymoStyle.color + '40' }}>
            <span style={{ color: '#8a93a8', fontSize: 9 }}>NYMO</span>
            <span style={{ color: nymoStyle.color, fontWeight: 800 }}>{nymo.value || '--'}</span>
            {nymo.turning_up && <span style={{ color: '#10dc9a', fontSize: 9 }}>TURN</span>}
            {nymo.turning_down && <span style={{ color: '#ff5656', fontSize: 9 }}>TURN</span>}
          </span>
          <span className="breadth-chip" style={{ borderColor: namoStyle.color + '40' }}>
            <span style={{ color: '#8a93a8', fontSize: 9 }}>NAMO</span>
            <span style={{ color: namoStyle.color, fontWeight: 800 }}>{namo.value || '--'}</span>
          </span>
        </span>
      )}

      <div style={{ flex: 1 }} />
      {pins.map((t) => {
        const data = confluence?.[t];
        if (!data) return <span key={t} className="conf-detail">{t}: --</span>;
        const macroKey =
          Object.keys(data.exp_data || {}).find((k) => k.startsWith('MACRO')) ||
          Object.keys(data.exp_data || {})[0];
        const ed = data.exp_data?.[macroKey];
        const kingAbove = (ed?.king || 0) > (data.spot || 0);
        const arrow = kingAbove ? '▲' : '▼';
        const arrowColor = kingAbove ? '#10dc9a' : '#ff5656';
        return (
          <span key={t} className="conf-detail">
            <strong style={{ color: '#c8cdd8' }}>{t}</strong>: King ${ed?.king ?? '--'} <span style={{ color: arrowColor }}>{arrow}</span> Spot ${fmtPrice(data.spot)}
          </span>
        );
      })}
    </div>
  );
}
