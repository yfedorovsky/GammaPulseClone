import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { createChart, LineStyle } from 'lightweight-charts';
import { useStore } from '../store.js';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';
import { computeAllIndicators, computeAnchoredVWAP } from '../lib/indicators.js';

const MACRO_KEY = 'MACRO (ALL 200D)';

const TIMEFRAMES = [
  { label: '1 Day (1min)', interval: '1min', days: 1 },
  { label: '5 Days (5min)', interval: '5min', days: 5 },
  { label: '1 Month', interval: 'daily', days: 30 },
  { label: '3 Months', interval: 'daily', days: 90 },
];

export default function OverlayTab() {
  const { watchlists, activeWL, chains, setChains, strikes, spotPrices } = useStore();
  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];
  const [current, setCurrent] = useState(wl.tickers[0] || 'SPY');
  const [tfIdx, setTfIdx] = useState(1); // default: 5 Days (5min)
  const [showLevels, setShowLevels] = useState(true);
  const [showZGL, setShowZGL] = useState(true);
  const [showGates, setShowGates] = useState(false);
  const [showOrbs, setShowOrbs] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showSessions, setShowSessions] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showIdeas, setShowIdeas] = useState(false);
  const [showVision, setShowVision] = useState(false);
  const [showMarkers, setShowMarkers] = useState(true);
  const [showEMAs, setShowEMAs] = useState(true);
  const [zoomLock, setZoomLock] = useState(false);
  const [indicators, setIndicators] = useState(null);
  const emaSeriesRef = useRef([]);

  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleRef = useRef(null);
  const volumeRef = useRef(null);
  const linesRef = useRef([]);

  const tf = TIMEFRAMES[tfIdx];

  // Load chain data
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await api.chains([current], strikes);
        if (!alive) return;
        const prev = useStore.getState().chains;
        setChains({ ...prev, ...data });
      } catch {}
    }
    load();
    const iv = setInterval(load, 120_000);
    return () => { alive = false; clearInterval(iv); };
  }, [current, strikes, setChains]);

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0a0f1c' },
        textColor: '#8a93a8',
        fontFamily: 'DM Mono, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.03)' },
      },
      rightPriceScale: { borderColor: '#1a2338', scaleMargins: { top: 0.05, bottom: 0.15 } },
      timeScale: { borderColor: '#1a2338', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const candle = chart.addCandlestickSeries({
      upColor: '#10dc9a',
      downColor: '#ff5656',
      borderVisible: false,
      wickUpColor: '#10dc9a',
      wickDownColor: '#ff5656',
    });
    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    chartRef.current = chart;
    candleRef.current = candle;
    volumeRef.current = volume;

    const resize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.remove();
    };
  }, []);

  // Load bars when ticker, timeframe, or sessions filter changes
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await api.bars(current, tf.interval, tf.days);
        if (!alive || !candleRef.current) return;
        let rawBars = data.bars || [];

        // Filter to regular trading hours (9:30-16:00 ET) when Sessions is on
        // Only applies to intraday bars (epoch timestamps)
        if (showSessions && tf.interval !== 'daily') {
          rawBars = rawBars.filter((b) => {
            if (typeof b.time !== 'number') return true; // daily bars pass through
            const d = new Date(b.time * 1000);
            // Convert to ET: UTC-4 (EDT) or UTC-5 (EST)
            // Approximate: use getUTCHours offset by 4 for EDT
            const etHour = (d.getUTCHours() - 4 + 24) % 24;
            const etMin = d.getUTCMinutes();
            const minuteOfDay = etHour * 60 + etMin;
            // 9:30 = 570, 16:00 = 960
            return minuteOfDay >= 570 && minuteOfDay <= 960;
          });
        }

        const bars = rawBars.map((b) => ({
          time: b.time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        const volBars = rawBars.map((b) => ({
          time: b.time,
          value: b.volume || 0,
          color: b.close >= b.open ? 'rgba(16,220,154,0.15)' : 'rgba(255,86,86,0.15)',
        }));
        candleRef.current.setData(bars);
        if (volumeRef.current) {
          volumeRef.current.setData(showVolume ? volBars : []);
        }
        if (chartRef.current && bars.length && !zoomLock) {
          chartRef.current.timeScale().fitContent();
        }

        // Compute technical indicators
        const ind = computeAllIndicators(rawBars);
        setIndicators(ind);

        // Draw EMA ribbons on chart
        const chart = chartRef.current;
        // Remove old EMA series
        for (const s of emaSeriesRef.current) {
          try { chart?.removeSeries(s); } catch {}
        }
        emaSeriesRef.current = [];

        if (showEMAs && chart) {
          const emaConfigs = [
            { data: ind.ema8, color: 'rgba(16,220,154,0.7)', width: 1 },   // Green
            { data: ind.ema21, color: 'rgba(162,77,255,0.7)', width: 1 },   // Purple
            { data: ind.ema50, color: 'rgba(255,255,255,0.5)', width: 1 },   // White
            { data: ind.ema200, color: 'rgba(255,165,0,0.6)', width: 1 },    // Orange
            // VWAP removed from line series — was causing cyan filled blocks
          ];
          for (const cfg of emaConfigs) {
            if (cfg.data.length > 0) {
              const series = chart.addLineSeries({
                color: cfg.color, lineWidth: cfg.width,
                crosshairMarkerVisible: false, priceLineVisible: false,
                lastValueVisible: false,
              });
              series.setData(cfg.data);
              emaSeriesRef.current.push(series);
            }
          }
        }

        // Draw Anchored VWAPs from auto-detected anchors
        // Only on daily timeframe (intraday has too many overlapping lines)
        if (showEMAs && chart && ind.avwapAnchors && tf.interval === 'daily') {
          for (const anchor of ind.avwapAnchors) {
            const avwapData = computeAnchoredVWAP(rawBars, anchor.index);
            if (avwapData.length > 1) {
              const avwapSeries = chart.addLineSeries({
                color: anchor.color, lineWidth: 1, lineStyle: 2,
                crosshairMarkerVisible: false, priceLineVisible: false,
                lastValueVisible: false,
              });
              avwapSeries.setData(avwapData);
              emaSeriesRef.current.push(avwapSeries);
            }
          }
        }

        // Load SOE signal markers for this ticker
        if (showMarkers) {
          try {
            const sigs = await api.signals(50, '', '');
            const tickerSigs = (sigs.signals || sigs || []).filter(
              (s) => s.ticker === current && s.ts
            );
            const markers = tickerSigs.map((s) => {
              const isBull = s.direction === '\u25b2';
              const isWin = s.status === 'WIN';
              const isLoss = s.status === 'LOSS';
              return {
                time: s.ts,
                position: isBull ? 'belowBar' : 'aboveBar',
                color: isWin ? '#10dc9a' : isLoss ? '#ff5656' : isBull ? '#10dc9a' : '#ff5656',
                shape: isBull ? 'arrowUp' : 'arrowDown',
                text: `${isBull ? 'BUY' : 'SELL'} ${s.option_type || ''} $${s.strike || ''}${isWin ? ' WIN' : isLoss ? ' LOSS' : ''}`,
              };
            }).sort((a, b) => a.time - b.time);
            if (markers.length) {
              candleRef.current.setMarkers(markers);
            }
          } catch {}
        }
      } catch (e) {
        console.warn('bars load failed', e);
      }
    }
    load();
    return () => { alive = false; };
  }, [current, tfIdx, tf.interval, tf.days, showSessions, showMarkers, showEMAs, zoomLock]);

  // Toggle volume visibility
  useEffect(() => {
    if (!volumeRef.current) return;
    // Re-fetch bars to toggle volume (lightweight-charts doesn't have a simple hide)
    // Actually we can set data to empty
    if (!showVolume) {
      volumeRef.current.setData([]);
    }
  }, [showVolume]);

  // Draw GEX levels on the chart
  const drawLevels = useCallback(() => {
    const candle = candleRef.current;
    if (!candle) return;
    // Always clear previous lines first
    const chart = chartRef.current;
    for (const line of linesRef.current) {
      try { candle.removePriceLine(line); } catch {
        // If it's a series (forward projection), remove from chart
        try { chart?.removeSeries(line); } catch {}
      }
    }
    linesRef.current = [];

    const data = chains[current];
    if (!data) return;
    const ed = data.exp_data?.[MACRO_KEY] || {};
    const king = ed.king;
    const floorVal = ed.floor;
    const ceilingVal = ed.ceiling;
    const zgl = ed.zgl;
    const gatekeepers = ed.gatekeepers || [];
    const strikesList = ed.strikes || [];
    const spot = spotPrices[current] ?? data?.spot;

    if (showVision) {
      // VISION MODE: aura bands, pulsing king, labeled levels
      const maxGex = strikesList.reduce((m, s) => Math.max(m, Math.abs(s.net_gex || 0)), 1);
      const top = [...strikesList].sort((a, b) => Math.abs(b.net_gex) - Math.abs(a.net_gex)).slice(0, 25);

      for (const s of top) {
        const isKing = s.strike === king;
        const isFloor = s.strike === floorVal;
        const isCeil = s.strike === ceilingVal;
        const intensity = Math.abs(s.net_gex) / maxGex;
        const isPos = s.net_gex >= 0;
        const lw = isKing ? 4 : Math.max(1, Math.round(intensity * 3));
        const alpha = isKing ? 0.85 : 0.25 + intensity * 0.45;

        let color, title;
        if (isKing) {
          color = isPos ? `rgba(244,196,48,${alpha})` : `rgba(162,77,255,${alpha})`;
          const pct = Math.round(intensity * 100);
          title = `KING $${s.strike} ${pct}%`;
        } else if (isFloor) {
          color = `rgba(16,220,154,${alpha})`;
          title = `FLR $${s.strike}`;
        } else if (isCeil) {
          color = `rgba(255,86,86,${alpha})`;
          title = `CEIL $${s.strike}`;
        } else {
          color = isPos ? `rgba(244,196,48,${alpha * 0.6})` : `rgba(162,77,255,${alpha * 0.6})`;
          title = '';
        }

        // VEX arrow
        const vexArrow = s.net_vex > 0 ? ' ↑' : s.net_vex < 0 ? ' ↓' : '';

        linesRef.current.push(
          candle.createPriceLine({
            price: s.strike,
            color,
            lineWidth: lw,
            lineStyle: isKing ? LineStyle.Solid : LineStyle.Solid,
            axisLabelVisible: isKing || isFloor || isCeil,
            title: title + vexArrow,
          }),
        );
      }

      // ZGL in vision mode (thinner, labeled)
      if (zgl) {
        linesRef.current.push(
          candle.createPriceLine({
            price: zgl,
            color: 'rgba(255,62,62,0.4)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'ZGL',
          }),
        );
      }

      // Confidence cone + forward projection using IV expected move
      if (spot && data.iv) {
        const ivAnnual = data.iv;
        const projDays = tf.days <= 1 ? 1 : tf.days <= 5 ? 3 : tf.days <= 30 ? 10 : 20;
        const em = spot * ivAnnual * Math.sqrt(projDays / 252);
        const upper = spot + em;
        const lower = spot - em;

        // Static cone bounds (current ±1σ)
        linesRef.current.push(
          candle.createPriceLine({
            price: upper, color: 'rgba(244,196,48,0.25)', lineWidth: 1,
            lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `+1σ $${upper.toFixed(0)}`,
          }),
        );
        linesRef.current.push(
          candle.createPriceLine({
            price: lower, color: 'rgba(244,196,48,0.25)', lineWidth: 1,
            lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `-1σ $${lower.toFixed(0)}`,
          }),
        );

        // Forward projection disabled — was causing visual artifacts
        // (large colored blocks instead of lines on some timeframes).
        // The confidence cone static ±1σ lines are still shown above.
      }
    } else {
      // STANDARD MODE: discrete lines
      if (showLevels && king) {
        const kingStrike = strikesList.find((s) => s.strike === king);
        const totalGex = strikesList.reduce((sum, s) => sum + Math.abs(s.net_gex || 0), 0) || 1;
        const kingPct = Math.round((Math.abs(kingStrike?.net_gex || 0) / totalGex) * 100);
        linesRef.current.push(
          candle.createPriceLine({
            price: king,
            color: (kingStrike?.net_gex || 0) >= 0 ? '#f4c430' : '#a24dff',
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: true,
            title: `+GEX KING ${kingPct}%`,
          }),
        );
      }
      if (showLevels && floorVal) {
        linesRef.current.push(
          candle.createPriceLine({ price: floorVal, color: '#10dc9a', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'FLOOR' }),
        );
      }
      if (showLevels && ceilingVal && ceilingVal !== king) {
        linesRef.current.push(
          candle.createPriceLine({ price: ceilingVal, color: '#ff5656', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'CEILING' }),
        );
      }
      if (showZGL && zgl) {
        linesRef.current.push(
          candle.createPriceLine({ price: zgl, color: '#ff3e3e', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'ZGL' }),
        );
      }
      if (showGates) {
        for (const gk of gatekeepers) {
          if (gk === king || gk === floorVal || gk === ceilingVal) continue;
          linesRef.current.push(
            candle.createPriceLine({ price: gk, color: 'rgba(162,77,255,0.5)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' }),
          );
        }
      }
      if (showOrbs) {
        const top = [...strikesList].sort((a, b) => Math.abs(b.net_gex) - Math.abs(a.net_gex)).slice(0, 30);
        for (const s of top) {
          if (s.strike === king) continue;
          const color = s.net_gex >= 0 ? 'rgba(16,220,154,0.35)' : 'rgba(255,86,86,0.35)';
          const lw = Math.max(1, Math.round((s.ratio || 0) * 4));
          linesRef.current.push(
            candle.createPriceLine({ price: s.strike, color, lineWidth: lw, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: '' }),
          );
        }
      }
    }

    // Spot marker (both modes)
    if (spot) {
      linesRef.current.push(
        candle.createPriceLine({ price: spot, color: 'rgba(255,255,255,0.5)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: '◀ SPOT' }),
      );
    }
  }, [chains, current, showLevels, showZGL, showGates, showOrbs, showVision, spotPrices, tf]);

  useEffect(() => {
    drawLevels();
  }, [drawLevels]);

  const ed = chains[current]?.exp_data?.[MACRO_KEY] || {};
  const spot = spotPrices[current] ?? chains[current]?.spot;
  const signal = chains[current]?.signal;
  const regime = chains[current]?.regime;
  const king = ed.king;
  const floor = ed.floor;
  const ceiling = ed.ceiling;

  const rr = useMemo(() => {
    if (!spot || !king) return null;
    const reward = Math.abs(king - spot);
    const risk = Math.abs((king > spot ? floor : ceiling || floor) - spot);
    if (!risk) return null;
    return reward / risk;
  }, [spot, king, floor, ceiling]);

  // Mini sidebar strikes
  const miniStrikes = useMemo(() => {
    const list = (ed.strikes || []).slice().sort((a, b) => b.strike - a.strike);
    const maxI = list.reduce((m, s) => Math.max(m, Math.abs(s.net_gex || 0)), 1);
    return list.slice(0, 80).map((s) => ({
      ...s,
      pct: Math.round((Math.abs(s.net_gex) / maxI) * 100),
    }));
  }, [ed]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Top info bar */}
      <div className="overlay-header">
        <span className="overlay-ticker">{current}</span>
        <span className="overlay-price">${fmtPrice(spot)}</span>
        {/* Daily price change */}
        {chains[current]?._daily_change != null && (
          <span style={{ color: chains[current]._daily_change >= 0 ? '#10dc9a' : '#ff5656', fontWeight: 700, fontSize: 'var(--fs-sm)' }}>
            {chains[current]._daily_change >= 0 ? '▲' : '▼'} ${Math.abs(chains[current]._daily_change || 0).toFixed(2)} ({((chains[current]._daily_change || 0) / (spot || 1) * 100).toFixed(2)}%)
          </span>
        )}
        {/* Regime alert badge — WATCHING FOR TOP/BOTTOM */}
        {signal && (
          <span style={{
            padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 800, letterSpacing: 0.5,
            background: (signal === 'RESISTANCE' || signal === 'AIR POCKET')
              ? 'rgba(255,86,86,0.2)' : signal === 'PINNING'
              ? 'rgba(244,196,48,0.2)' : 'rgba(16,220,154,0.2)',
            color: (signal === 'RESISTANCE' || signal === 'AIR POCKET')
              ? '#ff5656' : signal === 'PINNING'
              ? '#f4c430' : '#10dc9a',
          }}>
            {signal === 'RESISTANCE' || signal === 'AIR POCKET' ? '⏸ WATCHING FOR TOP'
              : signal === 'PINNING' ? '⏸ PINNED AT KING'
              : signal === 'SUPPORT' ? '⏸ WATCHING FOR BOTTOM'
              : '▲ MAGNET UP'}
          </span>
        )}
        {signal && <span className="signal-pill" data-signal={signal}>{signal}</span>}
        {regime && <span className="regime-pill">{regime} γ</span>}
        <span className="sep">·</span>
        <span style={{ color: '#f4c430' }}>King ${king}</span>
        {showVision && (
          <span style={{ padding: '2px 6px', borderRadius: 4, background: 'rgba(162,77,255,0.15)', color: '#bb7cff', fontSize: 10, fontWeight: 800, letterSpacing: '0.5px' }}>
            VISION {chains[current]?.net_vanna > 0 ? 'VANNA ↑' : chains[current]?.net_vanna < 0 ? 'VANNA ↓' : ''}
          </span>
        )}
      </div>

      {/* Toolbar */}
      <div className="overlay-toolbar-bar">
        <span className="overlay-ticker-sm">{current}</span>
        <select
          className="ctrl-select"
          value={tfIdx}
          onChange={(e) => setTfIdx(+e.target.value)}
        >
          {TIMEFRAMES.map((t, i) => (
            <option key={i} value={i}>{t.label}</option>
          ))}
        </select>
        <label className="ov-check"><input type="checkbox" checked={showVision} onChange={(e) => setShowVision(e.target.checked)} /> <span className="check-label" style={{ color: '#a24dff', fontWeight: 800 }}>VISION</span></label>
        <span style={{ width: 1, height: 16, background: 'var(--border-faint)', margin: '0 4px' }} />
        <label className="ov-check" style={{ opacity: showVision ? 0.3 : 1 }}><input type="checkbox" checked={showLevels} disabled={showVision} onChange={(e) => setShowLevels(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>GEX Levels</span></label>
        <label className="ov-check" style={{ opacity: showVision ? 0.3 : 1 }}><input type="checkbox" checked={showZGL} disabled={showVision} onChange={(e) => setShowZGL(e.target.checked)} /> <span className="check-label">ZGL</span></label>
        <label className="ov-check" style={{ opacity: showVision ? 0.3 : 1 }}><input type="checkbox" checked={showGates} disabled={showVision} onChange={(e) => setShowGates(e.target.checked)} /> <span className="check-label">Gates</span></label>
        <label className="ov-check" style={{ opacity: showVision ? 0.3 : 1 }}><input type="checkbox" checked={showOrbs} disabled={showVision} onChange={(e) => setShowOrbs(e.target.checked)} /> <span className="check-label">Orbs</span></label>
        <label className="ov-check"><input type="checkbox" checked={showSidebar} onChange={(e) => setShowSidebar(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Sidebar</span></label>
        <label className="ov-check"><input type="checkbox" checked={showSessions} onChange={(e) => setShowSessions(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Sessions</span></label>
        <label className="ov-check"><input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Volume</span></label>
        <label className="ov-check"><input type="checkbox" checked={showEMAs} onChange={(e) => setShowEMAs(e.target.checked)} /> <span className="check-label" style={{ color: '#a24dff' }}>EMAs</span></label>
        <label className="ov-check"><input type="checkbox" checked={showMarkers} onChange={(e) => setShowMarkers(e.target.checked)} /> <span className="check-label" style={{ color: '#f4c430' }}>Signals</span></label>
        <label className="ov-check"><input type="checkbox" checked={zoomLock} onChange={(e) => setZoomLock(e.target.checked)} /> <span className="check-label" style={{ color: zoomLock ? '#ff8c00' : undefined }}>🔒 Zoom</span></label>
        <span className="mini text-dim" style={{ marginLeft: 'auto' }}>Auto-refresh 2min</span>
      </div>

      {/* Main content */}
      <div className="overlay-wrap" style={{ flex: 1, minHeight: 0 }}>
        {/* Left sidebar: watchlist */}
        <div className="overlay-side">
          <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 6, fontWeight: 700 }}>
            Lists <span style={{ cursor: 'pointer', marginLeft: 4 }}>⊕</span>
          </div>
          {wl.tickers.map((t) => (
            <div
              key={t}
              className={`wl-item ${current === t ? 'active' : ''}`}
              onClick={() => setCurrent(t)}
            >
              <span style={{ fontWeight: 700 }}>{t}</span>
              <span className="text-mono" style={{ fontSize: 11 }}>
                ${fmtPrice(spotPrices[t] ?? chains[t]?.spot)}
              </span>
            </div>
          ))}
        </div>

        {/* Chart */}
        <div className="overlay-chart">
          <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
        </div>

        {/* GEX Levels + Indicators Sidebar */}
        {showSidebar && (
          <div className="overlay-panel">
            {/* GammaPulse panel header */}
            <div style={{ borderBottom: '1px solid var(--border-faint)', padding: '8px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 800, color: '#10dc9a', fontSize: 11 }}>GAMMAPULSE</span>
              {signal && (
                <span style={{
                  fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4,
                  background: (signal === 'RESISTANCE' || signal === 'AIR POCKET') ? 'rgba(255,86,86,0.2)' : signal === 'PINNING' ? 'rgba(244,196,48,0.2)' : 'rgba(16,220,154,0.2)',
                  color: (signal === 'RESISTANCE' || signal === 'AIR POCKET') ? '#ff5656' : signal === 'PINNING' ? '#f4c430' : '#10dc9a',
                }}>
                  {signal === 'SUPPORT' || signal === 'MAGNET UP' ? 'WATCHING FOR BOTTOM' : signal === 'RESISTANCE' || signal === 'AIR POCKET' ? 'WATCHING FOR TOP' : 'PINNED'}
                </span>
              )}
            </div>

            {/* Mode + IV + Alert */}
            <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-faint)', fontSize: 10, fontFamily: 'var(--mono)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ color: 'var(--text-3)' }}>MODE</span>
                <span style={{ fontWeight: 700 }}>{tf.days <= 1 ? '0DTE SCALP' : tf.days <= 5 ? 'SWING TRADE' : 'POSITION'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ color: 'var(--text-3)' }}>IV</span>
                <span style={{ fontWeight: 700, color: (ed.iv || 0) > 30 ? '#f4c430' : '#10dc9a' }}>
                  {ed.iv ? `${ed.iv.toFixed(1)}%` : '-'}
                  {(ed.iv || 0) > 40 ? ' HIGH' : (ed.iv || 0) > 25 ? ' ~ PRICEY' : ' ~ CHEAP'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ color: '#f4c430', fontWeight: 800 }}>LEVELS</span>
                <span style={{ color: 'var(--text-3)' }}>
                  S: ${floor || '-'} / ${ed.zgl || '-'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span />
                <span style={{ color: 'var(--text-3)' }}>
                  R: ${ceiling || '-'} / ${king || '-'}
                </span>
              </div>
            </div>

            {/* GEX Levels */}
            <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-faint)' }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: '#10dc9a', marginBottom: 6 }}>GEX LEVELS</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-3)' }}>King</span>
                  <span style={{ color: '#f4c430', fontWeight: 800 }}>${king || '-'} ★</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-3)' }}>Floor</span>
                  <span style={{ color: '#10dc9a', fontWeight: 700 }}>${floor || '-'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-3)' }}>Ceiling</span>
                  <span style={{ color: '#ff5656', fontWeight: 700 }}>${ceiling || '-'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-3)' }}>Signal</span>
                  <span style={{ fontWeight: 700 }}>
                    {signal === 'MAGNET UP' ? '▲' : signal === 'AIR POCKET' ? '▼' : '●'} {signal || '-'}
                  </span>
                </div>
              </div>
            </div>

            {/* Mini GEX strip (compact version of heatmap) */}
            <div style={{ padding: '4px 10px', borderBottom: '1px solid var(--border-faint)', maxHeight: 200, overflowY: 'auto' }}>
              {miniStrikes.slice(0, 30).map((s) => {
                let bg;
                if (s.node_type === 'king') bg = s.net_gex >= 0 ? '#f4c430' : '#a24dff';
                else if (s.node_type === 'gatekeeper') bg = '#a24dff';
                else if (s.net_gex >= 0) bg = '#1ca571';
                else bg = '#d22d3c';
                const isSpot = spot && Math.abs(s.strike - spot) < (spot * 0.002);
                return (
                  <div key={s.strike} style={{ display: 'flex', alignItems: 'center', gap: 2, height: 12, background: isSpot ? 'rgba(255,255,255,0.05)' : 'transparent' }}>
                    <span style={{ width: 32, fontSize: 9, color: isSpot ? '#fff' : 'var(--text-3)', textAlign: 'right', fontWeight: isSpot ? 800 : 400 }}>
                      {s.node_type === 'king' ? '★' : s.node_type === 'floor' ? '▼' : s.node_type === 'ceiling' ? '▲' : ''}{s.strike}
                    </span>
                    <div style={{
                      width: `${Math.max(2, s.pct * 0.5)}px`, height: 7,
                      background: bg, opacity: s.is_air ? 0.12 : 0.85, borderRadius: 1,
                    }} />
                  </div>
                );
              })}
            </div>

            {/* EMA values */}
            {indicators && (
              <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-faint)', fontFamily: 'var(--mono)', fontSize: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
                  <span style={{ color: 'rgba(16,220,154,0.8)' }}>EMA 8</span>
                  <span style={{ color: 'rgba(162,77,255,0.8)' }}>EMA 21</span>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>EMA 50</span>
                  <span style={{ color: 'rgba(255,165,0,0.7)' }}>EMA 200</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4, fontWeight: 700 }}>
                  <span style={{ color: 'rgba(16,220,154,0.8)' }}>{indicators.ema8_current?.toFixed(1) || '-'}</span>
                  <span style={{ color: 'rgba(162,77,255,0.8)' }}>{indicators.ema21_current?.toFixed(1) || '-'}</span>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>{indicators.ema50_current?.toFixed(1) || '-'}</span>
                  <span style={{ color: 'rgba(255,165,0,0.7)' }}>{indicators.ema200_current?.toFixed(1) || '-'}</span>
                </div>
              </div>
            )}

            {/* RSI + ADX + Trend + Extension */}
            {indicators && (
              <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-faint)', fontFamily: 'var(--mono)', fontSize: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ color: 'var(--text-3)' }}>RSI</span>
                  <span style={{
                    fontWeight: 700,
                    color: (indicators.rsi?.value || 50) > 70 ? '#ff5656' : (indicators.rsi?.value || 50) < 30 ? '#10dc9a' : '#c8cdd8',
                  }}>
                    {indicators.rsi?.value ?? '-'}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ color: 'var(--text-3)' }}>ADX</span>
                  <span style={{ fontWeight: 700 }}>
                    {indicators.adx?.value ?? '-'}
                    {indicators.adx?.trend && (
                      <span style={{
                        marginLeft: 4, fontSize: 8,
                        color: indicators.adx.trend === 'Active' ? '#10dc9a' : indicators.adx.trend === 'Developing' ? '#f4c430' : '#8a93a8',
                      }}>
                        {indicators.adx.trend}
                      </span>
                    )}
                  </span>
                </div>
                {/* Trend State (EMA cloud classification) */}
                {indicators.trendState && indicators.trendState.state !== 'UNKNOWN' && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ color: 'var(--text-3)' }}>Trend</span>
                    <span style={{
                      fontWeight: 700, fontSize: 9,
                      color: indicators.trendState.state.includes('BULLISH') ? '#10dc9a'
                        : indicators.trendState.state.includes('BEARISH') ? '#ff5656' : '#f4c430',
                    }}>
                      {indicators.trendState.state.replace('_', ' ')}
                    </span>
                  </div>
                )}
                {/* ATR Extension */}
                {indicators.atrExtension && indicators.atrExtension.state !== 'UNKNOWN' && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ color: 'var(--text-3)' }}>Location</span>
                    <span style={{
                      fontWeight: 700, fontSize: 9,
                      color: indicators.atrExtension.state === 'ACTIONABLE' ? '#10dc9a'
                        : indicators.atrExtension.state === 'NORMAL' ? '#c8cdd8'
                        : indicators.atrExtension.state === 'EXTENDED' ? '#f4c430'
                        : indicators.atrExtension.state === 'OVEREXTENDED' ? '#ff5656'
                        : indicators.atrExtension.state === 'OVERSOLD' ? '#10dc9a' : '#8a93a8',
                    }}>
                      {indicators.atrExtension.state}
                      {indicators.atrExtension.ext_from_20ma != null && (
                        <span style={{ color: 'var(--text-3)', marginLeft: 3 }}>
                          ({indicators.atrExtension.ext_from_20ma > 0 ? '+' : ''}{indicators.atrExtension.ext_from_20ma} ATR)
                        </span>
                      )}
                    </span>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-3)' }}>SOE</span>
                  <span style={{ fontWeight: 700 }}>
                    {chains[current]?.signal || '-'}
                  </span>
                </div>
              </div>
            )}

            {/* Greeks source */}
            <div style={{ padding: '6px 10px', fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--mono)' }}>
              Greeks: <span style={{ color: chains[current]?._greeks_source === 'massive' ? '#10dc9a' : '#ffc800', fontWeight: 700 }}>
                {chains[current]?._greeks_source === 'massive' ? 'MASSIVE' : 'TRADIER'}
              </span>
              {chains[current]?._greeks_age_seconds != null && (
                <span> ({chains[current]._greeks_age_seconds}s)</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* GEX strip — compact horizontal bar under chart */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '4px 14px',
        background: 'var(--bg-1)', borderTop: '1px solid var(--border-faint)',
        fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-2)',
      }}>
        <span style={{ color: '#f4c430', fontWeight: 800 }}>GEX</span>
        <span style={{ color: '#f4c430' }}>★ KING ${king || '-'}</span>
        <span style={{ color: '#10dc9a' }}>▼ FLOOR ${floor || '-'}</span>
        <span style={{ color: '#ff5656' }}>▲ CEIL ${ceiling || '-'}</span>
        <span>ZGL ${ed.zgl || '-'}</span>
        <span className="sep">·</span>
        <span style={{
          color: signal === 'MAGNET UP' || signal === 'SUPPORT' ? '#10dc9a' : signal === 'PINNING' ? '#f4c430' : '#ff5656',
          fontWeight: 700,
        }}>
          {signal === 'MAGNET UP' ? '▲' : signal === 'AIR POCKET' ? '▼' : '●'} {signal}
        </span>
        <span>{regime} γ</span>
        <div style={{ flex: 1 }} />
        {chains[current]?._ivp != null && (
          <span style={{ color: chains[current]._ivp <= 30 ? '#10dc9a' : chains[current]._ivp <= 50 ? '#f4c430' : '#ff5656' }}>
            IVP {chains[current]._ivp}%
          </span>
        )}
        <span>IV {ed.iv ? `${ed.iv.toFixed(1)}%` : '-'}</span>
      </div>

      {/* Bottom trade ideas button */}
      {!showIdeas && (
        <div
          className="overlay-ideas-btn"
          onClick={() => setShowIdeas(true)}
        >
          💡 Show Trade Ideas for {current}
        </div>
      )}
      {showIdeas && (
        <div className="overlay-ideas-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontWeight: 800, color: '#10dc9a' }}>💡 TRADE IDEA · {signal}</span>
            <button className="header-btn" onClick={() => setShowIdeas(false)}>✕</button>
          </div>
          <div className="text-mono" style={{ fontSize: 11 }}>
            <div>Entry: ${fmtPrice(spot)}</div>
            <div>Target: ${king} ({signal?.includes('UP') || signal === 'SUPPORT' ? 'king' : 'floor'})</div>
            <div>Stop: ${signal?.includes('UP') || signal === 'SUPPORT' ? floor : ceiling}</div>
            <div className="text-dim" style={{ marginTop: 4 }}>
              Reason: dealer {signal?.includes('UP') || signal === 'PINNING' ? 'long gamma' : 'short gamma'} near spot. Not financial advice.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
