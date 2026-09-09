"""API boundary regressions: auth derives tenant identity and errors stay safe."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from procurement.api import create_app
from procurement.api.contracts import CasePage, EvaluationRecord, Principal, VersionConflict
from procurement.domain.cases import ProcurementCase
from procurement.domain.decisions import Recommendation

PAPER_CASE = Path(__file__).parent.parent / "examples" / "paper_case.json"
AUTH_A = {"Authorization": "Bearer tenant-a-token"}
WRITE_HEADERS = {**AUTH_A, "Idempotency-Key": "request-001"}


class FakeAuthenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "tenant-a-token": Principal(company_id="demo-company", actor_id="operator-a"),
            "tenant-b-token": Principal(company_id="other-company", actor_id="operator-b"),
        }.get(credential)


class FakeCaseService:
    def __init__(self) -> None:
        self.cases: dict[tuple[str, str, int], ProcurementCase] = {}
        self.evaluations: dict[tuple[str, str, int], EvaluationRecord] = {}
        self.evaluation_calls: list[dict[str, object]] = []
        self.created_with: list[dict[str, object]] = []

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        key = (company_id, case.case_id, case.version)
        if key in self.cases:
            raise VersionConflict
        self.cases[key] = case
        self.created_with.append(
            {
                "company_id": company_id,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
        )
        return case

    async def get_case(
        self, *, company_id: str, case_id: str, version: int
    ) -> ProcurementCase | None:
        return self.cases.get((company_id, case_id, version))

    async def list_cases(self, *, company_id: str, cursor: str | None, limit: int) -> CasePage:
        items = tuple(case for (tenant, _, _), case in self.cases.items() if tenant == company_id)
        return CasePage(items=items[:limit])

    async def get_latest_evaluation(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> EvaluationRecord | None:
        return self.evaluations.get((company_id, case_id, version))

    async def record_evaluation(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        version: int,
        effective_at: datetime,
        recommendation: Recommendation,
        engine_version: str,
        input_digest: str,
        idempotency_key: str,
        request_digest: str,
    ) -> EvaluationRecord:
        self.evaluation_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "case_id": case_id,
                "version": version,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
        )
        record = EvaluationRecord(
            evaluation_id=f"evaluation-{len(self.evaluation_calls)}",
            audit_event_id=f"audit-{len(self.evaluation_calls)}",
            recommendation=recommendation,
            engine_version=engine_version,
            input_digest=input_digest,
            effective_at=effective_at,
        )
        self.evaluations[(company_id, case_id, version)] = record
        return record


def paper_case_payload() -> dict[str, Any]:
    return json.loads(PAPER_CASE.read_text(encoding="utf-8"))


def other_tenant_case() -> ProcurementCase:
    payload = paper_case_payload()
    payload["case_id"] = "other-case"
    payload["company_id"] = "other-company"
    payload["profile"]["company_id"] = "other-company"
    payload["selected_quote"]["company_id"] = "other-company"
    return ProcurementCase.model_validate(payload)


@pytest.fixture
def service() -> FakeCaseService:
    service = FakeCaseService()
    case = other_tenant_case()
    service.cases[(case.company_id, case.case_id, case.version)] = case
    return service


@pytest.fixture
def app(service: FakeCaseService):
    return create_app(service, FakeAuthenticator())


def request(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def test_health_is_public_and_openapi_has_no_tenant_auth_header(app: object) -> None:
    assert request(app, "GET", "/health").json() == {"status": "ok"}

    schema = request(app, "GET", "/openapi.json").json()
    parameters = schema["paths"]["/v1/cases"]["post"].get("parameters", [])
    tenant_headers = {"company", "company-id", "x-company-id"}
    assert not any(parameter["name"].lower() in tenant_headers for parameter in parameters)


def test_missing_and_invalid_bearer_have_identical_safe_error(app: object) -> None:
    missing = request(app, "GET", "/v1/cases")
    invalid = request(app, "GET", "/v1/cases", headers={"Authorization": "Bearer wrong-secret"})

    assert missing.status_code == invalid.status_code == 401
    assert missing.json() == invalid.json() == {"detail": "invalid_credentials"}
    assert missing.headers["www-authenticate"] == invalid.headers["www-authenticate"] == "Bearer"
    assert "wrong-secret" not in invalid.text


def test_create_rejects_body_tenant_mismatch_even_with_tenant_header(
    app: object, service: FakeCaseService
) -> None:
    payload = paper_case_payload()
    payload["company_id"] = "other-company"
    payload["profile"]["company_id"] = "other-company"
    payload["selected_quote"]["company_id"] = "other-company"

    response = request(
        app,
        "POST",
        "/v1/cases",
        headers={**WRITE_HEADERS, "X-Company-ID": "other-company"},
        json=payload,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "tenant_mismatch"}
    assert not service.created_with


def test_cross_tenant_guessed_path_is_indistinguishable_from_missing(app: object) -> None:
    guessed = request(app, "GET", "/v1/cases/other-case/versions/1", headers=AUTH_A)
    missing = request(app, "GET", "/v1/cases/not-there/versions/1", headers=AUTH_A)

    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}


def test_list_is_scoped_and_duplicate_immutable_version_conflicts(app: object) -> None:
    payload = paper_case_payload()
    created = request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=payload)
    duplicate = request(
        app,
        "POST",
        "/v1/cases",
        headers={**AUTH_A, "Idempotency-Key": "request-002"},
        json=payload,
    )
    listed = request(app, "GET", "/v1/cases?limit=1", headers=AUTH_A)

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "version_conflict"}
    assert [item["case_id"] for item in listed.json()["items"]] == ["synthetic-case-001"]


def test_evaluation_uses_authenticated_actor_and_rejects_client_actor(
    app: object, service: FakeCaseService
) -> None:
    payload = paper_case_payload()
    assert request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=payload).status_code == 201

    path = "/v1/cases/synthetic-case-001/versions/1/evaluations"
    malformed = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-001"},
        json={"effective_at": "2026-09-08T12:00:00+03:00", "actor_id": "attacker"},
    )
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "validation_error"}
    assert not service.evaluation_calls

    response = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-002"},
        json={"effective_at": "2026-10-01T12:00:00+03:00"},
    )

    assert response.status_code == 201
    assert response.json()["recommendation"]["decision"] == "do_not_participate"
    assert response.json()["engine_version"] == "s1"
    assert response.json()["audit_event_id"] == "audit-1"
    assert len(response.json()["input_digest"]) == 64
    assert len(service.evaluation_calls) == 1
    call = service.evaluation_calls[0]
    assert call["company_id"] == "demo-company"
    assert call["actor_id"] == "operator-a"
    assert call["case_id"] == "synthetic-case-001"
    assert call["version"] == 1
    assert call["idempotency_key"] == "evaluation-002"
    assert isinstance(call["request_digest"], str) and len(call["request_digest"]) == 64


def test_naive_time_float_and_invalid_idempotency_are_sanitized(app: object) -> None:
    path = "/v1/cases/synthetic-case-001/versions/1/evaluations"
    naive = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-003"},
        json={"effective_at": "2026-09-08T12:00:00"},
    )
    assert naive.status_code == 422
    assert naive.json() == {"detail": "validation_error"}

    invalid_money = paper_case_payload()
    invalid_money["nmck_ex_vat"] = 1.5
    invalid = request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=invalid_money)
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "validation_error"}

    bad_key = request(
        app,
        "POST",
        "/v1/cases",
        headers={**AUTH_A, "Idempotency-Key": "contains space"},
        json=paper_case_payload(),
    )
    assert bad_key.status_code == 422
    assert bad_key.json() == {"detail": "validation_error"}


def test_latest_evaluation_returns_only_the_persisted_record(
    app: object,
    service: FakeCaseService,
) -> None:
    case = ProcurementCase.model_validate(paper_case_payload())
    service.cases[(case.company_id, case.case_id, case.version)] = case
    latest_path = f"/v1/cases/{case.case_id}/versions/{case.version}/evaluations/latest"

    absent = request(app, "GET", latest_path, headers=AUTH_A)
    assert absent.status_code == 404
    assert absent.json() == {"detail": "not_found"}
    assert not service.evaluation_calls

    created = request(
        app,
        "POST",
        f"/v1/cases/{case.case_id}/versions/{case.version}/evaluations",
        headers={**AUTH_A, "Idempotency-Key": "latest-evaluation"},
        json={"effective_at": "2026-09-08T12:00:00+03:00"},
    )
    latest = request(app, "GET", latest_path, headers=AUTH_A)

    assert created.status_code == 201
    assert latest.status_code == 200
    assert latest.json() == created.json()
    assert len(service.evaluation_calls) == 1


def test_latest_evaluation_cross_tenant_and_absent_are_identical(
    app: object,
    service: FakeCaseService,
) -> None:
    created = request(
        app,
        "POST",
        "/v1/cases/other-case/versions/1/evaluations",
        headers={
            "Authorization": "Bearer tenant-b-token",
            "Idempotency-Key": "tenant-b-eval",
        },
        json={"effective_at": "2026-09-08T12:00:00+03:00"},
    )
    assert created.status_code == 201

    guessed = request(
        app,
        "GET",
        "/v1/cases/other-case/versions/1/evaluations/latest",
        headers={**AUTH_A, "X-Company-ID": "other-company"},
    )
    missing = request(
        app,
        "GET",
        "/v1/cases/not-there/versions/1/evaluations/latest",
        headers=AUTH_A,
    )
    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}
