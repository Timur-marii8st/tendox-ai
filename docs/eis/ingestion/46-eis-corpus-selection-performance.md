# EIS corpus historical queue selection

Date: 2026-10-03. Scope: read-only SQL shape for selecting already planned
44-FZ corpus windows. No migration, index, persistence, source request, quota,
concurrency or scheduler behavior changed.

## Bottleneck

The S167 selector preserved the historical queue through a correlated
`max(eis_sync_attempts.attempted_at)` scalar expression. PostgreSQL evaluated
that lookup while considering each tenant target. With roughly 147 thousand
planned targets, a fixed-clock production observation took about 26 seconds.
Removing a full-set `ROW_NUMBER` did not remove this dominant correlated work.

## Query contract

The historical lane now creates one tenant-filtered CTE grouped by
`window_key`, with `max(attempted_at)` exposed as `latest_at`. Planned tenant
targets `LEFT JOIN` this relation once. The existing conditions then use the
joined column:

- `NULL` means unattempted;
- `latest_at <= checked_at - 24 hours` means due;
- newer and future attempts remain in cooldown;
- completed windows remain excluded independently;
- ordering remains unattempted/oldest attempt first, then date descending and
  key ascending.

The recent-failure lane still ranks exact attempts to determine whether the
latest outcome is `FAILED`. Its seven completed Moscow days, bounded slot share,
stable ordering and completed-window exclusion are unchanged. Both lanes remain
one SQL statement in one tenant-scoped consistent-read snapshot, with dedup and
one global result limit.

## Verification

The isolated PostgreSQL gate retains the mixed large backlog and repair-lane
cases. It additionally verifies that an old failure followed by a future
`NO_DATA` observation is excluded, a due `NO_DATA` window remains eligible in
the historical lane, and another tenant's later observation for the same window
key cannot affect selection. Repeated selectors remain read-only.

Deployment requires a fixed-clock before/after equality comparison and measured
production selection time under the existing operational locks. The grouped
query shape alone is not evidence of a speedup or full-EIS SLA.

## Runtime evidence root, 2026-10-03

64 isolatedPG и279Linuxfocused tests passed; Ruff/mypy и независимый review
passed. Same-clock frozen production snapshot:147364targets/8736attempts.
Old selector27.094537s, grouped selector7.470841s; exact60keys совпали и
счётчики базы не изменились. Это примерно3.6раза в данном измерении, не SLA
и не измерение времени поиска товара. Deployment/API health прошли, SQL SHA
в repo и image совпал, isolatedDB удалена.

Proof VPS:s168-selection-proof-20261003T085110562921Z.json;
SHA258011fdc578f3ff8f501574ba28c83fb599d0ad5dfbde6becd33bd4f380607a.
