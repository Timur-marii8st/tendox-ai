"""Print only scoped EIS failure metadata; never source bytes or credentials."""

from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, func, select

from procurement.storage.models import eis_sync_attempts
from procurement.storage.repository import PostgresStorage


def main() -> None:
    company_id = os.environ.get("EIS_COMPANY_ID", "local-eis-supplier")
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        storage = PostgresStorage(engine)
        attempts = eis_sync_attempts
        with storage.transaction(company_id, consistent_read=True) as connection:
            codes = connection.execute(
                select(attempts.c.reason_code, func.count().label("count"))
                .where(attempts.c.company_id == company_id, attempts.c.outcome == "FAILED")
                .group_by(attempts.c.reason_code)
                .order_by(func.count().desc())
            ).all()
            recent = connection.execute(
                select(attempts.c.window_key, attempts.c.reason_code, attempts.c.attempted_at)
                .where(attempts.c.company_id == company_id, attempts.c.outcome == "FAILED")
                .order_by(attempts.c.attempted_at.desc())
                .limit(12)
            ).all()
        print(
            json.dumps(
                {
                    "failure_codes": {code or "UNKNOWN": count for code, count in codes},
                    "recent_failed_windows": [
                        {"window_key": key, "reason_code": code, "attempted_at": at.isoformat()}
                        for key, code, at in recent
                    ],
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
