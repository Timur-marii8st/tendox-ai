# ADR-0056 — проверка каталога223 и очереди обновления

Статус: **ACCEPTED / DEPLOYED**, S173, api/worker/web HEAD `20261003_05`.
Дата:2026-10-03. Owner:Astra; runtime owner:root. Зависимости:ADR0055/docs54–56.
Accounting-edge исправлена и перечитана; root сообщил15source tests PASS.

## Решение

PUBLIC_KLADR_SELECTOR проверяется раз в24h под существующим import lease;
FAILED/REVIEW_REQUIRED дают cooldown1h. Один normal-TLS Chromium GET exact URL,
streaming cap512KiB/timeout45s/no redirect admission. Exact closed DOM/identity
contract прежний. Malformed response/удаление membership не заменяют каталог.

Immutable tenant journal сохраняет observation time/outcome/HTTP/SHA/reason;
accepted имеет tenant FK на retained catalog. Same SHA даёт новое наблюдение
без изменения catalog row. Exact attempt replay идемпотентен; изменённые
evidence/reason/time отклоняются. Rejected body bounded и связан SHA. SQL
checks закрывают NULL-проходы; FORCE RLS/immutable/downgrade history guard.

Каталог выбирается по последнему ACCEPTED observation, не первой записи bytes.
A→B→A допустим при одинаковой membership; если B добавил codes, возврат к A
требует removal review. Subset check/accepted append используют один advisory
lock /223-regions. Bootstrap fallback — до первого accepted journal observation.

Wave сохраняет catalog SHA/frozen dates; новые codes применяются к следующей.
Coverage различает first observed time, последний success recheck SHA wave,
latest accepted SHA/time и последний check outcome. Ошибка не стирает success;
новый SHA не освежает старую wave.

## Throughput и fairness

Единый cron каждые10min (1/11/21/31/41/51) заменяет старый. Сохраняются32windows/
600s start budget,180s bounded started-window timeout,2GiB worker, per-window
DB100GiB/free40GiB, sequential transport/spacing и общий44/223 import lease.
Overlap даёт bounded wait/skip, не параллельную загрузку.

При limit>=3 первыми идут один fresh_due и один retry_due, затем unseen,
остаток retries/fresh без дублей. limit2 сохраняет retry/unseen. Fresh6h/retry1h
— due policy, не SLA. Новая wave после first sweep и смены source day больше
не ждёт24h от создания; catch-up<=2days, старые gaps сохраняются.

192windows/h — ceiling. Для900окон/6h нужно150windows/h без дополнительных
retries. Batch266–281s не доказывает sustained throughput/отсутствие contention44.
Нужны actual counts, POST/poll/GET, overrun/skip/lease и lag. Ошибка после начала
catalog GET должна учитывать запрос даже при outer timeout/cleanup error.

## Проверка и границы

Root сообщил33isolated PG,62focused,source13,runner6, mypy/webbuild PASS.
Actual public GET19:28:12UTC дал200/22514bytes/90codes с прежним SHA
`b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`;
proof `/research/regions/s173-public-probe-20261003T192813Z.json`.
На момент исходного review production journal ещё не заполнялся. Latest accepted
selection, SQL/FK/RLS/immutable/replay, wave freshness и lane order прочитаны.
Outer timeout/cleanup error теперь использует retained request_started flag,
который выставляется непосредственно перед page.goto; startup0/dispatch1.
Открытых blockers в проверенном bounded slice не осталось; свежие итоговые
stage/deployment gates выполнены root, результаты ниже.

## Deployment evidence

Root подтвердил backups/admission/cron/first-run и S173_DEPLOY_DONE.
`/var/lib/eis-browser/research/regions/s173-admission-20261003T193743Z.json`:
сохранён один прежний catalogSHA, добавлены1check+1audit,900targets/1wave
не изменились. Replay0writes, admission0newsourcecalls. Cron заменён только для
точной command entry на1/11/21/31/41/51; backup/idempotence проверены.

Первый32window run217.6817s:41POST/9GET,9SYNCED/23NO_DATA/0errors,
69newversions. Early fresh50lot-cancellation и31unseen реально выполнены.
Это один batch, не sustained SLA.33PG+69focused+ESLint/build/mypy/RuffPASS.
К19:42:02UTC read-only API показывает176/900terminal,index537;
следующий automatic cron уже работал. Whole coverage/freshness UNKNOWN.
Полный900sweep,retention,44parity,прочиеfamilies и stablelotassociation не закрыты.

WholeEIS coverage/freshness UNKNOWN. Catalog check не доказывает актуальность
всех partitions. Bounded retention,44parity,другие223families и stable lot
association остаются отдельными незавершёнными срезами.
