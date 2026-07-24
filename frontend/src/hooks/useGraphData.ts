import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/utils/apiClient";
import type { GraphResponse, GraphEdge, ClusterInfo, OverlayInterpretation, ClusterSimilarity } from "@/types/graph";
import type { GraphNode } from "@/types/graph";

export interface ForceGraphData {
  nodes: GraphNode[];
  links: (GraphEdge & { source: string; target: string })[];
  clusters: ClusterInfo[];
  interpretations: OverlayInterpretation[];
  clusterSimilarity: ClusterSimilarity[];
  // Render-only — NEVER fed to the force sim (see MindMap). Drawn as faint
  // threads behind the nodes when the co-occurrence toggle is on.
  cooccurrence: { source_id: string; target_id: string; weight: number }[];
}

export function useGraphData(userId: string | null, includeCooccurrence = false) {
  const [data, setData] = useState<ForceGraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async () => {
    if (!userId) return;
    setIsLoading(true);
    try {
      const qs = `?limit=500${includeCooccurrence ? "&include_cooccurrence=1" : ""}`;
      const res = await apiClient<GraphResponse>(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/graph/${userId}${qs}`,
      );
      // Layout is driven ONLY by the sparse semantic edges. Co-occurrence is kept
      // separate and never enters graphData.links → never affects positioning
      // (map spec §1B); it renders as a faint behind-nodes overlay when toggled on.
      const links: ForceGraphData["links"] = res.edges.map((e) => ({
        ...e, source: e.source_id, target: e.target_id,
      }));
      setData({
        nodes: res.nodes,
        links,
        clusters: res.clusters ?? [],
        interpretations: res.interpretations ?? [],
        clusterSimilarity: res.cluster_similarity ?? [],
        cooccurrence: res.cooccurrence ?? [],
      });
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load graph");
    } finally {
      setIsLoading(false);
    }
  }, [userId, includeCooccurrence]);

  useEffect(() => { load(); }, [load]);

  // The chat hook dispatches "graphUpdated" after each successful message.
  // A refetch is simpler and accurate — mention counts, edge weights and
  // valence aggregates are all server-truth.
  useEffect(() => {
    const handler = () => load();
    window.addEventListener("graphUpdated", handler);
    return () => window.removeEventListener("graphUpdated", handler);
  }, [load]);

  return { data, error, isLoading, refresh: load };
}
