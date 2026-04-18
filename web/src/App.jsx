import React, { useEffect, lazy, Suspense } from 'react';
import { useStore } from './store.js';
import { api, connectPriceStream } from './api.js';

import Header from './components/Header.jsx';
import ConfluenceBanner from './components/ConfluenceBanner.jsx';
import WatchlistTabs from './components/WatchlistTabs.jsx';
import LegendStrip from './components/LegendStrip.jsx';

// Eager: default tab loads immediately
import HeatmapsTab from './tabs/HeatmapsTab.jsx';
// Lazy: other tabs load on first visit (instant tab switching feel)
const OverlayTab = lazy(() => import('./tabs/OverlayTab.jsx'));
const ScannerTab = lazy(() => import('./tabs/ScannerTab.jsx'));
const FlowTab = lazy(() => import('./tabs/FlowTab.jsx'));
const SignalsTab = lazy(() => import('./tabs/SignalsTab.jsx'));
const SectorsTab = lazy(() => import('./tabs/SectorsTab.jsx'));
const HistoryTab = lazy(() => import('./tabs/HistoryTab.jsx'));
const MtfTab = lazy(() => import('./tabs/MtfTab.jsx'));
const EarningsTab = lazy(() => import('./tabs/EarningsTab.jsx'));
const NewsTab = lazy(() => import('./tabs/NewsTab.jsx'));
const PortfolioTab = lazy(() => import('./tabs/PortfolioTab.jsx'));
const SwingsTab = lazy(() => import('./tabs/SwingsTab.jsx'));
const SweepsTab = lazy(() => import('./tabs/SweepsTab.jsx'));
const BigFlowTab = lazy(() => import('./tabs/BigFlowTab.jsx'));
const GuideTab = lazy(() => import('./tabs/GuideTab.jsx'));

export default function App() {
  const {
    tab,
    zoom,
    watchlists,
    activeWL,
    setHealth,
    setConfluence,
    bulkSetSpots,
    setStreamMode,
    setEarningsThisWeek,
  } = useStore();

  const streamRef = React.useRef(null);

  const wl = watchlists.find((w) => w.id === activeWL) || watchlists[0];

  // Health poll
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const h = await api.health();
        if (alive) setHealth(h);
      } catch {}
    }
    load();
    const iv = setInterval(load, 15_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [setHealth]);

  // Confluence poll (every 2 minutes)
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const c = await api.confluence();
        if (alive) setConfluence(c);
      } catch {}
    }
    load();
    const iv = setInterval(load, 120_000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [setConfluence]);

  // Earnings fetch (once on load for badge display)
  useEffect(() => {
    async function loadEarnings() {
      try {
        const data = await api.earnings(0);
        const map = {};
        for (const day of data.days || []) {
          for (const t of day.tickers || []) {
            const ticker = typeof t === 'string' ? t : t.ticker;
            if (ticker) map[ticker] = { date: day.date, timing: t.timing || '' };
          }
        }
        setEarningsThisWeek(map);
      } catch {}
    }
    loadEarnings();
  }, [setEarningsThisWeek]);

  // Price stream — WebSocket first, SSE second, polling last
  useEffect(() => {
    const h = connectPriceStream(
      (prices) => {
        bulkSetSpots(prices);
        // Sync mode on first successful message
        const mode = h.getMode();
        if (mode !== useStore.getState().streamMode) setStreamMode(mode);
      },
      wl?.tickers || [],
    );
    streamRef.current = h;
    // Mode may shift during fallback chain; poll briefly to pick it up
    const modeTimer = setInterval(() => {
      const m = h.getMode();
      if (m !== useStore.getState().streamMode) setStreamMode(m);
    }, 2000);
    return () => {
      clearInterval(modeTimer);
      h.close();
      streamRef.current = null;
      setStreamMode('offline');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update subscription set when the active watchlist tickers change
  useEffect(() => {
    if (!wl?.tickers?.length) return;
    api.subscribe(wl.tickers).catch(() => {});
    streamRef.current?.setTickers(wl.tickers);
  }, [wl?.tickers?.join(',')]);

  return (
    <div className="app" style={{ fontSize: `${zoom}%` }}>
      <Header />
      {tab === 'HEATMAPS' && <LegendStrip />}
      {tab === 'HEATMAPS' && <ConfluenceBanner />}
      {tab === 'HEATMAPS' && <WatchlistTabs />}
      {tab === 'OVERLAY' && <WatchlistTabs />}
      <div className="app-body">
        <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-3)' }}>Loading...</div>}>
          {tab === 'HEATMAPS' && <HeatmapsTab />}
          {tab === 'OVERLAY' && <OverlayTab />}
          {tab === 'SCANNER' && <ScannerTab />}
          {tab === 'SWINGS' && <SwingsTab />}
          {tab === 'FLOW' && <FlowTab />}
          {tab === 'SWEEPS' && <SweepsTab />}
          {tab === 'BIGFLOW' && <BigFlowTab />}
          {tab === 'SIGNALS' && <SignalsTab />}
          {tab === 'PORTFOLIO' && <PortfolioTab />}
          {tab === 'SECTORS' && <SectorsTab />}
          {tab === 'HISTORY' && <HistoryTab />}
          {tab === 'MTF' && <MtfTab />}
          {tab === 'EARNINGS' && <EarningsTab />}
          {tab === 'NEWS' && <NewsTab />}
          {tab === 'GUIDE' && <GuideTab />}
        </Suspense>
      </div>
    </div>
  );
}
