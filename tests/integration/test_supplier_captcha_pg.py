from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_serp_pg import capture
from test_eis_supplier_serp_pg import storage as storage_fixture

from procurement.sources.supplier_serp import SearchEngine, parse_supplier_serp, source_url
from procurement.storage import eis_supplier_serp as serp
from procurement.storage.models import audit_events
from procurement.storage.supplier_captcha import (
    VERIFIED_EVENT,
    admit_captcha,
    audit_captcha_end,
    recovery_receipts,
)

storage = storage_fixture


def test_exact_admission_verified_receipt_and_single_refresh(storage, monkeypatch):
    company = "captcha-" + uuid4().hex
    request = ingest(storage, company)
    calls = []
    monkeypatch.setattr(serp, "observe_supplier_serp", lambda query, **kwargs: capture(query))
    saved = serp.prepare_supplier_serp(storage, company, request, actor_id="operator")
    with pytest.raises(ValueError, match="REFRESH_COOLDOWN"):
        serp.prepare_supplier_serp(storage, company, request, actor_id="operator", refresh=True)
    report = admit_captcha(
        storage, company, "operator", request, saved.report.run_id, SearchEngine.GOOGLE
    )
    with pytest.raises((LookupError, ValueError)):
        admit_captcha(
            storage,
            "foreign-" + company,
            "operator",
            request,
            saved.report.run_id,
            SearchEngine.GOOGLE,
        )
    with pytest.raises(ValueError, match="OBSERVATION_STALE"):
        admit_captcha(storage, company, "operator", request, str(uuid4()), SearchEngine.GOOGLE)
    with pytest.raises(ValueError, match="VERIFICATION_INVALID"):
        audit_captcha_end(
            storage,
            company,
            "operator",
            report,
            SearchEngine.GOOGLE,
            str(uuid4()),
            "VERIFIED",
            report.batch.attempts[2],
        )
    dom = b'<div id="search"><div class="MjjYud"><a href="https://supplier.ru/paper/"><h3>Supplier</h3></a></div></div>'
    attempt = parse_supplier_serp(
        SearchEngine.GOOGLE,
        report.query,
        dom,
        final_url=source_url(SearchEngine.GOOGLE, report.query),
        observed_at=datetime.now(UTC),
    )
    assert attempt.status == "COMPLETED"
    audit_captcha_end(
        storage, company, "operator", report, SearchEngine.GOOGLE, str(uuid4()), "VERIFIED", attempt
    )
    with storage.transaction(company, consistent_read=True) as conn:
        receipts = recovery_receipts(conn, company, datetime.now(UTC))
        assert receipts[0]["run_id"] == report.run_id
        assert receipts[0]["dom_sha256"] == attempt.dom_sha256
        assert receipts[0]["participation"] == "UNKNOWN"
    monkeypatch.setattr(
        serp,
        "observe_supplier_serp",
        lambda query, **kwargs: (calls.append(kwargs), capture(query))[1],
    )
    fresh = serp.prepare_supplier_serp(storage, company, request, actor_id="operator", refresh=True)
    assert fresh.created
    assert SearchEngine.GOOGLE not in calls[-1]["cooldowns"]
    assert SearchEngine.YANDEX in calls[-1]["cooldowns"]
    with pytest.raises(ValueError, match="REFRESH_COOLDOWN"):
        serp.prepare_supplier_serp(storage, company, request, actor_id="operator", refresh=True)
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == VERIFIED_EVENT)
            )
            == 0
        )


def test_cooldown_and_completed_results_cannot_authorize_manual_navigation(storage, monkeypatch):
    company = "captcha-negative-" + uuid4().hex
    request = ingest(storage, company)
    monkeypatch.setattr(serp, "observe_supplier_serp", lambda query, **kwargs: capture(query))
    saved = serp.prepare_supplier_serp(storage, company, request, actor_id="operator")
    with pytest.raises(ValueError, match="OBSERVATION_STALE"):
        admit_captcha(storage, company, "operator", request, saved.report.run_id, SearchEngine.BING)
