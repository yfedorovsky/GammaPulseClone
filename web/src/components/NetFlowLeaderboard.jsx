import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';

/**
 * NET FLOW LEADERBOARD — per-ticker call $ - put $ aggregated for today.
 *
 * Inspired by OG GammaPulse's Top Movers view. Shows:
 *   - Market-wide call vs put $ ratio bar at top
 *   - Per-ticker rows: spot, structural level (king/floor/ceiling),
 *     visual bars (red puts left, green calls right), net $
 *   - Filters: All / Bullish / Bearish
 *
 * Different from our INFORMED FLOW / CLUSTER strips:
 *   - INFORMED FLOW = per-contract instantaneous (Panuwat-style insider)
 *   - NetFlow Leaderboard = full-day aggregate per-ticker (where's smart
 *     money positioning across all contracts on a name)
 *
 * Use both: INFORMED FLOW catches the entry, NetFlow Leaderboard tracks
 * the continuation / scale of positioning.
 *
 * 2026-05-28 PM.
 */
const REFRESH_MS = 20_000;

const FILTERS = ['All', 'Bullish', 'Bearish'];
const SORTS = [
  { key: 'net', label: 'NET $' },
  { key: 'call', label: 'CALL $' },
  { key: 'put', label: 'PUT $' },
  { key: 'ticker', label: 'A-Z' },
];

function fmtBig(n) {
  if (!n) return '$0';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}
function fmtPrice(n) {
  if (n == null) return '--';
  if (n >= 1000) return `$${n.toFixed(2).replace(/\.00$/, '')}`;
  return `$${n.toFixed(2)}`;
}
function fmtNet(n) {
  const s = fmtBig(n);
  return n >= 0 ? `+${s}` : s;
}

export default function NetFlowLeaderboard({ onClickTicker }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState('All');
  const [sort, setSort] = useState('net');
  const [collapsed, setCollapsed] = useState(false);
  const inFlightRef = useRef(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 20_000);
        const res = await fetch(`${api.base}/api/flow/net_movers?limit=30`, {
          signal: ctrl.signal,
        });
        clearTimeout(tid);
        const json = await res.json();
        if (alive) setData(json);
      } catch {
        // ignore
      } finally {
        inFlightRef.current = false;
      }
    }
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const movers = useMemo(() => {
    if (!data?.movers) return [];
    let m = data.movers.slice();
    if (filter === 'Bullish') m = m.filter((r) => r.net_dollars > 0);
    if (filter === 'Bearish') m = m.filter((r) => r.net_dollars < 0);
    if (sort === 'net') m.sort((a, b) => b.net_dollars - a.net_dollars);
    if (sort === 'call') m.sort((a, b) => b.call_dollars - a.call_dollars);
    if (sort === 'put') m.sort((a, b) => b.put_dollars - a.put_dollars);
    if (sort === 'ticker') m.sort((a, b) => a.ticker.localeCompare(b.ticker));
    if (filter === 'Bearish' && sort === 'net') m.reverse(); // most negative first
    return m;
  }, [data, filter, sort]);

  if (!data?.movers?.length) return null;

  const totalCall = data.total_call_dollars || 0;
  const totalPut = data.total_put_dollars || 0;
  const total = totalCall + totalPut;
  const callPct = total > 0 ? (totalCall / total) * 100 : 50;

  // Max bar width — use the larger of max call $ or max put $ across visible rows
  const maxBarVal = movers.reduce(
    (m, r) => Math.max(m, r.call_dollars, r.put_dollars),
    1,
  );

  return (
    <div style={{
      marginBottom: 14,
      border: '1px solid var(--border-faint)',
      borderRadius: 6,
      background: 'var(--bg-card)',
      padding: '10px 12px',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 800, color: 'var(--text-1)',
          letterSpacing: 0.5, cursor: 'pointer',
        }} onClick={() => setCollapsed((c) => !c)}>
          NET FLOW LEADERBOARD
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          {data.n_tickers} tickers · last {data.since_hours}h
        </div>

        <div style={{ flex: 1 }} />

        {/* Filter chips */}
        {FILTERS.map((f) => (
          <button key={f}
            onClick={() => setFilter(f)}
            style={{
              fontSize: 10, padding: '3px 8px', borderRadius: 3,
              border: '1px solid var(--border-faint)',
              background: filter === f ? '#f4c430' : 'var(--bg-1)',
              color: filter === f ? '#000' : 'var(--text-2)',
              cursor: 'pointer',
              fontWeight: filter === f ? 700 : 500,
            }}>
            {f}
          </button>
        ))}

        <div style={{ width: 8 }} />

        <select value={sort} onChange={(e) => setSort(e.target.value)}
          style={{
            fontSize: 10, padding: '3px 8px', borderRadius: 3,
            border: '1px solid var(--border-faint)',
            background: 'var(--bg-1)', color: 'var(--text-1)',
          }}>
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>Sort: {s.label}</option>
          ))}
        </select>
      </div>

      {/* Market-wide ratio bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12,
      }}>
        <span style={{
          color: '#10dc9a', fontSize: 11, fontFamily: 'var(--mono)', minWidth: 90,
        }}>
          {fmtBig(totalCall)} Calls
        </span>
        <div style={{
          flex: 1, height: 8, borderRadius: 4, overflow: 'hidden',
          background: 'var(--bg-2)', position: 'relative',
        }}>
          <div style={{
            position: 'absolute', left: 0, top: 0, height: '100%',
            width: `${callPct}%`, background: '#10dc9a',
          }} />
          <div style={{
            position: 'absolute', right: 0, top: 0, height: '100%',
            width: `${100 - callPct}%`, background: '#ff5656',
          }} />
        </div>
        <span style={{
          color: '#ff5656', fontSize: 11, fontFamily: 'var(--mono)', minWidth: 90,
          textAlign: 'right',
        }}>
          Puts {fmtBig(totalPut)}
        </span>
      </div>
      <div style={{
        textAlign: 'center', fontSize: 9, color: 'var(--text-3)',
        marginTop: -6, marginBottom: 8,
      }}>
        Total Market Flow · {totalCall > totalPut
          ? `${(totalCall / Math.max(totalPut, 1)).toFixed(1)}:1 bullish`
          : `${(totalPut / Math.max(totalCall, 1)).toFixed(1)}:1 bearish`}
      </div>

      {/* Rows */}
      {!collapsed && (
        <div style={{ display: 'grid', gap: 4 }}>
          {/* Header row */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 90px 1fr',
            fontSize: 9, color: 'var(--text-3)',
            letterSpacing: 0.5, fontWeight: 700,
            padding: '4px 6px', borderBottom: '1px solid var(--border-faint)',
          }}>
            <span style={{ textAlign: 'right', paddingRight: 8 }}>PUT $</span>
            <span style={{ textAlign: 'center' }}>NET</span>
            <span style={{ paddingLeft: 8 }}>CALL $</span>
          </div>

          {movers.map((r) => {
            const isPos = r.net_dollars >= 0;
            const callWidth = (r.call_dollars / maxBarVal) * 50; // 50% max each side
            const putWidth = (r.put_dollars / maxBarVal) * 50;
            const lvl = r.king ? { label: 'King', val: r.king }
              : r.floor ? { label: 'Floor', val: r.floor }
              : r.ceiling ? { label: 'Ceiling', val: r.ceiling }
              : null;
            return (
              <div key={r.ticker}
                onClick={() => onClickTicker && onClickTicker(r.ticker)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 110px 1fr',
                  alignItems: 'center',
                  cursor: onClickTicker ? 'pointer' : 'default',
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                  padding: '6px 6px',
                  borderRadius: 3,
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-1)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                {/* PUT side — bar grows right-to-left */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
                  gap: 8, paddingRight: 8,
                }}>
                  <span style={{
                    color: r.put_dollars > 0 ? '#ff5656' : 'var(--text-3)',
                    fontSize: 10, minWidth: 60, textAlign: 'right',
                  }}>
                    {r.put_dollars > 0 ? fmtBig(r.put_dollars) : ''}
                  </span>
                  <div style={{
                    width: `${putWidth}%`, height: 14,
                    background: 'linear-gradient(to left, rgba(255,86,86,0.6), rgba(255,86,86,0.1))',
                    borderRadius: 2,
                  }} />
                </div>

                {/* CENTER — ticker + level */}
                <div style={{ textAlign: 'center', lineHeight: 1.2 }}>
                  <div style={{ fontWeight: 800, fontSize: 12, color: 'var(--text-1)' }}>
                    {r.ticker}
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text-2)' }}>
                    {fmtPrice(r.spot)}
                  </div>
                  <div style={{
                    fontSize: 9,
                    color: isPos ? '#10dc9a' : '#ff5656',
                    fontWeight: 700,
                  }}>
                    Net {fmtNet(r.net_dollars)}
                  </div>
                  {lvl && (
                    <div style={{ fontSize: 8, color: '#f4c430' }}>
                      ⚡ {lvl.label} {fmtPrice(lvl.val)}
                    </div>
                  )}
                </div>

                {/* CALL side — bar grows left-to-right */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, paddingLeft: 8,
                }}>
                  <div style={{
                    width: `${callWidth}%`, height: 14,
                    background: 'linear-gradient(to right, rgba(16,220,154,0.1), rgba(16,220,154,0.6))',
                    borderRadius: 2,
                  }} />
                  <span style={{
                    color: r.call_dollars > 0 ? '#10dc9a' : 'var(--text-3)',
                    fontSize: 10, minWidth: 60,
                  }}>
                    {r.call_dollars > 0 ? fmtBig(r.call_dollars) : ''}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
