import { useCallback, useEffect, useReducer, useState } from "react";
import { motion } from "motion/react";
import { api } from "../api";
import { useWindowDrop } from "../dnd";
import { emptyFeed, feedReducer } from "../feed";
import { springs } from "../motion";
import type { EventMsg, ReplayState, Snapshot, View } from "../types";
import { useEvents } from "../useEvents";
import { useToasts } from "../useToasts";
import { useUploads } from "../useUploads";
import { DragOverlay } from "./DragOverlay";
import { Feed } from "./Feed";
import { Library } from "./Library";
import { NewSnapshot } from "./NewSnapshot";
import { SnapshotView } from "./SnapshotView";
import { Toasts } from "./Toasts";
import "./Main.css";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [feed, dispatchFeed] = useReducer(feedReducer, undefined, emptyFeed);
  const { toasts, push, dismiss } = useToasts();
  const uploads = useUploads();
  const dragging = useWindowDrop((files) => {
    setView({ kind: "new" });
    uploads.add(files);
  });

  const onEvent = useCallback(
    (event: EventMsg) => {
      if (event.type === "replay") {
        setReplay(event.running ? { running: true, port: event.port, snapshot_id: event.snapshot_id } : null);
        if (event.running) dispatchFeed({ type: "clear" });
      } else if (event.type === "toast") {
        push(event.level, event.message);
      } else {
        dispatchFeed({ type: "event", event });
      }
    },
    [push],
  );

  const onDisconnect = useCallback(() => {
    // A dropped socket may mean the library was locked elsewhere, or that events were missed.
    api
      .state()
      .then((state) => {
        if (state.vault !== "unlocked") onLocked();
        else setReplay(state.replay);
      })
      .catch(() => {});
  }, [onLocked]);

  const status = useEvents(true, { onEvent, onDisconnect });

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

  const updated = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => all.map((s) => (s.id === snapshot.id ? snapshot : s)));
  }, []);

  const start = useCallback(
    async (id: string, port: number) => {
      try {
        const result = await api.startReplay(id, port);
        setReplay({ running: true, port: result.port, snapshot_id: id });
      } catch (e) {
        push("error", messageOf(e));
      }
    },
    [push],
  );

  const stop = useCallback(async () => {
    try {
      await api.stopReplay();
      setReplay(null);
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const openBrowser = useCallback(async () => {
    try {
      await api.openBrowser();
      push("info", "Opened Firefox with the replay proxy");
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  const selected = view.kind === "snapshot" ? snapshots.find((s) => s.id === view.id) : undefined;

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
        <motion.div
          key={view.kind === "snapshot" ? view.id : "new"}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.screen}
        >
          {view.kind === "new" && <NewSnapshot uploads={uploads} onCreated={created} />}
          {selected && (
            <SnapshotView
              snapshot={selected}
              replay={replay}
              onStart={(port) => start(selected.id, port)}
              onStop={stop}
              onOpenBrowser={openBrowser}
              onUpdated={updated}
            />
          )}
        </motion.div>
      </section>
      <Feed
        state={feed}
        status={status}
        running={!!replay?.running}
        onCopied={(count) => push("info", `Copied ${count} missed URL${count === 1 ? "" : "s"}`)}
      />
      <DragOverlay visible={dragging} />
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
