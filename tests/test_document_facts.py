"""Тесты маппера блоков в требования ТЗ."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import (
    DEFAULT_FACT_MIN_CONFIDENCE,
    FactMappingResult,
    UnmappedReason,
    map_blocks_to_requirements,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator


def _block(text: str, confidence: float = 1.0) -> ExtractedBlock:
    """Собрать блок с фиксированным provenance для тестов."""
    return ExtractedBlock(
        text=text,
        provenance=Provenance(
            document_id="test-doc",
            locator="paragraph 1",
            extractor=Extractor.NATIVE_DOCX,
            confidence=confidence,
        ),
    )


def test_warranty_months_mapped() -> None:
    """Гарантия в месяцах даёт требование warranty GE 24."""
    block = _block("Гарантия не менее 24 мес.")
    result = map_blocks_to_requirements((block,))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "warranty"
    assert req.operator is Operator.GE
    assert req.value == Decimal(24)
    assert req.unit == "мес"
    assert req.mandatory is True
    # Provenance блока сохраняется один в один.
    assert req.provenance == block.provenance
    assert result.blocks_total == 1
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


def test_warranty_years_converted_to_months() -> None:
    """Годовая гарантия пересчитывается в месяцы (2 года -> 24)."""
    result = map_blocks_to_requirements((_block("Гарантия не менее 2 года"),))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "warranty"
    assert req.operator is Operator.GE
    assert req.value == Decimal(24)
    assert req.unit == "мес"


def test_ports_mapped() -> None:
    """Фраза про порты даёт требование ethernet_ports GE 24."""
    result = map_blocks_to_requirements(
        (_block("Количество портов не менее 24 шт."),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "ethernet_ports"
    assert req.operator is Operator.GE
    assert req.value == Decimal(24)
    assert req.unit == "шт"
    assert result.blocks_mapped == 1


def test_garbage_text_is_unmapped() -> None:
    """Мусор без паттернов не синтезирует факты."""
    result = map_blocks_to_requirements((_block("Поставка в течение 30 дней"),))
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH
    assert result.blocks_mapped == 0
    assert result.blocks_total == 1


def test_low_confidence_block_is_not_mapped() -> None:
    """Блок с confidence ниже порога не маппится даже при узнаваемом тексте."""
    result = map_blocks_to_requirements(
        (_block("Гарантия не менее 24 мес.", confidence=0.74),),
        min_confidence=0.75,
    )
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.LOW_CONFIDENCE
    assert result.blocks_mapped == 0


def test_threshold_out_of_range_raises() -> None:
    """Порог вне [0, 1] отклоняется."""
    with pytest.raises(ValueError):
        map_blocks_to_requirements((_block("Гарантия не менее 24 мес."),), min_confidence=-0.1)
    with pytest.raises(ValueError):
        map_blocks_to_requirements((_block("Гарантия не менее 24 мес."),), min_confidence=1.1)


def test_two_patterns_in_one_block() -> None:
    """Один блок с двумя паттернами даёт два требования, но mapped == 1."""
    result = map_blocks_to_requirements(
        (
            _block(
                "Гарантия не менее 12 мес. Количество портов не менее 24 шт."
            ),
        )
    )
    assert len(result.requirements) == 2
    assert result.blocks_mapped == 1
    assert result.blocks_total == 1
    assert result.unmapped == ()
    props = {req.property for req in result.requirements}
    assert props == {"warranty", "ethernet_ports"}


def test_blocks_mapped_cannot_exceed_total() -> None:
    """Валидатор запрещает blocks_mapped больше blocks_total."""
    with pytest.raises(ValueError):
        FactMappingResult(blocks_total=1, blocks_mapped=2)


def test_default_threshold_constant() -> None:
    """Дефолтный порог равен 0.75."""
    assert DEFAULT_FACT_MIN_CONFIDENCE == 0.75


def test_equivalent_forbidden_sets_flag() -> None:
    """Фраза «эквивалент не допускается» даёт equivalent_allowed=False."""
    result = map_blocks_to_requirements((_block("Эквивалент не допускается"),))
    assert result.equivalent_allowed is False
    assert result.requirements == ()
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


def test_equivalent_absent_gives_none() -> None:
    """Без фразы запрета вывод не делается: equivalent_allowed is None."""
    result = map_blocks_to_requirements((_block("Гарантия не менее 24 мес."),))
    assert result.equivalent_allowed is None


def test_delivery_absolute_date_mapped() -> None:
    """Абсолютная дата поставки извлекается в delivery_deadline."""
    result = map_blocks_to_requirements(
        (_block("Срок поставки не позднее 01.12.2026"),)
    )
    assert result.delivery_deadline == date(2026, 12, 1)
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


def test_delivery_invalid_date_is_unmapped() -> None:
    """Невалидная дата не роняет маппер, блок уходит в unmapped."""
    result = map_blocks_to_requirements((_block("Поставка до 32.13.2026"),))
    assert result.delivery_deadline is None
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH
    assert result.blocks_mapped == 0


def test_delivery_relative_term_is_unmapped() -> None:
    """Относительный срок правилом R2 не покрывается."""
    result = map_blocks_to_requirements((_block("Поставка в течение 30 дней"),))
    assert result.delivery_deadline is None
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH


def test_depth_le_mapped() -> None:
    """Глубина с верхней границей даёт требование depth LE."""
    result = map_blocks_to_requirements((_block("Глубина не более 400 мм"),))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "depth"
    assert req.operator is Operator.LE
    assert req.value == Decimal(400)
    assert req.unit == "мм"
    assert req.mandatory is True
    assert result.blocks_mapped == 1


def test_data_rate_ge_mapped() -> None:
    """Пропускная способность с нижней границей даёт data_rate GE."""
    result = map_blocks_to_requirements(
        (_block("Пропускная способность не менее 10 Гбит/с"),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "data_rate"
    assert req.operator is Operator.GE
    assert req.value == Decimal(10)
    assert req.unit == "Гбит/с"
    assert result.blocks_mapped == 1


def test_power_comma_decimal_mapped() -> None:
    """Запятая превращается в точку: «1,5 кВт» → Decimal("1.5")."""
    result = map_blocks_to_requirements((_block("Мощность не менее 1,5 кВт"),))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "power"
    assert req.operator is Operator.GE
    assert req.value == Decimal("1.5")
    assert req.unit == "кВт"


def test_country_of_origin_eq_mapped() -> None:
    """Страна происхождения даёт требование country_of_origin EQ."""
    result = map_blocks_to_requirements(
        (_block("Страна происхождения: Россия"),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.EQ
    assert req.value == "Россия"
    assert req.unit is None
    assert req.mandatory is True


def test_flag_and_requirement_from_different_blocks() -> None:
    """Флаг R1 и требование из разных блоков одного вызова."""
    result = map_blocks_to_requirements(
        (
            _block("Эквивалент не допускается"),
            _block("Гарантия не менее 24 мес."),
        )
    )
    assert result.equivalent_allowed is False
    assert len(result.requirements) == 1
    assert result.requirements[0].property == "warranty"
    assert result.blocks_total == 2
    assert result.blocks_mapped == 2
    assert result.unmapped == ()


def test_first_valid_delivery_date_wins() -> None:
    """Первая валидная дата побеждает при нескольких блоках."""
    result = map_blocks_to_requirements(
        (
            _block("Поставка до 01.12.2026"),
            _block("Срок поставки не позднее 15.01.2027"),
        )
    )
    assert result.delivery_deadline == date(2026, 12, 1)
    assert result.blocks_mapped == 2


def test_country_ne_china_mapped() -> None:
    """Запрет китайского производства даёт country_of_origin NE Китай."""
    block = _block("товар китайского производства не допускается")
    result = map_blocks_to_requirements((block,))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.NE
    assert req.value == "Китай"
    assert req.unit is None
    assert req.mandatory is True
    assert req.weight == 1
    assert req.provenance == block.provenance
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


def test_country_ne_unknown_adjective_is_unmapped() -> None:
    """Неизвестное прилагательное не угадываем: блок в unmapped."""
    result = map_blocks_to_requirements(
        (_block("товар марсианского производства не допускается"),)
    )
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH
    assert result.blocks_mapped == 0


def test_country_eq_russia_still_works() -> None:
    """EQ-правило не сломано: «Страна происхождения: Россия» даёт EQ."""
    result = map_blocks_to_requirements(
        (_block("Страна происхождения: Россия"),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.EQ
    assert req.value == "Россия"
    assert result.blocks_mapped == 1


def test_r1_phrase_gives_no_country_requirement() -> None:
    """Фраза R1 не даёт country-требования: якорь «эквивалент» отдельный."""
    result = map_blocks_to_requirements((_block("Эквивалент не допускается"),))
    assert result.equivalent_allowed is False
    assert result.requirements == ()
    assert all(
        req.property != "country_of_origin" for req in result.requirements
    )


def test_country_ne_yo_normalization() -> None:
    """Написание через ё ловится словарём: нёмёцкого → Германия."""
    result = map_blocks_to_requirements(
        (_block("товар нёмёцкого производства не допускается"),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.NE
    assert req.value == "Германия"
    assert result.blocks_mapped == 1


def test_country_ne_case_insensitive() -> None:
    """NE-правило нечувствительно к регистру: РОССИЙСКОГО → Россия."""
    result = map_blocks_to_requirements(
        (_block("Товар РОССИЙСКОГО производства НЕ ДОПУСКАЕТСЯ"),)
    )
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.NE
    assert req.value == "Россия"
    assert result.blocks_mapped == 1


def test_delivery_deadline_tolerates_colon_after_anchor() -> None:
    """Обычная форма ТЗ с двоеточием: «Срок поставки: до 01.12.2026»."""
    result = map_blocks_to_requirements(
        (_block("Срок поставки: до 01.12.2026."),)
    )
    assert result.delivery_deadline == date(2026, 12, 1)
    assert result.blocks_mapped == 1
    assert result.unmapped == ()
