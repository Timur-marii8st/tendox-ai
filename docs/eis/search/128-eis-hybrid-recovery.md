# Гибридное обнаружение и восстановление: первый срез

24.10.2026. Owner root. INSTALLED; live control run PASS в ограниченном scope.
Контракт — [ADR0116](../../adr/0116-eis-hybrid-discovery-recovery.md),
[PRD3.1](../../product/11-product-requirements.md),
[существующий intake](../ingestion/84-eis-public-candidate-recovery.md).

Owned: scripts/server-eis-hybrid-recovery.py/.sh,
tests/test_eis_hybrid_recovery.py, ADR0116, этот отчёт, README индексы и live-план.
Дополнительно tests/test_eis_223_regional_runner.py: исправление воспроизводимого
UTC/MSK дефекта синтетической фикстуры, найденного обязательным full gate.
Dependencies: installed S201 recovery, official public HTML/getDocsIP, shared
leases/joint budget, PostgreSQL tenant isolation, trusted release workflow.
Evidence: tmp/eis-hybrid-20261024-v37/.

Acceptance первого среза: обнаружение отсутствующего номера в официальной
активной выдаче → durable queue → полный stock intake → keyword search с ценой,
сроком и SHA. Проверка на реальных закупках сначала в disposable PostgreSQL;
синтетические tests отдельно проверяют ошибочные фильтры/URL, partial parsing,
crash recovery/backoff, неизменность attempts и отказ при чужом tenant/scope.
Production activation и автоматическое расписание не считаются выполненными
по наличию скрипта или isolated PASS.

CLI: `scripts/server-eis-hybrid-recovery.sh --query 'бумага' --max-pages 3` —
наблюдение; `--apply` включает обработку очереди. Не вызывать Python entry point
в обход wrapper/import lease. Первый поддержанный scope только44-ФЗ; регион
не ограничивается, historical publication cutoff отсутствует. Очередь по номеру,
а не по локальному совпадению заголовка. Точное время/состояние подтверждает XML,
HTML дата остаётся discovery hint.

Поддержанная схема запуска сохраняет текущие service images/schema/cron до
проверенного выпуска. Подготовленный пилот первого профиля — один проход каждые10мин до25Oct00UTC;
включение требует нового receipt-bound payload. Совместная нагрузка и национальная
свежесть этим документом не объявлены PASS. Состояние подготовки — в live-плане.

## Проверка на реальных источниках

Официальная выдача24Oct, запрос «бумага», PRICE↓/44/AF/deadlineFrom24Oct:
50карточек,0неразобранных. HTML SHA
`6ca6d1c133d2c2c6cbe03d60da84d912cd0f7fede6cc9546786939c771105020`.
Readonly snapshot437463:437463: от23Oct22:45:30UTC выявил3отсутствующих номера.
На этапе isolated replay entry point не исполнялся с production writes. Два полных SOAP/ZIP набора
получены неизменённым установленным source reader и повторно проиграны через
новую queue/drain и stock intake в network-none disposable PostgreSQL.
В replay привязаны исходные request UUID; HTML/XML/ZIP bytes не изменялись.

| Номер | Проверенный результат isolated API | Ограничение |
| --- | --- | --- |
| 0162100021826000052 | 1редакция,3 611 000.00RUB; HTTP200 по номеру и «ремонт» | По «бумага» совпадения нет; public search и наш lexical index имеют разный охват текста |
| 0373100103926000241 | 1редакция,4 220 224.14RUB; HTTP200 по номеру и «бумага» | Комплект вложений DOCUMENT_SET_RESOURCE_LIMIT; карточка индексирована, ТЗ UNKNOWN |
| 0153200000126000001 | UNSUPPORTED, без скачивания/ложного INDEXED | Особая процедура вне поддержанных ea20/zk20/ok20 |

У двух импортов сохранены response/archive/XML SHA, version, Decimal цена,
timezone-aware deadline и RECORDED audit. Повторный drain:0новых source calls.
Чужой tenant видит0versions/search/audit/jobs. Полнота national/corpus UNKNOWN.
Evidence:actual-replay-result.json,actual-http-search.json,actual-replay-outcomes.json
в указанной выше private папке; исходные реальные файлы в tests не включены.
Первый replay остановился на слишком широком ожидании PLANNED для всех вложений:
действующий stock limit корректно вернул UNKNOWN для второго комплекта.
Проверка уточнена до явного ожидания этого ограничения; admission не ослаблялся.

Проверки:38новых tests PASS; вместе с S201 в disposable PG62PASS/0skip.
Независимое повторное code review: подтверждённых блокеров нет; первые замечания
об immutable observation и восстановлении audit устранены с регрессиями.
На момент запечатывания исходников full gate был PENDING; итог ниже.
Production activation тогда NOT_INSTALLED; актуальный итог в последнем разделе.
Изолированный результат не доказывает работающий production cron.

Основной UI endpoint global-price также проверен в isolated DB с law=all:
«бумага»→0373100103926000241; «ремонт»→0162100021826000052, HTTP200.
Evidence:actual-global-price.json. Внешняя сеть в replay недоступна.

Gate v1 release-20261023-225833-55a5b10bc8a5 остановлен на старой synthetic
223 idle fixture:23Oct23UTC уже24OctMSK; фикстура ошибочно объявляла вчерашнюю
московскую волну актуальной. Runtime правильно возвращал READY. Исправлена только
фикстура: exact probe now + Moscow day;8исходных IDs/assertions сохранены,
добавлены2проверки до/после московской полуночи.10focusedPASS. Предыдущий
FAIL сохранён; новый полный gate обязателен, skip/expectations не ослабляются.


## Результат полного выпуска и подготовка активации

Full gate v2 `release-20261023-230750-91dbea1f75c7`:50/50этапов PASS.
Python3877PASS/27исходных разрешённыхSKIP; PostgreSQL717PASS/0SKIP;
doctest9PASS; web205PASS; lint/types/docs/build/smoke PASS.
Все3864исходных unit IDs сохранены, добавлены38hybrid и2UTC/MSK cases.
Receipt SHA `2bb97d16096d98fcebaede2963d4c1fe78bde4c877497634f856fc82d66000b5`;
source archive SHA `91754ac184af31fa55f81c778d1f4afbbf12a20d46c0d71d1c0ae742fed1a2f3`.
Независимый reviewer повторно проверил typed receipt и hashes отчётов.
Образы full gate не установлены: adapter сохраняет API/WEB/worker/schema.
88загруженных procurement modules существующего worker совпадают с candidate.
Evidence:fullgate-summary.json,release-receipt.json,worker-module-compat.json.

Закупка0373100103926000241 на4.22млн — мебель/оснащение, а не поставка бумаги:
совпадение по позиции «Лоток для бумаги пластиковый» (purchaseObject[7]/name).
Чистая бумага0122100003226000063 на3.23млн восстановлена ранее вручную
(отчёт127); это не результат новой автоматизации.

После отдельного разрешения пользователя удалены только остановленный test
pgdata `improvement-m2-20261007/production6-isolated-replay-v2/pgdata` и unused
build cache. Рабочие БД/резервные копии/образы/тома сохранены. Освобождено до
44 692 750 336bytes; обязательный резерв40GiB восстановлен. Evidence:disk-cleanup.json.
Это конкретное разрешённое исключение, а не новая политика удаления данных.

Private activation adapter нужен потому, что legacy overlay отказывает новому
двухфайловому payload ([release contract](../../operations/115-candidate-quality-workflow.md)).
Он связывает receipt, installed scripts74→76, точные2файла, unchanged worker,
base-only Compose (именно его вызывает wrapper), schema и exact cron.
Ready gate с точным ключом отсутствует до успешных checks/ACTIVATED audit;
атомарная публикация gate — последний commit. Ошибка до commit, включая
persistent rollback failure/SIGKILL, не допускает source launch.14failure tests PASS.
Первый ручной запуск обязан использовать тот же gate/expiry, что cron.

Exact payload:e7962da36c922a2566e90d4766ab11afce87662f77fb98860276601efc4d6408,
private activation-plan.json; предыдущий55f7 superseded и запрещён к запуску.
Scope:44-ФЗ/«бумага», ротация3страниц, максимум3number attempts за проход,
каждые10мин, admission cutoff25Oct00UTC (03MSK); уже допущенный запуск может
дождаться lease и завершиться позднее. Shared budgets могут откладывать работу.
Evidence cap256MiB/5000entries и queue2000; без автоматического удаления.
Это ограниченный пилот; national completeness,223 и refresh existing UNKNOWN.
Активация требует отдельного exact approval; cleanup approval её не заменяет.

Этот раздел и live-план обновлены после запечатывания candidate; они не изменяют
runtime bytes и не выдаются за содержимое source receipt. Установка и production
source verification остаются отдельными ещё не выполненными шагами.


24Oct05:24UTC: независимый final adapter review PASS,14/14tests;
read-only host preflight READY_FOR_EXACT_APPROVAL под существующими leases.
Первая попытка корректно отказала ROLLOUT_BUSY; повтор после завершения текущего
priority-run прошёл. Production scripts/cron/gate не установлены, source calls0.
Evidence:independent-final-adapter-review-v2.json,activation-preflight.json.
Поле PENDING_FINAL_PAYLOAD в immutable plan — состояние на момент составления;
его закрывает внешний review, связанный с полным SHA этого exact payload.


## Подтверждённая установка и рабочий контрольный проход

Пользователь подтвердил exact e7962da3 («Включить пилот и проверить поиск»).
Установка24Oct05:31:26UTC:2script files, точный cron и ready gate проверены;
API/WEB/worker/schema не изменены. Tenant audit PREPARED+ACTIVATED записан.
Первая apply-попытка до mutations остановилась на занятом import lease;
после завершения планового223worker тот же approved adapter прошёл.
Evidence:activation-result.json,installed-verification.json,production-queue-audit.json.

Первый gated source pass:UNKNOWN/BROWSER_REQUEST_FAILED (данные не объявлены пустыми).
Повторный gated pass:13.437s,50cards/0unparsed,2missing. Номер0162100021826000052
автоматически SYNCED:before0versions/0lexical → after1/1,1attempt, RECORDED audit;
вложения PLANNED. Особая процедура0153200000126000001 остаётся UNSUPPORTED/0attempts.
Durable queue1INDEXED/1UNSUPPORTED, next_page2. Run statusPARTIAL честно отражает
неподдержанный номер. National coverage/полнотаТЗ/допуск UNKNOWN.

Рабочий `/v1/tender-discovery/global-price` с law=all:
- по0162100021826000052:HTTP200 за5.093s,3 611 000.00RUB, XML SHA совпадает;
- «бумага»:HTTP200 за21.409s,1868matches, карточка0373100103926000241/4 220 224.14RUB.

Последняя уже была в индексе при рабочем discovery; её не считаем восстановленной
гибридом. Фактически восстановлен ремонт техники, включённый в public выдачу ЕИС;
он доступен по номеру. Оснащение с лотком — не чистая бумага. Совпадение поисковых
семантик ЕИС/локального поиска не объявлено полным.

Evidence:production-first-success.json,production-http-readback.json,
production-queue-audit.json,production-acceptance.json. Реальный контрольный запуск
использовал exact cron command с теми же gate/expiry. Установка расписания проверена;
первый плановый tick отдельно ещё не наблюдался. Пилот заканчивает допуск новых
запусков25Oct00UTC; дальнейшее расширение/продление — отдельное изменение payload.
