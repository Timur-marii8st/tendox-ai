# ADR-0054 — evidence отмены отдельного лота 223-ФЗ

Статус: **ACCEPTED / DEPLOYED**, S171, HEAD `20261003_03`.
Дата и effective date runtime policy:2026-10-03. Owner:Astra.
Развёрнут UNKNOWN-only evidence/operation-hold contract. Реальное lot event
не получено: region50 окна2026-10-02 и2026-10-01 дали NO_DATA. Ни семантика
stable lot identity, ни отсутствие отмен, ни полнотаЕИС этим не подтверждены.
Зависимости: ADR0053, docs/50, уточняемое official research docs/52.

## Контекст

S170 хранит whole-purchase rejection. `purchaseLotCancellation` — другое
семейство с набором отменяемых лотов. Подмена им whole cancellation дала бы
ложный FAIL другим лотам. Схема использует source GUID/ordinal, тогда как API
`lot_index` выбирает позицию массива конкретной notice version. Они не равны.

В docs/50 установлены qualified paths, но annotation cancelledLot/guid
неоднозначна: «Глобальный идентификатор закупки». До подтверждения docs/52 и
live/source cross-check нельзя считать этот GUID доказанным stable lot GUID.
Текущий generic notice reader хранит lot.guid; старые AESMBO/ZKESMBO snapshots
не имеют этого extension. Нельзя восстанавливать GUID из ordinal/массива.

## Принятое решение

### Отдельный typed source contract

Admit только explicit `RI223/purchaseLotCancellation`, не notice/event aliases.
L=`/p:purchaseLotCancellation/p:body/p:item/p:purchaseLotCancellationData`.
Event identity L/p:guid; business number L/p:purchaseInfo/t:purchaseNoticeNumber.
Каждый L/p:cancelledLots/p:cancelledLot[i] сохраняет source guid, ordinalNumber,
jointLot, subject, отдельный locator и выбранные по descriptionType COMMON/
VARIOUS source reason/date fields. Порядок XML i — locator, не source ordinal.
No fake version/status; package GUID не event GUID. Exact paths, namespaces,
limits/shape и semantic completeness уточняются docs/52 до parser admission.

create/publication dateTime и cancellation xs:date — разные типы фактов.
Date-only не превращается в полночь timezone-aware datetime. Naive dateTime
остаётся UNKNOWN. PurchaseInfo publication относится к notice, не к event.
Не выводить effective cancellation instant из ingestion time. COMMON/VARIOUS
не должны молча подменять отсутствующие fields друг друга; XSD PASS не
гарантирует semantic completeness этих optional branches.

### Immutable store без ослабления whole-event contract

Рекомендуется отдельный bounded store lot events: windows, archive sources,
variants, exact schema checks и attempts. Immutable tenant/SHA ZIP blobs
переиспользуются. Whole-event model/SQL `purchaseRejection` остаются прежними;
семейство не добавляется в notice versions. Это сохраняет один законченный
срез без широкого переписывания работающего whole resolver.

Variants physical key `(company_id,event_guid,xml_sha256)` в family-specific
table; source eventGUID — business identity, не версия. Same GUID/different
bytes сохраняются атомарно и дают conflict UNKNOWN+hold. Same exact variant
replay идемпотентен. Safe parsed полный returned archive set либо unsafe/identity
failure всего окна; никакого тихого выбрасывания lot target/member.

Event-level exact schema checks привязаны к собственному GUID+XMLSHA,
schema/tree/package hashes и validator. Обе pinned full schemas нужны для
подтверждённого source evidence, но XSD PASS не разрешает спорный lot mapping.
FORCE RLS, tenant composite FK, immutable triggers, identity SQL checks и
guarded downgrade обязательны. Событие до notice допустимо без fake card.

### Shared per-lot resolver

Resolver получает exact notice snapshot и per-number lot-event evidence в
одном consistent read transaction. Lookup bounded one-hop:
purchaseNumber → direct eventGUID → all variants этих GUID. Conflicting number
association hold обеих сторон, no transitive traversal. Overflow UNKNOWN+hold,
не усечение с положительным вердиктом. Source cancelled-lot list также bounded;
превышение parser cap отклоняет полный window, не делает неполный COMPLETE.

Выход отдельно по каждому выбранному source lot:

- selected snapshot index, source ordinal/GUID/provenance;
- `relation: MATCH | DISJOINT | UNKNOWN`, отдельный scope reason;
- evidence_status, application_status FAIL/UNKNOWN, operation_hold и непустые
  reason_codes для любого hold;
- event refs/target locators; current procedure и full coverage UNKNOWN.

MATCH требует подтверждённого official identity mapping и непротиворечивого
уникального соответствия в exact notice. Один совпавший ordinal при отсутствующем/
неподтверждённом GUID не заменяет stable identity. Duplicate ordinal/GUID,
GUID/ordinal disagreement, source variants, неизвестный reorder/revision mapping
дают UNKNOWN. Array lot_index не участвует в match, кроме выбора исходного лота.

DISJOINT допустим только при достаточном том же identity contract/evidence;
отсутствующее поле или несовпавший guessed GUID не доказывают другой лот.
Для доказанно disjoint лота событие не создаёт operation hold; это не PASS
eligibility и не доказательство отсутствия другой отмены. При неоднозначности
hold только потенциально затронутого scope с UNKNOWN, не whole-purchase FAIL.
Если невозможно ограничить scope, показать notice-level unresolved scope и
UNKNOWN verification hold, сохраняя причину недостатка связи.

В S171 до подтверждения GUID/ordinal semantics запрещены и положительный
MATCH/confirmed cancellation, и DISJOINT с освобождением от hold. Любой связанный
lot event даёт выбранному лоту application UNKNOWN + verification hold; это
не утверждение отмены этого лота и не mandatory FAIL. No event остаётся UNKNOWN
без event hold. Наблюдаемые совпадения сохраняются как association evidence.

Даже обе full XSD PASS, совпавший purchase GUID, уникальные GUID/ordinal и
aware chronology noticePublication <= eventCreate <= eventPublication <= now
не доказывают revision relation: между indexed notice и event могла выйти
неполученная версия с другим составом/нумерацией. Эти проверки полезны для
диагностики, но не разрешают DISJOINT. Разрешение требует official stable-lot
identity semantics и доказанной связи с revision либо эквивалентного источника.
Live coincidence и synthetic exact mapping fixtures сами policy не включают.
Позднее notice P/cancelled=false/новый array order не снимают hold. Restoration
требует отдельного официального контракта, отсутствующий event не PASS.

### Consumers и критическое разделение gates

Whole-purchase rejection продолжает блокировать все лоты. Lot cancellation
применяется после него к выбранному лоту. Нельзя просто добавить lot reasons
в существующее общее `Comparison223Row.blocking_reasons`: source estimate
копирует это поле для любого выбранного лота и заблокировал бы unrelated lot.

Нужно отдельно хранить/возвращать:

1. purchase-wide blockers (stale/deadline/source availability/whole rejection);
2. selected-lot blockers;
3. document-collection hold для notice-wide manifest без доказанного lot mapping.

Source estimate проверяет1+2, а не автоматически3. В S171 выбранный лот при
любом связанном lot event всё равно получает отдельный UNKNOWN review hold;
это ограничение неполной association, а не вывод о его отмене. Comparison/search показывают
per-lot state; отмена одного лота не превращает всю карточку в FAIL. Если search
relevance не имеет однозначной lot identity, он показывает неопределённый scope
и требует явного выбора лота, не использует первый ordinal с совпавшим текстом.

Текущие document jobs notice-scoped. До отдельного manifest-to-lot contract
lot event может приостановить новые document fetch всего комплекта как scope
verification hold; это не whole cancellation и не экономический blocker
доказанно disjoint лота. Pending capacity/dispatch учитывают тот же document
hold, worker повторно проверяет его под tenant lock перед I/O/receipt. Cached
bytes доступны для review с предупреждением; их не удаляют.

Event ingestion сериализуется в порядке existing `eis223:company → company`,
без reverse lock path. Read-only API не парсит/source fetch/audit. Ranking не
снимает mandatory FAIL/UNKNOWN; неподтверждённая связь не даёт PARTICIPATE.

## Последствия и риски

Новый family делает отмены лотов видимыми, но без source-confirmed identity
может дать только честный verification hold. Главные риски: перепутать GUID
закупки и лота, применить ordinal новой версии к старой, поднять date до datetime,
или передать notice-wide document hold как экономический FAIL каждого лота.
Эти риски закрываются milestone acceptance до production admission.

## Альтернативы

- Whole-event reuse без отдельного scope: ложный FAIL всей закупке.
- Ordinal=array index: неверная identity при ordinal7 в позиции1/reorder.
- Считать XSD PASS proof lot linkage: схема не доказывает семантику GUID.
- Молчаливо игнорировать неоднозначность: ложное разрешение операций.

## Проверка и ввод

Независимое code review после исправления overflow projection и добавления
8MiB snapshot preflight: PASS. Root сообщил isolated PG84PASS, Linux454PASS,
local438PASS/16skip, mypy10/Ruff и webbuild/ESLint PASS; migration/backups/health
проверены. Полные pinned XSD16.2/16.3 PASS доказаны synthetic fixture без source
calls/DB writes. Это проверяет parser/schema path, не реальную отмену лота.
API/UI на существующей карточке показывают typed no-event UNKNOWN; реального
event-to-lot UI proof нет. Source estimate не может переопределить review hold.

Proof hashes и границы: [S171 implementation](../eis/ingestion/53-eis-223-lot-cancellation-implementation.md).
