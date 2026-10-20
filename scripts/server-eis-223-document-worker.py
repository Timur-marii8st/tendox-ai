"""One bounded queued223file; source secrets never appear in stdout."""

import json
import os

from sqlalchemy import create_engine

from procurement.sources.eis_223_document_worker import run_document223_step
from procurement.storage.repository import PostgresStorage

engine = create_engine(os.environ["DATABASE_URL"])
try:
    result = run_document223_step(
        PostgresStorage(engine), "local-eis-supplier", actor_id="223-document-worker"
    )
    print(result.model_dump_json())
except Exception:
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason": "DOCUMENT_223_WORKER_UNAVAILABLE",
                "eligibility": "UNKNOWN",
            }
        )
    )
    raise SystemExit(1) from None
finally:
    engine.dispose()
