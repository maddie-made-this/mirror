import json
import logging
import re
from uuid import UUID, uuid5

from pydantic import ValidationError

from config.loader import APP_CONFIG
from core.errors import ExtractionError
from llm.client import chat
from llm.prompts import build_extraction_messages, build_reflection_messages
from schemas.enums import KnowledgeSource, SubjectKind
from schemas.extraction import Proposition
from schemas.graph import GraphEdge, GraphNode, Mention
from services import dedup, embedding, graph_service
from services.maintenance import mark_user_dirty

logger = logging.getLogger(__name__)

# Surface forms that always resolve to the user's self-node.
SELF_REFERENCE_TERMS: frozenset[str] = frozenset({
    "i", "me", "myself", "my", "the user", "user", "self",
})


def is_self_reference(name: str, user_display_name: str) -> bool:
    """True if `name` is a self-reference term or matches the user's display name."""
    n = name.strip().lower()
    if n in SELF_REFERENCE_TERMS:
        return True
    if user_display_name and n == user_display_name.strip().lower():
        return True
    return False


# Contentless-node gate (insight-synthesis spec C2). A curated denylist + an
# all-function-words check — NOT a POS filter — so concrete one-word concepts
# ("recursion", "counterpoint", "entropy", "minimalism", "provenance") always pass; the
# junk the dumps surfaced ("not", "by me", "the experience", "urgently", "huge") does
# not. Errs toward keeping. Extend the lists as new junk appears.
_STOPWORD_NODES = {
    "not", "by", "for", "the", "a", "an", "it", "this", "that", "is", "are",
    "by me", "for the user", "to me", "of it", "for it", "the experience",
    "the situation", "this thing",
}
_BARE_MODIFIERS = {
    "huge", "nice", "intense", "urgently", "felt strongly", "experienced",
    "isn't endless", "really", "very", "just",
}
_FUNCTION_WORDS = {
    "by", "for", "to", "of", "the", "a", "an", "it", "this", "that",
    "me", "him", "her", "them", "my", "his", "i", "is", "are", "was",
}


def _is_contentless_node(name: str) -> bool:
    """True for a purely non-referential surface (function words / bare modifier /
    fragment). A single concrete noun is never in the denylist and never
    all-function-words, so it passes."""
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not n:
        return True
    if n in _STOPWORD_NODES or n in _BARE_MODIFIERS:
        return True
    toks = n.split()
    return bool(toks) and all(t in _FUNCTION_WORDS for t in toks)


async def resolve_node_identity(
    candidate_name: str,
    candidate_entity_type: str,
    candidate_embedding: list[float],
    user_id: UUID,
    user_display_name: str,
    self_node_id: str,
    allow_self: bool = True,
) -> str | None:
    """
    Decide whether to merge a candidate into an existing node or create a new one.

    Resolution order:
      1. Self-reference terms / user's display name → canonical self_node_id
         (ONLY when allow_self — the subject-attribution firewall short-circuits
         this for a non-user subject, §7: a real_person/character must never
         resolve onto the user's self-node, even if its surface form looks
         self-referential).
      2. Semantic cluster match within cluster_threshold → most similar existing node.
      3. None → caller creates a fresh node with the proposed id.
    """
    if allow_self and is_self_reference(candidate_name, user_display_name):
        return self_node_id

    hits = await dedup.find_similar_nodes(
        candidate_embedding, user_id,
        threshold=APP_CONFIG.cluster_threshold,
        limit=3,
    )
    if hits:
        # Qdrant returns sorted by score desc; highest similarity wins.
        return hits[0].canonical_id

    return None


def _strip_code_fence(raw: str) -> str:
    """
    Claude wraps JSON in a ```json ... ``` markdown fence even when told not to
    (it does not honour OpenRouter's json_object response_format). Strip the
    fence so json.loads can parse the payload.
    """
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]  # drop the opening ``` / ```json line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# Tokens that carry no semantic weight when they're the *entire* predicate.
_STOP_PREDICATES: frozenset[str] = frozenset({
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had",
    "do", "does", "did",
})


def normalize_predicate(raw: str) -> str:
    """
    Canonical form for an edge predicate.

    Strips surrounding whitespace and punctuation, collapses internal whitespace,
    and lowercases. Voice and tense are intentionally preserved — "hurt" stays
    distinct from "was hurt by", "fears" from "used to fear". This removes noise,
    never meaning. Replaces the old vector-similarity edge-label dedup for MVP.
    """
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.lower()
    s = s.strip(".,;:!?\"'")
    return s or raw.strip().lower()  # fallback: never return an empty string


def _salvage_objects(raw: str) -> list[dict]:
    """
    Recover complete top-level {...} JSON objects from a (likely truncated) string.

    A capped/truncated completion produces invalid JSON — e.g.
    '{"propositions":[{...},{...},{"subject":"ha' — but the proposition objects
    that DID finish are still intact. Scan brace depth (ignoring braces inside
    strings) and json.loads each balanced object, keeping the ones that parse.
    Lets a truncated extraction yield its completed propositions instead of zero.
    """
    s = _strip_code_fence(raw)
    objs: list[dict] = []
    stack: list[int] = []   # start index of each open brace, at any nesting depth
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            try:
                obj = json.loads(s[start : i + 1])
                if isinstance(obj, dict):
                    objs.append(obj)
            except json.JSONDecodeError:
                pass
    # The proposition objects are nested inside the (truncated, unclosed) wrapper,
    # so capture balanced {...} at ANY depth, then keep only proposition-shaped dicts.
    return [o for o in objs if any(k in o for k in ("subject", "predicate", "object"))]


def _parse_propositions_json(raw: str) -> list[dict]:
    """
    Parse a raw LLM JSON response into a list of proposition dicts.
    Accepts both {"propositions": [...]} and a bare [...] array. If the payload is
    invalid (typically a token-cap truncation), salvage any complete proposition
    objects before giving up; raise ExtractionError only if nothing is recoverable.
    """
    try:
        data = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        salvaged = _salvage_objects(raw)
        if salvaged:
            logger.warning(
                "Extraction JSON invalid (likely truncated); salvaged objects",
                extra={"salvaged": len(salvaged), "error": str(exc)},
            )
            return salvaged
        logger.error(
            "Extraction parse failure",
            extra={"raw_output": raw, "error": str(exc)},
        )
        raise ExtractionError("Could not parse extraction response") from exc

    if isinstance(data, dict):
        return data.get("propositions", [])
    if isinstance(data, list):
        return data
    return []


def _build_propositions(items: list[dict]) -> list[Proposition]:
    """
    Build Proposition objects from raw dicts, dropping (and logging) any item
    that fails validation. One malformed item never discards the good ones.
    """
    propositions: list[Proposition] = []
    for item in items:
        try:
            propositions.append(Proposition(**item))
        except (ValidationError, TypeError) as exc:
            logger.warning(
                "Dropping malformed proposition",
                extra={"item": item, "error": str(exc)},
            )
    return propositions


async def extract_propositions(
    message: str,
    active_nodes: list[GraphNode],
    active_predicates: list[str],
    *,
    conversation_id: UUID,
    message_id: UUID,
) -> list[Proposition]:
    """
    Two-pass extraction:
      Pass 1 — literal Subject-Predicate-Object triples (what was said).
      Pass 2 — the implied layer: tensions, recurring themes, underlying needs
               (only when reflection_system_prompt is configured).

    Both passes return {"propositions": [...]}; a bare array is still accepted.
    Injects conversation_id / message_id provenance into every proposition —
    the LLM never produces those fields.
    """
    # --- Pass 1: literal SPO triples ---
    # Extraction is best-effort graph enrichment — a parse failure must NEVER
    # fail the user's message (it used to raise -> 422). Degrade to no propositions
    # for this turn; the response still goes out and the graph just doesn't grow.
    pass1_messages = build_extraction_messages(message, active_nodes, active_predicates)
    raw1 = await chat(
        pass1_messages,
        model=APP_CONFIG.extraction_model_resolved,
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=APP_CONFIG.utility_max_tokens,
    )
    try:
        pass1_items = _parse_propositions_json(raw1)
    except ExtractionError:
        logger.warning("Pass 1 extraction unparseable; skipping graph growth this turn")
        return []
    propositions = _build_propositions(pass1_items)

    # --- Pass 2: reflection / implied layer (only if configured) ---
    # Pass the active nodes so pass-2 grounds inferences in existing concepts (§8).
    pass2_messages = build_reflection_messages(message, pass1_items, active_nodes)
    if pass2_messages:
        try:
            raw2 = await chat(
                pass2_messages,
                model=APP_CONFIG.extraction_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.2,  # slightly higher — inference needs flexibility
                max_tokens=APP_CONFIG.utility_max_tokens,
            )
            pass2_items = _parse_propositions_json(raw2)
            propositions += _build_propositions(pass2_items)
        except ExtractionError:
            # Pass 2 is additive — a reflection failure must not discard Pass 1.
            logger.warning("Reflection pass failed; continuing with Pass 1 only")

    # Provenance is guaranteed by the caller, not the LLM.
    for prop in propositions:
        prop.source_conversation_id = conversation_id
        prop.source_message_id = message_id

    return propositions


def _qdrant_point_id(node_id: str, user_id: UUID) -> str:
    """
    Deterministic Qdrant point ID derived from (node_id, user_id).
    Ensures upsert is truly idempotent — re-ingesting the same node never
    creates a duplicate Qdrant point.
    """
    return str(uuid5(user_id, node_id))


def _sanitize_entity_type(raw: str) -> str:
    """Map invalid entity types to 'concept' rather than crashing the ingest loop."""
    if raw not in APP_CONFIG.entity_types:
        logger.warning(
            "Invalid entity_type from LLM, falling back to 'concept'",
            extra={"raw_entity_type": raw},
        )
        return "concept"
    return raw


async def ingest_propositions(
    propositions: list[Proposition],
    user_id: UUID,
    session_number: int,
    active_node_ids: list[str] | None = None,
    user_display_name: str = "",
    self_node_id: str | None = None,
    depth_ramp: str = "",
) -> tuple[
    list[GraphNode], list[GraphNode], list[GraphEdge], list[GraphEdge],
    list[Proposition], set[str],
]:
    """
    For each proposition: resolve identity → upsert or bump nodes, upsert edge and
    mention into Neo4j → store vectors.

    Returns (nodes_created, nodes_updated, edges_created, edges_updated,
             propositions_skipped, touched_node_ids).

    Identity resolution (self-reference and cluster merge) runs before any DB
    write so propositions that refer to the same concept collapse to one canonical
    node. Low-confidence propositions are filtered first (H). All four Neo4j writes
    per proposition are one atomic transaction (I).
    """
    from qdrant_client.models import PointStruct

    from db.neo4j import get_tx
    from db.qdrant import get_client

    nodes_created: list[GraphNode] = []
    nodes_updated: list[GraphNode] = []
    edges_created: list[GraphEdge] = []
    edges_updated: list[GraphEdge] = []
    skipped: list[Proposition] = []
    touched_node_ids: set[str] = set()

    if not propositions:
        return nodes_created, nodes_updated, edges_created, edges_updated, skipped, touched_node_ids

    active_ids_set = set(active_node_ids or [])

    # H: confidence gating — filter before embedding so we don't pay for skips.
    kept: list[Proposition] = []
    for prop in propositions:
        if _is_contentless_node(prop.subject) or _is_contentless_node(prop.object):
            # C2: a triple whose subject or object is a pure function-word/fragment
            # ("not", "by me", "the experience") yields a junk node + edge. Drop it
            # before embedding. Concrete one-word concepts are never contentless.
            logger.info(
                "Skipping contentless-node proposition",
                extra={"prop_id": str(prop.id),
                       "subject": prop.subject, "object": prop.object},
            )
            skipped.append(prop)
        elif prop.confidence < APP_CONFIG.min_ingest_confidence:
            logger.info(
                "Skipping low-confidence proposition",
                extra={"prop_id": str(prop.id), "confidence": prop.confidence},
            )
            skipped.append(prop)
        else:
            kept.append(prop)

    if not kept:
        return nodes_created, nodes_updated, edges_created, edges_updated, skipped, touched_node_ids

    # One batched embedding call for all subject + object texts.
    all_texts: list[str] = []
    for prop in kept:
        all_texts.extend([prop.subject, prop.object])
    all_embeddings = await embedding.embed_batch(all_texts)

    for i, prop in enumerate(kept):
        try:
            subj_emb = all_embeddings[i * 2]
            obj_emb = all_embeddings[i * 2 + 1]

            subj_type = _sanitize_entity_type(prop.subject_entity_type or "concept")
            obj_type = _sanitize_entity_type(prop.object_entity_type or "concept")

            proposed_subj_id = graph_service.make_node_id(subj_type, prop.subject)
            proposed_obj_id = graph_service.make_node_id(obj_type, prop.object)

            # --- Cluster-aware identity resolution ---
            # Returns an existing node_id (self-ref or cluster match) or None (new node).
            # Firewall (§7): a non-user subject must NEVER resolve to the self-node,
            # even if its surface form looks self-referential. The object may still
            # be the user (e.g. "my mother criticized me" — mother->criticized->user
            # is a real biographical edge), so only the subject is gated.
            resolved_subj_id = await resolve_node_identity(
                prop.subject, subj_type, subj_emb,
                user_id, user_display_name, self_node_id or "",
                allow_self=(prop.subject_kind == SubjectKind.USER),
            )
            subj_id = resolved_subj_id if resolved_subj_id is not None else proposed_subj_id

            resolved_obj_id = await resolve_node_identity(
                prop.object, obj_type, obj_emb,
                user_id, user_display_name, self_node_id or "",
            )
            obj_id = resolved_obj_id if resolved_obj_id is not None else proposed_obj_id

            subj_spontaneous = proposed_subj_id not in active_ids_set
            obj_spontaneous = proposed_obj_id not in active_ids_set

            subj_node = GraphNode(
                id=subj_id,
                name=prop.subject,
                entity_type=subj_type,
                valence=prop.valence,
                valence_score=prop.valence_score,
                salience_score=prop.salience_score,
                knowledge_source=prop.subject_knowledge_source,
                prov_source=prop.prov_source,
                prov_authorship=prop.prov_authorship,
                prov_format=prop.prov_format,
                prov_elicited=prop.prov_elicited,
                # Firewall tag: the subject node carries its subject kind/ref so a
                # real_person/character is stored distinct from the self-model and
                # is queryable for legibility ("that was your character, not you").
                subject_kind=prop.subject_kind,
                subject_ref=prop.subject_ref,
                based_on_ref=prop.based_on_ref,
                first_session=session_number,
                last_session=session_number,
            )
            obj_node = GraphNode(
                id=obj_id,
                name=prop.object,
                entity_type=obj_type,
                valence=prop.valence,
                valence_score=prop.valence_score,
                salience_score=prop.salience_score,
                knowledge_source=prop.object_knowledge_source,
                prov_source=prop.prov_source,
                prov_authorship=prop.prov_authorship,
                prov_format=prop.prov_format,
                prov_elicited=prop.prov_elicited,
                first_session=session_number,
                last_session=session_number,
            )

            # The edge is keyed by the closed-taxonomy relation_type; the natural
            # phrase (normalized) is preserved on the Mention below.
            rel_label = normalize_predicate(prop.predicate)
            edge = GraphEdge(
                source_id=subj_id,
                target_id=obj_id,
                relation_type=prop.relation_type,
                causal_class=prop.causal_class,
                proposition_id=prop.id,
                knowledge_source=prop.subject_knowledge_source,
                first_session=session_number,
                last_session=session_number,
            )

            mention = Mention(
                user_id=user_id,
                conversation_id=prop.source_conversation_id,
                message_id=prop.source_message_id,
                proposition_id=prop.id,
                session_number=session_number,
                text=prop.source_span,
                predicate=rel_label,
                valence=prop.valence,
                valence_score=prop.valence_score,
                salience_score=prop.salience_score,
                confidence=prop.confidence,
                knowledge_source=prop.subject_knowledge_source,
                prov_source=prop.prov_source,
                prov_authorship=prop.prov_authorship,
                prov_format=prop.prov_format,
                prov_elicited=prop.prov_elicited,
                # Ramp position when said — deep-ramp mentions are
                # motif-formation moments (consolidation §2.2).
                depth_ramp=depth_ramp,
            )

            # I: subject + object + edge + mention writes are one atomic unit.
            async with get_tx() as tx:
                if resolved_subj_id is not None:
                    # Merging into existing node — bump aggregates only.
                    # The canonical name is preserved; this mention's surface form
                    # is captured in the Mention node's text field.
                    subj_node = await graph_service.bump_node_aggregates_tx(
                        tx, subj_id, user_id,
                        valence=prop.valence_score,
                        salience=prop.salience_score,
                        valence_enum=prop.valence.value,
                        session_number=session_number,
                        spontaneous=subj_spontaneous,
                    )
                    subj_created = False
                else:
                    subj_node, subj_created = await graph_service.upsert_node(
                        tx, subj_node, user_id, spontaneous=subj_spontaneous
                    )

                if resolved_obj_id is not None:
                    obj_node = await graph_service.bump_node_aggregates_tx(
                        tx, obj_id, user_id,
                        valence=prop.valence_score,
                        salience=prop.salience_score,
                        valence_enum=prop.valence.value,
                        session_number=session_number,
                        spontaneous=obj_spontaneous,
                    )
                    obj_created = False
                else:
                    obj_node, obj_created = await graph_service.upsert_node(
                        tx, obj_node, user_id, spontaneous=obj_spontaneous
                    )

                edge, edge_created = await graph_service.upsert_edge(tx, edge, user_id)
                await graph_service.create_mention(tx, mention, subj_id, obj_id)

            touched_node_ids.add(subj_id)
            touched_node_ids.add(obj_id)

            (nodes_created if subj_created else nodes_updated).append(subj_node)
            (nodes_created if obj_created else nodes_updated).append(obj_node)
            (edges_created if edge_created else edges_updated).append(edge)

            # Qdrant vectors — outside the Neo4j tx, only for newly-created nodes.
            if subj_created:
                await get_client().upsert(
                    collection_name=APP_CONFIG.node_collection,
                    points=[PointStruct(
                        id=_qdrant_point_id(subj_id, user_id),
                        vector=subj_emb,
                        payload={"node_id": subj_id, "user_id": str(user_id)},
                    )],
                )
            if obj_created:
                await get_client().upsert(
                    collection_name=APP_CONFIG.node_collection,
                    points=[PointStruct(
                        id=_qdrant_point_id(obj_id, user_id),
                        vector=obj_emb,
                        payload={"node_id": obj_id, "user_id": str(user_id)},
                    )],
                )

        except Exception as exc:
            # One bad proposition should not abort the rest.
            logger.exception(
                "Failed to ingest proposition, skipping",
                extra={"prop_id": str(prop.id), "error": str(exc)},
            )
            continue

    # Materialize co-occurrence between every node touched this turn (non-critical
    # — a failure here must not lose the turn's semantic writes).
    if len(touched_node_ids) >= 2:
        try:
            await graph_service.bump_cooccurrence_edges(
                touched_node_ids, user_id, session_number
            )
        except Exception:
            logger.exception("co-occurrence edge upsert failed")

    # Flag this user for the next background maintenance tick (clustering etc.)
    # only if the graph actually changed this turn.
    if touched_node_ids:
        mark_user_dirty(user_id)

    return nodes_created, nodes_updated, edges_created, edges_updated, skipped, touched_node_ids


# Distinct mode from user-message extraction: the firewall is LIFTED here because
# the user endorsed the piece. We WANT its elements — as the user's accepted facts.
_AFFIRMATION_SYSTEM = (
    "The user just AFFIRMED a generated piece as something they liked. Extract the "
    "DURABLE preferences this confirms — the themes/angles the user endorsed by "
    "affirming, and the underlying INTEREST the piece served for them — as "
    "user-subject Subject-Predicate-Object propositions. These are now the user's "
    "ACCEPTED preferences, not the piece's text.\n"
    "Return JSON {\"propositions\": [...]}; each: subject, predicate, object, "
    "source_span, subject_entity_type, object_entity_type, valence ('positive'), "
    "valence_score, salience_score, causal_class, confidence (0.8-0.95), "
    "relation_type (use 'serves' for the function), subject_kind ('user').\n"
    "Extract the 1-3 MOST important durable elements (the core theme + the interest "
    "it served). Specific, grounded concepts only — no set-dressing for its own "
    "sake. JSON only — no prose, no markdown."
)


async def extract_from_retry_correction(
    user_id: UUID,
    content_text: str,
    original_user_msg: str,
    rejected_beat: str,
    *,
    conversation_id: UUID,
    message_id: UUID,
    session_number: int,
    user_display_name: str = "",
) -> None:
    """
    The ONE bounded exception to "extraction never reads generated text" (reshape §6.2b /
    P0.3B): a retry-note CONTENT correction is RELATIVE ("more rigorous than THAT"), so the
    rejected beat is provided as reference CONTEXT — never itself extracted. Propositions
    are stamped prov_source='retry_correction' (low weight, reaction-testable). Best-effort
    and OFF the reroll path — a failure never affects the regeneration the user awaits.
    """
    context_msg = (
        f"{original_user_msg}\n"
        f"[the previous attempt they're correcting, for reference — extract the correction "
        f"this points at, NOT the attempt]: {rejected_beat}\n"
        f"[their correction]: {content_text}"
    )
    try:
        props = await extract_propositions(
            context_msg, [], [],
            conversation_id=conversation_id, message_id=message_id,
        )
    except Exception:
        logger.exception("retry-correction extraction failed",
                         extra={"message_id": str(message_id)})
        return
    for p in props:
        p.prov_source = "retry_correction"
        p.prov_elicited = "asked_and_answered"
    if props:
        try:
            await ingest_propositions(
                props, user_id, session_number, user_display_name=user_display_name,
            )
        except Exception:
            logger.exception("retry-correction ingest failed")


async def extract_from_affirmation(user_id: UUID, message_id: UUID) -> None:
    """
    Endorsement gate (extraction redesign §3/§6). Generated-piece content is NOT
    extracted as a user fact at generation time (the firewall suppresses it). When
    the user AFFIRMS a turn (a 'check'), THIS promotes the elements that turn
    introduced to USER_ACCEPTED, user-subject facts — the only path by which a
    generated piece's content (e.g. a motif the piece introduced) enters the user-model.

    Best-effort and async (off the response path). Prefers the persisted PieceBrief
    (structured) as the source; falls back to the rendered piece text.

    NOTE (per-element uptake): this promotes the affirmed turn as a whole. When the
    per-element uptake instrumentation lands (architecture doc), narrow this to only
    the elements actually taken up — same mechanism, don't build twice.
    """
    from db.postgres import get_pool
    from services import sessions

    pool = await get_pool()
    async with pool.acquire() as conn:
        turn = await conn.fetchrow(
            "SELECT conversation_id, response_text, piece_brief FROM conversation_turns "
            "WHERE user_id = $1 AND message_id = $2",
            str(user_id), str(message_id),
        )
    if turn is None or not (turn["response_text"] or "").strip():
        return

    brief = turn["piece_brief"]  # dict via the pool's jsonb codec, or None
    if isinstance(brief, dict):
        source = "AFFIRMED PIECE BRIEF:\n" + json.dumps(
            {k: brief.get(k) for k in
             ("function_to_serve", "piece_frame", "advance_directive", "delivery")},
            ensure_ascii=False,
        )
    else:
        source = "AFFIRMED PIECE:\n" + turn["response_text"][:4000]

    try:
        raw = await chat(
            [{"role": "system", "content": _AFFIRMATION_SYSTEM},
             {"role": "user", "content": source}],
            model=APP_CONFIG.extraction_model_resolved,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=APP_CONFIG.utility_max_tokens,
        )
        items = _parse_propositions_json(raw)
    except (ExtractionError, Exception):
        logger.warning("affirmation extraction failed", extra={"message_id": str(message_id)})
        return

    props = _build_propositions(items)
    if not props:
        return

    # Force the endorsement provenance — these are USER_ACCEPTED, user-subject facts.
    conv_id = UUID(str(turn["conversation_id"]))
    for p in props:
        p.subject_knowledge_source = KnowledgeSource.USER_ACCEPTED
        p.object_knowledge_source = KnowledgeSource.USER_ACCEPTED
        p.subject_kind = SubjectKind.USER
        p.subject_ref = None
        p.based_on_ref = None
        p.source_conversation_id = conv_id
        p.source_message_id = message_id

    session_number = await sessions.get_or_create_current_session(user_id)
    self_node_id = await graph_service.ensure_self_node(user_id, "Me")
    await ingest_propositions(
        props, user_id, session_number,
        user_display_name="Me", self_node_id=self_node_id,
    )
    logger.info(
        "affirmation promoted piece elements to USER_ACCEPTED",
        extra={"message_id": str(message_id), "count": len(props)},
    )
