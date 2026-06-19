import React, { useEffect, useState } from 'react';
import { api } from '../api.js';

/**
 * RS-DECOUPLE strip — today's intraday sector leaders (names pulling away from
 * their industry group). The GLW 6/18 case: +6.9% while Photonics/Fiber peers
 * were −4..−12%. Rare by construction (2-4 names/day) so it is prominent, not
 * another flow-firehose row. CONTEXT / attention flag, not a buy signal.
 *
 * Self-fetching, polls every 60s. Self-hides when there are no decouples.
 */
export default function RsDecoupleStrip() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await api.rsDecouples();
        if (alive) setData(d);
      } catch (e) {
        /* fail quiet */
      }
    };
    load();
    const iv = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const rows = data?.decouples || [];
  if (!rows.length) return null;

  return (
    <div style={{
      padding: '7px 12px', borderBottom: '1px solid var(--border-faint)',
      background: 'linear-gradient(90deg, rgba(16,220,154,0.06), transparent)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 5,
      }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.5, color: '#10dc9a' }}>
          🚀 RS DECOUPLE
        </span>
        <span style={{ fontSize: 9, color: 'var(--text-3)' }}>
          intraday sector leaders · {rows.length} today · context, not a buy signal
        </span>
        {data?.asof && (
          <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 'auto' }}>
            {data.asof}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {rows.map((e) => (
          <div key={e.ticker} title={
            e.flow?.top_strikes
              ? `Confirming flow: ${e.flow.n_high_conv} bull-ASK HIGH-conv · whales accumulating ${e.flow.top_strikes}`
              : `${e.n_peers} peers in ${e.sector}`
          } style={{
            display: 'flex', flexDirection: 'column', gap: 1,
            padding: '4px 10px', borderRadius: 'var(--radius-sm)',
            border: '1px solid rgba(16,220,154,0.35)',
            background: 'var(--bg-input, #14181a)',
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
              <span style={{ fontFamily: 'var(--mono)', fontWeight: 800, fontSize: 13, color: 'var(--text-1)' }}>
                {e.ticker}
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#10dc9a' }}>
                +{e.name_ret?.toFixed(1)}%
              </span>
              <span style={{ fontSize: 10, fontWeight: 700, color: '#f4c430' }}>
                +{e.spread?.toFixed(1)} vs sector
              </span>
            </div>
            <div style={{ fontSize: 8.5, color: 'var(--text-3)' }}>
              {e.sector} {e.sector_ret >= 0 ? '+' : ''}{e.sector_ret?.toFixed(1)}%
              {e.flow?.top_strikes ? ` · flow: ${e.flow.top_strikes}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
