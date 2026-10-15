import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { ApiError, api, setAuthHandlers } from "./api";
import { Main } from "./components/Main";
import { Notice } from "./components/Notice";
import { Unlock } from "./components/Unlock";
import { springs } from "./motion";

type Phase = "loading" | "forbidden" | "offline" | "new" | "locked" | "unlocked";

export function App() {
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    setAuthHandlers({
      locked: () => setPhase((p) => (p === "unlocked" ? "locked" : p)),
      forbidden: () => setPhase("forbidden"),
    });
    api
      .state()
      .then((state) => setPhase(state.vault))
      .catch((e) => setPhase(e instanceof ApiError && e.status === 403 ? "forbidden" : "offline"));
    return () => setAuthHandlers({});
  }, []);

  const screen = phase === "new" || phase === "locked" ? "unlock" : phase;
  return (
    <motion.div
      key={screen}
      className="screen"
      style={{ height: "100%" }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springs.screen}
    >
      {phase === "loading" && <p className="muted" style={{ padding: 24 }}>Loading…</p>}
      {(phase === "new" || phase === "locked") && <Unlock mode={phase} onUnlocked={() => setPhase("unlocked")} />}
      {phase === "unlocked" && <Main onLocked={() => setPhase("locked")} />}
      {phase === "forbidden" && (
        <Notice title="Session expired">
          <p>This page's access token is no longer valid. Open the URL printed in the terminal where burpweb is running.</p>
        </Notice>
      )}
      {phase === "offline" && (
        <Notice title="Can't reach burpweb">
          <p>The server didn't answer. Check that burpweb is still running in your terminal, then reload this page.</p>
        </Notice>
      )}
    </motion.div>
  );
}
