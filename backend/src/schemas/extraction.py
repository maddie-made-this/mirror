from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from schemas.enums import (
    CausalClass,
    KnowledgeSource,
    ProvElicited,
    ProvSource,
    RelationType,
    SubjectKind,
    Valence,
)


class Proposition(BaseModel):
    """
    Raw SPO triple extracted from one user message.
    Ephemeral — used to produce GraphNodes and GraphEdges, then stored for audit.
    Vectors are NOT here; they live in Qdrant.
    """
    id: UUID = Field(default_factory=uuid4)
    subject: str        # surface form, e.g. "my father"
    predicate: str      # free-text phrase, kept verbatim on the :Mention
    object: str         # surface form, e.g. "like I'm never enough"
    source_span: str    # verbatim substring that produced this triple

    # Canonical edge verb (closed taxonomy). The LLM maps `predicate` to the
    # nearest RelationType; the edge is keyed by this, the Mention keeps the
    # natural phrase above. Defaults so older/partial payloads still parse.
    relation_type: RelationType = RelationType.RELATES_TO

    # Confidence: 1.0 = direct user statement, 0.7–0.9 = strong inference,
    # 0.3–0.5 = speculative inference. LLM assigns this during extraction.
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    # LLM-assigned during extraction
    subject_entity_type: str = ""
    object_entity_type: str = ""
    valence: Valence = Valence.NEUTRAL
    valence_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    salience_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    causal_class: CausalClass = CausalClass.ASSOCIATIVE

    # Per-side knowledge source — position alone doesn't determine this (A6).
    subject_knowledge_source: KnowledgeSource = KnowledgeSource.USER_STATED
    object_knowledge_source: KnowledgeSource = KnowledgeSource.USER_STATED

    # Provenance spine (reshape §1.2) — travels from extraction to the write like
    # knowledge_source does. Standard extraction is conversational + volunteered; the
    # retry-correction path (P0.3B) overrides prov_source/prov_elicited before ingest.
    prov_source: str = ProvSource.CONVERSATION.value
    prov_authorship: str | None = None
    prov_format: str | None = None
    prov_elicited: str = ProvElicited.VOLUNTEERED.value

    # Subject attribution — the firewall (extraction redesign §2). Defaults to USER
    # (the common case) so the LLM only diverges on positive signal and old/partial
    # payloads still parse. subject_ref names the real person / character when not
    # the user; based_on_ref records a character's real-person origin at fork time
    # (provenance only — the character then DIVERGES, no live identity bridge).
    subject_kind: SubjectKind = SubjectKind.USER
    subject_ref: str | None = None
    based_on_ref: str | None = None

    # Injected by extract_propositions after parsing — not produced by the LLM (D3).
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None
