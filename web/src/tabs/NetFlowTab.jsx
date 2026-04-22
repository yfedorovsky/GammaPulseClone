/**
 * NetFlowTab — Price-to-Premium Gap visualization.
 *
 * Three-line chart showing spot Price, Net Call Premium (NCP), and Net
 * Put Premium (NPP) over time. Modeled after Unusual Whales' "Net Flow"
 * chart. Theory: options premium flow leads underlying price; when
 * premium outpaces price (gap), price tends to close the gap. When both
 * stall at the close, support/resistance forms.
 *
 * Data source: /api/net-flow/{ticker} (backend aggregator in
 * server/net_flow.py). Polled every 10s while the tab is mounted.
 *
 * Visual design:
 *   - Yellow line = Price (right axis, $ scale)
 *   - Green line  = NCP  (left axis, $M scale — bullish call positioning)
 *   - Magenta line = NPP (left axis, $M scale — bearish put positioning)
 *   - Histogram subpanel = signed volume (NCP + NPP, positive=green)
 *
 * Build reasoning: see server/net_flow.py docstring for sign convention
 * and theoretical background.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';

const DEFAULT_TICKERS = [
  'SPY', 'SPX', 'SPXW', 'QQQ', 'IWM',
  'AAPL', 'AMZN', 'NVDA', 'MSFT', 'META', 'GOOGL', 'TSLA',
  'ARM', 'NBIS', 'AVGO', 'MU', 'MRVL',
];

const RANGES = [
  { label: '1H', minutes: 60 },
  { label: '4H', minutes: 240 },
  { label: '1D', minutes: 1440 },
];

export default function NetFlowTab() {
  const [ticker, setTicker] = useState('SPY');
  const [minutes, setMinutes] = useState(240);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  // Chart refs
  const priceChartRef = useRef(null);
  const priceChartInstance = useRef(null);
  const volChartRef = useRef(null);
  const volChartInstance = useRef(null);
  const seriesRefs = useRef({});

  // Poll backend on mount + every 10 seconds while active.
  // Dependencies include ticker + minutes so changing them refetches.
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        setLoading(true);
        const resp = await api.netFlow(ticker, minutes);
        if (!alive) return;
        setData(resp);
        setErr(null);
      } catch (e) {
        if (!alive) return;
        setErr(e.message || String(e));
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    const iv = setInterval(load, 10_000);
    return () => { alive = false; clearInterval(iv); };
  }, [ticker, minutes]);

  // Build / teardown charts when data first arrives or ticker changes.
  // Two separate chart instances — one for price+NCP+NPP, one for volume
  // histogram. Synced via time axis.
  useEffect(() => {
    if (!priceChartRef.current || !volChartRef.current || !data?.bars?.length) return;

    // Clear previous instances
    if (priceChartInstance.current) { priceChartInstance.current.remove(); priceChartInstance.current = null; }
    if (volChartInstance.current) { volChartInstance.current.remove(); volChartInstance.current = null; }

    const commonLayout = {
      background: { color: '#0a0f1c' },
      textColor: '#8a93a8',
      fontFamily: 'DM Mono, monospace',
      fontSize: 10,
    };
    const commonGrid = {
      vertLines: { color: 'rgba(255,255,255,0.03)' },
      horzLines: { color: 'rgba(255,255,255,0.03)' },
    };

    // Main chart: price + NCP + NPP
    const priceChart = createChart(priceChartRef.current, {
      layout: commonLayout,
      grid: commonGrid,
      rightPriceScale: { borderColor: '#1a2338', scaleMargins: { top: 0.1, bottom: 0.1 } },
      leftPriceScale: { visible: true, borderColor: '#1a2338', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: '#1a2338', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      width: priceChartRef.current.clientWidth,
      height: 360,
    });
    priceChartInstance.current = priceChart;

    // Price (yellow, right axis in $)
    const priceLine = priceChart.addLineSeries({
      color: '#f4c430', lineWidth: 2, title: `${ticker}`,
      priceScaleId: 'right',
      crosshairMarkerVisible: true, priceLineVisible: false, lastValueVisible: true,
    });

    // NCP (green, left axis in $M)
    const ncpLine = priceChart.addLineSeries({
      color: '#10dc9a', lineWidth: 2, title: 'Net Call Prem',
      priceScaleId: 'left',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });

    // NPP (magenta, left axis in $M)
    const nppLine = priceChart.addLineSeries({
      color: '#ff4fa8', lineWidth: 2, title: 'Net Put Prem',
      priceScaleId: 'left',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });

    // Volume subchart
    const volChart = createChart(volChartRef.current, {
      layout: commonLayout,
      grid: commonGrid,
      rightPriceScale: { borderColor: '#1a2338', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: {
        borderColor: '#1a2338', timeVisible: true, secondsVisible: false,
        // Sync with main chart below via crosshair + time-range wiring later
      },
      crosshair: { mode: 0 },
      width: volChartRef.current.clientWidth,
      height: 120,
    });
    volChartInstance.current = volChart;

    const volHistogram = volChart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: true,
      title: 'Signed Vol',
    });

    seriesRefs.current = { priceLine, ncpLine, nppLine, volHistogram };

    // Sync time axes between the two charts (basic — pan/zoom one, mirror other)
    const unsubPrice = priceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (range) volChart.timeScale().setVisibleRange(range);
    });
    const unsubVol = volChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (range) priceChart.timeScale().setVisibleRange(range);
    });

    // Responsive resize
    const onResize = () => {
      priceChart.applyOptions({ width: priceChartRef.current.clientWidth });
      volChart.applyOptions({ width: volChartRef.current.clientWidth });
    };
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      priceChart.remove();
      volChart.remove();
      priceChartInstance.current = null;
      volChartInstance.current = null;
    };
    // We intentionally re-create on ticker change so the title labels update
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, priceChartRef.current, volChartRef.current]);

  // Push data into chart whenever `data` updates (every 10s poll)
  useEffect(() => {
    if (!data?.bars?.length || !seriesRefs.current.priceLine) return;
    const bars = data.bars;

    const priceData = [];
    const ncpData = [];
    const nppData = [];
    const volData = [];

    let lastPrice = null;
    for (const b of bars) {
      const t = b.t;
      if (!t) continue;
      // Price line — carry-forward last known price if this minute has no spot yet
      if (b.price != null) lastPrice = b.price;
      if (lastPrice != null) priceData.push({ time: t, value: lastPrice });
      // NCP / NPP in millions for readability
      ncpData.push({ time: t, value: (b.ncp || 0) / 1e6 });
      nppData.push({ time: t, value: (b.npp || 0) / 1e6 });
      // Signed volume — positive green, negative magenta
      const sv = (b.signed_vol || 0) / 1e6;
      volData.push({
        time: t,
        value: sv,
        color: sv >= 0 ? 'rgba(16, 220, 154, 0.7)' : 'rgba(255, 79, 168, 0.7)',
      });
    }

    seriesRefs.current.priceLine.setData(priceData);
    seriesRefs.current.ncpLine.setData(ncpData);
    seriesRefs.current.nppLine.setData(nppData);
    seriesRefs.current.volHistogram.setData(volData);
  }, [data]);

  const stats = useMemo(() => {
    if (!data) return null;
    return {
      cumNcp: data.cum_ncp || 0,
      cumNpp: data.cum_npp || 0,
      cumNet: data.cum_net || 0,
      bars: data.bars?.length || 0,
      tracked: data.tracked,
    };
  }, [data]);

  const latest = data?.latest;

  return (
    <div className="netflow-tab">
      {/* Header: controls + stats */}
      <div className="netflow-header">
        <div className="netflow-controls">
          <label className="netflow-label">TICKER</label>
          <select
            className="ctrl-select"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={{ minWidth: 90 }}
          >
            {DEFAULT_TICKERS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <label className="netflow-label" style={{ marginLeft: 16 }}>RANGE</label>
          <div className="ctrl-group">
            {RANGES.map((r) => (
              <button
                key={r.label}
                className={`ctrl-btn ${minutes === r.minutes ? 'active' : ''}`}
                onClick={() => setMinutes(r.minutes)}
              >
                {r.label}
              </button>
            ))}
          </div>

          {loading && <span className="netflow-loading">Loading…</span>}
          {err && <span className="netflow-err">⚠ {err}</span>}
          {stats && !stats.tracked && (
            <span className="netflow-err">
              ⚠ {ticker} not in TRACKED_TICKERS — no aggregation
            </span>
          )}
        </div>

        {/* Stats row */}
        {stats && (
          <div className="netflow-stats">
            <div className="netflow-stat">
              <span className="netflow-stat-label">CUM NCP</span>
              <span
                className="netflow-stat-val"
                style={{ color: stats.cumNcp >= 0 ? '#10dc9a' : '#ff5656' }}
              >
                {stats.cumNcp >= 0 ? '+' : ''}${fmtBig(stats.cumNcp)}
              </span>
            </div>
            <div className="netflow-stat">
              <span className="netflow-stat-label">CUM NPP</span>
              <span
                className="netflow-stat-val"
                style={{ color: stats.cumNpp >= 0 ? '#ff4fa8' : '#10dc9a' }}
              >
                {stats.cumNpp >= 0 ? '+' : ''}${fmtBig(stats.cumNpp)}
              </span>
            </div>
            <div className="netflow-stat">
              <span className="netflow-stat-label">NET (C-P)</span>
              <span
                className="netflow-stat-val"
                style={{ color: stats.cumNet >= 0 ? '#10dc9a' : '#ff5656', fontWeight: 800 }}
              >
                {stats.cumNet >= 0 ? '+' : ''}${fmtBig(stats.cumNet)}
              </span>
            </div>
            {latest?.price && (
              <div className="netflow-stat">
                <span className="netflow-stat-label">SPOT</span>
                <span className="netflow-stat-val" style={{ color: '#f4c430' }}>
                  ${fmtPrice(latest.price)}
                </span>
              </div>
            )}
            <div className="netflow-stat">
              <span className="netflow-stat-label">BARS</span>
              <span className="netflow-stat-val">{stats.bars}</span>
            </div>
          </div>
        )}

        {/* Regime banner — shown when signals/divergence detected */}
        {data?.regime && data.regime !== 'NO_SIGNAL' && (
          <div
            className={`netflow-regime regime-${data.regime_gap_direction || 'neutral'}`}
            title={data.regime_description}
          >
            <span className="netflow-regime-icon">
              {data.regime_gap_direction === 'bullish' ? '▲' :
               data.regime_gap_direction === 'bearish' ? '▼' : '◆'}
            </span>
            <span className="netflow-regime-name">{data.regime.replace(/_/g, ' ')}</span>
            <span className={`netflow-regime-conf conf-${data.regime_confidence || 'medium'}`}>
              {(data.regime_confidence || 'medium').toUpperCase()}
            </span>
            <span className="netflow-regime-desc">{data.regime_description}</span>
          </div>
        )}
      </div>

      {/* Main chart — price + NCP + NPP */}
      <div className="netflow-chart-wrap">
        <div ref={priceChartRef} className="netflow-chart-main" />
      </div>

      {/* Volume subpanel */}
      <div className="netflow-chart-wrap">
        <div className="netflow-chart-label">SIGNED VOLUME ($M/min)</div>
        <div ref={volChartRef} className="netflow-chart-vol" />
      </div>

      {/* Methodology footnote */}
      <div className="netflow-footer">
        <span className="netflow-footer-icon">ⓘ</span>
        <strong>Price-to-Premium Gap Theory</strong>: when premium (NCP/NPP) outpaces price, price tends
        to close the gap. When both premium and price stall together, support/resistance forms.
        <br />
        <span style={{ color: 'var(--text-3)', fontSize: 10 }}>
          NCP = Net Call Premium (call buys − call sells). NPP = Net Put Premium. Both in $ notional.
          Buy/sell classification via NBBO at trade time. Aggregation from same trade stream as sweep detector.
        </span>
      </div>
    </div>
  );
}
