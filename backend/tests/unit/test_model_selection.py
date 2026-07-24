"""
The user-selectable response model: registry validation + the request-scoped
override that response_gen reads.

The load-bearing property is that an unknown preference NEVER reaches the
provider — a stale or hand-edited profiles.preferred_model must fall back to the
configured default rather than 404 mid-turn.
"""
from config.loader import APP_CONFIG
from core import request_context
from services import models
from services import response_gen


# --- registry -------------------------------------------------------------- #

def test_catalogue_is_non_empty_and_well_formed():
    cat = models.catalogue()
    assert cat
    for entry in cat:
        assert entry["id"] and entry["label"] and entry["blurb"]
        # ids are provider-qualified slugs, never bare model names
        assert "/" in entry["id"], entry["id"]


def test_catalogue_ids_are_unique():
    ids = [m["id"] for m in models.catalogue()]
    assert len(ids) == len(set(ids))


def test_resolve_accepts_a_known_id():
    known = models.catalogue()[0]["id"]
    assert models.resolve(known) == known


def test_resolve_rejects_unknown_and_empty():
    # The whole point: junk in the column must not become a provider call.
    assert models.resolve("anthropic/claude-retired-9") is None
    assert models.resolve("not-a-model") is None
    assert models.resolve("") is None
    assert models.resolve(None) is None


def test_resolve_rejects_a_plausible_but_wrong_slug():
    # The default config once carried 'claude-sonnet-4-5' (hyphens) which is NOT a
    # real OpenRouter id; the registry must not wave that class of typo through.
    assert models.resolve("anthropic/claude-sonnet-4-5") is None


# --- request-scoped override ------------------------------------------------ #

def test_response_model_falls_back_to_config_when_unset():
    request_context.set_response_model(None)
    assert response_gen._response_model() == APP_CONFIG.response_model_resolved


def test_response_model_uses_the_request_override():
    chosen = models.catalogue()[0]["id"]
    request_context.set_response_model(chosen)
    try:
        assert response_gen._response_model() == chosen
    finally:
        request_context.set_response_model(None)


def test_segment_reasoner_label_honours_the_override():
    """Dual-render maps the 'reasoner' role onto the response tier, so the user's
    choice must apply there too — not just on the single-model path."""
    chosen = models.catalogue()[0]["id"]
    request_context.set_response_model(chosen)
    try:
        assert response_gen._resolve_segment_model("reasoner") == chosen
    finally:
        request_context.set_response_model(None)
