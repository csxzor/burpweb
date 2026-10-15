import { AnimatePresence, motion } from "motion/react";
import "./DragOverlay.css";

export function DragOverlay({ visible }: { visible: boolean }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="drag-overlay"
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
        >
          <div className="drag-overlay-frame">
            <div className="drag-overlay-title">Drop Burp XML exports</div>
            <div className="muted">to create a new snapshot</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
