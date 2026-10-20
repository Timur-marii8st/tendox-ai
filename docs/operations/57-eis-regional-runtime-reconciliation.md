# S174: сверка регионального runtime

2026-10-03,20:14–20:16UTC. Владелец: acquisition_research.
Read-only SSH и PostgreSQL; без EIS/source requests, runtime/DB mutations.
Сохранение небольших research proofs на VPS — единственная запись артефактов.
База измерения — docs56/S173. Все счётчики относятся к
`local-eis-supplier`, кроме явно отмеченного размера всей БД.

## Текущая волна

Снимок20:16:09.475519UTC. Wave `735f19c4-7fce-4f2a-b5a4-b596ae07c501`,
90PUBLIC_KLADR_SELECTOR codes,5families,даты02–03.10,900planned windows.
Каталог проверен19:28:12.761590UTC,statusACCEPTED; SHA unchanged
`b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`.

| Метрика | S17319:16:20 | S17420:16:09 |
| --- | ---: | ---: |
| Attempted/terminal |140|233|
| SYNCED |48|74|
| NO_DATA |92|159|
| Failed latest |0|0|
| Unattempted |760|667|
| Due |763|667|
| Regions attempted |67|90|
| Regions terminal по всем10окнам |1|1|

First sweep finished=false,scopePARTIAL,old gaps0,watermarknull.
Coverage/freshness UNKNOWN; все90затронуты ≠ полный обход.
Рост93distinct terminal keys за59m49s — наблюдённая дельта смешанных запусков,
не чистый cron throughput и не прогноз устойчивой производительности.

| Семейство | SYNCED | NO_DATA | Не проверено | Всего |
| --- | ---: | ---: | ---: | ---: |
| purchaseNoticeAESMBO |58|122|0|180|
| purchaseNoticeZKESMBO |15|32|133|180|
| purchaseNotice |1|1|178|180|
| purchaseRejection |0|2|178|180|
| purchaseLotCancellation |0|2|178|180|

AESMBO прошёл все окна этой волны, но это не доказательство текущей полноты
извещений или актуального статуса закупок. Общие извещения и события отмены
почти полностью ждут очереди. Группировка всех223attempt journals по
nonterminal status/reason дала0строк, не только0latestfailed.

## Cron после S173

Снимок log20:16:35UTC:71JSONстрока против67 в сохранённом S173.
Четыре добавленные строки в порядке файла:

| Событие | Окон | Seconds | Source posts | Archive GETs |
| --- | ---: | ---: | ---: | ---: |
| Завершённый проход |32|187.658668|39|7|
| SERVER_IMPORT_BUSY |0|не записано|0|0|
| SERVER_IMPORT_BUSY |0|не записано|0|0|
| Завершённый проход |32|253.704965|43|11|

В успешных строках budget_overrun_seconds=0. Всего64окна за441.36s
активных проходов,среднее220.68s/run. Записей с точным временем начала нет:
не приписывать этим четырём строкам конкретные cron slots. Историческая
Permission denied строка осталась1, новых таких строк нет.
Текущий crontab подтверждён: `1,11,21,31,41,51 * * * *`.
Номинальный максимум192windows/hour предполагает все6успешных запусков;
наблюдаемые lock skips показывают, почему это не гарантированный темп.

## 44-ФЗ продолжает работу

Tenant snapshot:4527feed windows,121797notice versions,11190sync attempts.
Исторические outcomes:4516SYNCED,6414NO_DATA,232FAILED,3SERVICE_ERROR,
25SKIPPED. Это attempts, не232текущих непоправленных окон.
Последние timestamps:SYNCED20:15:42.852344UTC,NO_DATA20:16:05.697UTC,
FAILED20:01:09.785036UTC,SERVICE_ERROR15:31:26.016286UTC.
Сосуществование активного44loader и lock skips223 соответствует contention
общего lease; конкретный владелец каждого skip из данного log не доказан.

## SQL и хранение

API-container engine использовал DATABASE_URL без вывода, options
`default_transaction_read_only=on`, `statement_timeout=5000`, tenant
`storage.transaction(...,consistent_read=True)`. SELECT only.
Coverage52.183ms,scheduler12.837ms,с учётомPython/connection; все запросы
уложились в5s. В этой итерации EXPLAIN повторно не нужен: текущая цель —
runtime reconciliation, предыдущие bounded планы сохранены в docs56.

Вся БД2,963,577,879bytes. Крупнейшие relation sizes включают индексы/TOAST;
estimated_rows — PostgreSQL statistics, не точный count:

| Таблица | Bytes | Estimated rows |
| --- | ---: | ---: |
| eis_feed_archives |2078580736|4925|
| eis_notice_versions |535592960|121797|
| audit_events |121880576|164346|
| eis_223_blobs |70000640|83|
| eis_notice_search_keys |65978368|121797|
| eis_sync_targets |47210496|147544|
| eis_sync_attempts |5439488|11190|
| eis_document_analyses |4702208|138|
| eis_document_blobs |4661248|60|
| eis_feed_archive_sources |4161536|4921|

20:14:39UTC disk snapshot: source volume `/var/lib/eis-browser`135MiB,
почти всё research; discovery28KiB. Host `/home/syurai/vibe-seller-state`8.8GiB
включает прежние retained/backup artifacts, не только источники223.
Root FS335GiB,used62GiB,available259GiB,20%used. Основной сырой корпус сейчас
в PG eis_feed_archives(~2.08GB), поэтому один du browser volume не измеряет
весь источник. На этом снимке disk reserve не является узким местом.

## Практический следующий ограниченный срез

Измеренный риск — справедливость общей очереди и порядок семейств. SQL быстрый,
source requests не все занимают600s; простое увеличение maxwindows не объясняет
и не устраняет lock skips. Новый S173 scheduler уже резервирует fresh slot;
на текущем снимке fresh_due backlog отсутствует (due=unattempted), поэтому
прежнее утверждение docs56 о полном вытеснении fresh_due не переносится сюда.

Следующий bounded slice: измеримые lease-attempt/start/end/duration/owner-kind
счётчики и fairness между44/223, затем ограниченный canary сравнения семейного
round-robin с текущим family-first. Критерий — оба loader продолжают прогресс,
отмены/общие извещения не ждут полного прохода предыдущих семейств, лимиты
32/600s/source quota и UNKNOWN сохраняются. Менять scheduler без этих
счётчиков по одному моментальному snapshot преждевременно.
Оставшиеся667окна требуют минимум21успешного32-window run без retry;
10mincron даёт идеальные3.5часа slots, но lock skips/архивы/refresh делают
это только нижней арифметической оценкой, не6hSLA или ETA.

## Proofs

На VPS `/home/syurai/vibe-seller-state/` и в ignored локальном
`data/research/eis-documents-2026-10-02/`:

- `s174-measure.json`: PG/coverage/families/selected32/largest tables;
  SHA256 `a176e49208756ceb85699b9176de5a9badd395726e337cd2f63048a82fa6023c`;
- `s174-measure-log.json`: компактная сводка log delta и crontab;
  SHA256 `96cfc277b7ed54be0a5f85c21c541ac38134ca7b28e6fa5eeb71d8af3061be22`;
- local `s174-measure.py`: воспроизводимый read-only helper.

Исходный log78433bytes,SHA256
`17dda12528bb6632ba93f3b73810450919e0e7b15f3d622ef2262e9ced3c1359`.
Полные outcomes и DSN не копировались. Worker продолжал работу между
измерениями; значения привязаны ко времени. Whole-EIS, full sweep,6hSLA
и допустимость участия не утверждаются.
