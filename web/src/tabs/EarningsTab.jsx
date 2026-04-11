import React, { useEffect, useState, useMemo } from 'react';
import { api } from '../api.js';

const FILTERS = ['ALL', 'EARNINGS', 'ECONOMIC'];

export default function EarningsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [weekOffset, setWeekOffset] = useState(0);
  const [filter, setFilter] = useState('ALL');

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const d = await api.earnings(weekOffset);
        setData(d);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [weekOffset]);

  const weekLabel = data
    ? `Week of ${fmtDate(data.week_start)}–${fmtDate(data.week_end)}`
    : 'Calendar';

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      {/* Header with navigation + filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <button className="header-btn" onClick={() => setWeekOffset(weekOffset - 1)}>◀ Prev</button>
        <strong style={{ fontSize: 16 }}>{weekLabel}</strong>
        <button className="header-btn" onClick={() => setWeekOffset(weekOffset + 1)}>Next ▶</button>
        <div style={{ flex: 1 }} />
        <div className="ctrl-group">
          {FILTERS.map((f) => (
            <button key={f} className={`ctrl-btn ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
              {f === 'EARNINGS' ? '📊 EARNINGS' : f === 'ECONOMIC' ? '🏛 ECONOMIC' : '📅 ALL'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>Loading...</div>
      ) : (
        <>
          {/* Economic events bar */}
          {(filter === 'ALL' || filter === 'ECONOMIC') && data?.economic_events?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-2)', fontWeight: 700, marginBottom: 6 }}>Economic Events This Week</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {data.economic_events.map((ev, i) => (
                  <div key={i} className="econ-event" data-impact={ev.impact}>
                    <span className="econ-icon">{ev.icon || '📅'}</span>
                    <span className="econ-name">{ev.name}</span>
                    <span className="econ-date">{ev.date} {ev.time || ''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Earnings grid */}
          {(filter === 'ALL' || filter === 'EARNINGS') && (
            <div className="earnings-grid">
              {(data?.days || []).map((day) => (
                <div key={day.date} className={`earn-card ${day.is_today ? 'today' : ''}`}>
                  <div className="earn-day">
                    {day.weekday}
                    {day.is_today && <span className="earn-today-badge">TODAY</span>}
                  </div>
                  <div className="earn-date">{fmtDate(day.date)}</div>
                  {day.tickers && day.tickers.length > 0 ? (
                    day.tickers.map((t, i) => {
                      const ticker = typeof t === 'string' ? t : t.ticker;
                      const timing = typeof t === 'object' ? t.timing : null;
                      const result = typeof t === 'object' ? t.result : null;
                      return (
                        <div key={i} className="earn-ticker" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 800, color: 'var(--accent)' }}>{ticker}</span>
                          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            {timing && <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{timing === 'bmo' ? 'Before Open' : timing === 'amc' ? 'After Close' : timing}</span>}
                            {result === 'beat' && <span style={{ color: '#10dc9a', fontWeight: 800, fontSize: 11 }}>✅ Beat</span>}
                            {result === 'miss' && <span style={{ color: '#ff5656', fontWeight: 800, fontSize: 11 }}>❌ Miss</span>}
                          </span>
                        </div>
                      );
                    })
                  ) : (
                    <div className="earn-empty">No earnings</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 12, textAlign: 'center' }}>
        Source: Finnhub · Filtered to GammaPulse ticker universe · Economic events: FOMC, CPI, PPI, Jobs, OPEX
      </div>
    </div>
  );
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
