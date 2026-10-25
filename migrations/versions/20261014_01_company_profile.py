"""Standalone company profile snapshots and exact version selection; no owner grant."""

from alembic import op

revision = "20261014_01"
down_revision = "20261006_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("""CREATE TABLE company_profile_versions (
      company_id TEXT NOT NULL, version INTEGER NOT NULL, parent_version INTEGER,
      snapshot JSONB NOT NULL, snapshot_sha256 VARCHAR(64) NOT NULL,
      snapshot_canonical BYTEA NOT NULL, command JSONB NOT NULL,
      command_sha256 VARCHAR(64) NOT NULL,
      created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, audit_event_id TEXT NOT NULL,
      CONSTRAINT pk_company_profile_versions PRIMARY KEY(company_id,version),
      CONSTRAINT uq_company_profile_exact UNIQUE(company_id,version,snapshot_sha256),
      CONSTRAINT fk_company_profile_parent FOREIGN KEY(company_id,parent_version)
        REFERENCES company_profile_versions(company_id,version),
      CONSTRAINT fk_company_profile_audit FOREIGN KEY(company_id,audit_event_id)
        REFERENCES audit_events(company_id,event_id),
      CONSTRAINT ck_company_profile_version CHECK
        ((version>=1 AND ((version=1 AND parent_version IS NULL) OR
          (version>1 AND parent_version=version-1))) IS TRUE),
      CONSTRAINT ck_company_profile_hash CHECK
        (company_id<>'' AND snapshot_sha256=encode(sha256(snapshot_canonical),'hex')
         AND octet_length(snapshot_canonical)<=262144),
      CONSTRAINT ck_company_profile_payload CHECK ((
        jsonb_typeof(snapshot)='object' AND jsonb_typeof(command)='object'
        AND command_sha256 ~ '^[0-9a-f]{64}$'
        AND snapshot->>'schema_version'='company-profile-snapshot-v1'
        AND snapshot->>'company_id'=company_id AND (snapshot->>'version')::int=version
        AND snapshot->>'snapshot_sha256'=snapshot_sha256
        AND snapshot->>'created_by'=created_by
        AND (snapshot->>'created_at')::timestamptz=created_at
        AND snapshot->>'audit_event_id'=audit_event_id
        AND snapshot->>'critical_settings_status'='OWNER_AUTHORIZATION_UNAVAILABLE') IS TRUE)
    )""")
    op.execute("""CREATE TABLE company_profile_selections (
      company_id TEXT NOT NULL, selection_id TEXT NOT NULL,
      profile_version INTEGER NOT NULL, profile_sha256 VARCHAR(64) NOT NULL,
      selection JSONB NOT NULL, selected_by TEXT NOT NULL, selected_at TIMESTAMPTZ NOT NULL,
      audit_event_id TEXT NOT NULL,
      CONSTRAINT pk_company_profile_selections PRIMARY KEY(company_id,selection_id),
      CONSTRAINT fk_company_profile_selection_exact
        FOREIGN KEY(company_id,profile_version,profile_sha256)
        REFERENCES company_profile_versions(company_id,version,snapshot_sha256),
      CONSTRAINT fk_company_profile_selection_audit FOREIGN KEY(company_id,audit_event_id)
        REFERENCES audit_events(company_id,event_id),
      CONSTRAINT ck_company_profile_selection_payload CHECK ((
        company_id<>'' AND jsonb_typeof(selection)='object'
        AND selection->>'company_id'=company_id AND selection->>'selection_id'=selection_id
        AND selection->'profile_ref'->>'company_id'=company_id
        AND (selection->'profile_ref'->>'version')::int=profile_version
        AND selection->'profile_ref'->>'snapshot_sha256'=profile_sha256
        AND selection->>'selected_by'=selected_by
        AND (selection->>'selected_at')::timestamptz=selected_at
        AND selection->>'audit_event_id'=audit_event_id) IS TRUE)
    )""")
    op.execute(
        "CREATE INDEX ix_company_profile_selection_time "
        "ON company_profile_selections(company_id,selected_at DESC,selection_id)"
    )
    tenant = "company_id = nullif(current_setting('app.company_id',true),'')"
    for table in ("company_profile_versions", "company_profile_selections"):
        for sql in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({tenant})",
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({tenant})",
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_immutable_mutation()",
            f"REVOKE ALL ON TABLE {table} FROM PUBLIC",
            f"GRANT SELECT,INSERT ON {table} TO procurement_app",
        ):
            op.execute(sql)


def downgrade() -> None:
    op.execute("SET LOCAL row_security=off")
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM company_profile_versions)
        OR EXISTS(SELECT 1 FROM company_profile_selections)
      THEN RAISE EXCEPTION 'company profile history must be preserved'; END IF;
    END $$""")
    op.drop_table("company_profile_selections")
    op.drop_table("company_profile_versions")
