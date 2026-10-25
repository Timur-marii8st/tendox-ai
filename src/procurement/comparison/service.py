"""Детерминированное сравнение 2–5 кейсов с точной версией профиля."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.comparison.profile_adapter import (
    aware,
    complete_domain_profile,
    digest,
    fact,
    validate_example_snapshot,
)
from procurement.domain.cases import GateKind, ProcurementCase, case_input_digest
from procurement.domain.decisions import GateStatus
from procurement.domain.economics import ScenarioKind
from procurement.domain.provenance import Provenance

POLICY_VERSION = "selected-company-comparison-v1/Europe-Moscow"


class ExactModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProfileRef(ExactModel):
    version: int = Field(ge=1, strict=True)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseRef(ExactModel):
    case_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1, strict=True)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompareCommand(ExactModel):
    profile_ref: ProfileRef
    case_refs: tuple[CaseRef, ...] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def _distinct_cases(self) -> CompareCommand:
        if len({ref.case_id for ref in self.case_refs}) != len(self.case_refs):
            raise ValueError("выберите разные закупки")
        return self


class ProfileSource(ExactModel):
    company_id: str | None = None
    provenance: Provenance
    kind: Literal["manual_declaration", "retained_document", "official_document"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: datetime
    recorded_by: str = Field(min_length=1)
    source_url: str | None


class ComparisonCheck(ExactModel):
    check_id: str
    label: str
    mandatory: bool = True
    status: GateStatus
    reason_code: str
    reason: str
    profile_field_paths: tuple[str, ...]
    profile_sources: tuple[ProfileSource, ...]
    case_sources: tuple[Provenance, ...]
    missing: tuple[str, ...]

    @model_validator(mode="after")
    def _evidence_required(self) -> ComparisonCheck:
        if self.status != GateStatus.UNKNOWN and not (self.profile_sources or self.case_sources):
            raise ValueError("результат требует evidence")
        if self.status == GateStatus.UNKNOWN and not self.missing:
            raise ValueError("UNKNOWN должен объяснять недостающие данные")
        return self


class ScenarioComparison(ExactModel):
    kind: ScenarioKind
    revenue_ex_vat: Decimal
    costs_ex_vat: Decimal
    profit_ex_vat: Decimal
    nds_rate: Decimal
    taxes: Decimal
    assumptions: tuple[str, ...]
    sources: tuple[Provenance, ...]


class CaseComparison(ExactModel):
    case_ref: CaseRef
    case_snapshot_sha256: str
    subject: str
    deadline: datetime
    nmck_ex_vat: Decimal
    overall_status: GateStatus
    checks: tuple[ComparisonCheck, ...]
    economics: tuple[ScenarioComparison, ...]


class ComparisonReport(ExactModel):
    schema_version: Literal["selected-company-comparison-v1"] = "selected-company-comparison-v1"
    company_id: str
    comparison_id: str
    profile_ref: ProfileRef
    compared_at: datetime
    comparison_policy_version: str = POLICY_VERSION
    input_sha256: str
    profile_name: str
    profile_created_at: datetime
    persistence: Literal["LOCAL_DEMO_EPHEMERAL", "EPHEMERAL"] = "LOCAL_DEMO_EPHEMERAL"
    audit_event_id: None = None
    rows: tuple[CaseComparison, ...]


@dataclass(frozen=True)
class SelectedCase:
    """Существующий кейс и подтверждение точной таблицы сценариев от адаптера."""

    case: ProcurementCase
    economics_input_sha256: str | None = None
    economics_sources: tuple[Provenance, ...] = ()


def _checks(snapshot: dict[str, Any], selected: SelectedCase, at: datetime) -> CaseComparison:
    case = ProcurementCase.model_validate(selected.case.model_dump(mode="python"))
    checks: list[ComparisonCheck] = []

    def add(
        key: str,
        label: str,
        status: GateStatus,
        code: str,
        reason: str,
        paths: tuple[str, ...] = (),
        sources: tuple[Provenance, ...] = (),
        missing: tuple[str, ...] = (),
    ) -> None:
        checks.append(
            ComparisonCheck(
                check_id=key,
                label=label,
                status=status,
                reason_code=code,
                reason=reason,
                profile_field_paths=paths,
                profile_sources=tuple(
                    ProfileSource.model_validate(source)
                    for path in paths
                    for source in fact(snapshot, path)["sources"]
                ),
                case_sources=sources,
                missing=missing,
            )
        )

    # Название/ОКВЭД не доказывают способность исполнить контракт.
    goods = fact(snapshot, "supplied_goods")
    declared_goods = (
        ", ".join(goods["value"]) or "не заявлены" if (goods["knowledge"] == "KNOWN") else "UNKNOWN"
    )
    add(
        "activity",
        "Деятельность",
        GateStatus.UNKNOWN,
        "MAPPING_NOT_REVIEWED",
        "Нужно проверенное сопоставление предмета закупки с товарами, работами и услугами. "
        f"Заявленные товары: {declared_goods}. "
        "Совпадение текста или ОКВЭД не подтверждает исполнение.",
        ("supplied_goods", "performed_works", "provided_services", "okved"),
        (case.tender.notice_provenance,),
        ("проверенное сопоставление деятельности",),
    )

    geo_paths = tuple(
        "geography." + name
        for name in ("all_russia", "regions", "cities", "federal_districts", "max_distance_km")
    )
    geo = {path.split(".")[1]: fact(snapshot, path) for path in geo_paths}
    addresses = case.tender.delivery.addresses
    sources = tuple(address.provenance for address in addresses)
    all_russia = geo["all_russia"]
    regions = geo["regions"]
    if (all_russia["knowledge"] == "KNOWN" and all_russia["value"] is True) or (
        regions["knowledge"] == "KNOWN"
        and all(address.region in regions["value"] for address in addresses)
    ):
        geo_status = GateStatus.PASS
    elif (
        all(
            geo[key]["knowledge"] == "KNOWN"
            for key in ("all_russia", "regions", "cities", "federal_districts")
        )
        and not geo["cities"]["value"]
        and not geo["federal_districts"]["value"]
    ):
        geo_status = GateStatus.FAIL
    else:
        geo_status = GateStatus.UNKNOWN
    if "critical_settings_status" in snapshot:
        geo_status = GateStatus.UNKNOWN
    add(
        "geography",
        "Территория",
        geo_status,
        "DECLARED_TERRITORY",
        f"Адреса: {', '.join(address.region + ' / ' + address.city for address in addresses)}. "
        + {
            GateStatus.PASS: "Входят в заявленную территорию; маршрут и доставка не проверены.",
            GateStatus.FAIL: "Как минимум один регион вне явно разрешённой территории.",
            GateStatus.UNKNOWN: (
                "Заявленный интерес поиска не подтверждает логистику или запрет территории."
            ),
        }[geo_status],
        geo_paths,
        sources,
        ("точная география и привязка города/округа",) if geo_status == GateStatus.UNKNOWN else (),
    )
    add(
        "distance",
        "Расстояние",
        GateStatus.UNKNOWN,
        "ROUTE_NOT_KNOWN",
        "Выполнимость маршрута не подтверждена: нет исходной точки и расчёта расстояния.",
        ("geography.max_distance_km",),
        sources,
        ("исходная точка и подтверждённый маршрут",),
    )

    open_now = case.tender.accepts_applications_at(at)
    add(
        "submission",
        "Срок подачи",
        GateStatus.PASS if open_now else GateStatus.FAIL,
        "SUBMISSION_OPEN" if open_now else "SUBMISSION_UNAVAILABLE",
        f"Срок: {case.tender.submission.closes_at.isoformat()}; стадия: {case.tender.stage.value}. "
        + (
            "По сохранённой версии срок ещё не истёк и стадия допускает подачу. "
            "Свежая проверка ЕИС не выполнялась."
            if open_now
            else "Срок истёк или стадия не допускает подачу."
        ),
        sources=(case.tender.submission.provenance, case.tender.notice_provenance),
    )
    add(
        "execution",
        "Возможность исполнения",
        GateStatus.UNKNOWN,
        "EXECUTION_NOT_PROVEN",
        "Открытый срок подачи не доказывает исполнение: нет проверенного срока поставки, "
        "производственного плана и ресурсов компании.",
        sources=sources,
        missing=("срок исполнения", "ресурсы, производство и логистический план"),
    )

    amount_paths = ("finance.min_contract_amount", "finance.max_contract_amount")
    amount_facts = [fact(snapshot, path) for path in amount_paths]
    missing: tuple[str, ...]
    if all(leaf["knowledge"] == "KNOWN" for leaf in amount_facts):
        low, high = (Decimal(leaf["value"]) for leaf in amount_facts)
        status = GateStatus.PASS if low <= case.nmck_ex_vat <= high else GateStatus.FAIL
        reason = f"НМЦК {case.nmck_ex_vat} RUB без НДС; лимиты {low}–{high}. "
        reason += "Проверен только диапазон суммы, это не выручка и не прибыль."
        missing = ()
    else:
        status, reason = GateStatus.UNKNOWN, "Неизвестны финансовые лимиты профиля."
        missing = tuple(
            path
            for path, leaf in zip(amount_paths, amount_facts, strict=True)
            if leaf["knowledge"] == "UNKNOWN"
        )
    add(
        "amount",
        "Финансовый диапазон",
        status,
        "AMOUNT_RANGE",
        reason,
        amount_paths,
        (case.nmck_source,),
        missing,
    )
    methods = fact(snapshot, "allowed_procedure_methods")
    method_status = (
        GateStatus.UNKNOWN
        if methods["knowledge"] != "KNOWN"
        else (GateStatus.PASS if case.tender.method.value in methods["value"] else GateStatus.FAIL)
    )
    add(
        "method",
        "Способ закупки",
        method_status,
        "ALLOWED_METHOD",
        f"Способ: {case.tender.method.value}; разрешённые способы: {methods['value']}. "
        "Проверяется явный выбор профиля, а не юридический допуск.",
        ("allowed_procedure_methods",),
        (case.tender.notice_provenance,),
        ("allowed_procedure_methods",) if method_status == GateStatus.UNKNOWN else (),
    )
    for key, label, path in (
        ("application_security", "Обеспечение заявки", "finance.max_application_security"),
        ("performance_security", "Обеспечение исполнения", "finance.max_performance_security"),
        (
            "extra_approval",
            "Внутреннее согласование суммы",
            "finance.max_contract_without_extra_approval",
        ),
    ):
        leaf = fact(snapshot, path)
        if key == "extra_approval" and leaf["knowledge"] == "KNOWN":
            needed = case.nmck_ex_vat > Decimal(leaf["value"])
            add(
                key,
                label,
                GateStatus.UNKNOWN if needed else GateStatus.PASS,
                "APPROVAL_REQUIRED" if needed else "WITHIN_APPROVAL_LIMIT",
                f"Лимит {leaf['value']} RUB без НДС. "
                + (
                    "Нужно отдельное подтверждение владельца."
                    if needed
                    else "Сумма в лимите; внешнее действие требует exact-payload approval."
                ),
                (path,),
                (case.nmck_source,),
                ("подтверждение владельца",) if needed else (),
            )
        else:
            add(
                key,
                label,
                GateStatus.UNKNOWN,
                "CASE_FIELD_MISSING",
                f"Лимит профиля: {leaf['value'] if leaf['knowledge'] == 'KNOWN' else 'UNKNOWN'}. "
                "Сумма/условия и источник на стороне кейса отсутствуют. "
                "Обеспечение не приравнивается к расходу.",
                (path,),
                missing=("сумма и условия обеспечения" if key != "extra_approval" else path,),
            )

    domain_profile = complete_domain_profile(snapshot)
    assessment = case.assessment
    valid_assessment = (
        domain_profile == case.profile
        and assessment is not None
        and assessment.input_digest == case_input_digest(case)
        and assessment.assessed_at <= at
        and (case.selected_quote is None or assessment.assessed_at >= case.selected_quote.issued_at)
    )
    gate_labels = {
        GateKind.LEGAL: "Правовые условия",
        GateKind.PARTICIPANT: "Требования к участнику",
        GateKind.TECHNICAL: "Технические требования",
        GateKind.DOCUMENT: "Документы заявки",
    }
    for kind, gate_label in gate_labels.items():
        gate = (
            next((gate for gate in assessment.checks if gate.kind == kind), None)
            if assessment
            else None
        )
        status = gate.status if valid_assessment and gate else GateStatus.UNKNOWN
        add(
            "mandatory_" + kind.value,
            gate_label,
            status,
            "RETAINED_EXACT_ASSESSMENT"
            if valid_assessment and gate
            else "ASSESSMENT_MISSING_OR_STALE",
            gate.reason
            if valid_assessment and gate
            else "Нет актуальной ручной проверки точных входов и выбранной версии профиля.",
            sources=gate.evidence if gate else (),
            missing=("актуальная проверка " + kind.value,) if status == GateStatus.UNKNOWN else (),
        )
    add(
        "policy",
        "Площадки, субподряд и запреты",
        GateStatus.UNKNOWN,
        "PREDICATE_UNSUPPORTED",
        "Нет platform_id и фактов субподряда в кейсе; condition запретов не исполняется как код. "
        "Применимость правил и полный охват обязательных условий не подтверждены.",
        ("enabled_platforms", "subcontracting_allowed", "prohibitions"),
        missing=("площадка", "условия субподряда", "применимость и полнота правил"),
    )
    add(
        "unsupported_finance",
        "Оплата, налоги и оборотные средства",
        GateStatus.UNKNOWN,
        "UNSUPPORTED_FIELD",
        "В SnapshotV1 нет налоговой политики, аванса/отсрочки, "
        "оборотных средств и лицензий. Эти условия требуют отдельной проверки.",
        missing=("налоговая политика", "аванс/отсрочка", "оборотные средства", "лицензии"),
    )

    quote = case.selected_quote
    scenarios = case.scenarios
    economics: list[ScenarioComparison] = []
    sufficient = (
        quote is not None
        and quote.is_complete
        and quote.is_valid_at(at)
        and scenarios is not None
        and scenarios.is_complete
        and selected.economics_sources
        and selected.economics_input_sha256 == case_input_digest(case)
    )
    if sufficient:
        assert scenarios is not None and quote is not None
        for scenario in scenarios.scenarios:
            values = scenario.economics
            assert values.nds_rate is not None
            economics.append(
                ScenarioComparison(
                    kind=scenario.kind,
                    revenue_ex_vat=values.contract_revenue,
                    costs_ex_vat=values.costs.all_in,
                    profit_ex_vat=values.gross_profit,
                    nds_rate=values.nds_rate,
                    taxes=values.costs.taxes,
                    assumptions=scenario.assumptions,
                    sources=selected.economics_sources,
                )
            )
        finance_paths = (
            "finance.min_margin",
            "finance.min_expected_profit",
            "finance.min_contract_amount",
            "finance.max_contract_amount",
        )
        finance_facts = [fact(snapshot, path) for path in finance_paths]
        realistic = scenarios.get(ScenarioKind.REALISTIC)
        missing_economics: tuple[str, ...]
        if all(leaf["knowledge"] == "KNOWN" for leaf in finance_facts):
            min_margin, min_profit, min_amount, max_amount = (
                Decimal(leaf["value"]) for leaf in finance_facts
            )
            economics_status = (
                GateStatus.PASS
                if (
                    realistic.gross_profit >= min_profit
                    and realistic.gross_profit / realistic.contract_revenue >= min_margin
                    and min_amount <= realistic.contract_revenue <= max_amount
                )
                else GateStatus.FAIL
            )
            missing_economics = ()
            financial_reason = (
                f"Реалистичный прогноз: прибыль {realistic.gross_profit} RUB без НДС; "
                f"минимум {min_profit}; минимальная маржа (доля) {min_margin}. "
                f"Выручка {realistic.contract_revenue}; диапазон {min_amount}–{max_amount}. "
                + (
                    "Пороги выполнены. "
                    if economics_status == GateStatus.PASS
                    else "Порог прибыли, маржи или суммы контракта не выполнен. "
                )
            )
        else:
            economics_status = GateStatus.UNKNOWN
            missing_economics = tuple(finance_paths)
            financial_reason = "Пороги прибыли/маржи профиля UNKNOWN. "
        add(
            "economics",
            "Экономика",
            economics_status,
            "CONFIRMED_SCENARIOS",
            "Показаны три сохранённых сценария с полными расходами, выручкой, явными налогами "
            "и допущениями. "
            + financial_reason
            + "Это прогноз, а не рекомендация участия или ранжирование прибыльности.",
            finance_paths,
            (quote.source, *selected.economics_sources),
            missing_economics,
        )
    else:
        economic_missing: list[str] = []
        if quote is None:
            economic_missing.append("полное КП на весь объём")
        elif not quote.is_complete:
            economic_missing.append("полнота условий КП: объём, наличие, доставка, оплата и НДС")
        elif not quote.is_valid_at(at):
            economic_missing.append("действующее КП на момент сравнения")
        if scenarios is None:
            economic_missing.append("сценарии base, realistic и conservative")
        elif not scenarios.is_complete:
            for scenario in scenarios.scenarios:
                values = scenario.economics
                absent = set(values.costs._cost_field_names) - set(
                    values.costs.specified_cost_fields
                )
                if absent:
                    economic_missing.append(
                        f"{scenario.kind.value}: явные расходы {', '.join(sorted(absent))}"
                    )
                if values.nds_rate is None:
                    economic_missing.append(f"{scenario.kind.value}: ставка НДС")
        if not selected.economics_sources:
            economic_missing.append("источники выручки и всех статей расходов")
        if selected.economics_input_sha256 != case_input_digest(case):
            economic_missing.append("подтверждение сценарных сумм для точной версии кейса")
        add(
            "economics",
            "Экономика",
            GateStatus.UNKNOWN,
            "ECONOMICS_INCOMPLETE",
            "Экономика UNKNOWN. Не хватает: "
            + "; ".join(economic_missing)
            + ". Из одной НМЦК прибыль не рассчитывается.",
            sources=((quote.source,) if quote else ()) + selected.economics_sources,
            missing=tuple(economic_missing),
        )
    overall = (
        GateStatus.FAIL
        if any(check.mandatory and check.status == GateStatus.FAIL for check in checks)
        else GateStatus.UNKNOWN
        if any(check.mandatory and check.status == GateStatus.UNKNOWN for check in checks)
        else GateStatus.PASS
    )
    return CaseComparison(
        case_ref=CaseRef(
            case_id=case.case_id, version=case.version, input_sha256=case_input_digest(case)
        ),
        case_snapshot_sha256=digest(case.model_dump(mode="python")),
        subject=case.tender.subject,
        deadline=case.tender.submission.closes_at,
        nmck_ex_vat=case.nmck_ex_vat,
        overall_status=overall,
        checks=tuple(checks),
        economics=tuple(economics),
    )


def compare_selected(
    company_id: str, snapshot: dict[str, Any], selected: tuple[SelectedCase, ...], *, at: datetime
) -> ComparisonReport:
    """Сравнить неизменяемые входы на фиксированный aware момент без записи/I/O."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("comparison time requires timezone")
    at = at.astimezone(ZoneInfo("Europe/Moscow"))
    snapshot = validate_example_snapshot(snapshot, company_id)
    if aware(snapshot["effective_at"]) > at:
        raise ValueError("profile is not effective yet")
    refs = tuple(
        CaseRef(
            case_id=item.case.case_id,
            version=item.case.version,
            input_sha256=case_input_digest(item.case),
        )
        for item in selected
    )
    ref = ProfileRef(version=snapshot["version"], snapshot_sha256=snapshot["snapshot_sha256"])
    CompareCommand(profile_ref=ref, case_refs=refs)
    if any(item.case.company_id != company_id for item in selected):
        raise LookupError("case not found")
    rows = tuple(_checks(snapshot, item, at) for item in selected)
    input_hash = digest(
        {
            "company_id": company_id,
            "profile": snapshot,
            "compared_at": at,
            "policy": POLICY_VERSION,
            "cases": [
                {
                    "snapshot": item.case.model_dump(mode="python"),
                    "economics_input_sha256": item.economics_input_sha256,
                    "economics_sources": [
                        source.model_dump(mode="python") for source in item.economics_sources
                    ],
                }
                for item in selected
            ],
        }
    )
    name = fact(snapshot, "identity.name")
    return ComparisonReport(
        company_id=company_id,
        comparison_id="local-" + input_hash,
        input_sha256=input_hash,
        profile_ref=ref,
        compared_at=at,
        profile_name=name["value"] or "Название UNKNOWN",
        profile_created_at=aware(snapshot["created_at"]),
        rows=rows,
    )
