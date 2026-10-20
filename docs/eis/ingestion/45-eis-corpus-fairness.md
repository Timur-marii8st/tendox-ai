# Fair retry lane for the EIS corpus queue

Date: 2026-10-03. Scope: read-only selection of already planned 44-FZ corpus
windows. Source calls, quotas, concurrency, cadence and persistence are unchanged.

## Problem

The historical queue orders unattempted windows before attempted windows. With a
large backlog, a recently corrected source window whose latest observation is
`FAILED` can remain behind all unattempted history even after its 24-hour retry
cooldown. This delays current useful evidence without certifying that the failed
window is complete.

## Selection contract

One SQL statement runs in a tenant-scoped consistent-read transaction and builds
two lanes:

1. A recent-failure lane receives `min(ceil(limit / 5), 12)` slots. Candidates
   are planned tenant windows dated within the seven completed Moscow calendar
   days, whose latest attempt is `FAILED` and at least 24 hours old. Completed
   feed windows are excluded. Ordering is window date descending, latest attempt
   ascending, then window key.
2. The existing historical queue fills every remaining slot in its prior order:
   oldest/unattempted observation, window date descending, then key. Keys already
   reserved by the first lane are excluded.

The historical lane applies its existing `ORDER BY` and a dynamic `LIMIT` before
assigning final lane positions. Position numbering therefore touches at most the
global caller limit rather than sorting the full historical target set with a
window function. Production selection time still requires separate measurement;
this query shape alone is not a throughput claim.

The final tuple remains unique and never exceeds the caller's global limit. For
`limit=1`, one due recent failure may use the pass. A newly recorded attempt puts
that key back into the existing 24-hour cooldown, allowing other work to progress
on the next pass.

The recent lane ranks attempts by `(attempted_at DESC, attempt_id DESC)` before
joining planned targets. It therefore reads recent attempts to find the exact
latest state and does not add another correlated scan over the full worklist.
The historical lane retains its existing query semantics.

## Evidence and limits

Synthetic isolated-PostgreSQL coverage includes a large unattempted backlog,
15 due recent failures, latest-not-failed, cooldown, completed, other-tenant and
old-failure exclusions. It verifies the 20% share, cap 12, stable ties, fill,
global dedup/limit and no writes by the selector.

Selection only schedules a retry. A failed window remains `UNKNOWN` until a
successful source response is atomically ingested. No source coverage or
throughput claim follows from this policy.
