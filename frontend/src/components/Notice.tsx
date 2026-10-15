import type { ReactNode } from "react";
import { motion } from "motion/react";
import { springs } from "../motion";
import "./Unlock.css";

export function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="unlock">
      <motion.div
        className="unlock-card"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.screen}
      >
        <div className="unlock-body">
          <div className="brand mono">
            <span className="brand-dot" />
            burpweb
          </div>
          <h1>{title}</h1>
          <div className="muted">{children}</div>
        </div>
      </motion.div>
    </main>
  );
}
