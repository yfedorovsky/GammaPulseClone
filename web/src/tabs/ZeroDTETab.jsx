/**
 * ZeroDTETab — Live 0DTE Confluence Alert Feed.
 *
 * Displays the most recent alerts from the 0DTE confluence engine (see
 * server/zero_dte_engine.py + server/zero_dte_loop.py).
 *
 * Each alert is rendered as a "trade ticket card" showing:
 *   - Grade (A+/A/B+/B/C) with direction emoji
 *   - Ticker + proposed contract (strike / right / expiration)
 *   - Entry / Target / Stop pricing + R-multiple
 *   - Confluence factor breakdown (5 factors × 0-4 stars)
 *   - GEX + Flow context
 *   - Copy-to-clipboard ticket button for fast execution
 *
 * Also shows a LIVE snapshot panel for each of the 4 tracked tickers
 * (SPY/SPX/QQQ/IWM) showing current evaluation even if no alert has fired
 * — useful for watching how close each ticker is to triggering.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import '../zdte-styles.css';

const TRACKED = ['SPY', 'SPX', 'QQQ', 'IWM'];

function StarBar({ points, max = 4 }) {
  const filled = '★'.repeat(Math.max(0, points));
  const empty = '☆'.repeat(Math.max(0, max - points));
  return (
    <span className="zdte-stars" data-pts={points}>
      {filled}{empty}
    </span>
  );
}

function GradeBadge({ grade, direction }) {
  const dirEmoji = direction === 'bullish' ? '🟢' : direction === 'bearish' ? '🔴' : '⚪';
  const cls = `zdte-grade zdte-grade-${grade?.replace('+', 'plus')?.toLowerCase() || 'c'}`;
  return (
    <span className={cls}>
      {dirEmoji} {grade}
    </span>
  );
}

function fmtMoney(v) {
  if (v == null) return '—';
  return `$${Number(v).toFixed(2)}`;
}
function fmtPct(v, digits = 2) {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%`;
}
function fmtRel(ts) {
  if (!ts) return '';
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function AlertCard({ alert }) {
  const [copied, setCopied] = useState(false);

  const strikeStr = alert.strike != null
    ? (Number(alert.strike) === Math.floor(alert.strike)
        ? `$${Math.floor(alert.strike)}`
        : `$${Number(alert.strike).toFixed(2)}`)
    : '?';
  const right = (alert.right || 'call').toUpperCase();

  const copyTicket = useCallback(() => {
    const text = [
      `${alert.grade} 0DTE: ${alert.ticker} ${strikeStr} ${right} ${alert.expiration}`,
      `Entry ${fmtMoney(alert.est_entry_price)} | Target ${fmtMoney(alert.target_mid)} (${alert.target_r}R) | Stop ${fmtMoney(alert.stop_mid)}`,
      `Spot ${fmtMoney(alert.spot)} → ${fmtMoney(alert.target_level)}`,
      `Signals: ${alert.gex_signal} · ${alert.flow_regime}`,
      `Confluence ${alert.total_points}/${alert.max_points}`,
    ].join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [alert, strikeStr, right]);

  return (
    <div className={`zdte-card zdte-card-${alert.direction}`}>
      <div className="zdte-card-header">
        <GradeBadge grade={alert.grade} direction={alert.direction} />
        <span className="zdte-card-ticker">{alert.ticker}</span>
        <span className="zdte-card-contract">
          {strikeStr} {right} {alert.expiration}
        </span>
        <div className="zdte-card-spacer" />
        <span className="zdte-card-age" title={alert.fired_at_iso}>
          {fmtRel(alert.fired_at)}
        </span>
        <button
          type="button"
          className="zdte-copy-btn"
          onClick={copyTicket}
          title="Copy trade ticket to clipboard"
        >
          {copied ? '✓ copied' : '⎘ copy'}
        </button>
      </div>

      <div className="zdte-card-pricing">
        <div className="zdte-pricing-item">
          <span className="zdte-pricing-label">ENTRY</span>
          <span className="zdte-pricing-val">{fmtMoney(alert.est_entry_price)}</span>
          {alert.est_bid && alert.est_ask && (
            <span className="zdte-pricing-spread">
              {fmtMoney(alert.est_bid)}/{fmtMoney(alert.est_ask)}
            </span>
          )}
        </div>
        <div className="zdte-pricing-item zdte-pricing-target">
          <span className="zdte-pricing-label">TARGET</span>
          <span className="zdte-pricing-val">{fmtMoney(alert.target_mid)}</span>
          {alert.target_r && (
            <span className="zdte-pricing-r">{alert.target_r}R</span>
          )}
        </div>
        <div className="zdte-pricing-item zdte-pricing-stop">
          <span className="zdte-pricing-label">STOP</span>
          <span className="zdte-pricing-val">{fmtMoney(alert.stop_mid)}</span>
          <span className="zdte-pricing-stop-pct">-50%</span>
        </div>
        <div className="zdte-pricing-item">
          <span className="zdte-pricing-label">TIME STOP</span>
          <span className="zdte-pricing-val">{alert.time_stop_minutes}min</span>
        </div>
      </div>

      <div className="zdte-factors">
        <div className="zdte-factors-header">
          <span>Confluence {alert.total_points}/{alert.max_points}</span>
          <span className="zdte-factors-spacer" />
          <span className="zdte-card-ctx">
            Spot <strong>{fmtMoney(alert.spot)}</strong>
            {alert.target_level && (
              <> → target <strong>{fmtMoney(alert.target_level)}</strong></>
            )}
          </span>
        </div>
        {alert.factors?.map((f) => (
          <div className="zdte-factor-row" key={f.name}>
            <StarBar points={f.points || 0} />
            <span className="zdte-factor-name">{f.name}</span>
            <span className="zdte-factor-reasoning">{f.reasoning}</span>
          </div>
        ))}
      </div>

      <div className="zdte-card-footer">
        <span>GEX: <strong>{alert.gex_signal || '—'}</strong></span>
        <span className="zdte-dot">·</span>
        <span>Flow: <strong>{alert.flow_regime || '—'}</strong></span>
        {alert.strike_quality === 'degraded' && (
          <>
            <span className="zdte-dot">·</span>
            <span className="zdte-warn">⚠ liquidity degraded</span>
          </>
        )}
      </div>
    </div>
  );
}

function LivePanel({ ticker }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const d = await api.zeroDteEvaluate(ticker);
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) setErr(e.message || String(e));
      }
    }
    load();
    const iv = setInterval(load, 5_000);
    return () => { alive = false; clearInterval(iv); };
  }, [ticker]);

  const ev = data?.evaluation;
  const direction = ev?.direction;
  const grade = ev?.grade || 'C';
  const points = ev?.total_points || 0;
  const maxPoints = ev?.max_points || 20;

  return (
    <div className={`zdte-live zdte-live-${direction || 'neutral'}`}>
      <div className="zdte-live-header">
        <strong className="zdte-live-ticker">{ticker}</strong>
        <GradeBadge grade={grade} direction={direction} />
        <span className="zdte-live-points">{points}/{maxPoints}</span>
        <div className="zdte-card-spacer" />
        <span className="zdte-live-spot">
          {ev?.spot ? fmtMoney(ev.spot) : '—'}
        </span>
      </div>
      {err && <div className="zdte-live-err">{err}</div>}
      {!err && ev && (
        <>
          <div className="zdte-live-ctx">
            {ev.gex_signal || '—'} · {ev.flow_regime || '—'}
            {ev.target_level && <> · target <strong>{fmtMoney(ev.target_level)}</strong></>}
          </div>
          {ev.factors?.length > 0 && (
            <div className="zdte-live-factors">
              {ev.factors.map((f) => (
                <span className="zdte-live-factor" key={f.name} title={f.reasoning}>
                  {f.name}
                  <StarBar points={f.points || 0} />
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function ZeroDTETab() {
  const [alerts, setAlerts] = useState([]);
  const [err, setErr] = useState(null);
  const [stats, setStats] = useState(null);

  // Poll alert history every 5s
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const d = await api.zeroDteAlerts(50);
        if (!alive) return;
        setAlerts(d.alerts || []);
        setStats(d.cooldown);
        setErr(null);
      } catch (e) {
        if (alive) setErr(e.message || String(e));
      }
    }
    load();
    const iv = setInterval(load, 5_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const summary = useMemo(() => {
    if (!alerts.length) return null;
    const byGrade = alerts.reduce((acc, a) => {
      acc[a.grade] = (acc[a.grade] || 0) + 1;
      return acc;
    }, {});
    return byGrade;
  }, [alerts]);

  return (
    <div className="zdte-tab">
      {/* Header */}
      <div className="zdte-header">
        <h2 className="zdte-title">
          🎯 0DTE CONFLUENCE ALERTS
        </h2>
        <div className="zdte-subtitle">
          Live combined signals: GEX + Fast NetFlow + Regime + Sweeps + GOLDEN.
          Fires on <strong>B+ grade or better</strong> (9+/20 points).
          10s eval loop · 10min cooldown per ticker/direction (grade upgrades bypass).
        </div>
      </div>

      {/* Summary row */}
      {summary && (
        <div className="zdte-summary">
          {['A+', 'A', 'B+', 'B', 'C'].map((g) => (
            summary[g] ? (
              <span className={`zdte-summary-pill zdte-grade-${g.replace('+', 'plus').toLowerCase()}`} key={g}>
                {g} × {summary[g]}
              </span>
            ) : null
          ))}
        </div>
      )}

      {/* Live panels — one per tracked ticker */}
      <div className="zdte-live-grid">
        {TRACKED.map((t) => <LivePanel key={t} ticker={t} />)}
      </div>

      {/* Alert feed */}
      {err && <div className="zdte-err">⚠ {err}</div>}
      <div className="zdte-feed-header">
        <h3>RECENT ALERTS</h3>
        <span className="zdte-feed-count">{alerts.length} alerts · newest first</span>
      </div>
      {alerts.length === 0 && !err && (
        <div className="zdte-empty">
          No alerts yet. System needs ~25 min of market data + qualifying confluence
          (9+ points) before firing. Live panels above show current scoring — watch
          for grades climbing toward B+/A/A+ to preview upcoming fires.
        </div>
      )}
      <div className="zdte-feed">
        {alerts.map((a) => (
          <AlertCard key={a.alert_id} alert={a} />
        ))}
      </div>

      {/* Footer cooldown stats */}
      {stats && (
        <div className="zdte-footer-stats">
          Fires: {stats.fires} · Suppressed (cooldown): {stats.suppressed} ·
          Suppressed (below B+): {stats.suppressed_low_grade} ·
          Active keys: {stats.active_keys}
        </div>
      )}
    </div>
  );
}
