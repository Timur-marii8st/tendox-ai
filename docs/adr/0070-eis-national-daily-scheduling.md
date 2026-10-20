# ADR-0070 — five-family daily planning with bounded backlog fairness

Статус: **DEPLOYED AND VERIFIED / BOUNDED DAILY5; COVERAGE AND CAPACITY UNKNOWN**.
Дата: 2026-10-04, S189. Owner ADR/review: Astra; runtime/tests: Sol;
operational evidence, acceptance и rollout: root.

## Выбор M1

Предпочтителен bounded daily plan для пяти families по завершённым датам:
EF/EZK/EOK/Cancel/CancelFailure. Добавляется отсутствующий EOK, existing
three-region hourly priority сохраняется. Candidate codes01..99 не объявляются
проверенным реестром действующих регионов.495 daily keys/day — не гарантия
завершения за24h и не доказательство полного source coverage.

National hourly создаёт495 новых keys/hour до retries. Это превышает только
existing priority ceiling288/hour; corpus240/hour — отдельный cap на общей
import lease, поэтому их нельзя складывать как независимую производительность.
Joint wall time, cooldowns,223 и documents должны входить в feasibility.
Source freshness/overall capacity могут оставаться UNKNOWN.

## Предлагаемый fairness contract

Существующий ordinary order NULL attempts first/date descending способен
поставить весь новый EOK cohort перед настоящим историческим backlog.
Нужна conditional fairness mode при limit>=2 и одновременном наличии recent
unattempted completed-date keys и genuine historical eligible backlog.

- Historical anchor выбран первым по прежнему old-lane order; source date
  строго раньше MSKtoday−7, tenant/planned, без LEGACY checkpoint, прежняя
  eligibility NULL либо last attempt не позже now−24h.
- Один recent unattempted key выбран вторым: MSK dates[today−7,today−1],
  без каких-либо attempts, без checkpoint. Same-day/future не допускаются.
- Затем existing recentFAILED и historical transient lanes в прежних верхних
  caps; оставшиеся slots — recent unattempted до ceil(40%limit) и stable
  ordinary fill. Все lanes deduplicated, budget основан на actual counts.
- limit2 даёт anchor+new; limit1 и отсутствие новых recent keys сохраняют
  прежнее поведение. Historical key выбран рано для progress до последующего
  priority yield, но source execution до первого yield не гарантируется.

Anchor исключает все keys, удовлетворяющие `historical_source_retry_clause`,
поэтому не расширяет transient cap и не пересекается с этой lane. Если eligible
ordinary historical anchor отсутствует, новая fairness mode не включается:
выполняется exact прежний selector. Recent keys не имеют ANY attempts.
Ceil40%limit — hard cap recent UNATTEMPTED, пока остаётся eligible ordinary
older backlog; overflow для work-conserving fill допускается только после
его исчерпания. Existing retry caps, latest/canonical/cooldown и `_KEY` guards
сохраняются, actual counts и dedup определяют остаток capacity.
Это новая условная ordering policy, а не обещание неизменного порядка для
всех входов. Без activation condition прежний порядок должен совпадать точно.

## Gates

Read-only M1 feasibility завершена. PG:limit1/2/60, actual-empty
lanes, exact cooldown/latest tie, tenants, date rollover, no pending deletion,
no duplicate keys, earliest historical anchor и сохранение ordering вне нового
условия. Planning idempotent; no schema/cron frequency/resource/concurrency
increase. Dry-run selector/EXPLAIN и реальные due counts перед rollout.

После final contract, independent code review и focused gates: backup/hashes,
не более3 STANDARD selected windows (history+EOK), не forced3EOK,
с exact receipts и immutable old attempts.
NO_DATA/PARTIAL не превращаются в canonical completion; все существующие
variant/source/parser guards сохраняются. Пока runtime/rollout не подтверждены.

## M1 evidence и execution границы

Snapshot19:42:50 UTC,13.635 s;1485 candidate windows =1197 planned +288
missing EOK (96/day). Existing9EOK:7 canonical /2 NO_DATA. Pure NULL overlay
поставил первые60 новых EOK вместо прежних60 keys за06.09 — риск starvation
исторического backlog подтверждён. Proof SHA-256
`f1ccaeb78698ee09a092ae119396487d48e1ef169d38c1c0e3d3db937743957e`.
Выбран DAILY5, SLA/overall capacity UNKNOWN.

В corpus runner нет240s wall cap: CLI его не передаёт. Прежние ограничения —
max60, source failures, resource gates и cooperative yield. Нельзя переносить
priority-worker240s budget на corpus или обещать strict wall time.
Joint-lease observations показывают223 occupancy17.6% за22.85h; у остальных
logs недостаточно timestamps, поэтому свободная capacity не доказана.

Допустимы несколько bounded SELECTs на одной READ ONLY REPEATABLE READ
connection; нельзя возвращать unbounded full queue в Python. Candidate reads
ограничены текущим max limit1000, query cost/EXPLAIN проверяются на VPS.
Contract ready для M2; code review и rollout evidence ожидаются.

## M2 initial code review

Runtime SHA-256
`dcbeb4a6bbc6f50ab77004c897bf363ec4639acb6067ab8574c88d31a05f0313`:
activation/fallback, anchor-first/new-second, actual residual retry caps,
ceil40% hard cap и work-conserving overflow соответствуют контракту.
Все reads выполняются на одной tenant READ ONLY RR connection; в active mode
до6 bounded SELECTs. DAILY script добавляет EOK без изменения остальных families.
Independent code review PASS, correctness blockers не обнаружены.
Sol сообщил Ruff/mypy и21 local unit PASS; реальные PG, selector latency/
EXPLAIN и deployment proofs остаются обязательными pending gates.

Final reviewed runtime SHA-256
`eff566e0255d6f3619f7ca862d98331df29db61c650552432eca1cad2a5c11ec`:
только fair-helper transient/recent-failure exclusions заменены на uncorrelated
IN с явным исключением NULL. Target key non-null, наборы tenant-filtered;
NOT IN эквивалентен прежнему equality NOT EXISTS без NULL trap.
Classic fallback неизменен. Final-hash PG34 PASS; semantic review PASS.

Первый synthetic overlay timeout60s выявил потерю planner statistics при
materialized company filter: estimate743 вместо148597 rows, ordinary estimate1
вызвали непредставительный nested-loop plan. Helper исправляет projected
tenant constant поверх уже tenant-filtered rows; повторный bounded замер pending.
Это ещё не evidence реальной runtime latency. Performance/release gate остаётся
открытым, contract и resource caps не меняются.

После exact288 EOK target bootstrap фактический table selector также достиг
timeout60s на ordinary fill. Поэтому проблема не списывается только на overlay.
Bootstrap replay0/source0 зафиксирован отдельно; production runtime ещё прежний.
Bootstrap proof SHA-256
`2e66414796babe98a25f6ebae28109e9a76e34a524738f70cdddf1a89bb7a2f8`.

Следующий reviewed runtime SHA-256
`f94333368b80761494abc6edd95464f9c3de0c1020289c57d888347ae0072ca0`:
fair-helper canonical exclusion — tenant-filtered LEGACY NOT IN nonnull;
latest timestamp — LEFT LATERAL attempted_at DESC,attempt_id DESC LIMIT1.
При nonnull attempted_at это эквивалент MAX timestamp; missing attempt даёт
NULL, cooldown24h/future checks и stable order сохранены. Tie identity
согласована с отдельной existing latest/transient classification.
Fallback/caps не изменены; independent semantic review PASS.
Root сообщил35 focused checks (14 PostgreSQL +21 unit) PASS на final code,
включая attempted anchor,23h/24h и tie-ID transition. Actual-table selector/
EXPLAIN gate после bootstrap ещё выполняется; deployment не подтверждён.

## Actual-table predeploy gate

Snapshot `55358:55358:`,20:13:44 UTC: source0/writes0, missing EOK0 после
bootstrap. limit3 за8.592 s: old81/06.09/CancelFailure первым,
new01/03.10/EOK вторым, recentFAILED77/29.09/EZK третьим.
limit60 за19.406 s:35 historical +24 new EOK +1 recentFAILED;
60 unique keys, hard24 new-key cap проверен по полному списку.
Два запуска вместе исполнили8 bounded SELECTs, EXPLAIN roots Limit.
Proof SHA-256
`f65107109d4b7dd662f96dbca247bda4ad331c991aed4dba29d9d17fb24447ec`.

Final-hash focused35 checks, Ruff/mypy и21 local unit PASS. Independent
predeploy review PASS: разрешён один bounded rollout и <=3 STANDARD live
selections.19.406 s — измеренный overhead, не speedup/SLA; прежние8.447 s
относятся к другой очереди и не являются сопоставимым baseline.
Cooperative yield может завершить run до исполнения всех3 keys.
Production deployment/live/operations receipts подтверждены ниже.

## Final release verification

Code backup20:15:58 UTC SHA-256
`524ee288460cce6c8028877ad53e3da4299504a3b45bac1359a73769b2c13c62`;
API/worker images rebuilt, API up, web unchanged. Host13/API1/web3/worker1
hash gates PASS, HEAD `20261004_03`, migration отсутствует.

Live20:16:51–20:17:26 UTC: selected3/attempted3, standard order
81/06.09/CancelFailure,06/03.10/EOK,07/03.10/EOK. Все NO_DATA,
exact response SHA/journal/audits проверены, canonical=false, versions0,
variant intake отсутствует. Между staged snapshot и live background workers
обработали5 keys, поэтому вторым стал06 вместо01; selection не подменялась.
Live proof SHA-256
`59802fc392c661c46d818d95dfb3a8843867fbd11cc09dcf5011a4f3d61031ab`.
У трёх live keys не было предыдущих attempts: их local immutability check
вакуумен. Отдельный typed proof подтвердил50 distinct сохранённых S184/S185
attempts: expected50/actual50, missing0/mismatch0. Tenant consistent RR,
aware clock, source0/writes0; saved-file SHA и sorted per-ID expected/actual
canonical row digests проверены. Scope только `RECORDED_S184_S185_ATTEMPTS_ONLY`,
не вся история БД. Helper Ruff/compile PASS. Proof `s189-originals-proof.json`,
SHA-256 `fcbaf82b614367fe7485917b4333f7055022ace3329a00a92124fd2e8ef0176c`.

API20:19:03 UTC: health200/auth401, paper828 matches/100 returned,
3727.377 ms, no-store/default scope/UNKNOWN. API proof SHA-256
`f65d4770e5b1c4a6212316ec008a2ac7e7b0dc23ca65242315ec97301495ac96`.
Operations20:19:04 UTC: DB3821181975 bytes/free262449061888 bytes,
test DB отсутствует, оба markersfalse, API/web OOMfalse; caps неизменны.
Operations proof SHA-256
`0d30f47a2ea5a3e2959b3eebade9823217d08c2b30ef37e53909c36069aef78c`.

Independent final review docs72/runtime/live facts PASS. Завершён bounded
DAILY5 scheduling slice; NO_DATA не закрывает canonical gaps. Суточная
capacity, national current-day hourly coverage и полнота ЕИС UNKNOWN.
Timestamped shared-lease measurement остаётся следующим отдельным срезом;
исторический backlog и pending targets не объявлены обработанными.
