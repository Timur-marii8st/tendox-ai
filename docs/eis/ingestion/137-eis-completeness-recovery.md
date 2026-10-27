# V49 — полнота ЕИС и сверка сайта

Root, 26Oct2026; в работе, национальная полнота UNKNOWN.
Evidence `tmp/eis-completeness-20261026-v49/`. Зависимости: установленный V48,
[coverage120](120-eis-national-coverage.md), [active sweep](../search/129-eis-active-sweep.md).

Первый продуктовый результат: официальный missing→canonical intake→main search
и видимая карточка сайта, без ослабления source/currentness/UNKNOWN gates.
Owned files, проверки и границы — `slice.json`. Пользователь поручил долго
работать над полнотой/скоростью; standing instruction исключает повторные
вопросы о разрешении. Exact owner plans/review/audit сохраняются.

## Сегодняшний baseline

13:51UTC keysetSQL5s: planned44=331336, canonical31576, unattempted153383,
NO_DATA146311, latestFAILED66. Это очередь окон, не число отсутствующих закупок.
66failed:43duplicate-version,8unsupportedmember,5duplicatearchive,3versionconflict,
3duplicate-in-window,2sourcerejected,1transport,1preparedmismatch.
Census12.17s/maxstatement0.093s, source0/business0; `census-before.json`.

13:59UTC native readonly:44=409840номеров/447324версии,223=48960/56915.
Все447324версии44 имеют lexical rows. За24h +6625/+2560редакций соответственно;
это наблюдаемый ingest, не число новых номеров и не source→search lag.
223 wave25–26Oct:900planned/900attempted,202SYNCED/698NO_DATA,failed0,90регионов;
COMPLETE только planned5families, nationalcoverage/freshness UNKNOWN.
`baseline-readonly.json`. Existing44census не содержит223, старый ingestionreport
ставитSQL30s; отдельный bounded native adapter сохраняет SQL5s/read-only.

## Проверка сайта

Public www.syurai.su заблокирован локальным Browser client. Через localhost-only
SSH forward к установленному web выполнен реальный UI поиск «бумага»:
44=1015/223=854совпадения, по100loaded, selected0101200007126000003,
983273.50руб., deadline02Nov06MSK и официальный URL отображаются.
Персональная сессия не создавалась; NO_QUOTE/admissionUNKNOWN сохранены.
`ui-baseline.json`. Прямой HTTP не выдаётся за UI проверку.

## Независимая официальная выборка

Exact9dda49a2:8queryfree active pages,4per44/223,50cards/page,once180s,
1440sceiling, expiry16:58UTC. Existing54min/hour, public60s cooldown,TLS,
global/dispatchlocks,SQL5s,DB100GiB/disk40GiB,worker3GiB/3CPU сохранены.
Discovery только audit/budget/raw, без ledger admission/кода/schema/cron.
30policytests/bash-n/independent reviewPASS; actual preflightREADY/source0.
Standing ownerdecision записан; сбор начат. Source страницы сохраняются
неизменённо с URL/SHA/time; consumed/uncertain requests не повторяются.
Снимок первых страниц не доказывает полноту страны.

## Подтверждённые пропуски и пересмотр подхода

Первые2страницы PASS, следующие2 — UNKNOWN/BROWSER_REQUEST_FAILED, все4claims
прочитаны обратно. После двух последовательных отказов навигационный подход
остановлен; индексы4–7(223) не запрашивались. Retained100строк дают59разных IDs:
подвижная выдача не является неизменным100-record snapshot. Повторы исключены.
Existing strict parser подтвердил filters/50cards/0unparsed на каждой странице.
`discovery-method-reassessment.json`, `observed-candidates.json`.

Все50номеров первой страницы отсутствовали и в versions/lexical, и в actual
mainHTTP ALL_CACHED. Проверка каждого номера стоила7.28–8.60s, median7.44s,
в сумме373.31s. Соседние чтения выполнялись в разное время, не единый RR snapshot;
source→search lag из этого не выводится. `compare-first-page-before.json`.

Canary exactec6f8ce1 (supersedes38e37b12 доsource):
0818300019926000257/ea20 once180s, preflight/reviewPASS, 21policytestsPASS.
14:31:46UTC existingrecover_one/sync_eis_number:0→1notice/1lexical, auditRECORDED,
fullZIP15e52386/XMLfbdf68fe, archive/source/immutableREQUESTED прочитаны обратно.
ActualmainHTTP200; реальный UI1результат,2598767.83руб.,03Nov09MSK,42позиции,
4ссылки на документы совпадают. Personalaccess не создавался, admissionUNKNOWN.
`recovery/canary-result.json`, `readback.json`, `ui-canary-proof.json`.
Независимая итоговая приёмка PASS; `recovery/acceptance.json`. Полнота страны UNKNOWN.

Исходный XML опубликован14:01:36UTC; адресный intake14:31:46UTC. Это один
замер, не национальный SLA. Штатный oneHourInfo выбирает start старше2h05m
(ADR0044/installedeis_freshness.py), поэтому currenthour ещё не eligible;
раннее отсутствие этой закупки не доказывает постоянный дефект загрузчика.

Следующий boundedexact0efe86cb: оставшиеся58фиксированных разныхномеров из
техже2страниц, последовательные chunksдо8, одинimmutableclaim/номер,
передsource повторное чтение canonicalpresence; alreadyindexed пропускается.
Source0 новыхpublicpages, existing54min/h+44/223reserves/leases/resources.
Два последовательных UNKNOWN/sourcefail останавливают подход для разбора.
21tests/bash-n/independentreviewPASS, actualpreflightREADY/source0; выполнение начато.
Evidence `wave/`; images/schema/hostscripts/cron неизменны.

Первый wave проход:4SYNCED, затем urgentIDLE/jointBLOCKED доsource для
0366200035626006838. Claims readback: ровно4, уblocked0; laterprobeREADY.
Transientcause UNKNOWN; `wave/guard-reassessment.json`, blockedreceipt сохранён.
Продолжение допускает только unattempted номера с повторным nativeguard.
Первым4 fullZIP/XML/window/lexical/audit readbackPASS; ноутбуки0372100002426000009
actualUI1result/367317.18руб./6шт/06Nov08MSK/4links PASS.

Nativecapacity14:46UTC:2000metric cap,1999completed/1failed, p95=5492.224ms.
С pacing2s conservative288slots/h против450latesthour/900twohourpoll;
recent/peakbudgetfitFAIL, feasibilityUNKNOWN; не benchmark устойчивого throughput.
450region×family groups:403unattempted/5284due; NO_DATA не отсутствие закупок.
`freshness-readonly.json`. Inventory13старых MEMBER_UNSUPPORTED/DUPLICATE_ARCHIVE:
0storedwindows/0retentionaudits; cachedreparse без исходников невозможен.
`failed-source-inventory.json`; потребуется отдельный exactsourcecapture.

15:25UTC checkpoint: wave37SYNCED/5ALREADY_INDEXED, source0guardstops2 и
1consumedSOURCE_TRANSPORT_FAILED(0190200000326012327) с auditRECORDED/0canonical.
Послеfailure30штатных native sourceboundSYNCED/NO_DATA подтвердили работу канала;
повтор номера запрещён, продолжены толькоunattempted20..57. Перенос междуchunks
не сбрасывает failure boundary без явного reassessment; `transport-readonly.json`.
NativefullZIP/XML/audit readback11+13+12 PASS, ещё6проверяются.
ActualUI37/37 PASS (включая3раннихproofs); exactnumber/title/amount/MSKdeadline/
EISURL/UNKNOWN. Keyword«газообразным гелием»: target0349100021126000461 первый
из61loaded, selectedcard/officialURL PASS. `wave/ui-batch-*.json`, `ui-keyword-helium.json`.

## Итог адресной выборки и следующий срез

15:36UTC: PARTIAL58/59, `wave/acceptance-partial.json`; independentreview
PASS_PARTIAL_EVIDENCE_REVIEW. 46адресныхSYNCED(включаяcanary),12подхваченыnative;
все58 fullZIP/XML/source/audit и поштучныйactualUI number/title/Decimalamount/
MSKdeadline/EISURL/UNKNOWN подтверждены. Wave46immutableclaims=45SYNCED+1failure;
source0guardstops2 сверены и исполненыonce, consumedsource retries0.
0190200000326012327 остаётся0canonical/0UI, SOURCE_TRANSPORT_FAILED/auditRECORDED.
Никакогоall59PASS/национальногоPASS нет; runtime/health/schema/cron/ownedcleanup PASS.

Следующий root срез: полнота лекарственных позиций. ReadonlySQL5s export6ZIP/XML,
source0, SHAverified:37…848(12),33…224(10),34…221/35…155/17…468/84…913(по1) =
26drugPurchaseObjectInfo; у всех26 явноеname,22quantityUndefined,4количественные.
Installed `_lot_items` читает толькоnotDrugbranch и вернул0. Evidence
`drug-diagnosis/diagnosis-summary.json`, `source/source-proof.json`.
Сначала независимый architecture review совместимости: canonicalparsed snapshots
immutable; простой новый parser не исправляет старыеrows и может сломать replay.
Нужно типизированное provenance, UNKNOWN без предположений о дозах/упаковках;
полнотаТЗ/КП/PARTICIPATE не принимается. Продуктовыйкод этого среза ещё не менялся.
