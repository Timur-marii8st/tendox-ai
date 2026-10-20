# S187 — сравнение карточек одним потоком SQL

Дата: 04.10.2026. Статус: DEPLOYED AND VERIFIED; две цели скорости не достигнуты.
Контракт — [ADR0069](../../adr/0069-eis-search-single-cursor.md).

## Задача и границы

S186 исключает истёкшие сроки до разбора карточек. Оставшаяся стоимость
включает повторное вычисление проверок блокировок, когда каждый следующий
пакет карточек запускает новый SELECT с теми же audit/projection CTE.

В S187 кандидатный запрос выполняется один раз серверным курсором PostgreSQL.
Python получает ограниченные пакеты, сравнивает карточки и читает события
на том же tenant connection в одном READ ONLY REPEATABLE READ snapshot.
Курсор закрывается до окончания транзакции, в том числе при ошибке.
Streaming options относятся только к этому выполнению запроса.

Shared hold/receipt/projection checks не меняются. Решения о конфликтах
не кешируются между запросами. Последние версии, deadline scopes,
резервный поиск без ключей, события, счётчики и ранжирование сохраняются.
Новые таблицы, индексы и миграции не добавляются. Source calls и задания
документов для проверок не нужны; лимиты CPU/memory/disk и cron прежние.

Один SELECT сам по себе не доказывает экономию ресурсов сервера:
материализация CTE и temp spill возможны. Требуются фактические планы и замеры.
Полнота ЕИС, свежесть и доходность остаются UNKNOWN.

## Acceptance

- Exact full pretop100 parity с S186 для обеих scopes и трёх запросов.
- PG несколько пакетов с event queries между ними, tenant/holds/latest/
  fallback/deadline/event regressions; закрытие курсора при ошибке.
- Настоящий server-side cursor, bounded partitions, без buffered `.all()`.
- Пять warm runs каждой реализации для каждой scope/query на одном frozen
  snapshot и aware clock; SQL calls/time, input bytes, JSON response bytes, RSS.
- Цель: scoped median <=80% S186; опубликовать результат даже при недостижении.
- EXPLAIN actual hydration query, temp I/O; independent review до rollout.
- Backup/hash/HEAD/API/UI/operations gates после выпуска.

Владельцы и owned files зафиксированы в docs15 до реализации.

## Проверки реализации

47 focused Linux tests PASS на VPS (3.88s); тот же набор локально47PASS/8.15s.
40 PostgreSQL tests PASS/17.00s: index, hold и projection, включая named cursor,
event queries между пакетами, exact payload parity batch1/batch500 в обеих scopes,
закрытие реального курсора при ошибке snapshot и чтения событий, receipt
corruption/late origins/audit/tenant/migration isolation. Runtime/test Ruff и
mypy PASS. Это87 разных focused tests, повторные запуски не суммируются.

Две первые попытки PG остановились на guard прежних migration tests: они
разрешают только test DB с именами S180/S180_m2. Guard не изменён. Последний
полный запуск использовал заново созданную `procurement_eis_test_20261004_s180_m2`:
до создания проверено отсутствие DB, admin/app URLs перенаправлены только в неё,
владелец удалил её в EXIT trap. Миграции в production не выполнялись. Логи
буферизованы и очищены от секретов до вывода. Все40tests пройдены без deselection.

Core independent review PASS. Module SHA256
`4443d23d17d9fe2e8e548bd1bda1927c0e53dbd255a3aa8fe15b5f3fa8ee43a0`.
Baseline — реальный deployed S186 module SHA256
`c9f43e7b9c32284962ea54d950803d867db0d60bf929b91761422ea2c0000034`.
Benchmark завершён; independent predeploy release review PASS с явно
недостигнутыми двумя performance targets. Release gates пройдены.

## Обычный SELECT и план серверного курсора

READ ONLY EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) обычного SELECT,
один snapshot/aware clock, 30s statement timeout, два полных hydration queries
для «бумага». Эти измерения не являются измерениями живого курсора:

| Scope | Rows | Planning, ms | Execution, ms | Temp read/write blocks |
| --- | ---: | ---: | ---: | ---: |
| ALL_CACHED | 2676 | 52.473 | 741.535 | 3460 / 7004 |
| NOT_EXPIRED_OR_UNKNOWN | 824 | 51.750 | 744.278 | 3460 / 7004 |

Audited projection CTE1032rows, loop1; около377–384ms. Resolved-pairs
материализация около637–648ms inclusive; вложенные timings не суммировать.
Sorts в памяти (121kB inner, около1764/1684kB worker), disk sort не наблюдался.
В этом обычном SELECT наблюдался temp spill при материализации CTE.
S186 EXPLAIN измерял первый LIMIT500, S187 — полный поток: прямого сравнения
этих execution times нет. Client fetch/network/разбор JSON в EXPLAIN не входят.

Proof: `/var/lib/eis-browser/research/rejected/s187-explain-proof.json`, SHA256
`05e801ca31c830fb13929790483cdf50e253d160a1be2855ec92e7c03ebdbbc1`.
Source calls0/DBwrites0. Ни shared hold policy, ни schema не менялись.

Отдельный `EXPLAIN (FORMAT JSON) DECLARE ... NO SCROLL CURSOR FOR ...`
проверил именно план курсора, без выполнения. Это поддерживается
[PostgreSQL16 EXPLAIN](https://www.postgresql.org/docs/16/sql-explain.html).
`cursor_tuple_fraction=0.1`. В обеих scopes план отличается: курсор использует
serial Index Scan `pk_eis_search_keys`, обычный SELECT — Gather Merge и parallel
Seq Scan/sort. Hold/projection CTE присутствуют в обоих планах. Estimated rows
453/141 — оценки, а не фактические строки. Фактические temp I/O и серверная память
курсора остаются UNKNOWN; таблица выше не доказывает расход ресурсов курсора.
Planner proof SHA256
`f45ef1922b6164b19e13973bdfd8d11bc075c03e25ce13bf8c355146415026d4`,
`/var/lib/eis-browser/research/rejected/s187-cursor-plan-proof.json`.

## Полный benchmark

Один READ ONLY REPEATABLE READ snapshot `54428:54428:`, frozen clock
`2026-10-04T17:58:48.636334+00:00`; пять warm runs каждой реализации для
каждой scope/query, порядок OLD/NEW чередуется. Profiling runs исключены из
медиан. Проверено138262 current карточки, scoped43788, excluded94474.
Все шесть полных pretop100 наборов и весь typed response payload, кроме elapsed,
совпали точно. За505.346s выполнены60 измеряемых поисков и отдельный profiling.

| Запрос | Scope | S186 median, ms | S187 median, ms | Выигрыш | Цель20% |
| --- | --- | ---: | ---: | ---: | --- |
| бумага | ALL_CACHED | 7972.341 | 4998.158 | 37.31% | PASS |
| бумага | NOT_EXPIRED_OR_UNKNOWN | 3593.510 | 2931.371 | 18.43% | MISS |
| серверное оборудование | ALL_CACHED | 15462.995 | 11236.546 | 27.33% | PASS |
| серверное оборудование | NOT_EXPIRED_OR_UNKNOWN | 6563.556 | 5081.378 | 22.58% | PASS |
| бумага А4 80 | ALL_CACHED | 9245.087 | 6340.002 | 31.42% | PASS |
| бумага А4 80 | NOT_EXPIRED_OR_UNKNOWN | 3877.537 | 3184.393 | 17.88% | MISS |

Предварительная scoped цель20% не достигнута для двух запросов. Threshold
не меняется; повторные замеры ради PASS не запускаются. Independent review
разрешил выпуск: все шесть медиан улучшились, parity и87tests PASS, число SQL
выполнений уменьшилось, наблюдаемого существенного resource regression нет.

| Запрос | Hydrated rows ALL/scoped | SQL calls OLD→NEW ALL/scoped | Input bytes ALL/scoped |
| --- | ---: | --- | ---: |
| бумага | 2676 / 824 | 17→12 / 10→9 | 81718582 / 22179838 |
| серверное оборудование | 5812 / 1762 | 29→18 / 14→11 | 127714530 / 37475674 |
| бумага А4 80 | 2676 / 824 | 17→12 / 10→9 | 81718582 / 22179838 |

Rows и input bytes OLD/NEW одинаковы: ускорение не получено исключением данных.
SQL execute timings не включают fetch/network и итерацию named cursor.
VmRSS с интервалом25ms: max OLD715632640bytes, NEW707260416bytes; allocator
retention мешает приписать разницу экономии памяти. Worker cap2GiB сохранён.
Source calls0/DBwrites0. Proof checked_at `2026-10-04T18:07:13.982749+00:00`,
`/var/lib/eis-browser/research/rejected/s187-benchmark-proof.json`, SHA256
`11ee673a50e699bed2eba8280716eac2aa826b77aca60a644689ef54e3df121a`.

## Выпуск и проверка продукта

VPS backup `/home/syurai/vibe-seller-state/backups/s187-before-20261004T181407Z-code.tar.gz`,
SHA256 `215b1e33afc706cd44061940033c74d7fee0e92c11deaa04229632b5caf6d0f3`.
API и worker images собраны, API обновлён. Host12/API1/web3/worker1 exact hash
gates PASS; frontend runtime прежний. Schema HEAD `20261004_03`, без миграций.

| Real API query | Default, ms / matches | ALL_CACHED, ms / matches |
| --- | ---: | ---: |
| бумага | 3313.38 / 823 | 5327.65 / 2671 |
| серверное оборудование | 5031.69 / 1690 | 11386.01 / 5581 |

Это отдельные end-to-end smoke calls, не повторные five-run medians.
API auth401/invalidscope422/223regression200/health200/no-store и aware deadline
checks PASS. Coverage/freshness UNKNOWN. API proof SHA256
`c55f84b9e04605c2cab28b67aa51b188cc95733af48b97e15b25b9071a3afa00`.

CUA UI: default paper823matches/43788scope/94474excluded/3095ms;
history2671matches/138262scope/5483ms. Оба режима и UNKNOWN labels PASS;
refresh unchecked, документы не запускались. Return default823matches/3060ms
PASS; во время него обычный background cron увеличил current138262→138264
и excluded94474→94476. Source0/writes0 относятся к foreground checks, а не
ко всему работающему серверу. UI proof и screenshots находятся локально в
`data/research/eis-documents-2026-10-02/s187-ui-*`.
Default screenshot SHA256
`c921b539f7d8f6017e95ad9d394d8490fdf2933d30afd68a3de6d44fb2fcd7ff`,
history `aa582f301a9c92d78f8753689d9914609e7794fbee13c4edaff27014d299c334`.
SSH forward восстановлен, localhost3000→VPS13000, binding127.0.0.1.

Operations `2026-10-04T18:16:17.322426+00:00`: DB3809008663bytes,
volume free263241908224bytes, test DBs отсутствуют, priority/223 markersfalse.
API/web OOMfalse; caps1GiB/768MiB и worker2GiB/CPU2 прежние.
Operations proof SHA256
`4ee5e71214975c63f2cb421c26a935a36739d55d18628c93628397aa28d2b996`.
Foreground proofs находятся в `/var/lib/eis-browser/research/rejected/s187-*.json`.
Source archives/documents остаются на VPS. Cron/source/schema/budgets не расширены.

## Следующий приоритет

Скорость cached comparison улучшена. Для цели всей свежей ЕИС следующий срез —
fresh census оставшихся ingestion gaps и отставания потока, с отдельным учётом
canonical/partial/HOLD и причин ошибок. Известный S185 остаток5 reference gaps
и5 member gaps требует свежей проверки, а не массового retry. Duplicate UID и
large XML обрабатываются отдельными bounded contracts с retained evidence и
resource gates. Полнота источника, полный анализ документов и прибыль пока UNKNOWN.
