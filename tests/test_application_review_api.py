from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from typing import Any

import httpx

from case_support import AT
from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import DocumentRecord, InvalidApplicationReview, Principal
from procurement.documents import (
    ApplicationAttachmentReview,
    ApplicationInventoryAssessment,
    ApplicationPackageRecord,
    ApplicationPriceAssessment,
    ApplicationRequirementReview,
    ApplicationReviewDecision,
    ApplicationReviewRecord,
    DocumentRole,
    ExtractionResult,
    ExtractionStatus,
    build_application_package,
    build_application_review_decision,
)
from procurement.domain.compliance import Verdict
from test_application_review import _record


class Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        roles = {
            "reviewer": ("reviewer-a", AccessRole.APPLICATION_REVIEWER),
            "self": ("operator-b", AccessRole.APPLICATION_REVIEWER),
            "operator": ("operator-c", AccessRole.OPERATOR),
            "auditor": ("auditor-a", AccessRole.AUDITOR),
            "foreign": ("reviewer-z", AccessRole.APPLICATION_REVIEWER),
        }
        identity = roles.get(credential)
        if identity is None:
            return None
        actor, role = identity
        return Principal(
            company_id="other-company" if credential == "foreign" else "demo-company",
            actor_id=actor,
            access_role=role,
        )


class Service:
    def __init__(self) -> None:
        original = _record()
        package = original.package
        assert package is not None
        updated = build_application_package(
            original.evidence,
            package_id=package.package_id,
            proposed_price_ex_vat=package.proposed_price_ex_vat,
            requirements=package.requirements,
            attachments=(
                package.attachments[0].model_copy(
                    update={
                        "document_sha256": hashlib.sha256(
                            b"exact application bytes"
                        ).hexdigest()
                    }
                ),
            ),
            current_recommendation=package.current_recommendation,
            prepared_by=package.prepared_by,
            prepared_at=package.prepared_at,
        )
        self.evidence = ApplicationPackageRecord(evidence=original.evidence, package=updated)
        self.decision: ApplicationReviewDecision | None = None
        self.corrupt_content = False

    async def get_application_review(
        self, *, company_id: str, package_id: str
    ) -> ApplicationReviewRecord | None:
        package = self.evidence.package
        assert package is not None
        if company_id != package.company_id or package_id != package.package_id:
            return None
        return ApplicationReviewRecord(evidence=self.evidence, decision=self.decision)

    async def decide_application_review(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        package_sha256: str,
        requirement_reviews: tuple[ApplicationRequirementReview, ...],
        attachment_reviews: tuple[ApplicationAttachmentReview, ...],
        inventory_assessment: ApplicationInventoryAssessment,
        inventory_source_document_ids: tuple[str, ...],
        inventory_reason: str,
        price_assessment: ApplicationPriceAssessment,
        price_reason: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationReviewDecision:
        del idempotency_key, request_digest
        package = self.evidence.package
        assert package is not None
        if (
            company_id != package.company_id
            or package_id != package.package_id
            or package_sha256 != package.package_sha256
        ):
            raise InvalidApplicationReview
        try:
            self.decision = build_application_review_decision(
                self.evidence,
                requirement_reviews=requirement_reviews,
                attachment_reviews=attachment_reviews,
                inventory_assessment=inventory_assessment,
                inventory_source_document_ids=inventory_source_document_ids,
                inventory_reason=inventory_reason,
                price_assessment=price_assessment,
                price_reason=price_reason,
                reason=reason,
                reviewed_by=actor_id,
                reviewed_at=AT + timedelta(minutes=3),
            )
        except ValueError as error:
            raise InvalidApplicationReview from error
        return self.decision

    async def get_document(
        self, *, company_id: str, document_id: str
    ) -> DocumentRecord | None:
        if company_id != "demo-company" or document_id != "application-document":
            return None
        return DocumentRecord(
            document_id=document_id,
            original_filename="application.pdf",
            media_type="application/pdf",
            document_role=DocumentRole.APPLICATION_ATTACHMENT,
            byte_size=len(b"exact application bytes"),
            sha256=hashlib.sha256(b"exact application bytes").hexdigest(),
            extraction=ExtractionResult(
                status=ExtractionStatus.UNKNOWN,
                source_units_total=0,
                source_units_extracted=0,
                characters_extracted=0,
            ),
            created_at=AT,
        )

    async def get_document_content(
        self, *, company_id: str, document_id: str
    ) -> bytes | None:
        if company_id != "demo-company" or document_id != "application-document":
            return None
        return b"corrupt bytes" if self.corrupt_content else b"exact application bytes"


def call(service: Service, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(service, Authenticator()))  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def payload(service: Service) -> dict[str, object]:
    package = service.evidence.package
    assert package is not None
    return {
        "package_sha256": package.package_sha256,
        "requirement_reviews": [
            {
                "requirement_ordinal": 1,
                "status": Verdict.PASS.value,
                "reason": "Сверено с ТЗ и файлом",
                "attachment_ordinals": [1],
            }
        ],
        "attachment_reviews": [
            {
                "attachment_ordinal": 1,
                "status": Verdict.PASS.value,
                "reason": "Содержимое проверено",
            }
        ],
        "inventory_assessment": "CONFIRMED_COMPLETE",
        "inventory_source_document_ids": ["tender-document"],
        "inventory_reason": "Все разделы ТЗ сопоставлены",
        "price_assessment": "CONFIRMED",
        "price_reason": "Цена и НДС проверены",
        "reason": "Независимый review завершён",
    }


def test_application_review_is_independent_exact_and_read_only_for_auditor() -> None:
    service = Service()
    path = "/v1/application-packages/package-1/review"
    operator = call(service, "GET", path, headers={"Authorization": "Bearer operator"})
    foreign = call(service, "GET", path, headers={"Authorization": "Bearer foreign"})
    assert operator.status_code == 403
    assert foreign.status_code == 404
    loaded = call(service, "GET", path, headers={"Authorization": "Bearer reviewer"})
    assert loaded.status_code == 200
    assert loaded.json()["decision"] is None
    created = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "review-1"},
        json=payload(service),
    )
    assert created.status_code == 201
    assert created.json()["status"] == "PASS"
    assert created.json()["external_action_authorized"] is False
    auditor = call(service, "GET", path, headers={"Authorization": "Bearer auditor"})
    assert auditor.status_code == 200
    assert call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer auditor", "Idempotency-Key": "audit-review"},
        json=payload(service),
    ).status_code == 403


def test_application_review_rejects_self_and_mismatched_package_digest() -> None:
    service = Service()
    path = "/v1/application-packages/package-1/review"
    self_review = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer self", "Idempotency-Key": "self-review"},
        json=payload(service),
    )
    assert self_review.status_code == 422
    wrong = payload(service)
    wrong["package_sha256"] = "f" * 64
    mismatch = call(
        service,
        "POST",
        path,
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "wrong-review"},
        json=wrong,
    )
    assert mismatch.status_code == 422


def test_review_document_download_is_limited_to_exact_package_members() -> None:
    service = Service()
    base = "/v1/application-packages/package-1/review/documents"
    unrelated = call(
        service,
        "GET",
        f"{base}/unrelated/content",
        headers={"Authorization": "Bearer reviewer"},
    )
    assert unrelated.status_code == 404
    operator = call(
        service,
        "GET",
        f"{base}/application-document/content",
        headers={"Authorization": "Bearer operator"},
    )
    assert operator.status_code == 403
    exact = call(
        service,
        "GET",
        f"{base}/application-document/content",
        headers={"Authorization": "Bearer reviewer"},
    )
    assert exact.status_code == 200
    assert exact.content == b"exact application bytes"
    assert exact.headers["x-content-type-options"] == "nosniff"
    service.corrupt_content = True
    mismatch = call(
        service,
        "GET",
        f"{base}/application-document/content",
        headers={"Authorization": "Bearer reviewer"},
    )
    assert mismatch.status_code == 422
