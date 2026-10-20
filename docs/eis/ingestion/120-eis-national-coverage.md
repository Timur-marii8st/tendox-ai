# Национальный охват и регулярная загрузка ЕИС

Приоритет пользователя изменён08.10.2026: публичные44-ФЗ и223-ФЗ по всей России,
максимально доступная история, обновление и удобный поиск. getDocsIP уже работает;
повторного подключения, выгрузки production6 или восстановления нет.

Уточнение приоритета09.10: первый продуктовый результат — **актуальные44/223
по всей России с измеренной свежестью**. История догружается отдельно на
оставшейся мощности и не блокирует fresh flow. После завершения текущей выкладки
root измеряет новые окна/сутки по официальному каталогу регионов и семейств,
реальный terminal throughput, source→search lag и конкретные необслуживаемые
координаты. Fresh throughput должен превышать arrival; история получает только
остаток с сохранением source pacing/leases и резерва сервера. Если timestamps
или независимая сверка отсутствуют, соответствующая метрика UNKNOWN. Проверять
нужно loaded/SYNCED/NO_DATA с provenance, а не число plans. Отчёт разделяет
ежедневную свежесть, неподдерживаемые типы и историю с прогнозом по пробелам;
общий исторический ETA не является acceptance. Этот следующий срез ещё не выполнен.

Root — один владелец; live/program/evidence и индекс документации. Первый
подтверждённый срез: ARCHIVE_COUNT_LIMIT notice223 для77/2026-10-05 и2026-10-06,
purchaseNotice. Перед source изменением фиксируются точные owned files и caps.
Acceptance: полный связанный набор источника атомарно сохранён, ранее
отсутствовавшие версии доступны через пользовательский поиск; tenant/provenance,
лимиты и approval сохранены; реальные память/время/backlog и ограничения раскрыты.

## Production before

Read-only RR census `national-priority-production-before-v1.json`, SHA
`823109cc36d59aff52a259cc2ec99a1d998c0f243c8c216e15c2ee9ee49943dd`.
DB clock2026-10-08T20:05:11.972665Z, snapshot123143:123143:, appprocurement_app;
2.830220s, source calls0/DBwrites0.44:300328versions/276074purchases;
223:15191versions/14197purchases. DB9603316759B.

Grouped44 coordinate fields in this first raw census include daily/hourly/
by-number key shapes; split_part groups are raw and must not be presented as
normalized coverage. A corrected coordinate report follows. Planned windows
are not proof of loaded data.223 currently has two old ARCHIVE_COUNT_LIMIT gaps;
current wave's COMPLETE only describes its exact planned two-day scope.

## Нормализованный census

`national-priority-normalized-census-v1.json`, SHA
`131ea7d9877ced450e072eb3722f322c1b4e26263ad6544efaf11f6a680fa365`,
использует существующий parser daily/hourly. Полные координаты и отдельно
by-number records: `national-priority-census-summary-v2.json`; 223 —
`national-priority-223-family-summary-v1.json`. Min/max ниже не означают
непрерывного покрытия между датами.

| Закон / семейство | Регионы с данными | Даты окон с данными |
|---|---:|---|
| 44 / epNotificationEF2020 | 90 | 12.08–08.10.2026 |
| 44 / epNotificationEZK2020 | 89 | 12.08–08.10.2026 |
| 44 / epNotificationEOK2020 | 77 | 29.09–08.10.2026 |
| 44 / epNotificationCancel | 89 | 12.08–08.10.2026 |
| 44 / epNotificationCancelFailure | 32 | 13.08–07.10.2026 |
| 223 / purchaseNotice | 85 | 02.10–08.10.2026 |
| 223 / purchaseNoticeAESMBO | 76 | 01.10–08.10.2026 |
| 223 / purchaseNoticeZKESMBO | 78 | 01.10–08.10.2026 |
| 223 / purchaseRejection | 62 | 01.10–08.10.2026 |
| 223 / purchaseLotCancellation | 2 | 02.10–06.10.2026 |

44 plans: коды01–99, четыре семейства с28.09.2025, EOK с29.09.2026.
Это не подтверждает ни корректность всех кодов, ни загрузку. 223: официальный
региональный каталог90 кодов; пять families запланированы во всех90 за02–08.10.
Нет saved purchaseNotice window для07/79/83/89/95; отсутствие данных не доказывает
наличия закупок: NO_DATA учитывается отдельно. Двухдневная current wave:
900 terminal attempts,457 SYNCED/443 NO_DATA; COMPLETE только этого scope.

Retained официальный каталог документов проверен02.10 (export26.09), не заново
08.10: PRIZ поддерживает5 из27 public/actual типов, RI223 —5 из67. По всем
публичным подсистемам каталог содержит126/93 типов для44/223;121/88 не реализованы.
Полный список неподдерживаемых кодов/подсистем/XML SHA — в `official_catalog`
нормализованного census. Иные подсистемы не исключаются молча из «всей ЕИС».
История ранее дат реально сохранённых окон не подтверждена.

За24h очередь44 без когда-либо terminal attempt уменьшилась128602→126423:
2179 окон нетто,90.79/h; за последний час95. Добавились825 plans,
3004 targets впервые получили SYNCED/NO_DATA. Это скорость обработки заданной
очереди, не независимая сверка полноты. При неизменном темпе текущие126423 targets
потребовали бы около58 дней; условная оценка не включает unsupported families,
дополнительную историю и повторные обновления. Первые canonical windows за24h:
44 —1313,223 —203; это другая метрика, не число новых закупок.

## Первый bounded fix и actual evidence

Root — один владелец; Astra — независимый review. Owned implementation:
`src/procurement/sources/eis_223_window_limits.py`, `src/procurement/storage/models.py`,
`tests/test_eis_223_index.py`, `tests/test_eis_223_sync.py`, миграции
`20261008_01_eis_223_eight_archive_window.py`, `20261008_02_merge_eis_window_budget.py`.
Owned docs: live/product16/этот документ/ingestion README/addendum ADR0059.
Helpers/evidence остаются private в `tmp/improvement-program/m2`.

Уточнение: окно77/05.10/purchaseNotice уже имело старый response2 ZIP/190 XML,
ingested05.10T11:02:10Z; отсутствует позднее полное обновление, а не любое окно.
`national-223-window-existing-history-v1.json` и
`national-223-window-diagnostic-result-v2.json`: новый полный set5 ZIP/433 XML,
compressed27881069B, expanded93890584B, largest XML1580613B. Старые cap4 и
aggregate400 блокируют обновление; byte/per-archive caps достаточны.
Изменены только8 ZIP/800 XML и CHECK БД. Миграция от actual installed08 не
требует unrelated pending09–12; отдельный merge сохраняет единый head.
Downgrade запрещён при history>4 и при невозможности увидеть все tenant rows.
Source measurement31.026s/peak511807488B; существующая223 lane под lease
дождалась47.008s и сняла marker. Повторных source requests нет.

**COMPLETE_ISOLATED_WINDOW_INGEST_AND_USER_SEARCH; production INCOMPLETE.**
Использован принятый stopped production6 PGdata, без нового export/restore.
Пакет неизменён; replay-копия теперь расширена, прежний ordered-hash acceptance
относится к её исходному состоянию. Для новых blobs добавлена только omitted
nullable content column. Отдельный nonsuper/NOBYPASSRLS writer имеет INSERT
на затронутые таблицы; поисковый procurement_app остаётся SELECT-only/read-only.

`national-223-isolated-resume-dispatch-v1.json`: полный set5 ZIP/433 XML сохранён
атомарно,243 отсутствовавшие версии14997→15240 за3.226s; windows3934→3935,
blobs2030→2035, archive sources1811→1816. Replay:0 новых версий/изменений counts.
Foreign tenant:0 в затронутых таблицах, HTTP выдача пуста. Downgrade отказP0001.
`national-223-boundary-dispatch-v1.json`:8 допускается с rollback,9 отказ23514;
downgrade при невидимой чужой history отказ42501. Production writes0.

По [ADR0051](../../adr/0051-eis-223-schema-quality.md) full-XSD — отдельное
evidence. Existing pinned validator/record_schema_check, batch2:866 observations,
816 PASS/50 FAIL, то есть408/25 XML по каждой16.2/16.3. Пустой phone или
отсутствующие обязательные даты placingProcedure дают FAIL; source не исправлялся.

Три запроса зафиксированы из первых трёх отсутствовавших source titles до поиска.
Точный deployed FastAPI endpoint вызван через HTTP ASGI с isolated auth;
production browser/live API этим запуском не проверены. Exact requests и raw
responses сохранены, названия ниже сокращены только для чтения.

| Запрос | Закупка / версия в выдаче | HTTP | Время,s | Source schema |
|---|---|---:|---:|---|
| 226428_Кислота серная контактная… | 32616436390 / v1 | 200 | 3.813819 | FAIL |
| права на использование Касперский смол офис | 32616436397 / v1 | 200 | 2.850716 | PASS |
| КО №4990/КО… Моторное топливо… | 32616333441 / v9 | 200 | 14.979112 | PASS |

Первые две — точные добавленные v1. Для третьей добавлена историческая v8,
а current search корректно показывает уже имевшуюся v9; доступность v8 через
этот endpoint не заявлена. Каждая первая страница100 результатов; весь обход
не проверялся. coverage/freshness UNKNOWN, indexed counts/latest_ingested_at
видны. Precision/recall без независимых labels не измерены.

Worker36.788893s, controller55.991417s; peak worker479506432B (457.29MiB),
PG271081472B (258.52MiB). Caps2GiB/1GiB, CPU1 каждому, swap0/OOM0.
Admission:6432989184B RAM,198135283712B disk; требуется4.5GiB с резервом1.5GiB
для приложения/productionPG и40GiB диска. Containers/internal network cleanup
PASS; изменённый корпус сохранён stopped. Raw: `national-223-isolated-preserved-v1`,
8 files19677387B, SHA в `national-223-isolated-preserved-manifest-v1.json`.
67 unit tests/Ruff/mypy PASS подтверждают локальный delta, не production rollout.

Отказы helpers сохранены: uid/chmod копии; ошибочный дополнительный XSD gate
нашего сценария (устранён сверкой действующего ADR, схемы не ослаблены);
ошибочная предпосылка отсутствия любого окна вместо exact нового response.
После двух неудач подход упрощён до reuse prepared input и existing ingest/
quality функций. Нового runner/gate или повторного source/corpus capture нет.

## Подтверждённый production blocker и следующий шаг

Read-only guard установленного release entrypoint отказал:
`QUALITY_GATE_ADAPTER_UNAVAILABLE: INSTALLED_BASE_OVERLAY`, script SHA
`5fdb8e21ed043bb914eeff000d6bd75f910ab447f2bba97ea3bd41cec047c793`;
`national-223-installed-promotion-blocker-v1.json`. Install не вызывался.
[Действующий контракт](../../operations/115-candidate-quality-workflow.md)
не разрешает overlays по full-source receipt. Emergency override не выполнялся;
локальный fix/isolated evidence не заменяют receipt или exact-payload approval.
Production-прогресс этого исправления равен0, оба старых обновления остаются open.

Открыты:77/06.10;44 ATTACHMENT_REFERENCE_INVALID (11 latest failed coordinates),
NOTICE_VERSION_CONFLICT05/01.10, duplicate/version/unsupported characteristic
failures; freshness default50/77/78; повторное сравнение кандидатов на каждой
странице; ранее принятый q05 timeout. Latest failure не доказывает отсутствия
старой загрузки окна. Поиск ещё не показывает полную региональную/календарную
матрицу пробелов: UNKNOWN и ingestion time не заменяют её. Полный охват не заявлен.

## Попытка полного source release09.10.2026 — INCOMPLETE

Root — один владелец release/evidence/live/этого документа/handoff; единственный
Astra reviewer повторно проверил готовый кандидат и реальный отказ. Application
fix не расширен; установленный controller/verifier/policy не изменялись.

Точная host-база сверена с работающим API:209 Python files, differences0;
web source136files, differences0. Existing packager создал полный snapshot:
1049files/13644156 input bytes, archive3230737B. Термин FULL_SOURCE_SNAPSHOT
здесь обозначает полный состав; допустимый existing source_kind —
WORKTREE_SNAPSHOT, а не отдельный новый enum. Исходная база сохранена отдельно.
Private derived Git commits не выдаются за исходную installed Git history.

Кандидат production223-candidate-v1.tar.gz, SHA
59e85eb93076ddb298cfe2c82d94e768667d2b548b2c2a4e43380870d15b7b0c,
treeSHA bb18f3de7ad8330b2f7cdb55da91ca68710f737c00e7f96c6c9ae429e757376b.
Ровно пять changed source paths плюс служебный manifest: limits, только CHECK
в установленном models, два принятых regression test files и08_01 от installed08.
Unchanged file hashes/modes/sizes совпали; deletions0. Merge08_02, pending
manufacturer и прочие local changes не включены. Exact patch SHA
89ed59e6c46a30cfcb06bab9371e457973487e5f2cfa467fa0b0ac845090e518.

Запущен именно установленный полный run_release_gate.py, без stage-selection,
policy override или отключения guard. Run release-20261008-210833-dfce0fcd8724
завершился за30.222348s: **FAIL docs-navigation**, Python ENOENT
/workspace/scripts/check_docs.py. Receipt отсутствует. Это не результат
unit/PG/API acceptance: downstream quality stages не выполнялись.

Дополнительная статическая сверка candidate manifest с неизменной policy:
отсутствуют также check_quality_scope.py,11 обязательных PG modules
(восемь manufacturer плюс mixed comparison/captcha/search pagination),
шесть web configs и семь web tests. Оба installed Dockerfile не совпадают
с recipe allowlist. Эти последующие стадии не запускались; их PASS/FAIL не
приписывается. Простое добавление двух helpers не решает общий конфликт.
Canonical policySHA f4d17fa49f6550a5a476e6d10ba8e4c425a9323e6a8d7a033953bb7296ba1efe.

Admission: RAM6427181056B, disk197947076608B; existing runner caps3GiB+PG1.5GiB,
остаток над суммой caps1595342848B. Фактический peak UNKNOWN: текущий workflow
не записал его до cleanup; caps не выдаются за измеренный peak.
Cleanup: четыре gate resources удалены; отдельный inventory по actual installed
session label подтвердил отсутствие containers/networks/images и receipt.
Первый local inventory query использовал неверный label key; corrected-v2
сохранён рядом с ним. API/PG/web IDs/images running прежние; production limits
и три trusted gate file SHA неизменны.

Evidence — private tmp/improvement-program/m2/production223-release-v1:
preparation.json, exact-delta-verification-v1.json, policy-compatibility-v1.json,
raw gate-preserved, post-gate-cleanup-v2.json, independent-review-v1.json,
root-result-v1.json; full candidate/base archives и patch сохранены локально.
Независимый review подтвердил delta/отказ/cleanup и несовместимость контракта.

Production установка/миграция/повторная обработка двух окон не выполнялись,
новых production versions от fix0, production search после fix не проверен.
Failed candidate не предъявлялся как готовый для exact-payload approval.
При неизменном составе и policy повторный запуск не обоснован.

Следующее одно действие: узко разрешить несовместимость существующего full-source
workflow с exact production branch, согласовав необходимый release scope;
не создавать новый guard, не обходить установленный и не включать посторонний
product code. После receipt — exact-payload approval, установка и оба окна.
Ночная инструкция09.10 разрешает после сохранения точного release blocker
перейти к независимому срезу скорости загрузки. Приоритет — измеренное
сокращение backlog с соблюдением лимитов ЕИС;
условные58 дней не считаются окончательным решением.

Независимый review: `national-223-count-fix-review-v1.json`, SHA
`faa6f6e648055cd15463fcebef85ef500016597cf5fbd9b176d8123d7dace960`;
ACCEPT_LOCAL_COUNT_FIX_AND_BOUNDED_ISOLATED_FUNCTIONAL_EVIDENCE.
Блокеров реализации нет; оговорка third target v8/current v9 включена выше.

## Production223 branch compatibility — COMPLETE technical / deployment BLOCKED

Root owns controller/verifier, exact branch policy, docs checker, regressions
and evidence; the same independent Astra reviewer is retained. Acceptance:
complete applicable gate and independently verifiable receipt, then supported
exact-payload promotion. Production6 and accepted restore are reused.

Complete map v4 separates required build/check tools, installed-function tests,
and uninstalled manufacturer/capture/benchmark/SERP-v2 tests. The55-path
supplement is test/build/navigation support plus one AST-equivalent formatting
change. No future product behavior was imported. Trusted controller/verifier
and policy diffs are separate; active provider and both guards are unchanged.

Exact v4:1079files/3280991B; archiveSHA
c6415267a4ec5340ef8be68266aea792d4b24a282874961347e4e0b03831102e,
treeSHA e573c9fcd98b341f49e1cab08da50a687ecf8263ed71c8e38207428ebb8b3b73,
manifestSHA d27ff331e5cd1c4280f899b769a195a9ac88170239b611bc1cd35e6277bc13d0.
Policy2026-10-09.production223.4 canonicalSHA
29fb4cd22d8e82dffdbe502b1fc373a022acf68d2c179cf3c456d8fc48005a71.
Scope:3172Python/9doctest/578PGtests in52modules14groups/127Node;
27named Python skips and existing optional omissions remain explicit.

Prior full failures are retained, never promoted to PASS: v1fixtures262.962s,
v2tenant mocks386.368s. On renewed user authorization fullv3 ran444.024s:
3145unitPASS/27knownskip,9doctestPASS,PG343PASS/4FAIL. All4 failures used
expired September synthetic deadlines. V4 changes only2PG tests and shared
test fixture; fixed-time domain fixtures and explicit reapproval remain.
Independent1079file source audit PASS; all341app files identicalv3.
Foundation plus10 previously unreached groups:334realPGPASS/0skip218.370s,
cleanupPASS. This targeted result is not a complete release receipt.

Fullv4 run release-20261008-222648-27c4a2414d9e completed all48mandatory
stages PASS in775.545973s.3145unitPASS/27exact knownskip,9doctest,578PG
and127NodePASS/0skip; build and startup smokePASS. Typed receipt verifier
and independent85report/105rawfile auditPASS. ReceiptSHA
11dd4ff15906cb574c0a622c0299ea63d4566d5df6206a4bc032d08f00ab6526.
Admission:MemAvailable6821576704B, disk196784807936B. Caps remain
Python3GiB+PG1.5GiB; PG/Python, Node and builds execute sequentially.
Root28controller/docs tests, Ruff and docs262/773/14PASS. Observed cgroup
peaks:Python581603328B,PG269713408B,Node2168373248B;OOM0, sampled host
minimum4627419136B.5second observations are not guaranteed total/final peaks.
Cleanup:9owned resources removed; containers/networks empty, exactly2accepted
images retained. Production API/PG/web IDs and activeprovider/guards unchanged.

A separate production promotion blocker is confirmed by independent review.
Existing activate_quality_provider.py only activates trusted provider files
(runtime_changes=[]); both legacy overlay mutators refuse before mutation.
There is no supported receipt-consuming FULL_SOURCE app promotion adapter.
Historical direct Docker/copy procedures are outside routine promotion.
The user forbids a new guard or bypass, so none is introduced. A technical
receipt or provider activation alone cannot install223 or migrate production.

Existing installer preflight passed exact provider package v4:
packageSHA50087eb19a2961565ff3d8467f1c4abd8c5cbb910deaf48978dbfc94daaccd62,
planSHA a57b0522314d0a638da65e216697ddf7957097bdf85face5ad49a0a4e0adf986.
No activation; prior approval covers different bytes. Exact request, code/DB
delta, installation limits and rollback are saved in overnight01-release.
Application approval is not ready as a final step while promotion is blocked.
No production migration, new post-fix versions or production-search proof.

Evidence: tmp/improvement-program/m2/production223-compat-v1:
complete-map-v4.json, support-supplement-v5.json, clock-fixture-fix-v4.diff,
trusted-controller-verifier.diff, trusted-policy-v4.diff, gate-preserved-v3,
targeted-pg-preserved-v4.tar.gz, targeted-pg-summary-v4.json,
independent-v4-source-review.json, independent-full-v4-review.json,
full-v4-audit.json, full-v4-summary.json, gate-preserved-v4. Next: unchanged
production ingestion throughput slice; supported app promotion remains blocked.


## Overnight throughput slice — 2026-10-09

One unchanged 60-window parent `46d06a54-014e-4dd6-bb2d-5b730a11e7aa` completed in 570.025 s under the existing shared leases, 2 s source spacing, 2 CPU / 2 GiB worker limit and 40 GiB disk reserve. It first closed 55 windows, added 1,182 versions of which 1,074 purchases had no prior version, and 22 events. Sampled worker peak 384,475,136 B; host minimum available 6,089,641,984 B. No cron, application image or schema change was installed. This single extra pass does not establish sustained acceleration.

Production HTTP search found new notices 0150200003926001104 / 1107 / 1108 via NOKB (Cyrillic), prostheses and PCR terms in 4.555 / 8.404 / 7.610 s, respectively, with source/version evidence retained. Three earlier multiword title queries each timed out at 35 s. Search quality remains UNKNOWN without independent labels. Evidence: `tmp/improvement-program/m2/overnight-20261009-v1/02-throughput/result-v1.json` and bound raw responses.

24 h baseline: 3,438 first terminal windows minus 825 new planned windows = 2,613 net reduction (108.875/h). 23 horizon-limited parents left 627 attempts unused; corpus import waiting total 19,255 s. Counts refer only to the planned queue. The conditional 48-day estimate is not a solution or whole-EIS completion claim. A same-snapshot SQL trial replacing LATERAL with aggregate preserved all 60 ordered keys but saved only 1.060 s (26.946 to 25.887); it was reverted. No ingestion code change is retained. Later local search slices are reported in [pagination](../search/113-eis-search-continuation.md) and [lexical comparison](../search/30-eis-fast-comparison.md).

Second bounded pass: parent8f906026-4247-46f2-a0e1-ad3feb62d536 completed60
NO_DATA attempts in407.765s after60.456s normal lease wait;52first terminal windows,
0new versions/purchases. Queue planned152446 unchanged; terminal27149→27214
during the full interval, but only52of65 newly terminal windows belong to this
parent. Eight attempts reconciled already terminal windows. First dispatch was
refused CORPUS_WORKER_BUSY before source attempts; diagnosed separate parent lock,
then one corrected bounded wait/retry passed. No third retry or lock bypass.
80five-second observations: source worker cgroup peak observed304201728B, host
MemAvailable minimum5908471808B, caps2CPU/2GiB unchanged, sampledOOM0. Samples
include cooperative regional workers and may miss a final peak. Existing840s
horizon,6segments,60attempt budget,2s spacing and100GiBDB/40GiBdisk gates retained.
Evidence: overnight02-throughput/result-additional-v3.json and bound journal,
parent receipts and raw samples. No new source-version search check needed for
this pass; the earlier three new-purchase production HTTP checks remain valid.

Combined extra passes:107first terminal windows,1182versions,1074previously
absent purchases,22events. They are additional work, not an installed scheduling
acceleration or proof of national/whole-history completeness. Sustained speed
improvement remains unproven; shared import/parent waiting and incomplete horizons
remain measured constraints. No new permanent speed setting was installed.

## Production223 installed and national fresh pilot — 2026-10-09

Approved exactv4 is installed; schema20261008_01, worker3GiB/3CPU. Both77Oct5/6
purchaseNotice sets now fit5archives:481versions/423previously absent purchases,
with three exact-version discovery HTTP proofs. Normal223 ingestion also closed
77Oct8 ARCHIVE_COUNT_LIMIT:5archives,414records,57additional versions. Integrity,
source bindings and original per-archive/row/batch limits are preserved; see
[release evidence](../../operations/115-candidate-quality-workflow.md).

Read-only repeatable tenant snapshot at2026-10-09T12:18:09Z checks the official
90-region catalog against five supported families per law for completed08.10.
44:448/450 terminal with source evidence (281SYNCED/167NO_DATA/2FAILED).
223:450/450 (236SYNCED/214NO_DATA). Remaining44 coordinates:48/EZK2020
DUPLICATE_NOTICE_VERSION;77/EOK2020 ATTACHMENT_REFERENCE_INVALID. NO_DATA is a
retained source observation, not proof that no procurement exists. This scope
excludes unsupported catalog families and does not establish whole-EIS completeness.
Retained catalog census reports5/27PRIZ and5/67RI223 implemented public families;
the official unsupported-type inventory remains explicit, not silently excluded.

The last24h baseline observed5163/2900 attempts44/223, including history/repeats;
335.96combined attempts/hour is not new-window throughput or source purchase arrival.
Supported scope generates450daily coordinates per law/day and450new44hour
coordinates/hour. True source purchase arrival remains UNKNOWN. Default priority
cron still selects50/77/78; daily observations do not establish hourly freshness
for the other87regions.

One bounded existing priority runner pass selected all90regions,60slots/240s
instead of24slots, preserving2s source spacing, leases and server reserve.
After30.487s normal priority-lock wait it completed43coordinates in241.358s:
7SYNCED/36NO_DATA,37new44versions/2events,0failed; terminal BLOCKED with
RUN_TIME_BUDGET_REACHED. It covered five families each in01–08 and three in09.
Total wrapper279.119s; active-rate641.4terminal/hour is one sample, not sustained
national capacity. Increased slots permit43rather than the old ceiling24, not a
controlled before/after speed comparison. Cron/scheduling policy was not changed.
Sampled ordinary-worker peak284721152B/OOM0, host available6630084608B;
final pilot/end-to-end peak UNKNOWN. Earlier full-snapshot postcheck OOM is retained.

All37new notices have search-key projections. Publication-to-index lag by source
region:01 one notice125.41min;02 34notices74.96–129.82min (median112.11);
05 two notices90.93–97.42min (median94.18). Frozen discovery queries returned200:
Куюргазинского found0801500001126001986/version1 in3.457s; межрегионального
and легкового returned38/382matches in3.711/5.953s, but their expected notices
were not in the first ten; availability for those two queries is not confirmed.
223 publication.value is commonly null with naive raw timestamps: timezone and
numeric publication-to-index lag remain UNKNOWN, not assumed Moscow time.
Search quality precision/recall remains UNKNOWN without independent labels.

Current rolling policy asks for900recent44poll coordinates/hour before daily223
and shared-lease work; one641.4/h sample does not fit that load. Legacy24-slot
capacity model also fails national450/h intake. Main confirmed constraints are
slot ceiling, repeat-poll workload and shared lease waiting; RAM is not a measured
normal-ingestion bottleneck. A conditional first450-coordinate sweep would take
about42active minutes at this sample rate, but hourly movement/repolls/contention
make it an invalid national freshness ETA. Full national freshness is INCOMPLETE.
Next bounded slice: latest eligible hour first with limited daily reconciliation
through the existing scheduler, measure shared44/223 capacity and reserve history
to spare work; no new launch platform or permanent unmeasured change is installed.

Evidence: production-promotion-20261009-v1/national-fresh-production-measurement-v1.json
and-v2.json, national-fresh-pilot-plan-v1.json, national-fresh-pilot-result-v1.json
(busy/no source calls) and-v2.json, production-fresh-runtime-memory-v1.jsonl,
national-fresh-projection-search-v1.json. Per-coordinate matrices, catalog source,
timestamps, query plans, raw responses and provenance are retained in these records.
