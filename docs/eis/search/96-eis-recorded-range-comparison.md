# S213 — сравнение записанных числовых диапазонов

Статус: DEPLOYED AND VERIFIED2026-10-06MSK. Contract and boundaries: [ADR0086](../../adr/0086-eis-recorded-range-evidence.md).
Root owns storage/integration/UI/release/docs; Sol parser/evidence/pure models and
tests, then wire contract tests; Astra independent read-only high-risk review.

Raw range endpoints retain explicit empty/malformed text; recognized complete
source shapes carry strict range_source_complete. New immutable v3 projection
coexists with v2; selected pair prefers v3 with no corrupt fallback. Legacy
completeness remains false. Source0 read bounds/auth/holds/digests unchanged.

Exact complete numeric ranges can show recorded SAME/DIFFERENT, preserving
fulltechnical/profit/participation/coverage UNKNOWN. Numeric equality uses Decimal;
no containment/overlap/unit conversion/instruction semantics or recommendation.
New UI shows range source completeness and actual endpoint raw text with SHA
locators; dual-policy validation enables ordered web/backend rollout.

## Проверки и установка

336 isolated PG/unit/API tests PASS36.60s/zero skips;83focused source/model tests,
13characteristic+9analog+8protocol Node tests, TypeScript/ESLint/build PASS.
Astra independent review closed after malformed/blank/opposite-bound/rawtruncation,
sNaN, mixed XML text, nested descriptions/valueSet and strictbool fixes. Authentic
sid/valueFormat=N metadata recognized; unknown additional fields remain incomplete.
Byte regression has oversized v3 and valid v2 below cap, proving no fallback.

Web-first release21:39:13UTC atomic5/host111/web22hashes PASS. Installed old-API
compatibility6reads37–201ms/5negatives PASS before backend change. Backend five-module
release21:40:01UTC atomic14/host118/API23/worker23hashes PASS. No migration, deps,
cron/source-budget change. Web verification propagates every command failure;
review found and fixed a Bash errexit masking issue before release.

21:43:09UTC five selected exact retained source refs recovered into v3, five new
projections/five audit rows. ZIP/XML/member digests/source holds PASS; canonical
rows unchanged; every replayfalse/counts unchanged. V2 evidence retained.
Five selected archives82,241,82,637,63KB; no download from EIS or to laptop.
Initial60s import lease wait yielded without writes; bounded300s retry succeeded.

Installed API/direct21:45:12UTC6same-clock identities PASS: HTTP26–114ms/direct
78–178ms;6auth/ref/index negatives PASS. Pair observations:12UNKNOWN;
1SAME+3UNKNOWN;3UNKNOWN. Pair2 records matching minimum500/greaterOrEqual/unitШтука.
Pair3 target has externalSid, outside the recognized value shape: source
completenessfalse and UNKNOWN, even though visible minimum500 matches. No full
technical PASS or supplier recommendation. First live probe wrongly expected a
pair3SAME; stopped on assertion, preserved partial proof, inspected retained XML
and repeated verification under a distinct proof prefix with the correct UNKNOWN
expectation. No source policy was relaxed to pass the probe.

Next Action+compiled SSR21:45:15UTC6reads92–182ms,5negative errors PASS; raw endpoints,
completeness/source locators/recorded equality visible. Analog925ms/104buttons;
no eager per-row call. Browser visual NOT_PERFORMED. Read pathsource0/jobs0/writes0;
explicit recovery separately writes five projections/five audit rows.

Ops21:45:16UTC DB5092580375/free257084674048bytes/head20261005_01/testDB0/health200,
markersfalse. API1GiB/web768MiB/worker2CPU2GiB unchanged. National coverageUNKNOWN.

## Pins and evidence

API `sha256:25b5529e5f43b7ee9f727f3d385a1ff39d1f76c0fffc0ddf8787126b10939b8c`;
worker `sha256:e7f933a0e14c8e3cec86946738ba4921b7226732b3f30f3000ccaf65ca7db03a`;
web `sha256:4b410b0f090389c35576d97255e8d848f2273daf0cd2e53655dcfda8174359f1`.
VPS state PG logSHA `6c0f9c2cf7ac75f8e336e8ac7fb0f91136d52d338bfd97f883943e8214679c9d`;
build logSHA `c3fce5a7ca00b78ffc56f8a0f9df86175b902e924d211452cf33f4fad28345fe`.

Private0600 `/var/lib/eis-browser/research/rejected/`:

- `s213-range-repair-preflight.json` SHA256 `df23600ec8d6fe87077a07f8e3b6899e1363773c4a1a436ab465f7c2f7eed323`.
- `s213-range-repair-proof.json` SHA256 `5f4a85459d2ba7678360ce6e498a4cdb07689b64788131f40c1089072db449e3`.
- `s213-verified-characteristic-live-proof.json` SHA256 `2d24f3650a977305b22d9d80ba8c21edc6ebd0877b232bcee3c4c9da5da851a6`.
- `s213-final-operations-proof.json` SHA256 `e189ea14cae435d24a38d5e3c617e4174bd512ea7f92702d88bb1037e88c1451`.

VPS state `s213-web-regression-proof.json` SHA256
`f08508ad9d9ab3f97e87f7d6ec465f8834e695c605910601bb0b20d11e7a45bf`;
oldAPI compatibility proofSHA `822fac447a3cc2a15e4a19be1283e4913555d330534210e8bf233c1a0c0067ce`.
Rollback web/code backups21:39:10/21:39:56UTC SHA256
`b392d164b272a76f833dd9f997849900ba439e85ac4fede111e2c77b5778454d` /
`b815d3775281dede8e7905ba8a8dda4839d7278e9bab534dc3875ba2ff8833d8`.

Далее продолжить ЕИС: дополнительные XML-формы, полнота ТЗ, связь требований
и доставки с позициями, полнота и свежесть корпуса. Отдельный продуктовый этап —
поиск производителей/поставщиков в интернете, сбор публичных цен и подготовка
получения КП; затем подтверждённая экономика. Ручной прайс пользователя является
дополнительным источником. Публичная цена не заменяет действительное полное КП;
до подтверждения всех входов реальная прибыль/участие UNKNOWN. Уточнённый порядок:
[план](../../history/implementation/07-eis-characteristics-and-recovery.md#порядок-дальнейшей-работы-уточнён-2026-10-06).
