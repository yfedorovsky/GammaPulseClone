import React, { useMemo } from 'react';
import { useStore } from '../store.js';
import { fmtBig, fmtBigPrecise, fmtPrice, fmtStrike } from '../lib/format.js';
import { rowBackground, rowClass, signalExplanation, signalStripClass } from '../lib/gex.js';
import TooltipPopup, { useTooltip } from './Tooltip.jsx';

const MACRO_KEY = 'MACRO (ALL 200D)';

// Helpers for the MACRO-view hint (directs user to near-dated expirations
// for tactical reads). Both functions operate on the exp list returned by
// the backend, which is ordered chronologically with MACRO sentinel keys
// possibly appearing alongside real YYYY-MM-DD expirations.

function isRealExpiration(e) {
  return typeof e === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(e);
}

function exps_list_has_near_dated(expList) {
  return Array.isArray(expList) && expList.some(isRealExpiration);
}

function findNearestExpiration(expList) {
  if (!Array.isArray(expList)) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let best = null;
  let bestDist = Infinity;
  for (const e of expList) {
    if (!isRealExpiration(e)) continue;
    const d = new Date(e + 'T00:00:00');
    const dist = Math.abs(d - today);
    if (dist < bestDist) {
      bestDist = dist;
      best = e;
    }
  }
  return best;
}

// king-selection-v3 fix #1 (2026-05-27) — nearest monthly OPEX (3rd Friday).
// The MACRO (ALL 200D) aggregation pulls king/floor/ceiling toward strikes
// where long-dated OI dominates (LEAPs + quarterly OPEX). That's too far
// from intraday spot to be tradeable — OG GammaPulse Pro defaults to the
// nearest monthly OPEX, which is where dealer hedging actually concentrates
// for intraday flow. This helper finds that expiration.
//
// Selection: 3rd Friday of the month (standard equity options monthly OPEX),
// future-dated, within 60 days. Falls back to findNearestExpiration if no
// monthly is within window — captures the "only weeklies are listed" case
// for thinly traded names.
export function findNearestMonthlyOpex(expList) {
  if (!Array.isArray(expList)) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const maxAheadMs = 60 * 24 * 3600 * 1000; // 60 days
  let best = null;
  let bestDist = Infinity;
  for (const e of expList) {
    if (!isRealExpiration(e)) continue;
    const d = new Date(e + 'T00:00:00');
    if (d < today) continue;
    const dom = d.getDate();
    const dow = d.getDay();
    // 3rd Friday: dow=Friday(5) AND day-of-month in [15, 21]
    if (dow !== 5 || dom < 15 || dom > 21) continue;
    const dist = d - today;
    if (dist > maxAheadMs) continue;
    if (dist < bestDist) {
      bestDist = dist;
      best = e;
    }
  }
  return best || findNearestExpiration(expList);
}

function HeatmapPanel({ ticker, panelIdx, expLabelOverride, matrixKing }) {
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
    zeroDte,
    earningsThisWeek,
  } = useStore();

  const data = chains[ticker];
  const expKey = `${ticker}-${panelIdx}`;
  const expList = data?.exps || [MACRO_KEY];

  // 0DTE mode: find today's expiration date
  const todayExp = useMemo(() => {
    if (!zeroDte) return null;
    const today = new Date().toISOString().slice(0, 10);
    return expList.find((e) => e === today || e.startsWith(today));
  }, [zeroDte, expList]);

  // Precedence: 0DTE mode forces today's exp > user's dropdown choice >
  // parent's default > nearest monthly OPEX > MACRO sentinel fallback.
  // User choice MUST beat expLabelOverride, otherwise the dropdown in FOCUS
  // mode appears dead (store updates but this derived value ignores it).
  //
  // king-selection-v3 fix #1 (2026-05-27): nearest monthly OPEX now sits
  // ahead of MACRO_KEY in the fallback. MACRO is still selectable via the
  // dropdown but is no longer the silent default — it pulls king/floor too
  // far from intraday spot (SMH compare: MACRO king $600 round-number vs
  // OG monthly king $585 from concentrated 3rd-Friday OI).
  const nearestMonthlyOpex = useMemo(
    () => findNearestMonthlyOpex(expList),
    [expList]
  );
  const currentExp = todayExp || exps[expKey] || expLabelOverride
    || nearestMonthlyOpex || MACRO_KEY;

  // Nearest real (YYYY-MM-DD) expiration — used by the MACRO hint to offer
  // a one-click jump to a tactical view. Null if the chain only has the
  // MACRO sentinel (edge case during initial load).
  const nearestExpiration = useMemo(
    () => findNearestExpiration(expList),
    [expList]
  );
  const spot = spotPrices[ticker] ?? data?.spot;
  const prev = prevSpotPrices[ticker];
  const dir =
    spot != null && prev != null && spot !== prev ? (spot > prev ? 'up' : 'down') : '';

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
    // king-selection-v3 (2026-05-27): on MACRO use king_far (unconstrained)
    // for the window-anchor — MACRO is the structural view; far-OTM kings
    // matter here. Per-expiration panels use the constrained king (5% cap).
    const king = exp_data.king_far || exp_data.king || spot || 0;
    const kingIdx = sorted.findIndex((s) => s.strike === king);
    const half = Math.floor(strikesWindow / 2);
    const lo = Math.max(
      0,
      (kingIdx === -1 ? Math.floor(sorted.length / 2) : kingIdx) - half,
    );
    const hi = Math.min(sorted.length, lo + strikesWindow);
    return sorted.slice(Math.max(0, hi - strikesWindow), hi);
  }, [rawStrikes, strikesWindow, exp_data.king, spot]);

  // MACRO panel surfaces king_far (unconstrained); per-expiration panels
  // surface king (constrained to 5% of spot). king-selection-v3 2026-05-27.
  const _isMacroPanel = currentExp.startsWith('MACRO');
  const king = (_isMacroPanel ? exp_data.king_far : exp_data.king) || 0;
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

  // Expected Move (1 trading day): spot * IV * sqrt(1/252).
  // The backend reports IV in PERCENT (e.g. 17.3), but this formula needs a
  // FRACTION (0.173). Without normalizing, EM printed 100x too large — SPY showed
  // "EM ±$799.05 (109.1%)" instead of the correct "±$7.99 (1.1%)". Normalize
  // defensively: anything > 1 is treated as a percent and divided by 100.
  const ivRaw = exp_data.iv || data?.iv || 0;
  const iv = ivRaw > 1 ? ivRaw / 100 : ivRaw;
  const expectedMove = useMemo(() => {
    if (!spot || !iv) return null;
    const em = spot * iv * Math.sqrt(1 / 252);
    return { dollars: em, pct: (em / spot) * 100 };
  }, [spot, iv]);

  // Dynamic prose strip — prefer backend's actionable callout when present
  // (OG-inspired format: "0.5% below king $70 · magnet pull"). Fall back to
  // legacy signalExplanation() if backend didn't populate callout (older
  // cached data or unusual strike set).
  const backendCallout = exp_data?.callout;
  const stripText = useMemo(() => {
    if (backendCallout) return backendCallout;
    return signalExplanation({
      signal, spot, king, kingIsPositive, regime,
    });
  }, [backendCallout, signal, spot, king, kingIsPositive, regime]);
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
          <>
            <span className="panel-ticker">{ticker}</span>
            {earningsThisWeek[ticker] && (
              <span className="earnings-badge-sm" title={`Earnings ${earningsThisWeek[ticker].date} ${earningsThisWeek[ticker].timing === 'bmo' ? 'Before Open' : earningsThisWeek[ticker].timing === 'amc' ? 'After Close' : ''}`}>
                📅
              </span>
            )}
          </>
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

      {/* MACRO-view hint — nudges users toward tactical (near-dated) expirations
         for day-trading decisions. MACRO aggregates 200 days of positioning and
         is best for structural reads, not intraday scalps. Validated by OG
         GammaPulse dev feedback 2026-04-21: "For a tactical read on today
         specifically, switching to a near-dated expiration in the dropdown
         usually gives sharper signal than macro." */}
      {currentExp.startsWith('MACRO') && nearestExpiration && (
        <div className="macro-hint">
          <span className="macro-hint-icon">ⓘ</span>
          MACRO aggregates 200D positioning — great for structural reads.
          For <strong>today's tactical levels</strong>, switch to a
          near-dated expiration
          <button
            type="button"
            className="macro-hint-jump"
            onClick={() => setExp(expKey, nearestExpiration)}
            title={`Jump to ${nearestExpiration}`}
          >
            → {nearestExpiration}
          </button>
        </div>
      )}

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
          {expectedMove && (
            <span className="em-badge">
              EM {'\u00b1'}${expectedMove.dollars.toFixed(2)} ({expectedMove.pct.toFixed(1)}%)
            </span>
          )}
          <div style={{ flex: 1 }} />
          {zeroDte && <span className="dte-badge">0DTE</span>}
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
          <span
            title={
              "GEX methodology (v4, Apr 21 2026):\n" +
              "  GEX = γ × activity-weighted OI × 100 × S² × 0.01\n" +
              "  Effective OI = raw_OI × (1 + 0.4 × log(1 + vol/OI))\n" +
              "  Log-scaling replaces hard cap (was min(vol/OI, 20) in v3)\n" +
              "  to prevent sign inversions on 0DTE ATM close-out volume.\n\n" +
              "KING bifurcation (v4):\n" +
              "  king_pos = biggest POSITIVE GEX (the magnet)\n" +
              "  king_neg = biggest NEGATIVE GEX (danger / acceleration zone)\n" +
              "  Primary KING label = king_pos; −KING pill marks king_neg.\n\n" +
              "Data: Tradier chain + ThetaData greeks, OCC settlement OI.\n" +
              "SPX updated every 15s via priority-refresh task.\n\n" +
              "Our magnitudes may differ from SpotGamma/Skylit (which use\n" +
              "OPRA tick-level trade classification). We're conservative,\n" +
              "reproducible, and bifurcate positive vs negative walls."
            }
            style={{
              marginLeft: 6, cursor: 'help', color: 'var(--text-3)',
              fontSize: 9, opacity: 0.5, userSelect: 'none',
            }}
          >
            ⓘ methodology
          </span>
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
              const isNegKing = s.node_type === 'neg_king';
              const isMatrixKing = matrixKing && Math.abs(s.strike - matrixKing.strike) < 0.01;
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
                    className={`row ${rowClass(s, spot)}${isKing ? ' king-row' : ''}${isNegKing ? ' neg-king-row' : ''}${isMatrixKing ? ' matrix-king-row' : ''}${s.node_type === 'gatekeeper' ? ' gatekeeper-row' : ''}`}
                    style={{
                      // neg-king-row class provides background via CSS (pink) — skip inline rowBackground override for it
                      backgroundColor: isNegKing ? undefined : rowBackground(s, spot),
                      ...(isMatrixKing ? {
                        boxShadow: 'inset 0 0 0 2px #f4c430',
                      } : {}),
                    }}
                    onMouseEnter={(e) => showTip(s, e)}
                    onMouseLeave={hideTip}
                  >
                    <span className="strike">
                      {isNegKing && (
                        <span
                          title="-GEX acceleration zone · whipsaw risk"
                          style={{ color: '#ff69b4', fontWeight: 800, marginRight: 3 }}
                        >◄</span>
                      )}
                      {fmtStrike(s.strike)}
                      {s.confluence && <span className="confl-icon"> ⚡</span>}
                      {s.net_vex !== 0 && (
                        <span className="vex-arrow" style={{ color: s.net_vex > 0 ? '#10dc9a' : '#ff5656' }}>
                          {s.net_vex > 0 ? '↑' : '↓'}
                        </span>
                      )}
                    </span>
                    <span className="gex">
                      {fmtBigPrecise(s.net_gex)}
                      {s.open_change_pct != null && (
                        <span
                          className={`change-badge change-badge--${s.open_change_pct >= 0 ? 'pos' : 'neg'}`}
                          title={`Change since 9:30 AM ET open: ${s.open_change_pct > 0 ? '+' : ''}${s.open_change_pct}%`}
                        >
                          {s.open_change_pct > 0 ? '+' : ''}{s.open_change_pct}%
                        </span>
                      )}
                      {isMatrixKing && (
                        <span
                          title="Matrix King — largest |GEX| across all visible expirations"
                          style={{
                            color: '#f4c430', fontWeight: 800, marginLeft: 6,
                            textShadow: '0 0 8px rgba(244,196,48,0.8)',
                          }}
                        >⭐</span>
                      )}
                      {isKing && <span className={`king-badge${isKing ? ' king-pulse' : ''}`}> ★ KING</span>}
                      {isNegKing && (
                        <span
                          className="neg-king-badge"
                          title="-GEX King · largest NEGATIVE gamma cluster · whipsaw / acceleration zone"
                        >◄ −KING</span>
                      )}
                      {s.node_type === 'gatekeeper' && <span style={{ color: '#a24dff' }}> ◆</span>}
                      {s.node_type === 'floor' && <span style={{ color: '#10dc9a' }}> ▬ FLOOR</span>}
                      {s.node_type === 'ceiling' && <span style={{ color: '#ff5656' }}> ▬ CEIL</span>}
                    </span>
                    <span className="vex">{fmtBigPrecise(s.net_vex)}</span>
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
              const isMatrixKing = matrixKing && Math.abs(s.strike - matrixKing.strike) < 0.01;
              const pct = maxIntensity
                ? (Math.abs(s.net_gex || 0) / maxIntensity) * 100
                : 0;
              let barColor;
              if (s.node_type === 'king') barColor = s.net_gex >= 0 ? '#f4c430' : '#a24dff';
              // Purple nodes for gatekeepers (top 6 by intensity)
              else if (s.node_type === 'gatekeeper') barColor = '#a24dff';
              else barColor = s.net_gex >= 0 ? '#1ca571' : '#d22d3c';
              let dotColor = barColor;
              if (s.is_air) dotColor = 'rgba(255,255,255,0.1)';

              // Magnetic strength: ratio of this strike's intensity to king
              const magStrength = s.ratio || 0;
              const magDir = s.strike > (spot || 0) ? 'pull-up' : 'pull-down';

              // VEX arrow: vanna direction indicator
              const vexArrow = s.net_vex > 0 ? '↑' : s.net_vex < 0 ? '↓' : '';
              const vexColor = s.net_vex > 0 ? '#10dc9a' : '#ff5656';

              return (
                <React.Fragment key={s.strike}>
                  {showSpotAbove && (
                    <div className="profile-row spot-row" style={{ padding: '3px 10px' }}>
                      <span className="strike text-mono" style={{ fontWeight: 800 }}>{fmtPrice(spot)} ◀</span>
                      <div />
                    </div>
                  )}
                  <div
                    className={`profile-row${s.node_type === 'king' ? ' king-row' : ''}${s.node_type === 'neg_king' ? ' neg-king-row' : ''}${isMatrixKing ? ' matrix-king-row' : ''}${s.node_type === 'gatekeeper' ? ' gatekeeper-row' : ''}`}
                    style={isMatrixKing ? { boxShadow: 'inset 0 0 0 2px #f4c430' } : undefined}
                    onMouseEnter={(e) => showTip(s, e)}
                    onMouseLeave={hideTip}
                  >
                    <span className="strike text-mono">
                      {s.node_type === 'neg_king' && (
                        <span
                          title="-GEX acceleration zone · whipsaw risk"
                          style={{ color: '#ff69b4', fontWeight: 800, marginRight: 3 }}
                        >◄</span>
                      )}
                      {fmtStrike(s.strike)}
                      {isMatrixKing && (
                        <span
                          title="Matrix King — largest |GEX| across all visible expirations"
                          style={{
                            color: '#f4c430', fontWeight: 800, marginLeft: 4,
                            textShadow: '0 0 8px rgba(244,196,48,0.8)',
                          }}
                        >⭐</span>
                      )}
                      <span className={`profile-dot${s.node_type === 'king' ? ' king-pulse' : ''}${s.node_type === 'neg_king' ? ' neg-king-pulse' : ''}`} style={{ background: dotColor }} />
                      {/* Per-strike VEX arrow */}
                      {vexArrow && <span className="vex-arrow" style={{ color: vexColor }}>{vexArrow}</span>}
                    </span>
                    <div className="profile-bar-track">
                      {/* Magnetic strength bar (background indicator) */}
                      {magStrength > 0.05 && (
                        <div className="mag-strength-bar" style={{
                          width: `${Math.min(100, magStrength * 100)}%`,
                          background: s.net_gex >= 0
                            ? 'rgba(28,165,113,0.08)'
                            : 'rgba(210,45,60,0.08)',
                        }} />
                      )}
                      <div
                        className="profile-bar-fill"
                        style={{ width: `${Math.max(1, pct)}%`, background: barColor }}
                      />
                      <span className="profile-val">
                        {fmtBigPrecise(s.net_gex)}
                        {s.open_change_pct != null && (
                          <span
                            className={`change-badge change-badge--${s.open_change_pct >= 0 ? 'pos' : 'neg'}`}
                            title={`Change since 9:30 AM ET open: ${s.open_change_pct > 0 ? '+' : ''}${s.open_change_pct}%`}
                          >
                            {s.open_change_pct > 0 ? '+' : ''}{s.open_change_pct}%
                          </span>
                        )}
                        {s.node_type === 'king' && <span className="king-badge"> ★ KING</span>}
                        {s.node_type === 'neg_king' && (
                          <span style={{
                            color: '#ff69b4',
                            fontWeight: 800,
                            marginLeft: 6,
                            padding: '1px 6px',
                            borderRadius: 3,
                            background: 'rgba(255,105,180,0.15)',
                          }}> ◄ −KING</span>
                        )}
                        {s.node_type === 'gatekeeper' && ' ◆'}
                        {s.node_type === 'floor' && ' ▬ FLOOR'}
                        {s.node_type === 'ceiling' && ' ▬ CEIL'}
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

// React.memo: only re-render when this panel's data actually changes
export default React.memo(HeatmapPanel);
