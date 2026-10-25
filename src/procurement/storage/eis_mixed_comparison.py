"""Read-only, law-preserving selected 44/223 comparison in one tenant snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_position_evidence import PositionLinkLead, position_links
from procurement.storage.eis_223_comparison import Comparison223Row, read_comparison223_row
from procurement.storage.eis_comparison import EisComparisonRow, comparison44_row
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_evidence_bridge import read_eis_evidence_bridge
from procurement.storage.models import eis_notice_versions

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


class MixedNoticeRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    law: Literal["44", "223"]
    purchase_number: str
    version_number: int = Field(ge=1)
    notice_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def law_bound_number(self) -> MixedNoticeRef:
        ref_type = NoticeDocumentRef if self.law == "44" else Notice223DocumentRef
        ref_type.model_validate(self.model_dump(exclude={"law"}))
        return self


class MixedComparisonRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    notices: tuple[MixedNoticeRef, ...] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def different_purchases(self) -> MixedComparisonRequest:
        if len({(r.law, r.purchase_number) for r in self.notices}) != len(self.notices):
            raise ValueError("DIFFERENT_PURCHASES_REQUIRED")
        return self


class Mixed44Row(EisComparisonRow):
    law: Literal["44"] = "44"
    source_window: str
    source_response_sha256: str
    archive_sha256: str
    source_schema_status: Literal["UNKNOWN"] = "UNKNOWN"


class Mixed223Row(Comparison223Row):
    law: Literal["223"] = "223"


MixedRow = Annotated[Mixed44Row | Mixed223Row, Field(discriminator="law")]


class MixedComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checked_at: datetime
    comparison_kind: Literal["PRELIMINARY"] = "PRELIMINARY"
    scope: Literal["SELECTED_KNOWN_XML_VERSIONS"] = "SELECTED_KNOWN_XML_VERSIONS"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    profit_order_status: Literal["UNKNOWN"] = "UNKNOWN"
    economic_comparability: Literal["UNKNOWN"] = "UNKNOWN"
    rows: tuple[MixedRow, ...] = Field(min_length=2, max_length=5)
    position_links: tuple[PositionLinkLead, ...] = Field(default=(), max_length=24)
    position_links_truncated: bool = False

    @model_validator(mode="after")
    def aware_clock(self) -> MixedComparisonResult:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        return self


def get_mixed_comparison(
    storage: PostgresStorage,
    company: str,
    request: MixedComparisonRequest,
    *,
    now: datetime | None = None,
) -> MixedComparisonResult:
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    rows: list[Mixed44Row | Mixed223Row] = []
    with storage.transaction(company, consistent_read=True) as conn:
        for chosen in request.notices:
            payload = chosen.model_dump(exclude={"law"})
            if chosen.law == "223":
                row223 = read_comparison223_row(
                    conn, company, Notice223DocumentRef.model_validate(payload), now=at
                )
                rows.append(Mixed223Row(**row223.model_dump()))
            else:
                ref = NoticeDocumentRef.model_validate(payload)
                bridge = read_eis_evidence_bridge(
                    conn, company, ref, now=at, include_competition_criteria=False
                )
                table = eis_notice_versions
                source = (
                    conn.execute(
                        select(
                            table.c.window_key, table.c.response_sha256, table.c.archive_sha256
                        ).where(
                            table.c.company_id == company,
                            table.c.purchase_number == ref.purchase_number,
                            table.c.version_number == ref.version_number,
                            table.c.xml_sha256 == ref.notice_xml_sha256,
                        )
                    )
                    .mappings()
                    .one()
                )
                rows.append(
                    Mixed44Row(
                        **comparison44_row(bridge).model_dump(),
                        source_window=source["window_key"],
                        source_response_sha256=source["response_sha256"],
                        archive_sha256=source["archive_sha256"],
                    )
                )
    sets = tuple(r.evidence.position_set if r.law == "44" else r.position_set for r in rows)
    # Preserve row indexes if compatibility fixtures/older rows have no position set.
    links, truncated = (
        position_links(tuple(s for s in sets if s is not None))
        if all(s is not None for s in sets)
        else ((), False)
    )
    return MixedComparisonResult(
        checked_at=at, rows=tuple(rows), position_links=links, position_links_truncated=truncated
    )
