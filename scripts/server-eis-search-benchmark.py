"""Synthetic scale check, strictly restricted to the disposable PostgreSQL gate DB."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url

from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import EisReadyWindow, ingest_ready_window
from procurement.storage.eis_search_index import backfill_search_keys
from procurement.storage.models import eis_notice_versions
from procurement.storage.repository import PostgresStorage

TEST_DATABASE = "procurement_eis_test_20260928"
SIZE = 50_000


def main() -> None:
    # Always rewrite both URLs; this script never seeds the production database.
    url = make_url(os.environ["DATABASE_URL"]).set(database=TEST_DATABASE)
    engine = create_engine(url)
    admin_engine = create_engine(
        make_url(os.environ["DATABASE_ADMIN_URL"]).set(database=TEST_DATABASE)
    )
    company = f"synthetic-benchmark-{uuid.uuid4()}"
    storage = PostgresStorage(engine)
    now = datetime.now(UTC)
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "seed.xml",
            """<export xmlns="http://zakupki.gov.ru/oos/export/1">
<epNotificationEF2020><versionNumber>1</versionNumber><commonInfo>
<purchaseNumber>9000000000000000000</purchaseNumber>
<purchaseObjectInfo>Seed benchmark</purchaseObjectInfo>
</commonInfo><notificationInfo/></epNotificationEF2020></export>""",
        )
    try:
        ingest_ready_window(
            storage,
            company,
            EisReadyWindow("getDocsIP/PRIZ/50/2026-09-25+03:00", "a" * 64, 1, (output.getvalue(),)),
            actor_id="synthetic-benchmark",
        )
        with storage.transaction(company) as connection:
            template = dict(connection.execute(select(eis_notice_versions)).mappings().one())
            # Synthetic SQL fixtures measure query cost; not source coverage/provenance proof.
            for start in range(1, SIZE, 500):
                rows = []
                for number in range(start, min(start + 500, SIZE)):
                    title = "Поставка серверного оборудования" if number % 1000 == 0 else "Бумага"
                    rows.append(
                        {
                            **template,
                            "purchase_number": f"{9000000000000000000 + number}",
                            "title": title,
                            "xml_sha256": hashlib.sha256(str(number).encode()).hexdigest(),
                        }
                    )
                connection.execute(insert(eis_notice_versions), rows)
        with admin_engine.begin() as connection:
            connection.execute(text("ANALYZE eis_notice_versions"))
        before = search_eis_index(storage, company, "серверное оборудование", now=now)
        assert before.inspected_current_notices == SIZE and before.matched_count == 49
        assert backfill_search_keys(storage, company, actor_id="synthetic-benchmark") == SIZE - 1
        with admin_engine.begin() as connection:
            connection.execute(text("ANALYZE eis_notice_search_keys"))
        samples = []
        for _ in range(5):
            after = search_eis_index(storage, company, "серверное оборудование", now=now)
            assert after.matched == before.matched
            assert after.evaluated_candidate_notices == 49 and after.unindexed_versions == 0
            samples.append(after.search_elapsed_ms)
        print(
            json.dumps(
                {
                    "fixture": "SYNTHETIC",
                    "current_cards": SIZE,
                    "matched": after.matched_count,
                    "before_ms": before.search_elapsed_ms,
                    "after_ms": samples,
                    "before_evaluated": before.evaluated_candidate_notices,
                    "after_evaluated": after.evaluated_candidate_notices,
                    "source_coverage": "UNKNOWN",
                }
            )
        )
    finally:
        engine.dispose()
        admin_engine.dispose()


if __name__ == "__main__":
    main()
