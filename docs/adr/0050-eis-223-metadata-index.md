# ADR-0050 — отдельный immutable metadata индекс 223-ФЗ

Статус: принято. Дата: 2026-10-02. Владелец: основной агент.

## Контекст

S149 проверил один RI223/purchaseNoticeAESMBO архив по официальным XSD16.2/16.3.
Номер223 состоит из11цифр; один XML может содержать несколько лотов с разными
валютами. Общий индекс44 и его document jobs предполагают другой source contract.
Источник15реальных XML не указывает пояс submissionCloseDateTime.

## Решение

Четыре отдельные таблицы: windows, tenant content-addressed blobs, archive sources,
notice versions. У всех FORCE RLS, tenant composite FK, immutable triggers.
Raw ZIP хранится один раз на tenant/SHA; SQL проверяет SHA256(content).
Identity JSON223 проверяется на соответствие номеру/версии/SHA колонок.
Prepared SOAP и XML provenance не превращаются в доказательство полного ЕИС.

Intake принимает только полное prepared множество из1–2архивов, связанное
с исходным UID. Preflight до transaction; advisory lock на tenant; конфликт
номер/версия/XMLSHA откатывает весь window, raw bytes, проекции и audit.
Один успешно сохранённый window даёт один EIS_223_WINDOW_INGESTED.
Повтор одинакового initial response и manifest не мутирует запись и сохраняет
первый preparedSHA; повторное получение prepared SOAP может менять его bytes.
Новый initial response сохраняет новый window/audit при dedup одинаковых ZIP/XML.
Scope selection sidecar — provenance оператора, не source-signed доказательство.

Read-only endpoint /v1/tender-discovery/eis-223-index: tenant из principal,
Cache-Control:no-store, consistent snapshot, latest version в известном корпусе.
GIN/search_keys_v1 лишь coarse prefilter; финальный morphology matcher сверяет
слова в одном title, одном subject лота или одной description позиции.
Слова разных items/lots не объединяются. До100результатов; matched_count полный
в известном корпусе. Классификация ОКПД не подменяет description позиции.

Деньги остаются Decimal/string по каждому лоту с currency/provenance. Итоговой
«НМЦК223» путём сложения нет. Naive deadline UNKNOWN; aware expired deadline FAIL;
даже будущий aware срок не означает PASS. Eligibility, комплект, прибыль,
freshness и глобальная coverage UNKNOWN. Отдельная UI секция явно называет223.
Reader/search не запускают source requests,44document jobs или отправку заявки.
Downgrade с source history запрещён, guard использует row_security=off fail closed.

## Последствия

223 можно искать и объяснять на основе уже проверенных metadata. Расширение
семейств, scheduler, документы223, статусы/протоколы и timezone interpretation
требуют следующих bounded slices. Миграция не меняет44проекцию/cron scope.

## Альтернативы

Общий44индекс отвергнут: несовместимые идентификаторы, multi-lot деньги и
source locators. Только in-memory search отвергнут: нет durable replay/RLS/audit.
