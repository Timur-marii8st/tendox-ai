"""Source-bound award observations and bounded indexed history, tenant-scoped throughout."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from io import BytesIO
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sqlalchemy import and_, case, exists, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.domain.actions import payload_digest
from procurement.domain.provenance import Provenance
from procurement.domain.regional_discount import (
    HistoryFact,
    HistoryMoney,
    RegionalCohort,
    RegionalHistory,
    RegionalObservation,
    source_date_bounds,
)
from procurement.sources.eis_223_regions import RegionCatalog, inspect_region_catalog
from procurement.sources.eis_contract_cards import (
    CardSnapshot,
    parse_contract_card,
    parse_notice_documents_card,
)
from procurement.sources.eis_contract_characteristics import specifications_bound
from procurement.sources.eis_contract_results import (
    EXPORT,
    TYPES,
    ContractResult,
    MarketItem,
    MarketNotice,
    contract_result,
    notice_market,
)
from procurement.sources.eis_contract_sync import OfficialBundle
from procurement.sources.tender_navigation import region_name_key
from procurement.storage.eis_contract_schema import (
    contract_evidence,
    contract_observation_sources,
    contract_observations,
)
from procurement.storage.eis_document_store import NoticeDocumentRef, load_notice
from procurement.storage.models import (
    audit_events,
    eis_223_region_catalogs,
    eis_feed_archives,
    eis_notice_versions,
)
from procurement.storage.repository import PostgresStorage


def _key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def read_region_catalog(storage: PostgresStorage, company: str) -> RegionCatalog:
    """Use the already recorded official region catalog, rechecking its bytes/hash."""
    table = eis_223_region_catalogs
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        row = (
            conn.execute(
                select(table)
                .where(
                    table.c.company_id == company, func.octet_length(table.c.content) <= 8 * 1024**2
                )
                .order_by(table.c.observed_at.desc(), table.c.catalog_sha256)
                .limit(1)
            )
            .mappings()
            .first()
        )
    if row is None:
        raise ValueError("HISTORY_REGION_CATALOG_UNAVAILABLE")
    catalog = inspect_region_catalog(
        bytes(row["content"]),
        source_url=row["source_url"],
        response_sha256=row["response_sha256"],
        observed_at=row["observed_at"],
    )
    if catalog.catalog_sha256 != row["catalog_sha256"] or catalog.regions != row["regions"]:
        raise ValueError("HISTORY_REGION_CATALOG_MISMATCH")
    return catalog


def delivery_region(
    addresses: tuple[HistoryFact[str], ...], catalog: RegionCatalog
) -> HistoryFact[str]:
    """Every address must resolve to the same explicit catalog region, no city inference."""
    if not addresses:
        return HistoryFact(
            value=None,
            source=Provenance(
                document_id=catalog.catalog_sha256,
                locator="delivery addresses absent",
                extractor="api",
            ),
        )
    found = []
    for address in addresses:
        matches = [
            name
            for name in catalog.regions.values()
            if region_name_key(name) == region_name_key((address.value or "").split(",", 1)[0])
        ]
        if len(matches) != 1:
            return HistoryFact(value=None, source=address.source)
        found.append(matches[0])
    value = found[0] if len(set(found)) == 1 else None
    return HistoryFact(
        value=value,
        source=addresses[0].source,
        supporting_sources=(
            Provenance(
                document_id=catalog.catalog_sha256, locator=catalog.source_url, extractor="api"
            ),
        ),
    )


def homogeneous_scope(
    items: tuple[MarketItem, ...],
) -> tuple[str | None, str | None, Decimal | None]:
    """Whole homogeneous lot; mixed, missing or duplicated source IDs are not allocated."""
    if not items:
        return None, None, None
    keys = set()
    for item in items:
        if item.product_key.value is None or item.specification.signature is None:
            return None, None, None
        key = item.product_key.value
        if item.specification.signature:
            key += ";SPEC:" + item.specification.signature
        if len(key) > 500:
            return None, None, None
        keys.add(key)
    units = {i.unit.value for i in items}
    sids = [i.sid.value for i in items]
    if (
        None in keys
        or None in units
        or None in sids
        or len(set(sids)) != len(sids)
        or len(keys) != 1
        or len(units) != 1
        or any(i.quantity.value is None or i.quantity.value <= 0 for i in items)
    ):
        return None, None, None
    with localcontext() as context:
        context.prec = 80
        quantity = sum(
            (i.quantity.value for i in items if i.quantity.value is not None), Decimal(0)
        )
    return next(iter(keys)), next(iter(units)), quantity


def qualify_contract(
    company: str,
    contract_bundle: OfficialBundle,
    notice_bundle: OfficialBundle,
    catalog: RegionCatalog,
    *,
    contract_card: CardSnapshot | None = None,
    notice_card: CardSnapshot | None = None,
) -> RegionalObservation:
    """Join original registered contract to its source-object IDs and unambiguous notice chain."""
    if (
        contract_bundle.subsystem != "RGK"
        or notice_bundle.subsystem != "PRIZ"
        or contract_bundle.selection_kind != "BY_NUMBER"
        or notice_bundle.selection_kind != "BY_NUMBER"
    ):
        raise ValueError("HISTORY_SOURCE_SUBSYSTEM_MISMATCH")
    contract_bundle.validate()
    notice_bundle.validate()
    documents = []
    reasons = []
    moments = [
        contract_bundle.requested_at,
        contract_bundle.checked_at,
        notice_bundle.requested_at,
        notice_bundle.checked_at,
    ]
    if max(moments) - min(moments) > timedelta(minutes=10):
        reasons.append("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED")
    for member, raw in contract_bundle.xml_documents():
        root = ET.fromstring(raw)
        kind = root[0].tag if root.tag == f"{{{EXPORT}}}export" and len(root) == 1 else ""
        if kind == f"{{{EXPORT}}}contract":
            documents.append(contract_result(raw, member))
        elif kind == f"{{{EXPORT}}}contractCancel":
            reasons.append("CONTRACT_ANNULMENT_IN_SOURCE")
        elif kind == f"{{{EXPORT}}}contractAvailableForElAct":
            # XSD zfcs_contractAvailableForElAct: access receipt, no price or award.
            node = root[0]
            fields = {
                f"{{{TYPES}}}{name}" for name in ("id", "regNum", "isAvailable", "availableDT")
            }
            if (
                any(child.tag not in fields for child in node)
                or len(node.findall(f"{{{TYPES}}}regNum")) != 1
                or node.findtext(f"{{{TYPES}}}regNum") != contract_bundle.number
                or node.findtext(f"{{{TYPES}}}isAvailable") not in {"true", "1"}
            ):
                reasons.append("CONTRACT_COMPANION_NOT_SUPPORTED")
        elif kind not in {f"{{{EXPORT}}}contractProcedure", f"{{{EXPORT}}}contractProcedureCancel"}:
            reasons.append("CONTRACT_COMPANION_NOT_SUPPORTED")
    if not documents or any(d.registry_number != contract_bundle.number for d in documents):
        raise ValueError("HISTORY_CONTRACT_IDENTITY_MISMATCH")
    versions: dict[int, ContractResult] = {}
    for document in documents:
        if document.version is None:
            reasons.append("CONTRACT_VERSION_UNKNOWN")
            continue
        if (
            document.version in versions
            and versions[document.version].xml_sha256 != document.xml_sha256
        ):
            reasons.append("CONTRACT_VERSION_CONFLICT")
        versions[document.version] = document
    original = versions.get(0)
    if original is None:
        raise ValueError("HISTORY_INITIAL_CONTRACT_ABSENT")
    if sorted(versions) != list(range(len(versions))):
        reasons.append("CONTRACT_VERSION_GAP")
    for document in documents:
        reasons.extend(document.reasons)
    if any(d.commercial_fingerprint != original.commercial_fingerprint for d in documents):
        reasons.append("CONTRACT_COMMERCIAL_SCOPE_CHANGED")
    if original.purchase_number.value != notice_bundle.number:
        raise ValueError("HISTORY_NOTICE_SOURCE_MISMATCH")
    notices: dict[int, MarketNotice] = {}
    for member, raw in notice_bundle.xml_documents():
        root = ET.fromstring(raw)
        if root.tag != f"{{{EXPORT}}}export" or len(root) != 1:
            reasons.append("NOTICE_SOURCE_DOCUMENT_UNSUPPORTED")
            continue
        kind = root[0].tag.removeprefix(f"{{{EXPORT}}}")
        if kind in {"epNotificationCancel", "epNotificationCancelFailure"}:
            reasons.append("NOTICE_CANCELLATION_EVENT_PRESENT")
        elif kind in {"epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020"}:
            market = notice_market(raw, member, customer_number=original.customer.value)
            if market.purchase_number != notice_bundle.number:
                reasons.append("NOTICE_NUMBER_CONFLICT")
                continue
            if (
                market.version in notices
                and notices[market.version].xml_sha256 != market.xml_sha256
            ):
                reasons.append("NOTICE_VERSION_CONFLICT")
            notices[market.version] = market
        elif not (
            root[0].tag.startswith(f"{{{EXPORT}}}epProtocol")
            or kind
            in {
                "fcsPlacementResult",
                "fcsProposalsResult",
                "epClarificationDoc",
            }
        ):
            reasons.append("NOTICE_SOURCE_DOCUMENT_UNSUPPORTED")
    if not notices:
        raise ValueError("HISTORY_NOTICE_ABSENT")
    if sorted(notices) != list(range(1, len(notices) + 1)):
        reasons.append("NOTICE_VERSION_GAP")
    applicable = []
    signed = original.signed_on.value
    if signed is None:
        reasons.append("CONTRACT_SIGN_DATE_UNKNOWN")
    else:
        lower, upper = source_date_bounds(signed)
        for notice in notices.values():
            published = notice.published_at.value
            if published is None:
                reasons.append("NOTICE_PUBLICATION_UNKNOWN")
            elif lower <= published <= upper:
                reasons.append("NOTICE_VERSION_AT_SIGN_DATE_AMBIGUOUS")
            elif published < lower:
                applicable.append(notice)
    # Keep a source-bearing diagnostic observation even when no baseline is applicable.
    baseline = (
        max(applicable, key=lambda n: n.version)
        if applicable
        else min(notices.values(), key=lambda n: n.version)
    )
    if not applicable:
        reasons.append("APPLICABLE_NOTICE_VERSION_UNKNOWN")
    reasons.extend(baseline.reasons)
    initial_items = {i.sid.value: i for i in baseline.items}
    final_items = {i.sid.value: i for i in original.items}
    if (
        None in initial_items
        or None in final_items
        or not initial_items
        or len(initial_items) != len(baseline.items)
        or len(final_items) != len(original.items)
        or set(initial_items) != set(final_items)
    ):
        reasons.append("WHOLE_SOURCE_OBJECT_SCOPE_NOT_BOUND")
    else:
        for sid, item in initial_items.items():
            counterpart = final_items[sid]
            if any(
                getattr(item, field).value != getattr(counterpart, field).value
                for field in ("product_key", "unit", "quantity")
            ):
                reasons.append("SOURCE_OBJECT_QUANTITY_UNIT_OR_PRODUCT_CHANGED")
            if specifications_bound(item.specification, counterpart.specification) is not True:
                reasons.append("SOURCE_PRODUCT_CHARACTERISTICS_NOT_BOUND")
    for items, total in [
        (baseline.items, baseline.initial.value),
        (original.items, original.price.value),
    ]:
        if total is None or total <= 0 or any(i.line_sum.value is None for i in items):
            reasons.append("WHOLE_NOMINAL_TOTAL_UNKNOWN")
        else:
            with localcontext() as context:
                context.prec = 80
                line_total = sum(
                    (i.line_sum.value for i in items if i.line_sum.value is not None), Decimal(0)
                )
                if abs(line_total - total) > Decimal("0.01"):
                    reasons.append("WHOLE_NOMINAL_TOTAL_SCOPE_MISMATCH")
    initial_region = delivery_region(baseline.delivery_addresses, catalog)
    final_region = delivery_region(original.delivery_addresses, catalog)
    if initial_region.value is None or initial_region.value != final_region.value:
        reasons.append("CONTRACT_NOTICE_DELIVERY_REGION_NOT_BOUND")
    key, unit, quantity = homogeneous_scope(baseline.items)
    if key is None:
        reasons.append("WHOLE_HOMOGENEOUS_MARKET_SCOPE_UNKNOWN")
    if original.published_at.value is None or any(
        d.published_at.value is None or d.published_at.value > contract_bundle.checked_at
        for d in documents
    ):
        reasons.append("CONTRACT_PUBLICATION_UNKNOWN_OR_FUTURE")
    current_reasons = []
    card_receipts = []
    if contract_card is None or notice_card is None:
        current_reasons.append("SOURCE_CURRENT_HISTORY_UNCONFIRMED")
    else:
        card = parse_contract_card(contract_card, contract_bundle.number)
        notice_state = parse_notice_documents_card(notice_card, notice_bundle.number)
        card_receipts = [asdict(card.receipt), asdict(notice_state.receipt)]
        current_reasons.extend(card.receipt.reasons)
        current_reasons.extend(notice_state.receipt.reasons)
        moments.extend(
            [
                contract_card.requested_at,
                contract_card.checked_at,
                notice_card.requested_at,
                notice_card.checked_at,
            ]
        )
        if max(moments) - min(moments) > timedelta(minutes=10):
            current_reasons.append("SOURCE_SNAPSHOT_TIME_SPAN_UNSUPPORTED")
        if (
            card.version.value != max(versions)
            or notice_state.version.value != max(notices)
            or card.purchase_number.value != notice_bundle.number
            or card.price.value != original.price.value
            or card.signed_on.value != original.signed_on.value
            or notice_state.initial.value != notices[max(notices)].notice_initial.value
        ):
            current_reasons.append("SOURCE_CURRENT_CARD_MISMATCH")
    manifest = [contract_bundle.receipt(), notice_bundle.receipt(), *card_receipts]
    import json

    manifest = json.loads(json.dumps(manifest, default=lambda value: value.isoformat()))
    receipt_source = Provenance(
        document_id=payload_digest({"sources": manifest}),
        locator=(
            "returned parts and observed scope checks; current cards checked within "
            f"{min(moments).isoformat()} .. {max(moments).isoformat()}; "
            "complete entity history UNKNOWN"
        ),
        extractor="api",
    )
    passed = not reasons
    proof = HistoryFact(value=True if passed else None, source=receipt_source)
    return RegionalObservation(
        company_id=company,
        law="44",
        purchase_number=notice_bundle.number,
        region=initial_region,
        product_key=HistoryFact(
            value=key,
            source=baseline.items[0].product_key.source
            if baseline.items
            else baseline.initial.source,
            supporting_sources=baseline.items[0].product_key.supporting_sources
            if baseline.items
            else (),
        ),
        procedure=HistoryFact(value=baseline.kind, source=baseline.initial.source),
        unit=HistoryFact(
            value=unit,
            source=original.items[0].unit.source if original.items else original.price.source,
        ),
        quantity=HistoryMoney(
            value=quantity,
            source=original.price.source.model_copy(
                update={
                    "locator": "DERIVED sum(products/product/quantity), whole homogeneous scope"
                }
            ),
        ),
        initial=baseline.initial,
        final=original.price,
        price_scope=baseline.scope_kind,
        customer=baseline.customer,
        concluded_at=HistoryFact(value=None, source=original.signed_on.source),
        concluded_date=original.signed_on,
        notice_lot_volume_link=proof,
        rub_nominal_totals=proof,
        concluded_contract=proof,
        current_result=HistoryFact(
            value=True if not reasons and not current_reasons else None, source=receipt_source
        ),
        qualification_reasons=tuple(dict.fromkeys([*reasons, *current_reasons])),
    )


def read_notice_market(
    storage: PostgresStorage, company: str, ref: NoticeDocumentRef
) -> MarketNotice:
    """Existing metadata API omits source SIDs/OKEI codes: read its exact bounded XML."""
    n, a = eis_notice_versions, eis_feed_archives
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        notice = load_notice(conn, company, ref)
        row = conn.execute(
            select(
                n.c.source_member,
                a.c.archive_sha256,
                case((func.octet_length(a.c.content) <= 50 * 1024**2, a.c.content), else_=None),
            )
            .join(
                a,
                and_(
                    a.c.company_id == n.c.company_id,
                    a.c.window_key == n.c.window_key,
                    a.c.response_sha256 == n.c.response_sha256,
                    a.c.archive_sha256 == n.c.archive_sha256,
                ),
            )
            .where(
                n.c.company_id == company,
                n.c.purchase_number == ref.purchase_number,
                n.c.version_number == ref.version_number,
                n.c.xml_sha256 == ref.notice_xml_sha256,
            )
        ).one()
        if row[2] is None:
            raise ValueError("HISTORY_NOTICE_ARCHIVE_LIMIT")
        archive = bytes(row[2])
    if hashlib.sha256(archive).hexdigest() != row[1]:
        raise ValueError("HISTORY_NOTICE_ARCHIVE_SHA")
    with ZipFile(BytesIO(archive)) as zipped:
        matches = [m for m in zipped.infolist() if m.filename == row[0]]
        if len(matches) != 1 or not 0 < matches[0].file_size <= 4 * 1024**2:
            raise ValueError("HISTORY_NOTICE_MEMBER_LIMIT")
        with zipped.open(matches[0]) as stream:
            raw = stream.read(4 * 1024**2 + 1)
    if len(raw) != matches[0].file_size or hashlib.sha256(raw).hexdigest() != ref.notice_xml_sha256:
        raise ValueError("HISTORY_NOTICE_XML_SHA")
    result = notice_market(raw, row[0])
    if (result.purchase_number, result.version, result.kind) != (
        ref.purchase_number,
        ref.version_number,
        notice.document_type,
    ):
        raise ValueError("HISTORY_NOTICE_MARKET_IDENTITY")
    return result


def store_contract_observation(
    storage: PostgresStorage,
    company: str,
    contract_bundle: OfficialBundle,
    notice_bundle: OfficialBundle,
    *,
    actor: str,
    contract_card: CardSnapshot | None = None,
    notice_card: CardSnapshot | None = None,
) -> str:
    """Append source evidence + checked observation + audit atomically; no client API."""
    if not actor.strip() or len(actor) > 200:
        raise ValueError("HISTORY_ACTOR_REQUIRED")
    if (contract_card is None) != (notice_card is None):
        raise ValueError("HISTORY_CURRENT_CARD_PAIR_REQUIRED")
    # No caller-supplied eligibility flags enter the ledger.
    observation = qualify_contract(
        company,
        contract_bundle,
        notice_bundle,
        read_region_catalog(storage, company),
        contract_card=contract_card,
        notice_card=notice_card,
    )
    receipts = [contract_bundle.receipt(), notice_bundle.receipt()]
    if contract_card is not None:
        receipts.append(asdict(parse_contract_card(contract_card, contract_bundle.number).receipt))
    if notice_card is not None:
        receipts.append(
            asdict(parse_notice_documents_card(notice_card, notice_bundle.number).receipt)
        )
    # Datetimes in card capture receipts are retained canonically as JSON strings.
    import json

    receipts = json.loads(json.dumps(receipts, default=lambda value: value.isoformat()))
    checked = min(
        contract_bundle.checked_at,
        notice_bundle.checked_at,
        *[card.checked_at for card in (contract_card, notice_card) if card is not None],
    )
    if len(observation.model_dump_json().encode()) > 262144:
        raise ValueError("HISTORY_PAYLOAD_LIMIT")
    evidence: dict[str, tuple[str, bytes]] = {}
    for bundle in (contract_bundle, notice_bundle):
        for kind, contents in [("ZIP", bundle.archives), ("SOAP", bundle.responses)]:
            for raw in contents:
                evidence[hashlib.sha256(raw).hexdigest()] = (kind, raw)
    for card in (contract_card, notice_card):
        if card is not None:
            evidence[hashlib.sha256(card.content).hexdigest()] = ("HTML", card.content)
    # The derived scope checks point to this exact retained JSON object.
    import json

    manifest = json.dumps(
        {"sources": receipts}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    evidence[hashlib.sha256(manifest).hexdigest()] = ("JSON", manifest)
    return _append_observation(
        storage,
        company,
        contract_bundle.number,
        observation,
        receipts,
        evidence,
        checked=checked,
        actor=actor,
    )


def _append_observation(
    storage: PostgresStorage,
    company: str,
    registry: str,
    observation: RegionalObservation,
    receipts: list[Any],
    evidence: dict[str, tuple[str, bytes]],
    *,
    checked: datetime,
    actor: str,
    linked_sources: tuple[str, ...] = (),
) -> str:
    payload = observation.model_dump(mode="json")
    digest = payload_digest(payload)
    receipt_id = payload_digest({"company": company, "payload": payload, "sources": receipts})
    with storage.transaction(company) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        conn.scalar(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(company + "/contract-history/" + receipt_id, 0)
                )
            )
        )
        existing = conn.execute(
            select(contract_observations.c.receipt_id).where(
                contract_observations.c.company_id == company,
                contract_observations.c.receipt_id == receipt_id,
            )
        ).first()
        if existing:
            return receipt_id
        event_id = str(uuid4())
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=event_id,
                actor_id=actor,
                event_type="EIS_CONTRACT_HISTORY_OBSERVED",
                object_type="eis_contract_history",
                object_id=registry,
                object_version=1,
                occurred_at=checked,
                basis={
                    "receipt_id": receipt_id,
                    "payload_sha256": digest,
                    "sources": receipts,
                    "qualification_reasons": observation.qualification_reasons,
                },
            )
        )
        for sha, (kind, raw) in evidence.items():
            conn.execute(
                pg_insert(contract_evidence)
                .values(company_id=company, sha256=sha, kind=kind, content=raw)
                .on_conflict_do_nothing()
            )
        conn.execute(
            insert(contract_observations).values(
                company_id=company,
                receipt_id=receipt_id,
                registry_number=registry,
                checked_at=checked,
                region_key=_key(observation.region.value) or None,
                product_key=_key(observation.product_key.value) or None,
                procedure=_key(observation.procedure.value) or None,
                unit=_key(observation.unit.value) or None,
                quantity=observation.quantity.value,
                payload=payload,
                payload_sha256=digest,
                source_receipts=receipts,
                audit_event_id=event_id,
            )
        )
        for sha in set(evidence).union(linked_sources):
            conn.execute(
                insert(contract_observation_sources).values(
                    company_id=company, receipt_id=receipt_id, sha256=sha
                )
            )
    return receipt_id


def record_contract_refresh_failure(
    storage: PostgresStorage,
    company: str,
    registry: str,
    *,
    actor: str,
    reason: str,
    checked_at: datetime,
) -> str | None:
    """Append an UNKNOWN hold before/during a refresh; never reuse an unvalidated prior state."""
    import json
    import re

    if (
        not actor.strip()
        or len(actor) > 200
        or reason not in {"HISTORY_REFRESH_FAILED", "HISTORY_REFRESH_IN_PROGRESS"}
        or not re.fullmatch(r"[0-9]{19,23}", registry)
        or checked_at.utcoffset() is None
    ):
        raise ValueError("HISTORY_FAILURE_RECEIPT_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        row = (
            conn.execute(
                select(contract_observations)
                .where(
                    contract_observations.c.company_id == company,
                    contract_observations.c.registry_number == registry,
                )
                .order_by(
                    contract_observations.c.checked_at.desc(), contract_observations.c.receipt_id
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is None:
            links = ()
        elif checked_at < row["checked_at"]:
            raise ValueError("HISTORY_FAILURE_TIME_BEFORE_OBSERVATION")
        if row is not None:
            links = tuple(
                conn.scalars(
                    select(contract_observation_sources.c.sha256).where(
                        contract_observation_sources.c.company_id == company,
                        contract_observation_sources.c.receipt_id == row["receipt_id"],
                    )
                )
            )
    if row is None:
        receipt = {
            "kind": "REFRESH_PENDING"
            if reason == "HISTORY_REFRESH_IN_PROGRESS"
            else "REFRESH_FAILURE",
            "registry_number": registry,
            "checked_at": checked_at.isoformat(),
            "reason": reason,
            "previous_receipt_id": None,
        }
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        sha = hashlib.sha256(raw).hexdigest()
        with storage.transaction(company) as conn:
            conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
            conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
            conn.execute(
                pg_insert(contract_evidence)
                .values(
                    company_id=company,
                    sha256=sha,
                    kind="JSON",
                    content=raw,
                )
                .on_conflict_do_nothing()
            )
            conn.execute(
                insert(audit_events).values(
                    company_id=company,
                    event_id=str(uuid4()),
                    actor_id=actor,
                    event_type="EIS_CONTRACT_HISTORY_REFRESH_PENDING"
                    if reason == "HISTORY_REFRESH_IN_PROGRESS"
                    else "EIS_CONTRACT_HISTORY_REFRESH_FAILED",
                    object_type="eis_contract_history",
                    object_id=registry,
                    object_version=1,
                    occurred_at=checked_at,
                    basis={"source_sha256": sha, **receipt},
                )
            )
        return None
    if payload_digest(row["payload"]) != row["payload_sha256"]:
        raise ValueError("HISTORY_OBSERVATION_DIGEST")
    old = RegionalObservation.model_validate(row["payload"])
    if old.company_id != company:
        raise ValueError("HISTORY_OBSERVATION_TENANT")
    receipt = {
        "kind": "REFRESH_PENDING" if reason == "HISTORY_REFRESH_IN_PROGRESS" else "REFRESH_FAILURE",
        "registry_number": registry,
        "checked_at": checked_at.isoformat(),
        "reason": reason,
        "previous_receipt_id": row["receipt_id"],
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    source = Provenance(
        document_id=sha, locator="refresh hold; previous source not revalidated", extractor="api"
    )
    observation = old.model_copy(
        update={
            "current_result": HistoryFact(value=None, source=source),
            "qualification_reasons": tuple(dict.fromkeys((*old.qualification_reasons, reason))),
        }
    )
    return _append_observation(
        storage,
        company,
        registry,
        observation,
        [receipt],
        {sha: ("JSON", raw)},
        checked=checked_at,
        actor=actor,
        linked_sources=links,
    )


def automatic_history(
    storage: PostgresStorage,
    company: str,
    ref: Any,
    *,
    source_company: str | None = None,
    now: datetime | None = None,
) -> RegionalHistory:
    """Server-derived target + latest indexed matching receipts, at most twenty, no network."""
    at = now or datetime.now(UTC)
    if at.utcoffset() is None:
        raise ValueError("HISTORY_TIMEZONE_REQUIRED")
    source_company = source_company or company
    chosen = ref.notice
    source_reasons: tuple[str, ...] = ()
    if chosen.law == "44":
        market = read_notice_market(
            storage,
            source_company,
            NoticeDocumentRef(
                purchase_number=chosen.purchase_number,
                version_number=chosen.version_number,
                notice_xml_sha256=chosen.notice_xml_sha256,
            ),
        )
        try:
            catalog = read_region_catalog(storage, source_company)
        except ValueError as error:
            if str(error) != "HISTORY_REGION_CATALOG_UNAVAILABLE":
                raise
            catalog = None
            source_reasons = ("HISTORY_REGION_CATALOG_UNAVAILABLE",)
        region = delivery_region(market.delivery_addresses, catalog).value if catalog else None
        product, unit, quantity = homogeneous_scope(market.items)
        if market.reasons:
            product = unit = quantity = None
            source_reasons += market.reasons
        basis = market.initial.source
        procedure = market.kind
    else:
        region = product = unit = quantity = procedure = None
        source_reasons = ("REGIONAL_HISTORY_223_NOT_SUPPORTED",)
        basis = Provenance(
            document_id=chosen.notice_xml_sha256,
            locator="223 regional contract context unsupported",
            extractor="api",
        )
    cohort = RegionalCohort(
        company_id=company,
        target_id=f"{chosen.law}:{chosen.purchase_number}:{ref.lot_index or 0}",
        law=chosen.law,
        region=region,
        product_key=product,
        procedure=procedure,
        unit=unit,
        quantity=quantity,
        period_start=at - timedelta(days=365),
        period_end=at,
        source=basis,
    )
    if any(v is None for v in (region, product, unit, quantity, procedure)):
        return RegionalHistory(cohort=cohort, observations=(), source_reasons=source_reasons)
    table = contract_observations
    newer = table.alias("newer_contract_history")
    with storage.transaction(source_company, consistent_read=True) as conn:
        conn.exec_driver_sql("SET LOCAL statement_timeout='5000ms'")
        conn.exec_driver_sql("SET LOCAL lock_timeout='1s'")
        rows = (
            conn.execute(
                select(table.c.payload, table.c.payload_sha256)
                .where(
                    table.c.company_id == source_company,
                    table.c.region_key == _key(region),
                    table.c.product_key == _key(product),
                    table.c.procedure == _key(procedure),
                    table.c.unit == _key(unit),
                    table.c.quantity >= quantity / 2,
                    table.c.quantity <= quantity * 2,
                    table.c.checked_at <= at,
                    table.c.checked_at >= at - timedelta(hours=24),
                    ~exists(
                        select(newer.c.receipt_id).where(
                            newer.c.company_id == table.c.company_id,
                            newer.c.registry_number == table.c.registry_number,
                            newer.c.checked_at >= table.c.checked_at,
                            newer.c.receipt_id != table.c.receipt_id,
                        )
                    ),
                )
                .order_by(table.c.checked_at.desc(), table.c.registry_number, table.c.receipt_id)
                .limit(20)
            )
            .mappings()
            .all()
        )
    observations = []
    for row in rows:
        if payload_digest(row["payload"]) != row["payload_sha256"]:
            raise ValueError("HISTORY_OBSERVATION_DIGEST")
        observed = RegionalObservation.model_validate(row["payload"])
        if observed.company_id != source_company:
            raise ValueError("HISTORY_OBSERVATION_TENANT")
        observations.append(observed.model_copy(update={"company_id": company}))
    return RegionalHistory(
        cohort=cohort, observations=tuple(observations), source_reasons=source_reasons
    )
