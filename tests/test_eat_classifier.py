"""Offline contract tests for the public EAT classifier probe."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest

from procurement.sources import eat_classifier
from procurement.sources.eat_classifier import EatClassifierError, parse_eat_classifier_archive

AT = datetime(2026, 9, 19, tzinfo=UTC)
XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<eatCategorySet xmlns="http://agregatoreat.ru/eat/object-types/"
  xmlns:e="http://agregatoreat.ru/eat/">
  <e:category><e:code>01</e:code><e:shortName>Root</e:shortName></e:category>
  <e:category><e:code>0101</e:code><e:shortName>Child</e:shortName>
    <e:parentCode>01</e:parentCode><e:deleted>true</e:deleted></e:category>
</eatCategorySet>"""


def _archive(xml: bytes, *, extra: bool = False) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr("eatCategorySet.xml", xml)
        if extra:
            zipped.writestr("unexpected.xml", xml)
    return output.getvalue()


def test_classifier_keeps_exact_source_and_deleted_state() -> None:
    snapshot = parse_eat_classifier_archive(_archive(XML), fetched_at=AT)
    assert snapshot.source_sha256
    assert snapshot.fetched_at == AT
    assert len(snapshot.categories) == 2
    assert snapshot.active_count == 1
    assert snapshot.categories[1].parent_code == "01"
    assert snapshot.categories[1].deleted


@pytest.mark.parametrize(
    "archive",
    [
        b"not a ZIP",
        _archive(XML, extra=True),
        _archive(XML.replace(b"<e:parentCode>01", b"<e:parentCode>99")),
        _archive(XML.replace(b"<e:code>0101", b"<e:code>01")),
        _archive(XML.replace(b"<?xml", b"<!DOCTYPE foo><?xml")),
    ],
    ids=["not-zip", "extra-member", "unknown-parent", "duplicate-code", "doctype"],
)
def test_untrusted_or_inconsistent_feed_is_rejected(archive: bytes) -> None:
    with pytest.raises(EatClassifierError):
        parse_eat_classifier_archive(archive, fetched_at=AT)


def test_naive_observation_time_is_rejected() -> None:
    with pytest.raises(EatClassifierError):
        parse_eat_classifier_archive(_archive(XML), fetched_at=datetime(2026, 9, 19))


def test_unavailable_feed_is_reported_as_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable() -> eat_classifier.EatClassifierSnapshot:
        raise EatClassifierError("classifier feed is unavailable")

    monkeypatch.setattr(eat_classifier, "fetch_eat_classifier", unavailable)
    assert eat_classifier.main() == 3
    assert json.loads(capsys.readouterr().out)["status"] == "UNKNOWN"
