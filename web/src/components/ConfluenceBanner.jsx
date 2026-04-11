import React from 'react';
import { useStore } from '../store.js';
import { computeConfluenceBanner } from '../lib/gex.js';
import { fmtPrice } from '../lib/format.js';

export default function ConfluenceBanner() {
  const { confluence } = useStore();
  const banner = computeConfluenceBanner(confluence);
  const pins = ['SPY', 'QQQ', 'IWM'];

  return (
    <div className="confluence-banner">
      <span className={`conf-pill ${banner.cls}`}>
        ⚡ {banner.label} ({banner.alignment})
      </span>
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
