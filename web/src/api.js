/**
 * HTTP client for the backend. In dev mode, /api/* requests are proxied to
 * http://localhost:8000 by Vite (see vite.config.js).
 */

const BASE = '';

async function json(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status}`);
  return r.json();
}

export const api = {
  health: () => json('GET', '/api/health'),
  chains: (tickers, strikes = 60) => json('POST', '/api/chains', { tickers, strikes }),
  confluence: () => json('GET', '/api/confluence'),
  quotes: (tickers) => json('POST', '/api/quotes', { tickers }),
  scanner: () => json('GET', '/api/scanner'),
  subscribe: (tickers) => json('POST', '/api/stream/subscribe', { tickers }),
  logSignal: (payload) => json('POST', '/api/signals/log', payload),
  history: (ticker, limit = 500) =>
    json('GET', `/api/history?ticker=${encodeURIComponent(ticker)}&limit=${limit}`),
  mtf: (ticker) => json('GET', `/api/mtf?ticker=${encodeURIComponent(ticker)}`),
  flowDetail: (ticker) => json('GET', `/api/flow/${encodeURIComponent(ticker)}`),
  flowScan: () => json('GET', '/api/flow/scan'),
  bars: (ticker, interval = '5min', days = 5) =>
    json('GET', `/api/bars/${encodeURIComponent(ticker)}?interval=${interval}&days=${days}`),
  tickers: () => json('GET', '/api/tickers'),
  addTickers: (tickers) => json('POST', '/api/tickers/add', { tickers }),
  removeTickers: (tickers) => json('POST', '/api/tickers/remove', { tickers }),
  earnings: (weekOffset = 0) => json('GET', `/api/earnings?week_offset=${weekOffset}`),
  alerts: (since = 0) => json('GET', `/api/alerts?since=${since}&limit=50`),
  signals: (limit = 50, status = '', grade = '') =>
    json('GET', `/api/signals?limit=${limit}${status ? '&status=' + status : ''}${grade ? '&grade=' + grade : ''}`),
  signalStats: () => json('GET', '/api/signals/stats'),
  news: (ticker) => json('GET', '/api/news/' + encodeURIComponent(ticker)),
  sectors: () => json('GET', '/api/sectors'),
  sectorDetail: (sector) => json('GET', `/api/sectors/${encodeURIComponent(sector)}`),
  breadth: () => json('GET', '/api/breadth'),
  rts: (direction = 'BULL', limit = 50) => json('GET', `/api/rts?direction=${direction}&limit=${limit}`),
  get: (url) => json('GET', url),
};

/**
 * Connect to the price stream. Tries WebSocket first (primary, tick-by-tick),
 * falls back to SSE if WebSocket fails to open, then finally to 5s polling
 * of /api/quotes if both are unavailable.
 *
 * Returns { close(), setTickers(list), getMode() }.
 */
export function connectPriceStream(onPrice, initialTickers = []) {
  let mode = 'ws';
  let ws = null;
  let es = null;
  let pollTimer = null;
  let tickers = [...initialTickers];
  let closed = false;

  function startPolling() {
    mode = 'poll';
    const tick = async () => {
      if (closed || !tickers.length) return;
      try {
        const data = await api.quotes(tickers);
        onPrice(data);
      } catch {
        /* ignore */
      }
    };
    tick();
    pollTimer = setInterval(tick, 5000);
  }

  function startSSE() {
    mode = 'sse';
    try {
      es = new EventSource('/api/stream/prices');
    } catch {
      startPolling();
      return;
    }
    let gotFirst = false;
    const fallbackTimer = setTimeout(() => {
      if (!gotFirst) {
        try { es?.close(); } catch {}
        es = null;
        startPolling();
      }
    }, 6000);
    es.onmessage = (ev) => {
      gotFirst = true;
      clearTimeout(fallbackTimer);
      try {
        onPrice(JSON.parse(ev.data));
      } catch {}
    };
    es.onerror = () => {
      /* EventSource auto-reconnects; if it keeps failing, fallbackTimer handles it */
    };
  }

  function startWS() {
    mode = 'ws';
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      ws = new WebSocket(`${proto}//${location.host}/ws/prices`);
    } catch {
      startSSE();
      return;
    }
    let openedOk = false;
    const openTimer = setTimeout(() => {
      if (!openedOk) {
        try { ws?.close(); } catch {}
        ws = null;
        startSSE();
      }
    }, 4000);
    ws.onopen = () => {
      openedOk = true;
      clearTimeout(openTimer);
      if (tickers.length) {
        try { ws.send(JSON.stringify({ subscribe: tickers })); } catch {}
      }
    };
    ws.onmessage = (ev) => {
      try {
        onPrice(JSON.parse(ev.data));
      } catch {}
    };
    ws.onerror = () => {};
    ws.onclose = () => {
      if (closed) return;
      // Fall through to SSE on unexpected close after successful open
      if (openedOk) {
        setTimeout(() => {
          if (!closed) startSSE();
        }, 500);
      }
    };
  }

  startWS();

  return {
    close() {
      closed = true;
      try { ws?.close(); } catch {}
      try { es?.close(); } catch {}
      if (pollTimer) clearInterval(pollTimer);
      ws = null;
      es = null;
      pollTimer = null;
    },
    setTickers(list) {
      tickers = [...list];
      if (mode === 'ws' && ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ subscribe: tickers })); } catch {}
      } else {
        // Polling path needs no special notification
        api.subscribe(tickers).catch(() => {});
      }
    },
    getMode: () => mode,
  };
}
