import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWindowDrop } from "../dnd";
import type { ReplayState, Snapshot, View } from "../types";
import { useUploads } from "../useUploads";
import { DragOverlay } from "./DragOverlay";
import { Library } from "./Library";
import { NewSnapshot } from "./NewSnapshot";
import "./Main.css";

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const uploads = useUploads();
  const dragging = useWindowDrop((files) => {
    setView({ kind: "new" });
    uploads.add(files);
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.snapshots(), api.state()])
      .then(([list, state]) => {
        if (cancelled) return;
        setSnapshots(list);
        setReplay(state.replay);
        const open = state.replay?.snapshot_id ?? list.at(-1)?.id;
        if (open) setView({ kind: "snapshot", id: open });
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    const updated = await api.rename(id, name);
    setSnapshots((all) => all.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.remove(id);
    setSnapshots((all) => all.filter((s) => s.id !== id));
    setView((v) => (v.kind === "snapshot" && v.id === id ? { kind: "new" } : v));
    setReplay((r) => (r?.snapshot_id === id ? null : r));
  }, []);

  const created = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => [...all, snapshot]);
    setView({ kind: "snapshot", id: snapshot.id });
  }, []);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  return (
    <div className="main-grid">
      <Library
        snapshots={snapshots}
        view={view}
        replayingId={replay?.snapshot_id ?? null}
        onSelect={setView}
        onRename={rename}
        onDelete={remove}
        onLock={lock}
      />
      <section className="col stage" aria-label="Stage">
        {loadError && (
          <p className="field-error" role="alert">
            Couldn't load the library: {loadError}
          </p>
        )}
        {view.kind === "new" && <NewSnapshot uploads={uploads} onCreated={created} />}
      </section>
      <aside className="col feed" aria-label="Live feed" />
      <DragOverlay visible={dragging} />
    </div>
  );
}
