# ADR-0068 — explicit deadline scope for cached EIS search

Статус: **DEPLOYED AND VERIFIED / RELEASE REVIEW PASS**.
Дата: 2026-10-04, S186. Owner ADR/review: Astra; storage/query tests: Sol;
API/UI, release gates и operational proofs: root.

## Основание

PRD3.1 исключает рекомендацию просроченных процедур и требует явно показывать
фактическое source coverage. Прежний cached search разбирает token candidates
в batches, а expired deadline определяет после hydration. Исторические карточки
увеличивают стоимость поиска. Ускорение должно сохранять exact matching,
tenant isolation, provenance, ranking и shared variant holds.

## Контракт scope

`search_scope` имеет два значения:

- `ALL_CACHED` — последние известные версии карточек в сохранённом индексе;
  default storage API для совместимости внутренних callsites.
- `NOT_EXPIRED_OR_UNKNOWN` — текущие versions с deadline NULL либо deadline
  строго позже единого timezone-aware `now`; default HTTP API и UI.

UI предоставляет явное переключение на исторический режим. Scope нельзя
называть «активные закупки»: NULL остаётся UNKNOWN, future deadline сам по себе
не доказывает открытость подачи. Результат не означает supplier PASS.

Latest version выбирается до deadline predicate. Истёкшая latest version
исключает purchase из scoped search даже при будущем deadline старой версии.
Deadline==now считается истёкшим. Predicate применяется в SQL к indexed
candidates и missing-key fallback до snapshot hydration; отсутствующие search
keys не теряют подходящие карточки. Existing holds, lifecycle event gates,
term evidence, ranking и top limit не меняются. Invalid scope и naive now
отвергаются до database I/O.

## Counts и evidence

Response явно возвращает `search_scope`, `total_current_notices` и
`excluded_expired_current_notices`. Последний означает число current rows,
исключённых выбранным deadline scope, поэтому в ALL_CACHED равен0.
`inspected_current_notices`, held/matched/evaluated/eligible counts относятся
к выбранному scope. Total current — cached latest purchase count до scope;
ни один из счётчиков не является количеством всех закупок ЕИС.
Global planned/pending/source coverage не сужается scope и остаётся UNKNOWN.

## Verification и resource границы

PG/API gates: latest-expired/older-future, NULL, equality boundary, tenant,
missing-key fallback, holds/events, exact rank/provenance и scoped counts.
Parity проверяется по полному совпадающему набору, а не фильтрацией уже
обрезанного top100 старого ответа. API default, invalid scope422, auth и
no-store обязательны; UI должен согласованно показывать scope и counters.

Benchmark: один frozen repeatable-read snapshot и aware clock, paper/server/mixed
queries,5 warm runs каждого scope. Сравнить median, evaluated rows, SQL calls,
payload bytes и peak RSS. Цель scoped median <=50% ALL_CACHED; опубликовать
фактический результат и при недостижении цели. Это измерение данного snapshot,
не full-EIS SLA. Selectivity и EXPLAIN должны объяснять результат.

Source calls, document jobs, очереди, cron, regions, budgets и schema этим
срезом не меняются. Новый индекс/migration допускается только отдельным
обоснованием EXPLAIN. Deployment требует focused Linux/PG, lint/types/build,
independent review, backup/hash и final API/operations proofs.

## Initial implementation review

Latest anti-join не зависит от deadline predicate; scoped filter применяется
к indexed и fallback branches до hydration, а также к held count. Global
coverage остаётся отдельной. Scope/aware clock validation выполняется до I/O.
Core storage/API blockers не обнаружены. UI не должен утверждать, что все
global unindexed versions проверены, когда expired rows исключены scope;
root исправил эту формулировку. Safe partial projections входят в сохранённый
индекс, но не превращают source window в LEGACY_CANONICAL checkpoint.

## Release gates и benchmark

Root подтвердил44 Linux /26 PG PASS, Ruff/mypy runtime2 PASS,
web types/lint/build PASS. Дополнительный исторический migration suite с
whitelist только S180 исключён из нерелевантного gate; guard не ослаблялся.

Frozen repeatable-read READ ONLY snapshot `53180:53180:`, clock
`2026-10-04T16:46:41.696859+00:00`:138257 current cards,
43790 в выбранном scope,94467 excluded. Full matches до top100 и порядок/
provenance совпали с oracle для всех трёх запросов. Межмодульная проверка
response использует model_dump equality, не identity разных Python classes.

| Query | Old ALL_CACHED median, ms | New scoped median, ms |
| --- | ---: | ---: |
| Бумага |8072.013|3609.358|
| Серверы |15587.794|6575.913|
| Бумага А4 80 |9278.921|4004.232|

Каждая median —5 warm runs на тех же данных и clock. Цель <=50% baseline
достигнута во всех трёх случаях. Serialized input snapshots: бумага
81718582→22179838 bytes, серверы127679458→37475674 bytes.
Measured RSS maximum815468544 bytes включает allocator retention;
снижение peak memory не доказано. Source0; этот benchmark не full-EIS SLA.
Proof SHA-256
`02b204c720d9b2190b427b9a396949cec884e241cdf07cc0949f34d6d096c36b`.

## Deployment и final verification

Root подтвердил backup `s186-before-20261004T170146Z-code.tar.gz`, SHA-256
`b391011238bdbb7333707e51a569382b441eae6cdbd63dd0623b9ad7604556d9`.
Production web build PASS; host14/API2/web3/worker2 exact hashes PASS,
HEAD `20261004_03`. API/web running, OOMfalse; caps1GiB/768MiB неизменны.
Deployment wrapper завершился exit1 из-за CR blank line после успешных
build/start/hash checks; LF normalization и bash syntax PASS подтвердили
исправление helper, runtime failure не выявлен.

Final API17:05:02 UTC: total138259 /scope43788 /excluded94471.
Default/history бумага3805.83/8290.08 ms,823/2671 matches;
серверы7005.37/15521.80 ms,1690/5580 matches. Aware clock, no-store,
auth401, invalid scope422,223 endpoint200 и health200 PASS; source0/jobs0.
Proof SHA-256
`99380e2637bff2a8ba0a7cc9deaa0dcdcb0aaa392d0e171f814e78ff8e0c671b`.

Browser actual VPS UI подтвердил default/history modes и counts823/2671;
измерено3832/8413 ms. Refresh unchecked, новых jobs нет. Изменение checkbox
до следующего поиска не переименовывает прежний result: его mode берётся из
response. Screenshots/AX сохранены в ignored research helper directory.

EXPLAIN на одном read-only snapshot: первый500-row batch ALL_CACHED63.676 ms,
scoped717.591 ms; scoped hold CTE377.809 ms, temporary buffers3460 read /
7004 written. Ускорение полного запроса обусловлено меньшим объёмом обработки,
не ускорением первого batch. Существующая стоимость hold CTE остаётся
измеренным ограничением; новый индекс без обоснования не добавлялся. Source0.
EXPLAIN proof SHA-256
`937cb0558cee4b376622986047ef21481df7041129ced0cd6fef179c91dd43c8`.

Operations17:06:19 UTC PASS: DB3808263191 bytes/free264058691584 bytes,
test DB отсутствует, оба markers отсутствуют. Proof SHA-256
`df4c71b0696ac85b78908b0014f63f1698a8ee21176fd3af78dc245ccb6abb73`.
Independent release review PASS: code и предоставленные gates согласуются
с контрактом; оставшихся blockers нет. S186 deployed and verified, без
утверждения полной свежести ЕИС или общего search/comparison SLA.
