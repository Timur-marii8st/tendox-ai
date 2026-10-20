"""Тесты маппера блоков в требования ТЗ."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import (
    DEFAULT_FACT_MIN_CONFIDENCE,
    CompletenessAssessment,
    CompletenessStatus,
    DocumentRole,
    FactMappingResult,
    UnmappedBlockReview,
    UnmappedDisposition,
    UnmappedReason,
)
from procurement.documents.facts import (
    map_blocks_to_requirements as _map_blocks_to_requirements,
)
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator


def map_blocks_to_requirements(
    blocks: tuple[ExtractedBlock, ...],
    *,
    min_confidence: float = DEFAULT_FACT_MIN_CONFIDENCE,
) -> FactMappingResult:
    """Явно пометить unit-входы как блоки ТЗ."""
    return _map_blocks_to_requirements(
        blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        min_confidence=min_confidence,
    )


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


def _table_block(text: str, locator: str, confidence: float = 1.0) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        provenance=Provenance(
            document_id="test-doc",
            locator=locator,
            extractor=Extractor.NATIVE_DOCX,
            confidence=confidence,
        ),
    )


def test_adjacent_table_cells_become_unverified_candidate() -> None:
    row = "table 1 row 3 cell 3 nested table 1 row 32"
    blocks = (
        _table_block("Объем каждого установленного накопителя", f"{row} cell 1"),
        _table_block("Больше или равно 960 Гбайт", f"{row} cell 2"),
        _table_block("Участник указывает значение", f"{row} cell 3"),
    )
    result = map_blocks_to_requirements(blocks)
    assert result.requirements == ()
    assert result.blocks_mapped == 0
    assert len(result.unmapped) == 3
    assert result.completeness.status is CompletenessStatus.UNKNOWN
    (candidate,) = result.table_row_candidates
    assert candidate.property_text == blocks[0].text
    assert candidate.value_text == blocks[1].text
    assert candidate.operator is Operator.GE
    assert candidate.value == Decimal(960)
    assert candidate.unit == "Гбайт"
    assert tuple(source.provenance for source in candidate.source_blocks) == tuple(
        block.provenance for block in blocks[:2]
    )


def test_table_unit_in_third_cell_and_no_cross_row_join() -> None:
    row = "table 1 row 2"
    blocks = (
        _table_block("Скорость накопителя HDD при чтении", f"{row} cell 3"),
        _table_block("≥ 186", f"{row} cell 4"),
        _table_block("Мегабайт в секунду", f"{row} cell 5"),
        _table_block("≥ 3900", "table 1 row 3 cell 4"),
    )
    result = map_blocks_to_requirements(blocks)
    (candidate,) = result.table_row_candidates
    assert candidate.value == Decimal(186)
    assert candidate.unit == "Мегабайт в секунду"
    assert len(candidate.source_blocks) == 3
    assert result.blocks_mapped == 0


def test_table_candidates_require_trusted_role_and_source_cells() -> None:
    row = "table 1 row 1"
    blocks = (
        _table_block("Количество ядер", f"{row} cell 1"),
        _table_block("Больше или равно 16 шт", f"{row} cell 2", confidence=0.7),
    )
    assert map_blocks_to_requirements(blocks).table_row_candidates == ()
    trusted = (blocks[0], _table_block("Больше или равно 16 шт", f"{row} cell 2"))
    quote = _map_blocks_to_requirements(trusted, document_role=DocumentRole.SUPPLIER_QUOTE)
    assert quote.table_row_candidates == ()
    assert quote.requirements == ()


def test_ambiguous_table_value_is_not_candidate() -> None:
    row = "table 1 row 1"
    result = map_blocks_to_requirements(
        (
            _table_block("Количество ядер", f"{row} cell 1"),
            _table_block("Не менее 16 или 24", f"{row} cell 2"),
        )
    )
    assert result.table_row_candidates == ()
    assert result.requirements == ()


def test_table_candidate_rejects_unrelated_source_cell() -> None:
    row = "table 1 row 1"
    result = map_blocks_to_requirements(
        (
            _table_block("Количество ядер", f"{row} cell 1"),
            _table_block("Больше или равно 16 шт", f"{row} cell 2"),
            _table_block("Примечание", "table 1 row 2 cell 3"),
        )
    )
    candidate = result.table_row_candidates[0]
    with pytest.raises(ValidationError, match="одной строке"):
        type(candidate).model_validate(
            candidate.model_dump()
            | {"source_blocks": (*candidate.source_blocks, result.unmapped[2])}
        )


def test_explicit_warranty_duration_mapped() -> None:
    block = _block("На поставляемый Товар должна быть предоставлена гарантия сроком 36 месяцев")
    result = map_blocks_to_requirements((block,))
    (requirement,) = result.requirements
    assert requirement.property == "warranty"
    assert requirement.operator is Operator.GE
    assert requirement.value == Decimal(36)
    assert requirement.provenance == block.provenance
    assert result.completeness.status is CompletenessStatus.UNKNOWN


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
    result = map_blocks_to_requirements((_block("Количество портов не менее 24 шт."),))
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
        (_block("Гарантия не менее 12 мес. Количество портов не менее 24 шт."),)
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
        FactMappingResult(
            document_role=DocumentRole.TENDER_REQUIREMENTS,
            blocks_total=1,
            blocks_mapped=2,
        )


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
    result = map_blocks_to_requirements((_block("Срок поставки не позднее 01.12.2026"),))
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
    result = map_blocks_to_requirements((_block("Пропускная способность не менее 10 Гбит/с"),))
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
    result = map_blocks_to_requirements((_block("Страна происхождения: Россия"),))
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
    result = map_blocks_to_requirements((_block("товар марсианского производства не допускается"),))
    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH
    assert result.blocks_mapped == 0


def test_country_eq_russia_still_works() -> None:
    """EQ-правило не сломано: «Страна происхождения: Россия» даёт EQ."""
    result = map_blocks_to_requirements((_block("Страна происхождения: Россия"),))
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
    assert all(req.property != "country_of_origin" for req in result.requirements)


def test_country_ne_yo_normalization() -> None:
    """Написание через ё ловится словарём: нёмёцкого → Германия."""
    result = map_blocks_to_requirements((_block("товар нёмёцкого производства не допускается"),))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.NE
    assert req.value == "Германия"
    assert result.blocks_mapped == 1


def test_country_ne_case_insensitive() -> None:
    """NE-правило нечувствительно к регистру: РОССИЙСКОГО → Россия."""
    result = map_blocks_to_requirements((_block("Товар РОССИЙСКОГО производства НЕ ДОПУСКАЕТСЯ"),))
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.property == "country_of_origin"
    assert req.operator is Operator.NE
    assert req.value == "Россия"
    assert result.blocks_mapped == 1


def test_delivery_deadline_tolerates_colon_after_anchor() -> None:
    """Обычная форма ТЗ с двоеточием: «Срок поставки: до 01.12.2026»."""
    result = map_blocks_to_requirements((_block("Срок поставки: до 01.12.2026."),))
    assert result.delivery_deadline == date(2026, 12, 1)
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (
            "Требуется действующая декларация соответствия ТР ТС.",
            "Декларация соответствия ТР ТС",
        ),
        (
            "Необходимо наличие сертификата соответствия ЕАЭС.",
            "Сертификат соответствия ЕАЭС",
        ),
    ],
)
def test_certificate_requirement_mapped(text: str, kind: str) -> None:
    """Явное требование разрешительного документа становится EXISTS с provenance."""
    block = _block(text)

    result = map_blocks_to_requirements((block,))

    assert len(result.requirements) == 1
    requirement = result.requirements[0]
    assert requirement.property == f"certificate:{kind}"
    assert requirement.operator is Operator.EXISTS
    assert requirement.value is None
    assert requirement.mandatory is True
    assert requirement.raw_text == text
    assert requirement.provenance == block.provenance
    assert result.blocks_mapped == 1
    assert result.unmapped == ()


def test_certificate_mention_without_requirement_stays_unmapped() -> None:
    """Упоминание сертификата в описании не выдаётся за требование ТЗ."""
    result = map_blocks_to_requirements(
        (_block("В комплект вложена декларация соответствия ТР ТС."),)
    )

    assert result.requirements == ()
    assert len(result.unmapped) == 1
    assert result.unmapped[0].reason is UnmappedReason.NO_PATTERN_MATCH


def test_document_role_is_required() -> None:
    """Без назначения документа requirement mapping не начинается."""
    with pytest.raises(TypeError):
        _map_blocks_to_requirements((_block("Гарантия не менее 36 мес."),))


def test_supplier_quote_cannot_create_tender_requirements() -> None:
    """Похожие на ТЗ фразы из КП остаются фактами другого класса, без hard gates."""
    blocks = (
        _block("Гарантия не менее 36 мес."),
        _block("Количество портов не менее 48 шт."),
        _block("Требуется действующая декларация соответствия ТР ТС."),
        _block("Эквивалент не допускается. Срок поставки: до 01.12.2026."),
    )

    result = _map_blocks_to_requirements(
        blocks,
        document_role=DocumentRole.SUPPLIER_QUOTE,
    )

    assert result.document_role is DocumentRole.SUPPLIER_QUOTE
    assert result.requirements == ()
    assert result.blocks_total == 4
    assert result.blocks_mapped == 0
    assert result.equivalent_allowed is None
    assert result.delivery_deadline is None
    assert len(result.unmapped) == 4
    assert all(block.reason is UnmappedReason.NON_REQUIREMENT_DOCUMENT for block in result.unmapped)


def test_application_attachment_cannot_create_tender_requirements() -> None:
    result = _map_blocks_to_requirements(
        (_block("Требуется действующая декларация соответствия ТР ТС."),),
        document_role=DocumentRole.APPLICATION_ATTACHMENT,
    )
    assert result.document_role is DocumentRole.APPLICATION_ATTACHMENT
    assert result.requirements == ()
    assert result.blocks_mapped == 0
    assert result.unmapped[0].reason is UnmappedReason.NON_REQUIREMENT_DOCUMENT


def test_unknown_document_role_cannot_create_tender_requirements() -> None:
    """Не классифицированный документ остаётся UNKNOWN и не создаёт hard gates."""
    result = _map_blocks_to_requirements(
        (_block("Требуется действующая декларация соответствия ТР ТС."),),
        document_role=DocumentRole.UNKNOWN,
    )

    assert result.document_role is DocumentRole.UNKNOWN
    assert result.requirements == ()
    assert result.blocks_mapped == 0
    assert result.unmapped[0].reason is UnmappedReason.UNKNOWN_DOCUMENT_ROLE


def test_quote_mapping_result_rejects_tender_facts() -> None:
    """Типизированный output не может одновременно быть КП и содержать требования ТЗ."""
    tender = map_blocks_to_requirements((_block("Гарантия не менее 36 мес."),))

    with pytest.raises(ValidationError, match="документ без роли ТЗ"):
        FactMappingResult(
            document_role=DocumentRole.SUPPLIER_QUOTE,
            requirements=tender.requirements,
            blocks_total=1,
            blocks_mapped=1,
        )


def _completeness_payload(
    result: FactMappingResult,
    *,
    status: CompletenessStatus,
    reviews: tuple[UnmappedBlockReview, ...] = (),
) -> dict[str, object]:
    """Подготовить повторную валидацию результата с review полноты."""
    payload = result.model_dump()
    document_ids = {requirement.provenance.document_id for requirement in result.requirements} | {
        block.provenance.document_id for block in result.unmapped
    }
    payload["completeness"] = CompletenessAssessment(
        status=status,
        scope="Все извлечённые блоки документа и существенные требования",
        source_document_ids=tuple(sorted(document_ids)),
        reviewer_id="reviewer-1",
        reviewed_at=datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
        review_reference="review:test-doc:v1",
        unmapped_reviews=reviews,
    )
    return payload


def test_empty_tender_mapping_completeness_stays_unknown() -> None:
    """Отсутствие извлечённых блоков не доказывает полноту ТЗ."""
    result = map_blocks_to_requirements(())

    assert result.completeness.status is CompletenessStatus.UNKNOWN
    with pytest.raises(ValidationError, match="формализованного требования"):
        FactMappingResult.model_validate(
            {
                **result.model_dump(),
                "completeness": {
                    "status": "PASS",
                    "scope": "Весь документ",
                    "source_document_ids": ("test-doc",),
                    "reviewer_id": "reviewer-1",
                    "reviewed_at": "2026-09-16T12:00:00+00:00",
                    "review_reference": "review:test-doc:v1",
                },
            }
        )


def test_flag_only_tender_mapping_cannot_have_completeness_pass() -> None:
    """Дата или флаг ТЗ без формализованных требований не открывают положительный gate."""
    result = map_blocks_to_requirements((_block("Срок поставки: до 30.09.2026"),))

    assert result.blocks_mapped == 1
    assert result.requirements == ()
    assert result.delivery_deadline == date(2026, 9, 30)
    with pytest.raises(ValidationError, match="формализованного требования"):
        FactMappingResult.model_validate(
            {
                **result.model_dump(),
                "completeness": {
                    "status": "PASS",
                    "scope": "Все извлечённые блоки документа",
                    "source_document_ids": ("test-doc",),
                    "reviewer_id": "reviewer-1",
                    "reviewed_at": "2026-09-16T12:00:00+00:00",
                    "review_reference": "review:test-doc:v1",
                },
            }
        )


def test_unresolved_mapping_completeness_is_unknown_by_default() -> None:
    """Даже частичный успех маппера не превращает непокрытый блок в PASS."""
    result = map_blocks_to_requirements(
        (
            _block("Гарантия не менее 24 мес."),
            _block("Монтаж выполняется по особым условиям заказчика."),
        )
    )

    assert result.blocks_mapped == 1
    assert len(result.unmapped) == 1
    assert result.completeness.status is CompletenessStatus.UNKNOWN


def test_completeness_pass_requires_review_of_each_unmapped_block() -> None:
    """Непроверенный unmapped-блок не допускает полноту PASS."""
    result = map_blocks_to_requirements(
        (_block("Гарантия не менее 24 мес."), _block("Информационный заголовок"))
    )

    with pytest.raises(ValidationError, match="по каждому unmapped"):
        FactMappingResult.model_validate(
            _completeness_payload(result, status=CompletenessStatus.PASS)
        )


def test_reviewed_non_requirement_allows_completeness_pass() -> None:
    """Reviewer может подтвердить, что unmapped-блок не является требованием."""
    result = map_blocks_to_requirements(
        (_block("Гарантия не менее 24 мес."), _block("Раздел 1. Общие сведения"))
    )
    review = UnmappedBlockReview(
        block=result.unmapped[0],
        disposition=UnmappedDisposition.NON_REQUIREMENT,
        rationale="Заголовок раздела не задаёт проверяемого условия",
    )

    reviewed = FactMappingResult.model_validate(
        _completeness_payload(
            result,
            status=CompletenessStatus.PASS,
            reviews=(review,),
        )
    )

    assert reviewed.completeness.status is CompletenessStatus.PASS
    assert reviewed.completeness.reviewer_id == "reviewer-1"
    assert reviewed.completeness.unmapped_reviews == (review,)


def test_material_unmapped_requirement_rejects_completeness_pass() -> None:
    """Выявленное, но не разобранное требование несовместимо с PASS."""
    result = map_blocks_to_requirements(
        (_block("Гарантия не менее 24 мес."), _block("Монтаж обязателен силами поставщика"))
    )
    review = UnmappedBlockReview(
        block=result.unmapped[0],
        disposition=UnmappedDisposition.MATERIAL_REQUIREMENT,
        rationale="Существенное условие исполнения ещё не структурировано",
    )

    with pytest.raises(ValidationError, match="PASS несовместим"):
        _completeness_payload(
            result,
            status=CompletenessStatus.PASS,
            reviews=(review,),
        )


def test_material_unmapped_requirement_can_mark_completeness_fail() -> None:
    """FAIL ссылается на точный существенный unmapped-блок."""
    result = map_blocks_to_requirements((_block("Монтаж обязателен силами поставщика"),))
    review = UnmappedBlockReview(
        block=result.unmapped[0],
        disposition=UnmappedDisposition.MATERIAL_REQUIREMENT,
        rationale="Условие обязательно и потеряно текущим маппером",
    )

    failed = FactMappingResult.model_validate(
        _completeness_payload(
            result,
            status=CompletenessStatus.FAIL,
            reviews=(review,),
        )
    )

    assert failed.completeness.status is CompletenessStatus.FAIL


def test_non_tender_document_cannot_have_completeness_pass() -> None:
    """КП не может получить подтверждение полноты требований ТЗ."""
    result = _map_blocks_to_requirements(
        (_block("Гарантия не менее 24 мес."),),
        document_role=DocumentRole.SUPPLIER_QUOTE,
    )
    review = UnmappedBlockReview(
        block=result.unmapped[0],
        disposition=UnmappedDisposition.EXCLUDED_FROM_SCOPE,
        rationale="Документ является КП, а не ТЗ",
    )

    with pytest.raises(ValidationError, match="без роли ТЗ"):
        FactMappingResult.model_validate(
            _completeness_payload(
                result,
                status=CompletenessStatus.PASS,
                reviews=(review,),
            )
        )


def test_completeness_review_requires_timezone_and_exact_source_binding() -> None:
    """Review нельзя отвязать от времени и provenance проверенного результата."""
    with pytest.raises(ValidationError, match="timezone"):
        CompletenessAssessment(
            status=CompletenessStatus.PASS,
            scope="Весь документ",
            source_document_ids=("test-doc",),
            reviewer_id="reviewer-1",
            reviewed_at=datetime(2026, 9, 16, 12, 0),
            review_reference="review:test-doc:v1",
        )

    result = map_blocks_to_requirements((_block("Гарантия не менее 24 мес."),))
    payload = _completeness_payload(result, status=CompletenessStatus.PASS)
    assessment = payload["completeness"]
    assert isinstance(assessment, CompletenessAssessment)
    payload["completeness"] = assessment.model_copy(update={"source_document_ids": ("other-doc",)})
    with pytest.raises(ValidationError, match="не совпадают с provenance"):
        FactMappingResult.model_validate(payload)
