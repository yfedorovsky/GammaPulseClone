/**
 * Volume Profile — lightweight-charts ISeriesPrimitive plugin.
 *
 * Draws Webull-style horizontal bars on the right side of the chart.
 * Green = buy volume (close >= open), Red = sell volume, POC = yellow.
 * Automatically syncs with zoom/pan/resize via the plugin lifecycle.
 */

// --- helpers ---

function positionsBox(p1, p2, pixelRatio) {
  const s1 = Math.round(pixelRatio * p1);
  const s2 = Math.round(pixelRatio * p2);
  return { position: Math.min(s1, s2), length: Math.abs(s2 - s1) + 1 };
}

function computeVolumeBins(bars, numBins) {
  if (!bars.length) return [];
  let lo = Infinity, hi = -Infinity;
  for (const b of bars) {
    if (b.low < lo) lo = b.low;
    if (b.high > hi) hi = b.high;
  }
  const step = (hi - lo) / numBins;
  if (step <= 0) return [];

  const bins = Array.from({ length: numBins }, (_, i) => ({
    priceLo: lo + step * i,
    priceHi: lo + step * (i + 1),
    totalVol: 0,
  }));

  for (const b of bars) {
    // Distribute volume across all bins the bar's range touches
    const vol = b.volume || 0;
    if (!vol) continue;
    const bLo = Math.max(0, Math.floor((b.low - lo) / step));
    const bHi = Math.min(numBins - 1, Math.floor((b.high - lo) / step));
    const perBin = vol / (bHi - bLo + 1);

    for (let i = bLo; i <= bHi; i++) {
      bins[i].totalVol += perBin;
    }
  }

  return bins.filter(b => b.totalVol > 0);
}

// --- renderer ---

class VPRenderer {
  constructor(data) {
    this._data = data;
  }

  draw(target) {
    target.useBitmapCoordinateSpace((scope) => {
      const { context: ctx, horizontalPixelRatio: hR, verticalPixelRatio: vR } = scope;
      const d = this._data;
      if (!d || !d.items.length) return;

      const maxVol = d.items.reduce((m, r) => Math.max(m, r.totalVol), 0);
      if (!maxVol) return;

      d.items.forEach((row) => {
        if (row.yLo == null || row.yHi == null) return;
        const frac = row.totalVol / maxVol;
        const barW = d.maxWidth * frac;
        const isPOC = row.isPOC;

        // Vertical extent of this price bin
        const vBox = positionsBox(row.yHi, row.yLo, vR);
        const barH = Math.max(vBox.length - 1, 1);
        const hBox = positionsBox(d.rightEdge - barW, d.rightEdge, hR);

        if (isPOC) {
          // POC: brighter gray + outline
          ctx.fillStyle = `rgba(180,190,210,0.45)`;
          ctx.fillRect(hBox.position, vBox.position, hBox.length, barH);
          ctx.strokeStyle = 'rgba(200,210,230,0.6)';
          ctx.lineWidth = 1;
          ctx.strokeRect(hBox.position, vBox.position, hBox.length, barH);
        } else {
          // Uniform gray, opacity scales with volume intensity
          ctx.fillStyle = `rgba(140,150,170,${0.10 + frac * 0.28})`;
          ctx.fillRect(hBox.position, vBox.position, hBox.length, barH);
        }
      });
    });
  }
}

// --- pane view ---

class VPPaneView {
  constructor(source) {
    this._source = source;
    this._data = null;
  }

  update() {
    const src = this._source;
    const series = src._series;
    const chart = src._chart;
    if (!series || !chart) return;

    const ts = chart.timeScale();
    const chartW = ts.width();
    const maxWidth = chartW * src._widthPct;

    const maxVol = src._bins.reduce((m, b) => Math.max(m, b.totalVol), 0);
    const pocBin = src._bins.find(b => b.totalVol === maxVol);

    const items = src._bins.map((bin) => ({
      yLo: series.priceToCoordinate(bin.priceLo),
      yHi: series.priceToCoordinate(bin.priceHi),
      totalVol: bin.totalVol,
      isPOC: bin === pocBin,
    }));

    this._data = { items, maxWidth, rightEdge: chartW };
  }

  renderer() {
    return new VPRenderer(this._data);
  }

  zOrder() {
    return 'bottom';
  }
}

// --- primitive (model) ---

export class VolumeProfilePrimitive {
  constructor(bars, { numBins = 50, widthPct = 0.18 } = {}) {
    this._chart = null;
    this._series = null;
    this._widthPct = widthPct;
    this._numBins = numBins;
    this._bins = computeVolumeBins(bars, numBins);
    this._paneViews = [new VPPaneView(this)];
  }

  // Called by lightweight-charts when attached to a series
  attached({ chart, series }) {
    this._chart = chart;
    this._series = series;
  }

  detached() {
    this._chart = null;
    this._series = null;
  }

  updateAllViews() {
    this._paneViews.forEach((v) => v.update());
  }

  paneViews() {
    return this._paneViews;
  }

  // Update data without detach/reattach
  setData(bars) {
    this._bins = computeVolumeBins(bars, this._numBins);
    // Force redraw
    if (this._chart) {
      this._chart.timeScale().applyOptions({});
    }
  }
}
