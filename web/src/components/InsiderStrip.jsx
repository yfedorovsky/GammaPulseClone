import React, { useEffect, useState, useRef } from 'react';
import { api } from '../api.js';

/**
 * Pinned strip of INFORMED FLOW alerts (is_insider=1).
 *
 * Renamed from "INSIDER PATTERN" 2026-05-27 PM after cross-LLM validation
 * (Perplexity/Gemini/Grok/ChatGPT). The actual signal is "informed-looking
 * flow ahead of catalysts" — not provably illegal insider trading.
 *
 * Score >= 5/6 on the 6-criteria signature (server/flow_alerts.py
 * `_classify_insider_signature`): V/OI ≥ 10x | opening | ASK | cheap-or-OTM
 * | short-dated ≤ 7 DTE | OTM |delta| ≤ 0.40. Now gated by oi≥100/vol≥500
 * sanity floors + $10K min notional + 30-min per-contract dedup.
 *
 * Pattern matches MU 3/31 whale, INTC 5/8, META 5/27 — the trades that
 * can 100× in hours. Pinned at the top of BigFlow tab so they don't get
 * lost in the daily flow firehose.
 */
const REFRESH_MS = 10_000;
const SHOW_HOURS = 6; // only show alerts from the last 6 hours

export default function InsiderStrip({ onClickTicker }) {
  const [alerts, setAlerts] = useState([]);
  const [collapsed, setCollapsed] = useState(false);
  const inFlightRef = useRef(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const since = Math.floor(Date.now() / 1000) - SHOW_HOURS * 3600;
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 15_000);
        const res = await fetch(`${api.base}/api/alerts/insider?since=${since}&limit=20`, {
          signal: ctrl.signal,
        });
        clearTimeout(tid);
        const json = await res.json();
        if (alive) setAlerts(Array.isArray(json.alerts) ? json.alerts : []);
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

  if (!alerts.length) return null;

  return (
    <div style={{
      marginBottom: 14,
      border: '2px solid #f4c430',
      borderRadius: 6,
      background: 'rgba(244,196,48,0.08)',
      padding: '10px 12px',
      boxShadow: '0 0 14px rgba(244,196,48,0.25)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
        cursor: 'pointer',
      }} onClick={() => setCollapsed((c) => !c)}>
        <div style={{
          fontSize: 13, fontWeight: 800, color: '#f4c430', letterSpacing: 0.8,
        }}>
          ⚡ INFORMED FLOW — {alerts.length} active
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          score ≥ 5/6 · last {SHOW_HOURS}h
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
          {collapsed ? 'click to expand' : 'click to collapse'}
        </div>
      </div>
      {!collapsed && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 8,
        }}>
          {alerts.map((a, i) => {
            const reasons = (a.insider_reasons || '').split(',').filter(Boolean);
            const sentColor = a.sentiment === 'BULLISH' ? '#10dc9a'
              : a.sentiment === 'BEARISH' ? '#ff5656' : 'var(--text-3)';
            const dt = new Date((a.ts || 0) * 1000);
            const timeStr = dt.toLocaleTimeString('en-US', {
              hour: '2-digit', minute: '2-digit', second: '2-digit',
              hour12: false, timeZone: 'America/New_York',
            });
            return (
              <div key={a.id || `${a.ticker}-${a.ts}-${i}`}
                onClick={() => onClickTicker && onClickTicker(a.ticker)}
                style={{
                  border: '1px solid rgba(244,196,48,0.4)',
                  borderRadius: 4,
                  padding: '7px 9px',
                  background: 'var(--bg-1)',
                  cursor: onClickTicker ? 'pointer' : 'default',
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-1)' }}>
                    {a.ticker}
                  </span>
                  <span style={{ color: 'var(--text-3)', fontSize: 10 }}>
                    ${a.strike} {String(a.option_type).toUpperCase()[0]} {a.expiration}
                  </span>
                  <div style={{ flex: 1 }} />
                  <span style={{ color: sentColor, fontWeight: 700, fontSize: 10 }}>
                    {a.sentiment}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, color: 'var(--text-2)', fontSize: 10 }}>
                  <span>V/OI {Number(a.vol_oi || 0).toFixed(1)}x</span>
                  <span>${Number(a.notional || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  <span>spot ${Number(a.spot || 0).toFixed(2)}</span>
                </div>
                <div style={{
                  marginTop: 4, fontSize: 9, color: 'var(--text-3)',
                  display: 'flex', gap: 4, flexWrap: 'wrap',
                }}>
                  {reasons.map((r) => (
                    <span key={r} style={{
                      background: 'rgba(244,196,48,0.15)',
                      border: '1px solid rgba(244,196,48,0.3)',
                      padding: '1px 5px', borderRadius: 2,
                    }}>{r}</span>
                  ))}
                  <span style={{
                    background: 'var(--bg-2)', padding: '1px 5px', borderRadius: 2,
                    color: 'var(--text-3)',
                  }}>{timeStr} ET</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
