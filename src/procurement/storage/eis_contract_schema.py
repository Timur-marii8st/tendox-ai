"""Immutable tenant source evidence and indexed regional observation receipts."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from procurement.storage.models import metadata

contract_evidence = Table(
    "eis_contract_evidence",
    metadata,
    Column("company_id", Text, primary_key=True),
    Column("sha256", String(64), primary_key=True),
    Column("kind", Text, nullable=False),
    Column("content", LargeBinary, nullable=False),
)
contract_observations = Table(
    "eis_contract_observations",
    metadata,
    Column("company_id", Text, primary_key=True),
    Column("receipt_id", String(64), primary_key=True),
    Column("registry_number", Text, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("region_key", Text),
    Column("product_key", Text),
    Column("procedure", Text),
    Column("unit", Text),
    Column("quantity", Numeric),
    Column("payload", JSONB, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("source_receipts", JSONB, nullable=False),
    Column("audit_event_id", Text, nullable=False),
    ForeignKeyConstraint(
        ["company_id", "audit_event_id"], ["audit_events.company_id", "audit_events.event_id"]
    ),
)
contract_observation_sources = Table(
    "eis_contract_observation_sources",
    metadata,
    Column("company_id", Text, primary_key=True),
    Column("receipt_id", String(64), primary_key=True),
    Column("sha256", String(64), primary_key=True),
    ForeignKeyConstraint(
        ["company_id", "receipt_id"],
        ["eis_contract_observations.company_id", "eis_contract_observations.receipt_id"],
    ),
    ForeignKeyConstraint(
        ["company_id", "sha256"],
        ["eis_contract_evidence.company_id", "eis_contract_evidence.sha256"],
    ),
)
