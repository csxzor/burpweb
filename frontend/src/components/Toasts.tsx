import { AnimatePresence, motion } from "motion/react";
import { springs } from "../motion";
import type { Toast } from "../useToasts";
import "./Toasts.css";

interface Props {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}

export function Toasts({ toasts, onDismiss }: Props) {
  return (
    <div className="toasts" aria-live="polite">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            layout
            className="toast"
            data-level={toast.level}
            role={toast.level === "error" ? "alert" : "status"}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={springs.screen}
          >
            <span>{toast.message}</span>
            <button aria-label="Dismiss" onClick={() => onDismiss(toast.id)}>
              ×
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
