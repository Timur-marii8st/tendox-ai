"""Две tenant-scoped таблицы профиля на общей metadata проекта."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from procurement.storage.models import metadata


def profile_tables(metadata: MetaData) -> tuple[Table, Table]:
    versions = Table(
        "company_profile_versions",
        metadata,
        Column("company_id", Text, nullable=False),
        Column("version", Integer, nullable=False),
        Column("parent_version", Integer),
        Column("snapshot", JSONB, nullable=False),
        Column("snapshot_sha256", String(64), nullable=False),
        Column("snapshot_canonical", LargeBinary, nullable=False),
        Column("command", JSONB, nullable=False),
        Column("command_sha256", String(64), nullable=False),
        Column("created_by", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("audit_event_id", Text, nullable=False),
        PrimaryKeyConstraint("company_id", "version", name="pk_company_profile_versions"),
        UniqueConstraint(
            "company_id", "version", "snapshot_sha256", name="uq_company_profile_exact"
        ),
        ForeignKeyConstraint(
            ["company_id", "parent_version"],
            ["company_profile_versions.company_id", "company_profile_versions.version"],
            name="fk_company_profile_parent",
        ),
        ForeignKeyConstraint(
            ["company_id", "audit_event_id"],
            ["audit_events.company_id", "audit_events.event_id"],
            name="fk_company_profile_audit",
        ),
        CheckConstraint(
            "version >= 1 AND ((version=1 AND parent_version IS NULL) OR parent_version=version-1)",
            name="ck_company_profile_version",
        ),
        CheckConstraint(
            "company_id <> '' AND snapshot_sha256 = encode(sha256(snapshot_canonical),'hex') "
            "AND octet_length(snapshot_canonical)<=262144",
            name="ck_company_profile_hash",
        ),
    )
    selections = Table(
        "company_profile_selections",
        metadata,
        Column("company_id", Text, nullable=False),
        Column("selection_id", Text, nullable=False),
        Column("profile_version", Integer, nullable=False),
        Column("profile_sha256", String(64), nullable=False),
        Column("selection", JSONB, nullable=False),
        Column("selected_by", Text, nullable=False),
        Column("selected_at", DateTime(timezone=True), nullable=False),
        Column("audit_event_id", Text, nullable=False),
        PrimaryKeyConstraint("company_id", "selection_id", name="pk_company_profile_selections"),
        ForeignKeyConstraint(
            ["company_id", "profile_version", "profile_sha256"],
            [
                "company_profile_versions.company_id",
                "company_profile_versions.version",
                "company_profile_versions.snapshot_sha256",
            ],
            name="fk_company_profile_selection_exact",
        ),
        ForeignKeyConstraint(
            ["company_id", "audit_event_id"],
            ["audit_events.company_id", "audit_events.event_id"],
            name="fk_company_profile_selection_audit",
        ),
    )
    return versions, selections


company_profile_versions, company_profile_selections = profile_tables(metadata)
