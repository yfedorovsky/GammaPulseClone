import React, { useEffect, useState, useMemo } from 'react';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';

const SENTIMENTS = ['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL'];
const CONVICTIONS = ['ALL', 'HIGH', 'MEDIUM', 'LOW'];

const STATUS_ICON = {
  OPEN: '🟢', APPROACHING: '🟡', KING_HIT: '✅', KING_BREAK: '🚀',
  FLOOR_HIT: '⚠️', EXPIRED: '⏰',
};
const CONV_STYLE = {
  HIGH: { border: '1px solid #f4c430', background: 'rgba(244,196,48,0.08)' },
  MEDIUM: { border: '1px solid var(--border-mid)', background: 'transparent' },
  LOW: { border: '1px solid var(--border-faint)', background: 'transparent' },
};

function AlertsView({ alerts, sentFilter, setSentFilter, convFilter, setConvFilter, onClickTicker }) {
  const filtered = useMemo(() => {
    let rows = [...alerts];
    if (sentFilter !== 'ALL') rows = rows.filter((a) => a.sentiment === sentFilter);
    if (convFilter !== 'ALL') rows = rows.filter((a) => a.conviction === convFilter);
    return rows;
  }, [alerts, sentFilter, convFilter]);

  const sentCounts = useMemo(() => {
    const c = { ALL: alerts.length, BULLISH: 0, BEARISH: 0, NEUTRAL: 0 };
    for (const a of alerts) { c[a.sentiment] = (c[a.sentiment] || 0) + 1; }
    return c;
  }, [alerts]);

  const convCounts = useMemo(() => {
    const c = { ALL: alerts.length, HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const a of alerts) { c[a.conviction || 'LOW'] = (c[a.conviction || 'LOW'] || 0) + 1; }
    return c;
  }, [alerts]);

  // Stats: win rate per conviction
  const stats = useMemo(() => {
    const buckets = { HIGH: { wins: 0, total: 0 }, MEDIUM: { wins: 0, total: 0 }, LOW: { wins: 0, total: 0 } };
    for (const a of alerts) {
      const conv = a.conviction || 'LOW';
      const status = a.status || 'OPEN';
      if (status !== 'OPEN' && status !== 'APPROACHING') {
        buckets[conv].total++;
        if (status === 'KING_HIT' || status === 'KING_BREAK') buckets[conv].wins++;
      }
    }
    return buckets;
  }, [alerts]);

  const timeAgo = (ts) => {
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  };

  return (
    <div>
      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 16, padding: '10px 14px', borderBottom: '1px solid var(--border-faint)', background: 'var(--bg-1)', fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: 'var(--text-2)' }}>
        <span>7-Day Win Rate:</span>
        {['HIGH', 'MEDIUM', 'LOW'].map((c) => {
          const b = stats[c];
          const rate = b.total > 0 ? ((b.wins / b.total) * 100).toFixed(0) : '--';
          return (
            <span key={c} style={{ color: c === 'HIGH' ? '#f4c430' : c === 'MEDIUM' ? 'var(--text-1)' : 'var(--text-3)' }}>
              {c}: {rate}% ({b.wins}/{b.total})
            </span>
          );
        })}
      </div>

      {/* Filter pills */}
      <div style={{ display: 'flex', gap: 6, padding: '8px 14px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)', marginRight: 4 }}>Sentiment:</span>
        {SENTIMENTS.map((s) => (
          <button key={s} className={`ctrl-btn ${sentFilter === s ? 'active' : ''}`} onClick={() => setSentFilter(s)}
            style={{ background: sentFilter === s ? (s === 'BULLISH' ? 'rgba(16,220,154,0.15)' : s === 'BEARISH' ? 'rgba(255,86,86,0.15)' : 'rgba(255,255,255,0.08)') : undefined }}>
            {s} ({sentCounts[s] || 0})
          </button>
        ))}
        <span style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)', marginLeft: 12, marginRight: 4 }}>Conviction:</span>
        {CONVICTIONS.map((c) => (
          <button key={c} className={`ctrl-btn ${convFilter === c ? 'active' : ''}`} onClick={() => setConvFilter(c)}
            style={{ color: convFilter === c && c === 'HIGH' ? '#f4c430' : undefined }}>
            {c} ({convCounts[c] || 0})
          </button>
        ))}
      </div>

      {/* Alert list */}
      <div style={{ padding: '0 14px' }}>
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>
            No flow alerts yet. Alerts fire during market hours when unusual volume is detected.
          </div>
        )}
        {filtered.map((a, i) => {
          const isCall = a.option_type === 'call';
          const emoji = a.sentiment === 'BULLISH' ? '🟢' : a.sentiment === 'BEARISH' ? '🔴' : '🟡';
          const statusIcon = STATUS_ICON[a.status] || '🟢';
          const convStyle = CONV_STYLE[a.conviction] || CONV_STYLE.LOW;
          return (
            <div key={a.id || i} className="flow-alert-row" style={convStyle} onClick={() => onClickTicker(a.ticker)}>
              <div className="flow-alert-top">
                <span>{emoji}</span>
                <span className="alert-ticker">{a.ticker}</span>
                <span className="alert-strike" style={{ color: isCall ? '#10dc9a' : '#ff5656' }}>
                  ${a.strike} {a.option_type?.toUpperCase()} {a.expiration}
                </span>
                <span style={{ flex: 1 }} />
                {a.conviction && (
                  <span style={{ fontSize: 'var(--fs-xxs)', fontWeight: 800, color: a.conviction === 'HIGH' ? '#f4c430' : a.conviction === 'MEDIUM' ? 'var(--text-1)' : 'var(--text-3)', letterSpacing: '0.5px' }}>
                    {a.conviction}
                  </span>
                )}
                <span style={{ fontSize: 'var(--fs-xxs)', marginLeft: 8 }}>{statusIcon} {a.status || 'OPEN'}</span>
                <span className="alert-time">{timeAgo(a.ts)}</span>
              </div>
              <div className="flow-alert-bottom">
                <span>Vol: {(a.volume || 0).toLocaleString()}</span>
                <span>OI: {(a.oi || 0).toLocaleString()}</span>
                <span style={{ color: '#ff5656' }}>{a.vol_oi}x</span>
                <span>Side: <strong style={{ color: a.side === 'ASK' ? '#10dc9a' : a.side === 'BID' ? '#ff5656' : 'var(--text-2)' }}>{a.side}</strong></span>
                <span style={{ color: a.sentiment === 'BULLISH' ? '#10dc9a' : a.sentiment === 'BEARISH' ? '#ff5656' : 'var(--text-2)' }}>{a.sentiment}</span>
                <span>${(a.last_price || 0).toFixed(2)}</span>
                <span>{fmtBig(a.notional)}</span>
                <span>IV: {a.iv}%</span>
                {a.king && <span style={{ color: 'var(--king-pos)' }}>King ${a.king}</span>}
                {a.signal && <span className="signal-pill" data-signal={a.signal} style={{ padding: '1px 5px', fontSize: '9px' }}>{a.signal}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function FlowTab() {
  const [mode, setMode] = useState('alerts'); // alerts | scan | detail
  const [ticker, setTicker] = useState('SPY');
  const [detail, setDetail] = useState(null);
  const [scanResults, setScanResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sentFilter, setSentFilter] = useState('ALL');
  const [convFilter, setConvFilter] = useState('ALL');
  const [alerts, setAlerts] = useState([]);
  const [alertSince, setAlertSince] = useState(0);

  useEffect(() => {
    if (mode === 'scan') loadScan();
    else if (mode === 'detail') loadDetail(ticker);
    else if (mode === 'alerts') loadAlerts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Auto-refresh alerts every 15s
  useEffect(() => {
    if (mode !== 'alerts') return;
    const iv = setInterval(loadAlerts, 15_000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function loadAlerts() {
    try {
      const d = await api.alerts(0);
      setAlerts(d.alerts || []);
    } catch (e) {
      console.warn(e);
    }
  }

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
          <button className={`ctrl-btn ${mode === 'alerts' ? 'active' : ''}`} onClick={() => setMode('alerts')}>ALERTS</button>
          <button className={`ctrl-btn ${mode === 'scan' ? 'active' : ''}`} onClick={() => setMode('scan')}>SCAN</button>
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
        {mode === 'alerts' ? (
          <AlertsView alerts={alerts} sentFilter={sentFilter} setSentFilter={setSentFilter} convFilter={convFilter} setConvFilter={setConvFilter} onClickTicker={(t) => { setTicker(t); setMode('detail'); loadDetail(t); }} />
        ) : mode === 'detail' && detail ? (
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
