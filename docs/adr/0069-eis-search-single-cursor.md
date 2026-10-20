# ADR-0069 — single streamed candidate cursor for cached EIS search

Статус: **DEPLOYED AND VERIFIED / RELEASE REVIEW PASS**.
Дата: 2026-10-04, S187. Owner ADR/high-risk review: Astra;
query implementation/tests: Sol; gates, benchmark и rollout: root.

## Основание и решение

S186 сократил hydration посредством deadline scope. Однако каждый keyset batch
исполняет новый candidate SELECT с теми же search-key и shared hold CTE;
отдельный held-count query также имеет собственную стоимость. Следующий bounded
срез заменяет только повторяющиеся hydration SELECT одним ordered server-side
cursor. Policy, source coverage и matching semantics не меняются.

Один SELECT содержит существующие tenant/current/deadline/indexed-or-fallback/
hold predicates и ORDER BY purchase_number. Result читается partitions не больше
прежнего batch_size (default500). Нужен настоящий server-side streaming cursor;
partitions поверх уже буферизованного полного результата недостаточно.
Streaming options задаются для hydration statement/execution, не изменяют
состояние общей connection для subsequent event/count queries.

Cursor живёт в существующей tenant `consistent_read=True` transaction:
PostgreSQL REPEATABLE READ + READ ONLY. Между partitions lifecycle events читаются
через ту же connection и snapshot. Это требует проверенного psycopg3 поведения
при открытом named cursor. Hold clauses сохраняют полную проверку exact audit,
canonical projection, receipts, origins и integrity; новые изменения после
snapshot видны следующему запросу, не частично текущему.

Python удерживает одну partition, связанные events и bounded top leaders.
Cursor закрывается явно в finally при normal exhaustion, early exit и exception,
до выхода из transaction. Исключение не возвращает частичный success. Отдельный
held-count query остаётся; SQL planner может использовать sort/temp spill,
поэтому server memory/I/O не объявляются ограниченными одним batch_size.

## Альтернатива

Transaction-local temporary table/materialization не требуется: она добавляет
write/lifecycle/cleanup обязанности и меняет read-only исполнение. Один cursor
убирает повтор statement evaluation без новой таблицы, persistent cache или
миграции. MATERIALIZED CTE внутри прежней hold policy не меняется.

## Acceptance

- Полная pre-top100 parity для ALL_CACHED и NOT_EXPIRED_OR_UNKNOWN: exact
  identities, ranking, provenance, matched/evaluated/eligible/held counters.
- Latest-before-deadline, NULL UNKNOWN, missing-key fallback, tenant isolation,
  lifecycle gates и receipt/origin corruption hold сохраняются.
- PG подтверждает event queries между partitions, один hydration statement,
  закрытие server cursor при exhaustion и искусственной ошибке обработки;
  поздний origin не создаёт смешанный snapshot и удерживает следующий поиск.
- Никакой early truncation кандидатов ради скорости, никаких source/job calls,
  schema/index/cron/budget изменений.

На одном frozen read-only snapshot/aware clock выполнить5 warm runs обоих
scopes для paper/server/mixed query против S186. Цель — минимум20% reduction
scoped median; публикуется actual result даже при недостижении. Измерить SQL
statement/CTE executions, evaluated rows, payload, EXPLAIN, temp I/O и RSS при
прежних контейнерных caps. Не обещать меньшую память или SLA без evidence.
Deployment допускается после focused PG/Linux, lint/types, independent review,
backup/hash и final API/operations proofs. Пока подтверждён только контракт.

## Initial independent implementation review

Reviewed runtime SHA-256
`4443d23d17d9fe2e8e548bd1bda1927c0e53dbd255a3aa8fe15b5f3fa8ee43a0`:
один ordered hydration SELECT; statement-local `yield_per=batch_size`,
`mappings().partitions(batch_size)` и закрытие исходного CursorResult в finally.
Candidate/hold predicates и comparison/count/rank loop сохранены, event queries
используют ту же connection. Code review PASS, blockers не выявлены.

PG assertions проверяют настоящий named cursor, event interleaving, exact
response parity batch1/500 для обоих scopes, закрытие после snapshot/event
exceptions. Root/Sol сообщили lint/types PASS и5 local unit PASS; actual PG,
frozen benchmark/EXPLAIN/RSS и deployment evidence ещё ожидаются.

## Gates и результаты benchmark

Root подтвердил47 Linux PASS (3.88 s),40 PG PASS (17 s), Ruff/mypy PASS.
Полный final PG suite включает projection/migration guard; whitelist не менялся,
test DB использовала разрешённое точное имя и удалялась cleanup trap.

EXPLAIN full SELECT: paper ALL2676 rows /741.535 ms, scoped824 rows /
744.278 ms. Audit CTE1032 rows,loops1,около377/384 ms; inclusive
materialization около637/648 ms. Temp buffers3460 read/7004 write;
sort в памяти, disk sort не наблюдался. Proof SHA-256
`05e801ca31c830fb13929790483cdf50e253d160a1be2855ec92e7c03ebdbbc1`.

Первый five-run paper result: ALL7972.341→4998.158 ms;
scoped3593.510→2931.371 ms (18.43% improvement). Scoped target20% здесь
не достигнут; threshold не меняется и замер не повторяется ради PASS.
Full pre-top100 и payload parity (кроме elapsed) PASS. Полные результаты ниже.

Frozen snapshot `54428:54428:`, clock `2026-10-04T17:58:48.636334Z`:

| Query / scope | S186 median, ms | S187 median, ms |
| --- | ---: | ---: |
| Paper / ALL |7972.341|4998.158|
| Paper / default |3593.510|2931.371|
| Servers / ALL |15462.995|11236.546|
| Servers / default |6563.556|5081.378|
| Paper A4 80 / ALL |9245.087|6340.002|
| Paper A4 80 / default |3877.537|3184.393|

Каждая median —5 warm runs. Scoped target20% не достигнут для paper и mixed:
18.43% /22.58% /17.88% improvement соответственно; threshold неизменен.
Все6 полных pre-top100 match sets и весь response payload, кроме elapsed,
имеют exact parity. Rows/input bytes неизменны. SQL calls ALL17→12 /29→18 /
17→12; default10→9 /14→11 /10→9.
Max warm RSS old715632640/new707260416 bytes; allocator confounding не позволяет
утверждать уменьшение памяти. Worker cap2GiB неизменен, source0/writes0.
Benchmark proof SHA-256
`11ee673a50e699bed2eba8280716eac2aa826b77aca60a644689ef54e3df121a`.

Отдельный EXPLAIN DECLARE показал отличие cursor plan от ordinary SELECT для
обоих scopes: cursor_tuple_fraction0.1, serial pk_eis_search_keys IndexScan без
GatherMerge против parallel SeqScan/GatherMerge/sort у ordinary SELECT.
Hold CTE присутствует. Приведённые выше temp3460/7004 и materialization timings
относятся только к ordinary SELECT; actual cursor temp I/O/server memory UNKNOWN.
DECLARE proof SHA-256
`f45ef1922b6164b19e13973bdfd8d11bc075c03e25ce13bf8c355146415026d4`.

Predeploy release review **PASS**:87 distinct focused tests, exact parity,
снижение всех6 medians/SQL calls и соблюдённые measured worker caps обосновывают
bounded rollout несмотря на два явно зафиксированных target misses. Это не
утверждение прохождения всех performance targets или общего SLA. Runtime SHA
остаётся указанным выше; rollout/API/operations verification подтверждены ниже.

## Production verification

Backup `s187-before-20261004T181407Z-code.tar.gz`, SHA-256
`215b1e33afc706cd44061940033c74d7fee0e92c11deaa04229632b5caf6d0f3`.
Host12/API1/web3/worker1 exact hashes PASS; HEAD `20261004_03`, migrations нет.
API/worker built, API recreated, web unchanged. API cap1073741824 bytes,
web805306368 bytes, OOMfalse.

Actual API: paper default3313.38 ms /823 matches, ALL5327.65 ms /2671;
servers default5031.69 ms /1690, ALL11386.01 ms /5581. Auth401, invalid422,
223 endpoint200, health200, no-store, aware deadline и UNKNOWN semantics PASS.
API proof SHA-256
`c55f84b9e04605c2cab28b67aa51b188cc95733af48b97e15b25b9071a3afa00`.

Browser paper default3095 ms /823 matches, scoped43788/excluded94474;
history5483 ms /2671. Return to default3060 ms /823. Scope/UNKNOWN labels
сохранены, refresh unchecked, document jobs0 и search source calls0.
Background cron продолжал ingestion: current138262→138264, поэтому общий
source0 для VPS не заявляется. Screenshot SHA-256 default
`c921b539f7d8f6017e95ad9d394d8490fdf2933d30afd68a3de6d44fb2fcd7ff`,
history `aa582f301a9c92d78f8753689d9914609e7794fbee13c4edaff27014d299c334`.

Operations `2026-10-04T18:16:17.322426Z`: DB3809008663 bytes,
free263241908224 bytes, test DB отсутствует, оба markers отсутствуют.
Proof SHA-256
`4ee5e71214975c63f2cb421c26a935a36739d55d18628c93628397aa28d2b996`.
Foreground checks source0/writes0; background cron resumed unchanged.

Final independent release review PASS. Deployed slice verified; два scoped
target20% misses остаются зафиксированными, actual cursor temp I/O/server
memory UNKNOWN. Одиночные production timings не заменяют frozen benchmark
и не являются общим SLA. Полный охват/свежесть ЕИС не подтверждены.
