import React, { useEffect, useState, useRef } from 'react';
import { api } from '../api.js';
import { fmtBig } from '../lib/format.js';

export default function AlertPanel({ open, onClose }) {
  const [alerts, setAlerts] = useState([]);
  const [newCount, setNewCount] = useState(0);
  const lastTs = useRef(0);

  // Poll for new alerts every 15 seconds
  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const data = await api.alerts(lastTs.current);
        if (!alive) return;
        if (data.alerts?.length) {
          setAlerts((prev) => {
            const existing = new Set(prev.map((a) => a.id));
            const fresh = data.alerts.filter((a) => !existing.has(a.id));
            if (fresh.length) setNewCount((c) => c + fresh.length);
            return [...fresh, ...prev].slice(0, 100);
          });
          const maxTs = Math.max(...data.alerts.map((a) => a.ts || 0));
          if (maxTs > lastTs.current) lastTs.current = maxTs;
        }
      } catch {}
    }
    poll();
    const iv = setInterval(poll, 15_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  // Clear new count when panel opens
  useEffect(() => {
    if (open) setNewCount(0);
  }, [open]);

  if (!open) return null;

  return (
    <div className="alert-panel">
      <div className="alert-header">
        <span style={{ fontWeight: 800, fontSize: 14 }}>🔔 Flow Alerts</span>
        <span className="mini text-dim">{alerts.length} alerts</span>
        <div style={{ flex: 1 }} />
        <button className="header-btn" onClick={onClose}>✕</button>
      </div>
      <div className="alert-list">
        {alerts.length === 0 && (
          <div style={{ padding: 30, textAlign: 'center', color: 'var(--text-3)' }}>
            No alerts yet. The flow scanner checks tier-1 tickers every 60s
            for unusual volume (V/OI ≥ 3×, notional ≥ $500K).
          </div>
        )}
        {alerts.map((a) => {
          const time = new Date((a.ts || 0) * 1000).toLocaleTimeString();
          const isBull = a.sentiment === 'BULLISH';
          const isBear = a.sentiment === 'BEARISH';
          return (
            <div key={a.id} className="alert-row">
              <div className="alert-row-top">
                <span className="alert-time">{time}</span>
                <span className="alert-ticker">{a.ticker}</span>
                <span
                  className="alert-strike"
                  style={{ color: a.option_type === 'call' ? '#10dc9a' : '#ff5656' }}
                >
                  ${a.strike} {a.option_type?.toUpperCase()}
                </span>
                <span className="text-dim">{a.expiration}</span>
                <div style={{ flex: 1 }} />
                <span
                  style={{
                    color: isBull ? '#10dc9a' : isBear ? '#ff5656' : '#ffcc4d',
                    fontWeight: 800,
                    fontSize: 11,
                  }}
                >
                  {a.sentiment}
                </span>
              </div>
              <div className="alert-row-bottom">
                <span>Vol: {a.volume?.toLocaleString()}</span>
                <span>OI: {a.oi?.toLocaleString()}</span>
                <span style={{ color: '#ff5656', fontWeight: 700 }}>{a.vol_oi}x</span>
                <span>
                  {a.side} @ ${a.last_price?.toFixed(2)}
                </span>
                <span>Notional: {fmtBig(a.notional)}</span>
                <span>IV: {a.iv}%</span>
                <span>Δ: {a.delta}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function useAlertCount() {
  const [count, setCount] = useState(0);
  const lastTs = useRef(0);

  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const data = await api.alerts(lastTs.current);
        if (!alive) return;
        if (data.alerts?.length) {
          setCount((c) => c + data.alerts.length);
          const maxTs = Math.max(...data.alerts.map((a) => a.ts || 0));
          if (maxTs > lastTs.current) lastTs.current = maxTs;
        }
      } catch {}
    }
    poll();
    const iv = setInterval(poll, 15_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  return [count, () => setCount(0)];
}
