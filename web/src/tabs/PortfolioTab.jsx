import React, { useEffect, useState, useRef, useCallback } from 'react';
import { createChart } from 'lightweight-charts';
import { api } from '../api.js';
import { fmtPrice } from '../lib/format.js';

export default function PortfolioTab() {
  const [acct, setAcct] = useState(null);
  const [openPos, setOpenPos] = useState([]);
  const [closedPos, setClosedPos] = useState([]);
  const [equity, setEquity] = useState([]);
  const [stats, setStats] = useState(null);
  const [showClosed, setShowClosed] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const chartRef = useRef(null);
  const containerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [p, h] = await Promise.all([api.portfolio(), api.portfolioHistory()]);
      setAcct(p.account);
      setOpenPos(p.open || []);
      setClosedPos(h.closed || []);
      setEquity(h.equity || []);
      setStats(h.stats);
    } catch {}
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15_000);
    return () => clearInterval(iv);
  }, [load]);

  // Equity curve chart
  useEffect(() => {
    if (!containerRef.current || !equity.length) return;
    if (chartRef.current) chartRef.current.remove();

    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0a0f1c' }, textColor: '#8a93a8', fontFamily: 'DM Mono, monospace', fontSize: 10 },
      grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
      rightPriceScale: { borderColor: '#1a2338' },
      timeScale: { borderColor: '#1a2338' },
      height: 200,
    });
    chartRef.current = chart;

    const startBal = acct?.starting_balance || 20000;
    const series = chart.addAreaSeries({
      lineColor: '#10dc9a',
      topColor: 'rgba(16,220,154,0.25)',
      bottomColor: 'rgba(16,220,154,0.02)',
      lineWidth: 2,
      priceLineVisible: false,
    });

    const data = equity.map((e) => {
      const [y, m, d] = e.date.split('-');
      return { time: { year: +y, month: +m, day: +d }, value: e.equity };
    });

    // Add starting point if no history yet
    if (!data.length && acct) {
      const now = new Date();
      data.push({ time: { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() }, value: startBal });
    }

    if (data.length) {
      series.setData(data);
      // Color red if below starting balance
      const last = data[data.length - 1]?.value || 0;
      if (last < startBal) {
        series.applyOptions({ lineColor: '#ff5656', topColor: 'rgba(255,86,86,0.15)', bottomColor: 'rgba(255,86,86,0.02)' });
      }
      // Starting balance line
      series.createPriceLine({ price: startBal, color: 'rgba(255,255,255,0.2)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Start' });
    }
    chart.timeScale().fitContent();

    const resize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.remove(); chartRef.current = null; };
  }, [equity, acct]);

  const pnlColor = (v) => (v > 0 ? '#10dc9a' : v < 0 ? '#ff5656' : '#8a93a8');
  const fmtPnl = (v) => `${v >= 0 ? '+' : '-'}$${Math.abs(v || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  const fmtPct = (v) => `${v >= 0 ? '+' : ''}${(v || 0).toFixed(1)}%`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
      {/* Title */}
      <div style={{ padding: '16px 20px 8px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 800 }}>
          <span style={{ color: '#10dc9a' }}>Paper</span> Portfolio
        </span>
        <button className="ctrl-btn" onClick={() => { if (confirm('Reset paper account to $20,000?')) api.portfolioReset().then(load); }} style={{ fontSize: 9, marginLeft: 'auto', color: '#ff5656' }}>
          Reset Account
        </button>
      </div>

      {/* Stats bar — MirBot style */}
      {acct && (
        <div style={{ display: 'flex', gap: 1, margin: '8px 20px', background: 'var(--border-faint)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          {[
            { label: 'PORTFOLIO', val: `$${(acct.equity || 0).toLocaleString()}`, color: 'var(--text-1)' },
            { label: 'P&L', val: `${fmtPnl(acct.total_pnl)} (${fmtPct(acct.total_pnl_pct)})`, color: pnlColor(acct.total_pnl) },
            { label: 'UNREALIZED', val: fmtPnl(acct.unrealized), color: pnlColor(acct.unrealized) },
            { label: 'WIN RATE', val: `${acct.win_rate}% (${acct.total_trades})`, color: '#f4c430' },
            { label: 'CASH AVAILABLE', val: `$${(acct.cash || 0).toLocaleString()}`, color: 'var(--text-1)' },
          ].map((c) => (
            <div key={c.label} style={{ flex: 1, padding: '14px 16px', background: 'var(--bg-panel)', textAlign: 'center' }}>
              <div style={{ fontSize: 9, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>{c.label}</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: c.color, fontFamily: 'var(--mono)' }}>{c.val}</div>
            </div>
          ))}
        </div>
      )}

      {/* Open Positions — MirBot style */}
      <div style={{ margin: '8px 20px' }}>
        <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, marginBottom: 6 }}>
          Open Positions: {openPos.length}
        </div>
        {openPos.length === 0 && (
          <div style={{ padding: '20px', background: 'var(--bg-panel)', borderRadius: 'var(--radius-md)', color: 'var(--text-3)', fontSize: 12, textAlign: 'center' }}>
            No open positions. Go to Signals tab and click "Paper Trade" on a signal.
          </div>
        )}
        {openPos.map((pos) => {
          const pnl = pos.unrealized_pnl || 0;
          const pnlPct = pos.entry_cost ? (pnl / pos.entry_cost * 100) : 0;
          const isExpanded = expandedId === pos.id;
          return (
            <div key={pos.id} style={{ marginBottom: 2 }}>
              <div
                onClick={() => setExpandedId(isExpanded ? null : pos.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                  background: 'var(--bg-panel)', borderRadius: isExpanded ? 'var(--radius-md) var(--radius-md) 0 0' : 'var(--radius-md)',
                  cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 12,
                  borderLeft: `3px solid ${pnlColor(pnl)}`,
                }}
              >
                <span style={{ fontWeight: 800, minWidth: 50 }}>{pos.ticker}</span>
                <span style={{ color: 'var(--text-2)' }}>
                  x{pos.contracts} LONG {pos.option_type === 'CALL' ? 'CALLS' : 'PUTS'} ${pos.strike}{pos.option_type === 'CALL' ? 'C' : 'P'} @${fmtPrice(pos.entry_price)}
                </span>
                <span style={{ color: 'var(--text-3)' }}>
                  ${fmtPrice(pos.entry_spot)} → ${fmtPrice(pos.current_spot)}
                </span>
                <span style={{ color: 'var(--text-3)', fontSize: 10 }}>
                  T:${fmtPrice(pos.target_price)} S:${fmtPrice(pos.stop_price)}
                </span>
                <span style={{ marginLeft: 'auto', fontWeight: 800, color: pnlColor(pnl), fontSize: 13 }}>
                  {fmtPnl(pnl)} ({fmtPct(pnlPct)})
                </span>
              </div>
              {isExpanded && (
                <div style={{ padding: '10px 14px', background: 'var(--bg-2)', borderRadius: '0 0 var(--radius-md) var(--radius-md)', borderLeft: `3px solid ${pnlColor(pnl)}` }}>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                    <button className="ctrl-btn" onClick={async () => { await api.portfolioClose(pos.id); load(); }} style={{ fontSize: 10, color: '#ff5656', border: '1px solid rgba(255,86,86,0.3)' }}>Close Position</button>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
                    Entry: {new Date(pos.opened_ts * 1000).toLocaleString()} · King: ${pos.entry_king} · Floor: ${pos.entry_floor} · Ceiling: ${pos.entry_ceiling} · Regime: {pos.entry_regime}
                  </div>
                  {pos.events?.length > 0 && (
                    <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text-3)' }}>
                      {pos.events.map((e, i) => (
                        <div key={i}>{new Date(e.ts * 1000).toLocaleTimeString()} — {e.event_type}: {e.message}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Equity Curve */}
      <div style={{ margin: '8px 20px' }}>
        <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, marginBottom: 6 }}>
          Equity Curve
          {equity.length > 0 && (
            <span style={{ marginLeft: 8, color: pnlColor((acct?.total_pnl) || 0), fontFamily: 'var(--mono)' }}>
              {fmtPct(acct?.total_pnl_pct)}
            </span>
          )}
        </div>
        <div ref={containerRef} style={{ width: '100%', height: 200, background: 'var(--bg-panel)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }} />
      </div>

      {/* Stats Grid */}
      {stats && stats.trades > 0 && (
        <div style={{ margin: '8px 20px', padding: '14px 20px', background: 'var(--bg-panel)', borderRadius: 'var(--radius-md)' }}>
          <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 700, marginBottom: 10 }}>PERFORMANCE</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, fontFamily: 'var(--mono)', fontSize: 11 }}>
            <div><span style={{ color: 'var(--text-3)' }}>Profit Factor</span><br /><span style={{ fontWeight: 700 }}>{stats.profit_factor ?? '∞'}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Avg Win</span><br /><span style={{ fontWeight: 700, color: '#10dc9a' }}>{fmtPct(stats.avg_win_pct)}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Avg Loss</span><br /><span style={{ fontWeight: 700, color: '#ff5656' }}>{fmtPct(stats.avg_loss_pct)}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Max DD</span><br /><span style={{ fontWeight: 700, color: '#ff5656' }}>{stats.max_drawdown_pct}%</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Largest Win</span><br /><span style={{ fontWeight: 700, color: '#10dc9a' }}>{fmtPnl(stats.largest_win)}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Largest Loss</span><br /><span style={{ fontWeight: 700, color: '#ff5656' }}>{fmtPnl(stats.largest_loss)}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Wins</span><br /><span style={{ fontWeight: 700 }}>{stats.wins}</span></div>
            <div><span style={{ color: 'var(--text-3)' }}>Losses</span><br /><span style={{ fontWeight: 700 }}>{stats.losses}</span></div>
          </div>

          {/* By-ticker breakdown */}
          {stats.by_ticker && Object.keys(stats.by_ticker).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 700, marginBottom: 6 }}>BY TICKER</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(stats.by_ticker).sort((a, b) => b[1].total_pnl - a[1].total_pnl).map(([t, s]) => (
                  <div key={t} style={{ padding: '6px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, fontSize: 10, fontFamily: 'var(--mono)', textAlign: 'center' }}>
                    <div style={{ fontWeight: 800 }}>{t}</div>
                    <div style={{ color: pnlColor(s.total_pnl) }}>{fmtPnl(s.total_pnl)}</div>
                    <div style={{ color: 'var(--text-3)' }}>{s.win_rate}% · {s.trades}T</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Close reasons */}
          {stats.close_reasons && Object.keys(stats.close_reasons).length > 0 && (
            <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-3)' }}>
              Exits: {Object.entries(stats.close_reasons).map(([r, n]) => `${r}(${n})`).join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* Closed Trades */}
      <div style={{ margin: '8px 20px', marginBottom: 20 }}>
        <button className="ctrl-btn" onClick={() => setShowClosed(!showClosed)} style={{ fontSize: 10, marginBottom: 6 }}>
          {showClosed ? '▼' : '▶'} Closed Trades ({closedPos.length})
        </button>
        {showClosed && closedPos.map((pos) => {
          const pnl = pos.realized_pnl || 0;
          const pnlPct = pos.realized_pnl_pct || 0;
          const isExpanded = expandedId === `closed-${pos.id}`;
          return (
            <div key={pos.id} style={{ marginBottom: 2 }}>
              <div
                onClick={() => setExpandedId(isExpanded ? null : `closed-${pos.id}`)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px',
                  background: 'var(--bg-panel)', borderRadius: isExpanded ? 'var(--radius-md) var(--radius-md) 0 0' : 'var(--radius-md)',
                  cursor: 'pointer', fontFamily: 'var(--mono)', fontSize: 11, opacity: 0.8,
                  borderLeft: `3px solid ${pnlColor(pnl)}`,
                }}
              >
                <span style={{ fontWeight: 800, minWidth: 50 }}>{pos.ticker}</span>
                <span style={{ color: 'var(--text-3)' }}>
                  x{pos.contracts} {pos.option_type === 'CALL' ? 'CALLS' : 'PUTS'} ${pos.strike} @${fmtPrice(pos.entry_price)}
                </span>
                <span style={{ color: 'var(--text-3)', fontSize: 9 }}>
                  {pos.close_reason}
                </span>
                <span style={{ marginLeft: 'auto', fontWeight: 800, color: pnlColor(pnl) }}>
                  {fmtPnl(pnl)} ({fmtPct(pnlPct)})
                </span>
              </div>
              {isExpanded && (
                <div style={{ padding: '10px 14px', background: 'var(--bg-2)', borderRadius: '0 0 var(--radius-md) var(--radius-md)', borderLeft: `3px solid ${pnlColor(pnl)}`, fontSize: 10, color: 'var(--text-3)' }}>
                  <div>Entry: {new Date(pos.opened_ts * 1000).toLocaleString()} · Spot ${fmtPrice(pos.entry_spot)} · Premium @${fmtPrice(pos.entry_price)} · Cost ${fmtPrice(pos.entry_cost)}</div>
                  <div>Exit: {pos.closed_ts ? new Date(pos.closed_ts * 1000).toLocaleString() : '-'} · Spot ${fmtPrice(pos.exit_spot)} · Premium @${fmtPrice(pos.exit_price)} · Reason: {pos.close_reason}</div>
                  <div>Hold: {pos.closed_ts && pos.opened_ts ? Math.round((pos.closed_ts - pos.opened_ts) / 3600) + 'h' : '-'} · R:R planned {pos.rr_ratio} · GEX: King ${pos.entry_king} Floor ${pos.entry_floor} Ceiling ${pos.entry_ceiling} ({pos.entry_regime})</div>
                  {pos.events?.length > 0 && (
                    <div style={{ marginTop: 4, borderTop: '1px solid var(--border-faint)', paddingTop: 4 }}>
                      {pos.events.map((e, i) => (
                        <div key={i}>{new Date(e.ts * 1000).toLocaleTimeString()} — <span style={{ color: e.event_type.includes('STOP') ? '#ff5656' : e.event_type.includes('TARGET') ? '#10dc9a' : '#8a93a8' }}>{e.event_type}</span>: {e.message}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
