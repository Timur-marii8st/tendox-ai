# ADR-0064 — automatic partial intake rejected notice44 window

Статус: **ACCEPTED / M2 DEPLOYED AND VERIFIED**.
Дата: 2026-10-04, S180 M2. Owner ADR: Astra; runtime ownership и gates —
по S180 M2 в docs15. Зависимость: deployed operator M1 из
[ADR-0063](0063-eis-44-retained-variant-projection.md).

## Решение

Для четырёх eligible rejection reasons — `DUPLICATE_NOTICE_VERSION`,
`DUPLICATE_NOTICE_VERSION_IN_WINDOW`, `NOTICE_VERSION_CONFLICT` и
`TRANSPORT_WINDOW_NOT_CANONICAL` — только после полного
RETAINED evidence и успешных retention/diagnosis audits, автоматически выполнить
S178 ledger, затем M1 projection на **том же exact archive set**. Дополнительных
source calls нет. Новые schema, regions, families, budgets или cron отсутствуют.

Оригинальный `EisRejectedWindowError` и source FAILED сохраняются независимо
от результата projection. Partial progress не завершает gap, не создаёт обычный
checkpoint и не меняет cadence/cooldown 24 h. Даже held_count=0 не означает
SYNCED: transport и canonical decisions остаются отдельным evidence contract.

## Typed result и counters

Отдельный intake report имеет status `PARTIAL | FAILED | NOT_ATTEMPTED`,
stage, безопасный reason, tenant/source binding, exact ledger/projection/audit
IDs и counts. Coverage/resolution остаются UNKNOWN.

- NOT_ATTEMPTED: prerequisites отсутствуют или rejection не eligible.
- FAILED: ledger/projection действительно начали, но не завершили; сохраняются
  уже durable IDs и исходная причина source отказа.
- PARTIAL: explicit pipeline завершён, включая replay, при всё ещё FAILED
  source window. Это не supplier PASS или разрешение участия.

Corpus/freshness сохраняют typed observation и отдельные partial counters.
Исторические batch counts не равны новым writes текущего run: replay delta 0
учитывается отдельно, чтобы повторные FAILED attempts не наращивали projected
или inserted totals. Успех summary допустим только после durable transaction.

## Failure и interruption

Stages сохраняют исходный source reason и не публикуют exception text, raw XML,
URL credentials или reflection. Database failure не маскируется как обычный
локальный source conflict: run останавливается с sanitized storage error и
сохранённым source context. Если failed transaction делает DB journal
недоступным, нельзя утверждать, что observation persisted.
В реализации любой stage FAILED останавливает run после доступной записи
исходного source FAILED; это консервативнее продолжения после локальной ошибки.

Interruption после ledger оставляет shared hold активным; projection атомарна.
Повтор использует deterministic receipt/audit/batch identities без дублирования
истории, затем продолжает незавершённый stage. Новый conflicting variant
возвращает hold по shared SQL даже после прежнего projection.

### Exact transport retry

При повторе прежний source conflict может смениться на
TRANSPORT_WINDOW_NOT_CANONICAL, потому что full transport уже сохранён.
Новый reason-specific manifest имеет иное observed_at и не заменяет прежний
transport evidence. Предпочтён read-only lookup exact существующего projection
batch → audited receipt/diagnosis до новой retention: tenant/window/initial
response/prepared SHA/ordered archive SHAs/URLs/full inventory должны совпасть.
Переиспользуются прежние manifest/observed_at/receipt; текущая outer rejection
reason остаётся TRANSPORT_WINDOW_NOT_CANONICAL. Timestamp comparisons writer
не ослабляются. Missing или неоднозначный existing binding означает failure,
не выбор latest. Transport без полного batch/audit — integrity failure.
Ledger-only interruption не создаёт transport и использует обычный retry.

## Acceptance

Проверить exact complete archives/source0 additional; prerequisites отсутствуют;
каждый stage failure и DB-stop policy; ledger-only interruption/retry; atomic
late projection failure; deterministic replay без counters inflation; conflicting
future variant rehold; tenant isolation; sanitized typed reports и persisted
corpus/freshness observations. Обычный source outcome остаётся FAILED, gap
pending и checkpoint false. Все прежние mandatory и consumer gates сохраняются.

Нужны isolated Linux/PG и полный retained end-to-end proof при прежнем memory
budget перед rollout. Existing 8 FAILED не переписываются; новые attempts не
обозначаются SYNCED ради partial progress. Production M2 пока не подтверждён.

## Bounded review

Проверены helper/feed, exact transport reuse, corpus/freshness/status и journal.
Reuse требует ровно один current-parser batch и exact audited receipt/diagnosis;
проверяются source coordinates, prepared SHA, ordered ZIP SHA/URLs, counts и
first-observed time. Writer повторяет полный inventory/replay check. Fallback
к новой reason-specific retention отсутствует.

Corpus report сохраняется в tenant/window/response audit basis; freshness
PARTIAL требует retained evidence и оба successful audits. Stage FAILED
останавливает run после записи исходного FAILED, replay new_versions равен0.
held_pairs означает сумму historical batch held counts обработанных partial
windows данного run, а не текущий global unresolved count.

Release code review PASS; root подтвердил 286 Linux + 72 isolated PG PASS
(358 tests), Ruff 8 runtime / 7 tests и mypy 8 modules. Ошибка
самой journal transaction может прервать run без persisted observation;
успешная persistence в таком случае не заявляется.

## Final isolated automatic gate

Exact full rejection hook proof 12:35:56 UTC: 5 ZIP / 499 XML / 498 pairs →
497 PROJECTED / 1 HOLD. Replay deltas всех 13 таблиц 0, source calls 0,
retained file writes 0, checkpoint false; ожидаемые четыре audit records.
Peak 552,386,560 bytes / 2 GiB с resident Chromium. Два полных runs с ledger
и replay заняли 101.737 s; это не search latency или online SLA.

Proof `/var/lib/eis-browser/research/rejected/s180-m2-isolated-proof.json`,
SHA-256 `89bc2bc5caff1f57af61d9396697ff57ca4b690822c2979dbd42407e1f8762f8`.
Staged release **PASS**; production и live evidence приведены ниже.

## Production и controlled live gate

Root подтвердил rollout 12:37:53 UTC: host21/runtime8 hashes совпали,
API/worker rebuilt, HEAD `20261004_03` неизменён. Code backup
`/state/backups/s180-m2-before-20261004T123753Z-code.tar.gz`, SHA-256
`937745e635926762fb5d5db69c144c29ef4f5a46118af9692c93611fd61ae72d`.

Production retained hook 12:38:55 UTC: first/replay deltas всех13 таблиц0,
new_versions0, source/file writes0, checkpoint false; 35.251 s,
peak510,578,688 bytes /2 GiB. Proof SHA-256
`6c685db32414507646a328f2b39bc294afff3702685dad4d0ae924ada2f60c71`.

Actual controlled live EIS attempt 12:40:18 UTC, region77 / 2026-09-29:
5 ZIP /499 XML /498 pairs → 0 PROJECTED /497 REPLAYED /1 HOLD.
Новый receipt/batch/498 decisions и typed journal **FAILED** отражают новое
source evidence. Старые8 FAILED сохранены; checkpoint false. 37.43 s,
peak525,844,480 bytes /2 GiB. Успешен automatic partial pipeline, а не обычный
canonical SYNCED target. Новых canonical versions в этом live attempt нет.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-live-proof.json`, SHA-256
`9002caa7ba1a56a8fb0b01fd6ab6ac3b0003f9f6793b0507fefa3d0dde909b47`.

M2 isolated test DB удалена. Final API smoke PASS 12:41:03 UTC: source calls0,
health200, anonymous401, все4 cached responses no-store; coverage/freshness
UNKNOWN. 44 current130458: paper2517 /7636.59 ms, server5269 /14218.4 ms;
223 current2882: paper59 /310.34 ms, server184 /539.79 ms. Это единичные
измерения, не SLA и не доказательство всей ЕИС.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-api-proof.json`, SHA-256
`7cb86d0a8d2ccf5c0cad8d6c2f06c4d30254edfde9e9e314e891c3a045daa030`.

При smoke priority marker отсутствовал; 223 marker присутствовал во время
concurrent regular cron refresh. Это наблюдение не объявляется утечкой marker;
окончательный cleanup подтверждён в12:44:23 UTC: priority=false, 223=false,
test DB отсутствует. Cron удалил свой marker самостоятельно; чужие markers
не удалялись. Owner read подтвердил HEAD03; privileges не изменены.
Proof `/var/lib/eis-browser/research/rejected/s180-m2-operations-proof.json`, SHA-256
`137aed5086b0c9db214022d52991a522cfadf494fa96c1ac725e04267d3b0ccb`.
Automatic partial intake проверен, обычный source gap остаётся FAILED/pending
по контракту. Operational cleanup завершён.
