import React, { useEffect, useState, useRef } from 'react';
import { api } from '../api.js';

/**
 * Pinned strip of INFORMED CLUSTER fires — N+ strikes same ticker/exp/direction
 * within 30-min rolling window.
 *
 * Renders above InsiderStrip in the BigFlow tab. When 2+ strikes on the same
 * underlying / expiration / direction have fired INFORMED FLOW in the last
 * 30 minutes, the cluster aggregates them into a single high-signal card.
 *
 * This is the unanimous 4/4 LLM-recommended top improvement (Perplexity,
 * Gemini, Grok, ChatGPT). Pattern matches Panuwat (3 strikes 70-84% of
 * daily volume) + META 5/27 ladder (615C/617.5C/620C 0DTE pre-paid-subs).
 */
const REFRESH_MS = 10_000;

export default function ClusterStrip({ onClickTicker }) {
  const [clusters, setClusters] = useState([]);
  const [collapsed, setCollapsed] = useState(false);
  const inFlightRef = useRef(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 15_000);
        const res = await fetch(`${api.base}/api/alerts/cluster?limit=20`, {
          signal: ctrl.signal,
        });
        clearTimeout(tid);
        const json = await res.json();
        if (alive) setClusters(Array.isArray(json.clusters) ? json.clusters : []);
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

  if (!clusters.length) return null;

  return (
    <div style={{
      marginBottom: 14,
      border: '2px solid #a24dff',
      borderRadius: 6,
      background: 'rgba(162,77,255,0.08)',
      padding: '10px 12px',
      boxShadow: '0 0 14px rgba(162,77,255,0.25)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
        cursor: 'pointer',
      }} onClick={() => setCollapsed((c) => !c)}>
        <div style={{
          fontSize: 13, fontWeight: 800, color: '#a24dff', letterSpacing: 0.8,
        }}>
          ⚡⚡ INFORMED CLUSTER — {clusters.length} active
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
          ≥2 strikes · 30-min window · sorted by notional
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
          {collapsed ? 'click to expand' : 'click to collapse'}
        </div>
      </div>
      {!collapsed && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 8,
        }}>
          {clusters.map((c, i) => {
            const dirColor = c.direction === 'BULL' ? '#10dc9a' : '#ff5656';
            const t1 = new Date((c.first_ts || 0) * 1000).toLocaleTimeString('en-US', {
              hour: '2-digit', minute: '2-digit', hour12: false,
              timeZone: 'America/New_York',
            });
            const t2 = new Date((c.last_ts || 0) * 1000).toLocaleTimeString('en-US', {
              hour: '2-digit', minute: '2-digit', hour12: false,
              timeZone: 'America/New_York',
            });
            const strikesShown = c.strikes.slice(0, 6).map((s) =>
              typeof s === 'number' ? `$${s}` : `$${s}`).join(' / ');
            const moreStrikes = c.strikes.length > 6 ? ` +${c.strikes.length - 6}` : '';
            return (
              <div key={`${c.ticker}-${c.expiration}-${c.direction}-${i}`}
                onClick={() => onClickTicker && onClickTicker(c.ticker)}
                style={{
                  border: '1px solid rgba(162,77,255,0.4)',
                  borderRadius: 4,
                  padding: '8px 10px',
                  background: 'var(--bg-1)',
                  cursor: onClickTicker ? 'pointer' : 'default',
                  fontFamily: 'var(--mono)',
                  fontSize: 11,
                }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-1)' }}>
                    {c.ticker}
                  </span>
                  <span style={{ color: 'var(--text-3)', fontSize: 10 }}>
                    {c.expiration}
                  </span>
                  <div style={{ flex: 1 }} />
                  <span style={{ color: dirColor, fontWeight: 800, fontSize: 11 }}>
                    {c.direction} · {c.n_strikes}-strike
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, color: 'var(--text-2)', fontSize: 10, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, color: '#f4c430' }}>
                    ${Number(c.total_notional || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                  <span>max {c.max_score}/6</span>
                  <span>avg V/OI {Number(c.avg_vol_oi || 0).toFixed(1)}x</span>
                  <span>{t1}-{t2} ET</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
                  {strikesShown}{moreStrikes}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
