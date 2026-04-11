import React, { useState } from 'react';
import { useStore } from '../store.js';

export default function WatchlistTabs() {
  const { watchlists, activeWL, setActiveWL, addWatchlist, removeWatchlist, updateWatchlist, editMode, setEditMode } = useStore();
  const [renaming, setRenaming] = useState(null);

  return (
    <div className="wl-tabs">
      {watchlists.map((wl) => (
        <div
          key={wl.id}
          className={`wl-tab ${activeWL === wl.id ? 'active' : ''}`}
          onClick={() => setActiveWL(wl.id)}
          onDoubleClick={() => setRenaming(wl.id)}
        >
          {renaming === wl.id ? (
            <input
              autoFocus
              defaultValue={wl.name}
              onBlur={(e) => {
                updateWatchlist(wl.id, { name: e.target.value || wl.name });
                setRenaming(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.target.blur();
                if (e.key === 'Escape') setRenaming(null);
              }}
              style={{ background: 'transparent', border: 0, color: 'inherit', width: 80 }}
            />
          ) : (
            wl.name
          )}
          {editMode && watchlists.length > 1 && (
            <span
              className="x"
              onClick={(e) => {
                e.stopPropagation();
                removeWatchlist(wl.id);
              }}
            >
              ✕
            </span>
          )}
        </div>
      ))}
      <button
        className="wl-tab"
        onClick={() => {
          const name = prompt('New watchlist name:', 'New List');
          if (name) addWatchlist(name);
        }}
      >
        + Add
      </button>
      <button
        className="wl-tab"
        onClick={() => setEditMode(!editMode)}
        title="Toggle edit mode"
      >
        {editMode ? '✓ Done' : '✎ Edit'}
      </button>
      <span style={{ color: 'var(--text-3)', fontSize: 11, marginLeft: 8 }}>
        double-click to rename
      </span>
    </div>
  );
}
