import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/utils/apiClient";

interface ProcessingStatus {
  pending: number;
  recently_added_node_ids: string[];
}

/**
 * Poll the backend's background extraction worker (Change 1). Extraction now runs
 * OFF the response path, so nodes land a few seconds after an utterance rather than
 * with the reply. This hook:
 *   - returns the live `pending` count for a quiet "N processing" indicator, and
 *   - dispatches "graphUpdated" whenever new nodes land or the queue drains, so the
 *     map (useGraphData listens for that event) pops new nodes as they arrive.
 *
 * Best-effort: a missing endpoint or transient error is ignored, and polling stops
 * when there's no user.
 */
export function useProcessing(userId: string | null, intervalMs = 2500) {
  const [pending, setPending] = useState(0);
  const lastSig = useRef<string>("");
  const lastPending = useRef<number>(0);

  useEffect(() => {
    if (!userId) return;
    let alive = true;

    const poll = async () => {
      try {
        const s = await apiClient<ProcessingStatus>(
          `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}/processing`,
        );
        if (!alive) return;
        setPending(s.pending);
        const sig = (s.recently_added_node_ids || []).join(",");
        // New nodes landed, or the queue just drained → refresh the graph.
        if (sig !== lastSig.current || (lastPending.current > 0 && s.pending === 0)) {
          lastSig.current = sig;
          window.dispatchEvent(new CustomEvent("graphUpdated"));
        }
        lastPending.current = s.pending;
      } catch {
        /* endpoint absent or transient — ignore */
      }
    };

    void poll();
    const id = setInterval(poll, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [userId, intervalMs]);

  return { pending };
}
