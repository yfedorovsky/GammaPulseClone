import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api.js';
import HitRateStrip from '../components/HitRateStrip.jsx';

/**
 * BIG FLOW tab — UW-style per-contract DAILY option flow aggregates.
 *
 * Unlike the SWEEPS tab (which shows only ISO-tagged prints in 30s rollup
 * windows), this tab shows ALL aggressive flow aggregated to one row per
 * contract-day. Matches the layout your Discord friend's tool shows.
 *
 * Each row includes:
 *   - Total volume + OI (e.g. 84,694 / 9,189)
 *   - Total notional (e.g. $22.2M)
 *   - Dominant side (BUY/SELL/NEUTRAL) with Bought% breakdown
 *   - Sweep share — how much of the total was ISO sweep (7% = real institutional urgency)
 *   - Block share — how much was off-exchange block trades
 *   - Biggest single print of the day
 *   - IV, Delta, Spot
 */

const REFRESH_MS = 15_000;

const NOTIONAL_PRESETS = [
  { label: 'All',      value: 0 },
  { label: '$500K+',   value: 500_000 },
  { label: '$1M+',     value: 1_000_000 },
  { label: '$5M+',     value: 5_000_000 },
  { label: '$10M+',    value: 10_000_000 },
  { label: '$25M+',    value: 25_000_000 },
];

const TYPE_FILTERS = ['ALL', 'CALL', 'PUT'];
const SIDE_FILTERS = ['ALL', 'BUY', 'SELL', 'NEUTRAL'];

const SIDE_COLORS = {
  BUY:     { fg: '#10dc9a', bg: 'rgba(16,220,154,0.08)' },
  SELL:    { fg: '#ff5656', bg: 'rgba(255,86,86,0.08)' },
  NEUTRAL: { fg: 'var(--text-3)', bg: 'transparent' },
};

const TIMEFRAMES = [
  { label: 'Today', days: 0 },
  { label: '3d',    days: 3 },
  { label: '5d',    days: 5 },
  { label: '1w',    days: 7 },
  { label: 'All',   days: null },
];

const SORT_COLUMNS = [
  { key: 'date',           label: 'Date' },
  { key: 'ticker',         label: 'Ticker' },
  { key: 'total_volume',   label: 'Volume' },
  { key: 'oi',             label: 'OI' },
  { key: 'total_notional', label: 'Notional' },
  { key: 'sweep_share',    label: 'Sweep%' },
  { key: 'bought_pct',     label: 'Bought%' },
  { key: 'largest_print_size', label: 'Biggest' },
];


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


export default function BigFlowTab({ onClickTicker }) {
  const [flow, setFlow] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const [tickerQuery, setTickerQuery] = useState('');
  const [minNotional, setMinNotional] = useState(500_000);
  const [minOI, setMinOI] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [sideFilter, setSideFilter] = useState('ALL');
  const [timeframe, setTimeframe] = useState(TIMEFRAMES[2]);  // 5d default
  const [sortBy, setSortBy] = useState('total_notional');
  const [sortDesc, setSortDesc] = useState(true);
  const [goldenOnly, setGoldenOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      let sinceDate = '';
      if (timeframe.days === 0) {
        sinceDate = new Date().toISOString().slice(0, 10);
      } else if (typeof timeframe.days === 'number') {
        const d = new Date();
        d.setDate(d.getDate() - timeframe.days);
        sinceDate = d.toISOString().slice(0, 10);
      }
      const resp = await api.flowDaily({
        sinceDate,
        ticker: '',
        minNotional,
        minOI: parseInt(minOI, 10) || 0,
        side: sideFilter,
        limit: 1000,
      });
      setFlow(resp.flow || []);
      setError(null);
      setLastRefresh(Date.now());
    } catch (e) {
      setError(e.message || 'Failed to load flow');
    } finally {
      setLoading(false);
    }
  }, [timeframe, minNotional, minOI, sideFilter]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // Client-side ticker search + type filter + sort
  const filtered = useMemo(() => {
    let rows = [...flow];

    // Derive fields server doesn't return pre-computed — including GOLDEN FLOW tag.
    // Classifier mirrors server.option_flow_daily.is_golden_flow exactly:
    //   - bought/sold% computed from DIRECTIONAL notional only (excluding neutral)
    //   - symmetric: either BUY≥65% OR SELL≥65% qualifies (insider puts OR calls)
    //   - threshold 65% (UW methodology, not 70%)
    rows = rows.map((r) => {
      const total = r.total_notional || 0;
      const sweepShare = total > 0 ? (r.sweep_notional || 0) / total : 0;
      const buy = r.buy_notional || 0;
      const sell = r.sell_notional || 0;
      const neutral = r.neutral_notional || 0;
      const directional = buy + sell;
      const boughtPct = directional > 0 ? buy / directional : 0;
      const soldPct = directional > 0 ? sell / directional : 0;
      let dominantSide = 'NEUTRAL';
      if (buy > sell && buy > neutral) dominantSide = 'BUY';
      else if (sell > buy && sell > neutral) dominantSide = 'SELL';

      // GOLDEN FLOW classifier — symmetric BUY or SELL dominance
      const vol = r.total_volume || 0;
      const oi = r.oi || 0;
      const volOi = oi > 0 ? vol / oi : Infinity;
      const otmPct = (r.spot > 0 && r.strike > 0) ? Math.abs(r.strike - r.spot) / r.spot : 1.0;
      let dte = 999;
      if (r.date && r.expiration) {
        const d1 = new Date(r.date); const d2 = new Date(r.expiration);
        dte = Math.round((d2 - d1) / 86400000);
      }
      const sideOk = boughtPct >= 0.65 || soldPct >= 0.65;
      const isGolden = (
        total >= 500_000 &&
        sideOk &&
        (oi === 0 || volOi >= 3.0) &&
        otmPct <= 0.025 &&
        dte <= 2
      );

      return {
        ...r,
        sweep_share: sweepShare,
        bought_pct: boughtPct,  // matches server definition (directional only)
        dominant_side: dominantSide,
        vol_oi: volOi === Infinity ? null : volOi,
        otm_pct: otmPct,
        dte,
        is_golden: isGolden,
      };
    });

    if (goldenOnly) {
      rows = rows.filter((r) => r.is_golden);
    }

    const q = tickerQuery.trim().toUpperCase();
    if (q) {
      rows = rows.filter((r) => (r.ticker || '').toUpperCase().includes(q));
    }

    if (typeFilter !== 'ALL') {
      const ot = typeFilter.toLowerCase();
      rows = rows.filter((r) => (r.option_type || '').toLowerCase() === ot);
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
  }, [flow, tickerQuery, typeFilter, sortBy, sortDesc, goldenOnly]);

  const stats = useMemo(() => {
    const tickers = new Set();
    let totalNotional = 0;
    let sweepNotional = 0;
    let buyNotional = 0;
    let sellNotional = 0;
    for (const r of filtered) {
      tickers.add(r.ticker);
      totalNotional += r.total_notional || 0;
      sweepNotional += r.sweep_notional || 0;
      buyNotional += r.buy_notional || 0;
      sellNotional += r.sell_notional || 0;
    }
    const sideTotal = buyNotional + sellNotional;
    const buyPct = sideTotal > 0 ? (buyNotional / sideTotal) * 100 : 0;
    const sweepPct = totalNotional > 0 ? (sweepNotional / totalNotional) * 100 : 0;
    return { count: filtered.length, tickers: tickers.size, totalNotional, sweepNotional, buyNotional, sellNotional, buyPct, sweepPct };
  }, [filtered]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDesc(!sortDesc);
    else { setSortBy(col); setSortDesc(true); }
  };

  return (
    <div style={{ padding: '12px 14px', fontFamily: 'var(--sans)' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10,
        marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-faint)',
      }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          🌊 BIG FLOW
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          All aggressive OPRA flow (not just ISO) • per-contract daily aggregate
        </div>

        <div style={{ flex: 1 }} />

        <input
          type="text" value={tickerQuery}
          onChange={(e) => setTickerQuery(e.target.value)}
          placeholder="Ticker..."
          style={{
            background: 'var(--bg-1)', border: '1px solid var(--border-mid)',
            color: 'var(--text-1)', padding: '5px 10px', borderRadius: 3,
            fontSize: 11, width: 120, fontFamily: 'var(--mono)', textTransform: 'uppercase',
          }}
        />

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

        <input
          type="number" value={minOI}
          onChange={(e) => setMinOI(e.target.value)}
          placeholder="Min OI" min={0}
          style={{
            background: 'var(--bg-1)', border: '1px solid var(--border-mid)',
            color: 'var(--text-1)', padding: '5px 8px', borderRadius: 3,
            fontSize: 11, width: 90, fontFamily: 'var(--mono)',
          }}
        />

        <div style={{ display: 'flex', gap: 2 }}>
          {TYPE_FILTERS.map((t) => (
            <button key={t} onClick={() => setTypeFilter(t)} style={{
              background: typeFilter === t ? 'var(--bg-2)' : 'transparent',
              color: typeFilter === t ? 'var(--text-1)' : 'var(--text-3)',
              border: '1px solid var(--border-mid)', padding: '5px 10px',
              fontSize: 10, fontFamily: 'var(--mono)', cursor: 'pointer', borderRadius: 3,
            }}>{t}</button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 2 }}>
          {SIDE_FILTERS.map((s) => {
            const active = sideFilter === s;
            const color = SIDE_COLORS[s]?.fg || 'var(--text-3)';
            return (
              <button key={s} onClick={() => setSideFilter(s)} style={{
                background: active ? 'var(--bg-2)' : 'transparent',
                color: active ? color : 'var(--text-3)',
                border: '1px solid var(--border-mid)', padding: '5px 10px',
                fontSize: 10, fontFamily: 'var(--mono)', cursor: 'pointer',
                borderRadius: 3, fontWeight: active ? 700 : 400,
              }}>{s}</button>
            );
          })}
        </div>

        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map((tf) => (
            <button key={tf.label} onClick={() => setTimeframe(tf)} style={{
              background: timeframe.label === tf.label ? 'var(--bg-2)' : 'transparent',
              color: timeframe.label === tf.label ? 'var(--text-1)' : 'var(--text-3)',
              border: '1px solid var(--border-mid)', padding: '5px 10px',
              fontSize: 10, fontFamily: 'var(--mono)', cursor: 'pointer', borderRadius: 3,
            }}>{tf.label}</button>
          ))}
        </div>

        {/* GOLDEN FLOW filter — SPY 647P pattern (≥$500K, ≥70% bought, V/OI≥3x, ≤2.5% OTM, ≤2DTE) */}
        <button
          onClick={() => setGoldenOnly(!goldenOnly)}
          title="Show only trades matching the composite insider-flow pattern: ≥$500K, ≥70% bought at ask, V/OI ≥3x, ≤2.5% OTM, ≤2 DTE"
          style={{
            background: goldenOnly ? '#f4c43030' : 'transparent',
            color: goldenOnly ? '#f4c430' : 'var(--text-3)',
            border: '1px solid ' + (goldenOnly ? '#f4c430' : 'var(--border-mid)'),
            padding: '5px 12px', fontSize: 10, fontFamily: 'var(--mono)',
            cursor: 'pointer', borderRadius: 3,
            fontWeight: goldenOnly ? 700 : 500,
          }}
        >
          ⚡ GOLDEN{goldenOnly ? ' ✓' : ''}
        </button>
      </div>

      {/* Stats */}
      <div style={{
        display: 'flex', gap: 20, padding: '8px 2px', fontSize: 11,
        fontFamily: 'var(--mono)', color: 'var(--text-2)', marginBottom: 8, flexWrap: 'wrap',
      }}>
        <span>Contracts: <b style={{ color: 'var(--text-1)' }}>{stats.count.toLocaleString()}</b></span>
        <span>Tickers: <b style={{ color: 'var(--text-1)' }}>{stats.tickers}</b></span>
        <span>Total: <b style={{ color: '#f4c430' }}>{fmtNotional(stats.totalNotional)}</b></span>
        {(stats.buyNotional > 0 || stats.sellNotional > 0) && (
          <>
            <span style={{ color: 'var(--text-3)' }}>|</span>
            <span>Bought: <b style={{ color: SIDE_COLORS.BUY.fg }}>{fmtNotional(stats.buyNotional)}</b> ({stats.buyPct.toFixed(0)}%)</span>
            <span>Sold: <b style={{ color: SIDE_COLORS.SELL.fg }}>{fmtNotional(stats.sellNotional)}</b> ({(100 - stats.buyPct).toFixed(0)}%)</span>
          </>
        )}
        {stats.sweepNotional > 0 && (
          <span style={{ color: 'var(--text-3)' }}>
            |  ISO sweeps: <b style={{ color: '#f4c430' }}>{fmtNotional(stats.sweepNotional)}</b> ({stats.sweepPct.toFixed(0)}%)
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-3)' }}>
          {lastRefresh ? `Updated ${new Date(lastRefresh).toLocaleTimeString()}` : 'Loading...'}
        </span>
      </div>

      {/* Hit-rate strip — forward returns by cohort (ticker + notional filter) */}
      <div style={{ marginBottom: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <HitRateStrip
          label={`BUY-dominant flow${tickerQuery ? ` on ${tickerQuery.toUpperCase()}` : ''}`}
          cohort={{
            sourceType: 'sweep',
            direction: 'BUY',
            ticker: tickerQuery.trim().toUpperCase() || '',
            minNotional,
            lookbackDays: 90,
          }}
        />
        <HitRateStrip
          label="SOE BUY signals"
          cohort={{ sourceType: 'soe_signal', direction: 'BUY', lookbackDays: 90 }}
        />
      </div>

      {error && (
        <div style={{ padding: 10, color: '#ff5656', fontFamily: 'var(--mono)', fontSize: 11 }}>
          Error: {error}
        </div>
      )}

      {loading && flow.length === 0 ? (
        <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 12, textAlign: 'center' }}>
          Loading daily flow...
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          padding: 24, color: 'var(--text-3)', fontSize: 12, textAlign: 'center',
          border: '1px dashed var(--border-faint)', borderRadius: 4,
        }}>
          No daily flow rows yet. Run backfill:
          <pre style={{ marginTop: 10, fontSize: 10, color: 'var(--text-2)' }}>
            python scripts/backfill_option_flow.py --days-back 5 --clean-first
          </pre>
        </div>
      ) : (
        <div style={{ overflow: 'auto', border: '1px solid var(--border-faint)', borderRadius: 4 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'var(--mono)' }}>
            <thead style={{
              position: 'sticky', top: 0, background: 'var(--bg-1)',
              borderBottom: '1px solid var(--border-mid)',
            }}>
              <tr>
                {SORT_COLUMNS.map((c) => (
                  <th key={c.key} onClick={() => toggleSort(c.key)} style={{
                    padding: '8px 10px', textAlign: 'left', cursor: 'pointer',
                    color: sortBy === c.key ? 'var(--text-1)' : 'var(--text-3)',
                    fontWeight: sortBy === c.key ? 700 : 500, userSelect: 'none',
                  }}>
                    {c.label}{sortBy === c.key ? (sortDesc ? ' ↓' : ' ↑') : ''}
                  </th>
                ))}
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>Side</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>Contract</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>IV</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', color: 'var(--text-3)' }}>Δ</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const isCall = (r.option_type || '').toLowerCase() === 'call';
                const side = r.dominant_side;
                const sideColors = SIDE_COLORS[side] || SIDE_COLORS.NEUTRAL;
                const isBig = (r.total_notional || 0) >= 10_000_000;
                const rowBg = isBig ? sideColors.bg.replace('0.08', '0.15') : sideColors.bg;
                const sweepPctRounded = Math.round(r.sweep_share * 100);
                const sweepBadgeColor = sweepPctRounded >= 20 ? '#f4c430' : sweepPctRounded >= 10 ? '#10dc9a' : 'var(--text-3)';

                return (
                  <tr key={`${r.date}|${r.ticker}|${r.strike}|${r.expiration}|${r.option_type}`} style={{
                    borderBottom: '1px solid var(--border-faint)',
                    background: rowBg,
                  }}>
                    <td style={{ padding: '6px 10px', color: 'var(--text-3)' }}>{r.date}</td>
                    <td style={{ padding: '6px 10px' }}>
                      <a onClick={(e) => { e.preventDefault(); if (onClickTicker) onClickTicker(r.ticker); }}
                        style={{
                          color: 'var(--text-1)', fontWeight: 700, cursor: 'pointer',
                          textDecoration: 'none',
                        }}>
                        {r.ticker}
                      </a>
                      {r.is_golden && (
                        <span
                          title="GOLDEN FLOW: matches the composite insider-pattern (≥$500K, ≥70% bought, V/OI ≥3x, ≤2.5% OTM, ≤2 DTE)"
                          style={{
                            marginLeft: 6, fontSize: 9, fontWeight: 700,
                            padding: '1px 4px', borderRadius: 2,
                            background: '#f4c430', color: '#1a1a1a',
                          }}
                        >⚡ GOLD</span>
                      )}
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-1)' }}>{fmtInt(r.total_volume)}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{fmtInt(r.oi)}</td>
                    <td style={{ padding: '6px 10px', color: '#f4c430', fontWeight: 700 }}>{fmtNotional(r.total_notional)}</td>
                    <td style={{ padding: '6px 10px', color: sweepBadgeColor, fontWeight: sweepPctRounded >= 10 ? 700 : 400 }}>
                      {sweepPctRounded}%
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{Math.round(r.bought_pct * 100)}%</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>
                      {r.largest_print_size > 0 ? (
                        <span title={`${r.largest_print_time || ''} on exch ${r.largest_print_venue}`}>
                          {fmtInt(r.largest_print_size)} @ ${r.largest_print_price?.toFixed(2)}
                          {r.largest_print_is_sweep ? ' ⚡' : ''}
                        </span>
                      ) : '--'}
                    </td>
                    <td style={{ padding: '6px 10px', color: sideColors.fg, fontWeight: 700, fontSize: 10 }}>
                      {side === 'BUY' ? '▲ BUY' : side === 'SELL' ? '▼ SELL' : '• NEUTRAL'}
                    </td>
                    <td style={{ padding: '6px 10px', color: isCall ? '#10dc9a' : '#ff5656', fontWeight: 600 }}>
                      ${r.strike?.toFixed(0)}{isCall ? 'C' : 'P'}{' '}
                      <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>{r.expiration}</span>
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-3)' }}>{fmtPct(r.iv)}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text-3)' }}>
                      {r.delta != null ? r.delta.toFixed(2) : '--'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{
        padding: '12px 2px', fontSize: 10, color: 'var(--text-3)',
        fontFamily: 'var(--mono)', lineHeight: 1.6,
      }}>
        🌊 All aggressive OPRA flow — includes ISO sweeps AND non-sweep bought-at-ask/sold-at-bid prints.
        Each row = one contract-day aggregate. Sweep% column shows how much of the total flow came through ISO orders
        (&gt;10% = real institutional urgency, &gt;20% gold). ⚡ on biggest-print = that single print was an ISO sweep.
      </div>
    </div>
  );
}
