# S170: evidence whole-purchase cancellation 223-ФЗ

Статус: **DEPLOYED, 2026-10-03**, HEAD20261003_02. Есть один реальный
purchaseRejection; naive времена сохраняют UNKNOWN + operation hold.
Дата:2026-10-03. Owner этой документации: Astra; owned только docs/51 и ADR0053.
Root назначает sequential code owners в docs/15 и выполняет rollout. Зависимости:
S169, docs/50 и [ADR0053](../../adr/0053-eis-223-cancellation-evidence.md).

## M1 — explicit parser и resolver

Предлагаемый owner реализации — Sol, новые bounded source modules/tests;
точные owned files утверждает root. Начать только purchaseRejection. Exact
root/Data/GUID/number paths и synthetic official-XSD fixtures — docs/50.
Не добавлять event family в `Eis223DocumentType` notice parser. Отдельные
event times/raw/quality, ни notice version/status, ни inference timezone.

Acceptance:

- Exact direct-path identity, case-normalized GUID с raw, ASCII number;
  missing/duplicate/shadow/wrong namespace fail closed.
- Unsafe ZIP/XML/DTD/ENTITY, bounds, duplicate members и неполный archive set
  отклоняются; все returned members accounted, причина недоверенна.
- Aware/naive/missing/future даты сохраняются честно; publication не подменяется
  rejection/create/ingest time. Full-XSD separate typed evidence без fake version.
- No events UNKNOWN. Valid linked rejection блокирует операции; confirmed
  aware/schema-valid evidence application FAIL. Naive/quality/guid conflict
  остаются UNKNOWN + verification hold. Нет перехода в PASS/reinstated.
- Несколько разных GUID одного business number не отменяют друг друга;
  поздний notice P/cancelled=false не снимает hold.

## M2 — tenant event store и shared consumer gate

Owner — root либо один назначенный bounded implementer. Separate event
window/archive source/event identity, reuse immutable tenant blobs допускается.
RLS/composite FK/immutability/audit обязательны; не требуется notice заранее.
Idempotent replay no extra event/audit. Same GUID different XML — immutable
variants с PK(company,event_guid,xml_sha256), полный atomic returned set и
явный conflict UNKNOWN+hold; нет fake versions или current winner.
Guarded downgrade сохраняет event/window/quality history любого tenant.

Quality cache привязан к event GUID/XMLSHA; notice quality schema не используется
с искусственным version=1. Read APIs читают cached facts одним tenant snapshot.
Exact source relation применяется независимо от типа исходного notice и его
версии: event относится к business number, не только к последней строке.
При GUID variants с разными номерами hold применяется к обоим номерам через
bounded one-hop lookup: direct matching GUIDs → all variants этих GUIDs, без
транзитивного обхода соседних номеров. Materialization overflow UNKNOWN+hold;
неполный evidence subset не может дать отсутствие конфликта/допуск.

Минимальные consumers: search, comparison, document enqueue/dispatch и source
estimate. Recheck до network document fetch нужен для jobs, созданных до event.
Уже скачанное можно просматривать; новые документы/сценарии при hold не создаются.
UI разделяет «есть подтверждённое событие отмены» и UNKNOWN текущей стадии;
не интерпретирует schema FAIL как техническое несоответствие товара.

PG checks: event до notice, same replay/immutable conflict variants, cross-tenant same
GUID/number, FORCE RLS, immutable UPDATE/DELETE rejection, stale notice+new
event, existing queued job+new event, same snapshot/no writes GET,
same GUID different numbers hold both, bounded overflow, атомарный rollback
unsafe/incomplete window; автоматического восстановления по новой notice версии нет.

## M3 — один bounded source window

Root выбирает region50/day/purchaseRejection после code/schema deployment,
под общими lease/rate/resource budgets. Полный returned set сохраняется,
raw/typed/XSD результаты различаются. NO_DATA не заменяет live parser proof.
Сверить хотя бы один настоящий event GUID и cancelNoticeRegistrationNumber
по exact XML и доступному официальному evidence; naive поля показать буквально.

Проверить cached API gate/повтор/no mutation и worker hold без отправки supplier
сообщений/участия. Не расширять cron автоматически; сначала measured duration,
pending targets, source scope/last checked. Все heavy raw/schema работы на VPS,
локально только код и компактные отчёты.

## Границы готовности

Срез подтверждает whole-purchase evidence и безопасный hold, не весь223 lifecycle.
Lot family требует собственного mapping/cancellationDate semantic review;
GUID неоднозначен по annotation, ordinal не равен array index. Результаты
протоколов, отказ от договора и расторжение не являются purchaseRejection.
Source status I не cancellation event. Unknown reversal/current coverage не
устраняется fresh notice/statusP или рейтингом. Сохраняются UNKNOWN ТЗ/КП/
экономика и все условия PARTICIPATE/exact-payload approval.

## M2 независимый review: findings до исправления

Read-only Astra review 2026-10-03 источника/transport/quality/store/SQL/migration,
consumer gates и queue обнаружил три конкретных проблемы, переданных root:

1. **P1 confirmed hold без причины:** resolver для полностью подтверждённого
   события возвращал operation_hold=True с пустым reason_codes. `_blocked`
   документа добавлял только эти reasons; итоговый пустой список позволял
   download/estimate при cancellation. Требуется обязательный stable reason
   любого hold, invariant и regression confirmed event → no download/BLOCKED.
2. **P2 contradictory event chronology:** проверка nonfuture/nonmissing times
   не сравнивала rejection_at и publication_at. Rejection позже publication
   ошибочно получал evidence PASS; согласно ADR0053 это UNKNOWN+hold.
3. **P2 pending queue:** SQL pending не исключал event-held purchase numbers;
   ранее созданные jobs могли вызывать ложный priority dispatch и расходовать
   retries без HTTP. Тот же predicate использовал общий notice.deadline для
   generic вместо selected_deadline, теряя lotOriented UNKNOWN jobs при
   истёкшем общем deadline. Исправлять shared pending predicate, сохраняя
   повторную проверку worker перед I/O.

Проверенные safeguards: physical tenant/GUID/SHA variants, exact number linkage,
bounded one-hop reader/overflow hold, independent schema identity/pinned policy,
FORCE RLS/immutable triggers/composite FK и guarded downgrade присутствуют.
Порядок import locks `eis223:company → company` не имеет обнаруженного reverse
пути в прочитанных 223 consumers: notice importer берёт только первый lock,
documents/jobs — только второй. Final receipt сериализуется с event commit;
новый source hold не превращается в перезапись уже полученных bytes.

Эта историческая запись фиксирует дефекты review до исправления. Все три
исправлены; окончательная проверка и deployment evidence приведены ниже.

### Финальный M2 review после исправлений

Все три указанных finding исправлены и повторно проверены чтением кода:
resolver выдаёт обязательную причину любого hold и запрещает пустые reasons
invariant; document consumer добавляет собственный defensive confirmed/review
marker независимо от содержимого reasons. Contradictory chronology даёт
UNKNOWN с `REJECTION_EVENT_TIME_ORDER_UNRESOLVED`. Shared pending predicate
исключает tenant purchase numbers с events и применяет selected_deadline для
generic; исправление действует одновременно на dispatch и queue capacity.

По переданному root результату пройдены **75 isolated PG** tests, включая
confirmed dual-XSD evidence → collect отказ до downloader, estimate BLOCKED
без scenarios, ранее созданная очередь → BLOCKED/next None, variants с разными
номерами, overflow, immutable/RLS/replay/downgrade. Root сообщил full web build
и ESLint PASS; окончательный Linux rerun после адаптации трёх старых mocks:
**421 PASS**. Ruff/mypy девяти файлов также PASS. Эти результаты переданы root;
Astra не выполнял независимый повтор suite/source intake.

Финальный read-only high-risk review не выявил оставшихся blockers. M2 contract
соответствует ADR0053. Deploy и bounded live source gate завершены root.
Статус этого раздела: **review complete, live evidence recorded**.

## Итоговые deployment/source evidence

Runtime deployed, HEAD20261003_02; code/server/image hashes совпали, health PASS.
Проверки:75 isolated PG,421 Linux tests, full web build/ESLint/Ruff/mypy9.
Root выполнил следующие два bounded operator probes:

- **2026-10-02, region50:** NO_DATA. Это отдельное наблюдение, не отсутствие
  отмен во всей ЕИС и не live parser fixture.
- **2026-10-01, region50:** SYNCED, весь returned set:1archive/1event/1purchase,
  18 753 compressed bytes,22,469с. Номер закупки `32616425280`, event GUID
  `4eee1725-c622-4fbd-a8dc-ff897b60bd7f`. Обе полные XSD16.2/16.3 PASS,
  сохранены2checks. Публикация raw `2026-10-01T11:09:27`, решение raw
  `2026-10-01T10:25:35` без timezone: evidence UNKNOWN и operation hold.

Event пришёл до notice: номер пока отсутствует в notice index, фиктивная
карточка/версия не создавались. Replay и read не дали дополнительных writes.
Exact source fingerprints нового event:

| Объект | SHA-256 |
|---|---|
| XML | `cd6420ac49b67d09b1f77ff39da6652113eb2205c7d14e9199261e8d2124f4e9` |
| ZIP | `46bb8471484e87a665b09b3a34317b7d20646410e719fef1581eff8584ba657d` |
| Initial response | `825f9e0c1d5fe132944f0e468af3e97c21fc5b8ab229915c4bc0e437a74a47b8` |

Отдельная synthetic pinned-full-XSD проверка PASS не делает synthetic XML
реальным событием;0DBwrites/requests. Первый helper import pytest завершился
ошибкой до source call; root исправил fixture bytes и повторил проверку.

HTTP comparison/estimate/document status/search показали новый state/current
UNKNOWN без writes. Browser проверил no-event UNKNOWN на существующей карточке
металлоконструкций; screenshot retained локально у root. Настоящая отменённая
закупка пока не индексирована, поэтому UI proof реальной отмены **не заявляется**.

Retained proof files на VPS, fingerprints переданы root:

| Proof | SHA-256 |
|---|---|
| `s170-live-proof-20261003T110613Z.json` — Oct2 NO_DATA | `5557cc6a65e68ea84cddc8759cf608665a1c9afe054b9ea16fdd2d0d39901d46` |
| `s170-live-proof-20261003T111127Z.json` — Oct1 real event/replay/quality | `c5752513370254fcf68c49708fd54cf1f54ad67bfae0d02b654c6ca8d9192ccd` |
| `s170-synthetic-schema-proof-20261003T111125Z.json` — synthetic schema only | `c6695fd924d38cce29a397a1fe611aad77ead90a002ff3656f666e27b0548074` |
| `s170-api-proof-20261003T110820Z.json` — cached HTTP no writes | `25db5617776b15050efb8728e44fee902c2c51d1d19b8294a6eb874ab93e264f` |

Свежесть всей ЕИС, другие регионы, полнота событий, отмены лотов и восстановление
остаются UNKNOWN. Один source sample не устанавливает throughput SLA.


Root final gate дополнение: два scheduler routing tests (NO_DATA/SYNCED) добавлены
после основного421Linux gate;25 tests текущего refresh module PASS локально и
наLinux с production image и mounted script. Focused union423, PG75. Runtime
код после deployed gates не менялся. Первый дополнительный helper не монтировал
scripts, ошибку окружения исправили; повтор25PASS. Script mount не является
source admission. Операционный snapshot~262GiB free; marker снят, testDB удалена.
