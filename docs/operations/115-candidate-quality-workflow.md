# Candidate quality workflow

**State: INSTALLED. Exact-payload activation approval: `RECEIVED`.
Bounded local-provider M1: `COMPLETE`.**
The local provider produced a complete typed technical receipt for one sealed
candidate; independent reviews passed the preparation and installed-run
evidence, and Root accepted M1 for the bounded local-provider scope. This does
not establish hosted CI, application deployment, or acceptance of later M2â€“M5
work. See the
[program](../product/16-improvement-program.md),
[M1 evidence](114-reproducible-quality-gates.md), and [ADR-0107](../adr/0107-candidate-triggered-quality-gate.md).

## Verified candidate receipt

Run `release-20261007-121512-94dd68d23b4a` completed 2026-10-07 12:15:12â€“12:27:28
UTC with status `PASS`, `complete=true`, and 50/50 stages passing. The typed
receipt is in `tmp/improvement-program/provider-v5-evidence/release-receipt.json`.
It is bound to policy `2026-10-07.2` (canonical SHA-256
`f4d17fa49f6550a5a476e6d10ba8e4c425a9323e6a8d7a033953bb7296ba1efe`), expanded
inventory SHA-256 `b9e9494fffdaef763d1fe318d8754495c1986676af0253dcf1fed8091cbb8ce3`,
and a sealed 1,189-file worktree snapshot: archive SHA-256
`88950ba5bbb6d9cc38d67389f7571f404047045d94ecf68691f8e9c9e0e9e2e1`, tree
SHA-256 `40d04da9f8f52ae9a672fbe4b3b383dfd708157d9116b30e23e55d944b7d5ea9`.

The unit collection was 3,302 tests: 3,275 PASS and 27 allowed skips. Nine
domain doctests passed. All 15 PostgreSQL groups passed 608 tests with zero
skips, and all 153 Node tests passed with zero skips. The combined Python JUnit
reports total 3,919 = 3,892 PASS + 27 skips; that total already includes the
unit, PostgreSQL, and doctest cases, so do not add the category counts to it
again. Ruff, mypy, web lint/build, and network-none API/web smoke stages passed.
The API image is
`sha256:12f41e054f4137e6032aa42ffd1f8929e74c5b42ad8e0cd831bf5d55d1ac606a`;
the web image is
`sha256:2cd6e22bf33c1d865cbfaf803e055bd9e40b2ecec9fc2dce28b188d70d6d5da0`;
the worker uses the exact API image. Nine owned disposable resources were
removed; the two accepted images were retained. PaddleOCR integration and
browser/E2E remain explicitly `NOT_PERFORMED`.

The receipt covers that original sealed archive only. This document was updated
after the v5 source was sealed; these documentation edits are not in the
receipt-bound archive and were not validated by that run. The independent
preparation audit is recorded in
`tmp/improvement-program/provider-v5-independent-review.json`. Its verdict is
`PASS_TECHNICAL_PREPARATION_ONLY`: the host typed verifier matched the sealed
source, policy, reports, and images; 89 bound report hashes and all 50 stages
were checked; and labeled live cleanup was independently inspected. It also
confirmed the Windows escaped-ID explanation: Windows subprocess output had
escaped Cyrillic test IDs, while the Linux collection and JUnit used native
UTF-8 IDs. This explains the earlier v4 expected-ID mismatch; it does not
change or combine the v5 test counts. That preparation audit left M1 incomplete
at the time; installed-run evidence and bounded acceptance below supersede that
status.

## Provider preparation and activation

The supported installed submission command is:

```text
python3 -B <installed-release>/run_release_gate.py --source-bundle <tar.gz> --expected-sha256 <64hex> --state-root <private-dir> [--policy <trusted-policy-path>]
```

Use `-B` on every trusted helper/verifier Python invocation as well. Bare
`python` may create `__pycache__` files beside the trusted release; do not widen
the immutable-file allowlist to accommodate them. Runs are stored under
`<private-dir>/runs/<run-id>/`. The policy path, when provided, must resolve to
the fixed trusted installed policy outside the candidate; candidate content
cannot select or weaken policy. Submission runs the full policy automatically,
with no stage-selection or skip options. The receipt verifier validates
source, policy, scope, reports, and image identity; a status string or
caller-provided JSON is not a receipt.

Package v4 passed the actual default-server preparation preflight; its plan
SHA-256 is
`b025eecb48cf5b0ea5c7b434b9fb2d4f0a83bc873656c81297a0e1ed7b996f50`, bundle ID
is `03abb8b05808fd2b679a0b5557e5ae917e976ad761e6451427d273d7d55eb2aa`, and
the installer SHA is
`b6e1b827577c98ab45425d8db2e90c693cc0531ce1fa2831f02611a335e0e282`. The
preflight verified the package copy and references; its receipt records the
pre-approval state `installed=false` and `activation_approval_received=false`.
That historical package receipt remains unchanged. Human approval for the exact
activation action payload (SHA-256 prefix `858e`) has since been received; this
approval is separate from the package receipt. The plan hash binds the payload
but does not itself grant approval. The server activation record now reports
`INSTALLED; WORKFLOW_ACCEPTANCE_PENDING` for this exact bundle and plan. Record:
`/home/syurai/vibe-seller-state/quality-provider/activations/b025eecb48cf5b0e-e1e59ccdfef2`;
the local evidence copy is
`tmp/improvement-program/provider-activation-v4-result.json`. It lists the two
operational guard paths and `runtime_changes=[]`.

Independent installed identity review passed with verdict
`PASS_INSTALLED_IDENTITY_ONLY_WORKFLOW_ACCEPTANCE_PENDING`. Evidence is
`tmp/improvement-program/provider-installed-independent-review.json`, SHA-256
`f0104f9f0ac60ba72c88a4ea5b399d58afa01a2d65e764ea7d5d0c3210651ae1`. It
verified the exact six-file release, installed manifest and pointer, guard
hashes, and activation record; no application deployment or runtime changes
were reported. The installed guard mode was observed as `0664`; the audit did
not independently record its pre-activation mode, so no mode-change conclusion
is made. This review is identity-only and leaves workflow acceptance pending.

The immutable provider release has six files: three controller files
(`run_release_gate.py`, `release_gate_receipt.py`, and `release_gate_policy.json`),
two pinned Docker tools (Buildx and its Docker client config), and `bundle.json`.
The two host-side legacy refusal guards are under `HOST/scripts`; `current.json`
is under `PROVIDER_ROOT`. They are outside the immutable release directory.
Controller state and receipts live in a private state root, separate from
candidate source. Focused preparation checks passed 20 controller refusal tests
and 16 installer tests; these do not replace installed-path acceptance.

A fresh six-file bytecode probe passed with the supported `python3 -B` command
and `run_release_gate.py --help`. Evidence is
`tmp/improvement-program/bytecode-bundle-probe-v1-result.json` (result SHA-256
`70310b721cdae63b324492d14ded89ee7fccb4c0b3378d4d2d874b4e7bbb7c9e`;
probe script SHA-256
`e8947e24ec19a705e1a11e5ee8df22547c5114e9c418f259b35fe4e8027a52d5`). The
before/after inventory confirms the exact six-file scope and unchanged file
hashes; no bytecode files were added, and the probe itself performed no
activation. This probe report is explicitly `NOT_INSTALLED` and
`NOT_FULL_GATE`; it does not establish installed-provider proof or complete any
required installed run.

After activation, the read-only refusal probe was run against the installed
guard directory `/home/syurai/vibe-seller/scripts` using the reviewed guard
hashes. All four checks passed: browser `install`, browser `install_locked`,
browser `enable_init`, and CAPTCHA `install` refused before any side-effect
boundary. The probe harness SHA-256 is
`4751da72cd68ac36e35c3eaa4d0c88a39fc1b9b04b85d28583f3cd8364ed9d9c`. The
persisted actual stdout proof is
`tmp/improvement-program/provider-installed-refusals-v4-result.json`, SHA-256
`d24e31d04d9f07dae1f53033f3786687e3f71747834699c29e914a566b8674cd`; it records
scope `POST_ACTIVATION_INSTALLED_READ_ONLY` and side effects
`FORBIDDEN_AND_NOT_REACHED`.

The installed sequential submission wrapper was independently accepted for
launch only (`ACCEPT_LAUNCHER_ONLY`). Wrapper SHA-256 is
`177319ba3caadcfcd4fcf6a318658f1af4dc1e06d7860bf62c50f5ea0dd9c82e`; review
evidence is `tmp/improvement-program/installed-launcher-independent-review.json`,
SHA-256 `cbcfe6055d1255a11720d44fe62f78fa6fe5e82a84653ad3fa511b52c6682b7d`.
It binds exact source archive `88950ba5bbb6d9cc38d67389f7571f404047045d94ecf68691f8e9c9e0e9e2e1`,
the installed release, and sequential ordinals 1 then 2 with `python3 -B` and no
stage or skip selection. This review accepts launch boundaries only; it does
not accept a full workflow run.

Ordinal 1, `release-20261007-135738-fe79f5d192ca`, passed as a complete
installed run. Its receipt SHA-256 is
`b95eef8f8957282ed8a663cbcc2ae5de42c4577080b0ec143d0c5e68b3864e7a`. The
independent per-run audit verdict is `PASS_INSTALLED_FULL_RUN_ONLY`; it
independently checked 89 report hashes and receipt cleanup. Evidence is
`tmp/improvement-program/provider-installed-run-1-review.json`, SHA-256
`38f4457e0c0c04a2647595bd9ced32cb45a18c782af0f866ecdf52a3e40b16ad`. The
per-run audit does not assign overall M1 acceptance.

Ordinal 2, `release-20261007-140948-4cdf2036cdb2`, completed its controller run
2026-10-07 14:09:48â€“14:21:54 UTC; the wrapper finished at 14:21:55. It reported
`PASS`, `complete=true`, and 50/50 stages passing. The 17 Python JUnit reports
total 3,919 = 3,892 PASS + 27 known skips; this includes the 608 PostgreSQL
tests across 15 groups with zero skips. All 153 Node tests passed. Its receipt SHA-256 is
`9180e99a122270d53c8a02a19e03528699a88f39acce0703709e5958163a0c12`. Local
evidence is under `tmp/improvement-program/provider-installed-run-2-evidence/`;
the wrapper recorded controller exit 0 and matching pre/post installed bundle
proofs. The independent audit verdict is `PASS_INSTALLED_FULL_RUN_ONLY`; it
independently checked 89 report hashes and exact cleanup. Evidence is
`tmp/improvement-program/provider-installed-run-2-review.json`, SHA-256
`b5a896338afadb367c857381f23108843300c95452836f2ffcbf8f3540f64de6`.

This run's accepted API/worker image is
`sha256:df390b2046ae4edc433999f55f2be9fc61866fe7d7b692a2d8f362ce0e3ad66f`;
its web image is
`sha256:902d723c97914dd5bd489f361d86a58f2a304a58369c15c7641cc7df1844c7e9`.
The earlier preparation/recovery images remain evidence for this same candidate,
but are separate from these per-run image identities.

## Trust, promotion, and operator boundaries

The controller, verifier, policy, run state, and receipt directory are trusted
inputs outside candidate-writable mounts. Candidate source is sealed and
read-only in workers. Workers have no production credentials, state volumes,
production network, or Docker socket; they may use private task networks for
isolated services. Controlled dependency acquisition is separate from worker
execution. The controller alone creates and removes labeled test resources and
finalizes receipts.

A receipt proves technical readiness only. It is not deployment approval,
external-action approval, or approval for an exact payload. Supported mutating
paths must check the exact receipt and target under their mutation lease.
Legacy installed-base overlays remain fail-closed until an adapter binds the
base, patch manifest, effective tree, and resulting artifacts. Full-source
receipts cannot authorize overlays. Worker image identity and executable
host-script payloads must remain bound wherever supported paths execute them.

M1 acceptance requires four installed-path refusal checks and two complete
fresh installed-command submissions with independent receipt and cleanup
audits. All four refusals passed; both installed runs passed their per-run audits.
Root accepted M1 for the bounded local-provider scope after Astra's review found
no technical blockers. The refusal checks were not activation prerequisites,
and the local v5 receipt alone did not satisfy the installed-run criteria. An emergency
privileged override remains outside routine
promotion, must record actor, time, reason, exact payload and before/after
identities, recovery outcome, and follow-up verification, and never creates a
quality `PASS`. Historical v1â€“v4 failures and their repairs are recorded in
[M1 evidence](114-reproducible-quality-gates.md).

The v5 receipt is the current complete candidate receipt; its technical
preparation audit and the installed identity-only review passed. Package v4 is
installed; all four installed-path refusal checks passed. Both full installed
runs and their independent per-run audits passed. Git commit
`9bffe2c9e979aa922af340f8793a97786a0f28ef` preserves the reviewed 1,189-file
source snapshot. Exact-payload human approval is received. Bounded local-provider
M1 is complete; hosted CI, application deployment, whole-EIS acceptance, and
M2â€“M5 remain outside this acceptance.

## Exact production223 branch compatibility (prepared 2026-10-09)

The saved installed production manifest differs from the later M1 inventory.
The complete static map separates build/check support, regressions for installed
functions, and tests for uninstalled manufacturer, capture/benchmark and SERP-v2
storage features. Missing files are not repaired by successive gate attempts.

The separate release_gate_policy.production223.json binds all three exact
candidate content identities. Its complete applicable scope is 3,172 Python
tests, 9 domain doctests, 52 PostgreSQL modules in 14 groups and 127 Node tests;
the existing 27 named Python skips and two explicit optional-suite omissions
remain unchanged. Pinned build recipes, dependency/network isolation, report
hashes, tenant tests, exact ordered stages and guarded cleanup remain mandatory.

A separately reviewed controller/verifier diff adds exact branch binding,
legacy-flat documentation link/anchor validation and PG-before-Node execution.
Python and PostgreSQL workers must stop successfully before Node starts; Node
must stop before image builds. Default modern policy behavior is unchanged.
The prepared provider is a private versioned copy with the same reviewed Docker
assets. The active provider and both existing guards remain unchanged. A receipt
from the prepared version proves only its exact candidate under its exact policy;
it neither activates that provider nor authorizes a production deployment.

Full production223 v4 completed 48 mandatory stages in775.546s:3145unit with
27 exact known skips,9doctests,578PG and127Node without skips, images/smoke/cleanup.
Receipt SHA11dd4ff15906cb574c0a622c0299ea63d4566d5df6206a4bc032d08f00ab6526;
source archive SHA c6415267a4ec5340ef8be68266aea792d4b24a282874961347e4e0b03831102e.
Independent exactreceipt review accepted. Accepted source includes only223 behavior
fix plus required support; later pagination and paper fixes are separate diagnostics.
Prepared provider package50087eb19a2961565ff3d8467f1c4abd8c5cbb910deaf48978dbfc94daaccd62
passed the existing activator preflight. That initial provider-only request was
superseded by the reviewed bounded FULL_SOURCE release below. The activator uses
provider-only runtime_changes=[]; legacy overlay guards still refuse mutation.
The final exact release was approved and activation completed; application
installation failed as recorded below. No223 migration or post-fix search succeeded.
A provider-only approval cannot substitute for approval of application installation.

## Bounded production223 FULL_SOURCE promotion — activated; application FAILED

Owner root; owned `scripts/server-supplier-browser-rollout.py`, its existing
entrypoint tests and this release documentation. The existing rollout entrypoint
adds prepare/preflight/install/rollback modes pinned only to accepted c641… source
and receipt11dd… . The old overlay mutators remain unconditional refusals. The
trusted diff is separate from application bytes; no new guard or release system.
Receipt, exact target/artifacts,350host file identities, worker/admin route,
environment/resource contract and guards are checked under the existing mutation
lease. Installation uses recorded immutable API/web/worker images without rebuild.

Final adapter SHA1558b34e7cce71ded5736f4cc687c5feb1765c871dba84d03d0c6a90c76e3077;
activation package SHAc8588e9462455ef595a96d4cfdfa846dc22ba4078d277d23c79649435c96a3ee;
application plan SHA6b3e2032adb9ea2a0eee0bf7182a550331fd492bd2441f983ee52ce76677584a.
Private evidence is under `tmp/improvement-program/m2/production-promotion-20261009-v1`:
`exact-approval-request-final-v2.md/json`, final plans/package, trusted adapter diff,
raw JUnit and independent review SHA917c2ed73e1ed2e586b955363233b4487e31474ff5d1ae42c9001a1cbd062b70.
21final entrypoint+25unchanged gate+16activation=62distinct tests PASS0skip; repeated
runs are not added. Ruff/mypy PASS. Real server source/receipt/effective-compose
prepare and unchanged provider installer preflight PASS0.2389s. Last admission
observed6013837312B available memory and184031969280B free disk; install rechecks
at least4GiB/40GiB reserve. Existing verified backup requires DBsize+40GiB disk.

The exact request covers provider/adapter activation plus minimal223 installation
and the two77/05–06.10 purchaseNotice reprocess/search checks. The four host changes
are223 limits/models, one migration and already reviewed AST-equivalent SERP
formatting; other346host bindings stay unchanged. Later pagination/paper code is
excluded. Human exact approval was received as human-final-v2-option1-20261009.
The unchanged installer activated exactc858 in1.027s, runtime_changes=[]. Installed
application preflight passed0.746s. The attempted application installation failed;
provider/guards remain activated, application images/schema remain the prior version.

Recovery binds original immutable images/host bytes and the checked inverse
configuration, including retry after a failed inverse compose launch. Known stopped
API/web can be restored; exact DB must run. Widened CHECK/schema and source history
are preserved, never downgraded or deleted to force recovery. Old runtime retains
its4-archive intake limit; all future wider-history view compatibility remains
UNKNOWN. Missing containers/artifacts, DB/Docker/storage failure or forced host
termination can leave UNKNOWN recovery. Per-phase deadlines, terminal private
audit and lease/container cleanup are mandatory; UNKNOWN never becomes PASS.


### Actual approved installation failure and recovery

`application-install-approved-final-v2.json`, `installation.json` and
`install-failure-diagnostics-v1.json` preserve the exact attempt. Elapsed769.204s;
controller child maxRSS53248KiB (52MiB), not the full Docker/DB peak. Admission
available RAM6310559744B and disk183894405120B. Existing verified backup completed,
`/home/syurai/vibe-seller-state/backups/procurement-20261009T065438Z.dump`,9505386972B.
Observed DB memory during backup1.281GiB; complete memory peak UNKNOWN.

Installed Compose2.40.3+ds1-0ubuntu1~24.04.1 supports `run --pull/--label` but rejects
`run --no-build`: read-only `docker compose run --no-build --help` returns1,
`unknown flag: --no-build`. This is the exact failing command option. No named
migration container was created, no migration ran; schema remains20261006_08.
The guard nevertheless executed its conservative automatic rollback. Audit reports
VERIFIED_IMAGES_HOST_HEALTH; APIe31518c5/web3799e6c3 and exact DB721873c3 are running,
original host-file hashes checked, leases/marker released. No forced DB downgrade.

Post-rollback actual authenticated production HTTP:223 query «бумага»,200,
225matches/10returned,1.554621s;44 «протезов»,200,103matches/10returned,4.212145s.
Raw responses: `rollback-live-search-v1.json`. These show prior search still works;
they do not establish223 fix success. Both77Oct5/6 reprocess checks remain blocked,
new purchases attributable to this release:0. Search pagination/paper fixes remain
outside this release. Provider activation is the only installed code change.

At the60-minute bound no second unchanged attempt or new preparation cycle started.
Next bounded slice: correct migration command for installed Compose, verify affected
CLI contract and failure evidence, prepare a separately reviewable exact retry plan
with preserved first-attempt backup/audit. The current immutable attempt cannot be
rerun by deleting its backup or bypassing FULL_SOURCE_INSTALL_ALREADY_ATTEMPTED;
changed trusted adapter/plan requires fresh exact approval. Application receipt and
accepted production6 corpus remain reusable and are not recreated.


### Prepared resource and migration retry v4 (2026-10-09)

The user authorized increasing worker resources when the host has reserve. Current
host has4logical CPU,8326946816B RAM (7.755GiB), no swap; observed available RAM
6498557952B (6.052GiB). Running worker snapshot about275MiB, OOM0 and CPU throttling0;
this observation does not prove the old cap is the ingestion bottleneck.

The proposed worker ceiling is3GiB/3CPU; current production remains2GiB/2CPU.
API1GiB/web768MiB/DB2GiB/proxy128MiB stay unchanged. Those container ceilings plus
worker total6.875GiB, leaving about0.88GiB outside these containers for host/Forgejo;
the CPU ceiling leaves one nominal core of host time outside the worker. These are
ceilings, not reserved allocations. Admission now requires available RAM>=5GiB,
hostCPU>=4 and free disk>=40GiB; it is checked again immediately before installation.
Existing backup retains DBsize+40GiB disk check. Source pacing/leases, per-archive/XML
caps, tenant isolation and provenance stay unchanged; no throughput gain is claimed.

Final trusted adapter042b7a80e3b08095b264a297f2e264e9156c773bb392da52b6459657f439dd8a
uses compatible `compose run` flags, inspected immutable image and `--pull never`;
installed parser read-only probePASS. Launch errors are preserved privately before
cleanup. Fixed retry stage is `/home/syurai/vibe-seller-state/full-source-production223-v2`;
failedv1 audit/backup and verified DBbackup remain intact. Strict worker before2/2,
after3/3 and exact environment/resource bindings are retained. The inverse overlay
sets2GiB/2CPU before validation of the full old runtime contract, then restores old
host config/images. Server read-only prospective3/3 followed by inverse2/2 produced
the identical before-contract hashb532044b71c5e9ffc60a86819b4e985cee69d37d9d8228bdbe5cb52545b27e22.

Package `quality-provider-production223-resource-v4.tar.gz`,
SHAc4f6b39ac2c52471f1dd7fda46ad8bc24a26ee8924f63630124131c9850f5d8c;
activation plan092d61f67700502a3c7f897ae5a5bae6a9b96716dadb0a0dba9874d7e373fe99;
application planbee8656c22716d97c35f133042425503e5b49f6388b5d5d4af14e31c02648a16.
App source/48-stage receipt/images unchanged; pagination/paper remain excluded.
Targeted checks67PASS0skip, Ruff/mypyPASS; realserver forward/inverse config and
apppreflightPASS, unchangedactivator preflightPASS0.238s. These are preparation,
not a production3/3 installation or successful223 intake. V3 was intermediate and
superseded after identifying inverse-budget validation; it was never activated.

Private evidence: `resource-retry-checks-v4.xml`, `resource-retry-prepare-v4.json`,
`activation-resource-preflight-v4.json`, `package-bindings-resource-v4.json`,
`trusted-resource-retry-v4.diff`, `independent-resource-review-v4.json` and
`exact-approval-resource-v4.md` under the existing production-promotion evidence directory.
New trusted bytes/application plan require fresh exact human approval; the earlier
c858/6b3e approval is not reused for this changed payload. Installation remains the
existing activator then existing FULL_SOURCE entrypoint, fresh verified backup,
admin migration and immutableimages; no direct Docker resource update bypass.

### Full installed-Compose path proof before retry approval (2026-10-09)

The exact v4 package/application plan/images and accepted application receipt did
not change. Private `exact-package-composition-resource-v4.json` contains all350
host bindings (4changes/346unchanged), all8 trusted members and SHA256, exact
images, schema/configuration/resources and rollback bindings. Readable complete
diffs: `application-production223-v4.diff` and
`trusted-resource-retry-v4-normalized.diff`; line-ending normalization changes
only the presentation, not package bytes. Controller/policy/verifier/tools and
captcha guard remain unchanged; pagination/paper are not in this release.

Existing exact adapter042b was exercised on installed Compose
2.40.3+ds1-0ubuntu1~24.04.1 using the full resolved production configuration.
Declared isolation substitutions: unique identities/paths/volumes, ephemeral
credentials/source tokens, no published ports and an internal network; proxy
was not started. All service profiles, dependencies and budgets, including
DB2GiB, were preserved. Synthetic two-tenant fixtures are not production data.
The fixed private invocation changes these identities only; it adds no launcher,
installed helper or release guard. Existing backup invokes real pg_dump/pg_restore-l.

`full-compose-path-result-v2.json`:36.037607s, actual INSTALLED then manual
ROLLED_BACK_DB_HISTORY_PRESERVED. The path includes receipt/images/config/guard
checks, verified backup, finite detached admin migration08→08_01, CHECK8,
four host changes, actual immutable API/web startup and HTTP health. Migration
uses supported run flags with --pull never and inspected image/label; up retains
--no-build. Schema and an8-archive row survive rollback; worker returns3/3→2/2.
Sampled peaks: API161894400B, web99508224B, DB101834752B, OOM0; these are service
cgroup peaks, not total production-ingestion memory. Exact commands are retained
in the result trace.

`full-compose-path-result-v3.json`:34.804110s, injected RuntimeError after actual
new health caused the existing install exception path to restore old images/host/
configuration/health automatically. Expected terminal FAILED records
VERIFIED_IMAGES_HOST_HEALTH; DB_CHECK_PRESERVED. CHECK/schema08_01 and the8-archive
history remain. Markers/leases are released; separate postflight confirmed zero
fixture containers/networks/volumes and actual production preflight PASS.
`production-target-post-rehearsal-v3.json` binds this postflight.

Independent `independent-full-path-review-v3.json`, SHA
1ad7f99409a593b21df187ab03c0dc86eb527759efeab85aa455fdc330a66437:
READY_FOR_SEPARATE_EXACT_APPROVAL, blockers[]. Actual production was not mutated;
production migration, two problem windows and post-fix user search remain pending.
The prior accepted application receipt is reused; unchanged mandatory checks
are not rerun. Exact commands, complete composition and human approval request
are in private `exact-approval-resource-v4.md`. No production approval is inferred
from isolated success or the earlier different-payload approval.

## Exact v4 — approved production execution, 2026-10-09

Human approval binds package c4f6b39ac2c52471f1dd7fda46ad8bc24a26ee8924f63630124131c9850f5d8c,
activation092d61f67700502a3c7f897ae5a5bae6a9b96716dadb0a0dba9874d7e373fe99,
applicationbee8656c22716d97c35f133042425503e5b49f6388b5d5d4af14e31c02648a16.
The existing activator and FULL_SOURCE installer completed: activation0.735s,
preflight0.742s, application777.067s, schema20261008_01. Accepted application
receipt11dd/sourcec641 and immutable API148407/webfd4f23 were reused unchanged.
Installed adapter042b preserves the guard. Worker budget is now3GiB/3CPU;
actual cgroup limits were checked. Verified backup9655911996B is retained.
Host available memory before install6646595584B, disk174071668736B; API/web health,
four-file host delta, tenant contract and lease cleanup passed. No rollback needed.

Both77/purchaseNotice windows05–06.10 now have5archives and433/466XML records:
243+238=481added versions,423previously absent purchases. Ordinary223 also closed
77/08.10 with5archives/414XML and57added versions. Bound archive blobs and SHA256
were checked; compressed totals27881069/30454112/24445405B stay below32MiB.
Queries имущества / Нагатино / пищеблоков found the expected exact purchase/version
in production HTTP200 at0.324/0.044/0.181s. 44 smoke протезов:HTTP200/3.891s.
These are authenticated application routes used by discovery; visual browser
verification was blocked by the browser URL security policy.

Two postcheck wrapper failures remain evidence, not PASS: reading all full223
snapshots exhausted3GiB (Docker OOM/exit137) after the first window committed;
compact retry reached180s shared lease wait before any source call. After these
two cycles, no third source replay was attempted. Committed source/audit records,
bounded identity projection and actual HTTP searches completed the product check.
A local44 response projection bug was repaired from its retained HTTP200 response
without repeating the request. Full pipeline/migration peak memory remains UNKNOWN.
Normal fresh-worker sampled peak284721152B/OOM0 is not an end-to-end peak;
DB lifetime peak2147663872B/max-events92684/OOM0 is not a release-phase measurement.

Evidence in private tmp/improvement-program/m2/production-promotion-20261009-v1:
human-approval-resource-v4.json, approved-resource-v4-execution.json,
production-installation-resource-v4.json, production-migration-resource-v4.json,
production-runtime-proof-resource-v4.json, production-committed-windows-search-v3.json,
production223-source-integrity-v1.json, production223-official-run-time-proof-v1.json,
production-two-windows-postcheck-v1.json/v2.json and postcheck-oom-diagnosis-v1.json.
Production223 installation/window/search slice is COMPLETE; national freshness
acceptance remains INCOMPLETE. Pagination and paper lexical changes are excluded.
