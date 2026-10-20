# Очередь документов из карточек ЕИС

## S144: сравнение 2–3 выбранных карточек (02.10.2026)

POST /v1/tender-discovery/eis-comparison принимает только 2–3 разных exact refs,
tenant берётся из bearer; read-only доступен и AUDITOR, Cache-Control no-store.
Сохранённые XML/analyses читаются последовательно; единое checked_at задаёт время
проверки deadlines, это не атомарный snapshot всего корпуса. Получение файлов,
новые jobs, разбор и audit writes не запускаются. Два разных номера требуются;
сравнение версий одной закупки сюда не входит. Stale/expired/cancelled BLOCKED,
остальные NEEDS_ANALYSIS; profit_order_status/coverage UNKNOWN.

Экран «Сравнение выбранных закупок» позволяет выбрать до трёх карточек и видеть
НМЦК, deadline, lot items, document readiness, условия и S143 context рядом.
Источники цены/срока/лота — XML SHA/member/locator, условия — document SHA/locator.
Полнота/roles/requirements и экономика не становятся PASS. НМЦК разных лотов
не нормализована по составу и не является сравнимой прибылью.

Live A4/80: №0104100002226000036 v1 (1 500 000.00 ₽, 4/4 files, 38 shown conditions)
и №0107300009526000178 v2 (150 600.00 ₽, 0/8 files, conditions UNKNOWN).
HTTP 200/no-store, 0.036329s на сервере; jobs/blobs/analyses/receipts/audit
[8,43,119,72,156790] до/после неизменны. Порядок input, profit UNKNOWN.
Proof comparison-20261002T055735686648Z.json в том же VPS directory,
SHA e3b047016f8824b2b1557f2f63f43338ca8f8d3e007fe4007947ae7a072d16b8.
UI подтвердил оба столбца, источник НМЦК/deadline, 4/4 против 0/8 и UNKNOWN.

58 unit/API/economics tests, 33 isolated PG tests, Ruff/mypy 20 files,
web production build и focused eslint успешны. Synthetic PG fixture сначала
дала WINDOW_REPLAY_CONFLICT (два номера делили одно test hour); исправлен только
номер фикстуры, защита replay сохранена. Test DB удалена; API/worker/web развёрнуты.
Данные о себестоимости/полное КП пока отсутствуют; P4 profit ranking не завершён.

## S143: read-only контекст условий (02.10.2026)

Bridge показывает до 3 snippets каждого kind /18 на документ; conditions_total
и conditions_truncated делают ограничение видимым. Для короткого заголовка
DOC/DOCX с двоеточием добавляется только следующий сохранённый block при
единственном совпадении header, same SHA/extractor/member и locator gap 1–4.
Новый раздел или неподходящий locator не присоединяется. Каждый соседний block
имеет собственный SHA/locator; ADJACENT_UNREVIEWED не подтверждает смысловую связь
или полный список мест/условий. Контекст ограничен 500 chars с truncation flag.
Для source mismatch выдаётся ошибка, не evidence. Parser/cache version не меняется.

Live exact S142 card: header line 8 → body line 9 (первый адрес);
header line 26 → body line 27 (заявки, 3 рабочих дня, срок до 17.12.2026).
Места могут продолжаться в следующих абзацах: один context block не подтверждает
полный список. UI подтвердил отдельные locators, UNKNOWN role и truncation counts.
Proof context-20261002T054339416310Z.json в том же VPS volume, SHA
402e891164f595f764f72d812899dfdb6696cea476d90ad1614c54da6355cb00.
Два bridge reads заняли 0.437417s; cache payload SHA
5b1cd80353cb6efae27b1299741c46d521aeac1edb5522bc2ebc51a17f53b48b
и audit count 156776→156776 не изменились. Source I/O отсутствует.
53 unit/API/economics tests, 32 isolated PG tests, Ruff/mypy 19 files,
production web build успешны; API/worker/web развёрнуты, health ok, test DB удалена.

## S142: legacy DOC / кеш v3 (02.10.2026)

Миграция 20261002_02 и parser v3-doc развёрнуты. Формат/preflight/process limits
описаны в [ADR 0049](../adr/0049-legacy-doc-text.md). Native DOCX/XLS/XLSX/PDF
сохраняют прежний контракт; legacy DOC даёт lossy text и UNKNOWN layout.
Условия доступны в существующем интерфейсе «Показать сохранённые условия»;
ни role review, ни полнота, ни расчёт выгоды этим не утверждаются.

Live №0104100002226000036, exact XML
b40f72ef6ac9074c7bd22da6761edcebc0d90190e50c5e7fde5ac0634802335d:

- описание объекта .doc: 79 360 bytes, source SHA
  82bfae2ab0e689c899b29f819bc3d23eb0112321e9c236b65f035e5e11f0f607,
  40 blocks /12 snippets /0.054584s;
- инструкция .doc: 86 528 bytes, source SHA
  be7c95af5f93f639ece38646874fbe58a1a291dd451fdb871e33f8f9c4ed28dd,
  72 blocks /21 snippets /0.063538s.

Оба UNKNOWN/LAYOUT_NOT_VERIFIED. Пример locator
`antiword-0.37-16 utf8 w0 :: line 28` сохраняет буквальную фразу о минимальной
партии 2 000 пачек. Строки таблицы требуют review. При просмотре обнаружено:
header «Место поставки»/«Срок поставки» попадает в snippets, следующий block
с адресом/датами сейчас не присоединяется; следующий срез расширит context evidence.

Proofs в /var/lib/eis-browser/research/document-gates/local-eis-supplier/:
doc-v3-01A0D7D1DD1172CF82DAE0D7FA0B752B-20261002T052552931124Z.json
SHA 017eb335e331dcf6b4108d09c8b9ecb315af926f499d0acdabf1ebce86440936;
doc-v3-01A0D7D1FCC7756E9A0E12BC8C087B5A-20261002T052552985816Z.json
SHA 174f1ffaa7e2ef7f6d4ad45d92960e034f15191d8e4aa1885edea381ebdd0ddc.
v1/v2 canonical payload SHA 918725ddf3c5855aaf6ee0d108c0461c060386a980db2b2567b0a8d2f8f57afd
не изменился, receipts 6→6, replays false. Все 4 listed files обработаны v3;
analysis_pending_count=0. Браузер подтвердил 4/4, DOC snippets/locators и UNKNOWN.

Gate: 31 isolated PG index/queue tests, 12 Linux DOC tests включая network/fork/
secret/timeout/output/UTF-8; локально 81 профильный test (5 Linux skipped),
117 API/facts/offers, domain doctests 9; Ruff/mypy 23 files. Test DB удалена.
API health ok/web 200; dpkg antiword 0.37-16; runtime/source SHA двух изменённых
модулей совпали. Raw документы и полные proofs остаются на VPS.

## S141: XLS и повторный разбор кеша (02.10.2026)

Миграция 20261002_01 разрешает explicit v1/v2-xls analysis keys; прежние строки
сохраняются с RLS/immutability. Новый worker может вернуть REANALYZED,
attempted=0/analyzed=1: один полученный файл проверен по SHA/size и разобран
новой версией без обращения к источнику. Повтор использует analysis cache.
Это выполняется и для полученных files expired current карточки; скачивание
новых files по ней по-прежнему блокируется. Статус analysis_pending_count
отличает ожидание cached разбора от неполученных bytes.

Live выбранный комплект №0104100002226000036 получил все 4 listed files
(XLS 44 032 /DOCX 42 531 /DOC 79 360 /DOC 86 528 bytes). Listed receipt
не подтверждает полный комплект: старый DOC пока UNKNOWN. XLS из того же
SHA 8e8d0680990f317791e6fcd8fd094c6e4b2f3cbdef9ea8e722d7c62020d9ed07
дал 76 literal blocks/1 snippet за 0.098045s. Итог UNKNOWN:
FORMULAS_IGNORED/EMBEDDED_MEDIA_IGNORED. Пример locator лет235.65!M1.
Ни формульные cached values, ни прибыль автоматически не подтверждены.

Старая v1 payload SHA 4e9198638b07824b47440dd370433ee2e0f06d40cf1f23ebe6a862e75bef89b6
осталась прежней; receipt rows before/after 6/6 (включая прежние попытки).
Первый вызов создал analysis, повтор вернул false. Raw proof на VPS:
research/document-gates/local-eis-supplier/xls-v2-20261001T222906636040Z.json,
SHA a73b1cd80b84bb4266d5b9cd3b10232aa89abec8d725355b6fcdbf8715207620.
Локально только малый xls-v2-summary.json в ignored research directory.

Проверки: 30 PG index/document tests +3 PG bundle tests, 88 профильных
extractor/bundle/API/workflow tests до дополнительного malformed-XLS negative;
последующий XLS/offer gate 31 passed, API bundle 4 passed, domain doctests 9.
Ruff и strict mypy 24 source files успешны; test DB удалена. API/worker/web
развёрнуты, production web build успешен. Общий P4 остаётся незавершённым:
legacy DOC, review ролей/полноты/требований, действительные КП и реальная
экономика ещё требуются.

## S140: проверка источника непосредственно перед загрузкой (02.10.2026)

Worker повторно проверяет известную exact XML версию, aware deadline и
официальные cancellation/recovery events. Новая версия, истёкший срок или
однозначная отмена останавливают новое скачивание; UNKNOWN stage допускает
чтение и остаётся UNKNOWN для участия. Проверка относится к времени чтения
индекса, не подтверждает свежесть всей ЕИС. Уже полученные bytes не удаляются.

Worker пишет `EIS_DOCUMENT_READ_BLOCKED` с exact ref, source XML/member,
deadline locator и event evidence. Повтор одной причины на тех же источниках
не дублирует запись; новый источник создаёт новое решение. Read-only GET
возвращает `read_gate` (checked_at/reasons/evidence), не пишет audit и не ходит
в ЕИС. UI объясняет остановку и прекращает автоматическое ожидание загрузки;
ручное чтение статуса и сохранённых файлов доступно. Другой tenant не видит job.

Истёкшее задание воспроизвело download до фикса. После исправления 28 isolated
PG gates и 26 профильных API/bridge/procedure tests прошли; Ruff/strict mypy и
production web build успешны. API/worker/web развёрнуты. Live shortlist
«бумага А4 80», top1 №0104100002226000036, версия 1, XML SHA
`b40f72ef6ac9074c7bd22da6761edcebc0d90190e50c5e7fde5ac0634802335d`:
четыре listed files, первый XLS получен (44 032 bytes, SHA
`8e8d0680990f317791e6fcd8fd094c6e4b2f3cbdef9ea8e722d7c62020d9ed07`),
native extraction UNKNOWN/UNSUPPORTED_FORMAT. Очередь продолжает остальные
файлы под прежними limits/60s public cooldown. Это доказательство чтения и
явной неполноты, не полного анализа. Следующий P4 срез — legacy DOC/XLS и
versioned повторный разбор cached bytes без повторного скачивания.

Proof snapshots на VPS: `research/document-gates/local-eis-supplier/`;
малые summary/helper локально `data/research/eis-documents-2026-10-02/`.

Дата: 2026-09-28. Ограниченный S124-срез.
Архитектура: [ADR 0047](../adr/0047-eis-version-bound-document-queue.md).

## Пользовательский путь

В «Поиске по сохранённым XML ЕИС» найдите карточку и нажмите **«Скачать и
разобрать документы»**. Сервер сохраняет exact-version задание; вкладка может
быть закрыта. Кнопка **«Проверить сохранённый разбор»** читает очередь/результат
без загрузки файлов. Открытая карточка обновляет статус раз в 15 секунд.

Для каждого файла видны: ожидание/получен/несовпадение размера/ошибка,
статус извлечения, причины, SHA и количество фрагментов условий/кандидатов
требований. **«Показать сохранённые условия»** читает native analysis с
локаторами источника. API также хранит/возвращает извлечённые блоки, а не
только snippets интерфейса. Кандидаты требований пока не утверждены.

Для пакетного запуска используйте **«Подготовить документы первых 3
кандидатов»**. Сервер сравнивает весь индекс по запросу, исключает FAIL и
карточки без приложений до лимита и планирует до трёх exact-version заданий.
Это предварительный порядок релевантности, без подтверждённой доходности.
Конфликт новой версии/лимит комплекта показывается отдельным пропуском.
API позволяет 1..5 кандидатов; каждый подбор записан в tenant audit.

«Получены все перечисленные файлы» означает только совпадение со списком XML.
Список может быть неполным; роль файла, полнота и review остаются UNKNOWN.
Скан, неподдержанный формат, повреждённый или ограниченный разбор не даёт PASS
для допуска. Пустой список — UNKNOWN_MANIFEST. Новая известная версия делает
старый разбор STALE; требуется повторный поиск и новое задание.

## Повторное использование

Jobs, байты, analysis и попытки сохраняются в PostgreSQL с tenant/RLS/audit.
Повтор создания не добавляет дубли. SHA + имя + версия analyzer позволяют
повторно использовать native analysis; на новой версии сначала заново
получаются байты. Старый UID/URL сам по себе не подтверждает их неизменность.
Доходность, hard gates и PARTICIPATE этим API не рассчитываются.

## Работа сервера

`server-eis-documents.sh` запускается каждую минуту и делает максимум один
файл, сохраняя существующие 60 секунд host delay. API/worker имеют общий
volume `eis_browser_state`, поэтому перезапуск контейнера не обнуляет паузу.
Глобальный import lock удерживается во время запуска. Proxy health проверяется
до создания worker; при недоступности — BLOCKED/PROXY_UNAVAILABLE и ноль
сетевых попыток. Задание остаётся в очереди до восстановления маршрута.

Лимиты: 32 файла/100 МиБ на комплект, 20 МиБ на файл, worker 2 ГБ/2 CPU,
guard БД 100 ГиБ/свободный резерв 40 ГиБ. Ошибки повторяются после cooldown,
неуспешные байты подходящего размера сохраняются как SIZE_MISMATCH evidence.
Запрос за пределами лимита отклоняется явно; он не считается проверенным.

API (bearer обязателен, company берётся из principal):

- POST `/v1/tender-discovery/eis-document-jobs`: оператор, точный номер,
  версия и SHA XML; ответ — сохранённый статус, сеть не выполняется.
- GET `/v1/tender-discovery/eis-document-jobs/{number}`: exact version/SHA
  в query; отдельные download/extraction/review статусы и список файлов.
- GET `/v1/tender-discovery/eis-document-jobs/{number}/{uid}/analysis`:
  сохранённый полный native analysis; неполученный/чужой файл — 404.
- POST `/v1/tender-discovery/eis-document-selection`: операторский подбор
  по query/max_candidates; без сети, с видимыми conflicts и PRELIMINARY.

## Проверенные границы и продолжение

16 PostgreSQL tests и 72 профильных unit/API/extractor test прошли; Ruff,
strict mypy новых модулей и production web build прошли. Миграция
`20260928_04` развернута. На реальной карточке №0148300000626001036 план
повторён без дублей: перечислено пять файлов, получено ноль, QUEUED и UNKNOWN
полноты/review. UI прочитал сохранённый статус. Общий cooldown API→worker
проверен без сетевого запроса; production worker остановился до сети с
PROXY_UNAVAILABLE. Живую загрузку нескольких процедур этот срез не доказывает.

Пакетный POST по «бумага» выбрал три задания из 46 предварительных кандидатов
с приложениями, без отклонённых планов; повтор не создал дубликатов. Проверка
на 107 синтетических карточках доказала применение фильтров до лимита:
105 карточек без приложений не скрыли подходящую карточку, просроченная
исключена. Browser UI проверил пакетную кнопку и отображение очереди.
Резервная копия с первым document job восстановлена в отдельную БД:
2918 версий, 144540 targets и одно задание; проверочная БД удалена.

Следующие этапы: подтвердить роли и полноту реальных комплектов,
интегрировать role/completeness review и
version-bound извлечение/сопоставление требований, затем полные КП, расходы,
три сценария и конкурентную историю. Скорость повторного сравнения строится
на подготовленных результатах; новая документация имеет отдельный статус
обработки.

## Живые документы после восстановления 29.09

Маршрут до ЕИС работает. Для №0148300000626001036 получены все пять
перечисленных файлов; для №0173200001426001823 — девять из девяти. Ещё два
задания в очереди. На момент проверки: 14 уникальных blobs, 14 кешированных
native analyses, суммарно 1 653 285 байт; SHA и заявленные размеры сверены
с фактическими bytes. Повторное GET вернуло тот же разбор без сети. Browser UI
показал 63 сохранённых фрагмента с provenance у одного DOCX. В первой карточке
два файла получили native PASS, три сохранили UNKNOWN с причинами
`UNSUPPORTED_MEMBERS`, `EXTERNAL_LINKS_IGNORED`,
`MEMBER_EXTRACTION_UNKNOWN`. Неутверждённых кандидатов требований: 0;
автоматический hard gate отсюда делать нельзя. Статусы review и полноты
официального комплекта остаются UNKNOWN, несмотря на `COMPLETE_LISTED_SET`.
Отдельная резервная копия восстановлена в проверочную БД: 3124 XML-версии,
четыре задания, 14 blobs, ноль ошибок SHA/размера и SHA analysis.

## Связка карточки, файлов и предварительной экономики

Кнопка **«Связать с карточкой и расчётом»** читает exact-version XML и
сохранённый разбор файлов одним tenant-scoped API-ответом. GET
`/v1/tender-discovery/eis-document-jobs/{number}/evidence` принимает версию
и SHA в query; внешнюю сеть не вызывает. НМЦК и позиции лота связаны с XML
SHA/локаторами, файл — с UID, SHA, XML-локатором, а ограниченные выдержки
условий — с исходным native provenance. Подсказка о роли берётся только из
имени файла; `role_status`, `requirement_status` и `completeness_status`
остаются `UNKNOWN`. Срок и официальные события отмены дают `FAIL` при
доказанном запрете. Старая версия получает `STALE`.

После ввода оператором стоимости всего товара, всех прочих расходов без НДС,
явной ставки НДС и источника оценки кнопка считает `base`, `realistic` и
`conservative` через существующий `DiscoveryCostInput`. Скидки по умолчанию
0/5/10%, рост затрат в conservative 10%; они видны в UI и ответе. POST
`/v1/tender-discovery/eis-document-jobs/{number}/estimate` проверяет exact
version/SHA и не сохраняет введённые суммы. Без подтверждения полноты
известных расходов расчёт остаётся `UNKNOWN`; при просрочке или
подтверждённой отмене — `BLOCKED` без сценариев. Даже `ESTIMATE` не является
полным КП, результатом hard gates или `PARTICIPATE`. Строгий `Decimal`
исключает `float` на денежном входе. Проверка полного комплекта, версии
правил, действительного КП и итоговых расходов — отдельные следующие этапы.

Живая проверка 29.09 после развёртывания: GET для
№0148300000626001036 вернул 5/5 полученных файлов и 21 привязанный к
сохранённому analysis фрагмент. Browser smoke открыл связку, ввёл
синтетические затраты и получил три предварительных сценария; итоговые
статусы application/economic/requirements/completeness без проверенного
комплекта и КП остались `UNKNOWN`. В PostgreSQL прошли 17 профильных
integration tests, включая точность bytes/SHA, версии и tenant isolation.
На сервере в момент проверки были 6 document jobs, 28 blobs и analyses:
четыре комплекта `COMPLETE_LISTED_SET`, один `INCOMPLETE`, один `QUEUED`.
`COMPLETE_LISTED_SET` означает только получение перечисленных файлов.


S147: read-only bridge/comparison дополняется competition_criteria по exact
сохранённому EOK XML. Верхние веса и source locators видны рядом с документами;
вложенные шкалы и квалификация поставщика UNKNOWN. Для других методов
NOT_APPLICABLE. Контракт, live evidence и ограничения: docs/eis/search/36-eis-open-competition.md.
