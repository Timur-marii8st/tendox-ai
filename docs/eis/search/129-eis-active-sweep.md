# Обход активных закупок без товарного запроса

24.10.2026. Owner root. INSTALLED_BOUNDED; первый production проход и exact HTTP PASS.
Контракт:[ADR0117](../../adr/0117-eis-active-sweep.md),[PRD3.1](../../product/11-product-requirements.md).
Evidence:tmp/eis-sweep-20261024-v38/. Review отдельно; runtime редактирует root.

Owned: scripts/server-eis-hybrid-recovery.py/.sh,server-eis-active-sweep.py;
tests/test_eis_active_sweep.py,integration/test_eis_active_sweep_pg.py; ADR0117,
этот отчёт, индексы и live-план. Старые tests/V37state не заменяются.
Dependencies: установленный V37/S201, source leases/pacing/jointbudget, tenant PG,
существующий disposable PG harness, полный trusted candidate workflow.

Acceptance: реальная выдача без query → сохранённый partition/checkpoint →
пропущенный номер → stock intake → основной поиск в isolated PostgreSQL.
Обязательны прежние hashes, атомарный split/попытки, глобальные caps, RLS,
ошибка discovery после успешного recovery, saturated day без ложной полноты.

## Наблюдения

Пилот V37 к проверке дал2успешных прохода,2восстановленных номера,3отказа
ROBOTS_CRAWL_DELAY и1BROWSER_REQUEST_FAILED. Плановый запуск подтверждён.
Поэтому повышение cron frequency само по себе не гарантирует ускорение.

Свежие публичные страницы ЕИС без query,44/AF/deadlineFrom24Oct/publishTo24Oct:
- PRICE:50parsed/0unparsed,все50уже в индексе; count«более54000».
- PUBLISH_DATE:50parsed/0unparsed,39present/11missing по readonly tenant snapshot.
Все11пропусков — route zk20. Ни count, ни50карточек не являются полным census.
HTML latest SHA `6c8557a9a0e8f3c67beda256cd13fe693cdfd43549783c7becd723f4efb4d050`.
Evidence:public-all.html/json,presence.json; PRICE наблюдение сохранено отдельно.

Source capture использует прежний установленный capture-only reader без изменения
его байтов. Частный shell нужен для удержания shared leases и выбора нового набора:
старый capture runner жёстко связан с прошлыми12номерами, публичный cross-check —
с NO_DATA report. Новая программа не выполняется с production writes.

## Текущая проверка

30новых unit cases +38V37 =68PASS. Проверки включают split, global dedup/cap,
legacy scope SHA и JSON для rollback, pacing,8attempts/один Budget,
durable IN_FLIGHT перед crash, refresh после неуспешного audit и root cycle binding.

Скачаны8реальных source sets за129.65s суммарного source capture:16SOAP/8ZIP.
Изолированный network-none PostgreSQL:8SYNCED,8audit RECORDED,8lexical projections,
8document queues PLANNED. Основной HTTP global-price по каждому точному номеру
возвращает закупку. RLS:0чужих строк. Ещё3из11номеров PENDING, не отброшены.
Evidence: capture-results.json,actual/*,actual-replay-result.json,actual-global-price.json.
39known берутся из frozen production readonly snapshot; они не синтезированы в PG.
Production writes этим replay не выполнялись; national coverage UNKNOWN.

Batch presence PG: два setup-отказа DELETE (app ACL, затем append-only trigger)
показали неверный способ построения отрицательной фикстуры. Подход изменён:
synthetic ingest с отключённым insert_search_keys моделирует незавершённую
проекцию без мутации immutable rows. Контракт не ослаблен.
Повторная проверка PostgreSQL:93focusedPASS, включая batch presence/tenant isolation
и отсутствие проекции. Fixture получила отдельное transport window для третьего
номера, чтобы не имитировать конфликт immutable replay.
Независимый review:блокеров нет; дополнительно воспроизведён crash после реального
persist callback при закрытии audit долга, same/cross partition, reload PASS.
Полный gate50/50PASS:Python3907PASS+27allowed skips, PG718/0skip,
doctest9, web205, builds/smokes PASS;9временных ресурсов удалены с identity check.
Run release-20261024-064500-763b306c404a; source archive
`cfae9e105b5f1d61d4fc70ffee1ddadeb9116302cb4d43abd631f9fa78075cd3`.
Первая попытка остановлена docs-navigation: ссылки из dirty workspace вели на
не включённую стороннюю документацию. Candidate indices построены от V37+V38;
исходники runtime не менялись. Успешный receipt принадлежит новой полной попытке.

Дополнительно: keyword global-price по«топлива дизельного»,«морозильная камера»,
«телевизор» возвращает восстановленные номера, Decimal/deadline/XML SHA проверены.
Реальный дочерний диапазон25Sep–24Oct:50parsed/0unparsed, фильтры подтверждены;
count floor54000 не доказывает полноту. Evidence:real-child-result.json.
88imported worker modules совпали с candidate byte-for-byte; worker image не меняется.

## Готовый план включения

Payload `eb4581ba905929cbbadc5720f2f15e6bfd0850acbe0ea8765b7def224b9835dc`:
2замены совместимых hybrid scripts+1новый sweep; host tree76→77.
Ровно одна строка V37 cron заменяется:active44/no query/as_of24Oct,
каждые10мин до25Oct00UTC(03MSK), до8attempts в прежнем source budget.
Остальные7строк/образы/schema сохраняются. Готовы immutable rollback inputs;
ready gate публикуется последним после successful audit, до этого source не запускается.
16adapter failure tests PASS, независимый code/draft/final receipt review PASS.
Проверены source/receipt/policy/host tree/Compose/schema/cron в существующем lease.
Preflight24Oct07:08:22UTC READY_FOR_EXACT_APPROVAL; source requests0.

После gate свободное место было ниже40GiB. По ранее полученному разрешению очищены
неиспользуемый Docker build cache и только .pyc caches в33неактивных stage directories;
active mounts/processes проверены, source/DB/backups/reports сохранены.
Свободно43163480064bytes(40.20GiB), per-run source reserve сохраняется.
Evidence:activation-plan.json,activation-preflight.json,final-review.json,
fullgate-summary.json,bytecode-cache-cleanup.json. Ниже — результат согласованной активации.
Устойчивое ускорение и national coverage UNKNOWN.


## Production активация и первый проход

Пользователь подтвердил exact payload eb4581ba в ответе на
call_f35e9915b01b481a9de30d80403a363b:«Включить расширенный обход и проверить поиск».
Установлен24Oct07:50:34UTC. Два предварительных отказа ROLLOUT_BUSY:eis-priority.lock
произошли до preflight/мутаций. После двух отказов способ изменён: дождались
наблюдаемого освобождения всех четырёх shared locks, затем применили прежний adapter.
Работающий импорт не прерывался; checks/lease не ослаблялись.
Effective host tree/cron/ready SHA совпали с планом; runtime/Compose/schema неизменны.
Tenant audit содержит PREPARED и ACTIVATED с exact payload и ссылкой на human approval.
Evidence:human-approval.json,activation-contention.json,activation-result.json,
installed-verification.json,production-queue-audit.json.

Первый штатный cron запущен24Oct07:51UTC, отчёт07:51:50UTC:OBSERVED,
50карточек/0неразобранных,42уже присутствовали,8отсутствовали.
8SYNCED, у каждой before0versions/0lexical → after1version/1lexical,
8audit RECORDED,8document queues PLANNED. Все8очередей INDEXED; pending0.
45.935s — длительность одного измеренного coordinator run, не устойчивая скорость.
Root SPLIT; дочерние PENDING:25Sep–24Oct и неограниченное прошлое по24Sep.
Checkpoint сохранён; покрытие UNKNOWN, обход всех диапазонов не завершён.
Исходный HTML SHA b2351dd7a2c61da699a4af516bf4bc4325d7ce5dd207533e7cb615d9038cdf71
повторно сверен с сохранёнными байтами.

Основной production HTTP /v1/tender-discovery/global-price:8/8точных номеров HTTP200,
положительные Decimal НМЦК, timezone-aware deadlines и XML SHA совпали с intake.
Восстановлены0190200000326012166,0190200000326012167,0321500002126000187,
0352200008226000082,0352200008226000083,0360300149626000020,
0387100012626000311,0848300049026000951.
Пример0321500002126000187:дизельное межсезонное топливо,2999300.00руб.
0848300049026000951:поставка/монтаж новогодней ёлки,1555000.00руб.
Evidence:production-first-run.json,production-http-readback.jsonl.
Keyword HTTP:«телевизор»→0352200008226000083 на1йстранице(88совпадений);
«морозильная камера»→0352200008226000082 на5йстранице(511совпадений),
price_desc/100настраницу. XML SHA совпали. Первый диагностический assert ошибочно
ожидал дешёвую камеру на первой странице; сохранённые cursor pages подтвердили,
что это пагинация, не отсутствие индекса. Дополнительный query«новогодней ёлки»:
320совпадений; target не в первых100, continuation не проверялся, exact HTTP PASS.
Evidence:production-keyword-pages.jsonl; итог production-acceptance.json PASS_BOUNDED_LIVE.

Расписание заменило V37; active44 безquery каждые10мин, admission до25Oct03MSK,
as_of24Oct. Закрытые закупки,223 и публикации после24Oct этим расширением не покрыты.
Лимиты256диапазонов/2000queue/256MiB evidence и прежние source budgets действуют.
Диск24Oct07:56:51UTC:43043016704bytes free, всего93343744bytes сверх40GiBreserve.
Временные source workloads меняют свободное место; последующие проходы могут
отклоняться source guard. Build cache0B, свободного неразмеченного места для
расширения ext4 нет; новых удалений в этой активации0.
Предварительно предложено расширение диска; после следующей разрешённой очистки
срочная необходимость снята. Исторический замер:production-capacity.json.

## Очистка резервных копий24Oct

Пользователь явно разрешил удалить старые резервные копии; разрешение заменяет
прежний запрет только в границах списка cleanup manifest. Владелец root.
24Oct09:09:14UTC удалены33старых procurement-*.dump,174418375109bytes(162.44GiB).
Сохранены22Oct/16Oct и исходный27Sep;2свежих архива полностью декодированы
pg_restore --file=/dev/null, exit0 (217.147s/168.22s). Это проверка чтения всех
данных архивов, не restore test в PostgreSQL. Перед unlink проверены manifest,
inode/size/mtime, отсутствие symlinks и открытых файлов. Рабочие тома/образы,
source evidence/code snapshots и Forgejo не удалялись.
ManifestSHA a2cb1ce136dfbe79c5b5b62ae74fd3b851df33346da480f33ec7441136e4d31a;
tenant audit EIS_BACKUP_RETENTION_MAINTENANCE PREPARED/COMPLETED прочитан обратно.
Free после удаления217374208000bytes(~202.4GiB); storage predicate free>=40GiB
и DB<100GiB PASS. Загрузка не проверялась дополнительным source запросом;
действующий cron не менялся. Покрытие ЕИС/устойчивая скорость по-прежнему UNKNOWN.
Очистка была разовой; затем включена и проверена [ротация126](../../operations/126-backup-rotation.md).
Срочное расширение340→500GiB больше не требуется для снятия дискового ограничения.
Evidence:tmp/eis-backup-cleanup-20261024/{manifest,result,archive-verification,
post-cleanup-check,vibe-saby-size}.json; полный список удалений в deletion-journal.json.
Vibe-saby:два Git-репозитория~89MiB; все каталоги Forgejo и home/backups вместе
со старой копией~328MiB (включают общие данные, исключают Docker image layers).


## Диагностика после освобождения диска24Oct

Root; bounded readonly slice, source requests0/business writes0. Срез БД11:59UTC
(14:59MSK), от cleanup09:09:14UTC:319новых уникальных закупок —44:283,223:36.
Всего450437(44:403554;223:46883), сегодняMSK764, за24ч5504.
Редакции отдельно:44:440551;223:54310. Lexical44:440551строк/403554номера.
Это сохранённый корпус, включая неактивные закупки; national coverage UNKNOWN.
Отдельные readonly transactions/SQL5s: concurrent ingest может менять соседние замеры.
DB23,048,879,127bytes, free~192GiB/availableRAM~5.8GiB: диск больше не блокирует.

25отчётов sweep07:51–11:51UTC:919card observations/370unique;13unique восстановлены,
из них2после cleanup. Очередь восстановления0pending; discovery продолжает работу.
12SPLIT/6PENDING/6SCANNING/1OBSERVED_PAGES. После cleanup15OBSERVED/2browser failures,
capacity guard отказов0; начальная разбивка дат повторяет первые страницы.

44priority после cleanup:RECENT_HOUR962NO_DATA/12SYNCED;
RECONCILE_DAY152SYNCED/68NO_DATA/2FAILED. NO_DATA не доказывает вечное отсутствие.
2FAILED имеют DUPLICATE_NOTICE_VERSION. Исторический corpus уступает mandatory fresh;
также наблюдались отказы общего часового бюджета. Частоту cron слепо не повышать.
223последние6отчётов:REGIONAL_PROBE_UNAVAILABLE. Readonly probe дважды воспроизвёл
OperationalError; SQLSTATE57014:statement timeout5000ms в recovery_windows→
regional_due_windows, до source access. EXPLAIN в223-selector-plan.json относится
к другому SELECT и не используется как доказательство плана проблемного запроса.

Следующий приоритет: ускорить223recovery selector, сохранив exact order/RLS/SQL5s;
проверить на одном production snapshot и обычном cron. Затем измерить перераспределение
часового бюджета в пользу суточной сверки, не принимая NO_DATA за полноту, и пакетный
обход нескольких страниц в прежнем source budget. Действующий sweep истекает25Oct03MSK;
автопродление/изменение cron в этой диагностике не выполнялось.
Evidence:tmp/eis-progress-20261024/{database,logs,223-probe,223-selector-plan,summary}.json.
