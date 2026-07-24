"use client";

import { useCallback, useEffect, useState } from "react";
import { announceMapPanel, onOtherMapPanel } from "./mapHelpers";
import { apiClient } from "@/utils/apiClient";
import type { Interpretation } from "@/types/graph";

const KIND_COLORS: Record<string, string> = {
  pattern: "#06b6d4",
  tension: "#a855f7",
  bridge: "#f59e0b",
  function: "#10b981",
  behavioral: "#64748b",
  stylistic: "#64748b",
};

// The "reflecting-back is visible" surface: the system's sourced, rejectable
// hypotheses (patterns, tensions, and cross-cluster bridges). Affirm/reject/
// qualify is the production efficacy loop — it dominates each insight's
// confidence and is the only valid efficacy test.
export function InsightsPanel({ userId }: { userId: string | null }) {
  const [insights, setInsights] = useState<Interpretation[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [nodePanelOpen, setNodePanelOpen] = useState(false);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const data = await apiClient<Interpretation[]>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/interpretations?limit=12`,
      );
      setInsights(data);
    } catch {
      /* signed out / offline — leave as-is */
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  // New insights can appear after a message triggers a background re-run.
  useEffect(() => {
    const handler = () => load();
    window.addEventListener("graphUpdated", handler);
    return () => window.removeEventListener("graphUpdated", handler);
  }, [load]);

  // Tapping an overlay on the map focuses the matching insight here.
  useEffect(() => {
    const handler = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id;
      if (!id) return;
      setOpen(true);
      announceMapPanel("insights");
      setHighlight(id);
      setTimeout(() => {
        document.getElementById(`insight-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 60);
      setTimeout(() => setHighlight((h) => (h === id ? null : h)), 2600);
    };
    window.addEventListener("focusInsight", handler);
    return () => window.removeEventListener("focusInsight", handler);
  }, []);

  // Only one floating map panel at a time — close if the legend opens.
  useEffect(() => onOtherMapPanel("insights", () => setOpen(false)), []);

  // Step aside while a node's context panel occupies the right column.
  useEffect(() => {
    const handler = (e: Event) =>
      setNodePanelOpen(!!(e as CustomEvent<{ open: boolean }>).detail?.open);
    window.addEventListener("mapNodePanel", handler);
    return () => window.removeEventListener("mapNodePanel", handler);
  }, []);

  const respond = async (id: string, response: "affirmed" | "rejected" | "qualified") => {
    setBusy(id);
    try {
      await apiClient(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/interpretations/${id}/respond`,
        { data: { response }, method: "POST" },
      );
      setInsights(prev => prev.filter(i => i.id !== id));
    } catch {
      /* leave it for retry */
    } finally {
      setBusy(null);
    }
  };

  if (!insights.length || nodePanelOpen) return null;

  return (
    <div className="absolute top-4 right-4 z-20 w-[min(360px,calc(100vw-2rem))]">
      <div className="bg-slate-900/90 backdrop-blur border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
        <button
          onClick={() => {
            const next = !open;
            setOpen(next);
            if (next) announceMapPanel("insights");
          }}
          className="w-full flex items-center justify-between px-3 py-2 text-left border-b border-slate-800"
        >
          <span className="text-slate-200 text-sm font-semibold">
            Insights <span className="text-slate-500">({insights.length})</span>
          </span>
          <span className="text-slate-500 text-xs">{open ? "▾" : "▸"}</span>
        </button>

        {open && (
          <div className="max-h-[60vh] overflow-y-auto divide-y divide-slate-800">
            {insights.map((i) => (
              <div
                key={i.id}
                id={`insight-${i.id}`}
                className={`p-3 transition-colors duration-500 ${
                  highlight === i.id ? "bg-amber-500/10 ring-1 ring-amber-500/40" : ""
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded"
                    style={{ color: KIND_COLORS[i.kind] ?? "#94a3b8", background: `${KIND_COLORS[i.kind] ?? "#94a3b8"}1a` }}
                  >
                    {i.kind}
                  </span>
                  <span className="text-slate-600 text-[10px]">conf {i.confidence.toFixed(2)}</span>
                </div>
                <p className="text-slate-200 text-[13px] leading-snug">{i.statement}</p>
                {i.inferential_step && (
                  <p className="text-slate-500 text-[11px] italic mt-1">
                    inference: {i.inferential_step}
                  </p>
                )}
                <div className="flex gap-2 mt-2">
                  <button
                    disabled={busy === i.id}
                    onClick={() => respond(i.id, "affirmed")}
                    className="px-2 py-1 text-[11px] rounded bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 disabled:opacity-50"
                  >
                    Yes, that's me
                  </button>
                  <button
                    disabled={busy === i.id}
                    onClick={() => respond(i.id, "qualified")}
                    className="px-2 py-1 text-[11px] rounded bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 disabled:opacity-50"
                  >
                    Sort of
                  </button>
                  <button
                    disabled={busy === i.id}
                    onClick={() => respond(i.id, "rejected")}
                    className="px-2 py-1 text-[11px] rounded bg-slate-700/40 text-slate-400 hover:bg-slate-700/70 disabled:opacity-50"
                  >
                    Not really
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
