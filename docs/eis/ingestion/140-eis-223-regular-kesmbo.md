# V52: регулярная загрузка конкурсов для МСП

Дата: 2026-10-27. Owner root. Статус: PASS_BOUNDED_INSTALLED.
Проверяемый результат: полный аутентифицированный региональный архив
`purchaseNoticeKESMBO` проходит штатный intake, основной поиск и интерфейс;
регулярный selector включает его без изменения старой истории.
[ADR121](../../adr/0121-eis-223-regular-kesmbo.md),
[границы охвата120](120-eis-national-coverage.md),
[селектор V39](../../operations/127-eis-223-selector.md).

## Источник и границы

Evidence: `tmp/eis-kesmbo-regular-20261026-v52/`. Parent — принятый V51,
acceptance SHA `b775a1ed35193ebf2b0247af27c19d2802ab4929b0b52a5f6a47d953bb70476e`.
Владелец/файлы/acceptance перечислены в `slice.json`; обоснованное расширение
на WEB и четвёртый CHECK — `scope-extension.json`. Permission question не нужна:
план и audit используют USER_STANDING_AUTHORIZATION от26Oct.

Сохранённый UID `5036a61f-1db5-40ec-8f02-5b346316b062`, регион02, день08Oct,
initial BY_REGION; prepared UID совпадает, набор ZIP полный. Selection manifest
SHA `c9aef056d5ebba21475f4f06d4cd44660a8a884c74c2c96157ed9b312d62d15a`.
ZIP82191B SHA `5aa6cb39e0e50c5e6996fbb0ce22bba7749da61c7a6ab668348cf112f5f23749`;
один XML №32616448012v1 SHA
`0dbd4f3d8dabfe99ffde11a197a2fe6fb37fd39f77675b5e5f418f351efe2779`.
Текущий typed parser и regular bind/preflight прошли source0. Ранее сохранённые
XSD16.2/16.3 PASS не выдаются за новую XSD-проверку. Срок без timezone UNKNOWN;
это не подтверждённая действующая закупка. Координаты — доверенный retained
selection, не server echo и не вывод из ИНН/даты публикации.

## Реализация и проверка

Новый binding проверяет ключ/kind/UID/response SHA/full archive set; негативы
охватывают BY_NUMBER→regional, регион/день/семейство, изменённые response hashes.
Добавление к плану происходит под tenant lock отдельной волной5→6 семейств;
точное множество ключей и pinned catalog обязательны. Старые900 targets и
attempts сохраняются, expanded1080 детерминированно текущая при равном now.
Миграция26_03 расширяет четыре CHECK; planned KES или count>990 уже запрещают
старый consumer/downgrade. В WEB добавлены тип и название способа без допуска.

Полный свежий gate6:52/52PASS, receipt `aeeab1c9`, source `36249ad6`.
4452 unit collected, 27 прежних разрешённых skips;781PG/223WEB/9doctest,
ошибок0. Trusted verifier и удаление9 собственных тестовых ресурсов PASS.
Журналы неудачных подготовительных запусков сохранены в evidence; успешные
этапы из них не подмешаны в новый полный receipt. Цепочка source/addenda,
исправленный независимый XML checker и exact plan проверены отдельно.

## Установленный результат

27Oct00:15МСК установлен план `4f4ce5f5` по standing authorization владельца;
нового human reply нет. API/defaultworker/collector `e1ac47db`, WEB `005281eb`,
schema `20261026_03`. Barrier записан до запуска совместимого API и до новых
planned keys. Три composefile, budgets/cron/host scripts и DB identity сверены;
собственные migration/source0 producers удалены. Audit: PREPARED →
COMPATIBILITY_BARRIER → ACTIVATED → BACKFILL_VERIFIED → READ_VERIFIED.

Текущая замороженная пара26–27Oct: новая волна
`9418fef1-7b76-460e-874d-218d78abaeb8`,1080coordinates. Старые900 targets/ordinals
волны `a5f9ad89-1dbc-4be1-9959-e5ef8447852c` побайтно совпадают по ordered digest
`a71aeb6d`. Смена суток сверена до seal; вчерашняя волна не подменяла baseline.

Retained архив08Oct импортирован полностью без новых запросов к ЕИС:
+1версия №32616448012,1лот/312позиций; native XML proof961raw/937missingfacts,
312 взаимно однозначных позиций с привязкой шести полей. Срок без timezone,
количества/единицы и сумма остаются UNKNOWN. `forSmallOrMiddle=false` сохраняется;
название семейства не выдаёт допуск. Прямая EIS URL отсутствует; подтверждена
ссылка площадки `https://corp.roseltorg.ru/#notice/834127`.

Exact final wheel в изолированном PG: whole typed snapshot, replay/RLS и два
mainHTTP запроса PASS. Рабочий mainHTTP по номеру/«РГАУ МФЦ» —200, whole snapshot
SHA `82372766`. Actual CUA: общий поиск всех законов →1результат; раскрыты все312
позиции, ordered display text SHA `3f36c453` совпал с native snapshot.
`actual-ui-after.json`, `actual-ui-overview.jpg` фиксируют результат.

Штатный `223-refresh` к00:32МСК обработал49новых KES координат:
19SYNCED/30NO_DATA/0FAILED. В этих окнах сохранены104версии, это не104независимых
закупки. Audit связан по basis.attempt_id; object_id указывает window key.
`installed-observation-20261026T213205Z.json`: вся текущая1080волна586attempted,
494unattempted, scope PARTIAL; отдельный cached08Oct не считается текущим окном.
Первый readback `213032` имел неверный audit join, исправлен в `213205`;
пустой результат первой диагностической выборки не означает отсутствие audit.

## Границы приёмки и следующий шаг

Установленный независимый final review PASS: `installed-independent-review.json`,
SHA `512d93e6`. Acceptance зафиксирован в `acceptance.json`. Source0-case, обычные
49attempts и вся1080волна имеют разные границы. Остальные131новая KES координата,
исторические пятисемейные волны и национальные диапазоны не объявляются закрытыми.
Полнота всей ЕИС, recall и устойчивое ускорение UNKNOWN; NO_DATA подтверждает
ответ конкретного окна и не доказывает отсутствие закупок в реестре.
Следом — сверка пяти новых штатных поступлений из независимых архивов с основным поиском.
Cron/budgets/expired sweep и consumed адресные payload сохраняют прежние границы.
