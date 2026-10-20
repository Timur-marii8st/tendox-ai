# Эффективность архитектуры ЕИС: аудит S166

Дата: 2026-10-03. Владелец: Astra (`architecture_review`). Owned file: только
этот документ. Зависимости: PRD 3.1–3.5, docs/26/32/33/37, результаты S160–S165
и предлагаемый S166A. Acceptance: проверяемые узкие места, границы измерений,
последовательные срезы для свежего поиска и реальной экономики. Код, production
данные, расписания и сетевой intake в рамках аудита не изменялись.

## Вывод

Существующая архитектура соответствует задаче: официальный импорт на VPS,
локальный индекс, быстрая выдача сохранённых данных, документы выбранных
кандидатов по очереди, отдельные детерминированные проверки. Переписывание
стека сейчас не обосновано. Наиболее полезны устранение ложного вытеснения
backfill, измерение реального свежего scope и завершение одного пути от
релевантного лота до проверенного КП и трёх сценариев. Рост числа XML сам по
себе не закрывает эти три задачи.

## Что подтверждено и что остаётся неизвестным

| Утверждение | Evidence и граница |
|---|---|
| Индекс уже содержит значимый объём 44-ФЗ | Переданный root снимок S166: 94 486 текущих карточек, 3 618 окон, 147 349 плановых окон. Это входные данные координации, не независимо повторённое измерение этого аудита. Окна разных типов/дней не образуют знаменатель числа публичных закупок. |
| 223-ФЗ пока узкий scope | Переданный root снимок: 73 current; docs/37 S154: регион 50, today/yesterday, AESMBO/ZKESMBO. Это два семейства МСП, не все 223-ФЗ. |
| Смешанное сравнение быстро на выбранных данных | docs/15 S163: 0,306627 с, повтор 0,087947 с для трёх строк; `eis_mixed_comparison.py:39` ограничивает выборку 2–3 карточками. Это не benchmark полного поиска. |
| Очередь документов даёт полезный результат | docs/15 S161: четыре перечисленных файла одного 44-ФЗ получены за 333,453342 с; первое получение 5,351735 с. Размер выборки один, SLA и системный throughput UNKNOWN. |
| Предварительная экономика работает | `eis_source_estimate.py:62–68` явно сохраняет PRELIMINARY и UNKNOWN для КП, требований, full cost review, eligibility и profit order. S164 использовал синтетические затраты; реальная прибыль не подтверждена. |
| Поиск 223 ограничен по памяти | `eis_223_index.py:50–51,425–475`: snapshot, keyset batches 200, глобальные 100 лидеров, полный обход SQL-prefiltered кандидатов. S165 доказывает сохранение результата; latency на миллионах неизвестна. |

Документированные measurements — исторические evidence из docs/15/37;
данный аудит не обновляет их время и не выдаёт их за текущий мониторинг.
Полнота публичной ЕИС, доля найденных релевантных лотов и свежесть всех регионов
остаются UNKNOWN. Количество planned targets нельзя показывать как loaded scope.

## Узкие места и review S166A

1. **Ложное вытеснение corpus.** До S166A `server-eis-priority.sh:16–18`
   создаёт marker до определения due work; `eis_corpus.py:279–281` завершает
   проход, увидев marker. Само наличие cron поэтому не доказывает полезную
   freshness работу. Read-only probe перед marker — правильное исправление.
   Общий source lock и завершение текущего атомарного окна сохраняются.

2. **Probe нельзя реализовать вызовом старого eligible.** До S166A
   `eis_freshness.py:151–152` планирует targets, затем читает попытки.
   При выделении общей функции чтения отсутствующая строка target должна
   означать unattempted/due, а не IDLE и не KeyError. Порядок должен остаться
   RECENT_HOUR → RECONCILE_DAY → EARLIER_HOUR, затем oldest attempted_at;
   равные timestamps сохраняют порядок `scope.targets()`, включая newest
   unattempted hour first. Runtime может планировать под lock и повторно
   проверять due; probe READY — только подсказка, не lease и не разрешение HTTP.

3. **Мониторинг свежести не принимает текущее число типов.**
   `eis_freshness_status.py:104` ограничивает `document_types <= 4`, тогда как
   `eis_feed_archive.py:29–34` содержит пять поддержанных типов, а CLI
   `eis_corpus_cli.py:116–122` использует их по умолчанию. Вызов default
   fresh-status до исправления заканчивается `CAPACITY_SCOPE_INVALID`.
   Нужен отдельный минимальный срез с регрессией default scope; capacity formula
   должна принимать актуальный контракт типов, сохраняя проверку недопустимого
   значения. Это дефект диагностики, а не доказательство остановленного импорта.

4. **Повторный старт browser в corpus.** `eis_corpus.py:294` вызывает
   `sync_eis_window_via_browser` на каждое окно; `eis_feed_sync.py:449` открывает
   новый transport, `_BrowserSession._ready():367–377` запускает Chromium и
   читает WSDL. Уже есть reusable `eis_browser_transport():403`. Следующий
   performance slice может использовать один transport на bounded corpus pass.
   Выигрыш требует before/after измерения; постоянный браузер без ограничения
   lifetime/RSS и повышение конкурентности из этого вывода не следуют.

5. **Низкая память не равна постоянному времени поиска.**
   `eis_223_index.py:441–474` читает и валидирует все совпадения prefilter,
   включая широкие запросы. До нового индекса нужны measured EXPLAIN и
   benchmark по числу evaluated кандидатов, p95, RSS и актуальности snapshot.
   Урезать обход первыми 100 нельзя: потеряются поздние лучшие кандидаты.

6. **Разрыв между discovery и доходностью.** PRD 3.2–3.5 требует полный состав
   требований, действительное КП, логистику/налоги/финансирование и hard gates.
   Текущий estimate принимает ручные costs (`eis_source_estimate.py:40,147`),
   но не доказывает их полноту или рыночную действительность. Следующий продуктовый
   результат должен соединить уже существующие domain gates с exact-version
   лотом и supplier evidence. Дополнительная сортировка НМЦК это не закрывает.

Номера строк фиксируют прочитанный код до/во время S166; после правок root они
могут сместиться. Finding 1–2 — review исходного поведения и acceptance S166A,
не утверждение о дефекте в окончательной реализации.

### Обязательные проверки proposed probe

- Нет targets/все not due → IDLE без plan, audit, HTTP, marker и import lock.
- Нет строки target/нет attempt → READY; foreign tenant не влияет на результат.
- Равные timestamps, смешанные lanes, failed cooldown и boundary времени
  дают тот же порядок, что runtime eligible до изменения.
- DB failure/некорректный CLI scope → BLOCKED, никаких marker/HTTP.
- Повторная проверка под lock сохраняет quota/resource/lease gates;
  между probe и runtime другой worker может забрать работу.
- Shell освобождает только принадлежащий ему marker; overlap/timeout не
  оставляют ложный приоритет. Live idle proof сравнивает counts до/после и
  показывает продолжение corpus, а не только exit code probe.

## Рекомендуемые следующие срезы

Порядок последовательный; перед каждым root назначает owner и конкретные
owned files. Таблица задаёт acceptance, а не выдаёт разрешение на deploy.

| Приоритет | Срез | Критерий результата |
|---|---|---|
| 1 | Завершить S166A и исправить status capacity | Idle не вытесняет corpus, missing due учитываются, проверки tenant/no writes/order; default five-type status возвращает диагностику. Живое evidence отдельно от unit tests. |
| 2 | Измерить полезную скорость и starvation | Несколько дневных/ночных интервалов: attempted/SYNCED/NO_DATA/errors, новые версии/час, oldest due, per-scope lag, lock wait, доля времени freshness/documents/backfill, RSS/DB growth. Не объединять пустые окна с XML throughput. |
| 3 | Reuse transport corpus | Один bounded transport/pass, одинаковые окна/исходы и error semantics, p50/p95 по окну и RSS до/после, quota и atomic boundaries без изменений. |
| 4 | Свежий широкий metadata scope | Явная матрица закон × семейство × регион × период; расширять по одному подтверждённому семейству/региональному scope после capacity measurement. Успешные повторные окна и сверка расхождений; gap/UNKNOWN виден пользователю. |
| 5 | Один реальный end-to-end supplier case | На 2–3 релевантных лотах: полный перечисленный manifest, reviewed требования, точный действительный КП, доставка/налоги/все затраты и три сценария; обновление XML/КП инвалидирует прежнее решение. Без этих данных результат NEEDS_ANALYSIS. |
| 6 | Recall/latency поисков поставщика | Размеченные запросы и синонимы, позиции/имена файлов/native ТЗ, distinct найденные закупки, пропущенные релевантные лоты, p95/RSS; evidence объясняет матч. Optional provider только после подтверждения условий и измерения дополнительного recall. |
| 7 | Историческая конкуренция | Отдельный официальный contract для протоколов/контрактов; сравнимые товары/условия, provenance и uncertainty. История не доказывает участников текущей подачи. |

Срезы 4–6 следует ограничивать полезным supplier scope. Они важнее бессрочного
наращивания истории; historical backfill продолжает использовать свободный
бюджет. Решение о расширении выбирается по missing relevant lots и freshness,
а не по одному абсолютному числу сохранённых записей.

## Ресурсы и неизменяемые границы

Тяжёлые данные, PostgreSQL, Chromium, parsing и очереди остаются на VPS.
`docker-compose.server.yml:4,36,53,63–64` ограничивает DB 2 GiB, API 1 GiB,
web 768 MiB и worker 2 GiB/2 CPU. Это конфигурационные лимиты, не измеренный RSS.
На ноутбук достаточно компактных отчётов, diffs и выбранных previews; копирование
корпуса не нужно. `eis_corpus.py:251–261` сохраняет DB/disk reserve gate.

Reuse и ускорение не ослабляют ZIP/XML bounds, официальный rate budget, TLS,
tenant isolation или provenance. Read-only API использует repeatable read и
postgresql_readonly (`repository.py:1078–1094`); новые очереди и caches остаются
tenant-scoped. Деньги — Decimal, deadline timezone-aware; неизвестная timezone,
неполный manifest и неподтверждённое КП сохраняют UNKNOWN. Mandatory FAIL
блокирует кандидата. RFQ/подача и другие внешние действия требуют exact-payload
approval. Полный corpus не является условием, позволяющим обойти эти gates.

Аудит проверен чтением исходников и сопоставлением с PRD/зафиксированными
результатами. Новые source requests, production writes, benchmarks и тесты
приложения в этой read-only задаче не выполнялись.

## Review реализации S166 перед deploy

Повторно прочитаны actual files `eis_freshness.py`,
`eis_freshness_dispatch_cli.py`, `eis_freshness_requests.py`,
`server-eis-priority.sh`, новые probe/PG тесты и metadata parser/test changes.
Production blocker в прочитанной реализации не обнаружен; результаты
запуска проверок и live proof остаются ответственностью root.

`read_due_freshness` читает последние попытки напрямую с tenant predicate,
DISTINCT ON и прежним tie-breaker по attempt_id. Отсутствующие targets получают
unattempted/due; stable lane/attempt ordering сохранён. `plan=False` foreground
probe использует read-only snapshot и не вызывает plan. Default cron проверяет
probe до marker; explicit args/smoke намеренно обходят default-scope probe,
поэтому обещание отсутствия idle preemption относится к штатному cron.

Выявлен P2 в новой PG регрессии: `datetime.now(UTC)` вместе с безусловным
`first[0].lane == "RECENT_HOUR"` делает тест зависимым от времени суток.
В 00:00–02:04 по Москве `scope.targets()` корректно возвращает только completed
day reconciliation. Рекомендовано сверять lane с фактической scope либо
использовать согласованный фиксированный clock. Существующий новый тест
проверяет одинаковый результат для unattempted scope; отдельная регрессия
persisted mixed lanes/равных timestamps усилит проверку сохранённого порядка.

Metadata contract Sol сохраняет все references до 4096 включительно и
атомарно отклоняет 4097 с отдельной причиной. Это допустимо без новой схемы:
тихого усечения нет, ZIP/XML/UID/URL gates сохранены. Тесты покрывают 101,
4096, 4097 и duplicate UID после старой границы. Отдельный download gate
`eis_document_store.py:38,383` остаётся 32 файла: успешная индексация большого
manifest не означает возможность скачать весь комплект штатным worker.
Фактическое число вложений отвергнутых live окон UNKNOWN (docs/43);
подтверждение устранения конкретного source отказа требует последующего
разрешённого runtime evidence, а не только успешного synthetic parser test.

### Повторный review S166B/C и ближайшая metadata задача

Root исправил зависимую от времени PG assertion: теперь ожидаемый lane
выводится из доступных scope targets. Добавлены regressions порядка/cooldown
и shell boundary. S166B заменяет устаревший предел capacity на
`len(SUPPORTED_NOTICE_TYPES)`; тест использует действительный default scope и
отклоняет excess count. Блокирующих замечаний к этому изменению нет.

Прочитанный S166C передаёт один lazy transport из `_corpus_pass` в
`run_corpus`; pre-window resource/priority gates, source failure stop, spacing
и обработка атомарных окон сохранены. `sync_eis_window` самостоятельно
проверяет ingested checkpoint до сети, как и прежний wrapper. Context manager
закрывает транспорт при выходе/ошибке; tests проверяют reuse, fail-fast,
pre-window gates и cleanup. Производительность/RSS требуют отдельного live
измерения; code review не обнаружил blocker.

**Ближайший bounded metadata slice: свежие исправленные пропуски.**
В `eis_corpus.py:206–246` глобальная очередь ставит все unattempted окна
(`last_attempt ASC NULLS FIRST`) перед любыми повторными попытками. При
длинной исторической очереди это откладывает повтор свежих окон, ранее
отклонённых уже исправленным parser. Newest-first применяется только после
разделения по attempted/unattempted и не решает эту проблему.

Предлагаемый следующий owner — Sol; prospective owned files:
`sources/eis_corpus.py`, `tests/test_eis_corpus.py`, профильная PG регрессия;
операционный proof и live status принадлежат root. Зависимость — завершённые
A/B/C и read-only разрез latest attempts. Реализация одного policy slice:
малый ограниченный слот повторов свежих FAILED окон за последние 3–7
завершённых дней, затем существующая очередь; единый max_windows, дедупликация
ключей, текущий 24h retry interval. Размер share и точный период выбрать из
измеренного backlog; не повышать source cadence и concurrency.

Acceptance: свежий due failure получает шанс при большом unattempted history,
но не вытесняет весь backfill; свежий unattempted также продвигается.
Completed checkpoints и ещё не due failures не запрашиваются, окна другого
tenant исключены, одинаковые исходные данные дают стабильный порядок.
Local metadata limits остаются видимыми failures, не NO_DATA/PASS. Сравнить
полезные новые XML/час и закрытые свежие gaps, а не только число попыток.
Для S166 metadata-fixed окон отдельно подтвердить реальную повторную попытку:
действующая freshness reconciliation может закрыть их раньше corpus только
если окно входит в её конкретный region/day/type scope.

### Review S167 fairness selector

Прочитаны новый selector, `test_eis_corpus_fairness_pg.py`, corpus tests и
docs/45. Контракт `min(ceil(limit/5),12)` реализован корректно: reserved lane
выбирает latest FAILED за семь завершённых московских дней и только после 24h;
historical lane вычитает фактически выбранное число, исключает reserved keys,
сохраняет прежний порядок и заполняет остаток общего limit. Все ветви имеют
tenant predicates, planned join и checkpoint exclusions; один SQL исполняется
в consistent read. Фильтр даты до ranking безопасен для latest semantics,
поскольку дата является частью ключа и одинакова для всех попыток этого окна.
Future attempted_at не проходит cooldown. Без найденного функционального
blocker; корректность требует успешной PG проверки root.

Есть конкретный performance risk для проверки перед deploy: historical
`ORDER BY ... LIMIT` заменён на `ROW_NUMBER() OVER (...)` с фильтром position
снаружи. Семантика та же, но план может потребовать сортировку всех eligible
строк и WindowAgg вместо прежней top-N сортировки. При текущей длинной очереди
нужно сравнить старый/новый read-only EXPLAIN ANALYZE под statement timeout:
execution time, rows, temp blocks/spill, buffer reads. Это гипотеза о плане,
а не измеренная регрессия; при приемлемом результате дальнейший refactor
не нужен. При существенной регрессии ограничивать каждую упорядоченную lane
через SQL LIMIT до финального union, сохраняя тот же порядок и dedup.

Текущий synthetic PG fixture покрывает насыщенный reserve, cap12, limit1,
read-only/tenant/checkpoint/cooldown и latest-not-failed. Повтор одного запроса
не проверяет tie-break по одинаковому timestamp (в fixture времена различны).
Рекомендованы дополнительные bounded cases: одинаковый attempted_at с разными
attempt_id/outcome, Moscow midnight/граница семи дней, пустой или недозаполненный
reserve с заполнением old lane. Эти случаи и cost evidence отделяются от уже
проверенного чтением SQL.

Final review S167: Sol устранил указанный plan-shape риск —
`historical_queue_limited` применяет прежний ORDER BY и динамический LIMIT
до ROW_NUMBER; window function теперь получает не больше общего limit.
Порядок NULLS FIRST, заполнение остатка и dedup сохранены. Дополнительная PG
регрессия покрывает zero/insufficient reserve, равные времена разных ключей
с обратным порядком insertion, московскую полночь и включительную нижнюю
границу семи дней. Блокирующих замечаний к финальной форме нет; дальнейшее
расширение тестов не требуется. Root выполняет итоговые PG gates и ограниченный
live old/new timing/count proof; этот review не подменяет их результаты.

### Review S168 grouped latest attempts

Прочитаны selector, расширенная isolated PG регрессия и docs/46. Замена
correlated MAX на tenant-filtered GROUP BY window_key + LEFT JOIN сохраняет
семантику: обе формы находят максимальный attempted_at той же компании и
того же окна. Поле attempted_at NOT NULL, поэтому NULL joined latest_at
по-прежнему означает unattempted. Future latest исключается cooldown,
due NO_DATA остаётся в historical lane, чужой tenant с тем же ключом не влияет.
Порядок, checkpoint exclusions, recent FAILED ranking, bounded fill/dedup и
один consistent snapshot не изменены. Блокирующих замечаний нет.

Новые PG assertions проверяют future latest, foreign-tenant same key и полный
eligible набор из 157 записей fixture. Дополнительных тестов review не требует.
Root выполняет fixed-clock before/after exact-result comparison и измерение
времени под timeout/operational locks. Заявление об ускорении допустимо только
после этих измерений; изменение SQL само по себе его не подтверждает.
