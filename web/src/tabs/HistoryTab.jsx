import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import { fmtBig, fmtPrice, fmtIV } from '../lib/format.js';

export default function HistoryTab() {
  const [ticker, setTicker] = useState('SPY');
  const [series, setSeries] = useState([]);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(false);

  async function load(t = ticker) {
    setLoading(true);
    try {
      const data = await api.history(t);
      setSeries(data.series || []);
      setIdx((data.series || []).length - 1);
    } catch {
      setSeries([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = series[idx];

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%' }}>
      <div className="ctrl-bar">
        <input
          className="ctrl-input"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          placeholder="Ticker"
          style={{ width: 90 }}
        />
        <button className="header-btn" onClick={() => load()}>Load</button>
        {loading && <span className="mini text-dim">Loading...</span>}
        <span className="mini text-dim">
          {series.length} snapshot(s) for {ticker}
        </span>
      </div>

      <div style={{ padding: 16, overflow: 'auto' }}>
        {series.length ? (
          <>
            <input
              type="range"
              min={0}
              max={Math.max(0, series.length - 1)}
              value={idx}
              onChange={(e) => setIdx(+e.target.value)}
              style={{ width: '100%' }}
            />
            <div className="mini text-dim" style={{ marginBottom: 12 }}>
              {current && new Date((current.ts || 0) * 1000).toLocaleString()}
            </div>
            {current && (
              <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                  <Stat label="Spot" value={`$${fmtPrice(current.spot)}`} />
                  <Stat label="Signal" value={<span className="signal-pill" data-signal={current.signal}>{current.signal}</span>} />
                  <Stat label="Regime" value={`${current.regime} γ`} />
                  <Stat label="King" value={`$${current.king}`} />
                  <Stat label="Floor" value={`$${current.floor}`} />
                  <Stat label="Ceiling" value={`$${current.ceiling}`} />
                  <Stat label="ZGL" value={`$${current.zgl}`} />
                  <Stat label="IV" value={fmtIV(current.iv)} />
                  <Stat label="+GEX" value={fmtBig(current.pos_gex)} />
                  <Stat label="−GEX" value={fmtBig(current.neg_gex)} />
                  <Stat label="Δ" value={fmtBig(current.net_delta)} />
                  <Stat label="V" value={fmtBig(current.net_vanna)} />
                </div>
              </div>
            )}
          </>
        ) : (
          <div style={{ textAlign: 'center', color: 'var(--text-3)', padding: 40 }}>
            No snapshots yet. Let the worker run for a few cycles, then reload.
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <div className="mini text-dim">{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
