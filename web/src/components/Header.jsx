import React, { useState } from 'react';
import { useStore } from '../store.js';
import AlertPanel, { useAlertCount } from './AlertPanel.jsx';

const TABS = ['HEATMAPS', 'OVERLAY', 'SCANNER', 'FLOW', 'HISTORY', 'MTF', 'EARNINGS', 'GUIDE'];
const ICONS = {
  HEATMAPS: '🔥',
  OVERLAY: '📈',
  SCANNER: '🔎',
  FLOW: '🌊',
  HISTORY: '⏪',
  MTF: '📅',
  EARNINGS: '📊',
  GUIDE: '📖',
};

function copyGexSummary() {
  const { chains, spotPrices, watchlists, activeWL } = useStore.getState();
  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];
  const lines = wl.tickers.map((t) => {
    const d = chains[t];
    if (!d) return `${t}: no data`;
    const macroKey = (d.exps || []).find((e) => e.startsWith('MACRO')) || (d.exps || [])[0];
    const ed = d.exp_data?.[macroKey] || {};
    const spot = spotPrices[t] ?? d.spot;
    return `${t} $${spot?.toFixed(2) || '-'} | ${d.signal || '-'} ${d.regime || '-'}γ | King $${ed.king || '-'} Floor $${ed.floor || '-'} Ceil $${ed.ceiling || '-'}`;
  });
  const text = `GammaPulse · ${new Date().toLocaleString()}\n${lines.join('\n')}`;
  navigator.clipboard.writeText(text).then(() => alert('Copied to clipboard'));
}

export default function Header() {
  const {
    tab, setTab, zoom, setZoom, health, streamMode,
    focus, setFocus, panels, setPanels, fpanels, setFpanels,
    strikes, setStrikes, viewMode, setViewMode,
  } = useStore();

  const marketColor = health?.market?.color || '#ff6b6b';
  const marketStatus = health?.market?.status || '--';
  const marketOpen = health?.market?.open;

  const [alertOpen, setAlertOpen] = useState(false);
  const [alertCount, clearAlerts] = useAlertCount();

  const streamBadge =
    streamMode === 'ws' ? '⚡ STREAM'
    : streamMode === 'sse' ? '⚡ STREAM'
    : streamMode === 'poll' ? '⟳ POLL'
    : '';

  return (
    <header className="header">
      <div className="logo">
        <span className="logo-mark" />
        <span className="logo-name">GammaPulse</span>
        <span className="logo-ver">PRO V1</span>
      </div>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={`tab ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
          >
            <span style={{ marginRight: 4 }}>{ICONS[t]}</span>
            {t}
          </button>
        ))}
      </nav>
      <div className="spacer" />

      {/* Inline controls — only show on HEATMAPS tab, matching original layout */}
      {tab === 'HEATMAPS' && (
        <div className="header-controls">
          <div className="ctrl-group">
            <button className={`ctrl-btn ${!focus ? 'active' : ''}`} onClick={() => setFocus(0)}>MULTI</button>
            <button className={`ctrl-btn ${focus ? 'active' : ''}`} onClick={() => setFocus(1)}>FOCUS</button>
          </div>
          {!focus ? (
            <select className="ctrl-select" value={panels} onChange={(e) => setPanels(+e.target.value)}>
              <option value={3}>3</option>
              <option value={4}>4</option>
              <option value={5}>5</option>
            </select>
          ) : (
            <select className="ctrl-select" value={fpanels} onChange={(e) => setFpanels(+e.target.value)}>
              <option value={1}>1</option>
              <option value={3}>3</option>
              <option value={5}>5</option>
            </select>
          )}
          <select className="ctrl-select" value={strikes} onChange={(e) => setStrikes(+e.target.value)}>
            {[20, 30, 40, 60, 80].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <div className="ctrl-group">
            <button className={`ctrl-btn ${viewMode === 'bars' ? 'active' : ''}`} onClick={() => setViewMode('bars')}>BARS</button>
            <button className={`ctrl-btn ${viewMode === 'profile' ? 'active' : ''}`} onClick={() => setViewMode('profile')}>PROFILE</button>
          </div>
          {streamBadge && <span className="stream-inline">{streamBadge}</span>}
        </div>
      )}

      <div className="market-badge">
        <span>{marketStatus}</span>
        <span className="market-dot" style={{ background: marketColor }} />
        <span style={{ color: marketOpen ? '#10dc9a' : '#ff5656', fontWeight: 800 }}>
          {marketOpen ? 'LIVE' : ''}
        </span>
      </div>
      <div className="zoom-group">
        <button className="header-btn" onClick={() => setZoom(Math.max(70, zoom - 10))}>−</button>
        <button className="header-btn" onClick={() => setZoom(100)}>{zoom}%</button>
        <button className="header-btn" onClick={() => setZoom(Math.min(150, zoom + 10))}>+</button>
      </div>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        <button className="header-btn" title="Flow Alerts" onClick={() => { setAlertOpen(!alertOpen); if (!alertOpen) clearAlerts(); }}>
          🔔
        </button>
        {alertCount > 0 && <span className="alert-badge">{alertCount}</span>}
        <AlertPanel open={alertOpen} onClose={() => setAlertOpen(false)} />
      </div>
      <button className="header-btn" title="Copy to clipboard" onClick={copyGexSummary}>📋</button>
      <button className="header-btn" title="Print / Save as PDF" onClick={() => window.print()}>📸</button>
      <button className="header-btn" title="Clear cache" onClick={() => location.reload()}>⟳</button>
    </header>
  );
}
