"""Shortlist не превращает публичные карточки в подходящие КП."""

import asyncio
import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.api.postgres import PostgresCaseService
from procurement.documents import (
    RequirementEntryDisposition,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetRecord,
    build_case_requirement_set_binding,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
)
from procurement.domain.compliance import Verdict
from procurement.domain.offers import Attribute
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement
from procurement.domain.server_bom import BomPart, PartKind, ServerBom
from procurement.domain.sourcing import (
    LeadSourceKind,
    LeadStatus,
    ServerLead,
    ServerShortlist,
    SourcingRunRecord,
    SourcingRunStatus,
    SourcingSourceStatus,
    shortlist_server_leads,
)
from procurement.sources.catalog_search import CatalogSourceAttempt


def source(document: str, locator: str) -> Provenance:
    return Provenance(document_id=document, locator=locator, extractor=Extractor.MANUAL)


def cpu_requirement() -> Requirement:
    return Requirement(
        property="cpu_cores_each",
        operator=Operator.GE,
        value=Decimal(16),
        unit="шт",
        mandatory=True,
        raw_text="Ядер каждого CPU не менее 16",
        provenance=source("ТЗ", "строка 48"),
    )


def lead(lead_id: str, cores: int | None = None, price: str | None = None) -> ServerLead:
    bom = None
    if cores is not None:
        bom = ServerBom(
            bom_id=f"bom-{lead_id}",
            source_sha256="b" * 64,
            source_provenance=source(f"bom-{lead_id}", "весь состав"),
            parts=(
                BomPart(
                    kind=PartKind.CPU,
                    sku=f"cpu-{cores}",
                    quantity=1,
                    provenance=source(f"bom-{lead_id}", "CPU"),
                    attributes=(
                        Attribute(
                            property="cpu_cores_each",
                            value=Decimal(cores),
                            unit="шт",
                            provenance=source("datasheet", "cores"),
                        ),
                    ),
                ),
            ),
        )
    return ServerLead(
        lead_id=lead_id,
        supplier="Поставщик",
        product_name="Сервер",
        source_url="https://supplier.example/server",
        source_sha256="a" * 64,
        observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        price_rub=price,
        bom=bom,
    )


def test_known_mandatory_failure_excludes_cheap_lead() -> None:
    result = shortlist_server_leads(
        (lead("cheap", cores=12, price="100.00"), lead("unknown", price="200.00")),
        (cpu_requirement(),),
    )
    assert [entry.lead.lead_id for entry in result.rejected] == ["cheap"]
    assert result.rejected[0].status is LeadStatus.REJECTED
    assert [entry.lead.lead_id for entry in result.review_queue] == ["unknown"]
    assert result.review_queue[0].open_properties == ("cpu_cores_each",)


def test_known_partial_match_remains_review_queue_not_pass() -> None:
    result = shortlist_server_leads((lead("partial", cores=16),), (cpu_requirement(),))
    assert len(result.review_queue) == 1
    assert result.review_queue[0].status is LeadStatus.NEEDS_TECHNICAL_REVIEW
    assert result.review_queue[0].assessment is not None
    assert result.review_queue[0].assessment.verdict.value == "UNKNOWN"


def test_price_is_exact_and_not_a_quote() -> None:
    assert lead("x", price="123.45").price_rub == Decimal("123.45")
    with pytest.raises(ValidationError):
        lead("x", price=12.5)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ServerLead(
            lead_id="x",
            supplier="s",
            product_name="p",
            source_url="http://supplier.example/p",
            source_sha256="a" * 64,
            observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


def test_duplicate_leads_rejected() -> None:
    with pytest.raises(ValueError, match="lead_id"):
        shortlist_server_leads((lead("x"), lead("x")), (cpu_requirement(),))


def test_persisted_search_cannot_claim_technical_pass() -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    with pytest.raises(ValidationError, match="техническое соответствие"):
        SourcingRunRecord(
            company_id="tenant",
            run_id="run-1",
            case_id="case-1",
            case_version=1,
            query="DL360 Gen12",
            source_name="ServerMall",
            source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
            status=SourcingRunStatus.COMPLETED,
            source_sha256="a" * 64,
            source_byte_size=10,
            observed_at=now,
            shortlist=ServerShortlist(review_queue=(), rejected=()),
            technical_scope_status="PASS",
            technical_scope_reason="ложный допуск",
            created_at=now,
        )


def test_source_error_has_no_cards_or_unverified_snapshot() -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    record = SourcingRunRecord(
        company_id="tenant",
        run_id="run-1",
        case_id="case-1",
        case_version=1,
        query="DL360 Gen12",
        source_name="ServerMall",
        source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
        status=SourcingRunStatus.SOURCE_ERROR,
        observed_at=now,
        shortlist=ServerShortlist(review_queue=(), rejected=()),
        technical_scope_reason="Источник недоступен.",
        error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        created_at=now,
    )
    assert record.source_sha256 is None
    assert record.shortlist.review_queue == ()


def test_sourcing_service_uses_only_exact_bound_pass_set(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = cpu_requirement()
    proposal = build_reviewed_requirement_set_proposal(
        company_id="tenant",
        set_id="set-1",
        source_document_id="ТЗ",
        source_document_sha256="c" * 64,
        declared_scope="all rows",
        expected_entry_count=1,
        entries=(
            ReviewedRequirementEntry(
                ordinal=1,
                raw_name="Ядер каждого CPU",
                raw_value="Не менее 16",
                provenance=requirement.provenance,
                disposition=RequirementEntryDisposition.EXECUTABLE,
                requirement=requirement,
                review_note="checked",
            ),
        ),
        prepared_by="operator-a",
        prepared_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    decision = build_reviewed_requirement_set_decision(
        proposal,
        coverage_assessment=RequirementSetCoverageAssessment.CONFIRMED,
        normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
        status=Verdict.PASS,
        reason="checked",
        reviewed_by="reviewer-a",
        reviewed_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    binding = build_case_requirement_set_binding(
        proposal,
        decision,
        binding_id="binding-1",
        case_id="case-1",
        case_version=1,
        bound_by="operator-b",
        bound_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    content = b"exact catalog snapshot"
    exact_lead = ServerLead.model_validate(
        {
            **lead("known-fail", cores=12).model_dump(mode="python"),
            "source_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    attempt = CatalogSourceAttempt(
        source_name="ServerMall",
        source_kind=LeadSourceKind.SUPPLIER_CATALOG,
        source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
        media_type="text/html",
        status=SourcingSourceStatus.COMPLETED,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        leads=(exact_lead,),
    )
    monkeypatch.setattr(
        "procurement.api.postgres.fetch_server_catalog_sources",
        lambda query: (attempt,),
    )

    class Storage:
        stored: SourcingRunRecord | None = None

        def get_bound_requirement_set(self, company_id: str, case_id: str, version: int):
            assert (company_id, case_id, version) == ("tenant", "case-1", 1)
            return binding, ReviewedRequirementSetRecord(proposal=proposal, decision=decision)

        def store_sourcing_run(
            self,
            company_id: str,
            actor_id: str,
            record: SourcingRunRecord,
            source_content: bytes,
            **kwargs: object,
        ) -> SourcingRunRecord:
            assert company_id == "tenant"
            assert actor_id == "operator-b"
            assert hashlib.sha256(source_content).hexdigest() == record.source_sha256
            assert kwargs["source_contents"] == (content,)
            self.stored = record
            return record

    storage = Storage()
    result = asyncio.run(
        PostgresCaseService(storage).run_server_sourcing(  # type: ignore[arg-type]
            company_id="tenant",
            actor_id="operator-b",
            case_id="case-1",
            version=1,
            query="DL360 Gen12",
            idempotency_key="source-1",
            request_digest="d" * 64,
        )
    )
    assert [item.lead.lead_id for item in result.shortlist.rejected] == ["known-fail"]
    assert result.requirement_set_id == "set-1"
    assert result.requirement_set_binding_sha256 == binding.binding_sha256
    assert result.technical_scope_status is Verdict.UNKNOWN
    assert result.sources[0].source_sha256 == attempt.sha256


def test_official_manufacturer_lead_cannot_claim_price_or_exact_bom() -> None:
    now = datetime(2026, 9, 20, tzinfo=UTC)
    official = ServerLead(
        lead_id="official-hpe",
        supplier="HPE",
        manufacturer="HPE",
        source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
        product_name="HPE ProLiant Compute DL360 Gen12",
        source_url="https://www.hpe.com/psnow/doc/a50006984enw",
        source_sha256="a" * 64,
        observed_at=now,
    )
    assert official.price_rub is None
    assert official.bom is None
    with pytest.raises(ValidationError, match="exact BOM"):
        ServerLead(
            lead_id="official-hpe",
            supplier="HPE",
            manufacturer="HPE",
            source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
            product_name="HPE ProLiant Compute DL360 Gen12",
            source_url="https://www.hpe.com/psnow/doc/a50006984enw",
            source_sha256="a" * 64,
            observed_at=now,
            price_rub=Decimal("1"),
        )
