"""Allow an explicitly bootstrapped company-profile owner credential."""

from alembic import op

revision = "20261023_02"
down_revision = "20261021_01"
branch_labels = None
depends_on = None

_PREVIOUS = (
    "access_role IN ('OPERATOR','MODEL_BRAND_REVIEWER','MANUFACTURER_REVIEWER',"
    "'COMPLETENESS_REVIEWER','AI_REQUIREMENTS_REVIEWER','AI_TRANSFER_APPROVER',"
    "'PARTICIPATION_APPROVER','APPLICATION_REVIEWER',"
    "'APPLICATION_SUBMISSION_APPROVER','APPLICATION_SUBMISSION_EXECUTOR','AUDITOR')"
)
_CURRENT = _PREVIOUS[:-1] + ",'COMPANY_PROFILE_OWNER')"
_PROFILE_PAYLOAD = """(
  jsonb_typeof(snapshot)='object' AND jsonb_typeof(command)='object'
  AND command_sha256 ~ '^[0-9a-f]{64}$'
  AND snapshot->>'schema_version'='company-profile-snapshot-v1'
  AND snapshot->>'company_id'=company_id AND (snapshot->>'version')::int=version
  AND snapshot->>'snapshot_sha256'=snapshot_sha256
  AND snapshot->>'created_by'=created_by
  AND (snapshot->>'created_at')::timestamptz=created_at
  AND snapshot->>'audit_event_id'=audit_event_id
  AND snapshot->>'critical_settings_status' IN
    ('OWNER_AUTHORIZATION_UNAVAILABLE','OWNER_AUTHORIZED')
  AND (
    snapshot->>'critical_settings_status'='OWNER_AUTHORIZATION_UNAVAILABLE'
    OR jsonb_typeof(snapshot->'policy_confirmation')='object'
  )
)"""
_OLD_PROFILE_PAYLOAD = """(
  jsonb_typeof(snapshot)='object' AND jsonb_typeof(command)='object'
  AND command_sha256 ~ '^[0-9a-f]{64}$'
  AND snapshot->>'schema_version'='company-profile-snapshot-v1'
  AND snapshot->>'company_id'=company_id AND (snapshot->>'version')::int=version
  AND snapshot->>'snapshot_sha256'=snapshot_sha256
  AND snapshot->>'created_by'=created_by
  AND (snapshot->>'created_at')::timestamptz=created_at
  AND snapshot->>'audit_event_id'=audit_event_id
  AND snapshot->>'critical_settings_status'='OWNER_AUTHORIZATION_UNAVAILABLE'
)"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout='5s'")
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint("ck_api_keys_access_role", "api_keys", _CURRENT)
    op.drop_constraint("ck_company_profile_payload", "company_profile_versions", type_="check")
    op.create_check_constraint(
        "ck_company_profile_payload", "company_profile_versions", _PROFILE_PAYLOAD
    )


def downgrade() -> None:
    op.drop_constraint("ck_api_keys_access_role", "api_keys", type_="check")
    op.create_check_constraint("ck_api_keys_access_role", "api_keys", _PREVIOUS)
    op.drop_constraint("ck_company_profile_payload", "company_profile_versions", type_="check")
    op.create_check_constraint(
        "ck_company_profile_payload", "company_profile_versions", _OLD_PROFILE_PAYLOAD
    )
