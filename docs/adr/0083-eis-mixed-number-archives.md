# ADR0083 — метаданные дополнительных документов адресного набора

Дата2026-10-05; owner root. Решение принято и реализовано на VPS.

S201 показал полный by-number набор: поддержанное извещение вместе с six companion
families. Отказ из-за неописанного member лишает поиск достоверного извещения.
Решение — явно описать metadata contract этих семей, сохранив every-member admission,
исходные bytes и provenance. Подмножество ZIP не создаётся, unknown не пропускается.

Whole-set metadata intake возможен только по точному номеру. Notice snapshot
использует прежний parser; companions сохраняются с отдельной parser identity и
SHA-based document id в существующем immutable tenant event store. Модель и CHECK
миграция фиксируют список типов; региональные запросы остаются прежними.

Companions не утверждают юридический результат/цену или текущий этап. Resolver
сохраняет их evidence, но chronology cancellation использует cancellation only.
Expired latest deadline блокирует чтение документов; missing/ambiguous facts UNKNOWN.
Source-aware participants/prices/stage interpretation — отдельный следующий slice.

Official contract: [ЕИС16.3/44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
ZIP SHA4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7.
Effective parser date2026-10-05, without applying new legal rules.
Первый apply — source0 replay трёх retainedS201 sets после XSD/PG gates.
Результат может появиться в поиске с FAIL/UNKNOWN; participation/fullEIS не утверждаются.

Acceptance: 95 Linux/isolatedPG tests, все 16 исходных XML прошли официальную XSD.
Source0 preview/apply восстановил 3 извещения и сохранил 13 companion metadata;
все три expired, queue BLOCKED, новых скачиваний документов0. HEAD20261005_01,
host59/API13/worker13 hashes PASS, API health200. Реальные evidence/hashes и
границы проверки поиска зафиксированы в [docs85](../eis/ingestion/85-eis-mixed-number-archives.md).
