import type { NodeReadings, Reading } from "@/types/graph";

// Read-side collapse for duplicate readings.
//
// Reclustering can leave two live interpretations that say the exact same thing.
// The write-side dedup (tier_2_matcher._find_existing_angle) matches on angle_key
// plus member-node overlap >= 0.6, so when a cluster's membership drifts far
// enough between runs the same angle is classified fresh and both rows survive.
// The panel then shows the identical sentence twice with different confidences.
//
// This collapses them where they're displayed. It does NOT fix the write path —
// the durable fix is containment-based matching rather than symmetric overlap.
//
// Which copy survives matters: an affirmed reading carries the user's own
// feedback, so it always wins over an unaffirmed one regardless of confidence.
// Keeping "the newest" or "the highest confidence" alone would silently discard
// that signal.
const STATUS_RANK: Record<string, number> = { affirmed: 3, qualified: 2, candidate: 1 };

// The minimum a reading needs for collapse. Kept structural so both the map
// panel's full Reading and the Understanding page's narrower row can use this.
type CollapsibleReading = {
  statement: string;
  confidence: number;
  status: string;
  angle_key?: string;
};

function rank(r: CollapsibleReading): number {
  return STATUS_RANK[r.status] ?? 0;
}

/** Identity of a reading for collapse purposes: the stable angle key when the
 *  backend supplies one, else the visible sentence — which is what "duplicate"
 *  means to someone looking at the panel. */
function identity(r: CollapsibleReading): string {
  return r.angle_key
    ? `k:${r.angle_key}`
    : `s:${r.statement.trim().toLowerCase()}`;
}

/** Collapse same-identity readings, keeping affirmed first, then highest
 *  confidence. Order of first appearance is preserved. */
export function collapseReadings<T extends CollapsibleReading>(readings: T[]): T[] {
  const best = new Map<string, T>();
  for (const r of readings) {
    const id = identity(r);
    const prev = best.get(id);
    if (
      !prev ||
      rank(r) > rank(prev) ||
      (rank(r) === rank(prev) && r.confidence > prev.confidence)
    ) {
      best.set(id, r);
    }
  }
  return Array.from(best.values());
}

/** Apply the collapse to every reading list on a node. */
export function collapseNodeReadings(r: NodeReadings): NodeReadings {
  return {
    ...r,
    angle: collapseReadings(r.angle),
    origin: collapseReadings(r.origin),
    function: collapseReadings(r.function),
    dynamics: collapseReadings(r.dynamics),
    reframing: collapseReadings(r.reframing),
    beliefs: collapseReadings(r.beliefs),
    other: collapseReadings(r.other),
  };
}
