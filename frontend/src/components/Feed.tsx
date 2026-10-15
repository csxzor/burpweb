import { memo, useState } from "react";
import { motion } from "motion/react";
import { visibleRows, type FeedRow, type FeedState, type TierFilter } from "../feed";
import { splitUrl } from "../format";
import { springs } from "../motion";
import type { ConnectionStatus } from "../useEvents";
import "./Feed.css";

const FILTERS: TierFilter[] = ["ALL", "EXACT", "FALLBACK", "HEAD", "MISS", "BLOCKED"];

interface Props {
  state: FeedState;
  status: ConnectionStatus;
  running: boolean;
  onCopied?: (count: number) => void;
}

const FeedRowView = memo(function FeedRowView({ row }: { row: FeedRow }) {
  const { origin, rest } = splitUrl(row.url);
  return (
    <motion.li
      className="feed-row"
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={springs.feed}
    >
      <span className="badge" data-tier={row.tier}>
        {row.tier}
      </span>
      <span className="row-method mono">{row.method}</span>
      <span className="row-status mono">{row.status ?? ""}</span>
      <span className="row-item mono">{row.item ?? ""}</span>
      <span className="row-url mono" title={row.url}>
        <span className="row-origin">{origin}</span>
        {rest}
      </span>
    </motion.li>
  );
});

export function Feed({ state, status, running, onCopied }: Props) {
  const [tab, setTab] = useState<"live" | "misses">("live");
  const [filter, setFilter] = useState<TierFilter>("ALL");
  const rows = visibleRows(state.rows, filter);

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(state.misses.map((m) => m.key).join("\n"));
      onCopied?.(state.misses.length);
    } catch {
      // clipboard unavailable or denied: nothing to report
    }
  }

  return (
    <aside className="col feed" aria-label="Live feed">
      <header className="col-head">
        <div className="tabs" role="tablist">
          <button role="tab" className="tab" aria-selected={tab === "live"} onClick={() => setTab("live")}>
            Live
          </button>
          <button role="tab" className="tab" aria-selected={tab === "misses"} onClick={() => setTab("misses")}>
            Misses
            {state.misses.length > 0 && <span className="tab-count mono">{state.misses.length}</span>}
          </button>
        </div>
        {status === "reconnecting" && (
          <span className="pill" role="status">
            Reconnecting…
          </span>
        )}
      </header>

      {tab === "live" ? (
        <>
          <div className="filters">
            {FILTERS.map((name) => (
              <button
                key={name}
                className="filter"
                aria-pressed={filter === name}
                onClick={() => setFilter(name)}
              >
                {name} {state.counts[name]}
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="feed-empty">
              {state.counts.ALL > 0
                ? "No requests match this filter."
                : running
                  ? "Waiting for requests… browse the site through the proxy."
                  : "Start a replay to see requests here."}
            </p>
          ) : (
            <ul className="rows" aria-label="Requests">
              {rows.map((row) => (
                <FeedRowView key={row.id} row={row} />
              ))}
            </ul>
          )}
        </>
      ) : state.misses.length === 0 ? (
        <p className="feed-empty">No misses yet — everything so far came from the snapshot.</p>
      ) : (
        <>
          <div className="misses-head">
            <button className="ghost small" onClick={copyAll}>
              Copy all
            </button>
          </div>
          <ul className="rows" aria-label="Missed URLs">
            {state.misses.map((miss) => (
              <li key={miss.key} className="miss-row">
                <span className="miss-key mono" title={miss.key}>
                  {miss.key}
                </span>
                <span className="miss-count mono">{miss.count}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  );
}
