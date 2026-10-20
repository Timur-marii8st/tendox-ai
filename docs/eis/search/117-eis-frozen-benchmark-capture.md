# M2b — неизменный снимок сохранённого поиска

Дата: 2026-10-07. Статус: CONTRACT, NOT EXECUTED. Владелец: Astra.
Зависимость: [M2a принят только локально](116-eis-search-quality-contract.md).
Основание: [M2 и метрики программы](../../product/16-improvement-program.md).
Этот контракт не подтверждает численный baseline, независимую реальную разметку
или полноту ЕИС. Полный source census относится к M5.

## Решение и последовательность

**M2b1:** один ограниченный инструмент durable capture и offline verification.
Он сохраняет полный tenant-scoped набор данных, читаемых текущим поиском, в
неизменный пакет ограниченных shards. Production — только READ ONLY/RLS;
запись только в новый приватный evidence directory. Restore, search measurements
и labels не выполняются этим инструментом. После его review root отдельно
фиксирует exact plan/runtime/output path и разрешает фактический capture.

**M2b2:** восстановление принятого пакета в изолированную БД, существующие search
functions с фиксированным clock, независимая разметка и доверенная проверка
baseline. Это следующий executable slice после принятого M2b1 capture, не
дополнительная возможность M2b1. M2a `REAL_FROZEN` остаётся UNKNOWN до него.

Выбран durable export: его можно повторно использовать для сравнения M3.
Общий exported PostgreSQL snapshot дал бы согласованные чтения только пока
жив exporter; после закрытия он не воспроизводит будущие сравнения. Поэтому
он не заменяет сохранённые bytes. Manifest + live HTTP также не frozen baseline.
Цена выбранного пути — место под payload и отдельная проверка restore parity.

## Точная граница capture

Первый план: `company_id=local-eis-supplier`, оба закона 44/223, весь сохранённый
tenant search index, все его версии, UNBOUNDED по регионам/публикации в пределах
этой БД на выбранный clock. Никакого отбора по словам, top-100, label pool или
списку найденных номеров. Current membership выводится отдельно из всех версий.
Поддерживаемые семейства и фактические source windows перечисляются в manifest;
сохранённый индекс не становится полным корпусом ЕИС.

Inventory 2026-10-07 14:31 UTC: 254765 версий 44 и 10625 версий 223 — только
предварительные counts, не будущий denominator и не freeze. Файл evidence:
`tmp/improvement-program/m2/production-corpus-inventory.json`. Изначальный
нулевой inventory без tenant RLS context отклонён и сохранён отдельно.

Capture plan фиксирует allowlist relation/column/type/PK/order/predicate,
read-closure version, runtime source hashes и schema revision. Нужны полные
поля notice snapshots/search keys, windows/targets/counters, procedure events,
holds/variants/origins/receipts, projection decisions/batches и используемый audit,
223 notice/schema/event/lot-event state. Конкретная замкнутая таблица зависимостей
проверяется по call graph и SQL существующих функций до реализации плана.
Различаются query-read data, служебные FK restore dependencies и raw provenance.
Read-closure audit: `tmp/improvement-program/m2/capture-read-closure-audit.json`,
SHA `db7e5850f52cfaed22b761cce18ab097f56e43fdfba8695627ab5ec0e6fc5cf4`:
11 runtime metadata relations для 44, 7 для 223 и 7 вспомогательных FK parents.
Capture берёт полные tenant rows этих runtime relations; `audit_events` — только
exact IDs, связанные с projection batches и receipt retention/diagnosis/ledger.
Предикаты, сокращающие runtime scan по query/candidates/validator, не сокращают
capture. FK parents выбираются по транзитивным exact ссылкам из сохранённых rows.
Нельзя пропустить tenant-wide integrity predicate, даже если его записи не
встречаются среди результатов. Нельзя экспортировать произвольные audit entities
или секреты под предлогом полноты; допустим только доказанный search read-closure.

Исторические ZIP/XML blob contents не копируются, если runtime search не читает
их bytes. Метаданные/ссылки/хеши, которые runtime читает, сохраняются. Исключение
каждой большой колонки имеет явную причину в плане. Saved snapshot payload
достаточен для воспроизведения поиска; сам по себе он не доказывает подлинность
официального XML. Для выбранных labels позже нужны исходные bytes и exact locators.
Выбран **search-projection copy**, не backup исходной БД. Вспомогательные
`eis_feed_archives`/`eis_223_blobs` сохраняют PK и metadata без `content bytea`;
остальные пять parents сохраняют необходимые metadata/FK поля. План явно
перечисляет каждое отличие projection schema, включая отсутствие исходного
NOT NULL binary column. Stub bytes и фиктивный SHA пустого архива запрещены.
Search-critical columns/types/indexes/RLS и связи сохраняются. Если pinned
runtime начинает читать исключённое поле, нужны новый closure/plan/freeze.

## Исполнение M2b1 и пределы

Одна tenant-bound READ ONLY REPEATABLE READ транзакция, один aware UTC clock
`T`, одна snapshot identity. Используется app-role без BYPASSRLS/superuser;
`SET LOCAL app.company_id` предшествует чтению tenant-таблиц. Явные tenant
predicates дополняют RLS. Проверяются current_user, readonly/isolation/context;
чужой tenant и DML отвергаются. Запрещены source requests, sync/jobs, schema
изменения, production restore, остановка ingestion и ослабление RLS.

План задаёт точные schema/types/PK и source/runtime identity. CRLF→LF равенство
допустимо только как отдельная диагностическая связь: runtime bytes SHA, Git blob
SHA и нормализация записываются раздельно, не подменяют друг друга. Pin включает
image ID, deployed source closure, lock/dependency versions, PostgreSQL/schema
revision и collector/verifier source SHA. Непредусмотренный drift останавливает
capture. Для schema metadata разрешены только явно перечисленные каталоги.

Строки читаются server-side bounded batches в устойчивом PK-порядке; `.all()`
всего корпуса запрещён. Counts, payload и зависимые таблицы берутся в той же
транзакции. Поздние committed imports/events не смешиваются с её состоянием.
Все сохранённые версии остаются в архиве; current-at-T выбирает максимальную
версию среди `ingested_at <= T`. Будущие/аномальные даты раскрываются отдельно,
не переносятся в current membership. Holds/events воспроизводятся из того же
snapshot, а не перечитываются после capture.

Исходные hard caps плана: 8 MiB на JSONL shard, 16 MiB на любой metadata artifact,
512 shards и 4 GiB total payload, 1 миллион rows на relation, batch <=500;
statement timeout 30 s, lock timeout 1 s, весь capture <=15 min. До старта
проверяются counts и свободное место >=5 GiB; во время чтения действуют byte/time
ограничения. Одна строка, не помещающаяся в shard, вызывает отказ, не усечение.
Root может принять иной явный plan version после инвентаризации ресурсов;
автоматическое повышение cap или молчаливый переход к subset запрещены.
Предварительный `capture-storage-budget.json` показывает ~7.64 GB физических
relations всех tenants, из них ~6.02 GB — archive/blob relations. Это не размер
JSON экспорта данного tenant: cap 4 GiB остаётся гипотезой с отказом при превышении.

При превышении cap, timeout, потере snapshot или source/schema drift —
`INCOMPLETE` с причиной и фактическими counts, без terminal complete manifest и
без approved digest anchor. Частичные файлы сохраняются для диагностики.
Возобновлять capture в новой транзакции под тем же capture ID нельзя.

## Формат и offline verification

Версионированный plan и terminal manifest содержат tenant/T/snapshot/runtime,
selection, схемы, counts, descriptors каждого shard: bytes/SHA/rows/first-last PK,
ordered-row digest и общий список файлов. Canonical typed JSONL сохраняет Decimal,
datetime/date, UUID, arrays, null и исходный JSON без преобразования в float.
Нормализация типов определяется схемой; восстановление обязано быть lossless.
Reference fields не подменяют сохранённые данные, реально читаемые поиском.

Verifier не подключается к БД/сети и не исполняет SQL/код из пакета. Allowlist
и schema contract берутся из reviewed tool/plan, а не произвольного manifest.
Он ограниченно читает каждый файл, проверяет SHA/bytes/rows, tenant, PK/order,
cross-shard дубли/пропуски descriptors, total counts и current-version derivation.
PK не может повторяться с другим payload. Несуществующая ссылка, неразрешённый
relation/column/type, потерянная FK dependency или incomplete table блокируют
пакет. Future-at-T строки не становятся current. Path traversal, symlink,
необычные file types и лишние файлы не принимаются. Shards не объединяются в
прежний flat corpus JSON сверх 16 MiB: M2a формат и cap сохраняются.
Проверка потоковая; лимит памяти/batch bytes фиксируется планом и проверяется
тестом на нескольких shards, а не предполагается из ограничения числа rows.

Результат verifier — `CAPTURE_CONTENT_VERIFIED | FAIL | INCOMPLETE`, отдельно
`capture_origin_trust=UNKNOWN`. Согласованные hashes доказывают целостность
полученных bytes, но не факт их происхождения из production snapshot.

## Доверие, M2b2 и первый измеряемый scope

Trust anchor находится **вне** недоверенного capture package: root после
независимого review фактического запуска утверждает exact manifest SHA, plan SHA,
runtime/schema identity, collector/verifier hashes и digest execution/audit proof.
Verifier принимает ожидаемый digest через доверенный launcher/operator context;
JSON внутри пакета не может сам назначить issuer или доверенный hash. При отсутствии
такого внешнего решения — UNKNOWN. Это operator trust, не выдуманная подпись.
Root сохраняет решение и независимое review immutable; origin checks включают
actual transaction/RLS/read-only evidence и повторную проверку всех shard bytes.

M2b2 восстанавливает только этот принятый dataset в отдельную disposable DB,
без production DSN/ports/secrets и source network. Проверяются schema/row hashes,
FK/read-closure parity с перечисленными projection exceptions, distinct tenant
rejection, точные существующие функции
`search_eis_index`/`search_notice223_index`, фиксированный `now=T` и неизменный
dataset до/после. Поиск работает app-role read-only; restore — отдельный этап.
Baseline называется SQL_STORAGE: duration включает DB queries/fetch/comparator,
но не HTTP/Server Action/UI. У HTTP нет управления этим clock без нового runner;
настоящая HTTP latency остаётся отдельным неподтверждённым измерением. Performance
зависит от copy environment/statistics/cache; это не SLA production. Требование
parity касается search payload/порядка/диагностик, не байтов полного backup БД.

Отдельная real suite freeze, не перезапись template M2a: первый bounded baseline
посвящён бумаге, с разными intent broad supply, office-A4 supply и paper-related
services; 44 включает оба режима срока, 223 только ALL_CACHED и office-A4 case.
Точные case IDs/число/queries/intent утверждаются в M2b2 до measurements.
Начальные параметры: page size100, три повтора, timeout30s, continuation budget20.
Предварительные/прогревочные вызовы и их duration сохраняются с явной ролью;
нельзя скрыть failed attempt или назвать warm run cold. Правило обязательной
следующей страницы при non-null cursor фиксируется в плане заранее; terminal
null не требует искусственных пустых страниц. Expansion этого условного плана
в exact attempts M2a требует проверяемого trace и не удаляет failed/missing page.
Превышение traversal budget — INCOMPLETE; criteria не меняются задним числом.
Полный M2 дополнительно требует natural-language, short-feature, abbreviation,
invalid-query и прочие заявленные cases template; unsupported active/region/
price/KTRU/date filters раскрываются явно. Paper baseline не заменяет полный M2.

Независимый reference pool включает selected и nonreturned кандидатов, negatives
и version conflicts; номера из старого top-100 не определяют весь эталон.
Label author и reviewer различаются; reviewer также не instrument author.
Они проверяют saved metadata и отдельно exact official XML/archive SHA/member/
locator. Недоступные raw bytes дают UNKNOWN, не network fetch в benchmark loop.
Review artifact связывает tenant/case/intent/scope/corpus/exact version, verdict,
membership, source evidence и method. Root утверждает его exact digest отдельным
внешним trust record; счётчик имён reviewer не является проверкой независимости.
До этих capture + raw + review checks `REAL_FROZEN` остаётся UNKNOWN.

## Owned files и acceptance M2b1

Sol, после решения root, только шесть новых файлов:
`src/procurement/sources/eis_search_capture.py` (формат/verifier),
`src/procurement/storage/eis_search_capture.py` (read-only collector),
`scripts/eis-search-capture.py` (capture/verify CLI),
`scripts/benchmarks/eis-search-capture-plan.v1.json`,
`tests/test_eis_search_capture.py`,
`tests/integration/test_eis_search_capture_pg.py`.
Search functions, M2a/v1, API, migrations и production не меняются.

Acceptance: synthetic PG capture → offline verify с lossless row roundtrip;
RLS tenant A/B isolation, concurrent newer notice/hold/event вне snapshot,
current-at-T parity, byte-exact cross-shard verification. Negative cases:
tenant/schema/runtime drift, omitted relation/dependency/shard, duplicate PK,
tampered bytes/count/order/time, boundary-sized row, cap/time/disk failure,
nonregular file/path escape и ложный package self-approval. Ни один не даёт
complete/trusted результат; tests не требуют production credentials. Focused
tests, real isolated PG tests без skips, Ruff/mypy и docs check; независимый
review до actual capture. Закрытие M2b1 не закрывает M2b2 или полный M2.

## Дополнение v2: большие логические audit rows

Дата решения: 2026-10-07. **Архитектура ACCEPTED; реализация и новый capture
ещё не подтверждены.** [ADR-0108](../../adr/0108-bounded-eis-audit-row-fragments.md)
задаёт wire/verification contract. Предыдущие разделы описывают исходный v1;
их правило отказа строки больше shard сохраняется для v1. Только описанное
здесь v2 исключение изменяет это правило. Root сохранил исходный 117 SHA
`0c08e82605dec89603a2df4acff99a759c8d1d5869bc00e921fdac0e705b4ab0` и семь
принятых source v9 files в
`tmp/improvement-program/m2/capture-v9-source-before-format-v2/`.

Причина: actual run1 остановился до relation export с `INCOMPLETE` /
`RAW_ROW_EXCEEDS_SHARD_LIMIT:audit_events`. Отдельный app-role readonly probe
увидел 96 linked rows, три >8 MiB, max raw 14 839 504 bytes, max basis text
14 839 307 bytes. Evidence и точные SHA приведены в ADR-0108. Probe не получал
basis и не доказал typed size/семантическую валидность. Его T/snapshot относятся
к новой транзакции. Clock failed marker — host attempted_at; DB T/snapshot
run1 остаются UNKNOWN. Run1 и его evidence не переписываются.

### Явное исключение и неизменные границы

Только `audit_events` в новом v2 plan допускает logical raw row <=32 MiB и
canonical typed row с newline <=64 MiB, максимум восемь binary fragments.
Другие relations сохраняют прежний single-row bound. Физические пределы
не повышаются: 8 MiB/file, 16 MiB metadata, 512 physical payload files и
4 GiB total **с fragments**, 1M logical rows/relation, batch <=8/64 MiB raw,
900 s capture, 30 s statement, 1 s lock, >=5 GiB free disk, 2 GiB container.
Это видимое versioned logical-row исключение, не automatic cap raise.

Full exact linked-ID selection, девять audit columns и весь basis сохраняются.
Малые rows имеют прежние canonical typed bytes; большая audit row получает
v2 descriptor в своём logical PK-порядке и consecutive fragments её **точных
исходных canonical typed bytes**. Descriptor связывает tenant/relation/typed
PK/logical ordinal, whole bytes/SHA и ordered fragment path/ordinal/offset/
bytes/SHA. Nonfinal fragment ровно 8 MiB, последний непустой; нет compression.
Fragment имеет одного row owner и входит в exact manifest file closure.

Verifier до reads/allocations проверяет declared limits, затем bounded
reassembly одной строки и прежние typed/tenant/PK/FK/projection/receipt checks.
Counts/digest считаются по восстановленной logical row один раз. Транспортные
hashes не заменяют semantic basis validation. Missing/extra/duplicate/reordered
или cross-parent fragments, gap/overlap, wrong offset/PK/size/hash, чужой tenant,
неразрешённый relation, unsafe path/file type и mixed version отвергаются.

Prefetch определяется **до cursor** из maximum raw width в том же snapshot:
`min(8, floor(64 MiB / max(1, maximum_raw_row_bytes)))`. Driver и partitions
имеют этот bound, дополнительно проверяются фактические row/batch bytes.
Canonical serializer пишет/hash-ит fragments постепенно и останавливается
на logical limit; проверки после неограниченной allocation недостаточны.
Raw prefetch cap не является измерением heap: collector/verifier обязаны
пройти multi-large-row peak-memory проверку в прежнем container budget.

Внутри fragment loops действуют time/disk/total caps. Частично записанная row
не считается завершённой; counts incomplete либо UNKNOWN. При ошибке нет
complete manifest/origin anchor. Новый incomplete record разделяет host
`attempted_at` и nullable фактические DB T/snapshot/runtime. Host clock не
подменяет T; basis/credentials в diagnostic logs не сохраняются.

### Один implementation slice и его acceptance

Sol после принятия exact contract изменяет только:

- `src/procurement/sources/eis_search_capture.py` — versioned format/verifier;
- `src/procurement/storage/eis_search_capture.py` — bounded collector;
- `scripts/eis-search-capture.py` — явный version dispatch;
- `scripts/benchmarks/eis-search-capture-plan.v2.json` — новый synthetic plan;
- `scripts/benchmarks/eis-search-capture-plan.production-20261006_08.v2.json`
  — новый production08 plan;
- `tests/test_eis_search_capture.py`;
- `tests/integration/test_eis_search_capture_pg.py`.

Оба v1 plans и исторические archives/results остаются неизменны. Valid v1
package продолжает проверяться v1 path; v1 не принимает v2 descriptors.
Search/API/migrations, M2a и production data/permissions не меняются.

Acceptance: прежние v1 controls; exact canonical roundtrip/digest на small и
fragmented rows; Unicode/Decimal/nested JSON и границы 8/32/64 MiB; все негативные
descriptor/fragment/file cases выше; hash-consistent basis corruption всё ещё
отвергается семантически. Fresh isolated real PG fixture содержит корректный
linked audit basis >8 MiB, несколько больших rows, RLS tenant isolation и
concurrent commit вне snapshot. Проверяются prefetch и фактическая peak memory
collector/verifier; cap/deadline посреди fragment оставляет INCOMPLETE/FAIL
без complete manifest. Затем focused checks и independent exact-source review.

Root отдельно фиксирует новый source archive/execution plan и fresh IDs после
instrument acceptance; при необходимом изменении controller version binding
оно получает собственный bounded review. Автоматического retry run1 нет.
Реальный corpus может по-прежнему не уложиться в logical/total/time limits;
это не разрешает truncation/subset. Actual content/origin acceptance, M2b2
replay/labels и метрики требуют последующей проверки и остаются UNKNOWN.

### Уточнение v2 от 2026-10-08: проверяемый raw bound и запись payload

По принятому root review F2-A/F2-B
`capture-format-v2-independent-review-v1.json` (SHA
`efc43df15786142f74758b4841ec7e3c71183cb2553b010bd0a8ee5a9d728251`)
действует [уточнение ADR-0108](../../adr/0108-bounded-eis-audit-row-fragments.md).
Предыдущие source/docs сохранены в
`tmp/improvement-program/m2/capture-format-v2-source-rejected-v1/`;
отклонённая реализация не становится принятой из-за изменения документа.

Exact raw width остаётся PostgreSQL scalar `::text` octet sum в capture TX;
collector обязательно проверяет его до prefetch. Offline verifier bounded-
обходом проверяет лишь нижнюю границу UTF-8 bytes decoded strings выбранных
колонок, включая JSON keys/leaves и strings arrays, по каждому вхождению.
Column names, typed wrappers и повторный PK metadata не считаются; numeric/date
и неустановленный PG formatting дают нулевой вклад. Нижняя граница >32 MiB —
FAIL; меньшая граница не доказывает exact source raw cap. Гигантская string
измеряется ограниченными chunks, без полной дополнительной byte allocation.

Во всех v2 reports: `raw_width_validation=DECODED_LOWER_BOUND_ONLY`,
`source_raw_width_attestation=UNKNOWN`, также при matched external digest.
Exact source raw-width соблюдение устанавливается только trusted collector
execution + внешним root origin audit. V1 reports/планы не меняются; package
не может сам аттестовать происхождение или заменить PG observation.

Перед новым physical payload file и каждой byte-записью резервируются global
file-count/payload-byte budgets и проверяются deadline/disk. Это относится к
inline shards, transitions и fragments. Исчерпанный cap не допускает лишний
payload на диске; partial-write accounting консервативен. Partial logical row
не считается completed. Logical caps и bounded temporary spool остаются.
Regressions обязаны воспроизвести оба отклонённых случая, покрыть границы и
partial failures; остальные acceptance/owned files/real PG/memory требования
выше сохраняются. Исправление source и новый capture пока не подтверждены.
