"""One bounded tenant-scoped RGK → PRIZ → current-card refresh.

The host owns the global ingestion lease and the supplied transport's joint budget,
TLS and pacing. This worker neither acquires a replacement transport nor bypasses
public-card cooldowns. Synchronous ledger writes never outlive a cancelled task in
an executor thread.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from xml.etree import ElementTree as ET

from sqlalchemy import select

from procurement.domain.actions import payload_digest
from procurement.domain.regional_discount import RegionalObservation
from procurement.sources.eis_contract_cards import CardSnapshot
from procurement.sources.eis_contract_results import EXPORT, contract_result
from procurement.sources.eis_contract_sync import (
    CardCaptureError,
    OfficialBundle,
    capture_current_card,
    fetch_official_bundle,
)
from procurement.sources.eis_feed_sync import _NETWORK_CODES, EisFeedTransport, EisSyncError
from procurement.storage import eis_contract_results as ledger
from procurement.storage.eis_contract_schema import contract_observations
from procurement.storage.repository import PostgresStorage

MAX_SECONDS = 600.0
_CARD_CODES = frozenset(
    {
        "CARD_BROWSER_UNAVAILABLE",
        "CARD_SOURCE_COOLDOWN",
        "CARD_RESPONSE_ABSENT",
        "CARD_HTTP_REJECTED",
        "CARD_REDIRECT_UNSUPPORTED",
        "CARD_RESPONSE_LENGTH_INVALID",
        "CARD_RESPONSE_LIMIT",
        "CARD_TRANSPORT_FAILED",
    }
)
_PARSE_CODES = frozenset(
    {
        "CONTRACT_XML_UNSAFE",
        "CONTRACT_XML_INVALID",
        "CONTRACT_EXPORT_INVALID",
        "CONTRACT_DUPLICATE_SCALAR",
        "CONTRACT_BUNDLE_INVALID",
        "CONTRACT_RESPONSE_BINDING_INVALID",
        "CONTRACT_PREPARED_PARTS_INCOMPLETE",
        "CONTRACT_INITIAL_NO_DATA",
        "CONTRACT_PREPARATION_PENDING",
        "CONTRACT_ARCHIVE_REJECTED",
        "CONTRACT_ARCHIVE_LIMIT",
        "HISTORY_REGION_CATALOG_UNAVAILABLE",
        "HISTORY_REGION_CATALOG_MISMATCH",
        "HISTORY_CONTRACT_IDENTITY_MISMATCH",
        "HISTORY_NOTICE_SOURCE_MISMATCH",
        "HISTORY_INITIAL_CONTRACT_ABSENT",
        "HISTORY_NOTICE_ABSENT",
    }
)


@dataclass(frozen=True)
class ContractRefreshSourceError:
    phase: str
    http_status: int | None = None
    service_code: int | None = None
    category: str | None = None
    network_code: str | None = None
    retry_at: datetime | None = None


@dataclass(frozen=True)
class ContractRefreshResult:
    status: Literal["PASS", "UNKNOWN"]
    registry_number: str
    purchase_number: str | None
    receipt_id: str | None
    reasons: tuple[str, ...]
    source_error: ContractRefreshSourceError | None = None


class ContractRefreshPersistenceError(RuntimeError):
    """Failure to durably revoke an earlier result; must stop the host job."""


class _Rejected(ValueError):
    def __init__(self, *reasons: str) -> None:
        self.reasons = reasons
        super().__init__("HISTORY_REFRESH_REJECTED")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _window(started: datetime, *sources: OfficialBundle | CardSnapshot) -> None:
    moments = [started, _utcnow()]
    for source in sources:
        if (
            source.requested_at.utcoffset() is None
            or source.checked_at.utcoffset() is None
            or source.requested_at > source.checked_at
        ):
            raise _Rejected("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED")
        moments.extend((source.requested_at, source.checked_at))
    if max(moments) - min(moments) > timedelta(seconds=MAX_SECONDS):
        raise _Rejected("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED")
    if any(source.requested_at <= started for source in sources):
        raise _Rejected("HISTORY_REFRESH_SOURCE_PRECEDES_HOLD")


def _original_purchase(bundle: OfficialBundle, registry: str) -> str:
    bundle.validate()
    if (
        bundle.subsystem != "RGK"
        or bundle.number != registry
        or bundle.selection_kind != "BY_NUMBER"
    ):
        raise _Rejected("HISTORY_CONTRACT_IDENTITY_MISMATCH")
    originals = {}
    for member, raw in bundle.xml_documents():
        root = ET.fromstring(raw)
        if root.tag != f"{{{EXPORT}}}export" or len(root) != 1:
            raise _Rejected("CONTRACT_EXPORT_INVALID")
        if root[0].tag != f"{{{EXPORT}}}contract":
            continue  # Companion/cancellation admission is checked by qualify_contract.
        document = contract_result(raw, member)
        if document.registry_number != registry:
            raise _Rejected("HISTORY_CONTRACT_IDENTITY_MISMATCH")
        if document.version == 0:
            originals[document.xml_sha256] = document
    if len(originals) != 1:
        raise _Rejected(
            "HISTORY_INITIAL_CONTRACT_ABSENT" if not originals else "CONTRACT_VERSION_CONFLICT"
        )
    purchase = next(iter(originals.values())).purchase_number.value
    if purchase is None or not re.fullmatch(r"[0-9]{19,23}", purchase):
        raise _Rejected("HISTORY_NOTICE_SOURCE_MISMATCH")
    return purchase


def _notice_kind(bundle: OfficialBundle, purchase: str) -> Literal["EF_DOCUMENTS", "EZK_DOCUMENTS"]:
    bundle.validate()
    if (
        bundle.subsystem != "PRIZ"
        or bundle.number != purchase
        or bundle.selection_kind != "BY_NUMBER"
    ):
        raise _Rejected("HISTORY_NOTICE_SOURCE_MISMATCH")
    kinds = set()
    for _, raw in bundle.xml_documents():
        root = ET.fromstring(raw)
        if root.tag == f"{{{EXPORT}}}export" and len(root) == 1:
            name = root[0].tag.removeprefix(f"{{{EXPORT}}}")
            if name in {"epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020"}:
                kinds.add(name)
    if len(kinds) != 1:
        raise _Rejected("HISTORY_NOTICE_KIND_UNCONFIRMED")
    kind = next(iter(kinds))
    if kind == "epNotificationEOK2020":
        raise _Rejected("HISTORY_NOTICE_KIND_UNSUPPORTED")
    return "EF_DOCUMENTS" if kind == "epNotificationEF2020" else "EZK_DOCUMENTS"


async def _card(
    number: str, kind: Literal["CONTRACT", "EF_DOCUMENTS", "EZK_DOCUMENTS"], deadline: float
) -> CardSnapshot:
    for _ in range(12):
        _remaining(deadline)
        try:
            return await capture_current_card(number=number, kind=kind)
        except CardCaptureError as error:
            retry_at = error.retry_at
            if (
                str(error) != "CARD_SOURCE_COOLDOWN"
                or retry_at is None
                or retry_at.utcoffset() is None
            ):
                raise
            delay = (retry_at - _utcnow()).total_seconds()
            if delay <= 0 or delay >= _remaining(deadline):
                raise
            await asyncio.sleep(delay)  # Honour the source's exact future retry time.
    raise _Rejected("HISTORY_PUBLIC_COOLDOWN_LIMIT")


def _stored_observation(
    storage: PostgresStorage, company: str, registry: str, receipt_id: str
) -> RegionalObservation:
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        row = (
            conn.execute(
                select(
                    contract_observations.c.payload, contract_observations.c.payload_sha256
                ).where(
                    contract_observations.c.company_id == company,
                    contract_observations.c.registry_number == registry,
                    contract_observations.c.receipt_id == receipt_id,
                )
            )
            .mappings()
            .first()
        )
    if row is None or payload_digest(row["payload"]) != row["payload_sha256"]:
        raise _Rejected("HISTORY_OBSERVATION_DIGEST")
    return RegionalObservation.model_validate(row["payload"])


def _safe_error(error: Exception) -> tuple[tuple[str, ...], ContractRefreshSourceError | None]:
    if isinstance(error, ContractRefreshPersistenceError):
        code = str(error)
        return (
            (
                code
                if code
                in {
                    "HISTORY_REFRESH_HOLD_FAILED",
                    "HISTORY_REFRESH_INVALIDATION_FAILED",
                }
                else "HISTORY_REFRESH_PERSISTENCE_FAILED"
            ),
        ), None
    if isinstance(error, _Rejected):
        return error.reasons, None
    if isinstance(error, TimeoutError):
        return ("HISTORY_REFRESH_TIMEOUT",), None
    if isinstance(error, CardCaptureError):
        reason = str(error) if str(error) in _CARD_CODES else "HISTORY_REFRESH_SOURCE_FAILED"
        return (reason,), ContractRefreshSourceError(
            phase="PUBLIC_CARD",
            http_status=error.http_status
            if type(error.http_status) is int and 100 <= error.http_status <= 599
            else None,
            network_code=error.network_code if error.network_code in _NETWORK_CODES else None,
            retry_at=error.retry_at
            if isinstance(error.retry_at, datetime) and error.retry_at.utcoffset() is not None
            else None,
        )
    if isinstance(error, EisSyncError) and error.source_error is not None:
        return ("HISTORY_REFRESH_SOURCE_FAILED",), ContractRefreshSourceError(
            **error.source_error.safe_metadata()
        )
    return ((str(error) if str(error) in _PARSE_CODES else "HISTORY_REFRESH_FAILED"),), None


def _invalidate(storage: PostgresStorage, company: str, registry: str, actor: str) -> str | None:
    try:
        return ledger.record_contract_refresh_failure(
            storage,
            company,
            registry,
            actor=actor,
            reason="HISTORY_REFRESH_FAILED",
            checked_at=_utcnow(),
        )
    except Exception:
        raise ContractRefreshPersistenceError("HISTORY_REFRESH_INVALIDATION_FAILED") from None


async def refresh_contract_observation(
    storage: PostgresStorage,
    company: str,
    registry_number: str,
    *,
    actor: str,
    transport: EisFeedTransport,
    token: str,
    timeout_seconds: float = MAX_SECONDS,
) -> ContractRefreshResult:
    """Refresh one registry; any failed attempt durably invalidates an earlier PASS.

    PASS denotes this source observation, not a sufficient regional cohort. Failure
    of the invalidation transaction raises a safe persistence error, never success.
    """
    if (
        not isinstance(company, str)
        or not company.strip()
        or len(company) > 200
        or not isinstance(actor, str)
        or not actor.strip()
        or len(actor) > 200
        or not isinstance(registry_number, str)
        or not re.fullmatch(r"[0-9]{19,23}", registry_number)
        or type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAX_SECONDS
    ):
        raise ValueError("HISTORY_REFRESH_ARGUMENT_INVALID")
    purchase = None
    started = _utcnow()
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Durable UNKNOWN before any source attempt: process death cannot leave the
    # preceding PASS visible. This records pending work, not a fabricated failure.
    try:
        ledger.record_contract_refresh_failure(
            storage,
            company,
            registry_number,
            actor=actor,
            reason="HISTORY_REFRESH_IN_PROGRESS",
            checked_at=started,
        )
    except Exception:
        raise ContractRefreshPersistenceError("HISTORY_REFRESH_HOLD_FAILED") from None
    try:
        async with asyncio.timeout_at(deadline):
            _remaining(deadline)
            contract = await fetch_official_bundle(
                transport, token, subsystem="RGK", number=registry_number
            )
            _window(started, contract)
            purchase = _original_purchase(contract, registry_number)
            _remaining(deadline)
            notice = await fetch_official_bundle(
                transport, token, subsystem="PRIZ", number=purchase
            )
            _window(started, contract, notice)
            kind = _notice_kind(notice, purchase)
            catalog = ledger.read_region_catalog(storage, company)
            provisional = ledger.qualify_contract(company, contract, notice, catalog)
            blockers = tuple(
                reason
                for reason in provisional.qualification_reasons
                if reason != "SOURCE_CURRENT_HISTORY_UNCONFIRMED"
            )
            if blockers:
                raise _Rejected(*blockers)
            _remaining(deadline)
            contract_card = await _card(registry_number, "CONTRACT", deadline)
            _window(started, contract, notice, contract_card)
            notice_card = await _card(purchase, kind, deadline)
            _window(started, contract, notice, contract_card, notice_card)
            qualified = ledger.qualify_contract(
                company,
                contract,
                notice,
                catalog,
                contract_card=contract_card,
                notice_card=notice_card,
            )
            if qualified.qualification_reasons or qualified.current_result.value is not True:
                raise _Rejected(
                    *(qualified.qualification_reasons or ("SOURCE_CURRENT_HISTORY_UNCONFIRMED",))
                )
            _remaining(deadline)
            receipt = ledger.store_contract_observation(
                storage,
                company,
                contract,
                notice,
                actor=actor,
                contract_card=contract_card,
                notice_card=notice_card,
            )
            stored = _stored_observation(storage, company, registry_number, receipt)
            _remaining(deadline)
            _window(started, contract, notice, contract_card, notice_card)
            if (
                stored.company_id != company
                or stored.purchase_number != purchase
                or stored.qualification_reasons
                or stored.current_result.value is not True
            ):
                raise _Rejected(
                    *(stored.qualification_reasons or ("HISTORY_STORED_OBSERVATION_UNCONFIRMED",))
                )
            return ContractRefreshResult("PASS", registry_number, purchase, receipt, ())
    except asyncio.CancelledError:
        _invalidate(storage, company, registry_number, actor)
        raise
    except Exception as error:
        reasons, source_error = _safe_error(error)
        receipt = _invalidate(storage, company, registry_number, actor)
        return ContractRefreshResult(
            "UNKNOWN", registry_number, purchase, receipt, reasons, source_error
        )
