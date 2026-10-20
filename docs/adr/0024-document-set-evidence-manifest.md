# ADR-0024: Явный evidence manifest комплекта документов

- Статус: принято
- Дата: 2026-09-17

## Контекст

Persisted completeness review из ADR-0021 доказывает состояние одного нативно
извлечённого ТЗ. Реальная закупка может состоять из нескольких файлов, но
автоматическое объединение их фактов небезопасно: одинаковые locators относятся к
разным источникам, а сроки и условия могут противоречить друг другу. Выбор
«последнего PASS» также потерял бы точную версию evidence.

До терминального multi-document review нужен отдельный неизменяемый объект,
который фиксирует, какие именно single-document snapshots оператор считает одним
комплектом. Сам факт выбора документов не доказывает полноту комплекта.

## Решение

Вводится `document-set-evidence-manifest-v1`. Оператор явно передаёт упорядоченный
список из 2–10 пар `review_id + evidence_sha256` и описание scope. Tenant,
actor, manifest ID и время назначает сервер. Каждый member проецируется только из
уже сохранённого native `TENDER_REQUIREMENTS` review snapshot и содержит source
document/SHA-256, mapper version/confidence и exact review binding. Extraction не
дублируется: exact review evidence digest уже связывает полный snapshot, включая
extraction и provenance.

Manifest всегда имеет:

- `completeness_status=UNKNOWN`;
- `reason=MULTI_DOCUMENT_REVIEW_REQUIRED`;
- digest, включающий порядок, scope и все member fields.

Repository повторно проверяет tenant-visible review, исходные document bytes,
extraction и source identity. Один source document нельзя включить дважды даже
через разные review IDs. Aggregate logical JSON evidence ограничен 20 МиБ до
загрузки snapshots.

Миграция `20260917_02` хранит header и ordered members в двух append-only
tenant-scoped таблицах с RLS/FORCE RLS. Exact review/evidence FK и deferred
constraint trigger сверяют число и порядок rows, JSON manifest, source binding,
mapper fields и exact review evidence. Manifest, members, audit event и
actor-bound idempotency receipt фиксируются одной транзакцией.

HTTP-граница:

- `POST /v1/document-set-evidence-manifests` доступен только `OPERATOR`, требует
  `Idempotency-Key` и принимает ограниченный 16 КиБ strict JSON без duplicate keys;
- `GET /v1/document-set-evidence-manifests/{manifest_id}` возвращает только
  tenant-visible immutable manifest;
- ответы имеют `Cache-Control: no-store`.

List/latest, terminal decision, case ingestion, UI, AI inference и внешняя
передача в этот срез не входят.

## Последствия

Положительное следствие: состав комплекта воспроизводим и проверяем; порядок и
каждая версия evidence явны, а cross-tenant или stale ссылки отклоняются.

Ограничение: manifest не объединяет requirements и не разрешает противоречия.
Даже если каждый входной review имеет решение `PASS`, статус комплекта остаётся
`UNKNOWN`. Следующий отдельный контракт должен выбрать exact constituent
decisions, проверить междокументные пробелы/конфликты и только затем создать
терминальный multi-document review.

## Отклонённые варианты

- Автоматически брать последние reviews: невоспроизводимо и создаёт скрытое
  изменение решения при появлении новой версии.
- Считать набор полным по constituent `PASS`: не обнаруживает противоречия и
  требования, распределённые между файлами.
- Принимать source/extraction/member fields от клиента: переносит trust boundary
  на недоверенный payload.
- Сразу соединять mappings в один `FactMappingResult`: текущая схема имеет
  одиночные поля для ряда условий и может молча потерять конфликт.
