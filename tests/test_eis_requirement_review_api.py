"""Requirement review endpoints enforce roles, strict bodies and exact forwarding."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import httpx

from procurement.access import AccessRole
from procurement.api import app as api_module
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.sources.eis_requirement_review import (
    DecisionRequest,
    ProposalRequest,
    RequirementComparison,
    RequirementDecision,
    RequirementProposal,
)
from procurement.storage.eis_requirement_review import (
    SavedRequirementDecision,
    SavedRequirementProposal,
)
from procurement.storage.repository import PostgresStorage

DATA = json.loads(
    (Path(__file__).parent / "fixtures" / "eis-requirement-review.json").read_text(encoding="utf-8")
)
PROPOSAL_REQUEST = ProposalRequest.model_validate(DATA["proposal_request"])
PROPOSAL = RequirementProposal.model_validate(DATA["proposal"])
DECISION_REQUEST = DecisionRequest.model_validate(DATA["decision_request"])
DECISION = RequirementDecision.model_validate(DATA["decision"])
COMPARISON = RequirementComparison.model_validate(DATA["comparison"])
BASE = "/v1/tender-discovery/eis/index/requirement-review"


class Auth:
    def __init__(self, role, actor="actor-a"):
        self.role = role
        self.actor = actor

    async def authenticate(self, credential):
        return (
            Principal(company_id="tenant-a", actor_id=self.actor, access_role=self.role)
            if credential == "test"
            else None
        )


def send(path, payload, role=AccessRole.OPERATOR, actor="actor-a", authorization="Bearer test"):
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(role, actor)),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def run():
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path, content=content, headers=headers)

    return asyncio.run(run())


def test_proposal_decision_read_and_comparison_forward_exact_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module,
        "create_requirement_proposal",
        lambda storage, company, request, actor_id: (
            calls.append(("proposal", company, request, actor_id)),
            SavedRequirementProposal(proposal=PROPOSAL, created=True),
        )[1],
    )
    response = send(BASE + "/proposals", PROPOSAL_REQUEST.model_dump(mode="json"))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(
        api_module,
        "create_requirement_decision",
        lambda storage, company, request, actor_id: (
            calls.append(("decision", company, request, actor_id)),
            SavedRequirementDecision(decision=DECISION, created=True),
        )[1],
    )
    assert (
        send(
            BASE + "/decisions",
            DECISION_REQUEST.model_dump(mode="json"),
            AccessRole.COMPLETENESS_REVIEWER,
            "reviewer-a",
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        api_module,
        "read_requirement_proposal",
        lambda storage, company, proposal_id: SavedRequirementProposal(
            proposal=PROPOSAL, created=False
        ),
    )
    assert send(BASE + "/proposals/read", {"proposal_id": PROPOSAL.proposal_id}).status_code == 200
    monkeypatch.setattr(api_module, "read_requirement_comparison", lambda *a: COMPARISON)
    assert send(BASE + "/comparison", {"proposal_id": PROPOSAL.proposal_id}).status_code == 200
    assert calls[0] == ("proposal", "tenant-a", PROPOSAL_REQUEST, "actor-a")
    assert calls[1] == ("decision", "tenant-a", DECISION_REQUEST, "reviewer-a")


def test_roles_auth_and_invalid_bodies_block_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(api_module, "create_requirement_proposal", lambda *a, **k: calls.append(1))
    valid = PROPOSAL_REQUEST.model_dump(mode="json")
    responses = (
        send(BASE + "/proposals", valid, AccessRole.AUDITOR),
        send(BASE + "/proposals", valid, authorization=None),
        send(BASE + "/proposals", b'{"rows":[],"rows":[]}'),
        send(BASE + "/proposals", b"{" + b" " * 4096 + b"}"),
        send(BASE + "/decisions", DECISION_REQUEST.model_dump(mode="json"), AccessRole.OPERATOR),
    )
    assert all(item.status_code in {401, 403, 413, 422} for item in responses)
    assert all(item.headers["cache-control"] == "no-store" for item in responses)
    assert calls == []


def test_review_openapi_schemas_are_fully_inlined():
    def refs(value):
        if isinstance(value, dict):
            return [
                item
                for key, nested in value.items()
                for item in ([nested] if key in {"$ref", "$defs"} else refs(nested))
            ]
        if isinstance(value, list):
            return [item for nested in value for item in refs(nested)]
        return []

    for schema in (
        api_module.EIS_REQUIREMENT_PROPOSAL_OPENAPI_SCHEMA,
        api_module.EIS_REQUIREMENT_PROPOSAL_READ_OPENAPI_SCHEMA,
        api_module.EIS_REQUIREMENT_DECISION_OPENAPI_SCHEMA,
        api_module.EIS_REQUIREMENT_COMPARISON_OPENAPI_SCHEMA,
    ):
        assert refs(schema) == []
