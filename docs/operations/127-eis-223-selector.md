# Ускорение выбора партии 223-ФЗ

24.10.2026. Owner root. INSTALLED; bounded live SQL/intake/search PASS.
Проверка24Oct19:48MSK закрыла ранее ожидавшийся post-release intake.
Контракт: убрать SQL timeout выбора очереди, подтвердить штатный импорт и поиск;
порядок/RLS/SQL5s/source budgets/schema/cron сохраняются.
Owned: storage/eis_223_regions.py, tests/integration/test_eis_223_regions_pg.py,
этот отчёт, operations/README и live-план. Evidence:tmp/eis-223-selector-20261024-v39/.

## Диагноз и решение

Installed baseline SHA2b0a65fd:223probe падает до source access, SQLSTATE57014.
EXPLAIN фактического ошибочного statement: фильтры даты/семейства занижают scope
до1строки; nested-loop left join многократно читает materialized latest history.
Scope-only materialization не устранила timeout; эта попытка не выпускается.

Кандидат материализует полный join scope/latest до внешних фильтров. Формулы дат,
календарьMSK, приоритет retry/new/repeated/recovery, границыcooldown и ordering сохранены.
Каждая ветка исходных таблиц остаётся tenant-scoped; схема и индексы не меняются.
Production optimizer settings не меняются. Enable_nestloop=off использован только
в readonly транзакции как oracle исходного запроса, не как исправление.

## Проверки

Baseline probe:6.73s total, statement прерван5s. Readonly comparison v2 на одном
PGsnapshot:recovery/fresh/reconciliation/history/fresh-first, limits2/32 —10/10PASS,
exact ordered keys совпали. Candidate0.503–1.789s total, recovery0.518–0.545s.
Запросы не скачивают source и не изменяют business data. Это замер на текущем корпусе,
не гарантия latency при любом будущем размере. 8из10 сравнений пустые; семантика
retry/final-day debt дополнительно проверена четырьмя непустыми PG regression cases.
FocusedPG4PASS, units28PASS, adapter rollback9PASS, независимые SQL/adapter reviews PASS.

Первый fullgate остановлен для исправления фикстуры новых тестов: незавершённые
текущие окна корректно опережали старый долг. SQL не менялся. Четыре disposable
ресурса удалены по проверенным ownership labels; исходные результаты сохранены.
Fullgate v2 release-20261024-140255-40bbac96da12 PASS, complete=true,50/50stages.
Archive6a1bd5b9/tree5fd2acd3, policy2026-10-24.223-selector-v39-v2; все50stages сохранены.
Units3929PASS/27allowedSKIP, PG722PASS/0SKIP, doctests9PASS, web205PASS;
ruff/mypy/lint/build/API+WEB smoke PASS. Первая прерванная попытка не является receipt.

Контроль до установки24Oct14:05UTC:46883закупки223,54310редакций; после очистки
09:09UTC +36закупок/+38редакций. Три новые карточки32616504417/419/420 доступны
через HTTP global-price, XML SHA/navigation совпали, anonymous401. Эти записи
добавлены до исправления; они не доказывают post-release прирост. Fresh24Oct
следующий recheck не ранее15:36:54UTC (18:36:54MSK); IDLE до due допустим.

## Установленный результат

План ff62343cc822d57dfd9958fd2ceaea9cf42c217b34ef02ef7fee44ffd47ed446
установлен24Oct14:21:04UTC (17:21MSK), API/worker image
dd6e55b2732c585f9cdf2822402cec7904962d6a6ab5ad056091f4a52805b853.
Installed module SHA46affa94a5db5eeaf62651a5683390335c9289be90be157f35601438004b4165.
Schema20261023_01, WEBf4e6e60d, cron, leases, worker3GiB/3CPU, SQL5s и source budgets
сохранены. БД и WEB не перезапускались. Audit PREPARED/ACTIVATED tenant-scoped.
Новый worker включает восемь beta-модулей, уже установленных в B11API; ни один из
них не входит в проверенный граф импорта223/corpus. Единственная смена в этом
графе — SQLselector; evidence module-delta.json/worker-imports-before.json.

После установки readonly на реальной БД: recovery0.585s, fresh1.056s,
history1.845s/32targets; statement_timeout5000 сохранён. Штатный entrypoint
server-eis-223-refresh.sh завершился exit0, IDLE,0due,0source_requests в14:21:37UTC.
Это устранение SQL-отказа, но не доказательство нового скачивания.
Автоматический cron14:25:02UTC также IDLE0due без SQL-отказа. Независимый installed
review проверил remote receipt50/50, образы, module SHA, Compose/schema/cron и
сохранность DB/WEB: bounded PASS; post-release ingestion/growth UNKNOWN/PENDING.

HTTP global-price после установки:32616504417/32616504419/32616504420 —200,
XML SHA и navigation совпадают с БД, anonymous401;0.057–0.142s на этих трёх номерах.
Всего46883закупки223/54310редакций; после очистки+36/+38. Эти36 не приписываются
релизу V39. Corpus coverage и национальная полнота остаются UNKNOWN.

На момент установки post-release intake оставался PENDING; историческое evidence
сохранено в acceptance.json. Финальные docs обновлены после sealed archive и не
входят в его receipt; runtime source идентичен проверенному.

## Проверка запуска18:45MSK и последующих проходов

Owner root; read-only follow-up24Oct19:46–19:48MSK. Owned: этот отчёт, live-план,
task-local evidence; production код/cron/budgets не менялись. Acceptance: факт
штатного скачивания, новые уникальные номера и HTTP search с XML provenance.

Запуск18:45:01–18:47:26MSK обработал5окон, скачал1архив и добавил новую закупку
32616504474 («Поставка овса фуражного») в18:45:27MSK. Остальные исходы этого
прохода:3NO_DATA и1SOURCE_TRANSPORT_FAILED; следующие cron продолжили работу.

На19:47:49MSK:46896закупок223/54324редакции. После установки V39 добавилось
13уникальных закупок и14редакций; все13 проверены через HTTP global-price с law223,
HTTP200, совпадением XML SHA/navigation, anonymous401. В том числе7закупок
«бумага офисная»:32616504463–32616504469, загружены19:26:17MSK.
Каждая из13 новых карточек связана window_key/response_sha256 с SYNCED исходом
штатного cron. Это post-release evidence, прежние36закупок не включены в прирост.

Журнал до19:48:39MSK:7завершённых проходов18:45–19:45,238попыток окон,
21SYNCED/213NO_DATA/2FAILED/2SERVICE_ERROR;14new_versions совпадают с БД.
SQL error lines0, BLOCKED0 после первого post-release cron17:25MSK.
ДваFAILED: SOURCE_TRANSPORT_FAILED и SOURCE_RESPONSE_REJECTED; source failures
не закрыты этим SQLfix и остаются предметом штатных повторов. Резерв диска,
source pacing и cooldown не обходились. National coverage остаётся UNKNOWN.

Evidence:followup-acceptance.json, followup-all-search.json,
followup-first-run-db.json, followup-runs-final.json в task evidence directory.
Статус ограниченного исправления: PASS_BOUNDED_POST_RELEASE_223_INGESTION_AND_SEARCH.
Следующий отдельный срез — причины оставшихся source failures/производительность
очереди; полнота ЕИС этим наблюдением не доказана.
