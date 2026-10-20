# ADR-0033: exact server BOM и коммерческое предложение как pending proposal

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

S84 находит публичные карточки серверных семейств, а S85 связывает независимо
проверенный набор требований с версией кейса. Ни публичная карточка, ни список
каталожных опций не доказывают поставляемую конфигурацию, цену, наличие и условия
КП. Встроенное в старый JSON кейса ручное `selected_quote` не связывает цену с
конкретным sourcing lead, BOM и immutable документом поставщика.

## Решение

Хранить `server-offer-proposal-v1` как отдельный append-only tenant-scoped
ресурс. Operator выбирает exact `case_id + version`, requirement-set binding,
sourcing run/lead и документ роли `SUPPLIER_QUOTE` с SHA-256. Сервер повторно
проверяет все связи и сам переносит название, URL и source digest карточки из
persisted sourcing run.

Proposal содержит полный упорядоченный BOM из 1–500 строк, explicit part kind,
manufacturer/SKU/description, Decimal-количество, необязательные Decimal-цены и
locator каждой строки в exact КП-документе. Коммерческие условия включают
поставщика, номер КП, RUB-сумму без НДС, ставку НДС, timezone-aware период
действия, coverage, наличие, поставку и оплату с отдельным locator. Если цены
указаны для всех строк, их сумма обязана совпасть с общей суммой КП.

Идентификатор, actor, время и canonical digest назначает сервер. Ресурс всегда
имеет `technical_status=UNKNOWN` и `review_status=PENDING_REVIEW`; caller не может
передать эти поля. Создание доступно только `OPERATOR`. Таблица защищена
RLS/FORCE RLS и immutable trigger, а запись proposal, audit event и idempotency
receipt выполняется в одной транзакции.

## Последствия

Operator transcription является воспроизводимым предложением для проверки, но
не независимым подтверждением содержимого документа. `covers_full_scope=true`,
действующий срок и совпадающая арифметика не создают технический `PASS` и не
подменяют review 87 строк. Следующий срез должен построить независимую матрицу
сопоставления requirements↔BOM/КП и сохранить terminal decision по exact proposal
digest.
