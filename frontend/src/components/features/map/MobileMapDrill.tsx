"use client";

import { useMemo, useState } from "react";
import { useGraphData } from "@/hooks/useGraphData";
import { MindMapSidePanel } from "./MindMapSidePanel";
import type { GraphNode } from "@/types/graph";

const UNSORTED = "__unsorted__";

interface Region {
  id: string;
  label: string;
  nodes: GraphNode[];
  maxCharge: number;
  motifs: number;
  preview: string;
}

/**
 * The mobile map (design §2.4): region-first, drill-don't-pan. The default view
 * is the cluster regions as a list — tap a region to enter it, tap a motif
 * for the full readings panel as a full-screen sheet. Navigation is a stack of
 * taps with state held across the stack, so back is instant. This is the
 * opt-in view now — the map tab lands on the canvas, and "☰ Regions" brings
 * you here; "View Map" goes back.
 */
export function MobileMapDrill({
  userId, onExplore,
}: { userId: string | null; onExplore: () => void }) {
  const { data, isLoading } = useGraphData(userId);
  const [regionId, setRegionId] = useState<string | null>(null);
  const [node, setNode] = useState<GraphNode | null>(null);

  const regions = useMemo<Region[]>(() => {
    if (!data) return [];
    const byCluster = new Map<string, GraphNode[]>();
    for (const n of data.nodes) {
      if (n.entity_type === "self") continue;
      const key = n.cluster_id || UNSORTED;
      const list = byCluster.get(key) ?? [];
      list.push(n);
      byCluster.set(key, list);
    }
    const labels = new Map(data.clusters.map((c) => [c.id, c.label]));
    const regionsOut: Region[] = [];
    for (const [id, nodes] of byCluster) {
      const sorted = [...nodes].sort((a, b) => b.mention_count - a.mention_count);
      regionsOut.push({
        id,
        label: id === UNSORTED ? "Unsorted" : labels.get(id) ?? "…",
        nodes,
        maxCharge: Math.max(0, ...nodes.map((n) => n.salience_score_mean ?? 0)),
        motifs: nodes.filter((n) => n.motif).length,
        preview: sorted.slice(0, 3).map((n) => n.name).join(" · "),
      });
    }
    // Unsorted sinks to the bottom; real regions order by size.
    return regionsOut.sort((a, b) => {
      if (a.id === UNSORTED) return 1;
      if (b.id === UNSORTED) return -1;
      return b.nodes.length - a.nodes.length;
    });
  }, [data]);

  const region = regions.find((r) => r.id === regionId) ?? null;

  const regionNodes = useMemo(() => {
    if (!region) return [];
    return [...region.nodes].sort(
      (a, b) =>
        Number(b.motif ?? false) - Number(a.motif ?? false) ||
        (b.salience_score_mean ?? 0) - (a.salience_score_mean ?? 0) ||
        b.mention_count - a.mention_count,
    );
  }, [region]);

  if (isLoading && !data) {
    return <div className="h-full w-full bg-slate-950" />;
  }

  return (
    <div className="relative h-full w-full bg-slate-950 overflow-hidden">
      {/* Level 1 + 2 share the scroll container; the sheet overlays both. */}
      <div className="h-full overflow-y-auto p-4 pb-24">
        {!region ? (
          <>
            <div className="flex items-center justify-between mb-4">
              <h1 className="text-lg font-semibold text-white">Your map</h1>
              <button
                onClick={onExplore}
                className="px-3 py-1.5 rounded-full text-xs font-bold bg-slate-800/80 border border-slate-700 text-slate-200"
              >
                🗺 View Map
              </button>
            </div>
            {regions.length === 0 ? (
              <div className="text-center p-10 text-slate-500 border border-dashed border-slate-800 rounded-2xl">
                Nothing mapped yet — it grows as you talk.
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {regions.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setRegionId(r.id)}
                    className="text-left bg-slate-900 border border-slate-800 rounded-xl p-4 active:bg-slate-800 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[15px] font-semibold text-white">{r.label}</span>
                      {r.motifs > 0 && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-300">
                          {r.motifs} motif{r.motifs > 1 ? "s" : ""}
                        </span>
                      )}
                      <div className="flex-1" />
                      <span className="text-xs text-slate-500">{r.nodes.length}</span>
                    </div>
                    {r.maxCharge >= 0.3 && (
                      <div className="mt-2 h-1 bg-slate-800 rounded overflow-hidden">
                        <div
                          className="h-full rounded bg-gradient-to-r from-amber-500 to-rose-500"
                          style={{ width: `${Math.min(r.maxCharge * 100, 100)}%` }}
                        />
                      </div>
                    )}
                    {r.preview && (
                      <div className="text-xs text-slate-500 mt-1.5 truncate">{r.preview}</div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-4">
              <button
                onClick={() => setRegionId(null)}
                className="text-slate-400 hover:text-slate-200 text-sm font-semibold"
              >
                ← Regions
              </button>
              <h1 className="text-lg font-semibold text-white truncate">{region.label}</h1>
            </div>
            <div className="flex flex-col gap-2">
              {regionNodes.map((n) => {
                const salience = Math.max(n.salience_score_mean ?? 0, 0);
                return (
                  <button
                    key={n.id}
                    onClick={() => setNode(n)}
                    className="text-left bg-slate-900 border border-slate-800 rounded-xl p-3.5 active:bg-slate-800 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium text-white truncate">{n.name}</span>
                      {n.motif && (
                        <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-300">
                          motif
                        </span>
                      )}
                      <div className="flex-1" />
                      <span className="text-xs text-slate-600 shrink-0">×{n.mention_count}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">
                        {n.entity_type}
                      </span>
                      {salience >= 0.3 && (
                        <div className="flex-1 max-w-32 h-1 bg-slate-800 rounded overflow-hidden">
                          <div
                            className="h-full rounded bg-gradient-to-r from-amber-500 to-rose-500"
                            style={{ width: `${Math.min(salience * 100, 100)}%` }}
                          />
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* Level 3: the readings panel as a full-screen sheet (§2.3 / §5). */}
      {node && (
        <div className="absolute inset-0 z-30 bg-slate-900">
          <MindMapSidePanel node={node} onClose={() => setNode(null)} />
        </div>
      )}
    </div>
  );
}
