"""Create a local development bearer key through the migration-owner connection."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy import create_engine

from procurement.access import AccessRole
from procurement.storage import ApiKeyRecord, PostgresStorage, api_key_digest


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a local development API key")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument(
        "--access-role",
        choices=[role.value for role in AccessRole],
        default=AccessRole.OPERATOR.value,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_ADMIN_URL")
    if not database_url:
        raise SystemExit("DATABASE_ADMIN_URL is required")
    secret = secrets.token_urlsafe(32)
    record = ApiKeyRecord(
        key_id=str(uuid.uuid4()),
        company_id=args.company_id,
        actor_id=args.actor_id,
        access_role=AccessRole(args.access_role),
        key_digest=api_key_digest(secret),
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        created = PostgresStorage(engine).register_api_key(record)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "company_id": created.company_id,
                "actor_id": created.actor_id,
                "access_role": created.access_role.value,
                "key_id": created.key_id,
                "bearer_secret": secret,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
