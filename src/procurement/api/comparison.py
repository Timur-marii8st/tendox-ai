"""Сравнение сохранённых exact кейсов с выбранной immutable версией профиля."""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from procurement.access import AccessRole
from procurement.api.contracts import Principal
from procurement.comparison.notices import (
    NoticeCompareCommand,
    NoticeComparisonReport,
    compare_notices,
)
from procurement.comparison.profile_adapter import fact
from procurement.comparison.service import (
    CompareCommand,
    ComparisonReport,
    SelectedCase,
    compare_selected,
)
from procurement.domain.cases import case_input_digest
from procurement.storage.company_profile import (
    ProfileEvidenceInvalid,
    ProfileNotFound,
    read_profile,
    read_selection,
)
from procurement.storage.eis_mixed_comparison import MixedComparisonRequest, get_mixed_comparison
from procurement.storage.repository import PostgresStorage


class SavedCompareCommand(CompareCommand):
    selection_id: UUID


def comparison_router(
    storage: PostgresStorage | None, authenticate: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(prefix="/v1/procurement-comparison", tags=["procurement-comparison"])

    async def reader(
        response: Response, principal: Annotated[Principal, Depends(authenticate)]
    ) -> Principal:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role not in (AccessRole.OPERATOR, AccessRole.AUDITOR):
            raise HTTPException(403, "comparison_role_required")
        return principal

    def available() -> PostgresStorage:
        if storage is None:
            raise HTTPException(503, "comparison_storage_unavailable")
        return storage

    def catalog(company: str, cursor: str | None = None) -> dict[str, Any]:
        repository = available()
        selection = read_selection(repository, company)
        snapshot = read_profile(repository, company, selection.profile_ref.version)
        if snapshot.snapshot_sha256 != selection.profile_ref.snapshot_sha256:
            raise ProfileEvidenceInvalid("selection_snapshot_mismatch")
        profile = snapshot.model_dump(mode="json")
        page = repository.list_cases(company, limit=200, cursor=cursor)
        return {
            "mode": "SAVED_CASES",
            "company_id": company,
            "selection_id": selection.selection_id,
            "compared_at": datetime.now(UTC).isoformat(),
            "profiles": [
                {
                    "ref": {
                        "version": snapshot.version,
                        "snapshot_sha256": snapshot.snapshot_sha256,
                    },
                    "name": fact(profile, "identity.name")["value"] or "Название UNKNOWN",
                    "created_at": snapshot.created_at.isoformat(),
                }
            ],
            "cases": [
                {
                    "ref": {
                        "case_id": case.case_id,
                        "version": case.version,
                        "input_sha256": case_input_digest(case),
                    },
                    "subject": case.tender.subject,
                    "nmck_ex_vat": str(case.nmck_ex_vat),
                    "deadline": case.tender.submission.closes_at.isoformat(),
                }
                for case in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    def compare(company: str, command: SavedCompareCommand) -> ComparisonReport:
        repository = available()
        selection = read_selection(repository, company, str(command.selection_id))
        if (selection.profile_ref.version, selection.profile_ref.snapshot_sha256) != (
            command.profile_ref.version,
            command.profile_ref.snapshot_sha256,
        ):
            raise ValueError("selection_ref_mismatch")
        snapshot = read_profile(repository, company, command.profile_ref.version)
        if snapshot.snapshot_sha256 != command.profile_ref.snapshot_sha256:
            raise ValueError("profile_ref_mismatch")
        selected = []
        for ref in command.case_refs:
            case = repository.get_case(company, ref.case_id, ref.version)
            if case is None or case.company_id != company:
                raise ProfileNotFound("case_not_found")
            if case_input_digest(case) != ref.input_sha256:
                raise ValueError("case_ref_mismatch")
            # Нет отдельного verified exact-case ledger: прибыль остаётся UNKNOWN.
            selected.append(SelectedCase(case))
        report = compare_selected(
            company, snapshot.model_dump(mode="json"), tuple(selected), at=datetime.now(UTC)
        )
        return report.model_copy(
            update={
                "persistence": "EPHEMERAL",
                "comparison_id": "comparison-" + report.input_sha256,
            }
        )

    async def execute(function: Callable[..., Any], *args: Any) -> Any:
        try:
            return await to_thread.run_sync(partial(function, *args))
        except LookupError as error:
            raise HTTPException(404, "selected_version_not_found") from error
        except (ProfileEvidenceInvalid, ValueError) as error:
            raise HTTPException(409, "selected_evidence_inconsistent") from error

    @router.get("/catalog")
    async def get_catalog(
        principal: Annotated[Principal, Depends(reader)],
        cursor: str | None = Query(default=None, max_length=2000),
    ) -> dict[str, Any]:
        return await execute(catalog, principal.company_id, cursor)

    @router.post("", response_model=ComparisonReport)
    async def post_comparison(
        command: SavedCompareCommand, principal: Annotated[Principal, Depends(reader)]
    ) -> ComparisonReport:
        if principal.access_role != AccessRole.OPERATOR:
            raise HTTPException(403, "comparison_requires_operator")
        return await execute(compare, principal.company_id, command)

    def notice_comparison(company: str, command: NoticeCompareCommand) -> NoticeComparisonReport:
        repository = available()
        selection = read_selection(repository, company, str(command.selection_id))
        if (selection.profile_ref.version, selection.profile_ref.snapshot_sha256) != (
            command.profile_ref.version,
            command.profile_ref.snapshot_sha256,
        ):
            raise ValueError("selection_ref_mismatch")
        snapshot = read_profile(repository, company, command.profile_ref.version)
        source = get_mixed_comparison(
            repository, company, MixedComparisonRequest(notices=command.notices)
        )
        return compare_notices(company, snapshot.model_dump(mode="json"), command, source)

    @router.post("/notices", response_model=NoticeComparisonReport)
    async def post_notice_comparison(
        command: NoticeCompareCommand, principal: Annotated[Principal, Depends(reader)]
    ) -> NoticeComparisonReport:
        if principal.access_role != AccessRole.OPERATOR:
            raise HTTPException(403, "comparison_requires_operator")
        return await execute(notice_comparison, principal.company_id, command)

    return router
