"""PostgreSQL review lifecycle preserves exact payload and reviewer separation."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from sqlalchemy import func, insert, select
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).parent / "integration"))
from test_eis_requirement_preview_pg import setup
from test_eis_supplier_search_pg import storage as storage_fixture

from procurement.sources.eis_requirement_preview import canonical_sha
from procurement.sources.eis_requirement_review import (
    DecisionRequest,
    ProposalRequest,
    RowChoice,
    build_requirement_decision,
    build_requirement_proposal,
)
from procurement.storage import eis_requirement_review as review_module
from procurement.storage.eis_requirement_preview import read_requirement_preview
from procurement.storage.eis_requirement_review import (
    create_requirement_decision,
    create_requirement_proposal,
    read_requirement_comparison,
    read_requirement_proposal,
)
from procurement.storage.models import (
    eis_requirement_review_decisions,
    eis_requirement_review_proposals,
)

storage = storage_fixture


def _format_docx() -> bytes:
    document = Document()
    table = document.add_table(rows=2, cols=5)
    headers = (
        "Наименование характеристики",
        "Тип характеристики (количественная/качественная)",
        "Значение характеристики",
        "Единица измерения характеристики",
        "Инструкция по заполнению характеристик",
    )
    for index, value in enumerate(headers):
        table.rows[0].cells[index].text = value
    table.rows[1].cells[0].text = "Формат"
    table.rows[1].cells[2].text = "А4"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


class _MetaResult:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value


class _TamperedConnection:
    def __init__(self, meta, payload):
        self.meta = meta
        self.payload = payload

    def execute(self, statement):
        return _MetaResult(self.meta)

    def scalar(self, statement):
        return self.payload


def test_metadata_identity_substitution_is_rejected_before_source_rebuild():
    from test_eis_requirement_review_api import DECISION, PROPOSAL

    foreign_proposal = build_requirement_proposal(
        company_id=PROPOSAL.company_id,
        proposal_id=str(uuid4()),
        request=PROPOSAL.request,
        preview=PROPOSAL.preview,
        prepared_by=PROPOSAL.prepared_by,
        prepared_at=PROPOSAL.prepared_at,
    )
    proposal_key = canonical_sha(
        {"actor": PROPOSAL.prepared_by, "request": PROPOSAL.request.model_dump(mode="json")}
    )
    proposal_meta = (
        PROPOSAL.proposal_id,
        foreign_proposal.proposal_sha256,
        proposal_key,
        PROPOSAL.preview.product.run_id,
        PROPOSAL.prepared_by,
        PROPOSAL.prepared_at,
        len(foreign_proposal.model_dump_json()),
    )
    with pytest.raises(ValueError, match="REQUIREMENT_PROPOSAL_EVIDENCE_CONFLICT"):
        review_module._load_proposal(
            _TamperedConnection(proposal_meta, foreign_proposal.model_dump(mode="json")),
            PROPOSAL.company_id,
            PROPOSAL.proposal_id,
        )
    foreign_decision = build_requirement_decision(
        company_id=DECISION.company_id,
        decision_id=str(uuid4()),
        request=DECISION.request,
        proposal=PROPOSAL,
        reviewed_by=DECISION.reviewed_by,
        reviewed_at=DECISION.reviewed_at,
    )
    decision_meta = (
        DECISION.decision_id,
        PROPOSAL.proposal_id,
        canonical_sha(DECISION.request),
        foreign_decision.decision_sha256,
        DECISION.reviewed_by,
        DECISION.reviewed_at,
        len(foreign_decision.model_dump_json()),
    )
    with pytest.raises(ValueError, match="REQUIREMENT_DECISION_EVIDENCE_CONFLICT"):
        review_module._load_decision(
            _TamperedConnection(decision_meta, foreign_decision.model_dump(mode="json")),
            DECISION.company_id,
            PROPOSAL,
        )


def test_tenant_busy_code_is_translated(monkeypatch):
    @contextmanager
    def busy(*args):
        raise ValueError("SUPPLIER_PAGE_TENANT_BUSY")
        yield

    monkeypatch.setattr(review_module, "_tenant_lease", busy)
    with (
        pytest.raises(ValueError, match=r"^REQUIREMENT_REVIEW_BUSY$"),
        review_module._review_lease(object(), "tenant"),
    ):
        pass


def proposal_request(storage, company, monkeypatch):
    import test_eis_requirement_preview_pg as preview_pg

    monkeypatch.setattr(preview_pg, "docx_table", _format_docx)
    preview_request = setup(storage, company, monkeypatch)
    preview = read_requirement_preview(storage, company, preview_request)
    return ProposalRequest(
        preview=preview_request,
        expected_preview_sha256=preview.preview_sha256,
        rows=(RowChoice(source_row=2, mode="PAPER_FORMAT", supplier_index=1, mandatory=True),),
        note="Operator selected the exact retained format row.",
    )


def test_proposal_replay_independent_decision_comparison_and_immutability(storage, monkeypatch):
    company = "requirement-review-" + uuid4().hex
    request = proposal_request(storage, company, monkeypatch)
    proposal = create_requirement_proposal(storage, company, request, actor_id="operator-a")
    replay = create_requirement_proposal(storage, company, request, actor_id="operator-a")
    assert proposal.created and not replay.created and replay.proposal == proposal.proposal
    assert (
        read_requirement_proposal(storage, company, proposal.proposal.proposal_id).proposal
        == proposal.proposal
    )
    decision_request = DecisionRequest(
        proposal_id=proposal.proposal.proposal_id,
        expected_proposal_sha256=proposal.proposal.proposal_sha256,
        normative_document=True,
        position_association=True,
        confirmed_rows=(2,),
        note="Independent reviewer confirmed the format row.",
    )
    with pytest.raises(ValueError, match="REVIEW_SELF_APPROVAL_FORBIDDEN"):
        create_requirement_decision(storage, company, decision_request, actor_id="operator-a")
    decision = create_requirement_decision(
        storage, company, decision_request, actor_id="reviewer-a"
    )
    exact = create_requirement_decision(storage, company, decision_request, actor_id="reviewer-a")
    assert decision.created and not exact.created and exact.decision == decision.decision
    comparison = read_requirement_comparison(storage, company, proposal.proposal.proposal_id)
    assert comparison.rows[0].status == "PASS" and not comparison.candidate_blocked
    assert comparison.technical == comparison.full_tspec_completeness == "UNKNOWN"
    with storage.transaction(company, consistent_read=True) as conn:
        proposal_row = dict(
            conn.execute(
                select(eis_requirement_review_proposals).where(
                    eis_requirement_review_proposals.c.proposal_id == proposal.proposal.proposal_id
                )
            )
            .mappings()
            .one()
        )
        decision_row = dict(
            conn.execute(
                select(eis_requirement_review_decisions).where(
                    eis_requirement_review_decisions.c.decision_id == decision.decision.decision_id
                )
            )
            .mappings()
            .one()
        )
    for null_value in (False, True):
        bad = {**proposal_row, "proposal": dict(proposal_row["proposal"])}
        bad["proposal_id"] = str(uuid4())
        bad["request_key"] = uuid4().hex + uuid4().hex
        bad["proposal"]["proposal_id"] = bad["proposal_id"]
        if null_value:
            bad["proposal"]["prepared_by"] = None
        else:
            bad["proposal"].pop("prepared_by")
        bad["proposal_sha256"] = canonical_sha(
            {key: value for key, value in bad["proposal"].items() if key != "proposal_sha256"}
        )
        bad["proposal"]["proposal_sha256"] = bad["proposal_sha256"]
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(insert(eis_requirement_review_proposals).values(**bad))
    second_proposal = create_requirement_proposal(
        storage,
        company,
        request.model_copy(update={"note": "A distinct exact proposal for constraint testing."}),
        actor_id="operator-a",
    ).proposal
    for null_value in (False, True):
        bad = {**decision_row, "decision": dict(decision_row["decision"])}
        bad["decision_id"] = str(uuid4())
        bad["proposal_id"] = second_proposal.proposal_id
        bad["decision"]["decision_id"] = bad["decision_id"]
        bad["decision"]["request"] = dict(bad["decision"]["request"])
        bad["decision"]["request"]["proposal_id"] = second_proposal.proposal_id
        bad["request_sha256"] = canonical_sha(bad["decision"]["request"])
        if null_value:
            bad["decision"]["reviewed_by"] = None
        else:
            bad["decision"].pop("reviewed_by")
        bad["decision_sha256"] = canonical_sha(
            {key: value for key, value in bad["decision"].items() if key != "decision_sha256"}
        )
        bad["decision"]["decision_sha256"] = bad["decision_sha256"]
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(insert(eis_requirement_review_decisions).values(**bad))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_requirement_review_proposals.delete())
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_requirement_review_decisions.delete())


def test_tenant_isolation_pending_decision_and_conflicting_replay(storage, monkeypatch):
    company = "requirement-review-negative-" + uuid4().hex
    request = proposal_request(storage, company, monkeypatch)
    proposal = create_requirement_proposal(
        storage, company, request, actor_id="operator-a"
    ).proposal
    with pytest.raises(LookupError, match="REQUIREMENT_DECISION_NOT_FOUND"):
        read_requirement_comparison(storage, company, proposal.proposal_id)
    with pytest.raises(LookupError, match="REQUIREMENT_PROPOSAL_NOT_FOUND"):
        read_requirement_proposal(storage, "foreign-" + company, proposal.proposal_id)
    first = DecisionRequest(
        proposal_id=proposal.proposal_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        normative_document=False,
        position_association=False,
        confirmed_rows=(),
    )
    create_requirement_decision(storage, company, first, actor_id="reviewer-a")
    changed = first.model_copy(update={"normative_document": True})
    with pytest.raises(ValueError, match="REQUIREMENT_DECISION_CONFLICT"):
        create_requirement_decision(storage, company, changed, actor_id="reviewer-a")
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_requirement_review_proposals)) == 0
