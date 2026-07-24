"use client";

import { useCallback, useRef, useState, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { forceCollide } from "d3-force-3d";
import { useGraphData, type ForceGraphData } from "@/hooks/useGraphData";
import { MindMapSidePanel } from "./MindMapSidePanel";
import { MapCommunityList } from "./MapCommunityList";
import {
  ENTITY_RING_COLORS, colorForNode, clusterColor, clusterIndexMap,
  nodeRadius, opacityForNode, edgeStyle,
  announceMapPanel, onOtherMapPanel,
} from "./mapHelpers";
import type { ColorMode } from "./mapHelpers";
import type { GraphEdge, GraphNode } from "@/types/graph";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// Semantic-zoom tiers (Google-Maps country -> cities -> streets):
//   OUT  : community regions + labels + interpretation overlays only
//   MID  : individual nodes appear; meaningful edges faint; regions soften
//   IN   : node labels + the full edge visual vocabulary
const OUT_MAX = 0.85;
const IN_MIN = 1.9;
// Community labels persist further into the zoom than node detail does, so you
// keep your bearings ("which community am I in?") well after zooming in.
const LABEL_UNTIL = 3.4;

// Short, human edge labels drawn along each edge (Neo4j-style) at the in tier.
const EDGE_LABELS: Record<string, string> = {
  is_a: "is a",
  part_of: "part of",
  has_property: "has",
  causes: "causes",
  contrasts_with: "contrasts",
  co_occurs_with: "co-occurs",
  relates_to: "relates",
};

// Pull same-cluster nodes toward their shared centroid so communities ball up
// like the Neo4j view; pull every node gently toward the origin so distinct
// communities don't drift into a sea of empty space; and pull each community
// toward its semantic kin (§3A) so the map's geography is meaningful — themes
// that are close in embedding space end up close on screen.
type SimLink = { a: string; b: string; score: number };
function forceCluster(
  strength: number,
  gravity: number,
  simLinks: SimLink[] = [],
  simStrength = 0,
  separation = 0,
  sepRadius = 240,
) {
  let nodes: any[] = [];
  const adj: Record<string, { other: string; score: number }[]> = {};
  for (const s of simLinks) {
    (adj[s.a] ||= []).push({ other: s.b, score: s.score });
    (adj[s.b] ||= []).push({ other: s.a, score: s.score });
  }
  function force(alpha: number) {
    const cen: Record<string, { x: number; y: number; n: number }> = {};
    for (const n of nodes) {
      if (!n.cluster_id || n.x == null) continue;
      const c = cen[n.cluster_id] || (cen[n.cluster_id] = { x: 0, y: 0, n: 0 });
      c.x += n.x; c.y += n.y; c.n += 1;
    }
    for (const k in cen) { cen[k].x /= cen[k].n; cen[k].y /= cen[k].n; }
    for (const n of nodes) {
      n.vx += -n.x * gravity * alpha;   // global gravity → compact overall layout
      n.vy += -n.y * gravity * alpha;
      const c = cen[n.cluster_id];
      if (!c) continue;
      n.vx += (c.x - n.x) * strength * alpha;  // intra-community cohesion
      n.vy += (c.y - n.y) * strength * alpha;
      // Inter-community semantic attraction: drift toward kin communities,
      // weighted by centroid-cosine similarity (so the strongest pairs sit
      // adjacent). Gentle, so it arranges without dissolving the communities.
      const kin = adj[n.cluster_id];
      if (kin && simStrength) {
        for (const { other, score } of kin) {
          const co = cen[other];
          if (!co) continue;
          n.vx += (co.x - n.x) * score * simStrength * alpha;
          n.vy += (co.y - n.y) * score * simStrength * alpha;
        }
      }
      // Inter-community separation (2.3): push away from OTHER clusters' centroids
      // that crowd this node, so communities settle into distinct screen regions
      // instead of one overlapping blob. Falls off with distance; weaker than
      // cohesion so a community drifts apart from its neighbours without dissolving.
      if (separation) {
        for (const k in cen) {
          if (k === n.cluster_id) continue;
          const oc = cen[k];
          const dx = n.x - oc.x, dy = n.y - oc.y;
          const d = Math.hypot(dx, dy) || 1;
          if (d < sepRadius) {
            const push = ((sepRadius - d) / sepRadius) * separation * alpha;
            n.vx += (dx / d) * push * sepRadius;
            n.vy += (dy / d) * push * sepRadius;
          }
        }
      }
    }
  }
  (force as any).initialize = (n: any[]) => { nodes = n; };
  return force;
}

function convexHull(points: { x: number; y: number }[]) {
  const pts = points.slice().sort((a, b) => a.x - b.x || a.y - b.y);
  if (pts.length < 3) return pts;
  const cross = (o: any, a: any, b: any) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: any[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: any[] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop(); upper.pop();
  return lower.concat(upper);
}

export function MindMap({
  userId,
  sampleData,
}: {
  userId: string | null;
  // Static dataset for the signed-out landing-page demo. When provided the hook
  // never fetches (userId is null there), node selection is disabled, and the
  // side panel — which would hit the API for a node that doesn't exist — is
  // suppressed. Purely illustrative; nothing here touches a real account.
  sampleData?: ForceGraphData;
}) {
  const isSample = !!sampleData;
  // ON by default in the sample: the landing page has one shot at showing that
  // co-occurrence exists, and a feature behind a toggle a visitor never finds is
  // a feature they never see. In the real map it stays off — a full graph's worth
  // of threads is noise until you ask for it.
  const [showCooc, setShowCooc] = useState(isSample);
  const { data: fetched, error: fetchError, isLoading: fetchLoading } = useGraphData(userId, showCooc);
  const data = sampleData ?? fetched;
  const error = isSample ? null : fetchError;
  const isLoading = isSample ? false : fetchLoading;
  // Position-based palette: hue comes from a cluster's index in this list, so
  // adjacent clusters are always visually distinct (see clusterColor).
  const clusterIndex = useMemo(
    () => clusterIndexMap((data?.clusters ?? []).map((c: any) => c.id)),
    [data],
  );
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<GraphEdge | null>(null);
  const [hoveredNode, setHoveredNode] = useState<any>(null);
  const [colorMode, setColorMode] = useState<ColorMode>("cluster");
  // Closed on arrival: the legend sat over the map on first paint, which on a
  // phone is most of the canvas. It's one tap away.
  const [legendOpen, setLegendOpen] = useState(false);
  const fgRef = useRef<any>(null);
  const zoomRef = useRef(1); // current globalScale, for scale-independent hit targets
  const didFitRef = useRef(false); // frame the whole map once, on first settle
  // The framing captured on first settle. Used to clamp panning and to power the
  // Recenter control, so the graph can never be lost off-screen.
  const homeRef = useRef<{ x: number; y: number; k: number } | null>(null);

  const recenter = useCallback(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.zoomToFit(400, 80);
  }, []);
  // ForceGraph2D sizes to the WINDOW unless told otherwise, which overflows any
  // embedded container. Measure the wrapper and pass explicit dimensions.
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setDims({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Tune the simulation to mimic the Neo4j-Browser graph: edges settle to a
  // fixed on-screen length, nodes never overlap, and repulsion is local rather
  // than global, so the layout reads as a tidy mesh of evenly-spaced nodes
  // joined by uniform-length rods — not a weighted spring-mass blob.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !data) return;
    try {
      // FIXED EDGE LENGTH: a constant distance (never scaled by weight) plus a
      // firm strength makes every link behave like a rigid rod that relaxes to
      // the same length — the defining characteristic of the Neo4j layout. Edge
      // *weight* still reads through line thickness (see drawLink), not length.
      const LINK_DISTANCE = 44;
      const link = fg.d3Force("link");
      // strength(1) = rigid rods: every edge relaxes firmly to LINK_DISTANCE, so
      // on-screen edge lengths read uniform (the Neo4j look) instead of varying
      // with how other forces tug each pair.
      if (link) link.distance(LINK_DISTANCE).strength(1);

      // LOCAL REPULSION: moderate charge with a distanceMax so nodes push their
      // neighbours apart for legibility but distant nodes don't blow the graph
      // open — communities stay tight, the whole map stays framed.
      fg.d3Force("charge")?.strength(-170).distanceMax(LINK_DISTANCE * 8);

      // NON-OVERLAP: the signature Neo4j-Browser look. Every node claims its
      // drawn radius plus a constant gap, so even dense clusters lay out as
      // separated discs instead of piling on top of one another. Two iterations
      // resolve tight packing firmly without visible jitter.
      fg.d3Force(
        "collide",
        forceCollide<any>((n: any) => nodeRadius(n) + 6).strength(0.9).iterations(2),
      );

      // Cluster cohesion + separation (2.3/2.4): firmer intra-community cohesion
      // pulls a community into a tight, legible mass with little internal empty
      // space; a lighter inter-community SEPARATION term pushes different
      // communities into distinct regions (less hull overlap); the semantic
      // kin-attraction is eased so similar communities sit ADJACENT, not on top of
      // each other. Cohesion > separation, so communities stay intact while parting.
      fg.d3Force(
        "cluster",
        forceCluster(0.18, 0.03, data.clusterSimilarity ?? [], 0.005, 0.045, 240),
      );
      fg.d3ReheatSimulation?.();
    } catch {
      /* force API not ready yet — harmless */
    }
  }, [data]);

  // The node context panel and the Insights panel both live on the right; tell
  // the Insights panel to step aside while a node is selected.
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("mapNodePanel", { detail: { open: !!selected } }));
  }, [selected]);

  // Only one floating map panel at a time — close if Insights opens.
  useEffect(() => onOtherMapPanel("legend", () => setLegendOpen(false)), []);

  const centroids = useCallback(() => {
    const cen: Record<string, { x: number; y: number; n: number; pts: { x: number; y: number }[] }> = {};
    for (const n of (data?.nodes ?? []) as any[]) {
      if (!n.cluster_id || n.x == null) continue;
      const c = cen[n.cluster_id] || (cen[n.cluster_id] = { x: 0, y: 0, n: 0, pts: [] });
      c.x += n.x; c.y += n.y; c.n += 1; c.pts.push({ x: n.x, y: n.y });
    }
    for (const k in cen) { cen[k].x /= cen[k].n; cen[k].y /= cen[k].n; }
    return cen;
  }, [data]);

  // Fly the camera to a community (used by the mobile community list). Zoom is
  // chosen so the community roughly fills the viewport regardless of its spread.
  const focusCluster = useCallback((clusterId: string) => {
    const c = centroids()[clusterId];
    const fg = fgRef.current;
    if (!c || !fg) return;
    let r = 24;
    for (const p of c.pts) r = Math.max(r, Math.hypot(p.x - c.x, p.y - c.y));
    fg.centerAt(c.x, c.y, 600);
    fg.zoom(Math.max(1.1, Math.min(3.2, 230 / (r + 40))), 600);
  }, [centroids]);

  // Draw one node label as a pill so it stays legible over circles/edges.
  const labelPill = useCallback(
    (ctx: CanvasRenderingContext2D, node: any, globalScale: number, emphasis: boolean) => {
      const r = nodeRadius(node);
      const fs = Math.max(9, (emphasis ? 12 : 11) / globalScale);
      ctx.font = `${emphasis ? "600 " : ""}${fs}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const w = ctx.measureText(node.name).width;
      const pad = 3 / globalScale;
      const ly = node.y + r + 2 / globalScale;
      ctx.fillStyle = emphasis ? "rgba(2,6,23,0.92)" : "rgba(2,6,23,0.62)";
      ctx.fillRect(node.x - w / 2 - pad, ly - pad, w + pad * 2, fs + pad * 2);
      ctx.fillStyle = emphasis ? "#fef3c7" : "rgba(255,255,255,0.9)";
      ctx.fillText(node.name, node.x, ly);
    },
    [],
  );

  // BEHIND the nodes: soft community regions + bridge-interpretation connectors.
  const drawRegions = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (!data) return;
      const cen = centroids();
      const hullAlpha = globalScale < OUT_MAX ? 0.12 : globalScale < IN_MIN ? 0.06 : 0.03;

      // Co-occurrence overlay (toggle): RENDER-ONLY faint threads, drawn from node
      // positions — these are NOT in graphData.links and never touch the force sim
      // (map spec §1B). Only at the mid/in tiers (noise behind blobs when zoomed out).
      // The zoom gate keeps these off the overview tier, where a real graph's
      // threads read as noise behind the cluster blobs. The 12-node sample has no
      // such problem, and zoom-to-fit can leave it below OUT_MAX, so it draws at
      // every tier — otherwise the demo silently shows nothing.
      if (showCooc && (isSample || globalScale >= OUT_MAX) && data.cooccurrence.length) {
        const pos: Record<string, any> = {};
        for (const n of data.nodes as any[]) if (n.x != null) pos[n.id] = n;
        ctx.save();
        // 0.18 alpha on a 0.6px line was below the threshold of actually visible —
        // the threads were being drawn and could not be seen, which reads as the
        // feature being broken. The real map keeps them quiet (they are context,
        // not structure); the sample states them plainly, since a visitor gets one
        // look and the legend explicitly points at them.
        ctx.strokeStyle = isSample ? "rgba(148,163,184,0.5)" : "rgba(148,163,184,0.28)";
        ctx.lineWidth = (isSample ? 1.3 : 0.8) / globalScale;
        ctx.setLineDash([3 / globalScale, 4 / globalScale]);
        for (const c of data.cooccurrence) {
          const s = pos[c.source_id], t = pos[c.target_id];
          if (!s || !t) continue;
          ctx.beginPath();
          ctx.moveTo(s.x, s.y);
          ctx.lineTo(t.x, t.y);
          ctx.stroke();
        }
        ctx.restore();
      }

      for (const cluster of data.clusters) {
        const c = cen[cluster.id];
        // Skip singleton/pair clusters — a hull around 1-2 nodes is just clutter.
        if (!c || c.pts.length < 3) continue;
        const color = clusterColor(cluster.id, clusterIndex[cluster.id]);
        ctx.save();
        // Lighter fill so overlapping regions read as adjacency, not mud (2.3);
        // a clearer outline carries the boundary. Tighter padding hugs the nodes,
        // so a hull spills less into its neighbours.
        ctx.globalAlpha = hullAlpha * 0.55;
        ctx.fillStyle = color;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2 / globalScale;
        const pad = 13 / globalScale + 5;
        if (c.pts.length >= 3) {
          const hull = convexHull(c.pts).map((p) => ({
            x: p.x + (p.x - c.x === 0 ? 0 : Math.sign(p.x - c.x) * pad),
            y: p.y + (p.y - c.y === 0 ? 0 : Math.sign(p.y - c.y) * pad),
          }));
          ctx.beginPath();
          ctx.moveTo((hull[0].x + hull[hull.length - 1].x) / 2, (hull[0].y + hull[hull.length - 1].y) / 2);
          for (let i = 0; i < hull.length; i++) {
            const cur = hull[i], nxt = hull[(i + 1) % hull.length];
            ctx.quadraticCurveTo(cur.x, cur.y, (cur.x + nxt.x) / 2, (cur.y + nxt.y) / 2);
          }
          ctx.closePath();
          ctx.fill();
          ctx.globalAlpha = Math.min(hullAlpha * 3.5, 0.5);
          ctx.stroke();
        } else {
          let r = pad;
          for (const p of c.pts) r = Math.max(r, Math.hypot(p.x - c.x, p.y - c.y) + pad);
          ctx.beginPath();
          ctx.arc(c.x, c.y, r, 0, 2 * Math.PI);
          ctx.fill();
          ctx.globalAlpha = Math.min(hullAlpha * 3.5, 0.5);
          ctx.stroke();
        }
        ctx.restore();
      }

      // Bridge interpretations: a glowing connector between two regions —
      // "insight, not structural link." Persists as deep into the zoom as the
      // community labels, so the cross-theme connection stays legible up close.
      if (globalScale < LABEL_UNTIL) {
        for (const it of data.interpretations) {
          if (it.cluster_ids.length < 2) continue;
          const a = cen[it.cluster_ids[0]], b = cen[it.cluster_ids[1]];
          if (!a || !b) continue;
          // Function-bridges (§6: shared-need connectors) render warm rose;
          // structural bridges stay golden. Alpha tracks confidence.
          const conf = Math.min(Math.max(it.confidence ?? 0.6, 0.35), 1);
          const hue = it.kind === "function" ? "251,113,133" : "250,204,21";
          ctx.save();
          ctx.strokeStyle = `rgba(${hue},${0.3 + 0.35 * conf})`;
          ctx.lineWidth = 2.5 / globalScale;
          ctx.setLineDash([8 / globalScale, 6 / globalScale]);
          ctx.shadowColor = `rgba(${hue},${0.45 + 0.4 * conf})`;
          ctx.shadowBlur = 12 * conf;
          const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - Math.hypot(b.x - a.x, b.y - a.y) * 0.12;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.quadraticCurveTo(mx, my, b.x, b.y);
          ctx.stroke();
          ctx.restore();
        }
      }
    },
    [data, centroids, showCooc, isSample],
  );

  // ON TOP: region labels (overview tiers) + interpretation "insight" markers.
  const drawOverlays = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (!data) return;
      const cen = centroids();

      // Occupied label boxes [x0,y0,x1,y1], so labels never overlap each other.
      // Cluster labels claim space first (priority); node labels avoid them.
      const placed: number[][] = [];
      const overlaps = (b: number[]) =>
        placed.some((p) => !(b[2] < p[0] || b[0] > p[2] || b[3] < p[1] || b[1] > p[3]));

      // Region labels — the "country names". Persist well into the zoom (past
      // node detail) so you keep your bearings, then fade when very close.
      if (globalScale < LABEL_UNTIL) {
        const fs = Math.max(11, 15 / globalScale);
        ctx.font = `600 ${fs}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        for (const cluster of data.clusters) {
          const c = cen[cluster.id];
          if (!c || c.n < 3) continue;  // match the hull threshold — no labels for tiny clusters
          // At the community centroid, but reserve its box first so node labels
          // flow around it instead of colliding with it.
          const w = ctx.measureText(cluster.label).width;
          ctx.fillStyle = "rgba(2,6,23,0.7)";
          ctx.fillRect(c.x - w / 2 - 6, c.y - fs / 2 - 3, w + 12, fs + 6);
          ctx.fillStyle = clusterColor(cluster.id, clusterIndex[cluster.id]);
          ctx.fillText(cluster.label, c.x, c.y);
          placed.push([c.x - w / 2 - 6, c.y - fs / 2 - 3, c.x + w / 2 + 6, c.y + fs / 2 + 3]);
        }
      }

      // Region interpretations: a glowing ring + ✦ over the cluster, meaning
      // "there's a *why* here." Confidence-gated + capped server-side, and the
      // ring's alpha tracks confidence (§2.1: unsure readings LOOK unsure).
      // Function regions (§2.2) — a shared need spanning the region — render
      // warm rose, distinct from the amber pattern/tension markers: the
      // headline aha is explanatory power, and it should read as the thing
      // most worth tapping.
      for (const it of data.interpretations) {
        if (it.cluster_ids.length !== 1) continue;
        const c = cen[it.cluster_ids[0]];
        if (!c) continue;
        let r = 26;
        for (const p of c.pts) r = Math.max(r, Math.hypot(p.x - c.x, p.y - c.y));
        r += 14 / globalScale + 6;
        const conf = Math.min(Math.max(it.confidence ?? 0.6, 0.35), 1);
        const isFunction = it.kind === "function";
        const hue = isFunction ? "251,113,133" : "250,204,21";
        ctx.save();
        ctx.strokeStyle = `rgba(${hue},${0.45 + 0.35 * conf})`;
        ctx.lineWidth = (conf < 0.55 ? 1.0 : 1.5) / globalScale;
        if (conf < 0.55) ctx.setLineDash([5 / globalScale, 4 / globalScale]);
        ctx.shadowColor = `rgba(${hue},${0.5 + 0.3 * conf})`;
        ctx.shadowBlur = 10 * conf;
        ctx.beginPath();
        ctx.arc(c.x, c.y, r, 0, 2 * Math.PI);
        ctx.stroke();
        const fs = Math.max(10, 13 / globalScale);
        ctx.font = `${fs}px Inter, system-ui`;
        ctx.fillStyle = `rgba(${hue},${0.6 + 0.35 * conf})`;
        ctx.textAlign = "center";
        ctx.fillText("✦", c.x + r * 0.7, c.y - r * 0.7);
        ctx.restore();
      }

      // Node labels — drawn after every circle so they sit on top. Collision-
      // culled: place the most important first (selected, then by mention count)
      // and skip any label that would overlap one already drawn (or a cluster
      // label). Keeps dense regions legible instead of a pile of overlapping text.
      if (globalScale >= IN_MIN) {
        const candidates = (data.nodes as any[])
          .filter(
            (n) =>
              n.x != null &&
              n !== hoveredNode &&
              (n.mention_count >= 2 || n === selected),
          )
          .sort(
            (a, b) =>
              (b === selected ? 1 : 0) - (a === selected ? 1 : 0) ||
              (b.mention_count ?? 0) - (a.mention_count ?? 0),
          );
        for (const node of candidates) {
          const emphasis = node === selected;
          const r = nodeRadius(node);
          const fs = Math.max(9, (emphasis ? 12 : 11) / globalScale);
          ctx.font = `${emphasis ? "600 " : ""}${fs}px Inter, system-ui, sans-serif`;
          const w = ctx.measureText(node.name).width;
          const pad = 3 / globalScale;
          const ly = node.y + r + 2 / globalScale;
          const box = [node.x - w / 2 - pad, ly - pad, node.x + w / 2 + pad, ly + fs + pad];
          if (!emphasis && overlaps(box)) continue;  // the selected node always shows
          ctx.globalAlpha = opacityForNode(node);
          labelPill(ctx, node, globalScale, emphasis);
          ctx.globalAlpha = 1;
          placed.push(box);
        }
      }

      // Edge labels — meaningful relations only (association/co-occurs stay
      // hover-only), collision-culled against cluster + node labels and each other.
      // Drawn last = lowest priority, so they fill gaps instead of piling onto node
      // text. Heaviest edges get first claim.
      if (globalScale >= IN_MIN) {
        const labeled = (data.links as any[])
          .filter(
            (l) =>
              typeof l.source === "object" &&
              typeof l.target === "object" &&
              l.relation_type !== "relates_to" &&
              l.relation_type !== "co_occurs_with",
          )
          .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
        const fs = 12 / globalScale;
        ctx.font = `${fs}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "rgba(148,163,184,0.85)";
        for (const link of labeled) {
          const s = link.source, t = link.target;
          const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
          const label = EDGE_LABELS[link.relation_type] ?? link.relation_type;
          const w = ctx.measureText(label).width;
          const box = [mx - w / 2, my - fs / 2, mx + w / 2, my + fs / 2];
          if (overlaps(box)) continue;
          let ang = Math.atan2(t.y - s.y, t.x - s.x);
          if (ang > Math.PI / 2 || ang < -Math.PI / 2) ang += Math.PI;
          ctx.save();
          ctx.translate(mx, my);
          ctx.rotate(ang);
          ctx.translate(0, -fs * 0.95);
          ctx.fillText(label, 0, 0);
          ctx.restore();
          placed.push(box);
        }
      }

      // Hovered node + its label, drawn LAST so they sit above everything.
      if (hoveredNode && hoveredNode.x != null && globalScale >= OUT_MAX) {
        const r = nodeRadius(hoveredNode);
        ctx.save();
        ctx.beginPath();
        ctx.arc(hoveredNode.x, hoveredNode.y, r + 3 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = colorForNode(hoveredNode, colorMode, clusterIndex);
        ctx.shadowColor = "rgba(255,255,255,0.6)";
        ctx.shadowBlur = 10;
        ctx.fill();
        ctx.restore();
        labelPill(ctx, hoveredNode, globalScale, true);
      }
    },
    [data, centroids, selected, hoveredNode, labelPill, colorMode, clusterIndex],
  );

  // Circles only — labels are drawn in a second pass (drawOverlays) so they sit
  // above EVERY node, never under a later-drawn circle.
  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (globalScale < OUT_MAX) return;  // overview tier: regions only
      const r = nodeRadius(node);
      // The force sim leaves x/y undefined on the first ticks before layout
      // settles. ctx.arc tolerates NaN (draws nothing); createRadialGradient
      // (the salience glow below) THROWS on non-finite input — guard up front.
      if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || !(r > 0)) return;
      ctx.save();
      ctx.globalAlpha = opacityForNode(node);

      // Motif salience (§2.1): a warm glow whose strength tracks the node's
      // mean salience — the high-salience terrain legible at a glance. Consolidated
      // motifs glow harder; neutral concepts stay plain discs.
      const salience = Math.max(node.salience_score_mean ?? 0, 0);
      if (salience >= 0.3) {
        const strength = Math.min(salience, 1) * (node.motif ? 1.25 : 1);
        const glow = ctx.createRadialGradient(
          node.x, node.y, r * 0.4, node.x, node.y, r * (2 + strength * 1.6),
        );
        glow.addColorStop(0, `rgba(251,113,133,${0.32 * strength})`);
        glow.addColorStop(0.6, `rgba(245,158,11,${0.14 * strength})`);
        glow.addColorStop(1, "rgba(245,158,11,0)");
        ctx.beginPath();
        ctx.arc(node.x, node.y, r * (2 + strength * 1.6), 0, 2 * Math.PI);
        ctx.fillStyle = glow;
        ctx.fill();
      }

      // Entity-type ring is a SUBTLE accent, not a halo: hug the node (offset
      // scales with r), thin stroke that scales with r, and only on significant
      // nodes at the in tier — so the many one-off nodes read as plain discs.
      const ring = ENTITY_RING_COLORS[node.entity_type];
      if (ring && globalScale >= IN_MIN && (node.mention_count ?? 1) >= 2) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + r * 0.4, 0, 2 * Math.PI);
        ctx.strokeStyle = ring;
        ctx.globalAlpha = opacityForNode(node) * 0.55;
        ctx.lineWidth = Math.max(0.4, r * 0.18) / globalScale;
        ctx.stroke();
        ctx.globalAlpha = opacityForNode(node);
      }
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = colorForNode(node, colorMode, clusterIndex);
      ctx.fill();

      // Consolidated motif (§2.2): a thin warm ring marks "this carries its
      // own weight now" — the invitation to tap.
      if (node.motif && globalScale >= IN_MIN) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + Math.max(1.2, r * 0.55), 0, 2 * Math.PI);
        ctx.strokeStyle = `rgba(251,113,133,${0.35 + 0.5 * (node.motif_confidence ?? 0)})`;
        ctx.lineWidth = Math.max(0.5, r * 0.14) / globalScale;
        ctx.stroke();
      }
      ctx.restore();
    },
    [colorMode, clusterIndex],
  );

  const drawLink = useCallback(
    (link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (globalScale < OUT_MAX) return;  // no edges at the overview tier
      const s = link.source, t = link.target;
      if (typeof s !== "object" || typeof t !== "object") return;

      const style = edgeStyle(link.relation_type);
      const isAssoc = link.relation_type === "relates_to" || link.relation_type === "co_occurs_with";
      // Mid tier: only the meaningful skeleton (hierarchy/causal/contrast); the
      // ambient association threads wait for the in tier.
      if (globalScale < IN_MIN && isAssoc) return;

      ctx.save();
      ctx.strokeStyle = style.color;
      ctx.lineWidth = Math.max(0.4, style.width * Math.min(2, Math.log(link.weight + 1.5))) / globalScale;
      if (style.dash) ctx.setLineDash(style.dash.map((d) => d / globalScale));

      if (style.centerBreak) {
        // Contrast: the two sides are held apart — a visible gap in the middle.
        const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
        const gap = 0.16;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(s.x + (mx - s.x) * (1 - gap), s.y + (my - s.y) * (1 - gap));
        ctx.moveTo(t.x, t.y);
        ctx.lineTo(t.x + (mx - t.x) * (1 - gap), t.y + (my - t.y) * (1 - gap));
        ctx.stroke();
      } else {
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
      }

      // Directional arrowhead (hierarchy child->parent, causal cause->effect).
      if (style.arrow) {
        const ang = Math.atan2(t.y - s.y, t.x - s.x);
        const tr = nodeRadius(t);
        const ax = t.x - Math.cos(ang) * (tr + 1);
        const ay = t.y - Math.sin(ang) * (tr + 1);
        const head = 5 / globalScale;
        ctx.setLineDash([]);
        ctx.fillStyle = style.color;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax - head * Math.cos(ang - 0.4), ay - head * Math.sin(ang - 0.4));
        ctx.lineTo(ax - head * Math.cos(ang + 0.4), ay - head * Math.sin(ang + 0.4));
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();

      // Edge label HERE is hover-only (boxed white). The always-on relation labels
      // are drawn — collision-culled — in drawOverlays so they never pile onto node
      // text. On hover, any edge (co-occurs included) shows its exact relation.
      if (hoveredEdge?.id === link.id && globalScale > 0.6) {
        const label = link.relation_type;
        const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
        let ang = Math.atan2(t.y - s.y, t.x - s.x);
        if (ang > Math.PI / 2 || ang < -Math.PI / 2) ang += Math.PI; // never upside-down
        const fs = 14.5 / globalScale;
        ctx.save();
        ctx.translate(mx, my);
        ctx.rotate(ang);
        ctx.translate(0, -fs * 0.95); // local +y is perpendicular to the edge
        ctx.font = `${fs}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const w = ctx.measureText(label).width;
        const padX = 2 / globalScale;
        ctx.fillStyle = "rgba(15,23,42,0.92)";
        ctx.fillRect(-w / 2 - padX, -fs / 2 - padX / 2, w + padX * 2, fs + padX);
        ctx.fillStyle = "#ffffff";
        ctx.fillText(label, 0, 0);
        ctx.restore();
      }
    },
    [hoveredEdge],
  );

  if (error) return <Panel><div className="text-rose-400">Error: {error}</div></Panel>;
  if (isLoading && !data) return <Panel><div className="text-slate-400">Loading…</div></Panel>;
  if (!data || data.nodes.length === 0) {
    return <Panel><div className="text-slate-400">
      Your map is empty. Start a chat to seed your first concepts.
    </div></Panel>;
  }

  return (
    <div className="relative flex h-full w-full bg-slate-950">
      {/* touch-action:none hands drag gestures to d3-zoom instead of the page
          scroller — without it mobile can pinch-zoom but never pan. */}
      <div
        className="flex-1 relative overflow-hidden"
        ref={wrapRef}
        style={{ touchAction: "none" }}
      >
        <ForceGraph2D
          ref={fgRef}
          graphData={data}
          {...(dims ? { width: dims.w, height: dims.h } : {})}
          backgroundColor="#020617"
          nodeRelSize={1}
          onRenderFramePre={drawRegions}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D) => {
            // Constant ~14px screen target regardless of zoom (graph units = px / scale),
            // never smaller than the drawn circle — so nodes stay clickable when zoomed out.
            const r = Math.max(nodeRadius(node) + 2, 14 / (zoomRef.current || 1));
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
            ctx.fill();
          }}
          linkCanvasObject={drawLink}
          linkPointerAreaPaint={(link: any, color: string, ctx: CanvasRenderingContext2D) => {
            const s = link.source, t = link.target;
            if (typeof s !== "object" || typeof t !== "object") return;
            ctx.strokeStyle = color;
            ctx.lineWidth = 8;
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
          }}
          onRenderFramePost={drawOverlays}
          onNodeClick={(node: any) => {
            if (isSample) return;   // demo map is read-only
            setSelected(node);
            fgRef.current?.centerAt(node.x, node.y, 600);
            fgRef.current?.zoom(2.6, 600);
          }}
          onLinkHover={(link: any) => setHoveredEdge(link)}
          onNodeHover={(node: any) => setHoveredNode(node)}
          minZoom={0.35}
          maxZoom={8}
          onZoom={(t: any) => { zoomRef.current = t?.k ?? zoomRef.current; }}
          onZoomEnd={(t: any) => {
            // PAN CLAMP: keep the graph reachable. If the layout's centroid has been
            // dragged outside the visible area (plus a margin), ease it back to the
            // nearest in-bounds position instead of letting the user strand
            // themselves on empty canvas.
            const fg = fgRef.current;
            const home = homeRef.current;
            if (!fg || !home || !dims) return;
            const k = t?.k ?? zoomRef.current ?? 1;
            const pt = fg.graph2ScreenCoords?.(home.x, home.y);
            if (!pt) return;
            const marginX = dims.w * 0.5;
            const marginY = dims.h * 0.5;
            const outside =
              pt.x < -marginX || pt.x > dims.w + marginX ||
              pt.y < -marginY || pt.y > dims.h + marginY;
            if (outside) {
              fg.centerAt(home.x, home.y, 350);
              if (k < 0.35 || k > 8) fg.zoom(Math.min(8, Math.max(0.35, k)), 350);
            }
          }}
          onBackgroundClick={(event: any) => {
            setSelected(null);
            // Tap an interpretation overlay (region marker / bridge connector)
            // to focus that insight in the panel. Map advertises, panel delivers.
            const fg = fgRef.current;
            const coords = fg?.screen2GraphCoords?.(event.offsetX, event.offsetY);
            if (!coords || !data?.interpretations?.length) return;
            const cen = centroids();
            let best: any = null, bestD = Infinity;
            for (const it of data.interpretations) {
              let ax: number, ay: number;
              if (it.cluster_ids.length >= 2) {
                const a = cen[it.cluster_ids[0]], b = cen[it.cluster_ids[1]];
                if (!a || !b) continue;
                ax = (a.x + b.x) / 2;
                ay = (a.y + b.y) / 2 - Math.hypot(b.x - a.x, b.y - a.y) * 0.12;
              } else {
                const c = cen[it.cluster_ids[0]];
                if (!c) continue;
                ax = c.x; ay = c.y;
              }
              const d = Math.hypot(coords.x - ax, coords.y - ay);
              if (d < bestD) { bestD = d; best = it; }
            }
            if (best && bestD < 55) {
              window.dispatchEvent(new CustomEvent("focusInsight", { detail: { id: best.id } }));
            }
          }}
          onEngineStop={() => {
            // Open framed on the whole map (all communities), not zoomed into one.
            if (didFitRef.current) return;
            didFitRef.current = true;
            fgRef.current?.zoomToFit(500, 80);
            // Record the settled centre as "home" for the pan clamp + Recenter.
            const ns = (data?.nodes ?? []) as any[];
            if (ns.length) {
              const xs = ns.map((n) => n.x ?? 0), ys = ns.map((n) => n.y ?? 0);
              homeRef.current = {
                x: xs.reduce((a, b) => a + b, 0) / xs.length,
                y: ys.reduce((a, b) => a + b, 0) / ys.length,
                k: zoomRef.current || 1,
              };
            }
          }}
          cooldownTicks={140}
          warmupTicks={50}
          d3AlphaDecay={0.025}
          // Higher velocity damping (Neo4j Browser uses ~0.4) settles the rigid
          // fixed-length layout firmly instead of letting it bounce/jitter.
          d3VelocityDecay={0.4}
        />

        {/* Legend & color-mode toggle — collapsible (it covers the map otherwise,
            especially on mobile), lifted above the mobile community bar.
            Opened, it's 240px wide and reaches past the centre of a phone, where
            the map's "Regions" button sits on the bottom-16 rail — so the open
            panel sits a rail higher (bottom-28) and the two never overlap. The
            collapsed button stays on bottom-16, aligned with Recenter. */}
        {legendOpen ? (
          <div className="absolute bottom-28 md:bottom-4 left-4 bg-slate-900/80 backdrop-blur rounded-lg p-3 pr-7 text-xs text-slate-300 space-y-2 max-w-[240px]">
            <button
              onClick={() => setLegendOpen(false)}
              aria-label="Hide legend"
              className="absolute top-1 right-1.5 text-slate-500 hover:text-slate-200 text-base leading-none"
            >
              ×
            </button>
            <div>
              <div className="font-semibold text-slate-100 mb-1">Edges</div>
              <div className="grid grid-cols-1 gap-0.5 text-[11px] text-slate-400">
                <span><span style={{ color: "#94a3b8" }}>→</span> hierarchy (is-a, part-of)</span>
                <span><span style={{ color: "#f59e0b" }}>→</span> causes</span>
                <span><span style={{ color: "#f43f5e" }}>⊣⊢</span> contrast (held apart)</span>
                <span><span style={{ color: "#94a3b8" }}>┄</span> association / co-occurs</span>
                <span><span style={{ color: "#facc15" }}>✦</span> insight overlay</span>
              </div>
            </div>
            <div className="pt-2 border-t border-slate-700">
              <div className="font-semibold text-slate-100 mb-1">Color by</div>
              <div className="flex flex-wrap gap-1">
                {(["cluster", "valence"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setColorMode(m)}
                    className={`px-2 py-0.5 rounded text-[11px] ${
                      colorMode === m ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
              <div className="text-[10px] text-slate-500 mt-1">Zoom out for communities · in for detail</div>
            </div>
            <div className="pt-2 border-t border-slate-700">
              <button
                onClick={() => setShowCooc((v) => !v)}
                className={`px-2 py-0.5 rounded text-[11px] ${
                  showCooc ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {showCooc ? "✓ " : ""}co-occurrence links
              </button>
              <div className="text-[10px] text-slate-500 mt-1">Faint threads between things you mention together</div>
            </div>
          </div>
        ) : (
          <button
            onClick={() => { setLegendOpen(true); announceMapPanel("legend"); }}
            className="absolute bottom-16 md:bottom-4 left-4 bg-slate-900/80 backdrop-blur rounded-lg px-3 py-1.5 text-xs text-slate-300 hover:text-white border border-slate-700"
          >
            Legend
          </button>
        )}
      </div>

      {/* Pinned to the viewport below the header (h-14), above the Insights panel
          (z-20). Fixed (not flex/absolute) so react-force-graph's fixed-width
          canvas can't push it off-screen and page scroll can't clip its header. */}
      {/* Always-available escape hatch: if the user pans or zooms into empty
          space, one tap re-frames the whole map.
          BOTTOM-right, not top-right: the insights panel owns the top-right and is
          responsive (w-[min(360px,100vw-2rem)]), so it buried this button. Anchoring
          beside the panel would just move the collision to another viewport width —
          the bottom corner is independent of it. bottom-16 on mobile clears the nav,
          matching the legend opposite. */}
      <button
        onClick={recenter}
        className="absolute bottom-16 md:bottom-4 right-4 z-20 bg-slate-900/85 backdrop-blur border border-slate-700 text-slate-300 hover:text-white rounded-lg px-2.5 py-1.5 text-[11px] shadow-lg"
        title="Re-frame the whole map"
      >
        Recenter
      </button>

      {!isSample && selected && (
        <div className="fixed top-14 right-0 bottom-0 z-30 w-full md:w-96 shadow-2xl">
          <MindMapSidePanel node={selected} onClose={() => setSelected(null)} />
        </div>
      )}

      {/* §10 — narrow-viewport navigation: a collapsible, tappable community index
          (mobile only). Hidden while a node's context panel covers the screen. */}
      {!selected && <MapCommunityList clusters={data.clusters} onFocus={focusCluster} />}
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full w-full items-center justify-center bg-slate-950">{children}</div>;
}
