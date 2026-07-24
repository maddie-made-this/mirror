#!/usr/bin/env python3
"""
Hard-delete a user across every store (product reshape §10.2 / P5.1) — the CLI wrapper
around services.account_delete.delete_user. Purges Postgres, Neo4j, Qdrant, then the
Supabase auth identity. Irreversible; backups expire ≤30 days.

Run from backend/:
    PYTHONPATH=src python scripts/delete_user.py <user_id> --yes
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

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
    parser = argparse.ArgumentParser(description="Hard-delete a user across all stores.")
    parser.add_argument("user_id", type=UUID)
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    if not args.yes:
        confirm = input(f"Permanently delete ALL data for {args.user_id}? Type DELETE: ")
        if confirm != "DELETE":
            print("Aborted.")
            return

    from db.neo4j import init_driver, close_driver
    from db.qdrant import init_client, close_client
    from services.account_delete import delete_user

    await init_driver()
    await init_client()
    try:
        status = await delete_user(args.user_id)
    finally:
        await close_client()
        await close_driver()
    print(f"Done. Per-store status: {status}")


if __name__ == "__main__":
    asyncio.run(main())
