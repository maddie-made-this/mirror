#!/usr/bin/env python3
"""
Backfill the provenance spine (product reshape §1.2 / P0.1) onto legacy :Node and
:Mention rows created before provenance existed. Idempotent (WHERE prov_source IS NULL) —
safe to re-run. Defaults match how everything was created pre-provenance: a conversation
turn the user volunteered.

Run from backend/:
    PYTHONPATH=src python scripts/backfill_provenance.py
"""
import asyncio
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "src"))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(_BACKEND / ".env")


async def main() -> None:
    from db.neo4j import get_session, init_driver

    await init_driver()
    async with get_session() as s:
        for label in ("Node", "Mention"):
            res = await s.run(
                f"""
                MATCH (n:{label})
                WHERE n.prov_source IS NULL
                SET n.prov_source = 'conversation', n.prov_elicited = 'volunteered'
                RETURN count(n) AS c
                """
            )
            rec = await res.single()
            print(f"{label}: stamped {rec['c']} legacy rows")
    print("Done. Idempotent — a second run stamps 0.")


if __name__ == "__main__":
    asyncio.run(main())
