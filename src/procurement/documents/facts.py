"""Маппер текстовых блоков в требования ТЗ.

Модуль превращает нативные текстовые блоки в типизированные требования
и честно фиксирует непокрытые блоки. Неподошедший текст никогда не
становится фактом: он уходит в ``unmapped`` с явной причиной.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.provenance import Provenance
from procurement.domain.requirements import Operator, Requirement

DEFAULT_FACT_MIN_CONFIDENCE = 0.75
"""Порог доверия по умолчанию: блоки с меньшим confidence не маппятся."""

# Регулярка гарантии: число и единица (месяцы либо годы с пересчётом в месяцы).
_WARRANTY_RE = re.compile(
    r"гаранти\w*\s+(?:не\s+менее|≥|>=?)\s*(\d+)\s*"
    r"(мес\w*|месяц\w*|год\w*|г\.|лет|года?)",
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


class UnmappedReason(StrEnum):
    """Почему блок не превратился в требование."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NO_PATTERN_MATCH = "NO_PATTERN_MATCH"


class UnmappedBlock(BaseModel):
    """Блок, из которого факт не извлечён, с явной причиной."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1, description="Исходный текст блока")
    provenance: Provenance
    reason: UnmappedReason


class FactMappingResult(BaseModel):
    """Итог маппинга блоков в требования."""

    model_config = ConfigDict(frozen=True)

    requirements: tuple[Requirement, ...] = ()
    unmapped: tuple[UnmappedBlock, ...] = ()
    blocks_total: int = Field(ge=0)
    blocks_mapped: int = Field(ge=0)
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
        """Число смаппленных блоков не может превышать общее число."""
        if self.blocks_mapped > self.blocks_total:
            raise ValueError("blocks_mapped не может превышать blocks_total")
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


def map_blocks_to_requirements(
    blocks: tuple[ExtractedBlock, ...],
    *,
    min_confidence: float = DEFAULT_FACT_MIN_CONFIDENCE,
) -> FactMappingResult:
    """Смаппить текстовые блоки в требования ТЗ.

    Блок с доверием ниже порога уходит в ``unmapped`` с причиной
    ``LOW_CONFIDENCE`` без попыток маппинга. Пустой блок уходит в
    ``unmapped`` с причиной ``NO_PATTERN_MATCH``. Из одного блока может
    получиться несколько требований (по одному на совпадение).

    Правила R1–R4: запрет эквивалента (флаг уровня вызова, True никогда),
    якорная дата поставки (первая валидная), ключевые числовые
    характеристики (глубина, пропускная способность, мощность) и страна
    происхождения (EQ по «Страна происхождения: X», NE по словарю
    «прилагательное производства не допускается»). Блок считается mapped,
    если дал хотя бы одно требование, флаг R1 или дату R2.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence должен лежать в [0, 1]")
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
                candidate = date(
                    int(match.group(3)), int(match.group(2)), int(match.group(1))
                )
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
            country = COUNTRY_ADJECTIVE_MAP.get(
                _normalize_country_adjective(match.group(1))
            )
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
        requirements=tuple(found),
        unmapped=tuple(unmapped),
        blocks_total=len(blocks),
        blocks_mapped=mapped_count,
        equivalent_allowed=equivalent_allowed,
        delivery_deadline=delivery_deadline,
    )
