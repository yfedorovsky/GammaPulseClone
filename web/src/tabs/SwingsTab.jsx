import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api.js';

const TAG_COLORS = {
  LEADER: '#10dc9a',
  TOP_SECTOR: '#f4c430',
  FIRST_PULLBACK: '#6ec6ff',
  NEAR_BREAKOUT: '#ff9800',
  CHEAP_IV: '#b39ddb',
  MIR_BASKET: '#e040fb',
  EXTENDED: '#ff5656',
  EARNINGS_SOON: '#ff5656',
};

const RUNNER_STATES = {
  DAY1_BREAKOUT:  { color: '#6ec6ff', label: 'DAY 1' },
  DAY2_CONFIRM:   { color: '#f4c430', label: 'DAY 2' },
  DAY3_EXPLOSION: { color: '#ff5656', label: 'DAY 3' },
};

// Backtest-validated WR per regime (365d, 251 trading days)
const VIX_REGIMES = {
  VIX_BULL_COMPRESS:  { color: '#10dc9a', label: 'BULL COMPRESS', wr: 80 },
  VIX_ELEVATED_COMP:  { color: '#10dc9a', label: 'VOL NORMALIZING', wr: 87 },
  VIX_LOW_FLAT:       { color: '#8a93a8', label: 'VIX FLAT', wr: 46 },
  VIX_ELEVATED_FLAT:  { color: '#ff9800', label: 'VIX STUCK', wr: 29 },
  VIX_LOW_RISING:     { color: '#ff5656', label: 'VIX RISING', wr: 13 },
  VIX_HIGH:           { color: '#ff9800', label: 'VIX HIGH', wr: 58 },
  VIX_SPIKE:          { color: '#ff5656', label: 'VIX SPIKE', wr: 20 },
};

const REFRESH_MS = 30_000;

function TagBadge({ tag }) {
  const color = TAG_COLORS[tag] || '#8a93a8';
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
      background: `${color}22`, color, border: `1px solid ${color}44`,
      marginRight: 4, whiteSpace: 'nowrap',
    }}>
      {tag.replace('_', ' ')}
    </span>
  );
}

function SectorRankBar({ ranks }) {
  if (!ranks || !Object.keys(ranks).length) return null;
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
      {Object.entries(ranks).map(([etf, rank]) => {
        const color = rank <= 3 ? '#10dc9a' : rank >= 9 ? '#ff5656' : '#8a93a8';
        return (
          <span key={etf} style={{
            fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
            background: `${color}18`, color, border: `1px solid ${color}33`,
            fontFamily: 'var(--mono)',
          }}>
            {rank}. {etf}
          </span>
        );
      })}
    </div>
  );
}

export default function SwingsTab() {
  const [data, setData] = useState(null);
  const [vixRegime, setVixRegime] = useState(null);
  const [mode, setMode] = useState('standard');
  const [loading, setLoading] = useState(true);
  const [sortCol, setSortCol] = useState('swing_score');
  const [sortDir, setSortDir] = useState(-1);

  const load = useCallback(async () => {
    try {
      const [d, v] = await Promise.all([
        api.swingScanner(mode),
        api.vixRegime().catch(() => null),
      ]);
      setData(d);
      if (v) setVixRegime(v);
    } catch (e) {
      console.error('[SwingsTab] load error:', e);
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    setLoading(true);
    load();
    const iv = setInterval(load, REFRESH_MS);
    return () => clearInterval(iv);
  }, [load]);

  const tickers = data?.tickers || [];
  const sorted = [...tickers].sort((a, b) => {
    const av = a[sortCol] ?? 0;
    const bv = b[sortCol] ?? 0;
    return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
  });

  const handleSort = (col) => {
    if (col === sortCol) setSortDir(-sortDir);
    else { setSortCol(col); setSortDir(-1); }
  };

  const ColHeader = ({ col, label, width, align }) => (
    <th onClick={() => handleSort(col)} style={{
      width, textAlign: align || 'left', cursor: 'pointer', userSelect: 'none',
      padding: '6px 8px', fontSize: 9, fontWeight: 700, color: 'var(--text-3)',
      textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: '1px solid var(--border-faint)',
    }}>
      {label} {sortCol === col ? (sortDir > 0 ? '\u25B2' : '\u25BC') : ''}
    </th>
  );

  const spyRegime = data?.spy_regime;
  const gateStats = data?.gate_stats || {};

  return (
    <div style={{ padding: '16px 20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 800 }}>
          <span style={{ color: '#f4c430' }}>Swing</span> Watchlist
        </span>

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 1, background: 'var(--border-faint)', borderRadius: 'var(--radius-md)', overflow: 'hidden', marginLeft: 12 }}>
          {['standard', 'wifey'].map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              padding: '4px 14px', fontSize: 10, fontWeight: 700, border: 'none',
              background: mode === m ? 'var(--bg-card)' : 'transparent',
              color: mode === m ? '#f4c430' : 'var(--text-3)',
              cursor: 'pointer', textTransform: 'uppercase',
            }}>
              {m === 'standard' ? '7-14 DTE' : 'Wifey 14-30 DTE'}
            </button>
          ))}
        </div>

        {/* VIX regime badge */}
        {vixRegime && vixRegime.regime && VIX_REGIMES[vixRegime.regime] && (() => {
          const r = VIX_REGIMES[vixRegime.regime];
          return (
            <span
              title={vixRegime.label || ''}
              style={{
                fontSize: 10, fontWeight: 800, padding: '4px 10px', borderRadius: 4,
                background: `${r.color}22`, color: r.color, border: `1px solid ${r.color}55`,
                fontFamily: 'var(--mono)', whiteSpace: 'nowrap', marginLeft: 8,
              }}
            >
              {r.label} · VIX {vixRegime.vix_current?.toFixed(1)}{' '}
              ({vixRegime.change_pct >= 0 ? '+' : ''}{vixRegime.change_pct?.toFixed(1)}%) · {r.wr}% WR
            </span>
          );
        })()}

        {/* Stats */}
        <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 'auto', fontFamily: 'var(--mono)' }}>
          {gateStats.passed || 0} / {gateStats.total || 0} pass
          {spyRegime && <> | SPY: <span style={{ color: spyRegime === 'BULL' ? '#10dc9a' : '#ff5656' }}>{spyRegime}</span></>}
          {data?.spy_spot && <> ${data.spy_spot} vs EMA21 ${data.spy_ema21}</>}
        </span>

        <button className="ctrl-btn" onClick={load} style={{ fontSize: 9, color: '#10dc9a' }}>
          REFRESH
        </button>
      </div>

      {/* Sector ranks */}
      <SectorRankBar ranks={data?.sector_ranks} />

      {/* Gate failure summary */}
      {gateStats.failed && Object.keys(gateStats.failed).length > 0 && (
        <details style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 8 }}>
          <summary style={{ cursor: 'pointer' }}>Gate stats</summary>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 4 }}>
            {Object.entries(gateStats.failed).sort((a, b) => b[1] - a[1]).map(([r, c]) => (
              <span key={r} style={{ fontFamily: 'var(--mono)' }}>{r}: {c}</span>
            ))}
          </div>
        </details>
      )}

      {/* SPY bear regime warning */}
      {spyRegime === 'BEAR' && (
        <div style={{ padding: 16, textAlign: 'center', color: '#ff5656', fontSize: 14, fontWeight: 700 }}>
          SPY below 21 EMA — long swing scanner paused
        </div>
      )}

      {/* Loading */}
      {loading && !tickers.length && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>Loading...</div>
      )}

      {/* Empty */}
      {!loading && !tickers.length && spyRegime !== 'BEAR' && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-3)' }}>
          No tickers pass all gates. Waiting for next scan cycle...
        </div>
      )}

      {/* Table */}
      {tickers.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'var(--mono)' }}>
            <thead>
              <tr>
                <ColHeader col="swing_score" label="Score" width={60} align="right" />
                <ColHeader col="ticker" label="Ticker" width={65} />
                <ColHeader col="spot" label="Spot" width={70} align="right" />
                <ColHeader col="rts_score" label="RTS" width={45} align="right" />
                <ColHeader col="adr_pct" label="ADR%" width={55} align="right" />
                <ColHeader col="rvol" label="RVOL" width={55} align="right" />
                <ColHeader col="ema21_dist_pct" label="vs EMA21" width={65} align="right" />
                <ColHeader col="dist_to_high_pct" label="vs 20d Hi" width={65} align="right" />
                <ColHeader col="sector_rank" label="Sect" width={55} />
                <ColHeader col="ivhv" label="IV/HV" width={55} align="right" />
                <ColHeader col="runner_score" label="Runner" width={75} align="center" />
                <th style={{ padding: '6px 8px', fontSize: 9, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', borderBottom: '1px solid var(--border-faint)' }}>
                  Option
                </th>
                <th style={{ padding: '6px 8px', fontSize: 9, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', borderBottom: '1px solid var(--border-faint)' }}>
                  Tags
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((t, i) => {
                const opt = t.option || {};
                const scoreColor = t.swing_score >= 70 ? '#10dc9a' : t.swing_score >= 50 ? '#f4c430' : '#8a93a8';
                const rtsColor = t.rts_score >= 70 ? '#10dc9a' : t.rts_score >= 60 ? '#f4c430' : '#8a93a8';
                return (
                  <tr key={t.ticker} style={{
                    borderBottom: '1px solid var(--border-faint)',
                    background: t._new_entry ? '#10dc9a08' : 'transparent',
                  }}>
                    <td style={{ padding: '8px', textAlign: 'right', fontWeight: 800, color: scoreColor, fontSize: 14 }}>
                      {t.swing_score.toFixed(0)}
                    </td>
                    <td style={{ padding: '8px', fontWeight: 700, color: 'var(--text-1)' }}>
                      {t.ticker}
                      {t._new_entry && <span style={{ fontSize: 8, color: '#10dc9a', marginLeft: 4 }}>NEW</span>}
                    </td>
                    <td style={{ padding: '8px', textAlign: 'right' }}>${t.spot.toFixed(2)}</td>
                    <td style={{ padding: '8px', textAlign: 'right', fontWeight: 700, color: rtsColor }}>{t.rts_score}</td>
                    <td style={{ padding: '8px', textAlign: 'right' }}>{t.adr_pct.toFixed(1)}%</td>
                    <td style={{ padding: '8px', textAlign: 'right', color: (t.rvol || 0) >= 1.5 ? '#10dc9a' : 'var(--text-2)' }}>
                      {t.rvol ? `${t.rvol.toFixed(1)}x` : '-'}
                    </td>
                    <td style={{ padding: '8px', textAlign: 'right', color: t.ema21_dist_pct > 8 ? '#ff5656' : t.ema21_dist_pct < 2 ? '#6ec6ff' : 'var(--text-2)' }}>
                      +{t.ema21_dist_pct.toFixed(1)}%
                    </td>
                    <td style={{ padding: '8px', textAlign: 'right', color: t.dist_to_high_pct < 3 ? '#10dc9a' : 'var(--text-3)' }}>
                      -{t.dist_to_high_pct.toFixed(1)}%
                    </td>
                    <td style={{ padding: '8px' }}>
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                        background: t.sector_rank <= 3 ? '#10dc9a22' : t.sector_rank >= 9 ? '#ff565622' : 'var(--bg-card)',
                        color: t.sector_rank <= 3 ? '#10dc9a' : t.sector_rank >= 9 ? '#ff5656' : 'var(--text-3)',
                      }}>
                        {t.sector || '?'} #{t.sector_rank}
                      </span>
                    </td>
                    <td style={{ padding: '8px', textAlign: 'right', color: (t.ivhv || 0) > 1.2 ? '#ff5656' : '#10dc9a' }}>
                      {t.ivhv ? t.ivhv.toFixed(2) : '-'}
                    </td>
                    <td style={{ padding: '8px', textAlign: 'center' }}>
                      {t.runner_state ? (() => {
                        const rs = RUNNER_STATES[t.runner_state];
                        if (!rs) return '-';
                        return (
                          <span style={{
                            fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
                            background: `${rs.color}22`, color: rs.color,
                            border: `1px solid ${rs.color}44`, whiteSpace: 'nowrap',
                          }}>
                            {rs.label}{t.runner_score != null ? ` (${Math.round(t.runner_score)})` : ''}
                            {t.runner_total_gain != null ? ` +${t.runner_total_gain.toFixed(1)}%` : ''}
                          </span>
                        );
                      })() : <span style={{ color: 'var(--text-4)' }}>-</span>}
                    </td>
                    <td style={{ padding: '8px', fontSize: 10, color: 'var(--text-3)' }}>
                      {opt.strike ? `$${opt.strike} ${opt.exp?.slice(5)} ${opt.dte}d sp=${opt.spread_pct}% OI=${opt.oi}` : '-'}
                    </td>
                    <td style={{ padding: '8px' }}>
                      {(t.tags || []).map(tag => <TagBadge key={tag} tag={tag} />)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
