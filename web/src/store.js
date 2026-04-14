import { create } from 'zustand';

const LS = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      if (v == null) return fallback;
      return JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* ignore */
    }
  },
};

const defaultWatchlist = [
  { id: 'default', name: 'Main', tickers: [
    'SPY', 'QQQ', 'IWM', 'NVDA', 'AAPL', 'MSFT', 'AMD', 'TSLA', 'META', 'AMZN', 'GOOGL',
    'MU', 'LRCX', 'AMAT', 'KLAC', 'SMH', 'AVGO', 'ARM',
    'AAOI', 'COHR', 'LITE', 'CIEN', 'GLW', 'AXTI',
    'AEHR', 'TER', 'VRT', 'ANET',
    'ASTS', 'RKLB', 'NBIS', 'OKLO', 'IREN',
    'PLTR', 'COIN', 'IBIT',
  ] },
];

export const useStore = create((set, get) => ({
  // Navigation
  tab: 'HEATMAPS',
  setTab: (tab) => set({ tab }),

  // View / mode
  viewMode: LS.get('gp_viewMode', 'bars'), // bars | profile
  setViewMode: (viewMode) => {
    LS.set('gp_viewMode', viewMode);
    set({ viewMode });
  },
  focus: LS.get('gp_focus', 0), // 0 multi, 1 focus
  setFocus: (focus) => {
    LS.set('gp_focus', focus);
    set({ focus });
  },
  panels: LS.get('gp_panels', 3),
  setPanels: (panels) => {
    LS.set('gp_panels', panels);
    set({ panels });
  },
  fpanels: LS.get('gp_fpanels', 3),
  setFpanels: (fpanels) => {
    LS.set('gp_fpanels', fpanels);
    set({ fpanels });
  },
  strikes: LS.get('gp_strikes', 60),
  setStrikes: (strikes) => {
    LS.set('gp_strikes', strikes);
    set({ strikes });
  },
  zoom: LS.get('gp_zoom', 100),
  setZoom: (zoom) => {
    LS.set('gp_zoom', zoom);
    set({ zoom });
  },

  // Watchlists
  watchlists: LS.get('gp_watchlists', defaultWatchlist),
  activeWL: LS.get('gp_activeWL', 'default'),
  setActiveWL: (activeWL) => {
    LS.set('gp_activeWL', activeWL);
    set({ activeWL });
  },
  updateWatchlist: (id, patch) => {
    const wls = get().watchlists.map((w) => (w.id === id ? { ...w, ...patch } : w));
    LS.set('gp_watchlists', wls);
    set({ watchlists: wls });
  },
  addWatchlist: (name) => {
    const id = 'wl_' + Math.random().toString(36).slice(2, 8);
    const wls = [...get().watchlists, { id, name, tickers: ['SPY'] }];
    LS.set('gp_watchlists', wls);
    set({ watchlists: wls, activeWL: id });
    LS.set('gp_activeWL', id);
  },
  removeWatchlist: (id) => {
    let wls = get().watchlists.filter((w) => w.id !== id);
    if (!wls.length) wls = defaultWatchlist;
    LS.set('gp_watchlists', wls);
    const newActive = wls[0].id;
    LS.set('gp_activeWL', newActive);
    set({ watchlists: wls, activeWL: newActive });
  },

  // Selected expirations per panel (key: `${ticker}-${idx}`)
  exps: LS.get('gp_exps', {}),
  setExp: (key, exp) => {
    const exps = { ...get().exps, [key]: exp };
    LS.set('gp_exps', exps);
    set({ exps });
  },

  // Live data
  chains: {}, // { ticker: tickerData }
  setChains: (chains) => set({ chains }),
  spotPrices: {}, // { ticker: lastPrice }
  prevSpotPrices: {},
  setSpot: (ticker, price) => {
    const state = get();
    const prev = { ...state.prevSpotPrices };
    prev[ticker] = state.spotPrices[ticker] ?? price;
    set({
      prevSpotPrices: prev,
      spotPrices: { ...state.spotPrices, [ticker]: price },
    });
  },
  bulkSetSpots: (obj) => {
    const state = get();
    const prev = { ...state.prevSpotPrices };
    for (const t of Object.keys(obj)) {
      prev[t] = state.spotPrices[t] ?? obj[t];
    }
    set({ prevSpotPrices: prev, spotPrices: { ...state.spotPrices, ...obj } });
  },

  // Confluence + health
  confluence: null,
  setConfluence: (c) => set({ confluence: c }),
  health: null,
  setHealth: (h) => set({ health: h }),

  // Scanner
  scanner: null,
  setScanner: (s) => set({ scanner: s }),

  // Edit mode (for ticker / wl drag-to-reorder)
  editMode: false,
  setEditMode: (v) => set({ editMode: v }),

  // 0DTE mode: when on, all panels switch to today's expiration
  zeroDte: false,
  setZeroDte: (v) => set({ zeroDte: v }),

  // Streaming transport mode: 'ws' | 'sse' | 'poll' | 'offline'
  streamMode: 'offline',
  setStreamMode: (streamMode) => set({ streamMode }),

  // Earnings data for badge display
  earningsThisWeek: {}, // { ticker: { date, timing } }
  setEarningsThisWeek: (e) => set({ earningsThisWeek: e }),

  // Selected scanner row (for MTF side panel)
  selectedRow: null,
  setSelectedRow: (r) => set({ selectedRow: r }),
}));

export function activeWatchlist() {
  const { watchlists, activeWL } = useStore.getState();
  return watchlists.find((w) => w.id === activeWL) || watchlists[0];
}
