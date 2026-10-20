> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

### S210 — сравнение записанных характеристик выбранной пары, завершено 2026-10-05UTC

Owner root: new storage/eis_characteristic_compare.py, API route app.py,
new API/isolated PG tests, docs93/docs15/docs28/docsREADME, ignored gates/release
helpers. Sol owns only new sources/eis_characteristic_compare.py and its pure
unit tests; Astra read-only high-risk review. No overlapping edits.
Dependencies: S209 backend/S207web, existing stored lot_items and optional
eis-position-v2-concrete projection; no source access or schema changes.
Acceptance: at most two exact selected saved positions, single read-only RR,
tenant/hold/SHA checks, byte limits before JSONB hydration and bounded output.
Source fields/projection read without ZIP parsing or new jobs; missing old
concrete-values schema remains UNKNOWN. Match unique normalized names only,
explicit complete values/instructions/units. Observation SAME/DIFFERENT/UNKNOWN
does not close technical/overall comparability, delivery, profit or participation.
Ranges, duplicate names, truncation, differing/missing units and legacy shapes
stay UNKNOWN. Exact Decimal and every nested provenance/ref validated. Focused
pure/API/PG gates, installed same-ref read/negative/ops checks, pinned backend
overlay with rollback. S211 will expose this on-demand pair report in analog UI.

Evidence:259isolatedPG/unit/APItests PASS33.30s/zero skips,20focusedlocaltests/
Ruff/mypy PASS; Astra range-raw/truncation blocker fixed with4regressions and
review closed. Exact refs/holds/RLS/bytes/digest/legacy recovery/no writes covered.
Deploy20:57:42UTC atomic10/host101/API21/worker21hashes PASS, S207web unchanged.
Six installed HTTP/direct fixed-clock identities PASS:12/4/3rows, allUNKNOWN
due to missing legacy concrete-values schema. HTTP77–240ms/direct75–168ms;
six authorization/ref/position negatives PASS. No production projection job or
source call. Ops20:57:57UTC DB5051554839/free257278357504/testDB0/head01/health200/
markersfalse; caps/cron/source budgets unchanged. Pins/proofs: docs93.

S210 docs seal20:58:49UTC atomic4/host101/API21/worker21/web14hashes PASS;
pins/cron/resources PASS, API/web running/OOMfalse; backupSHA
`793bdffca9d6119fa23908cb0b0e5e3d202bf8465cb02090cd2c86972df165c8`.

### S211 — сравнение характеристик в интерфейсе, завершено 2026-10-06MSK

Owner root: new characteristic-pair panel/view, historical-analog report/wrapper,
actions/procurement-api adapters, analog test configuration, docs94/docs15/docs28/
README and ignored build/release helpers. Sol owns only new web/lib
eis-characteristics.ts and tests/eis-characteristics.test.ts (strict wire
validation); Astra independent read-only review. Dependencies: deployed S210
API/S207web. Acceptance: on-demand exact position pair, no eager fetch, no extra
document/source jobs. Strict response binding/provenance/counts/bounds, stale
response invalidation on changed selection, source facts/raw values and reasons
visible, recorded SAME/DIFFERENT separate from all technical/profit UNKNOWN.
Typed boundary, relevant Node/TS/ESLint/production build and installed Server
Action/SSR positive/negative checks. Web-only pinned rollout/rollback; backend/
schema/caps/cron/source budgets unchanged. Browser visual is a separate check.

Evidence:10characteristic+9analog+8protocol Node tests/TypeScript/ESLint/build
PASS; pinned isolated2CPU2GiB/networknone. Astra enum/name/index/whitespace
findings fixed/regressions PASS, review closed. Deploy21:11:17UTC
atomic16/host109/web21hashes PASS; S210backend unchanged. Installed Next Action+
SSR21:11:41UTC6reads88–195ms/12,4,3UNKNOWN rows,5negativeerrors PASS;
live analog1387ms/104buttons after ordinary ingestion changed saved candidates.
No eager row calls/browser visual claim. Ops21:11:42UTC DB5085035543/
free257155776512/testDB0/head01/health200/223markertrue ordinary activity;
caps/cron/source budgets unchanged. Pins/proofs/rollback: docs94.

S211 docs seal21:15:50UTC atomic4/host109/API21/worker21/web21 hashes PASS;
images/cron/resources PASS, backupSHA
`4b75d03094db975eea4b8f63dc457d8583c6aefcdaa8a1a6544e4de1d3d9416c`.

### S212 — восстановление выбранных legacy-характеристик, завершено 2026-10-06MSK

Owner root: ignored bounded operational helpers, docs95/docs15/docs28/README.
Astra independent read-only review. Runtime files/schema/images unchanged.
Dependencies: S210 saved pair reader, S211 interface, existing explicit
`project_notice_positions` and retained archives. Two deduplicated candidate
refs from three verified pairs; metadata preflight PASS, archives241712/637549
bytes. Acceptance: <=2 exact tenant-scoped immutable projections with matching
audit, source holds/archive/XML digests checked, canonical rows unchanged;
replay creates no projection/audit. Installed API and UI reads prefer saved
projection and show original values with provenance. Source0/no global backfill;
technical/profit/participation/coverage remain UNKNOWN. Existing worker2CPU/2GiB
and short import lease; no new source budgets, cron or dependency changes.

Evidence:21:18:52UTC two projections/two audit events, unchanged canonical row
digests, replayfalse/no writes PASS. API/direct6same-clock identities27–150/
77–167ms,6negatives PASS; candidateSAVED_PROJECTION/legacyfalse. Next Action+
SSR6reads86–199ms,5negatives PASS; analog797ms/104buttons. 12/4/3UNKNOWN rows:
unmatched names/incomplete shapes, ranges deliberately unsupported.
Ops21:19:06UTC DB5087009815/free257170878464/head01/testDB0/health200/markersfalse.
Source0, no archives downloaded to laptop. Details/proofs: docs95.

S212 docs seal21:24:17UTC atomic4/host110/API21/worker21/web21 hashes PASS,
images/caps/cron PASS, backupSHA
`f3c63bf43271f027bcae4239f29288897b1beda0d2bb1cfb3f962a279b5a14c3`.

### S213 — исходные границы и записанные диапазоны, завершено 2026-10-06MSK

Owner root: storage/eis_position_projection.py and eis_characteristic_compare.py,
integration tests, UI report/fixture/tests, API/Web coordinated release, ADR/docs.
Sol owns sources/eis_feed_archive.py, eis_position_evidence.py,
eis_characteristic_compare.py and their three pure unit test files; then separate
sequential wire contract slice web/lib/eis-characteristics.ts and its test file.
Astra read-only architecture/high-risk review. No overlapping edits.
Dependencies S210/S211/S212. Acceptance: retain bound raw text and explicit source
completeness; new immutable projection parser version, old v2 stays readable but
cannot establish one-sided range completeness. Prefer new verified projection,
no fallback after corruption. Equal exact complete ranges with explicit same
instructions/units give recorded SAME, different ranges DIFFERENT; malformed,
unknown operators, reversed/empty ranges, mixed shapes, truncation/legacy remain
UNKNOWN. All fulltechnical/profit/participation/coverage UNKNOWN, no containment
or unit conversion. Two-sided and one-sided signed/zero Decimal regressions,
exact source holds/SHA/RLS/limits/replay, installed API/UI comparisons. Explicit
bounded recovery of selected refs only; no archive reads in comparison requests.

Evidence:336isolatedPG/unit/APItests PASS36.60s/zero skips;83focusedsource tests,
13characteristic+9analog+8protocol Node/TS/ESLint/build PASS. Astra review closed.
Web-first21:39:13UTC atomic5/host111/web22; oldAPIcompat6SSRreads/5negativePASS.
Backend21:40:01UTC atomic14/host118/API23/worker23 PASS; no schema/deps/cap/cron
change. Five selected retained v3 projections/five audit rows21:43:09UTC,
canonicalunchanged/replayfalse/countsunchanged. Import lease busy60s yielded
without writes, bounded300s retry succeeded. Installed6API/directidentities
26–114/78–178ms,6negatives PASS. Pair2oneSAME recordedrange500>=, otherfields
UNKNOWN; pair3externalSid unsupportedmetadata remainsUNKNOWN. Initialprobe
pair3SAME assertion corrected after exactXMLinspection, no policy relaxation.
NextAction+SSR6reads92–182ms/5negatives PASS, analog925ms/104buttons.
Ops21:45:16UTC DB5092580375/free257084674048/head01/testDB0/health200/markersfalse.
Fulltechnical/profit/participation/coverageUNKNOWN. Pins/proofs/rollback: docs96.

### Порядок дальнейшей работы, уточнён 2026-10-06

Owner root: docs15/docs96 и документационная запись в docs28. Acceptance:
прайс пользователя является необязательным дополнительным источником; развитие
ЕИС и поиск поставщиков продолжаются по продуктовому плану. Наличие цен и КП
остаётся условием достоверной экономики, а получение этих данных — задачей
самой системы. Зависимости: PRD3.2–3.4 и Supplier Discovery/RFQ/Quote Analyzer.

1. Продолжить ЕИС: дополнительные XML-формы (externalSid), извлечение полного
   ТЗ и адресов/сроков поставки с позиционной связью, измерение полноты и свежести
   национального корпуса. Наличие пользовательского прайса этот этап не ограничивает.
2. Отдельный этап Supplier Discovery: построить поисковые запросы по требованиям
   закупки, искать производителей/дистрибьюторов/оптовиков в интернете и каталогах,
   сохранять источники, время, характеристики, контакты, публичные цены и условия.
   Существующий `/supplier-discovery` содержит ограниченные адаптеры категорий и
   реестров; это основа для развития, а не готовый универсальный поиск поставщиков.
3. Сопоставить найденные товары с точной спецификацией и количеством. Публичная
   цена остаётся наблюдением: НДС, наличие, MOQ, срок и доставка неизвестны, пока
   не подтверждены источником. Предварительную оценку маркировать отдельно.
4. Подготовить адресные RFQ и запросы КП из shortlist. По PRD3.3/AGENTS любой
   исходящий запрос требует exact-payload approval; автоматический поиск и
   подготовка черновиков могут выполняться внутри системы. Полученное КП разобрать
   с ценой/НДС/сроком действия/доставкой/оплатой/гарантией и provenance.
5. После получения действительного полного КП считать расходы и сценарии
   base/realistic/conservative, сравнивать прибыль и риски, применять hard gates.
   Без полного подтверждённого входа прибыль/участие UNKNOWN.

Ручной прайс/КП пользователя может ускорить проверку кейса, но система должна
уметь сама искать источники закупочной цены и готовить получение КП. Предыдущая
запись об ожидании прайса как следующем блокере заменена этим порядком.

### S214 — числовые характеристики с externalSid, завершено 2026-10-06

Owner root: storage/eis_position_projection.py, storage/eis_characteristic_compare.py,
tests/integration/test_eis_characteristic_ranges_pg.py, docs15/docs28/docs97/README,
ADR0086 и ограниченные release/verification helpers. Sol owns only
sources/eis_feed_archive.py and tests/test_eis_feed_archive.py; Astra read-only
contract review. Dependencies: installed S213, retained exact selected XML.
Acceptance: optional nonblank scalar externalSid accepted only as metadata;
duplicates/attributes/nested/mixed/unknown shapes remain incomplete. New immutable
parser revision r1 preferred over original v3 then v2; v3 flags preserved, v2 cannot
claim source completeness. Corrupt preferred projection never falls back.
Recover only target 0348200080326000021 v1 from its retained archive after metadata
size/digest/hold preflight, one projection/audit, no canonical changes, replay0.
Bounded PG/unit/API regressions and installed API/Next Action/SSR comparisons.
No source HTTP or global backfill; fulltechnical/profit/participation/coverage
remain UNKNOWN. Then measure current coverage/freshness to choose the next slice.

Evidence:95 local/346 isolatedPG tests PASS38.57s, Ruff/review PASS. Deploy05:23:36UTC
atomic10/host119/API23/worker23 PASS, web unchanged. Single retained r1 projection/
audit05:23:53UTC, canonical/oldprojection digests unchanged, replay0. Six API/direct
identities81–243/83–177ms, six negatives PASS; pair3oneSAME+2UNKNOWN.
Six NextAction/SSR87–183ms/five negatives PASS. Analog regression BLOCKED:
unchanged analog module hits ANALOG_NOTICE_PAYLOAD_LIMIT after ordinary intake.
Ops05:26:09UTC DB5479963671/free252146888704/head01/testDB0/health200/markersfalse.
National completed03–05October:1485 planned/attempted,352canonical,1106NO_DATA,
27range-structureFAILED;4905versions/4905lexical. No full coverage claim.
Proofs/images/rollback: docs97.

Immediate priorities from measured failures: (1) unsupported characteristic shape
must not reject all cards in an otherwise valid archive; keep ambiguous fields UNKNOWN,
immutable parser revision, preserved XML provenance. (2) oversized analog candidate
must not disable the whole valid query; retain strict memory limits and report omissions.
(3) exact cached TSpec/delivery review preparation and binding to reviewed requirements,
then supplier discovery. Sequential bounded slices with appropriate tests/deployment.

### S215 — изоляция неподдерживаемых диапазонов при загрузке, завершено 2026-10-06

Owner root: storage/eis_position_projection.py, integration range tests,
sources/eis_position_evidence.py and its unit tests (conservative position gate),
storage/eis_gap_status.py and its unit test, docs15/docs28/docs98/README/ADR0086,
bounded release/verification helpers. Sol owns only sources/eis_feed_archive.py
and tests/test_eis_feed_archive.py; Astra read-only review. Dependencies: sealed
S214, observed27 failed completed-day windows. Acceptance: unsupported/ambiguous
range structure yields no asserted bound and source completeness false; valid
notice/archive metadata can be retained, without converting UNKNOWN to SAME/PASS.
Explicit source ambiguity survives in the cached source model and makes the
position characteristic status UNKNOWN, including mixed descriptions/concrete
values. No new wire fields or synthetic raw-bound sentinels.
New immutable r2 projection identity; r1/v3/v2 remain readable in order, old flags
preserved and corrupt preferred rows blocked. Exact legacy error classified as
PARSER_REVIEW. Unit/mixed-archive/PG/API gates, installed comparison regression;
bounded offline source probe if retained bytes exist. No increased budgets or
whole-corpus backfill. Observe remaining source failures separately; analog limit
fix follows as its own slice.

Evidence:142local/398isolatedPG tests PASS38.94s/zero skips, Ruff/Astra review PASS.
Deploy05:39:48UTC atomic13/host122/API24/worker24, web/schema/caps/cron unchanged.
One controlled real retry11.171s:2SOAP/2GET,2ZIP/1622611bytes,123newversions.
Frozen old parser fails on same bytes; old27attempts immutable. Independent RO
verification123versions=123lexical,1ambiguousnotice, canonical/journal/audit PASS.
Six installed API/direct and NextAction/SSR comparisons/negative gates PASS;
analog remains BLOCKED pending S216. OpsDB5498280983/free252101967872/head01/
testDB0/health200/markersfalse. Other26oldfailures not yet recovered.
Proofs/pins/rollback: [docs98](../../eis/search/98-eis-ambiguous-range-intake.md).

### S216 — ограниченная выдача аналогов при крупных карточках, завершено 2026-10-06

Owner Sol: sources/eis_analogs.py, storage/eis_analogs.py, tests/test_eis_analogs.py,
tests/integration/test_eis_analogs_pg.py and new bounded omission PG tests if needed.
Owner root: web/lib/eis-analogs.ts, historical-analog-report.tsx, related wire/render
tests, API test if required, ADR/docs and coordinated release helpers. Astra
read-only contract review. Dependencies: sealed S215 before deployment; independent
implementation may proceed while source leases are busy, without overlapping edits.
Acceptance: fixed first20 metadata refs plus21st sentinel, no refill/unbounded scan;
oversized target remains hard error. Candidates exceeding per-notice/remaining total
byte budget are omitted before hydration, with exact refs, typed reason and storage
size evidence; later smaller candidates can fit. Omission never equals EXCLUDED/FAIL,
position count UNKNOWN. Original predicates/order/holds/RLS/bounds/source0 preserved.
Versioned report policy, web-first dual compatibility, visible omission count/reasons
and honest empty-result wording. Real installed frozen-paper queries and negative
gates. Other integrity failures still reject, not silently skipped.

Evidence:409isolatedPG tests PASS41.56s/zero skips; Node13characteristic/11analog/
8protocol/TS/ESLint/build/Ruff/mypy/review PASS. Web-first05:50:29UTC atomic3/
oldAPIcompat sixSSRreads/five negatives; backend05:54:09UTC atomic9/host124/API24/
worker24. Three realqueries now19admitted/1omitted/142positions, HTTP1147–1297ms,
direct1134–1214ms,6same-clock identities,SQLomitted-not-hydrated/eight negatives.
NextAction+SSR threequeries1205–1312ms with visible omitted refs/reasons/UNKNOWN;
six characteristicreads/five negatives PASS. No browser visual claim. OpsDB5508307991/
free252010950656/head01/testDB0/health200/markersfalse; budgets unchanged.
Proofs/pins/rollback: [docs99](../../eis/search/99-eis-analog-payload-omissions.md).

### S217 — ограниченное восстановление ошибок прежнего парсера, исследование 2026-10-06

Owner root: docs15 и последующий выбранный bounded slice; Astra read-only
selector/lease/journal review, без изменений кода до фиксации контракта.
Зависимости: S215 exact same-source old/new proof; S216 завершить до выпуска.
Acceptance исследования: определить, как восстановить оставшиеся прежние
CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED failures в существующем бюджете,
без retry всех parser failures, переписывания journal и повторения canonical.
Учитывать exact latest attempt, tenant, completed dates, source holds,
cooldown/attempt limit и leases. Результат — один обоснованный механизм и
проверяемый ограниченный контракт. Full coverage остаётся UNKNOWN.

Исследование05:52:54UTC: штатный selector already admits recent latest FAILED
после24h; PARSER_REVIEW — категория отчётности, не блокировка очереди.
Exact27cohort:1canonical/26remaining, ни одно оставшееся окно ещё не прошло
cooldown; selector60 выбрал0изcohort. Первые due21:46UTC06October, последние
00:39UTC07October. Добавление новой lane сейчас не обосновано. Recovery не
объявлена завершённой; повтор выполняет существующий cron в прежнем бюджете.
Read-only proof SHA256e8a8a8397543b685ff01e94d3cdc47e14fb2dd929604297400cd9a64e9c24862.

