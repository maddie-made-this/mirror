import type { ForceGraphData } from "@/hooks/useGraphData";
import type { GraphNode, GraphEdge } from "@/types/graph";

/**
 * A small, entirely fictional graph for the signed-out landing page.
 *
 * The homepage claims the product builds "a knowledge graph of your recurring
 * themes, the angles you take on them, and what connects them" — but every real
 * feature page is auth-gated, so a visitor could not otherwise see the claim
 * demonstrated. This dataset is the proof directly under the claim.
 *
 * It is STATIC: no auth, no backend call, no real account.
 *
 * THREE THINGS THIS DATA HAS TO GET RIGHT, or the sample undersells the engine:
 *
 * 1. The nodes must read as a PERSON, not a syllabus. An extraction pass over
 *    someone actually talking does not produce "consistency models" — it produces
 *    the outage they keep returning to, the thing they refuse to do in review,
 *    the tension they cannot resolve. Hence the spread of entity types: memory,
 *    tension, belief, goal, preference. A graph of nothing but `concept` nodes is
 *    a glossary, and reads like one.
 *
 * 2. An angle must be a claim about the person, not about the subject. Two ways
 *    to get this wrong. "debugging → chasing an anomaly" is a synonym for the
 *    label, so the classifier looks like a relabeler. Subtler and just as dead:
 *    "API design → inhabiting another mind" is true of API design for everyone
 *    who has ever designed one. A real angle is something you could disagree with.
 *
 * 3. The conclusions must look like what the engine actually emits — typed,
 *    sourced, confidence-scored, and mostly sentence-length. A tier-2 angle's
 *    `statement` really is the short vocabulary name (services/tier_2_matcher.py
 *    sets `statement=entry.name`), but it ships alongside `inferential_step`, and
 *    the other kinds — bridge, function, tension, origin — are full sentences.
 *    Showing only the bare two-word names made the output look thin.
 *
 * The driver here is a distrust of the stated version of things. The payoff is
 * where it recurs: the March outage and code review come back with the SAME
 * angle, and a BRIDGE connects them explicitly. A postmortem and a pull-request
 * description are both confident written accounts, and this person goes around
 * both to the raw artifact. Nothing about either activity requires that — which
 * is what makes it a claim about them.
 */

const NOW = "2026-01-01T00:00:00Z";

// Defaults for the fields the renderer reads but the demo doesn't vary.
//
// `valence` is real per-node, not a constant. The map's "colour by valence" mode
// is a live toggle on this data, and the tension insight claims two nodes carry
// OPPOSITE valence — with everything hardcoded positive, flipping the toggle
// would flatly contradict the caption sitting under the map.
function node(
  id: string,
  name: string,
  entity_type: string,
  cluster_id: string,
  salience: number,
  mentions: number,
  valence: number,
  extra: Partial<GraphNode> = {},
): GraphNode {
  return {
    id,
    name,
    entity_type,
    cluster_id,
    valence: valence > 0.2 ? "positive" : valence < -0.2 ? "negative" : "ambivalent",
    valence_score: valence,
    valence_score_last: valence,
    valence_score_mean: valence,
    valence_score_min: Math.max(-1, valence - 0.25),
    valence_score_max: Math.min(1, valence + 0.25),
    salience_score: salience,
    salience_score_last: salience,
    salience_score_mean: salience,
    mention_count: mentions,
    spontaneous_mention_count: Math.max(1, Math.floor(mentions / 2)),
    stability_score: 0.6,
    knowledge_source: "user_stated",
    first_session: 1,
    last_session: 6,
    created_at: NOW,
    last_mentioned_at: NOW,
    ...extra,
  };
}

function edge(
  id: string,
  source_id: string,
  target_id: string,
  relation_type: GraphEdge["relation_type"],
  weight = 0.7,
): GraphEdge & { source: string; target: string } {
  return {
    id,
    source_id,
    target_id,
    source: source_id,
    target: target_id,
    relation_type,
    causal_class: "associative",
    is_directional: true,
    is_negated: false,
    weight,
    proposition_id: `p:${id}`,
    knowledge_source: "user_stated",
    first_session: 1,
    last_session: 6,
  };
}

const C_OUTAGE = "cluster:outage";
const C_REVIEW = "cluster:review";
const C_NAMING = "cluster:naming";
const C_CAREER = "cluster:career";

const nodes: GraphNode[] = [
  // Theme 1 — the March outage
  node("n:march-outage", "the March outage", "memory", C_OUTAGE, 0.79, 17, -0.5, { motif: true, motif_confidence: 0.86 }),
  node("n:retry-storm", "the retry storm", "concept", C_OUTAGE, 0.63, 11, -0.4),
  node("n:blameless-postmortems", "blameless postmortems", "belief", C_OUTAGE, 0.55, 8, 0.5),

  // Theme 2 — code review
  node("n:diff-before-description", "reading the diff before the description", "preference", C_REVIEW, 0.66, 12, 0.45),
  node("n:nitpick-or-wave", "nitpicking vs waving it through", "tension", C_REVIEW, 0.58, 9, 0.0),
  node("n:new-hire-pr", "the new hire's first PR", "memory", C_REVIEW, 0.5, 7, 0.3),

  // Theme 3 — naming and docs
  node("n:renaming-later", "renaming things months later", "pattern", C_NAMING, 0.68, 13, 0.15, { motif: true, motif_confidence: 0.78 }),
  node("n:docs-nobody-reads", "docs nobody reads", "tension", C_NAMING, 0.6, 10, -0.45),
  node("n:errors-as-docs", "error messages as documentation", "belief", C_NAMING, 0.64, 11, 0.55),

  // Theme 4 — staying technical. The valences here are load-bearing: the tension
  // insight rests on these two pulling opposite ways, so the goal is positive and
  // the job posting negative. Flip to "colour by valence" and the split is visible.
  node("n:stay-hands-on", "wanting to stay hands-on", "goal", C_CAREER, 0.72, 14, 0.6, { motif: true, motif_confidence: 0.81 }),
  node("n:staff-posting", "the staff engineer posting", "memory", C_CAREER, 0.48, 6, -0.35),
  node("n:meetings-morning", "meetings eating the morning", "tension", C_CAREER, 0.57, 9, -0.55),
];

const links = [
  // within themes
  edge("e1", "n:retry-storm", "n:march-outage", "causes", 0.8),
  edge("e2", "n:blameless-postmortems", "n:march-outage", "relates_to", 0.62),
  edge("e3", "n:diff-before-description", "n:nitpick-or-wave", "relates_to", 0.6),
  edge("e4", "n:new-hire-pr", "n:diff-before-description", "relates_to", 0.55),
  edge("e5", "n:renaming-later", "n:docs-nobody-reads", "causes", 0.58),
  edge("e6", "n:errors-as-docs", "n:docs-nobody-reads", "contrasts_with", 0.66),
  edge("e7", "n:staff-posting", "n:stay-hands-on", "contrasts_with", 0.74),
  edge("e8", "n:meetings-morning", "n:stay-hands-on", "contrasts_with", 0.6),

  // ACROSS themes — kept to FOUR on purpose. Every cross-link is an attractive
  // force in the sim, so a denser set pulls the four clusters into one blob and
  // the map stops reading as themes at all.
  edge("e9", "n:errors-as-docs", "n:march-outage", "relates_to", 0.55),
  edge("e10", "n:new-hire-pr", "n:docs-nobody-reads", "relates_to", 0.5),
  edge("e11", "n:meetings-morning", "n:nitpick-or-wave", "relates_to", 0.45),
  edge("e12", "n:stay-hands-on", "n:march-outage", "relates_to", 0.48),
];

// Tier-2 angle overlays for the MAP. Keys are real entries in the curated
// vocabulary, and `statement` is the canonical name because that is literally
// what the matcher stores (tier_2_matcher.py: statement=entry.name).
// NOTE: typed against OverlayInterpretation deliberately (no `as` cast) — the
// field is `cluster_ids`, and an invented shape here crashes the renderer.
const interpretations: ForceGraphData["interpretations"] = [
  {
    id: "i:angle-outage",
    kind: "angle",
    statement: "seeing through the official story",
    confidence: 0.78,
    cluster_ids: [C_OUTAGE],
  },
  {
    id: "i:angle-review",
    kind: "angle",
    statement: "seeing through the official story",
    confidence: 0.7,
    cluster_ids: [C_REVIEW],
  },
  {
    id: "i:angle-naming",
    kind: "angle",
    statement: "making the unspoken explicit",
    confidence: 0.71,
    cluster_ids: [C_NAMING],
  },
  {
    id: "i:angle-career",
    kind: "angle",
    statement: "holding two opposed ideas",
    confidence: 0.69,
    cluster_ids: [C_CAREER],
  },
];

/**
 * What the landing page shows under "What it concluded" — the typed insight set,
 * shaped like real :Interpretation rows (kind, statement, inferential_step,
 * confidence) so it matches what InsightsPanel renders for a signed-in user.
 * The real panel also offers affirm/reject/qualify; those need an account, so the
 * sample is read-only.
 */
export type SampleInsight = {
  id: string;
  kind: string;
  statement: string;
  inferential_step: string;
  confidence: number;
  cluster_ids: string[];
};

export const SAMPLE_INSIGHTS: SampleInsight[] = [
  {
    id: "s:angle-outage",
    kind: "angle",
    statement: "seeing through the official story",
    inferential_step:
      'anchored on "the March outage" and "blameless postmortems" — the write-up is treated as an account to get behind, not a record to accept.',
    confidence: 0.78,
    cluster_ids: [C_OUTAGE],
  },
  {
    id: "s:angle-review",
    kind: "angle",
    statement: "seeing through the official story",
    inferential_step:
      'anchored on "reading the diff before the description" — same move, applied to their own process.',
    confidence: 0.7,
    cluster_ids: [C_REVIEW],
  },
  {
    id: "s:tension",
    kind: "tension",
    statement:
      "Wanting to stay hands-on and the staff engineer posting pull in opposite directions, and neither has given way.",
    inferential_step:
      "both surface in the same conversations, with opposite valence and no resolution across six sessions.",
    confidence: 0.64,
    cluster_ids: [C_CAREER],
  },
];

const clusters: ForceGraphData["clusters"] = [
  { id: C_OUTAGE, label: "the March outage", size: 3 },
  { id: C_REVIEW, label: "code review", size: 3 },
  { id: C_NAMING, label: "naming and docs", size: 3 },
  { id: C_CAREER, label: "staying technical", size: 3 },
];

// Which themes sit near each other on the map. The outage and code review are
// closest — they share an angle, and cluster similarity is computed over the same
// signal the classifier reads.
const clusterSimilarity: ForceGraphData["clusterSimilarity"] = [
  { a: C_OUTAGE, b: C_REVIEW, score: 0.63 },
  { a: C_NAMING, b: C_REVIEW, score: 0.44 },
  { a: C_OUTAGE, b: C_NAMING, score: 0.36 },
];

// Co-occurrence: things mentioned in the same breath WITHOUT an extracted
// semantic relation between them. Render-only — never fed to the force sim, so
// they never distort layout; they draw as faint threads behind the nodes. Showing
// them marks the distinction between "the engine inferred a relationship" and
// "these just keep turning up together".
const cooccurrence = [
  { source_id: "n:retry-storm", target_id: "n:renaming-later", weight: 0.34 },
  { source_id: "n:blameless-postmortems", target_id: "n:new-hire-pr", weight: 0.38 },
  { source_id: "n:staff-posting", target_id: "n:docs-nobody-reads", weight: 0.29 },
  { source_id: "n:nitpick-or-wave", target_id: "n:errors-as-docs", weight: 0.42 },
];

export const SAMPLE_GRAPH: ForceGraphData = {
  nodes,
  links,
  clusters,
  interpretations,
  clusterSimilarity,
  cooccurrence,
};
