import { useState, type FormEvent } from "react";
import { motion, useAnimationControls } from "motion/react";
import { ApiError, api } from "../api";
import { springs } from "../motion";
import "./Unlock.css";

export const MIN_PASSPHRASE = 10;

export function passphraseStrength(p: string): { level: 0 | 1 | 2 | 3; label: string } {
  if (p.length < MIN_PASSPHRASE) return { level: 0, label: "Too short" };
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(p)).length;
  if (p.length >= 16 && classes >= 3) return { level: 3, label: "Strong" };
  if (p.length >= 12 || classes >= 3) return { level: 2, label: "Good" };
  return { level: 1, label: "Fair" };
}

interface Props {
  mode: "new" | "locked";
  onUnlocked: () => void;
}

export function Unlock({ mode, onUnlocked }: Props) {
  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const shake = useAnimationControls();
  const creating = mode === "new";
  const strength = passphraseStrength(passphrase);
  const mismatch = creating && confirm !== "" && confirm !== passphrase;
  const canSubmit =
    !pending && passphrase !== "" && (!creating || (passphrase.length >= MIN_PASSPHRASE && confirm === passphrase));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    const secret = passphrase;
    setPassphrase(""); // the secret lives in state only until the request is sent
    setConfirm("");
    try {
      if (creating) await api.createVault(secret);
      else await api.unlock(secret);
      onUnlocked();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401 ? "Wrong passphrase" : e instanceof Error ? e.message : "Something went wrong",
      );
      void shake.start({ x: [0, -8, 8, -5, 5, 0], transition: { duration: 0.38 } });
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="unlock">
      <motion.form
        className="unlock-card"
        onSubmit={submit}
        aria-labelledby="unlock-title"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.screen}
      >
        <motion.div className="unlock-body" animate={shake}>
          <div className="brand mono">
            <span className="brand-dot" />
            burpweb
          </div>
          <h1 id="unlock-title">{creating ? "Create your library passphrase" : "Unlock your library"}</h1>
          <p className="muted">
            {creating
              ? "Snapshots are encrypted with this passphrase. It never leaves this machine."
              : "Enter your passphrase to open your snapshots."}
          </p>
          <label>
            Passphrase
            <input
              type="password"
              autoFocus
              autoComplete={creating ? "new-password" : "current-password"}
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
            />
          </label>
          {creating && (
            <>
              <div className="strength" aria-live="polite">
                <div className="strength-track">
                  <div className="strength-bar" data-level={strength.level} />
                </div>
                <span>{strength.label}</span>
              </div>
              <label>
                Confirm passphrase
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </label>
              {mismatch && (
                <p className="field-error" role="alert">
                  Passphrases don't match
                </p>
              )}
              <p className="warning">If you forget this passphrase, stored snapshots can't be recovered.</p>
            </>
          )}
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="primary" disabled={!canSubmit}>
            {pending ? "Working…" : creating ? "Create library" : "Unlock"}
          </button>
        </motion.div>
      </motion.form>
    </main>
  );
}
