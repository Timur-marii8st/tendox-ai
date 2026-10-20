# Большая очередь публичных данных ЕИС

Статус: 2026-09-29. Реализованы сохраняемый план и ограниченный worker;
полный охват **не подтверждён**. Доступ к `my-server:22` после outage
восстановлен; рабочий SOCKS5-маршрут и свежий импорт подтверждены ниже.

## Что считается заданием

Один tenant-scoped target: региональный код × тип PRIZ × завершённая дата
со смещением +03:00. Поддержаны `epNotificationEF2020`,
`epNotificationEZK2020`, `epNotificationCancel`, `epNotificationCancelFailure`.
Два типа извещений проверены живым импортом. Отмены реализованы по официальной
XSD 16.3 и проверены синтетическими unit/PostgreSQL tests, живой proof ожидается.
Они хранятся отдельно от версий извещения; отсутствующая версия события не
выдумывается. Исходный ZIP, SHA, локатор, parser version и audit сохраняются.

`--regions all` разворачивается в **кандидатные коды 01..99**. Это перебор
адресуемого пространства двухзначных кодов, а не утверждение о 99 действующих
регионах. До получения официального актуального справочника
`region_registry_status=UNKNOWN`. Он не закрывает вопрос полного охвата.
223-ФЗ, другие процедуры 44-ФЗ и протоколы не входят в эту очередь.

Начальный период — 2025-09-28…2026-09-27, 365 дней, 144540 возможных targets
для четырёх типов. Это план запросов, а не количество полученных закупок.
Более длинную историю можно планировать отдельными диапазонами до 366 дней;
публичная/историческая доступность каждого семейства требует отдельной проверки.
Последний год сам по себе не доказывает полноту действующих закупок.
План уже сохранён на сервере: 144540 targets, SHA
`4cb88bd14e0ce383e8b809066c747820c5be76354924e60a4528675d734f81c9`.
Новых targets создано 144518; остальные 22 уже были в пилотном журнале.
Новые закупки из этого плана ещё не получены из-за outage.

## Команды

```bash
/home/syurai/vibe-seller/scripts/server-eis-corpus.sh plan --regions all \
  --from-day 2025-09-28 --through-day 2026-09-27 \
  --document-types epNotificationEF2020 epNotificationEZK2020 epNotificationCancel epNotificationCancelFailure
/home/syurai/vibe-seller/scripts/server-eis-corpus.sh run --max-windows 60 \
  --max-database-gib 100 --min-free-gib 40
```

План создаётся до любых сетевых запросов, не более 31 target за транзакцию.
Повтор не дублирует targets; прерывание сохраняет уже созданные задания.
Манифест scope с SHA/периодом/типами записывается в tenant audit. Worker
берёт до 60 окон, последовательно; приоритет — ещё не проверенные свежие даты.
Повтор NO_DATA/ошибки допустим после 24 часов, успешные checkpoints исключены.
Пропуски никогда не становятся полным охватом из-за истечения cooldown.

Общий `flock` защищает от одновременного ручного/daily/corpus импорта.
При нездоровом proxy скрипт возвращает `PROXY_UNAVAILABLE` до сетевого запуска;
все targets остаются открыты. Сетевая ошибка останавливает worker после
первого окна. SOAP и GET имеют консервативный интервал две секунды; worker
не распараллеливает запросы. Ограничения одного окна сохранены:
20 ZIP, 64 МиБ compressed, 128 МиБ expanded. Большие окна остаются пробелами;
адаптивное дробление требует отдельной реализации и проверки исторического API.

## Ресурсы и операционный режим

Worker ограничен 2 ГБ памяти и двумя CPU. Перед каждым окном он проверяет
размер БД и свободное место. При 100 ГиБ БД или менее 40 ГиБ свободного места
следующее окно не запускается. Это граница между окнами, не строгая квота
байт внутри одной транзакции. Бюджет включает запас для backups; их общий
рост и срок хранения нужно контролировать отдельно.
Сам backup не начинается, если свободного места меньше текущего размера
БД плюс резерв 40 ГиБ. Старые дампы автоматически не удаляются.

Cron потребляет очередь каждые 15 минут: не более 60 окон за запуск.
Перед импортом worker расширяет точный базовый scope до последней
завершённой даты, повторяя последние три даты плана. Watermark берётся
только из завершённых расширений **того же базового SHA**. Случайный ручной
план другой выборки не передвигает его. После длительного outage все
промежуточные даты планируются; прерывание расширения допускает replay без
дублей. Отдельный daily план в 04:10 добавляет недавние даты, но не заменяет
это продолжение базового scope. Логи находятся только
в `vibe-seller-state`; токены туда не записываются. Перезапуск компьютера
не удаляет очередь — она находится в PostgreSQL сервера. Ноутбук не хранит
новый большой корпус. Экран поиска показывает размер плана, остаток и число
запрошенных региональных кодов, сохраняя `corpus_coverage=UNKNOWN`.

## Проверки и оставшиеся gates

Профильные проверки защищают replay плана, RLS, свежие даты, NO_DATA cooldown,
бюджет до запроса, fail-fast сети, immutable event conflict/rollback и запрет
прибыли при отмене. PostgreSQL gate выполняется только в отдельной БД,
которая после тестов удаляется; production targets не используются тестами.
Проверки 28.09: 135 профильных unit tests, восемь PostgreSQL integration
tests, Ruff, strict mypy и production web build прошли. API/UI подтвердили
работу поиска при недоступном source egress. Live отмены ещё не проверены.

До заявления о полноте нужны живые отмены и остальные типы, официальный
каталог публичных типов/регионов, 223-ФЗ, обработка oversized windows,
контроль лага, подтверждение нулевых окон/late arrivals, сверка с источником
и полный проход выбранной границы. Очередь и успешные tests эти gates не заменяют.

## Восстановление 29.09

После включения второго VPS SSH доступен с ноутбука и основного сервера,
`eis-proxy` healthy. Ограниченный прогон четырёх окон кандидата 01/28.09:
две SYNCED с 16 новыми версиями и две `NO_DATA` с SHA официальных ответов
для типов отмены/отмены несостоявшегося определения поставщика. Событий
отмены в этом прогоне нет: это не доказательство, что тип в целом пуст.
Freshness всей ЕИС остаётся UNKNOWN. Cron общего корпуса каждые 15 минут,
план свежих дат и отдельная документная очередь каждую минуту проверены.
После прогона 144936 targets запланированы, 144915 остаются открытыми;
коды 01..99 остаются кандидатными, не реестром регионов.

## S135 / P2a — текущие часы и повторная сверка (01.10.2026)

Backfill и freshness теперь используют общий immutable journal, но разные
consumers. Date-only backfill исключает hour targets и сохраняет успешные
checkpoints. Freshness явно вызывает `refresh=True`: снова обращается к IP,
получает готовые архивы, атомарно добавляет новые версии/события и записывает
SHA ответа в attempts. Старые snapshots/XML остаются неизменными.

Расписание `fresh --regions 50,77`:

- Последний допустимый start часа = floor(now в +03 − 2h05m), только текущая
  дата. Ограничение >2h для начала oneHourInfo следует ADR-0044/официальному
  контракту; пяти минут достаточно для дополнительного запаса на границе.
- Последние два доступных часа проверяются не чаще раза в час; более ранние
  часы текущего дня — не чаще раза в шесть часов.
- Последние три завершённые даты сверяются не чаще раза в 24 часа, включая
  ранее успешно загруженные окна. Это ловит запоздалые изменения.
- FAILED/PREPARING/SERVICE_ERROR имеют минимум 15 минут между попытками;
  NO_DATA остаётся source observation с SHA и coverage UNKNOWN.
- Приоритет: последние часы, completed-day reconciliation, ранние часы.
  Внутри полосы сначала непроверенные окна, затем старейшая попытка.

`server-eis-priority.sh` имеет отдельный lock против дублей priority worker,
создаёт operational hint в общем постоянном томе и ждёт общий import lock до
300 секунд. Backfill уступает **между** атомарными окнами; hint старше 600
секунд не блокирует работу после аварии. EXIT очищает hint. Все обращения
последовательны; proxy/resource gates и лимиты архивов прежние. До 8 окон,
240 секунд — мягкий бюджет между окнами, не обрыв активной транзакции.

Начальный scope: 50 и 77 × EF2020/EZK2020/Cancel/CancelFailure. `--regions all`
для fresh CLI запрещён: расширение требует явной измеренной области и
расчёта пропускной способности. Это **не** same-day SLA всех регионов,
не полный 223-ФЗ и не полнота ЕИС. Ни частая проверка, ни новый source
watermark не переводят общую свежесть/coverage в PASS.

Команды оператора:

```bash
/home/syurai/vibe-seller/scripts/server-eis-priority.sh
/home/syurai/vibe-seller/scripts/server-eis-priority.sh --smoke
```

`--smoke` один раз перечитывает уже ingested завершённую дату поддержанного
типа, сохраняет before/after immutable snapshots, attempts и SHA кода в
`/var/lib/eis-browser/research/freshness/local-eis-supplier/<timestamp>`.
Большие данные остаются на VPS. Пользовательский поиск ещё не создаёт
динамический региональный refresh job; региональные lag/SLA и расширение
priority scope остаются следующим P2b.

## S136 / P2b1 — региональный status и расширение по замерам

С 01.10.2026 default priority scope **50,77,78** × четыре поддержанных типа.
Region 66 проверен пилотом, но не включён в постоянное расписание. Scope можно
задать `EIS_FRESHNESS_REGIONS` или явным CLI `--regions`; `all` остаётся
запрещённым shorthand для fresh. Новых миграций нет.

Каждая новая freshness attempt содержит typed observation в существующем
immutable audit: company/window/region/type/lane, aware start/finish,
monotonic duration_ms (Decimal), outcome/reason, response SHA, downloaded ZIP
bytes, new versions/events. Failed attempt не получает выдуманный SHA или
byte count. Старые attempts без metrics явно считаются missing observations.

Read-only status не выполняет запросов к ЕИС и не создаёт targets:

```bash
sudo -n docker compose -p vibe-seller -f docker-compose.server.yml run --rm -T --no-deps worker \
  python -m procurement.eis_corpus_cli fresh-status --regions 50,77,78 \
  --company-id local-eis-supplier --actor-id operator-status
```

Для каждой пары region/type выдаются hour/date targets, unattempted/due/
failed/NO_DATA, latest attempted, latest successful sync, latest NO_DATA,
oldest due hour и latest ingested hour. `eligible_hour_lag_seconds` — разница
между последним доступным hour start и последним ingested start. Это watermark,
не доказательство отсутствия дыр внутри периода. NO_DATA не даёт ingested
watermark. История NO_DATA/SYNCED сохраняется, даже когда latest attempt стала
FAILED. Tenant-scoped attempt/event IDs дают provenance. Query snapshot
consistent-read; до 2000 audit samples, признак truncation и missing metrics
явны. Coverage/freshness остаются UNKNOWN.

Capacity estimate: nearest-rank p50/p95 по SYNCED/NO_DATA, число failed/pending
отдельно; минимум 8 завершённых samples. В slot time включены две секунды
между окнами. Номинальный ceiling — 8 slots ×12 runs/hour =96; temporal ceiling
ограничивает slots мягким 240s бюджетом. Оценка пикового steady расписания:
`region_count × type_count × (2 +20/6 +3/24)`. PASS у budget_fit относится
только к этой арифметике, `overall_feasibility` всегда UNKNOWN. Startup,
контенция с backfill, дневной объём, clock skew, source outages и холодный
backlog не доказаны этим небольшим экспериментом.

Pilot двух новых регионов проверил 16 часов четырёх типов: 3 SYNCED /13 NO_DATA,
0 ошибок, +7 версий, 113479 ZIP bytes. Window p50=3.068s, p95=11.041s; выборка
ночная, source sparsity не гарантирует такой же дневной throughput. Расчёт
для 4 регионов: ~87.333 slots/hour; для 3:65.5. Default scope расширен до трёх,
чтобы оставить запас. Архивы/evidence на VPS; на ноутбуке только отчёты.

### Conflicting source windows

77/2026-09-29 EF diagnostic доказал один повтор одной версии с разными XML SHA.
Admission/parser остаётся строгим. Archive/index conflict сохраняет FAILED
window и UNKNOWN полноту; повтор source version конфликтов не чаще раза в
24 часа. Worker продолжает следующие окна. Transport/auth/HTTP/rate-limit/
service failure останавливает проход. Никакая версия из противоречивого набора
не выбирается произвольно, прошлые данные не стираются.

Raw diagnostic ограничен 64MiB ZIP/window, хранится tenant-scoped в volume
`research/freshness-diagnostic`; сохраняются response/ZIP SHA и XML member SHA,
без token/header/request secrets. Для существующего gap operator может вызвать
`scripts/server-eis-freshness-diagnostic.py` под общим import lock. Разрешение
конфликтов и адаптивное дробление крупных дат — следующий отдельный slice.
# S137: reuse transport и увеличенный bounded проход

Freshness CLI использует одну лениво созданную Chromium/WSDL session за
проход. Нет due targets или resource gate блокирует запуск — браузер не
открывается. Закрытие выполняется и при error/cancellation. Standalone
window CLI сохраняет одну session на окно. Worker остаётся последовательным:
2s на каждый POST/GET и между окнами, общий lock и прежние архивные лимиты.

Default freshness: 24 windows/240s между окнами, запуск раз в 300s. Runtime
может завершаться позже 240s для окончания начатого атомарного окна. Status
CLI использует тот же default; при override указывать `--max-windows`,
`--max-seconds`, `--cadence-seconds` и в измерении capacity. Номинальные 288
slots/hour не подтверждают непрерывную достижимость или полный охват.
Live 24 окна: 187.554s, 16 SYNCED /8 NO_DATA, один browser, +244 версии,
+8 событий, 4 181 952 bytes; подробности/evidence в docs/15 S137.

# S138: foreground по запросу поставщика

`POST /v1/tender-discovery/eis-refresh-requests` принимает товарный query и
1–3 разных source codes 01..99. Требуется OPERATOR; company/actor задаются
аутентификацией. Запрос и фиксированные окна сохраняются immutable audit:
два доступных recent часа текущего дня плюс предыдущая завершённая дата,
четыре поддержанных типа 44-ФЗ. До 02:05 MSK часов текущего дня нет.
ЕИС запрашивается по периоду/региону; товар фильтруется локальным индексом.
Регионы запроса — регионы публикации источника, не гарантия географии доставки.

TTL 1h, максимум 20 живых requests/tenant и 1 новый payload/минуту. Одинаковый
неполный запрос coalesced до expiry; завершённый — до 5 минут после создания.
CLI freshness включает foreground автоматически; чередует его с baseline,
dedup общих окон и round robin request очередей. Просроченный target пропускается
до сети. Полезные background scopes не становятся active default от пользовательского
запроса. Source conflicts/limits не меняют atomic admission и cooldown.

`GET /v1/tender-discovery/eis-refresh-requests/{id}` read-only, tenant-scoped.
QUEUED/PARTIAL/POLLED/EXPIRED выводятся по source attempts с SHA и временем
между request/expiry; POLLED включает NO_DATA и оставляет freshness/coverage
UNKNOWN. FAILED/неизвестное доказательство не закрывает окно. Другой tenant
получает 404. Live 66: 4/4 polled, +132 версии/+7 событий, errors 0 в foreground;
один baseline source conflict сохранился. Evidence и gates — docs/15 S138.

