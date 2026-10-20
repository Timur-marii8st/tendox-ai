from datetime import timedelta

import pytest

from procurement.sources import eis_requirement_review as r
from procurement.sources.eis_requirement_preview import build_requirement_preview, canonical_sha
from procurement.sources.eis_requirement_table import EISRequirementTable, RequirementTableRow
from test_eis_requirement_preview import NOW, cell
from test_eis_requirement_preview import preview as old_preview
from test_eis_supplier_product import build, details

PROPOSAL = "11111111-1111-4111-8111-111111111111"
DECISION = "22222222-2222-4222-8222-222222222222"


def preview(required: str = "А4", actual: str = "A4", duplicate: bool = False):
    base = old_preview()
    observed = details("Формат", *(["Формат бумаги"] if duplicate else []))
    observed = observed.model_copy(
        update={
            "characteristics": tuple(
                f.model_copy(update={"value_raw": actual}) for f in observed.characteristics
            )
        }
    )
    product = build(base.product.position, observed)
    cells = (cell(2, 1, "Формат", 5), cell(2, 3, required, 6))
    manual = (cell(3, 1, "Масса бумаги", 7), cell(3, 3, "≥ 80 и < 90", 8))
    context = (cell(4, 1, "Дополнительные характеристики", 9),)
    rows = (
        RequirementTableRow(
            source_row=2, kind="CHARACTERISTIC", cells=cells, absent_columns=(2, 4, 5)
        ),
        RequirementTableRow(
            source_row=3,
            kind="CHARACTERISTIC",
            cells=manual,
            absent_columns=(2, 4, 5),
            numeric_hints=({"operator": ">=", "value": "80"}, {"operator": "<", "value": "90"}),
        ),
        RequirementTableRow(
            source_row=4, kind="CONTEXT_ONLY", cells=context, absent_columns=(2, 3, 4, 5)
        ),
    )
    table = EISRequirementTable(
        document_sha256=base.table.document_sha256,
        table_index=1,
        header=base.table.header,
        rows=rows,
        row_count=3,
        cell_count=10,
        total_characters=sum(len(c.text) for c in (*base.table.header, *cells, *manual, *context)),
    )
    payload = base.model_dump(exclude={"preview_sha256"})
    payload.update(product=product, product_report_sha256=canonical_sha(product), table=table)
    return build_requirement_preview(**payload)


def proposal(required="А4", actual="A4", mandatory=True, duplicate=False):
    basis = preview(required, actual, duplicate)
    request = r.ProposalRequest(
        preview=basis.request,
        expected_preview_sha256=basis.preview_sha256,
        rows=(
            r.RowChoice(source_row=2, mode="PAPER_FORMAT", supplier_index=1, mandatory=mandatory),
            r.RowChoice(source_row=3, mode="MANUAL"),
            r.RowChoice(source_row=4, mode="MANUAL"),
        ),
    )
    return r.build_requirement_proposal(
        company_id="tenant-a",
        proposal_id=PROPOSAL,
        request=request,
        preview=basis,
        prepared_by="preparer",
        prepared_at=NOW,
    )


def decision(
    proposed=None,
    confirmed=(2,),
    normative=True,
    association=True,
    reviewer="reviewer",
    company="tenant-a",
):
    proposed = proposed or proposal()
    request = r.DecisionRequest(
        proposal_id=PROPOSAL,
        expected_proposal_sha256=proposed.proposal_sha256,
        normative_document=normative,
        position_association=association,
        confirmed_rows=confirmed,
    )
    return r.build_requirement_decision(
        company_id=company,
        decision_id=DECISION,
        request=request,
        proposal=proposed,
        reviewed_by=reviewer,
        reviewed_at=NOW + timedelta(seconds=1),
    )


def test_format_pass_keeps_manual_context_and_global_unknown():
    result = r.build_requirement_comparison(decision())
    assert [row.status for row in result.rows] == ["PASS", "UNKNOWN", "UNKNOWN"]
    assert (
        result.rows[0].check.requirement.provenance.document_id
        == result.decision.proposal.preview.table.document_sha256
    )
    assert (
        result.rows[0].supplier_provenance.document_id
        == result.decision.proposal.preview.product.details.html_sha256
    )
    assert result.technical == result.full_tspec_completeness == result.participation == "UNKNOWN"
    assert not result.candidate_blocked
    assert r.RequirementComparison.model_validate_json(result.model_dump_json()) == result


def test_mandatory_format_failure_blocks_no_fulltechnicalpass():
    result = r.build_requirement_comparison(decision(proposal(actual="B4")))
    assert result.rows[0].status == "FAIL" and result.candidate_blocked
    optional = r.build_requirement_comparison(decision(proposal(actual="B4", mandatory=False)))
    assert optional.rows[0].status == "FAIL" and not optional.candidate_blocked


@pytest.mark.parametrize(
    "kwargs", [{"confirmed": ()}, {"normative": False}, {"association": False}]
)
def test_unconfirmed_is_unknown(kwargs):
    result = r.build_requirement_comparison(decision(**kwargs))
    assert all(row.status == "UNKNOWN" for row in result.rows)
    assert not result.candidate_blocked


@pytest.mark.parametrize(
    "kwargs",
    [{"reviewer": "preparer"}, {"company": "tenant-b"}, {"confirmed": (3,)}, {"confirmed": (2, 2)}],
)
def test_selfreview_tenant_and_nonexecutable_confirmation_rejected(kwargs):
    with pytest.raises(ValueError):
        decision(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actual": "С4"},
        {"actual": "A 4"},
        {"required": "не ниже A4"},
        {"required": "A11"},
        {"duplicate": True},
        {"mandatory": None},
    ],
)
def test_closed_format_grammar_and_duplicate_source(kwargs):
    with pytest.raises(ValueError):
        proposal(**kwargs)


def test_omitted_rows_digest_and_forged_model_copy_rejected():
    proposed = proposal()
    incomplete = proposed.request.model_copy(update={"rows": proposed.request.rows[:1]})
    with pytest.raises(ValueError):
        r.build_requirement_proposal(
            company_id="tenant-a",
            proposal_id=PROPOSAL,
            request=incomplete,
            preview=proposed.preview,
            prepared_by="preparer",
            prepared_at=NOW,
        )
    with pytest.raises(ValueError):
        decision(proposed.model_copy(update={"proposal_sha256": "a" * 64}))
    result = r.build_requirement_comparison(decision())
    data = result.model_dump(mode="json")
    data["rows"][1]["status"] = "PASS"
    data["comparison_sha256"] = canonical_sha(
        {k: v for k, v in data.items() if k != "comparison_sha256"}
    )
    with pytest.raises(ValueError):
        r.RequirementComparison.model_validate(data)
    nested = proposed.preview.model_copy(update={"technical": "PASS"})
    with pytest.raises(ValueError):
        r.build_requirement_proposal(
            company_id="tenant-a",
            proposal_id=PROPOSAL,
            request=proposed.request,
            preview=nested,
            prepared_by="preparer",
            prepared_at=NOW,
        )


def test_deterministic_immutable_digests():
    assert proposal() == proposal()
    assert decision() == decision()
    assert r.build_requirement_comparison(decision()) == r.build_requirement_comparison(decision())


@pytest.mark.parametrize(
    "identity", ["", " ", " preparer", "preparer ", "\tpreparer", "reviewer\n"]
)
def test_actor_identities_rejected_without_silent_normalization(identity):
    proposed = proposal()
    with pytest.raises(ValueError):
        r.build_requirement_proposal(
            company_id="tenant-a",
            proposal_id=PROPOSAL,
            request=proposed.request,
            preview=proposed.preview,
            prepared_by=identity,
            prepared_at=NOW,
        )
    with pytest.raises(ValueError):
        decision(proposed, reviewer=identity)


def test_company_identity_must_be_canonical():
    proposed = proposal()
    with pytest.raises(ValueError):
        r.build_requirement_proposal(
            company_id=" tenant-a ",
            proposal_id=PROPOSAL,
            request=proposed.request,
            preview=proposed.preview,
            prepared_by="preparer",
            prepared_at=NOW,
        )
