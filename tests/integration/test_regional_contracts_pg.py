"""Synthetic PG admission, tenant isolation, immutable sources and atomic replay."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_characteristic_pair_pg import storage as storage_fixture

from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
from procurement.storage.eis_223_regions import register_region_catalog
from procurement.storage.eis_contract_results import store_contract_observation
from procurement.storage.eis_contract_schema import (
    contract_evidence,
    contract_observation_sources,
    contract_observations,
)
from procurement.storage.models import audit_events
from test_eis_223_regions import catalog_html
from test_eis_contract_results import NOW, NUMBER, REGISTRY, bundle, contract_xml, notice_xml

storage = storage_fixture
TABLES = (contract_evidence, contract_observations, contract_observation_sources)


def sources(storage, company):
    raw = catalog_html().decode().replace("Region 77", "г. Москва").encode()
    register_region_catalog(
        storage,
        company,
        raw,
        source_url=REGION_SELECTOR_URL,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at=NOW,
        actor_id="test",
    )
    return bundle("RGK", REGISTRY, contract_xml()), bundle("PRIZ", NUMBER, notice_xml())


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t)) for t in (*TABLES, audit_events)
        )


def test_sources_replay_idempotently_and_remain_unknown_without_currentness(storage):
    company = "contract-" + uuid4().hex
    rgk, priz = sources(storage, company)
    receipt = store_contract_observation(storage, company, rgk, priz, actor="test")
    before = counts(storage, company)
    assert store_contract_observation(storage, company, rgk, priz, actor="test") == receipt
    assert counts(storage, company) == before
    with storage.transaction(company, consistent_read=True) as conn:
        row = conn.execute(select(contract_observations)).mappings().one()
        assert row["payload"]["current_result"]["value"] is None
        assert "SOURCE_CURRENT_HISTORY_UNCONFIRMED" in row["payload"]["qualification_reasons"]
        assert row["payload_sha256"]
    other = "contract-other-" + uuid4().hex
    assert counts(storage, other) == (0, 0, 0, 0)
    for table in TABLES:
        for change in (update(table).values(company_id=other), delete(table)):
            with pytest.raises(DBAPIError), storage.transaction(company) as conn:
                conn.execute(change)
    with pytest.raises(DBAPIError), storage.transaction(other) as conn:
        conn.execute(
            insert(contract_evidence).values(
                company_id=company,
                sha256=hashlib.sha256(b"x").hexdigest(),
                kind="JSON",
                content=b"x",
            )
        )


def test_corrupted_content_and_cross_tenant_source_link_roll_back(storage):
    company = "contract-invalid-" + uuid4().hex
    rgk, priz = sources(storage, company)
    receipt = store_contract_observation(storage, company, rgk, priz, actor="test")
    before = counts(storage, company)
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(contract_evidence).values(
                company_id=company,
                sha256="a" * 64,
                kind="JSON",
                content=b"x",
            )
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(contract_observation_sources).values(
                company_id=company,
                receipt_id=receipt,
                sha256="b" * 64,
            )
        )
    assert counts(storage, company) == before


def test_concurrent_identical_receipts_do_not_duplicate_observation_or_audit(storage):
    company = "contract-race-" + uuid4().hex
    rgk, priz = sources(storage, company)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: store_contract_observation(storage, company, rgk, priz, actor="test"),
                range(2),
            )
        )
    assert results[0] == results[1]
    c = counts(storage, company)
    assert c[1] == 1 and c[3] == 2  # catalogue audit + exactly one observation audit


def test_automatic_selection_is_exact_read_only_and_new_market_change_hides_old_row(storage):
    from dataclasses import replace
    from datetime import date, timedelta
    from io import BytesIO
    from zipfile import ZipFile

    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.storage.beta_quote import BetaQuoteRef
    from procurement.storage.eis_contract_results import (
        automatic_history,
        record_contract_refresh_failure,
    )
    from procurement.storage.eis_notice_index import (
        EisReadyWindow,
        ingest_ready_window,
        preflight_ready_window,
    )
    from test_eis_contract_results import current_cards

    company = "contract-selection-" + uuid4().hex
    rgk, priz = sources(storage, company)
    target = "9" * 19
    out = BytesIO()
    with ZipFile(out, "w") as zipped:
        zipped.writestr("notice.xml", notice_xml(number=target))
    window = EisReadyWindow(
        EisDateSelection("77", date(2026, 10, 1), 3).window_key,
        "a" * 64,
        1,
        (out.getvalue(),),
    )
    record = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="test")
    ref = BetaQuoteRef(
        notice=dict(
            law="44",
            purchase_number=target,
            version_number=1,
            notice_xml_sha256=record.xml_sha256,
        )
    )
    c, n = current_cards()
    store_contract_observation(
        storage, company, rgk, priz, actor="test", contract_card=c, notice_card=n
    )
    before = counts(storage, company)
    found = automatic_history(storage, company, ref, now=NOW + timedelta(minutes=1))
    assert len(found.observations) == 1
    assert found.cohort.region == "г. Москва" and found.cohort.quantity == 10
    assert counts(storage, company) == before
    assert found.observations[0].current_result.value is True
    held = record_contract_refresh_failure(
        storage,
        company,
        REGISTRY,
        actor="test",
        reason="HISTORY_REFRESH_FAILED",
        checked_at=NOW + timedelta(minutes=1),
    )
    assert held is not None
    after_failure = automatic_history(storage, company, ref, now=NOW + timedelta(minutes=1))
    assert len(after_failure.observations) == 1
    assert after_failure.observations[0].current_result.value is None
    assert "HISTORY_REFRESH_FAILED" in after_failure.observations[0].qualification_reasons
    assert (
        record_contract_refresh_failure(
            storage,
            company + "-other",
            REGISTRY,
            actor="test",
            reason="HISTORY_REFRESH_FAILED",
            checked_at=NOW + timedelta(minutes=1),
        )
        is None
    )
    changed_rgk = bundle("RGK", REGISTRY, contract_xml(region="Region 50"))
    changed_priz = bundle("PRIZ", NUMBER, notice_xml(region="Region 50"))
    later = NOW + timedelta(minutes=2)
    changed_rgk = replace(changed_rgk, requested_at=later, checked_at=later)
    changed_priz = replace(changed_priz, requested_at=later, checked_at=later)
    store_contract_observation(storage, company, changed_rgk, changed_priz, actor="test")
    assert not automatic_history(storage, company, ref, now=later).observations

    # Same-time conflicting source receipts cannot be ordered by their hashes.
    tie_time = later + timedelta(minutes=1)
    tie_priz = replace(priz, requested_at=tie_time, checked_at=tie_time)
    for price in ("600", "700"):
        conflicting_rgk = replace(
            bundle("RGK", REGISTRY, contract_xml(price=price)),
            requested_at=tie_time,
            checked_at=tie_time,
        )
        store_contract_observation(storage, company, conflicting_rgk, tie_priz, actor="test")
    with storage.transaction(company, consistent_read=True) as conn:
        latest = (
            conn.execute(
                select(contract_observations).where(
                    contract_observations.c.company_id == company,
                    contract_observations.c.checked_at == tie_time,
                )
            )
            .mappings()
            .all()
        )
    assert len(latest) == 2
    assert not automatic_history(storage, company, ref, now=tie_time).observations


def test_single_source_customer_binds_read_only_history_without_granting_forecast(storage):
    from io import BytesIO
    from zipfile import ZipFile

    from procurement.storage.beta_quote import BetaQuoteRef, history_report
    from procurement.storage.eis_contract_results import automatic_history
    from procurement.storage.eis_notice_index import (
        EisReadyWindow,
        ingest_ready_window,
        preflight_ready_window,
    )
    from test_eis_contract_customer_scope import single_customer

    company = "single-customer-" + uuid4().hex
    sources(storage, company)
    raw = single_customer().replace(
        b"</e:purchaseNumber>",
        b"</e:purchaseNumber><e:purchaseObjectInfo>Synthetic paper</e:purchaseObjectInfo>",
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zipped:
        zipped.writestr("notice.xml", raw)
    window = EisReadyWindow(
        "getDocsIP/PRIZ/by-number/0100000000026000001", "a" * 64, 1, (buffer.getvalue(),)
    )
    record = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="test")
    ref = BetaQuoteRef(
        notice=dict(
            law="44",
            purchase_number=record.purchase_number,
            version_number=record.version_number,
            notice_xml_sha256=record.xml_sha256,
        )
    )
    before = counts(storage, company)
    history = automatic_history(storage, company, ref, now=NOW)
    assert history.source_reasons == ()
    assert history.cohort.region == "г. Москва" and history.cohort.quantity == 3
    assert history.cohort.unit == "796"
    assert history.cohort.source.document_id == record.xml_sha256
    assert "customerRequirementInfo[1]/contractConditionsInfo" in history.cohort.source.locator
    report = history_report(storage, company, ref, actor="test", now=NOW)
    assert report.history.status == "UNKNOWN" and report.history.sample_size == 0
    assert report.history.realistic_discount is report.history.conservative_discount is None
    assert counts(storage, company) == before


def test_current_card_manifest_and_source_proof_are_retained_in_same_transaction(storage):
    from procurement.domain.actions import payload_digest
    from test_eis_contract_results import current_cards

    company = "contract-cards-" + uuid4().hex
    rgk, priz = sources(storage, company)
    c, n = current_cards()
    receipt = store_contract_observation(
        storage,
        company,
        rgk,
        priz,
        actor="test",
        contract_card=c,
        notice_card=n,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        row = (
            conn.execute(
                select(contract_observations).where(
                    contract_observations.c.receipt_id == receipt,
                )
            )
            .mappings()
            .one()
        )
        assert row["payload"]["current_result"]["value"] is True
        proof = row["payload"]["current_result"]["source"]["document_id"]
        retained = (
            conn.execute(
                select(contract_evidence).where(
                    contract_evidence.c.sha256 == proof,
                )
            )
            .mappings()
            .one()
        )
        assert retained["kind"] == "JSON"
        import json

        assert payload_digest(json.loads(bytes(retained["content"]))) == proof
        assert (
            conn.scalar(
                select(func.count())
                .select_from(contract_evidence)
                .where(
                    contract_evidence.c.kind == "HTML",
                )
            )
            == 2
        )
    before = counts(storage, company)
    with pytest.raises(ValueError, match="PAIR_REQUIRED"):
        store_contract_observation(storage, company, rgk, priz, actor="test", contract_card=c)
    assert counts(storage, company) == before


def test_failed_first_refresh_is_durable_backoff_and_does_not_starve_other_registries(storage):
    import importlib.util
    from datetime import timedelta
    from pathlib import Path

    from procurement.storage.eis_contract_results import record_contract_refresh_failure

    spec = importlib.util.spec_from_file_location(
        "contract_refresh_job",
        Path(__file__).resolve().parents[2] / "scripts/server-eis-contract-refresh.py",
    )
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    company = "contract-initial-failure-" + uuid4().hex
    assert job.due_registry(storage, company, (REGISTRY,), now=NOW) == REGISTRY
    assert (
        record_contract_refresh_failure(
            storage,
            company,
            REGISTRY,
            actor="test",
            reason="HISTORY_REFRESH_FAILED",
            checked_at=NOW,
        )
        is None
    )
    assert counts(storage, company) == (1, 0, 0, 1)
    assert job.due_registry(storage, company, (REGISTRY,), now=NOW + timedelta(minutes=9)) is None
    assert (
        job.due_registry(storage, company, (REGISTRY,), now=NOW + timedelta(minutes=10)) == REGISTRY
    )
    other = "3" * 19
    assert job.due_registry(storage, company, (REGISTRY, other), now=NOW) == other
    assert job.due_registry(storage, company + "-other", (REGISTRY,), now=NOW) == REGISTRY


def test_pending_refresh_hides_prior_pass_until_newer_confirmed_receipt(storage):
    from dataclasses import replace
    from datetime import timedelta

    from procurement.storage.eis_contract_results import record_contract_refresh_failure
    from test_eis_contract_results import current_cards

    company = "contract-pending-" + uuid4().hex
    rgk, priz = sources(storage, company)
    c, n = current_cards()
    good = store_contract_observation(
        storage, company, rgk, priz, actor="test", contract_card=c, notice_card=n
    )
    pending = record_contract_refresh_failure(
        storage,
        company,
        REGISTRY,
        actor="test",
        reason="HISTORY_REFRESH_IN_PROGRESS",
        checked_at=NOW + timedelta(seconds=1),
    )
    assert pending is not None and pending != good
    with storage.transaction(company, consistent_read=True) as conn:
        payload = conn.scalar(
            select(contract_observations.c.payload).where(
                contract_observations.c.company_id == company,
                contract_observations.c.receipt_id == pending,
            )
        )
        assert payload["current_result"]["value"] is None
        assert "HISTORY_REFRESH_IN_PROGRESS" in payload["qualification_reasons"]
    later = NOW + timedelta(seconds=2)
    fresh = store_contract_observation(
        storage,
        company,
        replace(rgk, requested_at=later, checked_at=later),
        replace(priz, requested_at=later, checked_at=later),
        actor="test",
        contract_card=replace(c, requested_at=later, checked_at=later),
        notice_card=replace(n, requested_at=later, checked_at=later),
    )
    with storage.transaction(company, consistent_read=True) as conn:
        latest = (
            conn.execute(
                select(contract_observations)
                .where(contract_observations.c.company_id == company)
                .order_by(contract_observations.c.checked_at.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
        assert latest["receipt_id"] == fresh
        assert latest["payload"]["current_result"]["value"] is True
