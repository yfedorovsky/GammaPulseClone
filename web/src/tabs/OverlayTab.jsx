import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { createChart, LineStyle } from 'lightweight-charts';
import { useStore } from '../store.js';
import { api } from '../api.js';
import { fmtBig, fmtPrice } from '../lib/format.js';

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
          color: b.close >= b.open ? 'rgba(16,220,154,0.3)' : 'rgba(255,86,86,0.3)',
        }));
        candleRef.current.setData(bars);
        if (volumeRef.current) {
          volumeRef.current.setData(showVolume ? volBars : []);
        }
        if (chartRef.current && bars.length) {
          chartRef.current.timeScale().fitContent();
        }
      } catch (e) {
        console.warn('bars load failed', e);
      }
    }
    load();
    return () => { alive = false; };
  }, [current, tfIdx, tf.interval, tf.days, showSessions]);

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
    for (const line of linesRef.current) {
      try { candle.removePriceLine(line); } catch {}
    }
    linesRef.current = [];

    const data = chains[current];
    if (!data) return; // no chain data yet — lines cleared, chart shows candles only
    const ed = data.exp_data?.[MACRO_KEY] || {};
    const king = ed.king;
    const floor = ed.floor;
    const ceiling = ed.ceiling;
    const zgl = ed.zgl;
    const gatekeepers = ed.gatekeepers || [];
    const strikesList = ed.strikes || [];

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
    if (showLevels && floor) {
      linesRef.current.push(
        candle.createPriceLine({
          price: floor,
          color: '#10dc9a',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'FLOOR',
        }),
      );
    }
    if (showLevels && ceiling && ceiling !== king) {
      linesRef.current.push(
        candle.createPriceLine({
          price: ceiling,
          color: '#ff5656',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'CEILING',
        }),
      );
    }
    if (showZGL && zgl) {
      linesRef.current.push(
        candle.createPriceLine({
          price: zgl,
          color: '#ff3e3e',
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'ZGL',
        }),
      );
    }
    if (showGates) {
      for (const gk of gatekeepers) {
        if (gk === king || gk === floor || gk === ceiling) continue;
        linesRef.current.push(
          candle.createPriceLine({
            price: gk,
            color: 'rgba(162, 77, 255, 0.5)',
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: '',
          }),
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
          candle.createPriceLine({
            price: s.strike,
            color,
            lineWidth: lw,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: false,
            title: '',
          }),
        );
      }
    }
    // Spot marker
    const spot = spotPrices[current] ?? data?.spot;
    if (spot) {
      linesRef.current.push(
        candle.createPriceLine({
          price: spot,
          color: 'rgba(255,255,255,0.5)',
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: '◀ SPOT',
        }),
      );
    }
  }, [chains, current, showLevels, showZGL, showGates, showOrbs, spotPrices]);

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
        {signal && <span className="signal-pill" data-signal={signal}>{signal}</span>}
        {regime && <span className="regime-pill">{regime} γ</span>}
        <span className="sep">·</span>
        <span style={{ color: '#f4c430' }}>King ${king}</span>
        <span className="sep">·</span>
        <span>Floor ${floor} · Ceil ${ceiling}</span>
        <span className="sep">·</span>
        {rr != null && <span style={{ color: rr >= 1 ? '#10dc9a' : '#ff7070' }}>R:R {rr.toFixed(2)}</span>}
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
        <label className="ov-check"><input type="checkbox" checked={showLevels} onChange={(e) => setShowLevels(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>GEX Levels</span></label>
        <label className="ov-check"><input type="checkbox" checked={showZGL} onChange={(e) => setShowZGL(e.target.checked)} /> <span className="check-label">ZGL</span></label>
        <label className="ov-check"><input type="checkbox" checked={showGates} onChange={(e) => setShowGates(e.target.checked)} /> <span className="check-label">Gates</span></label>
        <label className="ov-check"><input type="checkbox" checked={showOrbs} onChange={(e) => setShowOrbs(e.target.checked)} /> <span className="check-label">Orbs</span></label>
        <label className="ov-check"><input type="checkbox" checked={showSidebar} onChange={(e) => setShowSidebar(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Sidebar</span></label>
        <label className="ov-check"><input type="checkbox" checked={showSessions} onChange={(e) => setShowSessions(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Sessions</span></label>
        <label className="ov-check"><input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} /> <span className="check-label" style={{ color: '#10dc9a' }}>Volume</span></label>
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

        {/* Mini heatmap sidebar */}
        {showSidebar && (
          <div className="overlay-mini">
            <div style={{ fontSize: 9, color: 'var(--text-3)', padding: '2px 0', fontWeight: 700 }}>GEX</div>
            {miniStrikes.map((s) => {
              let bg;
              if (s.node_type === 'king') bg = s.net_gex >= 0 ? '#f4c430' : '#a24dff';
              else if (s.net_gex >= 0) bg = '#1ca571';
              else bg = '#d22d3c';
              return (
                <div key={s.strike} style={{ display: 'flex', alignItems: 'center', gap: 2, height: 11 }}>
                  <span style={{ width: 30, fontSize: 9, color: 'var(--text-3)', textAlign: 'right' }}>{s.strike}</span>
                  <div
                    style={{
                      width: `${Math.max(2, s.pct * 0.6)}px`,
                      height: 7,
                      background: bg,
                      opacity: s.is_air ? 0.12 : 0.85,
                      borderRadius: 1,
                    }}
                  />
                  {s.pct >= 5 && (
                    <span style={{ fontSize: 8, color: 'var(--text-3)' }}>{s.pct}%</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
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
