import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, LineStyle } from 'lightweight-charts';
import { api } from '../api.js';
import { fmtBig, fmtPrice, fmtIV } from '../lib/format.js';

export default function HistoryTab() {
  const [ticker, setTicker] = useState('SPY');
  const [series, setSeries] = useState([]);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  async function load(t = ticker) {
    setLoading(true);
    try {
      const data = await api.history(t);
      setSeries(data.series || []);
      setIdx((data.series || []).length - 1);
    } catch {
      setSeries([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // GEX Time Machine chart — shows ZGL/King/Floor/Ceiling migration over time
  useEffect(() => {
    if (!chartContainerRef.current || !series.length) return;

    // Remove old chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0a0f1c' },
        textColor: '#8a93a8',
        fontFamily: 'DM Mono, monospace',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.03)' },
      },
      rightPriceScale: { borderColor: '#1a2338' },
      timeScale: { borderColor: '#1a2338', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      width: chartContainerRef.current.clientWidth,
      height: 280,
    });
    chartRef.current = chart;

    // Spot price line
    const spotLine = chart.addLineSeries({
      color: '#ffffff', lineWidth: 2, title: 'Spot',
      crosshairMarkerVisible: true, priceLineVisible: false, lastValueVisible: true,
    });
    spotLine.setData(series.filter(s => s.spot && s.ts).map(s => ({ time: s.ts, value: s.spot })));

    // King line
    const kingLine = chart.addLineSeries({
      color: '#f4c430', lineWidth: 2, lineStyle: LineStyle.Solid, title: 'King',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });
    kingLine.setData(series.filter(s => s.king && s.ts).map(s => ({ time: s.ts, value: s.king })));

    // ZGL line
    const zglLine = chart.addLineSeries({
      color: '#ff3e3e', lineWidth: 1, lineStyle: LineStyle.Dotted, title: 'ZGL',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });
    zglLine.setData(series.filter(s => s.zgl && s.ts).map(s => ({ time: s.ts, value: s.zgl })));

    // Floor line
    const floorLine = chart.addLineSeries({
      color: '#10dc9a', lineWidth: 1, lineStyle: LineStyle.Dashed, title: 'Floor',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });
    floorLine.setData(series.filter(s => s.floor && s.ts).map(s => ({ time: s.ts, value: s.floor })));

    // Ceiling line
    const ceilLine = chart.addLineSeries({
      color: '#ff5656', lineWidth: 1, lineStyle: LineStyle.Dashed, title: 'Ceiling',
      crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: true,
    });
    ceilLine.setData(series.filter(s => s.ceiling && s.ts).map(s => ({ time: s.ts, value: s.ceiling })));

    chart.timeScale().fitContent();

    // Markers for signal changes
    const markers = [];
    for (let i = 1; i < series.length; i++) {
      if (series[i].signal !== series[i-1].signal && series[i].ts && series[i].spot) {
        const isBull = series[i].signal === 'MAGNET UP' || series[i].signal === 'SUPPORT';
        markers.push({
          time: series[i].ts,
          position: isBull ? 'belowBar' : 'aboveBar',
          color: isBull ? '#10dc9a' : '#ff5656',
          shape: isBull ? 'arrowUp' : 'arrowDown',
          text: series[i].signal,
        });
      }
    }
    if (markers.length) spotLine.setMarkers(markers);

    return () => { chart.remove(); chartRef.current = null; };
  }, [series]);

  const current = series[idx];

  // Signal change log
  const signalChanges = useMemo(() => {
    const changes = [];
    for (let i = 1; i < series.length; i++) {
      if (series[i].signal !== series[i-1].signal) {
        changes.push({
          ts: series[i].ts,
          from: series[i-1].signal,
          to: series[i].signal,
          spot: series[i].spot,
          king: series[i].king,
          zgl: series[i].zgl,
        });
      }
    }
    return changes;
  }, [series]);

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto auto 1fr', height: '100%' }}>
      <div className="ctrl-bar">
        <strong style={{ fontSize: 14 }}>GEX Time Machine</strong>
        <input
          className="ctrl-input"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          placeholder="Ticker"
          style={{ width: 90 }}
        />
        <button className="header-btn" onClick={() => load()}>Load</button>
        {loading && <span className="mini text-dim">Loading...</span>}
        <span className="mini text-dim">
          {series.length} snapshots
        </span>
        <div style={{ flex: 1 }} />
        <span className="mini text-dim">
          <span style={{ color: '#fff' }}>━</span> Spot
          <span style={{ color: '#f4c430', marginLeft: 8 }}>━</span> King
          <span style={{ color: '#ff3e3e', marginLeft: 8 }}>···</span> ZGL
          <span style={{ color: '#10dc9a', marginLeft: 8 }}>---</span> Floor
          <span style={{ color: '#ff5656', marginLeft: 8 }}>---</span> Ceil
        </span>
      </div>

      {/* Time Machine Chart */}
      <div ref={chartContainerRef} style={{ width: '100%', minHeight: 280 }} />

      <div style={{ padding: 16, overflow: 'auto' }}>
        {series.length ? (
          <>
            {/* Timeline scrubber */}
            <input
              type="range"
              min={0}
              max={Math.max(0, series.length - 1)}
              value={idx}
              onChange={(e) => setIdx(+e.target.value)}
              style={{ width: '100%' }}
            />
            <div className="mini text-dim" style={{ marginBottom: 12 }}>
              {current && new Date((current.ts || 0) * 1000).toLocaleString()}
            </div>

            {/* Snapshot detail */}
            {current && (
              <div className="card" style={{ marginBottom: 14 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                  <Stat label="Spot" value={`$${fmtPrice(current.spot)}`} />
                  <Stat label="Signal" value={<span className="signal-pill" data-signal={current.signal}>{current.signal}</span>} />
                  <Stat label="Regime" value={`${current.regime} γ`} />
                  <Stat label="King" value={`$${current.king}`} color="#f4c430" />
                  <Stat label="Floor" value={`$${current.floor}`} color="#10dc9a" />
                  <Stat label="Ceiling" value={`$${current.ceiling}`} color="#ff5656" />
                  <Stat label="ZGL" value={`$${current.zgl}`} color="#ff3e3e" />
                  <Stat label="IV" value={fmtIV(current.iv)} />
                  <Stat label="+GEX" value={fmtBig(current.pos_gex)} />
                  <Stat label="-GEX" value={fmtBig(current.neg_gex)} />
                  <Stat label="Net Delta" value={fmtBig(current.net_delta)} />
                  <Stat label="Vanna" value={fmtBig(current.net_vanna)} />
                </div>
              </div>
            )}

            {/* Signal change log */}
            {signalChanges.length > 0 && (
              <div>
                <div style={{ fontWeight: 800, marginBottom: 6, fontSize: 12 }}>Signal Changes</div>
                {signalChanges.map((c, i) => (
                  <div key={i} style={{ fontSize: 11, fontFamily: 'var(--mono)', marginBottom: 3, display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--text-3)' }}>{new Date(c.ts * 1000).toLocaleTimeString()}</span>
                    <span style={{ color: '#ff5656' }}>{c.from}</span>
                    <span style={{ color: 'var(--text-3)' }}>→</span>
                    <span style={{ color: '#10dc9a' }}>{c.to}</span>
                    <span style={{ color: 'var(--text-3)' }}>@ ${fmtPrice(c.spot)}</span>
                    <span style={{ color: '#f4c430' }}>King ${c.king}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <div style={{ textAlign: 'center', color: 'var(--text-3)', padding: 40 }}>
            No snapshots yet. Let the worker run for a few cycles, then reload.
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <div className="mini text-dim">{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
