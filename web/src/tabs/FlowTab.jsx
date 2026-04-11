import React, { useEffect, useState, useMemo } from 'react';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';

const SENTIMENTS = ['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL'];

export default function FlowTab() {
  const [mode, setMode] = useState('detail'); // scan | detail
  const [ticker, setTicker] = useState('SPY');
  const [detail, setDetail] = useState(null);
  const [scanResults, setScanResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sentFilter, setSentFilter] = useState('ALL');

  useEffect(() => {
    if (mode === 'scan') loadScan();
    else loadDetail(ticker);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function loadScan() {
    setLoading(true);
    try {
      const d = await api.flowScan();
      setScanResults(d.results || []);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(t = ticker) {
    setLoading(true);
    try {
      const d = await api.flowDetail(t);
      setDetail(d);
    } catch (e) {
      setDetail(null);
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }

  const [sortKey, setSortKey] = useState('volume');
  const [sortDir, setSortDir] = useState('desc');

  const toggleSort = (k) => {
    if (sortKey === k) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(k); setSortDir('desc'); }
  };

  // Sentiment-filtered + sorted rows
  const filteredRows = useMemo(() => {
    if (!detail?.rows) return [];
    let rows = sentFilter === 'ALL' ? [...detail.rows] : detail.rows.filter((r) => r.sentiment === sentFilter);
    rows.sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      return sortDir === 'asc' ? av - bv : bv - av;
    });
    return rows;
  }, [detail, sentFilter, sortKey, sortDir]);

  // Counts per sentiment
  const counts = useMemo(() => {
    if (!detail?.rows) return {};
    const c = { ALL: detail.rows.length, BULLISH: 0, BEARISH: 0, NEUTRAL: 0 };
    for (const r of detail.rows) {
      if (r.sentiment === 'BULLISH') c.BULLISH++;
      else if (r.sentiment === 'BEARISH') c.BEARISH++;
      else c.NEUTRAL++;
    }
    return c;
  }, [detail]);

  const pcColor = detail?.pc_ratio < 0.7 ? '#10dc9a' : detail?.pc_ratio > 1.2 ? '#ff5656' : '#ffcc4d';
  const pcLabel = detail?.pc_ratio < 0.7 ? 'BULLISH' : detail?.pc_ratio > 1.2 ? 'BEARISH' : 'NEUTRAL';

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%' }}>
      {/* Header */}
      <div className="ctrl-bar" style={{ gap: 14 }}>
        <strong style={{ fontSize: 15, marginRight: 6 }}>Options Flow</strong>
        <div className="ctrl-group">
          <button className={`ctrl-btn ${mode === 'scan' ? 'active' : ''}`} onClick={() => setMode('scan')}>SCAN ALL</button>
          <button className={`ctrl-btn ${mode === 'detail' ? 'active' : ''}`} onClick={() => setMode('detail')}>DETAIL</button>
        </div>
        <div style={{ flex: 1 }} />
        {mode === 'detail' && (
          <>
            <input
              className="ctrl-input"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && loadDetail(ticker)}
              placeholder="Ticker"
              style={{ width: 70, textAlign: 'center', fontWeight: 800, color: 'var(--accent)' }}
            />
            <button className="header-btn" onClick={() => loadDetail(ticker)}>Load</button>
          </>
        )}
        {loading && <span className="mini text-dim">Loading...</span>}
      </div>

      <div style={{ overflow: 'auto', padding: 0 }}>
        {mode === 'detail' && detail ? (
          <div>
            {/* Summary cards */}
            <div className="flow-cards">
              <div className="flow-card">
                <div className="flow-card-val">${fmtPrice(detail.spot)}</div>
                <div className="flow-card-label">SPOT</div>
              </div>
              <div className="flow-card">
                <div className="flow-card-val" style={{ color: pcColor }}>
                  {detail.pc_ratio?.toFixed(2) || '-'}
                </div>
                <div className="flow-card-label">P/C RATIO · {pcLabel}</div>
              </div>
              <div className="flow-card">
                <div className="flow-card-val" style={{ color: '#10dc9a' }}>
                  {Math.round(detail.call_volume || 0).toLocaleString()}
                </div>
                <div className="flow-card-label">CALL VOL</div>
              </div>
              <div className="flow-card">
                <div className="flow-card-val" style={{ color: '#ff5656' }}>
                  {Math.round(detail.put_volume || 0).toLocaleString()}
                </div>
                <div className="flow-card-label">PUT VOL</div>
              </div>
            </div>

            {/* Sentiment filter pills */}
            <div style={{ display: 'flex', gap: 6, padding: '8px 14px' }}>
              {SENTIMENTS.map((s) => (
                <button
                  key={s}
                  className={`ctrl-btn ${sentFilter === s ? 'active' : ''}`}
                  onClick={() => setSentFilter(s)}
                  style={{
                    background: sentFilter === s
                      ? s === 'BULLISH' ? 'rgba(16,220,154,0.15)'
                      : s === 'BEARISH' ? 'rgba(255,86,86,0.15)'
                      : 'rgba(255,255,255,0.08)'
                      : undefined,
                  }}
                >
                  {s} ({counts[s] || 0})
                </button>
              ))}
            </div>

            {/* Flow table */}
            <table className="data-table">
              <thead>
                <tr>
                  <th>EXP</th>
                  <th onClick={() => toggleSort('strike')} style={{ cursor: 'pointer' }}>STRIKE {sortKey === 'strike' ? (sortDir === 'desc' ? '▼' : '▲') : ''}</th>
                  <th>TYPE</th>
                  <th>SIDE</th>
                  <th>SENTIMENT</th>
                  <th onClick={() => toggleSort('volume')} style={{ cursor: 'pointer' }}>VOL {sortKey === 'volume' ? (sortDir === 'desc' ? '▼' : '▲') : ''}</th>
                  <th onClick={() => toggleSort('oi')} style={{ cursor: 'pointer' }}>OI {sortKey === 'oi' ? (sortDir === 'desc' ? '▼' : '▲') : ''}</th>
                  <th onClick={() => toggleSort('vol_oi')} style={{ cursor: 'pointer', color: '#f4c430' }}>V/OI {sortKey === 'vol_oi' ? (sortDir === 'desc' ? '▼' : '▲') : ''}</th>
                  <th onClick={() => toggleSort('last')} style={{ cursor: 'pointer' }}>LAST</th>
                  <th onClick={() => toggleSort('notional')} style={{ cursor: 'pointer' }}>NOTIONAL {sortKey === 'notional' ? (sortDir === 'desc' ? '▼' : '▲') : ''}</th>
                  <th onClick={() => toggleSort('iv')} style={{ cursor: 'pointer' }}>IV</th>
                  <th onClick={() => toggleSort('delta')} style={{ cursor: 'pointer' }}>Δ</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.exp}</td>
                    <td style={{ fontWeight: 800 }}>${r.strike}</td>
                    <td style={{ color: r.type === 'call' ? '#10dc9a' : '#ff5656', fontWeight: 700 }}>
                      {r.type?.toUpperCase()}
                    </td>
                    <td style={{ color: r.side === 'ASK' ? '#10dc9a' : '#ff5656', fontWeight: 700 }}>
                      {r.side}
                    </td>
                    <td>
                      <span style={{
                        color: r.sentiment === 'BULLISH' ? '#10dc9a' : '#ff5656',
                        fontWeight: 700,
                      }}>
                        {r.sentiment}
                      </span>
                    </td>
                    <td>{Math.round(r.volume).toLocaleString()}</td>
                    <td>{Math.round(r.oi).toLocaleString()}</td>
                    <td style={{ color: '#ff5656', fontWeight: 700 }}>{r.vol_oi}x</td>
                    <td>${r.last?.toFixed(2)}</td>
                    <td>{fmtBig(r.notional)}</td>
                    <td>{r.iv}%</td>
                    <td>{r.delta}</td>
                  </tr>
                ))}
                {!filteredRows.length && (
                  <tr>
                    <td colSpan={12} style={{ textAlign: 'center', padding: 30, color: 'var(--text-3)' }}>
                      {loading ? 'Loading...' : 'No unusual flow found (Vol/OI ≥ 2×)'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            {/* How to Read footer */}
            <div className="flow-footer">
              <strong>How to Read</strong>
              <div className="flow-footer-text">
                <span style={{ color: '#ff5656' }}>Vol/OI ≥ 2×</span> = unusual volume — new positions opening.{' '}
                <strong>ASK side</strong> = bought aggressively (bullish for calls, bearish for puts).{' '}
                <strong style={{ color: '#ff5656' }}>BID side</strong> = sold aggressively (bearish for calls, bullish for puts).{' '}
                <strong>Notional</strong> = volume × last price × 100 (total $ committed).{' '}
                P/C Ratio {'<'} 0.7 = bullish, {'>'} 1.2 = bearish.
              </div>
            </div>
          </div>
        ) : mode === 'detail' ? (
          <div style={{ textAlign: 'center', color: 'var(--text-3)', padding: 40 }}>
            Enter a ticker and click Load.
          </div>
        ) : (
          /* SCAN ALL mode */
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Spot</th>
                <th>Signal</th>
                <th>Regime</th>
                <th>Top Strike</th>
                <th>GEX</th>
              </tr>
            </thead>
            <tbody>
              {(scanResults || []).map((r) => {
                const top = r.top?.[0];
                return (
                  <tr key={r.ticker} onClick={() => { setTicker(r.ticker); setMode('detail'); loadDetail(r.ticker); }}>
                    <td style={{ fontWeight: 800, color: 'var(--accent)' }}>{r.ticker}</td>
                    <td>{fmtPrice(r.spot)}</td>
                    <td><span className="signal-pill" data-signal={r.signal}>{r.signal}</span></td>
                    <td>{r.regime} γ</td>
                    <td>{top?.strike ?? '-'}</td>
                    <td className={top?.net_gex >= 0 ? 'num-pos' : 'num-neg'}>
                      {fmtBig(top?.net_gex || 0)}
                    </td>
                  </tr>
                );
              })}
              {!scanResults?.length && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: 20, color: 'var(--text-3)' }}>
                    Scanning...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
