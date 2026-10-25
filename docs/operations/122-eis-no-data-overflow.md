# Восстановление bounded NO_DATA retention

Владелец root. Статус на21Oct: V3_1_APPLIED_BOUNDED_RECOVERY_PASS.
SSH/disk reserve восстановлены21Oct. V3 и коррекция bare Compose установлены
по двум exact approvals; ordinary-cron retention/raw/journal proof PASS. Payloadv2 superseded из-за
воспроизведённого дефекта missing archive; receiptv2 остаётся evidence старых bytes.
Контракт: [ADR0110](../adr/0110-bounded-no-data-overflow.md), исходная причина —
[диагностика19Oct](121-eis-production-readiness.md).
Owned files: `src/procurement/sources/eis_no_data_evidence.py`,
`scripts/server-eis-no-data-store-report.py`, соответствующие два test modules,
этот документ, ADR и индексы/live-план. Работа одним агентом.

## Acceptance

- На изолированной копии полного рабочего store новый ответ сохраняется во втором
  сегменте; source/database production writes0. Данные fixture обозначены synthetic.
- Первый файл сохраняет hash, старые ссылки raw/manifest и replay работают;
  новый receipt проходит audit/journal/offline verification.
- После перехода первый файл больше не получает записи; оба файла сохраняют
  per-store лимиты, после заполнения второго — явный QUOTA_REACHED.
- Concurrent writers не создают дубли; busy/unsafe/IO не становятся RETAINED.
- Report показывает headroom второго файла и оба независимых snapshots.
- Полный обязательный release gate без ослабления stages/skips; installed runtime
  сохраняет все прочие файлы и настройки, схема и cron не меняются.
- Активация требует exact payload и audit; после неё нужен обычный cron с
  RETAINED/raw reparse/journal match. До этого live recovery не объявляется.

## Порядок выпуска

За основу берётся sealed source установленного speed-v2, а не всё текущее
рабочее дерево. В него добавляются только owned изменения. Provider и policy
находятся вне candidate; меняются лишь ожидаемые коллекции добавленных тестов.
Все прежние stages, assertions и allowed skips сохраняются.
Перед сборками проверяются память и свободный диск; штатные loaders продолжают
работу. Нельзя освобождать место удалением чужих данных или release evidence.

План активации должен связывать source/receipt/images/host scripts SHA,
ожидаемую исходную конфигурацию и хеш старой SQLite, проверку восстановления
старых references и postcheck. API/worker/reader должны понимать оба receipt paths.
Обратное переключение на reader, не знающий overflow, не считается безопасным
rollback после появления новых receipts. Данные не удаляются при rollback.

## Текущие проверки

Регрессии воспроизвели исходный отказ: второй ответ при заполненном store получал
FAILED. Добавлены проверки перехода, старых references, двух квот, sticky routing,
конкуренции, bounded lock и независимого quota report. Итог v2 приведён ниже.

Первый полный gate50/50 и actual-copy proof PASS сохранены, но payloadv1
не принимается к активации: финальный review воспроизвёл запись в свободные
ячейки уже полностью allocated файла. Добавлен отдельный regression и явный
page-count gate до INSERT. Scope и требование неизменного первого файла не
ослаблены; новый sourcev2 проходит полный mandatory gate заново.

## Итог v2 — 2026-10-19

Полный source-bound gate50/50PASS: unit3665PASS/27прежних explicit skips,
PostgreSQL16 —688PASS/0skips, Node178PASS/0skips,9doctests; Ruff/mypy,
docs, сборки и API/web smoke PASS. Cleanup9owned resources PASS; два accepted
images оставлены для выпуска. Все235Python modules итогового API image
проверены по source manifest. Изменены2модуля API: retention и ранее принятый
worker transport; defaultAPIgap2/worker configuration1.25 не меняются.

Изолированная копия реального store:57976records/128MiB. Старый файл сохранил
SHA256 после перехода; synthetic новый ответ сохранён в overflow20KiB,
old raw references3/3, replay и foreign-tenant refusal PASS. Production/source
requests0. Новый настоящий ответ ЕИС должен быть проверен после активации.

Receipt: `tmp/eis-no-data-segments-20261019-v1/release-receipt-v2.json`;
SHA256 `271a10e8a63aa5a16f6e462ad41fb8bd63e34bcd3bc4a254080dfdf8138bb3a6`.
Source68c64fd0…; image935dae45…; policy/verifier и все staged bytes связаны
с `activation-plan-v2.json` в том же каталоге. SHA256 точной операции:
`aca2b9b8edd68b2d8455ce125d9e7aca31007e40fd3c14dcaa31b97afdccb30d`.
Preflight этого payload PASS, source requests0/production writes0.

Операция обновляет API/worker image, host retention module/report и active
Compose override. Нужен короткий restartAPI; web/DB/schema/cron/source budgets
сохраняются. После неё ordinary cron должен дать RETAINED и raw/journal match;
без этого live recovery не объявляется. Нельзя применять superseded payloadv1.

На19Oct следующим действием было exact-payload approval по AGENTS, затем
установка и postcheck. Этот порядок для payloadv2 заменён проверкой20Oct ниже.
Коммерческий API/full coverage этим срезом не приняты.
Этот итоговый evidence текст добавлен после sealing sourcev2 и не является
частью receipt-bound source archive; сами proof/plan hashes проверены отдельно.

## Исправление missing archive — 2026-10-20

Владелец root, один агент. Owned files текущего delta: retention module,
`tests/test_eis_no_data_evidence.py`, этот документ и live-план.
Зависимости: прежний двухсегментный контракт ADR0110, существующий report и audit.
Acceptance: исчезновение первого файла при сохранном overflow не скрывается
успешным чтением, writer не создаёт пустой архив вместо утраченного; оба случая
сохраняют bytes overflow, штатный переход/replay/tenant guards продолжают работать.

Два новых regression tests сначала дали2FAIL: verifier возвращал
PASS/MATCHED_RAW_REPLY из overflow без первого файла, а lock создавал пустой
`no-data.sqlite3` до проверки наличия архива. Lock теперь создаёт только private
directory и lock-файл; создание SQLite остаётся в writer после проверки topology.
Reader возвращает UNKNOWN/STORE_UNAVAILABLE, writer — FAILED/STORE_UNSAFE;
первый файл остаётся отсутствующим, overflow неизменен.

Проверено на отдельном PostgreSQL16 с текущими миграциями и non-superuser
`procurement_app`:57PASS/0skips в двух retention/report modules с
`--require-postgres`. Включены raw+manifest/journal/audit match, переход между
обоими файлами и foreign-tenant refusal. Без PostgreSQL тот же набор дал
54PASS/3явных skips; это отдельный запуск, числа не складываются.
Ruff всего репозитория, format двух изменённых Python files, mypy module/domain
и9domain doctests PASS. Общий pytest:3376PASS/488skips/0failures/0errors;
пропуски не считаются проверенными. Три retention PostgreSQL skips из этого
запуска отдельно закрыты57-test набором выше. Одно предупреждение pytest о
несовместимости record_property с xunit2 в существующем search-capture PG module.
Полный50-stage release gate для изменённых bytes NOT_PERFORMED. JUnit и patch:
`tmp/eis-no-data-fix-20261020-v1/retention-pg.xml`, `pytest-all.xml`,
`retention-fix.patch`; текущая передача — `local-checks.json` там же.
Одноразовый PostgreSQL16 container удалён по точному ID; OOMfalse.

Массовый отказ QUOTA_REACHED подтверждён сохранённым snapshot18Oct:
11041FAILED/0RETAINED, первый файл128MiB/57976records. Это не live20Oct.
Ранее перечисленные11окон с duplicate version/attachment reference/expansion
limit требуют актуальных journal и raw evidence с VPS; исходные байты доступны
только там. Их исправление и повторная загрузка NOT_PERFORMED, причины не
объявляются допустимыми и resource/provenance guards не ослабляются.

Следующее действие: восстановить SSH-доступ, сверить актуальные runtime/очередь/
store и выполнить обязательный release gate для нового sealed candidate;
затем подготовить точную операцию установки и ordinary-cron postcheck.
Старые receipts не подтверждают новый код; production recovery остаётся UNKNOWN.

## Продолжение 21 октября — диск и candidate v3

Владелец root, один агент. Scope: прежние retention module/tests, этот отчёт и
live-план; новые production helpers не добавляются. Существующий activation
adapter перепривязан к v3 paths; receipt/source/approval checks сохранены.
Cache cleanup и установка выполняются под одним существующим deployment lease: без
этого cron мог бы возобновиться между cleanup и исправлением старого store.
Cleanup ограничен unused build cache; images/containers/volumes inventories до/после
должны совпадать. После cleanup требуется free>=40GiB; ошибка до замены файлов
не инициирует compose rollback. Семь offline action/refusal checks PASS; production
исполнение этой операции пока NOT_PERFORMED.
Acceptance исходного среза не меняется. Дополнительный результат: установить
расход диска и подготовить точную операцию восстановления резерва без удаления
дампов, образов, томов или release evidence.

SSH к `syurai@192.144.13.82` работает. API health/UI HTTP200, PostgreSQL и proxy
работают. Журнал corpus содержит `DISK_RESERVE_REACHED`. До gate свободно
42742030336bytes при минимуме40GiB=42949672960bytes; порог не снижается.
Распределение: `/home`210GiB, `/var`69GiB; state209GiB, из них backups178GiB.
В backups58дампов/190181854557bytes и156прочих файлов/186681312bytes.
PostgreSQL18247056407bytes. Docker сообщает build cache37.25GB, reclaimable33.7GB;
отрицательный reclaimable images counter недостоверен и не используется.
Оценка cache не гарантирует фактически освобождаемый объём.

Source-free READ ONLY snapshot21Oct12:17:36UTC за текущий день МСК:
NO_DATA evidence2FAILED/QUOTA_REACHED,0RETAINED; attempts44:3SYNCED,2NO_DATA,
1FAILED,6SKIPPED. Эти counts не подтверждают национальный охват/свежесть.
Никаких ручных запросов ЕИС, production DB writes или удалений не выполнено.

Candidatev3: archiveSHA`c41a998b8e6515c3665c987a79981f70fbd3a61198805fdfad4adb90ad49b5c5`.
За основу взят sealedv2; изменены только retention module и два новых regression
cases в его test module, остальные1305files byte-exact. Mandatory stages50,
прежние allowed skips сохранены; unit collection3692→3694 и root PostgreSQL
collection152→154 содержат ровно два новых test IDs, без удаления прежних.
Controller/verifier не менялись. Первый gate `release-20261021-121458-cc5495f558bc` FAIL: два legacy DOC tests
из-за запуска controller отroot вместо штатногоsyurai; worker/test scratch uid0
несовместим с root→nobody launcher. Остальные3665unit PASS/27skips,2FAIL.
Cleanup complete; failure receipt/logs сохранены, PASS не выдан. Повторный полный
gate `release-20261021-122130-172ed4928115` отsyurai(uid1000/gid1002) завершил
все50stage commands, но receipt FAIL: ожидаемая PG collection не учла два новых
tests. Фактически unit3667PASS/27skips, PG690PASS/0skips; PASS receipt не выдан.
Оба неуспешных подхода пересмотрены: до нового запуска сверены обе коллекции
с прежними hash/IDs; добавлены ровно те же два regression cases в PG expectation,
остальные expectations неизменны. Policyv3.1 хранится отдельно; старый policy
и failure evidence не переписывались. Новый полный gate
`release-20261021-123803-33f8951333cb` PASS50/50 отsyurai,
как в принятомv2. Четыре legacy subprocess checks отдельно PASS в новом worker.
Код, policy и assertions не менялись; root-owned task run state
передан владельцуsyurai, production permissions не менялись.

Изолированная актуальная копия:57976records/128MiB. Новый synthetic response
RETAINED в overflow20KiB; старые raw references3/3, replay и foreign-tenant guard
PASS. ArchiveSHA до/после одинаков:
`f6055e5c49214308947d64043b0c32fd4f6d07a1786e91c67ea15abe1d52d692`.
При исчезновении первого файла readerUNKNOWN/STORE_UNAVAILABLE,
writerFAILED/STORE_UNSAFE; overflow bytes неизменны, архив не создаётся заново.
Это offline proof, не production recovery и не обычный cron postcheck.

Evidence: `tmp/eis-no-data-recovery-20261021-v3/`; remote root с тем же basename
в `/home/syurai/vibe-seller-state/`. Disk/cache/backup inventories и live READ ONLY
snapshot сохранены отдельно. План: после полного gate и проверки installed-base
подготовить новый exact-payload для unused build cache cleanup и активацииv3;
сохранить дампы/образы/тома/evidence и проверить ordinary cron raw/journal.
Последний BACKUP_OK в журнале16Oct00:38:31UTC; далее пять
DISK_RESERVE_REACHED. Backup lifecycle требует отдельного retention/restore контракта;
очистка cache сама по себе не устанавливает долгосрочную policy копий.

READ ONLY сверка21Oct12:44:13UTC: в scope latest attempt по каждому window среди
attempts с18Oct00:00UTC осталось18FAILED windows:12DUPLICATE_NOTICE_VERSION,
3ARCHIVE_WINDOW_EXPANSION_LIMIT,2MEMBER_UNSUPPORTED,1ATTACHMENT_REFERENCE_INVALID.
Список ограничен100rows, фактически18; это не полный census национального охвата.
Срез retention/disk не объявляет эти отказы исправленными; resource/provenance
checks не ослабляются. Evidence: `current-failed-windows.json` в каталогеv3.

## Готовый payload v3 — 21 октября, активация ожидает approval

Полный source-bound gate завершён12:54:09UTC:50/50PASS, complete=true.
Unit3667PASS/27прежних skips; PostgreSQL16 —690PASS/0skips; Node178PASS/0skips;
9doctests, Ruff/mypy/docs, сборки и network-none API/web smoke PASS.
Typed verifier повторно проверил receipt/reports/source/policy. Cleanup9owned
resources complete; два accepted images сохранены. Browser/E2E и PaddleOCR
integration остаются NOT_PERFORMED по прежней policy.

Все235Python modules принятого API image соответствуют source manifest. Между
установленным API и кандидатом меняются только retention и ранее принятый worker
transport; остальные233modules byte-exact. API default gap2 и worker gap1.25,
web/DB/schema/cron/source budgets сохраняются. Installed-base precheck и полный
activation preflight PASS, source requests0/production writes0.

SourceSHA`c41a998b8e6515c3665c987a79981f70fbd3a61198805fdfad4adb90ad49b5c5`.
API/worker image:
`sha256:c2ca3bc9c739605dcb34916e7973ced8c75b06eaf51ddb951425ad0c91b3b2c6`.
Точная операция `activation-plan-v3.json`, SHA256:
`d1e10345453f019eabd9116ebc2083eb1ecaf503ba8ded4986de113b2d85afe2`.
Связанный cache-only plan SHA256:
`fce27174527983490331dea5e61079e3a5a4780bd7faa607f2941f35a88af86f`.
Executor SHA256:
`f02a899534b99539bb755670a0fafd4adb52a33557900f3621107aee263dbbb9`.
Локальные plan/receipt/proofs — `tmp/eis-no-data-recovery-20261021-v3/`,
серверные — одноимённый private root в `/home/syurai/vibe-seller-state/`.

Одна подтверждаемая операция под существующим deployment lease: tenant-scoped audit
approval → unused build cache prune → проверка неизменности images/containers/volumes
и free>=40GiB → три точные замены host files/Compose и API restart. Образы, тома,
дампы, старые raw replies и release evidence не удаляются. Кэш восстанавливается
следующей сборкой; его очистка не откатывается вместе с runtime. До появления новых
receipts runtime rollback использует старые files/images; после новых receipts
совместимый reader и оба store сохраняются, откатывается только worker.

Approval ещё не получен: cache prune/API restart/production installation
NOT_PERFORMED. Recovery UNKNOWN. Следующее действие — exact approval указанного
payload, применение, затем ordinary cron RETAINED + raw reparse/manifest/journal
match и неизменный hash первого архива. Manual source requests не добавляются.
Текст отчёта/live-плана обновлён после sealing; он не входит в receipt-bound
source archive и проверяется текущим docs check отдельно.

## Активация v3 — 21 октября, 16:16 МСК

Пользователь явно подтвердил полный SHA payloadv3 в чате. Approval reference:
`user-chat-20261021-exact-d1e10345453f`; operation ID
`eadc56dd-c737-43c6-8d54-e60f10808a64`. Повторный preflight и apply выполнены
неизменённым executor, SHA256 совпал с утверждённым планом. Audit:
`activation-audit-v3.json`, статус INSTALLED_AWAITING_ORDINARY_CRON_PROOF,
начало13:15:39UTC, завершение13:16:27UTC. Approval/start/install записаны также
в tenant-scoped центральный audit. Ручных source requests не было.

Cache-only cleanup завершён exit0: free42468151296→73339813888bytes,
освобождено30871662592bytes (28.75GiB), осталось68.3GiB. До/после совпали все
Docker image IDs/tags, container IDs и volume names. Дампы, образы, тома, raw replies
и release evidence не удалялись. Proof `disk-recovery-result.json`, command logSHA
`a60069c2672d9f4e2a87f857224665319d5adef3f41bcd71efb10c291f0b8dfb`.

API image установлен `c2ca3bc9…`, контейнер `822e7f8457c9…`; web и DB сохранили
контейнеры/образы, schema и cron hashes совпали. API health/UI HTTP200.
Installed reader: moduleSHA10cb0bf9…, три старых tenant references raw/manifest
PASS, hash первого128MiB архива по-прежнемуf6055e5c…. Evidence:
`installed-old-references.json`. До ordinary cron recovery остаётсяUNKNOWN;
следующий corpus slot16:30МСК. Cron и pacing не менялись, ручной импорт не запускался.

## Штатный cron выявил неполное переключение writer — 21 октября

Первый priority cron после установки стартовал16:17МСК и завершился16:20МСК:
60attempted,19SYNCED,41NO_DATA,0source FAILED;61new versions и2events.
Фактический worker image при docker inspect16:19МСК —96a570c1…, прежний speedv2.
Это установленный код, источник запускался обычным cron; ручных запросов не было.
READ ONLY postcheck since13:16:27UTC:0RETAINED/41FAILED, всеQUOTA_REACHED,
41NO_DATA attempts с capture audit; overflow отсутствует. Audit completeness PASS
не означает сохранения raw. Полное восстановление retention FAIL.
Proof: `post-activation-store-report.json`, полный report
`post-activation-store-full-proof.json`, SHA256
`d71ebc0d129e42864bb90905e6230581c2363b76045a79d6ea09991ca8b11291`.
Источник на VPS: `/var/lib/eis-browser/research/rejected/s199-store-health-10599eb3-0dce-4b13-b4aa-db0112dd83c5.json`.
Ordinary-run summary/route evidence: `ordinary-cron-v3-route-proof.json`.

Причина — дефект подготовленного root планаv3: helper full_configuration проверял
base+active override и workerc2ca3bc9, а priority/corpus/223/daily scripts используют
только основной `docker-compose.server.yml`. Его worker остался96a570c1; source
и сам accepted image исправны. Проверки approval/receipt не подменяли реальный
cron route. Исправление маршрута не входит в три утверждённых targetsv3.

Владелец root, один агент. Owned production target коррекции:
`/home/syurai/vibe-seller/docker-compose.server.yml`; staged adapter/plan/proofs
в прежнем private rootv3; отчёт/live-план/ADR. Acceptance: ровно один image digest
worker96a570c1→c2ca3bc9; весь остальной bare config и весь active-overlay config
идентичны; без restart API/web/DB, schema/cron/budgets/pacing без изменений.
Зависимости: принятый immutable source/image/receiptv3, работающий новый API reader,
сохранный первый архив и существующий deployment lease.

Существующийv3 executor ограничивает точный набор трёх targets и не может менять
основной Compose. Поэтому подготовлен отдельный узкий one-file adapter на тех же
atomic/lease/audit primitives; это воспроизводимый blocker применения прежнего
helper, а не новый общий rollout framework. Его source-free preflight проверяет
typed receipt, pinned image/helper/verifier/executor, before/after bytes и оба
эффективных Compose paths. Полный source gate не повторяется: source/archive/image
не меняются; новый payload не наследует deployment approvalv3.

Сравнение реально используемого worker96a570c1 и acceptedc2ca3bc9:235modules в
каждом, отличается только `sources/eis_no_data_evidence.py`;234остальных exact.
Staged bare Compose отличается только worker.image; active overlay полностью
идентичен. Четыре offline boundary checks PASS: wrong exact hash, missing approval,
успешная атомарная замена, rollback при несовпадении postcheck. Real preflight PASS,
source requests0/production writes0. Новый adapter ещё не применялся.

Точный план `worker-route-plan-v3-1.json`, SHA256:
`03a4f724cf4fe36f97193668e452d36d763d2294efd125ace88c5031bece8ea6`.
Executor `activate-worker-route-v3-1.py`, SHA256:
`5495373f0a1fb4df70eb6de1e944e34822d3c10343258808ec9b6c8bcb0cc5d3`.
Before ComposeSHA`3f44916d87a1d5852dc29128d0797f93fc106cccd0ee5967ba6092c98caf5774`;
afterSHA`dfccf9f2f316ee82d0b2875520644d1a9d676afc3d291e6d735f9b6ec0500ebc`.
Evidence рядом: `worker-route-scope-proof-v3-1.json`,
`worker-route-boundary-proof-v3-1.json`, `worker-route-preflight-v3-1.json`.

Следующее действие: новое exact approval указанной однострочной коррекции,
применение под existing deployment lease, затем реальный ordinary cron c принятым
worker image и RETAINED/raw+manifest/audit/journal proof. API reader не понижать,
оба store и все audit references сохранять. Уже потерянные raw41ответов не
реконструируются и не становятся RETAINED задним числом.

## Коррекция применена, bounded recovery подтверждено — 21 октября

Пользователь подтвердил предложенный exact payloadv3.1 SHA256
`03a4f724cf4fe36f97193668e452d36d763d2294efd125ace88c5031bece8ea6`.
Повторные hashes/preflight PASS. Apply завершён13:51:54UTC; approval reference
`user-chat-20261021-confirm-worker-route-03a4f724cf4f`, operation ID
`a757bb27-69d4-403d-b80d-1a17d95fe24f`. В основном Compose атомарно заменён
только worker image. API/web/DB не перезапускались; running container IDs, schema,
cron, все прочие bare параметры и полный active-overlay config совпали.
Audit/proof: `worker-route-activation-v3-1.json`; install/postcheck записаны
в tenant-scoped центральный audit. Исходныйv3/cache cleanup повторно не запускались.

Обычный priority cron запустил worker13:52:03UTC; реальный image при inspect:
`sha256:c2ca3bc9c739605dcb34916e7973ced8c75b06eaf51ddb951425ad0c91b3b2c6`.
Container `af552a213bd6…`, evidence `ordinary-worker-process-v3-1.json`.
Цикл обработал51window:12SYNCED/39NO_DATA,118new versions/2events. Он уступил
источник штатной223задаче с reasonFRESH_223_WORK_READY; это cooperative yield,
не ошибка источника и не доказательство завершения всей очереди.
Ручные source requests0; cron/pacing/source budgets не менялись.

READ ONLY snapshots13:55:25UTC since13:51:54UTC:
39RETAINED/0FAILED,39NO_DATA attempts,0missing capture audit, audit completenessPASS.
Overflow39rows, payload50414bytes, DB110592bytes; metadata countersMATCH.
Оставшаяся квота второго DB134107136bytes, лимиты обоих сегментов прежние.
Offline report проверил20samples: raw reparse20/20PASS, manifest/audit bindingPASS,
journal identity/time/actor match20/20PASS. Эти samples не выдаются за reparse всех39.
Первый128MiB архив сохранилSHA256
`f6055e5c49214308947d64043b0c32fd4f6d07a1786e91c67ea15abe1d52d692`;
три старые raw/manifest references PASS после реального перехода. Installed module
SHA10cb0bf9… совпадает с source/image proof. API health/UI HTTP200, df около69GiBfree.

Store report `s199-store-health-52e162c1-e807-4c00-94b5-648ae4ddd86f.json`, SHA256
`7d968d417cf35b59b85d1be32a403af6dd518997724101f532bac84493446fa5`.
Offline report `s198-offline-replies-8635be4e-ee9c-48b1-87ae-e90aa07072f4.json`, SHA256
`42ad5b581876bfa6f76a76ee942c8bc05e7c9bc37f614fe9cae3fbdf577f8541`.
Оба original proofs в `/var/lib/eis-browser/research/rejected/`; hashes локальных
полных copies проверены. Summary/proofs в каталогеv3:
`store-postcheck-v3-1.json`, `offline-postcheck-v3-1.json` и варианты`-full.json`,
`archive-postcheck-v3-1.json`, `ordinary-cron-summary-v3-1.json`,
`recovery-proof-v3-1.json`. Последний связывает activation/process/reports/archive
и recorded outcomePOSTCHECK_PASS_BOUNDED_RETENTION с company_id и operation ID.

Срез принят только как восстановление нового bounded NO_DATA evidence capture
с сохранением старых references. Предыдущие утраченные raw не восстановлены;
snapshot18failed windows, национальный coverage, sustained freshness, коммерческий
API и backup lifecycle остаются отдельными незавершёнными направлениями.
Следующий bounded шаг: source-free разбор одного DUPLICATE_NOTICE_VERSION по
сохранённым raw/journal; guards не ослаблять. Текущие docs изменены после sealing,
quality source/image не менялись, полный gate повторно не требовался.
