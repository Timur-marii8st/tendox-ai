"""Исторические факты отдельных документов; без прогнозов и объединения заявок."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.sources.eis_feed_archive import EisProcedureEvent, _notice

PARSER_VERSION: Literal["eis-protocol-facts-v1"] = "eis-protocol-facts-v1"
SUPPORTED_PROTOCOL_TYPES = (
    "epProtocolEOK2020Final",
    "fcsPlacementResult",
    "fcsProposalsResult",
)
EP = "http://zakupki.gov.ru/oos/EPtypes/1"
OOS = "http://zakupki.gov.ru/oos/types/1"
EXPORT = "http://zakupki.gov.ru/oos/export/1"
MAX_XML_BYTES = 4 * 1024**2
MAX_APPLICATION_ROWS = 200
T = TypeVar("T")


class ProtocolModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProtocolEvidence(ProtocolModel):
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_member: str
    document_type: str
    locator: str
    namespace: str


class ProtocolFact(ProtocolModel, Generic[T]):
    value: T | None
    status: Literal["PASS", "UNKNOWN"]
    reason: str | None = None
    evidence: ProtocolEvidence

    @field_validator("value", mode="before")
    @classmethod
    def reject_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("PROTOCOL_FLOAT_NOT_ALLOWED")
        return value

    @model_validator(mode="after")
    def consistent(self) -> ProtocolFact[T]:
        if (self.status == "PASS" and (self.value is None or self.reason is not None)) or (
            self.status == "UNKNOWN" and (self.value is not None or not self.reason)
        ):
            raise ValueError("PROTOCOL_FACT_STATUS_INVALID")
        return self


class ProtocolAmount(ProtocolModel):
    amount: ProtocolFact[Decimal]
    source_kind: Literal["FINAL_PROPOSAL", "PROPOSAL", "UNKNOWN"]
    right_to_conclude_contract: ProtocolFact[bool]
    currency: Literal["UNKNOWN"] = "UNKNOWN"
    tax_basis: Literal["UNKNOWN"] = "UNKNOWN"


class ProtocolApplication(ProtocolModel):
    row_number: int = Field(ge=1, le=MAX_APPLICATION_ROWS)
    application_id: ProtocolFact[str]
    admission: ProtocolFact[bool]
    rank: ProtocolFact[int]
    result_code: ProtocolFact[str]
    proposal: ProtocolAmount
    supplier_identity: Literal["UNKNOWN"] = "UNKNOWN"


class EisProtocolFacts(ProtocolModel):
    parser_version: Literal["eis-protocol-facts-v1"] = PARSER_VERSION
    source: ProtocolEvidence
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    document_kind: Literal["FINAL_PROTOCOL", "PLACEMENT_RESULT", "PROPOSALS_DISTRIBUTION"]
    published_at: AwareDatetime | None
    protocol_number: ProtocolFact[str]
    foundation_protocol_number: ProtocolFact[str]
    lot_number: ProtocolFact[str]
    observed_rows: ProtocolFact[int]
    represented_applications: ProtocolFact[int]
    applications: tuple[ProtocolApplication, ...]
    count_scope: Literal["APPLICATIONS_REPRESENTED_IN_THIS_DOCUMENT"] = (
        "APPLICATIONS_REPRESENTED_IN_THIS_DOCUMENT"
    )
    notice_version_link: Literal["UNKNOWN"] = "UNKNOWN"
    current_stage: Literal["UNKNOWN"] = "UNKNOWN"
    signed_contract: Literal["UNKNOWN"] = "UNKNOWN"
    competition_prediction: Literal["UNKNOWN"] = "UNKNOWN"


class EisProtocolError(ValueError):
    """Неоднозначная структура или неверная привязка исходного XML."""


def parse_protocol_facts(xml: bytes, event: EisProcedureEvent) -> EisProtocolFacts:
    """Читать только явно поддержанные поля одного exact XML; без I/O."""
    if event.document_type not in SUPPORTED_PROTOCOL_TYPES:
        raise EisProtocolError("PROTOCOL_TYPE_UNSUPPORTED")
    if (
        len(xml) > MAX_XML_BYTES
        or b"\x00" in xml
        or b"<!DOCTYPE" in xml.upper()
        or b"<!ENTITY" in xml.upper()
    ):
        raise EisProtocolError("PROTOCOL_XML_UNSAFE")
    if not 1 <= len(event.source_member.encode("utf-8")) <= 255:
        raise EisProtocolError("PROTOCOL_MEMBER_NAME_LIMIT")
    try:
        xml.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise EisProtocolError("PROTOCOL_XML_ENCODING_UNSUPPORTED") from error
    declaration = re.search(rb"<\?xml\b[^?]*\bencoding\s*=\s*['\"]([^'\"]+)['\"]", xml[:200])
    if declaration and declaration[1].lower() not in {b"utf-8", b"utf8"}:
        raise EisProtocolError("PROTOCOL_XML_ENCODING_UNSUPPORTED")
    try:
        parsed = _notice(xml, event.source_member, None, allow_companion_documents=True)
        root = ET.fromstring(xml)
    except ValueError as error:
        raise EisProtocolError("PROTOCOL_XML_INVALID") from error
    if parsed != event:
        raise EisProtocolError("PROTOCOL_SOURCE_MISMATCH")
    if root.tag != f"{{{EXPORT}}}export" or len(root) != 1:
        raise EisProtocolError("PROTOCOL_ROOT_INVALID")
    document = root[0]
    namespace = OOS if event.document_type == "fcsPlacementResult" else EP
    prefix = event.document_type

    def evidence(path: str) -> ProtocolEvidence:
        return ProtocolEvidence(
            xml_sha256=event.xml_sha256,
            source_member=event.source_member,
            document_type=event.document_type,
            locator=path,
            namespace=namespace,
        )

    def child(parent: ET.Element | None, name: str) -> ET.Element | None:
        if parent is None:
            return None
        nodes = [n for n in parent if n.tag.rsplit("}", 1)[-1] == name]
        if len(nodes) > 1 or any(n.tag != f"{{{namespace}}}{name}" for n in nodes):
            raise EisProtocolError("PROTOCOL_FIELD_AMBIGUOUS")
        return nodes[0] if nodes else None

    def unknown(path: str, reason: str = "NOT_RECORDED") -> ProtocolFact[Any]:
        return ProtocolFact(value=None, status="UNKNOWN", reason=reason, evidence=evidence(path))

    def fact(
        parent: ET.Element | None, name: str, path: str, kind: str = "text"
    ) -> ProtocolFact[Any]:
        target = f"{path}/{name}"
        node = child(parent, name)
        if node is None:
            return unknown(target)
        raw = (node.text or "").strip()
        if len(node) or not raw or len(raw) > 200:
            return unknown(target, "INVALID_SCALAR")
        value: str | int | bool | Decimal
        try:
            if kind == "decimal":
                if not re.fullmatch(r"-?[0-9]{1,20}(?:\.[0-9]{1,11})?", raw):
                    return unknown(target, "INVALID_AMOUNT")
                value = Decimal(raw)
            elif kind == "integer":
                if not re.fullmatch(r"[0-9]{1,5}", raw) or int(raw) <= 0:
                    return unknown(target, "INVALID_RANK")
                value = int(raw)
            elif kind == "bool":
                if raw not in {"true", "false", "1", "0"}:
                    return unknown(target, "INVALID_BOOLEAN")
                value = raw in {"true", "1"}
            elif kind == "result":
                if raw not in {"CC", "RC"}:
                    return unknown(target, "UNMAPPED_RESULT_CODE")
                value = raw
            else:
                value = raw
        except (ValueError, InvalidOperation):
            return unknown(target, "INVALID_VALUE")
        return ProtocolFact(value=value, status="PASS", evidence=evidence(target))

    final = event.document_type == "epProtocolEOK2020Final"
    if final:
        info = child(document, "protocolInfo")
        container = child(info, "applicationsInfo")
        list_path = f"{prefix}/protocolInfo/applicationsInfo"
        row_tag = "applicationInfo"
    else:
        container = child(document, "applications")
        list_path = f"{prefix}/applications"
        row_tag = "application"
    rows = list(container) if container is not None else []
    if len(rows) > MAX_APPLICATION_ROWS:
        raise EisProtocolError("PROTOCOL_APPLICATION_LIMIT")
    if any(row.tag != f"{{{namespace}}}{row_tag}" for row in rows):
        raise EisProtocolError("PROTOCOL_APPLICATION_SHAPE_INVALID")
    applications = []
    for index, row in enumerate(rows, 1):
        path = f"{list_path}/{row_tag}[{index}]"
        admission = unknown(path + "/admittedInfo", "NOT_INTERPRETED")
        rank = unknown(path + "/appRating")
        result = unknown(path + "/result")
        right = unknown(path + "/rightConcludeContractPrice")
        amount = unknown(path + "/price")
        source_kind: Literal["FINAL_PROPOSAL", "PROPOSAL", "UNKNOWN"] = "UNKNOWN"
        if final:
            common = child(row, "commonInfo")
            app_id = fact(common, "appNumber", path + "/commonInfo")
            admitted = child(row, "admittedInfo")
            branches = ("singleAppAdmittedInfo", "appAdmittedInfo", "appNotAdmittedInfo")
            selected = [(name, child(admitted, name)) for name in branches]
            selected = [(name, node) for name, node in selected if node is not None]
            if admitted is not None and (len(selected) != 1 or len(admitted) != 1):
                raise EisProtocolError("PROTOCOL_ADMISSION_AMBIGUOUS")
            if selected:
                branch, node = selected[0]
                branch_path = path + "/admittedInfo/" + branch
                if branch == "singleAppAdmittedInfo":
                    admission = fact(node, "admitted", branch_path, "bool")
                    if admission.value is False:
                        raise EisProtocolError("PROTOCOL_ADMISSION_CONTRADICTION")
                elif branch == "appAdmittedInfo":
                    rank = fact(node, "appRating", branch_path, "integer")
                else:
                    admission = ProtocolFact(
                        value=False, status="PASS", evidence=evidence(branch_path)
                    )
                if branch == "singleAppAdmittedInfo":
                    amount = fact(node, "finalPrice", branch_path, "decimal")
                    right = fact(node, "rightConcludeContractPrice", branch_path, "bool")
                    source_kind = "FINAL_PROPOSAL"
                # appAdmittedInfo contains criteria, not an explicit final price.
        else:
            field = "journalNumber" if namespace == OOS else "appNumber"
            app_id = fact(row, field, path)
            rank = fact(row, "appRating", path, "integer")
            result = fact(row, "result", path, "result")
            amount = fact(row, "price", path, "decimal")
            source_kind = "PROPOSAL"
        applications.append(
            ProtocolApplication(
                row_number=index,
                application_id=app_id,
                admission=admission,
                rank=rank,
                result_code=result,
                proposal=ProtocolAmount(
                    amount=amount, source_kind=source_kind, right_to_conclude_contract=right
                ),
            )
        )
    count: ProtocolFact[int] = unknown(list_path, "APPLICATION_LIST_ABSENT_OR_EMPTY")
    distinct: ProtocolFact[int] = unknown(list_path, "APPLICATION_LIST_ABSENT_OR_EMPTY")
    if rows:
        count = ProtocolFact(value=len(rows), status="PASS", evidence=evidence(list_path))
        ids = [row.application_id.value for row in applications]
        if None not in ids and len(set(ids)) == len(ids):
            distinct = ProtocolFact(value=len(ids), status="PASS", evidence=evidence(list_path))
        else:
            distinct = unknown(list_path, "APPLICATION_IDS_MISSING_OR_REPEATED")
    number_parent = child(document, "commonInfo") if final else document
    number_path = prefix + "/commonInfo" if final else prefix
    return EisProtocolFacts(
        source=evidence(prefix),
        purchase_number=event.purchase_number,
        document_kind="FINAL_PROTOCOL"
        if final
        else ("PLACEMENT_RESULT" if namespace == OOS else "PROPOSALS_DISTRIBUTION"),
        published_at=event.published_at,
        protocol_number=fact(
            number_parent, "docNumber" if final else "protocolNumber", number_path
        ),
        foundation_protocol_number=fact(document, "foundationProtocolNumber", prefix)
        if namespace == OOS
        else unknown(prefix + "/foundationProtocolNumber", "NOT_APPLICABLE"),
        lot_number=fact(document, "lotNumber", prefix)
        if namespace == OOS
        else unknown(prefix + "/lotNumber", "NOT_APPLICABLE"),
        observed_rows=count,
        represented_applications=distinct,
        applications=tuple(applications),
    )
