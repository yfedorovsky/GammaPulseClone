import React, { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store.js';
import { api } from '../api.js';
import HeatmapPanel, { findNearestMonthlyOpex } from '../components/HeatmapPanel.jsx';
import GexMatrix from '../components/GexMatrix.jsx';
import QuadChart from '../components/QuadChart.jsx';
import CollarStrip from '../components/CollarStrip.jsx';

export default function HeatmapsTab() {
  const {
    watchlists,
    activeWL,
    focus,
    panels,
    fpanels,
    viewMode,
    setViewMode,
    strikes: strikesWindow,
    setStrikes,
    setPanels,
    setFpanels,
    setFocus,
    setChains,
    chains,
    streamMode,
    focusTickerOverride,
    setFocusTickerOverride,
    exps,  // user's per-panel expiration picks (key: `${ticker}-${panelIdx}`)
  } = useStore();

  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];
  const multiTickers = wl.tickers.slice(0, panels);
  // FOCUS ticker resolution:
  //   1. User override (from the picker) — wins if set
  //   2. First ticker in active watchlist — legacy default
  //   3. SPY as last-resort fallback
  const focusTicker = (focusTickerOverride && focusTickerOverride.trim())
    || wl.tickers[0]
    || 'SPY';
  const focusPanelCount = Math.max(1, Math.min(5, fpanels));

  // Custom-ticker input state for the picker UI
  const [customInput, setCustomInput] = useState('');
  const [showCustom, setShowCustom] = useState(false);

  // Determine which tickers we actually need data for.
  // MATRIX view always needs the focus ticker's chain (its 2D grid is built
  // from that one ticker's per-expiration exp_data), regardless of MULTI/FOCUS.
  const neededTickers = useMemo(() => {
    if (viewMode === 'matrix' || viewMode === 'quad') return [focusTicker];
    return focus ? [focusTicker] : multiTickers;
  }, [viewMode, focus, focusTicker, multiTickers]);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await api.chains(neededTickers, strikesWindow);
        if (!alive) return;
        // Read the latest chains via getState to avoid stale closure
        const prev = useStore.getState().chains;
        setChains({ ...prev, ...data });
      } catch (e) {
        console.warn('chains load failed', e);
      }
    }
    load();
    // Chain data refreshes every 2 minutes — matches the upstream worker cycle.
    const iv = setInterval(load, 120_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neededTickers.join(','), strikesWindow]);

  const focusExps = useMemo(() => {
    const data = chains[focusTicker];
    return data?.exps || ['MACRO (ALL 200D)'];
  }, [chains, focusTicker]);

  /**
   * Matrix-wide "Heatseeker" King — the single largest-magnitude strike across
   * every visible FOCUS-mode expiration. Inspired by Skylit's ⭐ callout.
   * Returns { exp, strike, net_gex } or null if nothing to compare.
   *
   * IMPORTANT: MACRO (ALL 200D) is excluded from the comparison. MACRO is an
   * aggregated sum of all expirations, so its "largest cell" is almost always
   * the mathematical winner — which is meaningless. The whole point of the
   * Matrix King marker is to show WHICH SPECIFIC EXPIRATION hosts the
   * dominant dealer positioning. Skylit's example correctly marks a specific
   * weekly/monthly, never the aggregated view.
   */
  /**
   * Resolve what each panel is ACTUALLY displaying. User picks via the per-
   * panel exp dropdown persist in store.exps keyed by `${ticker}-${panelIdx}`.
   * If the user hasn't touched it, fall back to the default for that slot.
   */
  const visiblePanelExps = useMemo(() => {
    if (!focus) return [];
    // #73 (2026-06-18): when the focus name has a 0DTE expiration (indices like
    // SPY/QQQ/SPX), default panel 0 to it so the displayed king matches
    // GammaPulse Pro / OG, which key off the front (0DTE) expiration. Names
    // WITHOUT a 0DTE keep the nearest-monthly-OPEX default (king-selection-v3
    // fix #1 / task #10 — intraday-relevant dealer hedging for swing names).
    // ET "today" in YYYY-MM-DD (en-CA) to match the ISO exp keys.
    const etToday = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const realExps = focusExps.filter(e => !String(e).startsWith('MACRO'));
    const front0DTE = realExps[0] === etToday ? realExps[0] : null;
    return Array.from({ length: focusPanelCount }).map((_, i) => {
      const userPick = exps[`${focusTicker}-${i}`];
      const rawFallback = focusExps[Math.min(i, focusExps.length - 1)] || 'MACRO (ALL 200D)';
      // Panel 0 resolves to the MACRO sentinel by default — replace it with the
      // 0DTE expiration (if one exists) else nearest monthly OPEX, never MACRO.
      const fallback = String(rawFallback).startsWith('MACRO')
        ? (front0DTE || findNearestMonthlyOpex(focusExps) || rawFallback)
        : rawFallback;
      return userPick || fallback;
    });
  }, [focus, exps, focusTicker, focusExps, focusPanelCount]);

  const matrixKing = useMemo(() => {
    if (!focus) return null;
    const data = chains[focusTicker];
    if (!data?.exp_data) return null;

    // Exclude aggregated MACRO views from the comparison
    const comparableExps = visiblePanelExps.filter(e => !String(e).startsWith('MACRO'));
    if (comparableExps.length < 2) return null;

    let best = null;
    for (const exp of comparableExps) {
      const ed = data.exp_data[exp];
      if (!ed || !Array.isArray(ed.strikes)) continue;
      for (const s of ed.strikes) {
        const mag = Math.abs(s.net_gex || 0);
        if (best == null || mag > best.mag) {
          best = { exp, strike: s.strike, net_gex: s.net_gex, mag };
        }
      }
    }
    return best;
  }, [focus, chains, focusTicker, visiblePanelExps]);

  const streamLabel =
    streamMode === 'ws'
      ? '⚡ STREAMING'
      : streamMode === 'sse'
      ? '⚡ STREAMING (SSE)'
      : streamMode === 'poll'
      ? '⟳ POLLING'
      : '○ OFFLINE';
  const streamCls =
    streamMode === 'ws' || streamMode === 'sse'
      ? ''
      : streamMode === 'poll'
      ? 'poll'
      : 'offline';

  // Watchlist tickers offered in the FOCUS picker dropdown
  const watchlistTickers = wl.tickers || [];

  const applyCustomTicker = () => {
    const t = customInput.trim().toUpperCase();
    if (!t) return;
    setFocusTickerOverride(t);
    setShowCustom(false);
    setCustomInput('');
  };

  const isMatrix = viewMode === 'matrix';
  const isQuad = viewMode === 'quad';
  // Matrix/Quad view + FOCUS surface the single-ticker picker at the top.
  const showPicker = focus || isMatrix || isQuad;
  // JHEQX collar context strip — SPX only, single-ticker views (self-hides if
  // the collar can't be detected). #81.
  const showCollar = (focus || isMatrix || isQuad) && focusTicker === 'SPX';
  const gridRows = [showPicker && 'auto', showCollar && 'auto', '1fr']
    .filter(Boolean).join(' ');

  return (
    <div style={{ display: 'grid', gridTemplateRows: gridRows, height: '100%', minHeight: 0 }}>

      {/* FOCUS-mode / MATRIX-mode ticker picker */}
      {showPicker && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
          borderBottom: '1px solid var(--border-faint)',
          background: 'var(--bg-card)',
          fontSize: 11,
        }}>
          <span style={{
            fontSize: 9, fontWeight: 800, color: 'var(--text-3)',
            textTransform: 'uppercase', letterSpacing: 0.5,
          }}>
            Focus ticker
          </span>

          <select
            value={focusTicker}
            onChange={(e) => {
              if (e.target.value === '__custom__') {
                setShowCustom(true);
              } else {
                setShowCustom(false);
                setFocusTickerOverride(e.target.value);
              }
            }}
            style={{
              background: 'var(--bg-input, #1a1a20)',
              color: 'var(--text-1)',
              border: '1px solid var(--border-faint)',
              borderRadius: 'var(--radius-sm)',
              padding: '3px 8px', fontSize: 11, fontFamily: 'var(--mono)',
              fontWeight: 700, cursor: 'pointer', minWidth: 90,
            }}
          >
            {/* Keep the current focus ticker selectable even if not in watchlist */}
            {!watchlistTickers.includes(focusTicker) && (
              <option value={focusTicker}>{focusTicker} (custom)</option>
            )}
            {watchlistTickers.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
            <option value="__custom__">Custom…</option>
          </select>

          {showCustom && (
            <>
              <input
                autoFocus
                type="text"
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') applyCustomTicker();
                  if (e.key === 'Escape') { setShowCustom(false); setCustomInput(''); }
                }}
                placeholder="AAOI"
                maxLength={10}
                style={{
                  background: 'var(--bg-input, #1a1a20)',
                  color: '#f4c430',
                  border: '1px solid #f4c430',
                  borderRadius: 'var(--radius-sm)',
                  padding: '3px 8px', fontSize: 11, fontFamily: 'var(--mono)',
                  fontWeight: 800, width: 80, textTransform: 'uppercase',
                }}
              />
              <button
                onClick={applyCustomTicker}
                className="ctrl-btn"
                style={{ fontSize: 9, color: '#10dc9a' }}
              >
                APPLY
              </button>
              <button
                onClick={() => { setShowCustom(false); setCustomInput(''); }}
                className="ctrl-btn"
                style={{ fontSize: 9, color: 'var(--text-3)' }}
              >
                CANCEL
              </button>
            </>
          )}

          {focusTickerOverride && !showCustom && (
            <button
              onClick={() => setFocusTickerOverride(null)}
              className="ctrl-btn"
              style={{ fontSize: 9, color: 'var(--text-3)' }}
              title="Revert to first ticker in active watchlist"
            >
              ✕ CLEAR OVERRIDE
            </button>
          )}

          <span style={{ color: 'var(--text-3)', fontSize: 10, marginLeft: 'auto' }}>
            {isMatrix
              ? <>Matrix view · <b style={{ color: '#f4c430' }}>{focusTicker}</b> — strikes × expirations</>
              : focusTickerOverride
              ? <>Showing <b style={{ color: '#f4c430' }}>{focusTickerOverride}</b> across {focusPanelCount} expirations</>
              : <>Showing <b>{focusTicker}</b> (watchlist position 1)</>}
          </span>
        </div>
      )}

      {/* JHEQX collar structural-context strip (SPX only; self-hides). #81 */}
      {showCollar && <CollarStrip ticker="SPX" />}

      {/* Body: MATRIX view (per-expiration grid) takes precedence over the
         panel grids. It renders the focus ticker's full strike × expiration
         heatmap. Additive — BARS / PROFILE still drive the panel grids below. */}
      {isQuad ? (
        <QuadChart ticker={focusTicker} />
      ) : isMatrix ? (
        <GexMatrix ticker={focusTicker} />
      ) : focus ? (
        <div className={`panels cols-${focusPanelCount}`}>
          {Array.from({ length: focusPanelCount }).map((_, i) => {
            // expLabelOverride is just the DEFAULT for this panel slot —
            // HeatmapPanel's user-dropdown choice wins if set.
            // king-selection-v3 fix #1: same monthly-OPEX swap as
            // visiblePanelExps above. Panel slot 0 gets nearest 3rd-Friday
            // instead of the 200D aggregate.
            const _rawDefault = focusExps[Math.min(i, focusExps.length - 1)] || 'MACRO (ALL 200D)';
            const defaultExp = String(_rawDefault).startsWith('MACRO')
              ? (findNearestMonthlyOpex(focusExps) || _rawDefault)
              : _rawDefault;
            // Use visiblePanelExps (which already respects user overrides)
            // to decide which panel the matrix-king star should land on.
            const actualExp = visiblePanelExps[i] || defaultExp;
            const myMatrixKing = matrixKing && matrixKing.exp === actualExp ? matrixKing : null;
            return (
              <HeatmapPanel
                key={`focus-${focusTicker}-${i}`}
                ticker={focusTicker}
                panelIdx={i}
                expLabelOverride={defaultExp}
                matrixKing={myMatrixKing}
              />
            );
          })}
        </div>
      ) : (
        <div className={`panels cols-${panels}`}>
          {multiTickers.map((t, i) => (
            <HeatmapPanel key={`multi-${t}-${i}`} ticker={t} panelIdx={i} />
          ))}
        </div>
      )}
    </div>
  );
}
