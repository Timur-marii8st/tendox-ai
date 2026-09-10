"""Tenant-scoped synchronous repositories backed only by PostgreSQL."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, and_, create_engine, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from procurement.documents import ExtractionResult
from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case
from procurement.domain.decisions import Recommendation
from procurement.storage.models import (
    MAX_DOCUMENT_BYTES,
    api_keys,
    audit_events,
    case_versions,
    document_ocr_derivatives,
    documents,
    evaluations,
    write_receipts,
)


class StorageError(RuntimeError):
    """Base error exposed by the storage boundary."""


class CaseVersionConflict(StorageError):
    """The immutable identity already exists with a different payload."""


class DocumentConflict(StorageError):
    """The tenant already has an immutable document with this identity."""


class OcrDerivativeConflict(StorageError):
    """The tenant already has an immutable OCR derivative with this identity."""


class AuditEventConflict(StorageError):
    """The tenant already has an audit event with this identity."""


class ApiKeyConflict(StorageError):
    """An API key identity or digest is already registered."""


class IdempotencyConflict(StorageError):
    """An idempotency key was reused for a different request payload."""


class AuditEventRecord(BaseModel):
    """Complete persisted audit fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    object_type: str | None = Field(default=None, min_length=1)
    object_id: str | None = Field(default=None, min_length=1)
    object_version: int | None = Field(default=None, ge=1)
    basis: dict[str, Any]
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ApiKeyRecord(BaseModel):
    """Stored API-key metadata; plaintext key material is never persisted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: str = Field(min_length=1)
    enabled: bool = True
    created_at: datetime | None = None

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("created_at must include a timezone")
        return value


class Principal(BaseModel):
    """Identity returned by database-backed bearer authentication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)


class WriteReceiptRecord(BaseModel):
    """Immutable response associated with an exact idempotent request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: dict[str, Any]
    created_at: datetime | None = None


class EvaluationRecord(BaseModel):
    """Immutable result of evaluating one exact case version at one instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    effective_at: datetime
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine_version: str = Field(min_length=1)
    recommendation: Recommendation
    created_at: datetime | None = None

    @field_validator("effective_at", "created_at")
    @classmethod
    def _times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evaluation times must include a timezone")
        return value


class DocumentRecord(BaseModel):
    """Complete immutable source document and its typed extraction envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    byte_size: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes
    extraction: ExtractionResult
    created_at: datetime

    @field_validator("company_id", "document_id", "original_filename", "media_type")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document text fields must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("content")
    @classmethod
    def _content_is_not_empty(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("document content must not be empty")
        if len(value) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document content exceeds {MAX_DOCUMENT_BYTES} bytes")
        return value

    @model_validator(mode="after")
    def _content_matches_metadata(self) -> Self:
        if len(self.content) != self.byte_size:
            raise ValueError("byte_size does not match document content")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("sha256 does not match document content")
        return self


class OcrDerivativeRecord(BaseModel):
    """Immutable OCR derivative of one exact source document version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    ocr_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0)
    status: str = Field(min_length=1)
    result: dict[str, Any]
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @field_validator("company_id", "ocr_id", "source_document_id", "engine")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ocr text fields must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("status")
    @classmethod
    def _status_is_allowed(cls, value: str) -> str:
        if value not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("ocr status must be PASS, FAIL, or UNKNOWN")
        return value


class CasePage(BaseModel):
    """One cursor-addressed page containing the latest visible case versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ProcurementCase, ...]
    next_cursor: str | None = None


def _encode_cursor(case_id: str) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"after_case_id": case_id}, separators=(",", ":")).encode()
    )
    return encoded.decode().rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        case_id = payload["after_case_id"]
    except (KeyError, UnicodeDecodeError, ValueError, TypeError) as error:
        raise ValueError("invalid case-list cursor") from error
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("invalid case-list cursor")
    return case_id


def api_key_digest(secret: str) -> str:
    """Return the lowercase SHA-256 digest used for API-key lookup."""
    if not secret:
        raise ValueError("API key must not be empty")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _require_tenant(company_id: str) -> str:
    if not company_id:
        raise ValueError("company_id must not be empty")
    return company_id


def _require_sha256(value: str, *, field: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


class PostgresStorage:
    """One explicit tenant context and transaction per repository operation."""

    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresStorage requires a PostgreSQL engine")
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str, **engine_options: Any) -> PostgresStorage:
        """Build storage from a SQLAlchemy PostgreSQL URL."""
        return cls(create_engine(database_url, **engine_options))

    @contextmanager
    def transaction(self, company_id: str) -> Iterator[Connection]:
        """Open a transaction and bind PostgreSQL RLS to one tenant."""
        tenant = _require_tenant(company_id)
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.company_id', :company_id, true)"),
                {"company_id": tenant},
            )
            yield connection

    @staticmethod
    def _insert_case(
        connection: Connection,
        tenant: str,
        checked: ProcurementCase,
        *,
        allow_exact_replay: bool,
    ) -> None:
        payload = checked.model_dump(mode="json")
        statement = (
            postgresql_insert(case_versions)
            .values(
                company_id=tenant,
                case_id=checked.case_id,
                version=checked.version,
                payload=payload,
                input_sha256=case_input_digest(checked),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    case_versions.c.company_id,
                    case_versions.c.case_id,
                    case_versions.c.version,
                ]
            )
            .returning(case_versions.c.payload)
        )
        inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            stored = connection.execute(
                select(case_versions.c.payload).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == checked.case_id,
                        case_versions.c.version == checked.version,
                    )
                )
            ).scalar_one_or_none()
            if stored != payload or not allow_exact_replay:
                raise CaseVersionConflict(
                    f"case {checked.case_id!r} version {checked.version} already exists"
                )

    @staticmethod
    def _lock_idempotency(
        connection: Connection,
        tenant: str,
        operation: str,
        idempotency_key: str,
    ) -> None:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {
                "lock_key": (
                    f"{len(tenant)}:{tenant}{len(operation)}:{operation}{idempotency_key}"
                )
            },
        )

    @staticmethod
    def _existing_receipt(
        connection: Connection,
        tenant: str,
        operation: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            select(write_receipts.c.request_sha256, write_receipts.c.response).where(
                and_(
                    write_receipts.c.company_id == tenant,
                    write_receipts.c.operation == operation,
                    write_receipts.c.idempotency_key == idempotency_key,
                )
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was already used for another request"
            )
        return dict(row["response"])

    @staticmethod
    def _insert_receipt(
        connection: Connection,
        *,
        tenant: str,
        operation: str,
        idempotency_key: str,
        request_sha256: str,
        response: dict[str, Any],
    ) -> None:
        connection.execute(
            insert(write_receipts).values(
                company_id=tenant,
                operation=operation,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                response=response,
            )
        )

    def save_case(
        self,
        company_id: str,
        case: ProcurementCase,
        *,
        idempotency_key: str | None = None,
        request_sha256: str | None = None,
    ) -> ProcurementCase:
        """Insert an immutable version, with exact replay treated as idempotent."""
        tenant = _require_tenant(company_id)
        checked = ProcurementCase.model_validate(case.model_dump(mode="python"))
        if checked.company_id != tenant:
            raise ValueError("case company_id does not match repository tenant")
        if (idempotency_key is None) != (request_sha256 is None):
            raise ValueError("idempotency_key and request_sha256 must be supplied together")
        if request_sha256 is not None:
            _require_sha256(request_sha256, field="request_sha256")
        with self.transaction(tenant) as connection:
            if idempotency_key is not None and request_sha256 is not None:
                self._lock_idempotency(connection, tenant, "save_case", idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, "save_case", idempotency_key, request_sha256
                )
                if replay is not None:
                    identity = (replay.get("case_id"), replay.get("version"))
                    if identity != (checked.case_id, checked.version):
                        raise StorageError("stored save_case receipt has an invalid response")
                    return checked
            self._insert_case(
                connection,
                tenant,
                checked,
                allow_exact_replay=idempotency_key is None,
            )
            if idempotency_key is not None and request_sha256 is not None:
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="save_case",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"case_id": checked.case_id, "version": checked.version},
                )
        return checked

    def store_document(
        self,
        company_id: str,
        actor_id: str,
        original_filename: str,
        media_type: str,
        content: bytes,
        extraction: ExtractionResult | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
        *,
        document_id: str | None = None,
    ) -> DocumentRecord:
        """Atomically store source bytes, extraction, audit fact, and replay receipt."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not original_filename.strip():
            raise ValueError("original_filename must not be empty")
        if not media_type.strip():
            raise ValueError("media_type must not be empty")
        raw_content = bytes(content)
        if not raw_content:
            raise ValueError("document content must not be empty")
        if len(raw_content) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document content exceeds {MAX_DOCUMENT_BYTES} bytes")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_extraction = ExtractionResult.model_validate(extraction)
            normalized_extraction = checked_extraction.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("extraction must match the typed extraction schema") from error

        chosen_id = document_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("document_id must not be empty")
        content_sha256 = hashlib.sha256(raw_content).hexdigest()
        created_at = datetime.now(UTC)
        candidate = DocumentRecord(
            company_id=tenant,
            document_id=chosen_id,
            original_filename=original_filename,
            media_type=media_type,
            byte_size=len(raw_content),
            sha256=content_sha256,
            content=raw_content,
            extraction=checked_extraction,
            created_at=created_at,
        )
        extraction_sha256 = hashlib.sha256(
            json.dumps(
                normalized_extraction,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(
                    connection,
                    tenant,
                    "store_document",
                    idempotency_key,
                )
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    "store_document",
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("document_id")
                    row = connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == replay_id,
                            )
                        )
                    ).mappings().one_or_none()
                    if row is None:
                        raise StorageError(
                            "stored document receipt points to a missing record"
                        )
                    return DocumentRecord.model_validate(dict(row))

                row = (
                    connection.execute(
                        insert(documents)
                        .values(
                            **(
                                candidate.model_dump(mode="python", exclude={"extraction"})
                                | {"extraction": normalized_extraction}
                            )
                        )
                        .returning(documents)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.stored",
                    object_type="source_document",
                    object_id=chosen_id,
                    basis={
                        "original_filename": original_filename,
                        "media_type": media_type,
                        "byte_size": len(raw_content),
                        "sha256": content_sha256,
                        "extraction_sha256": extraction_sha256,
                    },
                    occurred_at=created_at,
                )
                connection.execute(
                    insert(audit_events).values(**event.model_dump(mode="python"))
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_document",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"document_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentConflict(
                    f"document {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return DocumentRecord.model_validate(dict(row))

    def get_document(self, company_id: str, document_id: str) -> DocumentRecord | None:
        """Load one visible immutable document, including its original bytes."""
        tenant = _require_tenant(company_id)
        if not document_id:
            raise ValueError("document_id must not be empty")
        with self.transaction(tenant) as connection:
            row = connection.execute(
                select(documents).where(
                    and_(
                        documents.c.company_id == tenant,
                        documents.c.document_id == document_id,
                    )
                )
            ).mappings().one_or_none()
        return None if row is None else DocumentRecord.model_validate(dict(row))

    @staticmethod
    def _ocr_record(row: Any) -> OcrDerivativeRecord:
        payload = dict(row)
        threshold = payload.get("threshold")
        if threshold is not None:
            payload["threshold"] = float(threshold)
        confidence = payload.get("mean_confidence")
        if confidence is not None:
            payload["mean_confidence"] = float(confidence)
        return OcrDerivativeRecord.model_validate(payload)

    def store_ocr_derivative(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        *,
        engine: str,
        threshold: float,
        status: str,
        result: dict[str, Any],
        mean_confidence: float | None,
        idempotency_key: str,
        request_sha256: str,
        ocr_id: str | None = None,
    ) -> OcrDerivativeRecord:
        """Atomically store one immutable OCR derivative, audit fact, and receipt."""
        from procurement.documents.ocr import OcrDerivative

        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not source_document_id.strip():
            raise ValueError("source_document_id must not be empty")
        if not engine.strip():
            raise ValueError("engine must not be empty")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be within [0, 1]")
        if status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("ocr status must be PASS, FAIL, or UNKNOWN")
        if not isinstance(result, dict):
            raise ValueError("ocr result must be a JSON object")
        if mean_confidence is not None and not 0.0 <= mean_confidence <= 1.0:
            raise ValueError("mean_confidence must be within [0, 1]")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_result = OcrDerivative.model_validate(result)
            normalized_result = checked_result.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("ocr result must match the typed OCR derivative schema") from error
        if checked_result.status.value != status:
            raise ValueError("ocr status does not match the typed OCR derivative")
        chosen_id = ocr_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("ocr_id must not be empty")
        created_at = datetime.now(UTC)
        result_sha256 = hashlib.sha256(
            json.dumps(
                normalized_result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(
                    connection, tenant, "store_ocr_derivative", idempotency_key
                )
                replay = self._existing_receipt(
                    connection, tenant, "store_ocr_derivative", idempotency_key, request_sha256
                )
                if replay is not None:
                    replay_id = replay.get("ocr_id")
                    row = connection.execute(
                        select(document_ocr_derivatives).where(
                            and_(
                                document_ocr_derivatives.c.company_id == tenant,
                                document_ocr_derivatives.c.ocr_id == replay_id,
                            )
                        )
                    ).mappings().one_or_none()
                    if row is None:
                        raise StorageError(
                            "stored ocr receipt points to a missing record"
                        )
                    return self._ocr_record(row)
                parent = connection.execute(
                    select(documents.c.document_id).where(
                        and_(
                            documents.c.company_id == tenant,
                            documents.c.document_id == source_document_id,
                        )
                    )
                ).scalar_one_or_none()
                if parent is None:
                    raise StorageError("source document does not exist in the tenant")
                row = (
                    connection.execute(
                        insert(document_ocr_derivatives)
                        .values(
                            company_id=tenant,
                            ocr_id=chosen_id,
                            source_document_id=source_document_id,
                            engine=engine,
                            threshold=threshold,
                            status=status,
                            result=normalized_result,
                            mean_confidence=mean_confidence,
                            created_at=created_at,
                        )
                        .returning(document_ocr_derivatives)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.ocr_stored",
                    object_type="source_document",
                    object_id=source_document_id,
                    basis={
                        "ocr_id": chosen_id,
                        "source_document_id": source_document_id,
                        "engine": engine,
                        "threshold": threshold,
                        "status": status,
                        "result_sha256": result_sha256,
                        "mean_confidence": mean_confidence,
                    },
                    occurred_at=created_at,
                )
                connection.execute(
                    insert(audit_events).values(**event.model_dump(mode="python"))
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_ocr_derivative",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"ocr_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise OcrDerivativeConflict(
                    f"ocr derivative {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return self._ocr_record(dict(row))

    def get_ocr_derivative(self, company_id: str, ocr_id: str) -> OcrDerivativeRecord | None:
        """Load one visible immutable OCR derivative by its identity."""
        tenant = _require_tenant(company_id)
        if not ocr_id:
            raise ValueError("ocr_id must not be empty")
        with self.transaction(tenant) as connection:
            row = connection.execute(
                select(document_ocr_derivatives).where(
                    and_(
                        document_ocr_derivatives.c.company_id == tenant,
                        document_ocr_derivatives.c.ocr_id == ocr_id,
                    )
                )
            ).mappings().one_or_none()
        return None if row is None else self._ocr_record(row)

    def get_latest_ocr_for_document(
        self, company_id: str, source_document_id: str
    ) -> OcrDerivativeRecord | None:
        """Load the latest visible OCR derivative for one source document."""
        tenant = _require_tenant(company_id)
        if not source_document_id:
            raise ValueError("source_document_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_ocr_derivatives)
                    .where(
                        and_(
                            document_ocr_derivatives.c.company_id == tenant,
                            document_ocr_derivatives.c.source_document_id
                            == source_document_id,
                        )
                    )
                    .order_by(
                        document_ocr_derivatives.c.created_at.desc(),
                        document_ocr_derivatives.c.ocr_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._ocr_record(row)

    def get_case(
        self,
        company_id: str,
        case_id: str,
        version: int | None = None,
    ) -> ProcurementCase | None:
        """Load one version, or the latest visible version when omitted."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        statement = select(case_versions.c.payload).where(
            and_(case_versions.c.company_id == tenant, case_versions.c.case_id == case_id)
        )
        if version is None:
            statement = statement.order_by(case_versions.c.version.desc()).limit(1)
        else:
            if version < 1:
                raise ValueError("version must be positive")
            statement = statement.where(case_versions.c.version == version)
        with self.transaction(tenant) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else ProcurementCase.model_validate(payload)

    def list_case_versions(self, company_id: str, case_id: str) -> list[ProcurementCase]:
        """List every visible immutable version in ascending version order."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        statement = (
            select(case_versions.c.payload)
            .where(
                and_(case_versions.c.company_id == tenant, case_versions.c.case_id == case_id)
            )
            .order_by(case_versions.c.version)
        )
        with self.transaction(tenant) as connection:
            payloads = connection.execute(statement).scalars().all()
        return [ProcurementCase.model_validate(payload) for payload in payloads]

    def list_cases(
        self,
        company_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CasePage:
        """List latest visible versions with a stable case-id cursor."""
        tenant = _require_tenant(company_id)
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        after_case = _decode_cursor(cursor) if cursor is not None else None
        ranked = select(
            case_versions.c.payload,
            case_versions.c.case_id,
            func.row_number()
            .over(
                partition_by=(case_versions.c.company_id, case_versions.c.case_id),
                order_by=case_versions.c.version.desc(),
            )
            .label("row_number"),
        ).where(case_versions.c.company_id == tenant).subquery()
        statement = select(ranked.c.payload, ranked.c.case_id).where(ranked.c.row_number == 1)
        if after_case is not None:
            statement = statement.where(ranked.c.case_id > after_case)
        statement = statement.order_by(ranked.c.case_id).limit(limit + 1)
        with self.transaction(tenant) as connection:
            rows = connection.execute(statement).mappings().all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(ProcurementCase.model_validate(row["payload"]) for row in selected)
        next_cursor = _encode_cursor(selected[-1]["case_id"]) if has_more and selected else None
        return CasePage(items=items, next_cursor=next_cursor)

    def append_audit(self, event: AuditEventRecord) -> AuditEventRecord:
        """Append one event; event identities cannot be silently replayed."""
        statement = insert(audit_events).values(**event.model_dump(mode="python"))
        try:
            with self.transaction(event.company_id) as connection:
                connection.execute(statement)
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AuditEventConflict(
                    f"audit event {event.event_id!r} already exists for tenant"
                ) from error
            raise
        return event

    def list_audit_events(
        self,
        company_id: str,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
    ) -> list[AuditEventRecord]:
        """List visible audit history in deterministic chronological order."""
        tenant = _require_tenant(company_id)
        statement = select(audit_events).where(audit_events.c.company_id == tenant)
        if object_type is not None:
            statement = statement.where(audit_events.c.object_type == object_type)
        if object_id is not None:
            statement = statement.where(audit_events.c.object_id == object_id)
        statement = statement.order_by(audit_events.c.occurred_at, audit_events.c.event_id)
        with self.transaction(tenant) as connection:
            rows = connection.execute(statement).mappings().all()
        return [AuditEventRecord.model_validate(dict(row)) for row in rows]

    def register_api_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        """Register already-digested key metadata inside its tenant."""
        values = record.model_dump(mode="python", exclude_none=True)
        try:
            with self.transaction(record.company_id) as connection:
                row = connection.execute(
                    insert(api_keys).values(**values).returning(api_keys)
                ).mappings().one()
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApiKeyConflict("API key identity or digest already exists") from error
            raise
        return ApiKeyRecord.model_validate(dict(row))

    def authenticate_api_key(self, secret: str) -> Principal | None:
        """Resolve bearer identity without accepting a caller-provided tenant."""
        digest = api_key_digest(secret)
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT company_id, actor_id, key_id "
                    "FROM authenticate_api_key(:key_digest)"
                ),
                {"key_digest": digest},
            ).mappings().one_or_none()
        return None if row is None else Principal.model_validate(dict(row))

    def set_api_key_enabled(self, company_id: str, key_id: str, *, enabled: bool) -> bool:
        """Enable or revoke one key in its tenant; return whether it existed."""
        tenant = _require_tenant(company_id)
        if not key_id:
            raise ValueError("key_id must not be empty")
        with self.transaction(tenant) as connection:
            result = connection.execute(
                update(api_keys)
                .where(and_(api_keys.c.company_id == tenant, api_keys.c.key_id == key_id))
                .values(enabled=enabled)
            )
        return result.rowcount == 1

    def get_evaluation(
        self,
        company_id: str,
        evaluation_id: str,
    ) -> EvaluationRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            row = connection.execute(
                select(evaluations).where(
                    and_(
                        evaluations.c.company_id == tenant,
                        evaluations.c.evaluation_id == evaluation_id,
                    )
                )
            ).mappings().one_or_none()
        return None if row is None else EvaluationRecord.model_validate(dict(row))

    def get_latest_evaluation(
        self,
        company_id: str,
        case_id: str,
        case_version: int,
    ) -> EvaluationRecord | None:
        """Load the latest persisted evaluation for one tenant-scoped case version."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        if case_version < 1:
            raise ValueError("case_version must be positive")
        statement = (
            select(evaluations)
            .where(
                and_(
                    evaluations.c.company_id == tenant,
                    evaluations.c.case_id == case_id,
                    evaluations.c.case_version == case_version,
                )
            )
            .order_by(evaluations.c.created_at.desc(), evaluations.c.evaluation_id.desc())
            .limit(1)
        )
        with self.transaction(tenant) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else EvaluationRecord.model_validate(dict(row))

    def record_evaluation(
        self,
        company_id: str,
        actor_id: str,
        case_id: str,
        case_version: int,
        effective_at: datetime,
        input_digest: str,
        engine_version: str,
        recommendation: Recommendation,
        idempotency_key: str,
        request_sha256: str,
    ) -> EvaluationRecord:
        """Atomically persist a verified evaluation, audit fact, and replay receipt."""
        tenant = _require_tenant(company_id)
        _require_sha256(input_digest, field="input_digest")
        _require_sha256(request_sha256, field="request_sha256")
        candidate = EvaluationRecord(
            company_id=tenant,
            evaluation_id=str(uuid.uuid4()),
            case_id=case_id,
            case_version=case_version,
            effective_at=effective_at,
            input_sha256=input_digest,
            engine_version=engine_version,
            recommendation=recommendation,
        )
        with self.transaction(tenant) as connection:
            self._lock_idempotency(
                connection,
                tenant,
                "record_evaluation",
                idempotency_key,
            )
            replay = self._existing_receipt(
                connection,
                tenant,
                "record_evaluation",
                idempotency_key,
                request_sha256,
            )
            if replay is not None:
                replay_id = replay.get("evaluation_id")
                row = connection.execute(
                    select(evaluations).where(
                        and_(
                            evaluations.c.company_id == tenant,
                            evaluations.c.evaluation_id == replay_id,
                        )
                    )
                ).mappings().one_or_none()
                if row is None:
                    raise StorageError("stored evaluation receipt points to a missing record")
                return EvaluationRecord.model_validate(dict(row))

            case_row = connection.execute(
                select(case_versions.c.payload, case_versions.c.input_sha256).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == case_id,
                        case_versions.c.version == case_version,
                    )
                )
            ).mappings().one_or_none()
            if case_row is None:
                raise StorageError("case version does not exist in the tenant")
            if case_row["input_sha256"] != input_digest:
                raise StorageError("input_digest does not match the stored case version")
            stored_case = ProcurementCase.model_validate(case_row["payload"])
            expected = evaluate_case(stored_case, at=effective_at)
            checked_recommendation = Recommendation.model_validate(
                recommendation.model_dump(mode="python")
            )
            if checked_recommendation != expected:
                raise StorageError("recommendation does not match deterministic evaluation")

            created_at = datetime.now(UTC)
            persisted = candidate.model_copy(update={"created_at": created_at})
            evaluation_values = persisted.model_dump(mode="python", exclude_none=True)
            evaluation_values["recommendation"] = persisted.recommendation.model_dump(mode="json")
            row = (
                connection.execute(
                    insert(evaluations).values(**evaluation_values).returning(evaluations)
                )
                .mappings()
                .one()
            )
            event = AuditEventRecord(
                event_id=candidate.evaluation_id,
                company_id=tenant,
                actor_id=actor_id,
                event_type="case.evaluated",
                object_type="procurement_case",
                object_id=case_id,
                object_version=case_version,
                basis={
                    "evaluation_id": candidate.evaluation_id,
                    "input_sha256": input_digest,
                    "engine_version": engine_version,
                    "effective_at": effective_at.isoformat(),
                },
                occurred_at=created_at,
            )
            connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
            self._insert_receipt(
                connection,
                tenant=tenant,
                operation="record_evaluation",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                response={"evaluation_id": candidate.evaluation_id},
            )
        return EvaluationRecord.model_validate(dict(row))
