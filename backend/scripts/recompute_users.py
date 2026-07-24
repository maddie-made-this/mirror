#!/usr/bin/env python3
"""
Run the maintenance pipeline (cluster -> cluster-similarity -> interpret reflection
-> motif reflection -> bridges) for specific users ON DEMAND — e.g. right after a
test run, before dumping, so the readings/interpretations reflect the full
conversation instead of waiting on the background scheduler's interval.

    PYTHONPATH=src python scripts/recompute_users.py <user_uuid> [<user_uuid> ...]
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

_B = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_B / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass
for line in (_B / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


async def main(uids: list[str]) -> None:
    from db.neo4j import close_driver, init_driver
    from db.postgres import close_pool, init_pool
    from db.qdrant import close_client, init_client
    from services.maintenance import _run_user_pipeline

    await init_driver()
    await init_pool()
    await init_client()
    try:
        for u in uids:
            print(f"recompute {u} ...", flush=True)
            try:
                await _run_user_pipeline(UUID(u))
                print(f"  done {u}", flush=True)
            except Exception as exc:
                print(f"  FAILED {u}: {type(exc).__name__}: {exc}", flush=True)
    finally:
        await close_driver()
        await close_pool()
        await close_client()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: recompute_users.py <user_uuid> [...]")
        sys.exit(1)
    asyncio.run(main(sys.argv[1:]))
