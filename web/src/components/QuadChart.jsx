import React, { useMemo, useState } from 'react';
import { useStore } from '../store.js';
import { fmtBig, fmtPrice, fmtStrike } from '../lib/format.js';

/**
 * QUAD CHART — GEX / DEX / VEX / CEX by strike (Quant-Data-style structural read).
 *
 * We already compute all four dealer-exposure profiles per strike:
 *   GEX (net_gex)   gamma  — convexity: PINS (long γ) vs ACCELERATES (short γ)
 *   DEX (net_delta) delta  — directional INVENTORY / lean
 *   VEX (net_vex)   vanna  — exposure to vol×spot (IV-shift sensitivity)
 *   CEX (net_cex)   charm  — delta decay into expiry (OPEX pin engine)
 *
 * This is a CONTEXT / awareness tool — read the structure, see where each
 * exposure concentrates relative to spot. It is NOT a break/bounce predictor:
 * we tested DEX-at-levels (docs/research/DEX_BACKTEST_FINDINGS.md → not useful;
 * AUC ~0.52, adds nothing over gamma). Use it to understand positioning, not to
 * forecast direction.
 */
const METRICS = [
  { key: 'net_gex', label: 'GEX', sub: 'gamma · pin/accel' },
  { key: 'net_delta', label: 'DEX', sub: 'delta · lean' },
  { key: 'net_vex', label: 'VEX', sub: 'vanna · vol×spot' },
  { key: 'net_cex', label: 'CEX', sub: 'charm · decay' },
];

const POS = 'rgba(28,165,113,0.85)';
const NEG = 'rgba(210,45,60,0.85)';

function isRealExp(e) {
  return typeof e === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(e);
}

export default function QuadChart({ ticker }) {
  const { chains, spotPrices } = useStore();
  const data = chains[ticker];
  const spot = spotPrices[ticker] ?? data?.spot ?? null;
  const exps = (data?.exps || []).filter(isRealExp);
  const [exp, setExp] = useState(null);
  const activeExp = exp || exps[0] || (data?.exps || [])[0];

  const { rows, maxAbs } = useMemo(() => {
    const ed = data?.exp_data?.[activeExp];
    const strikes = ed?.strikes || [];
    const lo = spot ? spot * 0.96 : 0;
    const hi = spot ? spot * 1.04 : Infinity;
    const r = strikes
      .filter((s) => !spot || (s.strike >= lo && s.strike <= hi))
      .sort((a, b) => b.strike - a.strike);
    const mx = {};
    for (const m of METRICS) {
      mx[m.key] = Math.max(1, ...r.map((s) => Math.abs(s[m.key] || 0)));
    }
    return { rows: r, maxAbs: mx };
  }, [data, activeExp, spot]);

  if (!data || !rows.length) {
    return <div style={{ padding: 20, color: 'var(--text-3)', fontSize: 12 }}>
      {data ? `No strike data for ${ticker} ${activeExp || ''}.` : `Loading ${ticker}…`}
    </div>;
  }

  const spotIdx = spot == null ? -1 : rows.findIndex((s) => s.strike < spot);

  // center-zero bar: positive grows right from center, negative left.
  const Bar = ({ v, max }) => {
    const r = Math.max(-1, Math.min(1, (v || 0) / (max || 1)));
    const w = Math.abs(r) * 50;
    const pos = r >= 0;
    return (
      <div style={{ position: 'relative', height: 14, background: 'var(--bg-input,#111418)', borderRadius: 2 }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'var(--border-faint)' }} />
        <div style={{
          position: 'absolute', top: 1, bottom: 1, height: 12,
          left: pos ? '50%' : `${50 - w}%`, width: `${w}%`,
          background: pos ? POS : NEG, borderRadius: 1,
        }} />
        <span style={{
          position: 'absolute', right: 3, top: 0, fontSize: 8, lineHeight: '14px',
          color: 'var(--text-2)', fontFamily: 'var(--mono)',
        }}>{Math.abs(v || 0) >= 1 ? fmtBig(v) : ''}</span>
      </div>
    );
  };

  const gridTpl = '64px repeat(4, 1fr)';
  return (
    <div style={{ padding: '4px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 12px' }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--text-1)' }}>{ticker} · QUAD</span>
        <span style={{ fontSize: 9, color: 'var(--text-3)' }}>spot ${fmtPrice(spot)} · GEX/DEX/VEX/CEX by strike · context, not a predictor</span>
        <select value={activeExp} onChange={(e) => setExp(e.target.value)} style={{
          marginLeft: 'auto', background: 'var(--bg-input,#1a1a20)', color: 'var(--text-1)',
          border: '1px solid var(--border-faint)', borderRadius: 4, fontSize: 10,
          fontFamily: 'var(--mono)', padding: '2px 6px',
        }}>
          {(data?.exps || []).map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
      </div>
      {/* header */}
      <div style={{ display: 'grid', gridTemplateColumns: gridTpl, gap: 4, padding: '2px 12px' }}>
        <div style={{ fontSize: 8, color: 'var(--text-3)', fontWeight: 700 }}>STRIKE</div>
        {METRICS.map((m) => (
          <div key={m.key} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text-1)' }}>{m.label}</div>
            <div style={{ fontSize: 7, color: 'var(--text-3)' }}>{m.sub}</div>
          </div>
        ))}
      </div>
      {/* rows */}
      <div style={{ maxHeight: 'calc(100% - 60px)', overflow: 'auto' }}>
        {rows.map((s, i) => (
          <React.Fragment key={s.strike}>
            {i === spotIdx && (
              <div style={{ display: 'grid', gridTemplateColumns: gridTpl, gap: 4, padding: '0 12px' }}>
                <div style={{ fontSize: 9, color: '#f4c430', fontWeight: 800, fontFamily: 'var(--mono)' }}>
                  ${fmtPrice(spot)} ◀
                </div>
                {METRICS.map((m) => <div key={m.key} style={{ borderTop: '1px dashed #f4c43055' }} />)}
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: gridTpl, gap: 4, padding: '1px 12px', alignItems: 'center' }}>
              <div style={{ fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--text-2)' }}>{fmtStrike(s.strike)}</div>
              {METRICS.map((m) => <Bar key={m.key} v={s[m.key]} max={maxAbs[m.key]} />)}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
