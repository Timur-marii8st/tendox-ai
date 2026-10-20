# S178: реестр вариантов извещения 44-ФЗ, milestone 1

Статус: milestone 1 завершён и deployed 04.10.2026 08:54 UTC.
Контракт — [ADR0061](../../adr/0061-eis-44-notice-variant-ledger.md).

## Что добавляется

Реестр хранит полный уже проверенный source set в трёх таблицах: receipt всей
выгрузки, каждый отдельный вариант XML и все member origins. Raw ZIP остаются
в карантине VPS; XML bodies не дублируются в PostgreSQL. Source facts варианта
содержат номер/версию/тип/XML SHA, идентификатор ЕИС и времена публикации/начала
подачи заявок с исходным текстом. Название, цена, позиции и вложения остаются
в исходном XML; их проекция в каноническую карточку относится к следующему
milestone после внедрения shared ambiguity hold.

Receipt связан с двумя существующими неизменяемыми audit records: сохранения
полного набора S175 и его диагностики S177. Упорядоченные SHA всех ZIP, manifest,
report, tenant и window должны совпасть. Повтор проверяет весь payload и каждый
origin; ошибка в последнем варианте или audit откатывает полный ledger batch.
Повторы одинакового XML сохраняют все origins, добавляя один distinct variant.
Разные XML одной версии накапливаются, без выбора более позднего файла.

## Границы результата

`inventory_status=COMPLETE` означает полное сохранение exact evidence batch.
`canonical_admission=NOT_ENABLED`, `coverage=UNKNOWN`, `resolution=UNKNOWN`
сохраняются даже при единственном варианте. Не меняются канонический индекс,
source checkpoints, sync attempts, поиск, документационные задачи и экономика.
Исходный44 gap остаётся FAILED. Реестр пока вызывается оператором для проверенного
retained набора; автоматический intake hook не включается на этом milestone.

Reader возвращает полный bounded набор либо явный overflow/ошибку. Сокращённая
история не выдаётся за полную. Межоконные origins сохраняются для каждого XML.
Перед подключением к продуктовым consumers нужен отдельный shared hold,
включая повторную проверку уже созданных jobs и receipts.

## Хранение и checks

Receipt UUID включает tenant/manifest/diagnosis. Variant key включает tenant,
номер/версию/тип/XML SHA; origin имеет composite tenant FKs к receipt/variant.
RLS FORCE и immutable triggers включены на всех трёх таблицах. Допустимы только
SELECT/INSERT для app role; отдельный ledger audit фиксируется в той же
транзакции, его FK deferred до commit. История не удаляется при downgrade.

Пределы: 20 ZIP, 2000 occurrences/variants/origins на full read/batch;
state read: максимум 20 receipts и 16 MiB совокупного evidence/audit JSON,
с проверкой размеров в PostgreSQL до загрузки полных payloads;
member filename≤255 без slash/backslash, `.xml`; facts≤4096bytes,
evidence≤128KiB. Source parser/retention caps S175/S177 прежние. Штатный schema
downgrade проверяет наличие любого ledger row всех tenants с row_security=off
до DDL; при недоступной полной видимости отказывается. Migration20261004_02
содержит frozen DDL, чтобы будущие модели не меняли историческую схему.

## Проверки

PASS: 54 Linux tests (17 ledger + 37 classifier), 36 isolated PostgreSQL tests
(14 ledger + 22 прежних index/retention/diagnosis), scoped Ruff и mypy,
независимый architecture review. Проверены late rollback, exact replay,
межоконные variants/origins, UTC/+03:00 hash roundtrip, empty migration roundtrip,
global downgrade refusal, NULL-safe DB checks, RLS/app permissions и immutable
trigger даже для DB owner. Overflow по counts/bytes возвращает пустой UNKNOWN.

Изолированная БД `procurement_eis_test_20261004_s178` удалена после gates.
Изолированный retained proof: 8.160s, peak375984128bytes (~359MiB)/2GiB с
resident Chromium. Доказательство на VPS:
`/var/lib/eis-browser/research/rejected/s178-isolated-proof.json`, SHA256
`7c33f48aadbdc15ee61488db4c4679073967a8780d58962b64441f9a80323b94`.

## Deployment и реальный набор

Code backup и validated schema-only dump (не data backup) сохранены на VPS:
`/home/syurai/vibe-seller-state/backups/s178-before-20261004T085351Z-code.tar.gz`
SHA256 `09e953450c8020f5d7859be17fdd1bf746787f7857be8bf86efebedb729e53d1`;
`/home/syurai/vibe-seller-state/backups/s178-before-20261004T085351Z-schema.sql`
SHA256 `f518c63f30abf8826b75138800e835864bafeb288fb88617d851e644a265fcc3`.
Host11/runtime3 hashes совпали, API/worker rebuilt, schema HEAD20261004_02.
Priority/import lease удерживался на migration и retained proof; cron/budgets
прежние, собственный demand marker снят.

Полный retained source set PRIZ/77/29.09: 5 ZIP, 499 XML, 498 semantic keys;
499 distinct variants, 499 origins, один receipt и один immutable ledger audit.
Manifest SHA `62532f02f3021f6078de78bc7cd86cc7a323fac4af9426c6f77fffba872c8a2e`;
diagnosis SHA `5ca4af5206ba669f257891dba79d19dfa0c64ad5253a8c94f6c70b685c494805`.
Receipt UUID `200fd4ea-ac55-5c8d-8731-600503287541`, SHA
`75a1baa4489b6e0f59c113a3448b83cb4a8ea5fbc9cc375a1937bb608678dd91`
совпадает с isolated proof. Пара0373100047426001450/version1/id44105096
прочитана как 2 variants/2 origins/ambiguity=true/UNKNOWN/NOT_ENABLED.

Production proof: 8.309s, peak381870080bytes (~364MiB)/2GiB с Chromium.
Source requests0; canonical index/checkpoint/attempt delta0. Replay variants/
origins/audit/file writes0. Исторические8FAILED preserved; gap не объявлен SYNCED.
`/var/lib/eis-browser/research/rejected/s178-retained-proof.json`, SHA256
`f25858f5d8c7a0bd5d195c3c5138965c43a632151a597a206351cc5d294a48ce`.
Это время offline ledger verification, не SLA поиска по всей ЕИС.

Final API 08:54:47UTC: health200/anonymous401/no-store, оба demand markers false.
Индекс223:2882current purchase numbers, бумага239.45ms/59matches,
серверное оборудование608.83ms/184matches. Изменение223counts относится к
обычному cron; ledger не пишет этот индекс. Coverage/freshness всейЕИС UNKNOWN.
API proof `/var/lib/eis-browser/research/regions/s178-final-api-20261004T085448Z.json`,
SHA256 `df0ddaccd15e4a7f6637f59c4c0d4ff75c4a9726cf11b997e85755be140a0f78`.

## Следующий milestone

Shared ambiguity hold для current-read/search/comparison/document queue/receipt/
estimate, включая уже созданные jobs. После проверки всех consumers — отдельный
ADR и перевод full-window intake на сохранение variants с канонической проекцией
только при допустимой source identity. M1 не подтверждает полный охват ЕИС.
