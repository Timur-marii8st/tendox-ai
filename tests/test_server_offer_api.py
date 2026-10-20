import asyncio
from datetime import UTC, datetime

import httpx

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Principal, ServerOfferConflict
from procurement.documents import (
    RequirementEntryDisposition,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetRecord,
    ServerOfferBomLineInput,
    ServerOfferBomScopeAssessment,
    ServerOfferCommercialAssessment,
    ServerOfferCommercialTermsInput,
    ServerOfferEvidenceKind,
    ServerOfferEvidenceRef,
    ServerOfferPartKind,
    ServerOfferRequirementDecision,
    ServerOfferReviewEvidence,
    ServerOfferReviewRecord,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
    build_server_offer_proposal,
    build_server_offer_review_decision,
)
from procurement.domain.compliance import Verdict
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


class _Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        role = {
            "operator": AccessRole.OPERATOR,
            "reviewer": AccessRole.COMPLETENESS_REVIEWER,
        }.get(credential)
        return None if role is None else Principal(
            company_id="tenant-a", actor_id=f"{credential}-a", access_role=role
        )


class _Service:
    def __init__(self) -> None:
        self.records = {}
        self.receipts = {}
        self.decisions = {}
        provenance = Provenance(
            document_id="tz-1", locator="table row 1", extractor=Extractor.MANUAL
        )
        proposal = build_reviewed_requirement_set_proposal(
            company_id="tenant-a",
            set_id="set-1",
            source_document_id="tz-1",
            source_document_sha256="d" * 64,
            declared_scope="all rows",
            expected_entry_count=1,
            entries=(
                ReviewedRequirementEntry(
                    ordinal=1,
                    raw_name="Chassis",
                    raw_value="configured",
                    provenance=provenance,
                    disposition=RequirementEntryDisposition.MANUAL_REVIEW_REQUIRED,
                    review_note="manual check",
                ),
            ),
            prepared_by="requirements-operator",
            prepared_at=NOW,
        )
        decision = build_reviewed_requirement_set_decision(
            proposal,
            coverage_assessment=RequirementSetCoverageAssessment.CONFIRMED,
            normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
            status=Verdict.PASS,
            reason="complete",
            reviewed_by="requirements-reviewer",
            reviewed_at=NOW,
        )
        self.requirement_set = ReviewedRequirementSetRecord(
            proposal=proposal, decision=decision
        )

    async def store_server_offer_proposal(self, **kwargs):
        key = kwargs["idempotency_key"]
        existing = self.receipts.get(key)
        if existing is not None:
            if existing[0] != kwargs["request_digest"]:
                raise ServerOfferConflict
            return existing[1]
        record = build_server_offer_proposal(
            company_id=kwargs["company_id"],
            offer_id=kwargs["offer_id"],
            case_id=kwargs["case_id"],
            case_version=kwargs["case_version"],
            requirement_set_binding_id=kwargs["requirement_set_binding_id"],
            requirement_set_binding_sha256=kwargs["requirement_set_binding_sha256"],
            sourcing_run_id=kwargs["sourcing_run_id"],
            lead_id=kwargs["lead_id"],
            lead_product_name="HPE DL360 Gen12",
            lead_product_url="https://example.com/hpe",
            lead_source_sha256="b" * 64,
            source_document_id=kwargs["source_document_id"],
            source_document_sha256=kwargs["source_document_sha256"],
            bom_lines=kwargs["bom_lines"],
            commercial_terms=kwargs["commercial_terms"],
            prepared_by=kwargs["actor_id"],
            prepared_at=NOW,
        )
        self.records[(kwargs["company_id"], record.offer_id)] = record
        self.receipts[key] = (kwargs["request_digest"], record)
        return record

    async def get_server_offer_proposal(self, *, company_id: str, offer_id: str):
        return self.records.get((company_id, offer_id))

    async def get_server_offer_review(self, *, company_id: str, offer_id: str):
        proposal = self.records.get((company_id, offer_id))
        if proposal is None:
            return None
        return ServerOfferReviewRecord(
            evidence=ServerOfferReviewEvidence(
                proposal=proposal, requirement_set=self.requirement_set
            ),
            decision=self.decisions.get((company_id, offer_id)),
        )

    async def decide_server_offer_proposal(self, **kwargs):
        record = await self.get_server_offer_review(
            company_id=kwargs["company_id"], offer_id=kwargs["offer_id"]
        )
        assert record is not None
        decision = build_server_offer_review_decision(
            record.evidence,
            requirement_decisions=kwargs["requirement_decisions"],
            bom_scope_assessment=kwargs["bom_scope_assessment"],
            commercial_terms_assessment=kwargs["commercial_terms_assessment"],
            reason=kwargs["reason"],
            reviewed_by=kwargs["reviewer_id"],
            reviewed_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
        self.decisions[(kwargs["company_id"], kwargs["offer_id"])] = decision
        return decision


def _call(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def payload() -> dict[str, object]:
    line = ServerOfferBomLineInput(
        ordinal=1,
        kind=ServerOfferPartKind.CHASSIS,
        manufacturer="HPE",
        sku="P-1",
        description="Exact configured chassis",
        quantity="1",
        unit="шт",
        line_total_ex_vat="1000.00",
        source_locator="page 1 row 1",
    )
    terms = ServerOfferCommercialTermsInput(
        quote_number="Q-1",
        supplier_id="supplier-1",
        supplier_name="Поставщик",
        amount_ex_vat="1000.00",
        nds_rate="0.20",
        issued_at=NOW,
        valid_until=datetime(2026, 10, 20, 12, tzinfo=UTC),
        covers_full_scope=True,
        availability_terms="В наличии",
        delivery_terms="10 дней",
        payment_terms="После поставки",
        source_locator="page 1 total",
    )
    return {
        "requirement_set_binding_id": "binding-1",
        "requirement_set_binding_sha256": "a" * 64,
        "sourcing_run_id": "run-1",
        "lead_id": "lead-1",
        "source_document_id": "quote-doc-1",
        "source_document_sha256": "c" * 64,
        "bom_lines": [line.model_dump(mode="json")],
        "commercial_terms": terms.model_dump(mode="json"),
    }


def test_operator_creates_and_reads_exact_pending_offer() -> None:
    app = create_app(_Service(), _Authenticator())
    created = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/server-offer-proposals",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "offer-1"},
        json=payload(),
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["technical_status"] == "UNKNOWN"
    assert proposal["review_status"] == "PENDING_REVIEW"
    assert proposal["bom_lines"][0]["sku"] == "P-1"

    loaded = _call(
        app,
        "GET",
        f"/v1/server-offer-proposals/{proposal['offer_id']}",
        headers={"Authorization": "Bearer operator"},
    )
    assert loaded.status_code == 200
    assert loaded.json()["proposal_sha256"] == proposal["proposal_sha256"]


def test_reviewer_cannot_create_offer_and_body_is_strict() -> None:
    app = create_app(_Service(), _Authenticator())
    denied = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/server-offer-proposals",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "offer-denied"},
        json=payload(),
    )
    assert denied.status_code == 403

    invalid_payload = payload() | {"technical_status": "PASS"}
    invalid = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/server-offer-proposals",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "offer-invalid"},
        json=invalid_payload,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_server_offer"


def test_reviewer_sees_exact_evidence_and_server_derives_decision() -> None:
    app = create_app(_Service(), _Authenticator())
    created = _call(
        app,
        "POST",
        "/v1/cases/case-1/versions/2/server-offer-proposals",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "offer-review"},
        json=payload(),
    ).json()
    offer_id = created["offer_id"]
    review = _call(
        app,
        "GET",
        f"/v1/server-offer-proposals/{offer_id}/review",
        headers={"Authorization": "Bearer reviewer"},
    )
    assert review.status_code == 200
    assert review.json()["evidence"]["proposal"]["proposal_sha256"] == created["proposal_sha256"]

    decision = _call(
        app,
        "POST",
        f"/v1/server-offer-proposals/{offer_id}/review-decision",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "decision-1"},
        json={
            "proposal_sha256": created["proposal_sha256"],
            "requirement_decisions": [
                ServerOfferRequirementDecision(
                    requirement_ordinal=1,
                    status=Verdict.PASS,
                    reason="BOM confirms chassis",
                    evidence=(
                        ServerOfferEvidenceRef(
                            kind=ServerOfferEvidenceKind.BOM_LINE, bom_line_ordinal=1
                        ),
                    ),
                ).model_dump(mode="json")
            ],
            "bom_scope_assessment": ServerOfferBomScopeAssessment.CONFIRMED_COMPLETE,
            "commercial_terms_assessment": ServerOfferCommercialAssessment.CONFIRMED,
            "reason": "all rows and quote checked",
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "PASS"
    assert decision.json()["quote_gate_status"] == "PASS"


def test_offer_review_is_reviewer_only_and_rejects_caller_status() -> None:
    app = create_app(_Service(), _Authenticator())
    denied = _call(
        app,
        "GET",
        "/v1/server-offer-proposals/missing/review",
        headers={"Authorization": "Bearer operator"},
    )
    assert denied.status_code == 403
    invalid = _call(
        app,
        "POST",
        "/v1/server-offer-proposals/missing/review-decision",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "invalid-review"},
        json={
            "proposal_sha256": "a" * 64,
            "requirement_decisions": [],
            "bom_scope_assessment": "UNRESOLVED",
            "commercial_terms_assessment": "UNRESOLVED",
            "reason": "unknown",
            "status": "PASS",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_server_offer_review"
