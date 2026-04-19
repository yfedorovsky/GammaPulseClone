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
  GROUP_STRENGTH: '#4fc3f7',  // IBD rotation: ≥3 members of same top-5 group qualifying
  SECTOR_LEADER:  '#ffd700',  // IBD Sector Leader — O'Neil CAN-SLIM pass (premier tier, gold)
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

// Oil regime badge palette — 4-LLM consensus (Apr 16 2026)
const OIL_REGIMES = {
  OIL_SPIKE_RISKOFF:  { color: '#ff5656', label: 'OIL RISK-OFF' },
  STAGFLATION_FEAR:   { color: '#ff5656', label: 'STAGFLATION' },
  OIL_UP_MILD:        { color: '#ff9800', label: 'OIL ELEVATED' },
  OIL_SPIKE:          { color: '#ff9800', label: 'OIL SPIKE' },
  OIL_DEMAND_RELIEF:  { color: '#10dc9a', label: 'DEMAND RELIEF' },
  OIL_CRASH_RELIEF:   { color: '#10dc9a', label: 'CRASH RELIEF' },
  OIL_DOWN_MILD:      { color: '#8a93a8', label: 'OIL DOWN' },
  OIL_CRASH:          { color: '#8a93a8', label: 'OIL CRASH' },
  OIL_CALM:           null,  // no badge — don't clutter UI on normal days
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
  const [oilRegime, setOilRegime] = useState(null);
  const [protoRunners, setProtoRunners] = useState(null);
  const [protoOpen, setProtoOpen] = useState(false);
  const [mode, setMode] = useState('standard');
  const [loading, setLoading] = useState(true);
  const [sortCol, setSortCol] = useState('swing_score');
  const [sortDir, setSortDir] = useState(-1);

  const load = useCallback(async () => {
    try {
      const [d, v, o, p] = await Promise.all([
        api.swingScanner(mode),
        api.vixRegime().catch(() => null),
        api.oilRegime().catch(() => null),
        api.protoRunners().catch(() => null),
      ]);
      setData(d);
      if (v) setVixRegime(v);
      if (o) setOilRegime(o);
      if (p) setProtoRunners(p);
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

        {/* Oil regime badge (hidden on OIL_CALM to reduce clutter) */}
        {oilRegime && oilRegime.regime && OIL_REGIMES[oilRegime.regime] && (() => {
          const r = OIL_REGIMES[oilRegime.regime];
          return (
            <span
              title={oilRegime.label || ''}
              style={{
                fontSize: 10, fontWeight: 800, padding: '4px 10px', borderRadius: 4,
                background: `${r.color}22`, color: r.color, border: `1px solid ${r.color}55`,
                fontFamily: 'var(--mono)', whiteSpace: 'nowrap', marginLeft: 8,
              }}
            >
              🛢 {r.label} · USO {oilRegime.uso_change_pct >= 0 ? '+' : ''}
              {oilRegime.uso_change_pct?.toFixed(1)}%
              {oilRegime.runner_score_modifier !== 0 && (
                <> · {oilRegime.runner_score_modifier > 0 ? '+' : ''}{oilRegime.runner_score_modifier}</>
              )}
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

      {/* PROTO_RUNNER observation panel (v3 — AMD case study) */}
      {protoRunners && (protoRunners.rows?.length > 0) && (() => {
        const pending = (protoRunners.rows || []).filter(r => r.outcome === 'PENDING');
        const s = protoRunners.summary || {};
        if (pending.length === 0 && s.promoted === 0 && s.faded === 0) return null;
        return (
          <div style={{
            marginBottom: 10, padding: '8px 12px',
            background: 'var(--bg-card)',
            border: '1px solid #6a5cff33',
            borderRadius: 'var(--radius-sm)',
            fontSize: 10, fontFamily: 'var(--mono)',
          }}>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
              onClick={() => setProtoOpen(!protoOpen)}
            >
              <span style={{ fontSize: 12 }}>📡</span>
              <span style={{ fontWeight: 800, color: '#a89bff' }}>
                PROTO_RUNNERS
              </span>
              <span style={{ color: '#a89bff' }}>
                {pending.length} watching
              </span>
              {s.hit_rate_pct !== null && s.hit_rate_pct !== undefined && (
                <span style={{ color: 'var(--text-3)' }}>
                  · hit rate {s.hit_rate_pct}% ({s.promoted}/{s.promoted + s.faded})
                </span>
              )}
              <span style={{ color: 'var(--text-3)', marginLeft: 'auto' }}>
                {protoOpen ? '▲' : '▼'} stealth-grind observation (no alerts / no trades)
              </span>
            </div>
            {protoOpen && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {(protoRunners.rows || []).slice(0, 20).map((r) => {
                  const gains = r.gains || [];
                  const cps = r.close_pcts || [];
                  const rvs = r.rvols || [];
                  const outcomeColor = {
                    PENDING: '#a89bff', PROMOTED: '#10dc9a',
                    FADED: '#ff6b6b', EXPIRED: 'var(--text-3)',
                  }[r.outcome] || 'var(--text-3)';
                  return (
                    <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span style={{ fontWeight: 800, width: 55 }}>{r.ticker}</span>
                      <span style={{ color: outcomeColor, width: 70 }}>{r.outcome}</span>
                      <span style={{ color: 'var(--text-3)', width: 80 }}>{r.detection_date}</span>
                      <span style={{ width: 50 }}>{r.window_days}d</span>
                      <span style={{
                        color: r.total_gain_pct >= 0 ? '#10dc9a' : '#ff6b6b',
                        fontWeight: 700, width: 70,
                      }}>
                        {r.total_gain_pct >= 0 ? '+' : ''}{r.total_gain_pct?.toFixed(2)}%
                      </span>
                      <span style={{ color: 'var(--text-3)' }}>
                        gains {gains.map(g => (g >= 0 ? '+' : '') + g.toFixed(1) + '%').join('/')}
                      </span>
                      <span style={{ color: 'var(--text-3)' }}>
                        cp {cps.map(c => Math.round(c * 100) + '%').join('/')}
                      </span>
                      <span style={{ color: 'var(--text-3)' }}>
                        RVOL {rvs.map(v => v.toFixed(2) + 'x').join('/')}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })()}

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
