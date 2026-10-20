"""Requirement previews bind exact saved evidence and remain UNKNOWN."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_requirement_preview import (
    RequirementPreviewRequest,
    build_requirement_preview,
    canonical_sha,
)
from procurement.sources.eis_requirement_table import (
    HEADERS,
    EISRequirementTable,
    RequirementTableCell,
    RequirementTableRow,
)
from procurement.storage.eis_document_review import ReviewDocumentRequest
from test_eis_supplier_product_api import result as product_result

DOC_SHA = "e" * 64
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def cell(row: int, column: int, text: str, block: int) -> RequirementTableCell:
    return RequirementTableCell(
        source_row=row,
        column=column,
        text=text,
        block_index=block,
        source_char_count=len(text),
        provenance=Provenance(
            document_id=DOC_SHA,
            locator=f"table 1 row {row} cell {column}",
            extractor=Extractor.NATIVE_DOCX,
        ),
    )


def table() -> EISRequirementTable:
    header = tuple(cell(1, index, text, index - 1) for index, text in enumerate(HEADERS, 1))
    values = (cell(2, 1, "Плотность", 5), cell(2, 3, ">= 80", 6))
    row = RequirementTableRow(
        source_row=2,
        kind="CHARACTERISTIC",
        cells=values,
        absent_columns=(2, 4, 5),
        numeric_hints=({"operator": ">=", "value": "80"},),
    )
    return EISRequirementTable(
        document_sha256=DOC_SHA,
        table_index=1,
        header=header,
        rows=(row,),
        row_count=1,
        cell_count=7,
        total_characters=sum(len(item.text) for item in (*header, *values)),
    )


def request() -> RequirementPreviewRequest:
    product = product_result().report.request
    return RequirementPreviewRequest(
        product=product,
        document=ReviewDocumentRequest(
            notice=product.catalog.page.position.selection.notice,
            content_uid="A" * 32,
            expected_document_sha256=DOC_SHA,
        ),
        table_index=1,
    )


def preview():
    product = product_result().report
    return build_requirement_preview(
        request=request(),
        product=product,
        product_report_sha256=canonical_sha(product),
        analysis_sha256="f" * 64,
        document_observation_id="observation-1",
        observed_at=NOW,
        analyzed_at=NOW,
        filename="requirements.docx",
        table=table(),
        approved_requirement_status="UNKNOWN",
        document_role="UNKNOWN",
        position_association="UNKNOWN",
        full_tspec_completeness="UNKNOWN",
        technical="UNKNOWN",
        participation="UNKNOWN",
        source_requests=0,
        jobs_created=0,
        database_writes=0,
    )


def test_preview_is_deterministic_and_never_approves_requirement():
    first = preview()
    second = preview()
    assert first == second
    assert first.preview_sha256 == second.preview_sha256
    assert first.technical == first.approved_requirement_status == "UNKNOWN"
    assert first.table.rows[0].numeric_hints[0].value == 80


@pytest.mark.parametrize("field", ["product_report_sha256", "analysis_sha256", "preview_sha256"])
def test_digest_tampering_is_rejected(field):
    payload = preview().model_dump()
    payload[field] = "0" * 64
    with pytest.raises(ValidationError):
        type(preview()).model_validate(payload)


def test_request_rejects_notice_mismatch_and_coercible_table_index():
    payload = request().model_dump()
    payload["document"]["notice"]["notice_xml_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        RequirementPreviewRequest.model_validate(payload)
    payload = request().model_dump()
    payload["table_index"] = True
    with pytest.raises(ValidationError):
        RequirementPreviewRequest.model_validate(payload)
