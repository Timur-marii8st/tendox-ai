# ЕИС: диагностика NO_DATA и готовность коммерческого API

Проверено 2026-10-19, 01:05 МСК. Владелец: root, один агент.
Статус: ограниченное исправление диагностики CHECKED; коммерческий API NOT READY.
Контракт источника — [ADR0044](../adr/0044-eis-source-contract.md), retention —
[S198](../eis/ingestion/81-eis-no-data-raw-evidence.md), эксплуатация —
[S199](82-eis-no-data-store-operations.md). Требования продукта —
[PRD](../product/11-product-requirements.md), текущие границы —
[live-план](../15-implementation-plan.md).

## Проверенный результат текущего среза

Owned files: `scripts/server-eis-no-data-store-report.py`,
`tests/test_eis_no_data_store_report.py`, этот отчёт и связанные индексы/live-план.
Зависимости: установленный журнал попыток, audit и immutable SQLite store.
Acceptance: отчёт завершается на текущем объёме; точное сопоставление
tenant/window/actor/SHA/time сохранено; дубли audit не умножают попытки;
диагностика source-free и READ ONLY, нехватка evidence не становится PASS.

Коррелированный EXISTS повторно читал audit для каждой попытки. На рабочем
объёме именно пятый SQL-запрос завершился timeout 30.002s, SQLSTATE57014;
предыдущие запросы занимали 0.002–0.034s. Вместо него используется один
агрегат earliest capture по window/actor/SHA и LEFT JOIN к попыткам.
Предикаты tenant, периода, payload identity и времени сохранены.
Исправленный read-only запуск получил полный результат за1.094s.
Это диагностическое сравнение, не нагрузочный benchmark или SLA.

Stdout теперь также содержит причины отказов, число NO_DATA attempts и
audit_completeness. Успешное совпадение audit с отказом сохранения не означает
успешное сохранение тела. Store PASS означает только согласованность metadata.

Проверки: 18 тестов PASS без skips на отдельном PostgreSQL18, в том числе
2000 разных ответов/4000 capture events, duplicate/foreign tenant/wrong actor/
late capture guards. Смежный Windows-набор:81PASS/5explicit skips
(PostgreSQL opt-in и symlink permissions); отдельно PG-тест пройден в группе18.
Ruff check/format, targeted mypy и docs check PASS. PostgreSQL18 cluster остановлен;
временные файлы оставлены.
Исправленный запрос дополнительно выполнен на рабочем PostgreSQL в READ ONLY.
Полный release gate и постоянная установка NOT_PERFORMED.

## Что означает текущий NO_DATA

Парсер `eis_feed.py` выдаёт NO_DATA только для единственной явной ветви
`noData=true|1`. Ошибки сервиса и невалидный XML не становятся NO_DATA.
Это наблюдение одного region/type/date/hour, а не отсутствие закупок в ЕИС.
На трёх сохранённых ответах повторно проверены raw/hash/parser/journal:3/3PASS.
Они предшествуют исчерпанию квоты и не подтверждают все последующие ответы.

В журналах за18Oct00:00UTC→около22:00UTC:44-ФЗ2253 новых редакции/69событий,
223-ФЗ41новая редакция. Это суммы инкрементальных результатов, не число
уникальных закупок и не весь национальный поток.
78 failed attempts44 относятся к11 разным windows:8duplicate-version,
1attachment-reference,2archive-expansion-limit. NO_DATA от них отделён.

Реальный blocker retention: SQLite достиг134217728/134217728bytes,
57976records, payload74844429bytes. Последний сохранённый ответ —
16Oct03:44:20UTC. В snapshot18Oct22:05:45UTC за период с18Oct00:00UTC:
11041FAILED, все QUOTA_REACHED, RETAINED0; соответствующий capture audit есть
для каждой попытки. Raw тела этих отказов данным store не сохранены.
Удаление/вытеснение evidence и увеличение лимита не выполнялись.

Fresh-status01:04МСК в scope90regions×5families×3completed days:
1350date targets,277unattempted/due,721latestNO_DATA,1latestFAIL.
Это снимок очереди, не доказательство пропуска всех277: новые дневные окна
появились после полуночи. Устойчивый lag/throughput ещё не подтверждён.
Старую capacity-модель full hourly polling нельзя использовать как точный
расчёт текущего checkpointed/mandatory-only scheduler с иным pacing.

## Последовательные условия готовности

| Результат | Что требуется для закрытия | Сейчас |
|---|---|---|
| Доказуемые ответы источника | Восстановить сохранение, обеспечить чтение старых audit references, проверить квоты и полный цикл после переключения | FAIL: store full; архивирование/rotation отсутствует |
| Объявленный охват ЕИС | Зафиксировать регионы/families/даты; разобрать11окон; сверить известные закупки и текущие редакции; завершить Татарстан | INCOMPLETE |
| Свежесть | Измерить arrival/terminal throughput и source→search lag на том же scope минимум за полный суточный цикл; очередь не растёт | UNKNOWN |
| Качество поиска | Зафиксированные запросы/эталоны, независимая разметка, recall/precision и latency/error report; пропуски явно видны | M2 не принят |
| Коммерческий API | Версионированный публичный контракт, per-client auth/tenant isolation, quotas/usage, ошибки и continuation; измеренный SLO и pilot acceptance | Полная готовность не подтверждена |
| Эксплуатация | Воспроизводимый выпуск/rollback, restore drill, capacity/retention alerts и проверенные действия оператора | Отдельные механизмы есть; общий acceptance не закрыт |
| Поиск выгодного снабжения | Реальные требования → подтверждённые поставщики/изготовитель → полное действующее КП → партия/налоги/доставка → три сценария | Сквозной кейс не подтверждён |

API сохранённого корпуса можно выпускать отдельным продуктом раньше полного
тендерного отдела, но только после проверки собственного ограниченного
контракта. Готовность manufacturer/RFQ не заменяет готовность data API и наоборот.

Одно следующее действие: реализовать и проверить bounded immutable archive/
rotation с разрешением старых audit references, затем подготовить точный payload
выпуска и переключения. Увеличение квоты без lifecycle не закрывает этот blocker.
Внешнее изменение требует exact-payload approval по AGENTS; текущий read-only
диагностический запуск не является таким изменением.

## Evidence

Локальный каталог: `tmp/eis-no-data-diagnostic-20261019-v1/`.
В нём сохранены исходный установленный report и stdout нового запуска.
SHA256 исправленного script:
`10e60461a90cdd56ca295600cded3a8037d45654797d4be83ca9d4089a1374ec`.
Production diagnostic proof:
`/var/lib/eis-browser/research/rejected/s199-store-health-db40a5dd-2588-4ad1-8e1b-33fc0b48de92.json`,
SHA256 `98217336aa1aaeb516e934fe376e85f0da24e834c3a46fd40d5b7fa184f24c9c`.
Raw replay proof:
`s198-offline-replies-cbf01428-cd91-414a-91b1-6a892fe4aef6.json`,
SHA256 `f6fcbf98115d8a5eed9da600d4acf21f4c211cb5198f6aa1cb09ec4ec98f6677`.
Source requests0/database writes0 для этих диагностик; штатный cron продолжался.
