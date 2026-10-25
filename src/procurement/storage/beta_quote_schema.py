"""Immutable tenant quote declarations, with source reference and audit binding."""

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

from procurement.storage.models import metadata

beta_quote_records = Table(
    "beta_quote_records",
    metadata,
    Column("company_id", Text, primary_key=True),
    Column("record_id", Text, primary_key=True),
    Column("law", Text, nullable=False),
    Column("purchase_number", Text, nullable=False),
    Column("version_number", Integer, nullable=False),
    Column("xml_sha256", String(64), nullable=False),
    Column("lot_index", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("audit_event_id", Text, nullable=False),
    ForeignKeyConstraint(
        ["company_id", "audit_event_id"], ["audit_events.company_id", "audit_events.event_id"]
    ),
)
