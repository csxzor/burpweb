import { useState } from "react";
import { AnimatePresence } from "motion/react";
import { api } from "../api";
import { formatBytes, formatDate } from "../format";
import type { ReplayState, Snapshot } from "../types";
import { useUploads, type MakeUpload } from "../useUploads";
import { DropZone } from "./DropZone";
import { UploadChip } from "./UploadChip";
import "./NewSnapshot.css"; // shared stage layout
import "./SnapshotView.css";

interface Props {
  snapshot: Snapshot;
  replay: ReplayState | null;
  onStart: (port: number) => Promise<void>;
  onStop: () => Promise<void>;
  onOpenBrowser: () => Promise<void>;
  onUpdated: (snapshot: Snapshot) => void;
  makeUpload?: MakeUpload;
}

export function SnapshotView({ snapshot, replay, onStart, onStop, onOpenBrowser, onUpdated, makeUpload }: Props) {
  const [port, setPort] = useState("8081");
  const [busy, setBusy] = useState<"start" | "stop" | "browser" | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const uploads = useUploads(makeUpload);

  const portNumber = /^\d{1,5}$/.test(port) ? Number(port) : NaN;
  const portValid = portNumber >= 1 && portNumber <= 65535;
  const running = !!replay?.running && replay.snapshot_id === snapshot.id;
  const elsewhere = !!replay?.running && replay.snapshot_id !== snapshot.id;
  const { stats } = snapshot;

  async function run(kind: "start" | "stop" | "browser", action: () => Promise<void>) {
    if (busy) return;
    setBusy(kind);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  }

  async function addFiles() {
    if (adding || uploads.busy || uploads.doneIds.length === 0) return;
    setAdding(true);
    setAddError(null);
    try {
      const updated = await api.addFiles(snapshot.id, uploads.doneIds);
      uploads.clear();
      onUpdated(updated);
    } catch (e) {
      uploads.clear(); // the server discards staged uploads when it rejects a request
      setAddError(e instanceof Error ? e.message : "Could not add the files");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="stage-page">
      <header>
        <h1 className="stage-title">{snapshot.name}</h1>
        <p className="stage-sub">
          Created {formatDate(snapshot.created)} · {snapshot.files.length} file{snapshot.files.length === 1 ? "" : "s"}
        </p>
      </header>

      <section className="replay-panel" data-running={running} aria-label="Replay">
        {running ? (
          <>
            <div className="replay-status">
              <span className="live-dot" aria-hidden />
              <span>Replaying on 127.0.0.1:{replay?.port}</span>
            </div>
            <div className="replay-controls">
              <button className="primary" disabled={busy !== null} onClick={() => run("browser", onOpenBrowser)}>
                Open Firefox
              </button>
              <button className="danger" disabled={busy !== null} onClick={() => run("stop", onStop)}>
                Stop
              </button>
            </div>
          </>
        ) : (
          <>
            {snapshot.damaged && (
              <p className="field-error">This snapshot is damaged and can't be replayed. You can still delete it.</p>
            )}
            {elsewhere && <p className="hint">Another snapshot is replaying — starting this one will switch the replay.</p>}
            <div className="replay-controls">
              <label className="port-field">
                Replay port
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="Replay port"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={snapshot.damaged || !portValid || busy !== null}
                onClick={() => run("start", () => onStart(portNumber))}
              >
                {busy === "start" ? "Starting…" : "Start replay"}
              </button>
            </div>
          </>
        )}
      </section>

      <section className="tiles" aria-label="Snapshot statistics">
        <Tile value={stats.items} label="Items" />
        <Tile value={stats.origins} label="Origins" />
        <Tile value={stats.skipped} label="No response" />
        <Tile value={stats.malformed.length} label="Malformed" />
      </section>

      {stats.malformed.length > 0 && (
        <details className="malformed">
          <summary>
            {stats.malformed.length} malformed item{stats.malformed.length === 1 ? "" : "s"} skipped
          </summary>
          <ul>
            {stats.malformed.map(([index, reason]) => (
              <li key={index}>
                <span className="mono">#{index}</span> {reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {stats.by_origin && stats.by_origin.length > 0 && (
        <section>
          <h2 className="col-title section-title">Origins</h2>
          <table className="origins">
            <thead>
              <tr>
                <th>Items</th>
                <th>Paths</th>
                <th>Origin</th>
              </tr>
            </thead>
            <tbody>
              {stats.by_origin.map((row) => (
                <tr key={row.origin}>
                  <td className="mono">{row.items.toLocaleString("en-US")}</td>
                  <td className="mono">{row.paths.toLocaleString("en-US")}</td>
                  <td className="mono origin">{row.origin}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2 className="col-title section-title">Files</h2>
        <ol className="files">
          {snapshot.files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              <span className="order mono">{index + 1}</span>
              <span>{file.name}</span>
              <span className="muted mono">{formatBytes(file.size)}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="add-files" aria-label="Add files">
        <DropZone compact title="Add more files to this snapshot" hint="Later files override earlier ones" onFiles={uploads.add} />
        <ul className="chips" aria-label="Files to add">
          <AnimatePresence initial={false}>
            {uploads.items.map((item, index) => (
              <UploadChip key={item.id} item={item} index={index} onRemove={() => uploads.remove(item.id)} />
            ))}
          </AnimatePresence>
        </ul>
        {uploads.items.length > 0 && running && (
          <p className="hint">Restart the replay afterwards to use the new files.</p>
        )}
        {addError && (
          <p className="field-error" role="alert">
            {addError}
          </p>
        )}
        {uploads.items.length > 0 && (
          <div>
            <button
              className="primary"
              disabled={adding || uploads.busy || uploads.doneIds.length === 0}
              onClick={addFiles}
            >
              {adding ? "Adding…" : "Add to snapshot"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

function Tile({ value, label }: { value: number; label: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value.toLocaleString("en-US")}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
