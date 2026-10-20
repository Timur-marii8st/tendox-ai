# ADR-0065 — полный gap census и bounded historical transient retry

Статус: **ACCEPTED / DEPLOYED AND VERIFIED**.
Дата: 2026-10-04, S181. Owner ADR: Astra; status/CLI/gates: root;
eligible_windows/fairness tests: Sol.

## Основание

VPS baseline, source calls0 / writes0: 143130 pending, из них 136630
unattempted, 6427 NO_DATA, 72 FAILED, 1 SERVICE_ERROR. Scope source dates:
2025-09-28…2026-10-04. Два старых SOURCE_TRANSPORT_FAILED не получают retry
на фоне большого unattempted backlog. 52 attachment-related FAILED и 5
MEMBER_UNSUPPORTED требуют отдельного parser review и не разрешаются этим slice.

Proof `/var/lib/eis-browser/research/rejected/s181-baseline-census.json`, SHA-256
`8679ec7d7c06bac6dced018170950c90f71baae5c7aa5d7e066c932887147d11`.

## Gap-status contract

Typed read-only census охватывает весь planned tenant scope в одном consistent
snapshot. Legacy canonical complete исключается; VARIANT_TRANSPORT не закрывает
gap. Latest attempt выбирается одинаково для census и scheduling, с полным
детерминированным ordering времени и immutable ID tie-break. Все groups/totals
точны и суммируются; bounded IDs маркируются как sample, не полный список.
NO_DATA означает наблюдение конкретного source window, не отсутствие закупок
во всей ЕИС. Coverage/freshness остаются UNKNOWN.

## Historical lane

Добавить до3 historical transient retries в обычный batch до60, без изменения
общего source/time/memory budget, cron, regions/families или migrations.
Source day должен быть старше существующего recent7 completed-day lane по
MSK calendar. Latest attempt — FAILED с точным двухкодовым transient allowlist
либо PREPARING/SERVICE_ERROR; конкретные два FAILED codes фиксируются runtime
контрактом: `SOURCE_TRANSPORT_FAILED` и `SOURCE_WSDL_UNAVAILABLE`;
prefix matching запрещён. Cooldown не меньше24h от latest attempt;
future timestamps не due.

Не eligible для reserved historical lane: legacy-complete, latest NO_DATA, semantic/parser errors,
partial/conflicting variants. Более старый transient attempt не обходит latest
excluded outcome. Existing recent-failure lane сохраняется; reservations делят
общий limit; historical reserve ограничен фактически выбранным recent count,
а не теоретической квотой. При limit2 и пустой recent lane остаются historical1
и ordinary1; при occupied recent — recent1 и ordinary1. Обычный backlog
заполняет остальные slots. При наличии backlog
ему гарантирован хотя бы один slot даже на малых runs; лимит1 не может быть
полностью захвачен historical reservation. Dedup window единожды на run.

Успех/отказ retry фиксируется через прежний journal; history не изменяется.
Только действительный canonical complete может закрыть gap. Typed local errors
и automatic partial intake не превращаются в SYNCED ради counts.

## Gates

Проверить tenant/RLS, exhaustive latest-state groups и сумму counts, samples,
same-time tie, MSK recent boundary,24h/future cooldown, exact transient codes,
newer NO_DATA/semantic failure exclusion, transport-vs-legacy checkpoint,
existing recent lane и no-starvation на limits1/2/60. EXPLAIN и реальный
read-only census измеряются на большом planned backlog, без загрузки XML.
После isolated gates/deploy допустим controlled retry не более двух старых
transient windows; его результат не предрешён. Production evidence ниже.

## Review и performance gate

Повторный review single-SQL census и actual-recent reservation пройден.
Totals, JSON groups и bounded JSON samples используют один MATERIALIZED
pending CTE в одном statement. CASE не выполняет retry predicate для
unattempted rows; это не меняет due semantics. Ordinary backlog политика
не меняется: исключения parser/NO_DATA относятся к новому reserved lane.

Первый вариант из трёх statements повторно строил pending set и занял
36.697 s на production census; single-SQL staged вариант — 8.475 s.
Selector — 8.369 s, EXPLAIN — 8.572 s. Старый S168 sample 7.47 s снят на
иной date/state и не доказывает точный overhead. Это wholequeue measurement,
не SLA. Финальные Linux148 + PG30 PASS подтверждены root, включая CASE и
explicit JSON sample aggregate ordering; root52 recheck PASS, Ruff8/mypy4 PASS.

## Production и live retry

Rollout13:20:27 UTC: host14/runtime4 hashes PASS, API/worker rebuilt,
HEAD `20261004_03` неизменён. Backup SHA-256
`5aa74ce97acf72857c08cde51be51c196566ed66452267ece65635ffe2ea4d01`.
Deployed census: planned148168 / canonical-completed5040 / pending143128 /
unattempted136602 / NO_DATA6451 / historical due2. Census8.357 s,
selector8.264 s, EXPLAIN8.372 s. Proof SHA-256
`bc1880e85a37867150ec7379b2bee4142d9203abc1892e9cc42eeaefd09ea3e5`.

Controlled retry двух old cancelFailure windows (region50/2026-09-24 и
region90/2026-09-17): каждый вернул NO_DATA,3.324/2.501 s. Старый FAILED
каждого окна сохранён; добавлены journal/audit observations, checkpoint false,
new versions0. Peak280,690,688 bytes /2 GiB. Live proof SHA-256
`46c233e57a976f5f912b737e20ea2530f538f7bb0b730cf75532791073a2c69f`.
Read-only followup: exact latest IDs совпали, historical due0, NO_DATA6453.
Proof SHA-256 `b623a291b32cd34c72be512332916450f4dc83689dde30026b39d98edf1c5694`.

API healthy / anonymous401 / no-store / coverage and freshness UNKNOWN;
44 sample paper7.733 s/server14.602 s,223295/520 ms. Test DB удалена.
Собственный marker удалён; при API snapshot priority marker принадлежал уже
работающему freshness cron. Operations13:25:07 UTC PASS: test DB отсутствует,
priority marker=false и223 marker=false; markers сняты собственными cron,
source calls0. Proof `s181-operations-proof.json`, SHA-256
`4cd89173a4cfd7146d94b9e169dce512b3e31e469fa60d12e093e070bfa2eb1a`.
Чужие markers не удалялись. Release blockers по code/gates/operations не осталось.
