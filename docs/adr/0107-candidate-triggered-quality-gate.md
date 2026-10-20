# ADR-0107: Provider-independent quality gate on candidate submission

- **Status:** ACCEPTED; **activation:** `INSTALLED` после exact-payload approval 2026-10-07; bounded M1 acceptance COMPLETE.
- **Date:** 2026-10-07
- **Decision owner:** root, program owner

## Context

M1 requires a reproducible release and a persistent complete quality gate. The
repository has no configured Git remote, and the checked-in GitHub workflow has
no established run path for this checkout. A workflow file or one-off local
run therefore cannot be represented as active hosted CI or as M1 completion.
The current mandatory PostgreSQL policy is 60 modules in 15 groups, with scope
identified by its expanded inventory; any policy change must version that
identity. The existing browser/CAPTCHA release paths also use installed-base
overlays, which are not equivalent to a clean full-source candidate.

## Decision

Use a provider-independent, candidate-triggered local workflow as the first
permanent-gate architecture. An operator submits one candidate to the trusted
controller. Submission seals its exact source archive and identity, then
automatically runs the entire versioned mandatory policy, builds and verifies
the exact artifacts, and creates one immutable receipt. There is no option to
skip, select, or substitute release checks. The local run ID is the workflow
run identity for this provider; it is not a GitHub or Forgejo hosted run. A
future provider may invoke the same policy and receipt contract.

The trusted controller, policy, verifier, run state, and receipt directory live
outside candidate-writable mounts. Candidate code runs only in isolated workers
with read-only sealed source and no production secrets, state volumes,
production networks, or Docker socket. A disposable private test network is
allowed for PostgreSQL; dependency retrieval uses a controlled preparation
phase with no application credentials. Host networking is forbidden. Startup
smoke runs have no network. The controller alone creates and removes its labeled test
resources and finalizes receipts. Candidate-produced reports are untrusted
inputs. Receipts bind the exact archive/tree/manifest, policy and expanded
scope, environment and base identities, per-stage results and report hashes,
and exact API/web/worker artifact IDs. A verifier rejects missing, partial,
interrupted, stale-policy, mismatched, or tampered evidence; absence or
ambiguity is `UNKNOWN`, and a required failure is `FAIL`. Only complete verified
evidence can yield a usable `PASS`.

The reviewed Docker recipes require BuildKit offline source execution. The
provider includes a private pinned Buildx plugin and empty Docker config as
explicit trusted tool assets, separate from candidate archives. Tool version,
platform, official source, byte size and hashes enter the activation identity;
the controller fixes the local engine endpoint and builder, rejects ambient
selection and legacy fallback, and keeps mutable Buildx state per run. Tool
updates require a new reviewed identity; this private dependency has no implied
automatic update mechanism.

Candidate test workers use the controller's unprivileged UID/GID so even private
0600 reports remain readable without privileged host permission repair. Only
the private `/test` scratch permits executable synthetic harnesses, retaining
nosuid/nodev and mode0700; sealed host source remains read-only. Node build
writes occur in a private copied tree, never in the sealed source.

Supported release entrypoints must validate the controller-owned receipt for
the exact candidate and target under the existing mutation lease, immediately
before any host write. They install recorded immutable artifact identities and
do not rebuild at installation. A receipt proves technical readiness only: it
does not approve deployment, external action, or an exact payload. Existing
approval and authorization rules still apply.

The first implementation may prepare and verify full-source snapshots. Legacy
installed-base overlay mutators fail closed with an explicit unavailable-gate
error until a separate adapter binds the immutable base, patched-file manifest,
effective tree, and resulting artifacts. A full-source receipt cannot authorize
an overlay, and this decision does not replace or rebuild the installed overlay.
Supported release paths must also preserve worker/host-script parity: executable
host scripts and worker image identities are bound to the accepted candidate;
image identity alone is insufficient when host code changes.

The gate applies to documented supported release paths. It cannot prevent a
privileged administrator from using raw Docker commands or copying files
outside those paths. Any emergency privileged override stays outside routine
promotion, records actor, time, reason, intended payload, before/after source,
image and configuration identities, backup/recovery outcome, and follow-up
verification, and never creates or implies a quality `PASS`.

## Consequences and acceptance boundary

Implementation and activation are separate. The architectural decision itself
does not authorize installation or deployment. Following the user's exact-payload
approval, the provider and two guarded legacy entrypoints were installed on
2026-10-07. Product 16 defines the local run identity; operations 114 records
the activation, receipt-bound checks and independent audits. Mandatory scope
and quality criteria do not change. This is not hosted CI or an application
deployment.

Bounded local-provider M1 is accepted after two fresh automatic full installed
submissions, independent typed-receipt and cleanup audits, exact Git/source
binding, clean build/run, same-candidate export/load/startup verification and
four installed legacy-entrypoint refusal checks. Operations 114 retains the
exact identities and historical failures. This acceptance does not claim
hosted CI, application deployment, database recovery or search quality.
Future overlay adapters, other provider setup and broader administrator
enforcement require separately scoped decisions.

## Production branch compatibility addendum (2026-10-09)

An older installed branch can use a separately reviewed policy version for its
complete applicable behavior. This version binds exact archive/tree/manifest
SHA identities and accounts explicitly for uninstalled function tests. It must
not import unrelated product code to match a newer inventory. All applicable
checks, pinned recipes, tenant/network isolation, receipt verification and
guarded cleanup remain mandatory.

The production223 branch uses legacy-flat link/anchor checks and sequential
PG/Python, Node and build phases; default policy behavior remains unchanged.
Trusted controller/verifier and policy diffs are reviewed separately. A private
prepared version does not activate a provider or authorize deployment; active
guards remain enabled and exact-payload approval remains required.

## Bounded FULL_SOURCE implementation addendum (2026-10-09)

The existing browser rollout entrypoint now has a separately reviewed FULL_SOURCE
adapter pinned to the accepted production223 snapshot only; exact activation is installed.
Legacy overlays still refuse unconditionally. Exact provider/guard activation and
application-plan approval remain separate from technical receipt and review.
Host/worker/configuration parity, admin-role migration, finite phase deadlines,
immutable inverse images/configuration and durable cleanup/failure audit implement
the existing promotion contract; no universal deployment platform is introduced.
Preparation and limits are recorded in [operations115](../operations/115-candidate-quality-workflow.md).
Approved execution activated the provider but application installation FAILED:
installed Compose rejects `run --no-build` before migration container creation.
Automatic rollback verified original images/host/health; schema20261006_08 unchanged.
Post-rollback HTTP search works on the prior application. Both window reprocessing
and post-fix search remain incomplete. Corrected trusted bytes and retry plan require
fresh exact approval; failure audit and verified backup must be preserved.


A separately prepared v4 retry binds the user-authorized3GiB/3CPU worker ceiling,
compatible Compose run flags and preserved first-attempt evidence. Its inverse
explicitly restores2GiB/2CPU before old-contract validation; all unrelated runtime
fields remain bound. Exact new activation/application plan approval is still required.
Read-only server forward/inverse validation is preparation, not successful rollout.

Before new exact approval, the same v4 adapter and immutable images completed
the full installed-Compose path using isolated full-config synthetic fixtures:
verified backup/admin migration/install/manual rollback36.038s and injected
failure/automatic rollback34.804s. Full traces and independent review are recorded
in operations115. Unchanged accepted application receipt is reused; guard/policy
requirements are retained. Isolated mechanics PASS does not authorize production
installation or establish production ingestion/search acceptance.

On2026-10-09 the human explicitly approved exactv4 packagec4f6/activation092d/
applicationbee8. The existing activator/FULL_SOURCE installer installed the
unchanged accepted minimal223 application, migration20261008_01 and3GiB/3CPU
worker budget. Actual production installation, committed77Oct5/6 source records
and authenticated discovery queries now complete this bounded acceptance.
Operations115 records results and retained failures; earlier pending-approval
statements describe preparation, not current state. No guard bypass or policy
exception was used; national flow and unrelated search changes remain separate.
