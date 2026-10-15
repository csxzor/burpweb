import { api } from "../api";
import "./Main.css";

export function Main({ onLocked }: { onLocked: () => void }) {
  const lock = async () => {
    await api.lock().catch(() => {});
    onLocked();
  };
  return (
    <div className="main-grid">
      <aside className="col library" aria-label="Library">
        <header className="col-head">
          <span className="col-title">Library</span>
          <button className="ghost small" onClick={lock}>
            Lock
          </button>
        </header>
      </aside>
      <section className="col stage" aria-label="Stage" />
      <aside className="col feed" aria-label="Live feed" />
    </div>
  );
}
