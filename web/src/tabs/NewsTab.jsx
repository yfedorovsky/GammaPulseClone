import React, { useEffect, useState, useMemo, useRef } from 'react';
import { api } from '../api.js';

const SENTIMENTS = ['ALL', 'BULLISH', 'BEARISH', 'NEUTRAL'];
const CATEGORIES = ['ALL', 'Earnings', 'M&A', 'Company', 'General'];

const SENT_ICON = { BULLISH: '▲', BEARISH: '▼', NEUTRAL: '·' };
const SENT_COLOR = { BULLISH: '#10dc9a', BEARISH: '#ff5656', NEUTRAL: '#5a6478' };

const LS_KEY = 'gp_news_watchlist';
const DEFAULT_TICKERS = ['SPY', 'QQQ', 'AAPL', 'TSLA', 'NVDA'];

function timeAgo(unixTs) {
  if (!unixTs) return '';
  const diff = Math.floor(Date.now() / 1000) - unixTs;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function loadSavedTickers() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }
  } catch {}
  return DEFAULT_TICKERS;
}

function saveTickers(list) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(list)); } catch {}
}

export default function NewsTab() {
  const [watchlist, setWatchlist] = useState(loadSavedTickers);
  const [activeTicker, setActiveTicker] = useState(watchlist[0] || 'SPY');
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [unconfigured, setUnconfigured] = useState(false);

  const [searchInput, setSearchInput] = useState('');
  const [sentFilter, setSentFilter] = useState('ALL');
  const [catFilter, setCatFilter] = useState('ALL');

  const searchRef = useRef(null);

  // Persist watchlist
  useEffect(() => { saveTickers(watchlist); }, [watchlist]);

  // Load news when active ticker changes
  useEffect(() => {
    if (!activeTicker) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setUnconfigured(false);
    api.news(activeTicker)
      .then((data) => {
        if (!alive) return;
        if (data.error) {
          setUnconfigured(true);
          setArticles([]);
        } else {
          setArticles(data.articles || []);
        }
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [activeTicker]);

  // Derived: filtered articles
  const filtered = useMemo(() => {
    let list = articles;
    if (sentFilter !== 'ALL') list = list.filter((a) => a.sentiment === sentFilter);
    if (catFilter !== 'ALL') {
      const lc = catFilter.toLowerCase();
      list = list.filter((a) => (a.category || '').toLowerCase().includes(lc));
    }
    return list;
  }, [articles, sentFilter, catFilter]);

  // Sentiment counts
  const counts = useMemo(() => {
    const c = { ALL: articles.length, BULLISH: 0, BEARISH: 0, NEUTRAL: 0 };
    for (const a of articles) {
      if (a.sentiment === 'BULLISH') c.BULLISH++;
      else if (a.sentiment === 'BEARISH') c.BEARISH++;
      else c.NEUTRAL++;
    }
    return c;
  }, [articles]);

  function handleSearchKey(e) {
    if (e.key === 'Enter') {
      const sym = searchInput.trim().toUpperCase();
      if (!sym) return;
      if (!watchlist.includes(sym)) {
        const next = [...watchlist, sym];
        setWatchlist(next);
      }
      setActiveTicker(sym);
      setSearchInput('');
    }
  }

  function removeTicker(sym) {
    const next = watchlist.filter((t) => t !== sym);
    setWatchlist(next.length ? next : DEFAULT_TICKERS);
    if (activeTicker === sym) setActiveTicker(next[0] || 'SPY');
  }

  return (
    <div className="news-layout">
      {/* Sidebar */}
      <aside className="news-sidebar">
        <div className="news-sidebar-search">
          <input
            ref={searchRef}
            className="ctrl-input"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
            onKeyDown={handleSearchKey}
            placeholder="Add ticker..."
            style={{ width: '100%', fontSize: 12 }}
          />
        </div>
        <div className="news-ticker-list">
          {watchlist.map((sym) => (
            <div
              key={sym}
              className={`news-ticker-row${activeTicker === sym ? ' active' : ''}`}
              onClick={() => setActiveTicker(sym)}
            >
              <span className="news-ticker-sym">{sym}</span>
              <button
                className="news-ticker-remove"
                onClick={(e) => { e.stopPropagation(); removeTicker(sym); }}
                title="Remove"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Main area */}
      <div className="news-main">
        {/* Controls */}
        <div className="ctrl-bar" style={{ gap: 10, flexWrap: 'wrap' }}>
          <strong style={{ fontSize: 15, color: 'var(--accent)' }}>{activeTicker}</strong>
          <span style={{ color: 'var(--text-3)', fontSize: 12 }}>News</span>
          <div style={{ flex: 1 }} />
          {/* Category filter */}
          {CATEGORIES.map((c) => (
            <button
              key={c}
              className={`ctrl-btn${catFilter === c ? ' active' : ''}`}
              onClick={() => setCatFilter(c)}
              style={{ fontSize: 11 }}
            >
              {c}
            </button>
          ))}
          {loading && <span className="mini text-dim">Loading...</span>}
        </div>

        {/* Sentiment pills */}
        <div className="news-sent-bar">
          {SENTIMENTS.map((s) => (
            <button
              key={s}
              className={`ctrl-btn${sentFilter === s ? ' active' : ''}`}
              onClick={() => setSentFilter(s)}
              style={{
                background: sentFilter === s
                  ? s === 'BULLISH' ? 'rgba(16,220,154,0.15)'
                  : s === 'BEARISH' ? 'rgba(255,86,86,0.15)'
                  : 'rgba(255,255,255,0.08)'
                  : undefined,
                color: s === 'BULLISH' ? '#10dc9a' : s === 'BEARISH' ? '#ff5656' : undefined,
              }}
            >
              {s === 'BULLISH' ? '▲ ' : s === 'BEARISH' ? '▼ ' : s === 'NEUTRAL' ? '· ' : ''}
              {s} <span style={{ opacity: 0.6 }}>({counts[s] ?? 0})</span>
            </button>
          ))}
        </div>

        {/* Article cards */}
        <div className="news-cards-area">
          {unconfigured && (
            <div className="news-config-msg">
              <div className="news-config-icon">📰</div>
              <div className="news-config-title">Finnhub API Key Not Configured</div>
              <div className="news-config-body">
                Add <code>FINNHUB_API_KEY=your_key_here</code> to your <code>.env</code> file and
                restart the server. Free keys are available at{' '}
                <a href="https://finnhub.io" target="_blank" rel="noreferrer">finnhub.io</a>.
              </div>
            </div>
          )}

          {error && !unconfigured && (
            <div style={{ padding: 24, color: 'var(--danger)', textAlign: 'center' }}>
              Error: {error}
            </div>
          )}

          {!unconfigured && !error && !loading && filtered.length === 0 && (
            <div style={{ padding: 40, color: 'var(--text-3)', textAlign: 'center' }}>
              No news found for <strong>{activeTicker}</strong>
              {sentFilter !== 'ALL' ? ` with ${sentFilter} sentiment` : ''}.
            </div>
          )}

          {filtered.map((article) => (
            <a
              key={article.id ?? article.url}
              href={article.url}
              target="_blank"
              rel="noreferrer"
              className="news-card"
            >
              {article.image && (
                <div className="news-card-img">
                  <img src={article.image} alt="" loading="lazy" />
                </div>
              )}
              <div className="news-card-body">
                <div className="news-card-meta">
                  <span className="news-source">{article.source}</span>
                  <span className="news-time">{timeAgo(article.datetime)}</span>
                  {article.category && (
                    <span className="news-cat">{article.category}</span>
                  )}
                  <span
                    className="news-sent-tag"
                    style={{ color: SENT_COLOR[article.sentiment] }}
                  >
                    {SENT_ICON[article.sentiment]} {article.sentiment}
                  </span>
                </div>
                <div className="news-headline">{article.headline}</div>
                {article.summary && (
                  <div className="news-summary">{article.summary}</div>
                )}
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
