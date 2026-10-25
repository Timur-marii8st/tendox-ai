# Сервер ограниченного индекса ЕИС

Первичный снимок: 2026-09-28. Пилот перенесён с ноутбука на `syurai@192.144.13.82` в
`/home/syurai/vibe-seller`. В этом первичном снимке индекс содержал **19 окон аукционов и
электронных запросов котировок, 44-ФЗ, регионы 50/77**, а не полную базу ЕИС. Охват и экономика в интерфейсе
остаются `UNKNOWN`.

Актуальные этапы и evidence приведены в последующих разделах этого файла;
актуальный rollout и его границы — в [live-плане](../15-implementation-plan.md).
Полный охват ЕИС остаётся UNKNOWN.

Порядок новых релизов задаёт [candidate quality workflow](115-candidate-quality-workflow.md)
по ADR-0107; его activation пока NOT_PERFORMED. Команды сборки, прямой замены
образов/host scripts и selective deploy ниже — историческое evidence,
а не текущий routine promotion. Новый неподдерживаемый payload требует отдельного
адаптера; ручной административный override возможен только как явно записанное
emergency действие и не создаёт quality PASS. Запуск неизменённых ingestion scripts
остаётся выполнением текущего кода, а не выпуском нового кандидата.

## Состав и доступ

### syurai.ru — конфигурация активирована 2026-10-06, DNS/TLS pending

**Актуальный доступ: https://www.syurai.su/**. По явному запросу пользователя
2026-10-06 site address заменён на `www.syurai.su`; старый блок `syurai.ru`
снят. Остальные настройки и credentials сохранены. DNS публично отдаёт
`192.144.13.82`, HTTPS-сертификат выпущен. Проверки с включённой TLS validation:
анонимный HTTPS 401, authenticated `/tender-discovery` 200, authenticated `/`
302 с `Location: /tender-discovery`, Forgejo HTTPS 200. Audit с company_id
`local-eis-supplier` — `activation-www-su.json` в staging-каталоге.
SHA-256 активного Caddyfile:
`10483641999c2f04d46070691cb0093b04c21fa1b7e9d1ab06bd589d3a99a6b3`.
Ниже сохранено evidence предшествующей попытки подключения `.ru`.

Владелец: root. Owned files: `scripts/prepare-syurai-domain.py`, этот документ
и запись в live-плане. Запрос пользователя: доступ к пилоту через `syurai.ru`.
На VPS подготовлены Caddyfile и Compose override в
`/home/syurai/vibe-seller-state/domain-syurai-ru` (права каталога 0700,
файлов 0600). Исходный Caddyfile сохранён рядом для отката.

Предложение: HTTPS для `syurai.ru`, HTTP redirect, Basic Auth пользователя
`pilot` на всех маршрутах, `/` → `/tender-discovery`, reverse proxy к
`vibe-seller-web-1:3000` с удалением входящего Authorization. Пароль случайный,
в конфигурации только bcrypt hash. Caddy подключается к `vibe-seller_default`;
override сохраняет эту сеть после пересоздания. Существующий блок Forgejo
сохранён. Это общий доступ к одному tenant пилота, не multi-user auth.

Evidence подготовки: Caddy 2.10.2 `validate` PASS, Compose `config --quiet`
PASS. SHA-256 proposed Caddyfile:
`71d2165eeb379f44a93c256b02985f01a3721ab53780875e44d1c711e93f3077`.
Пользователь подтвердил exact-payload публикацию в чате («подтверждаю»).
Конфигурация с указанным digest применена без изменения блока Forgejo,
runtime Caddy подключён к сети, та же сеть сохранена в `/opt/forgejo/compose.yaml`.
Исходный Compose сохранён в staging-каталоге. Tenant-scoped запись активации
и approval хранится в `activation.json` рядом с конфигурацией.
Проверки после активации: Compose config PASS, web loopback 200,
HTTP `Host: syurai.ru` → 308 HTTPS, существующий Forgejo HTTPS 200.
Полный HTTPS/401 без credentials/200 с credentials PENDING: ACME отказал
с DNS SERVFAIL. TLS verification не отключалась; Caddy автоматически повторяет.

DNS на момент проверки: родительская зона `.ru` делегирует Cloudflare
`hasslo.ns.cloudflare.com` / `crystal.ns.cloudflare.com`; публичный resolver
возвращает SERVFAIL. `ns1.reg.ru` авторитетно отдаёт A `95.163.244.138`.
После изменения пользователем `ns1.reg.ru` и `ns2.reg.ru` отдают правильный
A `192.144.13.82`; родительская делегация по-прежнему Cloudflare.
Для завершения нужны сохранение NS REG.RU и обновление делегации.
Источник: прямые `dig` запросы к `a.dns.ripn.net`, `ns1.reg.ru` и Google DNS
2026-10-06. Эти наблюдения не являются гарантией текущего DNS после изменений.

Конфигурация опирается на официальные
[Basic Auth](https://caddyserver.com/docs/caddyfile/directives/basic_auth) и
[Automatic HTTPS](https://caddyserver.com/docs/automatic-https) Caddy.

- `docker-compose.server.yml`: PostgreSQL 16, FastAPI, Next.js и ручной
  worker. Контейнеры API и web слушают только loopback сервера (`18000` и
  `13000`); публичные 80/443 и Forgejo не затронуты. Контейнеры ограничены
  по памяти (БД 2 ГБ, API 1 ГБ, web 768 МБ, worker 2 ГБ); worker также
  ограничен двумя CPU из четырёх.
- Секреты находятся только в серверном `.env` с правами `0600`. Файл не
  входит в release и не должен копироваться в документацию или логи.
- Папка `/home/syurai/vibe-seller-state` хранит исходный дамп миграции и
  ежедневные резервные копии; права `0700`.
- Для просмотра с ноутбука открыть собственный SSH-туннель:

  ```text
  ssh -N -L 13000:127.0.0.1:13000 syurai@192.144.13.82
  ```

  Затем открыть `http://127.0.0.1:13000/tender-discovery`. Туннель работает,
  пока работает команда SSH. Публичный доступ без отдельной аутентификации
  не включён.

## Проверка

S133: `EIS_DISCOVERY_DB=/var/lib/eis-browser/discovery/eis-discovery.sqlite3`
на API. Tenant-scoped поисковые сессии, raw artifacts и audit находятся в
постоянном `eis_browser_state`, переживают пересоздание контейнера. Ранее путь
по умолчанию `/app/data` был вне тома; перед миграцией 01.10 файл отсутствовал.
При последующем переносе существующей SQLite базы сохранить её согласованную
копию до смены пути; не копировать только основной файл при активном WAL.

```bash
cd /home/syurai/vibe-seller
sudo docker compose -p vibe-seller -f docker-compose.server.yml ps
python3 scripts/server-smoke.py
python3 scripts/server-eis-connectivity.py
sudo docker compose -p vibe-seller -f docker-compose.server.yml run --rm \
  -v /home/syurai/vibe-seller/scripts/server-ui-smoke.py:/tmp/server-ui-smoke.py:ro \
  worker python /tmp/server-ui-smoke.py
sudo docker compose -p vibe-seller -f docker-compose.server.yml run --rm \
  worker syurai-eis-gaps --company-id local-eis-supplier
```

Проверка миграции: 1562 XML-версии, 9 окон и 19 ZIP-архивов; API видит
1462 текущие карточки. Запрос «серверное оборудование» нашёл 113, «бумага»
28 предварительных совпадений. Сквозной браузерный тест отобразил 28 карточек
для «бумага». Эти числа подтверждают перенос данных и работу поиска, не
полноту ЕИС и не выгодность закупок.

Состояние после proxy-импорта 28.09: 2335 XML-версий, 14 окон, 30 архивов,
2194 текущие карточки, БД около 67 МиБ. Поиск дал 168 предварительных
совпадений для «серверное оборудование» и 40 для «бумага»; UI подтвердил 40
карточек. Получение одного DOCX через серверный API проверено (24 070 байт,
SHA-256 `9e8f6636eb1c3c25558225ef71be0ffc713ffd03e945c09b48d82498ddcc38b8`);
его `extraction_status=UNKNOWN` не превращается в полный анализ документа.

После добавления котировок: 2918 XML-версий (2335 аукционов, 583 котировки),
19 окон, 38 ZIP, 2765 текущих карточек, БД около 77 МиБ. Поиск показывает
203 предварительных совпадения по серверному оборудованию и 51 по бумаге.
API и браузерный тест проверили тип процедуры, ссылку `zk20` для котировок,
`UNKNOWN` экономики и отсутствие ложного допуска. Повтор дня котировок
добавил ноль версий; PostgreSQL gate из шести тестов прошёл в отдельной БД,
которую затем удалили. Все пять `NO_DATA` остаются видимыми пробелами.
114 профильных unit tests прошли на сервере. Ручной ежедневный запуск
обоих типов пропустил семь успешных окон без дублей и завершился с кодом 2
из-за пяти `NO_DATA`; это ожидаемый `PARTIAL`. Свежий backup восстановлен
в отдельную БД с 2918 версиями; временная БД удалена.

`server-eis-connectivity.py` проверяет прямой маршрут основного VPS, который
по-прежнему недоступен для ЕИС. Настроенный proxy-маршрут проверять отдельной
живой командой `python3 scripts/server-eis-proxy-smoke.py` (один DOCX через
API, учитывает cooldown ЕИС); не запускать её как частый healthcheck.

## Резервная копия

`scripts/server-backup.sh` делает PostgreSQL custom dump и проверяет
читаемость потока. Cron пользователя `syurai` запускает его ежедневно в
03:20 MSK. Дампы лежат в `vibe-seller-state/backups`, доступны только
владельцу. Первый дамп проверен чтением полного потока и временным
восстановлением через `scripts/server-verify-backup.sh`. С24.10.2026 включена [ротация](126-backup-rotation.md): новая копия и предыдущая
полностью декодируются перед удалением старых; остаются две проверенные и исходная.
При ошибке создания/проверки удаление не начинается; резерв диска40GiB сохраняется.

## Диагностика 27.09 и решение через второй VPS 28.09

27.09.2026 попытка `exactDate` для региона 50/17.09 завершилась
`SOURCE_TRANSPORT_FAILED`; дата записана как незакрытый пробел в
tenant-scoped журнале. С сервера DNS ЕИС разрешается, но TCP/443 к
`int.zakupki.gov.ru`, `int44.zakupki.gov.ru`,
`int44-ttls-cert.zakupki.gov.ru` и `zakupki.gov.ru` истекает по таймауту.
Другие HTTPS сайты доступны, исходящие соединения UFW разрешены, адрес
сервера определяется как RU. На ноутбуке официальный сайт отвечает.
Причина на стороне маршрута/фильтрации до ЕИС пока не установлена; журнал
не выдаёт ложный checkpoint. На этом этапе расписание импорта не включалось.

28.09 пользователь разрешил маршрут через `ssh my-server` (`88.218.66.108`).
Контейнер `eis-proxy` на основном VPS поддерживает SSH SOCKS5-туннель без
публичного порта. Отдельный ключ находится только в защищённой папке
`vibe-seller-state/eis-proxy`; authorized key на втором VPS ограничен
исходным IP основного VPS, запрещает shell/agent/PTY и разрешает только
адреса ЕИС на TCP/443. Host key закреплён в `known_hosts`. Существующие
Privoxy/sing-box второго VPS не менялись. В API/worker `EIS_BROWSER_PROXY`
применяется только к браузерным клиентам ЕИС (XML, карточки и вложения).

Корневой Russian Trusted Root CA получен по HTTPS с официального ресурса
Госуслуг и добавлен в системное/Chromium NSS хранилища **образа контейнера**;
хосты не изменены. Источник и SHA указаны в `docker/certs/README.md`.
Проверка TLS не отключалась. Живой импорт дня 17.09 региона 50 через новый
маршрут получил два ZIP/172 версии и закрыл прежний пробел. Повтор пропустил
checkpoint, новых дублей нет. Даты 19–20 региона 50 добавили 13 версий, даты
25 и 27 региона 77 — 588. `NO_DATA` для 50/27.09 и 77/26.09 остаётся двумя
видимыми пробелами с SHA ответов.

## Ежедневная загрузка выбранных регионов

Cron пользователя `syurai` запускает `scripts/server-eis-daily.sh` ежедневно
в 04:00 MSK: завершённые последние три даты, регионы **50 и 77**, типы
`epNotificationEF2020` и `epNotificationEZK2020` последовательно.
Лог: `vibe-seller-state/eis-daily.log`. Успешные
окна пропускаются; `NO_DATA` и ошибки остаются в журнале, дневной запуск
возвращает ненулевой код при пробелах. Ручной повтор использовать через
общий lock, а не параллельно с cron:

```bash
/home/syurai/vibe-seller/scripts/server-eis-run.sh 50 --from-day 2026-09-17 --through-day 2026-09-17 --utc-offset 3
/home/syurai/vibe-seller/scripts/server-eis-run.sh 50 --from-day 2026-09-25 --through-day 2026-09-25 --utc-offset 3 --document-type epNotificationEZK2020
```

`flock` возвращает `SERVER_IMPORT_BUSY` при втором запуске. Docker сохраняет
туннель после перезапуска; SSH keepalive/restart восстанавливают соединение.
Пределы одного окна (20 ZIP, 64 МиБ compressed, 128 МиБ expanded) сохранены,
worker ограничен 2 ГБ памяти. Расписание не загружает все регионы или типы
и не подтверждает полный охват. Остальные
типы 44-ФЗ/223-ФЗ, вложения, проверка экономики и протоколы остаются этапами
[плана полного индекса](../eis/search/26-eis-full-corpus-plan.md).

Отдельно проверены восстановление туннеля после restart и его границы:
соединение с `int.zakupki.gov.ru:443` проходит, с `example.com:443` запрещено
restricted SSH key. Proxy-контейнер потребляет около 2 МиБ памяти; ноутбук
в транспортном пути не участвует.

## Продолжение 28.09: очередь и новый outage

После первых успешных импортов `88.218.66.108:22` перестал отвечать
с основного VPS и ноутбука; TCP/443 этого VPS тоже недоступен с ноутбука.
Причина (питание, IP, firewall, маршрут) не установлена. Прямой egress
основного VPS до ЕИС по-прежнему timeout. Старый индекс доступен через API/UI;
сбой транспорта не стирает данные и не закрывает новые окна.

На основном сервере развернуты parser/resolver отмен, миграция
`20260928_02`, большая сохраняемая очередь и экран размера плана.
Живых отмен в БД ещё нет; их parser/storage проверены на синтетических
unit/PostgreSQL tests. Годовой план содержит 144540 targets по кодам
01..99 и четырём выбранным типам, из них 144522 незавершённых. Это
адресуемые кандидаты, не подтверждённые регионы и не загруженные закупки.

Cron: corpus run каждые 15 минут, до 60 окон; recent-day plan в 04:10.
До запуска worker проверяется health proxy; `PROXY_UNAVAILABLE` сохраняет
все задания. После восстановления используется продолжение базового SHA,
которое планирует все даты после outage. Общий flock сохранён. Worker
останавливается при БД 100 ГиБ/свободном месте менее 40 ГиБ; backup не
начинается без свободного места размером БД плюс 40 ГиБ. Полный runbook:
[большая очередь](29-eis-corpus-queue.md). 135 профильных unit tests,
восемь PostgreSQL tests, Ruff/mypy и production web build прошли.

## Восстановление 29.09

После включения `my-server` его SSH вновь доступен с ноутбука и основного
VPS; контейнер `eis-proxy` healthy. Никакая смена IP/ключа/TLS-настроек не
потребовалась. Ручной ограниченный импорт 50/28.09 аукционов дал 2 ZIP,
190 новых версий, статус COMPLETE; replay того же окна дал SKIPPED/0 новых.
Небольшой прогон корпуса дал ещё 16 версий по коду 01. API индексировал
3124 версии/2931 текущую карточку/22 окна; live поиск: 220 предварительных
совпадений серверного оборудования за 294 мс и 53 бумаги за 142 мс.
`corpus_coverage` и `source_freshness` остаются UNKNOWN. Ресурсы сервера:
БД около 244 МБ; лимиты worker и резерв 40 ГБ сохранены. Документная очередь
получила реальные байты, см. [операции документов](../documents/31-eis-document-queue.md).

## S135 — приоритетная свежесть поддержанного scope

01.10.2026 развёрнут новый `fresh` consumer. Cron `2-59/5` запускает
`server-eis-priority.sh`: 50/77, четыре поддержанных типа 44-ФЗ, до 8 окон,
мягкий бюджет 240 секунд между окнами. Существующие backup/daily/corpus/
documents cron сохранены. Queue API/web доступны после пересоздания API;
структура БД не менялась, production migration не нужна.

Priority intent хранится в общем Docker volume, имеет TTL 600 секунд и EXIT
cleanup. Общий import lock сохраняется. Backfill обрабатывает только даты и
проверяет intent перед следующим окном. Интенсивность источника не повышается
параллельными запросами. Сработавший `PRIORITY_REFRESH_REQUESTED` — уступка
приоритетному worker, а не ошибка конкретного source window.

Live evidence:

- Первое окно 20:00 MSK при 21:21 ошибочно было слишком свежим и вернуло
  SERVICE_ERROR; оно осталось неуспешной попыткой. Добавлено правило official
  oneHourInfo >2h от начала, с запасом 5 минут, и отдельные boundary tests.
- Два исправленных EF окна 19:00: один SYNCED / один NO_DATA, +5 версий.
- Следующие восемь окон четырёх типов: пять SYNCED / три NO_DATA, +40 версий
  и +2 cancellation events. Всего +45 версий / +2 события за 10 проверок.
- Повторное чтение уже ingested 50/2026-09-30 EF: 3 ZIP, 217 извещений,
  SYNCED, новых версий 0. Исходные snapshots сохранены; checkpoint не скрыл
  сетевой запрос. `reconcile.json` SHA:
  `58c01be5cac2862f7605d33da44570cb48d921c03eb86caf2d6ba8bceb035821`.
  Полный небольшой proof с before/after/attempt/source/code SHA находится в
  volume: `/var/lib/eis-browser/research/freshness/local-eis-supplier/20261001T183006458899Z`.
- 98 профильных synthetic tests прошли; 19 PG integration gates прошли в
  отдельной БД, после чего тестовая БД удалена. Ruff и strict mypy прошли.
  `/health` ok, `/tender-discovery` HTTP 200.

На ноутбук скопированы только небольшие JSON/log reports. Raw архивы и индекс
остаются на VPS; бюджеты 100 ГиБ DB / резерв 40 ГиБ / 2 ГБ RAM worker прежние.
Проход polling каждые 5 минут не означает новое извещение за 5 минут: IP
oneHourInfo требует >2h от начала часа, остальные delays/NO_DATA ещё влияют.
Все отчёты сохраняют coverage/freshness UNKNOWN. Операционный контракт:
[29-eis-corpus-queue.md](29-eis-corpus-queue.md), раздел S135.

Operational проверка S135: cron сам выполнил восемь окон (+9 версий/+1 отмена).
Отдельный hint probe дал `PRIORITY_REFRESH_REQUESTED`, attempted=0. При tar
переносе Windows был потерян execute bit corpus wrapper; исправлен `chmod 700`,
все шесть cron scripts снова executable. При deploy обязательно выполнять:

```bash
chmod 700 scripts/server-eis-corpus.sh scripts/server-eis-priority.sh
bash -n scripts/server-eis-corpus.sh scripts/server-eis-priority.sh
```

Reconcile evidence независимо сверен по SHA и code SHA; before snapshot
полностью входит в after (1 → 2), retained ZIP bytes этого ключа 7 202 362.
Raw replay archives пока сохраняются вместе с новой source response: дедупликация
хранилища — отдельный P7, поэтому budget gates необходимы и для freshness.

## S136 — measured region rollout и status (01.10.2026)

Default scope priority cron теперь 50/77/78. 66 и 78 отдельно проверены в
ночном pilot; 16 окон /3 SYNCED /13 NO_DATA /0 errors, +7 XML-версий. p50 окна
3.068s, p95 11.041s; sparse ночная выдача, не дневной SLA. С текущим eight-slot
пятиминутным cron measured/nominal ceiling 96 slots/hour. Пиковая steady
нагрузка на 4 региона ~87.333/h, на 3 ~65.5/h; для запаса принят scope из трёх.
Конкуренция с backfill, startup и daytime объём остаются непроверенными в этом
небольшом замере. Full regional registry/223/full EIS coverage UNKNOWN.

Read-only `fresh-status` выводит typed region/type due/unattempted/failed/NO_DATA,
attempt/success/NO_DATA timestamps, ingested-hour watermark, age gap к последнему
доступному hour start, event/attempt provenance и throughput estimate. Старые
attempts без метрик видны отдельно; source polling не превращается в PASS.
Файл snapshot:
`/home/syurai/vibe-seller-state/s136-active-status.json`. Через CLI выполняется
consistent read без сетевых запросов к ЕИС и без планирования новых targets.
Пример запуска и точные границы — docs/29, раздел S136.

77/2026-09-29 EF диагностирован: одинаковый number/version, разные XML SHA.
Противоречивый XML не принят. Raw response/ZIP/member SHA retained в постоянном
томе, diagnostic SHA:
`39f0e94666830f671aab03f433a866936af0255e79788a8bbfffd39682ce1103`.
Такие FAILED windows и count/size overflow имеют 24h cooldown и изолируются,
чтобы другие окна продолжали работу. Архивные лимиты не снимаются, ingestion
атомарный. Transport/auth/HTTP/rate-limit/content/service failure останавливает
worker. Immutable источники/старые версии не изменены.

После rollout active scope: 8 окон, 4 SYNCED /4 NO_DATA, failures 0. Status
snapshot: 211 due /202 unattempted /3 failed, overall freshness UNKNOWN —
есть холодный backlog. 104 synthetic tests /20 isolated PG gates прошли,
Ruff/strict mypy прошли. PG test DB удалена; production schema не менялась.
Все shell wrappers остаются executable. Большие данные и raw diagnostic на
VPS; локально только маленькие reports, фикстуры synthetic.
# S137: лимит freshness прохода и transport reuse

`server-eis-priority.sh` теперь запускает до 24 окон за 240s между окнами;
cron offset/cadence, общий import lock и scope 50/77/78 не меняются. Один
lazy Chromium обслуживает весь проход без изменения TLS/proxy или spacing
2s POST/GET. Live 24-window pass занял 187.554s, errors 0; worker memory
snapshot 261.1MiB /2GiB. Это bounded observation, не обещание SLA всей ЕИС.
`fresh-status` default соответствует 24/240/300; для иного operational
режима передать те же `--max-windows --max-seconds --cadence-seconds`.
Release backup: `/home/syurai/vibe-seller-state/s137-before.tar.gz`.

# S138: запросы обновления из интерфейса

Экран `/tender-discovery` ставит выбранные регионы в foreground очередь при
поиске (checkbox можно отключить). Первое сравнение использует сохранённый
индекс. Кнопка статуса не обращается к ЕИС; повторный поиск сравнивает индекс
после импорта. Query/regions/checkbox сохраняются после server action.
В single-tenant pilot requests читает тот же freshness cron для company-id
`local-eis-supplier`; иных компаний он не обслуживает. Slots делятся с baseline
50/77/78, общий import lock, proxy/TLS и resource budgets сохранены.
API/worker/web обновлены, migration не нужна. Backup:
`/home/syurai/vibe-seller-state/s138-before.tar.gz`. Live evidence:
`/var/lib/eis-browser/research/foreground/local-eis-supplier/`.
Подробные API/TTL/budget условия — docs/29 S138. Полная ЕИС/223/экономика UNKNOWN.

## S151 — отдельный bounded refresh223-ФЗ

Cron `11,41 * * * * scripts/server-eis-223-refresh.sh` сохраняет log в
`/home/syurai/vibe-seller-state/eis-223-refresh.log`. Только company
local-eis-supplier/region50/AESMBO/today+yesterday(+03:00); due6h, error1h.
Shared eis-import.lock/wait45s, worker2CPU/2GiB,2windows/180s source await,
100GiBDB/40GiBfree. Пропущенный lock не закрывает дату. NO_DATA не доказывает
полноту. Attempt journal FORCE RLS/audit, SQL checkpoint FK для SYNCED.

Первый проход36.016568s,2SYNCED/+4версии; immediate repeatNOT_DUE/0requests.
Схема20261002_05,19версий/15текущих223карточек;3window observations/2dedup ZIP.
Весь live набор19XML проверен поofficial223XSD16.2/16.3; coverage/freshnessUNKNOWN.
Детали evidence и gates в docs/37. Verified full DB backup передS150 и
отдельный223dump передS151 находятся в state/backups. Тестовая БД удалена.


## S154 — refresh двух223семейств

Region50/today+yesterday+03:00 дляAESMBO/ZKESMBO. Due targets4, oldest checked_at
first; max2за проход/180s,6h success/1h error, cron11,41 иобщийlock/budgets
сохранены. Migration20261002_07 расширяет immutable journal, history сохраняется.
83local/23Linuxsync/44PGtests, Ruff/mypy/shellsyntax/deploy прошли.
Live37.372801s:8new/2SYNCED; repeatNOT_DUE/0requests.
62версии/56current/6windows/4ZIP/4attempts. Proof
s154-refresh-proof-20261002T105057620924Z.json,
SHA66a090a3195a76ee1dbfde11179d4dab4b82f66e754c63742e0280c85497d246.
Full-XSD61/62validbothreleases;1XMLsubstantiationNationalRegimeValue104>100.
Typed metadata projection иfull-XSD — разные проверки; SYNCED неXSD PASS.
Raw history сохранена, eligibility/economics/coverage/freshness UNKNOWN.

## S155 — полная XSD проверка отдельным evidence

Точный номер/версия/XMLSHA связан compositeFK с immutable FORCE RLS quality
journal. Official schema package/root/tree SHA и parser version сохранены;
отсутствие полного evidence двух releases — UNKNOWN, любая schema ошибка — FAIL.
Schema PASS не даёт допуск/полное ТЗ/прибыль. Диагностика видна в API/UI.
Offline audit bounded200versions/32MiB compressed, без HTTP; pinned trees
проверяются целиком, external schemaLocation запрещён. [ADR0051](../adr/0051-eis-223-schema-quality.md).

Deployment2026-10-02:79версий/72current/10windows;158checks,156PASS/2FAIL
дляXML32616432455v1, SHA d95f415b79ee37f87d8a64e602a2ad62f2ed1cd5276d4ba56a709e4fb11fdc97.
Replay0new/source0; API0.324525s/GETне меняетaudit/jobs; CUA подтвердил
FAIL обеихXSD иисходнуюцену1615916.67RUB.97local/45PG/37Linuxtests,
Ruff/mypy/webbuild/ESLint прошли. Production schema20261002_08; testDBудалена.
Proofs s155-schema-proof-20261002T172747460572Z.json,
SHA1d46cb2a7ec7a42f4f0acebda883e06564bdbd889df04d2a366b4ca9ee5b5254;
APIproofs155-ui-api-proof-20261002T172855560054Z.json,
SHAbbfdf0bbc3084e0a45416a22215521cf6c9ae3232e97755659fa9ca15bdc39ec.

## S156 — автоматическая bounded очередь качества

Штатный223refresh выполняет offlinequality после source outcome или NOT_DUE.
Только latest tenant versions с отсутствующей проверкой текущих pinned16.2/.3
и текущего lxml validator. Записанный FAIL не вызывает бесконечный retry.
2XML/32MiB compressed/30s soft между целыми версиями, ZIP открывается один раз
наSHA. DB100GiB/free40GiB guard и существующий import lock сохраняются.
QUALITY_UNAVAILABLE отдельный safe reason; source SYNCED не переписывается.
API GET не запускает validation. Никакого supplierPASS из schema PASS.
104local/46isolatedPG/48Linux, Ruff/mypy/deploy прошли. Production livequeue0
(79versions уже158checks), repeat0new/source0, audit неизменен. Positive latest,
missing release/old validator/FAIL-done/tenant проверены isolated syntheticPG.
Proof s156-quality-proof-20261002T174256101204Z.json,
SHA f2e9e574bc2c1cd205f936226ddf9f4a00eeb4635cd43f6b19ab47ce9b9f161c.

S157 live:32616419658v2,393665bytes/DOCX/243blocks/90conditions,1of8files.
ExactSHA27c82fe85895fe628b3fdce98fa390b510fafd5af2eeefdb75d22fa84e3eb557.
124local/48PG/64Linux/build/ESLint/Ruff/mypy/deploy passed; API0.101792s,
GETno mutations/replay0network. Sourcequality/extraction != eligibility.

## S158: recovery executable modes иdocument routing

При распаковке archive изWindows серверные shell entry points получили0600;
cron corpus/documents/priority отвечал Permission denied.223refresh имел0700
и продолжал работать.2026-10-02 восстановлены0700 для server-eis-*.sh и
server-backup.sh; package-server-release.py теперь принудительно задаёт0700
в archive header для scripts/server-*.sh. После любого selective deploy из
Windows обязательны chmod700+test-x+bash-n для этих entry points. Customtar
должен использоватьтотже filter или восстанавливать mode после extraction.
Source/dump backup проверяется до deploy; history/failed windows не очищаются.
Prioritycron после recovery реально загрузил45newversions/24attemptedwindows
вpass18:22UTC и затем новые44events; эти числа не доказывают полный охват.

Документныйcron остаётся * * * * *, global eis-import.lock. Tenant routing
cursor:state/eis-documents/local-eis-supplier/next-law (44 или223); directory0700,
file0600, atomicreplace. Cooldown/SOURCE_BUSY сохраняют очередь за тем же law,
остальныеterminal worker results вращаютlaw. Неизвестныйoutput сохраняетcursor.
Onefile/run, public60slease. Cooldownjournal не расходует5actualfailure attempts.
Документная очередь может ждатьsource/freshness imports; SLA fullset не заявлен.
Следующий optimisation slice должен измерить ожидание выбранных документов и
сократить source lock contention при сохранении source квот/freshness evidence.

## S161 — due-document handoff

Dispatcher сначала берёт отдельный nonblocking eis-document-dispatch.lock:
следующий cron tick не создаёт ещё одного ожидающего процесса. Running API image
выполняет tenant read-only due probe: resource budgets, exact current source,
known cancellation/expiry, received/cache state, retry delays. Probe не создаёт
analysis/audit/observations и не обращается к ЕИС; provisional результат worker
проверяет заново перед I/O. Локальная reanalysis полученных bytes также считается
работой, без download. Для223 сохраняются existing pending SQL/5 actual attempts.

Cursor остаётся предпочтением при двух due families; idle/deferred family
пропускается, другая due family получает слот. При IDLE marker не создаётся,
source lock не запрашивается, cursor не меняется. При READY dispatcher берёт
eis-priority.lock nonblocking: занятый freshness/deploy не прерывается и его
marker не удаляется. Владелец lock создаёт existing eis-priority.request, ждёт
eis-import.lock максимум45s и очищает собственный marker при выходе. Corpus
уступает только между atomic windows; TTL существующего marker600s страхует
аварийный выход. Рабочий шаг сохраняет один файл/run, shared60s public host lease,
DB100GiB/free40GiB/20MiB file limits. Worker JSON дополнен dispatch_law и
source_lock_wait_seconds; cooldown сохраняет family turn. Максимальный срок
получения набора не гарантирован: freshness, outage, изменения версии и retries
могут его увеличить. Полнота требований/допуск/экономика остаются UNKNOWN.

Baseline 2026-10-02T19:58:52Z: selected223job32616419658v2 создан18:23:33.054680Z;
7последующих receipts с18:24:40.444858Z до18:51:04.603392Z: first67.390178s,
last1651.548712s (27m31.55s). Один более ранний manual receipt исключён из
ожидания очереди. Из последних120lines лога100JSON outcomes:53IDLE,
40SERVER_IMPORT_BUSY,1ROBOTS_CRAWL_DELAY,6PROCESSED. Лог исторически не имеет
timestamps, это sample, не суточный процент. Старые44jobs включают предыдущий
outage и не являются сопоставимым latency benchmark. Read-only baseline на VPS:
research/223/local-eis-supplier/s161-baseline-20261002T195852Z.json,
SHA9f33d08de0b98b831bb82bd76ff2e96b88f2d7c153c8e09104bfbe43c51ad11e.

Deployed S161:42local/57isolatedPG/55Linux, Ruff/mypy passed; новая schema не
нужна,HEAD20261002_10. Code backup2.7MiB; все server shell0700/bash-n/test-x,
testDB удалена. Live selected44job0151300010626000053v1:4/4received за333.453342s,
first5.351735s; remainingfiles штатнымcron. Freshness20:12–20:13 сохранён;
doc lock wait25s в20:15, corpus skipped0attempted поmarker. Итоговая очередьIDLE,
marker очищен; idle probes0.219263/0.180827s не меняют counts/audit.
Mixed API comparison0.085691s,4полученных files44 +8files223, no writes.
XLS formulas/media и DOCX external links оставляют extraction UNKNOWN;
download complete не утверждает полноту разбора/ТЗ/eligibility/economics.
Final proof:s161-live-20261002T201552908629Z.json,
SHA192ae79595b08f0277a407f6380175a3240429fc1fbe30e0139317313bb0a440.

## S166: freshness probe до вытеснения corpus

Обычный cron server-eis-priority.sh сначала читает tenant due attempts и
foreground requests через procurement.eis_freshness_dispatch_cli в работающем
API container. READY означает наличие работы, IDLE — отсутствие due работы
в текущем ограниченном scope, BLOCKED — ресурсный/технический stop. Это не
оценка полноты ЕИС. Probe не вызывает journal.plan, не пишет audit/targets,
не открывает Chromium/ЕИС и не создаёт/удаляет priority marker. Отсутствующая
запись target считается unattempted; учитывается foreground вне baseline.

Только READY после проверки proxy вызывает marker и ожидание import lock.
Worker повторно выбирает due под lock; marker убирается своим EXIT trap.
Занятый priority lock по-прежнему возвращает PRIORITY_WORKER_BUSY без cleanup
чужого marker. Custom args/--smoke используют worker validation под lock
без default-scope probe, чтобы иной scope не получил ошибочный IDLE.

Baseline остаётся 50,77,78 и пять поддержанных типов. Memory/disk/source
quota/atomic-window boundaries неизменны. Capacity status принимает все пять
типов; drift прежнего числа четыре устранён. No-data наблюдение не закрывает
coverage gap. Metadata attachments сохраняются полностью до4096; превышение
ATTACHMENT_METADATA_COUNT_LIMIT остаётся gap и получает суточный cooldown.
Document download caps этим не увеличены.

См. [архитектурный аудит](../research/41-eis-architecture-effectiveness.md),
[каналы получения](../research/42-eis-acquisition-research.md),
[контракт attachment metadata](../eis/ingestion/43-eis-attachment-limit-review.md).

## S166C: reusable corpus transport

CLI run использует один lazy Chromium transport на bounded pass. Source/
resource/priority gates и двухсекундный spacing прежние; если pass idle или
blocked до сети, браузер не инициализируется. Публичный Python caller без
transport сохраняет прежний single-window wrapper. Производительность
на большом scope надо измерять; число browser initializations само по себе
не является доказательством throughput или полноты.
См. [контракт и lifecycle tests](../eis/ingestion/44-eis-corpus-transport.md).

## S167: повторы свежих failures

Corpus резервирует min(ceil(max_windows/5),12) слотов для последних FAILED
попыток окон за7завершённых московских дней; остальные слоты идут в прежнюю
очередь. Проверяются tenant, planned target, отсутствие atomic checkpoint,
latest outcome и24hcooldown. Небольшой max_windows=1 может выбрать один due
failure; новая попытка вновь включает24hbackoff. Отбор и дедупликация идут
одним SQL в consistent read; reserve сортируется по dateDESC,attemptASC,key,
history по прежнему правилу. LIMIT применяется до служебного ROW_NUMBER.

Это предотвращает ожидание исправленных source gaps за большим unattempted
backlog. Оно не закрывает ошибку само по себе и не расширяет scope или квоту.
См. [контракт очереди](../eis/ingestion/45-eis-corpus-fairness.md).

## S168: выбор corpus без повторного MAX на каждую цель

Latest attempted_at вычисляется один раз через tenant GROUPBYwindow_key,
затем LEFTJOIN с исторической очередью. Отсутствующая attempt остаётсяNULL.
Recent FAILED lane сохраняет точный latest outcome, limit/fairness и cooldown.
Фоновый selector и пользовательский search — отдельные операции: measured
25–27s относится к предыдущему выбору source windows, не к запросу товара.
См. [SQL contract и измерение](../eis/ingestion/46-eis-corpus-selection-performance.md).

S168 production sample:147364targets/8736attempts,old27.095s/new7.471s;
exact60keys и source counters совпали при одном checked_at. Результат не
экстраполируется на миллион targets. Proof:s168-selection-proof-
20261003T085110562921Z.json,SHA258011fdc578f3ff8f501574ba28c83fb599d0ad5dfbde6becd33bd4f380607a.

## S169: общий тип 223-ФЗ на VPS

Развёрнуты API/worker/web, Alembic HEAD `20261003_01`. Выполнены backup кода и
схемы, bash-n/executable gates, 66 PostgreSQL и 397 Linux focused tests,
production build и health. Временная test DB удалена, priority marker снят.

Refresh поддерживает `purchaseNoticeAESMBO`, `purchaseNoticeZKESMBO`,
`purchaseNotice`: шесть целей на сегодня/вчера. Сохраняются регион 50,
max 2 windows / 180 секунд, расписание 11/41, global/priority leases,
DB 100 GiB / свободно минимум 40 GiB. Регионы и квота не расширялись.

Новое окно за 2 октября: один ZIP / 40 версий / 38 номеров, 38 начальных и
2 максимальные цены. XSD quality: 80 checks, 38 PASS / 2 FAIL каждой схемы.
Первый intake завершён в 09:42:41Z; ошибку post-commit proof helper исправили
проверкой точного immutable response без повторного запроса к ЕИС.
S152 SOURCE_REJECTED history не переписывалась.

Один публичный ТЗ DOCX нового семейства скачан и разобран: 32 фрагмента,
1/8 файлов, полный комплект и требования UNKNOWN. API и UI проверены.
Proof paths и hashes — в [плане S169](../15-implementation-plan.md).
Свободно около 263 GiB; API около 109 MiB, web 63 MiB, DB 607 MiB.
Полнота ЕИС и актуальность всех отмен не подтверждены; следующий этап —
отдельный контракт событий и региональной сверки.


## S170: отмены223 — операционный контракт

Код добавляет отдельный event family purchaseRejection, region50. Refresh рассматривает
только today/previous day: шесть notice targets и два cancellation targets, общий
порядок oldest observation; **2 windows / 180s**, прежний cron и disk/DB quotas.
Notice enum не расширяется. Журнал event attempts и checkpoints отдельный;
SYNCED означает полный сохранённый returned set, не актуальность/полноту ЕИС.
NO_DATA не означает отсутствие отмен. Naive timestamps не получают угаданную зону.

Full-XSD offline: до двух notice и двух event variants последовательно, до30s на
каждую очередь, без source requests. Ошибки схемы сохраняются отдельно от intake.
EventGUID/XMLSHA variants immutable; совпадающий GUID с другими bytes/номером
создаёт UNKNOWN+hold. Hold исключает document jobs из pending/dispatch, повторно
проверяется перед HTTP и сохраняет уже полученные документы.

Новая миграция20261003_02 использует FORCE RLS/compositeFK/immutable triggers.
Downgrade запрещён при history любого tenant. Deploy требует обычных priority/import
leases, code/schema backup, script gates, migrate/health; source probe bounded.
Текущий live outcome и fingerprint записываются в docs15 после deployment.


S170 deployed03.10, HEAD20261003_02. Реальный cancellation source event region50
за01.10 сохранён целиком (18,753bytes), обаXSD PASS; naive времена => UNKNOWN+hold.
За02.10 NO_DATA. Fingerprints и gates75PG/423focused в docs15; fullcoverage UNKNOWN.
Оба probes под общими leases; marker снят, тестоваяБД удалена. ДанныеVPS-only.


## S171: отмены лотов223 — развёрнуто03.10, HEAD20261003_03

purchaseLotCancellation имеет свои пять immutable tenant/RLS таблиц, общий raw
blob store; notice и whole-purchase event family остаются раздельными.
Refresh рассматривает10 today/previous-day targets: шесть notices, два whole
и два lot events. Они делят прежние2windows/180s, cron11/41 и disk/DB budgets.
Offline event quality не удваивается: до2variants выбранной family за проход,
whole в первой половине часа, lot во второй; notice quality2 прежние.

Любое связанное lot event требует сверки UNKNOWN. Документные jobs имеют
notice scope и отдельный LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED; selected
lot estimate использует собственный UNKNOWN hold. Coincident GUID/ordinal
не разрешает операцию, не доказывает отмену всей закупки или восстановление.
Before-HTTP/receipt commit повторно проверяет состояние под company lock.
Search читает bounded metadata до JSON:2000rows/100variants-per-number/8MiB
serialized snapshot budget; overflow UNKNOWN hold без частичного evidence.

Migration20261003_03 downgrade запрещает потерю lot history любого tenant.
Backups/build/migrate/health/hashes PASS,84PG/454Linux. Оба live окна01/02.10
вернулиNO_DATA; реальный XML отмены лота пока не подтверждён. Synthetic full XSD
и cached API/UI proof — docs15/docs53. ТестоваяБД удалена, priority marker снят.

## S172: общая региональная очередь223

Границы и live outcome — docs15; officialcatalog/mapping — docs54, architecture — docs55.
`server-eis-223-refresh.sh` включает EIS_223_REGIONAL_ENABLED=1; отсутствующий
проверенный catalog останавливает worker с OFFICIAL_REGION_CATALOG_MISSING,
не подставляет01..99.900frozen targets автоматически из90observedcodes,5families,
2dates; sharedlease и прежние cron11/41 сохраняются.32windows/600s startbudget,
<=180s bounded started-window overrun, CPU2/mem2GiB, DB100GiB/free40GiB perwindow.
No unbounded fanout, no attachment download, no bulk laptop data. Retained controls
admitted without network replay. API coverage readonly/tenant/no-store; sourcecalls0.
Каталог snapshot пока bootstrap; периодический refresh каталога и bounded raw
retention остаются следующим bounded slice. При stalecatalog нет fullcoverageclaim.

03.10.2026 S172 deployed, HEAD20261003_04; первый32-window run завершился
за331.323s (8SYNCED/24NO_DATA/0errors),102newversions. Coverage44/900,
856pending; index330current после admission controls и общегоrun. UI проверен
через SSH tunnel3000→13000. API no-store/health PASS; disk/source/CPU caps не
повышались. Proof paths и measured timings в docs15. Это не полный охват ЕИС.

## S173: каталог и регулярное обслуживание очереди

Новый HEAD20261003_05 добавляет immutable tenant/RLS журнал проверок публичного
selector. Успешная проверка повторяется через24h, failure/review — через1h.
ТочныйGET без token ограничен45s включая startup,512KiB streamed body;redirect,
не200 и другойURL отклоняются. Исчезновение ранее принятых кодов даёт review;
предыдущий каталог продолжает обслуживаться. SameSHA создаёт новое наблюдение,
не переписывает raw body или frozenwave. История запрещает destructive downgrade.

Новая cadence: `1,11,21,31,41,51 * * * *`, одна223entry. Установка:
`python3 scripts/server-eis-223-refresh-cron.py --apply` — меняется только точный
старый223command; прочиеjobs/comments сохраняются. Default без--apply показывает
безопасный summary.32windows/600s и<=180s started-window timeout,2GiB/CPU2,
sharedimportlease/45s wait,2s spacing, DB100GiB/free40GiB perwindow неизменны.
Overlappingrun ждёт/пропускается, а не создаёт fanout. Больше sharedlease time
может задержать44loader: надо измерять фактическую конкуренцию/skip, не SLA.

Earlyfresh1/retry1 приlimit>=3, остатокunseen; limit2 сохраняет retry/unseen.
После firstsweep и сменыMSKday новаяwave появляется без старого24h wall-clock
ожидания; end_day>=today ограничиваетcurrentwave, catchup<=2days иoldgaps сохранены.
Ceiling32×6=192windows/h, потребность900/6h=150/h; это расчёт ёмкости, не обещание.
UI показывает initialcatalog time, recheck точногоSHA и latestaccepted time
отдельно от неизвестной свежести карточек. Live outcomes/proofs — docs15.

Retention rawarchives/metadata, полный первый sweep, other223families/44parity и
реальная stablelotassociation ещё не завершены. Каталог проверяется автоматически;
такая проверка сама по себе не подтверждает полноту или актуальность всех закупок.

## S174: передача общего source lease

Один import lock по-прежнему сериализует source calls.223 wrapper сначала берёт
отдельный `eis-223-dispatch.lock` неблокирующе; второй запуск не трогает marker
первого. Read-only probe в API с5s SQL timeout проверяет due windows, catalog
refresh и новый календарный wave; IDLE и invalid probe не создают demand.
Только владелец dispatch выставляет `/var/lib/eis-browser/eis-223-refresh.request`.
EXIT/INT/TERM cleanup снимает собственный marker и завершает/reaps flock waiter.
Не удалять44priority marker из223wrapper.

Corpus получает дополнительный `--regional-request`; перед каждым новым atomic
window сначала проверяет44priority, затем223demand. Оба hints действуют0..600s;
stale/future marker не меняет очередь. `REGIONAL_REFRESH_REQUESTED` означает
передачу lease, а не failed source или потерю уже принятого archive set.
223 ждёт import до300s, без очереди дубликатов. После получения lease выполняет
один atomic window, затем при44priority не начинает следующее и пропускает
offline quality. Перед optional quality marker проверяется снова, в том числе
после последнего выбранного окна. Resource caps и immutable journal неизменны.

44document wait тоже300s; существующий document dispatch lock ограничивает
одного ожидающего. Freshness остаётся300s. Shell wait223 прерывается TERM,
cleanup завершает принадлежащий ему flock subprocess. SIGKILL/power loss не
выполняет trap: stale marker истекает600s. PID/lane locks — host operational
coordination; это не evidence закупки, approval или гарантия FIFO.

223 report добавляет UTC dispatch_requested_at/lease_acquired_at/worker_finished_at,
source_lock_wait_seconds и lease_work_seconds. Последняя метрика измеряет worker
часть под lock; cleanup/финальное закрытиеFD в неё не входят. Ожидание300s и
window source timeout180s не дают жёсткого SLA commit/browser cleanup. Точный
scope и остаток смотрятся в coverage API; whole-EIS coverage остаётся UNKNOWN.
Фактические rollout/gates фиксируются в docs15, исходный measurement — docs57,
решение — ADR0057. Изменения cron, source caps и схемы для этого slice не нужны.

S174 deployed03.10:76LinuxPASS, api/worker build/health/hash gates. Реальный
wrapper дождалсяlease18s, сохранил12окон/13новыхверсий за90.614s и уступил
44priority; duplicatecron не снялmarker владельца. Последующий44run завершил
10NO_DATAокон, ошибок в этом run0. Снимок20:34:18UTC: обаmarkers сняты,
278/900terminal223/622remaining/0latestfailed223. Дальнейшийsweep выполняет
обычный10mincron; этот результат не подтверждаетfullEIS или6h freshness.

## S175: сохранение спорных выгрузок (04.10.2026)

`EIS_REJECTED_EVIDENCE_DIR` включает сохранение отклонённого полного набора ZIP.
По умолчанию функция выключена; compose задаёт на VPS каталог
`/var/lib/eis-browser/rejected-evidence` в существующем volume. Ноутбук архивы
не получает. Первый контракт охватывает только `DUPLICATE_NOTICE_VERSION`,
`DUPLICATE_NOTICE_VERSION_IN_WINDOW` и `NOTICE_VERSION_CONFLICT` после
отказа preflight либо отката транзакции импорта. Другие ошибки не обходят свои
проверки и не получают фиктивное подтверждение сохранения.

Внутри каталога данные разделены по компании. ZIP хранится по SHA256;
manifest связывает компанию, окно, initial/prepared response SHA, упорядоченные
официальные URL и SHA всех ZIP, причину отказа и первое время сохранения с
часовым поясом. `manifest_sha256` — SHA256 фактических байтов файла, без
самоссылочного поля. Содержимое XML и URL не выводятся в тексте ошибки.
Операторская классификация членов архива — отдельное evidence в docs58.

Лимиты: 20 ZIP, 50 MiB на ZIP, 64 MiB на полный сжатый набор, 128 MiB после
распаковки, 32 MiB на member, 1000 members на ZIP и 5 GiB на весь каталог.
Содержимое и имена members проверяются на отражение токена до записи.
Файлы имеют Linux mode 0440, каталоги 0700; существующие SHA, размеры, пути и
режимы проверяются. Временные файлы публикуются без замены существующего файла;
manifest записывается последним. Ошибка записи или синхронизации каталога
возвращает `FAILED`, а не `RETAINED`. Повтор проверяет полный набор и сохраняет
первый `observed_at`.

После сохранения создаётся неизменяемый tenant audit с идентификатором от
компании и manifest SHA. Файлы и PostgreSQL не образуют общую транзакцию:
если audit не записан, файлы могут остаться. Отчёт явно показывает отдельно
статус сохранения и audit; повтор связывает сохранённый набор без повторного
скачивания и дополнительного audit event. Автоматической очистки нет: при
достижении 5 GiB новый набор не сохраняется, исходный конфликт остаётся видимым.
Расширение квоты или удаление evidence требуют отдельного решения о retention.

FAILED journal теперь получает проверенный source response SHA. Corpus report
содержит `rejected_windows` с безопасными статусами; freshness observation
содержит manifest SHA и статусы retention/audit. Ни сохранение, ни audit не
создают успешный checkpoint, новые карточки или допуск к участию. Исторические
FAILED attempts не переписываются. Lease, cron и общие resource caps прежние.

S175 deployed04.10:77Linux/20isolatedPG PASS, backups и host/runtime SHA gates.
Полный retained набор5ZIP успешно сохранён через deployed hook без sourcecalls;
повтор не пишет файлы и audit, index/checkpoint/attempts не меняются. Проверены
file fsync после readonly mode и sync обеих directory branches при replay.
Прошлый44 gap остаётся FAILED; его исторические8attempts не переписаны.
Proof paths/hashes и итоговый API smoke — docs15/58. Тестовая БД удалена.

## S176: четыре архива в notice223 window

Notice-only cap изменён с2до4 согласованно в binder, ReadyWindow и DB CHECK
миграцией20261004_01. Общие пределы:32MiB compressed,128MiB expanded,
400members; perZIP16MiB compressed/32MiB expanded/200members и perXML4MiB
прежние. Budget128MiB принят явно по retained real evidence; общий cgroup
2GiB не менялся. All ZIP headers проверяются до parsing, cumulativecompressed
проверяется послеGET до следующего запроса. Wrong/partialset — SET_MISMATCH,
согласованныйset>4 — COUNT_LIMIT. Resource reason codes видны в worker report.
Окна отмен и отмен лотов по-прежнему max2.

Перед schema change — backup кода и schema-only dump; это не data backup.
Downgrade к cap2 отказывается при wider source history любой компании;
не удалять и не переименовывать immutable данные ради downgrade. При отсутствии
гарантированной RLS visibility guard также должен отказать. Новую migration
выкатили после139Linux/21isolatedPG PASS и memory gate:полный cached fetch/
ingest/replay с residentChromium~328MiB peak при2GiB и7.220s, без sourcecalls.

Exact retained source window77/02.10/purchaseNotice принят целиком,365новых
XMLversions;8старыхFAILED сохранены,1новыйSYNCEDattempt. Replay0new,old_gaps0.
Coverage/freshness всейЕИС UNKNOWN; обычныйcron/familylanes/sourcelease прежние.
Proofs/sourcebytes/resourceконтракт подробно — docs59/ADR0059, live status — docs15.

## S177: offline диагностика отклонённых извещений 44-ФЗ

Диагностика использует уже сохранённый полный набор; дополнительных запросов
к ЕИС не выполняет. Запуск в rejection hook разрешён только после RETAINED
и успешного audit карантина. Отдельный immutable audit фиксирует полный отчёт,
точный manifest SHA и source coordinates. Corpus показывает aggregate counts
и diagnosis SHA; freshness observation — SHA и audit status. Ошибка диагностики
видна отдельно и не меняет исходный FAILED, backoff или checkpoint.

Повтор допускается без нового source fetch: сначала проверить SHA всех ZIP
и manifest, использовать прежний tenant/window, затем вызвать тот же hook.
Нельзя переписать manifest, исторические attempts или выбрать XML по времени.
Установленные caps источника, retention quota и общая память worker прежние.
Подробные результаты gates и deployment — docs61 и live plan.

S177 deployed07:49UTC:158Linux/22isolatedPG PASS;real499XML/replay с Chromium
~365MiB peak при2GiB. Один новый diagnosis audit, без новых source calls и
index/checkpoint/attempt writes. Schema HEAD прежний20261004_01; original44gap
FAILED. Host/runtime hash gates и API smoke PASS, markers сняты. Диагностический
COMPLETE относится только к inventory, не к полнотеЕИС или source admission.

## S178: evidence-only ledger вариантов44

Migration20261004_02 добавляет три tenant-scoped immutable таблицы с RLS FORCE.
Реестр принимает только полный набор с ранее записанными retention/diagnosis
audits. Автоматический intake hook и consumers не переключаются. Операторский
retained replay не выполняет source fetch, не пишет canonical checkpoints и
sync attempts. Receipt COMPLETE не означает SYNCED. Подробности — docs62.

Перед migration — code backup и проверенный schema-only dump (не data backup).
Непустой ledger блокирует downgrade до удаления любого schema object; история
в другой компании не должна скрываться RLS. Для recovery откатывается код,
immutable evidence и schema с историей сохраняются. Настройки cron/lease и
resource budgets прежние; raw ZIP находятся на VPS.

S178 deployed04.10.2026 08:54UTC, HEAD20261004_02. Gates54Linux/36isolatedPG,
Ruff/mypy/architecture review PASS. Проверенный retained набор5ZIP/499XML
записан как499variants/499origins/1receipt/1audit; replay0writes/sourcecalls0,
canonical index/checkpoint/attemptdelta0, прежние8FAILED сохранены. Peak~364MiB
при2GiB с Chromium. Test DB удалена; markers сняты; API200/anonymous401/no-store.
Coverage/freshness всейЕИС UNKNOWN. Backup/proof hashes и границыM1 — docs62.
До shared consumer hold и отдельного ADR не включать ledger intake в source hook.

## S179: общий consumer hold evidence-only вариантов44

Deployed04.10.2026 09:32UTC, schemaHEAD20261004_02 прежний. 172Linux/52PG,
scoped Ruff/mypy и независимый review PASS. Held rows исключаются до ranking;
exact cached reads и final receipt повторно проверяют hold. Ledger/document/
projection writes используют общий tenantlock. Worker held audit sample≤50,
normal queue исключает holds до LIMIT; readonly probe без audit. Latehold не
записывать какFAILED. APIhold422/no-store с явной причиной, включая live-number.

Metadata guard не читает XML/fullJSON; held count от ledgerkeys+currentjoin.
Singleton evidence-only; incomplete receipt удерживает tenant. Retainedproof
все12tabledeltas0/source0; canonical gap FAILED. Cron/budgets/intake прежние.
Backup/proof/timing — docs63/ADR0062; coverage/freshnessUNKNOWN. TestDB удалена,
markers сняты. Следующее включение intake требует отдельного ADR допустимости
canonical projection; текущий consumer guard не включает этот intake.

## S180 M1: retained transport/projection

Контракт/implementation — docs64/ADR0063; operator M1 deployed and verified.
Новый feedwindow intake_kind отделяет полный VARIANT_TRANSPORT от обычного
LEGACY_CANONICAL checkpoint. Ни один completion reader не закрывает gap по
transport-only. Operator batch сохраняет full ZIP/XML counts; canonical admission
отдельными audited immutable decisions. Новый guard использует exact audit JSON
membership, singleton history и canonical/origin binding; latest variant reholds.
Source hook/cadence не переключены. Миграция HEAD20261004_03; после появления
transport/projection истории downgrade запрещён глобально. Исправления — forward.
Proof на VPS под общим priority/import lease, sourcecalls0; raw ZIP не копировать
на notebook. 2GiB worker cap/Chromium memory gate; cron/budgets прежние.

04.10.2026 10:41UTC: HEAD20261004_03/API+worker rebuilt, host21/runtime11 hashesPASS.
176Linux/68PG=244tests/Ruff/mypy/review PASS. Backup prefix
`/home/syurai/vibe-seller-state/backups/s180-before-20261004T104122Z`;
точные SHA и proof paths — docs64. Production proof:497PROJECTED/1HOLD,
all499XML/498decisions retained, replay13table deltas0/source0/checkpointfalse.
Final API smoke10:46:57UTC:44current128803, бумага5.811s/2477,
сервер12.216s/5232;223current2882, бумага218ms/59, сервер573ms/184;
health200/anon401/no-store/markersfalse. Coverage/freshnessUNKNOWN.
Test DB `procurement_eis_test_20261004_s180` удалена после gates.
Следующий M2 включает live hook отдельным bounded slice; M1 автоматический
intake не переключает и полного охвата ЕИС не подтверждает.

## S180 M2: автоматическая проекция notice44

M2 deployed and verified; production/retained/live/API gates PASS. Docs65/ADR0064
описывают четыре eligible notice reasons, reuse exact audited transport и
typed partial intake. Source window остаётся FAILED/pending даже при held=0;
PARTIAL не завершает ordinary checkpoint. Все stage failures останавливают pass;
DB failure не маскировать source conflict. Original source reason сохраняется.
Счётчики new_versions — реальные новые записи, replay не увеличивает их;
held_pairs — per-run исторические batch counts, не глобальный consumer hold.
358 focused Linux/PG gates PASS; новая DB схема не требуется, HEAD20261004_03.
Перед rollout нужен полный real retained proof/Chromium2GiB, backup и hash gates.
Cron/budgets/regions/families/spacing прежние; сырые данные остаются на VPS.

Deployment12:37:53UTC, backup prefix `s180-m2-before-20261004T123753Z`;
host21/runtime8 hashesPASS, API+worker rebuilt. Production retained: all13table
deltas0/source0/oldHOLD/checkpointfalse. Actual getDocsIP12:40:18UTC:5ZIP499XML,
0PROJECTED497REPLAYED1HOLD, typedattemptFAILED/new_versions0/old8FAILEDpreserved,
37.43s/peak526MB2GiB. FinalHTTP44current130458 paper7.637s/server14.218s,
2232882current/310ms/540ms; health200/anon401/no-store/UNKNOWN. TestDBm2 удалена.
Proof paths/SHA — docs65. Priority markerfalse;223refresh marker при API снимке
true; не удалять marker другого штатного прохода. Следующий срез измеряет lag и
partial outcomes, затем bounded backfill/parity и отдельно большой searchindex.
Final operations12:44:23UTC: оба markersfalse, testDB отсутствует; HEAD03
подтверждён owner read. App role не имеет доступа к alembic_version, читать эту
таблицу для operational gate через owner, не расширять runtime privileges.

## S181 — gap census / historical source retry, deployed 04.10.2026

`python -m procurement.eis_corpus_cli gap-status --company-id local-eis-supplier
--actor-id operator --sample-limit 20` — read-only tenant queue census, source token
не требуется. Totals/groups полные, samples bounded; UNKNOWN coverage/freshness.
Выполнять как обычную worker CLI с DATABASE_URL runtime, не печатать credentials.

До3historical transient slots на60run, latestexactFAILED transport/WSDL либо
SERVICE_ERROR/PREPARING, cooldown24h и date<MSKtoday−7. Новый reserved lane не
допускает parser/conflict/NO_DATA; обычный backlog прежний. Legacy checkpoint
единственный completion. Limit1/2 сохраняют минимум ordinaryslot. Cron/budgets
прежние; HEAD03, migrations не требуются.178focusedLinux/PG PASS, Ruff/mypy PASS.

Deployment13:20:27UTC backup `s181-before-20261004T132027Z-code.tar.gz`, host14/
runtime4 hashesPASS, API+worker rebuilt. Typedcensus148168planned/5040completed/
143128pending,8.357s;selector8.264s. Controlled2oldtransientwindows→NO_DATA,
oldFAILED/audit сохранены, canonicalcheckpointfalse. Followupreservedretrydue0,
NO_DATA6453; индекс не стал полным. CachedHTTP44current131573/7.7–14.6s,
2232884/295–520ms;health200/anonymous401/no-store/UNKNOWN. TestDBs181 удалена.
Нашmarker снят; activeprioritymarker следующегоcron закрыт его владельцем.
Finaloperations13:25:07UTC: обаmarkersfalse/testDBотсутствует. Proofs/SHA
и следующий boundedrepair — [docs66](../eis/ingestion/66-eis-gap-census-and-source-retry.md).

## S182 — ручное восстановление прежних attachment-count отказов

Deployed 04.10.2026, 13:52:11 UTC. Из `/home/syurai/vibe-seller`:

```bash
bash scripts/server-eis-attachment-recovery.sh status
bash scripts/server-eis-attachment-recovery.sh run 3
```

Status — typed read-only plan, без token/source calls. Run допускает 1–3 окна,
600 s gate перед следующим окном, прежние global leases и resource budgets.
Только exact latest старого `ATTACHMENT_COUNT_LIMIT`, cooldown 24 h, planned
tenant scope и завершённый interval без canonical checkpoint. Перед source call
eligibility проверяется повторно. Новых cron/migrations нет, HEAD03.

251 focused Linux/PG tests PASS, Ruff/mypy и release review PASS. Backup prefix
`s182-before-20261004T135211Z-code.tar.gz`, host12/runtime2 hashes PASS.
Первый live pass: 3 SYNCED окна за39s, 5 ZIP/398 новых versions, actual canonical
receipts/audit проверены, все9старых FAILED сохранены;6окон остаются eligible.
Max193/240/278 metadata references не означает загрузку этих файлов.
Cached API44current132982/8.4–14.7s,223current2887/302–615ms,
health200/anon401/no-store/UNKNOWN. TestDBs182 удалена, финальные markersfalse
13:57:37UTC. Proof paths/SHA/контракт — [docs67](../eis/ingestion/67-eis-attachment-recovery.md).

## S183 — оставшиеся старые attachment-count окна восстановлены

04.10.2026: два последовательных `run 3`, 46 s/31 s. Все6 окон SYNCED,
actual canonical/source SHA/journal/audit подтверждены; 573 новых versions,
10 ZIP/582 notice records. Два часа77/EOK подтвердили уже сохранённые извещения
без новых versions. Все9 исходных FAILED сохранены; recovery status eligible0.
Runtime/cron/budgets/schema не менялись, rebuild не выполнялся.

Полный planned census:148168targets/5088canonical/143080pending,
136544unattempted/6472NO_DATA. 45invalidreferences и5unsupportedmembers
требуют отдельной диагностики. Полный охват/freshness UNKNOWN.
CachedHTTP44current133474/8.4–14.6s,223current2894/282–645ms;
health200/anon401/no-store. Operations14:09:55UTC:DB3698105367bytes,
free265857155072bytes,notestDB/bothmarkersfalse. SQL/hash/head receipts и
proofs/SHA — [docs67](../eis/ingestion/67-eis-attachment-recovery.md#s183--завершение-восстановления-старых-отказов).

## S184 — parser diagnostics и source display filenames

Deployed04.10.2026 14:38:05UTC;181focusedLinux/PG gates PASS, Ruff/mypy/review PASS,
host15/runtime4 hashesPASS,HEAD03. Новая pure function
`diagnose_eis_parser_window` возвращает typed source-bound flags/totals/samples,
admissionNOT_ENABLED. Проверяет все ZIPheaders и streamingnode/depth limits;
не открывает unsafe/oversized members. Исходные filenames с `/` сохраняются в
metadata, documentworker до download выдаёт ATTACHMENT_FILENAME_REQUIRES_REVIEW;
analysis/reanalysisUNKNOWN, label не преобразуется в локальный путь.

Diagnostic3captures:33.044s6SOAPPOST/5ZIPGET,no-intakeSQLcounts0;один controlled
live42Sep7EZK→SYNCED8.372s37newversions,8slashlabels preserved,50oldrecordsimmutable.
Новые budgets/cron/schema отсутствуют. Backup prefix
`s184-before-20261004T143805Z-code.tar.gz`. Fullplanned queue:
148183targets/5105canonical/143078pending,44references/5membersremain,UNKNOWN.
CachedAPI44current134030/8.5–15.6s,2232898/227–643ms;health200/anon401/no-store.
TestDBs184 удалена;finaloperations14:44:00UTC обаmarkersfalse,DB3.71GB/free265GB.
223cron marker снят владельцем штатно. Privateproof paths/SHA — [docs68](../eis/ingestion/68-eis-parser-gap-diagnostics.md).

## S185 — bounded metadata recovery на сервере

Operational cohort зафиксирована по39 прежним region42 reference failures.
Root-owned private helpers в `/home/syurai/vibe-seller-state/s185-*.py/.sh`;
baseline/pass/SQL receipts — `/var/lib/eis-browser/research/rejected/s185-*.json`.
Reports immutable; source bytes не передаются на ноутбук. Каждый source pass
максимум3 окна,600s gate, shared priority→import lease, DB100GiB/free40GiB.
Deployed S184 runtime/schema/cron/CPU2/memory2GiB не расширяются.

Первый interrupted pass обнаружил source duplicate. Проверенный existing
variant receipt сохраняет35projectedpairs и1HOLD без canonical checkpoint.
After independent review продолжение разрешено только для distinct unattempted
frozen cohort keys; конфликт не refetch. Validated full receipt/diagnosis/origins,
projection audit exactpayload и actual HOLD UNKNOWN проверяются до следующего
call. `FINISHED_WITH_GAPS` не означает завершённый source window. Иной source,
DB или proof error останавливает цепочку. Original50attempts не меняются.

Read-only preparation будущего SQL deadline scope:16:20:49UTC, paper2668token
candidates/816future,servers5806/1754future;expired1852/4052,unknown0,fallback0.
Это около70% fewer hydrated candidates, а не подтверждённое latency ускорение.
Scoped/history switch и exact parity/API/UI/benchmark — следующий S186.
Подробный контракт и proofs — [docs68](../eis/ingestion/68-eis-parser-gap-diagnostics.md#s185--восстановление-подтверждённой-группы-metadata-gaps).

S185 final:39unique frozen keys processed,38canonical/2046newversions плюс
35partialversions/1HOLD без LEGACY;region42references0,globalreferences5/members5.
14passes/463.021s. SQLall39/source/journal/audit/fullpartialproof/50oldrecords PASS.
Queue148213planned/5210canonical/143003pending; cached44current138253
paper8.323s/server15.693s,2232901paper280ms/server510ms;UNKNOWN.
Finaloperations16:25:03UTC:DB3.81GB/free264.95GB/no testDB/bothmarkersfalse.
Sourcebytes остаются VPS; configuredmemory cap не означает измеренныйpeak.
Runtime/schema/cron unchanged, independentreviewPASS; no new producttests/rebuild.
Final receipts SHA — docs68. Следующий S186: SQLdeadline scope + historicalmode,
exactparity и measuredbenchmark; fullcoverage/fullcomparison не подтверждены.

S186 cached search: SQL deadline scope реализован до snapshot hydration;
API/UI default NOT_EXPIRED_OR_UNKNOWN, explicit ALL_CACHED history.
44 Linux +26 PG tests PASS; real frozen benchmark exact full parity PASS,
5-run medians paper3.609s/server6.576s/paperA4804.004s против8.072/15.588/9.279s.
Source requests0, DBwrites0, schema HEAD20261004_03 и budgets прежние.
Deployment/API/UI/operations и independent review PASS. Host14/API2/web3/
worker2 hashes verified, productionwebbuild PASS, HEAD03 без миграций.
APIactualdefaultpaper3.806s/server7.005s; historytoggle UI823→2671matches PASS.
Operations17:06:19UTC DB3.81GB/free264.06GB/no testDB/bothmarkersfalse,
API/web OOMfalse,caps1GiB/768MiB unchanged. SSH localhost3000→VPS13000
восстановлен, binding127.0.0.1. Source requests/documentjobs0 в проверках.
Backup/receipts/EXPLAIN/limitations — [docs69](../eis/search/69-eis-search-deadline-scope.md).
Следующий S187 — уменьшение повторной стоимости hold/discharge SQL с exact
parity и прежними блокировками. Fullcoverage/freshness/profit UNKNOWN.

S187 deployed: один named cursor на ordered candidate SELECT, event reads на
той же tenantRRconnection, closefinally. 87distinctLinux/PGtests и Ruff/mypy PASS;
all6fullresult/payloadparity PASS. Five-run defaultpaper2.931s/server5.081s/mixed3.184s,
18.43%/22.58%/17.88% gain;20%targetpaper/mixedMISS явно сохранён. Allmediansimprove,
resourcecaps прежние, independentreviewPASS. OrdinarySELECT/DECLAREplansразличны:
cursoractualtempI/O/servermemoryUNKNOWN. Details — [docs70](../eis/search/70-eis-single-cursor-search.md).
API+workerbuilt/APIupdated, web unchanged; host12/API1/web3/worker1hashPASS HEAD03.
ActualAPIpaper3.313s/server5.032s, auth401/invalid422/223200/health200/no-storePASS;
UIdefault/history823/2671matchesPASS,refreshunchecked,returndefaultverified.
Operations18:16:17UTC DB3809008663/free263241908224bytes/no testDB/bothmarkersfalse;
API/webOOMfalse,caps1GiB/768MiB unchanged. Foregroundsource0/docjobs0/writes0;
backgroundcron/sourcebudgets прежние. SSHlocalhost3000forward восстановлен,
bound127.0.0.1. Backups/proofsSHA — docs70. СледующийS188 — freshgap/lagcensus,
известные5reference/5membergaps требуют exactlatest проверки перед recovery.

S188 read-only census/lag classification VERIFIED, без runtime/source/cron changes.
Planned census148243=5221canonical+143022pending,10parser keys unchanged;
V2 planned predicate fixed, v1 preserved. Latest3completed dates:1188attempted,
509canonical/678NO_DATA/1conflict. National daily4families excludesEOK; hourly
targets/attempts за сегодня только50/77/78. Recent30hourkeys29NO_DATA1SYNCED/due0;
13h/7h canonical distance объяснён subsequentNO_DATA, freshnessUNKNOWN.
RetainedtwoS184samples hash/binding/limitsverified,8withoutmatchUNKNOWN,
all10historicalsourceSHA NULL => no exact historical reconstruction/admission.
24h3317attempts/1037firstcanonicalkeys, automatic/manualactors отдельно.
Ruff/compile/bashsyntax/reviewPASS; runtimeAPI/web/workerhashesHEAD03 unchanged.
Operations18:34:30UTC DB3809287191/free263259516928bytes,notestDB/markersfalse,
API/webOOMfalse/capsunchanged. Foregroundsource0/writes0; backgroundcron работает.
Следующий S189 — feasible nationalcadence и dry-run, учитывая совместный lease,
priority288/h/corpus240/h caps и EOKgap. Proofs — [docs71](71-eis-fresh-gap-and-lag-census.md).

S189 deployed daily5 completeddates with EOK, conditional historicalanchorfirst/
recentnewsecond and40%newcap while ordinaryolderbacklog remains. Missing288EOK
keys planned/additive/repeat0/exactaudits;candidate01–99unverifiedregistry,
1485expected/planned threecompletedMSKdates. PG35/Ruff/mypy/reviewPASS;
actualSELECT3/60=8.592/19.406s,notSLA/speedup. Badnestedloopquery fixed beforedeploy.
APIworkerimagesrebuilt/APIup/webunchanged;host13/API1/web3/worker1hashHEAD03PASS.
Live3standardwindows20:16:51–20:17:26 allNO_DATA exactSHA/journal/audit,
noLEGACY/no versions;boundedPARTIALnotfullcoverage. Independent50recordedoriginals
exactunchanged,notallhistory. APIhealth200/auth401/paper3.727s/defaultUNKNOWN.
Ops20:19:04DB3821181975/free262449061888bytes,notestDB/markersfalse/OOMfalse,
APIweb1GiB/768MiB + worker2CPU/2GiB and100GiB/40GiBdiskbudget unchanged.
Codebackup20:15:58 andreceiptsSHA — docs72. Sourcebytes remainVPS.
NextS190 sharedlease timestampedcapacity/queue-age measurement before national
currentdaywaves;daily5scope ≠fullEIScoverage/freshness/profit.

S1905Oct deployed script-only common metrics6scripts/2tests/6docs, helpersfirst
atomicreplace14/host20hashPASS at05:39:57UTC. BackupcodeSHA
d0019725e9646bff357ff9f6b75e20cf36d64074ddd86cfb96744de205352b21.
Metrics tenantfixedprivate JSONL8+8MiB, schemawhitelist/noenv/argv/URL/payload,
loggernonblocking/failopen/exactexit. Narrowpriority/docwaiterTERMcleanup,
noactiveDockercancel/noexplicitunlock/sourcebudgets unchanged.
Linux54PASS/networknone/source0; observer15checksPASS/Ruff/mypy/bashsyntaxPASS.
Ordinarycron915s21complete runs across4lanes: heldlowerboundunion557.018s,
waitmax5.731s,18IDLE. CorpusERRORcodealone notsourcefault; lateststdoutyield223
exactbindingUNKNOWN. FinalROrecent1485expected/1092planned/missing393,
nextS191 robustidempotentdailyplanning. SampleisnotnationalSLA/fullEIS.
Ops/hash/docssync receipts and replay inputs — [docs73](73-eis-shared-lease-observability.md).

S190finalgate06:02:18UTC:host20/API2hashPASS,APIwebimageIDs/workerprefixunchanged,
HEAD03/health200/OOMfalse/API1GiBweb768MiB;DB3942718487/free258988384256bytes,
testDBnone. Markerregionaltrue reflectsordinaryactivecron; noforcedcleanup.
OpsSHA f58b35d18a1f7e0c7643af0eced87e4606330b4a709761a4edb7cf1250ee1a59,
docsbackupSHA07625aa6201bc82320b2314faf00c96b7c0b0366713d01a64e35b1cdd35630ca.

S1915Oct source0 durable dailyplanner deployed2scripts, noAPI/web/worker rebuild.
74LinuxPASS, privateatomictenantcursor and<=3completedday chunks recover busy,
failure and>3day downtime. InitialfloorOct2. Crononlyplannerchangedto4-59/5,
SHA012f1ca714ea84d61df7811ab2ac2461fc518c9fc2e350a0e62be956a8a4058f.
Livepartial6new+retry90remaining/exact1485keys/0gap/96exactaudits/repeat0/IDLE;
15982oldattempts+1389oldtargets unchangedfullrowSHA. Source/resourcebudgets unchanged.
S190recent393retracted (manualdefaultEFsuffix297falsegaps); actual96EOK repaired.
GlobalS190counts/leasetimingsunaffected; oldproofs retained MISKEYED_SCOPE.
Corrected06:26censusrecent1485planned/374canonical/1015NO_DATA/96unattempted,
coverage/freshness/profitUNKNOWN. Backups/SHA — docs74.

S191 final 06:37:20UTC: host21/API2 hashes PASS, images/workerprefix/HEAD03 unchanged,
health200/OOMfalse/API1GiB/web768MiB. DB3945159703/free258990403584bytes,
testDBnone/markersfalse in RO source0/DBwrites0 diagnostic; ordinary cron continues.
Ops SHA f5feef4ce59a58ccfc5d06323fa1154b88c2f6dba3f2d9624fc1a1cb0a519f89.
Final docs-only hash seal includes this receipt and corrected S190 documentation.

S192 source-free ingestion diagnostic installed06:53:46UTC,2scripts/1test/6docs,
atomic9/host23/API2 hashes PASS,cron/sourcebudgets unchanged. Operator command:
`scripts/server-eis-ingestion-report.sh --first-day 2026-10-02 --last-day 2026-10-04`.
One tenantRR/read-only snapshot, <=1485domainkeys, private0600UUIDproof,
per-statement30stimeout. No source credentials/URL/archives in output.
27Linux/Windows tests/Ruff/mypy PASS.954s ordinarycron samecohort:
24firstattempts/23NO_DATA/1canonical;+1version/+1lexicalrow;41unattemptedleft.
DiagnosticDBwrites0/source0; backgroundworkers sourcecontinue. Lease2censored,
capacity/fullEIS/freshness/documents/profitUNKNOWN. Receipts/backups — docs75.

S192 finalops07:07:59UTC host23/API2 hashes PASS, images/workerprefix/HEAD03 unchanged,
health200/OOMfalse/API1GiB/web768MiB. DB3970284567/free258939768832bytes,
testDBnone; prioritymarkertrue ordinarycron, untouched. CronSHA unchanged.
OpsSHA e1bb4ded2779fc576e8f9c8c71bc0bd10ba014519ca14e0b95ddded53c09ebad;
receipt additions included in finaldocs-only seal, runtimebytes frozenaftergates.

S193 first-attempt selection deployed07:24:16UTC:40%->60%newquota,
oldanchorfirst/newsecond,3new2otheronlywithretry prefix; fastnewprefixotherwiseunchanged.
41unit/isolatedPG testsPASS/Ruff/mypyPASS, no productionmigration. Runtimeonefile
overlayAPI/worker pinnedbases, atomic9/host25/API2/worker2hashPASS/APIhealth200.
No sourcecadence/concurrency/caps increase; new imageIDs/rollbacktags/backups — docs76.
BeforeOct2–4snapshot21unattempted; ordinarysourcecron observation completed below.

S193967safterdeployment:8freshfirstattempts(allNO_DATA),21->13unattempted,
canonical375/lexicalrows6488 unchanged. Journal1old+8new attempts actorcorpus,
lateststdout regionalyield9/60; no throughputgain claim. SeparateOct1scope0progress.
Lease21complete/0censored/0inconsistent,source0diagnostics/DBwrites0;
backgroundsourceworkers kept running. Nextboundedcontinuation must retain original
60budget rather than add periodicpasses. Sourcecomplete/freshness/profitUNKNOWN.

S193 final07:42:19UTC host25/API2/worker2hashPASS/releaseAPIworkerIDsverified,
webimageunchanged/HEAD03/health200/OOMfalse/API1GiB/web768MiB;
DB3970808855/free258912776192bytes/testDBnone/regionalmarkertrueordinarycron.
OpsSHA6b67bcfecaa254d03866071afabeeb0b71b9807f7cfd18e3d132e2cde680f407.
No foreignmarkercleanup. Receipt additions included in docs-only hashseal,
runtimebytesfrozenafter41PASS; rollback pinned tags and codebackup retained.

## S194 — bounded продолжение corpus после yield

Script-only rollout08:14:14UTC,95Linux tests PASS/networknone/Ruff/mypy/bashsyntax;
host28hashPASS, API/worker/web images/cron/schema20261004_03 unchanged.
Новый host runner держит corpus-dispatch lease; max60totalattempts/6segments,
840s start/wait horizon, не прерывая atomic window. Priority/regional owners
завершаются до reacquisition; чужие markers не удаляются. Source failures не retry.
`run` stdout — segmentJSONL, cumulative accounting в tenant parent receipts;
plan/extend/status прежние. Дополнительный capture buffer1MiB, receiptlogs≤4MiB.

Ordinary cron08:15:01–08:27:08UTC726.332s:13+26+21=60attempts,
29SYNCED/31NO_DATA,+563versions/+14events. Source stdoutSHA+parent+60journalrows
связаны; SQLreadonlyexactwindow/timegate563versions=563searchrows.
Oct1=36attempts,Sep4=24; mainOct2–4cohort917sunchanged/regressions0.
Lease22complete/0censored/0inconsistent; capacity/SLA/fullEISUNKNOWN.
BackupSHA d393d9df41412f4b658271ec0943bed77629f10863acb6db1f726f280a495e85.
Receipts и rollbackграницы — [S194](../eis/ingestion/77-eis-corpus-bounded-continuation.md).
NextS195 проверяет bounded NO_DATA retry по прежней24hpolicy.

S194 final08:32:59UTC host28/API2/worker2hashPASS/images+cronunchanged/HEAD03,
health200/testDBnone/OOMfalse/API1GiBweb768MiB;
DB3997506583/free258867539968bytes/bothmarkersfalse/noforeigncleanup.
OpsSHA90f127620d9c92f6d1214b2e5d679bfdd56967ddcd4902f2873ce28e653cfdd4.
Finaldocs-onlyseal включаетreceipt additions,95-test runtime bytes не меняются.

## S195 — recent NO_DATA rechecks внутри repair reserve

53unit/PGtestsPASS08:54:16UTC; Ruff/mypyPASS/testDBremoved/production schemaunchanged.
Census1148recentempty due>=24h/oldselected0; candidate sameRRshadow3of60.
Reserve<=3/segment within old12repair slots; remaining<=9forFAILED, unusedslots
returned to failures; total60parent/24h cooldown/leases/cadence/resource unchanged.
Pinnedone-module API/worker overlay08:56:53UTC atomic8/host28/API2/worker2hashPASS;
web/S194runner/cronunchanged/HEAD20261004_03. CodebackupSHA
c177db13a4d08e0399b7ddada9aa8c62ff8baee96170c56191167819dec4fd26.
Ordinarycron firsttwo segments:6priorNO_DATA rechecked at09:04:16UTC,
allNO_DATA/newIDs+SHA/cooldownreset,0canonical/versions/index/events. Parent stillactive
at snapshot; no terminalparent/SLAclaim. FullEIS/registry/absence/freshnessUNKNOWN.
Operator evidence/rollback scope — [S195](../eis/ingestion/78-eis-recent-no-data-rechecks.md).

S195 final09:07:38UTC host28/API2/worker2hashPASS/imagesverified/web+cronunchanged,
HEAD03/health200/testDBnone/OOMfalse/API1GiBweb768MiB;
DB4049787927/free258790928384bytes,prioritymarkertrueordinarycron/noforeigncleanup.
OpsSHAac66f846226cc567130975b625547ef7021114d4aaeb655a6571da3ca06aa2dc.
Finaldocs-onlyseal фиксируетreceipts, runtime frozenafter53PASS.

## S196 — повторяемый census пустых date windows

`bash scripts/server-eis-no-data-report.sh --first-day 2026-07-07 --last-day 2026-10-04`
читает tenant journal в API container: READ ONLY RR/SQL30s, no source traffic.
До90 завершённых MSK dates,495candidate date windows/day; aggregates<=450,
oldestdue samples<=20/private0600, JSON<=1MiB. Missing SHA/future attempt blocks
report. Latest before outcome; planned+tenant; any LEGACY_CANONICAL excluded,
VARIANT_TRANSPORT does not complete. Hourly/223/otheroffsets вне census.
Sparse cohorts не доказывают completion отсутствующих date/family rows.
Candidate11:27:13UTC:7341NO_DATA/1096recentdue/4399olderdue/1846cooldown;
source0/DBwrites0. Runtime/cron/images/schema not changed by diagnostic.
Contracts/evidence — [S196](../eis/ingestion/79-eis-no-data-aging-evidence.md).

S196 installed11:30:58UTC:host9/unchangedhost22/API2/worker2hashPASS,
S195images+web+cronunchanged/HEAD03/health200/testDBnone/OOMfalse.
Installedcensus11:30:55UTC:7345NO_DATA/1093recentdue/4404olderdue/1848cooldown.
ProofSHAd33c2e7ae72348f032623055da6d93791d8af9e6a476b1628261b2049983bfdd.
DB4294671383/free258531803136bytes; diagnostic source0/DBwrites0.

## S197 — ранний reserve older NO_DATA

При budget>=30 один oldest due olderempty из ordinary fill; smaller segments
без newreserve. Recent repair/transient/new quotas unchanged, total60perparent.
Exact policy/rollback/proofs — [S197](../eis/ingestion/80-eis-older-no-data-reserve.md).
SameRR shadow0->1olderempty/recent3/unique60. Source0/DB0/Ruff/mypy/66testsPASS.
Rollout11:58:44UTC atomic8/host28/API2/worker2hashPASS, S195rollbacktags,
one-module API/worker overlay, web/cron/HEAD03unchanged.
12:01:17UTC ordinarycron recheckedone olderNO_DATA withnewID/sourceSHA/24hreset,
canonical/versions/index/events0. TypedproofSHA
71a62555c6faf8d7cb29e644d24303d3201da776a45c997bf3eb5e1c91037e97.
12:01:06UTC health200/testDBnone/DB4336122903/free258470707200bytes,
regionalmarkertrueordinarycron/foreignmarkeruntouched. OpsSHA
966cc47c6398a85553ed4c90ee2787a21641e096403ecba2e8168fff0e47ed94.
Source guards unchanged, source0/DB0 diagnostic only. No fullEIS assertion.

S198: raw NO_DATA retention/audit/offline report implemented. 222Linux/isolatedPG
testsPASS12:31:53UTC, Ruff/mypyPASS; rollout/live evidence pending.
See [docs81](../eis/ingestion/81-eis-no-data-raw-evidence.md) and [ADR0079](../adr/0079-eis-no-data-raw-evidence.md).

S198 deployed2026-10-05T12:43:14Z:atomic13/host35/API5/worker5SHA PASS;
base images pinned S197, three-module network-none overlay. BackupSHA
 e8cb9394b2b9d9c5a83ee55e932ed82b6c781cca1a14887027aae05357ca9e90.
Cutover12:43:08.752311UTC:existingevidence0/storeabsent;
proofSHA2a53b1c26c738ea560673751122347c17d0daa4a9fb2db3ffd2bfd8a717bdcc3.
APIsha256:bc8e55852b9e9edc39881e7dedc62088255027226e246864653e5459cc3147d9;
workersha256:23987c6f3b8a0c074b35f6213862fad6f8d6504ee44df8ffd83e52943e59255b.
Ops12:43:30UTC:health200/HEAD03/testDBnone/DB4366883863/free258433990656bytes,
markersfalse, ordinary background cron intact. OpsSHA
4dc23fbe299e0a23aa32b1396f3b299e90cb37e1cd434b2df6ff09f63782e885.
Live raw/audit/journal verification remains pending. Source absence/fullEISUNKNOWN.

## Live acceptance — завершено

Обычный cron после cutover дал4 retained ответа, без FAILED retention на момент
2026-10-05T12:46:11.771737Z. Offline report проверил4/4 raw reparse и4/4 совпадения
с tenant audit/journal SHA/actor/window/time. Source requests0 / DB writes0 у
проверяющего инструмента; фоновые загрузчики продолжали обычную работу.
Proof: `/var/lib/eis-browser/research/rejected/s198-offline-replies-e1bc406a-4aea-4616-99aa-0663c656448b.json`.
SHA256: `2fdc6830f45cf18875bcd00055df761aa1d7a909e660bf8a2ffba9dd05a84650`.
Предыдущий snapshot12:44:42 имел0events; это последовательные snapshots, не сумма.

Store12:46:22UTC:4records, payload5169bytes, DB28672bytes; каждое исходное SOAP
тело623bytes, root0700/DB0600, journal отсутствовал на момент наблюдения.
SQLusage/count/sum паритет PASS, SQLite read-only. Metadata proof:
`/var/lib/eis-browser/research/rejected/s198-store-14010795-63da-4d1b-bcf7-6c287fb00b46.json`;
SHA256 `a126bbdd7bc8fe469c89fcf6e4108ccfa3ab20b29020c718d2ffc90349bc40f0`.
Значения4 не являются количеством всех пустых окон или исторической полнотой.

S198 завершён в описанных границах:222testsPASS + pinned deploy + real ordinary
cron + offline raw/audit/journal match. Runtime frozen после проверок; финальная
docs-only установка сохраняет35host/5API/5worker hashes и прежние cron/resources.
Независимое подтверждение отсутствия/полный охват ЕИС/общая freshness UNKNOWN.
Следующий S199: bounded operator quota/lifecycle для новых evidence, затем
отдельный контракт независимого подтверждения NO_DATA; не объявлять окна complete
по сохранённому пустому ответу.

S199 operator quota/lifecycle: [docs82](82-eis-no-data-store-operations.md),
48Linux/isolatedPG testsPASS, host-only installation pending; source0/DBwrites0.

## Live acceptance — завершено 2026-10-05

Gates48PASS13:28:41UTC (30S198 retention/offline +18S199 quota/PG checks),
Ruff/mypyPASS; isolated testDB removed, source credentials/browser paths unset.
Host-only rollout13:31:47UTC:atomic9, host38/API5/worker5 hashesPASS; runtime,
web images, cronSHA and HEAD20261004_03 unchanged. No restart/manual source pass.
BackupSHA `e2f960853f6dfc44b8781d846b3d694cd211878809fbe6d7e8dff7423a01fedd`.

Real PGsnapshot13:31:46.367122UTC / SQLite13:31:46.393039UTC:
112records, payload144674bytes/96MiB, DB278528bytes/128MiB;
rows remaining65424/65536, payload remaining100518622bytes,
DB remaining133939200bytes. Tenant112records, oldest12:45:20UTC/newest13:31:45UTC,
review-age30days rows0. RETAINED112/FAILED0; NO_DATA without matching capture audit0.
Action OBSERVE. Counts belong to these independent snapshots, not all corpus windows.

Proof `/var/lib/eis-browser/research/rejected/s199-store-health-78ca5522-c628-4696-a937-2e3a598b619a.json`;
SHA256 `fcc0cf5257592c10f399d97639c4033c01d6dc357418c38aec302d90f46ec563`.
Diagnostic source requests0 / DB writes0; ordinary cron continued in background.
Ops13:31:47UTC:health200/HEAD03/testDBnone/DB4445445143/free258312675328bytes,
markersfalse; proofSHA `8c8c1e67804efd75add3434679964facea8a1290a3cd510f84e42910f97b78d4`.
These observations do not prove independent source absence, national freshness or
fullEIS coverage; all remain UNKNOWN. S199 is complete as operator visibility /
HOLD_IMMUTABLE_EVIDENCE slice; archive export/rotation/deletion not implemented.
Next S200: independent NO_DATA corroboration contract against official source,
with exact cohort/scope/evidence and bounded source budget before completeness claims.

S200 public cross-check71Linux/PGtestsPASS13:56:38UTC, Ruff/mypyPASS;
researchDOM50/77 parsed, no scope-equivalence claim. Host rollout/live target pending.
See [docs83](../eis/ingestion/83-eis-no-data-public-cross-check.md).

## Live acceptance — завершено 2026-10-05

Host-only rollout14:01:13UTC:atomic9/host41/API5/worker5hashPASS;
HEAD03 and pinnedS198runtime/API/worker/web/cron/source worker budgets unchanged.
CodebackupSHA `ab9b62837bc0b6ab54164d4c4f5300cede4eea4e41b72886ff498f236876c510`.
Global import lease held for one manual diagnostic public navigation; no API restart,
canonical/index/audit/checkpoint mutation. Research probe earlier was one separate
navigation; these two navigations are not the complete count of browser asset requests.

Target-bound report14:01:11.851990UTC:
`getDocsIP/PRIZ/73/2026-09-02+03:00/epNotificationCancelFailure`.
Retained SOAP was verified and bound to latest tenant NO_DATA attempt/audit before
navigation. Public national44/allstages publication-day2026-09-02/page1/_50:
50scanned/50parsed/0unparsed, 27numbers in tenant versions, 23notindexed candidates.
Source count floor7300, exactfalse; do not state exactly7300 or full pagination.
These50cards are not restricted to region73/cancel-failure documents; no contradiction
or confirmed absence is inferred for the SOAP-window. New23numbers may include
unsupported methods and completed procedures; they are not participation suggestions.

DOM976052bytes, private tenant file
`/var/lib/eis-browser/research/rejected/public-no-data/local-eis-supplier/body-dab2bcb7-d88f-4001-b993-7fb317c0dbdd.html`;
SHA `4f2cb74a5a2e6e301374b8e99df1db33e2a049bfff09f3b70fa6389bf422ed2b`.
Typed proof `/var/lib/eis-browser/research/rejected/s200-public-check-60c82246-c776-421f-b885-216d6d5c41a0.json`;
SHA `e747bf27ea301f86a4087270a992533020ffb318396293a73400274f342c6b27`.
Offline verification after rollout: proof model/hash/DOM size+hash/reparse and target
retained SOAP manifest/hash PASS; source navigations0 / DB writes0 for verifier.

Ops14:01:12UTC:health200/HEAD03/testDBnone/DB4469455895/free258274816000bytes;
ordinary223markertrue, no foreign marker cleanup. OpsSHA
`bad426a59ddf20d4387e10642b2b2234c5f1923fc80ce63f775247716975dfdf`.
S200 complete as bounded access-path cross-check/candidate discovery slice.
Independent source corroboration/absence/fullEIS coverage UNKNOWN.
NextS201: bounded recovery of supported notindexed numbers, exact XML binding and
explicit evidence for unsupported cases, preserving source admission contracts.

## S201 — адресная загрузка public candidates

Контракт и команда: [docs84](../eis/ingestion/84-eis-public-candidate-recovery.md),
решение [ADR0082](../adr/0082-eis-public-candidate-recovery.md).
Host-only wrapper запускает временный worker под общим import lease; до источника
проверяет SHA/DOM/SOAP binding S200. <=3 номера/18 SOAP attempts/20 downloads,
180с network allowance, 64MiB accepted archives; whole-response overshoot считается
отдельно. Прежние admission/tenant/hold/document gates обязательны. Runtime images,
cron/schema не меняются. Проверки и bounded live acceptance завершены, результаты ниже.

## S201 live acceptance — завершено 2026-10-05

65Linux/isolatedPGtestsPASS14:41:24UTC; Ruff/mypyPASS, bash syntaxPASS.
Gate includes preservation of existing/replaced foreign markers and source0 cleanup
after import-busy. Synthetic exact notice+lexical+exact document job PASS;
foreign number/unsupported XML rejected atomically with retained evidence/audit.
Host-only initial rollout14:35:29UTC atomic9/host52/API11/worker11hashPASS;
code backupSHA `8a74bc35dfff465b7d3dbb197d9149db638430c672cf006952b5495b262490ce`.
Initial plain import wait expired after30s (source0/no report); wrapper adjusted
to existing priority lane, exclusive owned UUID marker and300s lease waits.
No runtime restart/image/schema/cron/source quota change.
Final seal14:46:20UTC: host52/API11/worker11hashPASS, pinned images/cron unchanged;
API/web running, no OOM. Seal backupSHA
`81172ad31ea6f5e5e2033adffbc168f74a5d981ed0b5b12c89966258aa8c4d93`.

Real report14:38:21.742553UTC:3 attempted numbers/6 SOAP attempts/3 downloads,
158156received+accepted archivebytes, 23.07465s worker pass (lease waits excluded).
Of S20023 missing candidates,12 already present at fresh tenant recheck,
8 unsupported route hints,3 attempted/rejected. The12 existing numbers are not new
writes attributable to this batch; indexed does not mean usable/fresh.
Attempted `0373100075926000096`, `0373100075926000095`, `0573500000526000095`:
all DOCUMENT_TYPE_UNSUPPORTED; before/after versions0/lexical0, no document queue.
All3 complete bound archives retained, all3 tenant audits RECORDED; new canonical
versions from this pass0. These historical/allstage candidates are not recommendations.

Recovery proof `/var/lib/eis-browser/research/rejected/addressed-recovery/local-eis-supplier/s201-600fa7d0-9b22-41ce-9c02-1a0fb250eed2.json`;
SHA `6ed2d640b90c005e9d30d6ef8b008ece90c8ffe30b9d8636aa98b6246f0026e0`.
Offline proof/model/input DOM+SOAP receipt/3audit payloads/3manifest+ZIP hashes PASS;
16XML members inventoried source0/DBwrites0. Types: epNotificationEOK2020,
epClarificationDoc, epProtocolEOK2020FirstSections/SecondSections/Final,
fcsPlacementResult, fcsProposalsResult. Supported notification occurs in every set;
other families block whole-set canonical intake. Nested purchaseNumber leaves are
not registry identity evidence. Need family-specific paths and official schema.
Offline proof `/var/lib/eis-browser/research/rejected/s201-offline-verification.json`;
SHA `107175bb8ee94aca306118acc444b8f63fbfe1071b5ac828cb24a69ba43ad735`.
Ops14:42:59UTC health200/HEAD03/no testDB/markersfalse;
DB4524792855/free258191085568bytes. OpsSHA
`538ed62fb21593e4e172698b95f6217a6355477ed2cb2dd9e8922597786d4891`.
FullEIS coverage/independent source absence/participation remain UNKNOWN.

NextS202: typed mixed by-number archive intake, beginning with these retained EOK
sets. Preserve every member and XML provenance; separate notification,
clarification and lifecycle/result families under explicit ADR. Unmapped members
remain UNKNOWN and cannot produce full-set/active/participation claims.
Replay stored bytes source0 first; demonstrate notice/search recovery with correct
lifecycle/hold semantics before new source requests or automatic recovery schedule.

## S202 — смешанные by-number наборы

Контракт: [docs85](../eis/ingestion/85-eis-mixed-number-archives.md),
[ADR0083](../adr/0083-eis-mixed-number-archives.md). Source0 preview/replay сохранённых
S201 наборов, migration20261005_01, pinned module overlay под всеми dispatch leases.
Companion metadata не подтверждают активный этап/participation. Source budgets и
cron прежние. Завершено2026-10-05: 95Linux/isolatedPGtests и16realXML XSD PASS.
Deploy15:46:33UTC HEAD20261005_01/host59/API13/worker13hashPASS, health200.
Source0 preview/apply сохранённых3наборов: 3newnotice versions/13companion rows,
3exactlexicalrefs/3tenant audits; ZIP158156bytes сохранены целиком. Все3expired:
FAIL/queueBLOCKED, document jobs0. Read-only proof15:48:51UTC проверяет original
bytes/13identities/prepared/sourceURL/audits; scoped title-query matches3, «бумага»0.
Ops15:48:52UTC DB4613258263/free258075906048bytes, testDB0/markersfalse.
Image IDs/backup/proof hashes: [docs85](../eis/ingestion/85-eis-mixed-number-archives.md).
Не удалять companion evidence для downgrade; использовать forward-compatible
rollback кода. Full coverage/freshness/semantic protocol analysis UNKNOWN.
Final docs seal15:50:51UTC: atomic6/host59/API13/worker13hashPASS,
API/web running/OOMfalse, image/cron pins PASS.

## S203 — исторические факты протоколов

Read-only exact-ref API из canonical ZIP: [docs86](../eis/search/86-eis-historical-protocol-facts.md),
[ADR0084](../adr/0084-eis-historical-protocol-facts.md). Source0, без новой схемы БД
и source/cron budgets. Foreground SQL/bytea/XML/rows/output ограничены.
Номер закупки не доказывает применимость протокола к версии извещения.
Завершено2026-10-05:158Linux/isolatedPGtestsPASS, Astrareview5findingsclosed.
Source0 direct/API9realXML/3exactrefs; no primary writes/new source calls.
EOK represented5/2/1; Proposals38rows repeatedIDs/countUNKNOWN. HTTP70–177ms
в одном loopback прогоне для сохранённых трёх refs, не поиск по всей ЕИС.
Deploy16:27:35UTC atomic13/host68/API16/worker16hashPASS, HEAD01 unchanged.
Ops16:28:18UTC health200/testDB0/markersfalse;
DB4682456087/free257977925632bytes. Web/cron/resources/source budgets прежние.
Proofs/images/backup hashes: docs86. UI display/cache/analog comparison pendingS204+.
Documentation seal16:30:35UTC: atomic6docs/host68/API16/worker16hashPASS;
API/web running/OOMfalse, pinned images/cron PASS.

## S204 — показ сохранённых протоколов

Реализовано: [docs87](../eis/search/87-eis-protocols-in-discovery-ui.md). Только web/BFF;
API/worker/схема/source budgets остаются S203. Сборка из pinned installed web image
в отдельном контейнере networknone/2CPU/2GiB; runtime web768MiB.
До замены image проверить тесты/TypeScript/ESLint/build и host baseline.
После замены проверить HTTP и фактический server action/UI для сохранённого
exact ref; не включать source refresh и не скачивать новые данные ЕИС.

VPS gates17:07:52UTC:8tests/TypeScript/ESLint/Next buildPASS, builder noOOM.
Deploy17:10:19UTC: atomic13/host75/web9hashPASS; web image861e3e8f348d…;
API/worker S203 unchanged. Real installed Server Action and compiled render:
3exactrefs/9protocols,4negative requests, no new source calls/DBwrites0;
132/102/88ms cached loopback reads, not nationwide/browser latency.
Visual browser check not performed: auto-review rejected local SSH tunnel start.
Ops17:13:56UTC health200/head01/testDB0/APIweb running/noOOM,
DB4809423895/free257766719488bytes; prioritymarker=true ordinary observed activity,
223marker=false. Memory/cron unchanged. Proof SHA/images/backup: docs87.
Docs seal17:16:10UTC: atomic4docs/host75/API16/worker16/web9hashPASS,
pinned images/cron/resources PASS; API/web running/noOOM.

## S205 — ограниченные исторические кандидаты через API

Контракт/evidence: [docs88](../eis/search/88-eis-historical-analog-selection.md),
[ADR0085](../adr/0085-bounded-historical-analog-selection.md). Read-only existing
lot_items projection; no archives/new source calls/schema/job writes.
SQL history/latest/holds/date/token prefilter before LIMIT21, hydrate20notices,
25positions each, payload256KiB/total2MiB/response4MiB/foreground15s/statement5s.
Missing publication stays UNKNOWN; source FAIL never overridden by rating.

193isolatedPGtests/Ruff/mypy PASS, Astra findings closed. Deploy18:39:45UTC:
atomic12/host82/API18/worker18hashPASS, head20261005_01/health200.
Three installed paper HTTP reads4066/3291/3236ms; same-time direct reports identical,
20notices/82positions each, review0/1/1; all truncated, no complete-coverage claim.
Source0/DBwrites0;52SQL/read provides next optimization baseline.
Ops18:41:42UTC DB4927994903/free257592745984bytes/testDB0;
223marker=true ordinary activity/priority=false. Memory/cron/source budgets
unchanged, S204web unchanged. Pins/proof hashes/backup: docs88.
Current backend has no analog UI; S206SQL optimization, S207UI planned.
Docs seal18:42:53UTC: atomic6/host82/API18/worker18/web9hashes PASS,
image/cron pins/resources PASS; API/web running/OOMfalse.

## S206 — SQL отбор аналогов с локальным отключением JIT

Contract/evidence: [docs89](../eis/search/89-eis-analog-query-performance.md). One storage module;
remove redundant candidate source rechecks in the same read-only RR snapshot,
preserve target assertion/full selector predicates/prehydration budget. SET LOCAL
jit=off for this transaction only; no global DB/index/schema change.
208isolatedPGtests/Ruff/mypy/Astra review PASS; JIT restored on subsequent transaction.
Final deploy19:15:01UTC atomic7/host84/API18/worker18hashes PASS, head01/health200.
Six same-paper first/repeat HTTP reads1977–2167ms; exact reports identical toS205,
full criteria/provenance/counts unchanged. Paired direct median3303→1942ms,
standalone52→13SQL; not a cold-cache/nationwide/load-capacity guarantee.
Source0/DBwrites0; sample20notices/82positions/truncated remains explicit.
Ops19:16:58UTC DB4971232279/free257516175360bytes/testDB0/markersfalse;
API1GiB/web768MiB/worker2CPU2GiB/cron/source budgets unchanged. Pins/backup/proofs:
docs89. Preserve previous S206 initial proof files; final proof prefixs206-final.
S207UI next; S208two-branch identity prefilter is an unverified performance hypothesis.
Docs seal19:18:24UTC atomic5/host84/API18/worker18/web9hashes PASS,
image/cron pins/resources PASS; API/web running/OOMfalse.

## S207 — исторические кандидаты в интерфейсе

Contract/evidence: [docs90](../eis/search/90-eis-analog-candidates-ui.md). On-demand position,
query/lookback selector, exact-ref typed transport, FAIL exclusions/UNKNOWN review,
both XML sources and bounded scope visible. No backend/schema/dependency changes.
9analog+8protocol Node tests/TS/scoped ESLint/production build/Astra review PASS.
Web-only deploy19:56:19UTC atomic13/host90/web14hashes PASS; API/worker S206 pins
and cron/resources unchanged. Installed Action+SSR19:57:35UTC3paper refs first/
repeat1946–2269ms,20notices/82positions/truncated each. Changed position2/period30
1796ms,8negative requests errors only. Previous protocol9documents/4negative
checks PASS. No nationwide performance/coverage or browser visual check claim.
Ops19:57:37UTC DB5039660055/free257407389696bytes/testDB0/health200/head01,
markersfalse; source0/read-only/DBwrites0. Pinfiles s207-web-image.txt,
s206-api-image.txt/s206-worker-image.txt; s207-hashes.json90 includes web14.
Private proofs/rollback/image SHA details in docs90. Existing S204 tunnel-start
automatic approval rejection respected; no new public ports/tunnel.
S208 measured SQL prefilter optimization next; technical/delivery/lot evidence and
calibrated competition/profit remain later domain slices.

## S208 — prefilter identities до полной проверки источника

Contract/evidence: [docs91](../eis/search/91-eis-analog-lexical-prefilter.md). Disjoint overlap
and missing-derivation branches; no early LIMIT, full latest/history/holds/RLS.
216PGtests/27localtests/Ruff/mypy/Astra review PASS; disposable DB removed.
Deploy20:25:42UTC atomic8/host92/API18/worker18hashes PASS, S207web unchanged.
Six installed full same-time/snapshot reports identical, balanced paired direct
median2122→1624ms, APIHTTP1612–1744ms; no GIN use observed in actual plan.
Next Action+SSR regression6reads/changedposition/8negativechecks PASS.
Ops20:27:15UTC DB5050481687/free257335136256bytes/testDB0/health200/head01;
prioritymarkertrue ordinary lane activity,223false. Source0/read-only/DBwrites0,
cron/source/resource budgets unchanged. Pins s208-api-image.txt/worker-image.txt,
s207-web-image.txt; s208-hashes.json92. Proof hashes/backup/image SHA in docs91.
Next S209: scoped audited resolution, preserving tenant-wide receipt integrity.

## S209 — область доказательств разрешения конфликтов

228isolatedPGtests PASS30.43s/zero skips, focused unit/API/Ruff/mypy PASS,
Astra review closed. Optional scope only analogs; default consumers and
tenant-wide receipt integrity unchanged. Audit arrays and canonical/all-origin
checks retained. No schema/source/write/cache change.
Two-module pinned deploy20:43:42UTC atomic11/host95/API19/worker19hashes PASS.
Six same-time/snapshot reports identical to frozen BOTH S208 modules;
direct median1618→723.5ms/HTTP712–871ms, same20notices/82positions/truncation.
Next Action+SSR648–821ms/changed225ms/8negative checks PASS; no browser check.
Ops20:44:40UTC DB5051169815/free257312370688/testDB0/health200/head01,
markersfalse. Existing1GiBAPI/768MiBweb/2CPU2GiBworker/cron/source budgets unchanged.
Proofs/images/backup: [docs92](../eis/search/92-eis-scoped-resolution-checks.md).

## S210 — API наблюдений характеристик выбранной пары

259isolatedPG/unit/APItests PASS33.30s/zero skips,20focusedlocaltests/Ruff/mypy
PASS; Astra review closed. Read at most two exact savedpositions in one read-only
RR; preferred verified v2 projection or stored fields, no archive/source/jobs/writes.
Legacy absence and ranges/truncation UNKNOWN, fulltechnical/delivery/profitUNKNOWN.
Deploy20:57:42UTC atomic10/host101/API21/worker21hashPASS, S207web unchanged.
Six actual API/direct reports identical,12/4/3rows allUNKNOWN due to old missing
concrete values; HTTP77–240ms,6negativechecks PASS. Ops20:57:57UTC
DB5051554839/free257278357504/testDB0/health200/head01/markersfalse.
Caps/cron/source budgets unchanged. Pins/proofs/backup: [docs93](../eis/search/93-eis-characteristic-pair-observations.md).

## S211 — on-demand сравнение характеристик в UI

10characteristic+9analog+8protocol Node tests/TypeScript/ESLint/build PASS,
Astra boundary review closed. Web-only pinned deploy21:11:17UTC
atomic16/host109/web21hashes PASS, S210backend/schema unchanged.
Installed Next Action+compiled SSR21:11:41UTC6reads88–195ms,
12/4/3UNKNOWN rows,5negativeerrors PASS; analog1387ms/104pair buttons after
ordinary background ingestion. No eager per-row reads or browser visual claim.
Ops21:11:42UTC DB5085035543/free257155776512/testDB0/health200/head01,
223markertrue ordinary activity. Source0/jobs0/DBwrites0; caps/cron/budgets unchanged.
Pins/proofs/rollback: [docs94](../eis/search/94-eis-characteristic-pair-ui.md).

## S212 — выбранные характеристики, 2026-10-06MSK

Две source0 проекции из retained XML, две audit rows; canonical rows unchanged,
replay без writes. Worker2CPU/2GiB/import lease, без изменения cron/schema/images.
Installed API/direct6identities и NextAction+SSR6reads/negatives PASS.
DB5087009815/free257170878464/testDB0/health200/head01. Evidence: [docs95](../eis/search/95-eis-selected-characteristic-recovery.md).

## S213 — записанные диапазоны, 2026-10-06MSK

Web-first dualpolicy rollout, затем пять backend-модулей; host118/API23/worker23/web22 hashes PASS.
336PG/unit/API и13characteristic Node tests/build PASS. Пять retained v3 проекций/
пять audit rows, canonical unchanged/replaywrites0. Installed API/direct/NextAction
проверены: один реальный совпавший диапазон, неподдерживаемые данные UNKNOWN.
DB5092580375/free257084674048/head01/testDB0/health200; caps/cron/sourcebudget прежние.
Pins/proofs/rollback: [docs96](../eis/search/96-eis-recorded-range-comparison.md).

## Уточнение продуктового порядка, 2026-10-06

Документационное исправление: поиск производителей/поставщиков, сбор цен и
RFQ/КП являются отдельным этапом системы. Развитие ЕИС продолжается без
ожидания пользовательского прайса. Ручной прайс — дополнительный источник.
Публичная цена не является подтверждённым КП; exact-payload approval для
исходящих сообщений сохраняется. Runtime/schema/cron/caps без изменений.
Порядок: [docs15](../15-implementation-plan.md).

## S214 — externalSid и проверка фактических блокеров

95 local/346 isolatedPG tests PASS; backend-only3module deploy05:23:36UTC,
host119/API23/worker23 PASS, web/schema/caps/cron unchanged. One retained r1
projection+audit, canonical/oldprojection digests unchanged/replay0. Selected pair
API/NextAction/SSR PASS, pair3oneSAME+2UNKNOWN. Fulltechnical/profit/coverageUNKNOWN.
Recent03–05October cohort:1485attempted/352canonical/1106NO_DATA/27range-structureFAILED,
4905versions/lexical. Analog check BLOCKED by a newly encountered oversized candidate;
byte guard retained, failure scheduled for bounded fix. Evidence/rollback: [docs97](../eis/search/97-eis-range-external-id.md).

## S215 — сохранение карточек с неоднозначными диапазонами

142local/398isolatedPG tests PASS, backend-only4module deployment05:39:48UTC,
host122/API24/worker24 PASS. Controlled exact failed-window retry11.171s:
2SOAP/2GET,2ZIP,123newversions=123lexical. Frozen old parser fails on same bytes;
old27attempts preserved, canonical/newjournal/audit independently verified.
One ambiguous notice remains conservative UNKNOWN. Six installed selected-pair
API/direct and NextAction/SSR checks PASS; oversized analog regression BLOCKED
until S216. DB5498280983/free252101967872/head01/testDB0/health200/markersfalse.
No schema/cron/cap/sourcebudget change; other26failedwindows pending recovery.
Proofs/pins/rollback: [docs98](../eis/search/98-eis-ambiguous-range-intake.md).

## S216 — аналоги с явными пропусками при ограничении памяти

409isolatedPGtests PASS; web-first05:50:29UTC затем backend2module05:54:09UTC,
host124/API24/worker24/web22 hashes PASS. All3realpaperqueries now19admitted/
1omitted/142positions, HTTP1147–1297ms; six same-clock API/direct identities,
SQLomitted-not-hydrated и negatives PASS. NextAction/SSR omission visibility PASS;
selectedcharacteristic regression PASS. DB5508307991/free252010950656/head01/
testDB0/health200/markersfalse, cron/caps/budgets прежние. Полный охват UNKNOWN.
Proofs/pins/rollback: [docs99](../eis/search/99-eis-analog-payload-omissions.md).

S217 investigation05:52:54UTC: old27range-failure cohort1canonical/26remaining;
all26 within24h cooldown, selector60 currently includes0. Existing recent-failure
retry already supports them; PARSER_REVIEW is reporting category, not queue gate.
Earliest due06October21:46UTC/latest07October00:39UTC. No new retry lane justified.
Read-only proof SHA256e8a8a8397543b685ff01e94d3cdc47e14fb2dd929604297400cd9a64e9c24862.

### S218 — source0 DOCX review foundation, 2026-10-06

Deploy06:28:19UTC, migration20261006_01/host133/API28/worker28, web S216.
487 isolatedPG PASS65.51s/zero skips. Реальный cached DOCX:202blocks/35967chars,
9pages65–77ms/prepare238ms/replay76ms; 1analysis/1audit/source0/jobs0/replay0.
Все retained строки восстановлены без потерь; notice/v3 immutable. Native/fullTSpec
UNKNOWN, body paragraphs/tables only. API/UI следующим S219. OpsDB5515295767/
free251975380992/testDB0/health200/markersfalse. Threeanalogs1219–1556ms,
6characteristicAPI/direct/SSR+negative gates PASS; browser visual NOT_PERFORMED.
Пины, snapshot, proof SHA: [docs100](../documents/100-eis-document-review-capture.md).


### S219 — source0 DOCX review API/UI, 2026-10-06

Backend06:49:44/web06:50:39/authfix06:58:12UTC; host147/API29/worker29/web31.
509 isolatedPG/34 finalLinuxAPI/Node8+13+11+8/TS/ESLint/build/review PASS.
Actual prepare1698ms/replay1541ms/pages66–107ms,1analysis/audit/source0/jobs0;
10negativeHTTPgates with no-store PASS. NextActionSSR2pages76–77ms/6negative,
largerDOCX7pages19–26ms lossless. Source/import worker может продолжать работу
во время source0 review; API exact-ref/tenant transaction gates действуют.
Ops07:00:23UTC DB5525920791/free251823386624/head06/testDB0/health200/markersfalse.
Browser visual NOT_PERFORMED/native/fullTSpec/fullEIS UNKNOWN.
Пины, immutable partial verification history, proofs и rollback: [docs101](../documents/101-eis-document-review-ui.md).


## S220: поиск снабжения из позиции ЕИС — установлен

[Контракт, proofs, pins и rollback](../suppliers/102-eis-position-supplier-search.md).
Backend07:46:51/web07:47:00UTC/head20261006_02, host166/API33/worker33/web39.
150finalPG/API/source PASS/zero skips, Node46/TS/ESLint/build/review PASS.
RealpositionСервер→8catalogcards/14publicprices/2236ms/source1; read95ms/
NextAction132ms/source0. Source HTML хранится на VPS; ноутбук не скачивает массив
ЕИС. OpsDB5551791127/free251641643008/testDB0/health200/markersfalse/noOOM.
Corpus/223/docs/priority budgets и cron неизменны. Комплектация/ТЗ/полный рынок/
КП/прибыль/участие UNKNOWN; browser visual NOT_PERFORMED.

## S221: связь DOCX-фрагментов с позицией — завершено

[Контракт, proofs/pins/rollback](../documents/103-eis-position-fragment-association.md).
Backend08:19:13/web08:19:16UTC/schema20261006_03, host182/API36/worker36/web46.
189finalPG/API/source PASS43.27s/zero skips, Node51/TS/ESLint/build/review PASS.
Actualpaperposition→2DOCXspans61chars/1association+1audit, save198/replay160/
read133ms, NextActionread186/save148ms/source0/jobs0. Pricejustification остаётся
контекстом, полнотаТЗ/requirements/technical/quote/participation UNKNOWN.
LegacyDOCX/supplier/characteristics/analogs PASS; browservisual NOT_PERFORMED.
Ops08:19:34UTC DB5574859799/free251540631552/testDB0/health200/markersfalse.
Аддитивный source0 rollout использует backend/web deployment mutex и bounded
DDL5s/60s; старые работающие workers продолжают intake. Dispatch/import leases,
prioritymarkers, cron/source budgets не менялись. Сама запись association
захватывает exacttenantlease до repeatable-read snapshot.

## S222: восстановление сохранённых связей — установлен

[Контракт, evidence/pins/rollback](../documents/104-eis-position-association-restore.md).
Backend09:39:03/web09:39:12UTC, schema20261006_03 прежняя, host185/API36/
worker36/web47. Final197PG/API/source PASS45.90s/zero skips, Node55/TS/ESLint/
build/review PASS. Actual2distinctlinks pages142/146ms/detail137/149ms;
NextActionlist188/147/detail217/145ms/SSR PASS, no fragment selectors in detail.
Read source0/jobs0/writes0; явный второй выбор для proof создал 1link+1audit.
Ops09:39:17UTC DB5682658327/free251283402752/testDB0/health200/markersfalse.
Cron/source budgets/ordinary intake workers неизменны; browser visual NOT_PERFORMED.

## S223 — изолированный браузерный поиск снабжения

Обычный Chromium запускается API в отдельной process group: 90 с wall / 45 с CPU, гарантированная очистка потомков. Tenant lease 1, API process 1, 20 запусков/час, 64 MiB ZIP за 24 часа; ZIP до 8 MiB. Инварианты и release evidence: [S223](../suppliers/105-eis-position-supplier-serp.md). Плановое получение ЕИС продолжается независимо.

Обновление 6–7 октября: supplier SERP использует ordinary headed Chrome/Xvfb
с отдельными tenant/origin профилями и durable pacing/cooldown. CDP приватен;
Docker init собирает завершившихся потомков. Установленный Bing→PostgreSQL→source0
проверен; Google/Яндекс/Маркет на VPS показали CAPTCHA. Схема08 и worker image
сохранены; [контракт и runtime evidence](../suppliers/105-eis-position-supplier-serp.md).

S223 установлен 2026-10-06 10:24 UTC: schema04, host203/API40/worker40/web54;
263 Python/PG и63 Node PASS. Реальный поиск3762мс/read92мс; исходныеDOM остаются
наVPS. Browser processes0 после завершения, OOMfalse, cron unchanged. Точные
measurements/pins/proofSHA в [docs105](../suppliers/105-eis-position-supplier-serp.md).
## S224 — чтение выбранного сайта кандидата

Установлен ограниченный API/UI срез 2026-10-06 11:00 UTC; schema05, health200.
336 Python/API/PG и 73 Node PASS, TS/ESLint/build PASS. Реальные цены пока не
извлечены: Комус/Бумага-С HTML прочитаны, ВсеИнструменты403. EOF reader исправлен;
старый immutable исход Бумага-С сохраняется до обычного refresh. Helpers0/OOMfalse.
Точное основание: current позиция → сохранённый SERP run/engine/rank → derived URL.
HTTPS DNS-pinned чтение одного HTML, body2MiB, dispatch≤3, child40s/CPU10s,
слоты/cooldown и tenant budget. Read/cache source0; raw HTML остаётся приватным.
Плановые intake workers продолжают работать. API1GiB/web768MiB, ноутбук не хранит
новых архивов ЕИС или site HTML. Контракт, pins и точные результаты:
[S224](../suppliers/106-eis-position-supplier-page.md).


## S225 — подтверждённый поиск товара в выбранном каталоге

COMPLETE в bounded scope, installed schema06.403 Python/API/PG/zero skips,
84 Node+TS/ESLint/production build PASS. Actual SEARCH10links2759мс,
PRODUCT299.6RUB2020мс;source0read73–127мс.4catalogrows/audits+2root.
90 source tests; frozenDDL/model matched; hidden/CAPTCHA/ancestry fixes reviewed.
DB5889899543/free250584690688,health200,testDB0,sourcehelpers0,OOMfalse.
API119.6MiB/1GiB/web68.01MiB/768MiB. Raw HTML остаётся VPS. Общие budgets/slot
S224; intake/cron продолжаются. Source0read не означает отсутствие audit writes
при новом чтении. Browser visual NOT_PERFORMED. НДС/партия/доставка/ТЗ UNKNOWN.
Pins/SHA/контракт и путь тестирования: [S225](../suppliers/107-eis-position-supplier-catalog.md).

## S226 — source0 условия сохранённого товара

COMPLETE в bounded scope, installed schema07/API/UI 2026-10-06.
Производный immutable report без новых HTTP/дублирования HTML.
Exact PRODUCT/current/tenant/parent/body, cache/read noHTML, bounded parser/CPUslot.
437 Python/API/PG PASS/zero skips;94 Node+TS/ESLint/production build PASS.
Actual6supplierfields/4publicrows, read163мс/cachedprepare142мс, Next156–260мс,
source0/jobs0. Product1/audit1;page8/catalog4/audits unchanged;helpers0/OOMfalse.
DB5991701527/free250369658880,health200,testDB0. API122.1MiB/web64.88MiB.
Cron/intake продолжаются; HTML остаётся на VPS. Browser visual NOT_PERFORMED.
Техническое соответствие/полнота/единица цены/прибыль UNKNOWN.
Pins, evidence и способ тестирования: [контракт](../suppliers/108-eis-position-supplier-product.md).

## S227 — readonly таблица DOCX рядом с товаром

COMPLETE в bounded scope, installed API/UI 2026-10-06. Schema07 без новых таблиц.
Exact saved S226 product/current + received DOCX/receipt/SHA +
authoritative reviewv1/tableindex. Preview source0/write0, без новых таблиц БД,
HTML/bytea/parser downloads. Явный existing prepareReview отдельно.
474Python/API/PG PASS/zero skips;106Node+TS/ESLint/build PASS. Actual4characteristics+
section/24cells/4instructions;preview215–268мс/Next230–338мс/source0/write0.
DB6001007639/free250253279232,health200/testDB0/helpers0/OOMfalse;
API123.4MiB/web64.27MiB. Intake223 добавил8своихaudits, cron не изменён.
Browser visual NOT_PERFORMED. Технический/mandatory/полнотаUNKNOWN.
Pins, proof и тестирование: [контракт](../documents/109-eis-requirement-table-preview.md).


## S228 — source0 independent requirement review

Статус: COMPLETE для выпуска механизма; production review PENDING. Additive schema 20261006_08: immutable proposals/decisions,
RLS и audit. OPERATOR создаёт предложение; COMPLETENESS_REVIEWER с другим
actor подтверждает exact digest. Не создавать production reviewer/token ради
проверки. Production pending proposal и OPERATOR→403 проверяются отдельно
от synthetic independent-review PASS/FAIL gates. Source0 не означает write0:
создание proposal/decision пишет aggregate и audit; replay/read — без записей.
Резервируются предыдущие source/image pins; intake/cron продолжается.

S228 release evidence: 505 real PG/Python/API tests, 116 Node tests,
TypeScript/ESLint/build PASS. Schema08 installed; host291/API58/worker58/web90
files hash guarded. API/web pinned digests и proofs — [S228](../documents/110-eis-independent-requirement-review.md).
Финальный source0 read-only status: DB6017563671 bytes, free250168291328 bytes,
health200, testDB0; source helpers0; API126.6MiB/1GiB, web68.04MiB/768MiB,
OOMfalse. Ordinary intake/cron продолжается; cron SHA не менялся.
Production pending proposal1, decision0, review audit1; Next replay не пишет.
Последующий шаг S229 — units/sheet-per-pack interpretation, без подмены полного КП.

Ручная CAPTCHA SERP установлена отдельным pinned overlay, schema08 сохранена,
без migrations/новых публичных портов. Protected UI передаёт JPEG/input через
API-owned Chrome; внешний VNC/CDP не публикуется. Manifest/rollback, бюджеты,
checks и границы live acceptance — [SERP112](../suppliers/112-human-supplier-captcha.md).
