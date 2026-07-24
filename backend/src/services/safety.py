import json
import logging
from enum import Enum

from pydantic import BaseModel

from config.loader import APP_CONFIG
from llm.client import chat

logger = logging.getLogger(__name__)


class SafetyDecision(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"


class SafetyResult(BaseModel):
    decision: SafetyDecision
    categories: list[str] = []   # which categories tripped, for audit logging
    reasoning: str = ""          # graded-judgment rationale (reasoning moderation)
    raw: str = ""                # raw classifier/judge output for audit


def _parse_guardrail_output(raw: str) -> SafetyResult:
    """
    Binary classifier path. Llama Guard returns "safe" or "unsafe\\n<categories>".
    Other classifiers that return a single word also work.
    """
    lines = (raw or "").strip().split("\n")
    decision = SafetyDecision.SAFE if lines[0].strip().lower() == "safe" else SafetyDecision.UNSAFE
    categories = [c.strip() for c in lines[1].split(",")] if len(lines) > 1 else []
    return SafetyResult(decision=decision, categories=categories, raw=raw or "")


def _strip_fence(raw: str | None) -> str:
    """Strip a leading/trailing ``` fence so json.loads can read a judged verdict."""
    if not raw:
        return ""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _reasoning_enabled() -> bool:
    return bool(
        APP_CONFIG.use_reasoning_moderation
        and APP_CONFIG.moderation_model
        and APP_CONFIG.moderation_rubric
    )


async def _binary_floor(prompt: str, user_content: str) -> SafetyResult | None:
    """
    Tier 1 — the hard floor. A binary classifier scoped to the inherently-illegal
    bright line (e.g. content involving minors, real-world harm instructions,
    targeted harassment of a real person). Strict and framing-independent: it
    does NOT defer to stated intent or framing. Returns None when no binary
    floor is configured (guardrail_model + prompt), so the caller falls through
    to the reasoning judge. A floor refusal is tagged 'hard_floor' for audit.
    """
    if not (APP_CONFIG.guardrail_model and prompt):
        return None
    raw = await chat(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        model=APP_CONFIG.guardrail_model,
        temperature=0.0,
        max_tokens=APP_CONFIG.moderation_max_tokens,
    )
    result = _parse_guardrail_output(raw)
    if result.decision == SafetyDecision.UNSAFE and not result.categories:
        result.categories = ["hard_floor"]
    return result


async def _reason_moderation(content: str, original_message: str | None) -> SafetyResult:
    """
    Graded reasoning judgment. A capable model applies the two-tier rubric to the
    content (with the originating user message for context) and returns a verdict
    with reasoning rather than a category label. The rubric encodes the bright
    line (always-refuse) and the err-toward-allowing posture for ambiguous cases.

    Parse failures err toward ALLOW (and log loudly): over-refusing ordinary
    personal material would make the product useless, and a malformed judge
    response should not manufacture an accusatory refusal. Clear bright-line
    cases produce well-formed refusals.
    """
    system = (
        APP_CONFIG.moderation_rubric
        + '\n\nReturn ONLY a JSON object: '
        '{"decision": "allow" | "refuse", "category": "<short tag or empty>", '
        '"reasoning": "<one sentence>"}.'
    )
    user = f"Content to judge:\n{content}"
    if original_message:
        user = f"User message:\n{original_message}\n\n{user}"

    raw = await chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=APP_CONFIG.moderation_model,
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=APP_CONFIG.moderation_max_tokens,
    )
    # A judge can return null content (e.g. it refused to engage). That is NOT a
    # safe verdict, but the bright line is owned by the Tier-1 binary floor, not
    # this judge — so on an unreadable verdict we err open here and log loudly.
    try:
        data = json.loads(_strip_fence(raw))
        refuse = str(data.get("decision", "")).strip().lower() == "refuse"
        category = data.get("category") or ""
        result = SafetyResult(
            decision=SafetyDecision.UNSAFE if refuse else SafetyDecision.SAFE,
            categories=[category] if category else [],
            reasoning=str(data.get("reasoning", "")),
            raw=raw,
        )
        # Always log the verdict so a refusal is never a mystery — the judge's
        # reasoning is the single most useful signal for tuning the rubric and
        # telling a rubric gap apart from judge over-caution.
        logger.info(
            "moderation_verdict",
            extra={
                "model": APP_CONFIG.moderation_model,
                "decision": result.decision.value,
                "category": category,
                "reasoning": result.reasoning,
                "content_snippet": content[:160],
            },
        )
        return result
    except (json.JSONDecodeError, TypeError, AttributeError):
        logger.warning(
            "moderation verdict parse failure; erring toward allow",
            extra={"raw_output": raw},
        )
        return SafetyResult(decision=SafetyDecision.SAFE, raw=raw or "")


async def check_input(message: str) -> SafetyResult:
    """
    Judge the user's input before any work (B1). Two tiers:
      1. Hard-floor binary classifier — strict, framing-independent. Short-circuits.
      2. Reasoning judge — graded judgment for the grey middle, erring toward allow.
    With neither configured, returns SAFE. With only the binary configured, the
    binary verdict stands (legacy behavior).
    """
    if not APP_CONFIG.use_input_guardrail:
        return SafetyResult(decision=SafetyDecision.SAFE)

    floor = await _binary_floor(APP_CONFIG.input_guardrail_prompt, message)
    if floor is not None and floor.decision == SafetyDecision.UNSAFE:
        logger.warning("hard_floor tripped (input)", extra={"categories": floor.categories})
        return floor

    if _reasoning_enabled():
        return await _reason_moderation(message, None)

    return floor or SafetyResult(decision=SafetyDecision.SAFE)


async def check_output(response: str, original_message: str) -> SafetyResult:
    """Judge the model output before returning it to the client (B1). See check_input."""
    if not APP_CONFIG.use_output_guardrail:
        return SafetyResult(decision=SafetyDecision.SAFE)

    floor_content = f"Input: {original_message}\n\nOutput: {response}"
    floor = await _binary_floor(APP_CONFIG.output_guardrail_prompt, floor_content)
    if floor is not None and floor.decision == SafetyDecision.UNSAFE:
        logger.warning("hard_floor tripped (output)", extra={"categories": floor.categories})
        return floor

    if _reasoning_enabled():
        return await _reason_moderation(response, original_message)

    return floor or SafetyResult(decision=SafetyDecision.SAFE)
