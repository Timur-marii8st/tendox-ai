# S211 — сравнение характеристик в исторической строке

Статус: DEPLOYED AND VERIFIED2026-10-06MSK. Root UI/adapters/build/docs;
Sol strict public contract/unit tests; Astra independent read-only review.
Backend contract: [S210](93-eis-characteristic-pair-observations.md).

After selecting a historical analog row, the user explicitly clicks
«Сравнить записанные характеристики». The request includes exact target and
candidate number/version/XMLSHA plus selected source indices. No eager reads
for every row, document download or projection job. Server-side bearer stays
outside browser; failed authorization/source/byte checks display errors.

Strict public response binding validates exact selections, nested provenance,
array/scalar limits, cardinality/truncation, row/count consistency and fixed
UNKNOWN statuses. The request session invalidates superseded responses; changing
the target or row remounts the selected-pair reader by full request key.

The report shows original descriptors/numeric values/instructions/units and
ranges with both source locators. Recorded SAME/DIFFERENT labels do not confirm
technical compatibility. Technical/delivery/profit/participation/coverage remain
UNKNOWN. Legacy missing values and preview truncation are visibly explained.
React escapes external source text. Decimal strings are displayed without
JavaScript arithmetic or unit conversion. Empty report does not imply equality.

Web-only pinned build/release, networknone/2CPU/2GiB builder; installed web768MiB.
S210API/worker/schema/cron/source budgets unchanged. Node boundary/session/render
tests, TypeScript/ESLint/build, installed Next Action+SSR and operations evidence
are recorded below. Browser visual check is separate from compiled SSR.

## Evidence

10characteristic+9analog+8protocol Node tests PASS; TypeScript/targeted ESLint
and production build PASS. Isolated pinned builder networknone/2CPU/2GiB;
no dependency change. Astra review closed after strict enum noncoercion,
source-bound display names/indexed nonempty rows, Python whitespace parity and
escaping regressions. Old pending replies are discarded by request revisions.

Web-only deploy21:11:17UTC atomic16/host109/web21hashes PASS; registered pair,
analog and protocol actions. Backend S210 pins/schema/caps/cron unchanged.
Installed web image: `sha256:9bccc90755c4ba9b1bc46f2be778b0d5096acb1b83725ef66dbfe3d9bf836094`.
Installed Next Action+compiled SSR21:11:41UTC:6pair reads88–195ms;
12/4/3rows allUNKNOWN, rawvalues/ranges/instructions/SHA/legacy labels visible.
Five malformed/held-reference errors PASS, no report on failure.
Live analog action1387ms and104comparison buttons in source0 rendered report.
Background ingestion changed the candidate set since S209 sample; this is not
a fixed-corpus timing comparison. Frontend makes no eager per-row request.
Checks validate production action and compiled render, not browser visual UX.

First helper attempt stopped before reads because request JSON was only in
the API evidence volume; bounded request export added, then all checks passed.
No tunnel/publicport change; S204 tunnel-start automatic approval rejection
remains respected. User testing still needs the existing private SSH forwarding.

Ops21:11:42UTC DB5085035543/free257155776512bytes/testDB0/health200/head01;
ordinary223markertrue, priorityfalse, not removed. Foreground source0/jobs0/
DBwrites0. API1GiB/web768MiB/worker2CPU2GiB, cron/source budgets unchanged.

VPS state `s211-web-build.log` SHA256 `fcdf8f47e5bdedcd1dc3b484adc99c6c233835466ff9797f53d3502a4765a12c`.
VPS0600 `/home/syurai/vibe-seller-state/s211-web-regression-proof.json`, SHA256
`780999e72d95ab99de8517c24ba1255b62b73c7cf057a286d5800190530dfb7b`.
`/var/lib/eis-browser/research/rejected/s211-final-operations-proof.json`, SHA256
`87f8006b73e8ce64343ee60eafc63710dbd89b9f843423f37012587da8fb8e6c`.
Rollback `/home/syurai/vibe-seller-state/backups/s211-before-20261005T211114Z-web.tar.gz`,
SHA256 `696fab44295771129df03de9c684a8d6cad8f7006204ddee4ae78a956e4a63d4`.

Next S212: existing explicit source0 projection workflow for two deduplicated
selected legacy refs, with bounded retained archives/digests/replay and new UI
observations. No global historical rebuild or automatic download is authorized
by the selected-pair read itself.
