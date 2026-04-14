/**
 * Client-side helpers for coloring GEX rows and classifying signals.
 */

export function rowBackground(strike, spot) {
  const { ratio, net_gex, is_air, node_type } = strike;
  const r = Math.max(0, Math.min(1, ratio || 0));
  if (is_air) return 'transparent';

  // Bold structural level backgrounds (matches OG GammaPulse Pro)
  if (node_type === 'king') {
    return net_gex >= 0
      ? 'rgba(244, 196, 48, 0.25)'   // Gold king
      : 'rgba(162, 77, 255, 0.25)';   // Purple -GEX king
  }
  if (node_type === 'gatekeeper') {
    return 'rgba(162, 77, 255, 0.15)'; // Purple gatekeepers
  }
  if (node_type === 'floor') {
    return 'rgba(16, 220, 154, 0.20)'; // Bright green floor
  }
  if (node_type === 'ceiling') {
    return 'rgba(255, 86, 86, 0.18)';  // Red ceiling
  }

  // Standard rows: intensity-based gradient (vivid, matches OG app)
  if (net_gex >= 0) {
    const alpha = 0.12 + r * 0.65;
    return `rgba(16, 180, 100, ${alpha.toFixed(3)})`;
  }
  // Negative GEX: teal-purple tint (not pure red like the OG)
  const alpha = 0.10 + r * 0.55;
  return `rgba(120, 50, 180, ${alpha.toFixed(3)})`;
}

export function rowClass(strike, spot) {
  const cls = [];
  if (strike.net_gex >= 0) cls.push('pos');
  else cls.push('neg');
  if (strike.node_type === 'king') {
    cls.push(strike.net_gex >= 0 ? 'king-pos' : 'king-neg');
  } else if (strike.node_type === 'gatekeeper') {
    cls.push('gatekeeper');
  } else if (strike.node_type === 'floor') {
    cls.push('floor');
  } else if (strike.node_type === 'ceiling') {
    cls.push('ceiling');
  }
  if (strike.is_air) cls.push('air');
  if (strike.confluence) cls.push('confluence');
  return cls.join(' ');
}

/** Position the spot marker: returns the strike index to insert above */
export function spotInsertIndex(strikes, spot) {
  if (!strikes || !strikes.length || spot == null) return -1;
  // Find the largest strike <= spot, insert above it in a descending list
  // (strikes are displayed highest-first).
  // Iterating desc: we want to render spot row where strike[i-1] > spot >= strike[i].
  let lastGte = -1;
  for (let i = 0; i < strikes.length; i++) {
    if (strikes[i].strike < spot) {
      return i; // insert at index i (i.e. between i-1 and i)
    }
    lastGte = i;
  }
  return strikes.length;
}

/**
 * Generate the dynamic prose strip that sits under a panel's stats row.
 *
 * Not a static lookup — reads the full live state (signal, regime, spot,
 * king, king polarity, floor, ceiling, distance to king) and composes a
 * context-aware sentence. Two tickers with the same signal will get
 * differently-worded strips depending on their exact positioning.
 *
 * Parts:
 *   [polarity] King $X [positional phrase]. [consequence clause]. [action clause].
 */
export function signalExplanation({ signal, spot, king, kingIsPositive, regime }) {
  if (!king || !spot) return '';

  const polarity = kingIsPositive ? '+GEX' : '-GEX';
  const distPct = Math.abs(spot - king) / spot;
  const above = king > spot;
  const below = king < spot;
  const atKing = distPct < 0.003;

  // Positional phrase — where is the king relative to spot?
  let where;
  if (atKing) where = 'at spot';
  else if (above) where = `above (+${(distPct * 100).toFixed(2)}%)`;
  else where = `below (-${(distPct * 100).toFixed(2)}%)`;

  // Consequence clause — what the algo says happens next
  const consequences = {
    'MAGNET UP': 'Price attracted upward',
    SUPPORT: 'Dips absorbed',
    PINNING: 'Volatility compressed',
    'AIR POCKET': 'Breakdown risk elevated',
    RESISTANCE: 'Rallies rejected',
    DANGER: 'Volatility expansion risk',
  };

  // Action clause — what to do about it
  const actions = {
    'MAGNET UP': 'lean long toward king',
    SUPPORT: 'buy dips near floor',
    PINNING: 'sell premium, range-bound',
    'AIR POCKET': 'cut longs or short rallies',
    RESISTANCE: 'fade rips into king',
    DANGER: 'reduce size, expect whipsaws',
  };

  const consequence = consequences[signal] || 'Structural level';
  const action = actions[signal] || 'monitor';

  // Regime flavor — adds nuance for NEG gamma days
  const regimeHint =
    regime === 'NEG'
      ? ' NEG γ: trending/volatile regime.'
      : regime === 'POS'
      ? ''
      : '';

  // Extra context for PINNING: how close to king
  if (signal === 'PINNING') {
    return `Pinned at ${polarity} King $${king}. ${consequence}. ${action}.${regimeHint}`;
  }

  // Atypical cases: king at spot but not a pinning signal → DANGER phrasing
  if (atKing && signal === 'DANGER') {
    return `Price at ${polarity} King $${king}. ${consequence}. ${action}.${regimeHint}`;
  }

  // Standard: "+GEX King $X above (+1.23%). Price attracted upward. Lean long toward king."
  return `${polarity} King $${king} ${where}. ${consequence}. ${action}.${regimeHint}`;
}

/** CSS tint class for the prose strip matching the signal */
export function signalStripClass(signal) {
  switch (signal) {
    case 'MAGNET UP':
    case 'SUPPORT':
      return 'strip-bull';
    case 'PINNING':
      return 'strip-pin';
    case 'AIR POCKET':
    case 'RESISTANCE':
    case 'DANGER':
      return 'strip-bear';
    default:
      return 'strip-neutral';
  }
}

export function computeConfluenceBanner(confluence) {
  if (!confluence) return { label: 'LOADING', cls: 'mixed', alignment: '0/3' };
  const reads = [];
  for (const ticker of ['SPY', 'QQQ', 'IWM']) {
    const t = confluence[ticker];
    if (!t) continue;
    const macroKey = Object.keys(t.exp_data || {}).find((k) => k.startsWith('MACRO')) || Object.keys(t.exp_data || {})[0];
    if (!macroKey) continue;
    const ed = t.exp_data[macroKey];
    const king = ed?.king || 0;
    const spot = t.spot || 0;
    if (!king || !spot) continue;
    // king above spot with +GEX = bullish; below spot with +GEX = bullish support
    const macro = ed.strikes?.find((s) => s.strike === king);
    const kingPositive = macro ? macro.net_gex >= 0 : true;
    if (kingPositive) reads.push('BULL');
    else reads.push('BEAR');
  }
  const bulls = reads.filter((r) => r === 'BULL').length;
  const bears = reads.filter((r) => r === 'BEAR').length;
  if (bulls === 3) return { label: 'BULLISH CONFLUENCE', cls: 'bullish', alignment: '3/3' };
  if (bears === 3) return { label: 'BEARISH CONFLUENCE', cls: 'bearish', alignment: '3/3' };
  if (bulls >= 2) return { label: 'BULLISH CONFLUENCE', cls: 'bullish', alignment: `${bulls}/3` };
  if (bears >= 2) return { label: 'BEARISH CONFLUENCE', cls: 'bearish', alignment: `${bears}/3` };
  return { label: 'MIXED / CHOPPY', cls: 'mixed', alignment: `${bulls}/3` };
}
