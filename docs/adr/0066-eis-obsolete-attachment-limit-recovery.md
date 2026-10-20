# ADR-0066 — bounded recovery obsolete attachment-count failures

Статус: **DEPLOYED AND VERIFIED / API AND OPERATIONS PASS**.
Дата: 2026-10-04, S182. Owner ADR: Astra; CLI/gates/deployment: root;
bounded recovery module/tests: Sol.

## Основание и scope

Read-only baseline16:35 MSK выявил9 uncompleted windows с прежним
`ATTACHMENT_COUNT_LIMIT`:7 date windows regions25/78 и2 hour windows
region77/EOK. Source calls0. S166 уже допускает bounded metadata до4096
attachments; превышение текущего cap имеет другой reason
`ATTACHMENT_METADATA_COUNT_LIMIT`. Старые отказы могут быть повторены без
ослабления parser/source safeguards. Baseline9 не гарантирует, что все9
останутся due к моменту запуска.

Добавить explicit manual CLI repair до3 windows/run, без automatic lane,
cron, regions/families, budgets или новой migration. Используются существующие
sync/browser/journal и global source leases; cap4096 и остальные safety gates
не изменяются.

## Eligibility и race

Только planned tenant windows, чей exact latest attempt имеет outcome FAILED
и reason ATTACHMENT_COUNT_LIMIT. Latest определяется по timestamp + immutable
attempt ID. Cooldown не меньше24h, future attempt не due. Window key — строго
valid +03:00 date/hour; весь интервал уже завершён. Legacy canonical checkpoint
исключает window; variant transport не является canonical completion.

Перед source operation повторно проверить latest immutable ID, eligibility и
completion. Superseded/completed/not-due candidate даёт typed skip и source0,
не «исправлен». Не принимать произвольные неплановые keys как новый scope.
Текущий ATTACHMENT_METADATA_COUNT_LIMIT, другие parser failures и NO_DATA
не входят в этот repair selector.

## Execution и result

Весь run соблюдает существующий priority/import lease, resource и transport
budgets. Перед каждым window повторяются обязательные resource checks;
DB failure останавливает run. Source response используется целиком, без subset
или filename-based выбора. Intake сохраняет существующие strict bindings,
variant partial pipeline и consumer holds.

Typed result разделяет selected/attempted/skipped и реальные outcomes.
NO_DATA не означает отсутствие закупок во всей ЕИС; PARTIAL не становится
SYNCED и не закрывает gap. Старые attempts/audits неизменны, новые evidence
имеют точный tenant/window/response binding. Metadata admission не означает
скачивание всех вложений, extraction PASS, supplier eligibility или участие.
Coverage/freshness остаются UNKNOWN.

## Gates

Tests: exact reason/current4096 exclusion; tenant/planned scope; aware24h и
date/hour completed interval; deterministic latest ties; pre-source superseded
и canonical-completed skips с0calls; limit1…3; resource/DB stop; full source
and journal outcomes; partial/replay counters; отсутствие cron/selector changes.
После isolated gates допустим bounded controlled run с неизменными budgets
и явными фактическими receipts. Результат production run приведён ниже.

## Final bounded review

Исправлен wrapper marker gap: EXIT/INT/TERM traps устанавливаются до marker
touch, ownership flag остаётся0 при ожидании чужого priority lock; priority и
import flock ожидаются асинхронно с kill/reap при interruption. Чужой marker
не удаляется. Linux process tests покрыли marker publication, import wait,
busy owner и worker failure cleanup.

Module повторяет полный eligibility predicate и exact immutable candidate
при operation time (начальное aware now + monotonic elapsed), до source call.
Typed reports проверяют source SHA для success/NO_DATA, membership/order,
counts, time и checkpoint consistency. Не найдено новых release blockers.

Root подтвердил Linux219 PASS / PG32 PASS, Ruff5/mypy2 PASS, включая реальные
101 attachment metadata, original history, ties/hour boundaries и clock rollback.
Production read-only plan:9 eligible,limit3 и exact candidates;1.957 s,
EXPLAIN895.854 ms,source0/writes0. Proof SHA-256
`deb5bda65a87224ae3fb552de5934c322e4900f690bc831b028e8a387ba0e8e7`.
Release review **PASS**.

## Deployment и controlled live evidence

Root подтвердил deployment 2026-10-04 13:52:11 UTC: API и worker rebuilt,
host12/runtime2 hashes PASS, schema HEAD `20261004_03` без новой migration.
Предварительный code backup:
`/home/syurai/vibe-seller-state/backups/s182-before-20261004T135211Z-code.tar.gz`,
SHA-256 `d2928434beeca140aafe898b3f06c1f918c851c94bf238f2f0450ffa958eea1a`.

Deployed read-only plan:9 eligible /3 selected,1.969 s, EXPLAIN910.364 ms,
source0/writes0. Proof SHA-256
`4f0450c7bc40ce6882fff01f24831ff02b7abf8d6fa05d60b09b577dd1428697`.

В 13:55:56 UTC один wrapper run завершился `FINISHED`, exit0,39 s:

| Region / date | Outcome | ZIP | New versions | Maximum attachment metadata |
| --- | --- | ---: | ---: | ---: |
|25 /2026-09-25|SYNCED|1|59|193|
|78 /2026-09-23|SYNCED|3|271|240|
|25 /2026-09-21|SYNCED|1|68|278|

Итого398 versions /5 ZIP, new events0. Проверены фактические canonical SHA,
journal и audit; все9 прежних attempt rows неизменны,6 окон остаются eligible.
Maximum metadata рассчитан только среди newly persisted rows, связанных с
соответствующими window/SHA. Это не число скачанных attachments и не доказательство
полного покрытия ЕИС; coverage/freshness остаются UNKNOWN.

Live proof: `/var/lib/eis-browser/research/rejected/s182-live-proof.json`,
SHA-256 `9f95e5181494fea24b2acbd0ec573a88e88716b15788430eeaafd8f0fe8352c1`.
Linux219 / PG32 gates PASS. Deployment и controlled run verified.

Final API check 13:56:58 UTC: health200, anonymous401, no-store;
coverage/freshness UNKNOWN, source0. Cached44 current132982:
paper2558 matches /8.390 s, server5373 /14.733 s. Cached223 current2887:
paper59 /302 ms, server185 /615 ms. Это отдельные измерения, не SLA.
Proof: `/var/lib/eis-browser/research/rejected/s182-api-proof.json`,
SHA-256 `90edca84d9b9338939f585ce17fb27379e0fd729c8a14db88841d0f00db64f8c`.

Final operations check 13:57:37 UTC: test DB S182 удалена, оба priority/source
markers отсутствуют, source0. Proof:
`/var/lib/eis-browser/research/rejected/s182-operations-proof.json`,
SHA-256 `63825cc567996e32e1d05c95d3982b0f99c638b107b09778872785724c922e04`.
Финальные API и operations gates **PASS**; ожидающих rollout проверок нет.
