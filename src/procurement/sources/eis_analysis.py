"""Нативный разбор сохранённых документов ЕИС для предварительного отбора.

Кандидаты требований не являются утверждённым ТЗ: роль и полноту комплекта
проверяет человек в существующем review-процессе.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict

from procurement.documents.bundle import DocumentBundleRejected, extract_document_bundle
from procurement.documents.extraction import (
    DocumentInput,
    DocumentRejected,
    ExtractedBlock,
    extract_document,
)
from procurement.documents.facts import DocumentRole, map_blocks_to_requirements
from procurement.domain.provenance import Provenance
from procurement.domain.requirements import Operator, RequirementValue

MEDIA = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".doc": "application/msword",
    ".zip": "application/zip",
}


class ConditionSnippet(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    text: str
    provenance: Provenance


class RequirementCandidate(BaseModel):
    """Гипотеза: формулировка станет требованием только после проверки роли и смысла."""

    model_config = ConfigDict(frozen=True)
    property: str
    operator: Operator
    value: RequirementValue | None
    unit: str | None
    raw_text: str
    provenance: Provenance
    reviewed: Literal[False] = False


class DocumentAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    url: str
    sha256: str
    byte_count: int
    status: Literal["PASS", "UNKNOWN", "FAIL"]
    reasons: tuple[str, ...] = ()
    blocks_total: int = 0
    unmapped_count: int = 0
    document_role: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_candidates: tuple[RequirementCandidate, ...] = ()
    snippets: tuple[ConditionSnippet, ...] = ()
    members: tuple[str, ...] = ()
    # Full blocks are retained in the scoped store, not truncated before mapping.
    blocks: tuple[ExtractedBlock, ...] = ()


_CONDITIONS = {
    "Поставка": r"поставк|доставк|отгрузк|монтаж",
    "Оплата": r"оплат|аванс|предоплат",
    "Обеспечение": r"обеспечени[ея]\s+(?:заявк|исполнени|контракт)|банковск.*гарант",
    "Ограничения": r"лицензи|сертификат|реестр|происхождени|эквивалент|национальн",
    "Ответственность": r"неустойк|штраф|пен[яию]|гаранти",
    "Количество": r"количеств|объ[её]м|единиц.*измерени",
}


def document_filename_requires_review(filename: str) -> bool:
    """Reject source labels that cannot be passed unchanged to the extractor."""
    return (
        not filename
        or "\x00" in filename
        or PurePosixPath(filename).name != filename
        or PureWindowsPath(filename).name != filename
    )


def analyze_document(
    content: bytes,
    filename: str,
    url: str,
    *,
    max_characters: int = 100_000,
) -> DocumentAnalysis:
    """Извлечь весь поддержанный текст и кандидаты с локаторами источника."""
    digest = hashlib.sha256(content).hexdigest()
    suffix = "." + filename.rsplit(".", 1)[-1].lower()
    base = dict(filename=filename, url=url, sha256=digest, byte_count=len(content))
    if document_filename_requires_review(filename):
        return DocumentAnalysis(
            **base, status="UNKNOWN", reasons=("ATTACHMENT_FILENAME_REQUIRES_REVIEW",)
        )
    if suffix not in MEDIA:
        return DocumentAnalysis(**base, status="UNKNOWN", reasons=("UNSUPPORTED_FORMAT",))
    try:
        source = DocumentInput(
            document_id=digest,
            filename=filename,
            declared_media_type=MEDIA[suffix],
            content=content,
        )
        if suffix == ".zip":
            bundle = extract_document_bundle(source)
            blocks = tuple(block for member in bundle.members for block in member.extraction.blocks)
            status = bundle.status.value
            reasons = tuple(reason.value for reason in bundle.reasons)
            members = tuple(member.archive_path for member in bundle.members)
        else:
            extraction = extract_document(source)
            blocks = extraction.blocks
            status = extraction.status.value
            reasons = tuple(reason.value for reason in extraction.reasons)
            members = ()
    except (DocumentRejected, DocumentBundleRejected) as error:
        return DocumentAnalysis(**base, status="UNKNOWN", reasons=(error.code.value,))
    retained: list[ExtractedBlock] = []
    remaining = max_characters
    for block in blocks:
        if len(block.text) > remaining or len(retained) >= 1000:
            status = "UNKNOWN"
            reasons = (*reasons, "ANALYSIS_LIMIT_FULL_SOURCE_RETAINED")
            break
        retained.append(block)
        remaining -= len(block.text)
    blocks = tuple(retained)
    # This mapping is explicitly hypothetical until document role and each candidate
    # are reviewed. It never creates an approved requirement set or hard gate.
    mapping = map_blocks_to_requirements(blocks, document_role=DocumentRole.TENDER_REQUIREMENTS)
    snippets = tuple(
        ConditionSnippet(kind=label, text=block.text, provenance=block.provenance)
        for block in blocks
        for label, pattern in _CONDITIONS.items()
        if re.search(pattern, block.text, re.IGNORECASE)
    )
    return DocumentAnalysis(
        **base,
        status=status,
        reasons=reasons,
        blocks_total=len(blocks),
        unmapped_count=len(mapping.unmapped),
        requirement_candidates=tuple(
            RequirementCandidate(
                property=item.property,
                operator=item.operator,
                value=item.value,
                unit=item.unit,
                raw_text=item.raw_text,
                provenance=item.provenance,
            )
            for item in mapping.requirements
        ),
        snippets=snippets,
        members=members,
        blocks=blocks,
    )
