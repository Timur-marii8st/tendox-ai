# S212 — восстановление характеристик выбранных карточек

Статус: VERIFIED 2026-10-06MSK. Owner root: operational helpers and documentation;
Astra independent read-only review closed. Existing S210/S211 runtime unchanged.

Two exact historical candidate refs from three tested pairs:
`0312100010026000041` v1 and `0160100008826000011` v1. Retained archives
are241712/637549bytes. Mutation freezes the metadata preflight SHA/exact refs,
rechecks source holds/tenant/archive identity and size before content load,
then uses deployed immutable `eis-position-v2-concrete` projector.
No EIS request/download/global rebuild. Worker2CPU/2GiB, short import lease,
statement5s/lock1s. No runtime/schema/image/cron/source-budget change.

## Result and verification

21:18:52UTC: two projections/two matching `EIS_POSITION_PROJECTED` audit events,
one position each. Retained ZIP/member/XML SHA checks PASS. Canonical row digests
unchanged. Replayfalse for both refs, projection/audit counts unchanged.
Recovery plus verification/replay590/129ms. Review closed before mutation.

Six API/direct same-clock identities PASS: candidateSAVED_PROJECTION/legacyfalse.
HTTP27–150ms/direct77–167ms. Six auth/tenant/ref/index negatives PASS.
Next Action+compiled SSR6reads86–199ms/5negative errors PASS, source fields/SHA
and UNKNOWN labels visible; analog797ms/104buttons. Browser visual NOT_PERFORMED.
Reads source0/jobs0/DBwrites0; explicit recovery separately writes two projection
and two audit rows. No archives downloaded to laptop.

12/4/3rows remain UNKNOWN. Pair1 paper towels versus office paper has12unmatched
names. Pair2 has3unsupported/incomplete shapes and1unmatched name; pair3 has3
unsupported/incomplete shapes. XML includes minimum500/greaterOrEqual/unitШтука;
current policy deliberately rejects ranges. Qualitative units can be absent,
instructions differ. Full technical/profit/participation/coverage UNKNOWN.

Ops21:19:06UTC DB5087009815/free257170878464bytes, health200/head20261005_01,
testDB0/markersfalse. API1GiB/web768MiB/worker2CPU2GiB, budgets unchanged.

## Evidence on VPS

Private0600 `/var/lib/eis-browser/research/rejected/`:

- `s212-legacy-repair-preflight.json` SHA256 `b4bac10b5bc35f9806ab7d86f9563ff6b7bb927d94dfb685977497b93bd9a425`.
- `s212-legacy-repair-proof.json` SHA256 `271a1294bd763b7c5a832f8550829c6616eab547d49b40f099890b29e2b88555`.
- `s212-final-characteristic-live-proof.json` SHA256 `283f671f79640dd1db3abfb5db4417a0931a17d3f590c5ed763a66f14b8f736f`.
- `s212-final-operations-proof.json` SHA256 `5525c6885599814aca62ada6c379faa932ba8a1e072615477447b37eaaf9079a`.

VPS state `s212-web-regression-proof.json` SHA256
`34855c2b5130a8157fd3a5de2bd37a8107f0e41a6ecf25b309a04fdb13769c10`.

Next S213: recorded numeric range observations with explicit unit/instruction
and bounded Decimal. A review found old projections cannot distinguish absent
opposite bounds from malformed source text; preserve raw/presence evidence under
a new projection version before supporting one-sided ranges. Actual profit
requires a valid complete supplier quote and expense data.
