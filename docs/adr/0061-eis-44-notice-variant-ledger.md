# ADR-0061 — immutable ledger вариантов notice44

Статус: **ACCEPTED / DEPLOYED**, 2026-10-04, 08:54 UTC.
Дата: 2026-10-04, S178. Owner ADR: Astra; schema/migration/PG/deployment: root;
storage module и unit tests: Sol.

## Контекст и граница

[ADR-0060](0060-eis-44-conflict-diagnosis.md) закрепил полный retained inventory:
499 XML members, одна divergent pair с одинаковыми purchase number, version и
document ID. Правило выбора winner отсутствует. S178 сохраняет все варианты и
origins в отдельном evidence ledger; canonical admission остаётся
**NOT_ENABLED**, включая записи с единственным вариантом.

Не изменяются canonical notice intake, search, document jobs, estimates,
`eis_feed_windows`, checkpoints и sync attempts. Исторический whole-window
FAILED остаётся FAILED. Shared consumer hold и возможный intake switch —
отдельный будущий milestone, не следствие ledger receipt.

## Три tenant-scoped таблицы

| Таблица | Identity и назначение |
|---|---|
| Receipts | PK `(company, receipt_uuid)`; unique `(company, manifest_sha, diagnosis_sha)`. Exact window/response/manifest/report, ordered ZIP SHAs, counts и aware time. |
| Variants | PK `(company, number, version, document_type, xml_sha)`. Immutable source facts без origin-specific window/member fields. |
| Origins | PK `(company, receipt_uuid, archive_ordinal, member_filename)`. Composite tenant FKs к receipt и exact variant. |

Receipt UUID детерминирован по company/manifest SHA/diagnosis SHA. Новая
интерпретация того же manifest может получить отдельный diagnosis receipt;
она не заменяет прежний и не выбирается как latest truth. Report/parser
identity сохраняется в receipt basis. Raw ZIP остаются в quarantine;
дублировать XML bodies в DB не требуется.

Один XML variant может иметь несколько members и receipts: сохраняется каждый
origin. Same variant across windows не заменяет source facts; разные SHA
накапливаются. Existing payload сравнивается полностью; `ON CONFLICT` не
может скрывать несовпадение immutable facts.

## Atomic admission только в ledger

В одной tenant transaction под advisory lock проверяются exact ранее
записанные retention и diagnosis audit bases: tenant, window, source response,
manifest SHA, ordered ZIP SHAs и полный report hash. Diagnosis повторно
валидируется вместе с inventory/group consistency. Недостающие number,
version или type, неоднозначные origins либо несовпадающие counts отклоняют
весь ledger batch. Unknown document ID допустим только как UNKNOWN evidence.

Все variants, origins, receipt и новый immutable audit фиксируются атомарно.
После insert проверяются member/origin и distinct-variant counts. Любой late
conflict откатывает полный batch; replay одинакового payload не добавляет rows
или audit. Receipt означает полное сохранение exact evidence set и не означает
SYNCED canonical source window или supplier eligibility.

## Constraints и чтение

Каждая таблица имеет RLS/FORCE RLS, immutable protection, composite tenant FKs,
SHA format и bounded count/ordinal checks. Member names безопасны и ограничены,
receipt time timezone-aware. Source XML остаётся недоверенным; ledger не
расширяет полномочия внешнего содержимого.

Typed read state видит накопленные cross-window variants. Более одного
distinct `(document_type, xml_sha)` для `(number, version)` означает ambiguous
UNKNOWN. Один вариант также не выдаёт PASS или canonical admission.
Bounded read при overflow сообщает UNKNOWN/incomplete; subset не выдаётся за
полную историю. Ни timestamp, ни numeric version, ни filename не разрешают
конфликт. No latest-winner projection.

## Migration и acceptance

Migration не изменяет прежнюю историю и canonical constraints. Downgrade
проверяет глобально наличие любого receipt/variant/origin **до** удаления
schema objects, с `row_security = off`; если tenant visibility невозможно
гарантировать, rollback отклоняется. Непустой ledger не удаляется ради downgrade.

Gates: fresh upgrade/empty downgrade roundtrip; immutable/RLS/composite tenant
FK; exact audited binding; full inventory and all origins; missing identity
whole-batch rejection; identical replay; cross-window same/different variants;
late conflict atomic rollback; global nonempty downgrade refusal. Exact retained
production operation допустима после isolated gates и review, без source calls.
Production deployment подтверждён приведёнными ниже proofs.

## Bounded implementation review

Frozen migration DDL проверен относительно моделей: три таблицы, composite
tenant FKs, deferred ledger audit FK, RLS/FORCE, immutable triggers и global
downgrade guard сохранены. Evidence CHECK использует null-safe comparisons
для RETAINED/complete_set и ограничивает JSON 128 KiB; facts ограничены 4096 B.

Writer проверяет exact prior retention/diagnosis audit bases, immutable facts,
полный sorted origin set и final audit в одной transaction. Review выявил
разную UTC сериализацию nested evidence при receipt hash; исправление сохраняет
source JSON представление и отдельно нормализует DB receipt time в UTC.

Оба readers проверяют полный receipt/origin/facts/hash/ledger audit, а не только
целевую notice pair. State read имеет caps: 20 receipts, 2000 origins/variants
и 16 MiB совокупного evidence/audit JSON; размеры проверяются в PG до загрузки
полных payloads. Overflow не выдаётся за COMPLETE и остаётся UNKNOWN с
NOT_ENABLED. Cross-window history не ранжируется и не выбирает winner.

Исправления проверены повторным read-only review; новых release blockers не
найдено. Финальные gates пройдены: root сообщил 54 Linux PASS, 36 isolated PG
PASS, Ruff/mypy PASS. Read validation проверяет также type/object_type/object_id
всех трёх audit records. Полнота transport evidence не меняет canonical FAILED.

## Isolated и production evidence

Isolated exact retained gate: 5 ZIP, 499 variants / 499 origins / 498 semantic
keys; SAME-ID divergent pair имеет два варианта, UNKNOWN / NOT_ENABLED.
Один ledger audit, replay без новых writes, source calls 0,
canonical/checkpoint/attempt delta 0. Время 8.160 s, peak 375,984,128 bytes
при cgroup 2 GiB с resident Chromium.
Proof `/var/lib/eis-browser/research/rejected/s178-isolated-proof.json`, SHA-256
`7c33f48aadbdc15ee61488db4c4679073967a8780d58962b64441f9a80323b94`.

Production rollout в 08:54 UTC: schema HEAD `20261004_02`, backup кода и
проверенный schema-only backup (без копии существующих data rows), scoped
host 11 / API 3 hashes совпали. Exact retained набор дал 499 variants,
499 origins, 1 receipt и 1 ledger audit. Receipt SHA совпадает с isolated:
`75a1baa4489b6e0f59c113a3448b83cb4a8ea5fbc9cc375a1937bb608678dd91`.

Replay: 0 source/file/audit/index/checkpoint/attempt writes. Старые 8 FAILED
сохранены; pair остаётся UNKNOWN / NOT_ENABLED. Время 8.309 s, peak
381,870,080 bytes (около 364 MiB) при прежних 2 GiB с resident Chromium.
Это offline retained measurement, не online SLA.
Production proof `/var/lib/eis-browser/research/rejected/s178-retained-proof.json`,
SHA-256 `f25858f5d8c7a0bd5d195c3c5138965c43a632151a597a206351cc5d294a48ce`.

API sample 08:54:47 UTC: health 200 / anonymous 401 / no-store, markers
отсутствуют. Isolated test DB удалена. Intake hook и consumer switch отсутствуют;
coverage/freshness ЕИС остаются UNKNOWN.
