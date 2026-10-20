# Электронный открытый конкурс 44-ФЗ

Статус: S146 / P5a2 завершён 2026-10-02. Явно поддержан
`epNotificationEOK2020`, без автоматического включения других типов каталога.
Поиск использует версии/предмет/позиции/цену/срок/manifest и существующие события
отмены. Критерии конкурса, квалификация и доходность остаются UNKNOWN до
разбора и проверки. Релевантность текста не является оценкой вероятности победы.

## Основание admission

- [Официальный каталог getNsi](../ingestion/35-eis-document-catalog.md): запись 123,
  PRIZ, `isDistributedPublicly=true`, `isActual=true`, source XML SHA
  `f53fed4befb36e66db38b75c29e3912f767be162ee7654c78c21ce4274283f02`.
- [Официальный пакет XSD 16.3](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
  SHA `4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`.
  `IntegrationEPTypes.xsd/notificationEOK2020Type` наследует notification2020;
  свой procedureEOK2020, общие price/collecting/attachments/purchaseObjects,
  дополнительный `criteriaInfo`, contractMultiInfo и конкурсные требования.
- Разрешённый live `getDocsIP` для региона 50, даты 2026-10-01 +03:00:
  1 ZIP **509342 bytes**, **32 XML**, все 32 валидны по fcsExport.xsd.
  XML/пакеты схем сохранены на VPS; реальных XML в tests нет.

Source key: `getDocsIP/PRIZ/50/2026-10-01+03:00/epNotificationEOK2020`.
Он отличается от аукциона/котировки/событий. Queue, journal, parser, preflight и
DB constraint допускают этот exact тип; mixed-type archive отвергается.
Номер и версия извлекаются из прямого commonInfo/purchaseNumber и versionNumber,
вложенные номера/версии иных сущностей их не подменяют. Деньги Decimal,
naive deadline UNKNOWN, SHA/member/locators сохраняются. Старые снимки не меняются.

UI и API используют `/ok20/view/common-info.html`, метод подписан как
«Электронный открытый конкурс, 44-ФЗ». Search reason и UI предупреждают о
непроверенных критериях/квалификации. Нельзя применять к конкурсному результату
предположение о победе исключительно по минимальной цене.

## Proof

Tenant root: `/var/lib/eis-browser/research/eok/local-eis-supplier/`.

| Artifact | Filename / SHA |
|---|---|
| Initial SOAP | `bdbcb4cc-d33f-467e-a182-3cb770dfc6a6-initial.xml`; `a4d576031da8a7b36d345dcb9dcffe11428aeb2d72537aed1947d6e326dd25eb` |
| Prepared SOAP | `bdbcb4cc-d33f-467e-a182-3cb770dfc6a6-prepared.xml`; `f49c3a42b10e48f23d5aff749848d2546e15d0f0441dbc04dfbb386b8249c08e` |
| ZIP | `bdbcb4cc-d33f-467e-a182-3cb770dfc6a6-1.zip`; `cfbbd48442c14eca13897aa9c1d1dddb8416f897e173d4fda24e6887b2ca0f5f` |
| XSD/direct-fields proof | `bdbcb4cc-d33f-467e-a182-3cb770dfc6a6-xsd.json`; `673c98b3a118de7f8cd92280fd5264f1c9604aed103f609f74b88588d48cc0cb` |
| Ingestion/search proof | `s146-ingestion-search.json`; `ae3140573dfdf59612d76d1821d7e91692014f8450b408704bedf75606d6e887` |

Первый проверенный XML №0348200080326000020 **v4**, SHA
`49156eda904546af591990c88511aec53cf2eb0c32e5f1e75f489b95e53ff203`,
НМЦК 5420000.00 RUB, deadline 2026-10-12 10:00 +03:00.
После развёртывания bounded freshness worker уже получил эту семью, поэтому
ручная загрузка сохранённого окна дала **0 новых версий**, 32 прочитанных XML;
повтор `replayed=true`, проверка ingestion 0.146348 s. Это не 32 дополнительных
свежих карточки поверх фонового индекса.

Search «экспозиции» через API занял **0.460650 s**. Для того же номера latest
оказалась **v5**, SHA
`2ff32c566f9b072af9dd84ef27001428c90c3c6d93c14726e64c5d56203e077f`,
deadline **2026-10-13 10:00 +03:00**, 3 позиции и 7 attachment refs.
Версия v4 не объявляется текущей после появления v5. API/UI показали EOK,
application/economics UNKNOWN и предупреждение о критериях. Открытая
[официальная карточка](https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html?regNumber=0348200080326000020)
подтвердила метод, 5420000.00 RUB и 13.10.2026 10:00 МСК; HTML не используется
для перезаписи XML snapshot. На публичной странице критерии цена 60% /
квалификация 40% — ещё один аргумент для следующего отдельного evidence slice.

## Проверки и эксплуатация

82 unit tests: source archive, index preflight, corpus/freshness, lexical search,
legacy discovery. 34 isolated PostgreSQL tests с миграцией, EOK/quotation
version replay, source conflict, RLS, search URL и документной очередью;
тестовая БД удалена. Ruff 16 files, mypy 8 source files, local production web
build и focused eslint прошли. API/worker/web deployed; production migration
`20261002_03`, health ok. Миграция и rebuild выполнены под global source lock,
чтобы cron не запускал новый parser до расширения DB constraint.

Default freshness теперь содержит 5 типов (3 notice + 2 events): число
запросов на тот же регион/период растёт на **25%**. Лимиты 24 windows / 240 s,
rate pauses, глобальный lock, database/disk budget сохраняются. Это расширяет
адресуемый scope и не подтверждает соблюдение глобального freshness SLA.
Существующий исторический backfill scope автоматически не пересоздаётся;
полный EOK backfill, все регионы и 223-ФЗ остаются отдельными этапами.

Downgrade намеренно не проходит при сохранённых EOK rows: он не удаляет
источник ради старого check constraint. Для полного сравнения конкурса
следующий этап должен показать exact критерии/веса с locators и неизвестными;
самостоятельно присваивать supplier score/право участия он не должен.


## S147: исходная схема оценки в сравнении (02.10.2026)

Из сохранённого ZIP, связанного с exact номером/версией/XML SHA, reader получает
верхние criterionInfo. Code/kind/value/addInfo имеют XML provenance; краткое имя
кода имеет отдельный provenance официального XSD 16.3 (SHA пакета выше).
Вес Decimal сохраняется отдельно для обычного режима либо для двух исходных
веток снижения цены: менее 25%, 25% и более. Вложенные indicatorsInfo/criterionInfo
не суммируются с верхними весами и остаются PRESENT_UNREVIEWED.

CONSISTENT означает только непротиворечивые исходные верхние веса: известные
коды соответствующего kind, без дубликатов, числа 0..100 и сумма 100 в каждой
показанной ветке. Пропущенный блок, неизвестный код, некорректная сумма/число,
смешанные либо дублированные ветки дают UNKNOWN. Другой метод NOT_APPLICABLE,
а не пустое подтверждение price-only. Supplier score, qualification/review
остаются UNKNOWN. Чтение не скачивает файлы и не пишет cache/jobs/audit.
ZIP/XML bytes и checksum проверяются; несовпадение exact evidence отклоняется.

Live v5 №0348200080326000020: цена CP60.00%, квалификация QO40.00%,
XML SHA 2ff32c566f9b072af9dd84ef27001428c90c3c6d93c14726e64c5d56203e077f.
GET evidence и POST comparison с другой процедурой вместе 0.047240 s;
counts jobs/blobs/analyses/write_receipts/audit_events не изменились.
Proof: /var/lib/eis-browser/research/eok/local-eis-supplier/
s147-criteria-comparison-20261002T073403295144Z.json,
SHA 9ff931d141a6a1800f41b574e116844d0a3a8b2e5bf09e4077785a8c15371cba.
Это одиночное измерение сохранённых источников, не global SLA.
UI через реальный BFF показывает exact v5, 60/40 и locators/SHA;
второй метод NOT_APPLICABLE. 82 bounded local checks, 35 isolated PG, Ruff/mypy,
web build/eslint прошли. API/worker/web deployed; migration/cache не менялись.
