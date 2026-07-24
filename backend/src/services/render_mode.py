"""
Render-mode detection (master spec C3 §3a). The mode is INFERRED from register, not
user-selected: each generation turn is one of

  - "author"        : the user requested a COMPLETE authored piece ("write me an
                      essay about…", "I want a piece where…", "a short essay on…").
                      One-shot long-form — one director brief → one full-piece render.
                      The PRIMARY long-form-authoring function; bypasses the
                      turn-by-turn beat machine entirely.
  - "cowrite"       : the user signalled INTERACTIVE co-writing — turn-by-turn
                      collaboration ("let's write this together", "your turn", "keep
                      going"). Loads the
                      heavy turn-by-turn director + arc apparatus (split/dual).
  - "analysis"      : the user asked to understand themselves ("why do I keep coming
                      back to…", "where does this come from"), or the conversation is
                      the explicit analytic branch. Single reasoner call, analysis voice.
  - "conversational": everything else — the DEFAULT. Cheap ResponseStance director +
                      one renderer call.

Tie-break is "conversational" by design (master spec §4: drifting to analysis — or
spinning up a whole generation apparatus — when the user just wanted to talk is the
killer failure). First cut is keyword/regex only (no extra LLM call, so the
conversational path stays cheap); a short LLM disambiguation of the ambiguous middle
can be layered on later behind the same interface.
"""
from __future__ import annotations

import re

# Long-form AUTHORED-piece request ("write me an essay about…", "I want a piece
# where…", "a short essay on…"). This is a PRIMARY function and is ONE-SHOT: the user
# wants a complete piece authored start-to-finish, NOT a turn-by-turn collaboration. It
# routes to the dedicated author path (no beat machine). Three shapes: a write/make verb
# on a piece noun; an "I want … a piece" request; and a bare descriptor+piece-noun
# phrase with no lead verb. ("co-write/your turn" belong to interactive piece, and bare
# "something" is too ambiguous to force one-shot — both intentionally excluded here.)
_AUTHOR_PATTERNS = [
    re.compile(r"\b(write|describe|narrate|continue|start|give me|do|tell|make|craft|"
               r"compose|generate)\b[^.?!]{0,40}\b(piece|essay|passage|stor(y|ies)|"
               r"exploration|meditation|reflection|it out)\b", re.I),
    re.compile(r"\b(i want|i'?d like|i would like|can i (get|have)|gimme|i need)\b"
               r"[^.?!]{0,40}\b(piece|essay|passage|stor(y|ies)|exploration|meditation)\b", re.I),
    re.compile(r"\b(short|long|quick|proper|full|little)\s+"
               r"(piece|essay|passage|stor(y|ies)|exploration|meditation|reflection)\b", re.I),
]

# Writing signalled but INTERACTIVE — turn-by-turn co-writing (the side capability).
# Loads the heavy turn-by-turn director + arc apparatus (split/dual). These are "let's
# write this together", "your turn", "keep going" — the user wants to
# BUILD a piece beat by beat, not receive a finished one.
_COWRITE_PATTERNS = [
    re.compile(r"\b(let'?s|wanna|want to|can we)\b[^.?!]{0,20}\b(co-?write|write together|"
               r"riff|brainstorm|play|act)\b", re.I),
    re.compile(r"\b(your turn|my turn|keep going|pick it up|take it from)\b", re.I),
    re.compile(r"\bwhat (would|do) you (write|add|say)\b[^.?!]{0,20}\bnext\b", re.I),
    re.compile(r"\bset the piece\b", re.I),
]

# The user is asking to understand THEMSELVES — analysis register. The bar is an
# explicit, unambiguous bid to understand oneself; plain topic disclosure, however
# detailed, is NEVER analysis (next_test_tech_spec C4). So the "what does it mean/say"
# cue requires a self-reference ("about me/myself" or "that I") — it must not fire on
# "what does it say about HIM" inside a piece.
_ANALYSIS_PATTERNS = [
    re.compile(r"\bwhy (do|am|is|are|does|did|would) i\b", re.I),
    re.compile(r"\bwhere does (this|that|it|my)\b[^.?!]{0,30}\bcome from\b", re.I),
    re.compile(r"\bwhat does it (mean|say)\b[^.?!]{0,20}\b(about (me|myself)|that i)\b", re.I),
    re.compile(r"\b(analy[sz]e|unpack|make sense of|understand why|figure out why)\b", re.I),
    re.compile(r"\bwhy (i'?m|am i) drawn to\b", re.I),
]


def detect_render_mode(message: str, session_type: str = "primary") -> str:
    """Return 'author' | 'cowrite' | 'analysis' | 'conversational' for this turn. The
    explicit analytic branch (session_type=='analytic') is always analysis; otherwise
    infer from the message, defaulting to conversational when nothing clearly signals.
    Author is checked BEFORE piece: a complete-piece request is unambiguously one-shot
    authoring, so it must never be caught by an interactive co-writing pattern."""
    if session_type == "analytic":
        return "analysis"
    msg = message or ""
    if any(p.search(msg) for p in _AUTHOR_PATTERNS):
        return "author"
    if any(p.search(msg) for p in _COWRITE_PATTERNS):
        return "cowrite"
    if any(p.search(msg) for p in _ANALYSIS_PATTERNS):
        return "analysis"
    return "conversational"
