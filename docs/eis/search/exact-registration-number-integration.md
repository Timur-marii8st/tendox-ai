# Exact registration number: quality integration

Owner: exact search port agent. Date: 2026-10-15.
Isolated branch: `integration/exact-search-port`.
Base: `0296b8fe15e94ea0fec539bd75eb20c1f5f028f6`, byte-exact frozen accepted quality source.
Original feature: `a2ab016`; its older `5edcadb` snapshot is not imported.

## Contract and adapted scope

A trimmed ASCII query with exactly 11 or 19–23 digits compares the stored purchase
number as a string, preserving leading zeroes. A missing exact identity returns
empty results even if a different notice title contains that number. Other queries
retain the current optimized lexical matcher and SQL text prefilter.

Only three search runtime modules, two existing discovery forms, focused tests and
these search documents change. The quality source's stemmer, securities filter,
scoped materialized hold proofs, current-version selection, tenant isolation,
deadline/document/failure scopes, pagination and comparison memo remain present.
Number searches read canonical identities without requiring derived text keys.
Number evidence includes PURCHASE_NUMBER, original string and identity XML locator.
A match does not confer participation or technical compliance.

The original feature's capture-test hunk is unnecessary: quality already isolates
that synthetic runtime test from frozen source pins. Its current implementation
is preserved. Frozen benchmark plans, intake, loaders, scheduler and migrations
are untouched. The historical feature report is linked separately and clearly
labelled; its production reads and timing measurements were not repeated.

## Fresh local validation

- 110 focused unit/API cases passed across exact-number, 44 matcher, 223 index/API,
  and search-page API modules. Then 13 new numeric-boundary cases passed; final
  exact-number unit module has 23 passing cases.
- 7 exact-number real PostgreSQL/API cases passed with no skips: both requested
  numbers, leading zeroes/edge whitespace, absent identity, latest version,
  authenticated tenant, read-only counts, expiry/failure/document scope, source
  hold, and missing derived text keys.
- 21 existing PostgreSQL search/pagination/scoping cases passed, 23 unrelated
  cases deselected by explicit `search or cached or scope or tenant or pagination`.
- Focused Ruff, Next route type generation, TypeScript and documentation check passed.
- ESLint of the two changed UI files passed; 7 discovery Node tests passed.
  The assembling integration agent owns broad final gates.
- A fresh checkout initially lacked generated Next PageProps/LayoutProps; running
  the standard next typegen resolved this environment prerequisite, then tsc passed.

PostgreSQL18 uses a new disposable local cluster on loopback55489 and database
`procurement_eis_test_exact_integration`, separate from existing services/databases.
Runtime role is non-superuser, non-owner `procurement_app`. XML is synthetic.
No production requests or mutations were made. Broad integration gates belong
to the assembling audit agent; local browser acceptance is not claimed here.

A binary diff patch from the frozen baseline to the feature commit passed
`git apply --cached --check` against a fresh alternate index loaded from that
baseline. CRLF-aware diff whitespace check and clean worktree status passed.
