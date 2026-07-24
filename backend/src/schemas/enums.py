from enum import Enum


class KnowledgeSource(str, Enum):
    USER_STATED   = "user_stated"    # user said it explicitly
    LLM_INFERRED  = "llm_inferred"   # model read it from subtext
    USER_ACCEPTED = "user_accepted"  # was suggested, user confirmed


class SubjectKind(str, Enum):
    """
    Whose model a proposition's facts flow to — the subject-attribution firewall
    (extraction redesign §2). USER is the hard default; the others are firewalled
    OFF the user's self-model.
    """
    USER        = "user"          # facts flow to the user's self-model (the default)
    REAL_PERSON = "real_person"   # a real person the user mentions; NEVER to self-model
    CHARACTER   = "character"     # a fictional prop; NEVER to self-model or to a real person


class Valence(str, Enum):
    POSITIVE   = "positive"
    NEGATIVE   = "negative"
    AMBIVALENT = "ambivalent"
    NEUTRAL    = "neutral"


class CausalClass(str, Enum):
    ASSOCIATIVE     = "associative"
    CAUSAL          = "causal"
    COUNTERFACTUAL  = "counterfactual"


class RelationType(str, Enum):
    """
    Closed taxonomy for graph edges. The natural-language phrase the user/LLM
    produced is preserved on the :Mention (Proposition.predicate); the edge
    itself is keyed by one of these canonical verbs so edges dedup by exact
    match and clustering has a stable relation vocabulary.
    """
    IS_A           = "is_a"
    PART_OF        = "part_of"
    HAS_PROPERTY   = "has_property"
    CO_OCCURS_WITH = "co_occurs_with"
    RELATES_TO     = "relates_to"
    CONTRASTS_WITH = "contrasts_with"
    CAUSES         = "causes"         # X produces / triggers state Y
    SERVES         = "serves"         # X does psychological work for / satisfies need Y


class MemoryType(str, Enum):
    EPISODIC = "episodic"   # specific event with time/place
    SEMANTIC = "semantic"    # generalised belief or pattern


# --- Provenance spine (product reshape §1.2) ---
# HOW we learned something is a different fact from HOW CONFIDENT we are it's true.
# Confidence stays truthful + uncapped; provenance gates what the evidence is ENTITLED
# to do (tier-3 eligibility, chip weighting, contested-readings). Stored as flat scalar
# props so the gates stay a simple Cypher WHERE.
class ProvSource(str, Enum):
    CONVERSATION     = "conversation"
    IMPORT           = "import"
    OFFERED_CHIP     = "offered_chip"
    FEEDBACK         = "feedback"
    RETRY_CORRECTION = "retry_correction"


class ProvAuthorship(str, Enum):
    USER_WROTE  = "user_wrote"
    OTHER_WROTE = "other_wrote"


class ProvFormat(str, Enum):
    JOURNAL     = "journal"
    FICTION     = "fiction"
    SOCIAL_POST = "social_post"
    ESSAY       = "essay"
    OTHER       = "other"


class ProvElicited(str, Enum):
    VOLUNTEERED          = "volunteered"
    OFFERED_AND_ACCEPTED = "offered_and_accepted"
    ASKED_AND_ANSWERED   = "asked_and_answered"
