import React, { useEffect, useState, useMemo } from 'react';
import { api } from '../api.js';
import { useStore } from '../store.js';

export default function MtfTab() {
  const { watchlists, activeWL } = useStore();
  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];
  const [data, setData] = useState({}); // { ticker: mtfResult }
  const [loading, setLoading] = useState(false);
  const [customTickers, setCustomTickers] = useState('');

  const tickers = useMemo(() => {
    if (customTickers.trim()) {
      return customTickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean);
    }
    return wl.tickers;
  }, [wl.tickers, customTickers]);

  async function loadAll(tickerList = tickers) {
    setLoading(true);
    try {
      const results = await Promise.all(
        tickerList.map((t) => api.mtf(t).then((d) => [t, d]).catch(() => [t, null])),
      );
      const map = {};
      for (const [t, d] of results) {
        if (d) map[t] = d;
      }
      setData(map);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    const iv = setInterval(() => loadAll(), 120_000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickers.join(',')]);

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%' }}>
      <div className="ctrl-bar" style={{ gap: 12 }}>
        <strong style={{ fontSize: 14 }}>Multi-Timeframe GEX</strong>
        <input
          className="ctrl-input"
          value={customTickers}
          onChange={(e) => setCustomTickers(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && loadAll()}
          placeholder={tickers.join(', ')}
          style={{ width: 260 }}
        />
        <button className="header-btn" onClick={() => loadAll()}>Load</button>
        <span className="mini text-dim">Auto-refresh 2min</span>
        {loading && <span className="mini text-dim">Loading...</span>}
      </div>

      <div style={{ overflow: 'auto', padding: 0 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Expiry</th>
              <th>King</th>
              <th>Floor</th>
              <th>Ceil</th>
              <th>POS/NEG</th>
            </tr>
          </thead>
          <tbody>
            {tickers.map((ticker) => {
              const d = data[ticker];
              if (!d) {
                return (
                  <tr key={ticker}>
                    <td style={{ fontWeight: 800, color: 'var(--accent)', fontSize: 14 }}>
                      {ticker}
                    </td>
                    <td colSpan={5} className="text-dim">Loading...</td>
                  </tr>
                );
              }
              const rows = (d.table || []).filter((r) => !r.expiration?.startsWith('MACRO'));
              const tickerIdx = tickers.indexOf(ticker);
              const isOdd = tickerIdx % 2 === 1;
              const groupBg = isOdd ? 'rgba(255,255,255,0.02)' : 'transparent';
              return (
                <React.Fragment key={ticker}>
                  {/* Separator gradient between groups */}
                  {tickerIdx > 0 && (
                    <tr>
                      <td colSpan={6} style={{
                        height: 3,
                        padding: 0,
                        background: 'linear-gradient(to right, var(--accent), var(--border-faint), transparent)',
                        border: 'none',
                      }} />
                    </tr>
                  )}
                  {rows.map((r, i) => {
                    const regime =
                      (r.pos_gex || 0) > Math.abs(r.neg_gex || 0) ? 'POS' : 'NEG';
                    return (
                      <tr
                        key={`${ticker}-${r.expiration}`}
                        style={{ background: groupBg }}
                      >
                        {i === 0 && (
                          <td
                            rowSpan={rows.length}
                            style={{
                              fontWeight: 800,
                              color: 'var(--accent)',
                              fontSize: 15,
                              verticalAlign: 'top',
                              borderRight: '2px solid var(--border-mid)',
                              paddingTop: 12,
                              paddingBottom: 12,
                              background: groupBg,
                            }}
                          >
                            {ticker}
                          </td>
                        )}
                        <td style={{ color: 'var(--text-2)' }}>{r.expiration}</td>
                        <td style={{ color: '#f4c430', fontWeight: 800 }}>${r.king ?? '-'}</td>
                        <td style={{ color: '#10dc9a', fontWeight: 700 }}>${r.floor ?? '-'}</td>
                        <td style={{ color: '#ff5656', fontWeight: 700 }}>${r.ceiling ?? '-'}</td>
                        <td>
                          <span style={{
                            color: regime === 'POS' ? '#10dc9a' : '#ff5656',
                            fontWeight: 700,
                          }}>
                            {regime} γ
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
        <div className="mini text-dim" style={{ padding: '12px 14px' }}>
          Compare king/floor/ceiling across expirations. MACRO = all expirations.
          Individual dates show near-term pin risk.
        </div>
      </div>
    </div>
  );
}
