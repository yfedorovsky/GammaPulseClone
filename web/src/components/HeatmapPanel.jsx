import React, { useMemo } from 'react';
import { useStore } from '../store.js';
import { fmtBig, fmtPrice, fmtStrike } from '../lib/format.js';
import { rowBackground, rowClass, signalExplanation, signalStripClass } from '../lib/gex.js';
import TooltipPopup, { useTooltip } from './Tooltip.jsx';

const MACRO_KEY = 'MACRO (ALL 200D)';

export default function HeatmapPanel({ ticker, panelIdx, expLabelOverride }) {
  const {
    chains,
    spotPrices,
    prevSpotPrices,
    viewMode,
    strikes: strikesWindow,
    exps,
    setExp,
    watchlists,
    activeWL,
    updateWatchlist,
    editMode,
  } = useStore();

  const data = chains[ticker];
  const expKey = `${ticker}-${panelIdx}`;
  const currentExp = expLabelOverride || exps[expKey] || MACRO_KEY;
  const spot = spotPrices[ticker] ?? data?.spot;
  const prev = prevSpotPrices[ticker];
  const dir =
    spot != null && prev != null && spot !== prev ? (spot > prev ? 'up' : 'down') : '';

  const expList = data?.exps || [MACRO_KEY];
  const exp_data =
    data?.exp_data?.[currentExp] || data?.exp_data?.[MACRO_KEY] || {};
  const rawStrikes = exp_data.strikes || [];

  // Trim to window, filter zero-GEX rows, display desc (highest first)
  const visibleStrikes = useMemo(() => {
    if (!rawStrikes.length) return [];
    // Remove strikes with zero GEX only (no open interest at all).
    // Keep everything else — even small values provide context.
    const nonZero = rawStrikes.filter(
      (s) => Math.abs(s.net_gex || 0) >= 1 || Math.abs(s.net_vex || 0) >= 1,
    );
    const sorted = [...nonZero].sort((a, b) => b.strike - a.strike);
    // For individual expirations (fewer strikes), show ALL non-zero rows.
    // For MACRO (many strikes), use the strike window to limit.
    const isMacro = currentExp.startsWith('MACRO');
    if (!isMacro || strikesWindow >= sorted.length) return sorted;
    const king = exp_data.king || spot || 0;
    const kingIdx = sorted.findIndex((s) => s.strike === king);
    const half = Math.floor(strikesWindow / 2);
    const lo = Math.max(
      0,
      (kingIdx === -1 ? Math.floor(sorted.length / 2) : kingIdx) - half,
    );
    const hi = Math.min(sorted.length, lo + strikesWindow);
    return sorted.slice(Math.max(0, hi - strikesWindow), hi);
  }, [rawStrikes, strikesWindow, exp_data.king, spot]);

  const king = exp_data.king || 0;
  const kingRow = rawStrikes.find((s) => s.strike === king);
  const kingIsPositive = kingRow ? kingRow.net_gex >= 0 : true;

  // Compute signal and regime PER-EXPIRATION (not from MACRO top-level)
  const posGex = exp_data.pos_gex || 0;
  const negGex = exp_data.neg_gex || 0;
  const regime = posGex > Math.abs(negGex) ? 'POS' : 'NEG';
  const delta = exp_data.net_delta ?? data?.net_delta;
  const vanna = exp_data.net_vanna ?? data?.net_vanna;
  const onePctMove = posGex + negGex;
  const floor = exp_data.floor;
  const ceiling = exp_data.ceiling;

  // Signal from per-expiration king position relative to spot
  const signal = useMemo(() => {
    if (!king || !spot) return '';
    const distPct = Math.abs(spot - king) / spot;
    if (distPct < 0.003) {
      return kingIsPositive ? 'PINNING' : 'DANGER';
    }
    if (kingIsPositive) {
      return king > spot ? 'MAGNET UP' : 'SUPPORT';
    }
    return king < spot ? 'AIR POCKET' : 'RESISTANCE';
  }, [king, spot, kingIsPositive]);

  // Expected-range indicator for the header (floor–ceiling)
  const rangeText = floor && ceiling ? `$${floor}–$${ceiling}` : '';

  // Dynamic prose strip
  const stripText = useMemo(
    () =>
      signalExplanation({
        signal,
        spot,
        king,
        kingIsPositive,
        regime,
      }),
    [signal, spot, king, kingIsPositive, regime],
  );
  const stripCls = signalStripClass(signal);

  // For spot row placement
  const spotIdx = useMemo(() => {
    if (spot == null) return -1;
    for (let i = 0; i < visibleStrikes.length; i++) {
      if (visibleStrikes[i].strike < spot) return i;
    }
    return visibleStrikes.length;
  }, [visibleStrikes, spot]);

  const maxIntensity = useMemo(() => {
    return visibleStrikes.reduce(
      (m, s) => Math.max(m, Math.abs(s.net_gex || 0)),
      1,
    );
  }, [visibleStrikes]);

  const { tip, show: showTip, hide: hideTip } = useTooltip();

  const onChangeTicker = (e) => {
    const v = e.target.value.toUpperCase().trim();
    if (!v) return;
    const wl = watchlists.find((w) => w.id === activeWL);
    if (!wl) return;
    const newTickers = [...wl.tickers];
    newTickers[panelIdx] = v;
    updateWatchlist(activeWL, { tickers: newTickers });
  };

  const onRemove = () => {
    const wl = watchlists.find((w) => w.id === activeWL);
    if (!wl || wl.tickers.length <= 1) return;
    const newTickers = wl.tickers.filter((_, i) => i !== panelIdx);
    updateWatchlist(activeWL, { tickers: newTickers });
  };

  return (
    <div className="panel">
      {/* Ticker + expiration selector */}
      <div className="panel-head">
        {editMode ? (
          <>
            <input
              className="ctrl-input"
              defaultValue={ticker}
              onBlur={onChangeTicker}
              onKeyDown={(e) => e.key === 'Enter' && e.target.blur()}
              style={{ width: 70 }}
            />
            <button className="header-btn" onClick={onRemove}>✕</button>
          </>
        ) : (
          <span className="panel-ticker">{ticker}</span>
        )}
        <select
          className="ctrl-select"
          value={currentExp}
          onChange={(e) => setExp(expKey, e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        >
          {expList.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
      </div>

      {/* Stats block: compact one-line format matching original */}
      <div className="panel-stats">
        <div className="panel-stat-row panel-top-row">
          <span className={`panel-spot ${dir}`}>${fmtPrice(spot)}</span>
          {signal && (
            <span className="signal-pill" data-signal={signal}>
              {signal}
            </span>
          )}
          {regime && <span className="regime-pill">{regime} γ</span>}
          <div style={{ flex: 1 }} />
          {rangeText && <span className="panel-range">{rangeText}</span>}
        </div>

        <div className="panel-subline">
          <strong style={{ color: kingIsPositive ? 'var(--king-pos)' : 'var(--king-neg)' }}>
            King ${king}
          </strong>
          <span className="sep">·</span>
          ZGL ${exp_data.zgl ?? '-'}
          <span className="sep">·</span>
          {rangeText}
          <span className="sep">·</span>
          Δ{fmtBig(delta)}
          <span className="sep">·</span>
          V {fmtBig(vanna)}
          <span className="sep">·</span>
          1%{fmtBig(onePctMove)}
        </div>

        <div className="panel-desc">
          {ticker} · {stripText || '\u00a0'}
        </div>
      </div>

      {/* Heatmap rows */}
      <div className="heatmap">
        <TooltipPopup tip={tip} fmtBig={fmtBig} />
        {viewMode === 'bars' ? (
          <>
            {visibleStrikes.map((s, idx) => {
              const showSpotAbove = idx === spotIdx;
              const isKing = s.node_type === 'king';
              return (
                <React.Fragment key={s.strike}>
                  {showSpotAbove && (
                    <div className="row spot-row">
                      <span className="strike">
                        {fmtPrice(spot)} ◀
                      </span>
                      <span className="gex" />
                      <span className="vex" />
                    </div>
                  )}
                  <div
                    className={`row ${rowClass(s, spot)}`}
                    style={{ backgroundColor: rowBackground(s, spot) }}
                    onMouseEnter={(e) => showTip(s, e)}
                    onMouseLeave={hideTip}
                  >
                    <span className="strike">
                      {fmtStrike(s.strike)}
                      {s.confluence && <span className="confl-icon"> ⚡</span>}
                    </span>
                    <span className="gex">
                      {fmtBig(s.net_gex)}
                      {isKing && <span className="king-badge"> ★ KING</span>}
                    </span>
                    <span className="vex">{fmtBig(s.net_vex)}</span>
                  </div>
                </React.Fragment>
              );
            })}
            {spotIdx === visibleStrikes.length && (
              <div className="row spot-row">
                <span className="strike">{fmtPrice(spot)} ◀</span>
                <span className="gex" />
                <span className="vex" />
              </div>
            )}
          </>
        ) : (
          <>
            <div className="profile-legend">
              ◀ SPOT ${fmtPrice(spot)} | <span style={{ color: '#1ca571' }}>Green = +GEX</span> | <span style={{ color: '#d22d3c' }}>Red = -GEX</span>
            </div>
            {visibleStrikes.map((s, idx) => {
              const showSpotAbove = idx === spotIdx;
              const pct = maxIntensity
                ? (Math.abs(s.net_gex || 0) / maxIntensity) * 100
                : 0;
              let barColor;
              if (s.node_type === 'king') barColor = s.net_gex >= 0 ? '#f4c430' : '#a24dff';
              else if (s.node_type === 'gatekeeper') barColor = s.net_gex >= 0 ? '#1ca571' : '#a24dff';
              else barColor = s.net_gex >= 0 ? '#1ca571' : '#d22d3c';
              let dotColor = barColor;
              if (s.is_air) dotColor = 'rgba(255,255,255,0.1)';
              return (
                <React.Fragment key={s.strike}>
                  {showSpotAbove && (
                    <div className="profile-row spot-row" style={{ padding: '3px 10px' }}>
                      <span className="strike text-mono" style={{ fontWeight: 800 }}>{fmtPrice(spot)} ◀</span>
                      <div />
                    </div>
                  )}
                  <div
                    className="profile-row"
                    onMouseEnter={(e) => showTip(s, e)}
                    onMouseLeave={hideTip}
                  >
                    <span className="strike text-mono">
                      {fmtStrike(s.strike)}
                      <span className="profile-dot" style={{ background: dotColor }} />
                    </span>
                    <div className="profile-bar-track">
                      <div
                        className="profile-bar-fill"
                        style={{ width: `${Math.max(1, pct)}%`, background: barColor }}
                      />
                      <span className="profile-val">
                        {fmtBig(s.net_gex)}
                        {s.node_type === 'king' && ' ★'}
                      </span>
                    </div>
                  </div>
                </React.Fragment>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
