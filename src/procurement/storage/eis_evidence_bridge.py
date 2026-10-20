"""Read-only, version-bound bridge from EIS cards to document and cost evidence."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING, Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import and_, select

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryEstimate,
    calculate_discovery_economics,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_analysis import ConditionSnippet, DocumentAnalysis
from procurement.sources.eis_competition_criteria import (
    MAX_XML_BYTES,
    EisCompetitionCriteria,
    extract_competition_criteria,
    unknown_competition_criteria,
)
from procurement.sources.eis_feed_archive import EisNoticeSnapshot, EisProcedureEvent
from procurement.sources.eis_position_evidence import PositionEvidenceSet, positions44
from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.storage.eis_document_store import (
    DocumentCollectionStatus,
    NoticeDocumentRef,
    _cached_analysis,
    load_notice,
    read_document_status,
)
from procurement.storage.eis_position_projection import read_position_projection
from procurement.storage.models import eis_feed_archives, eis_notice_versions, eis_procedure_events

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage

_EVENT = TypeAdapter(EisProcedureEvent)
_EVENT_FIELDS = frozenset(EisProcedureEvent.__dataclass_fields__)

RoleHint = Literal[
    "TECHNICAL_SPECIFICATION",
    "CONTRACT_DRAFT",
    "PRICE_JUSTIFICATION",
    "APPLICATION_INSTRUCTIONS",
    "UNKNOWN",
]


class EisEvidenceLotItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    quantity: Decimal | None
    unit: str | None
    ktru_code: str | None
    okpd2_code: str | None
    unit_price_rub: Decimal | None
    line_sum_rub: Decimal | None
    locator: str


class EisEvidenceContextBlock(BaseModel):
    """Adjacent text is a review lead, with its own exact source locator."""

    model_config = ConfigDict(frozen=True)
    excerpt: str = Field(min_length=1)
    truncated: bool
    provenance: Provenance


class EisEvidenceCondition(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    excerpt: str
    truncated: bool
    provenance: Provenance
    context: tuple[EisEvidenceContextBlock, ...] = ()
    context_status: Literal["ADJACENT_UNREVIEWED", "NOT_ATTACHED", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def _context_is_honest(self) -> EisEvidenceCondition:
        if bool(self.context) != (self.context_status == "ADJACENT_UNREVIEWED"):
            raise ValueError("context status must describe the attached evidence")
        if any(item.provenance.document_id != self.provenance.document_id for item in self.context):
            raise ValueError("context must belong to the same document")
        return self


class EisEvidenceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)
    content_uid: str
    role_hint: RoleHint
    role_status: Literal["UNKNOWN"] = "UNKNOWN"
    conditions: tuple[EisEvidenceCondition, ...]
    conditions_total: int = Field(default=0, ge=0)
    conditions_truncated: bool = False


class EisEvidenceBridge(BaseModel):
    """Review leads and cost inputs, never an approved requirement or profit."""

    model_config = ConfigDict(frozen=True)
    checked_at: datetime
    notice: NoticeDocumentRef
    title: str
    source_member: str
    document_type: str
    published_at: datetime | None
    deadline: datetime | None
    nmck_rub: Decimal | None
    nmck_provenance: Provenance | None
    lot_parse_status: str
    lot_items: tuple[EisEvidenceLotItem, ...]
    collection: DocumentCollectionStatus
    documents: tuple[EisEvidenceDocument, ...]
    application_status: Literal["FAIL", "UNKNOWN"]
    application_reasons: tuple[str, ...]
    requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    completeness_status: Literal["UNKNOWN"] = "UNKNOWN"
    economic_status: Literal["BLOCKED", "UNKNOWN"]
    economic_missing: tuple[str, ...]
    review_gaps: tuple[str, ...]
    competition_criteria: EisCompetitionCriteria | None = None
    position_set: PositionEvidenceSet | None = None


class EisPreliminaryEstimate(BaseModel):
    """Source-bound rough economics; it cannot produce a participation approval."""

    model_config = ConfigDict(frozen=True)
    notice: NoticeDocumentRef
    nmck_rub: Decimal | None
    nmck_provenance: Provenance | None
    application_status: Literal["FAIL", "UNKNOWN"]
    requirement_status: Literal["UNKNOWN"] = "UNKNOWN"
    quote_status: Literal["UNKNOWN"] = "UNKNOWN"
    completeness_status: Literal["UNKNOWN"] = "UNKNOWN"
    estimate: DiscoveryEstimate
    preliminary_guidance: Literal["NEEDS_ANALYSIS", "DO_NOT_PARTICIPATE"]


def _role_hint(filename: str) -> RoleHint:
    """Filename is a lead for a human; it never establishes the document role."""
    value = filename.casefold().replace("ё", "е")
    if "техническое задание" in value or ("описани" in value and "закупк" in value):
        return "TECHNICAL_SPECIFICATION"
    if "контракт" in value:
        return "CONTRACT_DRAFT"
    if "нмц" in value or ("обосновани" in value and "цен" in value):
        return "PRICE_JUSTIFICATION"
    if "заявк" in value or "инструкц" in value:
        return "APPLICATION_INSTRUCTIONS"
    return "UNKNOWN"


_TEXT_LOCATOR = re.compile(r"^(.*?)(paragraph |antiword-0\.37-16 utf8 w0 :: line )(\d+)$")
_NEXT_HEADING = re.compile(r"^\d+(?:\.\d+)*[.)]\s+\S")


def _heading_context(
    snippet: ConditionSnippet, blocks: tuple[ExtractedBlock, ...]
) -> tuple[EisEvidenceContextBlock, ...]:
    if snippet.provenance.extractor not in {Extractor.NATIVE_DOCX, Extractor.LEGACY_DOC_TEXT}:
        return ()
    positions = [
        index
        for index, block in enumerate(blocks)
        if block.provenance == snippet.provenance and block.text == snippet.text
    ]
    if len(positions) != 1 or positions[0] + 1 >= len(blocks):
        return ()
    following = blocks[positions[0] + 1]
    left = _TEXT_LOCATOR.fullmatch(snippet.provenance.locator)
    right = _TEXT_LOCATOR.fullmatch(following.provenance.locator)
    if (
        left is None
        or right is None
        or left.groups()[:2] != right.groups()[:2]
        or following.provenance.extractor != snippet.provenance.extractor
        or not 0 < int(right.group(3)) - int(left.group(3)) <= 4
        or _NEXT_HEADING.match(following.text.strip())
        or following.text.rstrip().endswith(":")
    ):
        return ()
    return (
        EisEvidenceContextBlock(
            excerpt=following.text[:500],
            truncated=len(following.text) > 500,
            provenance=following.provenance,
        ),
    )


def _conditions(analysis: DocumentAnalysis | None) -> tuple[EisEvidenceCondition, ...]:
    if analysis is None:
        return ()
    if any(block.provenance.document_id != analysis.sha256 for block in analysis.blocks) or any(
        snippet.provenance.document_id != analysis.sha256 for snippet in analysis.snippets
    ):
        raise ValueError("EIS_EVIDENCE_PROVENANCE_MISMATCH")
    selected: list[EisEvidenceCondition] = []
    counts: dict[str, int] = {}
    for snippet in analysis.snippets:
        if counts.get(snippet.kind, 0) >= 3:
            continue
        counts[snippet.kind] = counts.get(snippet.kind, 0) + 1
        heading = len(snippet.text) <= 160 and snippet.text.rstrip().endswith(":")
        context = _heading_context(snippet, analysis.blocks) if heading else ()
        selected.append(
            EisEvidenceCondition(
                kind=snippet.kind,
                excerpt=snippet.text[:350],
                truncated=len(snippet.text) > 350,
                provenance=snippet.provenance,
                context=context,
                context_status=(
                    "ADJACENT_UNREVIEWED" if context else "UNKNOWN" if heading else "NOT_ATTACHED"
                ),
            )
        )
        if len(selected) == 18:
            break
    return tuple(selected)


def build_eis_evidence_bridge(
    notice: EisNoticeSnapshot,
    collection: DocumentCollectionStatus,
    analyses: dict[str, DocumentAnalysis],
    events: tuple[EisProcedureEvent, ...],
    *,
    now: datetime,
    competition_criteria: EisCompetitionCriteria | None = None,
) -> EisEvidenceBridge:
    """Bind immutable evidence while keeping unreviewed facts and money unknown."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    ref = collection.notice
    criteria = competition_criteria or unknown_competition_criteria(
        notice, "CRITERIA_SOURCE_NOT_READ"
    )
    if (
        criteria.source_xml_sha256 != ref.notice_xml_sha256
        or criteria.document_type != notice.document_type
    ):
        raise ValueError("EIS_CRITERIA_EVIDENCE_MISMATCH")
    if (
        notice.purchase_number != ref.purchase_number
        or notice.version_number != ref.version_number
        or notice.xml_sha256 != ref.notice_xml_sha256
        or len(notice.attachments) != collection.listed_count
        or tuple(item.content_uid for item in notice.attachments)
        != tuple(item.content_uid for item in collection.documents)
        or set(analyses) - {item.content_uid for item in collection.documents}
    ):
        raise ValueError("EIS_EVIDENCE_VERSION_MISMATCH")
    documents = []
    for item in collection.documents:
        analysis = analyses.get(item.content_uid)
        if analysis is not None and (
            item.fetch_status != "RECEIVED"
            or analysis.sha256 != item.sha256
            or analysis.filename != item.filename
        ):
            raise ValueError("EIS_EVIDENCE_DOCUMENT_MISMATCH")
        conditions = _conditions(analysis)
        conditions_total = len(analysis.snippets) if analysis else 0
        documents.append(
            EisEvidenceDocument(
                content_uid=item.content_uid,
                role_hint=_role_hint(item.filename),
                conditions=conditions,
                conditions_total=conditions_total,
                conditions_truncated=len(conditions) < conditions_total,
            )
        )
    procedure = resolve_procedure_state(events, purchase_number=ref.purchase_number, now=now)
    expired = notice.deadline is not None and notice.deadline <= now
    application_status: Literal["FAIL", "UNKNOWN"] = (
        "FAIL" if expired or procedure.application_status == "FAIL" else "UNKNOWN"
    )
    reasons = list(procedure.reasons)
    if expired:
        reasons.append("DEADLINE_EXPIRED")
    elif notice.deadline is None:
        reasons.append("DEADLINE_UNKNOWN")
    else:
        reasons.append("CURRENT_SUBMISSION_STAGE_UNVERIFIED")
    gaps = ["SOURCE_MANIFEST_COVERAGE_UNVERIFIED", "DOCUMENT_ROLES_NOT_REVIEWED"]
    if not collection.requested:
        gaps.append("DOCUMENT_JOB_NOT_REQUESTED")
    if not collection.listed_count:
        gaps.append("DOCUMENT_MANIFEST_EMPTY")
    if collection.pending_count:
        gaps.append("DOCUMENTS_NOT_RECEIVED")
    if collection.extraction_status != "EXTRACTED":
        gaps.append("DOCUMENT_EXTRACTION_UNKNOWN")
    if notice.lot_parse_status != "PARSED":
        gaps.append("LOT_XML_NOT_PARSED")
    gaps.append("REQUIREMENTS_NOT_APPROVED")
    if notice.document_type == "epNotificationEOK2020":
        gaps.append("COMPETITION_CRITERIA_NOT_REVIEWED")
        gaps.append("COMPETITION_QUALIFICATION_NOT_REVIEWED")
        if criteria.source_status != "EXTRACTED" or criteria.weight_integrity != "CONSISTENT":
            gaps.append("COMPETITION_SOURCE_WEIGHTS_UNKNOWN")
    xml_provenance = (
        Provenance(
            document_id=ref.notice_xml_sha256,
            locator=(
                f"{notice.document_type}/notificationInfo/contractConditionsInfo/"
                "maxPriceInfo/maxPrice"
            ),
            extractor=Extractor.API,
        )
        if notice.nmck_rub is not None
        else None
    )
    return EisEvidenceBridge(
        position_set=positions44(notice, analyses.items()),
        checked_at=now,
        notice=ref,
        title=notice.title,
        source_member=notice.source_member,
        document_type=notice.document_type,
        published_at=notice.published_at,
        deadline=notice.deadline,
        nmck_rub=notice.nmck_rub,
        nmck_provenance=xml_provenance,
        lot_parse_status=notice.lot_parse_status,
        lot_items=tuple(
            EisEvidenceLotItem(
                name=item.name,
                quantity=item.quantity,
                unit=item.unit,
                ktru_code=item.ktru_code,
                okpd2_code=item.okpd2_code,
                unit_price_rub=item.unit_price_rub,
                line_sum_rub=item.line_sum_rub,
                locator=item.locator,
            )
            for item in notice.lot_items
        ),
        collection=collection,
        documents=tuple(documents),
        application_status=application_status,
        application_reasons=tuple(reasons),
        economic_status="BLOCKED" if application_status == "FAIL" else "UNKNOWN",
        economic_missing=(
            "SUPPLIER_QUOTE_MISSING",
            "ALL_IN_COSTS_MISSING",
            "TAX_MODEL_MISSING",
            "BASE_REALISTIC_CONSERVATIVE_MISSING",
        ),
        review_gaps=tuple(gaps),
        competition_criteria=criteria,
    )


def _stored_competition_criteria(
    connection: Connection, company_id: str, ref: NoticeDocumentRef, notice: EisNoticeSnapshot
) -> EisCompetitionCriteria:
    """Read only the exact immutable archive/member; unrelated versions cannot supply weights."""
    if notice.document_type != "epNotificationEOK2020":
        return unknown_competition_criteria(notice, "")
    row = connection.execute(
        select(eis_feed_archives.c.content, eis_feed_archives.c.archive_sha256)
        .join(
            eis_notice_versions,
            and_(
                eis_notice_versions.c.company_id == eis_feed_archives.c.company_id,
                eis_notice_versions.c.window_key == eis_feed_archives.c.window_key,
                eis_notice_versions.c.response_sha256 == eis_feed_archives.c.response_sha256,
                eis_notice_versions.c.archive_sha256 == eis_feed_archives.c.archive_sha256,
            ),
        )
        .where(
            eis_notice_versions.c.company_id == company_id,
            eis_notice_versions.c.purchase_number == ref.purchase_number,
            eis_notice_versions.c.version_number == ref.version_number,
            eis_notice_versions.c.xml_sha256 == ref.notice_xml_sha256,
        )
    ).first()
    if row is None:
        return unknown_competition_criteria(notice, "CRITERIA_SOURCE_UNAVAILABLE")
    raw = bytes(row.content)
    if len(raw) > 50 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != row.archive_sha256:
        raise ValueError("EIS_CRITERIA_ARCHIVE_DIGEST_MISMATCH")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = [m for m in archive.infolist() if m.filename == notice.source_member]
            if len(members) != 1 or members[0].file_size > MAX_XML_BYTES:
                return unknown_competition_criteria(notice, "CRITERIA_MEMBER_UNKNOWN")
            with archive.open(members[0]) as stream:
                content = stream.read(MAX_XML_BYTES + 1)
            if len(content) != members[0].file_size:
                return unknown_competition_criteria(notice, "CRITERIA_MEMBER_UNKNOWN")
    except (BadZipFile, RuntimeError) as error:
        raise ValueError("EIS_CRITERIA_ARCHIVE_INVALID") from error
    return extract_competition_criteria(content, notice)


def get_eis_evidence_bridge(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    *,
    now: datetime | None = None,
) -> EisEvidenceBridge:
    """Read one exact notice and saved documents; source/network is never touched."""
    observed_at = now or datetime.now(UTC)
    with storage.transaction(company_id, consistent_read=True) as connection:
        return read_eis_evidence_bridge(connection, company_id, ref, now=observed_at)


def read_eis_evidence_bridge(
    connection: Connection,
    company_id: str,
    ref: NoticeDocumentRef,
    *,
    now: datetime,
    include_competition_criteria: bool = True,
) -> EisEvidenceBridge:
    """One caller-owned snapshot; fast comparison skips archive/criteria parsing."""
    collection = read_document_status(connection, company_id, ref, now=now)
    notice = load_notice(connection, company_id, ref)
    criteria = (
        _stored_competition_criteria(connection, company_id, ref, notice)
        if include_competition_criteria
        else unknown_competition_criteria(notice, "CRITERIA_NOT_READ_IN_FAST_COMPARISON")
    )
    analyses = {
        item.content_uid: analysis
        for item in collection.documents
        if item.fetch_status == "RECEIVED" and item.sha256 is not None
        if (
            analysis := _cached_analysis(
                connection, company_id, item.sha256, item.filename, item.source_url
            )
        )
        is not None
    }
    events = tuple(
        _EVENT.validate_python({key: row[key] for key in _EVENT_FIELDS})
        for row in connection.execute(
            select(eis_procedure_events).where(
                eis_procedure_events.c.company_id == company_id,
                eis_procedure_events.c.purchase_number == ref.purchase_number,
            )
        ).mappings()
    )
    bridge = build_eis_evidence_bridge(
        notice, collection, analyses, events, now=now, competition_criteria=criteria
    )
    projection = read_position_projection(connection, company_id, ref)
    if projection is not None:
        native_tables = bridge.position_set.native_tables if bridge.position_set is not None else ()
        return bridge.model_copy(
            update={"position_set": projection.model_copy(update={"native_tables": native_tables})}
        )
    return bridge


def calculate_eis_preliminary_estimate(
    bridge: EisEvidenceBridge, costs: DiscoveryCostInput
) -> EisPreliminaryEstimate:
    """Use the exact notice ceiling and explicit supplier assumptions, never a guessed quote."""
    if (
        bridge.collection.read_gate is not None
        and "NOTICE_VARIANT_REVIEW_REQUIRED" in bridge.collection.read_gate.blocked_reasons
    ):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")
    if bridge.collection.version_status != "CURRENT_KNOWN_VERSION":
        raise ValueError("NOTICE_VERSION_STALE")
    estimate = calculate_discovery_economics(
        bridge.nmck_rub, costs, blocked=bridge.application_status == "FAIL"
    )
    return EisPreliminaryEstimate(
        notice=bridge.notice,
        nmck_rub=bridge.nmck_rub,
        nmck_provenance=bridge.nmck_provenance,
        application_status=bridge.application_status,
        estimate=estimate,
        preliminary_guidance=(
            "DO_NOT_PARTICIPATE" if bridge.application_status == "FAIL" else "NEEDS_ANALYSIS"
        ),
    )


def estimate_eis_notice(
    storage: PostgresStorage,
    company_id: str,
    ref: NoticeDocumentRef,
    costs: DiscoveryCostInput,
) -> EisPreliminaryEstimate:
    """Calculate a disposable estimate after rereading current tenant evidence."""
    bridge = get_eis_evidence_bridge(storage, company_id, ref)
    return calculate_eis_preliminary_estimate(bridge, costs)
