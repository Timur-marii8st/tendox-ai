# S176 — полное окно из четырёх архивов 223-ФЗ

## Причина отказа

Окно `getDocsIP/RI223/77/2026-10-02+03:00/purchaseNotice` оставалось FAILED
с причиной `ARCHIVE_SET_MISMATCH`. Диагностика 04.10.2026 установила:
исходный ответ перечисляет четыре уникальных UID; подготовленный ответ
содержит тот же полный набор и связан с исходным request ID. Проверки
официальных URL и UID проходят. Ошибку вызывал пилотный лимит двух архивов,
который проверялся вместе с реальным расхождением состава.

Входящие SOAP сохранены на VPS под `local-eis-supplier`, без исходящих запросов
или токена. Один запуск: 2 POST, 0 archive GET, 0 изменений production базы.
Каталог: `/var/lib/eis-browser/research/223/local-eis-supplier/s176-20261004T063737Z`.
SHA256 `capture.json`:
`75210e4ee522f86bb3c43ff1f6e3d880a4462fb1c4a2cf7387927b9057763077`.

## Полный набор и ограничения

Четыре ZIP: 24 527 171 сжатых bytes, 82 432 099 распакованных bytes,
365 XML members, без повторов номера закупки и версии. XML проходят
существующий reader `purchaseNotice`. Набор получен по тем же исходным
UID/URL, без смешивания разных запросов. Первый проход с прежним общим
лимитом 64 MiB закончился `WINDOW_EXPANSION_LIMIT`; сохранились только два
проверенных ZIP, успешного полного receipt или импорта не было. Второй
проход использовал эти два ZIP и скачал два остальных. Всего 6 archive GET.

SHA256 `download-full.json`:
`15f2d670369b5181cd96d96c3646d607259d5de6ae08ba5b171f2aa64a745bf9`.
Inventory связывает member name, XML SHA, номер/версию и SHA ZIP.
Raw ZIP остаются на VPS.

Новый контракт notice window: до 4 ZIP, до 32 MiB сжатых данных, до 128 MiB
после распаковки и до 400 members суммарно. Per-ZIP ограничения прежние:
16 MiB сжатых, 32 MiB распакованных, 200 members и 4 MiB на XML. Общий
expanded budget увеличен явно с 64 до 128 MiB на основании фактического
полного набора; перед admission требуется измерить весь pipeline под
прежним cgroup 2 GiB. Worker windows/timeouts/cron/lease не расширяются.

Полные source sets и UID проверяются до GET. Пять согласованных архивов
дают `ARCHIVE_COUNT_LIMIT`; неполный или чужой набор остаётся
`ARCHIVE_SET_MISMATCH`. После каждого GET проверяется cumulative compressed
budget до следующего скачивания. Все ZIP headers и общие expanded/member
bounds проверяются до любого XML parse. Ошибки `WINDOW_EXPANDED_LIMIT`,
`WINDOW_MEMBER_LIMIT`, `ARCHIVE_RESOURCE_LIMIT`, `ARCHIVE_INVALID` видны
отдельно от generic `SYNC_FAILED`. Частичный импорт запрещён.

## Хранилище и готовность

Модель, binder и notice-only DB CHECK согласованно допускают 1..4 ZIP.
Migration `20261004_01` меняет только `ck_eis_223_counts`. Downgrade до 2
запрещён при любой истории >2 архивов во всех компаниях; RLS не должен скрыть
историю от проверки. При отсутствии нужной видимости downgrade отказывается.
Исходная история не удаляется и не переименовывается. Event/lot-event окна
сохраняют лимит 2 ZIP.

Реализация требует isolated PG, полного memory gate и rollout; результаты
выполненных проверок и deployment приведены ниже. Whole-EIS coverage, свежесть
всех карточек и экономическая рекомендация остаются UNKNOWN. Решение: ADR0059;
текущие результаты этапа фиксируются в docs15.

## Проверки перед rollout

138 Linux unit tests и 21 PostgreSQL integration test PASS на отдельной БД
`procurement_eis_test_20261004_s176`. Проверены atomic rollback при конфликте
четвёртого ZIP, replay без повторных записей, tenant isolation, DB reject пятого
архива и безопасный downgrade: без wider history проходит, с историей >2 любой
компании отказывается до изменения constraint. Никаких production deletions.
После добавления regression точных resource codes финальный Linux gate повторяется.

Полный реальный retained набор прошёл cached fetch, preflight, isolated ingest,
checkpoint и replay, с Chromium в том же worker cgroup 2 GiB. Container memory
peak 343 482 368 bytes (~328 MiB), Python max RSS 193 003 520 bytes. Время:
fetch1.863s, ingest3.021s, replay1.662s, весь запуск7.220s. Source requests0;
365 версий сохранены в тестовой базе, replay новых версий не создаёт.
Измерение не включает задержку свежего скачивания ЕИС и не устанавливает SLA.

Proof `/var/lib/eis-browser/research/223/s176-memory-proof.json`, SHA256:
`5c646de291d44c5c3ccb5aec734a2dd2a540c42537ff7f19eebcfaaea7445096`.

## Развёрнуто 04.10.2026

Финальные139Linux unit tests и21isolatedPG tests PASS, Ruff/mypy и architecture
review PASS. Code backup и валидированный schema-only dump сохранены; миграция
`20261004_01` применена. Host15/API5 hashes совпадают, APIhealth200, anonymous401,
coverage no-store, markers сняты. Тестовая БД удалена.

Сохранённый полный набор прошёл admission на production под общим lease, без
повторных обращений к ЕИС:365XMLversions добавлены, window сохранено целиком,
один новый SYNCED attempt с initial response SHA подтверждён. Replay не добавил
версий или source rows. Production precompare не нашёл конфликтов; прежние
8FAILED остаются в immutable history. Старый regional gap223 закрыт;
`old_gaps=0`, текущий региональный scope COMPLETE. Whole-EIS coverage UNKNOWN.

Manifest SHA256:
`30eaf9aa480eba3b4513ec5ce7bb31b6309dc9d793665f4dd8257915b3f3eec6`.
Proof `/var/lib/eis-browser/research/223/s176-admit-proof.json`, SHA256:
`93440ab3f719c7ab6ae87654885721c34a6dc9fca6d555badd4921f19feba2c2`.

После импорта индекс223 содержит2876уникальныхcurrent purchase numbers и2979
XMLversions. Cached search бумага251.35ms/59matches, серверноеоборудование
607.15ms/184matches. Это время по накопленному индексу; source freshness,
соответствие требованиям и прибыль отдельной закупки не подтверждаются этим
измерением. API proof:
`/var/lib/eis-browser/research/regions/s176-final-api-20261004T065948Z.json`, SHA:
`7d05cfc26681ec8c763b4cdb50ab5e67bca9651463c5a39c9d9ff3a493762a2c`.
