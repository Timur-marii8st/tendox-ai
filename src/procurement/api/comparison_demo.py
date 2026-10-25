"""Изолированный local-only API сравнения; никакого production storage/ЕИС.

Запуск: COMPARISON_DEMO_TOKEN=<локальный token> uv run uvicorn
procurement.api.comparison_demo:create_demo_app --factory --host 127.0.0.1 --port 8123
"""

import json
import os
import secrets
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from procurement.access import AccessRole
from procurement.api.contracts import Authenticator, Principal
from procurement.comparison.profile_adapter import aware, fact, validate_example_snapshot
from procurement.comparison.service import (
    CaseRef,
    CompareCommand,
    ComparisonReport,
    ProfileRef,
    SelectedCase,
    compare_selected,
)
from procurement.domain.cases import ProcurementCase, case_input_digest
from procurement.domain.provenance import Provenance

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "comparison"
_bearer = HTTPBearer(auto_error=False)


class ContractExamplesAdapter:
    """Только согласованные статические примеры. API замена — отдельный acceptance."""

    def __init__(self, root: Path = EXAMPLES) -> None:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["mode"] != "LOCAL_DEMO_SYNTHETIC":
            raise ValueError("only isolated synthetic examples are supported")
        self.at = aware(manifest["compared_at"])
        self._profiles = [
            json.loads((root / name).read_text(encoding="utf-8")) for name in manifest["profiles"]
        ]
        self._cases: list[SelectedCase] = []
        for name in manifest["cases"]:
            data = json.loads((root / name).read_text(encoding="utf-8"))
            case = ProcurementCase.model_validate(data["case_snapshot"])
            self._cases.append(
                SelectedCase(
                    case=case,
                    economics_input_sha256=data["economics_input_sha256"],
                    economics_sources=tuple(
                        Provenance.model_validate(source) for source in data["economics_sources"]
                    ),
                )
            )
        for profile in self._profiles:
            validate_example_snapshot(profile, profile["company_id"])

    def catalog(self, company_id: str) -> dict[str, Any]:
        """Показать только точные refs текущего authenticated tenant."""
        profiles = []
        for profile in self._profiles:
            if profile["company_id"] == company_id:
                name = fact(profile, "identity.name")
                profiles.append(
                    {
                        "ref": {
                            "version": profile["version"],
                            "snapshot_sha256": profile["snapshot_sha256"],
                        },
                        "name": name["value"] or "Название UNKNOWN",
                        "created_at": profile["created_at"],
                    }
                )
        return {
            "mode": "LOCAL_DEMO_SYNTHETIC",
            "company_id": company_id,
            "compared_at": self.at.isoformat(),
            "profiles": profiles,
            "cases": [
                {
                    "ref": CaseRef(
                        case_id=item.case.case_id,
                        version=item.case.version,
                        input_sha256=case_input_digest(item.case),
                    ).model_dump(),
                    "subject": item.case.tender.subject,
                    "nmck_ex_vat": str(item.case.nmck_ex_vat),
                    "deadline": item.case.tender.submission.closes_at.isoformat(),
                }
                for item in self._cases
                if item.case.company_id == company_id
            ],
        }

    def profile(self, company_id: str, ref: ProfileRef) -> dict[str, Any]:
        """Разрешить точную версию/hash, не использовать latest."""
        for profile in self._profiles:
            if profile["company_id"] == company_id and profile["version"] == ref.version:
                if profile["snapshot_sha256"] != ref.snapshot_sha256:
                    raise ValueError("profile ref mismatch")
                return deepcopy(profile)
        raise LookupError("profile not found")

    def case(self, company_id: str, ref: CaseRef) -> SelectedCase:
        """Разрешить точный tenant-scoped кейс, отклонить изменённый hash."""
        for item in self._cases:
            case = item.case
            if (case.company_id, case.case_id, case.version) == (
                company_id,
                ref.case_id,
                ref.version,
            ):
                if case_input_digest(case) != ref.input_sha256:
                    raise ValueError("case ref mismatch")
                return SelectedCase(
                    case=ProcurementCase.model_validate(case.model_dump(mode="python")),
                    economics_input_sha256=item.economics_input_sha256,
                    economics_sources=item.economics_sources,
                )
        raise LookupError("case not found")


class DemoAuthenticator:
    """Локальный credential, явно отдельный от production/pilot-token."""

    def __init__(self, token: str) -> None:
        if len(token) < 16:
            raise ValueError("set a local COMPARISON_DEMO_TOKEN of at least 16 characters")
        self._token = token

    async def authenticate(self, credential: str) -> Principal | None:
        if secrets.compare_digest(credential, self._token):
            return Principal(company_id="demo-company", actor_id="local-demo-operator")
        return None


def create_comparison_app(
    adapter: ContractExamplesAdapter, authenticator: Authenticator
) -> FastAPI:
    """Публичная граница не принимает profile JSON, tenant, verdict или время."""
    app = FastAPI(title="Local procurement comparison — synthetic examples")

    async def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        principal = (
            await authenticator.authenticate(credentials.credentials) if credentials else None
        )
        if principal is None:
            raise HTTPException(401, "authentication required")
        return principal

    @app.get("/v1/local-comparison/catalog")
    async def catalog(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> dict[str, Any]:
        return adapter.catalog(principal.company_id)

    @app.post("/v1/local-comparison", response_model=ComparisonReport)
    async def compare(
        command: CompareCommand,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ComparisonReport:
        if principal.access_role != AccessRole.OPERATOR:
            raise HTTPException(403, "comparison requires OPERATOR")
        try:
            snapshot = adapter.profile(principal.company_id, command.profile_ref)
            cases = tuple(adapter.case(principal.company_id, ref) for ref in command.case_refs)
            return compare_selected(principal.company_id, snapshot, cases, at=adapter.at)
        except LookupError as error:
            raise HTTPException(404, "selected version not found") from error
        except ValueError as error:
            raise HTTPException(409, "selected snapshot is inconsistent; reload catalog") from error

    return app


def create_demo_app() -> FastAPI:
    """Factory требует отдельный локальный token; подключения к БД отсутствуют."""
    return create_comparison_app(
        ContractExamplesAdapter(), DemoAuthenticator(os.environ.get("COMPARISON_DEMO_TOKEN", ""))
    )
