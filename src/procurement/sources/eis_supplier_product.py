"""Pure UNKNOWN-only association of a saved EIS position and supplier details."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_characteristic_compare import SavedPosition
from procurement.sources.supplier_product_details import SupplierProductDetails
from procurement.storage.eis_supplier_catalog import SupplierCatalogRequest

POLICY_VERSION: Literal["eis-position-supplier-product-v1"] = "eis-position-supplier-product-v1"
MAX_ROWS = 24


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierProductRequest(Frozen):
    catalog: SupplierCatalogRequest
    product_run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")

    @model_validator(mode="after")
    def exact_product(self) -> Self:
        try:
            if str(uuid.UUID(self.product_run_id)) != self.product_run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_PRODUCT_RUN_ID_INVALID") from error
        if self.catalog.stage != "PRODUCT":
            raise ValueError("SUPPLIER_PRODUCT_CATALOG_STAGE_INVALID")
        return self


RowReason = Literal[
    "SUPPLIER_DETAILS_NOT_EXTRACTED",
    "POSITION_CHARACTERISTIC_NAME_MISSING",
    "POSITION_CHARACTERISTIC_VALUES_INCOMPLETE",
    "SUPPLIER_CHARACTERISTIC_MISSING",
    "SUPPLIER_CHARACTERISTIC_AMBIGUOUS",
    "PUBLIC_LABEL_MATCH_RECORDED",
]


class SupplierProductRow(Frozen):
    characteristic_index: int = Field(strict=True, ge=1, le=MAX_ROWS)
    name: str = Field(min_length=1, max_length=300)
    supplier_indices: tuple[int, ...] = Field(max_length=16)
    observation: Literal["UNKNOWN"] = "UNKNOWN"
    reason: RowReason

    @model_validator(mode="after")
    def exact_indices(self) -> Self:
        if any(type(index) is not int or not 1 <= index <= 16 for index in self.supplier_indices):
            raise ValueError("SUPPLIER_PRODUCT_ROW_INDEX_INVALID")
        if len(set(self.supplier_indices)) != len(self.supplier_indices):
            raise ValueError("SUPPLIER_PRODUCT_ROW_INDEX_DUPLICATE")
        matched = len(self.supplier_indices)
        if (
            (self.reason == "PUBLIC_LABEL_MATCH_RECORDED" and matched != 1)
            or (self.reason == "SUPPLIER_CHARACTERISTIC_AMBIGUOUS" and matched < 2)
            or (
                self.reason
                in {
                    "SUPPLIER_CHARACTERISTIC_MISSING",
                    "POSITION_CHARACTERISTIC_NAME_MISSING",
                }
                and matched != 0
            )
        ):
            raise ValueError("SUPPLIER_PRODUCT_ROW_REASON_CONFLICT")
        return self


class SupplierProductReport(Frozen):
    policy_version: Literal["eis-position-supplier-product-v1"] = POLICY_VERSION
    scope: Literal["PUBLIC_POSITION_AND_SAVED_PRODUCT"] = "PUBLIC_POSITION_AND_SAVED_PRODUCT"
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    request: SupplierProductRequest
    parent_product_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    position: SavedPosition
    details: SupplierProductDetails
    rows: tuple[SupplierProductRow, ...] = Field(max_length=MAX_ROWS)
    row_count: int = Field(strict=True, ge=0, le=MAX_ROWS)
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    price_comparability: Literal["UNKNOWN"] = "UNKNOWN"
    unit_cost: Literal["UNKNOWN"] = "UNKNOWN"
    party_total: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    profit: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    specification_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0

    @model_validator(mode="after")
    def exact_report(self) -> Self:
        try:
            if str(uuid.UUID(self.run_id)) != self.run_id:
                raise ValueError
        except ValueError as error:
            raise ValueError("SUPPLIER_PRODUCT_RUN_ID_INVALID") from error
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("SUPPLIER_PRODUCT_TIME_INVALID")
        if self.position.selection != self.request.catalog.page.position.selection:
            raise ValueError("SUPPLIER_PRODUCT_POSITION_SELECTION_CONFLICT")
        if self.details.html_sha256 != self.source_body_sha256:
            raise ValueError("SUPPLIER_PRODUCT_BODY_DIGEST_CONFLICT")
        if self.row_count != len(self.rows):
            raise ValueError("SUPPLIER_PRODUCT_ROW_COUNT_INVALID")
        expected = tuple(range(1, len(self.rows) + 1))
        if tuple(row.characteristic_index for row in self.rows) != expected:
            raise ValueError("SUPPLIER_PRODUCT_ROW_ORDER_INVALID")
        if len(self.rows) != len(self.position.position.characteristics):
            raise ValueError("SUPPLIER_PRODUCT_ROW_POSITION_CONFLICT")
        for row in self.rows:
            characteristic = self.position.position.characteristics[row.characteristic_index - 1]
            expected_name = (
                characteristic.name.value
                if characteristic.name and characteristic.name.value
                else "(без названия)"
            )
            if row.name != expected_name:
                raise ValueError("SUPPLIER_PRODUCT_ROW_NAME_CONFLICT")
            if any(index > len(self.details.characteristics) for index in row.supplier_indices):
                raise ValueError("SUPPLIER_PRODUCT_ROW_INDEX_INVALID")
        if self.rows != _build_rows(self.position, self.details):
            raise ValueError("SUPPLIER_PRODUCT_ROW_DERIVATION_CONFLICT")
        return self


class SavedSupplierProduct(Frozen):
    report: SupplierProductReport
    created: bool = Field(strict=True)
    source_requests: Literal[0] = 0
    jobs_created: Literal[0] = 0


_SPACE = re.compile(r"\s+")
_ALIASES = (
    frozenset({"формат", "формат бумаги"}),
    frozenset(
        {
            "плотность",
            "плотность бумаги",
            "плотность г м2",
            "масса бумаги площадью 1м грамм",
        }
    ),
    frozenset({"белизна", "белизна cie", "cie"}),
    frozenset({"яркость", "яркость iso", "iso яркость"}),
    frozenset({"непрозрачность"}),
    frozenset({"количество листов", "количество листов в пачке", "листов в пачке", "листов"}),
    frozenset({"цвет"}),
    frozenset({"класс бумаги", "марка бумаги", "класс"}),
)


def _label(value: str) -> str:
    return _SPACE.sub(" ", re.sub(r"[^0-9a-zа-яё]+", " ", value.casefold())).strip()


def _alias(value: str) -> frozenset[str] | None:
    normalized = _label(value)
    return next((group for group in _ALIASES if normalized in group), None)


def _build_rows(
    position: SavedPosition, details: SupplierProductDetails
) -> tuple[SupplierProductRow, ...]:
    supplier_groups: list[tuple[int, frozenset[str]]] = []
    for index, supplier_characteristic in enumerate(details.characteristics, 1):
        group = _alias(supplier_characteristic.label_raw)
        if group is not None:
            supplier_groups.append((index, group))

    rows: list[SupplierProductRow] = []
    if len(position.position.characteristics) > MAX_ROWS:
        raise ValueError("SUPPLIER_PRODUCT_POSITION_LIMIT")
    for index, position_characteristic in enumerate(position.position.characteristics, 1):
        name_value = (
            position_characteristic.name.value
            if position_characteristic.name
            and isinstance(position_characteristic.name.value, str)
            and position_characteristic.name.value.strip()
            else None
        )
        name = name_value or "(без названия)"
        group = _alias(name_value) if name_value is not None else None
        matched = tuple(
            i for i, candidate in supplier_groups if group is not None and candidate == group
        )
        if position_characteristic.name is None or name_value is None:
            reason: RowReason = "POSITION_CHARACTERISTIC_NAME_MISSING"
            matched = ()
        elif (
            position.legacy_values_unknown
            or position_characteristic.truncated
            or any(value.concrete_values_truncated for value in position_characteristic.values)
        ):
            reason = "POSITION_CHARACTERISTIC_VALUES_INCOMPLETE"
        elif not matched and details.status != "EXTRACTED":
            reason = "SUPPLIER_DETAILS_NOT_EXTRACTED"
        elif not matched:
            reason = "SUPPLIER_CHARACTERISTIC_MISSING"
        elif len(matched) > 1:
            reason = "SUPPLIER_CHARACTERISTIC_AMBIGUOUS"
        elif details.status != "EXTRACTED":
            reason = "SUPPLIER_DETAILS_NOT_EXTRACTED"
        else:
            reason = "PUBLIC_LABEL_MATCH_RECORDED"
        rows.append(
            SupplierProductRow(
                characteristic_index=index,
                name=name,
                supplier_indices=matched,
                reason=reason,
            )
        )
    return tuple(rows)


def build_supplier_product_report(
    request: SupplierProductRequest,
    position: SavedPosition,
    details: SupplierProductDetails,
    *,
    parent_product_report_sha256: str,
    position_sha256: str,
    source_body_sha256: str,
    run_id: str,
    created_at: datetime,
) -> SupplierProductReport:
    """Record bounded public label associations without compliance conclusions."""

    rows = _build_rows(position, details)
    return SupplierProductReport(
        run_id=run_id,
        request=request,
        parent_product_report_sha256=parent_product_report_sha256,
        position_sha256=position_sha256,
        source_body_sha256=source_body_sha256,
        created_at=created_at,
        position=position,
        details=details,
        rows=rows,
        row_count=len(rows),
    )
