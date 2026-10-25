# Isolated profile, search and comparison integration

## Frozen source

This local candidate starts at byte-exact baseline `0296b8fe15e94ea0fec539bd75eb20c1f5f028f6`
(tree `171ef570f2c1ce236dd0b5ad74b2a4c045b96fb5`, parent
`9dbc82b0000a23cad2e48428ce89f1b3b5aea364`). An alternate Git index and raw,
no-filter blobs captured 1,226 tracked/nonignored files from the accepted quality
worktree; ignored temporary files and secrets were excluded by Git ignore rules.
The recoverable baseline is `integration/frozen-quality-bytes-20261015`.
The external per-file SHA-256 manifest has SHA-256
`cd0a61f1fc746b247a0021700839b0b386987b1cf00f1668abb5b4923c7365c4`.
After feature integration began, all 1,226 original files still matched the
manifest and the original HEAD remained unchanged. The original index was never
used to stage this snapshot. Existing runtime file line endings are retained.

Only feature changes are reviewed relative to that baseline; the accumulated
quality work is inherited source, not part of the profile/search/comparison slice.
No production activation, collector operation or external source call occurred.

## Migration compatibility

Existing `20261014_01` retains parent `20261006_12`. New no-op merge
`20261015_01` joins `20261014_01` and frozen quality head `20261008_02`.
The prior `20261008_02` merge and all earlier revision identities are unchanged.
Actual Alembic traversal confirms `20260916_01` is an ancestor of
`20260916_02`, not an independent head; its model-brand catalog history is retained.

Real isolated PostgreSQL 18 at loopback port 55489 verified:

- fresh empty `procurement_integration_fresh` -> `upgrade heads` -> `20261015_01`;
- empty `procurement_integration_upgrade` -> `20261008_02` -> `upgrade heads`
  -> `20261015_01`;
- model-brand catalog and both profile tables remain present with RLS enabled;
- populated legacy case and model-brand catalog survived the quality-head upgrade
  with identical full-row digests in `procurement_integration_preservation`;
- standalone profile PostgreSQL/API suite: 18 passed, zero skips, using
  `--require-postgres`, separate migration owner and restricted runtime role.

The migration owner requires BYPASSRLS for the existing security-definer API-key
lookup function. A non-BYPASSRLS migration-owner attempt correctly failed on the
baseline authentication DDL; rerunning with the existing intended owner privilege
succeeded. The runtime role remains NOSUPERUSER/NOBYPASSRLS.

## Combined acceptance

Branch: `integration/profile-search-comparison-20261015`. Review the feature diff
against `0296b8f`, not the earlier dirty development snapshots.

The combined branch contains standalone profile `f85a404`, migration merge
`f0c492d`, adapted exact-number search `f78df05`, saved-profile comparison
`86a774b`, and CI test-environment compatibility `ee32e5f`.

- Exact-number search preserves strings, leading zeroes, whitespace trimming,
  tenant/current-version visibility, source holds and existing text search.
- Comparison reads the actual canonical flat-fact profile DTO, validates exact
  saved selection/version/hash, and reads tenant-scoped saved ProcurementCases.
- A shared personal session is used for profile and comparison. Distinct legacy
  and replacement cookie names avoid Next overwriting scoped cookie deletion.
- Real PostgreSQL acceptance: 26 passed, zero skips (18 profile, one saved-case
  comparison, seven exact-number/API cases). The comparison test also passed
  with standard CI DATABASE_* settings and --require-postgres.
- Existing search/pagination/scoping PostgreSQL subset: 21 passed in the adapted
  search worktree. Full database release groups were not rerun here.
- Ruff, domain typing, nine doctests and documentation/index checks passed.
- Frontend: ESLint, TypeScript, 163 Node tests (zero skips), and Next production
  build passed on the assembled tree.
- The initial broad unit run found one Windows timestamp-precision race in a
  freshness test. The test now fixes both filesystem mtime and its clock; all
  25 freshness tests passed. Scheduler/runtime code was not modified.

Final root full pytest: **3474 passed, 689 skipped, zero failed**, 346.72 seconds.
Command: `.venv/Scripts/python.exe -m pytest -o addopts='' -q -ra
--junitxml=../final-pytest-root.xml`. Skips are explicit environment limitations,
not successful validations: {'PostgreSQL environment': 530, 'Optional dependency': 15, 'Linux/platform-specific': 144}. The required changed-feature PostgreSQL
checks ran separately with 26 passes and no skips; this is not a complete Linux
or production release gate. Root fixed both mtime and the clock inside the
freshness test; no runtime scheduler behaviour changed.

External evidence beside this worktree: final-pytest-root.log/xml,
final-pytest-summary-root.json, final-static.log, final-postgres.log and
final-web.log. The first run's timestamp failure remains in final-unit.log,
not reclassified as a pass.

## Independent browser acceptance

Root used the ordinary browser UI on the assembled Next production build at
localhost:3035, API loopback:8135, and the isolated PostgreSQL database. All data
and credentials were synthetic. No source refresh or EIS request was triggered.

- Personal login, latest profile v2 with selected v1, and comparison of two saved
  cases with exact v1: PASS. The UI explicitly distinguishes saved state from a
  fresh EIS check and does not turn UNKNOWN into admission.
- 223 exact-number searches: ` 32616445250 ` and `32616445747` each returned one
  matching synthetic card; `32699999999` returned zero; text `кранов шаровых`
  returned both cards.
- Logout from the profile removed access to the comparison catalogue: PASS.
- Screenshot: root workspace `comparison-integrated-ui.png`; private credentials
  remain ignored and are not present in this document or Git.

## Remaining product and deployment boundaries

This is a locally verified integration candidate, not an installed release.
Production, loaders, scheduler, source access and resource limits were unchanged.
Comparison uses saved cases: converting arbitrary EIS search cards into complete
cases is not implemented by this slice. Reports remain EPHEMERAL with no stored
comparison audit/history. In the installed baseline critical financial settings
remain UNKNOWN; a local owner-authorisation extension is under separate
validation, as recorded in [ADR0115](../adr/0115-company-profile-owner-confirmation.md)
and [operations/125](../operations/125-spec-remediation.md). No production
activation or profit inference from initial price is claimed.
The normal comparison adapter has no separately verified scenario ledger.

The existing server-supplier-browser-rollout.py FULL_SOURCE adapter pins schema
20261008_01 and an older exact package/receipt. It cannot be reused unchanged for
this candidate's 20261015_01 head. A compatible exact installation/rollback plan,
release gate and new receipt are required before any production activation;
those guards were not edited or bypassed here.

## Source preservation

The final root SHA256 check inspected all 1,226 frozen source files. Original HEAD
remained 9dbc82b. All runtime/test/asset files still matched. Three live M0 docs
had changed during ongoing independent census work: docs/15-implementation-plan.md,
docs/eis/search/121-eis-active-procurement-product-plan.md, and
122-eis-active-census-m0.md. This integration diff does not edit those three files;
no concurrent updates were restored or overwritten. External evidence is
original-quality-preservation-root.json beside the worktree.
