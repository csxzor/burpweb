import { useState } from "react";
import { AnimatePresence } from "motion/react";
import type { Snapshot, View } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import { SnapshotCard } from "./SnapshotCard";
import "./Library.css";

interface Props {
  snapshots: Snapshot[];
  view: View;
  replayingId: string | null;
  onSelect: (view: View) => void;
  onRename: (id: string, name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onLock: () => void;
}

export function Library({ snapshots, view, replayingId, onSelect, onRename, onDelete, onLock }: Props) {
  const [pendingDelete, setPendingDelete] = useState<Snapshot | null>(null);

  return (
    <aside className="col library" aria-label="Library">
      <header className="col-head">
        <span className="col-title">Library</span>
        <button className="ghost small" onClick={onLock}>
          Lock
        </button>
      </header>
      <button className="new-snapshot" data-active={view.kind === "new"} onClick={() => onSelect({ kind: "new" })}>
        + New snapshot
      </button>
      <ul className="cards">
        <AnimatePresence initial={false}>
          {snapshots.map((snapshot) => (
            <SnapshotCard
              key={snapshot.id}
              snapshot={snapshot}
              selected={view.kind === "snapshot" && view.id === snapshot.id}
              live={replayingId === snapshot.id}
              onSelect={() => onSelect({ kind: "snapshot", id: snapshot.id })}
              onRename={(name) => onRename(snapshot.id, name)}
              onDelete={() => setPendingDelete(snapshot)}
            />
          ))}
        </AnimatePresence>
      </ul>
      {snapshots.length === 0 && <p className="muted empty">No snapshots yet. Drop a Burp export to create one.</p>}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete snapshot?"
        body={`“${pendingDelete?.name ?? ""}” will be permanently removed from the encrypted library.`}
        confirmLabel="Delete"
        onCancel={() => setPendingDelete(null)}
        onConfirm={async () => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (target) await onDelete(target.id);
        }}
      />
    </aside>
  );
}
