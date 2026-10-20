"""Маппер текстовых блоков в требования ТЗ.

Модуль превращает нативные текстовые блоки в типизированные требования
и честно фиксирует непокрытые блоки. Неподошедший текст никогда не
становится фактом: он уходит в ``unmapped`` с явной причиной.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement

DEFAULT_FACT_MIN_CONFIDENCE = 0.75
"""Порог доверия по умолчанию: блоки с меньшим confidence не маппятся."""

# Регулярка гарантии: число и единица (месяцы либо годы с пересчётом в месяцы).
_WARRANTY_RE = re.compile(
    r"гаранти\w*\s+(?:(?:сроком\s+)?(?:не\s+менее|≥|>=?)\s*|сроком\s+)(\d+)\s*"
    r"(мес\w*|месяц\w*|год\w*|г\.|лет|года?)",
    re.IGNORECASE,
)
_TABLE_CELL_RE = re.compile(
    r"^(?P<row>table \d+ row \d+(?: cell \d+ nested table \d+ row \d+)*)"
    r" cell (?P<cell>\d+)$"
)
_TABLE_NUMERIC_VALUE_RE = re.compile(
    r"^(?P<operator>≥|<=|≤|>=|больше\s+или\s+равно|меньше\s+или\s+равно|"
    r"не\s+менее|не\s+более)\s*(?P<value>\d+(?:[.,]\d+)?)"
    r"(?:\s+(?P<unit>[^\d]+?))?\s*$",
    re.IGNORECASE,
)
_TABLE_SEPARATE_UNIT_RE = re.compile(
    r"^(?:мегабайт\s+в\s+секунду|гбайт|мбайт|гбит/с|мбит/с|"
    r"шт\.?|штук|мм|см|м|кг|вт|квт|мгц|ггц)$",
    re.IGNORECASE,
)
# Регулярка портов: число портов с нижней границей.
_PORTS_RE = re.compile(
    r"портов?\s+(?:не\s+менее|≥|>=?)\s*(\d+)",
    re.IGNORECASE,
)
# R1: запрет эквивалента. True не ставится никогда: отсутствие фразы — это
# None, а не разрешение.
_EQUIVALENT_FORBIDDEN_RE = re.compile(
    r"эквивалент\w*\s+не\s+допуска[ею]тся",
    re.IGNORECASE,
)
# R2: якорная абсолютная дата поставки (день.месяц.год). Двоеточие или тире
# после якоря («Срок поставки: до ...») — обычная форма ТЗ, допускается.
_DELIVERY_DATE_RE = re.compile(
    r"(?:срок\w*\s+поставки|поставка)\s*[:—–-]?\s*(?:не\s+позднее|до)\s*"
    r"(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)
# R3: ключевые числовые характеристики. Свободного парсинга существительных
# нет — только перечисленные шаблоны.
_DEPTH_RE = re.compile(
    r"глубин\w*\s+(?:не\s+более|<=?|≤)\s*(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b",
    re.IGNORECASE,
)
_DATA_RATE_RE = re.compile(
    r"пропускн\w+\s+способност\w*\s+(?:не\s+менее|>=?|≥)\s*"
    r"(\d+(?:[.,]\d+)?)\s*(\S+)",
    re.IGNORECASE,
)
# Длинная альтернатива «МВт» стоит первой, иначе «Вт» съест её хвост.
_POWER_RE = re.compile(
    r"мощност\w*\s+(?:не\s+менее|>=?|≥)\s*(\d+(?:[.,]\d+)?)\s*(МВт|кВт|Вт)",
    re.IGNORECASE,
)
# R4: страна происхождения, только EQ.
_COUNTRY_RE = re.compile(
    r"стран\w*\s+происхождени\w*\s*:\s*([А-Яа-яA-Za-z][\w-]*)",
    re.IGNORECASE,
)
# Таблица ручная, расширяется отдельным срезом со сверкой по реестру
# разрешённых стран; неизвестное прилагательное — НЕ угадывать.
COUNTRY_ADJECTIVE_MAP: dict[str, str] = {
    "китайский": "Китай",
    "китайского": "Китай",
    "российский": "Россия",
    "российского": "Россия",
    "белорусский": "Беларусь",
    "белорусского": "Беларусь",
    "казахстанский": "Казахстан",
    "казахстанского": "Казахстан",
    "турецкий": "Турция",
    "турецкого": "Турция",
    "немецкий": "Германия",
    "немецкого": "Германия",
}
"""Нормализованное прилагательное → каноническая страна (только явные пары)."""
# R4-NE: запрет страны через прилагательное («китайского производства
# не допускается»). Якоря «эквивалент» здесь нет, правило R1 не задевается.
_COUNTRY_NE_RE = re.compile(
    r"([А-Яа-яA-Za-z][\w-]*)\s+производства\s+не\s+допуска[ею]тся",
    re.IGNORECASE,
)
# Разрешительные документы повышаются в требования только при явном модальном
# якоре. Простое упоминание сертификата в описании товара не является требованием.
_CERTIFICATE_REQUIREMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Декларация соответствия ТР ТС",
        re.compile(
            r"(?:требуется|необходимо\s+наличие|обязательн\w*\s+наличие|предоставить)\s+"
            r"(?:действующ\w+\s+)?декларац\w+\s+соответств\w+\s+ТР\s*ТС",
            re.IGNORECASE,
        ),
    ),
    (
        "Сертификат соответствия ЕАЭС",
        re.compile(
            r"(?:требуется|необходимо\s+наличие|обязательн\w*\s+наличие|предоставить)\s+"
            r"(?:действующ\w+\s+)?сертификат\w*\s+соответств\w+\s+ЕАЭС",
            re.IGNORECASE,
        ),
    ),
)


class DocumentRole(StrEnum):
    """Назначение документа до семантического маппинга его блоков."""

    UNKNOWN = "UNKNOWN"
    TENDER_REQUIREMENTS = "TENDER_REQUIREMENTS"
    SUPPLIER_QUOTE = "SUPPLIER_QUOTE"
    APPLICATION_ATTACHMENT = "APPLICATION_ATTACHMENT"


class UnmappedReason(StrEnum):
    """Почему блок не превратился в требование."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NO_PATTERN_MATCH = "NO_PATTERN_MATCH"
    NON_REQUIREMENT_DOCUMENT = "NON_REQUIREMENT_DOCUMENT"
    UNKNOWN_DOCUMENT_ROLE = "UNKNOWN_DOCUMENT_ROLE"


class UnmappedBlock(BaseModel):
    """Блок, из которого факт не извлечён, с явной причиной."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, description="Исходный текст блока")
    provenance: Provenance
    reason: UnmappedReason


class TableRowCandidate(BaseModel):
    """Непроверенная числовая характеристика из соседних ячеек одной строки.

    Не является ``Requirement``: имя свойства, предмет закупки, обязательность
    и смысл единицы ещё должны быть подтверждены reviewer по исходным ячейкам.
    """

    model_config = ConfigDict(frozen=True)

    property_text: str = Field(min_length=1)
    value_text: str = Field(min_length=1)
    operator: Operator
    value: Decimal
    unit: str | None = None
    source_blocks: tuple[UnmappedBlock, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _check_sources(self) -> TableRowCandidate:
        if self.operator not in (Operator.GE, Operator.LE):
            raise ValueError("табличный кандидат допускает только GE/LE")
        if self.source_blocks[0].text.strip() != self.property_text:
            raise ValueError("property_text должен совпадать с первой source cell")
        if self.source_blocks[1].text.strip() != self.value_text:
            raise ValueError("value_text должен совпадать со второй source cell")
        if len({block.provenance.document_id for block in self.source_blocks}) != 1:
            raise ValueError("ячейки кандидата должны быть из одного документа")
        locations = [
            _TABLE_CELL_RE.fullmatch(block.provenance.locator) for block in self.source_blocks
        ]
        if any(location is None for location in locations) or any(
            block.provenance.extractor is not Extractor.NATIVE_DOCX for block in self.source_blocks
        ):
            raise ValueError("кандидат требует нативные DOCX table cells")
        parsed = [location for location in locations if location is not None]
        if len({location.group("row") for location in parsed}) != 1 or [
            int(location.group("cell")) for location in parsed
        ] != list(range(int(parsed[0].group("cell")), int(parsed[0].group("cell")) + len(parsed))):
            raise ValueError("source cells кандидата должны быть соседними в одной строке")
        if (
            self.unit is not None
            and len(self.source_blocks) == 3
            and self.source_blocks[2].text.strip() != self.unit
        ):
            raise ValueError("unit должен совпадать с третьей source cell")
        return self


class CompletenessStatus(StrEnum):
    """Полнота покрытия требований в проверенном объёме документа."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class UnmappedDisposition(StrEnum):
    """Решение reviewer по блоку, который автоматический маппер не разобрал."""

    MATERIAL_REQUIREMENT = "MATERIAL_REQUIREMENT"
    NON_REQUIREMENT = "NON_REQUIREMENT"
    EXCLUDED_FROM_SCOPE = "EXCLUDED_FROM_SCOPE"


class UnmappedBlockReview(BaseModel):
    """Проверенное человеком решение по точному unmapped-блоку."""

    model_config = ConfigDict(frozen=True)

    block: UnmappedBlock
    disposition: UnmappedDisposition
    rationale: str = Field(min_length=1, description="Основание решения по блоку")


class CompletenessAssessment(BaseModel):
    """Оценка полноты, не подменяющая результат compliance.

    Автоматический маппинг создаёт только ``UNKNOWN``. Для ``PASS`` или ``FAIL``
    обязательны границы проверки и привязка к человеку, времени и review record.
    """

    model_config = ConfigDict(frozen=True)

    status: CompletenessStatus = CompletenessStatus.UNKNOWN
    scope: str | None = Field(
        default=None,
        min_length=1,
        description="Проверенный объём документа и существенных требований",
    )
    source_document_ids: tuple[str, ...] = ()
    reviewer_id: str | None = Field(default=None, min_length=1)
    reviewed_at: datetime | None = None
    review_reference: str | None = Field(default=None, min_length=1)
    unmapped_reviews: tuple[UnmappedBlockReview, ...] = ()

    @model_validator(mode="after")
    def _check_review_evidence(self) -> CompletenessAssessment:
        """Не разрешать терминальную оценку без полной review-привязки."""
        review_fields = (
            self.scope,
            self.reviewer_id,
            self.reviewed_at,
            self.review_reference,
        )
        has_review_evidence = any(value is not None for value in review_fields)
        has_all_review_evidence = all(value is not None for value in review_fields)
        has_review_payload = bool(
            has_review_evidence or self.source_document_ids or self.unmapped_reviews
        )
        if has_review_payload and not has_all_review_evidence:
            raise ValueError("review evidence полноты должно быть заполнено целиком")
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at полноты должен включать timezone")
        if has_all_review_evidence and not self.source_document_ids:
            raise ValueError("review полноты должен быть привязан к source_document_ids")
        if len(set(self.source_document_ids)) != len(self.source_document_ids):
            raise ValueError("source_document_ids не должны повторяться")
        if any(not document_id.strip() for document_id in self.source_document_ids):
            raise ValueError("source_document_ids не должны быть пустыми")
        if (self.unmapped_reviews or self.status is not CompletenessStatus.UNKNOWN) and not (
            has_all_review_evidence and self.source_document_ids
        ):
            raise ValueError("решения по полноте требуют reviewer, scope и source binding")
        review_keys = [
            (
                review.block.text,
                review.block.provenance.document_id,
                review.block.provenance.locator,
                review.block.reason,
            )
            for review in self.unmapped_reviews
        ]
        if len(set(review_keys)) != len(review_keys):
            raise ValueError("один unmapped-блок нельзя проверить дважды")
        if self.status is CompletenessStatus.PASS and any(
            review.disposition is UnmappedDisposition.MATERIAL_REQUIREMENT
            for review in self.unmapped_reviews
        ):
            raise ValueError("PASS несовместим с неразобранным существенным требованием")
        if self.status is CompletenessStatus.FAIL and not any(
            review.disposition is UnmappedDisposition.MATERIAL_REQUIREMENT
            for review in self.unmapped_reviews
        ):
            raise ValueError("FAIL полноты требует выявленного существенного требования")
        return self


class FactMappingResult(BaseModel):
    """Итог маппинга блоков в требования."""

    model_config = ConfigDict(frozen=True)

    document_role: DocumentRole
    requirements: tuple[Requirement, ...] = ()
    table_row_candidates: tuple[TableRowCandidate, ...] = ()
    unmapped: tuple[UnmappedBlock, ...] = ()
    blocks_total: int = Field(ge=0)
    blocks_mapped: int = Field(ge=0)
    completeness: CompletenessAssessment = Field(default_factory=CompletenessAssessment)
    # R1: None — фраза о запрете эквивалента нигде не встретилась.
    equivalent_allowed: bool | None = Field(
        default=None, description="False при явном запрете эквивалента"
    )
    # R2: None — абсолютной даты поставки в блоках нет.
    delivery_deadline: date | None = Field(
        default=None, description="Первая валидная якорная дата поставки"
    )

    @model_validator(mode="after")
    def _check_counts(self) -> FactMappingResult:
        """Проверить счётчики, роль документа и доказательства полноты."""
        if self.blocks_mapped > self.blocks_total:
            raise ValueError("blocks_mapped не может превышать blocks_total")
        if self.blocks_mapped + len(self.unmapped) != self.blocks_total:
            raise ValueError("каждый входной блок должен быть mapped или unmapped")
        if self.document_role is not DocumentRole.TENDER_REQUIREMENTS:
            if (
                self.requirements
                or self.table_row_candidates
                or self.blocks_mapped
                or self.equivalent_allowed is not None
                or self.delivery_deadline is not None
            ):
                raise ValueError("документ без роли ТЗ не может создавать требования или флаги ТЗ")
            expected_reason = (
                UnmappedReason.NON_REQUIREMENT_DOCUMENT
                if self.document_role
                in {DocumentRole.SUPPLIER_QUOTE, DocumentRole.APPLICATION_ATTACHMENT}
                else UnmappedReason.UNKNOWN_DOCUMENT_ROLE
            )
            if len(self.unmapped) != self.blocks_total or any(
                block.reason is not expected_reason for block in self.unmapped
            ):
                raise ValueError("каждый блок документа без роли ТЗ должен остаться unmapped")
            if self.completeness.status is not CompletenessStatus.UNKNOWN:
                raise ValueError(
                    "документ без роли ТЗ не может иметь подтверждённую полноту требований"
                )
        known_document_ids = {
            requirement.provenance.document_id for requirement in self.requirements
        } | {block.provenance.document_id for block in self.unmapped}
        if any(
            block not in self.unmapped
            for candidate in self.table_row_candidates
            for block in candidate.source_blocks
        ):
            raise ValueError("кандидат должен ссылаться на unmapped-блоки результата")
        if (
            self.completeness.source_document_ids
            and known_document_ids
            and known_document_ids != set(self.completeness.source_document_ids)
        ):
            raise ValueError("source_document_ids review не совпадают с provenance результата")
        if self.completeness.status is CompletenessStatus.PASS:
            if not self.requirements or self.blocks_total == 0 or self.blocks_mapped == 0:
                raise ValueError("PASS полноты требует хотя бы одного формализованного требования")
            reviewed_blocks = [review.block for review in self.completeness.unmapped_reviews]
            if len(reviewed_blocks) != len(self.unmapped) or any(
                block not in reviewed_blocks for block in self.unmapped
            ):
                raise ValueError("PASS требует решения reviewer по каждому unmapped-блоку")
            if any(
                review.disposition is UnmappedDisposition.MATERIAL_REQUIREMENT
                for review in self.completeness.unmapped_reviews
            ):
                raise ValueError("PASS невозможен при неразобранном существенном требовании")
        if self.completeness.status is CompletenessStatus.FAIL:
            reviewed_blocks = [review.block for review in self.completeness.unmapped_reviews]
            material_blocks = [
                review.block
                for review in self.completeness.unmapped_reviews
                if review.disposition is UnmappedDisposition.MATERIAL_REQUIREMENT
            ]
            if any(block not in self.unmapped for block in reviewed_blocks) or not material_blocks:
                raise ValueError("FAIL должен ссылаться на существенный unmapped-блок результата")
        return self


def _is_year_unit(unit: str) -> bool:
    """Определить, задана ли единица в годах (нужен пересчёт в месяцы)."""
    normalized = unit.strip().lower()
    # Все месячные формы начинаются с «мес» (мес., месяцев, месяц...).
    return not normalized.startswith("мес")


def _to_decimal(raw: str) -> Decimal:
    """Число с десятичной запятой или точкой в Decimal («1,5» → 1.5)."""
    return Decimal(raw.replace(",", "."))


def _normalize_country_adjective(raw: str) -> str:
    """Привести прилагательное к ключу словаря: strip + lower + ё→е."""
    return raw.strip().lower().replace("ё", "е")


def _table_row_candidates(
    blocks: tuple[ExtractedBlock, ...],
    unmapped: tuple[UnmappedBlock, ...],
    min_confidence: float,
) -> tuple[TableRowCandidate, ...]:
    """Связать соседние ячейки DOCX, не повышая их до требований."""
    available = {(block.provenance, block.text): block for block in unmapped}
    rows: dict[tuple[str, str], dict[int, UnmappedBlock]] = {}
    for block in blocks:
        provenance = block.provenance
        if (
            provenance.extractor is not Extractor.NATIVE_DOCX
            or provenance.confidence < min_confidence
        ):
            continue
        match = _TABLE_CELL_RE.fullmatch(provenance.locator)
        source = available.get((provenance, block.text))
        if match is None or source is None or source.reason is not UnmappedReason.NO_PATTERN_MATCH:
            continue
        rows.setdefault((provenance.document_id, match.group("row")), {})[
            int(match.group("cell"))
        ] = source

    candidates: list[TableRowCandidate] = []
    for cells in rows.values():
        for index, value_block in cells.items():
            property_block = cells.get(index - 1)
            if property_block is None or not property_block.text.strip():
                continue
            match = _TABLE_NUMERIC_VALUE_RE.fullmatch(value_block.text.strip())
            if match is None:
                continue
            operator_text = match.group("operator").lower()
            operator = (
                Operator.LE
                if operator_text in ("<=", "≤", "меньше или равно", "не более")
                else Operator.GE
            )
            sources = [property_block, value_block]
            unit = match.group("unit")
            next_block = cells.get(index + 1)
            if unit is None and next_block is not None:
                next_text = next_block.text.strip()
                if _TABLE_SEPARATE_UNIT_RE.fullmatch(next_text):
                    unit = next_text
                    sources.append(next_block)
            candidates.append(
                TableRowCandidate(
                    property_text=property_block.text.strip(),
                    value_text=value_block.text.strip(),
                    operator=operator,
                    value=_to_decimal(match.group("value")),
                    unit=unit,
                    source_blocks=tuple(sources),
                )
            )
    return tuple(candidates)


def map_blocks_to_requirements(
    blocks: tuple[ExtractedBlock, ...],
    *,
    document_role: DocumentRole,
    min_confidence: float = DEFAULT_FACT_MIN_CONFIDENCE,
) -> FactMappingResult:
    """Смаппить текстовые блоки в требования ТЗ.

    ``document_role`` обязателен: только ``TENDER_REQUIREMENTS`` разрешает
    создавать требования. Для ``SUPPLIER_QUOTE``, ``APPLICATION_ATTACHMENT`` и
    ``UNKNOWN`` все блоки остаются unmapped, даже если текст похож на ТЗ.

    Блок с доверием ниже порога уходит в ``unmapped`` с причиной
    ``LOW_CONFIDENCE`` без попыток маппинга. Пустой блок уходит в
    ``unmapped`` с причиной ``NO_PATTERN_MATCH``. Из одного блока может
    получиться несколько требований (по одному на совпадение).

    Правила R1–R4: запрет эквивалента (флаг уровня вызова, True никогда),
    якорная дата поставки (первая валидная), ключевые числовые
    характеристики (глубина, пропускная способность, мощность), страна
    происхождения (EQ по «Страна происхождения: X», NE по словарю
    «прилагательное производства не допускается») и два явных вида требований
    разрешительных документов. Блок считается mapped, если дал хотя бы одно
    требование, флаг R1 или дату R2.
    """
    if not isinstance(document_role, DocumentRole):
        raise TypeError("document_role должен быть DocumentRole")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence должен лежать в [0, 1]")
    if document_role is not DocumentRole.TENDER_REQUIREMENTS:
        reason = (
            UnmappedReason.NON_REQUIREMENT_DOCUMENT
            if document_role
            in {DocumentRole.SUPPLIER_QUOTE, DocumentRole.APPLICATION_ATTACHMENT}
            else UnmappedReason.UNKNOWN_DOCUMENT_ROLE
        )
        return FactMappingResult(
            document_role=document_role,
            requirements=(),
            unmapped=tuple(
                UnmappedBlock(
                    text=block.text,
                    provenance=block.provenance,
                    reason=reason,
                )
                for block in blocks
            ),
            blocks_total=len(blocks),
            blocks_mapped=0,
        )
    found: list[Requirement] = []
    unmapped: list[UnmappedBlock] = []
    mapped_count = 0
    # R1 виден на уровне всего вызова; True не ставим никогда.
    equivalent_allowed: bool | None = None
    # R2: первая валидная абсолютная дата побеждает.
    delivery_deadline: date | None = None
    for block in blocks:
        # Блок с низким доверием не маппим даже при узнаваемом тексте.
        if block.provenance.confidence < min_confidence:
            unmapped.append(
                UnmappedBlock(
                    text=block.text,
                    provenance=block.provenance,
                    reason=UnmappedReason.LOW_CONFIDENCE,
                )
            )
            continue
        stripped = block.text.strip()
        # Пробельный текст фактом не становится.
        if not stripped:
            unmapped.append(
                UnmappedBlock(
                    text=block.text,
                    provenance=block.provenance,
                    reason=UnmappedReason.NO_PATTERN_MATCH,
                )
            )
            continue
        block_requirements: list[Requirement] = []
        # Правило гарантии: нижняя граница срока, годы пересчитываем в месяцы.
        for match in _WARRANTY_RE.finditer(stripped):
            count = int(match.group(1))
            months = count * 12 if _is_year_unit(match.group(2)) else count
            block_requirements.append(
                Requirement(
                    property="warranty",
                    operator=Operator.GE,
                    value=Decimal(months),
                    unit="мес",
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # Правило портов: нижняя граница числа портов Ethernet.
        for match in _PORTS_RE.finditer(stripped):
            count = int(match.group(1))
            block_requirements.append(
                Requirement(
                    property="ethernet_ports",
                    operator=Operator.GE,
                    value=Decimal(count),
                    unit="шт",
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # R1 (запрет эквивалента): фраза делает блок mapped без требований.
        block_equivalent_hit = _EQUIVALENT_FORBIDDEN_RE.search(stripped) is not None
        if block_equivalent_hit:
            equivalent_allowed = False
        # R2 (якорная дата): первое валидное совпадение в блоке.
        block_deadline: date | None = None
        for match in _DELIVERY_DATE_RE.finditer(stripped):
            try:
                candidate = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except ValueError:
                # Невалидная дата (например 32.13.2026): не исключение наружу,
                # а пропуск совпадения.
                continue
            block_deadline = candidate
            break
        if block_deadline is not None and delivery_deadline is None:
            delivery_deadline = block_deadline
        # R3: ключевые числовые характеристики, единица — сырой строкой.
        for match in _DEPTH_RE.finditer(stripped):
            block_requirements.append(
                Requirement(
                    property="depth",
                    operator=Operator.LE,
                    value=_to_decimal(match.group(1)),
                    unit=match.group(2),
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        for match in _DATA_RATE_RE.finditer(stripped):
            block_requirements.append(
                Requirement(
                    property="data_rate",
                    operator=Operator.GE,
                    value=_to_decimal(match.group(1)),
                    # Отрезаем пунктуацию конца предложения от единицы.
                    unit=match.group(2).rstrip(".,;:"),
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        for match in _POWER_RE.finditer(stripped):
            block_requirements.append(
                Requirement(
                    property="power",
                    operator=Operator.GE,
                    value=_to_decimal(match.group(1)),
                    unit=match.group(2),
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # R4: страна происхождения, только EQ.
        for match in _COUNTRY_RE.finditer(stripped):
            block_requirements.append(
                Requirement(
                    property="country_of_origin",
                    operator=Operator.EQ,
                    value=match.group(1),
                    unit=None,
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # R4-NE: запрет страны через прилагательное по явному словарю.
        # Неизвестное прилагательное не угадываем: требования нет, блок
        # ниже уйдёт в unmapped с NO_PATTERN_MATCH общей логикой.
        for match in _COUNTRY_NE_RE.finditer(stripped):
            country = COUNTRY_ADJECTIVE_MAP.get(_normalize_country_adjective(match.group(1)))
            if country is None:
                continue
            block_requirements.append(
                Requirement(
                    property="country_of_origin",
                    operator=Operator.NE,
                    value=country,
                    unit=None,
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # Разрешительный документ: только EXISTS и только при явном требовании.
        # Канонический вид документа хранится в property после префикса, чтобы
        # compliance мог сопоставить его с Certificate.kind без догадок.
        for kind, pattern in _CERTIFICATE_REQUIREMENT_PATTERNS:
            if pattern.search(stripped) is None:
                continue
            block_requirements.append(
                Requirement(
                    property=f"certificate:{kind}",
                    operator=Operator.EXISTS,
                    mandatory=True,
                    weight=1,
                    raw_text=stripped,
                    provenance=block.provenance,
                )
            )
        # Без совпадений факт не синтезируем — фиксируем причину.
        # Блок mapped при требованиях, флаге R1 или дате R2.
        if not block_requirements and not block_equivalent_hit and block_deadline is None:
            unmapped.append(
                UnmappedBlock(
                    text=block.text,
                    provenance=block.provenance,
                    reason=UnmappedReason.NO_PATTERN_MATCH,
                )
            )
            continue
        mapped_count += 1
        found.extend(block_requirements)
    return FactMappingResult(
        document_role=document_role,
        requirements=tuple(found),
        unmapped=tuple(unmapped),
        table_row_candidates=_table_row_candidates(blocks, tuple(unmapped), min_confidence),
        blocks_total=len(blocks),
        blocks_mapped=mapped_count,
        equivalent_allowed=equivalent_allowed,
        delivery_deadline=delivery_deadline,
    )
