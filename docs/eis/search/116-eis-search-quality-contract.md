# M2a — честный benchmark сохранённого поиска, v2

Дата: 2026-10-07. Статус: M2a ACCEPTED LOCALLY; реальные метрики M2 UNKNOWN.
Владелец контракта: Astra. Зависимость M1 принята root; требования —
[программа M2 и метрики](../../product/16-improvement-program.md),
[PRD §3.1](../../product/11-product-requirements.md#31-поиск).
Этот срез выпускает offline-инструмент расчёта, а не завершает M2.
Ревизия 2 уточняет отказы, подтверждённые независимыми synthetic probes M2a.

## Граница и совместимость

Существующие `sources/eis_search_benchmark.py`, `server-eis-query-benchmark.py`,
suite v1 и [исторические результаты](34-eis-search-benchmark.md) сохраняются.
Их success-only p95 не становится all-outcome p95 задним числом. В v1 пустая
выдача даёт precision null, а reference recall не связан с обязательным
membership; optional membership относится только к текущим версиям 44-ФЗ.

M2a добавляет отдельные строгие v2 модели, проверку сохранённого evidence,
детерминированный JSON/Markdown report-only CLI и синтетические тесты.
CLI не имеет network/DB/capture режима, не исполняет код из evidence и не
импортирует v1 runner с сетевыми зависимостями. Реальный capture и независимая
разметка — следующий согласованный срез M2b. Изменение поиска, фильтров,
ранжирования, API, схемы БД, ingestion и deployment сюда не входит.

## Версионированный пакет

Каждый файл имеет собственный discriminator `eis-search-<kind>-v2`; пакет
связывает SHA-256 suite, corpus manifest, observations, labels и метода.
JSON модели frozen/extra-forbid; даты aware, числа метрик Decimal, длительности
конечные и неотрицательные. Нельзя молча принять v1 или неизвестную версию.

| Объект | Обязательная идентичность и evidence |
|---|---|
| Suite | Версия набора, уникальный case ID, query и intent, критерий релевантности, tenant, law, endpoint/measurement boundary, все параметры и defaults, repeats, timeout, порядок, warmup и page budget |
| Scope | Закон/семейства, набор регионов и его источник, интервал публикации и включённость границ либо явно UNBOUNDED, aware clock, deadline mode, filters с местом применения, порядок/rank version, page size и continuation policy |
| Corpus | Tenant, capture ID/time, полное описание selection и таблиц/полей, row counts/caps, упорядоченные записи и их SHA, schema/migration/runtime/source/lock identity, доказательство согласованного snapshot |
| Observation | Case/repeat/page ID, exact scope/suite/corpus SHA, начало/конец и monotonic duration, typed outcome, HTTP/error code при наличии, bounded raw response SHA/bytes/locator, упорядоченные exact result IDs, cursors и page fingerprint/clock |
| Label | Tenant, case/intent/scope SHA, law + purchase number + version + source XML SHA, RELEVANT/IRRELEVANT/UNKNOWN, PROVISIONAL/REVIEWED, reviewer/author identity, метод, aware review time, reason, exact evidence SHA/locator |
| Report | Все входные SHA, версия расчёта/исходников, проверенные и недостающие prerequisites, denominator/numerator, coverage разметки, outcomes, статус и явная граница каждого числа |

Scope hash использует документированную canonical JSON сериализацию, а файл
проверяется по SHA исходных bytes. Каждый artifact tenant-scoped. Пути только
внутри evidence root после resolve; traversal, symlink escape, изменённые bytes,
несуществующий locator и несовпадение exact identity отвергаются. Лимиты bytes,
числа записей и страниц заданы методом до чтения; превышение не обрезается молча.
Credentials, cookies, DSN, token и произвольный exception text не сохраняются.
Проверка confinement, regular file и ограниченное чтение не более cap+1 bytes
предшествуют hash/JSON parsing, включая корневой package manifest.

Для M2a `REAL_FROZEN` product acceptance всегда UNKNOWN: отдельный доверенный
M2b verifier capture/raw-source/review proof ещё не реализован. Поля consistency
и JSON, повторяющий identity/booleans, подтверждают лишь внутреннюю согласованность
пакета, не происхождение bytes и не независимость review. Prerequisites отчёта
различают проверенную целостность и отсутствующую доверенную проверку;
`consistent_complete_corpus` для реальных данных не становится true по декларации.
Synthetic report имеет SYNTHETIC_ONLY, даже когда арифметические цели выполнены.

## Реальные интерфейсы и замороженный baseline

44: GET `/v1/tender-discovery/eis-index`, параметры `query`, `search_scope`
(`ALL_CACHED`/`NOT_EXPIRED_OR_UNKNOWN`), `page_size`, `cursor`. 223: GET
`/v1/tender-discovery/eis-223-index`, только `query`, `page_size`, `cursor`;
его текущий storage mode — `ALL_CACHED`. Tenant берётся из principal.
Region/price/KTRU/OKPD2/publication-date HTTP filters не реализованы;
`require_documents`/`exclude_failed` доступны только 44 storage function.
Регионы обновления не являются поисковым фильтром. Case с неподдерживаемым
параметром получает UNSUPPORTED/UNKNOWN, а не притворную фильтрацию.
Offline post-filter требует отдельного имени и не измеряет HTTP filter.

Suite v2 template покрывает оба закона, оба поддержанных режима 44, первую
страницу и continuation, товарные слова/синонимы/аббревиатуры/короткие признаки,
natural-language и invalid query. Отдельные unsupported cases раскрывают
пробелы PRD. Каждый будущий реальный case получает фиксированные scope и intent;
template с незаполненным corpus/review evidence не допускает численную acceptance.
Широкое «бумага» не означает молча офисную А4: broad-paper, office-A4 supply
и paper-related services имеют разные intent/cases. «Доступные сейчас» требует
явной политики: 44 `NOT_EXPIRED_OR_UNKNOWN` допускает неизвестные сроки,
223 `ALL_CACHED` не фильтрует истёкшие. Future deadline без подтверждённого
submission state не доказывает открытый приём; unsupported active-only request
остаётся UNKNOWN. Template задаёт intent, но не готовые реальные labels.

Baseline M2b берёт уже сохранённый индекс один раз, без ЕИС/public fetch на
каждый запрос. Нужна согласованная копия всех влияющих на поиск данных:
точные версии и search keys, current-version selection, source/projection,
holds/variants/origins/receipts, procedure/lot events, schema eligibility и
используемые counters/watermarks. Набор latest IDs или output matches этого
не доказывает. Capture выполняется tenant-bound READ ONLY REPEATABLE READ,
с явным RLS context, стабильной сортировкой, лимитами и единственным clock.

До capture отдельно ревьюируется один способ: изолированная неизменная копия
сохранённой БД либо adapter общего exported PostgreSQL snapshot для всех чтений
существующих search functions. В последнем случае граница измерения называется
SQL/storage, а не HTTP. Для HTTP нужен отдельно доказанный frozen backend и
управление clock. Текущие HTTP handlers открывают отдельные транзакции и выбирают
новый clock: manifest + последующие live HTTP calls не доказывают frozen corpus.
[Cursor fingerprint](113-eis-search-continuation.md) относится к совпадениям
запроса, не к полному корпусу. TTL 15 минут, 409/410, drift/late event и restart
сохраняются как исходы; разные snapshots в один успешный traversal не склеиваются.
До этой проверки corpus consistency и baseline acceptance остаются UNKNOWN.
Внутренняя проверка связывает page snapshot_at с замороженными scope/capture
clock и запрещает записи, ingested позже допустимого clock. Для continuation
предыдущий output cursor обязан совпадать со следующим input; первая страница
не имеет input, законченный проход не имеет оставшегося output cursor.
Полный проход требует всех последовательных успешных страниц без пропусков,
дублей и drift; одинаковый fingerprint сам по себе недостаточен.

## Метрики v2

- **Latency:** nearest rank `ceil(0.95 × N)` по всем завершённым попыткам,
  включая error/timeout/invalid response/409/410; duration — до terminal outcome.
  `all_outcome_p50_ms`/`all_outcome_p95_ms` и success-only diagnostics имеют
  разные имена. Указываются planned/attempted/completed/not-attempted counts,
  причины остановки, error rate, timeout и warm/cold policy. Неисполненная
  попытка не получает 0 ms. Прерванный набор не получает threshold PASS.
  First-page requests и continuation requests имеют отдельные distributions;
  полный traversal — отдельная end-to-end метрика, а не смесь страниц с queries.
- **Precision@10:** первые десять уникальных purchase IDs в исходном порядке
  (law включён в ключ); версии не объединяются. При полном exact REVIEWED
  покрытии — relevant / `min(10, unique returned)`. Успешная пустая выдача с
  независимо подтверждёнными in-scope positives даёт 0, в том числе когда
  positive отсутствует в corpus; причина отдельно отражается как coverage loss.
  Пусто без известных positives — null/ZERO_DENOMINATOR, не 1 и не пропуск.
  Неразмеченные/конфликтующие позиции дают UNKNOWN и лишь явно подписанные
  bounds; ошибочный запрос не маскируется под успешную пустую выдачу.
- **Known-reference recall:** relevant references сначала разделяются на
  IN_SCOPE_PRESENT_EXACT, ABSENT_FROM_CORPUS, OUT_OF_SCOPE, VERSION_CONFLICT
  и MEMBERSHIP_UNKNOWN. Только первая группа образует denominator.
  В numerator входят exact versions, найденные в объявленной границе: @10
  либо COMPLETE_TRAVERSAL; названия различаются. Отсутствие доказывается полным
  corpus manifest, не top-100. Corpus loss, фильтровое исключение и retrieval
  miss раскрываются отдельно. Denominator 0 → null; неполный traversal не
  даёт completed recall. Другой SHA/версия того же номера не является hit.
  Membership вычисляется или проверяется по corpus/scope, а не выбирается label
  author: OUT_OF_SCOPE не может исключить запись, явно eligible в этом case.
  Review binding включает tenant, case и membership; противоречие остаётся
  UNKNOWN/отказом. Неуспешная первая страница даёт null/UNKNOWN recall и miss
  count, а не измеренный retrieval miss. При ошибке continuation допустима
  валидная диагностика @10 первой страницы, но complete recall остаётся UNKNOWN.

Отчёт показывает каждый case/repeat, а не выбирает лучший результат. Для
основного suite summary — macro mean по заранее заданным cases с равными
весами; complete repeated measurements усредняются внутри case. UNKNOWN,
ошибки, unsupported и zero-denominator перечисляются с counts: отсутствие
обязательного измерения запрещает общий PASS, measured-subset mean явно
диагностический. Reference recall aggregate дополнительно показывает сумму
hit/eligible без смешивания законов, scope или retrieval boundary.
Цели 5 s / 0.90 / 0.95 — proposed targets из программы; метод фиксирует,
к какому summary относится порог. Это не полученные показатели и не SLA.

## Независимая разметка и acceptance M2a

Инструмент не генерирует положительные labels из match score или своего top-10.
Набор reference candidates фиксируется до оценки: источник/метод отбора,
известные positives вне выдачи и отрицательные контрпримеры описаны явно.
Независимый reviewer, отличный от instrument/label author, проверяет точную
версию сохранённых bytes, locator и intent; одной строки имени недостаточно
для факта независимости — сохраняется review artifact с проверяемым provenance.
Конфликты сохраняются UNKNOWN; новый corpus/XML/intent требует нового binding
и review, а не переноса старого verdict. Relevance не является technical PASS,
действующим КП или разрешением PARTICIPATE.

Acceptance инструмента: synthetic end-to-end пакет → воспроизводимые JSON и
Markdown, повторный offline расчёт без сети/БД, все входные hashes проверены;
legacy v1 tests и результаты не изменены. Обязательные негативные случаи:

1. 19 быстрых успехов + 2 длинных timeout: p95 включает timeout; all-error и
   пустой набор; пропущенная запланированная попытка не скрывается.
2. Empty + reviewed positive → 0; empty без positive → null; partial labels,
   дубли и конфликт версий/вердиктов не увеличивают precision/recall.
3. Relevant absent from corpus — coverage loss; present exact but not retrieved
   — retrieval miss; wrong tenant/law/scope/date/XML/version не даёт hit.
4. Tampered bytes/locator, path escape, self-review, provisional label, missing
   consistency proof, row cap/partial manifest → отказ или явный UNKNOWN.
5. Continuation после 100, повтор/потеря страницы, clock/fingerprint drift,
   expired cursor, unsupported filter и ошибочный response не дают полный PASS.

Sol — один владелец реализации, только новые файлы:
`src/procurement/sources/eis_search_benchmark_v2.py`,
`scripts/eis-search-benchmark-v2.py`,
`scripts/benchmarks/eis-query-suite.v2.json`,
`tests/test_eis_search_benchmark_v2.py` (модуль и CLI).
Рабочее дерево: `C:/Users/elkgo/.codex/worktrees/quality-release/vibe-seller`,
ветка `codex/m2-search-benchmark` от `9dbc82b`; старт после acceptance root.
Synthetic fixtures создаются тестами; реальные данные остаются ignored/tenant-scoped.
Проверки: новые и legacy benchmark tests, scoped Ruff/mypy, docs check;
root назначает более широкий gate перед выпуском. Astra независимо ревьюирует
готовый slice. Root владеет README/live и назначает M2b только после acceptance.
Без реального frozen capture и независимых labels M2 остаётся IN PROGRESS,
quality/target acceptance — UNKNOWN; полный охват ЕИС не заявляется.

## Локальная приёмка M2a, 2026-10-07

Root принял только offline-инструмент v3 после независимого review Astra и
сверки Luna. Независимо выполнены 38 новых/legacy tests и 20 synthetic probe
cases; scoped Ruff/mypy и diff check PASS. Первоначальные шесть отказов и два
последующих случая denominator/continuation исправлены. Missing/failed page
не даёт complete recall; конфликт membership/verdict и stale version оставляют
recall UNKNOWN. Oversized manifest отклоняется до чтения; REAL_FROZEN acceptance
всегда UNKNOWN до доверенной проверки M2b. Это не deployment и не реальный baseline.

| Замороженный файл | SHA-256 |
|---|---|
| `sources/eis_search_benchmark_v2.py` | `e6eab93210f3b2bf73e6321369f01a317d4206caa0299e3fe79a955a1198055c` |
| `scripts/eis-search-benchmark-v2.py` | `aecda6c18d3dbca0c587aa9b8f49a8d50f97d10993633a8db8550449d7ae0890` |
| `scripts/benchmarks/eis-query-suite.v2.json` | `1dece7ff234deeee010d8bbde7272d5a076775e05420a153a9dbbbb3cebad89e` |
| `tests/test_eis_search_benchmark_v2.py` | `059aebbb40c6ceb477589bbc1242f4e7348fd3b1a2a1802c20a94b2fdbb0cf6d` |

Evidence (ignored): `tmp/improvement-program/m2/independent-instrument-review-v3.json`,
SHA `cef2e27818be09ac81194453da9dabe2e2be3b73ba8a32c25cb7edfc1c2ef37a`;
`oracle-comparison-v3.json`, SHA
`9ef0f01894c1f910a60111af4b3b1017ca470a5a1dc0dc954bc1c6a12370f128`.
Нормативная rev2 этого контракта до записи результата: SHA
`c2de82965fd1efb5de17e10813ff4e21a70dd965ad569fceb284ed6f5184bab9`,
сохранена как `tmp/improvement-program/m2/contract-116-rev2-preserved.md`.
Отклонённые implementation/review/probe v1/v2 сохранены рядом, не заменены v3.
Следующий срез — [durable capture M2b](117-eis-frozen-benchmark-capture.md).
