import React, { useState, useRef } from 'react';

const NODE_COLORS = {
  king: { pos: '#f4c430', neg: '#a24dff' },
  gatekeeper: '#e88a2e',
  floor: '#10dc9a',
  ceiling: '#ff5656',
  normal: { pos: '#1ca571', neg: '#d22d3c' },
};

const NODE_INFO = {
  king: {
    pos: { label: '+GEX KING', desc: 'Highest positive GEX. Price magnetically attracted here. Acts as support/magnet.' },
    neg: { label: '-GEX KING', desc: 'Highest negative GEX. Dealers amplify moves here. Acts as resistance/rejection.' },
  },
  gatekeeper: {
    pos: { label: 'GATEKEEPER', desc: 'Top 6 by intensity. Strong support/resistance. Breaking through is a meaningful structural move.' },
    neg: { label: 'GATEKEEPER', desc: 'Top 6 by intensity. Strong support/resistance. Breaking through is a meaningful structural move.' },
  },
  floor: {
    pos: { label: 'FLOOR', desc: 'Strongest +GEX below spot. Dealers buy here — price support.' },
    neg: { label: 'FLOOR', desc: 'Support level below spot.' },
  },
  ceiling: {
    pos: { label: 'CEILING', desc: 'Strongest +GEX above spot. Dealers sell here — price resistance.' },
    neg: { label: 'CEILING', desc: 'Resistance level above spot.' },
  },
  normal: {
    pos: { label: '+GEX (absorbs)', desc: 'Dealers absorb volatility here. Support zone.' },
    neg: { label: '-GEX (amplifies)', desc: 'Dealers amplify moves here. Breakdown zone.' },
  },
};

function getInfo(strike) {
  const type = strike.node_type || 'normal';
  const polarity = strike.net_gex >= 0 ? 'pos' : 'neg';
  if (strike.is_air) {
    return {
      label: 'AIR POCKET',
      desc: 'Very low GEX. Price accelerates through here.',
      color: 'rgba(255,255,255,0.15)',
    };
  }
  const group = NODE_INFO[type] || NODE_INFO.normal;
  const info = group[polarity] || group.pos;

  let color;
  const colorDef = NODE_COLORS[type] || NODE_COLORS.normal;
  if (typeof colorDef === 'string') color = colorDef;
  else color = colorDef[polarity] || colorDef.pos;

  return { ...info, color };
}

export function useTooltip() {
  const [tip, setTip] = useState(null);
  const timeout = useRef(null);

  const show = (strike, e) => {
    clearTimeout(timeout.current);
    const rect = e.currentTarget.getBoundingClientRect();
    setTip({
      strike,
      x: rect.left + rect.width / 2,
      y: rect.top,
    });
  };

  const hide = () => {
    timeout.current = setTimeout(() => setTip(null), 100);
  };

  return { tip, show, hide };
}

export default function TooltipPopup({ tip, fmtBig }) {
  if (!tip) return null;
  const { strike, x, y } = tip;
  const info = getInfo(strike);

  const style = {
    position: 'fixed',
    left: Math.min(x, window.innerWidth - 280),
    top: Math.max(4, y - 110),
    zIndex: 9999,
    pointerEvents: 'none',
  };

  return (
    <div style={style}>
      <div className="gex-tooltip">
        <div className="tt-title">
          <span className="tt-icon" style={{ background: info.color }} />
          {info.label}
          {strike.confluence && <span className="tt-confl-badge"> ⚡ CONFLUENCE</span>}
        </div>
        <div className="tt-desc">
          {info.desc}
          {strike.confluence && ' GEX + VEX both elevated — highest conviction.'}
        </div>
        <div className="tt-vals">
          GEX: <span className={strike.net_gex >= 0 ? 'num-pos' : 'num-neg'}>{fmtBig(strike.net_gex)}</span>
          {'  '}VEX: <span className={strike.net_vex >= 0 ? 'num-pos' : 'num-neg'}>{fmtBig(strike.net_vex)}</span>
        </div>
      </div>
    </div>
  );
}
