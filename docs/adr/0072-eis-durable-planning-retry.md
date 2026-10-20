# ADR0072 — durable retry of completed-date planning

Status: DEPLOYED / VERIFIED BOUNDED PLANNING. Effective2026-10-05, owner root.
Dependency S190: corrected missing96 actualkeys, shared lease lowerbound observations;
source capacity/national freshness UNKNOWN.

Daily cron's one nonblocking import-lease attempt can be skipped. Replace it
with source-free planning retries every5minutes at4,9,...59. Corpus source-run,
priority/document/223 cron, lock order, CPU/memory/disk budgets stay as before.
One planner dispatch lease excludes duplicates. Existing corpus wrapper owns
the nonblocking import lease, invokes the existing bounded worker and plan CLI.
No browser transport on plan branch. No busy loops or worker cancellation.

Private fixed tenant cursor starts2026-10-02, the S190 proven rolling gap floor.
Each pass plans at most3completed MSK dates×99candidatecodes×5families=1485keys.
Cursor advances only for exit0 + strict PLANNED/expected/whole scope SHA response.
Receipt binds tenant, actor, first/last day, expected/new count, aware UTC and digest.
Atomic replace with fsync; corruption/future cursor blocks instead of skipping dates.
If busy/failure/TERM before completion, cursor stays; existing31-target atomic
target+audit batches can be repeated via ON CONFLICT DO NOTHING. A crash after DB
planning but before cursor commit causes an idempotent repeat. Downtime>3days is
drained in successive <=3day chunks from last successful day, with no date jump.

Cursor receipt proves planning completion only. It is not canonical ingestion,
regional registry, source completeness, document coverage or freshness evidence.
Initial historical dates before2Oct remain outside this repair contract.
Source/resource/permission policy and prior attempts/NO_DATA are not modified.
Linux stubs validate failures/races/atomic cursor, and live tenant RO proof
must verify exact keys, added target audits, repeat0 and preserved attempt digest.

Gate06:16:03UTC Linux74PASS source0/networknone, planner20 + existing54lease/metrics.
Ruff/Linux-platformmypy/bashsyntax PASS. Controlled live verification completed below.

Source0controlled06:22:36–46UTC partial31batch6new + wrapper90remaining targets,
exact1485keys/0gap/96exactaudits/duplicateplan0/cachedIDLE.15982oldattempts and
1389oldtargets rowSHA unchanged. Cursor receipt commits after exactcomplete plan.
Cron06:23:57changed exactly1plannerentry to4-59/5; sourcebudgets/cadence unchanged.
S190 manualdefaultEFsuffix produced297falsegaps; recent393retracted, domain-key
census/reconstruction verifies96EOKgap. Originalproofs preserved, docs73corrected.
No canonical/source completeness/nationalfreshness/profit claim. Evidence — docs74.
