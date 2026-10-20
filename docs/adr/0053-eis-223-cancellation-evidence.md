# ADR-0053 — отдельное evidence отмены закупки 223-ФЗ

Статус: принято, **DEPLOYED**, 2026-10-03; HEAD20261003_02.
Дата/effective date: 2026-10-03. Владелец решения: Astra; rollout: root.

## Контекст

S169 расширил metadata notices. Он не устанавливает отсутствие поздней отмены:
P/lot cancelled=false относится к конкретному XML, не ко всей истории.
[Исследование S170](../eis/ingestion/50-eis-223-cancellation-contract.md) подтверждает в
сохранённых официальных NSI/XSD16.2/16.3 отдельное public/actual RI223 семейство
`purchaseRejection`. Exact sources/hashes/paths зафиксированы в docs/50.
После implementation root получил один live purchaseRejection из окна
region50/2026-10-01: обе full-XSD PASS, naive publication/rejection дают
UNKNOWN + operation hold. Exact evidence — в итогах docs/51.
`purchaseLotCancellation` имеет отдельную
непроверенную связь с лотами и не входит в первый admission.

Существующий 44-ФЗ код расположен в `sources/eis_feed_archive.py`
(EisProcedureEvent/parser), `storage/eis_notice_index.py` (atomic ingestion),
`sources/eis_procedure_state.py` (resolution) и `storage/models.py`
(eis_procedure_events), а не в отдельных eis_procedure_events.py. Он даёт
пример tenant provenance/replay, но его номера, recovery stages и временной
порядок нельзя перенести на 223 без собственного контракта.

## Решение

### Первый family и business relation

Первый bounded slice принимает только exact `{purchase namespace}purchaseRejection`.
База D: `/p:purchaseRejection/p:body/p:item/p:purchaseRejectionData`.
Собственная identity — D/p:guid; связь с закупкой — единственное прямое
D/p:cancelNoticeRegistrationNumber из 11 ASCII цифр. Packet/item GUID не
подменяют event GUID, вложенный похожий номер не fallback.

В Data **нет version/status/reversal**. Не создавать version=1, status=P,
fake highest notice version или запись в notice versions. Source notice I
остаётся отдельной недоступностью записи, не доказанной отменой закупки.
Событие может поступить раньше notice: хранить exact number relation без
обязательного FK на уже существующую карточку и без создания фиктивной notice.

Typed event сохраняет отдельные raw/parsed/provenance для createDateTime,
publicationDateTime, rejectionDate, причины, GUID и номера. Для naive/missing
времени aware value=None/status UNKNOWN. Ingest clock не заменяет публикацию;
rejectionDate не подставляется вместо optional publication. Source URLs и
causeForRejection — недоверенные данные, не разрешение fetch/действия.

### Immutable tenant storage

Создать отдельные event windows/archive sources/events с FORCE RLS, tenant
composite FK и immutable triggers. Можно переиспользовать независимый
tenant/SHA blob store 223 для raw ZIP; notice window family enum не расширять
событием только ради reuse. У event есть `(company_id, family, event_guid)`
identity и exact XMLSHA/member/parser version; source window содержит точные
selection/initial response/prepared response/manifest SHA и полный returned set.

Canonical GUID нормализуется с сохранением исходного literal/provenance;
UUIDv4 не требуется. Physical key варианта:
`(company_id, event_guid, xml_sha256)` в отдельном explicit-family store.
Business identity остаётся GUID. Identical GUID+XMLSHA replay идемпотентен,
без новых event/audit. Тот же GUID с другими bytes — несколько immutable
source variants, не версии и не last-write-wins. Все безопасно разобранные
варианты сохраняются атомарно вместе с полным returned set; конфликт отражается
счётчиком/причиной, evidence UNKNOWN и operation hold. Никакой вариант не
объявляется актуальным по SHA, времени загрузки или порядку INSERT. Даже
различие лишь форматирования bytes не снимает conflict автоматически.
Так сохраняются оба доказательства без отдельного quarantine commit после
rollback. Перезапись/разрешение source revision — будущий контракт.

Если один GUID имеет варианты с разными номерами, relation конфликтует для
обоих номеров. Read resolver: найти GUID, напрямую называющие запрошенный номер,
затем получить все варианты **только этих GUID** в том же tenant snapshot.
Не переходить от второго номера к другим GUID: transitive closure запрещён.
GUID/variant materialization bounded; overflow даёт explicit evidence-limit
reason, UNKNOWN и hold, не silent truncation и не разрешение. Exact quality
связывается с GUID+SHA каждого варианта.

Весь returned archive set проходит bounded безопасный parser. Unknown member,
неоднозначная identity, неверный namespace или unsafe ZIP/XML не
превращаются в частичный SYNCED. NO_DATA остаётся observation, не доказательством
отсутствия отмен. Multiple safe source variants могут дать SYNCED полного
transport/metadata set при conflict UNKNOWN; SYNCED не означает resolved state.
Audit фиксирует ingestion/conflict outcome и provenance.

### Quality, uncertain time и gates

Full-XSD event evidence привязать к exact event GUID/XMLSHA/schema hashes,
не использовать notice schema key с выдуманной версией. Pinned complete schema
trees читаются offline; external schemaLocation не исполняется. Metadata
admission и XSD quality различаются, как в ADR0051/0052.

Первый resolver имеет раздельные поля:

- `cancellation_evidence_status: PASS | FAIL | UNKNOWN` — качество/достаточность
  самого evidence, не допуска поставщика;
- `application_status: FAIL | UNKNOWN`;
- `blocked_reasons`, exact event references, `current_procedure_status: UNKNOWN`
  и `coverage: UNKNOWN`.

Без связанных events application/current status UNKNOWN; отсутствие blocker
не даёт PASS. При безопасно установленной связи хотя бы одного rejection event
создать operation hold: документы/предварительная экономика требуют официальной
сверки cancellation evidence до продолжения. Для полного source-XSD PASS обеих
pinned releases, aware nonfuture publication и rejection times и однозначной
identity evidence подтверждает наблюдение отмены, application FAIL. Это
**подтверждённое событие отмены**, не обещание полной текущей стадии.

При schema FAIL/UNKNOWN, naive/missing/future времени, конфликте вариантов или
неразрешённом порядке evidence не даёт подтверждённой текущей отмены:
application UNKNOWN + явный verification hold. Source-quality FAIL не
переименовывается в mandatory supplier FAIL. Для consistency наблюдаемое
rejectionDate после publicationDateTime считать unresolved, не исправлять clock.

Один uncertain event не снимает уже известный hold. Новый notice P, большая
notice version, более позднее ingest time, cancelled=false или высокий рейтинг
не доказывают восстановления. В изученном contract нет reversal; автоматического
снятия cancellation hold этот slice не содержит. Необходим новый официальный
контракт/evidence resolution перед реализацией восстановления. Общая стадия и
полнота истории остаются UNKNOWN даже при подтверждённом cancellation event.

### Сквозное применение

Единый resolver применяется к exact business number во всех трёх notice
families 223, tenant-scoped. Search/comparison показывают cancellation evidence
и reasons; подтверждённая отмена не получает хороший admission rank. Unknown
event hold виден отдельно, без фиктивного процента соответствия.

Document enqueue и worker проверяют gate перед source fetch; уже поставленная
задача не обходит позднее поступившее событие. Estimate использует тот же gate
в consistent read snapshot и не строит сценарии при hold. Сохранённые bytes
не удаляются, их просмотр с предупреждением допустим. Actual supplier action
и PARTICIPATE по-прежнему требуют всех domain gates/exact-payload approval.
GET не запускает event intake, parsing или запись audit.

## Последствия

Поддержка whole-purchase event — один ограниченный срез. Lot cancellation,
protocol/contract cancellation и restoration не admitted. Сохраняется usefulness
metadata discovery при честных blockers; нельзя объявить все active закупки
без полного свежего event scope. Source budgets, общие locks, память и дисковый
reserve не расширяются автоматически.

## Альтернативы

- Положить событие в notice versions: выдумывает версию и меняет current projection.
- Применить 44 recovery stages: не подтверждено контрактом 223.
- Игнорировать naive event: может разрешить действие после официального отказа.
- Считать любой linked XML бесспорной текущей отменой: скрывает quality/time
  uncertainty и неподтверждённый порядок восстановления.

## Проверка

Milestones и acceptance — [S170 implementation](../eis/ingestion/51-eis-223-cancellation-implementation.md).
Deployment и один live event подтверждены evidence root, приведённым в docs/51.
Они не подтверждают полноту отмен223, все регионы, lot cancellation или recovery.
