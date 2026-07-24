"""Request-scoped ambient values (contextvars).

Async-safe per-request state that would otherwise have to thread through many hot-path
signatures. Contextvars are copied when a task is created, so a value set inside one
request handler never leaks to another request.

Currently:
  - the P4.1 learned length target. The message handler resolves it once from the
    user's render_prefs and sets it here; format_rules.render reads it at prompt-build
    time, deep inside the renderer builders, without every builder growing a parameter.
  - the user's chosen response model. Same shape: resolved once per turn from the
    profile, read at each generation call site. Threading it through instead would
    mean a new parameter on every generate/stream function for a value that is
    ambient to the request.
"""
import contextvars

_target_words: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "render_target_words", default=None
)

_response_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "response_model_override", default=None
)


def set_target_words(value: int | None) -> None:
    _target_words.set(value)


def get_target_words() -> int | None:
    return _target_words.get()


def set_response_model(value: str | None) -> None:
    _response_model.set(value)


def get_response_model() -> str | None:
    """The per-user response model for this request, or None to use the config default."""
    return _response_model.get()
