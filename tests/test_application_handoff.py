from __future__ import annotations

import hashlib
import io
import json
from datetime import timedelta
from zipfile import ZipFile

import pytest

from case_support import AT
from procurement.documents.application_handoff import build_application_handoff
from test_application_submission_execution import BYTES, _approved


def test_handoff_contains_exact_approved_bytes_and_verifiable_manifest() -> None:
    submission = _approved()
    manifest, content = build_application_handoff(
        submission,
        attachment_bytes={"application-document": BYTES},
        at=AT + timedelta(minutes=6),
    )
    with ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == ["manifest.json", manifest.files[0].archive_path]
        assert archive.read(manifest.files[0].archive_path) == BYTES
        packed = json.loads(archive.read("manifest.json"))
    assert packed == manifest.model_dump(mode="json")
    assert manifest.files[0].sha256 == hashlib.sha256(BYTES).hexdigest()
    assert manifest.external_action_performed is False
    assert manifest.payload_sha256 == submission.intent.request.payload_sha256  # type: ignore[union-attr]


def test_handoff_fails_closed_for_bad_bytes_set_or_expired_approval() -> None:
    submission = _approved()
    for originals in ({}, {"application-document": b"changed"}, {
        "application-document": BYTES, "extra": b"x",
    }):
        with pytest.raises(ValueError):
            build_application_handoff(
                submission,
                attachment_bytes=originals,
                at=AT + timedelta(minutes=6),
            )
    assert submission.decision is not None and submission.decision.approval is not None
    with pytest.raises(ValueError, match="current"):
        build_application_handoff(
            submission,
            attachment_bytes={"application-document": BYTES},
            at=submission.decision.approval.expires_at,
        )
