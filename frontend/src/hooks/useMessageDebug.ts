import { useEffect, useState } from "react";
import type { MessageResponse } from "@/types/graph";

/**
 * Listens for the "messageDebug" CustomEvent dispatched by useChat after each
 * successful POST. Holds the last response so the DebugPanel can inspect it.
 */
export function useMessageDebug() {
  const [last, setLast] = useState<MessageResponse | null>(null);
  const [history, setHistory] = useState<MessageResponse[]>([]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<MessageResponse>).detail;
      setLast(detail);
      setHistory((h) => [...h.slice(-9), detail]);
    };
    window.addEventListener("messageDebug", handler);
    return () => window.removeEventListener("messageDebug", handler);
  }, []);

  return { last, history };
}
