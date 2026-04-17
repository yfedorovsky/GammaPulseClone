import React, { useEffect, useMemo } from 'react';
import { useStore } from '../store.js';
import { api } from '../api.js';
import HeatmapPanel from '../components/HeatmapPanel.jsx';

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
  } = useStore();

  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];
  const multiTickers = wl.tickers.slice(0, panels);
  const focusTicker = wl.tickers[0] || 'SPY';
  const focusPanelCount = Math.max(1, Math.min(5, fpanels));

  // Determine which tickers we actually need data for
  const neededTickers = useMemo(() => {
    return focus ? [focusTicker] : multiTickers;
  }, [focus, focusTicker, multiTickers]);

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
   * Applies only in FOCUS mode and only when multiple expirations are shown
   * (otherwise the per-expiration King already IS the matrix king).
   */
  const matrixKing = useMemo(() => {
    if (!focus) return null;
    const data = chains[focusTicker];
    if (!data?.exp_data) return null;
    const visibleExps = Array.from({ length: focusPanelCount }).map(
      (_, i) => focusExps[Math.min(i, focusExps.length - 1)] || 'MACRO (ALL 200D)'
    );
    if (visibleExps.length < 2) return null;

    let best = null;
    for (const exp of visibleExps) {
      const ed = data.exp_data[exp];
      if (!ed || !Array.isArray(ed.strikes)) continue;
      // Scan all strikes in this expiration for the largest |net_gex|
      for (const s of ed.strikes) {
        const mag = Math.abs(s.net_gex || 0);
        if (best == null || mag > best.mag) {
          best = { exp, strike: s.strike, net_gex: s.net_gex, mag };
        }
      }
    }
    return best;
  }, [focus, chains, focusTicker, focusExps, focusPanelCount]);

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

  return (
    <div style={{ display: 'grid', gridTemplateRows: '1fr', height: '100%', minHeight: 0 }}>

      {/* Panels grid */}
      {focus ? (
        <div className={`panels cols-${focusPanelCount}`}>
          {Array.from({ length: focusPanelCount }).map((_, i) => {
            const exp = focusExps[Math.min(i, focusExps.length - 1)] || 'MACRO (ALL 200D)';
            // Only pass matrixKing to the panel that actually owns the winning
            // cell — other panels get null so they render normal King styling.
            const myMatrixKing = matrixKing && matrixKing.exp === exp ? matrixKing : null;
            return (
              <HeatmapPanel
                key={`focus-${focusTicker}-${i}`}
                ticker={focusTicker}
                panelIdx={i}
                expLabelOverride={exp}
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
