import { useState } from "react";
import { motion } from "motion/react";
import { formatDate } from "../format";
import { springs } from "../motion";
import type { Snapshot } from "../types";

interface Props {
  snapshot: Snapshot;
  selected: boolean;
  live: boolean;
  onSelect: () => void;
  onRename: (name: string) => Promise<void>;
  onDelete: () => void;
}

export function SnapshotCard({ snapshot, selected, live, onSelect, onRename, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(snapshot.name);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const name = draft.trim();
    if (!name || name === snapshot.name) {
      setEditing(false);
      return;
    }
    try {
      await onRename(name);
      setError(null);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not rename");
    }
  }

  function startEditing() {
    setDraft(snapshot.name);
    setError(null);
    setEditing(true);
  }

  return (
    <motion.li
      layout
      className="card"
      data-selected={selected}
      aria-current={selected ? "true" : undefined}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springs.layout}
    >
      {editing ? (
        <div className="card-edit">
          <input
            type="text"
            aria-label="Snapshot name"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
              if (e.key === "Escape") setEditing(false);
            }}
          />
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : (
        <button className="card-main" onClick={onSelect}>
          <span className="card-name">
            {snapshot.name}
            {live && <span className="live-dot" role="img" aria-label="Replaying" />}
            {snapshot.damaged && <span className="badge-damaged">Damaged</span>}
          </span>
          {!snapshot.damaged && (
            <span className="card-meta mono">
              {snapshot.stats.items.toLocaleString("en-US")} items · {snapshot.stats.origins} origins ·{" "}
              {formatDate(snapshot.created)}
            </span>
          )}
        </button>
      )}
      {selected && !editing && (
        <div className="card-actions">
          {!snapshot.damaged && (
            <button className="ghost small" onClick={startEditing}>
              Rename
            </button>
          )}
          <button className="danger small ghost" onClick={onDelete}>
            Delete
          </button>
        </div>
      )}
    </motion.li>
  );
}
