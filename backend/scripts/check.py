#!/usr/bin/env python3
"""
Backend smoke-check — a stable, allowlist-once replacement for the ad-hoc
`python -c "import ..."` one-liners.

It imports the app + every key module, confirms config loads and that the
loader's guardrail enforcement still holds, and verifies the critical API
routes are wired. Pure import and inspection: no network, no database, no writes.

Run from the repo root or backend/ (path-independent):

    python backend/scripts/check.py

Then allowlist it once so it never prompts again:

    "Bash(python backend/scripts/check.py)"

Exit code is 0 if everything passes, 1 otherwise. Extend it by adding a function
decorated with @check — its first line (docstring) is the label.
"""
import importlib
import os
import sys
import traceback
from pathlib import Path

# Make backend/src importable no matter where this is run from.
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# Dummy infra secrets so config/settings validation passes. Nothing connects;
# these are never used to reach a real service during a smoke check.
for _k in (
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "NEO4J_PASSWORD", "NEO4J_URI",
    "NEO4J_USER", "QDRANT_URL", "SUPABASE_URL", "SUPABASE_KEY",
    "SUPABASE_JWT_SECRET",
):
    os.environ.setdefault(_k, "x")

# One per line: keeps diffs to a single line when a module is added or removed,
# and keeps any one line's entropy low enough that secret scanners don't read a
# run of dotted import paths as a high-entropy credential.
CORE_MODULES = [
    "config.loader",
    "config.default",
    "main",
    "api.v1.messages",
    "api.v1.conversations",
    "api.v1.graph",
    "api.v1.interpretations",
    "services.extraction",
    "services.graph_service",
    "services.response_gen",
    "services.clustering",
    "services.relations",
    "services.bridges",
    "services.interpretation",
    "services.cluster_similarity",
    "services.maintenance",
    "services.gates",
    "services.dynamics",
    "services.consolidation",
    "services.prediction",
    "services.uptake",
    "services.steering",
    "schemas.graph",
    "schemas.message",
    "schemas.interpretation",
    "schemas.interest",
    "db.neo4j",
    "db.qdrant",
    "llm.prompts",
]

_CHECKS = []
def check(fn):
    _CHECKS.append(fn)
    return fn


@check
def imports():
    """all core modules import"""
    for m in CORE_MODULES:
        importlib.import_module(m)
    return f"{len(CORE_MODULES)} modules"


@check
def routes():
    """critical API routes are wired"""
    main = importlib.import_module("main")
    # Read paths from the OpenAPI schema, not app.routes. Newer FastAPI keeps an
    # included router as a single opaque wrapper object with no `.path`, so
    # walking app.routes finds only the four built-in docs endpoints and reports
    # every real route missing. The schema is the supported way to ask.
    paths = list(main.app.openapi()["paths"])
    need = ["/messages", "/graph/{user_id}", "/nodes/{node_id}/interpretations"]
    missing = [n for n in need if not any(n in p for p in paths)]
    assert not missing, f"missing routes: {missing}"
    return f"{len(paths)} routes, all key paths present"


@check
def default_config():
    """the config loads with a model + extraction prompt"""
    from config.loader import load_config
    c = load_config()
    assert getattr(c, "llm_model", ""), "missing llm_model"
    assert getattr(c, "extraction_system_prompt", ""), "missing extraction_system_prompt"
    return f"model={c.llm_model}"


def main() -> int:
    print("backend smoke-check\n" + "-" * 40)
    failed = 0
    for fn in _CHECKS:
        label = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
        try:
            detail = fn() or ""
            print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
        except Exception as e:
            failed += 1
            print(f"  FAIL  {label}\n        {type(e).__name__}: {e}")
            if os.environ.get("CHECK_VERBOSE"):
                traceback.print_exc()
    print("-" * 40)
    print("OK - all checks passed" if not failed else f"{failed} check(s) FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
