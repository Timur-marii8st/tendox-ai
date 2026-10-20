"""SQL invariants for server-managed AI requirement materialization receipts."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import test_document_storage as helpers
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import DBAPIError

from procurement.storage import PostgresStorage
from procurement.storage.models import (
    ai_transfer_raw_responses,
    ai_transfer_requests,
    ai_transfer_requirement_materializations,
    document_ai_requirement_runs,
)


@pytest.fixture(scope="module")
def sql_storage():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    engine = create_engine(url)
    yield PostgresStorage(engine, raw_key_provider=helpers._EphemeralTenantKekProvider())
    engine.dispose()


@pytest.fixture()
def materialization_template(sql_storage):
    tenant = f"materialization-sql-{uuid.uuid4()}"
    admission, claim = helpers._claimed_ai_transfer(sql_storage, tenant)
    receipt, metadata = sql_storage.persist_captured_ai_transfer_result(
        tenant,
        claim.claimed_by,
        admission.execution_id,
        helpers._successful_transport_attempt(claim),
        helpers.SYNTHETIC_RAW_RESPONSE,
    )
    with sql_storage.transaction(tenant) as connection:
        request = dict(
            connection.execute(
                select(ai_transfer_requests).where(
                    ai_transfer_requests.c.transfer_id == claim.transfer_id
                )
            )
            .mappings()
            .one()
        )
        raw = dict(
            connection.execute(
                select(ai_transfer_raw_responses).where(
                    ai_transfer_raw_responses.c.raw_response_id == metadata.raw_response_id
                )
            )
            .mappings()
            .one()
        )
    return tenant, claim, receipt, raw, request


def _row(template, **changes):
    tenant, claim, receipt, raw, request = template
    materialized_at = datetime.now(UTC)
    row = {
        "company_id": tenant,
        "materialization_id": f"materialization-{uuid.uuid4()}",
        "transfer_id": claim.transfer_id,
        "execution_id": claim.execution_id,
        "ordinal": 1,
        "claim_id": claim.claim_id,
        "receipt_id": receipt.receipt_id,
        "raw_response_id": raw["raw_response_id"],
        "request_payload_sha256": request["payload_sha256"],
        "claim_payload_sha256": claim.payload_sha256,
        "receipt_payload_sha256": receipt.payload_sha256,
        "raw_metadata_sha256": raw["metadata_sha256"],
        "parser_version": "ai-transfer-requirement-parser-v1",
        "status": "REJECTED",
        "reason": "INVALID_CANDIDATE_EVIDENCE",
        "result_id": None,
        "result_payload_sha256": None,
        "run_id": None,
        "run_evidence_sha256": None,
        "materialized_by": "materializer",
        "materialized_at": materialized_at,
        "payload_sha256": "d" * 64,
        "created_at": materialized_at,
    }
    row.update(changes)
    receipt_json = {
        "schema_version": "ai-transfer-requirement-materialization-v1",
        **{
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items()
            if key not in {"materialization", "created_at"}
        },
    }
    row["materialization"] = receipt_json
    return row


def test_valid_rejected_materialization_is_immutable_and_tenant_scoped(
    sql_storage, materialization_template
):
    row = _row(materialization_template)
    tenant = row["company_id"]
    with sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_requirement_materializations).values(**row))
    with sql_storage.transaction(tenant) as connection:
        stored = (
            connection.execute(
                select(ai_transfer_requirement_materializations).where(
                    ai_transfer_requirement_materializations.c.materialization_id
                    == row["materialization_id"]
                )
            )
            .mappings()
            .one()
        )
        assert stored["materialization"] == row["materialization"]
    with sql_storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            ai_transfer_requirement_materializations.update()
            .where(
                ai_transfer_requirement_materializations.c.materialization_id
                == row["materialization_id"]
            )
            .values(reason="UNSUPPORTED_MULTI_CHUNK")
        )
    with sql_storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            ai_transfer_requirement_materializations.delete().where(
                ai_transfer_requirement_materializations.c.materialization_id
                == row["materialization_id"]
            )
        )
    with sql_storage.transaction(f"other-{uuid.uuid4()}") as connection:
        assert connection.execute(select(ai_transfer_requirement_materializations)).all() == []


@pytest.mark.parametrize("field,value", [("status", "MATERIALIZED"), ("reason", "MATERIALIZED")])
def test_materialization_rejects_forged_scalar_projection(
    sql_storage, materialization_template, field, value
):
    row = _row(materialization_template)
    row[field] = value
    with (
        pytest.raises(DBAPIError) as error,
        sql_storage.transaction(row["company_id"]) as connection,
    ):
        connection.execute(insert(ai_transfer_requirement_materializations).values(**row))
    assert error.value.orig.sqlstate == "23514"


def test_materialization_rejects_extra_json_and_forged_fk(sql_storage, materialization_template):
    row = _row(materialization_template)
    row["materialization"] = {**row["materialization"], "untrusted": True}
    with (
        pytest.raises(DBAPIError) as error,
        sql_storage.transaction(row["company_id"]) as connection,
    ):
        connection.execute(insert(ai_transfer_requirement_materializations).values(**row))
    assert error.value.orig.sqlstate == "23514"

    forged = _row(materialization_template, claim_payload_sha256="0" * 64)
    forged["materialization"]["claim_payload_sha256"] = "0" * 64
    with (
        pytest.raises(DBAPIError) as error,
        sql_storage.transaction(forged["company_id"]) as connection,
    ):
        connection.execute(insert(ai_transfer_requirement_materializations).values(**forged))
    assert error.value.orig.sqlstate == "23503"


def test_materialization_blocks_cross_tenant_insert(sql_storage, materialization_template):
    row = _row(materialization_template)
    other = f"other-{uuid.uuid4()}"
    with pytest.raises(DBAPIError), sql_storage.transaction(other) as connection:
        connection.execute(insert(ai_transfer_requirement_materializations).values(**row))


def test_run_snapshot_v1_accepts_exact_shape_and_orphan_v2_is_rejected(
    sql_storage, materialization_template
):
    tenant, _, _, _, request = materialization_template
    now = datetime.now(UTC)
    v1_id = f"run-v1-{uuid.uuid4()}"
    v1 = {
        "schema_version": "persisted-ai-requirement-run-v1",
        "origin": "IMPORTED_REPORT",
        "company_id": tenant,
        "run_id": v1_id,
        "source_document_id": request["source_document_id"],
        "source_sha256": request["source_sha256"],
        "extraction": {},
        "report": {},
        "completeness_status": "UNKNOWN",
        "submitted_by": "importer",
        "submitted_at": now.isoformat(),
        "evidence_sha256": "a" * 64,
    }
    v2_id = f"run-v2-{uuid.uuid4()}"
    v2 = {
        "schema_version": "persisted-ai-requirement-run-v2",
        "origin": "SERVER_MANAGED_TRANSFER",
        "company_id": tenant,
        "run_id": v2_id,
        "source_document_id": request["source_document_id"],
        "source_sha256": request["source_sha256"],
        "extraction": {},
        "result": {
            "company_id": tenant,
            "result_id": f"result-{uuid.uuid4()}",
            "prepared_by": "preparer",
            "materialized_by": "materializer",
            "materialized_at": now.isoformat(),
        },
        "completeness_status": "UNKNOWN",
        "prepared_by": "preparer",
        "materialized_by": "materializer",
        "materialized_at": now.isoformat(),
        "evidence_sha256": "b" * 64,
    }
    with sql_storage.transaction(tenant) as connection:
        connection.execute(
            insert(document_ai_requirement_runs).values(
                company_id=tenant,
                run_id=v1_id,
                source_document_id=request["source_document_id"],
                source_sha256=request["source_sha256"],
                evidence_sha256="a" * 64,
                snapshot=v1,
                created_at=now,
            )
        )

    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(
            insert(document_ai_requirement_runs).values(
                company_id=tenant,
                run_id=v2_id,
                source_document_id=request["source_document_id"],
                source_sha256=request["source_sha256"],
                evidence_sha256="b" * 64,
                snapshot=v2,
                created_at=now,
            )
        )
    assert error.value.orig.sqlstate == "23514"
    invalid_id = f"run-invalid-{uuid.uuid4()}"
    invalid = {**v2, "run_id": invalid_id, "evidence_sha256": "c" * 64, "extra": True}
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(
            insert(document_ai_requirement_runs).values(
                company_id=tenant,
                run_id=invalid_id,
                source_document_id=request["source_document_id"],
                source_sha256=request["source_sha256"],
                evidence_sha256="c" * 64,
                snapshot=invalid,
                created_at=now,
            )
        )
    assert error.value.orig.sqlstate == "23514"


def test_materialization_rejects_time_before_receipt(sql_storage, materialization_template):
    _, _, receipt, _, _ = materialization_template
    row = _row(
        materialization_template,
        materialized_at=receipt.recorded_at.replace(year=receipt.recorded_at.year - 1),
    )
    row["created_at"] = row["materialized_at"]
    row["materialization"]["materialized_at"] = row["materialized_at"].isoformat()

    with (
        pytest.raises(DBAPIError) as error,
        sql_storage.transaction(row["company_id"]) as connection,
    ):
        connection.execute(insert(ai_transfer_requirement_materializations).values(**row))
    assert error.value.orig.sqlstate == "23514"
