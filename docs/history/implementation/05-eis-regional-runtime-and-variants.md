> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

### S166 — охват и эффективность: аудит и три исправления (завершён)

Пользователь разрешил субагентов для независимой реализации/проверки и ресерча.
Milestone A: root владеет sources/eis_freshness.py, новым
eis_freshness_dispatch_cli.py, scripts/server-eis-priority.sh,
tests/test_eis_freshness.py, новым tests/test_eis_freshness_dispatch.py,
integration/test_eis_notice_index_pg.py, docs/15/28/README.
Acceptance: read-only tenant probe READY/IDLE/BLOCKED до priority marker/global
lock; idle cron не прерывает corpus и не планирует/не пишет audit/не делает HTTP;
отсутствующие due targets учитываются, budget/quota/lease/atomic boundaries
сохранены. Runtime может повторно проверить очередь под lock. Tests + isolatedPG
no writes; deploy/реальный idle proof и метрики, без обещания полногоЕИС.

Независимые bounded задачи:
- Astra: owner нового docs/research/41-eis-architecture-effectiveness.md; read-only review
  кода, PRD3.1–3.5, ops и плана. Acceptance: bottlenecks со ссылками на строки,
  throughput/coverage vs UNKNOWN, приоритеты именно для поиска выгодных свежих
  закупок; review предлагаемого S166 исправления, никаких production writes.
- Sol: owner sources/eis_feed_archive.py, tests/test_eis_feed_archive.py,
  нового docs/eis/ingestion/43-eis-attachment-limit-review.md. Acceptance: выяснить реальный
  ATTACHMENT_COUNT_LIMIT по сохранённым samples на VPS; если это искусственный
  малый cap, реализовать bounded source metadata handling с явной неполнотой/
  truncation и provenance, не ослабляя ZIP/XML/ресурсные гейты. Без admission,
  schema/deploy/network writes. Согласовать contract с root до поведения.
- Research: owner нового docs/research/42-eis-acquisition-research.md; primary official
  sources/публичные документы providers и текущая реализация, без production
  requests/секретов. Acceptance: сравнение каналов по полноте/свежести/цене/
  ограничениям, проверенные факты vs гипотезы, конкретные применимые шаги.
Дополнительно root owns storage/eis_freshness_requests.py: read-only selection
foreground requests без journal.plan, иначе idle probe мог пропускать пользовательскую
очередь вне baseline regions. Acceptance: тот же due/expiry/fairness contract.
Shared docs/15 и deploy только root. Изменения следующих milestones после
завершения и проверки A; файлы агентов не пересекаются.

S166 B: root owns sources/eis_freshness_status.py и
tests/test_eis_freshness_status.py. После A focused/review исправить drift
capacity bound 4 vs 5 supported types. Acceptance: поддержанный default scope
не бросает CAPACITY_SCOPE_INVALID; unsupported cardinality rejected,
metrics/UNKNOWN semantics прежние. Metadata contract Sol после его focused
tests и Astra review включается в B; deploy только после isolatedPG gate A/B.

S166 C: Sol owns sources/eis_corpus.py, eis_corpus_cli.py,
tests/test_eis_corpus.py и новый docs/eis/ingestion/44-eis-corpus-transport.md. Подготовка
независима от A/B, admission/deploy последовательно после A/B. Acceptance:
один reusable lazy transport на bounded corpus pass, последовательность,
source lock/quota, двухсекундный spacing, atomic-window yield, resource
gates и journal неизменны; idle/priority/block не открывает браузер и не делает
source calls. Контракт transport optional сохраняет callers. Focused tests,
root/Astra review, isolatedPG и измерение VPS без claims performance/fullEIS.

S166 A verification обнаружила устаревшие request tests: четыре типа вместо
пяти. Root additionally owns tests/test_eis_freshness_requests.py; ожидания
выводятся из подтверждённого SUPPORTED_NOTICE_TYPES, без изменения policy.
Sol contract согласован: metadata≤4096 сохраняется полностью; выше hard
ATTACHMENT_METADATA_COUNT_LIMIT, без truncation/download budget changes.

S166 A/B deployed 2026-10-03:56 local passed,3 shell tests skipped onWindows;
62 isolatedPG passed;266Linux focused passed (включая3 shell boundary checks).
Ruff/mypy passed, независимый Astra review. Code/schema-only backups,HEAD_11
без новой migration, testDB удалена. Live read probe13–17ms, attempts/targets/
audit/versions/windows и marker mtime до=после. Default scope15 due;
реальный IDLE cron ещё ожидается, не подменён synthetic проверкой.
Proof VPS s166-dispatch-proof-20261003T081455878601Z.json,
SHA35ff7718ba1aae7d63339bce537e6d0d176cd2302a4cf114b0b24952126025a4.
Пять supportedtypescapacity status теперьработает;observed p95=7850.388ms,
822completed/98failed из920samples,nominal/measured288slots/h в boundedscope.
Это историческое наблюдение limited3regions, не гарантия all-regions freshness.

S166C подготовлен Sol и просмотрен Astra/root;27localtests,Ruff/mypy passed.
Deployment/live transport reuse proof после отдельного Linux gate.

S166C deployed:37Linux tests passed,27local,Ruff/mypy и Astra/root review.
Live2windows:одна browser initialization,один underlyingtransport,4readycalls,
pageclosedпослеcontextexit. SYNCED3newversions+NO_DATA, оба journal attempts
имеют responseSHA; суммарно40.702s (включаяSQLвыборку),windows7.760s/2.626s.
Это bounded lifecycle proof, speedup/общийSLA UNKNOWN.
ProofVPS s166c-transport-proof-20261003T081848119563Z.json,
SHA980ccbaef7053cea55bb3032d308002b056a1006611c5abdbb040222585b6a96.

Следующий S167 — шанс свежим исправленным failures при большом historical
backlog. Owner Sol: sources/eis_corpus.py, tests/test_eis_corpus.py, отдельный
новый tests/integration/test_eis_corpus_fairness_pg.py и docs/eis/ingestion/45-eis-corpus-fairness.md.
Root owns docs15/28/README, helpers/gates/deploy. Dependencies:S166A/B/C gated
and deployed. Acceptance:до20%слотов boundedpass (ceil(limit/5),cap12) для
latestFAILED окон последних7завершённыхдней, далее прежняя очередь;dedup и
общийmaxwindows,24hcooldown,completedexcluded,tenant/snapshot/typedprovenance
не меняются. При limit1 единственныйduefailureможетзанятьодинslot; следующий
passпосленовойattempt24hbackoffдаётprogressостальным. SQLrepair selection
отattempts/recentkeys, а не ещё один expensivefullworklistscan. No network
вselector, no sourcequota/cadence/concurrency increase. Synthetic+PGtenant/
latest/completed/cooldown/backlog gates, review, измерениеselection time и
boundedliveproof. НеclaimзакрытиеFAILED безуспешногоsourceevidence.

S166A actual cron IDLE подтверждён2026-10-03T08:21:24.802320Z:
обычный server-eis-priority.sh вернулIDLE,baseline_due=foreground_due=0,
attempted=0безworkerlaunch. LogVPS /home/syurai/vibe-seller-state/
s166-live-priority.log, SHA3fc5e8425d1a7e9bd368d54281de0a4abe3319c170a9faf0c4764805c97f99ae.
Metadata77livefailures пока не объявлены исправленными: нужен новый atomic
sourceimport с этимparser. Публичный охват/свежесть всехрегионов UNKNOWN.

### S167 — повторы свежих ошибок (завершён)

Контракт, владелец и ownedfiles записаны выше; реализацияготовится отдельно
послезавершенияS166.

S166B livefollow-up08:29UTC: оба metadata-failed77windows сталиSYNCED
с atomiccheckpoints. EOK2026-10-02:1ZIP/36notices,max136attachments,
response50a3e369d966c658ccc392c12deadffa035c84ccce8815d15ae244acb339d2bc.
EF2026-09-30:6ZIP/595notices,max278attachments,
response21866c6b6f05330ec4de7f92b6f464339fd88967c9435adc7935ec708f4d6e2b.
СтарыеFAILEDattemptsсохранены;631XMLrecords в двухполныхокнах не равно631
новымуникальнымкарточкам. ProofVPS s166-metadata-proof-20261003T082914330927Z.json,
SHAea0aaeb16d00185992b4c5e67d4c05f378fdda85b36a187ac1097590688bd9d4.
Root additionallyowns finalizeddocs43 addendumпослепередачирезультатаSol.

S167 перваяSQLформа прошла63isolatedPG/279Linuxfocused; Astra review
выявилperfриск ROW_NUMBER на всейoldqueue. Доdeploy Sol меняет его на
прежнийORDERBYLIMIT передboundedROW_NUMBER; focusedPG повторится поfinalform.

S167 finalSQL gated:64 isolatedPG/279Linuxfocused passed;Ruff/mypy и
Astra/root review passed. PG повтор запущен на новой isolatedDB: повторное
использование прежнейБД сначала пересеклось с immutable projection history
в downgrade-тесте223; testDB пересоздана, production не затрагивалась.
Reserve latest/cooldown/checkpoint/tenant/limit/fill/tie/7day boundaries
проверены. Перед deploy проводится один old/new read-only timing на
одинаковом production scope и счётчиках, с60sstatementtimeout.

S167 deployed:до/послеsourcecountsравны[147364targets,8698attempts,3815windows,
160479audit]. Приsamechecked_atoldselection25.892s,new27.102s (+4.7%в одном
срезе);prefix12теперьduefailures01.10/30.09вместоhistory14.09. SQLsource
2f39177966616ba36457b2062dc11fff0611a58698b64b838df8475fcc4b7df8вrepo=image.
ProofVPS s167-selection-proof-20261003T084154455454Z.json,
SHAbe0ff3d6503773a30c36790aa5a149ef6622bbccd8f4b2a2157cf6acc477a307.
FullsourcecoverageUNKNOWN,ошибки не объявлены закрытыми безnewcheckpoint.

### S168 — стоимость SQL выбора corpus (завершён)

Измеренный selector25–27s — отдельный bottleneck, не сетьЕИС. OwnerSol:
sources/eis_corpus.py, tests/test_eis_corpus.py,
tests/integration/test_eis_corpus_fairness_pg.py и новый
docs/eis/ingestion/46-eis-corpus-selection-performance.md. Rootowns docs15/28/README,
gates/helpers/deploy. Dependencies:S166/S167 complete. Acceptance:replace
per-target correlatedMAX attempts with one tenant-filtered groupedMAX CTE
andLEFTJOIN; сохраняются exactoldhistoricalorder/nulls,cooldown,latestFAILED
repairlane,checkpoint exclusion/snapshot/dedup/limits. Безmigration,
index/recordmutation/sourceHTTP. PGcomparison latesttimestamps/fairness/tenant;
64existingPGgate+focused tests,Ruff/mypy,Astrareview. Old/newliteralresults
приsameclock+frozencountsдолжнысовпасть;timing с60stimeoutпередdeploy;
никакойSLAfullEISclaim.

Независимый research послеdocs42: ownerResearchнового
docs/eis/ingestion/47-eis-223-general-notice-contract.md. Read-only analysisофициальных
NSI/XSD16.3/retainedschemas и current223parser; выбратьодну publicgeneral
noticefamily, оценитьexactheader/lots/deadline/currency/UID/event/schema
contract, ownedruntimefiles иacceptanceдляследующегоslice. No sourceintake/
deploy/secretoutput. Цель — расширить223 за пределамиsmallbusinessregion50;
необъявлятьfamilyреализованнойпокодаплану.

S168 finalcode reviewAstra/root passed; Ruff/mypy passed. FullPG/Linux gate
на новойisolatedDB; fixedclock equality/performance admission передdeploy.

S168 deployed:64isolatedPG/279Linuxfocused,Ruff/mypy,Astra/rootreviewpassed.
Old/newexact60keysравны приsamechecked_at2026-10-03T08:50:34.554221Z;
sourcecountsunchanged[147364targets,8736attempts,3831windows,160534audit].
Измерение27.094537s→7.470841s (ratio0.276,около3.6раза в этом срезе).
Это latency backgroundselector, не всегоsourceintake/search и не allEISSLA.
Repo=imageSQLSHA5de1388a90bfebfac92d8ecb816144ae508cf7bce2675b9ad778edba0cc18fcc;
backup+scriptgates+apihealth passed,testDB удалена.
ProofVPS s168-selection-proof-20261003T085110562921Z.json,
SHA258011fdc578f3ff8f501574ba28c83fb599d0ad5dfbde6becd33bd4f380607a.

## Следующее продолжение послеS168

Research-only контрактgeneral223 сохранёнвdocs/47. `purchaseNoticeAE`
поofficialNSI/XSD — форматдо01.07.2018,хотяactual=true; егопростое
включениенедоказываетсвежийохват. ПредложенpurchaseNotice(«Инойспособ»,NSI62).
Retained25XML revalidation:24PASS/1FAIL обеихXSD;5лотовmaxContractPrice,
1lot-orientednotice,19naivedeadlines/6missing. Доadmission нужны typedprice
kind,lotdeadline/evidence,quarantineinvalidschema и отдельныеmigration/PG/
livegates. SOURCE_REJECTED исходногоS152probeсохранён; последующееexplicitadmission
реализовано вS169 ниже.
Приоритет:реализовать этотконтракт, затемрасширитьподтверждённыерегионы223
и дневнуюсверку, measurementofsource/searchrecall. Supplierprofit остаётся
зависимымотдействительныхКП/затрат/компании;загрузкаданныхнеподменяетих.

### S169 — общее извещение 223-ФЗ purchaseNotice (завершён, развёрнут)

Зависимости: S168, исследование [47](../../eis/ingestion/47-eis-223-general-notice-contract.md),
ADR-0051 и новое решение [ADR-0052](../../adr/0052-general-223-metadata.md).
Работа выполнена последовательно: типизированный парсер → хранилище и
потребители → проверки → развёртывание и новое окно источника.

Владельцы и файлы:

- Sol: `sources/eis_223_archive.py`, `sources/eis_223_sync.py`, соответствующие
  unit tests и новый `test_eis_223_general_archive.py`.
- Root: `storage/eis_223_*`, `storage/models.py`, `storage/eis_source_estimate.py`,
  новый `sources/eis_223_policy.py`, `sources/eis_223_documents.py`, миграция
  `20261003_01`, интеграционные проверки, серверный refresh, документация и rollout.
- Research: документация 49 и четыре файла UI: `procurement-api.ts`,
  `indexed-223-search.tsx`, `comparison-223.tsx`, `source-estimate.tsx`.
- Astra: ADR-0052, документация 48 и независимый review. Файлы задач не пересекались.

Контракт и acceptance выполнены:

- Явное семейство `purchaseNotice`, точные namespaces/identity и optional lotData.
- Вид цены, сумма, валюта, формула и исходные XML locators сохранены отдельно.
  `maxContractPrice` и неподдерживаемые формулы не становятся начальной ценой.
- Признаки МСП извещения и лотов сохраняются раздельно. Пропуск не означает допуск.
- Наивные даты остаются UNKNOWN; при сроках по лотам общий срок не применяется.
- documentFS/prev/additional/notPlacement сохраняются; неразрешённый manifest
  остаётся UNKNOWN. Скрытые файлы не скачиваются.
- Атомарно сохраняются все безопасно разобранные members возвращённого набора.
  Полная XSD quality независима: FAIL виден в сравнении и предварительном расчёте,
  исходный XML не исправляется, supplier hard gate из него не выводится.
- Подтверждённые hidden/accredited-only/invalidated source блокируют загрузку и
  расчёт; отменённый выбранный лот блокирует расчёт. UNKNOWN не становится PASS.
- Legacy snapshots, tenant RLS, immutable history, composite FK и replay сохранены.
  Downgrade защищает историю нового семейства во всех трёх таблицах.
- Refresh: три семейства × сегодня/вчера, прежний batch 2, регион 50 и бюджеты.

Проверки: **66 isolated PostgreSQL / 397 Linux focused tests**, Ruff/mypy девяти
файлов, ESLint, production build, TypeScript и независимый review прошли.
Это ограниченные suites; полный набор тестов репозитория не заявлен.

Сохранённая выборка: разобраны все 25 XML, 23 номера, 20 начальных и 5 максимальных
цен, 157 вложений. Три лота имеют признак МСП при отсутствии общего признака.
Официальные XSD 16.2/16.3: 24 PASS / 1 FAIL. Исходные JSON probe не изменены;
старое SOURCE_REJECTED не переписано.

Боевой VPS: API/worker/web обновлены, HEAD `20261003_01`. Новый запрос к ЕИС
за **2026-10-02, регион 50, purchaseNotice** принёс один ZIP: все **40 версий /
38 номеров** сохранены. Цены: 38 INITIAL_SUM / 2 MAX_CONTRACT_PRICE; подтверждённых
сроков с часовым поясом нет. XSD: 38 PASS / 2 FAIL на каждой версии схемы,
80 наблюдений качества; ошибочные members сохранены.

Первый live intake завершился в 09:42:41Z. После commit проверочный helper упал
из-за неверной распаковки результата preflight. Исправленная проверка использовала
тот же immutable response без нового запроса и записи журнала. Manifest и replay
проверены; повтор не добавил записи импорта. Ошибка helper не скрыта в evidence.

API и браузер проверены на `32615966906`, v15: максимальная цена договора
6 млн RUB показана отдельно; предварительная экономика UNKNOWN, сценариев нет.
Синтетические затраты использовались только для проверки, действительное КП
не заявлено. Read-only comparison/search не изменили счётчики. Запрос
«металлоконструкций» дал одно совпадение примерно за 39 мс в одном HTTP sample;
это не SLA и не доказательство полноты поиска.

ТЗ DOCX этой карточки скачан через обычный consumer: один из восьми файлов,
32 извлечённых фрагмента, статус извлечения и проверки требований UNKNOWN.
Комплект INCOMPLETE. Подтверждено прохождение файла через pipeline, а не полное ТЗ.

Proof files на VPS, `/var/lib/eis-browser/research/`:

| Проверка | Файл | SHA-256 |
|---|---|---|
| Retained | `s169-retained-proof-20261003T094121Z.json` | `df472ad7c995f58b6af72262fb5f6e7d88de191396c8b861451788e3d49866ff` |
| Live/replay | `s169-live-proof-20261003T094418Z.json` | `ba5358821f7c19746ef4d78d1f0137e7ea27a8e807d3eea308553f06c5d47875` |
| API | `s169-api-proof-20261003T094541Z.json` | `a7878b69ec79fa5fb22b1fac446fae8d551ca35f8ca0d8e9d8d3701dd24df0f9` |
| Документ | `s169-document-proof-20261003T094741Z.json` | `ea4cf1308dcc257cced77895da44e2542bab37ea2ba7398e232272d303328313` |

Backup, script gates и health прошли; временная БД удалена, priority marker снят,
штатный cron продолжает работу. Код парсера, модели и UI совпадает с образом.
Свободно около 263 GiB на VPS; новые данные не скачивались на ноутбук.

Следующий ограниченный этап: события отклонения/отмены 223-ФЗ и актуальные gates,
затем расширение регионов и дневная сверка. Полный охват ЕИС, подтверждённая
прибыль и полнота требований остаются UNKNOWN.

### S170 — события отмены закупок 223-ФЗ (deployed)

Зависимости: S169 deployed; точный источник — [50](../../eis/ingestion/50-eis-223-cancellation-contract.md).
Первое семейство — purchaseRejection (отмена всей закупки). Отмена отдельных
лотов, восстановление и расширение регионов требуют следующих контрактов.
Milestones: M1 parser/schema/event policy → M2 immutable event storage + shared
consumer hold + refresh → M3 isolated PostgreSQL/Linux/UI gates → M4 VPS live.

Владельцы и файлы до начала реализации:

- Sol: новые `sources/eis_223_events.py`, `sources/eis_223_event_sync.py`,
  `tests/test_eis_223_events.py`, `tests/test_eis_223_event_sync.py`.
- Root: новые `storage/eis_223_events.py`, таблицы `storage/models.py`, миграция
  `20261003_02`; consumers `storage/eis_223_index.py`, `eis_223_documents.py`,
  `eis_223_comparison.py`, `eis_source_estimate.py`; refresh `storage/eis_223_sync.py`,
  `scripts/server-eis-223-refresh.py` и необходимые scoped tests; docs15/28/37/README,
  helpers, gates, deployment.
- Research: новый docs50; затем отдельные UI types/search/comparison/estimate
  файлы, по зафиксированному root контракту, без пересечений runtime.
- Astra: новый ADR0053 и docs51; policy и независимый review.

Acceptance: событие имеет собственный GUID и точный номер связи, без выдуманной
notice version/status; root/Data/namespace/ZIP guards и provenance обязательны.
Полная XSD quality независима и привязана к точному событию/SHA. Время без зоны,
нет событий, неоднозначность/конфликт/будущее означают UNKNOWN; операция требует
сверки. Подтверждённая отмена блокирует кандидата; более поздний notice/высокая
цена не снимают blocker. Все факты событий и архивы immutable и tenant-scoped;
событие может предшествовать загрузке notice. Shared read snapshot и batched
lookup в поиске, повторная проверка при скачивании. Архивный набор атомарный;
replay не создаёт дополнительные source записи; конфликты сохраняют evidence.
Регион50, действующие 2 windows / 180s и cadence без расширения квоты. NO_DATA
не подтверждает отсутствие отмен. Код событий не расширяет notice enum.

S170 Root owned-files уточнение перед M2: новый sources/eis_223_event_quality_worker.py
и tests/integration/test_eis_223_events_pg.py — offline quality и PostgreSQL gates.

S170 review расширил Root owned-files: storage/eis_223_document_queue.py
и sources/eis_223_document_worker.py — held jobs не занимают dispatch;
общий deadline predicate использует effective selected_deadline для generic.

S170 M1–M3: parser + exact schema evidence + immutable GUID/SHA storage и все
consumers реализованы. Независимый review нашёл три дефекта и проверил исправления:
пустая причина confirmed hold, противоречивые даты, выбор held jobs очередью.
Изолированный PostgreSQL: **75 passed**, включая prior downgrade gates до новой
history, cross-number variants, replay, RLS/immutable, queued job hold,
запрет downloader и BLOCKED estimate без сценариев. Linux focused: **421 passed**;
исправлены три legacy mocks, не принимающие новый include_events keyword.
Ruff/mypy9 source files, full web build и ESLint PASS. M4 deployment/live pending.


S170 M4: **DEPLOYED, 2026-10-03**, HEAD `20261003_02`. Code/schema backup,
script executable/bash gates, build/migration/health прошли. Код парсера,
storage/models и UI в локальном checkout, server repo и контейнерах совпадает.
Cron frequency/net quotas не изменены; новый family делит прежний budget.

Боевые проверки, family purchaseRejection / region50:

- 02.10: официальный NO_DATA, 3.536s. Он не подтверждает отсутствие отмен.
- 01.10: отдельное bounded operator окно; SYNCED, весь один ZIP, **1 событие /
  1 номер**, **18 753 bytes**, 22.469s. Это targeted validation, не расширение
  автоматической истории today/previous day.
- Реальная связь: GUID `4eee1725-c622-4fbd-a8dc-ff897b60bd7f`, номер
  `32616425280`. XML SHA `cd6420ac49b67d09b1f77ff39da6652113eb2205c7d14e9199261e8d2124f4e9`.
  В filename источника есть null; version/status не выдуманы.
- Реальный XML PASS по обеим полным официальным XSD16.2/16.3, две immutable
  quality записи. Publication `2026-10-01T11:09:27`, rejection
  `2026-10-01T10:25:35` без зоны: evidence/application **UNKNOWN + operation hold**.
- Событие получено до notice: этот business number пока отсутствовал в notice
  индексе. Нет синтетической notice строки, рекомендации или fake live UI FAIL.
- Replay и cached read не создали записи. Отдельный synthetic XML тоже PASS
  по pinned schemas и confirmed hold, source requests/production writes =0.
- Authenticated HTTP comparison/source estimate/document status/search возвращают
  typed cancellation state и current procedure UNKNOWN; счётчики неизменны.
  Один metal search sample ~40ms; не SLA/полнота поиска.
- Браузер показывает новые пояснения в реальной существующей карточке
  `32615966906`: отсутствие event не означает PASS. 112 current notices /17
  windows в момент UI проверки, охват/свежесть UNKNOWN. Снимок
  `data/research/eis-documents-2026-10-02/s170-cancellation-ui.jpg`.

Дополнительные две scheduler routing regressions проверяют event NO_DATA/SYNCED
без notice version и общий batch cap: новый файл25tests PASS на локальной среде
и Linux. Итого focused union **423**, PG **75**; до добавления routing tests
основной Linux gate421 PASS. Runtime не менялся после основных gates.
Первый helper full-XSD импортировал test module без pytest и остановился до
source call; исправлен на literal synthetic bytes. Дополнительный routing helper
сначала не смонтировал scripts, затем mount исправлен и25 PASS. Эти ошибки
проверочного окружения не превратились в source success.

Proof files на VPS, `/var/lib/eis-browser/research/`:

| Проверка | Файл | SHA-256 |
|---|---|---|
| NO_DATA | `s170-live-proof-20261003T110613Z.json` | `5557cc6a65e68ea84cddc8759cf608665a1c9afe054b9ea16fdd2d0d39901d46` |
| Real event / replay / XSD | `s170-live-proof-20261003T111127Z.json` | `c5752513370254fcf68c49708fd54cf1f54ad67bfae0d02b654c6ca8d9192ccd` |
| Synthetic pinned XSD | `s170-synthetic-schema-proof-20261003T111125Z.json` | `c6695fd924d38cce29a397a1fe611aad77ead90a002ff3656f666e27b0548074` |
| Cached HTTP | `s170-api-proof-20261003T110820Z.json` | `25db5617776b15050efb8728e44fee902c2c51d1d19b8294a6eb874ab93e264f` |

Тестовая БД удалена; priority marker снят. Свободно ~262GiB на VPS,
API~110MiB/1GiB, web~62MiB/768MiB, DB~616MiB/2GiB. Raw source остаётся на VPS.
Полный охват ЕИС, восстановление процедур, полное ТЗ/КП и прибыль UNKNOWN.

### S171 — события отмены отдельных лотов223 (deployed, связь с версией UNKNOWN)

Порядок: official exact lot identity/source contract → strict parser/schema +
immutable lot events → shared lot gate/search/document/estimate → isolated PG,
real bounded source probe, deploy. Сначала выяснить GUID vs source ordinal vs
array index; не наследовать whole-purchase semantics. При неоднозначной связи
UNKNOWN+verification hold; не блокировать заведомо другой lot по догадке.
Владельцы/owned files/acceptance зафиксированы ниже до первой code mutation.
Затем — расширение регионов с ledger свежести, первичная выборка текущих карточек
и дневная сверка пропусков. До reconciliation labels полного охвата не выдаются.


S171 M1 начат 03.10.2026. Владельцы и owned files до code mutation:

- Sol: новые sources/eis_223_lot_events.py, eis_223_lot_event_sync.py и два
  соответствующих unit test файла. Точные reader/transport, без persisted writes.
- Root: отдельные storage/eis_223_lot_events.py, sources/eis_223_lot_event_policy.py,
  sources/eis_223_lot_event_quality_worker.py; storage/models.py, миграция
  20261003_03; shared consumers/index/documents/queue/comparison/source estimate,
  storage/eis_223_sync.py, server refresh, необходимые scoped tests;
  docs15/28/37/README, rollout/proof helpers. До изменения UI владельцы уточняются.
- Research: только новый docs52 — official exact source contract.
- Astra: только ADR0054/docs53 и независимый review runtime.

Acceptance: точный family purchaseLotCancellation, неизменяемый собственный
GUID/XML SHA и все returned members/archives. Purchase number, source ordinal,
source GUID и индекс массива хранятся раздельно. COMMON/VARIOUS и date-only
решение не превращаются в придуманное время; naive/пропуски/неоднозначная
связь UNKNOWN. Отмена лота не становится whole-purchase FAIL. Schema checks
exact16.2/16.3 независимы от semantic completeness. RLS/replay/variant conflicts,
событие до notice и обязательная повторная проверка document receipt. Общие
2windows/180s/ресурсные лимиты не расширяются. Неполный slice не объявляется
полным охватом или подтверждённым применением отмен всех лотов.

S171 UI owner уточнение перед mutation: Research — procurement-api.ts,
indexed-223-search.tsx, comparison-223.tsx, source-estimate.tsx и новый
lot-cancellation223-state.tsx. Root owns новый tests/test_eis_223_lot_event_policy.py
и tests/integration/test_eis_223_lot_events_pg.py.

S171 M2/M3: typed reader + immutable lot evidence + shared consumers implemented.
Независимый Astra review: два дефекта исправлены (overflow selected-state reason,
JSON byte preflight). До materialization metadata проверяет <=2000rows,
<=100variants/number, <=8MiB serialized JSON; иначе UNKNOWN hold.
Local focused438PASS/16Linux-onlySKIP; Linux454PASS (те же tests).
Изолированная PostgreSQL84PASS (prior75 +9lot gates); RLS/immutable/replay,
событие до notice, variant conflict, новые версии не снимают hold, downloader
не вызывается, estimate BLOCKED без сценариев, downgrade сохраняет историю.
Ruff/mypy10 runtime files PASS; UI build/ESLint PASS. На момент M3 deployment ещё не выполнялся.
Действующий budget сохраняется:10targets today/previousday делят2windows180s;
offline2event variants чередуются между whole/lot family в cron11/41 slots,
notice quality2 прежние. Семантика selectedlot/current procedure UNKNOWN-only,
пока не доказана стабильная связь идентификаторов и версии извещения.


S171 M4: **DEPLOYED 03.10.2026**, HEAD `20261003_03`. Code/schema backups,
script gates, api/worker/web builds, migration/health PASS. Server31files и
API image14runtime/migration files совпали с точными локальными hashes;
отдельные14 файлов не включают web: frontend вошёл в проверенную Docker build.
Тестовая БД удалена, priority marker снят, cron продолжает обычный bounded refresh.

Боевые probes region50/purchaseLotCancellation:

- 02.10: официальный NO_DATA, 3.552s.
- 01.10: отдельное targeted validation окно, официальный NO_DATA, 3.614s.
- Новых реальных lot XML/архивов не получено. Оба ответа не подтверждают
  отсутствие отмен, полноту базы или связь GUID с текущей версией лота.
- Минимальный синтетический XML прошёл обе полные pinned XSD16.2/16.3;
  policy UNKNOWN+hold. Production writes/source requests этой проверки =0.
- Cached authenticated comparison/documents/search/source estimate показывают
  typed lot state. Проверка не изменила counters и не обращалась к ЕИС.
  Один search sample41ms, не SLA. Максимальная цена договора по-прежнему не
  превращается в подтверждённую выручку; сценариев при UNKNOWN потолке нет.
- Браузер реальной существующей карточки32615966906 показывает новый отдельный
  блок «Проверка отмены лотов: UNKNOWN». Событий нет в проверенном scope;
  подтверждённая отмена лота в UI не заявлена. 112 актуальных сохранённых
  извещений/17окон на момент проверки. Screenshot:
  `data/research/eis-documents-2026-10-02/s171-lot-cancellation-ui.jpg`.

Proof files, VPS `/var/lib/eis-browser/research/`:

| Проверка | Файл | SHA-256 |
|---|---|---|
| NO_DATA02.10 | `s171-live-proof-20261003T120404Z.json` | `b3539abcf0a6c80d3c2716a4c17d599ce6199e4984ee2eb0da2a124ee35017b6` |
| NO_DATA01.10 | `s171-live-proof-20261003T120510Z.json` | `364550e03e433f17f696324b3f007f92db826e09a81c5f4f2711990c0c47e075` |
| Synthetic full XSD | `s171-synthetic-schema-proof-20261003T120402Z.json` | `9e226dc2d0b9c145205ac1a4544bff94298a2d1cf181a821f6c5593d535d77fc` |
| Cached HTTP | `s171-api-proof-20261003T120515Z.json` | `192e6c58929ee3f5c033cfb599f3f2e8d83a59c15eef0705033f69f792f8fa23` |

В этом срезе завершены bounded evidence intake, visible UNKNOWN review hold,
хранение и защита операций. Stable lot identity/revision и первый положительный
боевой XML остаются отдельными незавершёнными проверками. Они не блокируют
следующий этап измеримого расширения source coverage.
Свободно261GiB на VPS; API111.7MiB/1GiB, web62.35MiB/768MiB, DB616MiB/2GiB.
Raw/source processing остаётся на VPS; memory cap проверяется до materialization.

### S172 — автоматический охват регионов223 и измеримая свежесть (следующий этап)

Уточнение03.10 по вопросу пользователя: цель — быстрый поиск и сравнение
актуальных публичных закупок по всей ЕИС.77/78 были первыми контрольными
выборками, не конечным scope и не отдельными региональными адаптерами.
Один parameterized transport/loader и общий scheduler должны автоматически
обслуживать весь подтверждённый официальный каталог region codes. Новый
регион — запись каталога/конфигурации, не новый парсер или code milestone.

Последовательность:

1. Проверить официальный каталог и точный смысл region selection в export API;
   сохранить его version/provenance. Регион выгрузки не подменяет географию
   поставки, коммерческий профиль или ограничение пользовательского поиска.
2. Обобщить действующие50-only transport/attempt contracts до параметризуемого
   scope с совместимостью старых windows. Общая tenant очередь region/family/day,
   fairness/backoff и bounded returned sets; каталог покрывается автоматически.
3. Проверить механизм на небольшой контрольной выборке, включая77/78; после
   gate обслуживать весь подтверждённый каталог той же реализацией. Не ждать
   отдельной разработки/ручного включения каждого региона. Если ограниченный
   budget не обеспечивает свежесть, измерить throughput/lag и оптимизировать
   планировщик/доступную concurrency в пределах source quotas и VPS budgets.
4. Создать compact metadata index актуальных процедур и начальную выборку;
   отслеживать фактически обработанные/отложенные/failed partitions и свежесть.
   Дедупликация business number/version across regions обязательна. NO_DATA
   означает только exact queried window; непройденный scope остаётся UNKNOWN.
5. Пользовательский запрос быстро выбирает кандидатов из обновляемого индекса;
   карточки и документы выбранных кандидатов догружаются по требованию на VPS.
   Полный исторический архив и все вложения не являются зависимостью поиска.
6. Дневная сверка пропусков и контрольная независимая выборка; PostgreSQL/API/UI
   gates. Labels полного охвата разрешены только для доказанного точного scope.

На момент планирования M1 runtime223 обслуживал регион50; deployment S172 ниже
включает единую региональную очередь.
Это уточнение плана, не сообщение о завершённом rollout. Owner уточнения:Root,
owned docs15/docs37; runtime owners/owned files/acceptance фиксируются перед
следующей code mutation. S171 UNKNOWN lot identity остаётся отдельной задачей
и не заменяет приоритет общего охвата свежих карточек.


S172 M1 начат. Owners/owned files до mutation:

- Research: docs54 — official region catalog/meaning/provenance. UI ownership
  фиксируется отдельно после root API contract. Новые token source calls запрещены.
- Sol: sources/eis_223_sync.py, eis_223_event_sync.py, eis_223_lot_event_sync.py;
  соответствующие unit tests (transport portion tests/test_eis_223_sync.py).
- Root: новый sources/eis_223_regions.py; storage/eis_223_regions.py,
  storage/eis_223_sync.py, source index/admission region guards; storage/models.py,
  migration20261003_04 и нужные historical migration constraints; api/app.py,
  scripts/server-eis-223-refresh.py/.sh, docker-compose.server.yml (если потребуется
  передача catalog config); PG/scheduler/coverage tests, docs15/28/37/README,
  rollout/proof helpers. Runner tests после окончания Sol transport edits.
- Astra: ADR0055/docs55 и independent review. Runtime files не пересекаются.

Acceptance: параметризованный region с legacy default50, точный SOAP/key и
проверенный официальный region catalog, не генерация всех01..99 как active.
Tenant immutable catalog/wave/targets + существующие append-only attempt journals.
Конечные frozen-date волны не теряют незагруженные цели при смене суток.
Fairness/retry cooldown, shared checkpoint proof и provenance; NO_DATA не fullEIS.
Coverage API/UI показывает planned/completed/noData/failed/pending и возраст,
не выдаёт общероссийскую свежесть до сверки. Same-number/version across-regions
дедуплицируется без потери source receipts. Typed/PG/web/real bounded gates,
мigrations downgrade сохраняет regional history. Первые77/78 — контрольный probe,
весь каталог обрабатывается тем же алгоритмом без отдельных code steps.

Пилот2windows/30min даёт <=96attempts/day: для~990targets это>=10days и не
обеспечивает дневную свежесть. После source gates один последовательный run
bounded32windows/600s, прежние2cron slots/hour: theoretical<=1536attempts/day.
HTTP/source quotas, archive expansion, CPU/memory2GiB,DB100GiB/free40GiB остаются
ограничителями; реальный throughput/lock contention измеряются и показываются.
Это capacity ceiling, не обещанный SLA. Нет новой фоново запущенной работы до deploy.

S172 M1–M4 проверены03.10; deployment завершён (evidence ниже). Runtime owners после завершения
Sol:Root принимает models/migrations для последующих точечных исправлений.
Дополнительный Sol UI owner: procurement-api.ts, tender-discovery/actions.ts,
page.tsx, новыйregional-coverage.tsx; typed GET+readonly refresh, dynamic rendering.

Фактический каталог: PUBLIC_KLADR_SELECTOR,90 уникальных code/name из официального
https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html,22514bytes,
SHA b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d.
Полные11-character IDs сохранены в rawHTML. Два первых знака берутся только у
верхнего КЛАДР-объекта с девятью нулями; current-getDocs mapping дополнительно
проверен реальными77/78 controls. NSI isActual для всех90 не заявлен. nsiAllList
дал249entries; nsiSubjectRF/all и nsiKLADRShort/all NO_DATA. Подробностиdocs54.

One loader/one scheduler автоматически планирует все90codes ×5families ×2dates:
900immutabletargets. Family→region→adjacent current/previous dates; вчерашние
карточки не ждут полного прохода пустого сегодняшнего дня. Failed старых waves
остаются в retry lane; ранний retry slot переживает budget cutoff. Непройденные
окна не исчезают при смене суток. Catch-up даты продвигаются максимум на2дня,
не пропускают промежутки; новаяwave послеfirstsweep+>=24h, error≠complete.

Worker regional32windows/600s start budget; started window имеет собственный180s
source timeout, atomic READY intake не отменяется посередине batch deadline.
Overrun явен. DB100GiB/free40GiB проверяются перед каждым новым окном; resource
threshold допускает только один bounded in-flight overrun, не31imports подряд.
Local errors/PREPARING не блокируют другие регионы; global service/transport
ошибка прекращаетrun. Source SOAP posts/archive GETs измеряются, fullsetcaps
не повышены. Regional selected count не подменяет весь due/deferred backlog.

Gates:90PostgreSQL (fresh upgrade +tenant/RLS/immutable/replay/midnight/fairness/
oldgap/catchup/watermark/cross-regiondedup/downgrade),484Linux focused before
final parser guard,16focused latest catalog/runner gates; Ruff/mypy/web ESLint/
productionbuild PASS. Отдельная пустая testDB:03→04→03 восстанавливает literal50
CHECKs; deeper downgrade01→HEAD PASS. Все test data synthetic, кроме live controls.
Architecture review исправления: early retry, continue local failure, exactDOM
closure/placeholder, honestcounter, повторныйresourcegate. Новыеregionalhistory
guard запрещает откат при новойhistory любогоtenant; historical CHECKs заморожены.

Live controls за02.10 purchaseNoticeAESMBO:77SYNCED23.381s/2POST+2GET/2ZIP,
78SYNCED17.316s/2POST+1GET/1ZIP. Полныеboundedarchives сохраненыVPS; proof
/research/regions/s172-controls-20261003T173136Z.json. Пока0DBwrites, admission
послеdeployment повторно использует exact bytes без нового source download.
ПолнаяЕИС, все223families и своевременное обслуживание всех900окон ещё UNKNOWN.

### S172 deployment и первый региональный пакет — завершены 03.10.2026

Owner Root; acceptance текущего slice выполнен: общий загрузчик всех90кодов,
immutable wave/backlog, tenant API/UI, реальная загрузка и автоматический cron.
VPS api/worker/web пересобраны, schema HEAD `20261003_04`; перед изменением
сохранены code/schema backups. Две изолированные testDB удалены после gates.
Публичный каталог загружен однократно, его автоматическое обновление ещё pending.

- Admission proof: `/var/lib/eis-browser/research/regions/s172-admission-20261003T174923Z.json`.
  Повторно использованы контрольные ZIP77/78 без нового source request:
  108+14 новых версий, replay без записей. Wave
  `735f19c4-7fce-4f2a-b5a4-b596ae07c501`:900целей,02–03.10.2026.
- Первый общий run: `/home/syurai/vibe-seller-state/s172-first-refresh.json`.
  32окна за331.323s,40SOAP POST/8archive GET;8SYNCED/24NO_DATA/0ошибок,
  102новых версии; batch overrun0. Offline quality:2извещения/4checks,
  failed0, source requests0. Это один пакет, не SLA дальнейших суток.
- На17:55:50UTC:44/900окон terminal (14SYNCED/30NO_DATA),856не начато,
  19регионов начато/1завершён по всем пяти families за обе даты; old gaps0.
  Whole coverage/freshness UNKNOWN. NO_DATA относится только к точному окну.
- Read-only API proof: `/var/lib/eis-browser/research/regions/s172-final-api-20261003T180833Z.json`,
  SHA `9090da9596e191d411b63f9e1dc86b9017236eee3b7a7fc6dea4ffc60accfbab`.
  Coverage GET200/no-store21.41ms; индекс330current. API «бумага»28.83ms/7matches,
  «серверное оборудование»154.48ms/20matches. Затраты/КП не заданы,
  поэтому эти результаты не доказывают прибыльность или право участия.
  PostgreSQL2840345623bytes. Сетевой поиск при этих API reads не выполнялся.
- Браузерная проверка нового deploy:90/900,44terminal, даты/официальный источник
  и неподтверждённая свежесть отображаются корректно. Screenshot
  `data/research/eis-documents-2026-10-02/s172-regional-ui.png` (локальный ignored proof).
  SSH tunnel3000→VPS13000 обеспечивает локальный тестовый интерфейс.
- Наблюдение ресурсов: regional worker~252MiB при лимите2GiB,
  DB~633MiB/2GiB, API~110MiB/1GiB, web~72MiB/768MiB.
  Это snapshot, не peak memory. Архивы/БД находятся на VPS; на ноутбук
  поступили только малые proof files и screenshot.

Существующий refresh cron11/41 продолжает ту же очередь с32windows/600s,
общим lease, проверкой DB100GiB/free40GiB перед каждым новым окном.
Полный первый проход900окон не завершён; новый код не называет его готовым.

### Следующий slice S173

1. Измерить полный первый проход и повторное обслуживание: фактический throughput,
   возраст карточек, gaps/retries и contention общего lease. Проверить SQL EXPLAIN
   на выросших journals до любых обещаний скорости/свежести.
2. Реализовать bounded автоматическое обновление каталога с сохранением исходника,
   проверкой parser и атомарной заменой snapshot; текущую frozen wave не менять.
3. Определить и проверить retention для raw archives/metadata на VPS с сохранением
   immutable provenance и схемной истории; resource gate сейчас останавливает
   рост, а не удаляет историю.
4. Расширять223families и региональное обслуживание44-ФЗ отдельными доказанными
   slices. Реальный stable lot cancellation association остаётся UNKNOWN.

### S173 M1 — автоматическая проверка каталога, начато03.10

Owner Root: новый storage/eis_223_catalog_checks.py, storage/eis_223_regions.py,
models.py, migration20261003_05, runner refresh.py; PG tests/new scheduler tests,
docs15/28/55 и rollout. Sol: только новый sources/eis_223_catalog_fetch.py и его
unit tests. Astra: read-only architecture review. Research: только docs56 и
ignored readonly measurement helpers; source calls запрещены.

Acceptance: public selector GET без token,512KiB/45s/точный официальный URL,
проверки24h success/1h failure. Immutable tenant/RLS attempt journal связывает
accepted SHA с retained body; повторный sameSHA recheck не мутирует каталог.
Malformed/HTTP/failure/removal кодов не уменьшают охват, ошибка остаётся видимой.
Latest accepted observation выбирает каталог следующих waves; active wave
не меняется. API различает initial observed, exact-wave successful recheck и
latest accepted catalog. Проверить PG/replay/tenant/downgrade/sourcebounds и
один live public GET на VPS, затем deploy/readonly API. Current throughput/EXPLAIN
фиксируются отдельно без обещания полного охвата или6h свежести.

S173 M2 scope после measurements: Root дополнительно owns scheduler fairness,
server cron223 entry и docs56 link/status (research-owned docs56 не переписывать).
Measurements:32windows266–281s, прежние2slots/hour ограничивали64windows/h;
900окон/6h требуют150windows/h. После gates заменить единственнуюcronentry на
каждые10минут: ceiling192windows/h, не SLA.32/600s/2GiB/sharedlease/2s transport
spacing и perwindow disk caps неизменны; contention/skip явны.
Резерв early1fresh+1retry при limit>=3, limit2 сохраняет retry+unseen.
Убрать искусственное ожидание24h после созданияwave: после firstsweep и смены
MSKdate продвигаться <=2days; end_day>=today по-прежнему блокирует новыйcurrent
wave. Acceptance: partialbatch не теряет ранние lanes, frozenwaves/gaps intact,
PGmidnight/catchup/futuretimes tests, ровнооднаcronentry, rollout/liveboundedrun.

Root owns UI delta: web/src/lib/procurement-api.ts и tender-discovery/regional-coverage.tsx;
показать дату повторной проверки точного списка и ошибку последней попытки,
не подменяя её свежестью карточек. ESLint/build и browserproof входят в acceptance.

Final architecture/ADR ownership: Astra owns docs55 и новыйADR0056, Root уступает
docs55 до завершения review; Root owns docs15/28/README/ADRREADME.
Root также owns новый scripts/server-eis-223-refresh-cron.py и его unit tests:
точная замена только223croncommand, сохранение прочих jobs/comments, idempotence.

### S173 M1–M2 завершены и развёрнуты03.10.2026

HEAD `20261003_05`; api/worker/web build+migrate+health PASS, code/schema/cron
backups сохранены перед rollout.33isolatedPG PASS (journal/RLS/immutable/FK/null
constraints/replay/membership/catchup/midnight/earlylanes/downgrade),69focused
PASS, typed source/storage mypy/Ruff, webESLint/productionbuild PASS.
Изолированная testDB удалена после gates. Finalreview Astra READY/PASS.

- Реальный publicGET без token:03.10 19:28:12UTC,200/22514bytes/90codes;
  streamedCDP transport с normalTLS,45s total и512KiB проверен.
  SHA `b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`.
  Proof `/var/lib/eis-browser/research/regions/s173-public-probe-20261003T192813Z.json`.
- Admission `/var/lib/eis-browser/research/regions/s173-admission-20261003T193743Z.json`:
  exact retained bytes,0новых sourcecalls, sameSHA/1newcheck+1audit;
  catalog1/wave1/900targets не изменились. Replay не создаёт записей.
  Last successful recheck отдельно отinitial20:10MSK, новая дата22:28MSK.
- Ровноодна223cronentry `1,11,21,31,41,51 * * * *`; прочиеjobs сохранены.
  Runtime32/600s/2GiB/2s spacing/sharedlease/diskcaps не повышены.
  Раннийfresh-slot подтверждён фактически: повтор окна50/02.10/lotCancellation
  перед31unseen. Newwave календарный переход проверенPG до24h сcreation.
- Первый новый32-window run завершён за217.6817s,41SOAP POST/9archiveGET,
  9SYNCED/23NO_DATA/0errors,69newversions,overrun0. Catalog NOT_DUE/source0,
  offlinequality2notices/4checks/0failures/source0.
  Proof `/home/syurai/vibe-seller-state/s173-first-refresh.json`.
  На19:41:24UTC171/900terminal; следующий автоматическийcron уже продолжил
  очередь к19:42:02UTC176/900 (57→58SYNCED),724unattempted,0failed.
- FinalAPI proof `/var/lib/eis-browser/research/regions/s173-final-api-20261003T194202Z.json`,
  SHA `3c411d8c3fa4a94afeebe2954888ab86df987dbdbc1b2a538482837281b24886`:
  GET200/no-store30.02ms; anonymous401. Index537current; cachedpaper60.73ms/
  10matches,serverequipment140.33ms/31matches; sourcecalls0,DB2909428759bytes.
  Это metadata search текущего индекса, не выгода без КП и не full-EIS SLA.
- Browser refresh показал190/900terminal (60SYNCED/130NO_DATA/0errors), все90
  codes начаты; recheckdates иUNKNOWNfreshness корректны. Screenshot
  `data/research/eis-documents-2026-10-02/s173-catalog-refresh-ui.png`.
  Worker snapshot305.3MiB/2GiB,API110.1MiB,web65.5MiB,DB642.9MiB;
  не peak. Bulkданные остаютсяVPS-only; локально только code/proof/screenshot.

Следующий S174: полный900sweep и gap reconciliation, измерить actual10mincadence/
contention с44loader, freshness по точному scope безwhole-EIS claim. Разобрать
source/archivecap ошибки при их появлении до изменения caps. Затем bounded raw
retention и расширение44/223families. Полный sweep и устойчивый6h revisit ещё
не доказаны; ни числоначатых90, ни NO_DATA не заменяют доказательства охвата.

### S174 — конкуренция загрузчиков за общий lease, начато03.10

Наблюдение: после первого автоматического32-window прохода появились два
SERVER_IMPORT_BUSY.223 ждёт45s, а corpus44 может держать общий lease до60окон;
223 не просит backfill уступить и не уступает foreground44 между окнами.
Выбран bounded slice по этому узкому месту, до увеличения source caps/fanout.

Root owns scripts/server-eis-223-refresh.sh/.py, scripts/server-eis-documents.sh,
tests/test_eis_223_regional_runner.py, docs15/28/README. Sol owns новые shell tests,
sources/eis_corpus.py, eis_corpus_cli.py, scripts/server-eis-corpus.sh,
tests/test_eis_corpus.py. Astra — review/ADR; Research — readonly measurements,
ignored helpers и docs57. Зависимости: существующие immutable journals, общий
import lease, marker staleness; без миграции/переписывания очереди.

Acceptance: одна223dispatcher на host, marker с отдельным владельцем и cleanup,
bounded ожидание общего lease; corpus уступает запросу223 только между полными
atomic windows.223 уступает foreground44 между окнами с сохранением уже
полученного результата; остановка/ожидание измеримы и не означают failed source.
Не увеличивать source concurrency,32/600s/180s timeout,CPU/RAM/DB/disk caps.
Проверки marker expiry, partialbatch journal, конкурентных shell запусков и
cleanup; scoped tests/typing/bash-n, VPS backup/rollout/live proof. Измерить
текущий sweep/throughput/storage отдельно; full sweep/6h SLA остаются UNKNOWN.

### S174 завершён и развёрнут03.10.2026 — общий lease

HEAD остаётся20261003_05, schema/cron/source caps не менялись. Code/cron backups
перед rollout: state/backups/s174-code-before-20261003T202822Z.tar.gz и
s174-cron-before-20261003T202822Z.txt. API/worker rebuilt, API recreated/health200.
76Linux focused PASS за4.75s, включая8настоящих process/flock/signal cases;
Ruff, mypy corpus/CLI2modules, bash-n3scripts PASS. Нет новых storage mutations
или миграции; source receipts принимаются прежними atomic ingest functions.

1.223dispatcher nonblocking lane lock; read-only5s SQL probe перед marker,
  meaningful-work READY при catalog/no-wave/calendar/duewindows. Реальныйprobe
  READY/due2/source0; bootstrap и допустимый scheduler limit2 проверены review.
2.Собственный223demand marker заставляет corpus уступить между окнами;
 223не берёт44prioritylock. Import wait300s вместо45s, дубликаты не создают
  дополнительныеwaiters/markers. Signal whilewaiting завершает/reaps flock,
  trap установлен доtouch; TTL600 на crash.44documents wait300s.
3.После acquisition223 получаетодноatomicwindow и при44priority уступает до
  следующего sourcecall. Optional offlinequality проверяет marker снова;
  yieldedbatch сохраняет outcomes/pending, не пишет ложныйFAILED. UTC dispatch/
  acquisition/workerfinish и wait/workseconds видны в223report.

Live evidence на VPS:

- `/home/syurai/vibe-seller-state/s174-handoff-canary.json`:39/02.10/ZKESMBO,
  1SYNCED/4newversions,2POST/1GET,18.088s; затемPRIORITY_REFRESH_REQUESTED и
  DEFERRED_FOR_PRIORITY. Начатый полный archive set сохранён, второйне начат.
- `/home/syurai/vibe-seller-state/s174-first-dispatch.json`: самостоятельно
  объявленный223demand, corpuslogREGIONAL_REFRESH_REQUESTED после1atomicwindow;
  importwait18s, leaseworker94s, runner90.614s.12windows/13newversions,
  16POST/4GET/0failed223; уступка реальному44priority cron в20:32:05UTC.
  SHA `51a92cd4fce6ae8c33a255b588e3a6a06205e009423f9dfa99ad85c3d3ab0556`.
  Cron20:31:01UTC получилREGIONAL_DISPATCH_BUSY и не снялmarker владельца.
- Posthandoff readonly snapshot20:32:54UTC:44NO_DATA journal продвинулся до
 20:32:51.829Z; это подтверждает44progress послеrelease, не whole44freshness.
  Proof state/s174-after-handoff.json SHA
  `31d6cf9685537083c47df4cb5fc034fb7346519823a652732bc2692e6b172644`.
  В44history появился1новыйFAILED20:30:29 доhandoff; отдельная gap review ниже,
  нольошибок223 не означает нольошибок всегоEIS.
- API `/var/lib/eis-browser/research/regions/s174-final-api-20261003T203231Z.json`,
  SHA `cf32b8d6f3972ce74dee7b6349bf7eec66c18c9c3f72edb440f5c412175b2a12`:
  278/900terminal (93SYNCED/185NO_DATA),622unattempted,all90started,1complete.
  Coverage/freshnessUNKNOWN,firstsweepfalse. Metadata index758current;
  paper118.97ms/33matches,serverequipment130.40ms/44matches;GETno-store24.26ms,
  anonymous401/health200/source0.223marker снят;44prioritymarker принадлежал
  реальноработающемуcron, не удалялся root. DB2971671575bytes.
- Host15scopedfiles/API2runtimefiles SHA match. Browser sourcevolume135MiB,
  raw44archives основнойобъёмPG(~2.08GB),free259GiB; worker259.3MiB/2GiB
  snapshot,API124.3MiB,DB644.5MiB. Bulkdownloads остаютсяVPS-only.

Final cleanup snapshot20:34:18UTC: обаmarkersfalse,44priorityrun завершил
10NO_DATA/0failed послеhandoff; APIhealth200/no-store/anonymous401. Повторное
чтение индекса758:paper61.9ms/server175.81ms. Proof
`/var/lib/eis-browser/research/regions/s174-final-api-20261003T203418Z.json`,
SHA `98d7e892c4f3e3f1ddf13248abe587d31c7392da2d5cadf97bc24a4f0abdaa20`.

Reviewfixes доdeployment: mockedprobe скрывал limit1 при actualscheduler2..32;
исправленоlimit2+livePGprobe. No-waveacceptedcatalog separatelyread; quality
last-window recheck добавлен. Первые5shellfailures былиошибкойJSONstub в tests;
исправленыдо повторного76LinuxPASS, runtimeне разворачивалсяснепровереннымstub.
ADR0057 ACCEPTED/DEPLOYED; измерения доизменений — docs57.

Gap review44: новыйFAILED20:30:29UTC относится к прежнемуокну
`getDocsIP/PRIZ/77/2026-09-29+03:00`, reasonDUPLICATE_NOTICE_VERSION,
responseSHANULL. Все8retainedattempts этогоокнаFAILEDс темжекодом; ingestedwindow0,
targetсохранён. Это повтор source-shape blocker, не новаяошибкаlease/transport.
Следующийeligible после24hcooldown04.10 20:30:29.432893UTC, не обещаниеcron.
Proof `/home/syurai/vibe-seller-state/s174-44-failure-review.json`, SHA
`cffafe14c74f7ad55d96ce29c48a04ec4b44e4f114211d16695840c53d842dc0`.
БезretainedrejectedZIP фактическаяequality/conflict XMLUNKNOWN; нельзяслепо
сниматьguardDUPLICATE_NOTICE_VERSION. Нуженboundedretentionотклонённогоsource
и классификация exactbytesduplicate vs divergentversion сallmemberprovenance.

Следующий S175: сначалаretainedrejectedZIP/duplicateclassification для persistent
gap44 безослабленияконфликтов; затем ограниченный canary порядка семейства/региона, чтобы общие
извещения и отмены не ждали180AES/180ZKокон; сохранитьfrozen900targets иfresh/
retrylanes. Проверитьsource/archiveerrors поretainedevidence. Затемизмерять
steadycadence иage поscope, безопасныйretention raw storage и44regionalparity.
900firstsweep/6hSLA/полныйЕИС не завершены; обычныйcron продолжает очередь.

### S175 — восстановление duplicate window44, начато04.10

Root owns ignored bounded VPS capture/replay helpers, storage/eis_notice_index.py,
tests/integration/test_eis_notice_index_pg.py, docs15/28/README и rollout.
Sol после фактического образца owns sources/eis_feed_archive.py,
tests/test_eis_feed_archive.py и tests/test_eis_notice_index.py.
Astra owns ADR0058/review; Research owns docs58 и readonly measurement helpers.
Первый milestone — один exactwindow77/29.09 underpriority/import leases,
сохранение rawinboundSOAP/ZIP толькоVPS, tenant path, SHA/awaretime, bytecaps,
безtokens/outgoingrequests. Приошибке gap не становитсяSYNCED.
Второй milestone — классификацияповторов: exactXMLbytes/type можно принять
с сохранениемвсехmemberlocators/rawZIP; divergentXML/type прежнийFAIL/conflict.
Не менятьwindow/source/resourcecaps, events policy, money/participation gates.
Проверить syntheticduplicate/conflict/bounds, isolatedPGrollback/replay/tenant/
allmemberprovenance, retainedrealofflineparser, затемbackup/deploy иexactingest.
Изменениеfullcoverage не утверждать. Snapshot05:34UTC: новая223wave900terminal,
index2526,oldgaps1; прошлоеутверждение278/900 относилоськS17403.10.

S175 scope изменёнпослеобразца:5ZIP/499members/498versions;1DIVERGENTpair,
0byteidentical,2leafdifferences(publication/starttimes~87s). Неослаблятьduplicate
guards и не выбиратьlatesttimestamp безофициальногоконтрактаidentity.
Sol теперь owns только новыйsources/eis_rejected_evidence.py иunit tests;
Root owns новыйstorage/eis_rejected_evidence.py, feed_sync.py иtests,
corpus/freshness failureprovenance, composeoptin, isolatedPGaudit tests/docs.
Новыйverticalslice — typed boundedtenant quarantine: optinVPS root,5GiBstore/
64MiBfullwindow/per50MiB/expanded128MiB, immutableSHAblobs/manifestlast,
reflectioncheckraw+expanded передwrites, replayбезповторныхblobs/audit.
Отдельныйtenant audit подтверждаетretention; quota/IO/auditfailure оставляет
исходныйconflict иUNKNOWN, не создаётSYNCED и не изменяетhistoricalFAILED.
Operatorcapture+classification proofs вdocs58; нетbulkпереносаналaptop.

S175 implementation gates (до deployment): Linux 75 тестов, PostgreSQL 20 тестов
на отдельной БД `procurement_eis_test_20261004_s175`; ни один тест не работает
с production database. Проверены откат полного окна, неизменяемость audit,
межтенантная изоляция, безопасные ошибки, quota/path/reflection ограничения,
видимость retention/audit failure в corpus/freshness. Повторная проверка
полного набора fsync путей выполняется перед rollout; production пока прежний.

### S175 завершён и развёрнут 04.10.2026, 06:07 UTC

Результат: сохранение полного отклонённого набора ZIP включено на VPS,
проверенный SHA source response передаётся в новые FAILED attempts,
retention/audit status виден в corpus report и freshness observation.
Причины отказа и all-or-nothing импорт сохранены. В спорном окне реально
различаются publication/start times; это окно по-прежнему не принято.

Финальные gates: 77 Linux unit tests и 20 PostgreSQL integration tests PASS
на отдельной тестовой БД; Ruff/mypy PASS; Astra review PASS. Проверены
fsync failures и retry для parent, blob и manifest paths, immutable modes,
corruption/reflection/bounds, tenant RLS и отсутствие checkpoint при отказе.
Промежуточные проверки 74/75 tests предшествовали найденным и исправленным
recovery edges; production развернут только после финальных 77 PASS.

Перед rollout сохранён backup src/tests/docs/compose; API и worker images
пересобраны. Host18/API6 scoped file hashes совпали; schema HEAD остался
`20261003_05`. Тестовая БД после gates удалена; production schema не менялась.

Offline replay реальной capture под priority/import lease: 5 ZIP,
7 697 126 compressed bytes; RETAINED и audit RECORDED. Один новый audit event,
ноль изменений index/feed windows/attempts, ноль повторных file writes,
ноль source requests. Исторические 8 FAILED не переписаны. Manifest SHA:
`62532f02f3021f6078de78bc7cd86cc7a323fac4af9426c6f77fffba872c8a2e`.
VPS `/var/lib/eis-browser/research/rejected/s175-retained-proof.json`, SHA:
`3a7de5da9c6a495e358a1effd47e7c13abf0703d493415a00fae3d27e7998c13`.

После deployment: health200, anonymous401, coverage no-store; оба demand
markers сняты. Индекс223 содержит 2526 current records; cached query бумага
249.8ms/58matches, серверное оборудование489.89ms/157matches. Это скорость
по накопленному индексу, не полного онлайн-поиска и не расчёта прибыли.
Coverage/freshness всей ЕИС остаются UNKNOWN. API proof:
`/var/lib/eis-browser/research/regions/s175-final-api-20261004T060805Z.json`,
SHA `8d3f3c3f38cd705c43ccc69224057e6cfdc8a8e2c8cd2e99954894eb1b33e888`.

Следующий S176: отдельно разобрать единственный старый223 gap
`getDocsIP/RI223/77/2026-10-02+03:00/purchaseNotice` с ARCHIVE_SET_MISMATCH:
сохранить initial/prepared incoming evidence и состав archive set, определить
фактическое нарушение binding без частичного admission. Для44 нужен официальный
контракт вариантов одной версии; более поздняя публикация не выбирается
автоматически. После source gaps — cadence/family fairness, raw retention и
региональный44 parity. Полный охват и6hSLA этим срезом не подтверждены.

### S176 — состав архивов 223-ФЗ, завершён 04.10.2026

Перед работой назначены владельцы и границы:
- Root: diagnostic helpers, notice CHECK в models.py, migration20261004_01,
  refresh report, isolated PG tests, docs15/28/59, README и rollout.
- Sol: sources/eis_223_window_limits.py, sources/eis_223_sync.py,
  storage/eis_223_index.py, unit tests index/sync.
- Astra: независимый review и ADR0059.

Окно `getDocsIP/RI223/77/2026-10-02+03:00/purchaseNotice` отклонялось из-за
pilot cap2. Actual initial/prepared responses содержат одинаковые четыре
уникальных UID, request/URL binding проходит. Полный набор: 4 ZIP,
24 527 171 compressed bytes, 82 432 099 expanded bytes, 365 XML members,
без повторов номера и версии. Первый проход с expansion cap64MiB отказался;
повтор использовал два сохранённых ZIP и два GET того же запроса. На стадии
диагностики production не менялся. Source hashes и inventory — docs59.

Контракт notice window: максимум 4 ZIP, 32 MiB compressed, 128 MiB expanded,
400 members суммарно. Per-ZIP16MiB/32MiB/200 и per-XML4MiB прежние. Все
headers и общие бюджеты проверяются до XML parse; cumulative compressed —
после каждого GET до следующего запроса. Частичный source set не принимается.
Модель, binder и notice-only DB CHECK согласованы; event/lot-event max2 прежний.
Настоящий set mismatch и count limit различаются; resource codes видны в report.

Финальные gates: **139 Linux unit tests, 21 isolated PG tests, Ruff/mypy и
architecture review PASS**. Проверены четыре архива, отказ пятого до GET,
rollback при конфликте последнего ZIP, replay, tenant RLS и DB cap. Downgrade
без wider history проходит; с историей >2 любой компании отказывается до
изменения CHECK. Production downgrade не запускался.

Полный реальный cached pipeline с resident Chromium: 2 GiB cgroup,
peak343482368bytes (~328MiB), Python maxRSS193003520bytes, всего7.220s.
Fetch1.863s, ingest3.021s, replay1.662s; source requests0. Это время по
сохранённым данным, не сетевой SLA. Memory proof:
`/var/lib/eis-browser/research/223/s176-memory-proof.json`, SHA:
`5c646de291d44c5c3ccb5aec734a2dd2a540c42537ff7f19eebcfaaea7445096`.

Deployment 06:59 UTC: code backup и проверенный schema-only dump сохранены
(это не data backup). Migration20261004_01 применена с20261003_05;
host15/API5 hashes совпали. API/worker images обновлены. Тестовая БД удалена.

Retained admission под priority/import lease: все 4 ZIP импортированы,
365 новых XML versions, window0→1 и один SYNCED attempt. Precompare не нашёл
existing version identities или конфликтов. Replay не создал новых записей;
все 8 прежних FAILED сохранены. Старый gap223 закрыт: current regional scope
COMPLETE, old_gaps0. Coverage/freshness всей ЕИС остаются UNKNOWN.
Manifest SHA `30eaf9aa480eba3b4513ec5ce7bb31b6309dc9d793665f4dd8257915b3f3eec6`.
Admission proof `/var/lib/eis-browser/research/223/s176-admit-proof.json`, SHA:
`93440ab3f719c7ab6ae87654885721c34a6dc9fca6d555badd4921f19feba2c2`.

Final API: health200/anonymous401, coverage no-store, markers сняты.
Индекс223: 2876 current purchase numbers, 2979 XML versions. +365 versions
не означает +365 уникальных закупок. Cached search: бумага251.35ms/59matches,
серверное оборудование607.15ms/184matches. API proof:
`/var/lib/eis-browser/research/regions/s176-final-api-20261004T065948Z.json`, SHA:
`7d05cfc26681ec8c763b4cdb50ab5e67bca9651463c5a39c9d9ff3a493762a2c`.

Следующий S177: официальный revision/variant contract для divergence44 и
безопасный intake спорного полного окна; guards не снимать по timestamp.
Затем — измерение устойчивой freshness/cadence, coverage активных закупок
за более ранние даты, bounded backfill/retention и fairness семейств.
COMPLETE текущего плана не подтверждает полноту ЕИС, документации или
готовность сравнения прибыли поставщика.

### S177 — идентичность и диагностика конфликтов 44-ФЗ, завершён 04.10.2026

Контракт сверён с PRD: source ambiguity остаётся UNKNOWN; поиск и экономика
не могут получить выдуманную актуальную версию. Retained pair имеет одинаковые
номер, versionNumber=1 и id=44105096, но разные publishDTInEIS/startDT.
Официального правила выбора победителя по времени пока не найдено. Поэтому
этот slice не переключает intake на variants и не закрывает gap частичным набором.

Владельцы до реализации:
- Sol: новый sources/eis_notice_conflicts.py и tests/test_eis_notice_conflicts.py;
  bounded offline classifier полного ZIP set, строгие XML identity/provenance.
- Root: feed_sync.py, storage/eis_rejected_evidence.py, freshness.py/status.py,
  integration/unit tests этих путей, docs15/28/61/README, helpers и rollout.
- Research: только docs/eis/ingestion/60-eis-44-version-contract-research.md, official contracts.
- Astra: read-only review и ADR0060 после фиксации контракта.

Acceptance: typed deterministic diagnosis distinguishes identical XML from
divergent bytes and same/different/unknown document identities; archive/member
SHA and source coordinates retained for every occurrence. Full header/resource
preflight precedes XML parse; exact namespaces/direct unique children required;
token reflection and unsafe member paths rejected. Diagnostic failure preserves
the original source error. Diagnosis has tenant-scoped immutable audit and safe
summary in corpus/freshness; replay idempotent, no index/checkpoint writes.
No latest/first choice, subset admission, new source requests or bulk laptop data.
Gates: synthetic negatives, isolated PG tenant/replay/rollback, retained real
offline proof under existing budgets, architecture review, scoped deployment.
Dependencies: deployed S175 quarantine, S176 HEAD20261004_01, official schema
identity research; further canonical-variant intake requires a separate ADR/slice.

S177 pre-rollout gates PASS: 158 Linux tests, 22 isolated PostgreSQL tests,
Ruff/mypy пяти runtime files и architecture review. Test DB только
`procurement_eis_test_20261004_s177`. Exact retained offline run+replay с
resident Chromium: 5 ZIP/499 XML/all-member provenance, один divergent same-ID
pair; peak379813888bytes (~362MiB) при2GiB,13.154s. Source calls0,
index/checkpoint/attempt delta0, replay file writes0. Proofs и лимиты — docs61.
Production rollout и закрытие44 gap этим сообщением ещё не утверждаются.

S177 deployed07:49UTC: code backup, host18/API5 hashes PASS, API/worker rebuilt,
HEAD20261004_01 unchanged. Real retained full hook+replay13.387s, peak382709760
bytes (~365MiB) при2GiB с Chromium. Один новый immutable tenant diagnosis audit;
retention audit delta0, replay file writes0, source calls0, index/checkpoint/attempt
delta0. Report SHA одинаков с isolated gate, all499occurrences сохранены.
Полное окно44 по-прежнему FAILED: same id/version с разными business dates
не превращается в канонический XML. Proofs и API evidence — docs61.

Final API health200/anonymous401/no-store, demand markers сняты. Индекс223:
2880current purchase numbers; бумага241.87ms/59matches, серверное оборудование
585.35ms/184matches. Это cached index timing, не полный поискЕИС/экономика.
Coverage/freshness всейЕИС UNKNOWN. Test DB удалена после release gates.

Следующий S178 скорректирован по официальному research: вместо выбора latest
XML — отдельный immutable ledger всех notice variants и всех member origins.
Первый milestone: schema/typed storage/atomic complete transport receipt,
ambiguity UNKNOWN и isolated PG gates без переключения production intake.
Затем shared ambiguity hold во всех current-read/search/comparison/document
queue/receipt/estimate путях, включая уже созданные jobs; только после этого
отдельный ADR и переключение intake полного набора. Нельзя объявлять subset
полным или выбирать один raw variant. Такой контракт позволит сохранять
весь источник, не выдавая неоднозначной карточке выдуманный допуск.
После source gaps — измерения устойчивой cadence/freshness, активные закупки
за более ранние даты, bounded backfill/retention, parity регионов/семейств44.

### S178 — реестр вариантов извещения 44-ФЗ, milestone 1, завершён 04.10.2026

Контракт сверён с PRD/S177 и Astra: ledger хранит evidence полного набора,
а не каноническую карточку. Одной пары number/version может касаться несколько
XML SHA; выбор first/latest запрещён. Admission всегда NOT_ENABLED, coverage
UNKNOWN. Существующие source guards, search и document jobs не переключаются.

Владельцы до изменения кода:
- Root: новые три таблицы в storage/models.py, migration20261004_02,
  integration/test_eis_notice_variants_pg.py, docs15/28/62/README,
  scoped staging/isolated gates/backup/rollout и real retained proof.
- Sol: новый storage/eis_notice_variants.py и tests/test_eis_notice_variants.py;
  typed atomic writer, bounded readers и immutable replay.
- Astra: ADR0061 и независимый review schema/storage/resource/security.

Acceptance: receipt связан с exact audited S175 manifest и S177 diagnosis;
все occurrences присутствуют, каждый origin связан с tenant/receipt/variant.
Variant key включает number/version/type/XML SHA; facts не включают locator
конкретного receipt. Повторяет один immutable audit; late conflict откатывает
весь набор. RLS FORCE, tenant composite FKs, SHA/count/bounds constraints,
UPDATE/DELETE запрещены. Missing semantic key отклоняет full ledger, не subset.
Reader ограничен полным набором: overflow UNKNOWN без частичного результата.
Downgrade проверяет history всех tenants до DDL и отказывается при наличии.
Gates: focused Linux/isolated PG, tenant/replay/rollback/cross-window variants,
migration roundtrip и global downgrade guard; exact real retained proof под
priority/import lease без source fetch/canonical index/checkpoint/attempt writes.
Dependencies: S175/S177 audited quarantine, HEAD20261004_01, frozen ledger ADR.

S178 gates PASS:54Linux/36isolatedPG, Ruff/mypy, architecture review. Frozen
migration20261004_02, NULL-safe evidence checks и bounded full readers. Проверены
atomic late rollback, tenant isolation, immutable owner trigger, cross-window
origins, UTC/+03hash roundtrip, exact replay, empty migration roundtrip и global
downgrade refusal при history другого tenant. Isolated retained proof499variants/
499origins:8.160s/~359MiB peak при2GiB с Chromium. Test DB удалена после gates.

Deployed08:54UTC:code backup/validatedschema-onlydump, host11/runtime3hashPASS,
API/worker rebuilt, HEAD20261004_02. Реальный fullset5ZIP/499XML/498semantic keys
сохранён целиком:499variants,499origins,1receipt,1newledgeraudit. Спорная sameID
pair прочитана как2variants/ambiguitytrue/UNKNOWN/NOT_ENABLED. Replay0writes;
sourcecalls0, index/checkpoint/attemptdelta0, исторические8FAILED preserved.
Production proof8.309s/~364MiB peak при2GiB с Chromium. Paths/hashes — docs62.

API health200/anon401/no-store/markersfalse. Индекс223:2882current numbers,
бумага239.45ms/59matches, серверное оборудование608.83ms/184matches. Это cached
index timing; coverage/freshness всейЕИС UNKNOWN. Автоматический intake hook
и продуктовые consumers этим milestone не переключены.

Следующий S179: shared ambiguity hold во всех current-read/search/comparison/
documentqueue/receipt/estimate путях, в том числе revalidation уже созданных
jobs/receipts. Затем отдельный ADR и full-window variant intake/canonical
projection без выбора победителя по времени. После source gaps — cadence/
freshness, активные более ранние даты, bounded backfill и parity семейств/регионов.

### S179 — общий hold evidence-only вариантов44, завершён 04.10.2026

Контракт до реализации: UNKNOWN source evidence не допускается к сравнению/
расчёту как действующая каноническая карточка. Любой ledger variant/origin того
же tenant/number с version>=выбранной версии блокирует product consumer, включая
одиночный XML. Hold отдельный от supplier mandatory FAIL. Older-only ledger не
подменяет stale/version gates. Отсутствие ledger не подтверждает полноту ЕИС.
Intake не переключается; schema20261004_02 и immutable история сохраняются.

Владельцы/owned files:
- Sol: storage/eis_notice_hold.py, storage/eis_document_store.py,
  storage/eis_notice_variants.py, tests/test_eis_notice_hold.py,
  tests/test_eis_notice_variants.py, tests/test_eis_document_store.py.
  Shared SQL/typed guard, exact document/cache/replay guards и общий tenant lock
  ledger writer/receipt для предотвращения гонки финального сохранения.
- Root: storage/eis_index_query.py, storage/eis_evidence_bridge.py,
  storage/eis_position_projection.py, storage/eis_comparison.py,
  tests/integration/test_eis_notice_hold_pg.py,
  api/app.py, tests/test_eis_document_jobs_api.py, tests/test_eis_api.py;
  exact hold HTTP errors/no-store и live-number ValueError mapping;
  затронутые tests этих трёх путей, docs15/28/63/README, gates/proofs/rollout.
- Research: sources/eis_document_worker.py, sources/eis_number_sync.py и их
  tests; проверка worker cached/stale/error handling, current-number return.
- Astra: read-only review всех consumers/races и ADR0062.

Acceptance: SQL hold перед search ranking/count eligibility; exact consumer
guard в той же tenant snapshot до cached shortcut/read/write; worker получает
typed skip с idempotent audit до HTTP, late receipt/analysis replay также
проверяется; старые jobs/receipts не обходят hold. Origin-only orphan failclosed;
UNKNOWN hold не становится FAIL/PARTICIPATE. Shared lock предотвращает ledger/
receipt race. Negative synthetic + isolated PG gates для всех consumers,
cross-tenant, same/newer/older version, singleton, cached receipts/projections,
late hold и replay, query bounded/explain. Real retained read-only proof и API
smoke; scope/resource caps/cron/sourcefetch прежние. Dependencies: S178 deployed.

S179 deployed09:32UTC:172Linux/52PG (224tests), Ruff10runtime/10test, mypy9source/
storage, architecture review PASS. Shared guard исключает same/newer ledger,
singleton и incomplete receipt; sourceUNKNOWN не становится supplier FAIL.
Exact cached consumers и final receipt защищены; общий tenantlock сериализует
ledger/document/projection writes. Worker latehold не пишетFAILED; status-read/
failure-record races проверены. RealHTTPhold422/no-store; все consumerAPIclasses
покрыты. Held count оптимизирован UNIONmetadata→currentjoin. Общий44comparison
в одном snapshot. Host26/runtime10hashPASS, codebackup/API+workerbuild,
HEAD20261004_02 прежний. Retainedproofsource0/все12tabledeltas0; gap не закрыт.
TestDB удалена/markers сняты. Paths/hashes — docs63/ADR0062.

Индекс44:127150current numbers,46heldcurrent; бумага3.444s/2436matches,
сервер9.399s/5138matches. Это saved-index timing, не fullЕИС/документы/прибыльSLA.
MetadataSQL500rows2.884ms. APIhealth200/anon401/no-store;2232882current,
бумага243.89ms/59matches, сервер610.14ms/184matches. Coverage/freshnessUNKNOWN.

Следующий S180: отдельный ADR full-window variant intake/canonical projection
и immutable решение о допустимости конкретной проекции с exact provenance;
divergenceUNKNOWN, singleton не автоматически PASS. Переключение intake после
consumer gates. Далее cadence/freshness/активные более ранние даты/boundedbackfill/
parity; отдельно ускорение comparison текущего большого индекса.

### S180 M1 — retained transport и явная проекция44, выполнен 04.10.2026

Контракт ADR0063 принят до кода. Один operator slice без live intake hook.
Dependencies: deployed S178/S179, exact audited receipt и retained ZIP.
Owned files: root — storage/models.py, frozen migration20261004_03,
storage/eis_notice_hold.py, storage/eis_notice_index.py, storage/eis_index_query.py,
storage/eis_sync_journal.py, sources/eis_corpus.py, sources/eis_freshness_status.py,
tests/integration/test_eis_notice_projection_pg.py и связанные reader tests,
docs15/28/64/README/adrREADME, proofs/gates/deploy.
Sol — storage/eis_notice_projection.py, storage/eis_notice_variants.py,
tests/test_eis_notice_projection_store.py; atomic writer, audited connection read.
Source agent — sources/eis_notice_projection.py и tests/test_eis_notice_projection.py;
offline exact full-source parser. Astra — ADR0063 и read-only contract review.

Acceptance: all5ZIP/all499members retained, decisions всех498pair;
singletons only known sourceid/full parser/global onevariant; divergent/existing
differentSHA HOLD. Canonical/searchkeys/decision/audit atomic под tenant→ledgerlock.
Replay0writes; future variant/orphan/incomplete receipt reholds all consumers.
VARIANT_TRANSPORT исключён из ВСЕХ checkpoint/completion/coverage readers;
old8FAILED неизменны. Frozen migration/RLS/FORCE/immutable/global downgrade,
negative PG consumer/rollback gates; real retained parse/projection with bounded
memory/sourcecalls0. Полнота всейЕИС остаётся UNKNOWN, supplier gates прежние.

S180 pre-rollout gates PASS:176Linux/68PG=244; Ruff11runtime+4tests,
mypy9modules, independent architecture release review PASS. Exact retained
5ZIP/499members/498pairs→497PROJECTED/1HOLD; old8FAILED и checkpointfalse;
replay13table deltas0/source0. MeasuredUTF8sum13MB,16MiB aggregatecap прежний,
percard2MiB обоснован max1.15MB. Два MATERIALIZED CTE раскрывают audit и проверяют
source pair один раз:936/882ms на492current, selector349ms/arrayloops1.
Peak583MB/2GiB+Chromium. Proof/hashes — docs64/ADR0063.

Production deployed10:41UTC, HEAD20261004_03/API+worker rebuilt; backups и
host21/runtime11 hash gates PASS. Production retained proof PASS:497PROJECTED/
1HOLD, все499XML/498decisions сохранены; replay13table deltas0/sourcecalls0.
Old8FAILED/targetpending/checkpointfalse сохранены. API smoke10:46:57UTC PASS:
44current128803, бумага2477/5.811s, серверное оборудование5232/12.216s;
223current2882, бумага59/218ms, сервер184/573ms; health200/anon401/no-store.
Coverage/freshnessUNKNOWN; markersfalse, isolated test DB удалена.
Operator M1 завершён. Следующий M2 — bounded live hook и typed partial admission
в refresh/coverage: unresolved pair counts, cadence/retry без закрытия gap по
subset. Далее активные ранние даты/backfill/parity и ускорение большого индекса.

### S180 M2 — автоматическая проекция конфликтных окон44, выполнен 04.10.2026

Контракт перед кодом: существующий sync после полностью retained и audited
diagnosis сохраняет S178 ledger и вызывает проверенный M1 writer на тех же
байтах. Никаких дополнительных запросов ЕИС. Legacy outcome остаётся FAILED:
новый typed partial intake report содержит receipt/batch/audit ids и counts
projected/replayed/held; gap не закрывается даже при held=0. Частичный результат
не становится SYNCED, полной coverage/freshness или supplier PASS.
Ошибки retention/diagnosis/ledger/projection явно отражаются без секретов;
ledger после прерванной projection сохраняет fail-closed hold. Transport/DB
failure прекращает проход, source conflict сохраняет существующий24h retry.
Budgets/cron/source spacing прежние; M2 не расширяет регионы/даты/типы.

Owner root: sources/eis_corpus.py, sources/eis_freshness.py,
sources/eis_freshness_status.py, sources/eis_rejected_evidence.py; связанные tests/test_eis_corpus.py,
storage/eis_sync_journal.py (typed partial audit basis);
storage/eis_notice_projection.py (read-only exact transport reuse),
tests/integration/test_eis_notice_projection_pg.py (allowlisted isolated DB name);
test_eis_freshness.py, test_eis_freshness_status.py; новый integration
test_eis_variant_intake_pg.py; docs15/28/65/README/adrREADME, VPS proofs/deploy.
Sol: sources/eis_variant_intake.py, sources/eis_feed_sync.py,
tests/test_eis_variant_intake.py, tests/test_eis_feed_sync.py. Astra: ADR0064,
независимый contract/release review без runtime edits. Зависимость: deployedM1.
Acceptance: automatic real sync rejections→audited full ledger→all-pair decisions;
positive singleton и divergent HOLD; interruptions/replay/late-conflict gates;
typed persisted refresh evidence + corpus partial counts отдельно от synced;
ordinary completion/checkpoint и old FAILED неизменны. Focused Linux+PG gates,
bounded retained-through-rejection-hook proof source0; controlled live source probe на VPS
и final API smoke/hash check. Полный охват ЕИС остаётся UNKNOWN.

Retry clarification до integration: `TRANSPORT_WINDOW_NOT_CANONICAL` также
переходит в retained/diagnosed intake. Иначе окно без внутренних дубликатов,
первоначально отклонённое из-за existing canonical conflict, после сохранения
transport не сможет повторить projection. Это отдельный legacy FAILED reason,
не ordinary admission; процедура events остаётся вне notice adapter.

M2 pre-rollout gates PASS:286Linux/72PG=358, Ruff8runtime+7tests/mypy8,
независимый release review. Full real retained rejection hook5ZIP/499XML/498pairs
автоматически сохраняет ledger и497PROJECTED/1HOLD; replay13table deltas0,
new_versions0/source0/filewrites0/checkpointfalse. Peak552MB/2GiB сChromium,
дваполных intake вызова101.737s. Proof/SHA — docs65; production gates в работе.

Source agent получил ownership только tests/test_eis_freshness_status.py для
negative observation/capacity gates; пересекающихся edits нет. Production runtime
deployed12:37:53UTC, host21/runtime8 hashesPASS, API+worker rebuilt, HEAD03 прежний.
Production full retained automatic hook proofPASS12:38:55UTC: оба вызова
PARTIAL/replayed, new_versions0/все13table deltas0/source0/filewrites0,
checkpointfalse/HOLD;35.251s/peak511MB. Live source/API gates в работе.

Final livePASS12:40:18UTC: реальный getDocsIP date77/2026-09-29, full5ZIP/499XML/
498pairs→0PROJECTED/497REPLAYED/1HOLD, новый ledger/batch/audit/attemptFAILED.
Прежние8FAILED сохранены; checkpointfalse/new_versions0/37.43s/peak526MB2GiB.
Final APIPASS12:41:03UTC:44current130458, бумага2517/7.637s, сервер5269/14.218s;
223current2882, бумага59/310ms, сервер184/540ms; health200/anon401/no-store,
coverage/freshnessUNKNOWN/source0. Priority markerfalse;223marker при API снимке
true (concurrent cron отдельно проверяется). TestDBm2 удалена. Proof/hashesdocs65.
Final operations12:44:23UTC: оба markersfalse, testDB отсутствует; HEAD03 прежний.
223 marker штатно снят завершившимся concurrent cron. Runtime права не расширялись.
M2 завершён: автоматический conflict intake подключён, full corpus не подтверждён.
Следующий этап — измерить partial outcomes/cadence/lag и возраст пропусков,
расширить active earlier dates/bounded backfill с parity. Ускорение поиска
большого индекса требуется отдельно; текущие7.6–14.2s не объявлять fast SLA.

### S181 — сверка пропусков и ограниченная очередь старых сбоев связи, DEPLOYED

Baseline census04.10.2026 15:52МСК (12:52UTC), source0/writes0:143130pending
targets для99 candidate region codes,136630unattempted,6427NO_DATA,72FAILED,
1SERVICE_ERROR; возраст source dates2025-09-28..2026-10-04. Среди FAILED43
ATTACHMENT_REFERENCE_INVALID,9ATTACHMENT_COUNT_LIMIT,5MEMBER_UNSUPPORTED,
2SOURCE_TRANSPORT_FAILED. DB3.64GB/current131201. Census proof/SHA — docs66.
Большой unattempted хвост всегда предшествует старым attempts в historical lane:
старые transient failures могут не дождаться retry. Parser/resource/conflict
ошибки повторным запросом не объявлять исправленными; NO_DATA остаётся UNKNOWN.

Контракт до кода: typed read-only gap-status CLI по всей tenant queue, полные
aggregate counts/oldest/newest dates/reason groups и bounded evidence samples;
только LEGACY_CANONICAL закрывает target, partial transport не закрывает gap.
Source freshness/полныйохват UNKNOWN. Новый historical source-retry lane только
latestFAILED SOURCE_TRANSPORT_FAILED/SOURCE_WSDL_UNAVAILABLE либо latest
PREPARING/SERVICE_ERROR, due≥24h, source dates вне недавних7дней и past dates.
До3slots/60run (~5%); recent failure lane прежний, остальной backlog продвигается.
Smallrun не обещает слот каждому lane; сохраняется хотя бы1historical backlogslot.
Никаких увеличений cron/concurrency/bytes budgets/regions/families/проверокPASS.

Owner root: новый storage/eis_gap_status.py, eis_corpus_cli.py,
tests/test_eis_gap_status.py, tests/integration/test_eis_gap_status_pg.py,
docs15/28/66/README/adrREADME, census/isolatedproof/deploy/live/API gates.
Sol: sources/eis_corpus.py eligible_windows ONLY,
tests/integration/test_eis_corpus_fairness_pg.py и tests/test_eis_corpus.py
если нужны только SQLshape assertions; storage/eis_sync_journal.py — только
новый latest_eis_attempts metadata helper и imports. Astra: ADR0065 и read-only risk review.
Source agent: независимый bounded review причины backlog/parser gaps, без edits.
Dependencies: deployedM2, immutable journal и shared leases/budgets.
Acceptance: exact latest/due/tenant/ordinarycompletion predicate; noData/unknown/
parser/resource/partialconflict не попадают в новый repairlane; дедупликация lanes;
детерминированный порядок/лимит/сохранение backlog прогресса; gap-status source0,
записи0, полные totals и typed provenance, malformed/overflow остаются unknown.
FocusedLinux/PG+realproductionEXPLAIN/census, measured bounds; controlled retry
не более2старых transient source windows через тот же sync/journal, exact source
status/final checkpoint evidence; final API/hash checks. Это один завершённый slice.

Результат04.10.2026:148Linux+30PG=178focused PASS; Ruff8files/mypy4runtime PASS,
независимый architecture/release review. Historical reserve использует фактический
recent_count:limit2 с пустым recent допускает retry1+ordinary1;limit1 ordinary.
Полный census реализован одним SQL/общим MATERIALIZED pending, bounded JSON
samples имеют явный aggregate ordering. Первая staged36.697s→final deployed8.357s;
снимки live разные, точныйbenchmark/SLA не заявлять. Selector8.264s/EXPLAIN8.372s.

Production13:20:27UTC:backup/host14/runtime4 hashesPASS, API+worker rebuilt, HEAD03.
148168planned/5040canonical/143128pending/136602unattempted/6451NO_DATA/2retrydue,
1transportonlygap,99candidatecodes. Actual2oldsource retries(50/2026-09-24 и
90/2026-09-17 cancelFailure)→NO_DATA3.324/2.501s, новыеattempts/audits,
originalFAILED immutable, checkpointfalse/newversions0, peak281MB/2GiB.
Followupsource0: exactnewlatestIDs/retrydue0/NO_DATA6453; gaps не закрыты.
API44current131573 paper7.733s/server14.602s;2232884current295/520ms;
health200/anon401/no-store/UNKNOWN. TestDBs181 удалена; нашmarker снят,
freshnesscron marker приAPIactive; finaloperations13:25:07UTC:оба markersfalse,
testDB отсутствует. Чужойmarker снят штатным владельцем. S181 завершён.
Paths/SHA — docs66. Source/runtime privileges/budgets/cron не расширены.

Следующий bounded milestone: exact recovery9obsoleteATTACHMENT_COUNT_LIMIT
окон с текущим metadata catalogue parser, сначала evidence/read-onlyselection,
затем2–3livewindows с прежними budgets и только genuinecanonical checkpoint.
45ATTACHMENT_REFERENCE_INVALID требуют отдельной классификации references,
не broad retry/ослабления parser. Далееactive fresh backlog/parity и отдельно
searchindex latency; полный ЕИС и быстрый fullcomparison пока не подтверждены.

### S182 — восстановление окон с прежним attachment metadata limit, завершён

Baseline16:35МСК, source0/writes0:9latestFAILED ATTACHMENT_COUNT_LIMIT без
canonical checkpoint;7date windows (25/78) и2hour windows77/EOK за02.10.
Proof `/var/lib/eis-browser/research/rejected/s182-baseline.json`, SHA-256
834656c4e3a883881f7db43b29badf3b40dfab41ffa7327d4f958150854cd298.
Parser4096metadata entries уже deployed, >4096 даёт новый explicit code;
source URL/UID/duplicate/size checks и source/DB budgets прежние (docs43).

Контракт до кода: отдельный read-only typed recovery plan и bounded run CLI,
не новая автоматическая cron-полоса. Exact latestFAILED oldcode only,
due≥24h, valid past completeddate/hour +03 window, tenant scope и отсутствие
LEGACY_CANONICAL; latest NO_DATA/newparser/variant error/cooling/future исключены.
До3windows за запуск, прежний browser transport/sync/journal/leases/budgets,
новые source/DB/transient/failedpartial stage errors останавливают проход.
Перед каждой source operation повторно проверить exact candidate attempt ID:
смена latest/completion останавливает pass с UNKNOWN без stale retry.
Все результаты типизированы с source SHA, immutable original/new attempt IDs,
canonical completion и optional partial report. SKIPPED допускается только при
реальном canonical checkpoint; NO_DATA/FAIL/PARTIAL не дают completion/PASS.
Нельзя объявлять fullcoverage/документыскачанными по metadata ingestion.

Owner Sol: новый sources/eis_attachment_recovery.py, новый
tests/test_eis_attachment_recovery.py, новый integration
tests/integration/test_eis_attachment_recovery_pg.py. Root: eis_corpus_cli.py,
CLI unit tests в новом tests/test_eis_attachment_recovery_cli.py,
новый scripts/server-eis-attachment-recovery.sh (общие source leases, fixedbudgets),
docs15/28/67/README/adrREADME, VPS stage/proofs/gates/deploy/live. Astra:
новый ADR0066 и read-only contract/release review. Owned files не пересекаются.
Dependencies: S181 latest selector/journal, S166 metadata parser, S180M2partial.
Acceptance: read-only exact count/limit/provenance, dates+hours+invalidkey gates,
latest tie/tenant/oldattemptimmutability, recheckbeforeoperation, valid bounded
budgets/global lease, standard source intake atomicity и honest outcomes.
FocusedLinux/PG + productionreadonlyplan/EXPLAIN, backup/hash rollout,
controlled live≤3windows, final index/API/operational checks и documented status.

Результат 04.10.2026: 219 Linux + 32 PostgreSQL = 251 focused tests PASS;
Ruff 5 files/mypy 2 runtime PASS, независимый release review PASS. Wrapper process
tests проверяют interruption/cleanup и сохранность чужого marker. Реальный sync
в isolated DB импортировал 101 metadata entry с сохранением старой ошибки.

Deployment 13:52:11 UTC: backup/host 12/runtime 2 hashes PASS, API+worker rebuilt,
HEAD03. Deployed read-only plan 9 eligible/3 selected, 1.969 s/EXPLAIN 910.364 ms.
Один controlled pass из 3 окон занял 39 s: все SYNCED, 5 ZIP, 398 новых versions,
0 lifecycle events; actual canonical checkpoints/source SHA/journal/audit проверены.
Max metadata среди новых window/SHA rows: 193/240/278. Все 9 исходных FAILED
записей неизменны; remaining eligible 6. Metadata не означает загрузку файлов.

Cached API: 44 current 132982, бумага 8.390 s/серверы 14.733 s;
223 current 2887, бумага 302 ms/серверы 615 ms. Health200/anon401/no-store,
coverage/freshness UNKNOWN. TestDBs182 удалена, operations13:57:37UTC:
оба markers отсутствуют. Proof paths/SHA и запуск — [docs67](../../eis/ingestion/67-eis-attachment-recovery.md).
Cron, budgets, parser guards и права не расширены. S182 завершён.

Следующий bounded slice: remaining 6 obsolete-limit windows, до3 за проход,
с отдельной проверкой фактических receipts. Затем классифицировать invalid
references/unsupported members, проверить active fresh backlog/parity и отдельно
ускорить поиск. Полный охват и быстрый fullcomparison остаются неподтверждёнными.

### S183 — оставшиеся obsolete attachment-count окна, завершён

Контракт до запуска 04.10.2026: status 14:05:38 UTC подтвердил 6 eligible окон.
Owner root; owned files docs15/28/67 и ignored S183 proof/run helpers.
Зависимости: deployed S182, ADR0066, неизменные source leases/4096 metadata cap,
CPU2/memory2GiB, DB100GiB/free40GiB и 600s gate перед следующим окном.
Runtime/cron/schema не меняются; новых migrations/прав доступа не требуется.

Обработать до двух последовательных проходов по 3 окна. Между проходами
обязательны typed receipts, source SHA/canonical/journal/audit и проверка всех
9 исходных attempts на неизменность. Любая failed/service/DB/partial stage error
останавливает продолжение; NO_DATA не считать закрытым gap. Перед вторым проходом
повторить eligibility через deployed selector, не подставлять stale window keys.
Acceptance: все фактические outcomes и остаток очереди подтверждены read-only
проверкой; финальный cached API/operations/hash gate; evidence на VPS, UNKNOWN
coverage/freshness и metadata≠attachment downloads. Один operational slice.

Результат 04.10.2026: baseline 6 eligible; два sequential passes 46 s и 31 s,
каждый selected3/attempted3, все6 SYNCED с фактическими canonical checkpoints.
573 новых versions, 10 ZIP/582 notice records; два часовых окна77/EOK вернули
4 и5 уже сохранённых извещений, new_versions0. Дубликаты не считаются приростом.
Все9 исходных FAILED records неизменны, source SHA/new journal/audit сверены;
remaining eligible0. Вместе S182/S183:9 восстановленных окон/971 новых versions.

Полный tenant planned census14:09:05UTC:148168planned,5088completed,
143080pending,136544unattempted,6472NO_DATA; old attachment-count group отсутствует.
Это очередь запланированных source windows, не количество закупок и не полная
база ЕИС. Другие gaps:45invalidreferences,5unsupportedmembers и отдельные
variant/resource/sourcecontract ошибки. Cron продолжал обычный ingestion;
общий прирост completed/current не приписывается только нашему проходу.

Cached API44current133474 paper8.376s/server14.647s;223current2894
paper282ms/server645ms;health200/anon401/no-store/UNKNOWN. Finaloperations
14:09:55UTC:DB3698105367bytes,free265857155072bytes,notestDB/bothmarkersfalse.
Runtime не менялся, новые tests/rollout/rebuild не требовались; S182251 gates
не запускались повторно. Source/DB receipts, census/API/operations и финальные
hash/head gates — проверка этого operational slice. Proofs/SHA — docs67.

Следующий bounded slice: классифицировать45ATTACHMENT_REFERENCE_INVALID и
5MEMBER_UNSUPPORTED по точным сохранённым source bytes (либо bounded sample,
если bytes недоступны), с window/member/XML provenance и synthetic regression
для подтверждённой поддерживаемой формы. До подтверждения контракта не ослаблять
parser/UID/URL guards и не повторять всю группу. Затем fresh backlog/parity и
оптимизация search latency. Fullcoverage/fullcomparison UNKNOWN.

### S184 — классификация parser gaps по source bytes, завершён

Owner root: docs15/28/68/README и ignored baseline/capture/proof helpers.
Dependencies: S183, deployed parser и sync, tenant scope, прежние global leases
и resource budgets. Сначала read-only census latest FAILED45references/5members,
проверка доступности сохранённых bytes. Если bytes отсутствуют, до3 source
windows diagnostic fetch через прежний bind_ready_window/transport, без ingestion,
checkpoint, journal или новых доменных audit mutations. Полный source set и SHA
сохранить на VPS в bounded private research storage; token не сохранять.

Acceptance: typed/source-bound классификация точного predicate отказа с
window/response/archive/member/XML/ordinal evidence; неизвестные формы остаются
UNKNOWN, partial evidence не даёт completion. Подтверждённый parser fix получает
synthetic regression и release review до rollout; иное поведение не менять.
Нельзя снимать UID/URL/size/security/atomicity guards по догадке. Final API,
operations/hash checks и фактический next step обязательны. Scope реализации
и owned files parser фиксируются отдельно после получения evidence.

Дополнительное ownership до кода: Sol — новый sources/eis_parser_diagnostics.py
и tests/test_eis_parser_diagnostics.py (pure typed report, admission NOT_ENABLED);
Astra — независимый review и ADR0067, root — capture/проверки/документация.
Diagnostic report не выводит raw URL/filename/UID/text: member ordinal/name SHA,
XML SHA и attachment ordinal дают точную привязку к сохранённым bytes.

Подэтап до реализации: sample42 имеет8filename-forward-slash-only отказов,
при валидных UID/URL/size; sample30 duplicateUID; sample23 XML34586604bytes.
Root дополнительно owns sources/eis_feed_archive.py, tests/test_eis_feed_archive.py,
sources/eis_analysis.py, новый tests/test_eis_analysis_filename.py,
sources/eis_document_worker.py и tests/test_eis_document_worker.py.
Разрешить только `/` как неизменный source display filename; backslash/NUL/length,
UID/URL/duplicates и ZIP member path guards прежние. До document download вернуть
явный filename-review outcome, а analyze/reanalysis получают typed UNKNOWN до
DocumentInput. Не basename/normalize исходное имя и не создавать путь из него.
Acceptance: slash-only metadata сохраняется с exact ordinal/provenance, no-data/
unsafe refs не становятся PASS; no download/extractor invocation на reviewlabel,
typed UNKNOWN в collection/reanalysis, focused Linux/PG + retained-source proof,
review/backup/hash deployment и не более1controlled live recovery42window.
Root также owns additions в tests/integration/test_eis_document_queue_pg.py:
persisted job/API-status и cached reanalysis slashlabel UNKNOWN, source0.

Результат04.10.2026: source0 baseline45references/5members, retainedmatches0.
Diagnosticcapture3полныхboundwindows33.044s/6SOAPposts5ZIPgets;no-intakeSQLcounts0,
все50старыхrecordsimmutable. Sample42:8slash-only labels;30:duplicateUID;
23:XML34586604bytes. Newtyped diagnostic module проверяет globalZIPheaderbounds
до XML read и streaming50000nodes/depth128 до tree parse; incompleteUNKNOWN.
Slash разрешён только как точный source displaymetadata, worker до downloader
выдаётreviewattempted0;analysis/reanalysisUNKNOWN доDocumentInput.

141 Linux +40PG =181focused tests PASS, Ruff9/mypy4PASS, независимый reviewPASS.
Deployment14:38:05UTC backup/host15/runtime4 hashesPASS, API+workerrebuilt HEAD03.
Retained report42:37XML166attachments/findings0;30:16XML96attachments/duplicate1;
23:269headers266XML/1size-limit+2diagnosticnode-limitUNKNOWN;inspectionincomplete.
Actualsingle42Sep7EZKretry14:39:28UTC→SYNCED8.372s1ZIP37newversions0events,
actualcanonical/sourceSHA/journal/audit,50oldrecords и8rawslashlabels проверены.

Finalcensus148183planned/5105canonical/143078pending/136524unattempted/6491NO_DATA;
44references/5members остаются, coveragefreshnessUNKNOWN. CachedAPI44current134030
paper8.493s/server15.589s;2232898paper227ms/server643ms;health200anon401no-store.
TestDBs184удалена;finaloperations14:44:00UTC обаmarkersfalse/free265GB/DB3.71GB.
223cronmarker приAPIactive снят владельцем. Proofs/SHA — [docs68](../../eis/ingestion/68-eis-parser-gap-diagnostics.md).
Source/schema/cron/regions/budgets не расширены; source bytes остаются на VPS.

Следующийbounded slice: remaining region42 metadata gaps по подтверждённомуfix,
до3/source pass, exactlatest recheck, без broadretry всехreference failures.
Затем duplicateUID metadata classification и streaminglargeXML с resourceproof;
safeprocessingfilename отдельно сохраняет original displaylabel evidence.
Fresh backlog/parity и searchindexlatency остаются обязательными для цели.

### S185 — восстановление подтверждённой группы region42 metadata gaps, завершён с явным conflict gap

Owner root: docs15/28/68 и ignored s185 baseline/pass/verification helpers.
Dependencies: deployed S184 filename fix, immutable journal, прежние leases,
source transport, resource budgets; runtime/schema/cron не меняются.
Baseline16:00:14UTC:44reference failures,5member failures; region42 references39.
Scope — только эти39 exact baseline attempt IDs, максимум13 проходов по3 окна,
каждый проход максимум600s перед следующим source call. Не добавлять кандидатов
из новой очереди, других регионов/причин; no broad retry. Перед каждой операцией
проверять tenant/planned/latest ID/reason, completed date/hour+03:00,
canonical absence, DB100GiB/free40GiB. Между проходами освобождать leases.
Acceptance: стандартный sync без ослабления guards; при любом незавершённом
outcome или DB/journal/proof failure остановить следующие source calls.
После каждого прохода SQL-check actual canonical+source SHA, journal/audit,
new-version binding, неизменность всех50 S184 original attempts и точных
original attempts baseline S185. Типизированные candidate/outcome reports;
source bytes остаются на VPS. Итог — свежий census/API/operations, proof SHA,
actual deployed hashes; только canonical закрывает gap, coverage UNKNOWN.

S185 contract amendment до следующих source calls (16:11UTC): первый проход3
canonical162versions; второй4-еокно canonical74,5-еокно source duplicate→PARTIAL35,
1HOLD,canonicalfalse. Цепочка остановлена. Independent read-only proof подтверждает
37origins/receipt/batchcounts/4audits/HOLD UNKNOWN; исходные50records неизменны.
Review Astra: допустимо продолжить distinct unattempted keys исходной39cohort,
никогда не refetch conflict key. Новый root-owned ignored s185-resume helper
проверяет все previous canonical/partial receipts перед каждым source call;
continuation ONLY DUPLICATE_NOTICE_VERSION+PARTIAL stageCOMPLETE с полным bound
ledger/projection/origin/audit/HOLD proof и отсутствием LEGACY checkpoint.
Любая иная ошибка/DB/proof failure останавливает следующий call. Original
FAILED journal/UNKNOWN/partial сохраняются; new reports FINISHED_WITH_GAPS
не равны canonical completion. Remaining34IDs, по3/проход, максимум12 дополнительных
проходов (overall14 с прежним interruptedpass),600s-next-call gate unchanged.
Canonical newversions и partial projected/replayed/held считаются отдельно.
Resource/schema/cron/source/runtime guards прежние. Reports и stoppedproof
immutable, никаких raw source bytes на ноутбук. Это operational amendment,
не новое правило admission и не разрешение участия поставщика.

S185 дополнительный read-only preparation: root owns ignored
s185-search-scope-proof.py. Acceptance: один фиксированный aware UTC now и
RR tenant snapshot; exact latest versions и прежние token/hold predicates;
unknown/expired/future deadline census без source calls/DB writes/snapshot
hydration. Missing search-key fallback отдельно показывается. Это измеряет
selectivity будущего SQL-фильтра и не меняет API или утверждение coverage.

S185 read-only search preparation16:20:49UTC: paper2668token candidates,
1852expired/816future/0unknown; servers5806,4052expired/1754future/0unknown;
missing-key fallback0. ОднаRR snapshot/fixedawareclock,source0/write0,4.927s.
Уменьшение candidate hydration около70% — гипотеза ускорения, не latencyproof.

Следующий срез S186: явный cached search scope «срок не истёк или неизвестен»,
SQL-фильтр до snapshot hydration, historical toggle API/UI. Latest version
выбирается ДО фильтра; older unexpired нельзя воскресить вместо latest expired.
NULLdeadline остаётсяUNKNOWN, holds/events/rank/provenance неизменны. Counts
описывают selectedcached scope, coverage/freshnessUNKNOWN. Runtimefiles:
storage/eis_index_query.py,api/app.py,web/lib/procurement-api.ts,
tender-discovery/actions.ts и indexed-search.tsx (проверить exact path при старте).
Acceptance: exact parity с прежним allcached search после такого же фильтра,
tenant isolation/missing-search-key fallback/aware fixed now,PG/API/UI proof.
Пять warmruns на одинаковых frozen data дляpaper/server/mixedquery; targetmedian
<=50% прежнейlatency, evaluatedrows/SQL/payloadbytes/peakmemory измерить явно.
Если выигрыш не подтверждается, не обещать ускорение. Migration/index только
после EXPLAIN evidence. Историческую ingestionqueue не расширять для этого slice.

### S185 итог (04.10.2026)

Все39 frozen cohort keys обработаны по одномуразу,14 bounded passes,463.021s
суммарно внутри проходов (не latency одного пользовательского запроса).
38 genuine canonical windows/2046newversions; отдельно35partialprojectedversions,
1HOLDpair/37origins/noLEGACY. Conflicted window остаётся FAILED/UNKNOWN;
«осталось region42 references0» не означает все39canonical и не означает fullЕИС.
Finalread-only verification:39previous/remaining0,all50oldrecords immutable,
exact source/journal/audit/canonical counts и fullpartialproof PASS; reviewPASS.
Remainingglobal parser groups5references/5members. Baseline и stoppedpass
сохранены, причиной старыхотказов новые source SHA заднимчислом не становятся.

Census16:24:28UTC:148213planned/5210canonical/143003pending,
136385unattempted/6594NO_DATA,2transport-only. Candidate codes99,coverage/freshness
UNKNOWN. Cron работал независимо; весь прирост общей базы не приписывается S185.
CachedAPI44current138253,paper8.323s/2671matches,servers15.693s/5580;
223current2901,paper280ms/59,servers510ms/185. Health200/anon401/no-store,
coverage/freshnessUNKNOWN. Fast-search цель остаётся незавершённой.

Operations16:25:03UTC:DB3807796247bytes,free264945225728bytes,notestDB,
обаmarkersfalse. Actualmemory peak не измерялся; CPU2/memory2GiB configuredlimits
не расширялись. Runtime/schema/cron безизменений, rebuild/migrations не нужны;
новые продуктовыеtests не запускались. Operatorhelpers Ruff/compile/bashsyntax,
real-source receipts и SQL/API/operations/review — проверки данногоslice;
S184181tests не выдаются за повторный запуск. Finalproof SHA table — docs68.

S185 завершён как verified recovery с явным незавершённым conflict window.
Следующийприоритет S186 — ускорение поиска актуальных cached карточек по
описанному выше scope/parity/benchmark контракту. Fullcoverage/fullcomparison
UNKNOWN; documents/extraction/economics/допуск к участию этим не объявлены готовыми.


### S186 — поиск по сроку до разбора карточек, завершён

Owner Sol: src/procurement/storage/eis_index_query.py и additions в
 tests/integration/test_eis_notice_index_pg.py; при необходимости новый
 tests/test_eis_index_scope.py. Owner root: src/procurement/api/app.py,
 tests/test_eis_api.py, web/src/lib/procurement-api.ts,
 web/src/app/tender-discovery/actions.ts и indexed-search.tsx, docs15/28/69,
 docs/README.md и docs/adr/README.md, ignored rollout/benchmark/proof helpers.
Owner Astra: ADR0068 и независимый high-risk review, без пересечения ownedfiles.
Dependencies: S185 read-only selectivity proof, existing latest/hold/search-key
 contracts, PRD3.1/aware deadlines, deployed HEAD20261004_03/unchanged budgets.

Contract: search_scope ALL_CACHED | NOT_EXPIRED_OR_UNKNOWN. Storage default
 ALL_CACHED для совместимости внутренних callsites; API и UI default
 NOT_EXPIRED_OR_UNKNOWN, явный historical toggle. Не называть scope активными
 закупками: deadline null UNKNOWN, future не доказывает открытость подачи.
Latest version выбирается раньше deadlineфильтра (null OR > aware now);
expiredolder не воскресить. Tokenindex и missing-key fallback фильтруются вSQL
 до snapshot hydration; holds/events/rank/provenance unchanged. Result возвращает
 explicit search_scope/total_current_notices/excluded_expired_current_notices,
 inspected_current_notices/matched/evaluated/eligible относятся к выбранному
 scope; global queue/source coverage UNKNOWN. Invalidscope/naivenow failbeforeIO.

Acceptance: scoped parity со старым allcached после такого же deadlineфильтра,
 scoped counts/rank/toplimit и unknowndeadline сохранены; latestexpired suppresses
 oldfuture, boundary deadline==now excluded, tenant isolation/fallback/held/events
 verified in focused PG/API gates. UI clearly labels mode/counts, unknown остаётся
 UNKNOWN; auth/no-store/422invalidscope/APIdefaults tested. Before rollout review,
 focused Linux/PG/type/lint/web build and UIcheck, backup/exacthash/schema gates.
 Benchmark на одинаковом frozenRR snapshot/aware now:5warmruns per scope/query
 paper/server/mixed; exact parity rank/provenance (allresults not truncated),
 evaluated rows/SQLcalls/payloadbytes/peakRSS; targetmedian<=50% old ALL_CACHED,
 publish actual result even iftargetmiss. No new index/migration without EXPLAIN.
 No source calls/documentjobs/cron/regions/budget expansion for benchmark.

S186 pre-release evidence:44 Linux focused +26 PG tests PASS; runtime Ruff/mypy,
web TypeScript/lint/production build PASS. Frozen RR READ ONLY benchmark
snapshot53180:53180:, clock16:46:41.696859UTC, exact full pretop100 parity
all3queries. Five warm medians:paper8072.013→3609.358ms,
servers15587.794→6575.913ms,paperA4809278.921→4004.232ms; target<=50% PASS.
Current138257/scoped43790/excluded94467; hydrated2676→824/5811→1762.
Measured warmrun maxRSS815468544bytes, allocator retention prevents claiming
RSS reduction. Source0/DBwrites0/budgets unchanged. Proof/details — docs69.
VPS production build/deployment, host14/API2/web3/worker2 exacthash gates PASS;
backup verified, schema HEAD03 без миграций. API default/history/auth401/
invalid422/no-store/awareclock/223regression/health200 PASS. Actualdefault
paper3.806s/server7.005s. UIdefault/historycounts823/2671, correctscope and
unknownlabels PASS, refreshunchecked/source0/documentjobs0. Returndefault
проверен. Operations17:06:19UTC DB3.81GB/free264.06GB/no testDB/bothmarkersfalse,
API/web OOMfalse, caps1GiB/768MiB unchanged. Independentrelease reviewPASS,
ADR0068 DEPLOYED AND VERIFIED. Receipts/hashes/limitations — docs69.

### Следующий приоритет S187 — повторная стоимость проверок блокировок

S186 EXPLAIN показал scopedfirstbatch500:717.591ms против63.676ms ALL_CACHED,
hold/discharge CTE377.809ms и tempI/O. Это не отменяет fullsearch2.2–2.4x
ускорение; оставшиеся3–7s требуют отдельного SQLslice. До реализации назначить
одного владельца storagequery/holdquery, exactownedfiles и PG/parity acceptance.
Сначала разобрать фактический план и повторное выполнение CTE; затем уменьшить
стоимость без изменения tenant, latest/version receipts, conflict holds,
events/rank/provenance и UNKNOWN. Пять frozenwarmruns/full pretop100 parity,
EXPLAIN, API/UI/resource/hash/review gates обязательны. Schema/index менять
только при обоснованном плане. Source ingestion/cron/history budgets прежние.
Этот приоритет выполнен в S187 ниже; полный охват/свежесть/прибыль UNKNOWN.

### S187 — один поток SQL для сравнения cached карточек, завершён

Owner Sol: src/procurement/storage/eis_index_query.py,
tests/integration/test_eis_notice_index_pg.py, new tests/test_eis_index_cursor.py.
Owner Astra: new docs/adr/0069-eis-search-single-cursor.md и independent review.
Owner root: docs15/28/70, docs/README.md, docs/adr/README.md,
ignored stage/benchmark/EXPLAIN/gates/rollout/proof helpers. Ownedfiles не пересекаются.
Dependencies: S186 verified release/HEAD20261004_03, existing shared exact
hold/receipt/projection predicates и tenant consistent_read REPEATABLE READ.

Contract: существующий ordered candidate SELECT выполняется один раз через
server-side cursor; yield_per/max_row_buffer не больше batch_size, partitions
разбираются постепенно. Не подменять streaming разбиением buffered результата.
Event queries идут на том же connection/snapshot между partitions; cursor
закрывается в finally до выхода из transaction, в том числе при исключениях.
Shared hold/discharge policy, отдельный global heldcount, deadline scopes,
latest/fallback/ranking/provenance и API/UI outputs unchanged.
Не хранить разрешение конфликта между запросами и не создавать temp tables.

Acceptance: полный pretop100 набор и exact rank/provenance/counters совпадают
с deployedS186 для обеих scopes; PG multi-batch/eventquery/tenant/latest/
fallback/deadline/hold/corrupt-receipt/late-origin tests, cursorcleanup errors.
Ruff/mypy/focused Linux+PG, samefrozenRRclock/data5warmruns bothscopes3queries,
actual EXPLAIN/SQLcalls/inputbytes/RSS. Цель scoped median <=80% S186, без
обещания выигрыша до замеров; при недостижении опубликовать факты и пересмотреть
release. Sourcecalls/documentjobs/DBwrites0 в benchmark; schema/cron/budgets
unchanged. Перед rollout независимый review, backup/hash, API/UI/operations.

Результат04.10.2026: один настоящий server-side cursor, statement-local yield_per,
bounded partitions и finally cleanup; прежние tenant/latest/fallback/hold/events/
deadline/rank predicates сохранены. 47Linux+40PG=87distincttests PASS, Ruff/mypy
PASS. FrozenRR snapshot54428:54428:/aware17:58:48.636334UTC, all6 full pretop100
и весь response exceptelapsed exact parity PASS. Five warm medians default:
paper3593.510→2931.371ms,servers6563.556→5081.378ms,mixed3877.537→3184.393ms;
ALL7972.341→4998.158/15462.995→11236.546/9245.087→6340.002ms.
Scoped20% target MISSED paper/mixed, threshold неизменен; все6medians улучшены.
SQL calls reduced, rows/input unchanged; maxwarmRSS old715632640/new707260416,
allocatorconfounded, memoryreduction не заявляется. Independent rolloutreviewPASS.
OrdinarySELECT EXPLAIN отличается от DECLARE; livecursor tempI/O/servermemoryUNKNOWN.

VPS deployment/API/UI/operations PASS; backup verified, host12/API1/web3/worker1
exacthash PASS, HEAD03 без миграций. ActualAPIdefaultpaper3.313s/server5.032s;
UIpaperdefault3095ms823matches/history5483ms2671,returndefaultPASS,UNKNOWNlabels.
Operations18:16:17UTC DB3.81GB/free263.24GB/no testDB/bothmarkersfalse;
API/web OOMfalse,caps1GiB/768MiB unchanged. Foregroundsource0/docjobs0/writes0;
backgroundcron возобновлён без изменений. Proofs/hashes/limitations —
[docs70](../../eis/search/70-eis-single-cursor-search.md), ADR0069. Fullcoverage/freshness/profitUNKNOWN.

Следующий S188: свежий read-only census ingestion gaps и lag вместо дальнейшего
поиска ускорения без новой продуктовой необходимости. Сверить известные5reference/
5member gaps с exactlatest/canonical/partial/HOLD, выделить duplicateUID/largeXML
и необходимость дальнейшего bounded recovery. Перед реализацией назначить
ownedfiles/acceptance; retry только подтверждённой причины и конкретных окон,
retained evidence и CPU/memory/disk gates, без ослабления admission или broadretry.

### S188 — свежая сверка пропусков и производительности загрузки, завершён

Owner root: docs15/28, new docs/operations/71-eis-fresh-gap-and-lag-census.md,
docs/README.md, ignored s188 retained/operations/package/sync helpers.
Owner Sol: ignored s188-census.py и его evidence output на VPS.
Owner Astra: independent read-only review контракта и результатов; файлов не меняет.
Dependencies: deployed S187/HEAD20261004_03, exact latest journal ordering,
shared canonical/partial/HOLD policy, существующие scope/cadence/resource budgets.

Contract: read-only tenant REPEATABLE READ snapshot + fixed aware clock для
полного planned-queue census, latest failed parser cohorts, canonical/transport/
partial/hold counters и observed recent throughput. Freshness измерять отдельно
для фактического worker scope и national candidate-code planning scope;
capacity estimate не является SLA или подтверждением полноты источника.
Проверить deployed cron/script hashes и реальные параметры без вывода секретов.
Retained classification только существующих проверенных manifest/archive bytes,
hash/binding/path/resource guards; отсутствие bytes/полного разбора остаётся UNKNOWN.
Максимум10 latest parser gap keys, без source requests/retry/DB writes или
ослабления parser limits; source bytes остаются на VPS. Background cron прежний.

Acceptance: typed census counts reconcile, evidence tables/IDs/snapshot/clock/SHA;
точное разделение canonical, NO_DATA, unattempted, partial и HOLD; read-only
classification с bounded diagnostics и status UNKNOWN при неполном evidence;
измеренный throughput/lag с явным horizon и sample limits, без выдуманного ETA.
Ruff/compile helper checks, independent review, final operations/runtime hashes,
backup/docs sync и конкретный следующий bounded remediation по результату.

S188 amendment до дополнительного read-only probe: root owns ignored
s188-lag.py. В actual3region/5family scope проверить все допустимые current-day
hours и отдельно последние два часа; exact latest attempt/NO_DATA response SHA,
canonical source receipts и сохранённые publication timestamps. Разница между
latest eligible hour и latest nonempty canonical hour не равна polling lag:
позднейшие NO_DATA observations считать отдельно, без обещания freshness.
No source/DB writes. National current-day hours вне configured priority scope
показывать как ограничение конфигурации, не объявлять covered по dailydates.

Результат04.10.2026: corrected planned-EXISTS census v2, typed sums/tenant/time
PASS; v1 сохранён, parser cohort10 exact IDs unchanged. Snapshot54575:54575:,
aware18:29:25UTC,10.708s/source0/writes0. Queue148243=5221canonical+143022pending;
136230unattempted/6768NO_DATA/24failed (10parser/10variant/2resource/2contract).
NationalOct1–3:1188expected/planned,509canonical/678NO_DATA/1conflict,
unattempted0. Daily script4families не включаетEOK; currentdayhourcodes только
50/77/78. Retained2samples diagnosed,8no matchingS184sample; all10oldsourceSHAnull,
historicalbindingUNKNOWN; dup4fieldsequal≠subtreeequivalence,largeXMLinspectionUNKNOWN.

Lagproof18:31:59UTC exact300hourkeys/30recent:29NO_DATA1SYNCED, due0.
13h78EZK/7h77EF — distance от последнего canonical часа, после него13/7NO_DATA;
не polling stall. FreshnessUNKNOWN. 24h3317attempts/1037firstcanonicalkeys;
manual/recovery/automaticactors отдельно. Existing3regioncapacitymodelp957001.344ms,
nominal288/h fitPASS не nationalSLA. 99×5hourly495newwindows/h больше cap288/h
prioritylane; corpuslane отдельно240/h и общийimportlease учитываются совместно.

Ruff/compile/bashsyntax и independentreviewPASS. Runtime S187 hashes/head03
PASS, no rebuild/migration. Operations18:34:30UTC DB3.809GB/free263.26GB,
testDBnone/markersfalse/OOMfalse/capsunchanged. Foregroundsource0/writes0,
sourcebytesVPS,backgroundcronunchanged. Proofs/limitations —
[docs71](../../operations/71-eis-fresh-gap-and-lag-census.md).

Следующий S189: bounded national scheduling feasibility и dry-run выбранного
cadence. Сравнить daily five-family completeness (включаяEOK) и persistent
rolling currentdaywave; exactledger/ages, общий walltime/caps44lanes+223/document
leases, samplelimits и retries. Минимумодинbacklogslot, no resetstarvationпри
сменедаты. Не включать99×5hourly в прежнийpriorityworker под modeledPASS.
После выбранного реализуемого контракта — один bounded scheduler implementation.

