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


## R1: защищённая догрузка завершённых дней — кандидат22Oct

Владелец root, один агент. Зафиксированный read-only census22Oct16:12МСК:
44 —381040закупок/415263редакции;223 —41737/48038. За21Oct суточный44 scope
99candidate codes×5types:3canonical/492unattempted, не процент полноты ЕИС.
Logs показывают DEFERRED_FOR_NEW_HOURS, MANDATORY_FRESH_WORK_READY и исчерпание
joint start budget. Свежие часовые окна вытесняют обязательную суточную догрузку.

Кандидат вводит opt-in EIS_RECONCILIATION_SHARE_ENABLED=1: до360s фактической
обработки recent completed-day debt на каждый закон внутри прежнего общего
3240s/hour start budget; атомарный tail180s, lease/source pacing/resource gates
сохранены. Это доля допуска попыток, не гарантия SYNCED или полноты.
Свежие запросы сохраняют неиспользованные доли только при наличии recent debt;
история получает остаток.44 выбирает bounded exact coordinates последних3дней,
223 использует accepted official region catalog; неисполненное сохраняется.
Первые попытки44 идут перед terminal rechecks. NO_DATA остаётся наблюдением,
все guards/variant holds и прежние acknowledgement правила сохраняются.

Owned files и acceptance: tmp/eis-reconciliation-20261022-v25/scope.json.
Production пока B9; код в отдельном candidate, root source не подменялся.
Последовательность после R1: экономия NO_DATA retries, конкретные failed windows,
устойчивый throughput и отображение свежести. Сутки наблюдения и закрытие21Oct
ещё не выполнены; весь M5 остаётся INCOMPLETE.

R1 проверки22Oct: focused unit72PASS и isolated PG59PASS; accepted source ещё
проходит полный gate. Read-only realDB selector: прежний batch24/24RECENT_HOUR,
новый recent daily44 выбирает21Oct за0,190s,223 recent debt за2,873s;90official codes.
Source0/business writes0; это selection evidence, не фактическая догрузка.
R2 diagnostic13:36UTC: за24h9343NO_DATA/9343distinct44windows — повторов нет,
сокращение перепроверки по этому замеру не обосновано. R3:49expansion failures/
5windows,19ATTACHMENT_REFERENCE_INVALID/2windows; backlog устранения не закрыт.
Evidence: tmp/eis-reconciliation-20261022-v25/readonly-selection-proof.json,
retry-diagnostic.json и source-delta.patch. Установленный worker пока c2.

Финальный R1 source2898fc97, treecc7122ac; gate50/50PASS:
unit3815PASS/27allowedSKIP, PG708/Node199/doctest9PASS. Worker3462de61;
API/WEB/DB не переустанавливаются. Non-owned Python modules совпадают с installed
B9 API; runtime-delta/source provenance в worker-module-delta.json.
Accepted-image synthetic E2E: protected daily44/223 при fresh pressure, real
isolated PG, tenant isolation и NO_DATA-not-canonical PASS. Два ранних E2E fixture
сбоя (один регион не заполнял batch24; tmpfs16MiB закономерно нарушал40GiB reserve)
исправлены только в test harness. Финал использует пять регионов, ephemeral image
writable layer с действующим disk guard; source stubs, production writes0/source0.
Откат трёх файлов проверен7simulation guards; readonly activation preflight PASS.
Пакет activation-plan.json SHA256
`3c1a2bae41cd4f7db4870362c52aed9a3cf9387583ac60dfa965645326ce7b5f`.
Меняются base/active worker image+opt-in и exact host223 Python script под lease.
Нет migrations, forced worker stops, cron changes, API/WEB/DB restarts или удаления.
Production остаётся B9/worker c2 до exact approval. После установки — обычный
cron и real source/window/audit verification; закрытие21Oct и sustained freshness
ещё не подтверждены. M5/национальная полнота остаются INCOMPLETE/UNKNOWN.

## R1 установлен; R1b — блокер штатного запуска223

Подтверждённый payload3c1a2bae применён22Oct17:25МСК, operation
acc948eb-ade7-42a2-8a4a-6b6a0944b675. Worker3462de61 с opt-in1,3GiB/3CPU;
API6b/WEB949/DB ID/schema20261021_01 и cron сохранены. Health и tenant audit PASS.
Ordinary worker14:27UTC подтверждён inspect image/env/caps/OOM0; первый batch
15daily21Oct:7SYNCED/8NO_DATA, затем41fresh (первый snapshot56attempts).
Baseline14:22:43UTC по90official×5families:450окон,72canonical/1NO_DATA/377unattempted.
Source0/DBwrites0 относится к observer, не к штатной загрузке.
Evidence: tmp/eis-reconciliation-20261022-v25/activation-audit.json,
ordinary-progress.json и day21-official-baseline.json. R1 повторно не применять.

У223 ранее существующий REGIONAL_PROBE_UNAVAILABLE продолжается: last24h logs
показывают ошибки ещё до worker startup. Диагностика: coverage0,369s, fresh due0,420s,
recovery selector9,822s с SQLSTATE57014 при5s per-statement guard.
Новый bounded host probe проверяет только recent planned completed-day keys,
accepted catalog и latest tenant attempts трёх семейств; missing/cooling/terminal
и final-day cutoff сохраняются. Known recent debt избегает cold-history scan;
если его нет, прежний full recovery/history path сохранён. Ошибка/нет catalog/
нет source evidence не превращаются в IDLE. Worker selector и source intake неизменны.
RealDB readonly candidate READY0,907s, source0/business writes0; production host
пока прежний, новый payload ещё не установлен. Код/owned files:
tmp/eis-223-dispatch-20261022-v26/scope.json. Общая загрузка44+223 не объявляется PASS.


## R1b готов к точечной установке — 22 октября18:06МСК

Финальный source54a7298b/tree7e7aad12; release-20261022-144925-ca005fdc5c09:
50/50PASS, unit3819PASS/27allowedSKIP, PG710/Node199/doctest9PASS. Cleanup complete.
Первый прогон FAIL: два существующих unit fixtures storage=object не mock-али
новую readonly dependency; исправлены fixtures с сохранением assertions. Product
host script между прогонами не менялся; календарь новых тестов фиксирован.
Retained API6b image synthetic realPG E2E PASS: known recent debt READY,
cold-history skipped, tenant isolation, read-only; production business writes0,
source requests0. Все Python modules retained worker3462 совпадают с gate/source.
7activation simulations и readonly live preflight PASS; exact host-only payload:
`acdfb81ef580901560282ceb967bae283d9d27599e83eb59177a6fbd75eccf20`.
Меняется только scripts/server-eis-223-refresh.py, до approval НЕ установлен.
Worker/API/WEB/DB/schema/compose/cron сохраняются, restart/migrations нет.
Evidence: tmp/eis-223-dispatch-20261022-v26/handoff-current.json, acceptance.json,
activation-plan.json, fullgate-summary.json и runtime-parity-proof.json.
После exact approval — atomic install под прежним lease, ordinary223 и real
source/window/audit verification. Старый history fallback при отсутствии recent
work сохранён; национальная полнота и устойчивый lag по-прежнему UNKNOWN.
R1 live44: к14:51UTC за21Oct30SYNCED+30NO_DATA attempts и398новых редакций;
это observed progress, не доказательство полноты дня. Evidence: R1 post-install-counts.json
и live-installed-proof.json. R3 source errors/throughput/UI остаются backlog.


## R1b установлен — 22 октября20:18МСК

Exact approved payloadacdfb81e установлен20:18:21МСК под штатным lease,
operation90f64f77-ec44-4c19-80b0-8925333c610a. Заменён только host223 Python,
SHA bdb9d3d8. API/WEB/DB IDs, worker3462, schema20261021_01, compose и cron
сохранены; health и два tenant activation audit events PASS. Установленный
readonly probe READY1,96s; urgent current work. Это не source intake result.
Evidence: tmp/eis-223-dispatch-20261022-v26/activation-audit.json и
installed-readonly-proof.json. Ожидается ordinary22320:25МСК; не применять повторно.
Прежний dispatch мог проходить при других входных данных: до установки штатный
22317:15UTC также работал. Причинность/устойчивое ускорение этим не доказаны.
Readonly triage с14:25UTC:4ARCHIVE_RESOURCE_LIMIT attempts/2distinct windows,
2WINDOW_BYTES_LIMIT attempts/1window; source intake limits не ослаблены.
Эти ошибки относятся к R3, не к точечному dispatch payload.


R1b ordinary verification завершена22Oct20:29МСК: scheduled dispatch20:25:01,
worker20:25:03–20:28:07 с mounted exact host bdb9d3d8, image3462,3GiB/3CPU,
regional/reconciliation opt-in1 и OOMfalse. Попыток25:9SYNCED/16NO_DATA/0FAILED;
160новых редакций,0events,34sourcePOST/10archiveGET. Все25исходов совпали с
persisted tenant attempts и audit,9SYNCED с exact response checkpoints; два
activation audit events с approved SHA/operation совпали. Health/config/container/
schema/cron/compose invariants после завершения PASS. Stop PRIORITY_REFRESH_REQUESTED,
184s lease,0budget overrun. Lane MANDATORY: это bounded штатный intake PASS,
не доказательство post-install RECONCILIATION lane, sustained acceleration или
национальной полноты. NO_DATA не canonical. Прежние3resource-failed окна не закрыты.
Evidence: tmp/eis-223-dispatch-20261022-v26/live-installed-proof.json,
ordinary223-run.json, ordinary-db-audit-proof.json, post-ordinary-health-proof.json.
Следующий срез R3 source/resource/attachment errors; затем throughput/UI freshness.


## R3 — три resource-failed окна223, 22 октября

Ownerroot, isolated candidate tmp/eis-223-archive-recovery-20261022-v27/candidate;
root backend/web сохранены. Контракт — ADR0112. Original incoming source sets
retained:77/19Oct/AESMBO117XML,77/20Oct/general459XML,78/19Oct/general76XML.
Два XML4511001B/9471478B превышают4MiB, compressed33840461B превышает32MiB.
Полный diagnostic652XML выявил дополнительный cap:5874positions против5000.
Candidate notice-only12MiB/XML,40MiB/window,6000positions; остальные caps прежние.
Capture6POST/8GET, business DB writes0, existing lease/budget/pacing сохранены.
Capture1 helper positional signature mismatch:0POST/0GET,0business writes; исправлен
keyword call, failed evidence сохранён. Focused PG first runner s209 корректно
отклонён exact s176 guard; runner исправлен,6PGPASS. Первый retained ingest
остановился NOTICE_COLLECTION_LIMIT; после полного XML census scope дополнен
6000positions и negative/boundary/provenance tests. Это не production PASS.
Unit144PASS; retained pipeline, memory proof/full gate и установка ещё требуются.
Evidence: capture-summary.json, collection-diagnostic.json, scope.json в R3 tmp.


R3 готов к exact approval22Oct21:22МСК. Sourcec9bfdbc8/treea80c5355,
manifest62c66fb8; gate release-20261022-180131-5196df3df8e1:50/50PASS,
unit3828PASS/27allowedSKIP,PG711/Node199/doctest9PASS, cleanup complete.
Новый worker e2e2e209, ровно2changed modules:archive reader/window limits;
остальные modules byteexact относительно installed3462. API6b/WEB949 retained.
Accepted image actual full652XML/3windows isolatedPG ingest+replay/tenant PASS,
12,586s, Chromium same cgroup, peak498298880B (~475MiB) при3221225472B, OOMfalse.
Retained API6b прочитал652snapshots/max5874positions. Native exact recovery helper
проверен на отдельной DB:3windows/652versions/3SYNCED attempts+6audit rows;
replay0newversions, hash/missingapproval guards0writes, tenant isolation PASS,
peak395476992B, OOMfalse. Raw original sources/complete UID binding сохранены.
Production readonly precompare21:21МСК:147same/505missing/0immutable conflicts.
Readonly activation preflight PASS, production business writes0. Exact payload:
`8764ff9dcc8d80009645caeaf83e5182f028e888693aea48e0e1924a2e3da72a`.
План включает2worker image compose replacements, затем3точных retained source sets
under original lease; source requests0, API/WEB/DB IDs/schema/cron/host223 сохранены.
Admission manifest4ca3ede9 связывает652records и все original reply/ZIP SHA.
Изменения конфигурации откатываются поCAS при installation failure. После начала
admission immutable committed windows не удаляются: recovery interruption даёт
INCOMPLETE для reconciliation, не полный PASS.7two-file activation simulations PASS.
Production НЕ установлен,3failed windows ещё не закрыты. После exact approval —
live checkpoint/source/SYNCED/audit и version readback, затем ordinary new worker.
Evidence:tmp/eis-223-archive-recovery-20261022-v27/handoff-current.json,
acceptance.json, activation-plan.json, image-e2e-proof.json, recovery-helper-proof.json.
Другие44source failures, sustained throughput и UI freshness остаются backlog.
Национальная полнота и PARTICIPATE UNKNOWN.


## R3 установлен и три окна закрыты — 22 октября21:43МСК

Подтверждённый payload8764ff9d применён21:41:19МСК, operation
52bd5e1d-f855-4889-89f7-f46519a4b999. Worker e2e2e209; API6b/WEB949/DB IDs,
schema20261021_01, host223bdb9, cron и все resource/pacing caps кроме ADR0112 сохранены.
Source requests0: восстановлены exact retained full sets с capture22Oct20:50МСК.
77/19Oct/AESMBO117records/9new;77/20Oct/general459/458new;78/19Oct/general76/38new.
Production independent readonly readback PASS:3exact initial/prepared/manifest
checkpoints,3latestSYNCED с checkpoint responseSHA,6source-window+attempt audit
и3activation audit events по approvedSHA/opID. Все652records XML SHA совпали,
8ZIP blobs hash(content) совпали,505new/147previous versions сохранены.
Большое notice5874positions и последний provenance не обрезаны.6старых failed
attempts сохранены неизменными; исправление добавляет новые SYNCED, не правит историю.
После recovery health/config/container/schema/cron/host223 invariants PASS.
Evidence:tmp/eis-223-archive-recovery-20261022-v27/live-installed-proof.json,
live-db-audit-proof.json, post-recovery-health-proof.json, activation-audit.json.
Root backend/web существующая работа сохранена; source checkpoint/patch отдельно.
Это bounded recovery3windows, не ordinary cron/new full national completeness.
R3 повторно не применять. Далее оставшиеся44 expansion/attachment-reference errors,
затем sustained throughput/UI freshness; M5 и PARTICIPATE UNKNOWN.

### R4 — 26 окон44 восстановлены (22 октября)

Ownerroot. По exact approval payload
`b359e8d9f104ccf54c8e7bc19862c83da623631d51de9760ebb94d7f4f3e95fe`
установлены API/worker ab3b9686, operation69221888-f847-4eca-896f-fcbc9b12075d,
22Oct23:38МСК. WEB/DB контейнеры, schema20261021_01, cron, host223 и бюджеты сохранены.
Контракт — [ADR0113](../../adr/0113-bounded-44-source-references.md).

Final sourcefd7f2fc/a4b99fd3: gate50/50PASS(3862unit/27SKIP,714PG,199Node).
Actual-image26/26 ingest/replay/checkpoints/audit/tenant PASS; API4544typed
snapshots/auth/UNKNOWN aliases PASS, max907positions. Worker сChromium
peak824336384B/3GiB, API333967360B/1GiB; final recovery helper999beac8
2iterations/negative approval/tenant guards PASS, peak752312320B/3GiB.
SQLcompare128-key batches сохраняет timeout5s после воспроизведённого timeout
одного4544-key запроса; критерии immutable conflict и DB<100GiB не ослаблены.

Production readback PASS:26/26 latestSYNCED и canonical checkpoints,
52/52source audits,3/3activation audits;62/62ZIP content SHA + prepared SHA/URL,
4544/4544unique XML SHA из4577occurrences.3105new/1439existing;
26старыхFAILED сохранены без изменения actor/reason/time/NULLsourceSHA.
В unique версиях21alias metadata (23occurrences в наборах),8закупок/10UNKNOWN
ссылок. Document status сохраняет UNKNOWN и ATTACHMENT_REFERENCE_REQUIRES_REVIEW;
автоматический download/cache/analysis/review не получает допуск.
Health/config/schema/cron/host223 PASS, DB20764441623B; source requests0 на
activation и readback. Национальная полнота и sustained freshness UNKNOWN.

Evidence: `tmp/eis-44-archive-recovery-20261022-v28/live-installed-proof.json`,
`activation-audit.json`, `activation-execute.log`, `handoff-current.json`.
Штатный cron23:42МСК наблюдён на imageab3b9686,3GiB/3CPU, exit0:
60окон,7SYNCED/53NO_DATA,96new,0failed;60journal/audit и7canonical checkpoints
с provenance сверены в рабочей базе. Turn PARTIAL: очередь не исчерпана, freshness
UNKNOWN. LiveHTTP10requests: auth/largest907positions/8UNKNOWNaliases PASS.
Evidence: `ordinary-cron-proof.json`, `live-api-proof.json`, `acceptance.json`
в том же каталоге. План не применять повторно. Следующий шаг — sustained throughput
и UI freshness; новые ошибки исследовать отдельным bounded slice.


### R5/R6 — ссылки вложений и старые range-отказы (23 октября)

Ownerroot. Scope/evidence: `tmp/eis-attachment-followup-20261023-v29/` и
`tmp/eis-range-recovery-20261023-v30/`. Production code, API/worker imageab3b9686,
WEB, schema20261021_01, runtime configuration и контейнеры сохранены.
Это operational slice по установленному parser/source contract, а не новый release.

**R5: диагноз всех10 references.** Они относятся к8историческим закупкам и8unique
URL. Полные source XML/архивные SHA сверены с immutable версиями. Один UID/URL/size
опубликован в разных docKindInfo и под разными именами: MRJ/CP/POD/FPD.
Все варианты сохранены; выбор достоверного имени/назначения не сделан.
7unique files скачаны безопасным существующим public transport под import lock
и shared cooldown;26991139B, размеры и SHA проверены. Это9references, поскольку
2файла повторяются в разных закупках. Один XLSX28865235B превышает20971520B:
source GET для него не выполнялся, его доступность/содержимое не подтверждены.
Нельзя объявлять все10 «исправленными» или снимать UNKNOWN ролей по совпадению URL.
Canonical document receipts/analyses не добавлялись, deployed ADR0113 guards
сохранены. Все8сохранённых deadlines истекли; это не действующие рекомендации.
Evidence: inventory.json, source-labels.json, reference-summary.json,
notice-current-status.json в R5. Исходные PDF/XLSX оставлены только на сервере.

**R5/R6: закрыты27 legacy range failures.** Текущий parser уже сохраняет
неподдержанные range shapes как UNKNOWN с исходным XML provenance. Сначала3окна:
02/28Aug/EF107records,16/28Aug/EF119,17/28Aug/EZK9; затем оставшиеся24/2018records.
Обе партии прошли actual-image isolated ingest/replay/checkpoints/audit/tenant;
peak282046464B и448471040B <3GiB сChromium, OOMfalse, external source0 в тесте.
Native APIs не менялись, повторный full release gate не запускался.
Все полные source sets вновь bound по initial/prepared requests/URL/ZIP SHA.
Предварительное сравнение с production:235+2018missing/0conflicts. Внутренний
intake выполнен по текущему запросу пользователя через installed APIs, под
существующим import lock, с прежними SQL5s/DB100GiB/disk40GiB guards;
новых внешних или юридически значимых write actions нет.

Production23Oct08:21/08:31МСК: operation07f53166-d6ad-47bf-9118-1591b15cbebd и
5b1605fc-de6f-408c-9ce3-f6922e3ff72e, actors operator-r5-current-parser-recovery и
operator-r6-current-parser-recovery.2253new/2253typed snapshots,27latestSYNCED и
canonical checkpoints,54source audit events,40archive content SHA/preparedSHA/URL,
2253XML SHA PASS.27исходных FAILED rows сохранены с прежними time/actor/reason и
NULLsourceSHA; заднего заполнения нет.543range values остаются UNKNOWN,
range_source_complete false; metadata intake не даёт technical/compliance PASS.
Health/config/containers/schema/cron/host223 PASS. Live HTTP: новый largest539positions
и прежняя UNKNOWN attachment карточка200, anonymous401; corpus_coverage UNKNOWN.
Evidence: next-live-proof.json, operation-before.json, operation-intake.json,
isolated-run.log, readback.log в R6; первые3 — next-readback.log в R5.

**Оставшаяся очередь.** Readonly RR census использует1000-key pages и128-key
version comparisons; SQLtimeout5s не повышен. Старый монолитный gap report
вернул OperationalError при5s guard; точный SQLSTATE не сохранён, причина UNKNOWN.
Bounded census296551targets/297batches выполнен за10,75s; maxstatement0,053s.
После intake повторный snapshot:28346canonical/268205pending,149551unattempted,
118432NO_DATA,206FAILED и16SERVICE_ERROR. Range-failed group0. Общий прирост
completed69 включает concurrent cron; только27точных окон приписаны R5/R6.
NO_DATA не означает отсутствующую закупку или доказанную полноту.

Отдельно current223 wave22–23Oct:900planned/900attempted,271SYNCED/629NO_DATA,
failed0,90regions terminal,old_gaps0,source_day_lag0,scope COMPLETE.
Это EXACT_PLANNED_SCOPE_ONLY по5семействам, country coverage/freshness UNKNOWN.
Evidence: R5/coverage223.json, R6/post-census.json.
Следующие bounded operations —143SOURCE_TRANSPORT_FAILED и16SERVICE_ERROR,
затем8MEMBER_UNSUPPORTED/5DUPLICATE_ARCHIVE и variant/source-contract review.
Ни конфликтующие версии, ни неизвестные вложения не превращаются в PASS ради полноты.
Итоговая сводка с hashes proof-файлов: R6/acceptance.json; live-api-proof.json и
final-runtime-proof.json. Свободный диск >=40GiB, тестовые контейнеры очищены.


### R7 —143 транспортных и16 сервисных ошибок (23 октября, проверено)

Ownerroot; exact scope и передача: `tmp/eis-transient-recovery-20261023-v31/`.
Baseline23Oct09:18МСК:159latest pending targets,143FAILED с exact
SOURCE_TRANSPORT_FAILED и16SERVICE_ERROR. Все старше24h, canonical checkpoint0.
145часовых/14суточных координат проверены existing date/hour parser; исходная
наблюдательская проверка date-only parser пометила hourly неподдержанными,
затем corrected classification сохранена в targets.json без изменения старых rows.
Reserved historical clause ADR0065 использует date-only key grammar. Текущий
mandatory freshness отсекает старые hourly после своей границы; изменение этой
scheduler policy не входит в текущую операцию, новый код не установлен.

Данный запрос пользователя авторизует конечный internal recovery этих159окон.
Private driver вызывает installed sync_eis_window и EisSyncJournal, проверяет
exact latest attempt ID/отсутствие canonical completion/24h cooldown перед каждым
источником; fixed target digest, existing import lock/priority/regional hints,
joint budget с reserve223, max12окон/turn,90s start/180s atomic, worker3GiB/3CPU,
DB<100GiB/disk>=40GiB/SQL5s. Между партиями lock освобождается. Фонового расписания
не добавлено; external writes/юридически значимых действий нет.

Canary2hour windows01/9Oct/21h EF+Cancel вернули NO_DATA. Raw SOAP replies в
существующем bounded evidence store проверены native verify_no_data_reply;
2source evidence audits+2sync audits и2immutable oldFAILED PASS, checkpoints0.
Пустой source reply не создаёт fake canonical intake и не доказывает отсутствие
закупок в ЕИС. Proof:canary-readback.json, canary.log.
Private v1 добавлял2s между windows сверх native2s before POST/GET; после
наблюдения двойной паузы driver приведён к native freshness pacing. Оригинал
retry-targets-v1-extra-pause.py сохранён, BrowserTransport и его pauses неизменны.

Основной finite driver завершился: canary+14turns,159/159точных окон проверены.
23Oct09:25–09:50МСК, actor operator-r7-transient-recovery:2SYNCED/157NO_DATA,
ошибок0.143исходных FAILED →2SYNCED/141NO_DATA;16SERVICE_ERROR →16NO_DATA.
Только2окна получили canonical checkpoints:23/6Aug/EZK91records и24/6Aug/EF169.
Всего260newversions/0events,3архива. Все archive bytes и260XML SHA повторно
проверены по persisted source; journal latest ID/responseSHA/checkpoint manifestSHA/
preparedSHA/official URL привязки сверены. Новые карточки видны в live API и
возвращают правильный XML SHA и EIS notice URL; anonymous401, authenticated200.

157NO_DATA исходных SOAP replies проверены native verify_no_data_reply по
retained SQLite/overflow manifests и SHA;157source evidence audits+159attempt
audits+2window ingest audits=318verified events. Все159исходных rows, включая
actor/time/reason/source SHA, сохранены неизменно. Для157NO_DATA canonical
checkpoint отсутствует; новых versions/events из пустых ответов0.
Это действительный результат source retry, не доказательство отсутствия закупок.

145hourly targets сопоставлены с26daily keys:12имеют canonical checkpoint,
все26—post-day-cutoff terminal observation. Это readonly corroboration:
суточный источник не выдаётся за загруженный часовой архив. Auto historical
hour retry policy не менялась. Runtime/API/worker images/config/schema/cron/
host223 и main containers сохранены, health PASS; free44937887744B >40GiB.
Общая скорость/бюджетsource не повышены; source2s pacing, existing lock, native
priority/regional hints и joint protected223 share соблюдены. Полный release gate
не повторялся: product code/deployment changes0, slice проверен canary/live evidence.

Final RR census297001planned:28447canonical/268554pending,149401unattempted,
119090NO_DATA и63FAILED; SOURCE_TRANSPORT_FAILED/SERVICE_ERROR groups0.
Остаток:41DUPLICATE_NOTICE_VERSION,8MEMBER_UNSUPPORTED,5DUPLICATE_ARCHIVE,
3NOTICE_VERSION_CONFLICT,3DUPLICATE_NOTICE_VERSION_IN_WINDOW,2SOURCE_RESPONSE_REJECTED,
1PREPARED_REQUEST_MISMATCH. Concurrent planning/cron добавляли свою работу;
только159exact outcomes и2checkpoints/260newversions приписаны R7.

Evidence: acceptance.json, live-readback.json, outcomes.jsonl, turns.jsonl,
canary-readback.json, daily-counterparts.json, post-census.json, api-proof.json,
runtime-before.json/runtime-after.json в R7 tmp; hashes приведены в acceptance.
Следующий bounded slice —8MEMBER_UNSUPPORTED/5DUPLICATE_ARCHIVE с полными
источниками, затем variant/source-contract review. Полнота страны и sustained
freshness остаются UNKNOWN. R7 не запускать повторно по старому baseline.
