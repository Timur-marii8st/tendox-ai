"""Real PostgreSQL checks for immutable manufacturer RFQ drafts."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_manufacturer_directory_pg import setup

from procurement.domain.manufacturer_review import ReviewStatus
from procurement.domain.manufacturer_rfq import ManufacturerRfqCommand
from procurement.storage import manufacturer_rfq as module
from procurement.storage import manufacturer_search as search_module
from procurement.storage.manufacturer_review import (
    decide_manufacturer_review,
    prepare_manufacturer_review,
)
from procurement.storage.manufacturer_rfq import (
    ManufacturerRfqConflict,
    ManufacturerRfqIneligible,
    ManufacturerRfqNotFound,
    create_manufacturer_rfq_draft,
    read_manufacturer_rfq_draft,
)
from procurement.storage.models import manufacturer_rfq_drafts
from procurement.storage.repository import PostgresStorage

DATABASE = "procurement_manufacturer_test"


@pytest.fixture
def storage() -> PostgresStorage:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required")
    if make_url(url).database != DATABASE:
        pytest.fail(f"manufacturer RFQ requires isolated database {DATABASE}")
    return PostgresStorage.from_url(url)


def rfq_command(search, candidate, proposal, **changes):
    decision = proposal.proposal.proposal_id  # replaced by caller after decision lookup
    payload = {
        "command_id": str(uuid.uuid4()),
        "run_id": search.report.run_id,
        "record_id": candidate.record_id,
        "proposal_id": proposal.proposal.proposal_id,
        "decision_id": decision,
        "quantity": "100.00",
        "unit_raw": "шт.",
        "quantity_basis_raw": "Количество для пилотного запроса",
        "requirements": ["Новый товар", "Гарантия 12 месяцев"],
        "delivery_address_raw": "Москва, тестовый адрес",
        "desired_delivery_raw": "30 календарных дней",
        "reply_due_at": datetime.now(UTC) + timedelta(days=7),
    }
    payload.update(changes)
    return ManufacturerRfqCommand.model_validate(payload)


def prepared(storage, monkeypatch, company):
    search, candidate, _, _, proposal = setup(storage, monkeypatch, company=company)
    from procurement.storage.manufacturer_review import read_manufacturer_decision

    decision = read_manufacturer_decision(
        storage, company, proposal.proposal.proposal_id
    ).decision
    command = rfq_command(
        search, candidate, proposal, decision_id=decision.decision_id
    )
    return search, candidate, proposal, decision, command


def test_create_replay_read_and_manual_provenance(storage, monkeypatch):
    company = "manufacturer-rfq-" + uuid.uuid4().hex
    _search, candidate, proposal, decision, command = prepared(storage, monkeypatch, company)
    created = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    replay = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    monkeypatch.setattr(
        search_module,
        "capture_manufacturer_search",
        lambda query: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    read = read_manufacturer_rfq_draft(storage, company, created.draft.draft_id)
    assert created.created and not replay.created and replay.draft == created.draft
    assert read.current_status is ReviewStatus.PASS
    assert created.draft.registry_snapshot.record_id == candidate.record_id
    assert created.draft.proposal_sha256 == proposal.proposal.proposal_sha256
    assert created.draft.decision_sha256 == decision.decision_sha256
    facts = (
        created.draft.quantity_input, created.draft.unit, created.draft.quantity_basis,
        *created.draft.requirements, created.draft.delivery_address,
        created.draft.desired_delivery,
    )
    assert all(item.provenance.extractor == "manual" for item in facts)
    assert all(item.provenance.document_id == created.draft.draft_id for item in facts)
    assert "Получатель и отправка не определены" in created.draft.text
    with pytest.raises(ManufacturerRfqNotFound):
        read_manufacturer_rfq_draft(storage, "other-" + company, created.draft.draft_id)


def test_changed_replay_and_wrong_exact_decision_are_rejected(storage, monkeypatch):
    company = "manufacturer-rfq-conflict-" + uuid.uuid4().hex
    _, _, _, _, command = prepared(storage, monkeypatch, company)
    create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    changed = command.model_copy(update={"unit_raw": "упаковка"})
    with pytest.raises(ManufacturerRfqConflict):
        create_manufacturer_rfq_draft(storage, company, changed, "operator-rfq")
    wrong = command.model_copy(
        update={"command_id": str(uuid.uuid4()), "decision_id": str(uuid.uuid4())}
    )
    with pytest.raises(ManufacturerRfqIneligible):
        create_manufacturer_rfq_draft(storage, company, wrong, "operator-rfq")


def test_current_status_fails_at_reply_deadline_and_rows_are_immutable(storage, monkeypatch):
    company = "manufacturer-rfq-expiry-" + uuid.uuid4().hex
    _, _, _, _, command = prepared(storage, monkeypatch, company)
    saved = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    assert module._current_status(
        storage, company, saved.draft, command.reply_due_at
    ) is ReviewStatus.FAIL
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(manufacturer_rfq_drafts)
            .where(manufacturer_rfq_drafts.c.draft_id == saved.draft.draft_id)
            .values(created_by="forged")
        )


def test_exact_replay_after_reply_deadline_returns_historical_failed_draft(
    storage, monkeypatch
):
    company = "manufacturer-rfq-replay-expired-" + uuid.uuid4().hex
    _, _, _, _, command = prepared(storage, monkeypatch, company)
    created = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")

    class LaterDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return command.reply_due_at + timedelta(seconds=1)

    monkeypatch.setattr(module, "datetime", LaterDateTime)
    replay = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    assert replay.draft == created.draft and not replay.created
    assert replay.current_status is ReviewStatus.FAIL


def test_pending_review_after_draft_makes_current_status_unknown(storage, monkeypatch):
    company = "manufacturer-rfq-pending-" + uuid.uuid4().hex
    _, _, proposal, _, command = prepared(storage, monkeypatch, company)
    saved = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    prepare_manufacturer_review(
        storage,
        company,
        command.run_id,
        command.record_id,
        proposal.proposal.claimed_identity,
        proposal.proposal.citations,
        "operator",
        str(uuid.uuid4()),
    )
    assert read_manufacturer_rfq_draft(
        storage, company, saved.draft.draft_id
    ).current_status is ReviewStatus.UNKNOWN


def test_review_overflow_after_draft_makes_current_status_unknown(storage, monkeypatch):
    company = "manufacturer-rfq-overflow-" + uuid.uuid4().hex
    _, _, proposal, _, command = prepared(storage, monkeypatch, company)
    saved = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    for _ in range(20):  # the accepted proposal plus twenty new proposals exceeds the cap
        prepare_manufacturer_review(
            storage,
            company,
            command.run_id,
            command.record_id,
            proposal.proposal.claimed_identity,
            proposal.proposal.citations,
            "operator",
            str(uuid.uuid4()),
        )
    assert read_manufacturer_rfq_draft(
        storage, company, saved.draft.draft_id
    ).current_status is ReviewStatus.UNKNOWN


def test_expired_registry_source_makes_current_status_fail(storage, monkeypatch):
    company = "manufacturer-rfq-source-expired-" + uuid.uuid4().hex
    search, candidate, _, _, proposal = setup(
        storage, monkeypatch, company=company, decision=False
    )
    decision = decide_manufacturer_review(
        storage,
        company,
        proposal.proposal.proposal_id,
        ReviewStatus.PASS,
        ReviewStatus.PASS,
        True,
        True,
        True,
        datetime(2028, 1, 1, tzinfo=UTC),
        "Exact evidence confirmed.",
        (0,),
        "reviewer",
        str(uuid.uuid4()),
    )
    command = rfq_command(
        search,
        candidate,
        proposal,
        decision_id=decision.decision.decision_id,
        reply_due_at=datetime(2028, 1, 1, tzinfo=UTC),
    )
    saved = create_manufacturer_rfq_draft(storage, company, command, "operator-rfq")
    assert module._current_status(
        storage, company, saved.draft, datetime(2027, 1, 2, tzinfo=UTC)
    ) is ReviewStatus.FAIL
