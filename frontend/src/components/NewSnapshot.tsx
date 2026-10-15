import { useEffect, useRef, useState } from "react";
import { AnimatePresence } from "motion/react";
import { api } from "../api";
import type { Snapshot } from "../types";
import type { useUploads } from "../useUploads";
import { DropZone } from "./DropZone";
import { UploadChip } from "./UploadChip";
import "./NewSnapshot.css";

type Uploads = ReturnType<typeof useUploads>;

interface Props {
  uploads: Uploads;
  onCreated: (snapshot: Snapshot) => void;
}

export function NewSnapshot({ uploads, onCreated }: Props) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const touched = useRef(false);

  const firstName = uploads.items[0]?.name;
  useEffect(() => {
    if (!touched.current) setName(firstName ? firstName.replace(/\.[^.]+$/, "") : "");
  }, [firstName]);

  const canCreate = !creating && !uploads.busy && uploads.doneIds.length > 0 && name.trim() !== "";

  async function create() {
    if (!canCreate) return;
    setCreating(true);
    setError(null);
    try {
      const snapshot = await api.createSnapshot(name.trim(), uploads.doneIds);
      uploads.clear();
      onCreated(snapshot);
    } catch (e) {
      // The server discards every staged upload when it rejects a request, so the chips are stale.
      uploads.clear();
      setError(e instanceof Error ? e.message : "Could not create the snapshot");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="stage-page">
      <header>
        <h1 className="stage-title">New snapshot</h1>
        <p className="stage-sub">
          Drop the Burp XML exports from Proxy → HTTP history → Save items. Keep “Base64-encode requests and
          responses” ticked.
        </p>
      </header>

      <DropZone
        title="Drop Burp XML exports or click to browse"
        hint="You can add several files — frontend captures, later sessions."
        compact={uploads.items.length > 0}
        onFiles={uploads.add}
      />

      <ul className="chips" aria-label="Files to import">
        <AnimatePresence initial={false}>
          {uploads.items.map((item, index) => (
            <UploadChip key={item.id} item={item} index={index} onRemove={() => uploads.remove(item.id)} />
          ))}
        </AnimatePresence>
      </ul>
      {uploads.items.length > 1 && (
        <p className="hint">Order matters: later files override earlier ones for identical requests.</p>
      )}

      <label className="field">
        Snapshot name
        <input
          type="text"
          value={name}
          placeholder="e.g. Treasury portal, Oct 2026"
          onChange={(e) => {
            touched.current = true;
            setName(e.target.value);
          }}
        />
      </label>

      {error && (
        <div>
          <p className="field-error" role="alert">
            {error}
          </p>
          <p className="hint">The uploads were discarded; add the files again.</p>
        </div>
      )}

      <div className="create-row">
        <button className="primary" disabled={!canCreate} onClick={create} aria-busy={creating}>
          {creating ? "Validating…" : "Create snapshot"}
        </button>
        {creating && <div className="validating-bar" aria-hidden />}
      </div>
    </div>
  );
}
