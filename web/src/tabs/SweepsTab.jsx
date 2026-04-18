import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api.js';
import { fmtBig } from '../lib/format.js';

/**
 * SWEEPS tab — ISO sweep flow (OPRA condition=95/126/128) via ThetaData.
 *
 * Unlike regular flow alerts (vol/OI inference), these are real-time OPRA-
 * tagged sweeps: orders routed across multiple exchanges simultaneously.
 * UW's highest-hit-rate flow category — now piped directly from the same
 * OPRA feed they consume, into the same dashboard as our GEX/Mir signals.
 */

const REFRESH_MS = 10_000;

const NOTIONAL_PRESETS = [
  { label: 'All', value: 0 },
  { label: '$50K+', value: 50_000 },
  { label: '$100K+', value: 100_000 },
  { label: '$500K+', value: 500_000 },
  { label: '$1M+', value: 1_000_000 },
  { label: '$5M+', value: 5_000_000 },
];

const TYPE_FILTERS = ['ALL', 'CALL', 'PUT'];
const TIMEFRAMES = [
  { label: '1h', seconds: 3600 },
  { label: '4h', seconds: 14400 },
  { label: 'Today', seconds: null },
];

const SORT_COLUMNS = [
  { key: 'ts', label: 'Time' },
  { key: 'ticker', label: 'Ticker' },
  { key: 'sweep_notional', label: 'Notional' },
  { key: 'sweep_contracts', label: 'Contracts' },
  { key: 'sweep_venues', label: 'Venues' },
  { key: 'sweep_prints', label: 'Prints' },
  { key: 'oi', label: 'OI' },
  { key: 'iv', label: 'IV' },
];


function fmtTimeAgo(ts) {
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function fmtClockET(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    timeZone: 'America/New_York', hour12: false,
  });
}

function fmtNotional(n) {
  if (!n) return '--';
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtInt(n) {
  if (n == null) return '--';
  return n.toLocaleString('en-US');
}

function fmtPct(n) {
  if (n == null) return '--';
  return `${(n * 100).toFixed(1)}%`;
}


export default function SweepsTab({ onClickTicker }) {
  const [sweeps, setSweeps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  // Filter state
  const [tickerQuery, setTickerQuery] = useState('');
  const [minNotional, setMinNotional] = useState(100_000);
  const [minOI, setMinOI] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [timeframe, setTimeframe] = useState(TIMEFRAMES[2]);  // 'Today' default
  const [sortBy, setSortBy] = useState('sweep_notional');
  const [sortDesc, setSortDesc] = useState(true);

  const load = useCallback(async () => {
    try {
      const since = timeframe.seconds
        ? Math.floor(Date.now() / 1000) - timeframe.seconds
        : 0;
      const resp = await api.sweeps(since, 500, '', minNotional);
      setSweeps(resp.sweeps || []);
      setError(null);
      setLastRefresh(Date.now());
    } catch (e) {
      setError(e.message || 'Failed to load sweeps');
    } finally {
      setLoading(false);
    }
  }, [timeframe, minNotional]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Client-side filtering (ticker search + OI + type) + sorting
  const filtered = useMemo(() => {
    let rows = [...sweeps];

    const q = tickerQuery.trim().toUpperCase();
    if (q) {
      rows = rows.filter((s) => (s.ticker || '').toUpperCase().includes(q));
    }

    const oiThresh = parseInt(minOI, 10);
    if (!isNaN(oiThresh) && oiThresh > 0) {
      rows = rows.filter((s) => (s.oi || 0) >= oiThresh);
    }

    if (typeFilter !== 'ALL') {
      const ot = typeFilter.toLowerCase();
      rows = rows.filter((s) => (s.option_type || '').toLowerCase() === ot);
    }

    rows.sort((a, b) => {
      const va = a[sortBy] ?? 0;
      const vb = b[sortBy] ?? 0;
      if (typeof va === 'string') {
        return sortDesc ? vb.localeCompare(va) : va.localeCompare(vb);
      }
      return sortDesc ? vb - va : va - vb;
    });

    return rows;
  }, [sweeps, tickerQuery, minOI, typeFilter, sortBy, sortDesc]);

  // Stats bar
  const stats = useMemo(() => {
    const tickers = new Set();
    let totalNotional = 0;
    const tickerNotional = {};
    for (const s of filtered) {
      tickers.add(s.ticker);
      totalNotional += s.sweep_notional || 0;
      tickerNotional[s.ticker] = (tickerNotional[s.ticker] || 0) + (s.sweep_notional || 0);
    }
    let topTicker = null;
    let topNotional = 0;
    for (const [t, n] of Object.entries(tickerNotional)) {
      if (n > topNotional) { topNotional = n; topTicker = t; }
    }
    return {
      count: filtered.length,
      uniqueTickers: tickers.size,
      totalNotional,
      topTicker,
      topNotional,
    };
  }, [filtered]);

  const toggleSort = (col) => {
    if (sortBy === col) {
      setSortDesc(!sortDesc);
    } else {
      setSortBy(col);
      setSortDesc(true);
    }
  };

  return (
    <div style={{ padding: '12px 14px', fontFamily: 'var(--sans)' }}>
      {/* Header + filter row */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10,
        marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-faint)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          ⚡ ISO SWEEPS
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          OPRA condition=95 • real-time via ThetaData
        </div>

        <div style={{ flex: 1 }} />

        {/* Ticker search */}
        <input
          type="text"
          value={tickerQuery}
          onChange={(e) => setTickerQuery(e.target.value)}
          placeholder="Search ticker..."
          style={{
            background: 'var(--bg-1)', border: '1px solid var(--border-mid)',
            color: 'var(--text-1)', padding: '5px 10px', borderRadius: 3,
            fontSize: 11, width: 140, fontFamily: 'var(--mono)',
            textTransform: 'uppercase',
          }}
        />

        {/* Min Notional */}
        <select
          value={minNotional}
          onChange={(e) => setMinNotional(Number(e.target.value))}
          style={{
            background: 'var(--bg-1)', border: '1px solid var(--border-mid)',
            color: 'var(--text-1)', padding: '5px 8px', borderRadius: 3,
            fontSize: 11, fontFamily: 'var(--mono)',
          }}
        >
          {NOTIONAL_PRESETS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>

        {/* Min OI */}
        <input
          type="number"
          value={minOI}
          onChange={(e) => setMinOI(e.target.value)}
          placeholder="Min OI"
          min={0}
          style={{
            background: 'var(--bg-1)', border: '1px solid var(--border-mid)',
            color: 'var(--text-1)', padding: '5px 8px', borderRadius: 3,
            fontSize: 11, width: 90, fontFamily: 'var(--mono)',
          }}
        />

        {/* Type filter */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TYPE_FILTERS.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              style={{
                background: typeFilter === t ? 'var(--bg-2)' : 'transparent',
                color: typeFilter === t ? 'var(--text-1)' : 'var(--text-3)',
                border: '1px solid var(--border-mid)',
                padding: '5px 10px', fontSize: 10, fontFamily: 'var(--mono)',
                cursor: 'pointer', borderRadius: 3,
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Timeframe */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.label}
              onClick={() => setTimeframe(tf)}
              style={{
                background: timeframe.label === tf.label ? 'var(--bg-2)' : 'transparent',
                color: timeframe.label === tf.label ? 'var(--text-1)' : 'var(--text-3)',
                border: '1px solid var(--border-mid)',
                padding: '5px 10px', fontSize: 10, fontFamily: 'var(--mono)',
                cursor: 'pointer', borderRadius: 3,
              }}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats strip */}
      <div style={{
        display: 'flex', gap: 20, padding: '8px 2px',
        fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--text-2)',
        marginBottom: 8,
      }}>
        <span>Sweeps: <b style={{ color: 'var(--text-1)' }}>{stats.count.toLocaleString()}</b></span>
        <span>Tickers: <b style={{ color: 'var(--text-1)' }}>{stats.uniqueTickers}</b></span>
        <span>Total: <b style={{ color: '#f4c430' }}>{fmtNotional(stats.totalNotional)}</b></span>
        {stats.topTicker && (
          <span>Top: <b style={{ color: 'var(--text-1)' }}>{stats.topTicker}</b> ({fmtNotional(stats.topNotional)})</span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-3)' }}>
          {lastRefresh ? `Updated ${new Date(lastRefresh).toLocaleTimeString()}` : 'Loading...'}
        </span>
      </div>

      {error && (
        <div style={{ padding: 10, color: '#ff5656', fontFamily: 'var(--mono)', fontSize: 11 }}>
          Error: {error}
        </div>
      )}

      {loading && sweeps.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 12, textAlign: 'center' }}>
          Loading sweeps...
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          padding: 24, color: 'var(--text-3)', fontSize: 12, textAlign: 'center',
          border: '1px dashed var(--border-faint)', borderRadius: 4,
        }}>
          No sweeps match the current filters.
          {sweeps.length > 0 && ` (${sweeps.length} total in timeframe — relax filters to see them)`}
        </div>
      ) : (
        <div style={{ overflow: 'auto', border: '1px solid var(--border-faint)', borderRadius: 4 }}>
          <table style={{
            width: '100%', borderCollapse: 'collapse',
            fontSize: 11, fontFamily: 'var(--mono)',
          }}>
            <thead style={{
              position: 'sticky', top: 0, background: 'var(--bg-1)',
              borderBottom: '1px solid var(--border-mid)',
            }}>
              <tr>
                {SORT_COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    style={{
                      padding: '8px 10px', textAlign: 'left', cursor: 'pointer',
                      color: sortBy === c.key ? 'var(--text-1)' : 'var(--text-3)',
                      fontWeight: sortBy === c.key ? 700 : 500,
                      userSelect: 'none',
                    }}
                  >
                    {c.label}{sortBy === c.key ? (sortDesc ? ' ↓' : ' ↑') : ''}
                  </th>
                ))}
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>
                  Contract
                </th>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>
                  Δ
                </th>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>
                  Bid/Ask
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => {
                const isCall = (s.option_type || '').toLowerCase() === 'call';
                const rightColor = isCall ? '#10dc9a' : '#ff5656';
                const venues = s.sweep_venues || 0;
                const venueBadge = venues >= 3 ? '#f4c430' : venues >= 2 ? '#10dc9a' : 'var(--text-3)';
                return (
                  <tr
                    key={s.id}
                    style={{
                      borderBottom: '1px solid var(--border-faint)',
                      background: (s.sweep_notional || 0) >= 1_000_000
                        ? 'rgba(244,196,48,0.04)'
                        : 'transparent',
                    }}
                  >
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>
                      <span title={fmtClockET(s.ts) + ' ET'}>{fmtTimeAgo(s.ts)}</span>
                    </td>
                    <td style={{ padding: '6px 10px' }}>
                      <a
                        onClick={(e) => {
                          e.preventDefault();
                          if (onClickTicker) onClickTicker(s.ticker);
                        }}
                        style={{
                          color: 'var(--text-1)', fontWeight: 700, cursor: 'pointer',
                          textDecoration: 'none',
                        }}
                      >
                        {s.ticker}
                      </a>
                    </td>
                    <td style={{
                      padding: '6px 10px', color: '#f4c430', fontWeight: 700,
                    }}>
                      {fmtNotional(s.sweep_notional)}
                    </td>
                    <td style={{ padding: '6px 10px' }}>{fmtInt(s.sweep_contracts)}</td>
                    <td style={{ padding: '6px 10px', color: venueBadge, fontWeight: venues >= 2 ? 700 : 400 }}>
                      {venues}
                    </td>
                    <td style={{ padding: '6px 10px' }}>{s.sweep_prints}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{fmtInt(s.oi)}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{fmtPct(s.iv)}</td>
                    <td style={{ padding: '6px 10px', color: rightColor, fontWeight: 600 }}>
                      ${s.strike?.toFixed(0)}{isCall ? 'C' : 'P'}  <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>{s.expiration}</span>
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>
                      {s.delta != null ? s.delta.toFixed(2) : '--'}
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-3)' }}>
                      {s.bid != null ? `${s.bid.toFixed(2)} / ${s.ask?.toFixed(2)}` : '--'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer note */}
      <div style={{
        padding: '12px 2px', fontSize: 10, color: 'var(--text-3)',
        fontFamily: 'var(--mono)', lineHeight: 1.6,
      }}>
        ⚡ Sweeps are OPRA-tagged ISO prints (condition=95/126/128) — orders routed across multiple exchanges in &lt;500ms,
        indicating urgency + conviction. Venues ≥ 3 (gold) = textbook multi-venue sweep. Highlighted rows = $1M+ notional.
        <br />
        ⚠ Sweeps are Factor 3 of 5. Verify Mir/SOE signal + technical setup + macro context before entry.
      </div>
    </div>
  );
}
