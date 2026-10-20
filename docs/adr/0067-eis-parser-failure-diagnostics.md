# ADR-0067 — source-bound parser failure diagnostics

Статус: **DEPLOYED AND VERIFIED / LIVE, API AND OPERATIONS PASS**.
Дата: 2026-10-04, S184. Owner ADR/review: Astra; diagnostic module/tests: Sol;
capture, operational proofs и rollout: root.

## Контекст

После obsolete-limit recovery остаются latest FAILED группы
`ATTACHMENT_REFERENCE_INVALID` и `MEMBER_UNSUPPORTED`. Исторический reason без
сохранённых bytes не доказывает конкретную причину и не разрешает ослабить parser.
До трёх bounded samples предназначены для диагностики, не для оценки всей группы.

## Решение

Pure typed diagnostic module классифицирует точные predicates действующего
parser по полному bound source set. Каждый результат связан с window/response,
archive SHA, member ordinal/name hash и XML SHA. Raw member names, URLs и source
text не должны отражаться в безопасном summary. Неизвестные или неполные данные
остаются UNKNOWN; diagnostic completeness не означает canonical admission.

Capture использует существующий transport и `bind_ready_window`, tenant scope,
priority/import leases, CPU2/memory2GiB, DB100GiB/free40GiB и прежние source caps.
Архивы остаются на VPS: compressed64MiB/window и expanded128MiB/window.
Лимит600s проверяется перед следующим окном и не является строгим wall-clock SLA.
Все archive headers и совокупные resource bounds проверяются до XML parsing;
сам XML parsing также обязан иметь ограничение размера/структуры.

Diagnostic capture intercepts ingest отдельным `Captured(Exception)`, не
принадлежащим классам conflict exceptions; rejection hook дополнительно запрещён.
Нет canonical insert, partial intake, checkpoint, journal или domain audit writes.
Старые failures остаются неизменны. Заявленное поле writes0 само по себе не
заменяет независимую проверку mutations и source/write-route evidence.

## Неизменные границы

UID/official HTTPS URL, ZIP member safety, member limits, namespaces и atomic fullset
guards не ослабляются. Найденная форма сначала требует source-contract evidence,
отдельно записанного implementation scope и synthetic regression. Diagnosis не
выбирает subset/winner и не переводит supplier eligibility или coverage в PASS.
Сохранение attachment metadata не означает скачивание документов.

## Acceptance

Проверить resource preflight, безопасный XML, token reflection, строгий source
binding, полный occurrence inventory и typed UNKNOWN для неполной диагностики.
Сверить classification с действующими predicates, не подменяя их новым admission
контрактом. Synthetic tests и bounded retained-source proof предшествуют любому
parser fix. Выполненные release gates приведены ниже.

## Подтверждённый bounded metadata substage

Три complete bound captures:33.044 s,6 POST/5 GET; capture SHA-256
`07d56f7bb32ea35a68a43e9f1d468bc527b73364763373d6080c45a3dafc7fa9`.
Shape proof SHA-256
`576184002e1524df62343fd0cb6a03a40b1230ef594f762afbc0cd3e21f5b65c`:
42/2026-09-07/EZK — восемь notices с единственным filename predicate `/`;
30/2026-09-09/EF — duplicate UID;23/2026-09-30/EF — XML34,586,604 bytes,
выше действующего32MiB cap. Эти samples не классифицируют всю очередь.

Разрешён только forward slash в исходном attachment display label. Label
сохраняется точно, без basename/normalization; backslash, NUL, length1024,
UID/URL и duplicate guards неизменны. ZIP member names не получают исключения.
Duplicate UID и oversized XML остаются rejected, cap не повышается.

Document processing отдельно проверяет Posix/Windows basename: worker до
download возвращает `ATTACHMENT_FILENAME_REQUIRES_REVIEW`, attempted0;
probe не пишет в DB. Analysis/reanalysis возвращает typed UNKNOWN с исходным
label до создания DocumentInput. Это не разрешение extraction, не скачивание
вложений и не supplier PASS. Existing shared variant hold сохраняется, включая
late hold при записи результата.

## Independent code review

Resource blocker устранён: streaming XML preflight проверяет node/depth limits
до canonical parser и второго tree parse; DTD и decoded token reflection
отсекаются. Uninspected member имеет UNKNOWN, не ложное parser success.
Reviewed metadata predicate, document analysis boundary и worker pre-download
gate соответствуют этому контракту; оставшихся code blockers не выявлено.
Предварительные focused checks завершены; итоговые gates и controlled live
window42/2026-09-07/EZK подтверждены ниже.

## Release и production evidence

Root подтвердил141 Linux PASS (9.24 s),40 PostgreSQL PASS (17.35 s),
Ruff9/mypy4 PASS. PG проверил no-fetch/probe review и cached reanalysis UNKNOWN;
fixture использует существующий разрешённый analyzer v2, SQL contract не менялся.

Deployment14:38:05 UTC: code backup
`/state/backups/s184-before-20261004T143805Z-code.tar.gz`, SHA-256
`cd5c2b9e8353b7ef3ba31817ad1757621e14a61ee4f825b81b80855b98136339`;
host15/runtime4 hashes PASS, API/worker rebuilt, HEAD `20261004_03` без migration.

Live14:39:28 UTC:42/2026-09-07/EZK SYNCED за8.372 s,1 ZIP,
37 new versions,0 events. Все8 slash labels сохранены точно. Фактические
canonical SHA/journal/audit проверены,50 старых attempt rows неизменны.
Live proof `live-proof.json`, SHA-256
`ebd01123b4425ab98723f617d689734bbd36f9b6f87037deae44e31a5ce685ea`.

Deployed diagnostics:2.931 s, source0/writes0, SHA-256
`969bf5c12d2c8499c9a21ef21feb263694555c656e2fbcbd0954e7a14843389f`:

- Region42:37 XML /166 attachments, findings0 после metadata fix.
- Region30:16 XML /96 attachments,1 duplicate UID finding.
- Region23:269 headers,266 inspected XML;2 node-limit UNKNOWN и1 oversized XML.
  Inspection неполная; это не подтверждение остальных XML как admitted.

Отдельный no-intake SQL proof до live подтвердил нулевые mutations:
SHA-256 `32c5b291c17a4220e55868fd96a4e98f7bf6280c6da8b40ea428eeb9e2d4fe57`.
Final census:148183 planned,5105 completed,143078 pending,136524 unattempted,
6491 NO_DATA; remaining44 invalid-reference /5 unsupported-member gaps.
Coverage/freshness UNKNOWN.

API health200/anonymous401/no-store PASS:44 current134030,
paper8.493 s/server15.589 s;223 current2898,paper227 ms/server643 ms.
Одиночные измерения не являются SLA. API proof SHA-256
`ba860732947fdb6b3b7fb8a0cd99802c02047f80853d0ce49af03519c0ff24e3`.
Final operations14:44:00 UTC PASS: DB3,711,048,727 bytes,
free265,053,171,712 bytes; test DB отсутствуют, оба markers отсутствуют.
Обычный223 cron удалил свой marker естественно; root чужой marker не удалял.
Proof: `/var/lib/eis-browser/research/rejected/s184-operations-proof.json`,
SHA-256 `c4512afcbfad054062f7b3468606455fa1856a867ba0a7e0b090bc4243065b72`.
Live, API и operations gates завершены; ожидающих проверок этого slice нет.

Следующий bounded шаг — оставшиеся region42 windows с exact eligibility и
receipts. Duplicate UID требует отдельного анализа исходной структуры;
крупный XML — отдельного streaming/resource решения. Blanket parser relaxation
и повтор всей группы этим решением не разрешены.
