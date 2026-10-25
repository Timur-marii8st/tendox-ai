"""Канонический DTO профиля и отдельно legacy примеры локального демо.

UNKNOWN не заменяется defaults, hash и tenant проверяются существующей моделью.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, TypeAdapter

from procurement.domain.cases import _canonical
from procurement.domain.company import CompanyProfile, _finite_financial_decimal
from procurement.domain.provenance import Provenance
from procurement.domain.tenders import ProcedureMethod

SCHEMA = "company-profile-snapshot-v1"
GROUPS = ("identity", "geography", "finance")


def digest(value: object) -> str:
    """Канонический digest с правилами кейса и нормализацией Decimal/UTC."""

    def normalized(item: Any) -> Any:
        if isinstance(item, Decimal):
            decimal_text = format(item, "f")
            return (
                (decimal_text.rstrip("0").rstrip(".") if "." in decimal_text else decimal_text)
                if item != 0
                else "0"
            )
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, dict):
            return {key: normalized(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalized(val) for val in item]
        return item

    encoded = json.dumps(
        _canonical(normalized(value)), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def aware(value: str) -> datetime:
    """Прочитать момент, отклонив отсутствие timezone."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timezone required")
    return moment


def fact(snapshot: dict[str, Any], path: str) -> dict[str, Any]:
    """Прочитать лист согласованного контракта; не подставлять defaults."""
    if path in snapshot["facts"]:
        return dict(snapshot["facts"][path])
    value = snapshot["facts"]
    for part in path.split("."):
        value = value[part]
    return dict(value)


def _leaves() -> dict[str, Any]:
    leaves: dict[str, Any] = {}
    for name, field in CompanyProfile.model_fields.items():
        if name in {"company_id", "version"}:
            continue
        if name in GROUPS:
            assert isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel)
            for child, child_field in field.annotation.model_fields.items():
                leaves[f"{name}.{child}"] = child_field
        else:
            leaves[name] = field
    return leaves


def validate_example_snapshot(raw: dict[str, Any], company_id: str) -> dict[str, Any]:
    """Проверить read-only пример контракта, tenant, hash и существующие типы.

    API/CRUD валидация и разрешение документов остаются у владельца профиля.
    Примеры не принимаются от HTTP-клиента и не являются реестром профилей.
    """
    if "critical_settings_status" in raw:
        from procurement.domain.company_profile_snapshot import CompanyProfileSnapshot

        checked = CompanyProfileSnapshot.model_validate(raw)
        if checked.company_id != company_id:
            raise LookupError("snapshot not found")
        return checked.model_dump(mode="json")
    snapshot = deepcopy(raw)
    headers = {
        "schema_version",
        "company_id",
        "version",
        "parent_version",
        "created_at",
        "created_by",
        "effective_at",
        "currency",
        "amount_basis",
        "facts",
        "policy_confirmation",
        "snapshot_sha256",
        "audit_event_id",
    }
    if set(snapshot) != headers or snapshot["schema_version"] != SCHEMA:
        raise ValueError("unsupported snapshot shape")
    if snapshot["company_id"] != company_id:
        raise LookupError("snapshot not found")
    version = snapshot["version"]
    if type(version) is not int or version < 1:
        raise ValueError("invalid version")
    if snapshot["parent_version"] != (None if version == 1 else version - 1):
        raise ValueError("invalid parent version")
    if (snapshot["currency"], snapshot["amount_basis"]) != ("RUB", "EX_VAT"):
        raise ValueError("unsupported amount basis")
    created = aware(snapshot["created_at"])
    if aware(snapshot["effective_at"]) != created:
        raise ValueError("deferred activation unsupported")
    if not snapshot["created_by"] or not snapshot["audit_event_id"]:
        raise ValueError("missing snapshot provenance")
    confirmation = snapshot["policy_confirmation"]
    if set(confirmation) != {"actor_id", "confirmed_at", "command_sha256", "changed_paths"}:
        raise ValueError("invalid policy confirmation")
    if confirmation["actor_id"] != snapshot["created_by"]:
        raise ValueError("confirmation actor mismatch")
    aware(confirmation["confirmed_at"])
    if not re.fullmatch(r"[0-9a-f]{64}", confirmation["command_sha256"]):
        raise ValueError("invalid command hash")
    if snapshot["snapshot_sha256"] != digest(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    ):
        raise ValueError("snapshot digest mismatch")

    leaves = _leaves()
    expected_roots = {path.split(".")[0] for path in leaves}
    if set(snapshot["facts"]) != expected_roots:
        raise ValueError("missing or extra facts")
    for group in GROUPS:
        if set(snapshot["facts"][group]) != {
            path.split(".")[1] for path in leaves if path.startswith(group + ".")
        }:
            raise ValueError("missing or extra group facts")
    values: dict[str, Any] = {"company_id": company_id, "version": version}
    for path, field in leaves.items():
        leaf = fact(snapshot, path)
        if set(leaf) != {"knowledge", "value", "sources", "reason"}:
            raise ValueError("invalid fact shape")
        knowledge = leaf["knowledge"]
        if knowledge not in {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"}:
            raise ValueError("invalid knowledge")
        if knowledge == "UNKNOWN":
            if leaf["value"] is not None or leaf["reason"] not in {
                "NOT_PROVIDED",
                "SOURCE_MISSING",
                "AMBIGUOUS",
                "CONFLICTING_SOURCES",
                "UNSUPPORTED_FIELD",
            }:
                raise ValueError("invalid UNKNOWN")
        else:
            if not leaf["sources"]:
                raise ValueError("known fact requires source")
            if knowledge == "NOT_APPLICABLE":
                if path not in {"identity.kpp", "geography.max_distance_km"}:
                    raise ValueError("unsupported NOT_APPLICABLE")
                if leaf["value"] is not None or not leaf["reason"]:
                    raise ValueError("invalid NOT_APPLICABLE")
            elif leaf["value"] is None or leaf["reason"] is not None:
                raise ValueError("invalid KNOWN")
        for source in leaf["sources"]:
            if set(source) != {
                "provenance",
                "kind",
                "source_sha256",
                "recorded_at",
                "recorded_by",
                "source_url",
            }:
                raise ValueError("invalid field source")
            Provenance.model_validate(source["provenance"])
            if source["kind"] not in {
                "manual_declaration",
                "retained_document",
                "official_document",
            } or not re.fullmatch(r"[0-9a-f]{64}", source["source_sha256"]):
                raise ValueError("invalid source kind/hash")
            if not source["recorded_by"] or aware(source["recorded_at"]) > created:
                raise ValueError("invalid source actor/time")
        if knowledge == "UNKNOWN":
            continue
        value = leaf["value"]
        if path.startswith("finance.") or path == "geography.max_distance_km":
            if value is not None and not isinstance(value, str):
                raise ValueError("Decimal transport requires decimal string")
            if value is not None:
                _finite_financial_decimal(value)
        if path in {"geography.all_russia", "subcontracting_allowed"} and type(value) is not bool:
            raise ValueError("boolean required")
        value = TypeAdapter(field.rebuild_annotation()).validate_python(value)
        if path == "allowed_procedure_methods":
            for method in value:
                ProcedureMethod(method)
        parts = path.split(".")
        if len(parts) == 2:
            values.setdefault(parts[0], {})[parts[1]] = value
        else:
            values[path] = value
    # Неизвестный лимит не скрывает противоречия известных значений.
    finance = values.get("finance", {})
    for lower, upper in (
        ("min_contract_amount", "max_contract_amount"),
        ("max_contract_without_extra_approval", "max_contract_amount"),
        ("price_floor_margin", "min_margin"),
    ):
        if lower in finance and upper in finance and finance[lower] > finance[upper]:
            raise ValueError("contradictory financial limits")
    for group in GROUPS:
        group_type = CompanyProfile.model_fields[group].annotation
        if all(
            fact(snapshot, path)["knowledge"] != "UNKNOWN"
            for path in leaves
            if path.startswith(group + ".")
        ):
            assert isinstance(group_type, type) and issubclass(group_type, BaseModel)
            group_type.model_validate(values[group])
    if all(fact(snapshot, path)["knowledge"] != "UNKNOWN" for path in leaves):
        CompanyProfile.model_validate(values)
    return snapshot


def complete_domain_profile(snapshot: dict[str, Any]) -> CompanyProfile | None:
    """Адаптировать только полностью известный контракт, без UNKNOWN defaults."""
    values: dict[str, Any] = {"company_id": snapshot["company_id"], "version": snapshot["version"]}
    for path in _leaves():
        leaf = fact(snapshot, path)
        if leaf["knowledge"] == "UNKNOWN":
            return None
        parts = path.split(".")
        if len(parts) == 2:
            values.setdefault(parts[0], {})[parts[1]] = leaf["value"]
        else:
            values[path] = leaf["value"]
    return CompanyProfile.model_validate(values)
