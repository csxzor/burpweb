import { useEffect, useRef, useState } from "react";
import type { EventMsg } from "./types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting";

interface Options {
  onEvent: (event: EventMsg) => void;
  /** Called every time the socket drops, so the app can re-check whether it was locked. */
  onDisconnect?: () => void;
}

const defaultSocket = (url: string) => new WebSocket(url);

export function useEvents(
  enabled: boolean,
  options: Options,
  createSocket: (url: string) => WebSocket = defaultSocket,
): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    let stopped = false;
    let attempt = 0;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = createSocket(`${scheme}://${window.location.host}/api/events`);
      socket.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      socket.onmessage = (message) => {
        try {
          latest.current.onEvent(JSON.parse(message.data as string) as EventMsg);
        } catch {
          // ignore messages that are not valid JSON
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setStatus("reconnecting");
        latest.current.onDisconnect?.();
        const delay = Math.min(500 * 2 ** attempt, 5000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };

    setStatus("connecting");
    connect();
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      socket?.close();
    };
  }, [enabled, createSocket]);

  return status;
}
