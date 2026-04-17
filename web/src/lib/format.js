/** Format a dollar amount like 12.6B / 354.2M / 938.0K */
export function fmtBig(v) {
  if (v === 0 || v == null || Number.isNaN(v)) return '$0';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

/**
 * High-precision dollar format for heatmap cells. Keeps K as the base unit up
 * to $10M (matches Skylit heatseeker style), then switches to M. Shows 1 more
 * decimal than fmtBig for mid-range nodes so adjacent cells are actually
 * distinguishable (e.g. $2,656.7K vs $2,678.2K instead of both being "$2.7M").
 */
export function fmtBigPrecise(v) {
  if (v === 0 || v == null || Number.isNaN(v)) return '$0';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e7) return `${sign}$${(abs / 1e6).toFixed(2)}M`;    // ≥$10M → M
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;    // <$10M → K base
  return `${sign}$${abs.toFixed(0)}`;
}

export function fmtPrice(v) {
  if (v == null) return '-';
  if (v >= 1000) return v.toFixed(2);
  if (v >= 10) return v.toFixed(2);
  return v.toFixed(2);
}

export function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return '-';
  return `${(v * 100).toFixed(2)}%`;
}

export function fmtIV(v) {
  if (v == null || Number.isNaN(v)) return '-';
  return `${v.toFixed(1)}%`;
}

export function fmtStrike(v) {
  if (v == null) return '-';
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
