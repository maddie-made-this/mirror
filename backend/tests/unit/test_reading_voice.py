"""
Grammatical-person consistency across reading kinds.

Every reading rendered in the same card pane must use ONE grammatical person.
BRIDGE was written in the second person while ORIGIN/FUNCTION/etc. are third
person, so one pane showed two voices.

Third person is the correct target, and not merely for tidiness: the injected
reading kinds are spliced into a SYSTEM prompt under the header "What you've come
to understand about this person", where "you" addresses the MODEL. A statement
saying "you keep circling X" would read as a claim about the assistant itself.
"""
import re

from services import bridges, interpretation


# Second-person pronouns as they'd appear in a statement ABOUT the user.
#
# Two legitimate uses have to be excluded first, or this flags the prompt for
# doing its job: the prompt addresses the MODEL as "you" ("you emit", "you
# fill"), and it QUOTES the banned pronouns to prohibit them ("never 'you' or
# 'your'"). Naming forbidden tokens concretely is better prompting than an
# abstract rule, so strip single-quoted tokens before scanning the prose.
_QUOTED_TOKEN = re.compile(r"'[^']{1,12}'")
_SECOND_PERSON_EXEMPLAR = re.compile(r"\byour\b", re.IGNORECASE)


def _prose_only(prompt: str) -> str:
    """The prompt with single-quoted tokens removed — i.e. instruction prose and
    the worked example, minus any pronouns being quoted in order to ban them."""
    return _QUOTED_TOKEN.sub("", prompt)


def test_bridge_prompt_mandates_third_person():
    assert "THIRD person" in bridges._BRIDGE_SYSTEM


def test_bridge_exemplar_is_not_second_person():
    """The worked example teaches the voice more strongly than the instruction —
    the original exemplar was second person, which is what the model copied."""
    assert not _SECOND_PERSON_EXEMPLAR.search(_prose_only(bridges._BRIDGE_SYSTEM))


def test_bridge_prompt_forbids_guessed_gender():
    """Matches the subject-firewall rule the other reading kinds already carry."""
    assert "gendered pronoun" in bridges._BRIDGE_SYSTEM


def test_reflection_prompt_still_mandates_third_person():
    """Guards the other side of the invariant: tier-3 must not drift to second
    person either, or the same inconsistency reappears from the opposite end."""
    import inspect
    text = inspect.getsource(interpretation)
    assert "STABLE third person" in text
    assert "never assume their gender" in text


def test_bridge_exemplar_names_concrete_domain_material():
    """The exemplar has to model the intended domain, not just avoid the wrong one —
    a vague example produces vague bridges."""
    assert "For example:" in bridges._BRIDGE_SYSTEM
    assert "debugging" in bridges._BRIDGE_SYSTEM
