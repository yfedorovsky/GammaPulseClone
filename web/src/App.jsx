import React, { useEffect } from 'react';
import { useStore } from './store.js';
import { api, connectPriceStream } from './api.js';

import Header from './components/Header.jsx';
import ConfluenceBanner from './components/ConfluenceBanner.jsx';
import WatchlistTabs from './components/WatchlistTabs.jsx';
import LegendStrip from './components/LegendStrip.jsx';

import HeatmapsTab from './tabs/HeatmapsTab.jsx';
import OverlayTab from './tabs/OverlayTab.jsx';
import ScannerTab from './tabs/ScannerTab.jsx';
import FlowTab from './tabs/FlowTab.jsx';
import SignalsTab from './tabs/SignalsTab.jsx';
import SectorsTab from './tabs/SectorsTab.jsx';
import HistoryTab from './tabs/HistoryTab.jsx';
import MtfTab from './tabs/MtfTab.jsx';
import EarningsTab from './tabs/EarningsTab.jsx';
import NewsTab from './tabs/NewsTab.jsx';
import GuideTab from './tabs/GuideTab.jsx';

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
        {tab === 'HEATMAPS' && <HeatmapsTab />}
        {tab === 'OVERLAY' && <OverlayTab />}
        {tab === 'SCANNER' && <ScannerTab />}
        {tab === 'FLOW' && <FlowTab />}
        {tab === 'SIGNALS' && <SignalsTab />}
        {tab === 'SECTORS' && <SectorsTab />}
        {tab === 'HISTORY' && <HistoryTab />}
        {tab === 'MTF' && <MtfTab />}
        {tab === 'EARNINGS' && <EarningsTab />}
        {tab === 'NEWS' && <NewsTab />}
        {tab === 'GUIDE' && <GuideTab />}
      </div>
    </div>
  );
}
