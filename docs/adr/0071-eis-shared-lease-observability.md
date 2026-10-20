# ADR-0071 — bounded shared import-lease observability

Статус: **DEPLOYED / VERIFIED BOUNDED OBSERVABILITY**.
Дата: 2026-10-05, S190. Owner ADR/high-risk review: Astra; scripts/tests: Sol;
read-only observation helpers: source_limits; rollout/gates/docs: root.

## Цель и неизменные границы

Общую capacity невозможно вывести из несопоставимых wrapper logs.
Добавить одинаковые timestamped observations для corpus, priority, documents
и223 wrappers. Lock/dispatch/marker semantics, source/resource budgets, cron,
tenant policy, worker stdout, API/web/schema остаются неизменны.
Это operational evidence, не source receipt, audit или доказательство freshness.

## Event contract

Stdlib host helper и sourced shell helper пишут отдельный tenant-scoped JSONL.
Каждый event содержит schema version, tenant, whitelisted actor/lane/operation,
run UUID, phase, timezone-aware UTC timestamp, monotonic_ns и host boot hash.
Phase enum: dispatch_start, import_wait_start, import_acquired, work_start,
work_finish, dispatch_finish. Optional bounded result enum, integer exit code
и signal enum описывают success/idle/busy/timeout/error/interruption.
Отсутствие work/import phases допустимо для probe/idle/busy runs.

Запрещены произвольный reason text, argv, command line, environment dumps,
source URLs, token, request/response payloads и worker stdout/stderr.
Метаданные проходят whitelist/length/type validation; неприемлемый event
отбрасывается, а не отражается в log через exception text.

## Resource и failure behavior

Fixed private state directory, безопасное tenant filename, restricted permissions.
Line<=2KiB; current<=8MiB и previous<=8MiB. Append/rotation атомарно защищены
отдельным logger nonblocking flock; contention/failure не вызывает retries или
ожидание source worker. Никакого unbounded directory scan/read.

Logger failures подавляются без изменения saved worker exit code, lock wait,
marker ownership и cleanup traps. Не менять release/unlock timing ради метрики.
Effective2026-10-05: только priority/documents foreground flock waiter reaping
может быть исправлен, если TERM tests подтвердят прежний orphan/cleanup risk;
допустим existing223 pattern asynchronous wait + kill/reap. Delta записывается
отдельно с regression evidence. Источник правила — local wrapper contract,
не внешнее правовое правило. Explicit lease unlock/release, worker termination
policy и Docker cancellation не меняются.

## Интервалы и UNKNOWN

Wait duration вычисляется только из matching import_wait_start/import_acquired;
work duration — work_start/work_finish. Run/boot должны совпадать, monotonic
порядок валиден. UTC служит provenance и размещению интервала во времени;
wall-clock drift проверяется относительно monotonic duration.

Effective2026-10-05 operational quality assumption: допустимый drift не больше
max(2 seconds,1% matching monotonic duration). Превышение переводит affected
interval в UNKNOWN; missing phase затрагивает соответствующий interval,
repeated phase делает run inconsistent. Это local observation assumption,
не внешнее правовое правило. Lower-bound held требует тех же same-boot/order/
drift checks и не становится exact occupancy при успешной проверке.

Import-acquired → последнее событие до фактического FD close — только
`OBSERVED_HELD_LOWER_BOUND`. Work time не равно lease occupancy. Без явного
release receipt точную длительность удержания не заявлять. Missing/censored/
out-of-order/cross-boot/drift intervals остаются UNKNOWN. Retention rotation
может обрезать run; отсутствие events не доказывает отсутствие execution.
Полностью silent logger failure нельзя обнаружить по пустому файлу, поэтому
полнота observations сама по себе не становится PASS.

## Acceptance

Linux source-free stubs: success/idle/probe/busy/timeout/worker error/TERM,
exact saved exit status, no foreign marker deletion/no waiter leak;
nonblocking logger failure/rotation/secret rejection and bounded retention.
Independent review + script backup/hashes; API rebuild/migration не требуются.

Не менее15 минут наблюдать ordinary cron без extra source dispatch/reset.
Отчёт разделяет complete/censored runs и wait/work/lower-bound held intervals.
Shared occupancy — union наблюдённых интервалов, clipped к horizon, не сумма
пересекающихся длительностей. Не наблюдённые lanes, scheduler delay и источник
запросов не выдумываются из timing. Queue age читается в отдельном tenant
read-only snapshot с clock/IDs. Sample не является суточным/national SLA;
capacity/freshness UNKNOWN сохраняются, пока их evidence недостаточно.

## S190 verification before rollout

Astra runtime/logger/deployment review completed; observer horizon/file/result
corrections applied by source_limits/root. Linux source-free gate:54 PASS,
network disabled,05:38:31UTC5Oct. Observer synthetic checks14PASS.
The first Linux gate found priority TERM-before-trap race. Narrow wait traps
now precede owned marker creation and are reset after import acquisition;
priority/documents reap their own waiting flock child. Corpus original signal
policy retained. No active Docker cancellation or explicit unlock introduced.

Rollout05:39:57UTC5Oct script-only:6scripts/2tests/6docs, host20hashPASS,
backupSHA d0019725e9646bff357ff9f6b75e20cf36d64074ddd86cfb96744de205352b21.
Finalobserver15selfchecksPASS including lane filtering, terminalresultonce,
safe boundedcapturedfilebytes. Linux-platform logger mypyPASS.
Ordinarycron915s05:40:32–05:55:47UTC:21complete runs/0censored/0inconsistent,
4lanesrepresented. Heldlowerboundunion557.018s; waitmax5.731s. IDLE18 means
noimport/workphases, not missing-worker failure. CorpusprocessERROR1 is generic
nonzeroexit; lateststdoutcooperativeyield cannot be exactly timestamp-bound.
No source capacity/national SLA inference. Full proofs/limitations — docs73.
