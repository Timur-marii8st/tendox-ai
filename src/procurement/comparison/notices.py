"""Preliminary profile comparison of exact cached XML, without inventing cases."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from procurement.comparison.profile_adapter import digest, fact
from procurement.comparison.service import ComparisonCheck, ExactModel, ProfileRef, ProfileSource
from procurement.domain.company_profile_snapshot import CompanyProfileSnapshot
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_policy import deadline223
from procurement.storage.eis_mixed_comparison import (
    MixedComparisonRequest,
    MixedComparisonResult,
    MixedNoticeRef,
)


class NoticeCompareCommand(MixedComparisonRequest):
    selection_id: UUID
    profile_ref: ProfileRef


class NoticeComparisonRow(ExactModel):
    notice_ref: MixedNoticeRef
    subject: str
    overall_status: GateStatus
    checks: tuple[ComparisonCheck, ...]


class NoticeComparisonReport(ExactModel):
    schema_version: Literal["selected-profile-notice-comparison-v1"] = (
        "selected-profile-notice-comparison-v1"
    )
    comparison_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    persistence: Literal["EPHEMERAL"] = "EPHEMERAL"
    company_id: str
    selection_id: UUID
    profile_ref: ProfileRef
    profile_name: str
    profile_created_at: datetime
    compared_at: datetime
    input_sha256: str
    comparison_id: str
    rows: tuple[NoticeComparisonRow, ...]
    source: MixedComparisonResult


def _declarations(snapshot: dict[str, Any], paths: tuple[str, ...]) -> str:
    labels = {
        "supplied_goods": "Товары",
        "performed_works": "Работы",
        "provided_services": "Услуги",
        "okved": "ОКВЭД",
        "geography.all_russia": "Вся Россия",
        "geography.regions": "Регионы",
        "geography.cities": "Города",
        "geography.federal_districts": "Федеральные округа",
        "geography.max_distance_km": "Предельное расстояние, км",
    }
    result = []
    for path in paths:
        entry = fact(snapshot, path)
        value = entry["value"]
        if entry["knowledge"] != "KNOWN":
            text = "не указано"
        elif isinstance(value, bool):
            text = "Да" if value else "Нет"
        elif isinstance(value, list):
            text = ", ".join(str(item) for item in value) if value else "не заявлены"
        else:
            text = str(value)
        result.append(f"{labels[path]}: {text}")
    return "; ".join(result)


def compare_notices(
    company: str,
    snapshot: dict[str, Any],
    command: NoticeCompareCommand,
    source: MixedComparisonResult,
) -> NoticeComparisonReport:
    """Keep source availability distinct from supplier eligibility; never rank profit."""
    CompanyProfileSnapshot.model_validate(snapshot)
    if snapshot["company_id"] != company or (snapshot["version"], snapshot["snapshot_sha256"]) != (
        command.profile_ref.version,
        command.profile_ref.snapshot_sha256,
    ):
        raise ValueError("profile_ref_mismatch")
    if len(source.rows) != len(command.notices):
        raise ValueError("notice_reference_mismatch")

    activity_paths = ("supplied_goods", "performed_works", "provided_services", "okved")
    geo_paths = tuple(
        "geography." + name
        for name in ("all_russia", "regions", "cities", "federal_districts", "max_distance_km")
    )
    finance_paths = tuple(path for path in snapshot["facts"] if path.startswith("finance."))
    rows = []
    for ref, row in zip(command.notices, source.rows, strict=True):
        if row.law == "223":
            actual = (row.notice.purchase_number, row.notice.version_number, row.notice.xml_sha256)
            subject = row.notice.title.value or "Предмет UNKNOWN"
            deadline = deadline223(row.notice)
            sources = (*row.notice.identity_provenance, deadline.provenance)
            blocked = (deadline.value is not None and deadline.value <= source.checked_at) or (
                row.cancellation_state is not None
                and row.cancellation_state.application_status == "FAIL"
            )
            if row.cancellation_state is not None:
                # Cancellation evidence is retained in source; identity ties this check to XML.
                sources += tuple(
                    e.purchase_number_provenance for e in row.cancellation_state.events
                )
        else:
            evidence = row.evidence
            actual = (
                evidence.notice.purchase_number,
                evidence.notice.version_number,
                evidence.notice.notice_xml_sha256,
            )
            subject = evidence.title
            sources = (
                Provenance(
                    document_id=ref.notice_xml_sha256,
                    locator=evidence.source_member,
                    extractor=Extractor.API,
                ),
            )
            if row.deadline_provenance:
                sources += (row.deadline_provenance,)
            blocked = evidence.application_status == "FAIL"
        if ref.law != row.law or actual != (
            ref.purchase_number,
            ref.version_number,
            ref.notice_xml_sha256,
        ):
            raise ValueError("notice_reference_mismatch")
        checks = []

        def add(
            key: str,
            label: str,
            reason: str,
            *,
            fail: bool = False,
            paths: tuple[str, ...] = (),
            target: list[ComparisonCheck] = checks,
            evidence_sources: tuple[Provenance, ...] = sources,
        ) -> None:
            target.append(
                ComparisonCheck(
                    check_id=key,
                    label=label,
                    status=GateStatus.FAIL if fail else GateStatus.UNKNOWN,
                    reason_code="SOURCE_BLOCKER" if fail else "REVIEW_REQUIRED",
                    reason=reason,
                    profile_field_paths=paths,
                    profile_sources=tuple(
                        ProfileSource.model_validate(s)
                        for p in paths
                        for s in fact(snapshot, p)["sources"]
                    ),
                    case_sources=evidence_sources,
                    missing=() if fail else (reason,),
                )
            )

        add(
            "submission",
            "Подача заявки",
            "Истёкший срок или подтверждённая отмена."
            if blocked
            else "Актуальная возможность подачи и часовой пояс требуют проверки.",
            fail=blocked,
        )
        add(
            "source_readiness",
            "Состояние источника",
            "; ".join(row.blocking_reasons) or "Полнота и актуальность ЕИС UNKNOWN.",
            fail=bool(row.blocking_reasons),
        )
        for key, label, paths, reason in (
            (
                "activity",
                "Деятельность",
                activity_paths,
                "Нет проверенного сопоставления деятельности с предметом закупки. "
                + "Заявлено в профиле: "
                + _declarations(snapshot, activity_paths),
            ),
            (
                "geography",
                "География",
                geo_paths,
                "Место исполнения и ограничения профиля требуют проверки. "
                + "Заявлено в профиле: "
                + _declarations(snapshot, geo_paths),
            ),
            (
                "amount",
                "Цена",
                ("finance.min_contract_amount", "finance.max_contract_amount"),
                "Цена источника не подтверждает сумму без НДС и сопоставимость лотов.",
            ),
            (
                "method",
                "Способ закупки",
                ("allowed_procedure_methods",),
                "Способ и применимость ограничений профиля требуют проверки.",
            ),
            (
                "requirements",
                "Требования",
                (),
                "Фрагменты документов не являются утверждёнными требованиями.",
            ),
            (
                "finance",
                "Финансы",
                finance_paths,
                "Условия оплаты, налоги и оборотные средства не подтверждены.",
            ),
            (
                "economics",
                "Прибыль",
                (),
                "Нужны полное действительное КП и три сценария экономики.",
            ),
        ):
            add(key, label, reason, paths=paths)
        rows.append(
            NoticeComparisonRow(
                notice_ref=ref,
                subject=subject,
                overall_status=GateStatus.FAIL
                if any(c.status == GateStatus.FAIL for c in checks)
                else GateStatus.UNKNOWN,
                checks=tuple(checks),
            )
        )
    sha = digest(
        {
            "company": company,
            "command": command.model_dump(mode="json"),
            "source": source.model_dump(mode="json"),
        }
    )
    return NoticeComparisonReport(
        company_id=company,
        selection_id=command.selection_id,
        profile_ref=command.profile_ref,
        profile_name=fact(snapshot, "identity.name")["value"] or "Название UNKNOWN",
        profile_created_at=snapshot["created_at"],
        compared_at=source.checked_at,
        input_sha256=sha,
        comparison_id="comparison-" + sha,
        rows=tuple(rows),
        source=source,
    )
