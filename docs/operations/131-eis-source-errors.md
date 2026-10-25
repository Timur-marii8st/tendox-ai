# Доступ к ЕИС и сохранение причин отказов

24.10.2026; owner root. V41 INSTALLED21:41:02MSK; diagnostics PASS.
Post-release new intake/search UNKNOWN:25Oct01:10MSK повторный WSDL timeout.
Owned: sources/eis_feed_sync.py, три223 fetchers, server-eis-223-refresh.py,
source-error unit/223-regions PG tests, этот отчёт, индекс и live-план.
Контракт: PRD мониторинг/наблюдаемость, ADR0044, candidate quality workflow.
Acceptance: безопасные коды initial/prepared/HTTP/network сохраняются в attempt,
audit и отчёте; реальный запуск и новые закупки в HTTP search проверяются отдельно.
Evidence: `tmp/eis-source-errors-20261024-v41/`.

## Доступ

21:12MSK оба интеграционных WSDL int/int44 закрыли TLS/browser соединение:
ERR_CONNECTION_CLOSED. Публичная страница вернула HTTP434.21:16MSK её текст
подтвердил официальные регламентные работы24Oct20:00–25Oct01:00MSK;
ЕИС предупреждает о возможности изменения времени. Источник:
[главная страница ЕИС](https://zakupki.gov.ru/epz/main/public/home.html),
получена нормальным Chromium через установленный proxy, TLS validation включена.
Текст — public-error-page.json; запросы публичные, SOAP/token0.
Это объясняет совпавший по времени массовый сбой; восстановление интеграции
должно подтверждаться реальным ответом, не наступлением объявленного времени.
Proxy/IP/TLS/allowlist не менялись; обход ограничений не выполнялся.

## Исправление

EisSourceError содержит только ограниченные phase, числовые service_code/HTTP,
подтип отказа и allowlisted network code. Сообщение ЕИС, URL, SOAP и raw exception
не копируются. Все223 fetchers передают service code для initial и prepared;
HTTP-отказы и ограничения тела разделяются, включая скачивание архива.
BrowserSession различает запуск браузера, WSDL, SOAP и ARCHIVE.
Базовая строка исключения сохраняется для прежней обработки остальных callers.
223 runner сохраняет schema-compatible reason вида SERVICE_ERROR_INITIAL_CODE_13
и структурированные metadata в отчёте; tenant-scoped audit получает тот же reason.
Исторические null reasons не реконструируются. Source budgets, pacing1.25s,
SQL5s, очередь, cron, lease, схема, DB100GiB/free40GiB и worker3GiB/3CPU неизменны.

## Проверки и границы

Первоначальные9 regression cases воспроизвели потерю metadata на baseline.
Focused147PASS; после расширения25новых unitPASS. Независимый review обнаружил
несовместимость первого формата reason с DB constraint; исправлено до выпуска,
добавлены15PG cases для трёх семейств/пяти стадий с audit/RLS.
Full gate release-20261024-182251-fd12d9e7bded PASS, complete=true,50/50stages:
3954unitPASS/27allowedSKIP,737PGPASS,205webPASS,9doctests; lint/mypy/build/smoke PASS.
Первая попытка остановлена на docs-navigation: текущий live-план ссылался на
не включённый локальный remediation125. Candidate docs ограничены baseline/V40/V41;
повтор выполнен полностью, stages не пропускались. Receipt относится ко второй попытке.
Runtime и adapter independent reviews PASS;10rollback scenarios PASS.

## Установка и реальный запуск

План d0941d6970fdcc31650e8d8188d89f70a828d86d57866d60a60e02bd5d071aa8
установлен24Oct18:41:02UTC. API/worker image
b0a04204e25af07ca817b60b24a77e7df0d46d4e8a80a9cd02f11c1fc4969350.
Изменены четыре source-модуля и host223runner; все runtime module hashes совпали
с принятым candidate. Host runner SHA33ff57e080fd8d2b1606a7ea17f3d421844877268ad49ffc3cdc094c81656110.
Независимый installed review подтвердил252module hashes, image/config/host scope.
Активного worker при review не было; его digest подтверждён по конфигурации.
Schema20261023_01, DB/WEB containers, cron и budgets сохранены.
Snapshot/трёхфайловый rollback и tenant PREPARED/ACTIVATED audit сохранены.
Проверенные копии24Oct/22Oct/original сохранили identities; повторного чтения дампов не было.

Штатный server-eis-223-refresh.sh21:41:24MSK:1попытка,3.48s,
FAILED SOURCE_TRANSPORT_FAILED_WSDL_ERR_CONNECTION_CLOSED.
Report phase=WSDL/category=NETWORK/network_code=ERR_CONNECTION_CLOSED;
точный reason совпал с attempt и tenant-scoped audit в реальной БД. Это PASS
сохранения причины, не успешное скачивание. source_posts считает вызовы интерфейса
транспорта: при отказе WSDL он не доказывает отправку SOAP. Exit0 не является intake PASS.
После установки новых закупок0/редакций0; всего46899/54328 по223.
Три ранее загруженные карточки32616504463/464/465: HTTP200, XML SHA/navigation
совпали с БД; anonymous401. Эти карточки не засчитываются как новые после V41.

Контроль после регламента назначен25Oct01:10MSK в текущем чате, heartbeat automation.
Задание одноразовое: подтвердить новый intake/search либо сообщить наблюдённый
блокер, затем поставить себя на паузу. Окончание обслуживания не считается фактом
восстановления. Evidence acceptance.json разделяет installation/diagnostics PASS,
source_access FAIL и new_purchase_ingestion/search UNKNOWN. Национальный охват UNKNOWN.
Финальные docs изменены после sealed source; runtime соответствует receipt.


## Контроль25Oct01:10MSK после объявленного окна

Owner root; read-only follow-up и один штатный server-eis-223-refresh.sh.
Owned: этот отчёт, live-план и task-local followup evidence. Runtime изменений0.
Installed API/worker configuration, schema, cron, DB/WEB identities и host runner
совпали с V41. Активный worker завершился до inspect; его runtime limits отдельно
не подтверждены, сохранённая Compose configuration совпадает с проверенной.

Штатные проходы00:35/00:45/00:55MSK получили69/88/49NO_DATA (всего206),
новых редакций0. Это подтверждает временное восстановление ответов сервиса.
Следующий cron01:05MSK:FAILED SOURCE_TRANSPORT_FAILED_SOAP_TIMEOUT.
Ручной штатный запуск завершён01:10:59MSK:1attempt/27.38s,
FAILED SOURCE_TRANSPORT_FAILED_WSDL_TIMEOUT, archive_gets0. Устойчивое восстановление
не подтверждено; продление регламента не объявляется установленной причиной.

Снимок01:11:34MSK после точного installed_at24Oct18:41:02.497449UTC:
46899уникальных закупок/54328редакций223; прирост0/0. Попытки после установки:
206NO_DATA/20FAILED, SYNCED0. Новых номеров для HTTP/SHA/navigation проверки нет;
anonymous401 подтверждён. Ingestion/search для новых закупок остаются UNKNOWN.
Загрузка ранее сохранённых карточек не засчитывается как новое поступление.

V41 diagnostic helper упёрся в SQL5s на необязательном audit join за весь период.
Для счётчиков/HTTP использован существующий V39 live-readback.py без этого join;
SQL timeout не увеличивался. Ошибка диагностического запроса не приписывается
штатному загрузчику: его последний отказ относится к WSDL network timeout.
Evidence:followup-installed.json, followup-runs.json, followup-refresh.json,
followup-final-counts-search.json, followup-readback-note.json,
followup-acceptance.json. Исходный installation acceptance сохранён отдельно.
Автоматизация automation поставлена на PAUSED после одноразовой проверки.
Далее — диагностика нестабильной доступности сервиса; приёмка нового intake/search
потребует фактически полученных закупок. National coverage UNKNOWN.
