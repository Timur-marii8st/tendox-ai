> Исторический снимок плана до реорганизации 2026-10-06. Статусы и NEXT
> отражают момент записи; текущая задача — в [live-плане](../../15-implementation-plan.md).
> Содержимое и evidence сохранены; локальные ссылки перенесены механически.

### S189 — национальные завершённые даты пяти families и очередь без starvation, проверка завершена

Milestone1 owner Sol: ignored s189-feasibility.py, read-only VPS evidence.
Owner Astra: new docs/adr/0070-eis-national-daily-scheduling.md, архитектура и review.
Owner root: docs15/28, new docs/eis/ingestion/72-eis-national-daily-scheduling.md, docs/nav,
ignored deployment/gate/live/operations helpers. Owned files не пересекаются.
Dependencies: S188 exact queue/actual24h data, S187 runtime/HEAD20261004_03,
существующие date selection и parser EF/EZK/EOK/Cancel/CancelFailure contracts.

M1: сравнить national rolling hourly (495newwindows/hour) с national daily
five-family completed-date scope (495newwindows/day, bootstrap3days=1485keys).
Существующие priority24/240s/300cadence и corpus60/900cadence, общий import lease,
223/document interruptions и отсутствующие walltime metrics учитывать явно.
Read-only overlay отсутствующих EOK daily keys; ordered candidate dry-run,
данные последнего24h отдельно по actor/outcome/firstcanonical. Не выдавать
потолки slots/h или three-region p95 за SLA и не обещать размер всей базы.
Выбор cadence до runtime edits; source0/DBwrites0 для feasibility.

M2 после review M1: назначить runtime owner/files и точный bounded selection
contract. Предпочтительный slice — EOK в национальном daily plan и явная
защита старого backlog при добавлении последних дат; source admission unchanged.
Миграции, CPU/memory/disk caps, source concurrency и cron frequency не расширять.
Acceptance: finite durable keys, tenant/latest/canonical/cooldown predicates,
Moscow completed dates, no reset/delete pending на rollover, bounded limit,
хотя бы один старый backlog key при eligible backlog и selection limit>=2.
PG day rollover/latest/cross-tenant/idempotentplan/fairness regressions, runtime
lint/types/isolatedPG; actual stage dry-run, review перед backup/hash rollout.
После rollout только один bounded live verification pass (до3 windows) с
exact attempts/sourceSHA/canonical или NO_DATA/partial/HOLD verification;
UNKNOWN не превращать в completeness. Финальные hashes/HEAD/ops/docs обязательны.

S189 M1 PASS: DAILY5 выбран;19:42:50UTC snapshot13.635s, source0/writes0.
1485expected=1197planned+288missingEOK; existing9EOK=7canonical+2NO_DATA.
Pure NULL-attempt overlay first60newEOK/zero historical; exact oldselector60Sep6.
Joint source capacity/SLA UNKNOWN; corpus run не имеет240s wall-cap.
ADR0070 final contract принят до edits.
M2 owner Sol, owned ONLY src/procurement/sources/eis_corpus.py,
scripts/server-eis-corpus-daily.sh, tests/integration/test_eis_corpus_fairness_pg.py,
tests/test_eis_corpus.py (если требуется контрактом). Root/Astra эти files не меняют.
Activation limit>=2 +recent unattempted completed dates+eligible ordinary historical
anchor; anchor excludes transient retry predicate. First anchor, second recent;
ceil40% recent-unattempted hardcap while ordinaryolder backlog remains;
workconserving overflow после исчерпания. Existing retrycaps, exactold fallback,
oneRO RR, finite SELECTs/no fullqueue materialization. Daily addsEOK only.
Verification PG rollover/cooldown/ties/RLS/limit1/2/60/no duplicates/read-only/
idempotentplanning; stage selector/EXPLAIN, independentreview before rollout.
Live до3 STANDARDselected windows с history+EOK, no selector override.

S189 M2 amendment BEFORE internal queue writes: repeated overlay EXPLAIN выявил
искажение cardinality synthetic CTE (ordinary estimate1–3 vs actual136k),
NestedLoop на full latest/canonical sets; overlay timeout не считается actual
production latency. После PG34PASS и semanticreview разрешён finite EOK
bootstrap (до297 durable internal targetkeys, exactscope/audits/idempotence,
source0), затем staged REAL-table selector/EXPLAIN под sharedlease до runtime
rollout. Root owns ignored s189-bootstrap.py/.sh + proof. Existing targets и
attempts не меняются. Если selector gate не пройдёт, code rollout не выполняется;
добавленные желательные EOK targets сохраняются как pending, без ложного coverage.

S189 actual bootstrap20:09:56UTC PASS:288missingEOK persisted,1485/1485scope,
repeat0, exact288planningaudits; targets148273→148561. Proof SHA
2e66414796babe98a25f6ebae28109e9a76e34a524738f70cdddf1a89bb7a2f8.
Actual selector confirms normalfill cardinalityestimate1 and expensive nestedloop
against complete latest/canonical sets as well; runtime rollout still blocked by
performance gate. Sol owns narrow fairhelper repair: hashed canonical exclusion
and indexed latest attempt LATERAL LIMIT1; MAXtime/cooldown/order semantics exact,
oldfallbackunchanged. PG and actual stagedproof rerun before rollout; source0.

S189 final verification owner source_limits: ONLY ignored s189-originals-proof.py
и приватный proof. Read-only exact recheck ранее сохранённых original attempt
rows S184/S185 + releaseproofs. Source0/DBwrites0; missing bytes/rows UNKNOWN,
никаких retries или policy changes. Root docs15/28/72 остаются owned root.

S189 result04.10.2026: daily5 EF/EZK/EOK/Cancel/CancelFailure deployed;
99candidatecodes ×3completedMSKdates =1485planned. Bootstrap288EOK added,
repeat0/exact288audits, scopecoverageUNKNOWN. Conditional firsthistorical +
secondrecent/new40%hardcap, fallbackexactold, latestindexedLATERAL+nonnullsets.
PG35PASS (14integration+21unit), Ruff/mypy/bashsyntax/semanticreviewPASS.
After two queryshape iterations, actual RR55358:55358 selector3/60 took
8.592/19.406s;60=35historical+24newEOK+1recentFAILED, unique/capverified.
Это overhead measurements, не SLA/не speedup; source0/writes0 дляSELECTproof.

Rollout: codebackup20:15:58UTC, APIworkerbuild/APIup/webunchanged;
host13/API1/web3/worker1hashPASS HEAD20261004_03, no migration/budget/cadencechanges.
One standard max3livepass20:16:51–20:17:26UTC actually3:old81Sep6CancelFailure,
new06/07Oct3EOK. AllNO_DATA/exactsourceSHA+attemptaudits/canonicalfalse/versions0;
PARTIALreasonNULL means boundedpass, not completeEIS. liveadded0/repeat0.
Selectedoldattempts0 is vacuous; independentrecheck50distinct recordedS184/S185
originals allfieldsunchanged/missing0/mismatch0, не entirejournalstatement.
APIhealth200/auth401/defaultpaper828matches100returned3.727s/no-storeUNKNOWN.
Ops20:19:04UTC DB3821181975/free262449061888/testDBnone/markersfalse/OOMfalse,
API/webcaps1GiB/768MiB unchanged;sourcearchives remainVPS.
ExactproofsSHA/backups/runtimecost/limitations — docs72/ADR0070.
Finaldocs runtime/script/web/worker hash synchronization gate before turn closes.

NextS190: comparable timestamped importlease wait/work metrics for corpus,
priority/document workers alongside223, one bounded observation cycle and
jointcapacity/queue-age estimates. Current-day national99×5hourly remains
UNVERIFIED; daily5 doesnot prove fullEIS/allformats/documents/freshness/profit.
No newsource/resourceconcurrency/cadence contract before measuredcapacityreview.

### S190 — сопоставимые метрики общего import lease, завершён bounded slice

Owner Astra: ONLY new docs/adr/0071-eis-shared-lease-observability.md,
контракт и independent architecture/release review.
Owner Sol: ONLY scripts/server-eis-metrics.sh, scripts/server-eis-metrics.py,
scripts/server-eis-corpus.sh, scripts/server-eis-priority.sh,
scripts/server-eis-documents.sh, scripts/server-eis-223-refresh.sh,
tests/test_eis_worker_metrics.py, tests/test_eis_source_leases_shell.py.
Owner source_limits: ONLY ignored s190-baseline.py/s190-observation.py и приватные
read-only proof files на VPS; baseline/observation без source requests/DBwrites.
Owner root: docs15/28, new docs/operations/73-eis-shared-lease-observability.md, docs/nav,
ignored package/stage/gate/deploy/ops helpers. Owned files не пересекаются.
Dependencies S189 deployed daily5/HEAD03, existing flock/dispatch/marker guards,
current source/CPU/memory/disk caps and cron unchanged.

M1: precise common timestamped metric contract до edits. Tenant/actor/run UUID,
whitelisted lane/operation/phase, aware UTC clock и monotonic duration;
source calls/unknown data не выводить из timing. Separate bounded JSONL (не
менять worker stdout), no raw worker payload/cmdline/env/URL/token, <=16MiB retention.
Cover IDLE/probe/error/busy/timeout/signal paths, failure logging does not change
worker exit/lock/marker behavior. Incomplete/censored intervals remain UNKNOWN.
M2 focused Linux stub tests/source0 incl success/idle/busy/timeout/TERM/cleanup,
no foreign marker delete/no waiter leak, no metric-secret spill, bounded retention,
independentreview + backup/hash script-only rollout; API/web/query/schema unchanged.
M3 one >=15minute bounded observation of ordinary cron (no extra source dispatch,
no resets/queue deletion), actual sharedwork/wait/censoring/provenance and RO
queue-age census; capacity sample is not national SLA. Final hashes/ops/docs.

S190 ownership continuation: subagents stopped after their implementation/review
due to unavailable quota; root owns remaining fixes/gates/observation and their
formerly owned files from this point. No concurrent editors. Astra reviewed
runtime/logger/deployment and observer corrections before stopping. Linux gate
found priority marker/TERM trap race; traps now installed before marker touch,
restricted to import wait and restored after acquisition. Recheck pending.

S190 M2 gates: Linux network-disabled source-free stubs54PASS05:38:31UTC5Oct;
observer14syntheticchecksPASS incl horizon/terminalonce/FIFO/boundedread,
Ruff/compile/bashsyntaxPASS. Astra runtime/logger/deployreviewPASS; observer
corrections applied. Script-onlybackup/hashrollout and15mordinarycron pending.

S190 deployed05:39:57UTC5Oct: helpersfirst/atomic14files,host20hashPASS,
codebackupSHA d0019725e9646bff357ff9f6b75e20cf36d64074ddd86cfb96744de205352b21.
Linux54PASS, observer15checksPASS, Ruff/compile/bashsyntax/Linux-platformmypyPASS.
Ordinarycron05:40:32–05:55:47UTC915s:21runs complete21/censored0/inconsistent0;
corpus1/priority3/documents15/223two. Heldlowerboundunion557.018s, notutilization.
Waitknown3sum5.797s/max5.731s,workknown3sum556.587s;18IDLE noimport/workphases.
CorpusnonzeroexitERROR operational only; lateststdoutREGIONAL_REFRESH_REQUESTED
cooperativeyield, exactstdout↔metric bindingUNKNOWN. Source/parserfaultnotproven.
FinalRR/RO05:55:55:planned149065/canonical5487/pending143578/unattempted135507/
NO_DATA8046. RecentOct2–4expected1485/planned1092/missing393 (297EF+96EOK),
priority50/77/78105planned/due0. Manualhelperssource0/DBwrites0;
backgroundordinarycron continued. ProofSHA/limits — docs73/ADR0071.
NextS191 retryableidempotentdaily5planning/exactkeys/rollover before sourcecapacity
expansion. FullEIS/nationalcurrentdaySLA/profitUNKNOWN. Finalhash/ops/docssync gate.

S190 finalgate06:02:18UTC:host20/API2hashPASS/unchangedAPIwebimages+workerprefix,
HEAD03/health200/OOMfalse/caps1GiB768MiB;DB3942718487/free258988384256bytes,
testDBnone. Regionalmarkertrue ordinarycronactive, noreset. OpsproofSHA
f58b35d18a1f7e0c7643af0eced87e4606330b4a709761a4edb7cf1250ee1a59.
CronSHA d20580264560d4bb8e733172a907d39c6b92aeb6fd4c418182e2390c2c88ef88.
Receiptadditions includedinfinaldocs-onlyhashseal;runtimecode frozenafter54PASS.

### S191 — durable daily5 planning retry, завершён bounded slice

Owner root (existing subagents unavailable): ONLY scripts/server-eis-corpus-daily.sh,
new scripts/server-eis-corpus-plan-state.py, tests/test_eis_corpus_planner.py,
docs15/28/73correction/new74, ADR0072 and nav; ignored stage/deploy/proof helpers.
Acceptance: busy/failed/invalid output never advances cursor; exact successful
scope digest/expected keys required; repeat completed scope source0/newtargets0;
recover interruption between31-target batches; catch up after >3day downtime
in <=3day chunks without dropping older dates. Existing attempts remain unchanged.
Initial floor2026-10-02 from S190 evidenced gap; older five-family gaps UNKNOWN.
Keep import lease/source/resource gates and worker2CPU/2GiB. Retry planner only
at minutes4-59/5 (source-free plan), skip on completed cursor; source cron unchanged.
M1 contract; M2 Linux source-free gates; M3 backup/hash/cadence-only rollout,
controlled source0 planning/exact1485 keys/96 actual gap repair/repeat0 and RO evidence.

S191 correction: S190recent393invalidmanualEFsuffix ->297falsegaps; actual96EOK
missing beforelive. Originalrecentproofsubcounts withdrawn/MISKEYED_SCOPE,
globalcounts/lease timingunaffected. Correctedreader usesdomainfactory; reconstructed
planned_at at bothS190cutoffs1389planned/96missing/EF297present. Docs73corrected.
74LinuxPASS source0/networknone, Ruff/Linuxmypy/bashsyntaxPASS.
Script-onlydeploy06:20:28, host20hashPASS06:21:06, backupSHAe6d2cb8b4bc944ef94608d958e792c791e042f4e2fbfa1e28243122e3d5d4220.
Source0controlledpartial31batch6newtargets, realwrapper90remaining, exact1485/
gap0/96exactaudits;15982oldattempts+1389oldtargetsfullrowSHAunchanged;
duplicateCLInew0/cachedIDLE. Cronexact1plannerentry every5min at4-59/5,
sourceentriesunchanged. Corrected06:26:48census1485planned/374canonical/
1015NO_DATA/96unattempted; sourcecompletenessUNKNOWN. Proofs — docs74/ADR0072.

S191 final gate 06:37:20 UTC: host21/API2 hashes PASS, runtime2scripts+test
equal Linux74-gated stage; API/web images and worker12charprefix unchanged,
HEAD03/health200/OOMfalse/API1GiB/web768MiB. DB3945159703/free258990403584bytes,
testDBnone/priority223markersfalse. RO ops proof SHA
f5feef4ce59a58ccfc5d06323fa1154b88c2f6dba3f2d9624fc1a1cb0a519f89;
cron hash unchanged after S191 planner-only cadence update. Receipt additions
included in final docs-only hash seal. Next bounded slice: measure actual recent
source ingestion, canonical completion and queue age before concurrency changes.

### S192 — измерение прохождения свежих окон в индекс, завершён bounded slice

Owner root: scripts/server-eis-ingestion-report.py, scripts/server-eis-ingestion-report.sh,
tests/test_eis_ingestion_report.py, docs/operations/75-eis-recent-ingestion-report.md,
docs15/28/navigation, ADR0073; ignored packaging/read-only proof helpers.
Dependencies: S191 durable planner, existing domain scope factory, tenant RLS,
canonical window receipts, notice versions/search keys and procedure events.
Acceptance: bounded completed-date scope <=3days×99candidatecodes×5families;
one tenant repeatable-read/read-only snapshot; exact domain keys including legacy EF;
disjoint window states; NO_DATA/transport-only never canonical; actual version↔search
key parity separately from source completeness; aware age/provenance and safe metadata.
Synthetic regression gates + two ordinary-cron snapshots of the same cohort,
show actual transition counts and limitations. No source dispatch, migration,
queue reset, permission/concurrency/budget change. Source/coverage/freshness UNKNOWN.

S192:27 regression tests PASS Windows/Linux (Linux networknone,2CPU2GiB);
Ruff/mypy/bashsyntax PASS. Atomic9 script-only rollout06:53:46UTC,
host23/API2 hashes PASS/cron unchanged; backupSHA
c01fdd4bac4cf5ad02ba40f46032afa055c74571505e15c1673dbfef5d96ab6c.
Same scope2–4Oct exact1485 keys 06:49:46–07:05:40UTC954s:
374->375canonical,1046->1069NO_DATA,65->41unattempted,
6487->6488versions/lexicalrows,events177unchanged.24 first attempts:
23NO_DATA/1canonical,regressions0. No manualsource dispatch; diagnosticDBwrites0.
Lease23runs/21complete/2censored, capacity UNKNOWN. Docs75/ADR0073 bind receipts.
NextS193: reduce fresh first-attempt age without starving history or changing
source/resource gates; separately verify bounded NO_DATA retries under existing
policy. Current-day national hourly scope/fullEIS/documents/profit remain UNKNOWN.

S192 finalops07:07:59UTC host23/API2hashPASS/unchangedAPIwebimages+workerprefix,
HEAD03/health200/OOMfalse/API1GiBweb768MiB. DB3970284567/free258939768832bytes,
testDBnone/prioritymarkertrueordinarycron, noforcedcleanup. OpsSHA
e1bb4ded2779fc576e8f9c8c71bc0bd10ba014519ca14e0b95ddded53c09ebad.
Finaldocs-only hashseal includes receipt additions; runtime frozenafter27LinuxPASS.

### S193 — первая обработка свежих окон, завершён bounded selection slice

Owner root: src/procurement/sources/eis_corpus.py,
tests/test_eis_corpus.py, tests/integration/test_eis_corpus_fairness_pg.py,
docs76/ADR0074/docs15/28/navigation; ignored release/gate/proof helpers.
Dependencies: S192 exact cohort report, S189 daily queue and current source gates.
Acceptance: active daily lane changes new-window quota40%->60% (24->36 of60),
keeps old anchor first and new window second, interleaves remaining3new/2other
only with a retry prefix, otherwise preserves fast prefix; within-lane order stays;
recent repair<=12/historical transient<=3,
unique selected keys/limit and legacy fallback when no activation unchanged.
PG tenant/latest/cooldown/canonical/readonly gates, pure prefix tests,
backup/runtime-image hash rollout and live selector/cohort evidence.
No extra source pass/concurrency/cadence/migration or NO_DATA policy change.
Capacity/national hourly freshness/fullEIS remain UNKNOWN. NO_DATA verification
is deferred to a separate bounded slice; this slice changes selection only.

S193 M2:41PASS (27unit/14PG) isolatedtestDB07:22:26UTC/Ruff/mypyPASS,
production schema unchanged/testDBremoved/sourcecredentialsunset forpytest.
Unconditional interleave rejected aftershadowprefix5->4; conditionalprefix fixed,
finalsameRRshadow07:21:38 old24->new36fresh/first6=5->5/oldanchorunchanged.
ShadowSHA ddb38d9df6b6f95c05dd8eeec1fb11f602a6f676d4b7d79a32205f0a3aa8892a.
Deploy07:24:16 atomic9/host25/API2/worker2hashPASS, pinnedonemoduleoverlay,
APIhealth200,webunchanged/HEAD03/cronunchanged. CodebackupSHA
7f7cdf0fc2be88139bbbe5b53040ac459455bc70546cddb5ccd0ff3efca2d753.
Before07:24:11cohortOct2–4:375canonical/1089NO_DATA/21unattempted,
6488versions/6488lexicalrows; ordinarycron observation completed below. Limits/sourcepolicy unchanged.

S193 ordinarycron967s07:24:11–07:40:18UTC:8firstattempts(allNO_DATA),
21->13unattempted,canonical375/index6488unchanged/regressions0.
SeparateoverlapOct1–3 sample840s has0progress; don'tsum overlappingcounts.
Journal9records=1Sep4old+8Oct4new, all actorserver-corpus-worker/NO_DATA.
Lease21complete/0censored/0inconsistent; observedheldlowerbound202.36181s.
LatestcorpusstdoutREGIONAL_REFRESH_REQUESTED/attempted9of60, exactmetricbindingUNKNOWN.
Selectionquota36verified, throughputgain/notional1.5xspeedupUNVERIFIED.
NextS194: bounded continuation aftercooperativeyield within ORIGINAL60-window
budget and a bounded time horizon, preserving leases/markers/source/CPU/memory/disk
and other lanes; no additional periodic source pass. NO_DATAverify separate.
FullEIS/currentdaynationalhourlyfreshness/capacity/profitUNKNOWN. Receipts — docs76.

S193 final07:42:19UTC:host25/API2/worker2hashPASS/releaseAPIworkerIDsverified,
webimageunchanged/HEAD03/health200/OOMfalse/API1GiBweb768MiB;
DB3970808855/free258912776192bytes/testDBnone. Regionalmarkertrueordinarycron,
notouchedforeignmarkers. OpsSHA6b67bcfecaa254d03866071afabeeb0b71b9807f7cfd18e3d132e2cde680f407.
Finaldocs-onlyhashseal includesreceipts; runtimefrozenafter41PASS.

### S194 — продолжение после cooperative yield, завершён bounded slice

Owner root, owned scripts/server-eis-corpus.sh, новый scripts/server-eis-corpus-run.py,
tests/test_eis_corpus_continuation.py, tests/test_eis_worker_metrics.py,
docs77/ADR0075/docs15/28/navigation. Existing agents unavailable; root implementation
and self-review, no independent review claim.
Dependencies: S193 worker contract, S190 segment metrics, existing source leases.
Acceptance: один parent dispatch, максимум исходные60 окон суммарно, не более6
segments, start/wait horizon840s (не прерывает in-flight atomic window).
Continue only exact validated BLOCKED + exit2 + priority/regional requested;
all attempts including NO_DATA/failed consume budget. Resource/source failures,
malformed output and cancellation stop. Release import lease while waiting,
priority/regional dispatch owners finish before reacquisition; foreign markers
untouched, duplicate corpus parent rejected. Each segment has own metrics UUID;
tenant-scoped bounded parent receipts bind outputSHA/counters/segment UUID.
Linux process tests use real flock and fake Docker without network; script-only
atomic VPS rollout, unchanged images/cron/resources, ordinary cron observation.
No national completeness or throughput claim without evidence.

S194 M2:95Linux process/unit tests PASS08:13:43UTC (networknone,2CPU2GiB),
Ruff/mypy--platformlinux/bashsyntaxPASS. Frozen runtime after finalgates.
Atomic10 script/docs/test rollout08:14:14UTC,host28hashPASS, API/worker/web image
IDs and cron unchanged,HEAD03/health200. CodebackupSHA
d393d9df41412f4b658271ec0943bed77629f10863acb6db1f726f280a495e85.
First ordinary cron parent08:15:01:13attempts thenpriorityyield; continuation
with47budget started08:18:22;26attempts thenregionalyield; known total39.
Interim receipt+metric bindings PASS bothsegments, remaining21; historical interim
observation, final completed below.
Completed Oct2–4baseline08:14:05 already375canonical/1110NO_DATA/0unattempted,
6488versions/index,events177. Maincohort changes alone cannot measure Oct1/history.

S194 ordinary parent completed08:27:08UTC in726.332s:3segments budgets60/47/21,
attempts13/26/21=60, two cooperativeyields, PASS_FINISHED/workerPARTIAL/coverageUNKNOWN.
Journal60records matches: Oct1=36 (11SYNCED/25NO_DATA), Sep4=24 (18SYNCED/6NO_DATA).
Source stdout exactSHA bindings:29SYNCED/31NO_DATA,+563versions/+14events;
read-only exact60-window + parentinterval projection gate563versions=563lexicalrows.
MainOct2–4cohort917s unchanged/regressions0; progress belongs to Oct1/history.
Lease22complete/0censored/0inconsistent; threecorpusmetricbindingsPASS,
heldlowerboundunion724.641s acrosslanes, notcapacity/SLA. No manualsourcepass.
Private receipts/hashes and limitations in docs77. Source/fullEIS/hourlyfreshness UNKNOWN.
NextS195: bounded verification of NO_DATA retry/evidence under existing24h policy;
do not convert sourceempty into canonical completeness or increase sourcebudget.

S194 final08:32:59UTC host28/API2/worker2hashPASS/images+cronunchanged/HEAD03,
health200/testDBnone/OOMfalse/API1GiBweb768MiB;
DB3997506583/free258867539968bytes/bothmarkersfalse/noforeigncleanup.
OpsSHA90f127620d9c92f6d1214b2e5d679bfdd56967ddcd4902f2873ce28e653cfdd4.
Finaldocs-onlyseal includesoperationalreceipts; runtimefrozenafter95PASS.

### S195 — bounded повторная проверка NO_DATA, завершён selector/recheck slice

Owner root: src/procurement/sources/eis_corpus.py,
tests/integration/test_eis_corpus_fairness_pg.py, docs78/ADR0076/docs15/28/navigation;
ignored source-free census/shadow/release/proof helpers. Existing agents unavailable;
implementation and self-review by root, no independent review claim.
Dependencies: S194 shared60budget/continuation, S193 selector, latest journal evidence.
Baseline tenant RR/read-only08:40:31UTC:1807recentNO_DATA,1148due>=24h,
selected due0of60; all due have sourceSHA, oldestSep29. CensusSHA
6bf1ac0dc9934b25090ced9b553f298c7f5ebf937c3f5d52c56d488faf5f3a6b.
Acceptance: reserve<=ceil(limit/20),max3,inside existing repair quota<=12;
only latest NO_DATA, valid sourceSHA, completed MSK dates in last7days,
age>=24h, exact planned key, no canonical receipt, same tenant. Failures retain
remaining repair capacity and use all unused slots; historical retries<=3,
daily new36/oldanchor/unique60/legacy limit1 unchanged. oldest recheck first.
NO_DATA remains UNKNOWN, successful recheck must be proven by canonical receipt
and index parity. PG tenant/latest/tie/cooldown/boundary/canonical/sourceproof/read-only
gates, one-snapshot old/candidate comparison, pinned one-module rollout, ordinary
cron receipts showing actual prior NO_DATA transitions. No extra source pass,
source concurrency/24h cooldown/cadence/resource changes or migration.

S19553tests PASS08:54:16UTC (27unit/26PG),isolatedtestDBremoved,
sourcecredentialsunset duringpytest; production schemaunchanged. Ruff/mypyPASS.
SameRRshadow08:52:32UTC:old0/candidate3dueNO_DATA,60uniquechoices unchanged,
dailynewlane inactive onlive snapshot; original9/28–9/29 retries displaced only
3historicalfirstattempts. SQLold11.932s/candidate12.046s, no speed/SLAclaim.
ShadowSHAde987ecb5835e80e5b73d8834a0c12d3cc310debbe2b57e5f95fa7fb9a04efa8.
Pinnedone-module API/worker rollout08:56:53UTC atomic8/host28/API2/worker2hashPASS,
web/cron/HEAD03 unchanged; worker2CPU2GiB/API1GiB. CodebackupSHA
c177db13a4d08e0399b7ddada9aa8c62ff8baee96170c56191167819dec4fd26.
Predeploybaseline08:56:47UTC exact1148duekeys withpriorattemptID/time/sourceSHA,
privatebaselineSHA449f1c4a616aaa5cd0507e34b49c5bb78ca6225aee99e739732f5ed79e976860.
Ordinarycron09:00firstsegment:3rechecks observed09:01:30;6acrosstwosegments at
09:04:16. AllNO_DATA,6newattemptIDs/sourceSHA,6cooldownresets,0canonical,
0versions/index/events. TypedROproofSHA
b34c998ef99a30543faf346a9598d852dc5497797299ace897b0a751714cdbf7.
Reservation<=3 is persegment, not entireparent; S194total60budget remains strict.
Parentstillactive atthissnapshot; no terminalparent/throughput assertion.
No manualsourcepass/diagnosticDBwrites/sourcecalls. FullEIS/freshness/absenceUNKNOWN.
NextS196: inspect independent source evidence and due-backlog age across completed
dates, including windows leaving7day reserve; do not equate repeatempty with absence.

S195 final09:07:38UTC host28/API2/worker2hashPASS/S195imagesverified,
web+cronunchanged/HEAD03/health200/testDBnone/OOMfalse/API1GiBweb768MiB;
DB4049787927/free258790928384bytes. Ordinary prioritymarkertrue/noforeigncleanup.
OpsSHAac66f846226cc567130975b625547ef7021114d4aaeb655a6571da3ca06aa2dc.
Finaldocs-onlyseal includesopsreceipt; runtime frozenafter53PASS.

### S196 — возраст и границы доказательств NO_DATA, завершён diagnostic slice

Owner root; owned files: scripts/server-eis-no-data-report.py/.sh,
tests/test_eis_no_data_report.py, docs79/ADR0077/docs15/28/navigation;
ignored packaging/release helpers. Dependencies: S195 selector/latest journal,
S192 read-only snapshot conventions. Agents unavailable; root self-review.
Acceptance: bounded <=90 completed MSK dates, tenant-scoped latest attempt before
outcome filtering, exact planned date keys, canonical receipt exclusion; aggregate
NO_DATA by day/type, 24h cooldown and membership of 7day reserve, <=20 oldest
evidence samples. Missing SHA/future times fail closed. Read-only RR, SQL30s,
zero source calls/DB writes; immutable private proof <=1MiB, no XML/token output.
Tests cover boundaries/latest/tenant/canonical distinction and typed count parity.
Host-only diagnostic rollout with checksums; ordinary cron/resources/images unchanged.
Repeated NO_DATA/hash does not prove absence; source-response body retention and
independent source corroboration remain UNKNOWN. Census must quantify older due
windows before changing historical reserve policy.

S196 tests54PASS11:25:35UTC on isolated PG, Ruff/mypyPASS. Candidate snapshot
11:27:13UTC/90completedMSKdates/131cohorts:7341NO_DATA=1096recentdue+4399olderdue+
1846cooldown; oldestdueage623326s. ProofSHA
7f23c4855776dc854f6eb7d9d1ce256f1d166f28d3c4833d90d855a5cdcf4aca.
4399olderdue are outside recent reserve, not forbidden in general fill.
Source sync inspection: empty branch returns hash only, raw SOAP not retained by
this branch; independent corroboration/absence/fullEISUNKNOWN. Diagnostic source0,
DBwrites0, source runtime unchanged. NextS197: bounded fair share for older due
NO_DATA inside current total60budget; preserve new intake/repair/transient lanes.

Host-only rollout11:30:58UTC:atomic9/hashPASS, unchangedhost22/API2/worker2PASS,
S195runtime+webimages/cronunchanged,HEAD03/health200/testDBnone/OOMfalse,
DB4294671383/free258531803136bytes. Installedsnapshot11:30:55UTC replacescandidate:
7345NO_DATA=1093recentdue+4404olderdue+1848cooldown,oldestdueage623548s.
ProofSHAd33c2e7ae72348f032623055da6d93791d8af9e6a476b1628261b2049983bfdd.
No manualsourcepass/runtime/schema/cronchange; docs seal preserves frozen runtime.

### S197 — резерв старых NO_DATA, завершён selector/recheck slice

Owner root. Owned: src/procurement/sources/eis_corpus.py,
tests/integration/test_eis_corpus_fairness_pg.py, docs80/ADR0078/docs15/28/navigation;
ignored shadow/baseline/release/proof helpers. Dependencies S196 census/S195
recent reserve/S194 shared60budget. Root implementation/self-review; agents unavailable.
Acceptance: one oldest due older NO_DATA reserved per selector segment for limit>=30;
zero added reserve for limit<30. Latest tenant planned exact date key, valid SHA,
>=24h cooldown, day<todayMSK-7, no canonical receipt. Preserve daily new36/60,
recent3NO_DATA+9FAILED, historical3transients, ordinary old anchor/unique total<=L.
One slot taken from ordinary fill; unused returned. In fallback put older reserve
first; daily interleave makes it early; existing anchor counts if it is olderNO_DATA.
PASS PG eligibility/tie/tenant/date/cooldown/canonical/quota/fallback/reset/read-only,
source-free frozen shadow and pinned module rollout. Actual ordinary cron recheck
must bind prior/new attempt IDs/SHA and canonical/index evidence; NO_DATA UNKNOWN.
No new source pass, source budget/concurrency/cadence/schema/permissions change.

S19766testsPASS11:55:43UTC(27unit/39PG),isolatedtestDBremoved/sourcecredentialsunset,
Ruff/mypyPASS. SameRRshadow11:55:44UTC:60unique, recentempty3unchanged,
olderempty0->1, historicalfirstattempts57->56, dailynewinactive. Query12.294s vs
11.816s background/noSLA. ProofSHA
9bcac99222f5ca049828874f8a24f6de67d11a2e99a93d98983f60c627d44571.

S197 rollout11:58:44UTC atomic8/host28/API2/worker2hashPASS, pinnedone-moduleoverlay,
HEAD03/cronunchanged/S195rollbackimages. BackupSHA
81253e9cde1284bbac012e3ea4dd7d145a26bf7f769c59d58fd6bce8ae530acf.
Predeploy11:58:38UTC typedbaseline60oldestduekeys/IDs/time/SHA (not all4404),
proofSHAfd6b0f3dfa46fd99b3b77b1b359c5bebfd7b5bc85ae9057f0191bbe774157b91.
Real cron transitions pending. No manualsourcepass or source budget changes.

Ordinarycron observed12:01:17UTC:one prior olderNO_DATA rechecked with newattemptID/
validsourceSHA, due>=24h, latestNO_DATA/newcooldown. Canonical0/versions/index/events0.
TypedROproofSHA71a62555c6faf8d7cb29e644d24303d3201da776a45c997bf3eb5e1c91037e97.
No manualsourcepass; diagnostic source0/DB0; no terminalparent/throughputclaim.
Earlier0 and later1snapshots cumulative, not summed. NO_DATA/absence/fullEISUNKNOWN.
Ops12:01:06UTC health200/HEAD03/testDBnone/DB4336122903/free258470707200bytes,
ordinaryregionalmarkertrue/noforeigncleanup; OpsSHA
966cc47c6398a85553ed4c90ee2787a21641e096403ecba2e8168fff0e47ed94.
NextS198: bounded retention of raw NO_DATA reply for reproducible source parsing;
hash/repeat are not independent corroboration or canonical completion.

### S198 — bounded raw NO_DATA retention, завершён evidence slice

Owner root. Owned: src/procurement/sources/eis_no_data_evidence.py,
src/procurement/storage/eis_no_data_evidence.py,
src/procurement/sources/eis_feed_sync.py, tests/test_eis_no_data_evidence.py,
tests/test_eis_feed_sync.py, scripts/server-eis-no-data-evidence-report.py/.sh,
docs81/ADR0079/docs15/28/navigation;
ignored release/offline verification helpers. Dependencies: existing parsed reply,
S197 ordinary source cron/journal/audit schema and persistent browser volume.
Root implementation/self-review; existing agents unavailable.
Acceptance: only matched PROD IP BY_REGION NO_DATA; exact raw SHA/request binding,
no request/token storage, decoded reflection rejection; typed tenant/window/actor
manifest and retention status. Atomic SQLite retention with duplicate replay,
private store0600, reply<=64KiB, global payload<=96MiB/65536records,
DB<=128MiB (rollback journal temporary additional file), bounded lock timeout.
No automatic deletion/eviction. Quota/IO/unsafe response must not promote absence;
NO_DATA remains UNKNOWN, failed retention audited distinctly. No new source calls,
no migrations or budget/cron changes. _parsed_post compatibility for223 preserved;
single-window CLI JSON remains serializable. Tests binding/secret/quotas/rollback/
tenant/replay/tampering/concurrency+sync and isolatedPGaudit; pinned module overlay,
real ordinary cron artifact/offline reparse/audit/journal SHA equality required.

S198: raw NO_DATA retention/audit/offline report implemented. 222Linux/isolatedPG
testsPASS12:31:53UTC, Ruff/mypyPASS; rollout/live evidence pending.
See [docs81](../../eis/ingestion/81-eis-no-data-raw-evidence.md) and [ADR0079](../../adr/0079-eis-no-data-raw-evidence.md).

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

### S199 — operator evidence quota/lifecycle, завершён operator slice

Owner root; owned scripts/server-eis-no-data-store-report.py/.sh,
tests/test_eis_no_data_store_report.py, docs82/ADR0080/docs15/28/navigation;
ignored gate/release helpers. Dependencies S198 immutable store/audit/ordinarycron.
Root implementation/self-review. Acceptance: typed source-free READ ONLY report,
global physical/payload/row headroom, tenant-only age and retention/audit failures,
NO_DATA attempts without matching capture audit remain UNKNOWN. Bounded SQLite
128MiB/65536rows/2s, PG RR/RO/SQL30s/<=7days, <=10 failure samples, proof<=1MiB0600.
Counters mismatch/unsafe schema/invalid age FAIL, unavailable/busy/missing UNKNOWN;
80% quota threshold prompts operator archival planning, no automatic eviction.
Do not read raw XML into report, expose foreigntenant identities or add sourcecalls.
Tests boundary/corruption/tenant/no-writes and isolatedPG missingaudit/failureparity.
Host-only atomic install, existing runtime/images/cron/schema/budgets stay pinned;
real VPS report required. FullEIS/sourceabsence/independentcorroboration UNKNOWN.

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

### S200 — public-channel NO_DATA cross-check, завершён candidate slice

Owner root; owned scripts/server-eis-no-data-public-check.py/.sh,
tests/test_eis_no_data_public_check.py, docs83/ADR0081/docs15/28/navigation;
ignored gate/release/probe helpers. Dependencies S198 retained response/offline
binding, public parser/browser/proxy/cooldown and immutable tenant index.
Acceptance: one latest retained+latest journal NO_DATA with matching tenant/key/actor/
SHA, exact offline raw reparse; one public national44day/allstage/50card page
under global import lease and browser cooldown. Echo date/law/stage/page controls
required; preserve rendered DOM+typed proof within8MiB/32MiB per-tenant8captures.
No token/request retention, reflection guard, no writes to corpus/checkpoints.
<=50 official number candidates / tenant indexed comparison read-only; no region/type
scope equality claim. Empty/blocked/unverified remain UNKNOWN, never absencePASS.
Tests scope/binding/blocked/number/retention quota/tenant/no-writes; bounded live VPS
observation and host-only atomic deploy preserving runtime/images/cron/budgets.
Do not call alternate transport independent dataset; fuller corroboration remains
UNKNOWN pending exact region/type/date/versions coverage and trusted semantics.

S200 public cross-check71Linux/PGtestsPASS13:56:38UTC, Ruff/mypyPASS;
researchDOM50/77 parsed, no scope-equivalence claim. Host rollout/live target pending.
See [docs83](../../eis/ingestion/83-eis-no-data-public-cross-check.md).

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

### S201 — адресная загрузка public candidates, завершён bounded slice

Owner root; owned scripts/server-eis-public-candidate-recovery.py/.sh,
tests/test_eis_public_candidate_recovery.py, docs84/ADR0082/docs15/28/navigation;
ignored release/gate helpers. Dependencies S200 immutable proof/DOM, existing
by-number admission, tenant lexical index/document jobs and rejected evidence store.
Acceptance: verified proof SHA/model/DOM reparse/offline SOAP binding before source;
route is only a scheduling hint, not XML admission. Recheck tenant index before each
request; <=3 missing ea20/zk20/ok20 candidates, <=18 SOAP attempts/20 downloads/
64MiB accepted archives/180s network budget, one sequential browser/global import
lease; DB<=100GiB/free>=40GiB. Preserve complete rejected bound archive sets and
actual rejection reason; tenant audit and typed proof report index changes even if
post-ingest hold/queue fails. Only usable exact latest version queues documents.
No alternate-number/subset XML admission, no participation/completeness claim.
Tests proof corruption/budget/unsupported/foreign number/atomic rejection/tenant
isolation/lexical parity/exact document job; isolated PG and bounded real VPS pass.
Host-only install; runtime images/schema/cron and ordinary source budgets stay pinned.

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

### S202 — mixed by-number metadata intake, завершено 2026-10-05

Owner root; owned sources/eis_feed_archive.py/eis_procedure_state.py,
storage/eis_notice_index.py/models.py, migration20261005_01,
tests/test_eis_mixed_number_archive.py, scripts/server-eis-mixed-number-replay.py/.sh,
docs85/ADR0083/docs15/28/navigation; ignored release/XSD/gate helpers.
Dependencies: S2013 retained complete sets, official44404 XSD16.3 ZIP SHA4313b235…,
existing by-number/preflight/tenant/lexical/document/cancellation contracts.
Acceptance: only exact by-number enables6 companion metadata families; all members
retained and parsed or atomic FAIL; field-specific number paths, immutable XML SHA
identity, real publication date only (createDate not publication). Metadata-only
events never create an active-stage PASS or mask cancellation; deadline FAIL persists.
Version0 in result metadata is not an invalid notice version. Model/migration family
constraints coupled; old dated admission unchanged. Synthetic namespace/foreignnumber/
unknownfamily/duplicate/rollback/replay/tenant/lexical/document/stage tests; isolated PG.
Offline full-XSD proof and source0 replay of all3 saved sets; synthetic usable exact
document queue refs, real expired notices blocked without new document jobs.
Deploy under existing leases with pinned overlay/backup/forward migration;
do not downgrade by deleting evidence. No new source requests/schedule/quota increase.

Acceptance: 95 Linux/isolatedPG tests PASS15:30:30UTC, Ruff/mypy/bash PASS.
16 real XML passed full official XSD16.3 validation; source0/DBwrites0.
Deployment15:46:33UTC: HEAD20261005_01, host59/API13/worker13 hashes PASS;
pinned API/worker overlays, web/cron/resources/source budgets unchanged.
Preview15:46:43UTC source0/canonical writes0; apply15:46:59UTC source0,
3 new notice versions,13 companion rows,3 exact lexical refs/tenant audits.
Every original ZIP/member retained; total158156 bytes. All3 expired: FAIL,
document queue BLOCKED/DEADLINE_EXPIRED, document jobs0.
Read-only verification15:48:51UTC: original bytes/source URLs/prepared hashes,
13 event identities,3 audits exact; all3 title-query comparisons match with FAIL.
Scoped «бумага» query matches0: these service/work notices are technical S201
cohort, not supplier recommendations or evidence of nationwide query coverage.
Ops15:48:52UTC health200/HEAD01/testDB0/markersfalse;
DB4613258263/free258075906048 bytes. Proofs and SHA: [docs85](../../eis/ingestion/85-eis-mixed-number-archives.md).
Full coverage/freshness/protocol semantics/participation remain UNKNOWN.
Final docs seal15:50:51UTC: atomic6/host59/API13/worker13hashPASS;
installed images pinned, web/cron unchanged, API/web running/noOOM.

Next S203: bounded source0 interpretation of stored EOK protocol facts against
official XSD. Separate typed provenance for stage, application counts, proposal
prices and result; preserve cancellation/deadline/mandatory gates and Decimal.
Register owner/files/acceptance before implementation. Do not turn historical
competition facts or НМЦК into active status, expected profit or PARTICIPATE.

### S203 — source0 historical protocol facts, завершено 2026-10-05

Owner root; owned sources/eis_protocols.py, storage/eis_protocols.py,
api/app.py, tests/test_eis_protocols.py, tests/test_eis_protocols_api.py,
tests/integration/test_eis_protocols_pg.py; docs86/ADR0084/docs15/28/navigation,
scripts/server-eis-protocol-check.py, ignored release/gate helpers.
Astra owns independent read-only high-risk review (no overlapping edited files).
Dependencies: S202 immutable companion events/original canonical ZIPs/exact notice
refs, official XSD16.3, tenant RLS/source-hold/cancellation/deadline contracts.
Acceptance: typed per-document field provenance; exact namespace and field paths,
Decimal amounts, absence/ambiguity UNKNOWN. Distinguish rows from unique application
IDs and applications from supplier identities. No cross-document latest guessing,
rank1/signed-contract inference, implicit currency/VAT, profit or probability.
Explicit bounded read-only API over one exact notice ref; no source calls, mutations
or automatic source/queue expansion. Wrong ref/tenant/SHA/unsafe ZIP/limits rejected.
Real source0 verification on three S202 saved sets, isolated PG/API negative tests,
review fixes, controlled pinned deployment and hash/health/documentation seal.
Complete one bounded slice; current stage/freshness/full coverage UNKNOWN.

Acceptance:158 Linux/isolatedPG testsPASS16:26:12UTC (10.86s), Ruff/mypyPASS.
Astra read-only review:five findings fixed and independently confirmed;
UTF16/32DTD/name bounds/docNumber/admission branches/family fields regressions.
Direct source0 preview16:27:17UTC:9 exact documents/3notices, DBwrites0;
three reads69/95/107ms excluding container startup. EOK Final represented counts
5/2/1; Proposals0096 has38 repeated rows/countUNKNOWN, not38suppliers.
55totalrows/48explicitamount observations are not aggregated bids/supplier counts.
Deployment16:27:35UTC atomic13/host68/API16/worker16hashPASS; HEAD01 unchanged.
HTTP authenticated check16:28:17UTC:3responses200/no-store,70/81/177ms;
source0/DBwrites0. Existing expiredFAIL and UNKNOWN participation/stage/freshness
retained. Ops16:28:18UTC DB4682456087/free257977925632bytes,
testDB0/markersfalse/health200. Web/cron/resources/source budgets unchanged.
Proofs/imageIDs/backup/SHA: [docs86](../../eis/search/86-eis-historical-protocol-facts.md).
Documentation seal16:30:35UTC: atomic6docs/host68/API16/worker16hashPASS;
image/cron pins PASS, API/web running/OOMfalse.

NextS204: exact-ref UI/BFF display of historical protocol facts in discovery card.
Clearly distinguish per-document rows/applications from supplier identities,
keep source locators and UNKNOWN notice-version applicability/currency/tax/current
stage. No recommendation/discount/probability inference or new source requests.
Mass historical aggregation/cache/analog comparability remains a later bounded slice.

### S204 — исторические протоколы в карточке, завершено 2026-10-05

Owner root. Owned files: web/src/lib/eis-protocols.ts,
web/src/lib/procurement-api.ts (read-only adapter),
web/src/app/tender-discovery/actions.ts (read action), indexed-search.tsx,
historical-protocols.tsx, historical-protocol-report.tsx;
web/tests/eis-protocols.test.tsx, web/tsconfig.protocol-tests.json,
web/package.json (bounded test command), web/.gitignore;
docs87/docs15/docs28/docsREADME, ignored deployment/proof helpers.
Dependencies: S203 installed exact-ref API, existing server-side bearer/BFF,
React escaping and card remount on exact version/SHA.
Acceptance: explicit on-demand read of saved protocols; no automatic fetch or
source/queue writes. Wrong/malformed ref rejected; response must match exact ref.
Rows/applications/supplier identity, unknown currency/tax/version linkage/current
stage remain explicit. Amount string never converted to Number; each displayed
fact has XML/member/locator provenance. Empty list does not mean zero competitors;
rank1/result codes do not imply a signed contract. FAIL remains visible.
Verify synthetic render regressions, TypeScript/ESLint, production web build,
installed real UI read and pinned API/worker/web resources/hash checks.

Evidence:8 synthetic render/transport/ref tests PASS, scoped ESLint/TypeScript
and VPS Next build17:07:52UTC PASS (networknone/2CPU/2GiB/noOOM).
Astra read-only review: transport rejection fixed, independently confirmed.
Deploy17:10:19UTC: atomic13/host75/web9hashes PASS; pinned API/worker unchanged.
Installed actual Next Server Action plus production component render17:12:42UTC:
3exactrefs/9realprotocols, FAIL/expired and repeated38rows/countUNKNOWN retained;
132/102/88ms web loopback reads, source0/DBwrites0.4negative ref/tenant requests
give safe errors. HTTP200; head20261005_01, testDB0/resources/cron unchanged.
Browser visual click not performed: approval review rejected SSH tunnel startup;
no workaround changing network access. Evidence/proofs/backup/images: [docs87](../../eis/search/87-eis-protocols-in-discovery-ui.md).
Docs seal17:16:10UTC: atomic4docs/host75/API16/worker16/web9hashes PASS;
pinned images/cron/resources PASS, API/web running/noOOM.

Next S205: specify comparable historical analogs (item/lot/region/period/quantity),
bounded source0 projection/cache with original document provenance and transparent
sample exclusions. Separate raw proposal rows from independent applications;
keep uncertain supplier identity/currency/tax/version linkage UNKNOWN.
No cross-document sum, uncalibrated win probability or recommendation without quotes/scenarios.

### S205 — ограниченная выборка исторических аналогов, backend завершён 2026-10-05

Owner root. Owned: sources/eis_analogs.py, storage/eis_analogs.py,
api/app.py (new read-only POST), tests/test_eis_analogs.py,
tests/test_eis_analogs_api.py, tests/integration/test_eis_analogs_pg.py;
docs88/ADR0085/docs15/docs28/navigation, ignored deployment/gate/live helpers.
Astra owns independent read-only contract/review; no overlapping edits.
Acceptance: dedicated SQL selector in one consistent tenant read, target excluded
and latest/source holds/history/publication/token filters before LIMIT21.
At most20 candidate notices/25positions each; explicit truncation and incomplete
lexical recall. SQL timeout and payload/output budgets; LIMIT is not a DB scan bound.
Exact selected target/ref/position; no target-date fallback to now.
Per-dimension PASS/FAIL/UNKNOWN and both source locators, Decimal quantity filter
0.5..2 inclusive with same normalized unit label (retrieval predicate only).
Known conflicting KTRU blocks fallback; otherwise exact OKPD2+whole normalized name.
Technical equivalence and delivery region UNKNOWN; publication region never reused.
Any dimension FAIL excludes row; no score/competitor count/price/participation
inference. Source0/read-only/no jobs/new schema. Test negative RLS/refs/holds/
history-before-limit/counts/bounds, real source0 API/ops and controlled deploy.

Evidence:27local/193isolatedLinuxPGtests PASS; scoped Ruff/mypy PASS.
Astra independent review closed; oversized quantity, missing-source evidence,
SQL correlation and meaningful before-limit cases fixed. Deploy18:39:45UTC:
atomic12/host82/API18/worker18hashes PASS, head01/health200.
Installed HTTP+exact-time direct reads18:41:41UTC identical on3fresh paper refs:
4066/3291/3236ms HTTP; each20notices/82positions, review0/1/1, remainderFAIL.
All selection_truncated=true, coverage/technical/delivery/participation UNKNOWN;
not all history or confirmed analogs. Source0/DBwrites0; no UI yet.
Ops18:41:42UTC DB4927994903/free257592745984bytes/testDB0/resources unchanged.
Pins/proofs/backup: [docs88](../../eis/search/88-eis-historical-analog-selection.md).
Docs seal18:42:53UTC: atomic6/host82/API18/worker18/web9hashes PASS,
image/cron pins and runtime resources PASS; API/web running/OOMfalse.

Next S206: measured SQL optimization before adding UI. Current direct reads52SQL;
20redundant hold queries+20SET LOCAL can be removed inside same REPEATABLE READ,
retaining target assertion and complete selector/integrity predicate. Owner root;
planned owned files storage/eis_analogs.py, bounded PG tests/metrics and docs.
Acceptance: fixed-time reports identical; unresolved/resolved/invalidated holds,
receipt integrity and RLS gates; fewer SQL and recorded same-ref first/repeat
latency. No claimed speedup before measurements. S207 then position-selection
and source-explained historical candidates UI; technical/delivery evidence later.

### S206 — SQL ускорение аналогов, завершено 2026-10-05

Owner root. Owned files: storage/eis_analogs.py (redundant loop and query-local JIT),
new tests/integration/test_eis_analog_holds_pg.py; docs89/docs15/docs28/
docsREADME/ADR0085 (record unchanged contract), ignored release/metrics helpers.
Astra owns independent read-only review of hold equivalence and regression gates;
no overlapping edits. Depends on installed pinned S205, schema20261005_01,
same complete hold selector and read-only REPEATABLE READ transaction.
Acceptance: target assertion and selector hold/integrity/audited-origin predicates
unchanged, budget remains before hydration. Fixed-time full reports identical
to immutable S205 reader;20candidate read13SQL instead of52. Cover same/newer
unresolved evidence, incomplete tenant receipt, valid resolution and invalidated
audit/origins, RLS/read-only isolation. Measure same3paper refs first/repeated
HTTP+direct reads, deploy only one module with source/cron/resources unchanged.
Do not claim nationwide speed/freshness/coverage, confirmed analogs or UI delivery.

Measured refinement19:02:31UTC: removing redundant reads alone left3.1–3.4sHTTP.
Bounded source0 EXPLAIN identified JIT compilation1150ms; same selector JITon
3037ms vs JIToff1888ms. Add only SET LOCAL jit=off in this read-only transaction;
no global DB setting. Net39fewer commands (40removed,1local setup added).
Preserve reports and test setting restoration after transaction. Remaining large
scan/index strategy is later measured work, not part of this single-module slice.

Final gate19:05:15UTC208PASS in22.18s, Ruff/mypy and Astra review PASS.
Final deploy19:15:01UTC atomic7/host84/API18/worker18hashes PASS; head01/health200.
Six installed first/repeat reads19:16:57UTC HTTP1977–2167ms; full reports identical
to frozenS205 in same-time/same snapshot and HTTP/direct equality. Median paired
body3303→1942ms (~41% lower in warmed sample); standalone52→13SQL.
20notices/82positions each, all truncated; review0/1/1 unchanged; coverage/
technical/delivery/profit/participation UNKNOWN. No nationwide speed claim.
Ops19:16:58UTC DB4971232279/free257516175360bytes/testDB0/source0/DBwrites0,
head01/resources/cron unchanged. Pins/proofs/backup: [docs89](../../eis/search/89-eis-analog-query-performance.md).
Docs seal19:18:24UTC atomic5/host84/API18/worker18/web9hashes PASS;
image/cron pins/resources PASS, API/web running/OOMfalse.

Next S207: source-position selector and on-demand historical candidates in existing
discovery UI, transparent exclusions/provenance/limits/UNKNOWN, typed exact-ref
transport, no automatic source requests or quote/profit/participation inference.
Then S208: measured two-branch lexical identity prefilter (overlap + no derivation),
without early branch LIMIT; preserve holds/RLS/empty-key/ties/latest/filter semantics
and full fixed-time report identity before performance adoption.

### S207 — интерфейс исторических кандидатов, завершено 2026-10-05

Owner root. Owned files: new web/src/lib/eis-analogs.ts,
web/src/app/tender-discovery/historical-analogs.tsx and historical-analog-report.tsx,
new web/tests/eis-analogs.test.tsx and web/tsconfig.analog-tests.json;
bounded additions to procurement-api.ts, actions.ts, indexed-search.tsx, package.json;
docs90/docs15/docs28/docsREADME and ignored web release/proof helpers.
Astra owns independent read-only contract review; no overlapping edits.
Depends on installed S206 API/worker and S204 web, unchanged schema20261005_01.
Acceptance: explicit source-position/query/lookback selection, exact request-bound
typed response, stale/transport errors cannot display another selection's report;
FAIL exclusions, UNKNOWN review, both XML provenance and bounded/truncated/empty
scope visible. Quantity strings retain precision. No source requests, jobs, DB
writes, profit/rank/participation inference or new dependency. Relevant render and
negative transport tests, TypeScript/ESLint/production build, installed server
action and source0 operations proof. Web-only pinned deployment with rollback;
API/worker/cron/resource settings unchanged. Browser visual check is a separate
verification and must not be claimed from SSR checks.

Evidence:9analog+8protocol Node tests PASS; TypeScript/targeted ESLint/production
build PASS on isolated VPS container networknone/2CPU/2GiB, no dependency change.
Astra review closed after strict enum/unknown inherited-key guards, correct family
links and exact20-result wording regressions. Web-only deploy19:56:19UTC:
atomic13/host90/web14hashes PASS; old backend pins/head01/resources unchanged.
Installed Server Action/production SSR19:57:35UTC:3fresh paper refs first/repeat,
1946–2269ms, each20notices/82positions/truncated; excluded/review82/0,81/1,81/1.
Changed source_index2/lookback30 request1796ms with exact binding. Eight negative
requests return errors without reports. Previous protocols:3refs/9documents and
4negative checks PASS. These are loopback HTTP+SSR checks, not browser visual or
nationwide latency/SLA. Browser check not performed; existing S204 tunnel-start
automatic approval rejection remains respected, no new public ports/tunnel.
Ops19:57:37UTC DB5039660055/free257407389696bytes/testDB0/health200/head01,
markersfalse. Source0/read-only/DBwrites0; API1GiB/web768MiB/worker2CPU2GiB,
cron unchanged. Pins/proof hashes/backup: [docs90](../../eis/search/90-eis-analog-candidates-ui.md).
Docs seal19:59:04UTC atomic4/host90/API18/worker18/web14hashes PASS;
image/cron pins/resources PASS, API/web running/OOMfalse.

Next S208: measured two-branch lexical identity prefilter, as specified in S206
and docs89. Owner root; planned owned storage/eis_analogs.py, bounded PG tests,
ignored plan/latency helpers and docs. Acceptance: immutable pinnedS206 fixed-time
full report identity; missing/empty derivations, ties/latest/holds/RLS and bounds;
actual EXPLAIN buffers/subplan loops and same-ref first/repeat HTTP timings before
adopting or claiming speedup. No scope expansion or automatic full-history fetch.

### S208 — SQL prefilter исторических кандидатов, завершено 2026-10-05

Owner root. Owned files: storage/eis_analogs.py, new
tests/integration/test_eis_analog_prefilter_pg.py, bounded disposable-DB guard
addition in test_eis_analog_holds_pg.py; docs91/docs15/docs28/docsREADME/ADR0085,
ignored immutable baseline, plan/latency/gate/release helpers. Astra owns independent
read-only review, no overlapping edits. Dependencies: pinned S206 API/worker,
S207 web, schema20261005_01 and existing lexical GIN/PK indexes.
Acceptance: disjoint indexed overlap and missing-derivation identities, complete
family/date/latest/hold filters and final order/LIMIT21 unchanged. Empty stored
keys do not become missing derivations. No early branch limit or new source/data
writes. Immutable S206 same-time/snapshot full report identity; missing/empty keys,
ties/latest, multi-tenant/RLS/holds/history-before-limit/bounds/read-only gates.
Measured actual plan/buffers/subplan loops, same-target first/repeat HTTP/direct
latencies before adopting. Pinned one-module API/worker deploy with rollback,
web/cron/resources unchanged. Do not claim full coverage or nationwide SLA.

Evidence:216isolatedPGtests PASS24.81s/zero skips,27localunit/APItests/Ruff/mypy
PASS; Astra read-only review closed. Missing/empty/custom derivations are inserted
synthetically under runtime tenant scope; no owner UPDATE/DELETE/trigger bypass.
Initial same-snapshot reports identical. Actual selector1950→1534ms, hold-subplan
loops49031→938; no GIN use observed, gain is reduced notice/hold probes.
Deploy20:25:42UTC atomic8/host92/API18/worker18hashPASS; pinned S207web unchanged.
Six installed source0 same-time/snapshot/full reports identical; balanced paired
body median2122→1624ms (~23.5% lower in warmed sample), HTTP1612–1744ms.
Same20notices/82positions/truncation/review0/1/1/UNKNOWN,13standaloneSQL unchanged.
Installed Next Action+SSR regression20:27:14UTC:6reads1545–2011ms, changed
position2/period30 227ms,8negativechecks PASS; not browser visual/nationwide SLA.
Ops20:27:15UTC DB5050481687/free257335136256bytes/testDB0/head01/health200,
prioritymarkertrue ordinary activity; resources/cron/source budgets unchanged.
Pins/proofs/backups: [docs91](../../eis/search/91-eis-analog-lexical-prefilter.md).
Next S209: optionally scope projection-resolution pairs and referenced audit
batches to all pre-limit eligible candidates and same/newer retained evidence;
keep tenant-wide receipt integrity and every canonical/transport/audit/all-origin
check. Existing unscoped consumers unchanged. Measure spills and exact reports.

S208 docs seal20:28:53UTC atomic5/host92/API18/worker18/web14hashes PASS;
image/cron pins/resources PASS, API/web running/OOMfalse.

### S209 — scoped live resolution checks, завершено 2026-10-05

Owner root. Owned files: storage/eis_notice_hold.py and storage/eis_analogs.py;
new tests/integration/test_eis_analog_resolution_scope_pg.py; bounded disposable
DB guard additions in test_eis_analog_holds_pg.py/test_eis_analog_prefilter_pg.py;
docs92/docs15/docs28/docsREADME/ADR0085 and closing S208seal line in docs91;
ignored immutable baseline/gate/plan/latency/release helpers. Astra independent
read-only review, no overlapping edits. Dependencies: pinned S208 API/worker,
S207web, schema20261005_01. Optional resolution scope initially only analog reads.
Acceptance: eligible refs before holds/LIMIT, include every same/newer retained
variant/origin pair and referenced projection audit batch. Keep full audit array
length/equality, canonical bytes/transport/exact origin and all conflicting
origins/variants checks; receipt integrity remains tenant-wide. Default unscoped
consumers unchanged. Freeze BOTH old analog and old hold modules for full-report
equivalence, test newer origins beyond target publication, additional receipt
conflicts, multi-purchase audit batches/malformed arrays/unrelated incomplete
receipts/RLS/read-only/bounds. Measure actual CTErows/tempblocks and same-target
first/repeat latency; adopt only observed gain. No schema/new source/write/cache.
Controlled two-module overlay deploy/rollback; web/cron/resources unchanged.

Evidence:228isolatedPGtests PASS30.43s/zero skips,27unit/API/Ruff/mypy PASS,
Astra source-gate review closed. Initial3exact reports identical;
selector1496→571ms, audit2285→98rows/resolved187→2rows,
tempread6194→3460/tempwritten13071→3460blocks (spill remains).
Deploy20:43:42UTC atomic11/host95/API19/worker19hashes PASS, S207web unchanged.
Six installed balanced paired full-report/HTTP identities PASS; direct median
1618→723.5ms (~55% warmed sample), HTTP712–871ms. Selection20/82/truncated,
review0/1/1 and UNKNOWN unchanged.13standaloneSQL/source0/jobs0/DBwrites0.
Next Action+SSR20:44:39UTC648–821ms/changed225ms/8negative PASS;
not browser visual/full-source SLA. Ops20:44:40UTC DB5051169815/free257312370688,
testDB0/head01/health200/markersfalse; caps/cron/source budgets unchanged.
Pins/proofs/backup: [docs92](../../eis/search/92-eis-scoped-resolution-checks.md).

S209 docs seal20:46:05UTC atomic6/host95/API19/worker19/web14hashes PASS;
pins/cron/resources PASS, API/web running/OOMfalse. Seal backup SHA256
`33fdc21737e8698a47d238660c43340e79df481ce75c52e38f472aedeaf9298f`.

