"""Транспортный снимок профиля с UNKNOWN; правила значений берутся из company.py."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_serializer, model_validator

from procurement.domain.actions import payload_digest
from procurement.domain.company import (
    CompanyIdentity,
    CompanyProfile,
    FinancialPolicy,
    GeographyPolicy,
    _finite_financial_decimal,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.tenders import ProcedureMethod

Knowledge = Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]
InputValue = str | bool | tuple[str, ...] | None
FactValue = str | bool | Decimal | tuple[str, ...] | None
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DECIMAL_PATHS = frozenset(
    [f"finance.{name}" for name in FinancialPolicy.model_fields] + ["geography.max_distance_km"]
)
SET_PATHS = frozenset(
    [f"geography.{name}" for name in ("federal_districts", "regions", "cities")]
    + ["enabled_platforms", "allowed_procedure_methods"]
)
CRITICAL_PATHS = frozenset(
    [f"finance.{name}" for name in FinancialPolicy.model_fields]
    + ["enabled_platforms", "allowed_procedure_methods", "subcontracting_allowed", "prohibitions"]
)
UNSUPPORTED_CRITICAL_PATHS = frozenset({"prohibitions"})
OPTIONAL_PATHS = frozenset({"identity.kpp", "geography.max_distance_km"})
_GROUPS: dict[str, type[BaseModel]] = {
    "identity": CompanyIdentity,
    "geography": GeographyPolicy,
    "finance": FinancialPolicy,
}
_ROOT_NAMES = (
    "okved",
    "business_description",
    "supplied_goods",
    "performed_works",
    "provided_services",
    "enabled_platforms",
    "subcontracting_allowed",
    "allowed_procedure_methods",
    "prohibitions",
)
FIELD_PATHS = tuple(
    [f"{group}.{name}" for group, model in _GROUPS.items() for name in model.model_fields]
    + list(_ROOT_NAMES)
)


def validate_profile_value(path: str, value: InputValue | Decimal) -> FactValue:
    """Проверить значение по исходному доменному полю без изменения старого профиля."""
    if path not in FIELD_PATHS:
        raise ValueError("unsupported_field")
    if value is None:
        raise ValueError("known_value_required")
    if path == "prohibitions":
        # Запреты недоступны для изменения без доверенной роли владельца.
        if value != ():
            raise ValueError("critical_settings_locked")
        return ()
    if "." in path:
        group, name = path.split(".", 1)
        info = _GROUPS[group].model_fields[name]
    else:
        info = CompanyProfile.model_fields[path]
    if path in DECIMAL_PATHS:
        value = _finite_financial_decimal(value)
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError("empty_value")
    elif isinstance(value, tuple):
        if len(value) > 100 or any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("invalid_list")
        value = tuple(dict.fromkeys(item.strip() for item in value))
    annotation = Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    adapter: TypeAdapter[Any] = TypeAdapter(cast(Any, annotation))
    if path in SET_PATHS and isinstance(value, tuple):
        value = frozenset(value)  # type: ignore[assignment]
    checked = adapter.validate_python(value, strict=True)
    if path in SET_PATHS:
        checked = tuple(sorted(checked))
    if path == "allowed_procedure_methods" and not set(checked) <= {
        item.value for item in ProcedureMethod
    }:
        raise ValueError("unsupported_procedure_method")
    if isinstance(checked, Decimal):
        if not checked.is_finite():
            raise ValueError("finite_decimal_required")
        return Decimal(format(checked.normalize(), "f")) if checked else Decimal("0")
    return checked  # type: ignore[no-any-return]


class ProfileFactInput(BaseModel):
    """Точный ручной ввод: источники/личность задаёт сервер, числа передаются строками."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    knowledge: Knowledge
    value: InputValue = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _json_lists(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("value"), list):
            return {**value, "value": tuple(value["value"])}
        return value

    @model_validator(mode="after")
    def _state(self) -> Self:
        if self.knowledge == "KNOWN":
            if self.value is None or self.reason is not None:
                raise ValueError("known_value_required")
        elif self.value is not None or not self.reason or not self.reason.strip():
            raise ValueError("unknown_requires_null_and_reason")
        return self


class ProfileFieldSource(BaseModel):
    """Источник заявления, привязанный к tenant и сохранённой команде."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: str = Field(min_length=1)
    provenance: Provenance
    kind: Literal["manual_declaration"] = "manual_declaration"
    source_sha256: SHA
    recorded_at: datetime
    recorded_by: str = Field(min_length=1)
    source_url: None = None

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("aware_timestamp_required")
        if self.provenance.extractor is not Extractor.MANUAL:
            raise ValueError("manual_source_required")
        return self


class ProfileFact(BaseModel):
    """Состояние знания не является вердиктом соответствия."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    knowledge: Knowledge = "UNKNOWN"
    value: FactValue = None
    sources: tuple[ProfileFieldSource, ...] = ()
    reason: str | None = "NOT_PROVIDED"

    @model_validator(mode="after")
    def _state(self) -> Self:
        if self.knowledge == "KNOWN":
            if self.value is None or not self.sources or self.reason is not None:
                raise ValueError("known_fact_requires_value_and_sources")
        elif self.value is not None or not self.reason:
            raise ValueError("unknown_fact_requires_null_and_reason")
        elif self.knowledge == "NOT_APPLICABLE" and not self.sources:
            raise ValueError("not_applicable_requires_source")
        return self


class ProfileSaveCommand(BaseModel):
    """Изменения относительно точной редакции, а не произвольный полный JSON профиля."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: Literal["company-profile-save-command-v1"] = "company-profile-save-command-v1"
    expected_version: int = Field(ge=0)
    changes: dict[str, ProfileFactInput] = Field(max_length=50)
    confirmation_sha256: SHA | None = None

    @model_validator(mode="after")
    def _fields(self) -> Self:
        for path, fact in self.changes.items():
            if path not in FIELD_PATHS:
                raise ValueError(f"unsupported_field:{path}")
            if path in UNSUPPORTED_CRITICAL_PATHS:
                raise ValueError(f"unsupported_profile_field:{path}")
            if fact.knowledge == "NOT_APPLICABLE" and path not in OPTIONAL_PATHS:
                raise ValueError(f"not_applicable_forbidden:{path}")
            if fact.knowledge == "KNOWN":
                try:
                    validate_profile_value(path, fact.value)
                except ValueError as error:
                    raise ValueError(f"invalid_profile_field:{path}") from error
        return self

    def normalized_changes(self) -> dict[str, ProfileFactInput]:
        """Нормализовать ввод до hashing и проверки идемпотентности."""
        result: dict[str, ProfileFactInput] = {}
        for path, fact in self.changes.items():
            value = validate_profile_value(path, fact.value) if fact.knowledge == "KNOWN" else None
            if isinstance(value, Decimal):
                value = format(value, "f")
            result[path] = ProfileFactInput(
                knowledge=fact.knowledge,
                value=value,
                reason=fact.reason,
            )
        return result

    def digest(self) -> str:
        """Связать receipt с нормализованным payload."""
        return payload_digest(
            {
                "schema_version": self.schema_version,
                "expected_version": self.expected_version,
                "changes": {
                    key: value.model_dump(mode="json")
                    for key, value in self.normalized_changes().items()
                },
            }
        )

    def confirmation_digest(self, company_id: str, actor_id: str) -> str:
        """Вернуть digest точного server-bound подтверждения policy-изменения."""
        return payload_digest(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "command_sha256": self.digest(),
            }
        )


class ProfilePolicyConfirmation(BaseModel):
    """Неизменяемая привязка owner-подтверждения к точной команде версии."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    command_sha256: SHA
    confirmation_sha256: SHA
    confirmed_by: str = Field(min_length=1)
    confirmed_at: datetime
    changed_paths: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("aware_timestamp_required")
        if not self.changed_paths or not set(self.changed_paths) <= CRITICAL_PATHS:
            raise ValueError("invalid_policy_confirmation_paths")
        return self


class CompanyProfileSnapshot(BaseModel):
    """Неизменяемая независимая редакция; старые кейсы её не читают автоматически."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["company-profile-snapshot-v1"] = "company-profile-snapshot-v1"
    company_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    parent_version: int | None = Field(default=None, ge=1)
    created_at: datetime
    created_by: str = Field(min_length=1)
    effective_at: datetime
    currency: Literal["RUB"] = "RUB"
    amount_basis: Literal["EX_VAT"] = "EX_VAT"
    facts: dict[str, ProfileFact]
    critical_settings_status: Literal["OWNER_AUTHORIZATION_UNAVAILABLE", "OWNER_AUTHORIZED"] = (
        "OWNER_AUTHORIZATION_UNAVAILABLE"
    )
    policy_confirmation: ProfilePolicyConfirmation | None = None
    snapshot_sha256: SHA
    audit_event_id: str = Field(min_length=1)

    @model_serializer(mode="wrap")
    def _legacy_wire(self, handler: Any) -> dict[str, Any]:
        """Не добавлять null в exact JSON уже сохранённых legacy-снимков."""
        payload = cast(dict[str, Any], handler(self))
        if payload.get("policy_confirmation") is None:
            payload.pop("policy_confirmation")
        return payload

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if set(self.facts) != set(FIELD_PATHS):
            raise ValueError("exact_profile_fields_required")
        if self.parent_version != (self.version - 1 if self.version > 1 else None):
            raise ValueError("invalid_parent_version")
        for moment in (self.created_at, self.effective_at):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("aware_timestamp_required")
        if (self.critical_settings_status == "OWNER_AUTHORIZED") != (
            self.policy_confirmation is not None
        ):
            raise ValueError("policy_confirmation_status_mismatch")
        for path, fact in self.facts.items():
            if fact.knowledge == "KNOWN":
                validate_profile_value(path, fact.value)
            if fact.knowledge == "NOT_APPLICABLE" and path not in OPTIONAL_PATHS:
                raise ValueError("invalid_not_applicable")
            if any(source.company_id != self.company_id for source in fact.sources):
                raise ValueError("source_tenant_mismatch")
        validate_partial_profile(self.facts)
        if self.snapshot_sha256 != snapshot_digest(snapshot_payload(self)):
            raise ValueError("snapshot_digest_mismatch")
        return self


def snapshot_digest(payload: dict[str, Any]) -> str:
    """Использовать существующий JSON hash; Decimal уже сериализован строкой."""
    return payload_digest(payload)


def snapshot_payload(snapshot: CompanyProfileSnapshot) -> dict[str, Any]:
    """Канонический payload, совместимый с версиями до policy_confirmation."""
    payload = snapshot.model_dump(mode="json", exclude={"snapshot_sha256"})
    if payload.get("policy_confirmation") is None:
        payload.pop("policy_confirmation", None)
    return payload


def validate_partial_profile(facts: dict[str, ProfileFact]) -> None:
    """Проверить известные взаимосвязи без подстановки неизвестных defaults."""
    for group, model in _GROUPS.items():
        paths = [f"{group}.{name}" for name in model.model_fields]
        if all(facts[path].knowledge != "UNKNOWN" for path in paths):
            try:
                model.model_validate({path.split(".", 1)[1]: facts[path].value for path in paths})
            except ValueError as error:
                raise ValueError(f"invalid_profile_group:{group}") from error
    finance = {
        path.split(".", 1)[1]: facts[path].value
        for path in FIELD_PATHS
        if path.startswith("finance.") and facts[path].knowledge == "KNOWN"
    }
    pairs = (
        ("min_contract_amount", "max_contract_amount"),
        ("max_contract_without_extra_approval", "max_contract_amount"),
        ("price_floor_margin", "min_margin"),
    )
    for low, high in pairs:
        if (
            low in finance
            and high in finance
            and Decimal(str(finance[low])) > Decimal(str(finance[high]))
        ):
            raise ValueError(f"unordered_limits:{low}:{high}")


def new_snapshot(
    company_id: str,
    actor_id: str,
    command: ProfileSaveCommand,
    previous: CompanyProfileSnapshot | None,
    audit_event_id: str,
    policy_confirmation: ProfilePolicyConfirmation | None = None,
) -> CompanyProfileSnapshot:
    """Материализовать источники ручного ввода, сохранив evidence неизменённых полей."""
    at = datetime.now(UTC)
    digest = command.digest()
    facts = dict(previous.facts) if previous else {path: ProfileFact() for path in FIELD_PATHS}
    for path, incoming in command.normalized_changes().items():
        old = facts[path]
        if (old.knowledge, old.value, old.reason) == (
            incoming.knowledge,
            incoming.value,
            incoming.reason,
        ):
            continue
        sources: tuple[ProfileFieldSource, ...] = ()
        if incoming.knowledge != "UNKNOWN":
            sources = (
                ProfileFieldSource(
                    company_id=company_id,
                    provenance=Provenance(
                        document_id=f"profile-command:{digest}",
                        locator=path,
                        extractor=Extractor.MANUAL,
                    ),
                    source_sha256=digest,
                    recorded_at=at,
                    recorded_by=actor_id,
                ),
            )
        facts[path] = ProfileFact(
            knowledge=incoming.knowledge,
            value=incoming.value,
            reason=incoming.reason,
            sources=sources,
        )
    payload = {
        "schema_version": "company-profile-snapshot-v1",
        "company_id": company_id,
        "version": command.expected_version + 1,
        "parent_version": command.expected_version or None,
        "created_at": at.isoformat().replace("+00:00", "Z"),
        "effective_at": at.isoformat().replace("+00:00", "Z"),
        "created_by": actor_id,
        "currency": "RUB",
        "amount_basis": "EX_VAT",
        "facts": {path: fact.model_dump(mode="json") for path, fact in facts.items()},
        "audit_event_id": audit_event_id,
    }
    confirmation = policy_confirmation or (previous.policy_confirmation if previous else None)
    if confirmation is not None:
        payload["critical_settings_status"] = "OWNER_AUTHORIZED"
        payload["policy_confirmation"] = confirmation.model_dump(mode="json")
    else:
        payload["critical_settings_status"] = "OWNER_AUTHORIZATION_UNAVAILABLE"
    return CompanyProfileSnapshot.model_validate(
        {**payload, "snapshot_sha256": snapshot_digest(payload)}
    )


class ProfileVersionRef(BaseModel):
    """Точная ссылка для передачи агенту сравнения."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    company_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    snapshot_sha256: SHA


class ProfileSelectionCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    version: int = Field(ge=1)
    snapshot_sha256: SHA


class ProfileSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["company-profile-selection-v1"] = "company-profile-selection-v1"
    company_id: str
    selection_id: str
    profile_ref: ProfileVersionRef
    selected_at: datetime
    selected_by: str
    audit_event_id: str

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.company_id != self.profile_ref.company_id:
            raise ValueError("selection_tenant_mismatch")
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None:
            raise ValueError("aware_timestamp_required")
        return self
