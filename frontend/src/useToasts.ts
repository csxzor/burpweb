import { useCallback, useEffect, useRef, useState } from "react";

export interface Toast {
  id: number;
  level: "error" | "info";
  message: string;
}

export function useToasts(autoDismissMs = 6000) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const current = useRef<Toast[]>([]); // mirrors state so push() can de-duplicate without side effects in an updater
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    current.current = current.current.filter((t) => t.id !== id);
    setToasts(current.current);
  }, []);

  const push = useCallback(
    (level: Toast["level"], message: string) => {
      if (current.current.some((t) => t.level === level && t.message === message)) return;
      const toast = { id: nextId.current++, level, message };
      current.current = [...current.current, toast];
      setToasts(current.current);
      if (level === "info") timers.current.set(toast.id, setTimeout(() => dismiss(toast.id), autoDismissMs));
    },
    [autoDismissMs, dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => clearTimeout(timer));
  }, []);

  return { toasts, push, dismiss };
}
