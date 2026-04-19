import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { useStore } from '../store.js';
import { fmtBig, fmtPrice, fmtIV } from '../lib/format.js';

const SIGNALS = ['ALL', 'MAGNET UP', 'SUPPORT', 'PINNING', 'RESISTANCE', 'AIR POCKET', 'DANGER'];

const SIGNAL_COLORS = {
  'MAGNET UP': '#10dc9a',
  SUPPORT: '#10dc9a',
  PINNING: '#f4c430',
  RESISTANCE: '#ff9090',
  'AIR POCKET': '#bb7cff',
  DANGER: '#ff5656',
};

// Theme-based watchlist grouping
const THEMES = {
  'Index ETFs': ['SPY', 'QQQ', 'IWM', 'DIA', 'SMH', 'SOXX', 'XBI', 'IBIT', 'UVXY'],
  'Mag 7': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA'],
  'Semis / Chip Equipment': ['AMD', 'AVGO', 'INTC', 'MU', 'MRVL', 'TSM', 'QCOM', 'TXN', 'AMAT', 'LRCX', 'KLAC', 'ASML', 'ARM', 'SMCI'],
  'Photonics / Fiber': ['LITE', 'COHR', 'AAOI', 'GLW', 'CIEN', 'AXTI'],
  'Semi Equipment': ['AEHR', 'TER', 'AMAT', 'LRCX', 'KLAC'],
  'Space': ['RKLB', 'ASTS'],
  'AI / DC Infra': ['ANET', 'VRT', 'NET', 'SNOW', 'PLTR', 'CRWD', 'PANW', 'ZS', 'NBIS', 'OKLO', 'IREN'],
  'Crypto / Fintech': ['COIN', 'MSTR', 'MARA', 'RIOT', 'XYZ', 'HOOD', 'SOFI'],
  'Consumer / Retail': ['AMZN', 'COST', 'WMT', 'TGT', 'NKE', 'SBUX', 'MCD'],
  'Space / Defense': ['BA', 'LMT', 'RTX', 'NOC', 'GD'],
  'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'OXY'],
  'Biotech / Health': ['LLY', 'UNH', 'PFE', 'MRK', 'ABBV', 'MRNA'],
  'Financials': ['JPM', 'BAC', 'GS', 'MS', 'V', 'MA'],
};

export default function ScannerTab() {
  const { scanner, setScanner, selectedRow, setSelectedRow } = useStore();
  const [filter, setFilter] = useState('ALL');
  const [regimeFilter, setRegimeFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('pos_gex');
  const [sortDir, setSortDir] = useState('desc');
  const [showPerf, setShowPerf] = useState(false);
  const [showThemes, setShowThemes] = useState(false);
  const [expandedTheme, setExpandedTheme] = useState(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await api.scanner();
        if (alive) setScanner(data);
      } catch {}
    }
    load();
    const iv = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [setScanner]);

  // Signal counts for pill badges
  const signalCounts = useMemo(() => {
    if (!scanner?.tickers) return {};
    const c = { ALL: scanner.tickers.length };
    for (const sig of SIGNALS.slice(1)) c[sig] = 0;
    for (const t of scanner.tickers) {
      if (c[t.signal] !== undefined) c[t.signal]++;
    }
    return c;
  }, [scanner]);

  const rows = useMemo(() => {
    if (!scanner?.tickers) return [];
    let r = [...scanner.tickers];
    if (filter !== 'ALL') r = r.filter((x) => x.signal === filter);
    if (regimeFilter !== 'ALL') r = r.filter((x) => x.regime === regimeFilter);
    if (search) {
      const s = search.toUpperCase();
      r = r.filter((x) => x._ticker?.includes(s));
    }
    r.sort((a, b) => {
      // IBD rank sorts lowest-first (#1 is strongest); unmapped tickers
      // sort last regardless of direction via 999 sentinel.
      const av = sortKey === '_rts_score' ? (a._rts?.score ?? 0)
        : sortKey === '_mir_score' ? (a._mir_score ?? 0)
        : sortKey === '_ibd_group_rank' ? (a._ibd_group_rank ?? 999)
        : (a[sortKey] ?? 0);
      const bv = sortKey === '_rts_score' ? (b._rts?.score ?? 0)
        : sortKey === '_mir_score' ? (b._mir_score ?? 0)
        : sortKey === '_ibd_group_rank' ? (b._ibd_group_rank ?? 999)
        : (b[sortKey] ?? 0);
      if (typeof av === 'string')
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === 'asc' ? av - bv : bv - av;
    });
    return r;
  }, [scanner, filter, regimeFilter, search, sortKey, sortDir]);

  const toggleSort = (k) => {
    if (sortKey === k) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else {
      setSortKey(k);
      setSortDir('desc');
    }
  };

  const totalTickers = scanner?.tickers?.length || 0;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: selectedRow ? '1fr 360px' : '1fr',
        height: '100%',
      }}
    >
      <div style={{ display: 'grid', gridTemplateRows: 'auto auto auto 1fr', minHeight: 0 }}>
        {/* Title + worker status */}
        <div className="ctrl-bar" style={{ gap: 12 }}>
          <strong style={{ fontSize: 14 }}>Scanner</strong>
          <span className="mini text-dim">
            {rows.length}/{totalTickers} tickers
          </span>
          <div style={{ flex: 1 }} />
          <span className="mini text-dim">
            {scanner?.worker_status?.status} · Auto-refreshes every 30s
          </span>
        </div>

        {/* Signal filter pills */}
        <div style={{ display: 'flex', gap: 6, padding: '6px 14px', flexWrap: 'wrap', borderBottom: '1px solid var(--border-faint)', background: 'var(--bg-1)' }}>
          {SIGNALS.map((sig) => {
            const count = signalCounts[sig] || 0;
            const isActive = filter === sig;
            const color = SIGNAL_COLORS[sig];
            return (
              <button
                key={sig}
                onClick={() => setFilter(sig)}
                style={{
                  border: isActive ? `1px solid ${color || 'var(--text-2)'}` : '1px solid var(--border-faint)',
                  background: isActive ? `${color || 'var(--text-2)'}22` : 'transparent',
                  color: isActive ? (color || 'var(--text-1)') : 'var(--text-2)',
                  padding: '4px 12px',
                  borderRadius: 8,
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer',
                  letterSpacing: 0.4,
                }}
              >
                {sig} ({count})
              </button>
            );
          })}
        </div>

        {/* Search + regime filter + add tickers */}
        <div className="ctrl-bar" style={{ gap: 10 }}>
          <input
            className="ctrl-input"
            placeholder="SEARCH TICKER..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 130, textTransform: 'uppercase' }}
          />
          <select
            className="ctrl-select"
            value={regimeFilter}
            onChange={(e) => setRegimeFilter(e.target.value)}
          >
            <option value="ALL">All Regime</option>
            <option value="POS">POS γ</option>
            <option value="NEG">NEG γ</option>
          </select>
          <button className="header-btn" onClick={() => setShowPerf(!showPerf)}>
            {showPerf ? 'Hide' : 'Show'} Perf
          </button>
          <button
            className="header-btn"
            onClick={() => setShowThemes(!showThemes)}
            style={{
              background: showThemes ? 'rgba(162,77,255,0.2)' : undefined,
              color: showThemes ? '#a24dff' : undefined,
              border: showThemes ? '1px solid #a24dff' : undefined,
            }}
          >
            {showThemes ? 'Table' : 'Themes'}
          </button>
          <div style={{ flex: 1 }} />
          <input
            className="ctrl-input"
            placeholder="Add tickers (comma-sep)..."
            style={{ width: 180 }}
            onKeyDown={async (e) => {
              if (e.key === 'Enter') {
                const val = e.target.value.trim();
                if (!val) return;
                const syms = val.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
                try {
                  const result = await api.addTickers(syms);
                  if (result.added?.length) {
                    e.target.value = '';
                    // Refresh scanner to pick up new tickers
                    const data = await api.scanner();
                    setScanner(data);
                  }
                } catch {}
              }
            }}
          />
        </div>

        {showPerf && (
          <div className="card" style={{ margin: 10 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>
              Signal Accuracy (last 7 days)
            </div>
            <div className="mini text-dim">
              Requires snapshot history to populate. As the worker runs over
              multiple cycles, this table will show win rate per signal type.
            </div>
          </div>
        )}

        {/* Themes View */}
        {showThemes && (
          <div style={{ overflow: 'auto', padding: 10 }}>
            {Object.entries(THEMES).map(([theme, tickers]) => {
              const themeRows = tickers
                .map((t) => scanner?.tickers?.find((r) => r._ticker === t))
                .filter(Boolean);
              if (!themeRows.length) return null;
              const bullish = themeRows.filter((r) => r.signal === 'MAGNET UP' || r.signal === 'SUPPORT').length;
              const avgKingPct = themeRows.reduce((sum, r) => {
                const kp = r.actual_spot && r.king ? ((r.king - r.actual_spot) / r.actual_spot) * 100 : 0;
                return sum + kp;
              }, 0) / themeRows.length;
              const isExpanded = expandedTheme === theme;

              return (
                <div key={theme} style={{ marginBottom: 6 }}>
                  <div
                    onClick={() => setExpandedTheme(isExpanded ? null : theme)}
                    style={{
                      padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
                      border: '1px solid var(--border-faint)',
                      background: isExpanded ? 'rgba(162,77,255,0.05)' : 'var(--bg-panel)',
                      display: 'flex', alignItems: 'center', gap: 12,
                    }}
                  >
                    <span style={{ fontWeight: 800, fontSize: 13, minWidth: 160 }}>{theme}</span>
                    <span style={{
                      padding: '2px 8px', borderRadius: 6, fontWeight: 800, fontSize: 11,
                      fontFamily: 'var(--mono)',
                      background: avgKingPct > 0 ? 'rgba(16,220,154,0.15)' : 'rgba(255,86,86,0.15)',
                      color: avgKingPct > 0 ? '#10dc9a' : '#ff5656',
                    }}>
                      {avgKingPct > 0 ? '+' : ''}{avgKingPct.toFixed(1)}%
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
                      {bullish}/{themeRows.length} bullish
                    </span>
                    <div style={{ flex: 1 }} />
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{isExpanded ? '▼' : '▶'}</span>
                  </div>
                  {isExpanded && (
                    <div style={{ padding: '6px 0 6px 20px' }}>
                      {themeRows.map((r) => {
                        const kp = r.actual_spot && r.king ? ((r.king - r.actual_spot) / r.actual_spot) * 100 : 0;
                        const sigColor = SIGNAL_COLORS[r.signal] || 'var(--text-2)';
                        return (
                          <div
                            key={r._ticker}
                            onClick={() => setSelectedRow(selectedRow?._ticker === r._ticker ? null : r)}
                            style={{
                              display: 'flex', gap: 12, alignItems: 'center', padding: '4px 10px',
                              cursor: 'pointer', borderRadius: 4, fontFamily: 'var(--mono)', fontSize: 11,
                              borderLeft: `3px solid ${sigColor}`,
                              background: selectedRow?._ticker === r._ticker ? 'rgba(255,255,255,0.04)' : 'transparent',
                            }}
                          >
                            <span style={{ fontWeight: 800, color: 'var(--accent)', width: 50 }}>{r._ticker}</span>
                            <span style={{ color: kp > 0 ? '#10dc9a' : '#ff5656', width: 50 }}>
                              {kp > 0 ? '+' : ''}{kp.toFixed(1)}%
                            </span>
                            <span className="signal-pill" data-signal={r.signal} style={{ fontSize: 9 }}>{r.signal}</span>
                            <span style={{ color: 'var(--text-3)', width: 40 }}>{r.regime}</span>
                            {r._rts?.score != null && (
                              <span style={{
                                color: r._rts.score >= 70 ? '#10dc9a' : r._rts.score >= 40 ? '#f4c430' : '#ff5656',
                                fontWeight: 800, width: 40,
                              }}>
                                RS {r._rts.score}
                              </span>
                            )}
                            {r._ivp != null && (
                              <span style={{ color: r._ivp <= 30 ? '#10dc9a' : r._ivp <= 50 ? '#f4c430' : '#ff5656', width: 40 }}>
                                IVP {r._ivp}%
                              </span>
                            )}
                            <span style={{
                              fontSize: 9, fontWeight: 800, padding: '1px 4px', borderRadius: 3,
                              background: r._greeks_source === 'massive' ? 'rgba(16,220,154,0.15)' : 'rgba(255,200,0,0.12)',
                              color: r._greeks_source === 'massive' ? '#10dc9a' : '#ffc800',
                            }}>
                              {r._greeks_source === 'massive' ? 'M' : 'T'}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Table */}
        {!showThemes && <div style={{ overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort('_ticker')}>Ticker</th>
                <th>Signal</th>
                <th onClick={() => toggleSort('regime')}>Regime</th>
                <th onClick={() => toggleSort('actual_spot')}>Spot</th>
                <th onClick={() => toggleSort('king')}>King</th>
                <th onClick={() => toggleSort('_king_pct')}>King %</th>
                <th onClick={() => toggleSort('pos_gex')} style={{ color: '#f4c430' }}>
                  GEX MAG {sortKey === 'pos_gex' ? (sortDir === 'desc' ? '▼' : '▲') : ''}
                </th>
                <th onClick={() => toggleSort('_rts_score')}>RS</th>
                <th onClick={() => toggleSort('_mir_score')}>Mir</th>
                <th onClick={() => toggleSort('_ibd_group_rank')} title="IBD industry group rank (1=strongest YTD). Hover a cell to see group name + YTD%.">IBD</th>
                <th>Mode</th>
                <th onClick={() => toggleSort('iv')}>IV</th>
                <th onClick={() => toggleSort('_ivp')}>IVP</th>
                <th onClick={() => toggleSort('net_delta')}>NET Δ</th>
                <th>SRC</th>
                <th>AGE</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const kingPct =
                  r.actual_spot && r.king
                    ? (((r.king - r.actual_spot) / r.actual_spot) * 100).toFixed(1)
                    : '-';
                const kingPctNum = parseFloat(kingPct);
                const gexMag = (r.pos_gex || 0) + Math.abs(r.neg_gex || 0);
                // Compute age from _updated
                let age = '-';
                if (r._updated) {
                  const updMs = new Date(r._updated).getTime();
                  const mins = Math.round((Date.now() - updMs) / 60000);
                  if (mins < 60) age = `${mins}m`;
                  else age = `${Math.round(mins / 60)}h`;
                }
                const sigColor = SIGNAL_COLORS[r.signal] || 'var(--text-2)';
                return (
                  <tr
                    key={r._ticker}
                    className={selectedRow?._ticker === r._ticker ? 'selected' : ''}
                    style={{ borderLeft: `3px solid ${sigColor}` }}
                    onClick={() =>
                      setSelectedRow(
                        selectedRow?._ticker === r._ticker ? null : r,
                      )
                    }
                  >
                    <td style={{ fontWeight: 800, color: 'var(--accent)' }}>
                      {r._ticker}
                    </td>
                    <td>
                      <span className="signal-pill" data-signal={r.signal}>
                        {r.signal}
                      </span>
                    </td>
                    <td>{r.regime} γ</td>
                    <td>{fmtPrice(r.actual_spot)}</td>
                    <td style={{ fontWeight: 800, color: '#10dc9a' }}>
                      ${r.king}
                    </td>
                    <td
                      style={{
                        color:
                          kingPctNum > 0
                            ? '#10dc9a'
                            : kingPctNum < 0
                            ? '#ff5656'
                            : 'var(--text-2)',
                        fontWeight: 700,
                      }}
                    >
                      {kingPctNum > 0 ? '+' : ''}
                      {kingPct}%
                    </td>
                    <td>{fmtBig(gexMag)}</td>
                    <td>
                      {(() => {
                        const rs = r._rts?.score;
                        if (rs == null) return <span style={{ color: 'var(--text-3)' }}>-</span>;
                        const color = rs >= 70 ? '#10dc9a' : rs >= 40 ? '#f4c430' : '#ff5656';
                        const ext = r._rts?.extension;
                        return (
                          <span style={{ fontWeight: 700, color }}>
                            {rs}
                            {ext === 'EXTENDED' && <span style={{ fontSize: 8, color: '#f4c430' }}> EXT</span>}
                            {ext === 'OVEREXTENDED' && <span style={{ fontSize: 8, color: '#ff5656' }}> OVR</span>}
                          </span>
                        );
                      })()}
                    </td>
                    <td>
                      {r._mir_score != null ? (
                        <span style={{
                          fontWeight: 700,
                          color: r._mir_score >= 5 ? '#10dc9a' : r._mir_score >= 4 ? '#f4c430' : 'var(--text-3)',
                        }}>
                          {r._mir_score}
                          {r._mir_conviction && (
                            <span style={{ fontSize: 8, marginLeft: 2, color: r._mir_conviction === 'HIGH' ? '#10dc9a' : '#f4c430' }}>
                              {r._mir_conviction === 'HIGH' ? 'H' : 'M'}
                            </span>
                          )}
                        </span>
                      ) : <span style={{ color: 'var(--text-3)' }}>-</span>}
                    </td>
                    <td>
                      {r._ibd_sector_leader && (
                        <span
                          title="IBD Sector Leader — passes O'Neil's full CAN-SLIM screen. Highest conviction tier."
                          style={{
                            fontWeight: 800, fontSize: 10, marginRight: 3,
                            color: '#ffd700',  // gold — Sector Leader is the premier tier
                          }}
                        >
                          ★★
                        </span>
                      )}
                      {r._ibd_group_rank != null ? (
                        <span
                          title={`#${r._ibd_group_rank} ${r._ibd_group_name} — YTD ${r._ibd_group_ytd}% — leader rank ${r._ibd_group_leader_rank} in group${r._ibd_sector_leader ? ' · IBD Sector Leader' : ''}`}
                          style={{
                            fontWeight: 800,
                            fontSize: 11,
                            padding: '1px 4px',
                            borderRadius: 3,
                            background: r._ibd_group_rank <= 3
                              ? 'rgba(16,220,154,0.18)'
                              : r._ibd_group_rank <= 5
                              ? 'rgba(244,196,48,0.15)'
                              : 'rgba(160,160,160,0.10)',
                            color: r._ibd_group_rank <= 3
                              ? '#10dc9a'
                              : r._ibd_group_rank <= 5
                              ? '#f4c430'
                              : 'var(--text-2)',
                          }}
                        >
                          #{r._ibd_group_rank}
                          {r._ibd_group_leader_rank === 1 && (
                            <span style={{ fontSize: 8, marginLeft: 2 }}>★</span>
                          )}
                        </span>
                      ) : r._ibd_sector_leader ? (
                        <span
                          title="IBD Sector Leader (not in a mapped industry group)"
                          style={{ fontSize: 11, color: '#ffd700', fontWeight: 700 }}
                        >
                          LEADER
                        </span>
                      ) : <span style={{ color: 'var(--text-3)' }}>-</span>}
                    </td>
                    <td>
                      {r._trend_mode && r._trend_mode !== 'NORMAL' ? (
                        <span style={{
                          fontSize: 9, fontWeight: 800, padding: '1px 4px', borderRadius: 3,
                          background: r._trend_mode === 'EXTREME_TREND' ? 'rgba(255,86,86,0.15)' : 'rgba(244,196,48,0.15)',
                          color: r._trend_mode === 'EXTREME_TREND' ? '#ff5656' : '#f4c430',
                        }}>
                          {r._gap_pct > 0 ? '+' : ''}{r._gap_pct}%
                        </span>
                      ) : <span style={{ color: 'var(--text-3)' }}>-</span>}
                    </td>
                    <td>{fmtIV(r.iv)}</td>
                    <td style={{ color: r._ivp != null ? (r._ivp <= 30 ? '#10dc9a' : r._ivp <= 50 ? '#f4c430' : '#ff5656') : 'var(--text-3)' }}>
                      {r._ivp != null ? `${r._ivp}%` : '-'}
                    </td>
                    <td>{fmtBig(r.net_delta)}</td>
                    <td>
                      <span style={{
                        fontSize: 9, fontWeight: 800, padding: '1px 4px', borderRadius: 3,
                        background: r._greeks_source === 'massive' ? 'rgba(16,220,154,0.15)' : 'rgba(255,200,0,0.12)',
                        color: r._greeks_source === 'massive' ? '#10dc9a' : '#ffc800',
                      }}>
                        {r._greeks_source === 'massive' ? 'M' : 'T'}
                      </span>
                    </td>
                    <td className="text-dim">{age}</td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td
                    colSpan={15}
                    style={{
                      textAlign: 'center',
                      padding: 40,
                      color: 'var(--text-3)',
                    }}
                  >
                    No rows. Waiting for the first scanner cycle to complete...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>}
      </div>

      {/* MTF side panel */}
      {selectedRow && (
        <div
          style={{
            borderLeft: '1px solid var(--border-faint)',
            background: 'var(--bg-panel)',
            overflowY: 'auto',
            padding: 12,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 10,
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 800 }}>{selectedRow._ticker}</div>
            <button className="header-btn" onClick={() => setSelectedRow(null)}>
              ✕ Close
            </button>
          </div>

          <div style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 20, fontWeight: 800, marginRight: 8 }}>
              ${fmtPrice(selectedRow.actual_spot)}
            </span>
            <span className="signal-pill" data-signal={selectedRow.signal}>
              {selectedRow.signal}
            </span>{' '}
            <span className="regime-pill">{selectedRow.regime} γ</span>
          </div>

          <div className="mini" style={{ marginBottom: 14 }}>
            <span style={{ color: '#f4c430', fontWeight: 800 }}>
              King ${selectedRow.king}
            </span>
            <span className="sep"> · </span>
            Floor ${selectedRow.floor}
            <span className="sep"> · </span>
            Ceil ${selectedRow.ceiling}
          </div>

          {/* Greeks + IVP + IV/HV context */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 14, fontFamily: 'var(--mono)', fontSize: 11 }}>
            {selectedRow._greeks_source && (
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontWeight: 800,
                background: selectedRow._greeks_source === 'massive' ? 'rgba(16,220,154,0.15)' : 'rgba(255,200,0,0.12)',
                color: selectedRow._greeks_source === 'massive' ? '#10dc9a' : '#ffc800',
              }}>
                {selectedRow._greeks_source === 'massive' ? 'MASSIVE' : 'TRADIER'} Greeks
              </span>
            )}
            {selectedRow._ivp != null && (
              <span style={{ color: selectedRow._ivp <= 30 ? '#10dc9a' : selectedRow._ivp <= 50 ? '#f4c430' : '#ff5656' }}>
                IVP: {selectedRow._ivp}%
              </span>
            )}
            {selectedRow._ivhv_ratio != null && (
              <span style={{ color: selectedRow._ivhv_ratio < 1.2 ? '#10dc9a' : selectedRow._ivhv_ratio < 1.5 ? '#f4c430' : '#ff5656' }}>
                IV/HV: {selectedRow._ivhv_ratio}x
              </span>
            )}
          </div>

          <div style={{ fontWeight: 800, marginBottom: 6 }}>Multi-Timeframe</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Expiry</th>
                <th>King</th>
                <th>Floor</th>
                <th>Ceil</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(selectedRow.exps || []).map((exp) => {
                const ed = (selectedRow.exp_data || {})[exp] || {};
                const regime =
                  (ed.pos_gex || 0) > Math.abs(ed.neg_gex || 0) ? 'POS' : 'NEG';
                return (
                  <tr key={exp}>
                    <td>{exp}</td>
                    <td style={{ color: '#f4c430', fontWeight: 700 }}>
                      ${ed.king ?? '-'}
                    </td>
                    <td style={{ color: '#10dc9a' }}>${ed.floor ?? '-'}</td>
                    <td style={{ color: '#ff5656' }}>${ed.ceiling ?? '-'}</td>
                    <td>{regime}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mini text-dim" style={{ marginTop: 10 }}>
            Click another row to switch · Click same row or ✕ to close
          </div>
        </div>
      )}
    </div>
  );
}
