"""One-registry refresh orchestration with synthetic sources, no DB or network."""

import asyncio
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from procurement.sources import eis_contract_worker as worker
from procurement.sources.eis_contract_cards import CardSnapshot
from procurement.sources.eis_contract_sync import CardCaptureError
from procurement.sources.eis_feed_sync import EisSourceError, EisSyncError
from test_eis_contract_results import NUMBER, REGISTRY, bundle, contract_xml, notice_xml, qualify

_REAL_READBACK = worker._stored_observation


class ReadbackStorage:
    def __init__(self, row):
        self.row = row
        self.parameters = None

    @contextmanager
    def transaction(self, company, *, consistent_read):
        assert company == "tenant-a" and consistent_read is True
        yield self

    def exec_driver_sql(self, statement):
        assert statement == "SET LOCAL statement_timeout='5000ms'"

    def execute(self, statement):
        self.parameters = statement.compile().params
        assert "payload_sha256" in str(statement)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))


@pytest.fixture
def harness(monkeypatch):
    now = datetime.now(UTC)
    rgk = replace(
        bundle("RGK", REGISTRY, contract_xml()),
        requested_at=now + timedelta(milliseconds=1),
        checked_at=now + timedelta(milliseconds=1),
    )
    priz = replace(
        bundle("PRIZ", NUMBER, notice_xml()),
        requested_at=now + timedelta(milliseconds=1),
        checked_at=now + timedelta(milliseconds=1),
    )
    events = []
    stored = SimpleNamespace(
        company_id="tenant-a",
        purchase_number=NUMBER,
        qualification_reasons=(),
        current_result=SimpleNamespace(value=True),
    )
    state = SimpleNamespace(
        rgk=rgk,
        priz=priz,
        events=events,
        clock=now,
        stored=stored,
        pre_reasons=("SOURCE_CURRENT_HISTORY_UNCONFIRMED",),
        final_reasons=(),
        invalidations=[],
        holds=[],
        cards=[],
        store_count=0,
        readback_count=0,
    )
    monkeypatch.setattr(worker, "_utcnow", lambda: state.clock)

    async def fetch(transport, token, *, subsystem, number):
        assert transport is state.transport
        assert token == "not-a-real-token"
        events.append(("fetch", subsystem, number))
        state.clock += timedelta(milliseconds=2)
        return state.rgk if subsystem == "RGK" else state.priz

    async def capture(*, number, kind):
        events.append(("card", kind, number))
        card = CardSnapshot(
            "https://zakupki.gov.ru/",
            "https://zakupki.gov.ru/",
            200,
            state.clock,
            state.clock,
            b"<html>synthetic</html>",
        )
        state.cards.append(card)
        return card

    def catalog(storage, company):
        assert storage is state.storage and company == "tenant-a"
        events.append(("catalog",))
        return "synthetic-catalog"

    def qualify(company, contract, notice, catalog, **kwargs):
        assert company == "tenant-a" and contract is state.rgk and notice is state.priz
        assert catalog == "synthetic-catalog"
        events.append(("qualify", bool(kwargs)))
        reasons = state.final_reasons if kwargs else state.pre_reasons
        return SimpleNamespace(
            qualification_reasons=reasons, current_result=SimpleNamespace(value=not reasons)
        )

    def store(storage, company, contract, notice, *, actor, **kwargs):
        assert storage is state.storage and company == "tenant-a" and actor == "worker"
        assert contract is state.rgk and notice is state.priz
        assert kwargs == {"contract_card": state.cards[0], "notice_card": state.cards[1]}
        events.append(("store",))
        state.store_count += 1
        return "receipt-good"

    def readback(storage, company, registry, receipt):
        assert storage is state.storage and (company, registry, receipt) == (
            "tenant-a",
            REGISTRY,
            "receipt-good",
        )
        events.append(("readback",))
        state.readback_count += 1
        return state.stored

    def invalidate(storage, company, registry, **kwargs):
        assert storage is state.storage and company == "tenant-a" and registry == REGISTRY
        if kwargs.get("reason") == "HISTORY_REFRESH_IN_PROGRESS":
            assert kwargs == {
                "actor": "worker",
                "reason": "HISTORY_REFRESH_IN_PROGRESS",
                "checked_at": state.clock,
            }
            events.append(("hold",))
            state.holds.append(kwargs)
            return "receipt-pending"
        assert kwargs == {
            "actor": "worker",
            "reason": "HISTORY_REFRESH_FAILED",
            "checked_at": state.clock,
        }
        events.append(("invalidate",))
        state.invalidations.append(kwargs)
        return "receipt-failed"

    state.storage, state.transport = object(), object()
    state.fetch, state.capture, state.invalidate = fetch, capture, invalidate
    monkeypatch.setattr(worker, "fetch_official_bundle", fetch)
    monkeypatch.setattr(worker, "capture_current_card", capture)
    monkeypatch.setattr(worker.ledger, "read_region_catalog", catalog)
    monkeypatch.setattr(worker.ledger, "qualify_contract", qualify)
    monkeypatch.setattr(worker.ledger, "store_contract_observation", store)
    monkeypatch.setattr(worker.ledger, "record_contract_refresh_failure", invalidate)
    monkeypatch.setattr(worker, "_stored_observation", readback)
    return state


def run(state, **kwargs):
    return asyncio.run(
        worker.refresh_contract_observation(
            state.storage,
            "tenant-a",
            REGISTRY,
            actor="worker",
            transport=state.transport,
            token="not-a-real-token",
            **kwargs,
        )
    )


def test_full_refresh_validates_pair_before_cards_and_returns_only_stored_pass(harness):
    result = run(harness)
    assert result == worker.ContractRefreshResult("PASS", REGISTRY, NUMBER, "receipt-good", ())
    assert harness.events == [
        ("hold",),
        ("fetch", "RGK", REGISTRY),
        ("fetch", "PRIZ", NUMBER),
        ("catalog",),
        ("qualify", False),
        ("card", "CONTRACT", REGISTRY),
        ("card", "EF_DOCUMENTS", NUMBER),
        ("qualify", True),
        ("store",),
        ("readback",),
    ]
    assert not harness.invalidations
    with pytest.raises(FrozenInstanceError):
        result.status = "UNKNOWN"


def test_zk_routes_to_observed_documents_card(harness):
    harness.priz = replace(
        bundle(
            "PRIZ", NUMBER, notice_xml().replace(b"epNotificationEF2020", b"epNotificationEZK2020")
        ),
        requested_at=harness.clock + timedelta(milliseconds=1),
        checked_at=harness.clock + timedelta(milliseconds=1),
    )
    assert run(harness).status == "PASS"
    assert ("card", "EZK_DOCUMENTS", NUMBER) in harness.events


def test_eok_is_explicit_unknown_and_invalidates_before_cards(harness):
    harness.priz = replace(
        bundle(
            "PRIZ", NUMBER, notice_xml().replace(b"epNotificationEF2020", b"epNotificationEOK2020")
        ),
        requested_at=harness.clock + timedelta(milliseconds=1),
        checked_at=harness.clock + timedelta(milliseconds=1),
    )
    result = run(harness)
    assert result.status == "UNKNOWN"
    assert result.reasons == ("HISTORY_NOTICE_KIND_UNSUPPORTED",)
    assert not harness.cards and not harness.store_count
    assert len(harness.invalidations) == 1


def test_original_v0_purchase_is_used_not_latest_revision_purchase(harness):
    harness.rgk = replace(
        bundle("RGK", REGISTRY, contract_xml(version=1, number="3" * 19), contract_xml()),
        requested_at=harness.clock + timedelta(milliseconds=1),
        checked_at=harness.clock + timedelta(milliseconds=1),
    )
    harness.pre_reasons = (
        "CONTRACT_COMMERCIAL_SCOPE_CHANGED",
        "SOURCE_CURRENT_HISTORY_UNCONFIRMED",
    )
    result = run(harness)
    assert ("fetch", "PRIZ", NUMBER) in harness.events
    assert result.reasons == ("CONTRACT_COMMERCIAL_SCOPE_CHANGED",)
    assert not harness.cards
    assert len(harness.invalidations) == 1


@pytest.mark.parametrize(
    "source", ["registry", "purchase", "original-missing", "original-conflict"]
)
def test_wrong_source_pair_never_reaches_cards_or_preserves_previous_pass(harness, source):
    if source == "registry":
        harness.rgk = replace(harness.rgk, number="9" * 19)
    elif source == "purchase":
        harness.priz = replace(harness.priz, number="9" * 19)
    else:
        docs = (
            [contract_xml(version=1)]
            if source == "original-missing"
            else [contract_xml(), contract_xml(price="699")]
        )
        harness.rgk = replace(
            bundle("RGK", REGISTRY, *docs),
            requested_at=harness.clock + timedelta(milliseconds=1),
            checked_at=harness.clock,
        )
    result = run(harness)
    assert result.status == "UNKNOWN"
    assert result.receipt_id == "receipt-failed"
    assert len(harness.invalidations) == 1
    assert not harness.cards and not harness.store_count


@pytest.mark.parametrize(
    "reason",
    [
        "CUSTOMER_PARTITION_QUANTITY_CONFLICT",
        "WHOLE_SOURCE_OBJECT_SCOPE_NOT_BOUND",
        "SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED",
        "NOTICE_CANCELLATION_EVENT_PRESENT",
    ],
)
def test_prequalifier_ignores_only_absent_current_card_proof(harness, reason):
    harness.pre_reasons = (reason, "SOURCE_CURRENT_HISTORY_UNCONFIRMED")
    result = run(harness)
    assert result.reasons == (reason,)
    assert not harness.cards
    assert len(harness.invalidations) == 1


def test_public_cooldown_waits_until_retry_and_preserves_shared_fetches(harness, monkeypatch):
    calls = 0
    sleeps = []

    async def capture(**kwargs):
        nonlocal calls
        calls += 1
        if calls in {1, 3}:
            raise CardCaptureError(
                "CARD_SOURCE_COOLDOWN", retry_at=harness.clock + timedelta(seconds=61)
            )
        return await harness.capture(**kwargs)

    async def sleep(delay):
        sleeps.append(delay)
        harness.clock += timedelta(seconds=delay)

    monkeypatch.setattr(worker, "capture_current_card", capture)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    result = run(harness)
    assert result.status == "PASS"
    assert sleeps == [61, 61]
    assert len([event for event in harness.events if event[0] == "fetch"]) == 2
    assert not harness.invalidations


@pytest.mark.parametrize("delta", [None, -1, 601])
def test_invalid_or_out_of_budget_retry_does_not_bypass_cooldown(harness, monkeypatch, delta):
    async def capture(**kwargs):
        raise CardCaptureError(
            "CARD_SOURCE_COOLDOWN",
            retry_at=None if delta is None else harness.clock + timedelta(seconds=delta),
        )

    monkeypatch.setattr(worker, "capture_current_card", capture)
    result = run(harness)
    assert result.status == "UNKNOWN" and result.reasons == ("CARD_SOURCE_COOLDOWN",)
    assert not harness.cards and not harness.store_count
    assert len(harness.invalidations) == 1


def test_monotonic_timeout_cancels_pending_fetch_and_invalidates(harness, monkeypatch):
    cancelled = []

    async def fetch(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(worker, "fetch_official_bundle", fetch)
    result = run(harness, timeout_seconds=0.01)
    assert result.status == "UNKNOWN"
    assert result.reasons == ("HISTORY_REFRESH_TIMEOUT",)
    assert cancelled == [True]
    assert len(harness.invalidations) == 1


def test_caller_cancellation_invalidates_then_propagates(harness, monkeypatch):
    async def fetch(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "fetch_official_bundle", fetch)
    with pytest.raises(asyncio.CancelledError):
        run(harness)
    assert len(harness.invalidations) == 1


@pytest.mark.parametrize("stage", ["bundle", "second-card"])
def test_source_snapshot_window_includes_all_transport_receipts(harness, monkeypatch, stage):
    if stage == "bundle":
        harness.rgk = replace(harness.rgk, requested_at=harness.clock - timedelta(seconds=601))
    else:

        async def capture(**kwargs):
            if kwargs["kind"] != "CONTRACT":
                harness.clock += timedelta(seconds=601)
            return await harness.capture(**kwargs)

        monkeypatch.setattr(worker, "capture_current_card", capture)
    result = run(harness)
    assert result.reasons == ("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED",)
    assert len(harness.invalidations) == 1 and not harness.store_count


@pytest.mark.parametrize(
    "reason",
    ["CARD_CACHED_RESPONSE", "SOURCE_CURRENT_CARD_MISMATCH", "CARD_RESPONSE_DATE_UNCONFIRMED"],
)
def test_final_current_card_failure_invalidates_without_storing_pass(harness, reason):
    harness.final_reasons = (reason,)
    result = run(harness)
    assert result.status == "UNKNOWN" and result.reasons == (reason,)
    assert len(harness.cards) == 2
    assert not harness.store_count
    assert len(harness.invalidations) == 1


def test_readback_unknown_cannot_be_reported_pass_after_catalog_change(harness):
    harness.stored.qualification_reasons = ("CONTRACT_NOTICE_DELIVERY_REGION_NOT_BOUND",)
    harness.stored.current_result.value = None
    result = run(harness)
    assert harness.store_count == 1 and harness.readback_count == 1
    assert result.status == "UNKNOWN"
    assert result.receipt_id == "receipt-failed"
    assert len(harness.invalidations) == 1


@pytest.mark.parametrize("where", ["fetch", "catalog", "qualify", "store", "readback"])
def test_unstructured_failures_are_generic_and_always_invalidate(harness, monkeypatch, where):
    secret = "token=private-password https://credentials@private.example/?secret=1"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    async def async_fail(*args, **kwargs):
        fail()

    if where == "fetch":
        monkeypatch.setattr(worker, "fetch_official_bundle", async_fail)
    elif where == "readback":
        monkeypatch.setattr(worker, "_stored_observation", fail)
    else:
        monkeypatch.setattr(
            worker.ledger,
            {
                "catalog": "read_region_catalog",
                "qualify": "qualify_contract",
                "store": "store_contract_observation",
            }[where],
            fail,
        )
    result = run(harness)
    assert result.status == "UNKNOWN" and result.reasons == ("HISTORY_REFRESH_FAILED",)
    assert "private" not in repr(result)
    assert len(harness.invalidations) == 1


def test_safe_source_metadata_retains_codes_without_raw_exception(harness, monkeypatch):
    async def fetch(*args, **kwargs):
        raise EisSyncError(
            "secret token",
            source_error=EisSourceError(
                "PREPARED", service_code=-42, http_status=503, network_code="TIMEOUT"
            ),
        )

    monkeypatch.setattr(worker, "fetch_official_bundle", fetch)
    result = run(harness)
    assert result.source_error == worker.ContractRefreshSourceError(
        "PREPARED", 503, -42, None, "TIMEOUT"
    )
    assert result.reasons == ("HISTORY_REFRESH_SOURCE_FAILED",)
    assert "secret" not in repr(result)


def test_card_network_metadata_is_whitelisted(harness, monkeypatch):
    async def capture(**kwargs):
        raise CardCaptureError("secret", http_status=503, network_code="token=private")

    monkeypatch.setattr(worker, "capture_current_card", capture)
    result = run(harness)
    assert result.source_error.http_status == 503
    assert result.source_error.network_code is None
    assert "private" not in repr(result) and "secret" not in repr(result)


def test_invalidation_failure_raises_safe_stop_error_never_claiming_revocation(
    harness, monkeypatch
):
    harness.pre_reasons = ("NOTICE_CANCELLATION_EVENT_PRESENT",)

    def failed_invalidation(*args, **kwargs):
        if kwargs.get("reason") == "HISTORY_REFRESH_IN_PROGRESS":
            return harness.invalidate(*args, **kwargs)
        raise RuntimeError("private database secret")

    monkeypatch.setattr(worker.ledger, "record_contract_refresh_failure", failed_invalidation)
    with pytest.raises(
        worker.ContractRefreshPersistenceError, match=r"^HISTORY_REFRESH_INVALIDATION_FAILED$"
    ):
        run(harness)


@pytest.mark.parametrize("timeout", [0, -1, 601, float("inf"), float("nan"), True])
def test_timeout_argument_cannot_disable_ten_minute_bound(harness, timeout):
    with pytest.raises(ValueError, match="ARGUMENT_INVALID"):
        run(harness, timeout_seconds=timeout)
    assert harness.events == []


def test_window_expiring_during_persistence_revokes_new_result(harness, monkeypatch):
    def readback(*args):
        harness.clock += timedelta(seconds=601)
        return harness.stored

    monkeypatch.setattr(worker, "_stored_observation", readback)
    result = run(harness)
    assert harness.store_count == 1
    assert result.status == "UNKNOWN"
    assert result.reasons == ("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED",)
    assert len(harness.invalidations) == 1


def test_readback_wrong_tenant_or_purchase_never_returns_pass(harness):
    harness.stored.company_id = "tenant-b"
    result = run(harness)
    assert result.status == "UNKNOWN"
    assert result.reasons == ("HISTORY_STORED_OBSERVATION_UNCONFIRMED",)
    assert len(harness.invalidations) == 1


def test_exact_readback_verifies_payload_digest_and_query_scope():
    observation = qualify()
    payload = observation.model_dump(mode="json")
    storage = ReadbackStorage(
        {"payload": payload, "payload_sha256": worker.payload_digest(payload)}
    )
    actual = _REAL_READBACK(storage, "tenant-a", REGISTRY, "receipt-good")
    assert actual == observation
    assert set(storage.parameters.values()) == {"tenant-a", REGISTRY, "receipt-good"}


@pytest.mark.parametrize(
    "row", [None, {"payload": {"untrusted": "changed"}, "payload_sha256": "a" * 64}]
)
def test_missing_or_corrupted_readback_is_rejected_before_payload_admission(row):
    with pytest.raises(worker._Rejected) as caught:
        _REAL_READBACK(ReadbackStorage(row), "tenant-a", REGISTRY, "receipt-good")
    assert caught.value.reasons == ("HISTORY_OBSERVATION_DIGEST",)


def test_corrupted_persisted_payload_triggers_durable_invalidation(harness, monkeypatch):
    payload = qualify().model_dump(mode="json")
    digest = worker.payload_digest(payload)
    payload["initial"]["value"] = "99999999.99"
    harness.storage = ReadbackStorage({"payload": payload, "payload_sha256": digest})
    monkeypatch.setattr(worker, "_stored_observation", _REAL_READBACK)
    result = run(harness)
    assert harness.store_count == 1
    assert result.status == "UNKNOWN"
    assert result.reasons == ("HISTORY_OBSERVATION_DIGEST",)
    assert result.receipt_id == "receipt-failed"
    assert len(harness.invalidations) == 1


def test_pending_hold_is_required_before_any_source_io(harness, monkeypatch):
    def fail_hold(*args, **kwargs):
        assert kwargs["reason"] == "HISTORY_REFRESH_IN_PROGRESS"
        raise RuntimeError("private database credentials")

    monkeypatch.setattr(worker.ledger, "record_contract_refresh_failure", fail_hold)
    with pytest.raises(
        worker.ContractRefreshPersistenceError, match=r"^HISTORY_REFRESH_HOLD_FAILED$"
    ):
        run(harness)
    assert harness.events == []


def test_abrupt_exit_leaves_pending_hold_without_fabricated_source_failure(harness, monkeypatch):
    class ProcessDeath(BaseException):
        pass

    async def fetch(*args, **kwargs):
        assert len(harness.holds) == 1
        raise ProcessDeath

    monkeypatch.setattr(worker, "fetch_official_bundle", fetch)
    with pytest.raises(ProcessDeath):
        run(harness)
    assert len(harness.holds) == 1
    assert harness.invalidations == []
    assert harness.store_count == 0


def test_source_before_or_equal_to_hold_cannot_reactivate_previous_pass(harness):
    harness.rgk = replace(harness.rgk, requested_at=harness.clock, checked_at=harness.clock)
    result = run(harness)
    assert result.status == "UNKNOWN"
    assert result.reasons == ("HISTORY_REFRESH_SOURCE_PRECEDES_HOLD",)
    assert len(harness.holds) == len(harness.invalidations) == 1
    assert harness.store_count == 0


@pytest.mark.parametrize(
    "code", ["HISTORY_REFRESH_HOLD_FAILED", "HISTORY_REFRESH_INVALIDATION_FAILED"]
)
def test_critical_persistence_errors_keep_safe_distinct_codes_for_host(code):
    assert worker._safe_error(worker.ContractRefreshPersistenceError(code)) == ((code,), None)
    reasons, _ = worker._safe_error(worker.ContractRefreshPersistenceError("private secret"))
    assert reasons == ("HISTORY_REFRESH_PERSISTENCE_FAILED",)
