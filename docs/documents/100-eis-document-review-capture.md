# S218 — точный исходный текст выбранного DOCX для проверки

Статус: серверный срез завершён 2026-10-06. API/UI — следующий S219.

Старый v3 сохраняет максимум1000blocks/100kchars, а blocks_total сообщает только
retained count. Bridge выдаёт максимум18выдержек по350символов. Это не полный ТЗ.
Новый отдельный eis-native-review-v1 сохраняется append-only в таблице анализов.
Shared analyze_document/v3 и 223 receipt behavior не меняются.

Вход: exact44notice/version/XML SHA + content_uid + expecteddocumentSHA. Проверки:
tenant/sourceholds/currentnotice/uniqueattachment/latestRECEIVED/receiptSHA,
SQL размер до hydration и digest реальных bytes. DOCX only, blob<=4MiB,
expanded<=32MiB/nativeunits<=20000/nativecharacters<=1million; сохранение целого
префикса <=1000blocks/100kchars. Другие форматы явно unsupported.

Counts/status/reasons до retention сохраняются отдельно от retained
blocks/chars/truncation. Scope явно ограничен поддержанными параграфами и
таблицами тела DOCX. Полнота всего нативного текста всегда UNKNOWN: существующий
извлекатель не покрывает колонтитулы и другие части DOCX. Флаг complete retention
описывает только сохранение уже извлечённого текста, не покрытие источника.
Native rejection сохраняет UNKNOWN и неизвестные totals.
Текст читается ограниченными deterministic страницами <=25blocks/256KiB,
с exact source locators и продолжением внутри длинного блока без пропуска текста.
Парный cursor block_index/character_offset позволяет прочитать весь retained text.
Delivery leads —
raw blocks+соседний контекст, без утверждённого адреса/срока/позиционной связи.

Роль, позиционная связь, requirements/fullTSpec completeness/участие UNKNOWN.
Prepare создаёт один immutable анализ и audit; replay использует cache без
повторного bytea read или writes. Read проверяет source gates в read-only RR.
Источник HTTP и document jobs не создаются. Серверный wrapper ограничен
worker2CPU/2GiB/60s; обычные бюджеты загрузки не увеличиваются.

Зависимость: additive check migration20261006_01 допускает новыйrevision и
оставляет v1/v2/v3. Downgrade с существующим review evidence блокируется,
никаких удалений или переписывания источников.

## Проверенный выпуск

487 isolated PostgreSQL tests PASS/65.51s/zero skips; pure DOCX9/Ruff/mypy и
Astra review PASS. PG log SHA256:
`11381db0e466573cc147b4c18806cd46002b6e2826d2423cf16c7c042d117829`.
Deploy06:28:19UTC: atomic13/host133/API28/worker28; head20261006_01.
Миграция additive, старые receipts не изменены. Migration log SHA256:
`cc728d3461ab07647223c9c9286a2284c2451a26ad657491dc3d4c008a59141d`.
API pin `sha256:7576fa59332b7e85d375758f654405c20b0b68db2f3cfe45205ed69fa8ee7ceb`;
worker `sha256:55944d1de345a1c6b1cb57233cf1b5d4c60676c43ac8105d365a6a54362c0ade`.
Web остаётся S216, source budgets/cron без изменений.

Реальный сохранённый DOCX06:29:10UTC: карточка0108500000426005169v1,
UID01A0F0E5BBD4711FB75501B4FA454C64,
SHAaf5e813af2d1286523d9806e43583cdd2e32311c3524002255a0828f4ae8f224.
Файл «Приложение 2 Проект контракта (Бумага).docx»,46657bytes; название не
утверждает роль. Извлечены/сохранены202blocks/35967characters; retention не
усечена. Native/fullTSpec UNKNOWN, EXTERNAL_LINKS_IGNORED. Prepare238ms,
replay76ms,9pages65–77ms; весь retained text восстановлен символ в символ на уровне
Unicode строк без потерь. Один новый immutable анализ/один audit; replay0writes,
sourceHTTP0/jobs0. Notice row и прежний v3 analysis имеют прежние digests.
Семь negative gates PASS. Private proof (source text остаётся на VPS):
`/var/lib/eis-browser/research/rejected/s218-review-live-proof.json`, SHA256
`6d03be928cbc8ac006724393eed503b70448003e7f774ee2ba4f1a10d1d3ef38`.

Шесть API/direct characteristic identities и negative gates PASS; NextAction/SSR
шесть reads87–184ms/пять negatives. Три аналоговые выдачи1219–1556ms:
19admitted/1omitted/157positions (корпус обновился со времени S216).
SSR proof SHA256 `9a95e71eb007c47c1ce506dc9df935a45932ff345fa9fd3550a19d1e05bc8250`;
characteristic proof SHA256
`7c613bf30dc51ee82815ae755d465b454ff6cca8f53045d2c5f14bfa37926396`.
Ops06:29:16UTC: DB5515295767bytes/free251975380992/head06/testDB0/health200,
markersfalse; proof SHA256
`326cae445f9dbb9ad04928802d5b035bf18732255adf1d24ad1ea3498a826cd2`.
Browser visual NOT_PERFORMED; ёмкость и полный охват ЕИС UNKNOWN.

Rollback snapshot:
`/home/syurai/vibe-seller-state/backups/s218-before-20261006T062811Z-code.tar.gz`,
SHA256 `ae8999aedf307fe0dfd1c5152af31611e56ad28cdf6aa5dfe402082f5eb00b8a`.
Rollback кода/образов сохраняет forward-compatible constraint и новые evidence.
PDF/XLSX/DOC/ZIP идут отдельными срезами; ZIP требует parent/member manifest.
