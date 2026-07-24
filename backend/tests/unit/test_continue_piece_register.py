"""A piece must not fall out of the generative register on its second beat.

Register detection reads the message text alone. That is right for a fresh
request but wrong for a continuation: a reaction chip's instruction ("Move to
the next phase: propose what a beat tracker would need") reads as ordinary
conversation, so the turn after a piece was classified conversational, stored no
generative register, and the client stopped offering chips — the co-writing loop
died one turn in and could not restart.
"""
from types import SimpleNamespace

import pytest

from api.v1.messages import GENERATIVE_MODES, _resolve_render_mode
from services.render_mode import detect_render_mode


def _body(message: str, continue_piece: bool = False):
    return SimpleNamespace(message=message, continue_piece=continue_piece)


# The real chip instructions that shipped with the bug.
CHIP_INSTRUCTIONS = [
    "Move to the next phase: propose what a beat tracker or MIR pipeline would need",
    "Make it concrete with a track",
    "Show it on a real grid",
    "Check it against a fact-schema",
]


@pytest.mark.parametrize("instruction", CHIP_INSTRUCTIONS)
def test_chip_instructions_alone_do_not_read_as_generative(instruction):
    """Guards the premise. If detection ever learns to recognise these on its own
    this test fails loudly rather than leaving the continuation flag looking
    pointless."""
    assert detect_render_mode(instruction, "primary") not in GENERATIVE_MODES


@pytest.mark.parametrize("instruction", CHIP_INSTRUCTIONS)
def test_continuation_keeps_a_piece_generative(instruction):
    assert _resolve_render_mode(_body(instruction, continue_piece=True), "primary") in (
        GENERATIVE_MODES
    )


def test_continuation_does_not_downgrade_an_explicit_piece_request():
    """A continuation that ALREADY reads as generative keeps its own mode rather
    than being rewritten to 'author'."""
    msg = "Let's keep going — your turn"
    detected = detect_render_mode(msg, "primary")
    assert detected == "cowrite"
    assert _resolve_render_mode(_body(msg, continue_piece=True), "primary") == "cowrite"


def test_without_the_flag_conversation_stays_conversational():
    """The flag is the only thing that forces the register — an ordinary message
    must never be promoted to a piece."""
    msg = "Which of the four bins is hardest to detect?"
    assert _resolve_render_mode(_body(msg, continue_piece=False), "primary") == "conversational"


def test_analytic_branch_is_never_forced_generative():
    """session_type='analytic' is analysis unconditionally; a stray continuation
    flag must not turn the analytic branch into a piece generator."""
    assert (
        _resolve_render_mode(_body("Move to the next phase", continue_piece=True), "analytic")
        == "analysis"
    )
