"""Создать только синтетический пример; это не инструмент подтверждения реальных кейсов."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from procurement.domain.cases import (
    CaseAssessment,
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
)
from procurement.domain.company import CompanyProfile, FinancialPolicy, GeographyPolicy
from procurement.domain.decisions import GateStatus, ScoreFactor, TenderRating
from procurement.domain.economics import (
    COST_FIELD_NAMES,
    CostBreakdown,
    DealEconomics,
    EconomicsScenario,
    ScenarioKind,
    ScenarioSet,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.quotes import Currency, Quote
from procurement.domain.tenders import (
    DeliveryAddress,
    DeliveryPlan,
    ProcedureMethod,
    ProcedureStage,
    ProcurementLaw,
    SubmissionWindow,
    TenderProcedure,
)


def build_example() -> ProcurementCase:
    """Данные целиком вымышлены, включая документы, ставки и результаты проверок."""
    source = Provenance(
        document_id="SYNTHETIC-paper-case-not-a-real-document",
        locator="synthetic scenario specification",
        extractor=Extractor.MANUAL,
    )
    profile = CompanyProfile(
        company_id="demo-company",
        version=1,
        identity={
            "name": "Синтетическая демо-компания — не реальный участник",
            "inn": "0000000000",
            "kpp": "000000000",
            "ogrn": "0000000000000",
            "legal_form": "Синтетическое ООО",
        },
        business_description="Синтетическая поставка офисной бумаги",
        supplied_goods=("Офисная бумага А4, 500 листов",),
        geography=GeographyPolicy(regions=frozenset({"Татарстан"})),
        finance=FinancialPolicy(
            min_contract_amount=Decimal("500000"),
            max_contract_amount=Decimal("10000000"),
            min_margin=Decimal("0.15"),
            min_expected_profit=Decimal("150000"),
            max_contract_without_extra_approval=Decimal("5000000"),
            max_application_security=Decimal("300000"),
            max_performance_security=Decimal("1000000"),
            price_floor_margin=Decimal("0.10"),
        ),
        enabled_platforms=frozenset({"synthetic-platform"}),
        allowed_procedure_methods=frozenset({"electronic_auction"}),
    )
    tender = TenderProcedure(
        tender_id="synthetic-paper-001",
        customer_name="Синтетический заказчик",
        subject="ДЕМО: поставка офисной бумаги в Казань",
        law=ProcurementLaw.FZ_44,
        method=ProcedureMethod.ELECTRONIC_AUCTION,
        stage=ProcedureStage.SUBMISSION_OPEN,
        submission=SubmissionWindow(
            closes_at=datetime.fromisoformat("2026-09-30T12:00:00+03:00"),
            timezone="Europe/Moscow",
            provenance=source,
        ),
        delivery=DeliveryPlan(
            addresses=(
                DeliveryAddress(
                    region="Татарстан",
                    city="Казань",
                    address="Синтетический адрес доставки",
                    provenance=source,
                ),
            )
        ),
        notice_provenance=source,
    )
    quote = Quote(
        quote_id="synthetic-quote-001",
        version=1,
        company_id=profile.company_id,
        tender_id=tender.tender_id,
        supplier_id="synthetic-supplier",
        currency=Currency.RUB,
        amount_ex_vat=Decimal("900000"),
        nds_rate=Decimal("0"),
        issued_at=datetime.fromisoformat("2026-09-07T09:00:00+03:00"),
        valid_until=datetime.fromisoformat("2026-09-25T18:00:00+03:00"),
        source=source,
        covers_full_scope=True,
        availability_terms="ДЕМО: весь комплект в наличии",
        delivery_terms="ДЕМО: перевозка оплачивается отдельно, 70000 рублей",
        payment_terms="ДЕМО: 100% предоплата поставщику",
    )
    variants = []
    for kind, revenue, reserve in (
        (ScenarioKind.BASE, "1500000", "20000"),
        (ScenarioKind.REALISTIC, "1450000", "40000"),
        (ScenarioKind.CONSERVATIVE, "1350000", "70000"),
    ):
        costs = dict.fromkeys(COST_FIELD_NAMES, Decimal(0))
        costs.update(
            goods=Decimal("900000"),
            logistics=Decimal("70000"),
            finance=Decimal("25000"),
            taxes=Decimal("50000"),
            risk_reserve=Decimal(reserve),
        )
        variants.append(
            EconomicsScenario(
                kind=kind,
                economics=DealEconomics(
                    contract_revenue=Decimal(revenue),
                    costs=CostBreakdown(**costs),
                    nds_rate=Decimal("0"),
                ),
                assumptions=(
                    "Все суммы и нули заданы только для синтетического примера",
                    "Расходы введены вручную; ставка не является налоговой рекомендацией",
                ),
            )
        )
    case = ProcurementCase(
        case_id="synthetic-case-001",
        version=1,
        company_id=profile.company_id,
        profile=profile,
        tender=tender,
        nmck_ex_vat=Decimal("1500000"),
        nmck_source=source,
        selected_quote=quote,
        scenarios=ScenarioSet(scenarios=tuple(variants)),
        rating=TenderRating(
            score=85,
            factors=(ScoreFactor(name="demo", points=85, explanation="Синтетический рейтинг"),),
        ),
    )
    assessment = CaseAssessment(
        reviewer_id="synthetic-reviewer",
        assessed_at=datetime.fromisoformat("2026-09-08T10:00:00+03:00"),
        input_digest=case_input_digest(case),
        checks=tuple(
            GateCheck(
                kind=kind,
                status=GateStatus.PASS,
                reason="Синтетическая проверка для демонстрации; реального заключения нет",
                evidence=(source,),
            )
            for kind in GateKind
        ),
    )
    return case.model_copy(update={"assessment": assessment})


if __name__ == "__main__":
    Path(__file__).with_name("paper_case.json").write_text(
        build_example().model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
