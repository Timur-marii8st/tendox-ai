"""Дедлайн и география являются hard facts, а не текстовыми подсказками."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from conftest import TZ
from procurement.domain.tenders import (
    DeliveryAddress,
    DeliveryPlan,
    DeliveryTopology,
    ProcedureMethod,
    ProcedureStage,
    ProcurementLaw,
    SubmissionWindow,
    TenderProcedure,
)


def address(region: str, city: str) -> DeliveryAddress:
    return DeliveryAddress(region=region, city=city, address="Тестовая, 1", provenance=TZ)


def test_submission_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        SubmissionWindow(
            closes_at=datetime(2026, 9, 5, 10), timezone="Europe/Moscow", provenance=TZ
        )


def test_expired_submission_is_closed_and_countdown_is_zero() -> None:
    zone = ZoneInfo("Europe/Moscow")
    window = SubmissionWindow(
        closes_at=datetime(2026, 9, 5, 10, tzinfo=zone),
        timezone="Europe/Moscow",
        provenance=TZ,
    )
    now = datetime(2026, 9, 5, 11, tzinfo=zone)
    assert window.is_open_at(now) is False
    assert window.seconds_left(now) == 0


@pytest.mark.parametrize(
    ("addresses", "expected"),
    [
        ((address("Татарстан", "Казань"),), DeliveryTopology.SINGLE_CITY),
        (
            (address("Татарстан", "Казань"), address("Татарстан", "Набережные Челны")),
            DeliveryTopology.MULTI_CITY_ONE_REGION,
        ),
        (
            (address("Татарстан", "Казань"), address("Самарская область", "Самара")),
            DeliveryTopology.MULTI_REGION,
        ),
    ],
)
def test_delivery_topology(
    addresses: tuple[DeliveryAddress, ...], expected: DeliveryTopology
) -> None:
    assert DeliveryPlan(addresses=addresses).topology is expected


def test_publication_does_not_prove_submission_is_open() -> None:
    zone = ZoneInfo("Europe/Moscow")
    tender = TenderProcedure(
        tender_id="t",
        customer_name="customer",
        subject="paper",
        law=ProcurementLaw.FZ_44,
        method=ProcedureMethod.ELECTRONIC_AUCTION,
        stage=ProcedureStage.PUBLISHED,
        submission=SubmissionWindow(
            closes_at=datetime(2026, 10, 2, tzinfo=zone), timezone="Europe/Moscow", provenance=TZ
        ),
        delivery=DeliveryPlan(addresses=(address("Татарстан", "Казань"),)),
        notice_provenance=TZ,
    )
    assert not tender.accepts_applications_at(datetime(2026, 10, 1, tzinfo=zone))
