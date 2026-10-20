# S210 — записанные характеристики двух выбранных позиций

Статус: DEPLOYED AND VERIFIED2026-10-05UTC. Root owns storage/API/PG/docs;
Sol owns pure model/unit tests; Astra independent read-only review.

`POST /v1/tender-discovery/eis-characteristic-pair` accepts `target` and
`candidate`, each `{notice: {purchase_number, version_number, notice_xml_sha256},
source_index}`. Source indices strict1–25, no caller tenant. Authenticated
principal selects tenant; auditor read allowed; `Cache-Control: no-store`.

At most two exact saved 44-ФЗ positions in a single read-only REPEATABLE READ.
Canonical ref and source holds checked for each selection. Existing
`eis-position-v2-concrete` projection preferred, with identity/digest checks;
otherwise typed stored notice fields. No archive/XML reads, projection creation,
EIS calls, jobs, audit writes or schema changes. Old missing concrete-values
schema is explicitly UNKNOWN. No automatic fallback after a corrupt projection.

Each position retains values, names, units, instructions and exact XML locators.
Names match only by whole whitespace/casefold normalization. Unique complete
explicit values and matching units/instructions can give recorded-value
observation SAME or DIFFERENT. Duplicate names, missing values, legacy schema,
truncation, ranges/mixed shapes or differing/missing units remain UNKNOWN.
Observation is not PASS/FAIL for a supplier or a technical hard gate. Full
technical/overall equivalence, delivery, participation, profit and coverage
remain UNKNOWN. Numeric values use exact Decimal; no physical-unit conversion.

Notice JSONB<=256KiB/projection JSONB<=512KiB before hydration, max two selected
sources;24characteristics/8values/8concrete values per field, response<=2MiB,
15sforeground/5sstatement/1slock budgets. Scalars<=4096characters; exact numeric
precision/exponent bounded. Truncation and missing fields never imply equality.

S211 will add an on-demand comparison button for an explicitly chosen historical
row in the UI. This backend slice is not an all-card specification review or
evidence that source coverage is complete.

## Evidence

259 isolated PG/unit/API tests PASS33.30s/zero skips,20focused local pure/API
tests/Ruff/mypy PASS. PG fixtures include exact different values, foreign/SHA/
position failures, unresolved retained origins, pre-hydration byte guards,
projection digest failures, no writes, and legacy values UNKNOWN until explicit
saved v2 projection. Production projection creation was not invoked.
Astra blocker closed: unparsed/truncated raw range forces UNKNOWN, with four
regressions for both bounds. First PG attempt failed on an unavailable imported
test helper; API fixture made self-contained and full gate repeated.

Deploy20:57:42UTC atomic10/host101/API21/worker21hashes PASS; HEAD20261005_01.
Six installed authenticated API/direct exact report identities at fixed clock
PASS20:57:56UTC. Three actual pairs have12/4/3observations, allUNKNOWN because
historical stored fields lack concrete-values schema; no fabricated SAME.
Recorded raw values are returned. HTTP77–240ms/direct75–168ms,
responses53033–102956bytes. These are saved-pair loopback measurements, not SLA
or complete specification review. Six unauthorized/ref/position negatives PASS.
Foreground source0/jobs0/DBwrites0. S207web unchanged; S211UI pending.

Ops20:57:57UTC DB5051554839/free257278357504bytes/testDB0/health200/head01,
markersfalse. Caps/cron/source budgets unchanged.

Pins: API `sha256:81e58a700422739b8deb321faf21060c5884adc94142e7e3dd8e674a1083b0bd`;
worker `sha256:9d1d300906299813068efd1b38d1ffc16b4af3ff1c07f0403f38fe285dd531e1`;
web remains S207. PGlog SHA256 `5646b8aa0c25a633e6968dbbc1ce9336c4a264cb06c9bd88d537f7548e597369`.
VPS-only0600 `/var/lib/eis-browser/research/rejected/s210-final-characteristic-live-proof.json`,
SHA256 `5b05aa868822be5d199d24f3983112e5a3deed9374a708d24ba586aeaadc18ab`;
six typed `s210-final-characteristic-report-{1..3}-{first,repeat}.json` hashes in
that proof. Ops `s210-final-operations-proof.json`, SHA256
`8cac69c7209c2fe18098cfcfafaf9c40a9515a65e8b4a3cefdae5b67c31b98a9`.
Rollback `/home/syurai/vibe-seller-state/backups/s210-before-20261005T205736Z-code.tar.gz`,
SHA256 `20874c1b752202a258b7daa45e8b806dd3e452474d5477e5838530e8f566bc6f`.
