import { useEffect, useRef, useState } from "react";

export function hasFiles(dt: DataTransfer | null | undefined): boolean {
  return !!dt && Array.from(dt.types ?? []).includes("Files");
}

/**
 * Window-wide file drag handling. It also cancels file drops that no drop zone took:
 * without that, Firefox would navigate to the dropped XML file and unload the page.
 */
export function useWindowDrop(onFiles: (files: File[]) => void, enabled = true): boolean {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const latest = useRef(onFiles);
  latest.current = onFiles;

  useEffect(() => {
    if (!enabled) {
      depth.current = 0;
      setDragging(false);
      return;
    }
    const enter = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current += 1;
      setDragging(true);
    };
    const over = (e: DragEvent) => {
      if (hasFiles(e.dataTransfer)) e.preventDefault(); // required for the drop event to fire
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current = 0;
      setDragging(false);
      if (e.defaultPrevented) return; // a drop zone already took these files
      e.preventDefault();
      const dropped = Array.from(e.dataTransfer?.files ?? []);
      if (dropped.length) latest.current(dropped);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [enabled]);

  return dragging;
}
