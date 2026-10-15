import { motion } from "motion/react";
import { formatBytes } from "../format";
import { springs } from "../motion";
import type { UploadItem } from "../useUploads";
import "./UploadChip.css";

interface Props {
  item: UploadItem;
  index: number;
  onRemove: () => void;
}

export function UploadChip({ item, index, onRemove }: Props) {
  const percent = item.size ? Math.min(100, (item.loaded / item.size) * 100) : 0;
  return (
    <motion.li
      layout
      className="chip"
      data-status={item.status}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springs.layout}
    >
      <span className="chip-order mono">{index + 1}</span>
      <div className="chip-body">
        <div className="chip-line">
          <span className="chip-name">{item.name}</span>
          <span className="chip-size mono">{formatBytes(item.size)}</span>
        </div>
        {item.status === "error" ? (
          <span className="chip-error" role="alert">
            {item.error}
          </span>
        ) : (
          <div
            className="chip-track"
            role="progressbar"
            aria-label={`Upload progress for ${item.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percent)}
          >
            <motion.div className="chip-bar" animate={{ width: `${percent}%` }} transition={springs.bar} />
          </div>
        )}
      </div>
      <span className="chip-state" aria-hidden>
        {item.status === "done" ? "✓" : item.status === "error" ? "!" : ""}
      </span>
      <button className="chip-remove" aria-label={`Remove ${item.name}`} onClick={onRemove}>
        ×
      </button>
    </motion.li>
  );
}
