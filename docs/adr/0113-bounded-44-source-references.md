# ADR-0113 — большие окна44 и повторные ссылки на вложения

Статус: ACCEPTED / установлен и проверен на сервере.
Дата: 2026-10-22. Владелец: root. Effective date: 2026-10-22T20:38:09Z (23:38МСК).

## Контекст

Readonly census выявил26 последних отказов44 с причинами
ARCHIVE_WINDOW_EXPANSION_LIMIT и ATTACHMENT_REFERENCE_INVALID. Для всех26
сохранены полные bound getDocsIP/PRIZ initial/prepared ответы и ZIP, без intake.
Официальный источник — исходные ответы сервиса ЕИС getDocsIP и XML44 ЕИС;
точные window/response/archive SHA находятся в private capture-summary.json:
`tmp/eis-44-archive-recovery-20261022-v28/`. Старые FAILED с NULL response SHA
не получают задним числом digest нового capture.

Максимальный полный набор301762206B, XML60128638B. Повторные UID имеют один
официальный URL и размер; часть отличается именем или классификацией. Подписи,
даты и описания не интерпретируются как подтверждение подлинности документа.
Первичный XML сохраняет эти сведения через точный archive/member/XML provenance.

## Решение

Только44: XML64MiB, суммарное expanded window320MiB. Без изменений:
ZIP50MiB, compressed window64MiB, expanded ZIP200MiB,20архивов,1000members,
4096metadata occurrences, namespace/DTD/entity/member safety, atomic full-set.
Рабочий бюджет3GiB/3CPU не повышается. Заголовки всего набора проверяются до XML.

Повтор UID с одинаковыми URL и byte_count — один binary reference с typed aliases
каждого следующего occurrence: исходные filename, kind_code и locator. Primary
сохраняется в исходном порядке. Любое различие filename/kind_code даёт вычисляемый
reference_status UNKNOWN, без выбора достоверного победителя. Полностью одинаковые
имя и тип дают PASS только идентичности ссылки, не содержимому, ТЗ или допуску.
Отсутствие kind_code остаётся отсутствием, не подтверждением типа документа.

Неверный UID/URL/размер и конфликт размеров по UID остаются FAIL полного окна.
Прежний тест duplicate_attachment_uid_after_the_old_limit_remains_invalid сохраняется:
его повтор содержит противоречивый размер. ADR0067 в части запрета любого повтора
заменяется этим контрактом, остальные source/variant/tenant guards неизменны.
Диагностика отличает информационный alias от нарушения ссылки; canonical admission
самой диагностикой не разрешается.

UNKNOWN attachment блокируется до HTTP download, receipt bytes, cached analysis,
reanalysis и review с ATTACHMENT_REFERENCE_REQUIRES_REVIEW. Probe не пишет.
Карточка/API и document status возвращают aliases и reference_status. Неоднозначное
вложение остаётся видимым, extraction/requirements UNKNOWN; notice metadata может
быть сохранено атомарно с полным source set. Старый кеш не обходит эти guards.
Поэтому API и worker обновляются совместно; WEB и schema не меняются.

## Проверка и последствия

Synthetic regression: одинаковые aliases, различающиеся labels, JSON roundtrip,
неверные URL/UID/размеры, bounded XML/полное окно, download0/probe writes0,
receipt/cache/review rejection, tenant и replay. Изолированная проверка всех26
исходных наборов на сервере предшествует release gate и exact-payload approval.

Первый parser-only proof:26/26,4577notice occurrences,23aliases,10UNKNOWN;
с Chromium cgroup peak677588992B при3GiB, без source requests.
Это не production checkpoints и не доказательство национальной полноты.
Полный ingest/replay/checkpoints/audit и trusted gate фиксируются отдельно.
Variant holds/конфликт редакций не снимаются ради SYNCED. Старые FAILED immutable.

## Альтернативы

Удаление повторов теряет provenance. Выбор имени по эвристике создаёт ложный PASS.
Отклонение всего окна из-за двух названий одного binary reference оставляет
проверяемые метаданные остальных закупок недоступными. Неограниченное увеличение
ресурсов не принято; лимиты проверены на полном сохранённом наборе.

Полный isolated PostgreSQL:26/26 ingest/replay/checkpoints/audit PASS,4544new/33existing,
26старых synthetic FAILED сохранены, cross-tenant read0. С Chromium cgroup
peak736968704B (<3GiB).38PG document guards PASS, включая seeded legacy cache
без изменения immutable notice rows. Это предварительная isolated проверка до установки.

Consumer audit перед выпуском расширил guard на pure document-set assessor
и evidence bridge: supplied/cached analysis для UNKNOWN reference не становится
conditions/native tables, collection extraction UNKNOWN и явный review gap.
Новые regression сначала воспроизвели bypass; затем44targeted tests PASS.
Первый gate не принят из-за root scratch permissions; второй остановлен
для этого исправления. Требуется новый полный gate на новом source SHA.

Финальный source fd7f2fc/a4b99fd3, image ab3b9686, gate
release-20261022-193853-7795aed4f2f7:50/50PASS,3862unit/27SKIP,714PG,199Node.
Все26 complete sets в actual image ingest/replay/checkpoints/audit PASS;
worker сChromium peak824336384B/3GiB. Actual API4544typed snapshots,
current largest/8UNKNOWN notices/auth PASS, max907positions,
peak333967360B/1GiB. Production readonly:1439same/3105missing/0conflicts;
26старых FAILED unchanged. Single4544-key compare превысил5s; разбит на128-key
statements без повышения timeout, realDB PASS. Exact helper проверяется повторно
после этой локальной ops-правки. Product source при ops-правке не менялся.

Final exact helper999beac8 на actual image:2iterations,4544new затем0new,
26checkpoints, RLS/invalid SHA/missing approval guards PASS;
peak752312320B/3GiB. Затем human exactSHA approval планаb359e8d9;
установка22Oct23:38МСК, operation69221888-f847-4eca-896f-fcbc9b12075d.
API/worker ab3b9686, WEB/DB/schema/cron/host223 сохранены; health PASS.
Production readback26/26 latestSYNCED/checkpoints,52source audits,
3activation audits,62ZIP SHA/provenance и4544unique XML SHA PASS;
3105new/1439existing,26oldFAILED immutable.8закупок/10references UNKNOWN
с document processing guard. Полнота страны M5 UNKNOWN.
Exact plan/approval и evidence: `tmp/eis-44-archive-recovery-20261022-v28/`
`activation-plan.json`, `activation-audit.json`, `live-installed-proof.json`.

Штатный cron23:42МСК на новом image,3GiB/3CPU: exit0,60окон,7SYNCED,
53NO_DATA,96new,0failed;60journal/audit и7canonical checkpoints PASS.
LiveHTTP10requests/auth/largest907positions/8UNKNOWNaliases PASS.
Turn PARTIAL из-за оставшейся очереди; sustained/national freshness UNKNOWN.
Evidence в том же каталоге: ordinary-cron-proof.json, live-api-proof.json, acceptance.json.
