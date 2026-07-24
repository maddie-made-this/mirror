// Mirrors the backend Pydantic schemas. Keep in sync when schemas change.

export type Valence = "positive" | "negative" | "ambivalent" | "neutral";
export type CausalClass = "associative" | "causal" | "counterfactual";
export type KnowledgeSource = "user_stated" | "llm_inferred";
export type RelationType =
  | "is_a" | "part_of" | "has_property" | "co_occurs_with"
  | "relates_to" | "contrasts_with" | "causes";

export interface GraphNode {
  id: string;
  name: string;
  entity_type: string;
  cluster_id?: string | null;

  valence: Valence;
  valence_score: number;        // compat alias for valence_score_last
  valence_score_last: number;
  valence_score_mean: number;
  valence_score_min: number;
  valence_score_max: number;
  salience_score: number;        // compat alias for salience_score_last
  salience_score_last: number;
  salience_score_mean: number;

  mention_count: number;
  spontaneous_mention_count: number;
  stability_score: number;
  knowledge_source: KnowledgeSource;

  // Consolidation (interest-model §2.2): set by the background rule when this
  // configuration has become an autonomous motif.
  motif?: boolean;
  motif_confidence?: number;

  first_session: number;
  last_session: number;
  created_at: string;
  last_mentioned_at: string;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: RelationType;
  causal_class: CausalClass;
  is_directional: boolean;
  is_negated: boolean;
  weight: number;
  proposition_id: string;
  knowledge_source: KnowledgeSource;
  first_session: number;
  last_session: number;
}

export interface Mention {
  id: string;
  user_id: string;
  conversation_id: string;
  message_id: string;
  proposition_id: string;
  session_number: number;
  text: string;
  predicate: string;
  valence: Valence;
  valence_score: number;
  salience_score: number;
  confidence: number;
  knowledge_source: KnowledgeSource;
  created_at: string;
}

export interface Proposition {
  id: string;
  subject: string;
  predicate: string;
  object: string;
  source_span: string;
  confidence: number;
  subject_entity_type: string;
  object_entity_type: string;
  valence: Valence;
  valence_score: number;
  salience_score: number;
  causal_class: CausalClass;
  subject_knowledge_source: KnowledgeSource;
  object_knowledge_source: KnowledgeSource;
}

// Director→renderer split (Part B). Mirrors backend schemas/piece_brief.py.
export interface PieceRegister {
  vividness: string;
  prose_density: string;
  person_tense: string;
  emphasis: string;
}

export interface PieceFrame {
  subject_pov: string;
  subjects: string;
  context: string;
  current_section: string;
}

export interface PieceBrief {
  action: "ask" | "write" | "ask_then_write";
  question: string | null;
  advance_directive: string;
  do_not_repeat: string[];
  prerequisites_to_establish: string[];
  function_to_serve: string;
  delivery: PieceRegister;
  piece_frame: PieceFrame;
  pacing: "early" | "mid" | "deep";
  interest_anchor: string;
  hard_avoid: string[];
}

export interface PromptContext {
  system_layers: Record<string, string | null>;
  history_messages: { role: string; content: string }[];
  user_message: string;
  model: string;
  temperature: number;
  // Split mode (Part B): the director debug breakdown also carries the emitted
  // brief, the renderer tier, and a stage marker.
  brief?: PieceBrief | null;
  renderer_model?: string;
  stage?: string;
}

export interface MessageResponse {
  message_id: string;
  conversation_id: string;
  session_number: number;
  response_text: string;
  propositions: Proposition[];
  propositions_skipped?: Proposition[];
  nodes_created: GraphNode[];
  nodes_updated: GraphNode[];
  edges_created: GraphEdge[];
  edges_updated: GraphEdge[];
  prompt_context?: PromptContext | null;
  // Part B: the director's PieceBrief for this turn (split + debug only).
  piece_brief?: PieceBrief | null;
}

export interface ClusterInfo {
  id: string;
  label: string;
  size: number;
}

export interface Chip {
  kind: "advance" | "regenerate" | "wildcard" | string;
  label: string;
  instruction: string;
}

export type InterpretationKind =
  | "pattern" | "tension" | "bridge" | "function" | "behavioral" | "stylistic"
  | "origin" | "dynamics" | "belief" | "reframing"
  | "angle"; // tier-2 — the felt character a cluster takes for this user

// --- Interest-model readings (the explanation product, §8) ---

export interface Reading {
  id: string;
  kind: string;
  statement: string;
  category: string;
  confidence: number;
  status: string;
  what_would_change_this: string;
  evidence_quotes: string[];
  // kind=origin
  origin_distribution?: {
    innate: number;
    learned_episodic: number;
    reframing_consolidated: number;
  };
  origin_episode?: string;
  // kind=reframing
  belief_statement?: string;
  // kind=belief
  presses_on?: string[];
  context_sensitivity?: number;
}

export interface NodeReadings {
  headline: string;
  angle: Reading[];      // tier-2 — sits between the tier-1 headline and tier-3 readings
  origin: Reading[];
  function: Reading[];
  dynamics: Reading[];
  reframing: Reading[];
  beliefs: Reading[];
  other: Reading[];
}

// One row of the episodic "Memories" page (user-wide verbatim record).
export interface UserMention {
  id: string;
  text: string;
  predicate: string;
  valence_score: number;
  salience_score: number;
  session_number: number;
  conversation_id: string;
  created_at: string;
  nodes: { id: string; name: string; entity_type: string }[];
}

// One row of the semantic "Understanding" page (the map's list twin).
export interface UnderstandingNode {
  id: string;
  name: string;
  entity_type: string;
  mention_count: number;
  salience: number;
  motif: boolean;
  motif_confidence: number;
  cluster_id: string | null;
  readings: {
    id: string;
    kind: string;
    statement: string;
    confidence: number;
    status: string;
  }[];
}

export interface Interpretation {
  id: string;
  statement: string;
  kind: InterpretationKind;
  inferential_step: string;
  confidence: number;
  status: string;
  attached_node_ids: string[];
  attached_cluster_ids: string[];
}

export interface OverlayInterpretation {
  id: string;
  statement: string;
  kind: string;
  confidence: number;
  cluster_ids: string[];
}

export interface ClusterSimilarity {
  a: string;
  b: string;
  score: number;
}

export interface CooccurrenceEdge {
  source_id: string;
  target_id: string;
  weight: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters?: ClusterInfo[];
  interpretations?: OverlayInterpretation[];
  cluster_similarity?: ClusterSimilarity[];
  cooccurrence?: CooccurrenceEdge[];
}
