import { useRef, useState } from "react";
import { motion } from "motion/react";
import { hasFiles } from "../dnd";
import { springs } from "../motion";
import "./DropZone.css";

interface Props {
  title: string;
  hint?: string;
  compact?: boolean;
  onFiles: (files: File[]) => void;
}

export function DropZone({ title, hint, compact, onFiles }: Props) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const report = (list: FileList | null) => {
    if (list && list.length > 0) onFiles(Array.from(list));
  };

  return (
    <motion.div
      className="dropzone"
      data-compact={compact || undefined}
      data-over={over || undefined}
      role="button"
      tabIndex={0}
      aria-label={title}
      animate={{ scale: over ? 1.015 : 1 }}
      transition={springs.drop}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragEnter={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => {
        if (hasFiles(e.dataTransfer)) e.preventDefault();
      }}
      onDragLeave={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      }}
      onDrop={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        e.preventDefault(); // the window-level handler sees this and does not deliver the files twice
        depth.current = 0;
        setOver(false);
        report(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          report(e.target.files);
          e.target.value = "";
        }}
      />
      <span className="dropzone-icon" aria-hidden>
        ⬆
      </span>
      <span className="dropzone-title">{compact ? "Add more files" : "Drop Burp XML exports"}</span>
      {hint && <span className="dropzone-hint">{hint}</span>}
    </motion.div>
  );
}
