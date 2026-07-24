from pydantic import BaseModel


class FewShotExample(BaseModel):
    """One worked example for the extraction prompt."""

    user_message: str
    expected_json: str  # the JSON the LLM should produce — embedded as a string


class AppConfig(BaseModel):
    """
    All mode-sensitive values live here.
    Nothing mode-specific is hardcoded anywhere else in the codebase.
    """

    # --- Entity types ---
    # Valid entity type slugs for this deployment.
    # The field_validator on GraphNode checks against this list at runtime.
    entity_types: list[str]

    # --- Dedup thresholds ---
    relationship_dedup_threshold: float = 0.88
    node_dedup_threshold: float = 0.92
    # Producer-spec C2 (two DIFFERENT thresholds, tunable):
    # bridges aggressive — many rewordings of one connection are near-identical;
    # readings conservative — close-but-distinct functions (e.g. "relief from
    # responsibility" vs "permission not to perform") must NOT collapse. Err toward keeping.
    bridge_dedup_threshold: float = 0.90
    reading_dedup_threshold: float = 0.93
    # Producer-spec C3a: readings below this confidence are never stored/surfaced
    # (the dump had a conf=0.05 function reading on display).
    reading_confidence_floor: float = 0.15
    # Master flag for the identity firewall (gates the identity record + ingest gate
    # + reconciliation, 4a/4d/4f). OFF: the in-piece-vs-real distinction it depends on
    # — telling a figure's words inside a generated piece apart from the user speaking
    # about themselves — was never validated against a live run, so we ship only the
    # distinction-INDEPENDENT pieces (the 4e subject firewall in the reflection
    # prompts, which is unconditional) and hold the judgment-dependent
    # record/gate/reconciliation until a later run validates it.
    identity_firewall_enabled: bool = False

    # --- Clustering / entity resolution ---
    # cluster_threshold: looser than node_dedup — if embedding distance is within
    # this, fold the candidate into the existing node rather than creating a new one.
    cluster_threshold: float = 0.62
    # Louvain resolution — the granularity dial for community detection.
    # >1 favours MORE, SMALLER communities; <1 fewer and broader; 1.0 is the
    # library default. 1.0 produced one community holding ~45% of the graph
    # (distinct concepts subsumed into a single broad theme), so the default is
    # raised. Tune this first if clusters feel too coarse or too fragmented.
    cluster_resolution: float = 1.6
    # Ceiling for the size-scaled resolution (see clustering._resolution_for).
    # Without a cap, a large graph would keep pushing resolution up until
    # communities shatter into singletons, which is as useless as one big blob.
    cluster_resolution_max: float = 4.0
    # How often to check a node for a potential k=2 split (every N new mentions).
    recluster_check_every: int = 20
    # Minimum silhouette score for the split to be treated as a genuine cluster pair.
    recluster_min_silhouette: float = 0.55

    # --- Context retrieval ---
    # Minimum cosine similarity for a node to count as "relevant to this message"
    # (flow-1 grounding + the flow-2 interpretation match both read from this set).
    # CALIBRATION: text-embedding-3-small produces a COMPRESSED cosine scale — a
    # full conversational sentence vs. a terse concept slug ("grasping-a-whole-system")
    # tops out around 0.50 even when dead-on-topic. 0.6 silently filtered EVERY
    # node on every turn (relevant_nodes always empty), starving flows 1 and 2.
    # 0.35 captures the genuinely-relevant cluster and drops the long tail; limit
    # caps the count.
    context_retrieval_threshold: float = 0.35
    context_retrieval_limit: int = 10

    # Identity seed (Change 2): entity types whose USER-subject nodes are stable
    # identity facts — background, discipline, long-running preoccupations — to seed
    # DETERMINISTICALLY into every conversation's context, unioned with semantic
    # retrieval. Retrieval finds what's relevant to the message; the seed guarantees
    # what's always relevant about the PERSON, so a brand-new conversation is oriented
    # to who the user is before their first message happens to retrieve it. Empty (the
    # default) = no seed; semantic retrieval alone governs context, unchanged.
    identity_seed_entity_types: list[str] = []
    identity_seed_limit: int = 8

    # --- Models ---
    # llm_model is the FRONTIER tier — used only for the user-facing response,
    # the one place prose quality matters. Everything mechanical (extraction,
    # reflection, clustering, chips, bridges, interpretation) routes to the
    # cheaper utility_model. utility_model="" falls back to llm_model so nothing
    # changes for deployments that don't set it.
    llm_model: str
    utility_model: str = ""
    # Reflection (interpretation/motif readings) is the one MECHANICAL task that
    # rewards a stronger model: it must produce idiographic psychological insight,
    # not echo mentions, and respect the person's own framing/gender. Empty falls
    # back to utility_model_resolved so the default is unchanged; a deployment that
    # wants a stronger reflection tier sets it explicitly.
    reflection_model: str = ""
    # The user-facing RESPONSE-generation model. Empty falls back to llm_model, so
    # nothing changes by default. Exists as a reversible probe lever (set via the
    # RESPONSE_MODEL env var) to repoint ONLY generation — e.g. to a frontier
    # reasoner for the Part-A capability probe — without touching any other tier.
    # When the director/renderer split is OFF this is the single-model generator;
    # when it is ON it is the default DIRECTOR tier (see director_model below).
    response_model: str = ""

    # --- Director / renderer split (Part B) ---
    # The split puts frontier REASONING in the director (decides what the piece does,
    # emits a PieceBrief) and PROSE CRAFT in the renderer (renders the brief). The two
    # jobs reward different models — planning wants a reasoner, voice wants a stylist —
    # so the tiers are separate. Off by default: generation stays single-model
    # (response_model_resolved) until this is set.
    use_director_split: bool = False
    # DIRECTOR tier — the frontier reasoner (the editorial mind). Empty falls back to
    # response_model_resolved, so the existing RESPONSE_MODEL probe lever (e.g.
    # Sonnet) becomes the director automatically when the split turns on.
    director_model: str = ""
    # RENDERER tier — the prose stylist (the voice). Empty falls back to llm_model, the
    # baseline generation model, so the renderer never inherits the frontier probe model
    # by accident.
    renderer_model: str = ""

    # AUTHOR-MODE director override. Author-mode planning is a pure authorial task
    # (gap-filling + beat-listing on a blank account); it does NOT need the same
    # frontier reasoner the turn-by-turn director needs. Lever to point author planning
    # at a faster/cheaper model if the director remains the latency bottleneck even on a
    # compact-brief envelope. Empty falls back to director_model_resolved.
    author_director_model: str = ""

    # --- Dual-model render (Change 6) ---
    # When on (and the split is on, on generation turns), the director emits a
    # SegmentedPlan and the segments render CONCURRENTLY on different models,
    # concatenated in order. Off by default — standard split until enabled. Viable ONLY
    # because segments are independent (they never see each other's prose), so latency
    # ~= max(segment renders) rather than the sum.
    use_dual_render: bool = False
    # The role -> writer RULE, applied in code (NOT self-assigned by the director):
    # expressive prose — where voice and texture carry the passage — routes to the
    # stylist; only genuinely connective tissue goes to the reasoner. A dict so the map
    # is configurable per genre — never hard-coded. Labels resolve to tiers in
    # response_gen: reasoner->response_model, stylist->renderer_model. The
    # .get(role, "stylist") default in _run_dual sends any non-'connective' label to the
    # stylist (errs toward voice).
    segment_role_model: dict[str, str] = {"connective": "reasoner", "expressive": "stylist"}

    # --- Small-model swaps (L9 / P5.3) ---
    # Dedicated cheap-tier levers for the classify-into-known-set jobs (extraction,
    # tier-2 matcher, headline/consolidation synthesis, retry-note classifier). Each
    # empty → falls back to utility_model_resolved, so default behaviour is unchanged;
    # set via env to move a single call site onto a Haiku-class model independently.
    extraction_model: str = ""
    matcher_model: str = ""
    headline_model: str = ""

    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536  # must match embedding_model output dimension

    # --- Warming-up UX (S8 / P5.4) ---
    # If the renderer produces no first token within this many seconds (serverless cold
    # start), the stream emits a {type:'warming'} SSE event so the client can show an
    # honest "warming up" state instead of a dead spinner. No fake progress bars.
    warming_ttft_s: float = 8.0

    # --- Output token caps (0 = uncapped) ---
    # Bound completion length per tier to control cost. Defaults uncapped so prod
    # behaviour is unchanged; tighten via env (see Settings) for cheap test runs.
    response_max_tokens: int = 0
    utility_max_tokens: int = 0
    moderation_max_tokens: int = 0
    # Director cap — non-zero by DEFAULT, unlike the others. The director emits a
    # short PieceBrief JSON, so a generous cap never truncates it, but leaving the
    # call uncapped makes OpenRouter RESERVE the model's worst-case completion cost
    # up front — which 402s an otherwise-sufficient balance on an expensive reasoner
    # (Sonnet). Capping bounds the reserve to cents. The parse-retry + carry-forward
    # fallback covers the rare truncation. Tunable via DIRECTOR_MAX_TOKENS.
    director_max_tokens: int = 2000

    # AUTHOR-MODE director cap (SPEC_prose_quality_round 2b). The author director emits
    # a COMPACT brief (premise + 6-10 one-clause beats), so 900 tokens is generous; the
    # tighter cap both prevents a verbose-plan blowout (the shipped 2000-tok/52s failure
    # that left piece_beats empty) AND cuts director latency toward the hard <30s gate.
    # A beat outline needs ~600-800 tokens; 900 is the headroom buffer.
    author_director_max_tokens: int = 900

    @property
    def utility_model_resolved(self) -> str:
        """The cheap-tier model, falling back to the frontier model if unset."""
        return self.utility_model or self.llm_model

    @property
    def reflection_model_resolved(self) -> str:
        """The reflection-tier model: reflection_model, else the cheap utility tier."""
        return self.reflection_model or self.utility_model_resolved

    @property
    def extraction_model_resolved(self) -> str:
        """Extraction/retry-note tier (P5.3), falling back to the cheap utility tier."""
        return self.extraction_model or self.utility_model_resolved

    @property
    def matcher_model_resolved(self) -> str:
        """Tier-2 angle matcher tier (P5.3), falling back to the cheap utility tier."""
        return self.matcher_model or self.utility_model_resolved

    @property
    def headline_model_resolved(self) -> str:
        """Headline/consolidation-synthesis tier (P5.3), falling back to utility."""
        return self.headline_model or self.utility_model_resolved

    @property
    def response_model_resolved(self) -> str:
        """The response-generation model: response_model override, else llm_model."""
        return self.response_model or self.llm_model

    @property
    def director_model_resolved(self) -> str:
        """
        The DIRECTOR tier (frontier reasoner). Falls back to the response-generation
        model so the existing RESPONSE_MODEL probe lever doubles as the director.
        """
        return self.director_model or self.response_model_resolved

    @property
    def author_director_model_resolved(self) -> str:
        """
        The AUTHOR-MODE director model. Falls back to the piece director so existing
        configs are unaffected. Set author_director_model to point author-mode planning
        at a faster/cheaper model without touching the piece director.
        """
        return self.author_director_model or self.director_model_resolved

    @property
    def renderer_model_resolved(self) -> str:
        """
        The RENDERER tier (prose craft). Falls back to llm_model — the baseline
        generator — NOT to the frontier response/probe model.
        """
        return self.renderer_model or self.llm_model

    # --- Qdrant collections ---
    node_collection: str = "graph_nodes"
    edge_label_collection: str = "edge_labels"

    # --- System prompts ---
    extraction_system_prompt: str
    response_system_prompt: str  # used when the layered stack is off; layers override it

    # Pass 2 of extraction: detects what a message IMPLIES rather than states.
    # Empty string disables the reflection pass for this deployment.
    reflection_system_prompt: str = ""

    # Nomothetic categories (A3 / interest-model §3) — the provisional, REVISABLE
    # index the reflection tags an idiographic statement with. One list indexes
    # BOTH function hypotheses and limiting beliefs. Empty = no taxonomy
    # (empty by default). Populated per family by a deployment that defines a
    # taxonomy. Never frozen.
    nomothetic_categories: list[str] = []

    # --- Extraction prompt content (layered: system prompt + few-shot + live hints) ---
    extraction_examples: list[FewShotExample] = []
    extraction_active_nodes_hint: str = (
        "These nodes already exist in the user's graph. If the user is referring "
        "to one of them (by name or paraphrase), use its name and entity_type "
        "exactly so we merge into it. Do not invent new variants."
    )
    extraction_active_predicates_hint: str = (
        "The user tends to use these predicates. Reuse them where the meaning "
        "matches; coin a new predicate only if none fit."
    )

    # --- Ingest gating ---
    # Propositions below this confidence are logged but not written to the graph.
    min_ingest_confidence: float = 0.55

    # --- Prompt layer toggles ---
    use_identity_layer: bool = False      # default: off (base model has its own)
    use_safety_layer: bool = False        # default: off (base model handles refusals)
    use_capability_layer: bool = True
    use_format_layer: bool = True
    use_graph_context_layer: bool = True
    use_recent_messages_layer: bool = True

    # --- Prompt layer content ---
    core_identity_text: str = ""
    safety_rules_text: str = ""
    capability_rules_text: str = ""
    # Analytic-register capability (B10): used INSTEAD of capability_rules_text when a
    # conversation's session_type is 'analytic' (the "why" branch). Empty = no separate
    # analytic register (falls back to the normal capability when unset).
    analytic_capability_text: str = ""
    static_format_rules_text: str = ""   # baseline before dynamic preference nodes
    recent_messages_limit: int = 10

    # --- Director / renderer prompts (Part B) ---
    # The director ENVELOPE is appended last to the (inherited) layered system prompt
    # and flips the output contract: instead of writing the reply, emit a PieceBrief.
    # It is structural — the persona/register lives in the layers it inherits — so a
    # deployment can enrich it without rewriting it. The renderer SYSTEM is the thin
    # "voice" prompt: render the brief as prose, no reasoning.
    director_envelope_text: str = (
        "[YOUR OUTPUT THIS TURN]\n"
        "You are the DECIDING MIND and the EDITOR, not the voice. Do NOT write the "
        "reply prose. Using everything above (who this person is, what you understand "
        "about them, the dynamics, the history, and their latest message), decide the "
        "single best next move and emit it as a PIECE BRIEF — a set of directives a "
        "separate writer turns into prose.\n\n"
        "FIRST, every turn, decide: what is the NEXT BEAT of this piece? You are "
        "building an argument or an exploration that DEVELOPS — the writer only renders "
        "beats, so only you hold the arc; if you don't advance it, nothing will. "
        "Probing what makes this person tick is a distant second to developing the "
        "piece, and never the turn's purpose.\n\n"
        "Output ONLY a JSON object with these fields (no prose around it):\n"
        '  "action": "ask" | "write" | "ask_then_write"\n'
        '  "question": the ONE in-register question to ask, or null\n'
        '  "arc_position": "opening" | "rising" | "turning" | "culmination" | '
        '"resolution" — where the WHOLE piece is; advance it as the piece builds\n'
        '  "arc_synopsis": a one-two sentence rolling summary of the piece so far — '
        "REVISE the prior synopsis to fold in this turn; do NOT rebuild it from "
        "scratch or list every beat. Do NOT emit beat_history — the system maintains "
        "the full beat log for you.\n"
        '  "next_beat": the SPECIFIC move this turn makes — deepen the argument, turn '
        "to the counterexample, introduce a new angle, build toward the central claim, "
        'or begin the close. NEVER "continue" or "more of the same"\n'
        '  "advance_directive": next_beat written as a concrete imperative for the '
        "writer — what must CHANGE versus the previous turn; this is what stops the "
        "reply from repeating itself\n"
        '  "do_not_repeat": [the ~6 MOST RECENT beats/lines/images that must not '
        "recur — keep it short; the system trims it to the latest few]\n"
        '  "prerequisites_to_establish": [irreducible facts still missing that are '
        "needed before the piece can be concrete — empty if all known]\n"
        '  "function_to_serve": the underlying interest to lean into (from what you '
        "understand about them) — to be rendered as EXPERIENCE on the page, never named\n"
        '  "delivery": {"vividness","prose_density","person_tense",'
        '"emphasis"} — register/delivery dials, not content\n'
        '  "piece_frame": {"subject_pov","subjects","context","current_section"} '
        "— the piece's fixed frame (subject, subjects, setting), so the writer can show "
        "rather than restate\n"
        '  "pacing": "early" | "mid" | "deep"\n'
        '  "interest_anchor": a one-line reminder of what keeps the USER\'s interest '
        "central\n"
        '  "hard_avoid": [topics/registers that must never appear]\n\n'
        "ADVANCEMENT (this is what stops the piece from stalling):\n"
        "- next_beat MUST name a specific NEW move. If beat_history shows the piece "
        "has dwelt on one idea for 2+ turns, next_beat MUST move to a genuinely new "
        "beat (deepen or turn), not another variation of it.\n"
        "- Carry arc_position + arc_synopsis forward from the prior brief (shown "
        "below when present): REVISE the synopsis to fold in this turn, set "
        "arc_position, and emit next_beat for THIS turn only. NEVER re-emit the beat "
        "list — the system appends it for you.\n\n"
        "DECISION POLICY:\n"
        "- Default to \"write\". The person is here for the piece, not an interview.\n"
        "- Ask ONLY when an IRREDUCIBLE fact is genuinely missing — the subject of the "
        "piece, the claim it turns on, or the form it should take. Tone, prior "
        "reading, exact register, and framing are ENRICHING, not blocking: pick a "
        "sensible default from what you already know and write.\n"
        "- NEVER ask the person to author the piece for you — no \"what do you want it "
        "to say?\", no \"tell me what you want.\" Deciding the next beat is YOUR job; "
        "handing it back is the one move that breaks the experience.\n"
        "- One question maximum, and NEVER two asking-turns in a row. If the previous "
        "turn already asked, this turn writes.\n"
        "- Momentum overrides everything: if the person signals eagerness or asks you "
        "to continue (\"yes\", \"keep going\", \"what happens next\"), choose \"write\" "
        "and move — do not ask.\n"
        "- Use \"ask_then_write\" only to check one irreducible thing while STILL "
        "opening the piece this turn; then advance_directive is the opening beat you "
        "write, not just the question.\n\n"
        "PROBES ARE GARNISH, NOT THE MEAL:\n"
        "- At most an occasional light thread woven INTO an advancing beat. NEVER "
        "spend 2+ consecutive turns on the same probe — if a thread didn't land last "
        "turn, drop it and move the piece. (This is the interested-reader role.)\n\n"
        "NEVER MINE THE PIECE FOR DATA:\n"
        "- A figure's voice inside the piece is CONTENT, not evidence about the "
        "user. Do not infer the user's beliefs or motives from what a character "
        "says or does. Only the USER speaking OUT of the piece (about themselves, "
        "not their subject) is a real signal.\n\n"
        "PIECE FRAME (the fixed given of the piece — subject, subjects, setting, form):\n"
        "- On the FIRST turn, ESTABLISH it by confident inference from what you "
        "already know — their identity facts (above), the conversation so far, and "
        "their actual request. If the piece grew out of a conversation, build it from "
        "that accumulated context; do NOT start cold or ask what you can infer. Ask "
        "ONLY for a genuinely-missing IRREDUCIBLE fact that fundamentally changes the "
        "piece — never the enriching detail.\n"
        "- Once established it is LOCKED (shown below when present): echo it "
        "UNCHANGED. Contradicting the frame the user set is the highest-priority "
        "error, above every stylistic concern.\n"
        "- The user may RE-FRAME the piece (\"make it an essay this time\", \"try it as "
        "a dialogue\"): apply that to piece_frame for THIS piece only — a choice that "
        "never changes who the person actually is. When unsure whether a statement "
        "re-frames the piece or corrects a real fact about them, treat it as a "
        "piece-only re-frame (reversible; a real correction can be restated).\n\n"
        "The brief carries directives and judgment, not finished prose. Keep any "
        "question in the interlocutor's register."
    )
    renderer_system_text: str = (
        "You are the VOICE. A director has already decided what happens next and "
        "handed you a PIECE BRIEF. Render the next beat as absorbing, in-register "
        "prose that continues the conversation naturally — the user must never see "
        "the seams.\n\n"
        "THE WALL — the brief has two kinds of field and you treat them OPPOSITELY:\n"
        "- STAGING are directions written TO you (the move to make, what must advance, "
        "what not to repeat, what's still unknown, the interest to serve, pacing, what "
        "to keep central, what to avoid). These are NOTES. You ACT on them; you NEVER "
        "quote, name, paraphrase, or speak them. A staging line like 'ask what they "
        "want' or 'build toward the central claim' is an instruction to YOU — turn it "
        "into living prose, never into a sentence on the page.\n"
        "- CONTENT is what actually goes into the piece: the frame (subject / setting / "
        "subjects — SHOW it as concrete detail, never recite it) and the register dials "
        "(how it sounds).\n\n"
        "Rules:\n"
        "- Write ONLY the reply prose. Never output the brief, JSON, field names, "
        "headings, directives, or any meta-commentary.\n"
        "- If the brief tells you to ask something, EXPRESS it as natural dialogue in "
        "your own voice — never paste or flatly paraphrase the directive (\"tell me "
        "what you want\" is a NOTE to you, not a line to say).\n"
        "- Obey the advance / do-not-repeat directions exactly: move the piece forward; "
        "never reuse a forbidden beat, line, or image.\n"
        "- Render the interest-to-serve as experience on the page — show it, never "
        "name it.\n"
        "- Match the register dials. Keep the user's interest central. Never include "
        "anything marked off-limits.\n"
        "- The judgment was made upstream — render the beat; don't add framing, "
        "caveats, or commentary."
    )

    # AUTHOR-MODE one-shot envelope (Option A). Distinct from director_envelope_text:
    # NO turn-by-turn beat-machine framing. The director plans ONE complete piece and the
    # renderer writes the whole arc in a single pass — there is no "next turn", so the
    # director resolves every unspecified detail itself and briefs the FULL arc, never one
    # beat. This is what makes long-form authoring a real path
    # instead of a fragment of the turn-by-turn path.
    author_director_envelope_text: str = (
        "You are the AUTHOR and DECIDING MIND of a single, COMPLETE written piece. The "
        "person asked you to WRITE THEM SOMETHING — an essay, a passage, an exploration "
        "in the vein of what they keep circling. A separate writer will render the whole "
        "piece from your brief in ONE pass — your job is the SKELETON that writer "
        "expands.\n\n"
        "OUTPUT A COMPACT STRUCTURED BRIEF — NOT A PROSE PLAN. Do NOT narrate the piece, "
        "do NOT write paragraphs of planning, do NOT draft prose. Output only the JSON "
        "PieceBrief, kept SHORT (target under 600 tokens total) so the structured fields "
        "never truncate. A verbose narrative plan is the single worst failure here — it "
        "blows the budget, leaves piece_beats empty, and the writer gets nothing to "
        "expand. Write the SKELETON only.\n\n"
        "REQUIRED — populate these two fields with the actual content:\n"
        "  arc_synopsis: ONE LINE — the subject + the angle it turns on + the form. "
        "Example: 'why debugging is the purest form of reading; framed as the pleasure "
        "of the anomaly rather than the fix; a first-person essay that opens on a "
        "specific bug.'\n"
        "  piece_beats: 6-10 ORDERED beats, each ONE SHORT CLAUSE — no prose, no "
        "elaboration. Each beat names the move and (optionally) the example or line. "
        "Example list:\n"
        "    ['1. open on the concrete bug — the log line that made no sense',\n"
        "     '2. the reflex: assume you misread it',\n"
        "     '3. the turn — the machine is never wrong about what it did',\n"
        "     '4. name the real pleasure: the world is more consistent than you are',\n"
        "     '5. counterexample — the bug that WAS a compiler fault',\n"
        "     '6. concede it, then show why it proves the rule',\n"
        "     '7. widen: this is how you read people, too',\n"
        "     '8. the claim stated plainly, once, without hedging',\n"
        "     '9. close back on the original log line, now legible']\n"
        "Each beat is ONE clause. Do NOT expand them. The renderer expands.\n\n"
        "ABSOLUTE RULES:\n"
        "- action MUST be 'write' (never 'ask' or 'ask_then_write'). NEVER ask the "
        "person anything. If a detail is unspecified — the form, the examples, whether "
        "the argument concedes or presses — YOU DECIDE IT (that is what an author does) "
        "and put the decision in arc_synopsis and the beats.\n"
        "- HONOR what they specified. If they named the subject, the angle, the "
        "examples, or the form, those appear as beats. You decide only the GAPS.\n"
        "- Set arc_position='opening'; the renderer will traverse the whole arc.\n\n"
        "Also fill (briefly): function_to_serve (one line — the interest this piece is "
        "for), delivery (lean and concrete, never purple), piece_frame (one-line "
        "subject/frame/form — decide them), interest_anchor (one line), hard_avoid (only "
        "true bright lines). Leave next_beat, advance_directive, do_not_repeat, "
        "prerequisites_to_establish, beat_history EMPTY — they are turn-by-turn fields "
        "the author path does not use.\n\n"
        "Compact in, full piece out. That is the whole job."
    )

    # AUTHOR-MODE renderer system text — the VOICE for a one-shot complete piece. A real
    # default (not "") so it does NOT inherit the beat-framed renderer_system_text
    # ("render the next beat"), which fights author-mode. Same STAGING/CONTENT wall + no-
    # meta/no-refusal discipline as the turn-by-turn renderer, but framed to write the
    # WHOLE arc to a payoff in one pass. The persona still flows through the layered
    # understanding stack.
    author_renderer_system_text: str = (
        "You are the VOICE. A director has handed you a PIECE BRIEF for a COMPLETE piece "
        "the person asked to be written. Render the ENTIRE piece now, start to finish, as "
        "one continuous run of absorbing, in-register prose — a full arc (setup, "
        "development, complication, the claim, close), NOT an opening beat.\n\n"
        "THE WALL — the brief has two kinds of field and you treat them OPPOSITELY:\n"
        "- STAGING are directions written TO you (the arc to travel, the interest to "
        "serve, what to keep central, what to avoid). These are NOTES. You ACT on them; "
        "you NEVER quote, name, paraphrase, or speak them.\n"
        "- CONTENT is what actually goes into the piece: the frame (subject / setting / "
        "form — SHOW as concrete detail, never recite) and the register dials (how it "
        "sounds).\n\n"
        "Rules:\n"
        "- Write ONLY the prose. Never output the brief, JSON, field names, headings, "
        "directives, or any meta-commentary.\n"
        "- Write the WHOLE piece to a real payoff. Do NOT stop early, do NOT end on a "
        "question to the reader, do NOT write 'to be continued'. They asked for a "
        "finished piece — deliver one.\n"
        "- Travel the full arc the brief lays out: build, complicate, land. Don't dwell "
        "on one beat; don't rush to the end either — let the setup earn the claim.\n"
        "- Lean and concrete beats ornate — no purple, no throat-clearing, no essayistic "
        "hedging — and HOLD that voice across the whole length.\n"
        "- Land the ENDING on the piece's own thought — the tension held live, the "
        "argument intact. Do NOT resolve into uplift, both-sides softness, or a tidy "
        "moral; the close is the payoff of THIS idea, not a lesson.\n"
        "- Render the interest-to-serve as experience on the page — show it, never name "
        "it. Match the register dials. Keep the user's interest central. Never include "
        "anything marked off-limits.\n"
        "- The judgment was made upstream — render the complete piece; don't add "
        "framing, caveats, or commentary."
    )

    # Token budget for the AUTHOR render (one complete piece, so much larger than a
    # single beat). response_max_tokens (the per-beat budget) is too small for a full
    # piece. Validated band: 1400 — 4000 invited padding and looping in testing;
    # the clean runs were ~500-1000w natural length.
    author_response_max_tokens: int = 1400

    # Completeness floor for the author render. Measured across test runs: truncated
    # renders came in <=554 words and stopped at ~beat 6, while complete ones ran
    # to 1144. A render under this floor is treated as truncated -> one
    # regeneration. 900 cleanly separated the two.
    author_render_word_floor: int = 900

    # Validated author-render SAMPLER (the configuration that produced 4/4 clean
    # output in testing). LOW rep-penalty — the high-penalty guess was BACKWARDS and caused
    # word-salad. All tunable without code edits.
    author_render_temperature: float = 0.8
    author_render_top_p: float = 0.95
    author_render_rep_penalty: float = 1.05       # repetition_penalty (vLLM/Together/DeepInfra accept it)
    author_render_freq_penalty: float = 0.0       # frequency_penalty — for hosted APIs w/o rep_penalty (~0.3-0.4)
    author_render_presence_penalty: float = 0.0   # presence_penalty — ditto
    # Anti-tic / banned phrases wired into the author render: the stock essayistic
    # openers that leaked despite instruction. Extendable without code edits.
    author_render_banned_phrases: list[str] = [
        "In today's world",
        "It's worth noting that",
        "At the end of the day",
        "we find ourselves",
    ]

    # Dual-model director envelope (Change 6): appended to the layered stack INSTEAD
    # of director_envelope_text when dual render is on. Same understanding + the same
    # editorial / advancement / frame / no-fiction-as-data discipline, but the output
    # contract is a SegmentedPlan (ordered segments rendered by separate writers and
    # concatenated) rather than one PieceBrief.
    dual_director_envelope_text: str = (
        "[YOUR OUTPUT THIS TURN]\n"
        "You are the DECIDING MIND and EDITOR. Do NOT write the reply prose. Decide the "
        "next BEAT of the piece (advance the arc — never dwell), then break THIS turn's "
        "reply into an ORDERED list of SEGMENTS. Each segment is rendered by a SEPARATE "
        "writer that does NOT see the others' prose, then the pieces are concatenated "
        "in order — so each directive must stand on its own.\n\n"
        "Output ONLY a JSON object (no prose around it):\n"
        '  "tone": one unified voice/register for the whole reply, so the separately-'
        "written segments cohere\n"
        '  "piece_frame": {"subject_pov","subjects","context","current_section"} — '
        "the FIXED frame; echo the locked values (below) UNCHANGED\n"
        '  "arc_position": "opening"|"rising"|"turning"|"culmination"|"resolution"\n'
        '  "arc_synopsis": one-two sentence rolling summary — REVISE to fold in this '
        "turn; do NOT rebuild it from scratch or emit the beat list (the system "
        "maintains the full beat log)\n"
        '  "next_beat": the SPECIFIC new move this turn makes (never "continue")\n'
        '  "do_not_repeat": [the ~6 MOST RECENT beats/lines/images — forbidden for ALL '
        "segments; keep it short, the system trims it]\n"
        '  "todos": [at most ~3 things this reply must accomplish]\n'
        '  "function_to_serve": the interest to serve (rendered, never named)\n'
        '  "delivery": {"vividness","prose_density","person_tense","emphasis"}\n'
        '  "pacing": "early"|"mid"|"deep"\n'
        '  "interest_anchor": one line keeping the USER\'s interest central\n'
        '  "hard_avoid": [topics/registers that must never appear]\n'
        '  "segments": ORDERED list; each = {"index": 0-based order, "role": '
        '"expressive"|"connective", "model": "reasoner"|"stylist", "directive": what '
        "THIS segment must cover — staging (what happens), NEVER the prose itself, ~40 "
        "words max}\n\n"
        "SEGMENTING (label by whether VOICE carries the passage):\n"
        "- expressive = any passage where the writing itself does the work: imagery, "
        "argument with texture, a turn that has to land in the reader's ear. WHEN IN "
        "DOUBT, label expressive — only genuinely functional prose is connective.\n"
        "- connective = ONLY plumbing: transitions, setup, restating the given. If the "
        "sentence has to SOUND like something, it is expressive.\n"
        "- model = which writer renders it: 'reasoner' (for connective prose) or "
        "'stylist' (the prose model — for expressive prose). Assign by what each "
        "segment honestly NEEDS.\n"
        "- Keep segments coherent and few (1-4 typical); a simple beat may be ONE "
        "segment. Order them as they should read.\n\n"
        "Carry the arc forward; keep piece_frame LOCKED (contradicting the frame the "
        "user set is the highest-priority error); never ask the user to author the "
        "piece; demote probes (never 2 turns on one); and NEVER mine the piece's own "
        "subjects as data about the user. Directives carry judgment, never finished "
        "prose."
    )

    # Conversational-mode director envelope. Appended to the layered stack for turns
    # that are conversation rather than generation; the director emits a tiny
    # ResponseStance (not a PieceBrief) — what to react to, land-a-read vs ask vs
    # engage, register, avoids.
    conversational_director_envelope_text: str = (
        "[YOUR OUTPUT THIS TURN — CONVERSATIONAL MODE]\n"
        "This is a CONVERSATION, not a piece. Do NOT write the reply and do NOT spin up "
        "a piece or an arc. Read their latest message and what you know about them, and "
        "emit a tiny RESPONSE STANCE a writer turns into one in-voice reply.\n\n"
        "Output ONLY a JSON object (no prose around it):\n"
        '  "engagement_target": the specific thing in their message to react to\n'
        '  "move": "land_read" | "ask_targeted" | "engage"\n'
        "      land_read = drop a grounded, confident read of them — ONLY if you "
        "actually have the material (never invented);\n"
        "      ask_targeted = ask ONE sharp, genuine question (good early, to learn);\n"
        "      engage = just respond in voice — react, push back, move the thread.\n"
        '  "read": for land_read — the observation, grounded in what they actually '
        "said, stated PLAINLY (not a question, not begging for agreement)\n"
        '  "question": for ask_targeted — the ONE question, in the interlocutor\'s '
        "voice\n"
        '  "register_notes": delivery cues (direct, offhand; plain language is fine)\n'
        '  "avoid": [what to steer clear of — drifting into analysis, strained warmth, '
        "flattery, generic filler]\n"
        '  "user_knowledge_level": "early" | "accumulated" — early: assert lightly and '
        "earn depth; accumulated: lean on what you already know about them\n\n"
        "Stay in the direct, offhand voice from your identity. Reads are dropped, never "
        "agreement-begged (the user reacts with check/x). A genuine question is good — "
        "asking for agreement is not."
    )

    # --- Debug ---
    # When True, MessageResponse carries the full labeled prompt breakdown.
    # Leaks the system prompt to the client — never enable in production.
    expose_prompt_debug: bool = False

    # "Mirror's thinking" click-through (P2.4): the REAL artifacts always render (free).
    # This gates the OPTIONAL narrativized "its read" summary — one cheap-model call,
    # lazy on first open + cached. Off by default: the per-message narrative CoT cost is
    # to be measured before committing (change-doc §3.6 / §12.3). Flip on to enable it.
    enable_thinking_summary: bool = False

    # --- Safety: two-tier moderation ---
    # Tier 1 — HARD FLOOR (binary classifier). Scoped to the inherently-illegal
    # bright line (content involving minors, real-world harm instructions, targeted
    # harassment of a real person). Strict and framing-independent; it does NOT defer
    # to intent or fiction. Runs first and short-circuits. A dedicated binary model is
    # the right tool here — fast, deterministic, and not dependent on a reasoning
    # model's "err toward allowing" posture.
    use_input_guardrail: bool = False
    use_output_guardrail: bool = False
    # Change 4: when the director/renderer split is active, the (Sonnet) director is
    # the bright-line floor — a hard-floor input would have to get past Sonnet to
    # produce a brief, and Sonnet won't emit a bright-line brief. So the separate
    # input-guard LLM call is redundant on the split path and is SKIPPED. Flip this
    # False (or swap the director for a less-aligned model) to restore it; when it
    # runs, the handler fires it CONCURRENTLY with context build (zero added latency).
    # The output guard is never skipped — it is the only watcher of the renderer.
    skip_input_guard_on_split: bool = True
    guardrail_model: str = ""            # e.g. "meta-llama/llama-guard-3-8b"
    input_guardrail_prompt: str = ""     # hard-floor classification prompt (input)
    output_guardrail_prompt: str = ""    # hard-floor classification prompt (output)
    guardrail_refusal_message: str = "I can't help with that."

    # Tier 2 — REASONING JUDGE (graded judgment). A capable model weighs intent
    # and framing on the grey middle (difficult subject matter, self-analysis),
    # erring toward allowing good-faith exploration, and outputs reasoning + a decision.
    # Runs only when the hard floor passes. The two tiers compose: the bright line
    # stays binary and strict; everything else gets judgment, not classification.
    use_reasoning_moderation: bool = False
    moderation_model: str = ""           # judgment model (may differ from llm_model)
    moderation_rubric: str = ""          # rubric for the grey middle (err-toward-allow)
