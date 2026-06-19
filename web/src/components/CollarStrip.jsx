import React from 'react';
import { useStore } from '../store.js';
import { fmtStrike } from '../lib/format.js';

/**
 * JHEQX (JPMorgan Hedged Equity Fund) quarterly SPX collar — structural CONTEXT
 * strip. Renders the three collar legs (cap / support / floor) with distance from
 * spot. NOT a trade signal: the pin/support effect was pre-registered and tested
 * (docs/research/JPM_COLLAR_BACKTEST_FINDINGS.md → verdict display_only — the pin
 * is a distance confound, not a collar magnet), so this is awareness only.
 *
 * Self-hiding: renders nothing for non-SPX or when the collar can't be detected.
 * Data comes from the `collar` block on the SPX chains response (server
 * main._collar_overlay / /api/collar).
 */
const ROLE_META = {
  cap: { label: 'CALL WALL / CAP', color: '#d22d3c' },
  support: { label: 'SUPPORT', color: '#f4c430' },
  floor: { label: 'FLOOR', color: '#1ca571' },
};

function Leg({ role, leg, spot }) {
  if (!leg) return null;
  const meta = ROLE_META[role] || { label: role.toUpperCase(), color: 'var(--text-2)' };
  const dist = leg.dist_pct != null
    ? leg.dist_pct
    : (spot ? (leg.strike / spot - 1) * 100 : null);
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 1,
      padding: '3px 10px', borderLeft: `2px solid ${meta.color}`,
      background: 'var(--bg-input, #15151b)', borderRadius: 'var(--radius-sm)',
    }}>
      <span style={{ fontSize: 8, fontWeight: 800, letterSpacing: 0.4, color: meta.color }}>
        {meta.label}
      </span>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>
        {fmtStrike(leg.strike)}
        {dist != null && (
          <span style={{ color: 'var(--text-3)', fontWeight: 500, marginLeft: 5, fontSize: 10 }}>
            {dist >= 0 ? '+' : ''}{dist.toFixed(1)}%
          </span>
        )}
      </span>
    </div>
  );
}

export default function CollarStrip({ ticker = 'SPX' }) {
  const { chains } = useStore();
  const collar = chains?.[ticker]?.collar;
  if (!collar || !collar.legs || collar.confidence === 'none') return null;
  const { legs, exp, spot, confidence } = collar;
  if (!legs.short_call && !legs.long_put && !legs.short_put) return null;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      padding: '5px 12px', borderBottom: '1px solid var(--border-faint)',
      background: 'var(--bg-card)', fontSize: 11,
    }}>
      <span style={{
        fontSize: 9, fontWeight: 800, letterSpacing: 0.5, color: 'var(--text-2)',
        textTransform: 'uppercase',
      }}>
        JHEQX Collar
      </span>
      <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{exp}</span>
      <Leg role="cap" leg={legs.short_call} spot={spot} />
      <Leg role="support" leg={legs.long_put} spot={spot} />
      <Leg role="floor" leg={legs.short_put} spot={spot} />
      <span style={{
        marginLeft: 'auto', fontSize: 8.5, color: 'var(--text-3)', fontStyle: 'italic',
        maxWidth: 230, textAlign: 'right', lineHeight: 1.25,
      }}>
        structural context · not a signal
        <br />
        (pin tested display-only · conf {confidence})
      </span>
    </div>
  );
}
