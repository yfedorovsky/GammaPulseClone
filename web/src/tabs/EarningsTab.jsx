import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function EarningsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const d = await api.earnings();
        setData(d);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>Loading...</div>;

  const weekLabel = data
    ? `Week of ${formatDate(data.week_start)}–${formatDate(data.week_end)}`
    : 'Earnings Calendar';

  return (
    <div style={{ padding: 16 }}>
      <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 12 }}>{weekLabel}</div>
      <div className="earnings-grid">
        {(data?.days || []).map((day) => (
          <div key={day.date} className={`earn-card ${day.is_today ? 'today' : ''}`}>
            <div className="earn-day">
              {day.weekday}
              {day.is_today && <span className="earn-today-badge">TODAY</span>}
            </div>
            <div className="earn-date">{formatDate(day.date)}</div>
            {day.tickers && day.tickers.length > 0 ? (
              day.tickers.map((t, i) => (
                <div key={i} className="earn-ticker">{typeof t === 'string' ? t : t.ticker || t}</div>
              ))
            ) : (
              <div className="earn-empty">No earnings</div>
            )}
          </div>
        ))}
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 12, textAlign: 'center' }}>
        {data?.source || 'Source: Connect a Nasdaq or Yahoo earnings feed for real data. · Filtered to GammaPulse ticker universe · Refreshed daily'}
      </div>
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
