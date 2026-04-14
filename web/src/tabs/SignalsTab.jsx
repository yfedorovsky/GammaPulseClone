import React, { useEffect, useState, useMemo } from 'react';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';

const GRADES = ['All Grades', 'A+', 'A', 'B+', 'B', 'C'];
const OUTCOMES = ['All Outcomes', 'PENDING', 'WIN', 'LOSS', 'EXPIRED'];

const GRADE_COLOR = {
  'A+': '#10dc9a',
  A: '#10dc9a',
  'B+': '#f4c430',
  B: '#f4c430',
  C: '#ff5656',
};
const GRADE_BG = {
  'A+': 'rgba(16,220,154,0.12)',
  A: 'rgba(16,220,154,0.12)',
  'B+': 'rgba(244,196,48,0.12)',
  B: 'rgba(244,196,48,0.12)',
  C: 'rgba(255,86,86,0.12)',
};
const STATUS_STYLE = {
  PENDING: { color: '#8a93a8' },
  WIN: { color: '#10dc9a', fontWeight: 800 },
  LOSS: { color: '#ff5656', fontWeight: 800 },
  EXPIRED: { color: '#5a6478' },
};

export default function SignalsTab() {
  const [signals, setSignals] = useState([]);
  const [stats, setStats] = useState(null);
  const [gradeFilter, setGradeFilter] = useState('All Grades');
  const [outcomeFilter, setOutcomeFilter] = useState('All Outcomes');
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [abData, setAbData] = useState(null);
  const [showAB, setShowAB] = useState(false);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, []);

  // AB results (slower poll — 60s)
  useEffect(() => {
    if (!showAB) return;
    loadAB();
    const iv = setInterval(loadAB, 60_000);
    return () => clearInterval(iv);
  }, [showAB]);

  async function load() {
    try {
      const [s, st] = await Promise.all([api.signals(100), api.signalStats()]);
      setSignals(s.signals || []);
      setStats(st);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }

  async function loadAB() {
    try {
      const data = await api.abResults();
      setAbData(data);
    } catch {}
  }

  const filtered = useMemo(() => {
    let rows = [...signals];
    if (gradeFilter !== 'All Grades') rows = rows.filter((s) => s.grade === gradeFilter);
    if (outcomeFilter !== 'All Outcomes') rows = rows.filter((s) => s.status === outcomeFilter);
    return rows;
  }, [signals, gradeFilter, outcomeFilter]);

  const todayCount = useMemo(() => {
    const todayStart = Math.floor(new Date().setHours(0, 0, 0, 0) / 1000);
    return signals.filter((s) => s.ts >= todayStart).length;
  }, [signals]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
      {/* Title */}
      <div style={{ padding: '16px 20px 8px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 800 }}>
          <span style={{ color: '#f4c430' }}>⚡</span> SOE <span style={{ color: '#10dc9a' }}>Signals</span>
        </span>
        <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xs)', padding: '3px 10px', background: 'rgba(255,255,255,0.04)', borderRadius: 6 }}>
          Signal → Strike → Trade
        </span>
        <span style={{ color: 'var(--text-dim)', fontSize: 'var(--fs-xxs)', marginLeft: 'auto' }}>
          GammaPulse Pro v4.0
        </span>
      </div>

      {/* Stats cards */}
      <div style={{ display: 'flex', gap: 1, margin: '8px 20px', background: 'var(--border-faint)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
        {[
          { label: 'TOTAL SIGNALS', val: stats?.total ?? 0, color: 'var(--text-1)' },
          { label: 'WINS', val: stats?.wins ?? 0, color: '#10dc9a' },
          { label: 'LOSSES', val: stats?.losses ?? 0, color: '#ff5656' },
          { label: 'PENDING', val: stats?.pending ?? 0, color: '#8a93a8' },
          { label: 'WIN RATE', val: stats?.win_rate ? `${stats.win_rate}%` : '0%', color: '#f4c430' },
          { label: '24H SIGNALS', val: todayCount, color: '#10dc9a' },
        ].map((c) => (
          <div key={c.label} style={{ flex: 1, padding: '14px 16px', background: 'var(--bg-panel)', textAlign: 'center' }}>
            <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>{c.label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: c.color, fontFamily: 'var(--mono)' }}>{c.val}</div>
          </div>
        ))}
      </div>

      {/* Win rate by grade */}
      {stats?.by_grade && Object.keys(stats.by_grade).length > 0 && (
        <div style={{ margin: '8px 20px', padding: '14px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border-faint)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-3)', marginBottom: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Win Rate by Conviction Grade</div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {['A+', 'A', 'B+', 'B', 'C'].filter((g) => stats.by_grade[g]).map((g) => {
              const b = stats.by_grade[g];
              return (
                <div key={g} style={{ padding: '10px 16px', border: `1px solid ${GRADE_COLOR[g] || 'var(--border-faint)'}`, borderRadius: 'var(--radius-md)', textAlign: 'center', minWidth: 80, background: GRADE_BG[g] }}>
                  <div style={{ display: 'inline-block', padding: '2px 10px', borderRadius: 6, border: `1px solid ${GRADE_COLOR[g]}`, color: GRADE_COLOR[g], fontWeight: 800, fontSize: 'var(--fs-md)', marginBottom: 4 }}>{g}</div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: GRADE_COLOR[g], fontFamily: 'var(--mono)' }}>{b.win_rate}%</div>
                  <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>{b.wins}W / {b.losses}L / {b.total}T</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* A/B Test Panel */}
      <div style={{ margin: '8px 20px' }}>
        <button
          className="ctrl-btn"
          onClick={() => setShowAB(!showAB)}
          style={{ fontSize: 10, padding: '4px 12px', background: showAB ? 'rgba(162,77,255,0.15)' : undefined, color: showAB ? '#bb7cff' : undefined, border: showAB ? '1px solid rgba(162,77,255,0.3)' : undefined }}
        >
          {showAB ? '▼' : '▶'} A/B Test: Mir+GEX vs Mir-only
        </button>
        {showAB && abData && abData.total > 0 && (() => {
          const a = abData.summary?.book_a || {};
          const b = abData.summary?.book_b || {};
          const gex = abData.gex_contribution || {};
          const ef = gex.entry_filter || {};
          return (
            <div style={{ marginTop: 8, padding: '14px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border-faint)', borderRadius: 'var(--radius-md)' }}>
              {/* Book comparison */}
              <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                <div style={{ flex: 1, padding: '12px 16px', border: '1px solid rgba(16,220,154,0.2)', borderRadius: 'var(--radius-md)', background: 'rgba(16,220,154,0.05)' }}>
                  <div style={{ fontSize: 10, color: '#10dc9a', fontWeight: 800, marginBottom: 6 }}>BOOK A — Mir + GEX</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: '#10dc9a', fontFamily: 'var(--mono)' }}>{a.win_rate || 0}%</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{a.wins || 0}W / {a.losses || 0}L · {a.would_trade || 0} trades · avg {a.avg_pnl || 0}%</div>
                </div>
                <div style={{ flex: 1, padding: '12px 16px', border: '1px solid rgba(162,77,255,0.2)', borderRadius: 'var(--radius-md)', background: 'rgba(162,77,255,0.05)' }}>
                  <div style={{ fontSize: 10, color: '#bb7cff', fontWeight: 800, marginBottom: 6 }}>BOOK B — Mir Only</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: '#bb7cff', fontFamily: 'var(--mono)' }}>{b.win_rate || 0}%</div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)' }}>{b.wins || 0}W / {b.losses || 0}L · {b.would_trade || 0} trades · avg {b.avg_pnl || 0}%</div>
                </div>
              </div>
              {/* GEX contribution */}
              <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, marginBottom: 6 }}>GEX CONTRIBUTION</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, fontSize: 10 }}>
                  <div style={{ color: 'var(--text-3)', marginBottom: 2 }}>Entry Filter</div>
                  <div style={{ fontWeight: 700 }}>Blocked {ef.signals_blocked || 0} signals</div>
                  <div style={{ color: '#10dc9a' }}>Saved {ef.would_have_lost || 0} losses</div>
                  <div style={{ color: '#ff5656' }}>Missed {ef.would_have_won || 0} wins</div>
                </div>
                <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, fontSize: 10 }}>
                  <div style={{ color: 'var(--text-3)', marginBottom: 2 }}>Targeting</div>
                  <div>GEX R:R: <span style={{ fontWeight: 700, color: '#10dc9a' }}>{gex.targeting?.avg_rr_with_gex || '-'}</span></div>
                  <div>Fixed R:R: <span style={{ fontWeight: 700, color: '#bb7cff' }}>{gex.targeting?.avg_rr_without_gex || '-'}</span></div>
                </div>
              </div>
              {/* By conviction */}
              {abData.by_conviction && (
                <>
                  <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, marginBottom: 6 }}>BY CONVICTION</div>
                  <div style={{ display: 'flex', gap: 8, fontFamily: 'var(--mono)', fontSize: 10 }}>
                    {['HIGH', 'MEDIUM', 'LOW', 'NONE'].map((c) => {
                      const d = abData.by_conviction[c];
                      if (!d || !d.count) return null;
                      return (
                        <div key={c} style={{ padding: '6px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, textAlign: 'center' }}>
                          <div style={{ fontWeight: 800, color: c === 'HIGH' ? '#10dc9a' : c === 'MEDIUM' ? '#f4c430' : '#8a93a8' }}>{c}</div>
                          <div>A: {d.a_wr}% · B: {d.b_wr}%</div>
                          <div style={{ color: 'var(--text-3)' }}>{d.count} decisions</div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
              <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 8 }}>
                {abData.summary?.total_decisions || 0} total decisions · {a.pending || 0} pending
              </div>
            </div>
          );
        })()}
        {showAB && (!abData || abData.total === 0) && (
          <div style={{ marginTop: 8, padding: '14px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border-faint)', borderRadius: 'var(--radius-md)', fontSize: 11, color: 'var(--text-3)' }}>
            No A/B decisions logged yet. Data will appear after the next signal generation cycle.
          </div>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, padding: '10px 20px', alignItems: 'center' }}>
        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-3)', fontWeight: 700 }}>FILTERS</span>
        <select className="ctrl-select" value={gradeFilter} onChange={(e) => setGradeFilter(e.target.value)}>
          {GRADES.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select className="ctrl-select" value={outcomeFilter} onChange={(e) => setOutcomeFilter(e.target.value)}>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <button className="ctrl-btn active" onClick={load} style={{ padding: '4px 12px' }}>↻ Refresh</button>
      </div>

      <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-3)', padding: '0 20px 8px' }}>
        {filtered.length} signals · click to expand
      </div>

      {/* Signal cards */}
      <div style={{ padding: '0 20px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>Loading...</div>}
        {filtered.map((sig) => (
          <SignalCard key={sig.id} sig={sig} expanded={expanded === sig.id} onToggle={() => setExpanded(expanded === sig.id ? null : sig.id)} />
        ))}
        {!loading && filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>
            No signals yet. The engine generates signals during market hours based on GEX structure.
          </div>
        )}
      </div>
    </div>
  );
}

function SignalCard({ sig, expanded, onToggle }) {
  const gradeColor = GRADE_COLOR[sig.grade] || 'var(--text-2)';
  const gradeBg = GRADE_BG[sig.grade] || 'rgba(255,255,255,0.04)';
  const statusStyle = STATUS_STYLE[sig.status] || {};
  const isCall = sig.option_type === 'CALL';
  const scoreBar = Math.min(100, (sig.score / sig.max_score) * 100);

  const time = new Date(sig.ts * 1000).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });

  return (
    <div
      onClick={onToggle}
      style={{
        border: `1px solid ${gradeColor}40`,
        borderRadius: 'var(--radius-md)',
        background: 'var(--bg-panel)',
        cursor: 'pointer',
        overflow: 'hidden',
      }}
    >
      {/* Header row */}
      <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 18, color: sig.direction === '▲' ? '#10dc9a' : '#ff5656' }}>{sig.direction}</span>
        <span style={{ fontSize: 18, fontWeight: 800 }}>{sig.ticker}</span>
        <span style={{ padding: '2px 10px', borderRadius: 6, border: `1px solid ${gradeColor}`, color: gradeColor, fontWeight: 800, fontSize: 'var(--fs-sm)', background: gradeBg }}>{sig.grade}</span>
        <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--text-2)' }}>{sig.signal_type}</span>
        {/* Greeks source badge */}
        {sig.greeks_source && (
          <span style={{
            padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 800, fontFamily: 'var(--mono)',
            background: sig.greeks_source === 'massive' ? 'rgba(16,220,154,0.15)' : 'rgba(255,200,0,0.15)',
            color: sig.greeks_source === 'massive' ? '#10dc9a' : '#ffc800',
          }}>{sig.greeks_source === 'massive' ? 'MASSIVE' : 'TRADIER'}</span>
        )}
        {/* Mir conviction badge */}
        {sig._mir_conviction && (
          <span style={{
            padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 800, fontFamily: 'var(--mono)',
            background: sig._mir_conviction === 'HIGH' ? 'rgba(244,196,48,0.2)' : 'rgba(244,196,48,0.1)',
            color: '#f4c430',
          }}>MIR {sig._mir_conviction}</span>
        )}
        {/* 0DTE experimental badge */}
        {sig._0dte_status === 'EXPERIMENTAL' && (
          <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 800, fontFamily: 'var(--mono)', background: 'rgba(255,140,0,0.2)', color: '#ff8c00' }}>0DTE EXPERIMENTAL</span>
        )}
        {sig._0dte_status === 'TRADEABLE' && sig.dte === 0 && (
          <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 800, fontFamily: 'var(--mono)', background: 'rgba(16,220,154,0.15)', color: '#10dc9a' }}>0DTE LIVE</span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ ...statusStyle, fontSize: 'var(--fs-sm)', fontFamily: 'var(--mono)' }}>{sig.status}</span>
        <span style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>{time}</span>
      </div>

      {/* Quick stats row */}
      <div style={{ padding: '0 16px 10px', display: 'flex', gap: 20, fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)' }}>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>SPOT</span><br />
          <span style={{ fontWeight: 700 }}>${fmtPrice(sig.spot)}</span>
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>SCORE</span><br />
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 40, height: 6, background: 'var(--border-faint)', borderRadius: 3, overflow: 'hidden', display: 'inline-block' }}>
              <span style={{ width: `${scoreBar}%`, height: '100%', background: gradeColor, display: 'block', borderRadius: 3 }} />
            </span>
            <span style={{ color: gradeColor, fontWeight: 700 }}>{sig.score}/{sig.max_score}</span>
          </span>
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>STRIKE</span><br />
          <span style={{ color: isCall ? '#10dc9a' : '#ff5656', fontWeight: 700 }}>${sig.strike}</span>
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>EXP</span><br />
          <span style={{ fontWeight: 700 }}>{sig.expiration || '-'}</span>
          {sig.dte != null && <span style={{ color: 'var(--text-3)', fontSize: 9, marginLeft: 4 }}>({sig.dte}d)</span>}
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>DELTA</span><br />
          <span style={{ color: '#10dc9a', fontWeight: 700 }}>{sig.delta?.toFixed(2) || '-'}</span>
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>IV</span><br />
          <span style={{ color: '#10dc9a', fontWeight: 700 }}>{sig.iv ? (sig.iv * 100).toFixed(1) + '%' : '-'}</span>
        </div>
        <div>
          <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>R:R</span><br />
          <span style={{ color: sig.rr_ratio >= 2 ? '#10dc9a' : sig.rr_ratio >= 1 ? '#f4c430' : '#ff5656', fontWeight: 700 }}>
            {sig.rr_ratio ? `${sig.rr_ratio}x` : '-'}
          </span>
        </div>
        {sig.spread_pct != null && (
          <div>
            <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>SPREAD</span><br />
            <span style={{ color: sig.spread_pct <= 5 ? '#10dc9a' : sig.spread_pct <= 10 ? '#f4c430' : '#ff5656', fontWeight: 700 }}>
              {sig.spread_pct}%
            </span>
          </div>
        )}
        {sig.contract_oi != null && (
          <div>
            <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>OI</span><br />
            <span style={{ fontWeight: 700 }}>{sig.contract_oi?.toLocaleString()}</span>
          </div>
        )}
        {/* Discipline fields */}
        {sig.base_rate_tier && (
          <div>
            <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>TIER</span><br />
            <span style={{ padding: '1px 6px', borderRadius: 4, fontSize: 'var(--fs-xxs)', fontWeight: 800,
              background: sig.base_rate_tier === 'PROVEN' ? 'rgba(16,220,154,0.15)' : sig.base_rate_tier === 'DEVELOPING' ? 'rgba(244,196,48,0.15)' : 'rgba(255,255,255,0.06)',
              color: sig.base_rate_tier === 'PROVEN' ? '#10dc9a' : sig.base_rate_tier === 'DEVELOPING' ? '#f4c430' : 'var(--text-3)' }}>
              {sig.base_rate_tier}
            </span>
          </div>
        )}
        {sig.kelly_size_pct != null && (
          <div>
            <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>SIZE</span><br />
            <span style={{ fontWeight: 700, color: '#f4c430' }}>{sig.kelly_size_pct}%</span>
          </div>
        )}
        {sig.gate_score != null && (
          <div>
            <span style={{ color: 'var(--text-3)', fontSize: 'var(--fs-xxs)' }}>GATE</span><br />
            <span style={{ fontWeight: 700, color: sig.gate_label === 'VALID' ? '#10dc9a' : sig.gate_label === 'WEAK' ? '#f4c430' : '#ff5656' }}>
              {sig.gate_score}/{sig.gate_max}
            </span>
          </div>
        )}
      </div>

      {/* Discipline warnings */}
      {sig.discipline_note && (
        <div style={{ padding: '4px 16px 8px', fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: sig.discipline_grade === 'SKIP' || sig.discipline_grade === 'BLOCKED' ? '#ff5656' : '#f4c430' }}>
          ⚠ {sig.discipline_note}
        </div>
      )}
      {sig.earnings_blocked && (
        <div style={{ padding: '4px 16px 8px', fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: '#ff5656', fontWeight: 800 }}>
          🚫 TOXIC LIST: Earnings proximity — do not trade
        </div>
      )}

      {/* Expanded detail */}
      {expanded && (
        <div style={{ borderTop: '1px solid var(--border-faint)', padding: 16 }}>
          {/* Trade action */}
          <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 800, marginBottom: 4 }}>
            BUY {sig.ticker} ${sig.strike} {sig.option_type} — {sig.expiration} ({sig.dte} DTE)
          </div>
          <div style={{ color: 'var(--text-2)', fontSize: 'var(--fs-sm)', marginBottom: 12 }}>
            {sig.signal_type.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())}
          </div>

          {/* Entry / Target / Stop / R:R */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, background: 'var(--border-faint)', borderRadius: 'var(--radius-md)', overflow: 'hidden', marginBottom: 14 }}>
            <div style={{ background: 'var(--bg-2)', padding: '10px 14px' }}>
              <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>ENTRY</div>
              <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: '#10dc9a', fontFamily: 'var(--mono)' }}>${fmtPrice(sig.spot)}</div>
            </div>
            <div style={{ background: 'var(--bg-2)', padding: '10px 14px' }}>
              <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>TARGET</div>
              <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: '#10dc9a', fontFamily: 'var(--mono)' }}>${fmtPrice(sig.target)}</div>
              <div style={{ fontSize: 'var(--fs-xxs)', color: '#10dc9a' }}>{sig.target_label} ({sig.target && sig.spot ? ((Math.abs(sig.target - sig.spot) / sig.spot) * 100).toFixed(1) : 0}%)</div>
            </div>
            <div style={{ background: 'var(--bg-2)', padding: '10px 14px' }}>
              <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>STOP</div>
              <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: '#ff5656', fontFamily: 'var(--mono)' }}>${fmtPrice(sig.stop)}</div>
              <div style={{ fontSize: 'var(--fs-xxs)', color: '#ff5656' }}>{sig.stop_label} ({sig.stop && sig.spot ? ((Math.abs(sig.stop - sig.spot) / sig.spot) * 100).toFixed(1) : 0}%)</div>
            </div>
            <div style={{ background: 'var(--bg-2)', padding: '10px 14px' }}>
              <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>R:R</div>
              <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: sig.rr_ratio >= 1 ? '#10dc9a' : '#ff5656', fontFamily: 'var(--mono)' }}>1:{sig.rr_ratio}</div>
              <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>Score {sig.score}/{sig.max_score}</div>
            </div>
          </div>

          {/* Reasoning checklist */}
          <div style={{ fontFamily: 'var(--mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-2)', lineHeight: 2 }}>
            {(sig.reasoning || '').split('\n').map((line, i) => (
              <div key={i} style={{ color: line.startsWith('✓') ? '#10dc9a' : 'var(--text-2)' }}>{line}</div>
            ))}
          </div>

          {/* GEX context */}
          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 1, background: 'var(--border-faint)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            {[
              { label: 'KING', val: `$${sig.king}`, color: '#f4c430' },
              { label: 'FLOOR', val: `$${sig.floor_level}`, color: '#10dc9a' },
              { label: 'CEILING', val: `$${sig.ceiling_level}`, color: '#ff5656' },
              { label: 'ZGL', val: `$${sig.zgl}`, color: 'var(--text-1)' },
              { label: 'REGIME', val: sig.regime + ' γ', color: sig.regime === 'POS' ? '#10dc9a' : '#ff5656' },
            ].map((c) => (
              <div key={c.label} style={{ background: 'var(--bg-2)', padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 'var(--fs-xxs)', color: 'var(--text-3)' }}>{c.label}</div>
                <div style={{ fontWeight: 700, color: c.color, fontFamily: 'var(--mono)', fontSize: 'var(--fs-sm)' }}>{c.val}</div>
              </div>
            ))}
          </div>

          {/* 5-Factor Gate */}
          {sig.gate_factors && (
            <div style={{ marginTop: 14, padding: 12, background: 'var(--bg-2)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-faint)' }}>
              <div style={{ fontSize: 'var(--fs-xs)', fontWeight: 700, color: 'var(--text-2)', marginBottom: 8 }}>
                5-FACTOR GATE: <span style={{ color: sig.gate_label === 'VALID' ? '#10dc9a' : sig.gate_label === 'WEAK' ? '#f4c430' : '#ff5656' }}>
                  {sig.gate_score}/{sig.gate_max} {sig.gate_label}
                </span>
                <span style={{ color: 'var(--text-3)', marginLeft: 8 }}>{sig.gate_action}</span>
              </div>
              {sig.gate_factors.map((f, i) => (
                <div key={i} style={{ fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: f.pass ? '#10dc9a' : '#ff5656', lineHeight: 1.8 }}>
                  {f.pass ? '✓' : '✗'} {f.name}: {f.detail}
                </div>
              ))}
            </div>
          )}

          {/* Exit Ladder */}
          {sig.exit_ladder && (
            <div style={{ marginTop: 14, padding: 12, background: 'var(--bg-2)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-faint)' }}>
              <div style={{ fontSize: 'var(--fs-xs)', fontWeight: 700, color: 'var(--text-2)', marginBottom: 6 }}>EXIT LADDER</div>
              {sig.exit_ladder.map((lvl, i) => (
                <div key={i} style={{ fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: 'var(--text-2)', lineHeight: 1.8 }}>
                  +{lvl.gain_pct}% → {lvl.label}
                </div>
              ))}
            </div>
          )}

          {/* Kelly sizing detail */}
          {sig.kelly_reason && (
            <div style={{ marginTop: 10, fontSize: 'var(--fs-xxs)', fontFamily: 'var(--mono)', color: 'var(--text-3)' }}>
              Position: {sig.kelly_reason}
              {sig.kelly_capped_by && <span style={{ color: '#f4c430' }}> (capped: {sig.kelly_capped_by})</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
