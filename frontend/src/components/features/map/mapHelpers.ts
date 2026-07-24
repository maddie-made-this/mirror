import type { GraphNode, Valence } from "@/types/graph";

export const VALENCE_COLORS: Record<Valence, string> = {
  positive: "#4ade80",   // green
  negative: "#f87171",   // red
  ambivalent: "#fbbf24", // amber
  neutral: "#94a3b8",    // slate
};

export const ENTITY_RING_COLORS: Record<string, string> = {
  emotion: "#ec4899",
  goal: "#3b82f6",
  tension: "#a855f7",
  pattern: "#06b6d4",
  belief: "#f59e0b",
  value: "#10b981",
  person: "#ef4444",
  memory: "#8b5cf6",
  preference: "#64748b",
  format_rule: "#64748b",
};

// Two modes only. The mean/min/max valence aggregates were dev-diagnostic noise —
// a reader wants "which theme is this?" or "how does it feel?", not four
// near-identical valence variants. The aggregates still exist on the node for
// the side panel; they are just not a colouring choice.
export type ColorMode = "cluster" | "valence";

// Build {clusterId -> position} from the ordered cluster list. Position, not a
// hash of the id, is what drives hue — see clusterColor.
export function clusterIndexMap(clusterIds: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  clusterIds.forEach((id, i) => { out[id] = i; });
  return out;
}

// The golden angle. Successive multiples land maximally far apart on the hue
// circle for ANY count, so the Nth cluster is always well separated from the
// N-1 before it.
const GOLDEN_ANGLE = 137.508;

/**
 * Colour for a cluster.
 *
 * `index` (its position in the cluster list) drives the hue via golden-angle
 * spacing. The previous version hashed the cluster id straight to a hue, which
 * guaranteed nothing: a real five-cluster graph produced hues 149/162/170/175 —
 * four themes inside a 26 degree band, two of them 5 degrees apart, i.e. visually
 * identical. Hashing gives you a stable colour, not a distinguishable one.
 *
 * Falls back to the old hash when no index is supplied (caller has an id but no
 * ordering), so every call site keeps working.
 */
export function clusterColor(
  clusterId: string | null | undefined,
  index?: number,
): string {
  if (!clusterId) return "#475569";
  if (index === undefined) {
    let h = 0;
    for (let i = 0; i < clusterId.length; i++) h = (h * 31 + clusterId.charCodeAt(i)) % 360;
    return `hsl(${h}, 68%, 60%)`;
  }
  const hue = (index * GOLDEN_ANGLE) % 360;
  // Alternate lightness every other cluster so that even near-identical hues
  // (only possible well past ~20 clusters) stay separable.
  const light = index % 2 === 0 ? 62 : 52;
  return `hsl(${hue.toFixed(1)}, 70%, ${light}%)`;
}

export function colorForNode(
  node: GraphNode,
  mode: ColorMode = "cluster",
  clusterIndex?: Record<string, number>,
): string {
  if (mode === "cluster") {
    const idx = node.cluster_id ? clusterIndex?.[node.cluster_id] : undefined;
    return clusterColor(node.cluster_id, idx);
  }
  // Valence = how the most recent mention felt; the display-truth aggregate.
  const score = node.valence_score_last;

  if (score > 0.2)            return VALENCE_COLORS.positive;
  if (score < -0.2)           return VALENCE_COLORS.negative;
  if (Math.abs(score) > 0.05) return VALENCE_COLORS.ambivalent;
  return VALENCE_COLORS.neutral;
}

// Small, fairly uniform dots (Neo4j-browser feel) — frequency still reads via a
// modest size gradient, but nodes stay small so the edges between them are
// individually legible rather than buried under fat circles.
export function nodeRadius(node: GraphNode): number {
  return Math.max(2.5, Math.min(10, 2.5 + Math.sqrt(node.mention_count) * 1.5));
}

// Inferred nodes (the system's read of what you implied) render dimmer than
// things you stated outright — so the reflected-back layer is visually distinct
// and legibly "ours, not yours". Explainability is a core value, not a mode.
export function opacityForNode(node: GraphNode): number {
  return node.knowledge_source === "llm_inferred" ? 0.45 : 1;
}

// Four meaning-families with distinct visual languages. Hierarchy/association/
// causation all read as "belong together"; contrast is the deliberate odd-one-out.
export type RelationFamily = "hierarchy" | "association" | "causal" | "contrast";

export function relationFamily(rt: string | undefined): RelationFamily {
  switch (rt) {
    case "is_a": case "part_of": case "has_property": return "hierarchy";
    case "causes": return "causal";
    case "contrasts_with": return "contrast";
    default: return "association";  // relates_to, co_occurs_with
  }
}

export interface EdgeStyle {
  color: string;
  width: number;        // base width (scaled by /globalScale at draw time)
  dash: number[] | null;
  arrow: boolean;       // directional arrowhead
  centerBreak: boolean; // contrast: line doesn't connect in the middle
}

export function edgeStyle(rt: string | undefined): EdgeStyle {
  const fam = relationFamily(rt);
  if (fam === "hierarchy")
    return { color: "rgba(148,163,184,0.85)", width: 1.8, dash: null, arrow: true, centerBreak: false };
  if (fam === "causal")
    return { color: "rgba(245,158,11,0.9)", width: 1.6, dash: null, arrow: true, centerBreak: false };
  if (fam === "contrast")
    return { color: "rgba(244,63,94,0.9)", width: 1.6, dash: null, arrow: false, centerBreak: true };
  // association — co_occurs_with is the quietest (dotted), relates_to a touch more present
  if (rt === "co_occurs_with")
    return { color: "rgba(148,163,184,0.22)", width: 0.8, dash: [2, 4], arrow: false, centerBreak: false };
  return { color: "rgba(148,163,184,0.4)", width: 1.0, dash: null, arrow: false, centerBreak: false };
}

// The legend (bottom-left) and the Insights panel (top-right) both float over
// the canvas. Both start closed — the map tab should show the map, not two
// panels covering it.
//
// They're siblings with no common owner, so they coordinate by event: whoever
// opens announces it, and the other closes. MOBILE ONLY: on a phone either
// panel open is most of the screen, so they have to take turns. A desktop
// canvas has room for both at once, and force-closing one there just takes
// away a choice the user made.
export const MAP_PANEL_EVENT = "mapPanelOpened";
export type MapPanelId = "legend" | "insights";

/** Matches the useIsMobile breakpoint. */
const MOBILE_QUERY = "(max-width: 767px)";

export function announceMapPanel(panel: MapPanelId) {
  window.dispatchEvent(new CustomEvent(MAP_PANEL_EVENT, { detail: { panel } }));
}

/**
 * Run `close` when a DIFFERENT map panel opens, on narrow viewports only.
 * Evaluated per event rather than captured, so it stays correct across resizes
 * and device-mode toggles without re-subscribing.
 */
export function onOtherMapPanel(self: MapPanelId, close: () => void) {
  const handler = (e: Event) => {
    if (!window.matchMedia(MOBILE_QUERY).matches) return;
    const panel = (e as CustomEvent<{ panel: MapPanelId }>).detail?.panel;
    if (panel && panel !== self) close();
  };
  window.addEventListener(MAP_PANEL_EVENT, handler);
  return () => window.removeEventListener(MAP_PANEL_EVENT, handler);
}
