# ADR0097 — точная таблица DOCX перед review требований

Дата:2026-10-06. Статус: принято для bounded S227.

## Контекст

S226 показывает публичные XML поля и товар, но legacy значения неполны.
S221 ссылки тестовой бумаги относятся к обоснованию цены. Описание объекта
уже получено; инструкции заказчика нужны для проверки требований.

## Решение

Выбранная retained native table рядом с exact saved S226 report. Все text cells,
section rows, инструкции и provenance сохранены. Один readonly tenant snapshot
после current/hold/digest guards; deterministic self-digest. Новая таблица БД и
дублирование source bytes не нужны. Existing explicit prepareReview отдельно.

Выход — draft hints с mandatory/approved/technical UNKNOWN. Не создаются
фиктивный TENDER_REQUIREMENTS DocumentRecord, independent decision или
исполняемый Requirement. Старый complete-table materialization другой системы
регистрации документов напрямую не используется. Downstream reviewed/compliance
правила применяются после отдельного точного review.

## Последствия

Инструкции заказчика видны. Границы >=80 и <90 различаются, C/С/Сэ не
упорядочиваются. Missing cell text — NO_RETAINED_TEXT, не доказанная пустая
клетка. Grid/merge topology и полнота DOCX остаются UNKNOWN. Нет новых
intermediate persisted сущностей или source downloads.
