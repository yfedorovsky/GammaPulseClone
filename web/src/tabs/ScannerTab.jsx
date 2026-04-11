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

export default function ScannerTab() {
  const { scanner, setScanner, selectedRow, setSelectedRow } = useStore();
  const [filter, setFilter] = useState('ALL');
  const [regimeFilter, setRegimeFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('pos_gex');
  const [sortDir, setSortDir] = useState('desc');
  const [showPerf, setShowPerf] = useState(false);

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
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
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
            {showPerf ? 'Hide' : 'Show'} Signal Performance
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

        {/* Table */}
        <div style={{ overflow: 'auto' }}>
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
                <th onClick={() => toggleSort('iv')}>IV</th>
                <th onClick={() => toggleSort('net_delta')}>NET Δ</th>
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
                    <td>{fmtIV(r.iv)}</td>
                    <td>{fmtBig(r.net_delta)}</td>
                    <td className="text-dim">{age}</td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td
                    colSpan={10}
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
        </div>
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
