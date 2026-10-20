# ADR0086 — исходные границы и наблюдения записанных диапазонов

Статус: принято, реализовано и проверено; effective2026-10-06MSK. Внутреннее правило
наблюдения исходных данных, без изменения законодательства или правил допуска.
Официальный источник конкретных значений — сохранённый XML ЕИС с exact SHA и
локатором; нормативные выводы по инструкциям заполнения не делаются.

## Причина

S210/S211 отвергают диапазоны. В выбранном XML есть «не менее500листов»;
v2 projection содержит parsed minimum500, но не сохраняет raw opposite bound.
Отсутствие max и malformed max могли стать одинаковыми None/rawNone.
Повторное использование такой записи для вывода о полном диапазоне небезопасно.

## Решение

Parser retains bound raw strings, including empty present strings, and a strict
range_source_complete marker only for the recognized source shape. Unsupported
range structure fails closed; malformed numeric text is retained and stays
UNKNOWN. New immutable projection `eis-position-v3-range-evidence` alongside
v2; comparison prefers v3, validates source holds/identity/digest/bytes first.
Corrupt v3 never falls back. V2 completeness always false, including unexpected
new marker in legacy JSON. Canonical source rows are not rewritten; bounded
selected source0 recovery creates separate projection+audit and replay writes0.

Policy `eis-characteristic-observation-v2`: unique full names, complete values,
equal explicit instruction/unit labels. Pure ranges require raw/value consistency,
finite bounded Decimal, at leastone endpoint, known operators greater/greaterOrEqual
and less/lessOrEqual, no orphan operator, no reversed/empty interval. Equal bounds
with bothinclusive allowed. No mixed description/concrete/range, truncation or
ambiguous source. Exact numeric range+operator equality gives recorded SAME;
different complete ranges DIFFERENT. This is numeric equality, not lexical equality
(`500` and `500.0` equal), containment, intersection or unit conversion.

## Boundaries and rollout

All technical/comparability/delivery/profit/participation/coverage statuses UNKNOWN.
No supplier eligibility, recommendation, ranking or hard gate changes. Source0
foreground reads never parse archives or schedule recovery. New web accepts old
v1 and new v2 wire contracts during rollout, requiring strict completeness marker
on v2 values. Build/test web before backend release. Existing resource/cron/source
budgets unchanged; no schema migration. Verify source/pure/storage negative cases,
legacy coexistence/preference/corruption/RLS/replay and installed API/SSR.

336 isolated PG/unit/API tests and13characteristic Node tests PASS; installed
same-clock API/direct and Next Action/SSR PASS. One real matching range observed;
externalSid outside current recognized form remains UNKNOWN. Evidence: [S213](../eis/search/96-eis-recorded-range-comparison.md).

## S214 revision, effective 2026-10-06

Optional nonblank scalar externalSid is recognized as metadata, with duplicate,
attribute, nesting and mixed-text guards. Source: retained EIS XML and cached
IntegrationTypes.xsd optional externalIdType declaration; no UUID assumption.
New immutable r1 identity prevents rewriting original v3 meaning. Read preference
r1 > original v3 > v2; corrupt preferred rows never fall back. Original v3 is
readable but cannot be created by the revised parser. Archive size is checked
before loading content. Observation policy/wire/hard gates stay unchanged.
Verification status and exact operational scope: [S214](../eis/search/97-eis-range-external-id.md).

## S215 revision, effective 2026-10-06

An unsupported characteristic range cannot reject otherwise usable notice/archive
metadata. No partial bound is asserted; a strict cached source ambiguity marker
forces the entire affected position's characteristic status UNKNOWN, including
mixed description/concrete forms. This does not approve the technical specification.
Other positions and all existing XML/identity/attachment guards are preserved.
Immutable r2 identity, r2/r1/v3/v2 preference and corruption refusal; no wire-policy
change. Evidence and live limitations: [S215](../eis/search/98-eis-ambiguous-range-intake.md).
