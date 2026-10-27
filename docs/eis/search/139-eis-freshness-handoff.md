# V51: свежая загрузка дожидается общего замка

Owner root. Статус: PASS_BOUNDED_INSTALLED_FRESHNESS_HANDOFF; host-only18:38UTC.
[ADR120](../../adr/0120-eis-freshness-priority-wait.md),
[предыдущий срез](../ingestion/138-eis-drug-positions.md).

Проверяемый результат: штатный fresh44 tick переживает document priority wait,
получает актуальный readiness и bounded source progress; дубликаты не накапливаются.
Owned/acceptance/dependencies: `tmp/eis-freshness-handoff-20261026-v51/slice.json`.

Read-only17:31UTC:44 —412429номеров/450238версий,223 —49558/57584.
Весь44lexical совпал с числом версий. Корпус включает неактивные закупки;
национальная полнота UNKNOWN. V49 transportgap0190200000326012327 всё ещё отсутствует.
17:37freshness:450region×familygroups,657unattempted/6083due/2failed.
Модель p95 даёт288slots/hour, не устойчивый throughput.900polls — консервативная
модель; checkpointed selector уже исключает terminal hour windows.

Existing processmetrics16–17UTC:44 —11наблюдаемых dispatch,5BUSY/5SUCCESS/1ERROR;
223 —6SUCCESS; documents —15SUCCESS/12ERROR/32BUSY/1incomplete. SUCCESS не receipt.
Все5freshBUSY пересеклись с document import wait при занятом priorityFD8,
118–195s. Exact installed/local script hashes совпали. Это подтверждённый механизм
lost tick; незаполненные интервалы нельзя автоматически считать source headroom.
Evidence: `tmp/eis-sweep-renewal-20261026-v51/priority-contention-proof.json`,
`dispatch-interval-16-17.json`, `decision-review.json`, `fresh-coordination-review.json`.

Expiry-only renewal старого V38 отложен: он мог бы дополнительно занимать priority.
Его checkpoint27partitions/asof24Oct/claims сохранены, renewal plan/apply не выполнялись.
Код исправления меняет только fresh dispatcher: один private FD7, bounded
interruptible priorityFD8 wait300, затем прежние probe/importFD9/worker.
Cron/cadence, documents/223, images/schema/source limits неизменны.

Обязательные проверки: реальные flock/duplicate/timeout/INT/TERM, актуальный probe
после ожидания, foreign marker и worker lifetime, прежние source аргументы/metrics;
полный release gate, независимый review, exact host-only rollout и наблюдение
штатного cron с native receipts/очередью. Bounded scope принят ниже; sustained UNKNOWN.

V51 source d8690531/tree9e2a6292: gate50PASS, unit4414+27allowedskips,
PG771/web222/doctest9. Receipt0eb7ae96;9новых processcases,14installerfaultcases.
Independent code/executor/exactplan PASS; планbae5755d установлен после BUSY
и наблюдения свободных leases, без preemption. Только priority040c→f8ec8b2c,
mode/owner сохранены. API0249/WEB71e/schema26_02/cron/остальные hostfiles
неизменны; tenantPREPARED/ACTIVATED и healthPASS. Gateimages не установлены.
18:28native baseline:807unattempted/6486due/2failed,450groups.
Ordinarycron и пять новых карточек проверены; bounded runtime PASS, national UNKNOWN.
Evidence: `tmp/eis-freshness-handoff-20261026-v51/installed-readback.json`,
`runtime-observation-plan.json`, `current-handoff.json`.

Итог19:07UTC: independent review f9a4886d PASS. Реальный47tick ждал88.272s
за documents/223, тот же PID получил import и закрыл60окон/+11версий.
57tick тоже дождался import, затем JOINT_START_BUDGET_REACHED:0attempts,
его ERROR/BLOCKED не превращён в sourcePASS. Max observed freshwrapper1;
synthetic duplicate/foreignmarker/INT/TERM PASS; runtimeforeignmarker не создавался.

Сопоставимые20min18:15–35 и18:40–19:00: native120→180разных окон,
после установки168NO_DATA/12SYNCED/+27версий.223дваSUCCESS,7documentaudits.
До был gateCPU; dispatchcohort и completedsource boundaries различаются,
поэтому устойчивый множитель скорости не заявлен. Один и тот же450group/hour
горизонт18:44→19:00:687→567unattempted,2failed неизменно. Новые часы
после19:05 в это сравнение не входят; национальная полнота UNKNOWN.

Пять новых nominalrefs:0351300159026000321,0332300301426000050,
0432200000826005481/5482/5483 — nativeZIP/XML→canonical/lexical→mainHTTP
и actualCUA ordinarysearch PASS:полное название/номер/версия/НМЦК/срок/
officialURL/visibleXMLSHA/UNKNOWN.4из5 в одномZIP, всего2ZIP;
это пять карточек, не пять независимых контрактных аналогов.
Первый sample-not-ready и неуспешный draftanalysis сохранены; budgetstop
и неодинаковый datetimeformat не скрыты (`observation-reassessment.json`).
Finiteobserver SSH255, trace продолжился за19:00; послеdeadline observerPID0.
Final19:04health/scopePASS. Fullgate disposable resources удалены штатно.

Acceptance: `tmp/eis-freshness-handoff-20261026-v51/acceptance.json`;
`runtime-analysis.json`, `actual-ui.json`, `installed-independent-review.json`.
V49 номер0190200000326012327 оставалсяmissing18:40, consumedmanualretry0.
Следующий срез — regularKESMBO: targeted parser уже есть, regular lane нет.
