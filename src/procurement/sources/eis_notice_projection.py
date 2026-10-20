"""Bounded offline preparation of explicit canonical notice projection decisions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Literal
from zipfile import BadZipFile, ZipFile

from procurement.sources.eis_feed_archive import (
    EisFeedArchiveError,
    EisNoticeSnapshot,
    EisProcedureEvent,
    _notice,
)
from procurement.sources.eis_notice_conflicts import (
    EisNoticeConflictDiagnosis,
    EisNoticeConflictError,
    EisNoticeOccurrence,
    diagnose_notice_conflicts,
)

MAX_PROJECTION_SNAPSHOT_BYTES = 16 * 1024 * 1024
_REBIND_SENTINEL = "eis-projection-rebind-sentinel-0063"


class EisNoticeProjectionError(ValueError):
    """The retained archive set cannot produce a fully bound decision batch."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EisNoticeProjectionCandidate:
    purchase_number: str
    version_number: int
    document_type: str
    xml_sha256: str
    archive_ordinal: int
    member_filename: str
    snapshot: EisNoticeSnapshot | None
    reason: (
        Literal[
            "DIVERGENT_VARIANT_REVIEW_REQUIRED",
            "SOURCE_ID_UNKNOWN",
        ]
        | str
        | None
    )

    def __post_init__(self) -> None:
        if (self.snapshot is None) == (self.reason is None):
            raise ValueError("PROJECTION_CANDIDATE_DECISION_INVALID")
        if self.snapshot is not None and (
            self.snapshot.purchase_number != self.purchase_number
            or self.snapshot.version_number != self.version_number
            or self.snapshot.document_type != self.document_type
            or self.snapshot.xml_sha256 != self.xml_sha256
            or self.snapshot.source_member != self.member_filename
        ):
            raise ValueError("PROJECTION_SNAPSHOT_BINDING_INVALID")


@dataclass(frozen=True)
class EisNoticeProjectionBatch:
    diagnosis_sha256: str
    archive_sha256s: tuple[str, ...]
    occurrence_count: int
    archive_member_counts: tuple[int, ...]
    candidates: tuple[EisNoticeProjectionCandidate, ...]

    def __post_init__(self) -> None:
        if (
            len(self.diagnosis_sha256) != 64
            or len(self.archive_sha256s) != len(self.archive_member_counts)
            or sum(self.archive_member_counts) != self.occurrence_count
            or len({(item.purchase_number, item.version_number) for item in self.candidates})
            != len(self.candidates)
        ):
            raise ValueError("PROJECTION_BATCH_INVALID")


def prepare_notice_projection(
    archives: tuple[bytes, ...], diagnosis: EisNoticeConflictDiagnosis
) -> EisNoticeProjectionBatch:
    """Rebind every retained member and prepare one explicit decision per semantic pair."""
    try:
        fresh = diagnose_notice_conflicts(archives, _REBIND_SENTINEL)
    except EisNoticeConflictError as error:
        raise EisNoticeProjectionError(error.code) from error
    if fresh.sha256 != diagnosis.sha256 or fresh != diagnosis:
        raise EisNoticeProjectionError("DIAGNOSIS_BINDING_MISMATCH")

    contents = _member_contents(archives, diagnosis)
    grouped: dict[tuple[str, int], list[EisNoticeOccurrence]] = defaultdict(list)
    member_counts = Counter(item.archive_ordinal for item in diagnosis.occurrences)
    for occurrence in diagnosis.occurrences:
        if occurrence.purchase_number is None or occurrence.version_number is None:
            raise EisNoticeProjectionError("SEMANTIC_IDENTITY_UNKNOWN")
        grouped[(occurrence.purchase_number, occurrence.version_number)].append(occurrence)

    candidates: list[EisNoticeProjectionCandidate] = []
    snapshot_bytes = 0
    for key, occurrences in sorted(grouped.items()):
        occurrences.sort(
            key=lambda item: (item.archive_ordinal, item.member_filename, item.xml_sha256)
        )
        selected = occurrences[0]
        document_types = {item.document_type for item in occurrences}
        xml_hashes = {item.xml_sha256 for item in occurrences}
        if selected.document_type is None or len(document_types) != 1:
            candidates.append(_held(selected, "DIVERGENT_VARIANT_REVIEW_REQUIRED"))
            continue
        if len(xml_hashes) != 1:
            candidates.append(_held(selected, "DIVERGENT_VARIANT_REVIEW_REQUIRED"))
            continue
        if any(item.document_id is None for item in occurrences):
            candidates.append(_held(selected, "SOURCE_ID_UNKNOWN"))
            continue
        content = contents[(selected.archive_ordinal, selected.member_filename)]
        try:
            parsed = _notice(content, selected.member_filename, selected.document_type)
        except EisFeedArchiveError as error:
            candidates.append(_held(selected, f"NOTICE_PARSE_FAILED:{error}"))
            continue
        if isinstance(parsed, EisProcedureEvent):
            candidates.append(_held(selected, "NOTICE_PARSE_FAILED:DOCUMENT_TYPE_UNSUPPORTED"))
            continue
        if (
            parsed.purchase_number != key[0]
            or parsed.version_number != key[1]
            or parsed.document_type != selected.document_type
            or parsed.xml_sha256 != selected.xml_sha256
        ):
            raise EisNoticeProjectionError("SNAPSHOT_BINDING_MISMATCH")
        snapshot_bytes += _snapshot_payload_bytes(parsed)
        if snapshot_bytes > MAX_PROJECTION_SNAPSHOT_BYTES:
            raise EisNoticeProjectionError("PROJECTION_SNAPSHOT_BYTES_LIMIT")
        candidates.append(
            EisNoticeProjectionCandidate(
                purchase_number=key[0],
                version_number=key[1],
                document_type=selected.document_type,
                xml_sha256=selected.xml_sha256,
                archive_ordinal=selected.archive_ordinal,
                member_filename=selected.member_filename,
                snapshot=parsed,
                reason=None,
            )
        )
    return EisNoticeProjectionBatch(
        diagnosis_sha256=diagnosis.sha256,
        archive_sha256s=diagnosis.archive_sha256s,
        occurrence_count=diagnosis.occurrence_count,
        archive_member_counts=tuple(
            member_counts[ordinal] for ordinal in range(diagnosis.archive_count)
        ),
        candidates=tuple(candidates),
    )


def _member_contents(
    archives: tuple[bytes, ...], diagnosis: EisNoticeConflictDiagnosis
) -> dict[tuple[int, str], bytes]:
    expected = {
        (item.archive_ordinal, item.member_filename): item.xml_sha256
        for item in diagnosis.occurrences
    }
    result: dict[tuple[int, str], bytes] = {}
    try:
        for ordinal, raw in enumerate(archives):
            if hashlib.sha256(raw).hexdigest() != diagnosis.archive_sha256s[ordinal]:
                raise EisNoticeProjectionError("ARCHIVE_BINDING_MISMATCH")
            with ZipFile(BytesIO(raw)) as bundle:
                for member in bundle.infolist():
                    key = (ordinal, member.filename)
                    content = bundle.read(member)
                    if expected.get(key) != hashlib.sha256(content).hexdigest():
                        raise EisNoticeProjectionError("MEMBER_BINDING_MISMATCH")
                    result[key] = content
    except (BadZipFile, RuntimeError, IndexError) as error:
        raise EisNoticeProjectionError("ARCHIVE_BINDING_MISMATCH") from error
    if result.keys() != expected.keys():
        raise EisNoticeProjectionError("INVENTORY_BINDING_MISMATCH")
    return result


def _snapshot_payload_bytes(snapshot: EisNoticeSnapshot) -> int:
    """Measure the compact UTF-8 JSON representation persisted by the writer."""
    return len(
        json.dumps(
            asdict(snapshot),
            default=str,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _held(occurrence: EisNoticeOccurrence, reason: str) -> EisNoticeProjectionCandidate:
    if occurrence.purchase_number is None or occurrence.version_number is None:
        raise EisNoticeProjectionError("SEMANTIC_IDENTITY_UNKNOWN")
    return EisNoticeProjectionCandidate(
        purchase_number=occurrence.purchase_number,
        version_number=occurrence.version_number,
        document_type=occurrence.document_type or "UNKNOWN",
        xml_sha256=occurrence.xml_sha256,
        archive_ordinal=occurrence.archive_ordinal,
        member_filename=occurrence.member_filename,
        snapshot=None,
        reason=reason,
    )
