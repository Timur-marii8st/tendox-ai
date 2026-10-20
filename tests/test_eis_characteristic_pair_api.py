"""Pair observations never accept a caller tenant or expose a database failure."""

from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.sources.eis_characteristic_compare import (
    CharacteristicPairRequest,
    PositionSelection,
    SavedPosition,
    build_characteristic_pair_report,
)
from procurement.sources.eis_feed_archive import EisLotItem, EisNoticeSnapshot
from procurement.sources.eis_position_evidence import positions44
from procurement.storage.eis_document_store import NoticeDocumentRef
from test_eis_document_jobs_api import send

PATH = "/v1/tender-discovery/eis-characteristic-pair"
NOTICE = EisNoticeSnapshot(
    purchase_number="1" * 19,
    document_type="epNotificationEF2020",
    version_number=1,
    title="Бумага",
    published_at=None,
    deadline=None,
    nmck_rub=None,
    xml_sha256="a" * 64,
    source_member="notice.xml",
    lot_items=(
        EisLotItem(
            name="Бумага",
            ktru_code=None,
            okpd2_code=None,
            quantity=None,
            unit=None,
            unit_price_rub=None,
            line_sum_rub=None,
            foreign_goods_prohibited=None,
            locator="objects/item[1]",
        ),
    ),
)
REF = NoticeDocumentRef(
    purchase_number=NOTICE.purchase_number,
    version_number=NOTICE.version_number,
    notice_xml_sha256=NOTICE.xml_sha256,
)
SELECTION = PositionSelection(notice=REF, source_index=1)
REQUEST = CharacteristicPairRequest(target=SELECTION, candidate=SELECTION)
BODY = REQUEST.model_dump(mode="json")


def test_authorized_read_uses_principal_and_retains_unknowns(monkeypatch):
    calls = []
    saved = SavedPosition(
        selection=SELECTION,
        position=positions44(NOTICE).positions[0],
        storage_kind="SAVED_NOTICE_FIELDS",
        legacy_values_unknown=False,
    )

    def read(storage, company, request, *, now):
        calls.append((company, request))
        return build_characteristic_pair_report(request, saved, saved, now=now)

    monkeypatch.setattr(import_module("procurement.api.app"), "read_characteristic_pair", read)
    assert send("POST", PATH, body=BODY, token="invalid").status_code == 401
    assert not calls
    response = send("POST", PATH, body=BODY, role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", REQUEST)]
    assert response.json()["technical"] == response.json()["profit"] == "UNKNOWN"
    assert response.json()["source_requests"] == 0


@pytest.mark.parametrize(
    "body",
    [
        BODY | {"company_id": "another"},
        BODY | {"target": dict(BODY["target"], source_index=True)},
        BODY | {"target": dict(BODY["target"], source_index=26)},
        BODY
        | {
            "candidate": dict(
                BODY["candidate"], notice=dict(BODY["candidate"]["notice"], notice_xml_sha256="bad")
            )
        },
    ],
)
def test_invalid_binding_never_reads_storage(monkeypatch, body):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid request reached storage")

    monkeypatch.setattr(import_module("procurement.api.app"), "read_characteristic_pair", forbidden)
    assert send("POST", PATH, body=body).status_code == 422


def test_hold_is_not_unknown_success_and_database_error_is_safe(monkeypatch):
    from sqlalchemy.exc import OperationalError

    def held(*args, **kwargs):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")

    monkeypatch.setattr(import_module("procurement.api.app"), "read_characteristic_pair", held)
    response = send("POST", PATH, body=BODY)
    assert (
        response.status_code == 422
        and response.json()["detail"] == "NOTICE_VARIANT_REVIEW_REQUIRED"
    )

    def failed(*args, **kwargs):
        raise OperationalError("private SQL", {}, Exception("private connection"))

    monkeypatch.setattr(import_module("procurement.api.app"), "read_characteristic_pair", failed)
    response = send("POST", PATH, body=BODY)
    assert (
        response.status_code == 503
        and response.json()["detail"] == "characteristic_read_unavailable"
    )
