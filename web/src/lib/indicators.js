/**
 * Technical indicators computed from OHLCV bar data.
 * Used by OverlayTab for EMA ribbons, RSI, ADX, and VWAP anchors.
 */

export function computeEMA(closes, period) {
  if (closes.length < period) return [];
  const k = 2 / (period + 1);
  const ema = [closes.slice(0, period).reduce((a, b) => a + b, 0) / period];
  for (let i = period; i < closes.length; i++) {
    ema.push(closes[i] * k + ema[ema.length - 1] * (1 - k));
  }
  // Pad front with nulls so indices align with closes
  return Array(period - 1).fill(null).concat(ema);
}

export function computeRSI(closes, period = 14) {
  if (closes.length < period + 1) return { value: null, values: [] };
  const changes = [];
  for (let i = 1; i < closes.length; i++) {
    changes.push(closes[i] - closes[i - 1]);
  }

  let avgGain = 0, avgLoss = 0;
  for (let i = 0; i < period; i++) {
    if (changes[i] > 0) avgGain += changes[i];
    else avgLoss += Math.abs(changes[i]);
  }
  avgGain /= period;
  avgLoss /= period;

  const rsiValues = [];
  for (let i = period; i < changes.length; i++) {
    if (i > period) {
      const change = changes[i];
      avgGain = (avgGain * (period - 1) + (change > 0 ? change : 0)) / period;
      avgLoss = (avgLoss * (period - 1) + (change < 0 ? Math.abs(change) : 0)) / period;
    }
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    rsiValues.push(100 - 100 / (1 + rs));
  }

  return {
    value: rsiValues.length ? Math.round(rsiValues[rsiValues.length - 1] * 10) / 10 : null,
    values: rsiValues,
  };
}

export function computeADX(highs, lows, closes, period = 14) {
  if (closes.length < period * 2) return { value: null };

  const trueRanges = [];
  const plusDM = [];
  const minusDM = [];

  for (let i = 1; i < closes.length; i++) {
    const h = highs[i], l = lows[i], pc = closes[i - 1];
    trueRanges.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));

    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }

  // Smoothed averages
  const smooth = (arr) => {
    const result = [arr.slice(0, period).reduce((a, b) => a + b, 0)];
    for (let i = period; i < arr.length; i++) {
      result.push(result[result.length - 1] - result[result.length - 1] / period + arr[i]);
    }
    return result;
  };

  const atr = smooth(trueRanges);
  const spDM = smooth(plusDM);
  const smDM = smooth(minusDM);

  const dx = [];
  for (let i = 0; i < atr.length; i++) {
    if (atr[i] === 0) { dx.push(0); continue; }
    const pdi = (spDM[i] / atr[i]) * 100;
    const mdi = (smDM[i] / atr[i]) * 100;
    const sum = pdi + mdi;
    dx.push(sum === 0 ? 0 : Math.abs(pdi - mdi) / sum * 100);
  }

  if (dx.length < period) return { value: null };
  let adx = dx.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < dx.length; i++) {
    adx = (adx * (period - 1) + dx[i]) / period;
  }

  return {
    value: Math.round(adx * 10) / 10,
    trend: adx > 25 ? 'Active' : adx > 20 ? 'Developing' : 'Weak',
  };
}

export function computeVWAP(bars) {
  // Session VWAP from bar data (intraday only)
  if (!bars.length) return [];
  let cumVol = 0, cumTP = 0;
  return bars.map((b) => {
    const tp = (b.high + b.low + b.close) / 3;
    const vol = b.volume || 1;
    cumVol += vol;
    cumTP += tp * vol;
    return { time: b.time, value: cumVol ? cumTP / cumVol : tp };
  });
}

/**
 * Compute ATR and extension state relative to MAs.
 * "A lot of bad options entries are right stock, wrong location." — ChatGPT
 */
export function computeATRExtension(closes, highs, lows, period = 14) {
  if (closes.length < period + 1) return { atr: null, ext20: null, ext50: null, state: 'UNKNOWN' };

  // ATR
  const trs = [];
  for (let i = closes.length - period; i < closes.length; i++) {
    const h = highs[i] || closes[i];
    const l = lows[i] || closes[i];
    const pc = closes[i - 1];
    trs.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  const atr = trs.reduce((a, b) => a + b, 0) / trs.length;

  const spot = closes[closes.length - 1];

  // Extension from 20MA
  let ext20 = null;
  if (closes.length >= 20) {
    const ma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
    ext20 = atr > 0 ? (spot - ma20) / atr : 0;
  }

  // Extension from 50MA
  let ext50 = null;
  if (closes.length >= 50) {
    const ma50 = closes.slice(-50).reduce((a, b) => a + b, 0) / 50;
    ext50 = atr > 0 ? (spot - ma50) / atr : 0;
  }

  // State
  let state = 'NORMAL';
  const maxExt = Math.max(Math.abs(ext20 || 0), Math.abs(ext50 || 0));
  if (maxExt > 3) state = 'OVEREXTENDED';
  else if (maxExt > 2) state = 'EXTENDED';
  else if (maxExt < -2) state = 'OVERSOLD';
  else if (ext20 !== null && Math.abs(ext20) < 0.5) state = 'ACTIONABLE';  // Near MA = pullback zone

  return {
    atr: Math.round(atr * 100) / 100,
    ext_from_20ma: ext20 !== null ? Math.round(ext20 * 10) / 10 : null,
    ext_from_50ma: ext50 !== null ? Math.round(ext50 * 10) / 10 : null,
    state,
  };
}

/**
 * Classify trend state from EMA cloud.
 * "Use it as trend classification, not signal generation." — ChatGPT
 */
export function classifyTrendState(closes, spot) {
  if (closes.length < 50) return { state: 'UNKNOWN', details: 'Insufficient data' };

  const ema8 = computeEMA(closes, 8);
  const ema21 = computeEMA(closes, 21);
  const ema50 = computeEMA(closes, 50);

  const e8 = ema8[ema8.length - 1];
  const e21 = ema21[ema21.length - 1];
  const e50 = ema50[ema50.length - 1];

  if (!e8 || !e21 || !e50) return { state: 'UNKNOWN', details: 'EMA computation failed' };

  // Slope of EMA21 (comparing current to 5 bars ago)
  const e21_prev = ema21[ema21.length - 6] || e21;
  const slope = ((e21 - e21_prev) / e21_prev) * 100;

  // Cloud state
  let state, details;
  if (spot > e8 && e8 > e21 && e21 > e50 && slope > 0) {
    state = 'BULLISH_TREND';
    details = 'Price > EMA8 > EMA21 > EMA50, slope positive — trend intact';
  } else if (spot > e21 && e21 > e50 && slope > 0) {
    state = 'BULLISH_PULLBACK';
    details = 'Above EMA21/50 but below EMA8 — pullback within trend (buyable dip)';
  } else if (spot > e50 && slope >= 0) {
    state = 'NEUTRAL_ABOVE';
    details = 'Above EMA50 but EMAs not aligned — range/chop, be selective';
  } else if (spot < e50 && slope < 0) {
    state = 'BEARISH_TREND';
    details = 'Below all EMAs, slope negative — bearish, avoid longs';
  } else if (spot < e21 && spot > e50) {
    state = 'NEUTRAL_WEAK';
    details = 'Below EMA21, above EMA50 — weakening, wait for resolution';
  } else {
    state = 'NEUTRAL';
    details = 'Mixed signals — no clear trend';
  }

  return {
    state,
    details,
    ema8: Math.round(e8 * 100) / 100,
    ema21: Math.round(e21 * 100) / 100,
    ema50: Math.round(e50 * 100) / 100,
    slope_21: Math.round(slope * 100) / 100,
    price_vs_cloud: spot > e21 ? 'ABOVE' : 'BELOW',
  };
}

/**
 * Compute Anchored VWAP from a specific bar index.
 * "Strongest next add" — ChatGPT
 */
export function computeAnchoredVWAP(bars, anchorIndex) {
  if (anchorIndex < 0 || anchorIndex >= bars.length) return [];
  let cumVol = 0, cumTP = 0;
  const result = [];
  for (let i = anchorIndex; i < bars.length; i++) {
    const b = bars[i];
    const tp = (b.high + b.low + b.close) / 3;
    const vol = b.volume || 1;
    cumVol += vol;
    cumTP += tp * vol;
    result.push({ time: b.time, value: cumVol ? cumTP / cumVol : tp });
  }
  return result;
}

/**
 * Auto-detect useful AVWAP anchors from price action.
 * Finds: major swing lows, major swing highs, gap days, high-volume days.
 */
export function findAVWAPAnchors(bars) {
  if (bars.length < 20) return [];
  const anchors = [];

  // Find the lowest close in the dataset (major low)
  let minIdx = 0, minClose = Infinity;
  let maxIdx = 0, maxClose = -Infinity;
  for (let i = 0; i < bars.length; i++) {
    if (bars[i].close < minClose) { minClose = bars[i].close; minIdx = i; }
    if (bars[i].close > maxClose) { maxClose = bars[i].close; maxIdx = i; }
  }
  anchors.push({ index: minIdx, label: 'Major Low', color: 'rgba(16,220,154,0.6)' });
  anchors.push({ index: maxIdx, label: 'Major High', color: 'rgba(255,86,86,0.6)' });

  // Find highest volume day (institutional activity)
  let maxVolIdx = 0, maxVol = 0;
  for (let i = 0; i < bars.length; i++) {
    if ((bars[i].volume || 0) > maxVol) { maxVol = bars[i].volume; maxVolIdx = i; }
  }
  if (maxVolIdx !== minIdx && maxVolIdx !== maxIdx) {
    anchors.push({ index: maxVolIdx, label: 'High Volume', color: 'rgba(162,77,255,0.6)' });
  }

  return anchors;
}

/**
 * Compute all indicators from raw bars.
 * Returns { emas, rsi, adx, vwap, atrExtension, trendState, avwapAnchors }
 */
export function computeAllIndicators(rawBars) {
  const closes = rawBars.map(b => b.close);
  const highs = rawBars.map(b => b.high || b.close);
  const lows = rawBars.map(b => b.low || b.close);

  const ema8 = computeEMA(closes, 8);
  const ema21 = computeEMA(closes, 21);
  const ema50 = computeEMA(closes, 50);
  const ema200 = computeEMA(closes, 200);

  const rsi = computeRSI(closes, 14);
  const adx = computeADX(highs, lows, closes, 14);
  const vwap = computeVWAP(rawBars);

  // Format EMAs as line series data
  const formatEMA = (values, bars) =>
    values.map((v, i) => v != null ? { time: bars[i].time, value: v } : null).filter(Boolean);

  return {
    ema8: formatEMA(ema8, rawBars),
    ema21: formatEMA(ema21, rawBars),
    ema50: formatEMA(ema50, rawBars),
    ema200: formatEMA(ema200, rawBars),
    ema8_current: ema8[ema8.length - 1],
    ema21_current: ema21[ema21.length - 1],
    ema50_current: ema50[ema50.length - 1],
    ema200_current: ema200[ema200.length - 1],
    rsi,
    adx,
    vwap,
    // New context layers (ChatGPT final review recommendations)
    atrExtension: computeATRExtension(closes, highs, lows),
    trendState: classifyTrendState(closes, closes[closes.length - 1]),
    avwapAnchors: findAVWAPAnchors(rawBars),
  };
}
